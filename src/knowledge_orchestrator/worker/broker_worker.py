from __future__ import annotations

import asyncio
import queue
import threading
import time

from knowledge_orchestrator.config import BrokerSettings
from knowledge_orchestrator.domain.models import ApplicationEvent
from knowledge_orchestrator.integrations.broker_client import BrokerClientError
from knowledge_orchestrator.services.broker_dispatch import BrokerDispatcher, BrokerPoller
from knowledge_orchestrator.services.model_discovery import ModelDiscoveryService
from knowledge_orchestrator.services.publication import PublicationService
from knowledge_orchestrator.services.semantic_broker import SemanticBrokerProcessor
from knowledge_orchestrator.services.workflow_planner import WorkflowPlanner


class BrokerWorker:
    """Bucle de red asíncrono aislado de la UI y del worker de filesystem."""

    def __init__(
        self,
        planner: WorkflowPlanner,
        dispatcher: BrokerDispatcher,
        poller: BrokerPoller,
        discovery: ModelDiscoveryService,
        events: "queue.Queue[ApplicationEvent]",
        settings: BrokerSettings,
        publisher: PublicationService | None = None,
        semantic_processor: SemanticBrokerProcessor | None = None,
    ) -> None:
        self.planner = planner
        self.dispatcher = dispatcher
        self.poller = poller
        self.discovery = discovery
        self.events = events
        self.settings = settings
        self.publisher = publisher
        self.semantic_processor = semantic_processor
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._broker_online: bool | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="broker-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            wait_seconds = timeout if timeout is not None else self.settings.request_timeout_seconds + 2.0
            self._thread.join(wait_seconds)
            if self._thread.is_alive():
                raise TimeoutError("El worker del Broker no se detuvo a tiempo")

    def _run(self) -> None:
        try:
            asyncio.run(self._run_async())
        except Exception as error:  # protección de la frontera del hilo
            self._emit("BROKER_WORKER_CRASH", str(error))

    async def _run_async(self) -> None:
        next_poll = 0.0
        next_discovery = 0.0
        next_health = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            try:
                planned = self.planner.plan_unplanned()
                accepted = await self.dispatcher.dispatch_once()
                if planned or accepted:
                    self._emit(
                        "BROKER_QUEUE_UPDATED",
                        f"Workflows planificados: {len(planned)}; tareas aceptadas: {accepted}",
                        {"planned": len(planned), "accepted": accepted},
                    )
                if now >= next_poll:
                    updated = await self.poller.poll_once()
                    if updated:
                        self._emit("BROKER_TASKS_UPDATED", f"Tareas actualizadas: {updated}", {"updated": updated})
                    next_poll = now + self.settings.poll_interval_seconds
                if self.publisher is not None:
                    published = self.publisher.publish_ready()
                    if published:
                        self._emit("NOTES_PUBLISHED", f"Notas publicadas: {published}", {"published": published})
                if self.semantic_processor is not None:
                    semantic_accepted = await self.semantic_processor.dispatch_once()
                    semantic_updated = await self.semantic_processor.poll_once()
                    if semantic_accepted or semantic_updated:
                        self._emit(
                            "SEMANTIC_JOBS_UPDATED",
                            f"Jobs semánticos aceptados: {semantic_accepted}; actualizados: {semantic_updated}",
                            {"accepted": semantic_accepted, "updated": semantic_updated},
                        )
                if now >= next_discovery:
                    try:
                        count = await self.discovery.refresh()
                        self._emit("BROKER_MODELS_UPDATED", f"Modelos disponibles: {count}", {"count": count})
                    except BrokerClientError as error:
                        self._emit("BROKER_OFFLINE", str(error))
                    next_discovery = now + self.settings.discovery_interval_seconds
                if now >= next_health:
                    await self._check_health()
                    next_health = now + self.settings.health_interval_seconds
            except BrokerClientError as error:
                self._emit("BROKER_OFFLINE", str(error))
            except Exception as error:
                self._emit("BROKER_CYCLE_ERROR", str(error))
            await self._sleep_until_next_cycle()

        client = self.dispatcher.client
        await client.close()

    async def _check_health(self) -> None:
        try:
            await self.dispatcher.client.health()
        except BrokerClientError as error:
            if self._broker_online is not False:
                self._emit("BROKER_OFFLINE", str(error))
            self._broker_online = False
        else:
            if self._broker_online is not True:
                self._emit("BROKER_ONLINE", "Broker disponible")
            self._broker_online = True

    async def _sleep_until_next_cycle(self) -> None:
        deadline = time.monotonic() + self.settings.dispatcher_interval_seconds
        while not self._stop.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def _emit(self, event_type: str, message: str, details: dict | None = None) -> None:
        self.events.put(
            ApplicationEvent(
                event_type=event_type,
                capture_id=None,
                message=message,
                details=details or {},
            )
        )
