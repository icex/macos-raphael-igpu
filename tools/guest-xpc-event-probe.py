#!/usr/bin/env python3
"""Build/run the bounded XPC event probe in an already admitted interactive guest."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shlex
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--vm-dir', type=Path, required=True)
p.add_argument('--results', type=Path, required=True)
p.add_argument('--mode', choices=['compile', 'transport', 'one', 'rounds'], required=True)
a = p.parse_args()
r = a.results
ready = json.loads((r / 'interactive-ready.json').read_text())
assert time.time() < ready['deadline_epoch'] - 250 and not (r / 'stop-requested').exists()
probe = json.loads((r / 'probe.json').read_text())
rows = [json.loads(l.split(' ', 1)[1]) for l in probe['output'].splitlines()
        if l.startswith('RGPU_DESKTOP_METAL_RESULT ')]
assert len(rows) == 1 and rows[0]['passed'] and rows[0]['run_id'] == ready['run_id']
source = (ROOT / 'tests/iosurface_xpc_event_probe.m').read_bytes()
sha = hashlib.sha256(source).hexdigest()
app = '/var/tmp/rgpu-event-' + sha[:12] + '.app'
helper = app + '/Contents/XPCServices/Worker.xpc'
exe = app + '/Contents/MacOS/Probe'
nonce = uuid.uuid4().hex
q = shlex.quote

def put(data, path):
    return 'printf %s ' + q(base64.b64encode(data).decode()) + ' | base64 -D > ' + q(path)

if a.mode == 'compile':
    host_info = {'CFBundleIdentifier': 'org.raphael.GPUEventProbe',
                 'CFBundleExecutable': 'Probe', 'CFBundlePackageType': 'APPL',
                 'CFBundleVersion': '1', 'LSBackgroundOnly': True}
    helper_info = {'CFBundleIdentifier': 'org.raphael.GPUEventProbe.Worker',
                   'CFBundleExecutable': 'Worker', 'CFBundlePackageType': 'XPC!',
                   'CFBundleVersion': '1', 'XPCService': {'ServiceType': 'Application'}}
    commands = [f'mkdir -p {q(app + "/Contents/MacOS")} {q(helper + "/Contents/MacOS")}',
                put(source, app + '/probe.m'),
                put(plistlib.dumps(host_info), app + '/Contents/Info.plist'),
                put(plistlib.dumps(helper_info), helper + '/Contents/Info.plist')]
    for service, path in [(0, exe), (1, helper + '/Contents/MacOS/Worker')]:
        commands.append(f'xcrun clang -fobjc-arc -O2 -Wall -Wextra -DRGPU_XPC_SERVICE={service} '
                        f'{q(app + "/probe.m")} -framework Foundation -framework Metal -framework IOSurface -o {q(path)}')
    commands += [f'codesign --force --sign - {q(helper)}', f'codesign --force --sign - {q(app)}']
    command = ' && '.join(commands)
else:
    count = {'transport': 0, 'one': 1, 'rounds': 32}[a.mode]
    if a.mode != 'transport':
        prior = json.loads((r / 'xpc-transport-summary.json').read_text())
        assert prior['source_sha256'] == sha and prior['result']['passed']
    if a.mode == 'rounds':
        prior = json.loads((r / 'xpc-one-summary.json').read_text())
        assert prior['source_sha256'] == sha and prior['result']['passed']
    command = f'{q(exe)} {int(rows[0]["registry_id"])} {count}'
command += f'; rc=$?; echo XPC_EXIT_{nonce}=$rc'
label = 'xpc-' + a.mode
assert not (r / (label + '-command.json')).exists(), 'Do not overwrite prior attempts'
(r / (label + '-command.json')).write_text(json.dumps({
    'command': command, 'source_sha256': sha, 'run_id': ready['run_id'],
    'nonce': nonce, 'start_epoch': time.time()}, indent=2) + '\n')
result = subprocess.run([str(a.vm_dir / 'gx'), command], stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, timeout=220,
                        env=os.environ | {'GX_TIMEOUT': '210'})
(r / (label + '-output.txt')).write_bytes(result.stdout)
print(result.stdout.decode(errors='replace')[-6000:])
assert result.returncode == 0 and f'XPC_EXIT_{nonce}=0'.encode() in result.stdout
if a.mode != 'compile':
    records = [json.loads(l) for l in result.stdout.decode().splitlines() if l.startswith('{')]
    final = [d for d in records if d.get('phase') == 'result']
    assert len(final) == 1 and final[0]['passed'] and final[0]['rounds'] == count
    assert final[0]['bad_pixels'] == 0 and final[0]['pixels'] == count * 1003 * 769
    assert final[0]['helper_shutdown_ack'] and final[0]['helper_absent']
    rounds = [d for d in records if d.get('phase') == 'round']
    assert len(rounds) == count and all(d['passed'] and d['bad_pixels'] == 0 for d in rounds)
    (r / (label + '-summary.json')).write_text(json.dumps({
        'source_sha256': sha, 'run_id': ready['run_id'], 'result': final[0],
        'records': records}, indent=2) + '\n')
