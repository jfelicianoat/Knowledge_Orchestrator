from __future__ import annotations

import os
import subprocess
import sys
import unittest


class DesktopBootstrapTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32' and sys.version_info[:3] == (3, 14, 0),
                         'Regresión de arranque del runtime Windows Python 3.14.0')
    def test_desktop_entry_initializes_tcl_without_changing_environment(self):
        result = subprocess.run([sys.executable, '-B', '-c', '''
import os
from knowledge_orchestrator.ui.desktop_bootstrap import load_dashboard
before = {key: os.environ.get(key) for key in ('TCL_LIBRARY', 'TK_LIBRARY')}
assert callable(load_dashboard())
import tkinter
for _ in range(2):
    interpreter = tkinter.Tcl()
    assert interpreter.eval('info patchlevel') == '8.6.15'
assert before == {key: os.environ.get(key) for key in before}
from knowledge_orchestrator.ui.dashboard.base import DashboardBase
class ClosingWindow(DashboardBase):
    def __init__(self):
        tkinter.Tk.__init__(self)
window = ClosingWindow()
window.withdraw()
job = window.after(100, lambda: None)
window.destroy()
assert job not in window.tk.call('after', 'info'), 'closed window retains a scheduled callback'
print('desktop-tcl-ready')
'''], capture_output=True, text=True, timeout=15, env=os.environ.copy())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('desktop-tcl-ready', result.stdout)
