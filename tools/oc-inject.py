#!/usr/bin/env python3
"""Enable/disable OpenCore Kernel>Add entries by bundle path.

    ./oc-inject.py on  Lilu.kext RaphaelGPU.kext
    ./oc-inject.py off RaphaelGPU.kext
    ./oc-inject.py list
Operates on config.plist in place (preserving the file's pre-XML header).
"""
import plistlib, sys, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
raw = open('config.plist','rb').read(); i = raw.index(b'<?xml')
head, d = raw[:i], plistlib.loads(raw[i:])
add = d['Kernel']['Add']
mode = sys.argv[1]
if mode == 'list':
    for a in add: print(f"  {'ON ' if a['Enabled'] else 'off'} {a['BundlePath']}")
    raise SystemExit
want = mode == 'on'
for name in sys.argv[2:]:
    hits = [a for a in add if a['BundlePath'] == name]
    assert hits, f"{name} not in Kernel>Add"
    for a in hits: a['Enabled'] = want
    print(f"  {name}: Enabled={want}")
open('config.plist','wb').write(head + plistlib.dumps(d))
