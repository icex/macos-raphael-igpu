#!/usr/bin/env python3
"""Edit the OpenCore config.plist: inject device properties and set boot-args.

config.plist here starts with XML comments BEFORE the declaration, which plistlib
refuses, so the leading comment block is split off and restored verbatim.
"""
import plistlib, sys, argparse, re

ap = argparse.ArgumentParser()
ap.add_argument('plist')
ap.add_argument('-o', '--output')
ap.add_argument('--vbios', help='file to inject as ATY,bin_image')
ap.add_argument('--path', action='append', default=[], help='PCI device path (repeatable)')
ap.add_argument('--boot-args', help='replace boot-args entirely')
ap.add_argument('--drop-vbios', action='store_true')
ap.add_argument('--prop', action='append', default=[],
                help='KEY=HEXBYTES -- set a DeviceProperties value (OSData, which is what\n                      AmdTtlServices::getRegistryProperty and AmdRegistryUtilities::\n                      parseOSObjectValue both accept). e.g. PP_PhmUseDummyBackEnd=01000000')
ap.add_argument('--drop-prop', action='append', default=[], help='remove a DeviceProperties key')
ap.add_argument('--show', action='store_true')
ap.add_argument('--kext-patch', action='append', default=[],
                help='id:find_hex:replace_hex:comment -- add a Kernel>Patch entry')
ap.add_argument('--drop-kext-patches', action='store_true',
                help='remove every Kernel>Patch entry whose Comment starts with "RE:"')
a = ap.parse_args()

raw = open(a.plist, 'rb').read()
m = re.search(rb'<\?xml', raw)
head, body = raw[:m.start()], raw[m.start():]
d = plistlib.loads(body)

add = d.setdefault('DeviceProperties', {}).setdefault('Add', {})

if a.drop_vbios:
    for p, props in list(add.items()):
        props.pop('ATY,bin_image', None)
        if not props: del add[p]

if a.vbios:
    rom = open(a.vbios, 'rb').read()
    for p in (a.path or ['PciRoot(0x0)/Pci(0x6,0x0)']):
        add.setdefault(p, {})['ATY,bin_image'] = rom

for spec in a.prop:
    key, val = spec.split('=', 1)
    for p in (a.path or ['PciRoot(0x0)/Pci(0x6,0x0)']):
        add.setdefault(p, {})[key] = bytes.fromhex(val)
for key in a.drop_prop:
    for props in add.values():
        props.pop(key, None)

kp = d.setdefault('Kernel', {}).setdefault('Patch', [])
if a.drop_kext_patches:
    d['Kernel']['Patch'] = kp = [p for p in kp if not str(p.get('Comment','')).startswith('RE:')]
for spec in a.kext_patch:
    ident, find, repl, comment = spec.split(':', 3)
    f, r = bytes.fromhex(find), bytes.fromhex(repl)
    assert len(f) == len(r), f'find/replace length mismatch: {len(f)} vs {len(r)}'
    kp.append({
        'Arch': 'x86_64', 'Base': '', 'Comment': 'RE: ' + comment,
        'Count': 1, 'Enabled': True, 'Find': f, 'Identifier': ident,
        'Limit': 0, 'Mask': b'', 'MaxKernel': '', 'MinKernel': '',
        'Replace': r, 'ReplaceMask': b'', 'Skip': 0,
    })

if a.boot_args:
    d['NVRAM']['Add']['7C436110-AB2A-4BBB-A880-FE41995C9F82']['boot-args'] = a.boot_args

if a.show:
    for p, props in add.items():
        print(f"  {p}")
        for k, v in props.items():
            print(f"      {k} = {type(v).__name__}"
                  + (f" ({len(v)} bytes)" if isinstance(v, bytes) else f" {v!r}"))
    for p in d.get('Kernel', {}).get('Patch', []):
        if str(p.get('Comment','')).startswith('RE:'):
            print(f"  patch {p['Identifier']}  {p['Find'].hex()} -> {p['Replace'].hex()}"
                  f"  enabled={p['Enabled']}  # {p['Comment']}")
    print("  boot-args =",
          d['NVRAM']['Add']['7C436110-AB2A-4BBB-A880-FE41995C9F82'].get('boot-args'))

out = a.output or a.plist
if not a.show or a.output:
    open(out, 'wb').write(head + plistlib.dumps(d))
    print(f"wrote {out} ({len(head)+len(plistlib.dumps(d))} bytes)")
