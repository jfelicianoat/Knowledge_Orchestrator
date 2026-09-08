from __future__ import annotations

import time
import tkinter as tk
import unittest

from knowledge_orchestrator.ui.dashboard import OrchestratorDashboard
from knowledge_orchestrator.ui.operations_snapshots import OperationsSnapshots
from tests import test_phase_six_semantic_maintenance as phase_six
from tests import test_phase_twelve_knowledge_maintenance as phase_twelve


class PhaseThirteenOperationsUiTests(unittest.TestCase):
    setUp = phase_six.PhaseSixSemanticMaintenanceTests.setUp
    tearDown = phase_six.PhaseSixSemanticMaintenanceTests.tearDown
    publish = phase_six.PhaseSixSemanticMaintenanceTests.publish
    extraction = staticmethod(phase_six.PhaseSixSemanticMaintenanceTests.extraction)
    prepare_candidate = phase_six.PhaseSixSemanticMaintenanceTests.prepare_candidate
    publish_monitored = phase_twelve.PhaseTwelveKnowledgeMaintenanceTests.publish_monitored

    def test_empty_snapshot_and_filter_validation(self):
        snapshots = OperationsSnapshots(self.runtime.database)
        self.assertEqual(snapshots.knowledge()['items'], [])
        self.assertEqual(snapshots.counts(), dict.fromkeys(
            ['current', 'historical', 'review', 'sources', 'changes', 'analysis', 'proposals',
             'applied', 'contradictions', 'source_errors'], 0))
        with self.assertRaises(ValueError):
            snapshots.knowledge(state='incorrect')
        with self.assertRaises(ValueError):
            snapshots.knowledge(offset=-1)

    def test_explorer_uses_same_current_and_history_as_knowledge_core(self):
        _, _, candidate_id, old_text, new_text = self.prepare_candidate()
        service = self.runtime.semantic_maintenance
        service.compare(candidate_id, phase_twelve.PhaseTwelveKnowledgeMaintenanceTests.decision(new_text))
        applied = service.approve(candidate_id)
        snapshots = OperationsSnapshots(self.runtime.database)
        current = snapshots.knowledge(query='Producto X')
        self.assertEqual({c['claim_id'] for c in current['items']},
                         {c.claim_id for c in self.runtime.knowledge.repository.claims()})
        self.assertEqual(current['total'], 2)
        historical = snapshots.knowledge(state='historical')
        self.assertEqual(historical['items'][0]['statement'], old_text)
        self.assertEqual(historical['items'][0]['superseded_by'], applied.applied_successor_id)
        self.assertFalse(historical['items'][0]['available_current'])
        first = snapshots.knowledge(state='all', limit=1)
        second = snapshots.knowledge(state='all', limit=1, offset=1)
        self.assertEqual(first['total'], 3)
        self.assertNotEqual(first['items'][0]['claim_id'], second['items'][0]['claim_id'])
        self.assertEqual(snapshots.knowledge(query='entidad inexistente')['total'], 0)
        self.assertEqual(snapshots.counts()['applied'], 1)

    def test_disputed_claims_are_findable_without_presenting_them_as_current(self):
        _, _, candidate_id, _, new_text = self.prepare_candidate()
        self.runtime.semantic_maintenance.compare(candidate_id, {
            **phase_twelve.PhaseTwelveKnowledgeMaintenanceTests.decision(new_text), 'relation': 'CONTRADICTS'})
        snapshots = OperationsSnapshots(self.runtime.database)
        self.assertEqual(snapshots.knowledge()['total'], 0)
        self.assertEqual(snapshots.knowledge(state='review')['total'], 2)
        self.assertEqual(snapshots.counts()['contradictions'], 1)
        self.assertEqual(snapshots.counts()['review'], 2)

    def test_widgets_filter_evidence_and_clear_hidden_selection(self):
        try:
            probe = tk.Tk()
        except tk.TclError as error:
            if "Can't find a usable init.tcl" in str(error) or 'no display name' in str(error):
                self.skipTest('Tcl/Tk no disponible; checkpoint visual pendiente')
            raise
        probe.destroy()
        _, _, candidate_id, old_text, new_text = self.prepare_candidate()
        self.runtime.semantic_maintenance.compare(candidate_id,
                            phase_twelve.PhaseTwelveKnowledgeMaintenanceTests.decision(new_text))
        self.runtime.semantic_maintenance.approve(candidate_id)
        window = OrchestratorDashboard(self.runtime)
        window.withdraw()
        self.addCleanup(window.destroy)
        window._show_page('knowledge')
        self.settle(window)
        self.assertEqual(len(window.knowledge_tree.get_children()), 2)
        window.knowledge_tree.selection_set(window.knowledge_tree.get_children()[0])
        window._select_knowledge()
        self.assertIn(new_text, window.knowledge_detail.get('1.0', 'end'))
        window.knowledge_state.set('Histórico')
        window._reset_knowledge()
        self.settle(window)
        self.assertEqual(window.knowledge_tree.selection(), ())
        self.assertIn('Selecciona', window.knowledge_detail.get('1.0', 'end'))
        window.knowledge_tree.selection_set(window.knowledge_tree.get_children()[0])
        window._select_knowledge()
        self.assertIn(old_text, window.knowledge_detail.get('1.0', 'end'))
        self.assertIn(new_text, window.knowledge_detail.get('1.0', 'end'))
        window._open_flow('history', scope='all')
        window.flow_tree.selection_set(str(candidate_id))
        window._select_flow()
        window._show_flow_revision()
        historical_text = window.flow_detail.get('1.0', 'end')
        self.assertIn('Versión anterior conservada', historical_text)
        window._refresh_flow()
        self.assertEqual(window.flow_detail.get('1.0', 'end'), historical_text)
        window.geometry('1080x680')
        window.deiconify()
        window._audit_flow_proposal()
        from knowledge_orchestrator.ui.proposal_audit_dialog import ProposalAuditDialog
        audit = next(child for child in window.winfo_children() if isinstance(child, ProposalAuditDialog))
        deadline = time.monotonic() + 5
        while audit.busy and time.monotonic() < deadline:
            window.update()
            time.sleep(0.01)
        self.assertFalse(audit.busy)
        self.assertEqual(audit.record['candidate']['candidate_id'], candidate_id)
        self.assertIn(old_text, audit.before.get('1.0', 'end'))
        self.assertIn(new_text, audit.proposed.get('1.0', 'end'))
        self.assertIn('Versión anterior de nota conservada', audit.decision.get('1.0', 'end'))
        self.assertGreater(audit.before.winfo_height(), 100)
        audit.destroy()
        window.search_var.set('Búsqueda que excluye el documento')
        window._work_items = {}
        window._open_flow_item()
        self.assertEqual(window._current_page, 'work')
        self.assertEqual(window.search_var.get(), '')
        window._show_page('services')
        deadline = time.monotonic() + 5
        while window._services_busy and time.monotonic() < deadline:
            window.update()
            time.sleep(0.01)
        self.assertFalse(window._services_busy)
        self.assertIn('Detenida', window.api_status_var.get())
        self.assertIn('Autoaprobación por políticas · Desactivada', window.automation_detail.get('1.0', 'end'))
        self.assertIn('Lotes confirmados por personas', window.automation_detail.get('1.0', 'end'))
        target_capture = window._flow_item()['capture_id']
        self.assertEqual(window._selected_work_id, target_capture)

    def test_refresh_reconciles_external_edits_and_clamps_pagination(self):
        old, _, _, _, _ = self.prepare_candidate()
        snapshots = OperationsSnapshots(self.runtime.database)
        old.vault_path.write_text('Edición externa', encoding='utf-8')
        snapshot = snapshots.refresh_knowledge(offset=100)
        self.assertEqual(snapshot['total'], 1)
        self.assertEqual(snapshot['offset'], 0)
        self.assertNotEqual(snapshot['items'][0]['note_id'], old.note_id)
        self.assertEqual(snapshots.refresh_counts()['current'], 1)

    def test_flow_empty_stages_and_invalid_filter(self):
        snapshots = OperationsSnapshots(self.runtime.database)
        for kind in ('changes', 'analysis', 'proposals', 'history', 'activity'):
            for scope in ('pending', 'errors', 'all'):
                with self.subTest(kind=kind, scope=scope):
                    result = snapshots.flow(kind, scope=scope)
                    self.assertIsInstance(result['items'], list)
                    self.assertEqual(result['offset'], 0)
        with self.assertRaises(ValueError):
            snapshots.flow('missing')
        with self.assertRaises(ValueError):
            snapshots.flow('analysis', scope='missing')

    def test_monitored_change_links_to_capture_note_and_proposal(self):
        old_text, new_text = 'Producto X versión 1.', 'Producto X versión 2.'
        old = self.publish_monitored(old_text, trust_level=95, source_role='official_documentation')
        new = self.publish_monitored(new_text, trust_level=95, source_role='official_documentation')
        service = self.runtime.semantic_maintenance
        service.ingest_extraction(old.note_id, self.extraction(old, old_text))
        candidate_id = service.ingest_extraction(new.note_id, self.extraction(new, new_text))[0]
        service.compare(candidate_id, phase_twelve.PhaseTwelveKnowledgeMaintenanceTests.decision(new_text))
        snapshots = OperationsSnapshots(self.runtime.database)
        changes = snapshots.flow('changes', scope='all')
        self.assertEqual(changes['total'], 2)
        row = next(item for item in changes['items'] if item['capture_id'] == new.capture_id)
        flow = snapshots.change_flow(row['id'])
        self.assertEqual(flow['note_ids'], [new.note_id])
        self.assertEqual(flow['candidate_ids'], [candidate_id])
        self.assertIsNotNone(flow['capture_status'])
        self.assertEqual(snapshots.flow('changes')['total'], 0)
        self.assertEqual(snapshots.flow('proposals')['items'][0]['id'], candidate_id)
        self.assertEqual(snapshots.flow('history')['total'], 0)
        before = old.vault_path.read_text(encoding='utf-8')
        service.approve(candidate_id)
        resolved = snapshots.flow('history', scope='all')['items'][0]
        self.assertEqual(resolved['id'], candidate_id)
        self.assertEqual(resolved['status'], 'APPLIED')
        self.assertEqual(self.runtime.semantic_repository.revision_content(resolved['id']), before)
        for record in snapshots.flow('analysis', scope='all')['items']:
            self.assertNotIn('request_json', record)
            self.assertNotIn('result_json', record)
        for record in snapshots.flow('activity')['items']:
            self.assertNotIn('details_json', record)

    def test_flow_incidents_and_pagination_are_not_hidden_by_success(self):
        _, _, candidate_id, _, new_text = self.prepare_candidate()
        service = self.runtime.semantic_maintenance
        snapshots = OperationsSnapshots(self.runtime.database)
        self.assertEqual(snapshots.counts()['proposals'], snapshots.flow('proposals')['total'])
        service.compare(candidate_id, phase_twelve.PhaseTwelveKnowledgeMaintenanceTests.decision(new_text))
        with self.runtime.database.transaction() as connection:
            connection.execute("UPDATE semantic_jobs SET status='ERROR',error_code='BROKER_OFFLINE'")
        self.runtime.semantic_repository.mark_candidate(candidate_id, 'CONFLICT', reason='NOTE_CHANGED_AFTER_DIFF')
        snapshots = OperationsSnapshots(self.runtime.database)
        self.assertEqual(snapshots.flow('proposals', scope='errors')['items'][0]['id'], candidate_id)
        self.assertEqual(snapshots.flow('analysis')['total'], 0)
        failed = snapshots.flow('analysis', scope='errors', limit=1, offset=999)
        self.assertEqual(failed['total'], 2)
        self.assertEqual(failed['offset'], 1)
        self.assertEqual(failed['items'][0]['error_code'], 'BROKER_OFFLINE')
        self.assertEqual(snapshots.counts()['proposals'], snapshots.flow('proposals')['total'])
        self.assertEqual(self.runtime.semantic_repository.get_candidate(candidate_id).status, 'CONFLICT')
        from knowledge_orchestrator.ui.snapshots import UiSnapshotService
        reviews = UiSnapshotService(self.runtime.database).reviews()
        self.assertEqual(reviews[0].candidate_id, candidate_id)
        self.assertEqual(reviews[0].status, 'CONFLICT')

    @staticmethod
    def settle(window):
        deadline = time.monotonic() + 5
        while window._knowledge_refreshing and time.monotonic() < deadline:
            window.update()
            time.sleep(0.01)
        if window._knowledge_refreshing:
            raise AssertionError('El explorador no completó su lectura')


if __name__ == '__main__':
    unittest.main()
