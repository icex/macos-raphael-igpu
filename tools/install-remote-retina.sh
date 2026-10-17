#!/bin/sh
set -eu

if [ "$(uname -s)" != Darwin ]; then
    echo "remote-retina installer requires macOS" >&2
    exit 1
fi
if [ "$(id -u)" -eq 0 ]; then
    echo "run this installer as the logged-in user, not root" >&2
    exit 1
fi
CONSOLE_UID=$(stat -f %u /dev/console)
[ "$(id -u)" = "$CONSOLE_UID" ] || {
    echo "run this installer from the current console user's session" >&2
    exit 1
}

ACTION=${1:-}
case "$ACTION" in
    --install|--uninstall|--status) ;;
    *) echo "usage: $0 --install|--uninstall|--status" >&2; exit 2 ;;
esac

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE=$SCRIPT_DIR/remote-retina.m
APP_DIR="${HOME}/Library/Application Support/RaphaelGPU/remote-retina"
BINARY=$APP_DIR/remote-retina
PLIST=${HOME}/Library/LaunchAgents/org.raphaelgpu.remote-retina.plist
LABEL=org.raphaelgpu.remote-retina
DISABLED_PLIST=$PLIST.disabled-black-screen
TMP_FILE=
TMP_BINARY=
cleanup() {
    [ -z "$TMP_FILE" ] || rm -f -- "$TMP_FILE"
    [ -z "$TMP_BINARY" ] || rm -f -- "$TMP_BINARY"
}
trap cleanup EXIT HUP INT TERM

check_owned_paths() {
    [ ! -L "$BINARY" ] || { echo "refusing symlink binary: $BINARY" >&2; exit 1; }
    [ ! -L "$PLIST" ] || { echo "refusing symlink plist: $PLIST" >&2; exit 1; }
    owned_plist=$PLIST
    if [ ! -e "$PLIST" ] && [ -e "$DISABLED_PLIST" ]; then owned_plist=$DISABLED_PLIST; fi
    [ ! -L "$owned_plist" ] || { echo "refusing symlink ownership receipt" >&2; exit 1; }
    if [ -e "$owned_plist" ]; then
        command -v xcrun >/dev/null 2>&1 || { echo "xcrun is required" >&2; exit 1; }
        xcrun python3 - "$owned_plist" "$BINARY" <<'PY'
import plistlib
import sys

path, binary = sys.argv[1:]
try:
    with open(path, 'rb') as source:
        data = plistlib.load(source)
except Exception as error:
    raise SystemExit('cannot validate existing LaunchAgent: ' + str(error))
if (data.get('Label') != 'org.raphaelgpu.remote-retina' or
        data.get('ProgramArguments') != [binary, '--configure']):
    raise SystemExit('existing LaunchAgent is not owned by remote-retina')
PY
    fi
}

check_owned_paths
if [ -e "$BINARY" ] && [ ! -e "$PLIST" ] && [ ! -e "$DISABLED_PLIST" ]; then
    echo "refusing an existing binary without an owned LaunchAgent: $BINARY" >&2
    exit 1
fi

if [ "$ACTION" = --status ]; then
    [ -x "$BINARY" ] || { echo "remote-retina is not installed" >&2; exit 1; }
    exec "$BINARY" --status
fi

if [ "$ACTION" = --uninstall ]; then
    if command -v launchctl >/dev/null 2>&1; then
        launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || :
    fi
    if [ -x "$BINARY" ]; then
        "$BINARY" --low-resolution || echo "could not select low resolution; login default will still be removed" >&2
    fi
    rm -f -- "$PLIST" "$BINARY"
    exit 0
fi

[ -f "$SOURCE" ] || { echo "missing adjacent source: $SOURCE" >&2; exit 1; }
command -v xcrun >/dev/null 2>&1 || { echo "xcrun is required" >&2; exit 1; }
mkdir -p -- "$APP_DIR" "$(dirname -- "$PLIST")"

tmpbin=$(mktemp "$APP_DIR/.remote-retina.binary.XXXXXX")
TMP_BINARY=$tmpbin
xcrun clang -fobjc-arc -fblocks -O2 -Wall -Wextra -Werror \
    -framework Foundation -framework CoreGraphics -framework AppKit \
    "$SOURCE" -o "$tmpbin"
chmod 755 "$tmpbin"
"$tmpbin" --configure

stamp=$(date +%Y%m%d%H%M%S).$$
had_binary=0
had_plist=0
if [ -e "$BINARY" ]; then
    had_binary=1
    cp -p -- "$BINARY" "$BINARY.bak.$stamp"
fi
if [ -e "$PLIST" ]; then
    had_plist=1
    cp -p -- "$PLIST" "$PLIST.bak.$stamp"
fi

tmpplist=$(mktemp "$APP_DIR/.remote-retina.plist.XXXXXX")
TMP_FILE=$tmpplist
PLIST_PATH=$PLIST BINARY_PATH=$BINARY LABEL=$LABEL TMP_PLIST_PATH=$tmpplist xcrun python3 - <<'PY'
import os
import plistlib
from pathlib import Path

path = Path(os.environ['PLIST_PATH'])
binary = os.environ['BINARY_PATH']
label = os.environ['LABEL']
data = {
    'Label': label,
    'ProgramArguments': [binary, '--configure'],
    'RunAtLoad': True,
    'StandardOutPath': str(Path(binary).with_name('remote-retina.stdout.log')),
    'StandardErrorPath': str(Path(binary).with_name('remote-retina.stderr.log')),
}
with open(os.environ['TMP_PLIST_PATH'], 'wb') as output:
    plistlib.dump(data, output, fmt=plistlib.FMT_XML, sort_keys=False)
PY

check_owned_paths
mv -f -- "$tmpbin" "$BINARY"
TMP_BINARY=
mv -f -- "$tmpplist" "$PLIST"
TMP_FILE=

# Replace only this label if an earlier copy is loaded, then publish our agent.
launchctl bootout "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || :
if ! launchctl bootstrap "gui/$(id -u)" "$PLIST"; then
    rm -f -- "$PLIST" "$BINARY"
    if [ "$had_binary" -eq 1 ]; then cp -p -- "$BINARY.bak.$stamp" "$BINARY"; fi
    if [ "$had_plist" -eq 1 ]; then
        cp -p -- "$PLIST.bak.$stamp" "$PLIST"
        launchctl bootstrap "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || :
    fi
    exit 1
fi
