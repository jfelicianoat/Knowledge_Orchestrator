from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import unittest
from types import MethodType, SimpleNamespace
from unittest.mock import Mock, patch

from knowledge_orchestrator.services.reversion_view import reversion_view
from knowledge_orchestrator.ui.reversion_panel import ReversionPanel
from tests import test_maintenance_reversion as reversion

MODULE = 'knowledge_orchestrator.ui.reversion_panel'


class ReversionUiTests(unittest.TestCase):
    setUp = reversion.MaintenanceReversionTests.setUp
    tearDown = reversion.MaintenanceReversionTests.tearDown
    publish_monitored = reversion.MaintenanceReversionTests.publish_monitored
    extraction = staticmethod(reversion.MaintenanceReversionTests.extraction)
    prepared = reversion.MaintenanceReversionTests.prepared
    simulation = reversion.MaintenanceReversionTests.simulation
    authorize = reversion.MaintenanceReversionTests.authorize
    queue = reversion.MaintenanceReversionTests.queue
    applied = reversion.MaintenanceReversionTests.applied

    def panel(self):
        panel = SimpleNamespace(service=self.runtime.maintenance_reversion, ready=lambda: True,
            closed=False, busy=False, uncertain=False, offset=0, history_offset=0, application=None,
            record=None, rows={}, history_rows=[], _preview_key=None, results=queue.SimpleQueue(),
            status=Mock(), tree=Mock(), history_choice=Mock(), before=Mock(), proposed=Mock(), evidence=Mock(),
            after=Mock(return_value='poll'))
        for name in ('_submit', '_poll', '_receive', '_load', '_page', '_load_history', '_history_page',
                     '_prepare', '_confirm', '_read_record', '_reload', '_clear_record', '_clear_history'):
            setattr(panel, name, MethodType(getattr(ReversionPanel, name), panel))
        panel._actions = Mock()
        panel.tree.get_children.return_value = ()
        panel._history_label = ReversionPanel._history_label
        panel._actor_label = ReversionPanel._actor_label
        return panel

    def selected(self):
        old, _, candidate, before, _ = self.applied()
        panel = self.panel()
        panel.application = panel.service.repository.publications()[0]
        return panel, old, candidate, before

    def settle(self, panel):
        deadline = time.monotonic() + 5
        while panel.busy and time.monotonic() < deadline:
            panel._poll()
            time.sleep(0.005)
        self.assertFalse(panel.busy)

    def test_failed_pagination_does_not_skip_publications_or_history(self):
        panel, _, _, _ = self.selected()
        repo = panel.service.repository
        for method, reader, offset in (('_page', 'publications', 'offset'),
                                       ('_history_page', 'list_records', 'history_offset')):
            with self.subTest(method=method):
                with patch.object(repo, reader, side_effect=OSError('unavailable')) as failed:
                    getattr(panel, method)(100)
                    self.settle(panel)
                    self.assertEqual(getattr(panel, offset), 0)
                    failed.assert_called_once()
                with patch.object(repo, reader, return_value=[]) as succeeded:
                    getattr(panel, method)(100)
                    self.settle(panel)
                    self.assertEqual(succeeded.call_args.kwargs['offset'], 100)
                    self.assertEqual(getattr(panel, offset), 100)
                # Restore the selection cleared by an empty publications page.
                panel.application = repo.publications()[0]

    def test_preview_retry_after_lost_response_reuses_frozen_plan(self):
        panel, _, _, _ = self.selected()
        original = panel.service.preview
        def lose_response(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('response lost')
        with patch.object(panel.service, 'preview', side_effect=lose_response):
            panel._prepare()
            self.settle(panel)
        self.assertIsNone(panel.record)
        panel._prepare()
        self.settle(panel)
        self.assertEqual(panel.record['status'], 'PREVIEW')
        self.assertEqual(len(panel.service.repository.list_records(actor='ui')), 1)

    def test_cancelled_confirmation_and_missing_reason_leave_note_unchanged(self):
        panel, old, _, _ = self.selected()
        panel._prepare()
        self.settle(panel)
        published = old.vault_path.read_bytes()
        for answer, reason in ((False, 'unused'), (True, None), (True, '')):
            with patch(MODULE + '.messagebox.askyesno', return_value=answer), \
                    patch(MODULE + '.simpledialog.askstring', return_value=reason):
                panel._confirm()
            self.assertFalse(panel.busy)
            self.assertEqual(old.vault_path.read_bytes(), published)
            self.assertEqual(panel.service.repository.audit(panel.record['reversion_id'])['status'], 'PREVIEW')

    def test_failed_record_read_disables_previous_confirmation_until_reload(self):
        panel, _, _, _ = self.selected()
        panel._prepare()
        self.settle(panel)
        original_id = panel.record['reversion_id']
        panel._read_record('missing-record')
        self.settle(panel)
        self.assertTrue(panel.uncertain)
        with patch(MODULE + '.messagebox.askyesno') as question:
            panel._confirm()
        question.assert_not_called()
        panel._reload()
        self.settle(panel)
        self.assertFalse(panel.uncertain)
        self.assertEqual(panel.record['reversion_id'], original_id)

    def test_lost_confirmation_response_is_recovered_from_receipt(self):
        panel, old, _, before = self.selected()
        panel._prepare()
        self.settle(panel)
        original = panel.service.confirm
        def lose_response(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('lost after commit')
        with patch.object(panel.service, 'confirm', side_effect=lose_response), \
                patch(MODULE + '.messagebox.askyesno', return_value=True), \
                patch(MODULE + '.simpledialog.askstring', return_value='Reviewed'):
            panel._confirm()
            self.settle(panel)
        self.assertTrue(panel.uncertain)
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), before)
        panel._reload()
        self.settle(panel)
        self.assertEqual(panel.record['status'], 'APPLIED')
        self.assertFalse(panel.uncertain)

    def test_local_audit_can_read_other_owner_but_cannot_confirm_their_plan(self):
        panel, _, candidate, _ = self.selected()
        foreign = panel.service.preview(candidate.candidate_id, expected_revision=candidate.proposal_revision,
                                        actor='api:reviewer', key='foreign-ui-audit-01')
        panel._load_history()
        self.settle(panel)
        self.assertEqual([row['owner'] for row in panel.history_rows], ['api:reviewer'])
        panel._read_record(foreign['reversion_id'])
        self.settle(panel)
        self.assertEqual(panel.record, reversion_view(foreign))
        with patch(MODULE + '.messagebox.askyesno') as question:
            panel._confirm()
        question.assert_not_called()
        with self.assertRaises(ValueError):
            panel.service.repository.get(foreign['reversion_id'], actor='ui')

    def test_startup_busy_and_changed_selection_cannot_retarget_confirmation(self):
        panel, _, _, _ = self.selected()
        panel._prepare()
        self.settle(panel)
        record = panel.record
        for field, value in (('ready', lambda: False), ('busy', True),
                             ('application', {'candidate_id': -1})):
            previous = getattr(panel, field)
            setattr(panel, field, value)
            with patch(MODULE + '.messagebox.askyesno') as question:
                panel._confirm()
            question.assert_not_called()
            setattr(panel, field, previous)
        panel._receive('record', {**record, 'candidate_id': -1})
        self.assertIs(panel.record, record)
        panel.busy = True
        panel.tree.selection.return_value = ('other',)
        ReversionPanel._select(panel)
        panel.tree.selection_set.assert_called_with((str(record['candidate_id']),))

    def test_background_operation_never_updates_widgets(self):
        panel = self.panel()
        main = threading.get_ident()
        threads = []
        panel._actions = lambda: threads.append(threading.get_ident())
        panel._submit('probe', threading.get_ident)
        kind, worker, error = panel.results.get(timeout=3)
        self.assertEqual((kind, error), ('probe', None))
        self.assertNotEqual(worker, main)
        self.assertEqual(threads, [main])
        panel.status.set.assert_not_called()

    def test_keyboard_scroll_moves_only_clipped_pixels(self):
        canvas = Mock()
        canvas.winfo_rooty.return_value = 100
        canvas.winfo_height.return_value = 400
        canvas.canvasy.return_value = 200
        canvas.bbox.return_value = (0, 0, 1000, 1000)
        widget = Mock()
        widget.winfo_height.return_value = 120
        for root_y, expected in ((400, 0.22), (95, 0.195)):
            widget.winfo_rooty.return_value = root_y
            ReversionPanel._reveal_focus(SimpleNamespace(canvas=canvas), SimpleNamespace(widget=widget))
            canvas.yview_moveto.assert_called_with(expected)
        canvas.yview_moveto.reset_mock()
        widget.winfo_rooty.return_value = 200
        ReversionPanel._reveal_focus(SimpleNamespace(canvas=canvas), SimpleNamespace(widget=widget))
        canvas.yview_moveto.assert_not_called()

    def test_native_preview_confirm_and_small_window_keep_actions_accessible(self):
        try:
            root = tk.Tk()
        except tk.TclError as error:
            if 'init.tcl' in str(error) or 'no display name' in str(error):
                self.skipTest(str(error))
            raise
        self.addCleanup(root.destroy)
        root.geometry('1080x480')
        old, _, candidate, before, _ = self.applied()
        colors = {'surface': '#11191e', 'raised': '#182228', 'text': '#f2f6f8'}
        panel = ReversionPanel(root, self.runtime.maintenance_reversion, colors, lambda: True)
        panel.pack(fill='both', expand=True)
        def settle():
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                root.update()
                if not panel.busy:
                    break
                time.sleep(0.01)
            self.assertFalse(panel.busy)
        settle()
        panel.tree.selection_set(str(candidate.candidate_id))
        root.update()
        settle()
        panel._prepare()
        settle()
        self.assertEqual(panel.record['status'], 'PREVIEW')
        self.assertFalse(panel.confirm_button.instate(['disabled']))
        self.assertLessEqual(panel.confirm_button.winfo_rooty() + panel.confirm_button.winfo_height(),
                             root.winfo_rooty() + root.winfo_height())
        self.assertGreater(float(panel.canvas.bbox('all')[3]), panel.canvas.winfo_height())
        with patch(MODULE + '.messagebox.askyesno', return_value=True), \
                patch(MODULE + '.simpledialog.askstring', return_value='Native review'):
            panel._confirm()
        settle()
        self.assertEqual(panel.record['status'], 'APPLIED')
        self.assertEqual(old.vault_path.read_text(encoding='utf-8'), before)
