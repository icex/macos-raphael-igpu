import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('entry_console',ROOT/'tools/libvirt-console-entry.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)


class DaemonEnvironmentTests(unittest.TestCase):
    def test_child_discovery_cannot_select_inherited_launcher_shim(self):
        # Exercise child PATH lookup without executing an emulator or libvirtd.
        with tempfile.TemporaryDirectory() as tmp:
            shim=Path(tmp)/'qemu-system-x86_64'
            shim.write_text('#!/bin/sh\nexit 99\n');shim.chmod(0o755)
            inherited=dict(os.environ,PATH=tmp+':/usr/bin',
                           XDG_RUNTIME_DIR='/run/vm/private/runtime',
                           RGPU_LIBVIRT_RUN_ID='test-run')
            real_run=subprocess.run
            code='import shutil,os,json;print(json.dumps(dict(binary=shutil.which("qemu-system-x86_64"),runtime=os.environ["XDG_RUNTIME_DIR"],run=os.environ["RGPU_LIBVIRT_RUN_ID"])))'
            control=real_run([sys.executable,'-c',code],env=inherited,
                             capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(control.stdout)['binary'],str(shim))
            observed=[]
            def fake_daemon(argv,**kw):
                self.assertEqual(argv,['libvirtd','--daemon'])
                self.assertTrue(kw['check']);self.assertEqual(kw['timeout'],7)
                result=real_run([sys.executable,'-c',code],env=kw['env'],
                                capture_output=True,text=True,check=True)
                observed.append(json.loads(result.stdout))
                return result
            with patch.dict(os.environ,inherited,clear=True), \
                 patch.object(mod.time,'monotonic',return_value=100), \
                 patch.object(mod.subprocess,'run',side_effect=fake_daemon):
                mod.start_daemon(107)
                self.assertEqual(os.environ['PATH'],inherited['PATH'])
            self.assertNotEqual(observed[0]['binary'],str(shim))
            self.assertEqual(observed[0]['runtime'],inherited['XDG_RUNTIME_DIR'])
            self.assertEqual(observed[0]['run'],'test-run')

    def test_daemon_failure_is_not_swallowed(self):
        with patch.object(mod.subprocess,'run',side_effect=subprocess.CalledProcessError(1,['libvirtd'])):
            with self.assertRaises(subprocess.CalledProcessError):mod.start_daemon(0)

    def test_daemon_wait_retains_ten_second_cap(self):
        with patch.object(mod.time,'monotonic',return_value=100), \
             patch.object(mod.subprocess,'run') as run:
            mod.start_daemon(500)
            self.assertEqual(run.call_args.kwargs['timeout'],10)


class RefreshPlanBindingTests(unittest.TestCase):
    def plan(self,refresh='default'):
        spice=mod.native.configuration.planner.SPICE
        if refresh=='60':spice+=',max-refresh-rate=60'
        return {'native_argv':['-spice',spice,'-device',mod.native.configuration.planner.BOCHS]}
    def test_agent_mouse_route_bound_to_admission_both_directions(self):
        for refresh in ('default','60'):
            bare=self.plan(refresh)
            active=self.plan(refresh);active['native_argv'][1]+=',agent-mouse=off'
            admitted={'console_refresh':refresh,'console_vdagent':'on'}
            mod.validate_plan_refresh(active,admitted)
            for plan,admission in [(bare,admitted),(active,{'console_refresh':refresh}),
                                   (active,dict(admitted,console_vdagent=True))]:
                with self.assertRaises(ValueError):mod.validate_plan_refresh(plan,admission)

    def test_snapshot_binds_both_directions_and_historical_default(self):
        for setting in ('on','restart'):
            suffix=',x-debug-snapshot-restart=on' if setting=='restart' else ''
            plan=self.plan('60');plan['native_argv'][-1]+=',x-debug-full-refresh=on,x-debug-snapshot=on'+suffix
            admitted={'console_refresh':'60','console_full_refresh':'on','console_snapshot':setting}
            mod.validate_plan_refresh(plan,admitted)
            for value in ('off',None,True,'on' if setting=='restart' else 'restart'):
                bad=dict(admitted,console_snapshot=value)
                with self.assertRaises(ValueError):mod.validate_plan_refresh(plan,bad)
            bare=self.plan('60');bare['native_argv'][-1]+=',x-debug-full-refresh=on'
            with self.assertRaises(ValueError):mod.validate_plan_refresh(bare,admitted)

    def test_full_refresh_is_bound_to_admission_in_both_directions(self):
        plan=self.plan('60');plan['native_argv'][-1]+=',x-debug-full-refresh=on'
        admitted={'console_refresh':'60','console_full_refresh':'on'}
        mod.validate_plan_refresh(plan,admitted)
        for p,a in [(plan,{'console_refresh':'60'}),(self.plan('60'),admitted)]:
            with self.assertRaisesRegex(ValueError,'full refresh differs'):mod.validate_plan_refresh(p,a)

    def test_exact_and_historical_default_bindings(self):
        for admission,refresh in [({},'default'),({'console_refresh':'default'},'default'),({'console_refresh':'60'},'60')]:
            mod.validate_plan_refresh(self.plan(refresh),admission)
        for admission,refresh in [({},'60'),({'console_refresh':'default'},'60'),({'console_refresh':'60'},'default')]:
            with self.assertRaisesRegex(ValueError,'differs from admission'):mod.validate_plan_refresh(self.plan(refresh),admission)
    def test_mismatch_refuses_before_daemon_or_domain_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);admission={'run_id':'a'*32,'deadline_epoch':mod.time.time()+120,'console_refresh':'60'}
            with patch.object(mod,'context',return_value=(directory,admission,'digest')), \
                 patch.object(mod,'dependency_check'),patch.object(mod.os,'getppid',return_value=1), \
                 patch.object(mod.Path,'read_text',return_value='docker-init'), \
                 patch.object(mod.native.configuration.planner,'build_plan',return_value=self.plan()), \
                 patch.object(mod,'start_daemon') as daemon,patch.object(mod.native,'NativeBackend') as backend:
                with self.assertRaisesRegex(ValueError,'differs from admission'):mod.launch([])
                daemon.assert_not_called();backend.assert_not_called()
            failure=json.loads((directory/'planning-failure.json').read_text())
            self.assertEqual(failure['phase'],'before-libvirtd-and-qemu')
    def test_independent_paused_and_running_inspection_refuse_mismatch(self):
        for paused in (True,False):
            with self.subTest(paused=paused),tempfile.TemporaryDirectory() as tmp:
                directory=Path(tmp);(directory/'plan.json').write_text(json.dumps(self.plan()))
                with patch.object(mod,'context',return_value=(directory,{'console_refresh':'60'},'digest')), \
                     patch.dict(os.environ,{},clear=False),patch.object(mod.native.local,'LocalBackend') as backend:
                    with self.assertRaisesRegex(ValueError,'differs from admission'):mod.inspect_domain(paused)
                    backend.assert_not_called()
    def test_exited_proof_refuses_mismatch_before_process_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp)
            for name,value in [('plan',self.plan()),('paused',{}),('resume',{}),('running',{})]:
                (directory/(name+'.json')).write_text(json.dumps(value))
            with patch.object(mod,'context',return_value=(directory,{'console_refresh':'60'},'digest')), \
                 patch.object(mod.handoff,'validate_permit'),patch.object(mod.native.local,'process') as process:
                result=mod.inspect_exited_report()
                self.assertEqual(result,{'exited':False,'refusal':{'stage':'plan-binding','code':'validation-refused'}})
                process.assert_not_called()
