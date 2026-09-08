from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import unittest
from dataclasses import asdict
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

from knowledge_orchestrator.domain.automation import AutomationPolicyConfig
from knowledge_orchestrator.ui.automation_form import AutomationForm
from knowledge_orchestrator.ui.automation_panel import AutomationPanel
from knowledge_orchestrator.ui.automation_plan import AutomationPlanView
from knowledge_orchestrator.ui.automation_presenter import NUMERIC_FIELDS, config_from_fields, simulation_matches
from tests import test_automation_governance as governance


class AutomationUiTests(unittest.TestCase):
    setUp = governance.AutomationGovernanceTests.setUp
    tearDown = governance.AutomationGovernanceTests.tearDown
    publish_monitored = governance.AutomationGovernanceTests.publish_monitored
    extraction = staticmethod(governance.AutomationGovernanceTests.extraction)
    prepared = governance.AutomationGovernanceTests.prepared

    def controller(self):
        panel = SimpleNamespace(runtime=self.runtime, service=self.runtime.automation_governance,
            ready=lambda: True, busy=False, closed=False, dirty=False, creating=False, control_busy=False,
            control={}, policy=None, simulation=None, review_selection=None,
            policy_offset=0, source_offset=0, audit_offset=0,
            simulation_cursor=0, _simulation_key=None, _create_key='test-draft-stable',
            _audit_kind_loaded='Versiones y decisiones', _audit_selected=(), policy_rows=[], audit_rows={},
            results=queue.SimpleQueue(), status=Mock(), control_text=Mock(), pause_button=Mock(), choice=Mock(),
            form=Mock(), plan=Mock(), tabs=Mock(), audit_tree=Mock(), audit_text=Mock(), audit_kind=Mock(),
            audit_previous=Mock(), audit_next=Mock(), _actions=Mock(), _discard=Mock(return_value=True),
            _refresh_control=Mock(), after=Mock(return_value='poll'), winfo_ismapped=lambda: False)
        panel.audit_tree.get_children.return_value = ()
        panel.audit_kind.get.return_value = 'Versiones y decisiones'
        for name in ('_submit', '_poll', '_receive', '_policy_page', '_source_page', '_load_audit', '_audit_page',
                     '_clear_audit', 'refresh', '_choose', '_simulate', '_simulate_next', 'review_candidate'):
            setattr(panel, name, MethodType(getattr(AutomationPanel, name), panel))
        panel._policy_label = AutomationPanel._policy_label
        return panel

    def settle_controller(self, panel):
        deadline = time.monotonic() + 5
        while panel.busy and time.monotonic() < deadline:
            panel._poll()
            time.sleep(0.005)
        self.assertFalse(panel.busy)

    def test_policy_page_failure_preserves_selected_policy_and_draft_until_success(self):
        _, _, _, _, policy, _ = self.prepared()
        panel = self.controller()
        repo = panel.service.policies
        panel.policy, panel.dirty = policy, True
        with patch.object(repo, 'list', side_effect=OSError('offline')):
            panel._policy_page(100)
            self.settle_controller(panel)
        self.assertIs(panel.policy, policy)
        self.assertTrue(panel.dirty)
        self.assertEqual(panel.policy_offset, 0)
        panel.form.set_config.assert_not_called()
        with patch.object(repo, 'list', return_value=[]) as read:
            panel._policy_page(100)
            self.settle_controller(panel)
        self.assertEqual(read.call_args.kwargs['offset'], 100)
        self.assertEqual(panel.policy_offset, 100)
        self.assertIsNone(panel.policy)
        self.assertFalse(panel.dirty)

    def test_source_page_failure_preserves_current_rows_and_retries_same_offset(self):
        panel = self.controller()
        repo = self.runtime.sources.repository
        with patch.object(repo, 'list_sources', side_effect=OSError('offline')):
            panel._source_page(100)
            self.settle_controller(panel)
        self.assertEqual(panel.source_offset, 0)
        panel.form.show_sources.assert_not_called()
        with patch.object(repo, 'list_sources', return_value=[]) as read:
            panel._source_page(100)
            self.settle_controller(panel)
        self.assertEqual(read.call_args.kwargs['offset'], 100)
        self.assertEqual(panel.source_offset, 100)
        panel.form.show_sources.assert_called_once_with([], 100)

    def test_audit_failure_preserves_page_and_kind_then_retry_commits_together(self):
        panel = self.controller()
        panel.audit_kind.get.return_value = 'Pausa global'
        panel.audit_rows = {'old': {'created_at': 'previous'}}
        repo = panel.service.repository
        with patch.object(repo, 'control_history', side_effect=OSError('offline')):
            panel._audit_page(100)
            self.settle_controller(panel)
        self.assertEqual(panel.audit_offset, 0)
        self.assertIn('old', panel.audit_rows)
        panel.audit_kind.set.assert_called_with('Versiones y decisiones')
        with patch.object(repo, 'control_history', return_value=[]) as read:
            panel._audit_page(100)
            self.settle_controller(panel)
        self.assertEqual(read.call_args.kwargs['offset'], 100)
        self.assertEqual((panel.audit_offset, panel._audit_kind_loaded), (100, 'Pausa global'))
        self.assertEqual(panel.audit_rows, {})

    def test_failed_policy_selection_keeps_visible_identity_of_existing_draft(self):
        _, _, _, _, policy, _ = self.prepared()
        panel = self.controller()
        repo = panel.service.policies
        panel.policy, panel.dirty = policy, True
        panel.policy_rows = [{'policy_id': policy['policy_id'] + 1}]
        panel.choice.current.return_value = 0
        with patch.object(repo, 'get', side_effect=OSError('offline')):
            panel._choose()
            self.settle_controller(panel)
        self.assertIs(panel.policy, policy)
        self.assertTrue(panel.dirty)
        panel.choice.set.assert_called_with(AutomationPanel._policy_label(
            {**policy, 'name': policy['config']['name']}))
        panel.form.set_config.assert_not_called()

    def test_next_simulation_retry_reuses_key_and_return_to_first_page_changes_it(self):
        _, _, candidate, repo, policy, _ = self.prepared()
        panel = self.controller()
        panel.policy = policy
        panel.plan.page_size.get.return_value = '1'
        panel._simulate()
        self.settle_controller(panel)
        first = panel.simulation
        self.assertEqual(first['plan']['items'][0]['candidate_id'], candidate.candidate_id)
        simulate = panel.service.simulate_page
        calls = []
        def lost(*args, **kwargs):
            calls.append(kwargs)
            simulate(*args, **kwargs)
            raise OSError('response lost after commit')
        with patch.object(panel.service, 'simulate_page', side_effect=lost):
            panel._simulate_next()
            self.settle_controller(panel)
        panel._simulate_next()
        self.settle_controller(panel)
        self.assertEqual(panel.simulation['plan']['selection_page']['after_candidate_id'], candidate.candidate_id)
        self.assertEqual(len(panel.service.repository.list_records('simulations', policy_id=policy['policy_id'])), 2)
        # Returning to page one after a failed next-page request cannot reuse its different request identity.
        panel.simulation = first
        with patch.object(panel.service, 'simulate_page', side_effect=lost):
            panel._simulate_next()
            self.settle_controller(panel)
        next_key = calls[-1]['key']
        with patch.object(panel.service, 'simulate_page', wraps=simulate) as read:
            panel._simulate()
            self.settle_controller(panel)
        self.assertEqual(read.call_args.kwargs['after_candidate_id'], 0)
        self.assertNotEqual(read.call_args.kwargs['key'], next_key)
        self.assertEqual(panel.simulation['plan']['items'][0]['candidate_id'], candidate.candidate_id)

    def test_form_focus_scroll_uses_minimum_pixels_without_overshooting(self):
        canvas, widget = Mock(), Mock()
        canvas.winfo_rooty.return_value = 100
        canvas.winfo_height.return_value = 400
        canvas.canvasy.return_value = 200
        canvas.bbox.return_value = (0, 0, 1000, 1000)
        widget.winfo_height.return_value = 120
        for y, expected in ((400, 0.22), (95, 0.195)):
            widget.winfo_rooty.return_value = y
            for view in (AutomationForm, AutomationPlanView):
                view._reveal_focus(SimpleNamespace(canvas=canvas), SimpleNamespace(widget=widget))
                canvas.yview_moveto.assert_called_with(expected)

    def test_form_conditions_preserve_explicit_scope_and_reject_invalid_limits(self):
        config = asdict(AutomationPolicyConfig('Oficial', (3, 4)))
        values = {name: str(config[name]) for name in ('name', *NUMERIC_FIELDS)}
        values['claim_types'], values['min_confidence'] = 'VERSION, FACT', '0,97'
        choices = {name: config[name] for name in ('source_kinds', 'source_roles', 'relations')}
        parsed = config_from_fields(values, choices, {3, 4})
        self.assertEqual(parsed.source_ids, (3, 4))
        self.assertEqual(parsed.claim_types, ('FACT', 'VERSION'))
        self.assertEqual(parsed.min_confidence, 0.97)
        for field, value in (('max_tasks_per_run', '99999'), ('min_confidence', 'NaN'), ('max_tasks_per_day', 'dos')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                config_from_fields({**values, field: value}, choices, {3})
        with self.assertRaises(ValueError):
            config_from_fields(values, choices, set())

    def test_authorization_requires_matching_policy_configuration_activation_and_control(self):
        _, _, _, _, policy, _ = self.prepared()
        simulation = self.runtime.automation_governance.simulate(
            policy['policy_id'], expected_revision=policy['revision'], actor='ui', key='ui-simulation-01')
        control = self.runtime.automation_policies.control()
        self.assertTrue(simulation_matches(policy, simulation, control, dirty=False))
        self.assertFalse(simulation_matches(policy, simulation, control, dirty=True))
        for field in ('policy_id', 'revision', 'state_revision'):
            self.assertFalse(simulation_matches({**policy, field: policy[field] + 1}, simulation, control, dirty=False))
        self.assertFalse(simulation_matches(policy, simulation, {**control, 'revision': 999}, dirty=False))

    def test_source_selection_retains_other_pages_and_ignores_disabled_widget_events(self):
        source_tree = SimpleNamespace(instate=lambda _states: False, selection=lambda: ('2',))
        form = SimpleNamespace(_rendering=False, sources=source_tree, source_ids={1, 101}, _source_rows={1, 2},
                               changed=Mock(), _source_status=Mock())
        AutomationForm._source_selection(form)
        self.assertEqual(form.source_ids, {2, 101})
        form.changed.assert_called_once()
        source_tree.instate = lambda _states: True
        source_tree.selection = lambda: ()
        AutomationForm._source_selection(form)
        self.assertEqual(form.source_ids, {2, 101})
        form.changed.assert_called_once()

    def test_pause_remains_available_while_simulation_is_busy_and_uses_captured_revision(self):
        repo = self.runtime.automation_policies
        repo.set_paused(False, expected_revision=1, actor='ui', reason='Test only')
        actor_thread = threading.get_ident()
        actions_threads = []
        panel = SimpleNamespace(ready=lambda: True, closed=False, control_busy=False, busy=True,
                                control=repo.control(), service=self.runtime.automation_governance,
                                results=queue.SimpleQueue(),
                                _actions=lambda: actions_threads.append(threading.get_ident()))
        panel._submit = lambda *args, **kwargs: AutomationPanel._submit(panel, *args, **kwargs)
        with patch('knowledge_orchestrator.ui.automation_panel.messagebox.askyesno', return_value=True), \
                patch('knowledge_orchestrator.ui.automation_panel.simpledialog.askstring', return_value='Pause test'):
            AutomationPanel._pause(panel)
        kind, result, error, is_control = panel.results.get(timeout=3)
        self.assertEqual((kind, error, is_control), ('control', None, True))
        self.assertTrue(result['paused'])
        self.assertEqual(actions_threads, [actor_thread])
        self.assertTrue(panel.busy)  # Ongoing simulation is independent of the pause request.

    def test_cancelled_authorization_cannot_activate_policy(self):
        _, _, _, repo, policy, _ = self.prepared()
        service = self.runtime.automation_governance
        simulation = service.simulate(policy['policy_id'], expected_revision=1, actor='ui', key='cancel-sim-001')
        submit = Mock()
        panel = SimpleNamespace(policy=policy, simulation=simulation, control=repo.control(), ready=lambda: True,
                                busy=False, dirty=False, review_selection=None, _submit=submit)
        with patch('knowledge_orchestrator.ui.automation_panel.messagebox.askyesno', return_value=False):
            AutomationPanel._activation(panel, True)
        submit.assert_not_called()
        self.assertFalse(repo.get(policy['policy_id'])['enabled'])

    def test_actions_do_not_write_before_startup_finishes(self):
        submit = Mock()
        panel = SimpleNamespace(ready=lambda: False, busy=False, control_busy=False, control={'paused': False},
                                policy={'policy_id': 1}, simulation=None, dirty=False, _submit=submit)
        AutomationPanel._pause(panel)
        AutomationPanel._simulate(panel)
        AutomationPanel._activation(panel, True)
        submit.assert_not_called()

    def test_creating_draft_leaves_busy_state_after_background_error(self):
        results = queue.SimpleQueue()
        results.put(('policy', None, 'Error recuperable', False))
        panel = SimpleNamespace(closed=False, results=results, creating=True, dirty=True, busy=True,
                                control_busy=False, status=SimpleNamespace(set=Mock()), _actions=Mock(),
                                after=Mock(return_value='poll'), _poll=Mock(), winfo_ismapped=lambda: False)
        AutomationPanel._poll(panel)
        self.assertFalse(panel.busy)
        self.assertTrue(panel.dirty)
        self.assertTrue(panel.creating)
        panel.status.set.assert_called_once_with('Error recuperable')

    def test_visible_panel_refreshes_external_pause_without_overwriting_draft(self):
        refresh = Mock()
        panel = SimpleNamespace(closed=False, results=queue.SimpleQueue(), creating=True, dirty=True, busy=True,
                                control_busy=False, _actions=Mock(), _next_control_refresh=0, _refresh_control=refresh,
                                after=Mock(return_value='poll'), _poll=Mock(), winfo_ismapped=lambda: True)
        AutomationPanel._poll(panel)
        refresh.assert_called_once()
        self.assertTrue(panel.dirty and panel.busy)
        refresh.reset_mock()
        panel.control_busy = True
        AutomationPanel._poll(panel)
        refresh.assert_not_called()

    def test_simulation_pages_are_scoped_bounded_and_replay_after_candidates_change(self):
        _, _, first, repo, policy, _ = self.prepared()
        self.prepared(label='Outside', key='outside-policy')
        service = self.runtime.automation_governance
        page = service.simulate_page(policy['policy_id'], expected_revision=1, actor='ui', key='ui-page-001', limit=1)
        self.assertEqual([item['candidate_id'] for item in page['plan']['items']], [first.candidate_id])
        self.runtime.semantic_repository.set_manual_lock(first.target_claim_id, True)
        self.assertEqual(service.simulate_page(policy['policy_id'], expected_revision=1, actor='ui',
                                               key='ui-page-001', limit=1), page)
        next_page = service.simulate_page(policy['policy_id'], expected_revision=1, actor='ui', key='ui-page-002',
                                          after_candidate_id=first.candidate_id, limit=1)
        self.assertEqual(next_page['plan']['items'], [])
        for limit in (0, 101, True):
            with self.assertRaises(ValueError):
                service.simulate_page(policy['policy_id'], expected_revision=1, actor='ui',
                                      key='ui-bad-page', limit=limit)
        self.assertFalse(repo.get(policy['policy_id'])['enabled'])

    def test_retry_after_policy_commit_and_lost_response_does_not_create_duplicate(self):
        _, _, _, repo, _, config = self.prepared()
        submitted, failures = [], []
        panel = SimpleNamespace(ready=lambda: True, busy=False, dirty=True, policy=None, _create_key='stable-draft-001',
                                form=SimpleNamespace(read_config=lambda: config),
                                service=SimpleNamespace(policies=repo), status=SimpleNamespace(set=Mock()))
        original_get = repo.get
        first_read = True
        def fail_first_read(identifier):
            nonlocal first_read
            if first_read:
                first_read = False
                raise RuntimeError('lost response after commit')
            return original_get(identifier)
        def submit(_kind, operation):
            try:
                submitted.append(operation())
            except RuntimeError as error:
                failures.append(error)
        panel._submit = submit
        with patch.object(repo, 'get', side_effect=fail_first_read):
            AutomationPanel._save(panel)
            AutomationPanel._save(panel)
        self.assertEqual(len(failures), 1)
        self.assertEqual(len(submitted), 1)
        self.assertEqual(len(repo.list()), 2)  # Fixture policy plus one UI draft, despite two attempts.

    def test_audit_selection_cannot_switch_under_pending_detail_read(self):
        selection_set = Mock()
        panel = SimpleNamespace(busy=True, _audit_selected=('old',), audit_tree=SimpleNamespace(
            selection=lambda: ('new',), exists=lambda _identifier: True, selection_set=selection_set))
        AutomationPanel._audit_detail(panel)
        selection_set.assert_called_once_with(('old',))

    def test_native_policy_flow_preserves_sources_invalidates_dirty_preview_and_authorizes_explicitly(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            if 'init.tcl' in str(error) or 'no display name' in str(error):
                self.skipTest(str(error))
            raise
        root.geometry('1080x680')
        self.addCleanup(root.destroy)
        _, _, candidate, repo, policy, _ = self.prepared()
        colors = {'surface': '#11191e', 'raised': '#182228', 'text': '#f2f6f8'}
        from tkinter import ttk
        outer = ttk.Notebook(root)
        outer.pack(fill='both', expand=True)
        inner = ttk.Notebook(outer)
        outer.add(inner, text='Automatizaciones')
        panel = AutomationPanel(inner, self.runtime, colors, lambda: True)
        inner.add(panel, text='Políticas y decisiones')
        def settle():
            deadline = time.monotonic() + 5
            while (panel.busy or panel.control_busy) and time.monotonic() < deadline:
                root.update()
                time.sleep(0.01)
            root.update()
            self.assertFalse(panel.busy or panel.control_busy)
        settle()
        panel._submit('policy', lambda: repo.get(policy['policy_id']))
        settle()
        self.assertEqual(panel.form.source_ids, set(policy['config']['source_ids']))
        self.assertFalse(panel.dirty)
        self.assertTrue(panel.authorize_button.instate(['disabled']))
        self.assertTrue(panel.review_candidate(candidate.candidate_id, 1))
        panel._simulate()
        settle()
        self.assertGreaterEqual(panel.plan.before.master.master.master.winfo_height(), 220)
        self.assertTrue(panel.authorize_button.winfo_viewable())
        self.assertEqual([item['candidate_id'] for item in panel.simulation['plan']['items']], [candidate.candidate_id])
        self.assertFalse(panel.authorize_button.instate(['disabled']))
        panel.form.fields['name'].set('Unsaved change')
        self.assertTrue(panel.dirty)
        self.assertIsNone(panel.simulation)
        self.assertTrue(panel.authorize_button.instate(['disabled']))
        panel._submit('policy', lambda: repo.get(policy['policy_id']))
        settle()
        panel._simulate()
        settle()
        with patch('knowledge_orchestrator.ui.automation_panel.messagebox.askyesno', return_value=True), \
                patch('knowledge_orchestrator.ui.automation_panel.simpledialog.askstring', return_value='Reviewed'):
            panel._activation(True)
        settle()
        self.assertTrue(repo.get(policy['policy_id'])['enabled'])
        self.assertTrue(repo.control()['paused'])
        self.assertFalse(panel.disable_button.instate(['disabled']))
