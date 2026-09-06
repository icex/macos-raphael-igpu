#!/usr/bin/env bash
# Replace a kext bundle inside the OpenCore ESP image (run/oc-raw.img) so that
# OpenCore's own Kernel>Add injection -- which lands in the BOOT kernel
# collection, i.e. before the AMD stack starts -- carries the current binary.
#
#   ./esp-kext.sh path/to/Some.kext [more.kext ...]
# Afterwards run ./redeploy.sh, which converts oc-raw.img back into OpenCore.qcow2.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
export MTOOLS_SKIP_CHECK=1
IMG="run/oc-raw.img@@1048576"
[[ -f run/oc-raw.img ]] || { echo "run/oc-raw.img missing; run ./redeploy.sh once first" >&2; exit 1; }
# A guest boot costs ~90s; preflight catches bad constants, unsafe routes and
# non-unique patterns in well under a second. Refuse to ship if it fails.
if [[ -x ./preflight.py && "${SKIP_PREFLIGHT:-0}" != 1 ]]; then
    ./preflight.py >/dev/null || {
        echo "esp-kext: preflight FAILED -- run ./preflight.py to see why" >&2; exit 1; }
fi

for k in "$@"; do
    b="$(basename "$k")"
    # A failed build leaves the bundle without its executable, and mcopy will happily
    # ship the empty directory -- which looks like a successful deploy and wastes a
    # whole boot. Refuse anything that is not a real kext.
    exe="$k/Contents/MacOS/$(basename "$k" .kext)"
    [[ -s "$exe" && -s "$k/Contents/Info.plist" ]] || {
        echo "esp-kext: $b has no executable or Info.plist -- did the build fail?" >&2; exit 1; }
    mdeltree -i "$IMG" "::/EFI/OC/Kexts/$b" >/dev/null 2>&1 || true
    mcopy -s -o -i "$IMG" "$k" "::/EFI/OC/Kexts/"
    echo "  ESP <- $b  ($(du -sh "$k" | cut -f1))"
done
mdir -/ -b -i "$IMG" ::/EFI/OC/Kexts 2>/dev/null | grep -iE 'lilu|raphael' | sed 's/^/    /'
