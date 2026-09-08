from __future__ import annotations

import unittest
from contextlib import closing
from unittest.mock import patch

from knowledge_orchestrator.domain.automation import AutomationPolicyConfig
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.provenance import source_provenance
from knowledge_orchestrator.services.semantic_maintenance import SemanticContractError
from tests import test_automation_execution as execution


class TemporalAuthorizationTests(unittest.TestCase):
    setUp = execution.AutomationExecutionTests.setUp
    tearDown = execution.AutomationExecutionTests.tearDown
    publish_monitored = execution.AutomationExecutionTests.publish_monitored
    extraction = staticmethod(execution.AutomationExecutionTests.extraction)
    authorize = execution.AutomationExecutionTests.authorize

    def dated_note(self, text, source_date, observed_at):
        note = self.publish_monitored(text, trust_level=95, source_role="official_documentation")
        payload = self.extraction(note, text, entities=("Producto Calendario",), source_date=source_date)
        payload["claims"][0]["observed_at"] = observed_at
        candidates = self.runtime.semantic_maintenance.ingest_extraction(note.note_id, payload)
        return note, candidates

    def policy_for(self, note):
        source_id = source_provenance(self.runtime.database, note.capture_id)["monitoring"]["monitored_source_id"]
        repo = self.runtime.automation_policies
        policy = repo.create(AutomationPolicyConfig("Versiones con evidencia", (source_id,)),
                             actor="human:test", key="temporal-policy")
        return self.authorize(repo, policy)

    def snapshot(self):
        repo = self.runtime.semantic_repository
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            history = [tuple(row) for row in connection.execute(
                "SELECT * FROM claim_state_history ORDER BY history_id")]
        return {
            "notes": {note.note_id: note.vault_path.read_bytes()
                      for note in self.runtime.publication_repository.list_notes_by_status("PUBLISHED")},
            "claims": repo.list_claims(), "candidates": repo.list_candidates(), "history": history,
        }

    def assert_no_publication(self, before):
        self.assertEqual(self.snapshot(), before)
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            for table in ("note_revisions", "automation_runs", "automation_reservations"):
                self.assertEqual(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0], 0, table)

    def advance_and_restart(self):
        # Future scheduling dates must not manufacture evidence or an application.
        clock_path = "knowledge_orchestrator.repositories.automation_schedule_repository.time.time"
        for index, now in enumerate((4102444800.0, 4102444861.0, 4102444922.0)):
            if index == 1:
                self.runtime = build_runtime(self.runtime.paths)
                self.runtime.recover_once(ingest_inbox=False)
            with patch(clock_path, return_value=now):
                self.assertTrue(self.runtime.automation_scheduler.tick())
        self.assertFalse(self.runtime.broker_worker.running)

    def test_elapsed_date_without_new_evidence_never_creates_proposal_or_publication(self):
        text = "La versión de Producto Calendario tiene soporte hasta 2000-12-31."
        note, candidates = self.dated_note(text, "1999-01-01", "1999-01-02T10:00:00Z")
        self.assertEqual(candidates, [])
        self.policy_for(note)
        before = self.snapshot()
        self.advance_and_restart()
        self.assert_no_publication(before)
        claim = self.runtime.semantic_repository.list_claims()[0]
        self.assertEqual(claim.source_date, "1999-01-01")
        self.assertEqual(claim.knowledge_state, "CURRENT")
        self.assertIsNone(claim.superseded_by)
        self.assertEqual(self.runtime.knowledge_access.claim(claim.claim_id)["verification"],
                         "evidence_linked_not_independently_verified")

    def test_new_observation_date_with_same_statement_does_not_authorize_replacement(self):
        text = "La versión de Producto Calendario tiene soporte hasta 2000-12-31."
        self.dated_note(text, "1999-01-01", "1999-01-02T10:00:00Z")
        new, candidates = self.dated_note(text, "2026-01-01", "2026-01-02T10:00:00Z")
        self.assertEqual(len(candidates), 1)
        candidate = self.runtime.semantic_maintenance.compare(candidates[0], {
            "relation": "SUPPORTS", "confidence": 1.0, "impact": "LOW",
            "rationale": "La observación es posterior pero conserva la misma afirmación.", "replacement_text": None,
        })
        policy = self.policy_for(new)
        simulation = self.runtime.automation_simulation.simulate(
            policy["policy_id"], expected_revision=policy["revision"], actor="human:test",
            selection=[{"candidate_id": candidate.candidate_id, "expected_revision": candidate.proposal_revision}],
        )
        self.assertEqual(simulation["plan"]["counts"]["eligible"], 0)
        self.assertIsNone(candidate.patch_json)
        before = self.snapshot()
        self.advance_and_restart()
        self.assert_no_publication(before)

    def test_elapsed_date_cannot_justify_unquoted_model_replacement_even_with_approved_policy(self):
        text = "La versión de Producto Calendario tiene soporte hasta 2000-12-31."
        self.dated_note(text, "1999-01-01", "1999-01-02T10:00:00Z")
        new, candidates = self.dated_note(text, "2026-01-01", "2026-01-02T10:00:00Z")
        self.assertEqual(len(candidates), 1)
        policy = self.policy_for(new)
        before = self.snapshot()
        with self.assertRaisesRegex(SemanticContractError, "evidencia nueva"):
            self.runtime.semantic_maintenance.compare(candidates[0], {
                "relation": "SUPERSEDES", "confidence": 1.0, "impact": "HIGH",
                "rationale": "La fecha ya pasó; deduzco que el producto ya no tiene soporte.",
                "replacement_text": "Producto Calendario ya no tiene soporte.",
            })
        simulation = self.runtime.automation_simulation.simulate(
            policy["policy_id"], expected_revision=policy["revision"], actor="human:test",
            selection=[{"candidate_id": candidates[0], "expected_revision": 0}],
        )
        self.assertEqual(simulation["plan"]["counts"]["eligible"], 0)
        self.advance_and_restart()
        self.assert_no_publication(before)
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM maintenance_proposal_versions").fetchone()[0], 0)
