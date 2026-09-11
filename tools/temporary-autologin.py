#!/usr/bin/env python3
"""Arm or restore a short-lived, reboot-safe macOS automatic-login transaction.

This tool does not launch a VM.  It requires an already supervised guest and an
existing root gx command agent.  The password is streamed through an exact-CID,
memory-only one-shot server and is never included in a command or result.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import stat
import subprocess
import sys
import time
import uuid


CID_RE = re.compile(r'[0-9a-f]{64}')
NONCE_RE = re.compile(r'[0-9a-f]{32}')
USER_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_.-]{0,63}')
PORT = 8890

ONE_SHOT_SERVER = r'''import http.server,os,sys
raw=sys.stdin.buffer.read()
line,sep,body=raw.partition(b"\n")
if not sep: raise SystemExit(2)
token=line.decode("ascii")
class H(http.server.BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path != "/secret/" + token:
   self.send_error(404); return
  if getattr(self.server,"used",False):
   self.send_error(410); return
  self.server.used=True
  self.send_response(200); self.send_header("Content-Length",str(len(body)))
  self.end_headers(); self.wfile.write(body)
 def log_message(self,*args): pass
class S(http.server.HTTPServer): allow_reuse_address=False
s=S(("0.0.0.0",8890),H); s.timeout=90
print("READY "+str(os.getpid()),flush=True); s.handle_request()
'''

ENCODER_C = r'''#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
int main(int argc,char **argv) {
 static const uint8_t key[]={0x7d,0x89,0x52,0x23,0xd2,0xbc,0xdd,0xea,0xa3,0xb9,0x1f};
 uint8_t in[1025],out[1036]; size_t n=0,m,i; int fd;
 if(argc!=2) return 64;
 while(n<sizeof(in) && (m=fread(in+n,1,sizeof(in)-n,stdin))>0) n+=m;
 if(ferror(stdin)||n==0||n>1024) return 65;
 if(memchr(in,0,n)) return 66;
 if(in[n-1]=='\n') n--;
 if(n && in[n-1]=='\r') n--;
 if(n==0) return 67;
 m=((n+12)/12)*12;
 for(i=0;i<m;i++) out[i]=(i<n?in[i]:0)^key[i%11];
 fd=open(argv[1],O_WRONLY|O_CREAT|O_EXCL,0600); if(fd<0) return 68;
 if(write(fd,out,m)!=(ssize_t)m||fsync(fd)||close(fd)) return 69;
 memset(in,0,sizeof(in)); memset(out,0,sizeof(out)); return 0;
}'''


def read_secret(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError('credential must be a regular non-symlink file')
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise ValueError('credential mode must be 0600')
    data = bytearray(path.read_bytes())
    if data.endswith(b'\n'):
        del data[-1:]
    if data.endswith(b'\r'):
        del data[-1:]
    if not data or len(data) > 1024 or b'\0' in data:
        raise ValueError('credential must be 1..1024 non-NUL bytes')
    return data


def supervised_cid(run, now=None):
    row = json.loads((run / 'supervision.json').read_text())
    cid = row.get('cid')
    if not isinstance(cid, str) or not CID_RE.fullmatch(cid):
        raise ValueError('supervision lacks an exact full container ID')
    deadline = row.get('deadline_epoch')
    if type(deadline) not in (int, float) or deadline <= (time.time() if now is None else now):
        raise ValueError('supervision deadline is absent or expired')
    return cid


def secret_server_argv(cid):
    if not CID_RE.fullmatch(cid):
        raise ValueError('invalid container ID')
    return ['docker', 'exec', '-i', cid, 'python3', '-c', ONE_SHOT_SERVER]


def restore_script(nonce, expiry):
    if not NONCE_RE.fullmatch(nonce) or type(expiry) is not int:
        raise ValueError('invalid restoration identity')
    return f'''#!/bin/sh
set -u
state=/var/db/rgpu-autologin-{nonce}
daemon=/Library/LaunchDaemons/org.raphaelgpu.autologin-{nonce}.plist
test "${{1:-}}" = force || test "$(/bin/date +%s)" -ge {expiry} || exit 0
failed=0
/bin/mkdir "$state/restore.lock" 2>/dev/null || exit 75
trap '/bin/rmdir "$state/restore.lock"' EXIT HUP INT TERM
restore_one() {{
 target=$1; name=$2
 if test -f "$state/$name.present"; then
  /usr/bin/ditto --rsrc "$state/$name.backup" "$target" || failed=1
  /usr/bin/cmp -s "$state/$name.backup" "$target" || failed=1
  test "$(/usr/bin/stat -f '%Su:%Sg:%Lp' "$state/$name.backup")" = "$(/usr/bin/stat -f '%Su:%Sg:%Lp' "$target")" || failed=1
 else
  /bin/rm -f "$target" || failed=1
  test ! -e "$target" || failed=1
 fi
}}
restore_one /Library/Preferences/com.apple.loginwindow.plist loginwindow
restore_one /etc/kcpassword kcpassword
/usr/bin/killall cfprefsd >/dev/null 2>&1 || true
if test "$failed" -ne 0; then
 /usr/bin/touch "$state/RESTORE_FAILED"
 exit 1
fi
/usr/bin/touch "$state/RESTORED"
exit 0
'''


def _daemon_plist(nonce, script):
    label = f'org.raphaelgpu.autologin-{nonce}'
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>Label</key><string>{label}</string>
<key>ProgramArguments</key><array><string>{script}</string></array>
<key>RunAtLoad</key><true/><key>StartInterval</key><integer>30</integer>
</dict></plist>'''


def arm_command(nonce, user, expiry, port=PORT):
    if not NONCE_RE.fullmatch(nonce) or not USER_RE.fullmatch(user):
        raise ValueError('invalid nonce or account')
    state = f'/var/db/rgpu-autologin-{nonce}'
    script = state + '/restore.sh'
    daemon = f'/Library/LaunchDaemons/org.raphaelgpu.autologin-{nonce}.plist'
    restore64 = base64.b64encode(restore_script(nonce, expiry).encode()).decode()
    daemon64 = base64.b64encode(_daemon_plist(nonce, script).encode()).decode()
    encoder64 = base64.b64encode(ENCODER_C.encode()).decode()
    q = shlex.quote
    # Trap calls the already-installed rollback for every failure after backup.
    action = f'''test "$(/usr/bin/id -u)" = 0 &&
test "$(/bin/date +%s)" -le {expiry} &&
permit="$(/usr/bin/curl -fsS --max-time 3 http://10.0.2.2:8889/metal-permit-{nonce})" && test "$permit" = {nonce} &&
test "$(/usr/bin/dscl . -read /Users/{q(user)} RecordName 2>/dev/null | /usr/bin/awk '{{print $2}}')" = {q(user)} &&
uid="$(/usr/bin/dscl . -read /Users/{q(user)} UniqueID | /usr/bin/awk '{{print $2}}')" && test "$uid" -ge 500 &&
test "$(/usr/bin/fdesetup status)" = "FileVault is Off." &&
enrollment="$(/usr/bin/profiles status -type enrollment 2>&1)" &&
/usr/bin/printf '%s\\n' "$enrollment" | /usr/bin/grep -q "Enrolled via DEP: No" &&
/usr/bin/printf '%s\\n' "$enrollment" | /usr/bin/grep -q "MDM enrollment: No" &&
test -z "$(/usr/bin/find /var/db -maxdepth 1 -name 'rgpu-autologin-*' -print -quit)" &&
test ! -e {state} && test ! -e {daemon} &&
( test ! -e /Library/Preferences/com.apple.loginwindow.plist || ( test -f /Library/Preferences/com.apple.loginwindow.plist && test ! -L /Library/Preferences/com.apple.loginwindow.plist ) ) &&
( test ! -e /etc/kcpassword || ( test -f /etc/kcpassword && test ! -L /etc/kcpassword ) ) &&
/bin/mkdir -m 700 {state} && /usr/sbin/chown root:wheel {state} &&
( test ! -e /Library/Preferences/com.apple.loginwindow.plist || ( /usr/bin/ditto --rsrc /Library/Preferences/com.apple.loginwindow.plist {state}/loginwindow.backup && /usr/bin/touch {state}/loginwindow.present ) ) &&
( test ! -e /etc/kcpassword || ( /usr/bin/ditto --rsrc /etc/kcpassword {state}/kcpassword.backup && /usr/bin/touch {state}/kcpassword.present ) ) &&
/usr/bin/printf '%s' {q(restore64)} | /usr/bin/base64 -D > {script} && /bin/chmod 700 {script} && /usr/sbin/chown root:wheel {script} &&
/usr/bin/printf '%s' {q(daemon64)} | /usr/bin/base64 -D > {daemon} && /bin/chmod 600 {daemon} && /usr/sbin/chown root:wheel {daemon} &&
/bin/launchctl bootstrap system {daemon} && /bin/launchctl print system/org.raphaelgpu.autologin-{nonce} >/dev/null &&
( armed=0; trap 'test "$armed" = 1 || {script} force' EXIT HUP INT TERM;
 /usr/bin/printf '%s' {q(encoder64)} | /usr/bin/base64 -D > {state}/encoder.c &&
 /usr/bin/xcrun clang -Os -Wall -Wextra -Werror {state}/encoder.c -o {state}/encoder &&
 test "$(/bin/date +%s)" -le {expiry} &&
 /bin/bash -o pipefail -c '/usr/bin/curl -fsS --max-time 20 http://10.0.2.2:{int(port)}/secret/{nonce} | {state}/encoder {state}/kcpassword.new' &&
 /usr/bin/defaults write /Library/Preferences/com.apple.loginwindow autoLoginUser -string {q(user)} &&
 /bin/chmod 600 /Library/Preferences/com.apple.loginwindow.plist && /usr/sbin/chown root:wheel /Library/Preferences/com.apple.loginwindow.plist &&
 /bin/mv -f {state}/kcpassword.new /etc/kcpassword && /bin/chmod 600 /etc/kcpassword && /usr/sbin/chown root:wheel /etc/kcpassword &&
 ( /usr/bin/killall cfprefsd >/dev/null 2>&1 || true ) &&
 test -f /etc/kcpassword && test "$(/usr/bin/defaults read /Library/Preferences/com.apple.loginwindow autoLoginUser)" = {q(user)} && armed=1 ) &&
/usr/bin/printf 'RGPU_AUTOLOGIN {{"schema":1,"nonce":"{nonce}","action":"armed","account":"{user}","uid":%s,"recovery_installed":true,"restoration_verified":false}}\\n' "$uid" '''
    return f'( {action}; result=$?; printf "RGPU_EXIT {nonce} %s\\n" "$result" )'


def restore_command(nonce):
    if not NONCE_RE.fullmatch(nonce):
        raise ValueError('invalid nonce')
    script = f'/var/db/rgpu-autologin-{nonce}/restore.sh'
    daemon = f'/Library/LaunchDaemons/org.raphaelgpu.autologin-{nonce}.plist'
    action = (f'test "$(/usr/bin/id -u)" = 0 && test -x {script} && {script} force && '
              f'test -f /var/db/rgpu-autologin-{nonce}/RESTORED && '
              f'/bin/launchctl bootout system/org.raphaelgpu.autologin-{nonce} && '
              f'/bin/rm -f {daemon} && /bin/rm -rf /var/db/rgpu-autologin-{nonce} && '
              f'/usr/bin/printf \'RGPU_AUTOLOGIN {{"schema":1,"nonce":"{nonce}",'
              f'"action":"restored","account":"","uid":0,"recovery_installed":false,'
              f'"restoration_verified":true}}\\n\'')
    return f'( {action}; result=$?; printf "RGPU_EXIT {nonce} %s\\n" "$result" )'


def validate_receipt(output, nonce, action):
    rows = [x.removeprefix('RGPU_AUTOLOGIN ') for x in output.splitlines()
            if x.startswith('RGPU_AUTOLOGIN ')]
    exits = re.findall(r'^RGPU_EXIT '+re.escape(nonce)+r' (\d+)$', output, re.M)
    if len(rows) != 1 or exits != ['0']:
        raise ValueError('incomplete or unsuccessful guest receipt')
    row = json.loads(rows[0])
    keys = {'schema','nonce','action','account','uid','recovery_installed','restoration_verified'}
    if set(row) != keys or row['schema'] != 1 or row['nonce'] != nonce or row['action'] != action:
        raise ValueError('invalid guest receipt')
    if type(row['uid']) is not int or type(row['recovery_installed']) is not bool or type(row['restoration_verified']) is not bool:
        raise ValueError('invalid guest receipt types')
    if action == 'armed' and (row['uid'] < 500 or not row['account'] or
                              not row['recovery_installed'] or row['restoration_verified']):
        raise ValueError('invalid armed receipt semantics')
    if action == 'restored' and (row['uid'] != 0 or row['account'] or
                                 row['recovery_installed'] or not row['restoration_verified']):
        raise ValueError('invalid restored receipt semantics')
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', type=Path, required=True)
    parser.add_argument('--user', default=None)
    parser.add_argument('--ttl', type=int, default=300)
    parser.add_argument('--restore', metavar='NONCE')
    args = parser.parse_args()
    vm = args.vm_dir.resolve()
    if not (vm/'gx').is_file() or not (vm/'run').is_dir():
        parser.error('--vm-dir must contain gx and run/')
    cid = supervised_cid(vm/'run')
    inspect = subprocess.run(['docker','inspect','-f','{{.Id}} {{.State.Running}}',cid],
                             text=True,capture_output=True,timeout=5)
    if inspect.returncode or inspect.stdout.strip() != cid+' true':
        raise RuntimeError('exact supervised container is not running')
    metal = __import__('importlib.util').util.spec_from_file_location('metal_test', Path(__file__).with_name('metal-test.py'))
    mt = __import__('importlib.util').util.module_from_spec(metal); metal.loader.exec_module(mt)
    if args.restore:
        nonce = args.restore
        command = restore_command(nonce)
        proc = mt.run_guest_command(vm, command, nonce, dict(os.environ,GX_TIMEOUT='45'), timeout=55, execution_grace=0)
        receipt = validate_receipt(proc.stdout, nonce, 'restored')
    else:
        if not args.user or not USER_RE.fullmatch(args.user) or not 60 <= args.ttl <= 900:
            parser.error('--user is required and --ttl must be 60..900 seconds')
        secret = read_secret(vm/'.guestpw')
        nonce = uuid.uuid4().hex; expiry = int(time.time()) + args.ttl
        server = subprocess.Popen(secret_server_argv(cid), stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        server_pid = None
        try:
            server.stdin.write(nonce.encode()+b'\n'+secret); server.stdin.close()
            selector = selectors.DefaultSelector(); selector.register(server.stdout, selectors.EVENT_READ)
            if not selector.select(timeout=5):
                raise RuntimeError('one-shot credential service startup timed out')
            ready = server.stdout.readline().decode('ascii', errors='replace').strip().split()
            if len(ready) != 2 or ready[0] != 'READY' or not ready[1].isdigit():
                raise RuntimeError('one-shot credential service failed to start')
            server_pid = int(ready[1])
            command = arm_command(nonce,args.user,expiry)
            proc = mt.run_guest_command(vm,command,nonce,dict(os.environ,GX_TIMEOUT='70'),timeout=80,execution_grace=0)
            receipt = validate_receipt(proc.stdout,nonce,'armed')
        finally:
            for i in range(len(secret)): secret[i]=0
            if server.poll() is None and server_pid is not None:
                subprocess.run(['docker','exec',cid,'kill','-TERM',str(server_pid)],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3)
            if server.poll() is None: server.terminate()
            try: server.wait(timeout=3)
            except subprocess.TimeoutExpired: server.kill(); server.wait()
    print(json.dumps(receipt,sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
