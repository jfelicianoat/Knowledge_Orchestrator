from __future__ import annotations

import unittest

import httpx

from knowledge_orchestrator.config import BrokerSettings
from knowledge_orchestrator.domain.broker_contracts import BrokerContractError
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

    async def test_reads_v27_capabilities(self) -> None:
        client = BrokerClient(
            BrokerSettings(base_url="http://broker.test"),
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={
                "contract_version": "2.7",
                "strategies": ["single", "auto"],
                "work_lanes": ["inference"],
            })),
        )
        try:
            capabilities = await client.capabilities()
        finally:
            await client.close()
        self.assertEqual(capabilities["contract_version"], "2.7")
        self.assertIn("auto", capabilities["strategies"])

    async def test_capabilities_version_mismatch_is_reported_without_blocking_client(self) -> None:
        client = BrokerClient(
            BrokerSettings(base_url="http://broker.test"),
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, json={"contract_version": "2.8", "future_field": True})
            ),
        )
        try:
            capabilities = await client.capabilities()
        finally:
            await client.close()
        self.assertEqual(capabilities["contract_version"], "2.8")
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


if __name__ == "__main__":
    unittest.main()
