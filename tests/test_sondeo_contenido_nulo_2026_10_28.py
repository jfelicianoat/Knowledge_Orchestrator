"""28-oct: una respuesta `completed` con assistant_content null paraba todo el sondeo.

`study_notes_quality_error(None)` lanzaba AttributeError; la excepción salía de
`poll_once` y en cada ciclo se consultaba solo la primera tarea de la cola: las
otras 394 seguían «en cola» aunque el Broker ya las había terminado.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from knowledge_orchestrator.services.broker_dispatch import BrokerDispatcher, BrokerPoller
from knowledge_orchestrator.services.output_quality import study_notes_quality_error
from tests import test_phase_three_workflows as phase_three
from tests.helpers import generic_markdown


def accepted(broker_id: str) -> dict:
    return {"task_id": broker_id, "status": "queued", "status_url": f"/api/v1/tasks/{broker_id}",
            "cancel_url": f"/api/v1/tasks/{broker_id}", "execution_strategy": "single",
            "execution_preset": "fast", "selection_mode": "auto"}


class FakeClient:
    def __init__(self, contents: dict[str, str | None]) -> None:
        self.contents = contents
        self.created: list[str] = []

    async def create_task(self, payload: dict) -> dict:
        self.created.append(payload["request_id"])
        return accepted(f"b_{len(self.created)}")

    async def get_task(self, broker_task_id: str, **_: object) -> dict:
        return {"task_id": broker_task_id, "status": "completed", "error": None,
                "result": {"assistant_content": self.contents[broker_task_id]}}


class SondeoContenidoNuloTests(unittest.IsolatedAsyncioTestCase):
    make_runtime = phase_three.PhaseThreeWorkflowTests.make_runtime

    def test_empty_content_is_a_quality_error_not_a_crash(self) -> None:
        self.assertEqual(study_notes_quality_error(None, final=True), "EMPTY_OUTPUT")
        self.assertEqual(study_notes_quality_error("  \n", final=True), "EMPTY_OUTPUT")

    async def test_a_null_answer_does_not_stop_polling_the_rest(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        runtime = self.make_runtime(Path(temporary.name), capture_id="nulo_a", transcript="Texto breve.")
        second = runtime.paths.inbox / "nulo_b.md"
        second.write_bytes(generic_markdown(capture_id="nulo_b"))
        self.assertTrue(runtime.ingestion.ingest(second).accepted)
        repository = runtime.workflow_repository
        tasks = []
        for capture in ("nulo_a", "nulo_b"):
            task = repository.list_workflow_tasks(runtime.workflow_planner.plan_capture(capture))[0]
            self.assertIsNotNone(repository.claim_submission(task.task_id))
            repository.mark_accepted(task.task_id, accepted(f"b_{capture}"))
            tasks.append(task)

        client = FakeClient({"b_nulo_a": None, "b_nulo_b": "Nota final"})
        updated = await BrokerPoller(repository, client, runtime.workflow_planner).poll_once()  # type: ignore[arg-type]

        self.assertEqual(updated, 2)
        first, second_task = (repository.get_task(task.task_id) for task in tasks)
        self.assertEqual(first.status.value, "ERROR")
        self.assertEqual(first.error_code, "EMPTY_OUTPUT")
        self.assertEqual(second_task.status.value, "SUCCESS")

    async def test_only_a_few_tasks_are_in_the_broker_at_once(self) -> None:
        """Mismo día: 634 tareas enviadas de golpe; ningún documento terminaba."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        runtime = self.make_runtime(Path(temporary.name), capture_id="cupo_a", transcript="Texto breve.")
        for capture in ("cupo_b", "cupo_c"):
            source = runtime.paths.inbox / f"{capture}.md"
            source.write_bytes(generic_markdown(capture_id=capture))
            self.assertTrue(runtime.ingestion.ingest(source).accepted)
        tasks = [runtime.workflow_repository.list_workflow_tasks(runtime.workflow_planner.plan_capture(capture))[0]
                 for capture in ("cupo_a", "cupo_b", "cupo_c")]
        client = FakeClient({})
        dispatcher = BrokerDispatcher(runtime.workflow_repository, client, max_in_flight=2)  # type: ignore[arg-type]

        self.assertEqual(await dispatcher.dispatch_once(), 2)
        self.assertEqual(await dispatcher.dispatch_once(), 0)  # cupo lleno: el tercero espera en KO
        self.assertEqual(client.created, [json.loads(task.request_json)["request_id"] for task in tasks[:2]])
        # Lo que se pide a mano desde la UI no espera al cupo.
        self.assertEqual(await dispatcher.dispatch_once([tasks[2].task_id]), 1)


if __name__ == "__main__":
    unittest.main()
