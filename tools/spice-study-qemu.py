#!/usr/bin/env python3
"""Load one isolated study library for bounded software QEMU fixtures only."""
import hashlib
import json
import os
from pathlib import Path
import sys


def validate(argv):
    flags={'-S','-nodefaults','-no-user-config','-no-reboot'}
    pairs={'-L','-machine','-m','-vga','-display','-nic','-device','-qtest',
           '-qtest-log','-qmp','-spice','-bios','-trace'}
    values={};i=0
    while i<len(argv):
        key=argv[i];i+=1
        if key in flags:values.setdefault(key,[]).append(True);continue
        if key not in pairs or i==len(argv):raise ValueError('non-fixture QEMU option')
        value=argv[i];i+=1;values.setdefault(key,[]).append(value)
    if values.get('-machine')!=['q35,accel=tcg'] or values.get('-nodefaults')!=[True]:
        raise ValueError('software TCG/no-defaults profile required')
    if values.get('-display')!=['none'] or values.get('-vga')!=['none']:
        raise ValueError('no physical display profile required')
    if values.get('-nic', ['none'])!=['none']:raise ValueError('network device refused')
    for device in values.get('-device',[]):
        parts=device.split(',')
        if parts[0]!='bochs-display' or any(p not in {
                'id=console','addr=02.0','vgamem=64M','x-debug-snapshot=on',
                'x-debug-full-refresh=on','x-debug-full-refresh=off'} for p in parts[1:]):
            raise ValueError('only explicit software Bochs fixture device admitted')
    if len(values.get('-device',[]))!=1:raise ValueError('one software device required')
    for endpoint in values.get('-spice',[]):
        if not endpoint.startswith('unix=on,addr='):raise ValueError('only local Unix SPICE admitted')
    return True


def main():
    config=json.loads(Path(sys.argv[1]).read_text());argv=sys.argv[2:]
    validate(argv)
    for key in ('qemu','library'):
        path=Path(config[key])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=config[key+'_sha256']:
            raise ValueError('study binary identity changed')
    env=dict(os.environ)
    if env.get('LD_PRELOAD') or env.get('LD_AUDIT'):
        raise ValueError('injected loader hook refused')
    # Do not inherit an unrelated library search path.
    env['LD_LIBRARY_PATH']=str(Path(config['library']).parent)
    os.execve(config['qemu'],[config['qemu'],*argv],env)

if __name__=='__main__':main()
