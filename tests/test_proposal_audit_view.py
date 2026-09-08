from __future__ import annotations

import json
import queue
import threading
import time
import unittest
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

from knowledge_orchestrator.services.proposal_audit import ProposalAuditReader
from knowledge_orchestrator.ui.dashboard.operaciones import OperacionesMixin
from knowledge_orchestrator.ui.dashboard.revision import RevisionMixin
from knowledge_orchestrator.ui.proposal_audit_dialog import ProposalAuditDialog
from knowledge_orchestrator.ui.proposal_audit_presenter import audit_text
from tests import test_maintenance_reversion as reversion
from tests import test_phase_six_semantic_maintenance as phase_six


class ProposalAuditViewTests(unittest.TestCase):
    setUp = reversion.MaintenanceReversionTests.setUp
    tearDown = reversion.MaintenanceReversionTests.tearDown
    prepared = reversion.MaintenanceReversionTests.prepared
    publish_monitored = reversion.MaintenanceReversionTests.publish_monitored
    extraction = staticmethod(reversion.MaintenanceReversionTests.extraction)
    publish = reversion.MaintenanceReversionTests.publish
    prepare_candidate = phase_six.PhaseSixSemanticMaintenanceTests.prepare_candidate
    applied = reversion.MaintenanceReversionTests.applied
    authorize = reversion.MaintenanceReversionTests.authorize
    simulation = reversion.MaintenanceReversionTests.simulation
    queue = reversion.MaintenanceReversionTests.queue
    preview = reversion.MaintenanceReversionTests.preview
    confirm = reversion.MaintenanceReversionTests.confirm
    decision = staticmethod(reversion.MaintenanceReversionTests.decision)

    def controller(self, candidate_id):
        value = SimpleNamespace(reader=ProposalAuditReader(self.runtime.database), candidate_id=candidate_id,
            busy=False, closed=False, record=None, pending=(0, None), results=queue.SimpleQueue(),
            status=Mock(), choice=Mock(), previous=Mock(), next=Mock(), retry=Mock(),
            before=Mock(), proposed=Mock(), evidence=Mock(), decision=Mock(), after=Mock(return_value='timer'))
        for name in ('_actions', '_load', '_choose', '_page', '_poll'):
            setattr(value, name, MethodType(getattr(ProposalAuditDialog, name), value))
        value._label = ProposalAuditDialog._label
        return value

    def settle(self, controller):
        deadline = time.monotonic() + 5
        while controller.busy and time.monotonic() < deadline:
            controller._poll()
            time.sleep(0.005)
        self.assertFalse(controller.busy)

    def test_reader_separates_selected_historical_revision_from_current_decision_without_mutations(self):
        old, new, candidate, _, _, _ = self.prepared()
        service = self.runtime.semantic_maintenance
        original = old.vault_path.read_bytes()
        first = service.proposal_detail(candidate.candidate_id)['assessment']
        quote = self.runtime.semantic_repository.list_claims(new.note_id)[0].statement
        service.edit(candidate.candidate_id, {**self.decision(quote), 'rationale': 'Nueva justificación'},
                     expected_revision=1, actor='human:editor')
        reader = ProposalAuditReader(self.runtime.database)
        result = reader.read(candidate.candidate_id, revision=1)
        text = audit_text(result)
        self.assertEqual(result['snapshot'], first)
        self.assertIn('Mostrando revisión 1', text['summary'])
        self.assertIn('Revisión actual de propuesta: 2', text['decision'])
        self.assertNotIn('Nueva justificación', text['evidence'])
        self.assertIn('Fuente vigilada', text['evidence'])
        self.assertIn('No consta una intención', text['decision'])
        self.assertEqual(old.vault_path.read_bytes(), original)
        self.assertNotIn('request_json', json.dumps(result))
        with self.assertRaises(ValueError):
            reader.read(candidate.candidate_id, revision=99)
        with self.assertRaises(LookupError):
            reader.read(99999)

    def test_revision_pages_are_bounded_and_new_revisions_relocate_without_replacing_selection(self):
        _, _, candidate, _, _, _ = self.prepared()
        with self.runtime.database.transaction() as connection:
            # Historical metadata fixture; snapshots are inserted, never rewritten.
            for revision in range(2, 103):
                connection.execute('INSERT INTO maintenance_proposal_versions '
                    '(candidate_id,revision,snapshot_json,actor) VALUES (?,?,?,?)',
                    (candidate.candidate_id, revision, '{}', 'fixture:history'))
        reader = ProposalAuditReader(self.runtime.database)
        latest = reader.read(candidate.candidate_id)
        oldest = reader.read(candidate.candidate_id, offset=100)
        self.assertEqual((len(latest['versions']), latest['total']), (100, 102))
        self.assertEqual([version['revision'] for version in oldest['versions']], [2, 1])
        self.assertEqual(oldest['selected']['revision'], 2)
        self.assertEqual(reader.read(candidate.candidate_id, offset=1000)['offset'], 100)
        self.assertEqual(reader.read(candidate.candidate_id, offset=100, revision=102)['offset'], 0)
        boundary = reader.read(candidate.candidate_id, revision=3)
        self.assertEqual(boundary['offset'], 0)
        with self.runtime.database.transaction() as connection:
            connection.execute('INSERT INTO maintenance_proposal_versions '
                '(candidate_id,revision,snapshot_json,actor) VALUES (?,103,?,?)',
                (candidate.candidate_id, '{}', 'fixture:concurrent'))
        relocated = reader.read(candidate.candidate_id, offset=boundary['offset'], revision=3)
        self.assertEqual((relocated['offset'], relocated['selected']['revision']), (100, 3))

    def test_execution_simulation_and_human_authorization_simulation_remain_distinct(self):
        _, _, candidate, repo, policy, _ = self.prepared()
        governance = self.runtime.automation_governance
        reviewed = governance.simulate(policy['policy_id'], expected_revision=1, actor='ui', key='audit-authorize')
        policy = governance.set_enabled(policy['policy_id'], True, expected_revision=1, expected_state_revision=1,
            actor='ui', reason='Revisión humana', reviewed_simulation_id=reviewed['simulation_id'])
        repo.set_paused(False, expected_revision=1, actor='ui', reason='Reanudar fixture')
        run = self.queue(repo, policy, candidate)
        self.runtime.automation_execution.run_next()
        self.assertNotEqual(run['simulation_id'], reviewed['simulation_id'])
        record = ProposalAuditReader(self.runtime.database).read(candidate.candidate_id)
        self.assertEqual(record['policy']['reviewed_simulation_id'], reviewed['simulation_id'])
        text = audit_text(record)['decision']
        self.assertIn('Simulación de ejecución: ' + run['simulation_id'], text)
        self.assertIn('Simulación revisada al autorizar: ' + reviewed['simulation_id'], text)

    def test_policy_publication_and_reversion_are_visible_without_claiming_current_vigency(self):
        _, _, candidate, _, run = self.applied()
        reader = ProposalAuditReader(self.runtime.database)
        before = reader.read(candidate.candidate_id)
        self.assertEqual(before['policy']['run_id'], run['run_id'])
        self.assertIsNotNone(before['previous_note'])
        self.assertIn('Política que autorizó la intención', audit_text(before)['decision'])
        self.confirm(self.preview(candidate))
        after = reader.read(candidate.candidate_id)
        self.assertEqual(after['candidate']['status'], 'APPLIED')
        self.assertIn('Esta publicación fue revertida', audit_text(after)['decision'])
        self.assertIn('no autoriza cambios ni acredita vigencia actual', audit_text(after)['summary'])

    def test_legacy_without_snapshot_explains_missing_evidence_instead_of_inventing_analysis(self):
        _, _, candidate_id, _, _ = self.prepare_candidate()
        value = ProposalAuditReader(self.runtime.database).read(candidate_id)
        texts = audit_text(value)
        self.assertEqual(value['versions'], [])
        self.assertIsNone(value['selected'])
        self.assertIn('Sin evaluación versionada', texts['summary'])
        self.assertIn('No se infiere un modelo', texts['evidence'])

    def test_failed_revision_read_preserves_caption_content_and_retries_exact_selection_off_ui_thread(self):
        _, new, candidate, _, _, _ = self.prepared()
        self.runtime.semantic_maintenance.edit(candidate.candidate_id,
            self.decision(self.runtime.semantic_repository.list_claims(new.note_id)[0].statement),
            expected_revision=1, actor='human:editor')
        controller = self.controller(candidate.candidate_id)
        controller._load(0, None)
        self.settle(controller)
        original = controller.record
        main = threading.get_ident()
        calls = []
        def unavailable(*args, **kwargs):
            calls.append((threading.get_ident(), args, kwargs))
            raise OSError('private-storage-error')
        controller.choice.current.return_value = 1
        with patch.object(controller.reader, 'read', side_effect=unavailable):
            controller._choose()
            self.settle(controller)
        self.assertIs(controller.record, original)
        controller.choice.set.assert_called_with(controller._label(original['selected']))
        self.assertEqual(controller.pending, (0, 1))
        self.assertNotEqual(calls[0][0], main)
        self.assertNotIn('private-storage-error', controller.status.set.call_args.args[0])
        controller._load(*controller.pending)
        self.settle(controller)
        self.assertEqual(controller.record['selected']['revision'], 1)

    def test_closed_dialog_does_not_render_late_result_and_busy_selection_cannot_start_another_read(self):
        _, _, candidate, _, _, _ = self.prepared()
        controller = self.controller(candidate.candidate_id)
        controller.busy = True
        with patch.object(controller.reader, 'read') as read:
            controller._load(100, 1)
        read.assert_not_called()
        controller.closed = True
        controller.results.put(({'private': 'late'}, None))
        controller._poll()
        controller.before.insert.assert_not_called()
        controller.after.assert_not_called()

    def test_navigation_captures_proposal_identity_from_review_and_history_only(self):
        dashboard = SimpleNamespace(_selected_review=SimpleNamespace(candidate_id=17), _open_proposal_audit=Mock(),
                                    _flow_kind='history', _flow_item=lambda: {'id': 18})
        RevisionMixin._audit_selected_review(dashboard)
        dashboard._open_proposal_audit.assert_called_once_with(17)
        OperacionesMixin._audit_flow_proposal(dashboard)
        dashboard._open_proposal_audit.assert_called_with(18)
        dashboard._flow_kind = 'activity'
        OperacionesMixin._audit_flow_proposal(dashboard)
        self.assertEqual(dashboard._open_proposal_audit.call_count, 2)
