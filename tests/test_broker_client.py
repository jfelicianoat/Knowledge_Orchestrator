from __future__ import annotations

import unittest

import httpx

from knowledge_orchestrator.config import BrokerSettings
from knowledge_orchestrator.domain.broker_contracts import BrokerContractError
from knowledge_orchestrator.integrations.broker_client import BrokerClient, TransientBrokerError
from tests.test_broker_contracts import valid_request


class BrokerClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_202_and_polls_long_running_task(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                return httpx.Response(202, json={
                    "task_id": "task_1", "status": "queued",
                    "status_url": "/api/v1/tasks/task_1", "cancel_url": "/api/v1/tasks/task_1",
                })
            return httpx.Response(200, json={"task_id": "task_1", "status": "processing"})

        client = BrokerClient(BrokerSettings(base_url="http://broker.test"), transport=httpx.MockTransport(handler))
        try:
            accepted = await client.create_task(valid_request())
            status = await client.get_task("task_1", status_url=accepted["status_url"])
            self.assertEqual(status["status"], "processing")
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


if __name__ == "__main__":
    unittest.main()
