#!/usr/bin/env python3
"""Support-only console addon. Never rewrites/signs the installed capture app.

Publication requires unloaded helpers; bootstrap is a separate caller action.
Original installer journals are handled only by the original installer.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shlex
import stat
import subprocess
import tempfile

SOURCE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('console_install_transaction',SOURCE/'console-install-transaction.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
SOURCES=('virtual-display-server.m','console-display-control.h','console-vdagent-agent.py',
         'console-display-control.py','console-vdagent-monitors.py','console-vdagent-handshake.py',
         'console-support-launcher.sh','console-support-install.py','console-install-transaction.py',
         'console-preferences.py','console-vdagent-clipboard.py','console-clipboard.m')
INFO=dict(CFBundleIdentifier='org.raphaelgpu.console',CFBundleName='Raphael Console',
          CFBundleExecutable='console-presenter',CFBundlePackageType='APPL',
          CFBundleShortVersionString='0.1.0',CFBundleVersion='1',LSUIElement=True,
          NSScreenCaptureUsageDescription='Show the accelerated macOS desktop in the virtual machine console.')

def require(value,message):
    if not value:raise RuntimeError(message)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def signing_fields(text):
    cd=re.findall(r'(?m)^CDHash=([0-9a-f]+)$',text)
    dr=re.findall(r'(?m)^(?:# )?designated => (.+)$',text)
    require(len(cd)==len(dr)==1,'missing or ambiguous capture signing identity')
    return cd[0],dr[0]
def command(args):
    return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT,timeout=60)

def validate_capture(home,source=SOURCE,run=command):
    home=Path(home);app=home/'Applications/Raphael Console.app'
    receipt=home/'Library/Application Support/RaphaelGPU/console/build-provenance.json'
    app_digest=base.digest(app);receipt_digest=base.digest(receipt)
    require(app_digest and receipt_digest,'existing capture installation required')
    data=json.loads(receipt.read_text())
    require(data.get('schema')==1 and data.get('kind')=='console-helper-installed-build' and
            data.get('app_identifier')==INFO['CFBundleIdentifier'] and data.get('architecture')=='x86_64',
            'unsupported capture provenance')
    for name in ('console-presenter.m','console-source-token.h'):
        require((Path(source)/name).is_file() and not (Path(source)/name).is_symlink(),'invalid expected capture source')
        require(data.get('sources',{}).get(name)==sha(Path(source)/name),'capture source identity changed: '+name)
    require((app/'Contents/Info.plist').read_bytes()==plistlib.dumps(INFO),'capture Info.plist differs')
    for name in ('MacOS/console-presenter','Helpers/console-display-layout'):
        require(data.get('binaries',{}).get(name)==sha(app/'Contents'/name),'capture binary identity changed: '+name)
    run(['codesign','--verify','--deep','--strict',str(app)])
    current=run(['codesign','-d','--verbose=4','-r-',str(app)])
    require(signing_fields(current)==signing_fields(data.get('signature_details','')),'capture signing identity changed')
    require(base.digest(app)==app_digest and base.digest(receipt)==receipt_digest,'capture changed during validation')
    return dict(app=app_digest,receipt=receipt_digest,signature=list(signing_fields(current)))

class SupportTransaction(base.Transaction):
    def __init__(self,home,source=SOURCE,active=None,run=command):
        super().__init__(home,active=active or base.refuse_active)
        self.source=Path(source);self.run=run;self.holder_active=self.active
        self.journal=self.control/'console-support-transaction.json'
        self.original_journal=self.control/'console-install-transaction.json'
        self.helpers=self.support/'helpers';self.capture=None
        self.active=self.check_inactive
    def lock(self):
        fd=super().lock() # Same lock serializes original and addon installation.
        try:base.owned_directory(self.helpers)
        except BaseException:os.close(fd);raise
        return fd
    def check_inactive(self,app):
        require(not self.original_journal.exists() and not self.original_journal.is_symlink(),
                'original installer transaction pending; recover it first')
        self.holder_active(app)
        if self.holder_active is base.refuse_active:
            processes=self.run(['/bin/ps','-axo','command='])
            for name in ('console-vdagent-agent.py','console-vdagent-monitors.py','console-clipboard'):
                require(not any(name in row for row in processes.splitlines()),'resize helper still running: '+name)
        if self.capture:
            require(base.digest(self.app)==self.capture['app'] and
                    base.digest(self.support/'build-provenance.json')==self.capture['receipt'],
                    'capture app/provenance changed; no addon mutation permitted')
    def set_targets(self,identity):
        require(isinstance(identity,str) and re.fullmatch('[0-9a-f]{64}',identity),'invalid payload identity')
        self.targets=[self.helpers/identity,self.support/'start-console.sh',self.agent]
    def read_journal(self):
        info=self.journal.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid==os.getuid() and info.st_nlink==1 and
                not info.st_mode&0o077 and info.st_size<=65536,'invalid addon journal')
        value=json.loads(self.journal.read_text())
        require(value.get('kind')=='console-support-addon','wrong addon journal kind')
        capture=value.get('capture',{})
        require(set(capture)=={'app','receipt','signature'} and all(
            isinstance(capture[k],str) and re.fullmatch('[0-9a-f]{64}',capture[k]) for k in ('app','receipt')),
            'invalid capture preconditions')
        self.capture=capture;self.set_targets(value.get('payload'))
        result=super().read_journal()
        self.check_inactive(self.app)
        return result
    def install(self,build):
        require(not self.journal.exists() and not self.journal.is_symlink(),'pending addon transaction; recover first')
        self.capture=validate_capture(self.home,self.source,self.run);self.check_inactive(self.app)
        stage=Path(tempfile.mkdtemp(prefix='.raphael-install-',dir=self.app.parent))
        template=(self.source/'console-support-launcher.sh').read_bytes()
        payload=stage/'payload';payload.mkdir(mode=0o700)
        build(payload,self.capture)
        identity=base.digest(payload);require(identity,'missing addon payload');self.set_targets(identity)
        # Versioned payload publication never replaces an existing payload.
        require(not self.targets[0].exists() and not self.targets[0].is_symlink(),'payload version already installed')
        require((self.source/'console-support-launcher.sh').read_bytes()==template,'launcher changed during build')
        launcher=template.decode()
        require(launcher.count('@@PAYLOAD@@')==1,'invalid launcher template')
        launcher=launcher.replace('@@PAYLOAD@@',shlex.quote(str(self.targets[0])))
        (stage/'launcher').write_text(launcher);(stage/'launcher').chmod(0o700)
        agent=dict(Label='org.raphaelgpu.console',ProgramArguments=['/bin/bash',str(self.targets[1])],RunAtLoad=True,
                   EnvironmentVariables={'RGPU_CONSOLE_CACHE':'wc'},
                   StandardOutPath=str(self.support/'launcher.log'),StandardErrorPath=str(self.support/'launcher.log'))
        (stage/'agent').write_bytes(plistlib.dumps(agent))
        sources=[payload,stage/'launcher',stage/'agent']
        before=[base.digest(p) for p in self.targets];entries=[]
        for i,(source,target,old) in enumerate(zip(sources,self.targets,before)):
            fresh=stage/('new-%d'%i);base.rename(source,fresh);base.sync_tree(fresh)
            entries.append(dict(target=str(target),backup=str(stage/('old-%d'%i)),new=str(fresh),before=old,after=base.digest(fresh)))
        self.check_inactive(self.app)
        require([base.digest(p) for p in self.targets]==before,'addon targets changed before publication')
        value=dict(schema=1,kind='console-support-addon',stage=str(stage),payload=identity,capture=self.capture,entries=entries)
        base.write_json(self.journal,value)
        try:
            for entry in entries:
                self.check_inactive(self.app)
                require(base.digest(entry['target'])==entry['before'],'addon target changed during publication')
                if entry['before'] is not None:base.move_verified(entry['target'],entry['backup'],entry['before'])
                base.move_verified(entry['new'],entry['target'],entry['after'])
            self.check_inactive(self.app);self.finish(value,'installed')
        except Exception:
            self.recover();raise
        return stage

def build_payload(source,payload,capture,run=command):
    source=Path(source);hashes={}
    for name in SOURCES:
        path=source/name
        require(path.is_file() and not path.is_symlink(),'missing/symlinked addon source: '+name)
        hashes[name]=sha(path)
    for name in SOURCES:
        if name.endswith('.py') and name not in ('console-support-install.py','console-install-transaction.py'):
            (payload/name).write_bytes((source/name).read_bytes())
    run(['xcrun','clang','-O2','-fobjc-arc','-fblocks',str(source/'virtual-display-server.m'),
         '-framework','AppKit','-framework','CoreGraphics','-o',str(payload/'virtual-display-server')])
    (payload/'virtual-display-server').chmod(0o700)
    run(['xcrun','clang','-O2','-fobjc-arc',str(source/'console-clipboard.m'),
         '-framework','AppKit','-o',str(payload/'console-clipboard')])
    (payload/'console-clipboard').chmod(0o700)
    require(all(sha(source/name)==digest for name,digest in hashes.items()),'addon source changed during build')
    receipt=dict(schema=1,kind='console-support-addon-build',capture=capture,sources=hashes,
                 binaries={p.name:sha(p) for p in payload.iterdir()},
                 compiler=run(['xcrun','clang','--version']).strip(),sdk=run(['xcrun','--show-sdk-version']).strip(),
                 scope='external support helpers only; capture app and consent are not rewritten')
    base.write_json(payload/'support-provenance.json',receipt)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--recover',action='store_true');a=p.parse_args()
    require(platform.system()=='Darwin' and platform.machine()=='x86_64' and os.getuid()==os.geteuid()!=0,
            'run as logged-in nonroot x86_64 macOS user')
    transaction=SupportTransaction(Path.home());fd=transaction.lock()
    try:
        if a.recover:transaction.recover();print('Addon rolled back; capture app unchanged; no agent started.')
        else:
            stage=transaction.install(lambda payload,capture:build_payload(SOURCE,payload,capture))
            print('Addon installed; capture app unchanged; no agent started. Retained transaction: '+str(stage))
    finally:os.close(fd)
if __name__=='__main__':main()
