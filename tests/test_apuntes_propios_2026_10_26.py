"""Apuntes propios: se publican tal cual y sus claims pesan menos (26-oct-2026).

Antes, importar unos apuntes ya hechos los mandaba al Broker para resumirlos
otra vez. Ahora la casilla «Ya son apuntes míos» publica el texto sin tocarlo,
y sus afirmaciones quedan marcadas `claim_origin = OWN_NOTE`: no proponen
cambios en otras notas y bajan en las búsquedas.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import yaml

from knowledge_orchestrator.config import BrokerSettings, PipelinePaths
from knowledge_orchestrator.domain.semantic_models import ExtractedClaim
from knowledge_orchestrator.runtime import build_runtime
from knowledge_orchestrator.services.markdown_import import write_converted

APUNTES = (
    "# Estocástico\n\n"
    "El oscilador estocástico compara el cierre con el rango de 14 sesiones.\n\n"
    "Una lectura por encima de 80 indica sobrecompra.\n"
)


class ApuntesPropiosTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.runtime = build_runtime(
            PipelinePaths.under(root / "datos"), broker_settings=BrokerSettings(base_url="http://127.0.0.1:9"),
        )
        self.outside = root / "descargas"
        self.outside.mkdir()

    def _import(self, name: str, text: str, *, own_notes: bool) -> str:
        source = self.outside / name
        source.write_text(text, encoding="utf-8")
        target = write_converted(source, self.runtime.paths.inbox, own_notes=own_notes)
        result = self.runtime.ingestion.ingest(target)
        self.assertTrue(result.accepted, result)
        return target.stem

    def _publish(self, capture_id: str) -> int:
        self.runtime.workflow_planner.plan_unplanned()
        self.runtime.publication.publish_ready()
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            row = connection.execute("SELECT note_id FROM notes WHERE capture_id = ?", (capture_id,)).fetchone()
        self.assertIsNotNone(row, "la nota no se publicó")
        return int(row["note_id"])

    def test_own_notes_are_published_verbatim_without_broker_tasks(self) -> None:
        capture_id = self._import("apuntes.md", APUNTES, own_notes=True)
        note_id = self._publish(capture_id)

        with closing(self.runtime.database.connect(readonly=True)) as connection:
            tasks = connection.execute("SELECT count(*) FROM tasks WHERE capture_id = ?", (capture_id,)).fetchone()[0]
            plan = connection.execute("SELECT plan_json FROM workflows WHERE capture_id = ?", (capture_id,)).fetchone()
        self.assertEqual(tasks, 0, "un apunte propio no se envía al Broker para resumirlo")
        self.assertEqual(json.loads(plan[0])["strategy"], "own_note")
        note = Path(self.runtime.semantic_repository.note_context(note_id)["vault_path"]).read_text(encoding="utf-8")
        frontmatter, body = note.split("---\n", 2)[1:]
        self.assertEqual(yaml.safe_load(frontmatter)["note_origin"], "own_note")
        self.assertEqual(body.strip(), APUNTES.strip(), "el apunte se publica tal cual")

    def test_ordinary_import_still_goes_to_the_broker(self) -> None:
        capture_id = self._import("articulo.md", APUNTES, own_notes=False)
        self.runtime.workflow_planner.plan_unplanned()
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            tasks = connection.execute("SELECT count(*) FROM tasks WHERE capture_id = ?", (capture_id,)).fetchone()[0]
        self.assertGreater(tasks, 0)

    def test_own_note_claims_are_marked_and_never_rewrite_other_notes(self) -> None:
        note_id = self._publish(self._import("apuntes.md", APUNTES, own_notes=True))
        maintenance = self.runtime.semantic_maintenance
        job = self.runtime.semantic_repository.extraction_jobs(note_id)[-1]
        prompt = json.loads(job.request_json)["content"]["prompt"]
        # La fuente de un apunte propio es él mismo: no se le ofrece al modelo como respaldo.
        self.assertIn("<untrusted_source_segments_json>[]</untrusted_source_segments_json>", prompt)

        created = maintenance.ingest_extraction(note_id, {"claims": [{
            "note_segment": "N2", "source_segments": [], "claim_type": "DEFINICION", "volatility": "LOW",
            "entities": ["estocástico"], "manual_lock": False, "observed_at": None, "source_date": None,
        }]})
        self.assertEqual(created, [], "un apunte propio no propone cambios en otras notas")
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT claim_id FROM knowledge_claims WHERE note_id = ?", (note_id,))]
        self.assertEqual(len(ids), 1)
        self.assertEqual(self.runtime.semantic_repository.get_claim(ids[0]).claim_origin, "OWN_NOTE")
        self.assertEqual(self.runtime.knowledge_access.claim_payload(ids[0])["claim_origin"], "OWN_NOTE")

    def test_own_note_claims_rank_below_documented_ones(self) -> None:
        own = self._publish(self._import("apuntes.md", APUNTES, own_notes=True))
        documented = self._publish_documented("Una lectura por encima de 80 indica sobrecompra en el estocástico.\n")
        for note_id in (own, documented):
            self._add_claim(note_id, "Una lectura por encima de 80 indica sobrecompra")
        found = self.runtime.knowledge_access.search("lectura 80 sobrecompra")
        self.assertEqual([item["claim_origin"] for item in found], ["DOCUMENT", "OWN_NOTE"])

    def _add_claim(self, note_id: int, quote: str) -> int:
        path = Path(self.runtime.semantic_repository.note_context(note_id)["vault_path"])
        start = path.read_text(encoding="utf-8").index(quote)
        return self.runtime.semantic_repository.add_claim(note_id, ExtractedClaim(
            statement=quote, claim_type="CIFRA", volatility="LOW", span_start=start, span_end=start + len(quote),
            quote=quote,
        ), source_path=path).claim_id

    def _publish_documented(self, text: str) -> int:
        """Una nota normal, con su resultado del Broker simulado."""

        capture_id = self._import("documento.md", text, own_notes=False)
        self.runtime.workflow_planner.plan_unplanned()
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            workflow_id = connection.execute(
                "SELECT workflow_id FROM workflows WHERE capture_id = ?", (capture_id,)).fetchone()[0]
        self.runtime.workflow_repository.finish_workflow(workflow_id, text)
        self.runtime.publication.publish_ready()
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            return int(connection.execute("SELECT note_id FROM notes WHERE capture_id = ?",
                                          (capture_id,)).fetchone()[0])

    def test_interrupted_own_note_workflow_is_closed_on_recovery(self) -> None:
        capture_id = self._import("apuntes.md", APUNTES, own_notes=True)
        planner = self.runtime.workflow_planner
        original = self.runtime.workflow_repository.finish_workflow
        self.runtime.workflow_repository.finish_workflow = lambda *_args: None  # type: ignore[method-assign]
        planner.plan_unplanned()
        self.runtime.workflow_repository.finish_workflow = original  # type: ignore[method-assign]
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            workflow_id, status = connection.execute(
                "SELECT workflow_id, status FROM workflows WHERE capture_id = ?", (capture_id,)).fetchone()
        self.assertEqual(status, "PLANNED")
        planner.advance_workflow(workflow_id)
        self.assertEqual(self.runtime.workflow_repository.get_workflow(workflow_id).status.value, "SUCCESS")


if __name__ == "__main__":
    unittest.main()
