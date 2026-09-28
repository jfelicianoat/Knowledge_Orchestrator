"""Regresiones de la auditoría del 27-sep-2026 (H01–H12) y de lo que apareció al revisarla.

Cada prueba reproduce el escenario del informe y afirma también la AUSENCIA de
efectos no autorizados: nada publicado sin aprobar, ningún envío tras cancelar,
ninguna afirmación respaldada por una fuente que no la dice.
"""
from __future__ import annotations

import asyncio
import errno
import json
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from unittest import mock

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.domain.broker_models import StepKind, TaskStatus, WorkflowStatus
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services import filesystem
from knowledge_orchestrator.services.file_stability import FileStabilityChecker
from knowledge_orchestrator.services.prompting import estimate_tokens
from knowledge_orchestrator.services.semantic_broker import SemanticBrokerProcessor
from knowledge_orchestrator.services.semantic_maintenance import SemanticContractError
from knowledge_orchestrator.services.workflow_planner import WorkflowPlanner
from tests.helpers import generic_markdown
from tests.note_editor import FakeNoteEditor

LONG_TRANSCRIPT = "\n".join(
    f"[00:{index // 60:02d}:{index % 60:02d}] Frase número {index} sobre inversión, dividendos y riesgo "
    f"del mercado con detalle suficiente para ocupar espacio en la ventana."
    for index in range(1200)
)
ACCEPTED = {
    "status": "queued", "execution_strategy": "single", "execution_preset": "fast", "selection_mode": "auto",
}


class AuditBase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.paths = PipelinePaths.under(self.root)
        self.runtime = build_runtime(self.paths, note_editor=FakeNoteEditor(self.paths.obsidian_vault))
        self.runtime.ingestion.stability_checker = FileStabilityChecker(interval_seconds=0, sleep=lambda _: None)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def profile(self, **changes):
        profile = self.runtime.profiles.list_profiles(enabled_only=True)[0]
        if changes:
            self.runtime.profiles.save_profile(replace(profile, **changes))
        return self.runtime.profiles.list_profiles(enabled_only=True)[0]

    def ingest(self, capture_id: str, transcript: str = "Contenido aportado manualmente por el usuario.") -> None:
        source = self.paths.inbox / f"{capture_id}.md"
        source.write_bytes(generic_markdown(capture_id=capture_id, title=f"Documento {capture_id}",
                                            transcript=transcript))
        self.assertTrue(self.runtime.ingestion.ingest(source).accepted)

    def succeed(self, task_id: str, content: str, *, broker_id: str | None = None) -> None:
        repository = self.runtime.workflow_repository
        self.assertIsNotNone(repository.claim_submission(task_id))
        broker = broker_id or f"broker_{task_id}"
        repository.mark_accepted(task_id, {**ACCEPTED, "task_id": broker, "status_url": f"/t/{broker}",
                                           "cancel_url": f"/t/{broker}"})
        repository.apply_status(task_id, {"task_id": broker, "status": "success",
                                          "result": {"assistant_content": content}, "error": None})

    def publish(self, capture_id: str, body: str, transcript: str | None = None):
        self.ingest(capture_id, transcript if transcript is not None else body)
        workflow_id = self.runtime.workflow_planner.plan_capture(capture_id)
        task = self.runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
        self.succeed(task.task_id, body)
        self.runtime.workflow_planner.advance_workflow(workflow_id)
        self.assertEqual(self.runtime.publication.publish_ready(), 1)
        return next(note for note in self.runtime.publication_repository.list_notes_by_status("PUBLISHED")
                    if note.capture_id == capture_id)


STUDY_NOTE = (
    "# Resumen\n\n"
    "## Ideas clave\n\n"
    "- La cartera reparte dividendos cada trimestre y reinvierte una parte.\n"
    "- El riesgo principal es la concentración sectorial de la cartera.\n"
)


class HumanReviewTests(AuditBase):
    """H01: con la casilla marcada, nada llega a la bóveda sin una decisión humana."""

    def setUp(self) -> None:
        super().setUp()
        self.profile(human_review_required=True)
        self.ingest("revisada", STUDY_NOTE)
        self.workflow_id = self.runtime.workflow_planner.plan_capture("revisada")
        task = self.runtime.workflow_repository.list_workflow_tasks(self.workflow_id)[0]
        self.succeed(task.task_id, STUDY_NOTE)
        self.runtime.workflow_planner.advance_workflow(self.workflow_id)

    def vault_notes(self) -> list[Path]:
        return [path for path in self.paths.obsidian_vault.rglob("*.md")]

    def test_finished_result_waits_as_draft_even_after_restart(self) -> None:
        self.assertEqual(self.runtime.publication.publish_ready(), 0)
        self.runtime.recover_once(ingest_inbox=False)
        self.assertEqual(self.runtime.publication.publish_ready(), 0)
        self.assertEqual(self.vault_notes(), [])
        draft = self.runtime.publication_repository.get_draft("revisada")
        assert draft is not None
        self.assertEqual(draft.review_status, "PENDING")
        item = next(item for item in self.runtime_snapshots().work_items() if item.capture_id == "revisada")
        self.assertEqual((item.status, item.category, item.status_label),
                         ("AWAITING_REVIEW", "attention", "Pendiente de revisión"))

    def runtime_snapshots(self):
        from knowledge_orchestrator.ui.snapshots import UiSnapshotService

        return UiSnapshotService(self.runtime.database)

    def test_approval_is_bound_to_the_reviewed_text(self) -> None:
        draft = self.runtime.publication_repository.get_draft("revisada")
        assert draft is not None
        self.assertFalse(self.runtime.publication_repository.approve_draft(draft.workflow_id, "0" * 64))
        self.assertEqual(self.runtime.publication.publish_ready(), 0)
        self.assertTrue(self.runtime.publication_repository.approve_draft(draft.workflow_id, draft.result_hash))
        self.assertFalse(self.runtime.publication_repository.approve_draft(draft.workflow_id, draft.result_hash))
        self.assertEqual(self.runtime.publication.publish_ready(), 1)
        [note] = self.vault_notes()
        self.assertIn("reinvierte una parte", note.read_text(encoding="utf-8"))

    def test_rejection_keeps_source_and_result_and_allows_reprocessing(self) -> None:
        draft = self.runtime.publication_repository.get_draft("revisada")
        assert draft is not None
        self.assertTrue(self.runtime.publication_repository.reject_draft(draft.workflow_id))
        self.assertEqual(self.runtime.publication.publish_ready(), 0)
        self.assertEqual(self.vault_notes(), [])
        capture = self.runtime.repository.get("revisada")
        assert capture is not None and capture.processing_path is not None
        self.assertTrue(capture.processing_path.exists())
        self.assertEqual(capture.status.value, "REJECTED")
        self.assertIn("reinvierte", self.runtime.workflow_repository.get_workflow(draft.workflow_id).final_result)
        self.assertTrue(self.runtime.publication_repository.reopen_rejected_draft("revisada"))
        [planned] = self.runtime.workflow_planner.plan_unplanned()
        self.assertTrue(planned.endswith("_r2"))


class WorkflowCancellationTests(AuditBase):
    """H02: cancelar un documento para todas sus partes y no es un error."""

    def setUp(self) -> None:
        super().setUp()
        self.runtime.workflow_planner.max_context_tokens = 4_000
        self.ingest("largo", LONG_TRANSCRIPT)
        self.workflow_id = self.runtime.workflow_planner.plan_capture("largo")
        self.tasks = self.runtime.workflow_repository.list_workflow_tasks(self.workflow_id)

    def test_cancelling_one_part_stops_the_whole_document(self) -> None:
        repository = self.runtime.workflow_repository
        self.assertGreater(len(self.tasks), 10)
        first, second = self.tasks[0], self.tasks[1]
        self.succeed(first.task_id, "Resumen parcial uno.")
        self.assertIsNotNone(repository.claim_submission(second.task_id))
        repository.mark_accepted(second.task_id, {**ACCEPTED, "task_id": "b2", "status_url": "/t/b2",
                                                  "cancel_url": "/t/b2"})
        self.assertTrue(repository.request_cancel(second.task_id))
        self.assertEqual(repository.list_dispatchable(), [])
        self.assertEqual(repository.get_workflow(self.workflow_id).status, WorkflowStatus.CANCELLED)
        self.assertEqual(self.runtime.repository.get("largo").status.value, "CANCELLED")
        self.assertEqual([task.task_id for task in repository.list_cancel_requested()], [second.task_id])
        # Llega tarde la confirmación del Broker: sigue cancelado, no es un error.
        repository.apply_status(second.task_id, {"task_id": "b2", "status": "cancelled", "result": None,
                                                 "error": {"code": "CANCELLED", "message": "cancelada"}})
        self.runtime.workflow_planner.advance_workflow(self.workflow_id)
        self.assertEqual(repository.get_workflow(self.workflow_id).status, WorkflowStatus.CANCELLED)
        self.assertEqual(self.runtime.repository.get("largo").status.value, "CANCELLED")
        self.assertFalse(any(task.step_kind is StepKind.SYNTHESIS
                             for task in repository.list_workflow_tasks(self.workflow_id)))
        self.assertFalse(repository.cancel_capture("largo"))
        from knowledge_orchestrator.ui.snapshots import UiSnapshotService

        item = next(item for item in UiSnapshotService(self.runtime.database).work_items()
                    if item.capture_id == "largo")
        self.assertEqual((item.status, item.category), ("CANCELLED", "completed"))

    def test_cancellation_while_submitting_is_cancelled_remotely_or_closed_locally(self) -> None:
        repository = self.runtime.workflow_repository
        in_flight = self.tasks[0]
        self.assertIsNotNone(repository.claim_submission(in_flight.task_id))
        self.assertTrue(repository.cancel_capture("largo"))
        # El POST sí llegó: se guardan sus identificadores para cancelarla en el Broker.
        repository.mark_accepted(in_flight.task_id, {**ACCEPTED, "task_id": "late", "status_url": "/t/late",
                                                     "cancel_url": "/t/late"})
        self.assertEqual(repository.get_task(in_flight.task_id).broker_task_id, "late")
        self.assertEqual(repository.get_task(in_flight.task_id).status, TaskStatus.CANCEL_REQUESTED)
        self.assertEqual(repository.settle_orphan_cancellations(), 0)


class StartupIsolationTests(AuditBase):
    """H03: una nota movida no impide arrancar ni analizar las demás."""

    def test_missing_note_does_not_abort_recovery(self) -> None:
        moved = self.publish("movida", STUDY_NOTE)
        healthy = self.publish("sana", STUDY_NOTE.replace("trimestre", "mes"))
        with closing(self.runtime.database.connect()) as connection, connection:
            connection.execute("DELETE FROM semantic_jobs")
        moved.vault_path.rename(moved.vault_path.with_name("renombrada.md"))
        self.runtime.recover_once(ingest_inbox=False)
        jobs = {job.note_id for job in self.runtime.semantic_repository.list_dispatchable_jobs()}
        self.assertEqual(jobs, {healthy.note_id})
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            blocked = connection.execute(
                "SELECT COUNT(*) FROM events WHERE event_type = 'NOTE_ANALYSIS_BLOCKED' AND capture_id = 'movida'"
            ).fetchone()[0]
        self.assertEqual(blocked, 1)
        # Repetir el arranque no repite el aviso ni lo convierte en un fallo.
        self.runtime.recover_once(ingest_inbox=False)


class _Client:
    def __init__(self, results: dict[str, dict]) -> None:
        self.results = results

    async def get_task(self, task_id, *, status_url=None):
        return self.results[task_id]


class InvalidJsonTests(AuditBase):
    """H04: tipos inesperados terminan el trabajo como incidencia, sin bloquear la cola."""

    def test_list_where_a_string_goes_fails_the_job_and_the_next_one_still_runs(self) -> None:
        first = self.publish("mala", STUDY_NOTE)
        second = self.publish("buena", STUDY_NOTE.replace("trimestre", "mes"))
        repository = self.runtime.semantic_repository
        jobs = {job.note_id: job for job in repository.list_dispatchable_jobs()}
        for note_id, job in jobs.items():
            repository.claim_job(job.job_id)
            repository.accept_job(job.job_id, {"task_id": f"b{note_id}", "status_url": f"/t/b{note_id}"})
        bad = {"claims": [{"note_segment": "N1", "source_segments": [], "claim_type": "HECHO",
                           "volatility": [], "entities": []}]}
        good = {"claims": [{"note_segment": "N1", "source_segments": ["S1"], "claim_type": "HECHO",
                            "volatility": "LOW", "entities": ["cartera"]}]}
        client = _Client({
            f"b{first.note_id}": {"status": "success", "result": {"assistant_content": json.dumps(bad)}},
            f"b{second.note_id}": {"status": "success", "result": {"assistant_content": json.dumps(good)}},
        })
        processor = SemanticBrokerProcessor(repository, self.runtime.semantic_maintenance, client)
        asyncio.run(processor.poll_once())
        self.assertEqual(repository.get_job(jobs[first.note_id].job_id).status, "ERROR")
        self.assertEqual(repository.get_job(jobs[second.note_id].job_id).status, "SUCCESS")
        self.assertEqual(repository.list_claims(first.note_id), [])
        self.assertEqual(len(repository.list_claims(second.note_id)), 1)
        for value in ([], {}, 3, None):
            payload = {"relation": value, "confidence": 0.5, "impact": "LOW", "rationale": "x",
                       "replacement_text": None}
            with self.assertRaises(SemanticContractError):
                self.runtime.semantic_maintenance._parse_comparison(payload)


class AnalysisRetryTests(AuditBase):
    """H05: tras un fallo, cambiar el modelo produce un intento nuevo y despachable."""

    def test_reanalysis_creates_a_new_attempt_with_the_current_model(self) -> None:
        note = self.publish("reintento", STUDY_NOTE)
        service, repository = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        first = repository.list_dispatchable_jobs()[0]
        repository.claim_job(first.job_id)
        repository.fail_job(first.job_id, "SEMANTIC_CONTRACT_FAILED", "basura")
        self.assertEqual(service.schedule_extraction(note.note_id), first.job_id)  # arranque: no duplica
        self.profile(analysis_model="modelo-nuevo:7b")
        second_id = service.reanalyze_note(note.note_id)
        self.assertNotEqual(second_id, first.job_id)
        self.assertEqual(service.reanalyze_note(note.note_id), second_id)  # en curso: no duplica
        second = repository.get_job(second_id)
        self.assertEqual(second.status, "READY")
        request = json.loads(second.request_json)
        self.assertEqual(request["model_requirements"]["preferred_model"], "modelo-nuevo:7b")
        # Modelo fijado a mano: exacto, sin que el Broker lo sustituya (H10).
        self.assertFalse(request["model_requirements"]["fallback_allowed"])
        self.assertFalse(request["execution"]["selection"]["allow_substitution"])
        self.assertEqual(repository.get_job(first.job_id).status, "ERROR")
        self.assertEqual([job.job_id for job in repository.extraction_jobs(note.note_id)], [first.job_id, second_id])


class LongDocumentContextTests(AuditBase):
    """H06: ninguna petición supera la ventana, tampoco la síntesis."""

    def test_every_request_fits_the_window_through_hierarchical_reduction(self) -> None:
        window = 4_000
        self.runtime.workflow_planner.max_context_tokens = window
        self.ingest("enorme", LONG_TRANSCRIPT)
        workflow_id = self.runtime.workflow_planner.plan_capture("enorme")
        repository = self.runtime.workflow_repository
        planner: WorkflowPlanner = self.runtime.workflow_planner
        seen: set[str] = set()
        for _ in range(12):
            tasks = repository.list_workflow_tasks(workflow_id)
            for task in tasks:
                if task.task_id in seen or task.status is not TaskStatus.READY:
                    continue
                seen.add(task.task_id)
                request = json.loads(task.request_json)
                used = estimate_tokens(request["content"]["prompt"]) + request["generation"]["max_output_tokens"]
                self.assertLessEqual(used, window, task.step_id)
                self.succeed(task.task_id, "Síntesis parcial. " * 400)
            planner.advance_workflow(workflow_id)
            if repository.get_workflow(workflow_id).status is WorkflowStatus.SUCCESS:
                break
        self.assertEqual(repository.get_workflow(workflow_id).status, WorkflowStatus.SUCCESS)
        steps = [task.step_id for task in repository.list_workflow_tasks(workflow_id)]
        self.assertTrue(any(step.startswith("reduce_1_") for step in steps))
        self.assertIn("synthesis", steps)


class SourceEvidenceTests(AuditBase):
    """H07: una frase inventada en el resumen nunca queda respaldada por la fuente."""

    def test_invented_summary_sentence_is_marked_summary_only_and_proposes_nothing(self) -> None:
        body = STUDY_NOTE + "- La Luna está hecha de queso según el autor.\n"
        note = self.publish("luna", body, transcript=STUDY_NOTE)
        service, repository = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        payload = {"claims": [
            {"note_segment": "N1", "source_segments": ["S1"], "claim_type": "HECHO", "volatility": "LOW",
             "entities": ["cartera"]},
            {"note_segment": "N3", "source_segments": ["S1"], "claim_type": "HECHO", "volatility": "LOW",
             "entities": ["Luna"]},
        ]}
        self.assertEqual(service.ingest_extraction(note.note_id, payload), [])
        claims = {claim.statement: claim for claim in repository.list_claims(note.note_id)}
        moon = claims["La Luna está hecha de queso según el autor."]
        dividends = claims["La cartera reparte dividendos cada trimestre y reinvierte una parte."]
        # El modelo señaló S1, pero la fuente no lo dice: queda como enlace sin verificar.
        self.assertEqual(moon.source_support, "MODEL_LINKED")
        self.assertTrue(all(item["method"] == "MODEL_LINK" for item in repository.source_evidence(moon.claim_id)))
        self.assertEqual(dividends.source_support, "SOURCE")
        [evidence] = repository.source_evidence(dividends.claim_id)
        self.assertIn("reparte dividendos", evidence["quote"])
        self.assertEqual(service.generate_candidates(moon.claim_id), [])

    def test_unknown_note_segments_are_discarded_and_counted_never_invented(self) -> None:
        note = self.publish("inventada", STUDY_NOTE)
        valid = {"note_segment": "N1", "source_segments": [], "claim_type": "HECHO", "volatility": "LOW",
                 "entities": []}
        unknown = {**valid, "note_segment": "N99"}
        service = self.runtime.semantic_maintenance
        with self.assertRaises(SemanticContractError):
            service.ingest_extraction(note.note_id, {"claims": [unknown]})
        self.assertEqual(self.runtime.semantic_repository.list_claims(note.note_id), [])
        service.ingest_extraction(note.note_id, {"claims": [valid, unknown]})
        self.assertEqual(len(self.runtime.semantic_repository.list_claims(note.note_id)), 1)
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            message = connection.execute(
                "SELECT message FROM events WHERE event_type = 'KNOWLEDGE_EXTRACTED' ORDER BY event_id DESC"
            ).fetchone()[0]
        self.assertIn("Se descartaron 1", message)


class DocumentBudgetTests(AuditBase):
    """H08: el presupuesto es del documento, no de cada petición."""

    def test_split_document_never_reserves_more_than_its_budget(self) -> None:
        self.profile(max_cost_usd=0.05)
        self.runtime.workflow_planner.max_context_tokens = 4_000
        self.ingest("coste", LONG_TRANSCRIPT)
        workflow_id = self.runtime.workflow_planner.plan_capture("coste")
        repository = self.runtime.workflow_repository
        tasks = repository.list_workflow_tasks(workflow_id)
        total = sum(json.loads(task.request_json)["model_requirements"]["max_cost_usd"] for task in tasks)
        self.assertLessEqual(total, 0.05)
        # Aunque alguien inflara una petición, la bolsa la para antes de enviarla.
        with closing(self.runtime.database.connect()) as connection, connection:
            connection.execute("UPDATE workflows SET budget_reserved_usd = 0.0499999 WHERE workflow_id = ?",
                               (workflow_id,))
        self.assertIsNone(repository.claim_submission(tasks[0].task_id))
        failed = repository.get_task(tasks[0].task_id)
        self.assertEqual(failed.error_code, "DOCUMENT_BUDGET_EXHAUSTED")
        self.assertEqual(repository.get_workflow(workflow_id).status, WorkflowStatus.ERROR)

    def test_failure_that_never_ran_returns_its_reservation(self) -> None:
        self.profile(max_cost_usd=0.05)
        self.ingest("devolucion", "Texto breve.")
        workflow_id = self.runtime.workflow_planner.plan_capture("devolucion")
        repository = self.runtime.workflow_repository
        task = repository.list_workflow_tasks(workflow_id)[0]
        repository.claim_submission(task.task_id)
        repository.mark_accepted(task.task_id, {**ACCEPTED, "task_id": "d", "status_url": "/t/d", "cancel_url": "/t/d"})
        repository.apply_status(task.task_id, {"task_id": "d", "status": "failed", "result": None,
                                               "error": {"code": "MODEL_UNAVAILABLE", "message": "no"}})
        self.assertTrue(repository.retry_failed_task(task.task_id))
        self.assertIsNotNone(repository.claim_submission(task.task_id))


class FallbackAndRetryPolicyTests(AuditBase):
    """H11 y H12: `auto` cae a single; reintentar no mezcla políticas."""

    def test_auto_strategy_reaches_its_fallback(self) -> None:
        self.profile(execution_strategy="auto", multitasking_steps=("single", "synthesis"),
                     consensus_fallback_to_single=True)
        self.ingest("auto", "Texto breve.")
        workflow_id = self.runtime.workflow_planner.plan_capture("auto")
        repository = self.runtime.workflow_repository
        task = repository.list_workflow_tasks(workflow_id)[0]
        repository.claim_submission(task.task_id)
        repository.mark_accepted(task.task_id, {**ACCEPTED, "execution_strategy": "auto", "task_id": "a",
                                                "status_url": "/t/a", "cancel_url": "/t/a"})
        repository.apply_status(task.task_id, {"task_id": "a", "status": "failed", "result": None,
                                               "error": {"code": "CONSENSUS_QUORUM_NOT_REACHED", "message": "q"}})
        self.assertNotEqual(repository.get_workflow(workflow_id).status, WorkflowStatus.ERROR)
        self.runtime.workflow_planner.advance_workflow(workflow_id)
        fallbacks = [item for item in repository.list_workflow_tasks(workflow_id)
                     if item.replacement_for_task_id == task.task_id]
        self.assertEqual(len(fallbacks), 1)

    def test_retry_rebuilds_the_whole_policy_from_the_current_profile(self) -> None:
        self.profile(data_classification="public", fallback_allowed=True)
        self.ingest("politica", "Texto breve.")
        workflow_id = self.runtime.workflow_planner.plan_capture("politica")
        repository = self.runtime.workflow_repository
        task = repository.list_workflow_tasks(workflow_id)[0]
        self.assertEqual(json.loads(task.request_json)["risk"]["data_classification"], "public")
        self.profile(data_classification="local_only", fallback_allowed=False)
        repository.apply_status(task.task_id, {"task_id": "x", "status": "failed", "result": None,
                                               "error": {"code": "MODEL_UNAVAILABLE", "message": "no"}})
        self.assertTrue(repository.retry_failed_task(task.task_id))
        resent = json.loads(repository.get_task(task.task_id).request_json)
        self.assertEqual(resent["risk"]["data_classification"], "local_only")
        self.assertFalse(resent["model_requirements"]["fallback_allowed"])
        self.assertFalse(resent["execution"]["selection"]["allow_substitution"])
        self.assertNotIn("allowed_providers", resent["model_requirements"])


class RealVaultFilesystemTests(unittest.TestCase):
    """Lo que falló con la configuración real: Google Drive sin enlaces duros, C: y Y: distintas."""

    def test_publication_installs_without_hard_links_and_never_overwrites(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            temporary, destination = Path(folder) / ".nota.tmp", Path(folder) / "nota.md"
            temporary.write_text("nueva", encoding="utf-8")
            with mock.patch("os.link", side_effect=OSError(1, "Función incorrecta")):
                if filesystem.os.name == "nt":
                    filesystem.install_new_file(temporary, destination)
                    self.assertEqual(destination.read_text(encoding="utf-8"), "nueva")
                    other = Path(folder) / ".otra.tmp"
                    other.write_text("ajena", encoding="utf-8")
                    with self.assertRaises(FileExistsError):
                        filesystem.install_new_file(other, destination)
                    self.assertEqual(destination.read_text(encoding="utf-8"), "nueva")
                else:
                    with self.assertRaises(OSError):
                        filesystem.install_new_file(temporary, destination)

    def test_move_between_volumes_copies_verifies_and_retires_the_source(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / "a.md", Path(folder) / "otra" / "a.md"
            source.write_bytes(b"contenido")
            real_replace = filesystem.os.replace
            calls = {"n": 0}

            def cross_device_once(src, dst):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise OSError(errno.EXDEV, "not same device")
                return real_replace(src, dst)

            with mock.patch.object(filesystem.os, "replace", side_effect=cross_device_once):
                filesystem.move_file(source, target)
            self.assertEqual(target.read_bytes(), b"contenido")
            self.assertFalse(source.exists())
            self.assertEqual(list(target.parent.glob(".*.tmp")), [])

    def test_orphan_quarantine_intent_is_set_aside_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            paths = PipelinePaths.under(Path(folder))
            runtime = build_runtime(paths)
            intent = paths.failed / "duplicates" / ".quarantine-abc.pending.json"
            intent.parent.mkdir(parents=True, exist_ok=True)
            intent.write_text(json.dumps({
                "source_path": str((paths.inbox / "desaparecido.md").resolve()),
                "destination_path": str((paths.failed / "duplicates" / "desaparecido.md").resolve()),
                "sidecar_path": str((paths.failed / "duplicates" / "desaparecido.md.error.json").resolve()),
                "error": {"code": "DUPLICATE_CAPTURE"},
            }), encoding="utf-8")
            runtime.recover_once(ingest_inbox=False)
            runtime.recover_once(ingest_inbox=False)
            self.assertFalse(intent.exists())
            self.assertTrue(intent.with_name(".quarantine-abc.abandoned.json").exists())
            with closing(runtime.database.connect(readonly=True)) as connection:
                counts = dict(connection.execute(
                    "SELECT event_type, COUNT(*) FROM events WHERE event_type LIKE 'QUARANTINE%' GROUP BY 1"
                ).fetchall())
            self.assertEqual(counts, {"QUARANTINE_INTENT_ABANDONED": 1})


if __name__ == "__main__":
    unittest.main()


class ImageIntentShieldTests(unittest.TestCase):
    """Un documento que habla de «generar imágenes» no es una petición de imagen (Broker real, 27-sep)."""

    def test_trigger_phrases_are_broken_and_restored_exactly(self) -> None:
        from knowledge_orchestrator.services.broker_shield import WORD_JOINER, shield_prompt, unshield

        for text in ("Con MCP se pueden conectar servicios para generar imágenes o videos.",
                     "Generate images with AI.", "Luego crea una imagen de portada.", "Haz fotos del producto."):
            shielded = shield_prompt(text)
            self.assertIn(WORD_JOINER, shielded, text)
            self.assertEqual(unshield(shielded), text)
        for harmless in ("la generación de imágenes", "crear una propuesta de servicio", "imágenes generadas"):
            self.assertEqual(shield_prompt(harmless), harmless)

    def test_note_and_analysis_requests_are_shielded_and_results_cleaned(self) -> None:
        from knowledge_orchestrator.domain.models import ProfileDefinition
        from knowledge_orchestrator.repositories.workflow_repository.estado import resultado_de
        from knowledge_orchestrator.services.broker_shield import WORD_JOINER
        from knowledge_orchestrator.services.prompting import build_chat_request
        from knowledge_orchestrator.services.semantic_maintenance.prompts import PromptsMixin

        profile = ProfileDefinition(name="p", system_prompt="s", user_prompt="u", chunk_prompt="c",
                                    synthesis_prompt="y", preferred_model="")
        request = build_chat_request(task_id="t", idempotency_key="k", workflow_id="w", step_id="single",
                                     profile=profile, system_content="Resume.",
                                     user_content="El vídeo enseña a generar imágenes.", execution_step="single")
        self.assertIn(WORD_JOINER, request["content"]["prompt"])
        semantic = PromptsMixin.broker_json_request(request_id="j", prompt="nota: generar imágenes",
                                                    schema={"type": "object"})
        self.assertIn(WORD_JOINER, semantic["content"]["prompt"])
        cleaned = resultado_de({"assistant_content": "Sirve para generar i" + WORD_JOINER + "mágenes."})
        self.assertNotIn(WORD_JOINER, cleaned["assistant_content"])


class StorageWarningTests(unittest.TestCase):
    """La base operativa en una carpeta sincronizada daba «disk I/O error» en la instalación real."""

    def test_synced_data_root_is_flagged_and_local_is_not(self) -> None:
        from knowledge_orchestrator.services.path_settings import storage_warnings

        synced = PipelinePaths.under(Path("Y:/Mi unidad/Vaults/Conocimiento/.knowledge-orchestrator"))
        self.assertTrue(storage_warnings(synced))
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(storage_warnings(PipelinePaths.under(Path(folder))), [])


class LocationValidationTests(unittest.TestCase):
    """H13: la configuración no admite ubicaciones que las operaciones no soportan."""

    def test_overlapping_locations_are_refused(self) -> None:
        from knowledge_orchestrator.services.path_settings import PipelinePathStore

        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            store = PipelinePathStore(base / "paths.json")
            for data_root, inbox, vault in (
                (base / "datos", base / "vault" / "inbox", base / "vault"),
                (base / "datos", base / "misma", base / "misma"),
                (base / "datos", base / "datos" / "inbox", base / "vault"),
                (base / "datos", base / "inbox", base / "datos" / "vault"),
            ):
                with self.subTest(inbox=inbox, vault=vault), self.assertRaises(ValueError):
                    store.save(data_root, inbox, vault)
            self.assertFalse((base / "paths.json").exists())
            # La raíz de datos dentro de la bóveda (p. ej. `.knowledge-orchestrator`) sí es válida.
            saved = store.save(base / "vault" / ".ko", base / "inbox", base / "vault")
            self.assertEqual(saved.obsidian_vault, (base / "vault").resolve())
            self.assertEqual(list((base / "vault").glob(".ko-probe-*")), [])


class ExternalEditResolutionTests(AuditBase):
    """H14: una edición o un traslado en Obsidian se resuelven desde la aplicación."""

    def claims_payload(self):
        return {"claims": [{"note_segment": "N1", "source_segments": ["S1"], "claim_type": "HECHO",
                            "volatility": "LOW", "entities": ["cartera"]}]}

    def test_adopting_an_obsidian_edit_versions_it_retires_old_claims_and_reanalyzes(self) -> None:
        note = self.publish("editada", STUDY_NOTE)
        service = self.runtime.semantic_maintenance
        service.ingest_extraction(note.note_id, self.claims_payload())
        edited = note.vault_path.read_text(encoding="utf-8") + "\n- Añadido a mano en Obsidian.\n"
        note.vault_path.write_text(edited, encoding="utf-8")
        self.runtime.knowledge.reconcile()
        resolver = self.runtime.note_reconciliation
        [issue] = resolver.issues()
        self.assertEqual(issue["state"], "CONFLICT")
        text, digest = resolver.current_text(note.note_id)
        self.assertIn("Añadido a mano", text)
        with self.assertRaises(ValueError):
            resolver.adopt_external_version(note.note_id, "0" * 64)
        job_id = resolver.adopt_external_version(note.note_id, digest)
        self.assertEqual(note.vault_path.read_text(encoding="utf-8"), edited)  # nunca se sobrescribe
        self.assertEqual(resolver.issues(), [])
        self.assertEqual(self.runtime.semantic_repository.list_claims(note.note_id, status="ACTIVE"), [])
        self.assertEqual(self.runtime.semantic_repository.get_job(job_id).status, "READY")
        request = json.loads(self.runtime.semantic_repository.get_job(job_id).request_json)
        self.assertIn("Añadido a mano", request["content"]["prompt"])

    def test_moved_note_is_relocated_and_retire_keeps_the_file(self) -> None:
        note = self.publish("movida", STUDY_NOTE)
        moved = note.vault_path.with_name("otro nombre.md")
        note.vault_path.rename(moved)
        self.runtime.knowledge.reconcile()
        resolver = self.runtime.note_reconciliation
        self.assertEqual(resolver.issues()[0]["state"], "MISSING")
        self.assertEqual(resolver.relocate(note.note_id, moved), "IN_SYNC")
        self.runtime.knowledge.reconcile()
        self.assertEqual(resolver.issues(), [])
        resolver.retire(note.note_id)
        self.assertTrue(moved.exists())
        self.assertEqual(self.runtime.publication_repository.get_note(note.note_id).status, "RETIRED")


class SegmentationDriftTests(AuditBase):
    """Si la numeración N#/S# cambia entre envío y respuesta, no se mezclan frases."""

    def test_answer_for_a_different_numbering_is_rejected(self) -> None:
        note = self.publish("deriva", STUDY_NOTE)
        repository = self.runtime.semantic_repository
        job = repository.list_dispatchable_jobs()[0]
        request = json.loads(job.request_json)
        self.assertTrue(request["content"]["metadata"]["segments_sha"])
        payload = {"claims": [{"note_segment": "N1", "source_segments": [], "claim_type": "HECHO",
                               "volatility": "LOW", "entities": []}]}
        with self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.ingest_extraction(note.note_id, payload, expected_segments="otra")
        self.runtime.semantic_maintenance.process_job_result(job, json.dumps(payload))
        self.assertEqual(len(repository.list_claims(note.note_id)), 1)


class ComparisonRetryTests(AuditBase):
    """Una comparación fallida no deja la propuesta atascada para siempre."""

    def test_failed_comparison_gets_a_new_attempt_and_ignores_text_on_supports(self) -> None:
        old = self.publish("comp_vieja", "# Estado\n\nLa versión estable de Producto X es 1.0.\n")
        new = self.publish("comp_nueva", "# Estado\n\nLa versión estable de Producto X es 2.0.\n")
        service, repository = self.runtime.semantic_maintenance, self.runtime.semantic_repository
        payload = {"claims": [{"note_segment": "N1", "source_segments": ["S1"], "claim_type": "VERSION",
                               "volatility": "HIGH", "entities": ["Producto X"]}]}
        service.ingest_extraction(old.note_id, payload)
        [candidate_id] = service.ingest_extraction(new.note_id, payload)
        first = service.schedule_comparison(candidate_id)
        repository.claim_job(first)
        repository.fail_job(first, "SEMANTIC_CONTRACT_FAILED", "roto")
        second = service.retry_comparison(candidate_id)
        self.assertNotEqual(first, second)
        self.assertEqual(service.retry_comparison(candidate_id), second)
        decision = service._parse_comparison({"relation": "SUPPORTS", "confidence": 0.9, "impact": "LOW",
                                              "rationale": "Coinciden.", "replacement_text": "null"})
        self.assertIsNone(decision.replacement_text)
