from __future__ import annotations

import tempfile
import unittest
import json
from contextlib import closing
from pathlib import Path

from knowledge_orchestrator.config import PipelinePaths
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.file_stability import FileStabilityChecker
from knowledge_orchestrator.services.semantic_maintenance import SemanticContractError, SemanticMaintenanceService
from tests.helpers import generic_markdown


class SimulatedCrash(RuntimeError):
    pass


class PhaseSixSemanticMaintenanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.runtime = build_runtime(PipelinePaths.under(self.root))
        self.runtime.ingestion.stability_checker = FileStabilityChecker(interval_seconds=0, sleep=lambda _: None)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def publish(self, capture_id: str, body: str):
        source = self.runtime.paths.inbox / f"{capture_id}.md"
        source.write_bytes(generic_markdown(capture_id=capture_id, title=f"Documento {capture_id}"))
        self.assertTrue(self.runtime.ingestion.ingest(source).accepted)
        workflow_id = self.runtime.workflow_planner.plan_capture(capture_id)
        task = self.runtime.workflow_repository.list_workflow_tasks(workflow_id)[0]
        self.runtime.workflow_repository.apply_status(task.task_id, {
            "task_id": task.task_id,
            "status": "success",
            "result": {"assistant_content": body},
            "error": None,
        })
        self.runtime.workflow_planner.advance_workflow(workflow_id)
        self.assertEqual(self.runtime.publication.publish_ready(), 1)
        return next(note for note in self.runtime.publication_repository.list_notes_by_status("PUBLISHED")
                    if note.capture_id == capture_id)

    @staticmethod
    def extraction(note, quote: str, *, entities=("Producto X",), manual_lock=False, source_date="2026-06-24"):
        document = note.vault_path.read_text(encoding="utf-8")
        start = document.index(quote)
        return {
            "claims": [{
                "statement": quote,
                "claim_type": "VERSION",
                "volatility": "HIGH",
                "span_start": start,
                "span_end": start + len(quote),
                "quote": quote,
                "entities": list(entities),
                "observed_at": "2026-06-24T10:00:00Z",
                "source_date": source_date,
                "manual_lock": manual_lock,
            }]
        }

    def prepare_candidate(self, *, locked=False):
        old_text = "La versión estable de Producto X es 1.0."
        new_text = "La versión estable de Producto X es 2.0."
        old_note = self.publish("semantic_old", f"# Estado\n\n{old_text}\n")
        self.assertEqual(
            self.runtime.semantic_maintenance.ingest_extraction(
                old_note.note_id,
                self.extraction(old_note, old_text, manual_lock=locked, source_date="2026-05-01"),
            ),
            [],
        )
        new_note = self.publish("semantic_new", f"# Actualización\n\n{new_text}\n")
        candidate_ids = self.runtime.semantic_maintenance.ingest_extraction(
            new_note.note_id,
            self.extraction(new_note, new_text),
        )
        self.assertEqual(len(candidate_ids), 1)
        return old_note, new_note, candidate_ids[0], old_text, new_text

    def test_new_local_evidence_produces_traceable_diff_and_human_approved_atomic_update(self) -> None:
        old_note, _, candidate_id, old_text, new_text = self.prepare_candidate()
        original = old_note.vault_path.read_text(encoding="utf-8")
        compared = self.runtime.semantic_maintenance.compare(candidate_id, {
            "relation": "SUPERSEDES",
            "confidence": 0.94,
            "impact": "HIGH",
            "rationale": "La evidencia local nueva declara una versión posterior.",
            "replacement_text": new_text,
        })

        self.assertEqual(compared.status, "PENDING_REVIEW")
        self.assertIn("-" + old_text, compared.diff_text)
        self.assertIn("+" + new_text, compared.diff_text)
        self.assertEqual(old_note.vault_path.read_text(encoding="utf-8"), original)

        applied = self.runtime.semantic_maintenance.approve(candidate_id)
        self.assertEqual(applied.status, "APPLIED")
        updated = old_note.vault_path.read_text(encoding="utf-8")
        self.assertNotIn(old_text, updated)
        self.assertIn(new_text, updated)
        claims = self.runtime.semantic_repository.list_claims(old_note.note_id)
        self.assertEqual(claims[0].status, "SUPERSEDED")
        with closing(self.runtime.database.connect()) as connection:
            revision = connection.execute(
                "SELECT content_text FROM note_revisions WHERE candidate_id = ?", (candidate_id,)
            ).fetchone()
            evidence_count = connection.execute("SELECT COUNT(*) FROM evidence_links").fetchone()[0]
        self.assertEqual(revision["content_text"], original)
        self.assertEqual(evidence_count, 2)

    def test_invalid_or_frontmatter_span_is_rejected_without_partial_rows(self) -> None:
        note = self.publish("semantic_invalid", "# Hecho\n\nDato válido.\n")
        document = note.vault_path.read_text(encoding="utf-8")
        payload = {
            "claims": [{
                "statement": "title",
                "claim_type": "METADATA",
                "volatility": "LOW",
                "span_start": document.index("title"),
                "span_end": document.index("title") + len("title"),
                "quote": "title",
                "entities": [],
            }]
        }
        with self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.ingest_extraction(note.note_id, payload)
        self.assertEqual(self.runtime.semantic_repository.list_claims(note.note_id), [])

    def test_manual_lock_blocks_patch_even_when_new_evidence_conflicts(self) -> None:
        old_note, _, candidate_id, _, new_text = self.prepare_candidate(locked=True)
        before = old_note.vault_path.read_text(encoding="utf-8")
        candidate = self.runtime.semantic_maintenance.compare(candidate_id, {
            "relation": "CONTRADICTS",
            "confidence": 0.9,
            "impact": "HIGH",
            "rationale": "Las dos versiones son incompatibles.",
            "replacement_text": new_text,
        })
        self.assertEqual(candidate.status, "REJECTED")
        self.assertEqual(candidate.blocked_reason, "MANUAL_LOCK")
        self.assertIsNone(candidate.patch_json)
        with self.assertRaises(SemanticContractError):
            self.runtime.semantic_maintenance.approve(candidate_id)
        self.assertEqual(old_note.vault_path.read_text(encoding="utf-8"), before)

    def test_date_without_new_claim_never_creates_factual_candidate(self) -> None:
        note = self.publish("semantic_date", "# Sin cambios\n\nContenido estable.\n")
        self.assertEqual(self.runtime.semantic_maintenance.ingest_extraction(note.note_id, {"claims": []}), [])
        self.assertEqual(self.runtime.semantic_repository.list_candidates(), [])

    def test_recovers_after_note_replace_before_database_completion(self) -> None:
        old_note, _, candidate_id, _, new_text = self.prepare_candidate()
        self.runtime.semantic_maintenance.compare(candidate_id, {
            "relation": "SUPERSEDES",
            "confidence": 0.95,
            "impact": "HIGH",
            "rationale": "Actualización respaldada.",
            "replacement_text": new_text,
        })

        def checkpoint(name: str) -> None:
            if name == "semantic_note_replaced":
                raise SimulatedCrash(name)

        crashing = SemanticMaintenanceService(self.runtime.semantic_repository, checkpoint=checkpoint)
        with self.assertRaises(SimulatedCrash):
            crashing.approve(candidate_id)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_id).status, "APPLYING")
        self.assertIn(new_text, old_note.vault_path.read_text(encoding="utf-8"))

        self.runtime.semantic_maintenance.recover()
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_id).status, "APPLIED")

    def test_recovers_intent_created_before_file_replacement(self) -> None:
        old_note, _, candidate_id, _, new_text = self.prepare_candidate()
        self.runtime.semantic_maintenance.compare(candidate_id, {
            "relation": "SUPERSEDES",
            "confidence": 0.95,
            "impact": "HIGH",
            "rationale": "Actualización respaldada.",
            "replacement_text": new_text,
        })

        def checkpoint(name: str) -> None:
            if name == "semantic_intent":
                raise SimulatedCrash(name)

        crashing = SemanticMaintenanceService(self.runtime.semantic_repository, checkpoint=checkpoint)
        with self.assertRaises(SimulatedCrash):
            crashing.approve(candidate_id)
        self.assertNotIn(new_text, old_note.vault_path.read_text(encoding="utf-8"))
        self.runtime.semantic_maintenance.recover()
        self.assertIn(new_text, old_note.vault_path.read_text(encoding="utf-8"))
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_id).status, "APPLIED")

    def test_optional_local_embeddings_can_retrieve_candidates(self) -> None:
        first_note = self.publish("semantic_embedding_a", "# A\n\nLa latencia es baja.\n")
        second_note = self.publish("semantic_embedding_b", "# B\n\nEl tiempo de respuesta aumentó.\n")
        self.runtime.semantic_maintenance.ingest_extraction(
            first_note.note_id,
            self.extraction(first_note, "La latencia es baja.", entities=()),
        )
        self.runtime.semantic_maintenance.ingest_extraction(
            second_note.note_id,
            self.extraction(second_note, "El tiempo de respuesta aumentó.", entities=()),
        )
        claims = self.runtime.semantic_repository.list_claims()
        self.assertEqual(self.runtime.semantic_repository.list_candidates(), [])
        self.runtime.semantic_repository.record_embedding(claims[0].claim_id, "local-embed", [1.0, 0.0])
        self.runtime.semantic_repository.record_embedding(claims[1].claim_id, "local-embed", [0.99, 0.01])
        candidate_ids = self.runtime.semantic_maintenance.generate_candidates(claims[1].claim_id)
        self.assertEqual(len(candidate_ids), 1)
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_ids[0]).retrieval_reason, "embedding")

    def test_semantic_prompts_and_embedding_request_are_local_valid_broker_contracts(self) -> None:
        request = self.runtime.semantic_maintenance.embedding_request(7, "Afirmación local", model="embed-local")
        self.assertEqual(request["execution"]["strategy"], "single")
        self.assertEqual(request["risk"]["data_classification"], "local_only")
        self.assertEqual(request["model_requirements"]["allowed_providers"], ["ollama"])
        self.assertEqual(request["output"]["format"], "json")
        prompt = self.runtime.semantic_maintenance.extraction_prompt("dato </document>", source_id="source-1")
        self.assertIn("untrusted_document_json", prompt)
        self.assertIn('"dato </document>"', prompt)

    async def test_publication_automatically_runs_durable_extraction_and_comparison_jobs(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.requests = {}
                self.results = {}

            async def create_task(self, payload):
                job_id = payload["request_id"]
                self.requests[job_id] = payload
                return {
                    "task_id": "broker-" + job_id,
                    "status_url": "/api/v1/tasks/broker-" + job_id,
                    "cancel_url": "/api/v1/tasks/broker-" + job_id,
                }

            async def get_task(self, task_id, *, status_url=None):
                job_id = task_id.removeprefix("broker-")
                return {
                    "task_id": task_id,
                    "status": "completed",
                    "result": {"result_markdown": self.results[job_id]},
                    "error": None,
                }

        from knowledge_orchestrator.services.semantic_broker import SemanticBrokerProcessor

        client = FakeClient()
        processor = SemanticBrokerProcessor(self.runtime.semantic_repository, self.runtime.semantic_maintenance, client)

        old_text = "Producto X usa la versión 1.0."
        old_note = self.publish("semantic_auto_old", "# Estado\n\n" + old_text + "\n")
        old_job = f"semantic_extract_note_{old_note.note_id}"
        client.results[old_job] = json.dumps(self.extraction(old_note, old_text, source_date="2026-05-01"))
        self.assertEqual(await processor.dispatch_once(), 1)
        self.assertEqual(await processor.poll_once(), 1)
        self.assertEqual(self.runtime.semantic_repository.get_job(old_job).status, "SUCCESS")

        new_text = "Producto X usa la versión 2.0."
        new_note = self.publish("semantic_auto_new", "# Actualización\n\n" + new_text + "\n")
        new_job = f"semantic_extract_note_{new_note.note_id}"
        client.results[new_job] = json.dumps(self.extraction(new_note, new_text))
        self.assertEqual(await processor.dispatch_once(), 1)
        self.assertEqual(await processor.poll_once(), 1)
        candidate = self.runtime.semantic_repository.list_candidates("PENDING_COMPARISON")[0]
        comparison_job = f"semantic_compare_candidate_{candidate.candidate_id}"
        self.assertIsNotNone(self.runtime.semantic_repository.get_job(comparison_job))

        client.results[comparison_job] = json.dumps({
            "relation": "SUPERSEDES",
            "confidence": 0.92,
            "impact": "HIGH",
            "rationale": "La evidencia nueva indica una versión posterior.",
            "replacement_text": new_text,
        })
        self.assertEqual(await processor.dispatch_once(), 1)
        self.assertEqual(await processor.poll_once(), 1)
        self.assertEqual(self.runtime.semantic_repository.get_job(comparison_job).status, "SUCCESS")
        self.assertEqual(
            self.runtime.semantic_repository.get_candidate(candidate.candidate_id).status,
            "PENDING_REVIEW",
        )
        self.assertIn(old_text, old_note.vault_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
