"""Recorrido real: AI OS Core decide qué tareas de KO van al AI Broker de verdad.

Uso: python scripts/verify_ai_os_core.py <core_url> <token_ko> <token_director> <broker_url> <carpeta>
     con KO_BROKER_ADMIN_TOKEN en el entorno.

El runtime es el real (ingesta, planificador, despachador y sondeo) sobre una carpeta de
usar y tirar: los datos reales de %LOCALAPPDATA%\\Knowledge Orchestrator no se tocan.
Core ha de tener las políticas de `sembrar_ecosistema.py` y el token por app de
knowledge_orchestrator; el token director (común) pone y quita la política DENY.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from tests.helpers import generic_markdown  # noqa: E402

from knowledge_orchestrator.config import BrokerSettings, PipelinePaths  # noqa: E402
from knowledge_orchestrator.integrations.broker_client import BrokerClient  # noqa: E402
from knowledge_orchestrator.runtime import build_runtime  # noqa: E402
from knowledge_orchestrator.services.broker_dispatch import BrokerDispatcher, BrokerPoller  # noqa: E402
from knowledge_orchestrator.services.file_stability import FileStabilityChecker  # noqa: E402

CORE, TOK_KO, TOK_DIR, BROKER, WORK = sys.argv[1:6]
ok = 0


def step(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(f"[{'OK ' if cond else 'FALLO'}] {name} {detail}", flush=True)
    if not cond:
        sys.exit(1)
    ok += 1


def new_task(runtime, capture: str):
    source = runtime.paths.inbox / f"{capture}.md"
    document = generic_markdown(capture_id=capture).decode("utf-8").replace(
        "Contenido aportado manualmente por el usuario.",
        "AI OS Core es el plano de control: decide qué trabajo sale hacia el Broker.",
    )
    source.write_text(document, encoding="utf-8")
    assert runtime.ingestion.ingest(source).accepted
    workflow = runtime.workflow_planner.plan_capture(capture)
    return runtime.workflow_repository.list_workflow_tasks(workflow)[0]


async def main() -> None:
    runtime = build_runtime(PipelinePaths.under(Path(WORK) / f"ko-{os.getpid()}"))
    runtime.ingestion.stability_checker = FileStabilityChecker(interval_seconds=0, sleep=lambda _: None)
    director = httpx.Client(base_url=CORE, headers={"Authorization": f"Bearer {TOK_DIR}"}, timeout=10)
    settings = dict(base_url=BROKER, admin_token=os.environ["KO_BROKER_ADMIN_TOKEN"], core_token=TOK_KO)
    client = BrokerClient(BrokerSettings(**settings, core_url=CORE))
    repository = runtime.workflow_repository
    deny = {"policy_id": "verify_ko_deny", "policy_key": "verify_ko_deny", "scope": "knowledge_orchestrator:broker",
            "decision_if_matched": "DENY",
            "conditions": [{"field": "operation_type", "operator": "equals", "value": "study_notes"}]}
    try:
        step("director pone DENY", director.post("/api/v1/policies", json=deny).status_code in (200, 201))
        task = new_task(runtime, "verify_core_deny")
        accepted = await BrokerDispatcher(repository, client).dispatch_once({task.task_id})
        saved = repository.get_task(task.task_id)
        step("con DENY no se envía y queda CORE_DENIED", accepted == 0 and saved.error_code == "CORE_DENIED",
             saved.error_message[:140])
        step("director quita DENY", director.post("/api/v1/policies", json={**deny, "enabled": False}).status_code
             in (200, 201))

        down = BrokerClient(BrokerSettings(**settings, core_url="http://127.0.0.1:9"))
        task = new_task(runtime, "verify_core_down")
        accepted = await BrokerDispatcher(repository, down).dispatch_once({task.task_id})
        saved = repository.get_task(task.task_id)
        step("con Core caído no se envía y se reintentará", accepted == 0 and saved.status.value == "READY"
             and saved.next_retry_at is not None, saved.error_message[:140])
        await down.close()

        task = new_task(runtime, "verify_core_allow")
        accepted = await BrokerDispatcher(repository, client).dispatch_once({task.task_id})
        step("con ALLOW la tarea entra en el Broker real", accepted == 1)
        poller = BrokerPoller(repository, client, runtime.workflow_planner)
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            await poller.poll_once()
            saved = repository.get_task(task.task_id)
            if saved.status.value in {"SUCCESS", "FAILED", "CANCELLED"}:
                break
            await asyncio.sleep(3)
        step("la tarea terminó en el Broker real", saved.status.value == "SUCCESS",
             f"{saved.status.value} {saved.error_code} {(saved.error_message or '')[:120]}")
        receipt = director.post("/api/v1/operations/status", json={
            "operation_id": saved.idempotency_key, "target_service_id": "ai_broker"}).json()
        step("Core tiene el recibo succeeded", receipt.get("status") == "succeeded", str(receipt)[:200])
    finally:
        await client.close()
    print(f"\n{ok} comprobaciones OK")


asyncio.run(main())
