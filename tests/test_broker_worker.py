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


class _ReconfigurableClient:
    def __init__(self) -> None:
        self.settings: BrokerSettings | None = None

    async def reconfigure(self, settings: BrokerSettings) -> None:
        self.settings = settings


class _OfflineClient:
    async def capabilities(self) -> dict:
        return {"contract_version": "2.8"}

    async def health(self) -> dict:
        raise TransientBrokerError("Broker desconectado")

    async def close(self) -> None:
        pass


class _OnlineClient(_OfflineClient):
    async def health(self) -> dict:
        return {"status": "ok"}

    async def auth_check(self) -> dict:
        return {"authenticated": True, "auth_required": False}


class _CountingDispatcher:
    def __init__(self, client: object) -> None:
        self.client = client
        self.calls = 0

    async def dispatch_once(self, _task_ids=None) -> int:
        self.calls += 1
        return 0


class _EmptyRepository:
    def list_cancel_requested(self) -> list:
        return []


class _EmptyPoller:
    def __init__(self) -> None:
        self.repository = _EmptyRepository()

    async def poll_once(self) -> int:
        return 0


class _EmptyDiscovery:
    async def refresh(self) -> int:
        return 0


class _OneCycleOfflineWorker(BrokerWorker):
    async def _sleep_until_next_cycle(self, consecutive_errors: int = 0) -> None:
        self._stop.set()


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

    async def test_connection_settings_are_applied_without_restarting_worker(self) -> None:
        client = _ReconfigurableClient()
        worker = self._worker(client)
        settings = BrokerSettings(base_url="http://new-broker.test:8765", admin_token="new-token")

        worker.reconfigure(settings)

        self.assertTrue(await worker._apply_pending_settings())
        self.assertIs(client.settings, settings)
        self.assertIs(worker.settings, settings)
        self.assertEqual(worker.events.get_nowait().event_type, "BROKER_CONNECTION_UPDATED")

    async def test_selected_tasks_can_request_an_immediate_dispatch_cycle(self) -> None:
        worker = self._worker(_ReconfigurableClient())

        worker.request_dispatch(["task-b", "task-a", "task-b"])

        self.assertEqual(set(worker._take_dispatch_request()), {"task-a", "task-b"})
        self.assertEqual(worker._take_dispatch_request(), ())

    async def test_offline_broker_blocks_task_submission_for_the_whole_cycle(self) -> None:
        client = _OfflineClient()
        dispatcher = _CountingDispatcher(client)
        worker = _OneCycleOfflineWorker(
            planner=SimpleNamespace(plan_unplanned=lambda: []),
            dispatcher=dispatcher,  # type: ignore[arg-type]
            poller=_EmptyPoller(),  # type: ignore[arg-type]
            discovery=_EmptyDiscovery(),  # type: ignore[arg-type]
            events=queue.Queue(),
            settings=BrokerSettings(),
        )

        await worker._run_async()

        self.assertEqual(dispatcher.calls, 0)

    async def test_submission_resumes_after_health_check_succeeds(self) -> None:
        client = _OnlineClient()
        dispatcher = _CountingDispatcher(client)
        worker = _OneCycleOfflineWorker(
            planner=SimpleNamespace(plan_unplanned=lambda: []),
            dispatcher=dispatcher,  # type: ignore[arg-type]
            poller=_EmptyPoller(),  # type: ignore[arg-type]
            discovery=_EmptyDiscovery(),  # type: ignore[arg-type]
            events=queue.Queue(),
            settings=BrokerSettings(),
        )

        await worker._run_async()

        self.assertEqual(dispatcher.calls, 1)


if __name__ == "__main__":
    unittest.main()
