"""AI OS Core dirige los envíos al Broker: sin su ALLOW no sale ninguna tarea.

Broker y Core se simulan por transporte (formas de Core 0.2.1); el runtime, el
repositorio y el despachador son los reales. El recorrido contra el Core y el Broker
reales está en ``scripts/verify_ai_os_core.py``.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import httpx

from knowledge_orchestrator.config import BrokerSettings
from knowledge_orchestrator.integrations.ai_os_core import KoCoreGate, flow_id_for
from knowledge_orchestrator.integrations.broker_client import BrokerClient
from knowledge_orchestrator.services.broker_dispatch import BrokerDispatcher, BrokerPoller
from tests import test_phase_three_workflows as phase_three


class FakeCore:
    def __init__(self, authorization: str = "ALLOW", *, down: bool = False, monitor_down: bool = False) -> None:
        self.authorization = authorization
        self.down = down
        self.monitor_down = monitor_down
        self.calls: list[tuple[str, dict]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down or (self.monitor_down and request.url.path == "/api/v1/flows/hops"):
            raise httpx.ConnectError("Core apagado")
        assert request.headers["X-Principal-Id"] == "knowledge_orchestrator"
        assert request.headers["Authorization"] == "Bearer tok-ko"
        body = json.loads(request.content)
        self.calls.append((request.url.path, body))
        if request.url.path == "/api/v1/policies/evaluate":
            return httpx.Response(200, json={"authorization": self.authorization,
                                             "executable": self.authorization == "ALLOW", "unknown_inputs": []})
        return httpx.Response(201, json={})

    def receipts(self) -> list[dict]:
        return [body for path, body in self.calls if path.endswith("/receipts")]

    def hops(self) -> list[dict]:
        return [body for path, body in self.calls if path == "/api/v1/flows/hops"]


class FakeBroker:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v1/tasks":
            payload = json.loads(request.content)
            self.created.append(payload)
            return httpx.Response(202, json={
                "task_id": "broker_1", "status": "queued", "execution_strategy": "single",
                "execution_preset": "fast", "selection_mode": "auto",
                "status_url": "/api/v1/tasks/broker_1", "cancel_url": "/api/v1/tasks/broker_1",
            })
        if request.method == "GET" and request.url.path == "/api/v1/tasks/broker_1":
            return httpx.Response(200, json={
                "task_id": "broker_1", "status": "completed", "request_id": self.created[0]["request_id"],
                "created_at": "2026-10-18T10:00:00Z", "updated_at": "2026-10-18T10:01:00Z",
                "execution_strategy": "single", "execution_preset": "fast", "selection_mode": "auto",
                "progress": {"phase": "completed", "invocations_completed": 1, "invocations_total": 1},
                "result": {"result_markdown": "# Nota", "usage": {"invocations": 1, "cost_usd": 0.0},
                           "models_used": [{"model": "gemma4:12b"}]},
                "error": None,
            })
        return httpx.Response(404, json={"detail": "no"})


class AiOsCoreTests(unittest.IsolatedAsyncioTestCase):
    make_runtime = phase_three.PhaseThreeWorkflowTests.make_runtime

    def clients(self, core: FakeCore) -> tuple[BrokerClient, FakeBroker]:
        broker = FakeBroker()
        client = BrokerClient(BrokerSettings(base_url="http://broker.test", admin_token="t"),
                              transport=httpx.MockTransport(broker.handler))
        client.core = KoCoreGate("http://core.test", "tok-ko", transport=httpx.MockTransport(core.handler))
        return client, broker

    async def dispatch(self, core: FakeCore, capture: str):
        client, broker = self.clients(core)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        runtime = self.make_runtime(Path(temporary.name), capture_id=capture, transcript="Texto breve.")
        workflow_id = runtime.workflow_planner.plan_capture(capture)
        task = runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
        accepted = await BrokerDispatcher(runtime.workflow_repository, client).dispatch_once({task.task_id})
        self.addAsyncCleanup(client.close)
        return runtime, client, broker, task, accepted

    async def test_denied_task_never_reaches_the_broker_and_says_why(self) -> None:
        for decision in ("DENY", "REQUIRE_APPROVAL", "INDETERMINATE"):
            core = FakeCore(decision)
            runtime, _, broker, task, accepted = await self.dispatch(core, f"core_{decision.lower()}")
            self.assertEqual(accepted, 0)
            self.assertEqual(broker.created, [])
            saved = runtime.workflow_repository.get_task(task.task_id)
            self.assertEqual(saved.error_code, "CORE_DENIED")
            self.assertIn("AI OS Core", saved.error_message)
            (evaluation,) = [body for _, body in core.calls]
            self.assertEqual(evaluation["scope"], "knowledge_orchestrator:broker")
            self.assertEqual(evaluation["context"]["operation_type"], "study_notes")
            self.assertIn(evaluation["context"]["data_classification"], {"internal", "confidential", "local_only"})

    async def test_core_down_sends_nothing_and_retries_later(self) -> None:
        runtime, _, broker, task, accepted = await self.dispatch(FakeCore(down=True), "core_down")
        self.assertEqual(accepted, 0)
        self.assertEqual(broker.created, [])
        saved = runtime.workflow_repository.get_task(task.task_id)
        self.assertEqual(saved.status.value, "READY")
        self.assertIsNotNone(saved.next_retry_at)
        self.assertIn("AI OS Core", saved.error_message)

    async def test_allowed_task_runs_and_leaves_receipts(self) -> None:
        core = FakeCore()
        runtime, client, broker, task, accepted = await self.dispatch(core, "core_allow")
        self.assertEqual(accepted, 1)
        self.assertEqual(len(broker.created), 1)
        await BrokerPoller(runtime.workflow_repository, client, runtime.workflow_planner).poll_once()
        receipts = core.receipts()
        self.assertEqual([r["status"] for r in receipts], ["accepted", "succeeded"])
        self.assertEqual({r["operation_id"] for r in receipts}, {broker.created[0]["idempotency_key"]})
        self.assertEqual(runtime.workflow_repository.get_task(task.task_id).status.value, "SUCCESS")

    async def test_the_task_trip_is_seen_in_the_core_monitor(self) -> None:
        """KO 0.4.4: autorización, recibos y saltos comparten el flujo de la tarea."""
        core = FakeCore()
        runtime, client, broker, _, _ = await self.dispatch(core, "core_monitor")
        await BrokerPoller(runtime.workflow_repository, client, runtime.workflow_planner).poll_once()
        flow = flow_id_for(broker.created[0]["idempotency_key"])
        evaluation = next(body for path, body in core.calls if path.endswith("/evaluate"))
        self.assertEqual(evaluation["context"]["flow_id"], flow)
        self.assertEqual({r["evidence"]["flow_id"] for r in core.receipts()}, {flow})
        hops = core.hops()
        self.assertEqual([h["kind"] for h in hops], ["request", "response"])
        self.assertEqual({(h["flow_id"], h["source_system"], h["target_system"]) for h in hops},
                         {(flow, "knowledge_orchestrator", "ai_broker")})
        self.assertGreaterEqual(hops[1]["details"]["latency_ms"], 0)

    async def test_a_monitor_that_is_down_never_stops_the_task(self) -> None:
        core = FakeCore(monitor_down=True)
        runtime, client, _, task, accepted = await self.dispatch(core, "core_monitor_down")
        await BrokerPoller(runtime.workflow_repository, client, runtime.workflow_planner).poll_once()
        self.assertEqual(accepted, 1)
        self.assertEqual(runtime.workflow_repository.get_task(task.task_id).status.value, "SUCCESS")

    def test_flow_id_is_always_acceptable_to_core(self) -> None:
        self.assertEqual(flow_id_for("ko:tarea 1/ñ"), "ko:tarea_1__")
        self.assertEqual(len(flow_id_for("x" * 500)), 128)

    def test_core_only_with_url(self) -> None:
        self.assertIsNone(BrokerClient(BrokerSettings(base_url="http://b:1", core_url=None)).core)
        self.assertIsNotNone(BrokerClient(BrokerSettings(base_url="http://b:1", core_url="http://c:2")).core)


if __name__ == "__main__":
    unittest.main()


class SinPegarTokensTests(unittest.IsolatedAsyncioTestCase):
    """Core deja su conexión a KO y le da el token del Broker, que se renueva tras un 403."""

    async def test_core_da_el_token_del_broker_y_lo_renueva(self) -> None:
        import os
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from unittest import mock

        vigente = ["broker-1"]

        class Core(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                ok = self.headers.get("Authorization") == "Bearer tok-ko"
                self.send_response(200 if ok else 401)
                self.end_headers()
                self.wfile.write(json.dumps({"token": vigente[0]} if ok else {}).encode())

            def log_message(self, *_: object) -> None:
                pass

        servidor = HTTPServer(("127.0.0.1", 0), Core)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        self.addCleanup(servidor.shutdown)
        carpeta = tempfile.mkdtemp()
        url = f"http://127.0.0.1:{servidor.server_port}"
        Path(carpeta, "knowledge_orchestrator.json").write_text(json.dumps({"core_url": url, "token": "tok-ko"}))

        vistos: list[str | None] = []

        def broker(request: httpx.Request) -> httpx.Response:
            vistos.append(request.headers.get("X-Admin-Token"))
            ok = request.headers.get("X-Admin-Token") == vigente[0]
            return httpx.Response(200 if ok else 403, json={} if ok else {"detail": "ADMIN_AUTH_REQUIRED"})

        entorno = {"AI_OS_CONNECT_DIR": carpeta}
        with mock.patch.dict(os.environ, entorno):
            os.environ.pop("KO_CORE_URL", None)
            os.environ.pop("KO_CORE_TOKEN", None)
            settings = BrokerSettings(base_url="http://broker.test", admin_token="pegado-caducado")
        self.assertEqual((settings.core_url, settings.core_token), (url, "tok-ko"))
        client = BrokerClient(settings, transport=httpx.MockTransport(broker))
        self.addAsyncCleanup(client.close)
        self.assertEqual((await client._request("GET", "/api/v1/capabilities")).status_code, 200)
        vigente[0] = "broker-2"  # el Broker se reinicia; el runner publica el nuevo en Core
        self.assertEqual((await client._request("GET", "/api/v1/capabilities")).status_code, 200)
        self.assertEqual(vistos, ["broker-1", "broker-1", "broker-2"])
