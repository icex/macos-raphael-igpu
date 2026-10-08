#!/bin/bash
# Run as the logged-in macOS user. Installs only guest presentation helpers.
set -euo pipefail
[[ $(uname -s) == Darwin && $EUID -ne 0 ]] || { echo 'Run as the logged-in macOS user' >&2; exit 2; }
source_dir=$(cd "$(dirname "$0")" && pwd)
app="$HOME/Applications/Raphael Console.app"
support="$HOME/Library/Application Support/RaphaelGPU/console"
agent="$HOME/Library/LaunchAgents/org.raphaelgpu.console.plist"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Helpers" "$support" "$(dirname "$agent")"
xcrun clang -fobjc-arc -fblocks "$source_dir/console-presenter.m" -framework AppKit -framework ScreenCaptureKit -framework IOKit -framework CoreMedia -framework CoreVideo -o "$app/Contents/MacOS/console-presenter"
xcrun clang -fobjc-arc -fblocks "$source_dir/virtual-display-server.m" -framework AppKit -framework CoreGraphics -o "$app/Contents/Helpers/virtual-display-server"
xcrun clang -fobjc-arc "$source_dir/console-display-layout.m" -framework Foundation -framework CoreGraphics -o "$app/Contents/Helpers/console-display-layout"
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
