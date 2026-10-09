#!/bin/bash
# Run as the logged-in macOS user. Installs only guest presentation helpers.
set -euo pipefail
[[ $(uname -s) == Darwin && $EUID -ne 0 ]] || { echo 'Run as the logged-in macOS user' >&2; exit 2; }
source_dir=$(cd "$(dirname "$0")" && pwd)
app="$HOME/Applications/Raphael Console.app"
support="$HOME/Library/Application Support/RaphaelGPU/console"
agent="$HOME/Library/LaunchAgents/org.raphaelgpu.console.plist"
# Verify packaged inputs before creating or replacing installed files.
/usr/bin/python3 - "$source_dir" <<'PYVERIFY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]);manifest=root/'console-helper-manifest.json'
if manifest.exists():
    value=json.loads(manifest.read_text())
    expected={'install-console-desktop.sh','console-presenter.m','console-display-layout.m',
              'virtual-display-server.m','console-helper-install.md'}
    if value.get('schema')!=1 or value.get('kind')!='console-helper-source-package' or set(value.get('files',{}))!=expected:
        raise SystemExit('Invalid console source manifest')
    for name,item in value['files'].items():
        path=root/name
        if path.is_symlink() or not path.is_file():raise SystemExit('Invalid source input: '+name)
        data=path.read_bytes()
        if len(data)!=item['bytes'] or hashlib.sha256(data).hexdigest()!=item['sha256']:
            raise SystemExit('Source hash mismatch: '+name)
PYVERIFY
mkdir -p "$app/Contents/MacOS" "$app/Contents/Helpers" "$support" "$(dirname "$agent")"
xcrun clang -O2 -fobjc-arc -fblocks "$source_dir/console-presenter.m" -framework AppKit -framework ScreenCaptureKit -framework IOKit -framework CoreMedia -framework CoreVideo -o "$app/Contents/MacOS/console-presenter"
xcrun clang -O2 -fobjc-arc -fblocks "$source_dir/virtual-display-server.m" -framework AppKit -framework CoreGraphics -o "$app/Contents/Helpers/virtual-display-server"
xcrun clang -O2 -fobjc-arc "$source_dir/console-display-layout.m" -framework Foundation -framework CoreGraphics -o "$app/Contents/Helpers/console-display-layout"
/usr/bin/python3 - "$app" "$agent" "$support" <<'PY'
import plistlib,sys
from pathlib import Path
app,agent,support=map(Path,sys.argv[1:])
(app/'Contents/Info.plist').write_bytes(plistlib.dumps(dict(
 CFBundleIdentifier='org.raphaelgpu.console',CFBundleName='Raphael Console',
 CFBundleExecutable='console-presenter',CFBundlePackageType='APPL',
 CFBundleShortVersionString='0.1.0',CFBundleVersion='1',LSUIElement=True,
 NSScreenCaptureUsageDescription='Show the accelerated macOS desktop in the virtual machine console.')))
agent.write_bytes(plistlib.dumps(dict(Label='org.raphaelgpu.console',
 ProgramArguments=['/bin/bash',str(support/'start-console.sh')],RunAtLoad=True,
 EnvironmentVariables={'RGPU_CONSOLE_CACHE':'wc'},
 StandardOutPath=str(support/'launcher.log'),StandardErrorPath=str(support/'launcher.log'))))
PY
codesign --force --deep --sign - "$app"
codesign --verify --deep --strict "$app"
# Keep the receipt outside the signed bundle: never alter its seal afterwards.
/usr/bin/python3 - "$app" "$source_dir" "$support" <<'PYRECEIPT'
import hashlib,json,platform,subprocess,sys
from pathlib import Path
app,source,support=map(Path,sys.argv[1:])
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def command(*args):return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT).strip()
signature=command('codesign','-d','--verbose=4','-r-',str(app))
if 'CDHash=' not in signature or 'designated =>' not in signature:
    raise SystemExit('Signing identity details missing')
manifest=source/'console-helper-manifest.json'
value=dict(schema=1,kind='console-helper-installed-build',app_identifier='org.raphaelgpu.console',
    architecture=platform.machine(),compiler=command('xcrun','clang','--version'),
    sdk_path=command('xcrun','--show-sdk-path'),sdk_version=command('xcrun','--show-sdk-version'),
    optimization='-O2',signing='ad-hoc',signature_details=signature,
    consent_note='Ad-hoc CDHash changes may require normal Screen Recording consent renewal.',
    source_manifest=json.loads(manifest.read_text()) if manifest.exists() else None,
    sources={name:sha(source/name) for name in ('install-console-desktop.sh','console-presenter.m',
        'console-display-layout.m','virtual-display-server.m')},
    binaries={name:sha(app/'Contents'/name) for name in ('MacOS/console-presenter',
        'Helpers/virtual-display-server','Helpers/console-display-layout')})
target=support/'build-provenance.json';temporary=support/'build-provenance.json.tmp'
temporary.write_text(json.dumps(value,indent=2)+'\n');temporary.replace(target)
PYRECEIPT
cat > "$support/start-console.sh" <<'SH'
#!/bin/bash
set -euo pipefail
# Skip physical-display profiles. This agent never launches or resets the GPU.
ioreg -r -c RaphaelConsole -d 1 | grep -q 'RaphaelConsole' || exit 0
app="$HOME/Applications/Raphael Console.app"
support="$HOME/Library/Application Support/RaphaelGPU/console"
vd=''; awake=''
cleanup() {
 [[ -z "$vd" ]] || kill "$vd" 2>/dev/null || true
 [[ -z "$awake" ]] || kill "$awake" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM INT
caffeinate -dimsu -t 6000 & awake=$!
: >"$support/display.log" # clear previous readiness before the child can start
"$app/Contents/Helpers/virtual-display-server" --serve >"$support/display.log" 2>&1 & vd=$!
for ((i=0;i<200;i++)); do
 grep -q '"phase":"serving"' "$support/display.log" && break
 kill -0 "$vd" 2>/dev/null || exit 3
 sleep .1
done
grep -q '"phase":"serving"' "$support/display.log" || exit 3
"$app/Contents/Helpers/console-display-layout" >"$support/layout.log" 2>&1
"$app/Contents/MacOS/console-presenter" auto 60 6000 >"$support/presenter.log" 2>&1
SH
chmod 700 "$support/start-console.sh"
# Bootstrap separately so installing never disrupts an existing presentation test.
printf 'Installed %s\nStart: launchctl bootstrap gui/%s "%s"\n' "$app" "$(id -u)" "$agent"
printf 'Enable Raphael Console in Privacy & Security > Screen & System Audio Recording if prompted.\n'
