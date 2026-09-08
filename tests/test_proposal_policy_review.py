from __future__ import annotations

import copy
import json
import unittest
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from knowledge_orchestrator.api.application import KnowledgeApi
from knowledge_orchestrator.api.auth import ApiAuth
from knowledge_orchestrator.api.response_schemas import SCHEMAS
from knowledge_orchestrator.services.maintenance_assessment import assess_proposal
from knowledge_orchestrator.ui.automation_panel import AutomationPanel
from knowledge_orchestrator.ui.automation_presenter import simulation_matches
from knowledge_orchestrator.ui.dashboard.revision import RevisionMixin
from knowledge_orchestrator.ui.dashboard.servicios import ServiciosMixin
from tests import test_automation_governance_api as governance_api
from tests import test_automation_ui as automation_ui


class ProposalPolicyReviewTests(unittest.TestCase):
    setUp = automation_ui.AutomationUiTests.setUp
    tearDown = automation_ui.AutomationUiTests.tearDown
    publish_monitored = automation_ui.AutomationUiTests.publish_monitored
    extraction = staticmethod(automation_ui.AutomationUiTests.extraction)
    prepared = automation_ui.AutomationUiTests.prepared
    controller = automation_ui.AutomationUiTests.controller
    settle_controller = automation_ui.AutomationUiTests.settle_controller
    assert_contract = governance_api.AutomationGovernanceApiTests.assert_contract

    def test_new_assessment_requires_evaluation_instead_of_claiming_policy_absence(self):
        _, _, candidate, repo, policy, _ = self.prepared()
        repo.set_enabled(policy['policy_id'], True, expected_revision=1, expected_state_revision=1,
                         actor='human:test', reason='Fixture authorization')
        detail = self.runtime.semantic_maintenance.proposal_detail(candidate.candidate_id)
        self.assert_contract(detail, SCHEMAS['ProposalReview'])
        approval = detail['assessment']['autoapproval']
        self.assertFalse(approval['eligible'])
        self.assertFalse(approval['policy_evaluated'])
        self.assertIn('POLICY_EVALUATION_REQUIRED', approval['reasons'])
        self.assertNotIn('NO_APPROVED_POLICY', approval['reasons'])
        self.assertEqual(detail['automation_review']['selection'],
                         [{'candidate_id': candidate.candidate_id, 'expected_revision': 1}])
        evaluation = self.runtime.automation_governance.simulate(policy['policy_id'], expected_revision=1,
            actor='ui', key='proposal-review-evaluation', selection=detail['automation_review']['selection'])
        self.assertTrue(evaluation['plan']['items'][0]['eligible'])
        self.assertIn('AUTOMATION_PAUSED', evaluation['plan']['execution_gates'])
        self.assertFalse(evaluation['plan']['publication_authorized'])
        stored = self.runtime.semantic_repository.get_candidate(candidate.candidate_id)
        self.assertEqual(stored.status, 'PENDING_REVIEW')

    def test_legacy_snapshot_stays_byte_exact_when_api_explains_policy_evaluation(self):
        def legacy(*args, **kwargs):
            assessment = assess_proposal(*args, **kwargs)
            assessment['autoapproval'] = {'eligible': False, 'reasons': ['NO_APPROVED_POLICY']}
            return assessment
        with patch('knowledge_orchestrator.services.semantic_maintenance.assess_proposal', side_effect=legacy):
            _, _, candidate, _, _, _ = self.prepared()
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            before = connection.execute('SELECT snapshot_json FROM maintenance_proposal_versions '
                                         'WHERE candidate_id=?', (candidate.candidate_id,)).fetchone()[0]
        token = 'test-policy-review-token-0000000001'
        auth = ApiAuth([{'name': 'reviewer', 'token': token, 'scopes': ['review', 'read']}])
        with httpx.Client(transport=httpx.WSGITransport(KnowledgeApi(self.runtime, auth)),
                          base_url='http://localhost/api/v1/') as client:
            response = client.get(f'review-tasks/{candidate.candidate_id}',
                                   headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(response.status_code, 200)
        detail = response.json()['review']
        self.assert_contract(detail, SCHEMAS['ProposalReview'])
        self.assertEqual(detail['assessment'], json.loads(before))
        self.assertEqual(detail['automation_review']['status'], 'POLICY_SIMULATION_REQUIRED')
        with closing(self.runtime.database.connect(readonly=True)) as connection:
            rows = connection.execute('SELECT snapshot_json FROM maintenance_proposal_versions '
                                       'WHERE candidate_id=?', (candidate.candidate_id,)).fetchall()
        self.assertEqual([row[0] for row in rows], [before])

    def test_review_bridge_evaluates_only_selected_candidate_and_retains_policy_draft(self):
        old, _, candidate, repo, policy, _ = self.prepared()
        self.prepared(label='Other', key='other-proposal-policy')
        panel = self.controller()
        panel.policy, panel.dirty = policy, True
        original = old.vault_path.read_bytes()
        self.assertTrue(panel.review_candidate(candidate.candidate_id, candidate.proposal_revision))
        self.assertTrue(panel.dirty)
        panel.form.set_config.assert_not_called()
        panel._simulate()
        self.assertFalse(panel.busy)
        panel.dirty = False
        panel._simulate()
        self.settle_controller(panel)
        self.assertEqual([item['candidate_id'] for item in panel.simulation['plan']['items']], [candidate.candidate_id])
        self.assertTrue(panel.simulation['plan']['items'][0]['eligible'])
        self.assertFalse(repo.get(policy['policy_id'])['enabled'])
        self.assertEqual(old.vault_path.read_bytes(), original)
        panel._simulate_next()  # Explicitly remove the proposal filter, without running another simulation.
        self.assertIsNone(panel.review_selection)
        self.assertIsNone(panel.simulation)
        self.assertFalse(panel.busy)

    def test_scope_cannot_change_while_busy_and_stale_revision_cannot_be_substituted(self):
        _, new, candidate, _, policy, _ = self.prepared()
        panel = self.controller()
        panel.policy = policy
        panel.review_candidate(candidate.candidate_id, 1)
        expected = copy.deepcopy(panel.review_selection)
        panel.busy = True
        self.assertFalse(panel.review_candidate(candidate.candidate_id + 1, 1))
        self.assertEqual(panel.review_selection, expected)
        panel.busy = False
        quote = self.runtime.semantic_repository.list_claims(new.note_id)[0].statement
        self.runtime.semantic_maintenance.edit(candidate.candidate_id,
            {'relation': 'SUPERSEDES', 'confidence': 0.99, 'impact': 'HIGH', 'rationale': 'Updated review',
             'replacement_text': quote}, expected_revision=1, actor='human:test')
        panel._simulate()
        self.settle_controller(panel)
        self.assertFalse(panel.simulation['plan']['items'][0]['eligible'])
        self.assertEqual(panel.review_selection, expected)
        self.assertTrue(panel.simulation['plan']['items'][0]['blockers'])

    def test_selected_simulation_replays_after_response_lost_without_new_record(self):
        _, _, candidate, _, policy, _ = self.prepared()
        panel = self.controller()
        panel.policy = policy
        panel.review_candidate(candidate.candidate_id, 1)
        original = panel.service.simulate
        def lost(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('Lost response')
        with patch.object(panel.service, 'simulate', side_effect=lost):
            panel._simulate()
            self.settle_controller(panel)
        panel._simulate()
        self.settle_controller(panel)
        self.assertEqual(len(panel.service.repository.list_records('simulations', policy_id=policy['policy_id'])), 1)
        self.assertEqual(panel.simulation['plan']['items'][0]['candidate_id'], candidate.candidate_id)

    def test_historical_simulation_cannot_authorize_a_different_selected_proposal_or_revision(self):
        _, _, candidate, repo, policy, _ = self.prepared()
        _, _, other, _, _, _ = self.prepared(label='Other', key='history-other-policy')
        panel = self.controller()
        panel.policy, panel.control = policy, repo.control()
        panel.review_candidate(candidate.candidate_id, 1)
        selected = copy.deepcopy(panel.review_selection)
        for item in ({'candidate_id': other.candidate_id, 'expected_revision': 1},
                     {'candidate_id': candidate.candidate_id, 'expected_revision': 2}):
            with self.subTest(item=item):
                historical = panel.service.simulate(policy['policy_id'], expected_revision=1,
                    actor='ui', key=f"history-{item['candidate_id']}-{item['expected_revision']}", selection=[item])
                panel.audit_rows = {'row': historical}
                panel.audit_tree.selection.return_value = ('row',)
                panel._simulation_key = 'pending-filtered-simulation'
                AutomationPanel._audit_detail(panel)
                self.settle_controller(panel)
                self.assertIn('Simulación histórica', panel.status.set.call_args.args[0])
                self.assertIn('otras propuestas o revisiones', panel.status.set.call_args.args[0])
                self.assertEqual(panel.review_selection, selected)
                self.assertEqual(panel._simulation_key, 'pending-filtered-simulation')
                self.assertTrue(simulation_matches(policy, panel.simulation, panel.control, dirty=False))
                self.assertFalse(simulation_matches(policy, panel.simulation, panel.control,
                                                    dirty=False, selection=selected))
                with patch('knowledge_orchestrator.ui.automation_panel.messagebox.askyesno') as confirm:
                    AutomationPanel._activation(panel, True)
                confirm.assert_not_called()
                self.assertFalse(repo.get(policy['policy_id'])['enabled'])
        panel._simulate()
        self.settle_controller(panel)
        self.assertTrue(simulation_matches(policy, panel.simulation, panel.control, dirty=False, selection=selected))
        self.assertIn('corresponde a la propuesta y revisión seleccionadas', panel.status.set.call_args.args[0])

    def test_navigation_opens_both_policy_tabs_only_after_candidate_is_accepted(self):
        dashboard = SimpleNamespace(automation_panel=Mock(), _show_page=Mock(), _services_tabs=Mock(),
            _services_automation_page='automation', _automation_tabs=Mock(), status_var=Mock())
        dashboard.automation_panel.review_candidate.return_value = False
        ServiciosMixin._review_proposal_policy(dashboard, 8, 3)
        dashboard._show_page.assert_not_called()
        dashboard.automation_panel.review_candidate.return_value = True
        ServiciosMixin._review_proposal_policy(dashboard, 8, 3)
        dashboard.automation_panel.review_candidate.assert_called_with(8, 3)
        dashboard._services_tabs.select.assert_called_once_with('automation')
        dashboard._automation_tabs.select.assert_called_once_with(dashboard.automation_panel)
        review = SimpleNamespace(_selected_review=SimpleNamespace(candidate_id=8, proposal_revision=3),
                                  _review_proposal_policy=Mock())
        RevisionMixin._evaluate_selected_policy(review)
        review._review_proposal_policy.assert_called_once_with(8, 3)
