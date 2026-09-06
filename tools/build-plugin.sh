#!/usr/bin/env bash
# Build RaphaelGPU.kext only (no guest install, no AuxKC relink).
# Prints the version it stamped so both delivery paths can quote it.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
NEXT=$(( $(cat .plugin-build 2>/dev/null || echo 0) + 1 ))
echo "$NEXT" > .plugin-build
VER="1.0.$NEXT"
# build-kext.sh does not exit nonzero on a compile error, and the Info.plist step
# below would then happily stamp a new version onto the PREVIOUS binary. Delete the
# executable first so its absence is the failure signal.
# Regenerate the embedded RLC firmware header from /lib/firmware before every build, so
# the bytes can never drift from what mkrlcfw.py reports. Not fatal if absent: the
# plugin compiles without RLC substitution via __has_include.
./mkrlcfw.py >/dev/null || echo "build-plugin: mkrlcfw failed; building without RLC firmware" >&2
EXE=build/out/RaphaelGPU/RaphaelGPU.kext/Contents/MacOS/RaphaelGPU
rm -f "$EXE"
(cd build && ./build-kext.sh src-rgpu RaphaelGPU as.rgpu.RaphaelGPU "$VER") 2>&1 | tail -3
[[ -s "$EXE" ]] || { echo "build-plugin: compile failed, $EXE not produced" >&2; exit 1; }
python3 - "$VER" <<'PY'
import plistlib, sys
VER = sys.argv[1]
p='build/out/RaphaelGPU/RaphaelGPU.kext/Contents/Info.plist'
d={'CFBundleDevelopmentRegion':'en','CFBundleExecutable':'RaphaelGPU',
   'CFBundleIdentifier':'as.rgpu.RaphaelGPU','CFBundleInfoDictionaryVersion':'6.0',
   'CFBundleName':'RaphaelGPU','CFBundlePackageType':'KEXT','CFBundleSignature':'????',
   'CFBundleShortVersionString':VER,'CFBundleVersion':VER,
   'CFBundleSupportedPlatforms':['MacOSX'],'OSBundleRequired':'Root',
   'IOKitPersonalities':{'as.rgpu.RaphaelGPU':{
       'CFBundleIdentifier':'as.rgpu.RaphaelGPU','IOClass':'RaphaelGPU',
       'IOMatchCategory':'RaphaelGPU','IOProviderClass':'IOResources',
       'IOResourceMatch':'IOKit'}},
   'OSBundleLibraries':{'as.vit9696.Lilu':'1.2.0','com.apple.kpi.bsd':'10.0.0',
       'com.apple.kpi.dsep':'10.0.0','com.apple.kpi.iokit':'10.0.0',
       'com.apple.kpi.libkern':'10.0.0','com.apple.kpi.mach':'10.0.0',
       'com.apple.kpi.unsupported':'10.0.0'}}
plistlib.dump(d, open(p,'wb'))
PY
echo "### RaphaelGPU.kext $VER"
