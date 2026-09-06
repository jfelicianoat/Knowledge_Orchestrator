from __future__ import annotations

import json
import unittest

import httpx

from knowledge_orchestrator.config import BrokerSettings
from knowledge_orchestrator.domain.broker_contracts import (
    BrokerContractError,
    auxiliary_invocations_for,
    final_artifact,
    is_contractual_invocation,
)
from knowledge_orchestrator.integrations.broker_client import BrokerClient, TransientBrokerError
from tests.test_broker_contracts import accepted_response, valid_request


class BrokerClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_202_and_polls_long_running_task(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(202, json=accepted_response())
            return httpx.Response(200, json={
                "task_id": "broker_task_1", "status": "generating", "request_id": "task_1",
                "created_at": "2026-06-23T10:00:00Z", "updated_at": "2026-06-23T10:00:10Z",
                "execution_strategy": "single", "execution_preset": "fast", "selection_mode": "auto",
                "progress": {"phase": "generating"}, "result": None, "error": None,
            })

        client = BrokerClient(BrokerSettings(base_url="http://broker.test"), transport=httpx.MockTransport(handler))
        try:
            accepted = await client.create_task(valid_request())
            status = await client.get_task("broker_task_1", status_url=accepted["status_url"])
            self.assertEqual(status["status"], "generating")
        finally:
            await client.close()

    async def test_classifies_503_as_transient(self) -> None:
        client = BrokerClient(
            BrokerSettings(base_url="http://broker.test"),
            transport=httpx.MockTransport(lambda _request: httpx.Response(503, json={"message": "busy"})),
        )
        try:
            with self.assertRaises(TransientBrokerError):
                await client.create_task(valid_request())
        finally:
            await client.close()

    async def test_rejects_invalid_response_immediately(self) -> None:
        client = BrokerClient(
            BrokerSettings(base_url="http://broker.test"),
            transport=httpx.MockTransport(lambda _request: httpx.Response(202, json={
                "task_id": "wrong", "status": "queued", "status_url": "/x", "cancel_url": "/x",
            })),
        )
        try:
            with self.assertRaises(BrokerContractError):
                await client.create_task(valid_request())
        finally:
            await client.close()

    async def test_sends_admin_token_header_when_configured(self) -> None:
        seen_headers: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.append(request.headers.get("x-admin-token"))
            return httpx.Response(202, json=accepted_response())

        client = BrokerClient(
            BrokerSettings(base_url="http://broker.test", admin_token="secret-token"),
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.create_task(valid_request())
        finally:
            await client.close()
        self.assertEqual(seen_headers, ["secret-token"])

    async def test_omits_admin_token_header_when_not_configured(self) -> None:
        seen_headers: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen_headers.append(request.headers.get("x-admin-token"))
            return httpx.Response(202, json=accepted_response())

        client = BrokerClient(
            BrokerSettings(base_url="http://broker.test"),
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.create_task(valid_request())
        finally:
            await client.close()
        self.assertEqual(seen_headers, [None])

    async def test_reconfigure_replaces_endpoint_and_token_without_restart(self) -> None:
        seen: list[tuple[str, str | None]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            endpoint = str(request.url.copy_with(path="", query=None)).rstrip("/")
            seen.append((endpoint, request.headers.get("x-admin-token")))
            return httpx.Response(200, json={"authenticated": True, "auth_required": True})

        client = BrokerClient(
            BrokerSettings(base_url="http://old-broker.test", admin_token="old-token"),
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.auth_check()
            await client.reconfigure(
                BrokerSettings(base_url="http://new-broker.test:8765", admin_token="new-token")
            )
            await client.auth_check()
        finally:
            await client.close()

        self.assertEqual(
            seen,
            [
                ("http://old-broker.test", "old-token"),
                ("http://new-broker.test:8765", "new-token"),
            ],
        )

    async def test_reads_v28_capabilities(self) -> None:
        client = BrokerClient(
            BrokerSettings(base_url="http://broker.test"),
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={
                "contract_version": "2.8",
                "strategies": ["single", "auto"],
                "work_lanes": ["inference"],
                "agent_skills_egress": ["web_search"],
                "task_dependencies": True,
            })),
        )
        try:
            capabilities = await client.capabilities()
        finally:
            await client.close()
        self.assertEqual(capabilities["contract_version"], "2.8")
        self.assertIn("auto", capabilities["strategies"])
        self.assertEqual(capabilities["work_lanes"], ["inference"])
        self.assertEqual(capabilities["agent_skills_egress"], ["web_search"])
        self.assertTrue(capabilities["task_dependencies"])

    async def test_validates_admin_token_against_auth_check(self) -> None:
        seen: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.headers.get("x-admin-token"))
            return httpx.Response(200, json={"authenticated": True, "auth_required": True})

        client = BrokerClient(
            BrokerSettings(base_url="http://broker.test", admin_token="secret-token"),
            transport=httpx.MockTransport(handler),
        )
        try:
            result = await client.auth_check()
        finally:
            await client.close()
        self.assertTrue(result["authenticated"])
        self.assertEqual(seen, ["secret-token"])

    async def test_rejects_malformed_auth_check_response(self) -> None:
        client = BrokerClient(
            BrokerSettings(base_url="http://broker.test"),
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"authenticated": "yes"})),
        )
        try:
            with self.assertRaisesRegex(Exception, "validación de credencial inválida"):
                await client.auth_check()
        finally:
            await client.close()

    async def test_capabilities_version_mismatch_is_reported_without_blocking_client(self) -> None:
        client = BrokerClient(
            BrokerSettings(base_url="http://broker.test"),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"contract_version": "2.9", "future_field": True})
            ),
        )
        try:
            capabilities = await client.capabilities()
        finally:
            await client.close()
        self.assertEqual(capabilities["contract_version"], "2.9")
        self.assertTrue(capabilities["future_field"])

    async def test_treats_rotated_admin_token_as_recoverable(self) -> None:
        client = BrokerClient(
            BrokerSettings(base_url="http://broker.test", admin_token="expired"),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    403,
                    json={"detail": {"code": "ADMIN_AUTH_REQUIRED", "message": "token caducado"}},
                )
            ),
        )
        try:
            with self.assertRaises(TransientBrokerError) as caught:
                await client.get_task("broker_task_1")
        finally:
            await client.close()
        self.assertIn("token caducado", str(caught.exception))
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(caught.exception.code, "ADMIN_AUTH_REQUIRED")

    async def test_cancels_through_advertised_url_with_delete(self) -> None:
        seen: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path))
            return httpx.Response(200, json={
                "task_id": "broker_task_1", "kind": "inference", "status": "cancelled",
                "created_at": "2026-07-28T10:00:00Z", "updated_at": "2026-07-28T10:01:00Z",
                "execution_strategy": "single", "execution_preset": "fast", "selection_mode": "auto",
                "progress": {"phase": "cancelled"}, "result": None, "error": None,
            })

        client = BrokerClient(
            BrokerSettings(base_url="http://broker.test"),
            transport=httpx.MockTransport(handler),
        )
        try:
            result = await client.cancel_task(
                "broker_task_1",
                cancel_url="/api/v1/tasks/broker_task_1",
            )
        finally:
            await client.close()
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(seen, [("DELETE", "/api/v1/tasks/broker_task_1")])


class BrokerContract210Tests(unittest.IsolatedAsyncioTestCase):
    """Contrato 2.10: ejecucion demostrable (Client_API.md, 8.1/8.3/8.4)."""

    CAPABILITIES_210 = {
        "contract_version": "2.10",
        "strategies": ["single"],
        "auxiliary_invocations": True,
        "auxiliary_invocations_optout": True,
        "invocation_contract": True,
        "prompt_compression_echo": True,
        "task_artifacts": True,
        "canonical_artifacts": True,
    }

    def _client(self, handler) -> BrokerClient:
        return BrokerClient(
            BrokerSettings(base_url="http://broker.test"),
            transport=httpx.MockTransport(handler),
        )

    async def test_content_exclusivity_reaches_a_broker_that_offers_the_optout(self) -> None:
        sent: list[dict] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/capabilities":
                return httpx.Response(200, json=self.CAPABILITIES_210)
            sent.append(json.loads(request.content))
            return httpx.Response(202, json=accepted_response())

        client = self._client(handler)
        try:
            await client.capabilities()
            request = dict(valid_request())
            request["auxiliary_invocations"] = False
            await client.create_task(request)
        finally:
            await client.close()

        self.assertIs(sent[0]["auxiliary_invocations"], False)

    async def test_content_exclusivity_is_dropped_rather_than_killing_the_task(self) -> None:
        """El Broker valida con extra=forbid: un campo que no conoce hace
        fallar la peticion entera con 422. Perder la garantia adicional es
        malo; perder la tarea por haberla pedido es peor."""
        sent: list[dict] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/capabilities":
                return httpx.Response(200, json={"contract_version": "2.9", "strategies": ["single"]})
            sent.append(json.loads(request.content))
            return httpx.Response(202, json=accepted_response())

        client = self._client(handler)
        try:
            await client.capabilities()
            request = dict(valid_request())
            request["auxiliary_invocations"] = False
            await client.create_task(request)
        finally:
            await client.close()

        self.assertNotIn("auxiliary_invocations", sent[0])

    async def test_reconfiguring_forgets_what_the_previous_broker_promised(self) -> None:
        sent: list[dict] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/capabilities":
                return httpx.Response(200, json=self.CAPABILITIES_210)
            sent.append(json.loads(request.content))
            return httpx.Response(202, json=accepted_response())

        client = self._client(handler)
        try:
            await client.capabilities()
            await client.reconfigure(BrokerSettings(base_url="http://other-broker.test"))
            request = dict(valid_request())
            request["auxiliary_invocations"] = False
            await client.create_task(request)
        finally:
            await client.close()

        self.assertNotIn("auxiliary_invocations", sent[0])

    async def test_invocation_telemetry_separates_the_work_the_broker_does_alone(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "task_id": "broker_task_1",
                "items": [
                    {"invocation_id": "inv_1", "role": "single", "status": "completed",
                     "contractual": True,
                     "prompt_compression": {"requested": "off", "effective": "off"}},
                    {"invocation_id": "inv_2", "role": "shadow_probe", "status": "completed",
                     "contractual": False,
                     "prompt_compression": {"requested": "off", "effective": "off"}},
                ],
            })

        client = self._client(handler)
        try:
            items = await client.invocations("broker_task_1")
        finally:
            await client.close()

        contractual = [item for item in items if is_contractual_invocation(item)]
        self.assertEqual(len(items), 2)
        self.assertEqual([item["invocation_id"] for item in contractual], ["inv_1"])

    async def test_an_unknown_role_is_accepted_not_rejected(self) -> None:
        """El contrato crece: un rol nuevo no puede romper al orquestador."""
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "task_id": "broker_task_1",
                "items": [{"invocation_id": "inv_1", "role": "rol_del_futuro",
                           "status": "estado_del_futuro", "contractual": True}],
            })

        client = self._client(handler)
        try:
            items = await client.invocations("broker_task_1")
        finally:
            await client.close()

        self.assertTrue(is_contractual_invocation(items[0]))

    async def test_the_deliverable_is_the_final_artifact_not_the_first_one(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "task_id": "broker_task_1",
                "items": [
                    {"artifact_id": "art_img", "artifact_type": "image_output",
                     "sha256": "0" * 64, "available": True, "final": False},
                    {"artifact_id": "art_out", "artifact_type": "single_output",
                     "sha256": "a" * 64, "available": True, "final": True},
                ],
            })

        client = self._client(handler)
        try:
            items = await client.artifacts("broker_task_1")
        finally:
            await client.close()

        entregable = final_artifact(items)
        self.assertIsNotNone(entregable)
        assert entregable is not None
        self.assertEqual(entregable["artifact_id"], "art_out")

    async def test_without_canonical_artifacts_there_is_no_deliverable_to_point_at(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "task_id": "broker_task_1",
                "items": [{"artifact_id": "art_1", "artifact_type": "single_output",
                           "sha256": "a" * 64, "available": True}],
            })

        client = self._client(handler)
        try:
            items = await client.artifacts("broker_task_1")
        finally:
            await client.close()

        self.assertIsNone(final_artifact(items))

    def test_restricted_content_does_not_tolerate_auxiliary_invocations(self) -> None:
        self.assertFalse(auxiliary_invocations_for("local_only"))
        self.assertFalse(auxiliary_invocations_for("confidential"))
        self.assertTrue(auxiliary_invocations_for("internal"))
        self.assertTrue(auxiliary_invocations_for("public"))


if __name__ == "__main__":
    unittest.main()
