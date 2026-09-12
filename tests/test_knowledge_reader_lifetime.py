from __future__ import annotations

import gc
import queue
import unittest
import weakref
from types import SimpleNamespace
from unittest.mock import patch

from knowledge_orchestrator.ui.dashboard.conocimiento import ConocimientoMixin


class KnowledgeReaderLifetimeTests(unittest.TestCase):
    def test_pending_reader_does_not_keep_closed_window_alive(self):
        class View:
            pass

        view = View()
        view._knowledge_refreshing = False
        view._knowledge_applied_state = 'current'
        view._knowledge_applied_query = ''
        view._knowledge_offset = 0
        view.knowledge_summary = SimpleNamespace(set=lambda value: None)
        view.operations = SimpleNamespace(refresh_knowledge=lambda **kwargs: {'items': []})
        results = view._knowledge_results = queue.SimpleQueue()
        view._poll_knowledge = lambda: None
        view.after = lambda *args: None
        with patch('knowledge_orchestrator.ui.dashboard.conocimiento.threading.Thread') as thread:
            ConocimientoMixin._refresh_knowledge(view)
            work = thread.call_args.kwargs['target']
        reference = weakref.ref(view)
        del view
        gc.collect()
        self.assertIsNone(reference(), 'background reader retains the window and its Tcl variables')
        work()
        self.assertEqual(results.get_nowait(), (('current', '', 0), {'items': []}))
