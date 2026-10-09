import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('native_console',ROOT/'tools/libvirt-console-native.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)


class NativeTests(unittest.TestCase):
    def test_cpu_queries_refresh_on_resume_process_change_and_interval(self):
        backend=mod.NativeBackend.__new__(mod.NativeBackend);backend.cpu_cache=None
        calls=[]
        def qmp(name,cmd,args):
            calls.append(cmd)
            if cmd=='query-cpus-fast':return [{'qom-path':'/cpu/0'}]
            return {'query-kvm':{'enabled':True,'present':True},'qom-get':True}[cmd]
        backend.qmp=qmp
        state=dict(pid=10,start_ticks=20,running=False)
        with patch.object(mod.local.LocalBackend,'_snapshot',side_effect=lambda name:dict(state)),patch.object(mod.time,'monotonic',return_value=100) as clock:
            backend._snapshot('test');self.assertEqual(len(calls),6)
            cached=backend._snapshot('test');self.assertEqual(len(calls),6)
            cached['cpu_properties']['/cpu/0']['vendor']='mutated'
            self.assertIs(backend._snapshot('test')['cpu_properties']['/cpu/0']['vendor'],True)
            state['running']=True;backend._snapshot('test');self.assertEqual(len(calls),12)
            state['start_ticks']=21;backend._snapshot('test');self.assertEqual(len(calls),18)
            clock.return_value=131;backend._snapshot('test');self.assertEqual(len(calls),24)

if __name__=='__main__':unittest.main()
