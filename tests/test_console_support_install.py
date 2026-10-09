import copy
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('support_install',ROOT/'tools/console-support-install.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SupportInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT.parent,prefix="candidate-support-test-");self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name);self.source=self.home/'sources';self.source.mkdir()
        for name in ('console-presenter.m','console-source-token.h'):(self.source/name).write_text(name)
        (self.source/'console-support-launcher.sh').write_bytes((ROOT/'tools/console-support-launcher.sh').read_bytes())
        self.app=self.home/'Applications/Raphael Console.app'
        (self.app/'Contents/MacOS').mkdir(parents=True);(self.app/'Contents/Helpers').mkdir()
        (self.app/'Contents/Info.plist').write_bytes(plistlib.dumps(m.INFO))
        for name in ('MacOS/console-presenter','Helpers/console-display-layout','Helpers/virtual-display-server'):
            (self.app/'Contents'/name).write_text('old sealed '+name)
        self.support=self.home/'Library/Application Support/RaphaelGPU/console';self.support.mkdir(parents=True)
        self.signature='CDHash='+'a'*40+'\ndesignated => identifier org.raphaelgpu.console\n'
        self.receipt=dict(schema=1,kind='console-helper-installed-build',app_identifier='org.raphaelgpu.console',architecture='x86_64',
            sources={n:m.sha(self.source/n) for n in ('console-presenter.m','console-source-token.h')},
            binaries={n:m.sha(self.app/'Contents'/n) for n in ('MacOS/console-presenter','Helpers/console-display-layout')},signature_details=self.signature)
        (self.support/'build-provenance.json').write_text(json.dumps(self.receipt))
        (self.support/'start-console.sh').write_text('old launcher')
        agent=self.home/'Library/LaunchAgents/org.raphaelgpu.console.plist';agent.parent.mkdir(parents=True);agent.write_text('old agent')
        self.transaction=m.SupportTransaction(self.home,self.source,active=lambda app:None,run=self.fake_run)
        self.lock=self.transaction.lock();self.addCleanup(os.close,self.lock)
        self.app_before=m.base.digest(self.app);self.receipt_before=m.base.digest(self.support/'build-provenance.json')
    def fake_run(self,args):return self.signature if '-d' in args else ''
    def build(self,payload,capture):
        (payload/'virtual-display-server').write_text('new holder');(payload/'virtual-display-server').chmod(0o700)
        (payload/'support-provenance.json').write_text(json.dumps(dict(capture=capture)))
    def unchanged(self):
        self.assertEqual(m.base.digest(self.app),self.app_before)
        self.assertEqual(m.base.digest(self.support/'build-provenance.json'),self.receipt_before)
    def test_install_external_payload_preserves_sealed_capture(self):
        stage=self.transaction.install(self.build);self.unchanged()
        result=json.loads((stage/'result.json').read_text())
        self.assertEqual(result['outcome'],'installed');self.assertFalse(self.transaction.journal.exists())
        launcher=(self.support/'start-console.sh').read_text()
        self.assertIn(str(self.transaction.targets[0]),launcher)
        self.assertIn('"$app/Contents/MacOS/console-presenter"',launcher)
        self.assertNotIn('"$app/Contents/Helpers/virtual-display-server"',launcher)
        agent=plistlib.loads(self.transaction.agent.read_bytes())
        self.assertTrue(agent['RunAtLoad']);self.assertNotIn('KeepAlive',agent)
        self.assertEqual(len(result['entries']),3)
        self.assertNotIn(str(self.app),[x['target'] for x in result['entries']])
    def test_publication_failure_rolls_back_without_capture_mutation(self):
        original=m.base.move_verified;calls=[]
        def fail(source,target,digest):
            calls.append((source,target))
            if Path(source).name=='new-1':raise RuntimeError('injected publication failure')
            return original(source,target,digest)
        with patch.object(m.base,'move_verified',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'injected'):self.transaction.install(self.build)
        self.unchanged();self.assertEqual((self.support/'start-console.sh').read_text(),'old launcher')
        self.assertEqual(self.transaction.agent.read_text(),'old agent')
        self.assertEqual(list(self.transaction.helpers.iterdir()),[])
    def test_interrupted_publication_recovers_in_fresh_process_model(self):
        original=m.base.move_verified
        def interrupt(source,target,digest):
            if Path(source).name=='new-1':raise KeyboardInterrupt()
            return original(source,target,digest)
        with patch.object(m.base,'move_verified',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):self.transaction.install(self.build)
        self.assertTrue(self.transaction.journal.exists())
        recovered=m.SupportTransaction(self.home,self.source,active=lambda app:None,run=self.fake_run)
        recovered.recover();self.unchanged()
        self.assertEqual((self.support/'start-console.sh').read_text(),'old launcher')
        self.assertFalse(recovered.journal.exists())
    def test_loaded_helper_refuses_before_build(self):
        def active(app):raise RuntimeError('loaded')
        self.transaction.holder_active=active
        with self.assertRaisesRegex(RuntimeError,'loaded'):self.transaction.install(lambda *args:self.fail('built while loaded'))
        self.unchanged()
    def test_capture_source_or_info_or_binary_or_signature_mismatch_refuses(self):
        originals={self.source/'console-presenter.m':(self.source/'console-presenter.m').read_bytes(),
                   self.app/'Contents/Info.plist':(self.app/'Contents/Info.plist').read_bytes(),
                   self.app/'Contents/MacOS/console-presenter':(self.app/'Contents/MacOS/console-presenter').read_bytes()}
        for path,data in originals.items():
            with self.subTest(path=path):
                path.write_bytes(b'changed')
                with self.assertRaises(RuntimeError):m.validate_capture(self.home,self.source,self.fake_run)
                path.write_bytes(data)
        with self.assertRaisesRegex(RuntimeError,'signing identity'):
            m.validate_capture(self.home,self.source,lambda args:self.signature.replace('a'*40,'b'*40))
    def test_capture_changes_during_build_refuse_publication(self):
        def changed(payload,capture):
            self.build(payload,capture);(self.app/'Contents/Helpers/virtual-display-server').write_text('foreign edit')
        with self.assertRaisesRegex(RuntimeError,'capture app/provenance changed'):self.transaction.install(changed)
        self.assertEqual((self.support/'start-console.sh').read_text(),'old launcher')
        self.assertFalse(self.transaction.journal.exists())
    def test_original_installer_journal_blocks_addon_without_rewriting_it(self):
        self.transaction.original_journal.write_text('retained original journal')
        with self.assertRaisesRegex(RuntimeError,'original installer'):self.transaction.install(self.build)
        self.assertEqual(self.transaction.original_journal.read_text(),'retained original journal');self.unchanged()
    def test_foreign_edit_during_recovery_is_not_overwritten(self):
        original=m.base.move_verified
        def interrupt(source,target,digest):
            if Path(source).name=='new-1':raise KeyboardInterrupt()
            return original(source,target,digest)
        with patch.object(m.base,'move_verified',side_effect=interrupt):
            with self.assertRaises(KeyboardInterrupt):self.transaction.install(self.build)
        (self.support/'start-console.sh').write_text('foreign data')
        with self.assertRaisesRegex(RuntimeError,'Concurrent change'):self.transaction.recover()
        self.assertEqual((self.support/'start-console.sh').read_text(),'foreign data')
        self.assertTrue(self.transaction.journal.exists());self.unchanged()
    def test_generated_launcher_owns_children_and_skips_physical_profile(self):
        payload=self.home/'test payload';payload.mkdir()
        bindir=self.home/'bin';bindir.mkdir()
        ioreg=bindir/'ioreg';ioreg.write_text('#!/bin/sh\necho RaphaelConsole\n');ioreg.chmod(0o700)
        caffeinate=bindir/'caffeinate';caffeinate.write_text('#!/bin/sh\nexec sleep 30\n');caffeinate.chmod(0o700)
        holder=payload/'virtual-display-server'
        holder.write_text('#!/usr/bin/env python3\nimport os,pathlib,socket,sys,time\np=pathlib.Path(sys.argv[sys.argv.index("--control-dir")+1]);p.mkdir(mode=0o700,exist_ok=True)\nos.chdir(p);s=socket.socket(socket.AF_UNIX);s.bind("control.sock")\n(p/"holder.pid").write_text(str(os.getpid()))\nprint(\'{"phase":"serving"}\',flush=True)\ntime.sleep(30)\n')
        holder.chmod(0o700)
        for name in ('MacOS/console-presenter','Helpers/console-display-layout'):
            path=self.app/'Contents'/name;path.write_text('#!/bin/sh\nexit 0\n');path.chmod(0o700)
        launcher=(self.source/'console-support-launcher.sh').read_text().replace('@@PAYLOAD@@',shlex.quote(str(payload)))
        env=dict(os.environ,HOME=str(self.home),PATH=str(bindir)+os.pathsep+os.environ['PATH'])
        result=subprocess.run(['bash','-c',launcher],env=env,capture_output=True,text=True,timeout=6)
        self.assertEqual(result.returncode,0,result.stderr)
        pid=int((self.support/'control/holder.pid').read_text())
        with self.assertRaises(ProcessLookupError):os.kill(pid,0)
        (self.support/'control/holder.pid').unlink()
        ioreg.write_text('#!/bin/sh\nexit 0\n')
        result=subprocess.run(['bash','-c',launcher],env=env,capture_output=True,text=True,timeout=3)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.support/'control/holder.pid').exists())

    def test_payload_and_journal_cannot_escape_fixed_targets(self):
        for bad in ('../escape','x'*64,'a'*63):
            with self.assertRaises(RuntimeError):self.transaction.set_targets(bad)
    def test_launcher_source_change_during_build_refuses(self):
        def changed(payload,capture):
            self.build(payload,capture);(self.source/'console-support-launcher.sh').write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'launcher changed'):self.transaction.install(changed)
        self.unchanged()

if __name__=='__main__':unittest.main()
