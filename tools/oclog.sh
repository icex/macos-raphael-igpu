#!/usr/bin/env bash
# Toggle OpenCore's own log onto the guest serial port, so its kext-patcher
# results ("OCAK: ...") land in run/serial.log and every Kernel>Patch becomes
# directly verifiable instead of inferred from the guest's behaviour.
#
#   ./oclog.sh on    # Target |= 8 (serial), DisplayLevel |= 0x40 (DEBUG_INFO)
#   ./oclog.sh off   # back to Target 3 / stock DisplayLevel
# Then ./redeploy.sh. Do NOT run while autorun.sh is mid-rung: both rewrite config.plist.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
mode="${1:-on}"
python3 - "$mode" <<'PY'
import plistlib, re, sys
mode = sys.argv[1]
p='config.plist'
raw=open(p,'rb').read(); i=raw.index(b'<?xml'); head, d = raw[:i], plistlib.loads(raw[i:])
dbg = d['Misc']['Debug']
if mode == 'on':
    dbg['Target'] = 0x0B            # 1 enable | 2 console | 8 serial
    dbg['DisplayLevel'] = 0x80000042  # ERROR | WARN | INFO  (patcher logs at INFO)
else:
    dbg['Target'] = 3
    dbg['DisplayLevel'] = 0x80000002
open(p,'wb').write(head + plistlib.dumps(d))
print(f"Misc>Debug: Target={dbg['Target']:#x} DisplayLevel={dbg['DisplayLevel']:#x}")
PY
echo "now run ./redeploy.sh ; then: grep -iE 'OCAK|patch' run/serial.log"
