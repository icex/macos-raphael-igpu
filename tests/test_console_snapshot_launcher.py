"""Execute the real launcher with software children; no IOKit, tty or GUI use."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STUB = '''#!/usr/bin/python3
import json, os, pathlib, signal, socket, sys, time
role=pathlib.Path(sys.argv[0]).name
out=pathlib.Path(os.environ['FIXTURE_RECORDS'])
(out/(role+'.pid')).write_text(str(os.getpid()))
def stop(sig,frame):
 (out/(role+'.stopped')).write_text(str(sig))
 sys.exit(0)
signal.signal(signal.SIGTERM,stop)
if role=='virtual-display-server':
 p=pathlib.Path(sys.argv[sys.argv.index('--control-dir')+1]);p.mkdir(mode=0o700)
 os.chdir(p);s=socket.socket(socket.AF_UNIX);s.bind('control.sock')
 print('{"phase":"serving"}',flush=True)
if role=='console-display-layout':sys.exit(0)
if role=='console-presenter':
 with (out/'presenter.jsonl').open('a') as f:
  f.write(json.dumps(dict(snapshot=os.getenv('RGPU_CONSOLE_SNAPSHOT'),cache=os.getenv('RGPU_CONSOLE_CACHE')))+'\\n')
 deadline=time.monotonic()+2
 while not (out/'console-vdagent-agent.py.pid').exists():
  if time.monotonic()>deadline:sys.exit(99)
  time.sleep(.01)
 sys.exit(int(os.environ['FIXTURE_PRESENTER_EXIT']))
while True:time.sleep(.05)
'''

class SnapshotLauncherTests(unittest.TestCase):
    def run_launcher(self, restartable, protocol, incoming, expected, exitcode=0):
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory);home.chmod(0o700)
            support=home/'Library/Application Support/RaphaelGPU/console'
            support.mkdir(parents=True,mode=0o700)
            payload=home/'payload';payload.mkdir()
            bindir=home/'bin';bindir.mkdir()
            records=home/'records';records.mkdir()
            app=home/'Applications/Raphael Console.app/Contents'
            (app/'MacOS').mkdir(parents=True);(app/'Helpers').mkdir()
            (payload/'console-preferences.py').write_bytes((ROOT/'tools/console-preferences.py').read_bytes())
            for path in (payload/'virtual-display-server',payload/'console-vdagent-agent.py',bindir/'caffeinate',app/'MacOS/console-presenter',app/'Helpers/console-display-layout'):
                path.write_text(STUB);path.chmod(0o700)
            inventory='RaphaelConsole\n'
            if restartable is not None:inventory+=f'"SnapshotRestartable" = {restartable}\n'
            if protocol is not None:inventory+=f'"SnapshotProtocol" = {protocol}\n'
            (bindir/'ioreg').write_text('#!/bin/sh\nprintf %s '+shlex.quote(inventory)+'\n')
            (bindir/'ioreg').chmod(0o700)
            launcher=(ROOT/'tools/console-support-launcher.sh').read_text().replace('@@PAYLOAD@@',shlex.quote(str(payload)))
            # Only the channel-availability pathname is substituted. Stub agent
            # never opens /dev/null; real preferences and actual shell run intact.
            launcher=launcher.replace('/dev/tty.com.redhat.spice.0','/dev/null')
            env=dict(os.environ,HOME=str(home),PATH=str(bindir)+os.pathsep+os.environ['PATH'],
                FIXTURE_RECORDS=str(records),FIXTURE_PRESENTER_EXIT=str(exitcode),
                RGPU_CONSOLE_SNAPSHOT=incoming,RGPU_CONSOLE_CACHE='wc')
            process=subprocess.Popen(['bash','-c',launcher],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True)
            try:
                stdout,stderr=process.communicate(timeout=8)
                self.assertEqual(process.returncode,exitcode,stdout+stderr)
                rows=[json.loads(s) for s in (records/'presenter.jsonl').read_text().splitlines()]
                self.assertEqual(rows,[dict(snapshot=expected,cache='default')])
                for role in ('virtual-display-server','console-vdagent-agent.py','caffeinate'):
                    self.assertTrue((records/(role+'.stopped')).exists(),role)
                    pid=int((records/(role+'.pid')).read_text())
                    with self.assertRaises(ProcessLookupError):os.kill(pid,0)
            finally:
                # Kill only this fixture's new process group if a failed test
                # leaves a stub child; never discover processes by executable.
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=3)

    def test_ready_native_framebuffer_suppresses_capture_helpers(self):
        # Execute the actual early guard with ioreg output selected by class.
        source=(ROOT/'tools/console-support-launcher.sh').read_text()
        guard=source[source.index('native=$(ioreg'):source.index('bridge=$(ioreg')]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);tool=root/'ioreg'
            tool.write_text("#!/bin/sh\nprintf %s '\"NativeConsoleReady\" = Yes'\n");tool.chmod(0o700)
            env=dict(os.environ,PATH=str(root)+os.pathsep+os.environ['PATH'])
            result=subprocess.run(['bash','-c',guard+'\nprintf UNEXPECTED_CONTINUATION'],env=env,capture_output=True,text=True,timeout=3)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('exclusive native mode ownership',result.stdout)
            self.assertNotIn('UNEXPECTED_CONTINUATION',result.stdout)

    def test_restartable_overrides_inherited_disable_and_wc(self):
        self.run_launcher(1,1,'0','1')

    def test_legacy_and_unavailable_override_inherited_enable(self):
        for capability in ((0,1),(None,None),(1,0)):
            with self.subTest(capability=capability):
                self.run_launcher(*capability,'1','0')

    def test_presenter_failure_exits_once_and_stops_owned_children(self):
        self.run_launcher(1,1,'0','1',23)
