#!/usr/bin/env bash
# Add or remove a kernel boot argument in config.plist (other args are preserved;
# milestones.py only ever rewrites the rgpu= token, so the two do not fight).
#   ./bootarg.sh add npci=0x2000
#   ./bootarg.sh del npci
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
python3 - "$1" "$2" <<'PY'
import plistlib, re, sys
mode, arg = sys.argv[1], sys.argv[2]
UUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"
raw = open('config.plist','rb').read(); i = raw.index(b'<?xml')
head, d = raw[:i], plistlib.loads(raw[i:])
nv = d['NVRAM']['Add'][UUID]
key = arg.split('=')[0]
ba = re.sub(rf"\s*{re.escape(key)}(=\S+)?\b", "", nv.get('boot-args','')).strip()
if mode == 'add': ba = f"{ba} {arg}".strip()
nv['boot-args'] = ba
open('config.plist','wb').write(head + plistlib.dumps(d))
print("boot-args:", ba)
PY
