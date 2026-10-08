import importlib.util
from pathlib import Path
import socket
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('console_window', ROOT/'tools/console-window.py')
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)


class ConsoleWindowTest(unittest.TestCase):
    def test_live_socket_and_exact_container_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'run').mkdir()
            with socket.socket(socket.AF_UNIX) as server:
                server.bind(str(root/'run/console-vnc.sock'))
                state = {'cid': 'abc', 'started_at': 'start'}
                live = {'Id': 'abc', 'State': {'Running': True, 'StartedAt': 'start'},
                        'Config': {'Env': ['VM_CONSOLE=bochs']}}
                command = tool.viewer_command(root, state, live, '/usr/bin/vncviewer')
                self.assertIn('-Shared', command)
                self.assertIn('-RemoteResize=0', command)
                for changed in ({'cid': 'other', 'started_at': 'start'},
                                {'cid': 'abc', 'started_at': 'old'}):
                    with self.assertRaises(ValueError):
                        tool.viewer_command(root, changed, live, '/usr/bin/vncviewer')
                live['Config']['Env'] = []
                with self.assertRaises(ValueError):
                    tool.viewer_command(root, state, live, '/usr/bin/vncviewer')
                live['Config']['Env'] = ['VM_CONSOLE=bochs']
                (root/'run/console-vnc.sock').unlink()
                (root/'run/console-vnc.sock').write_text('not a socket')
                with self.assertRaises(ValueError):
                    tool.viewer_command(root, state, live, '/usr/bin/vncviewer')
