from __future__ import annotations

import queue
import unittest
from types import SimpleNamespace

from knowledge_orchestrator.config import BrokerSettings
from knowledge_orchestrator.integrations.broker_client import TransientBrokerError
from knowledge_orchestrator.worker.broker_worker import BrokerWorker


class _UnavailableCapabilitiesClient:
    async def capabilities(self) -> dict:
        raise TransientBrokerError("discovery no disponible")


class _FutureCapabilitiesClient:
    async def capabilities(self) -> dict:
        return {"contract_version": "2.9", "strategies": ["single"], "future_field": True}


class BrokerWorkerCapabilitiesTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _worker(client: object) -> BrokerWorker:
        return BrokerWorker(
            planner=None,  # type: ignore[arg-type]
            dispatcher=SimpleNamespace(client=client),  # type: ignore[arg-type]
            poller=None,  # type: ignore[arg-type]
            discovery=None,  # type: ignore[arg-type]
            events=queue.Queue(),
            settings=BrokerSettings(),
        )

    async def test_capabilities_failure_warns_without_raising_or_blocking(self) -> None:
        worker = self._worker(_UnavailableCapabilitiesClient())

        await worker._refresh_capabilities()

        self.assertEqual(worker.capabilities_snapshot(), {})
        event = worker.events.get_nowait()
        self.assertEqual(event.event_type, "BROKER_CAPABILITIES_UNAVAILABLE")

    async def test_future_contract_is_retained_and_reported_as_warning(self) -> None:
        worker = self._worker(_FutureCapabilitiesClient())

        await worker._refresh_capabilities()

        self.assertEqual(worker.capabilities_snapshot()["contract_version"], "2.9")
        events = [worker.events.get_nowait(), worker.events.get_nowait()]
        self.assertEqual([event.event_type for event in events], [
            "BROKER_CONTRACT_WARNING",
            "BROKER_CAPABILITIES_UPDATED",
        ])


if __name__ == "__main__":
    unittest.main()
