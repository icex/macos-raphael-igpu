#!/usr/bin/env bash
# Rebuild RaphaelGPU.kext, push it into the running guest, and relink the
# Auxiliary kernel collection. Requires a logged-in guest with the gx agent up.
#
# Why the Aux KC and not OpenCore injection: OpenCore rejects the bundle
# ("Invalid Parameter") and, more importantly, OpenCore's Kernel>Patch cannot
# reach kexts in SystemKernelExtensions.kc at all. See docs/patch-delivery.md.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
PW=$(cat .guestpw)
KDK_GUEST=/Library/Developer/KDKs/KDK_15.7.9_24G830.kdk

echo "### build"
(cd build && ./build-kext.sh src-rgpu RaphaelGPU as.rgpu.RaphaelGPU 1.0.0) 2>&1 | tail -2
python3 - <<'PY'
import plistlib
p='build/out/RaphaelGPU/RaphaelGPU.kext/Contents/Info.plist'
d={'CFBundleDevelopmentRegion':'en','CFBundleExecutable':'RaphaelGPU',
   'CFBundleIdentifier':'as.rgpu.RaphaelGPU','CFBundleInfoDictionaryVersion':'6.0',
   'CFBundleName':'RaphaelGPU','CFBundlePackageType':'KEXT','CFBundleSignature':'????',
   'CFBundleShortVersionString':'1.0.0','CFBundleVersion':'1.0.0',
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
tar -C build/out/RaphaelGPU -czf run/RaphaelGPU.kext.tar.gz RaphaelGPU.kext
echo "  staged $(stat -c%s run/RaphaelGPU.kext.tar.gz) bytes"

echo "### install into the guest + relink the Aux KC"
GX_TIMEOUT=900 ./gx "cd /tmp && rm -rf RaphaelGPU.kext && curl -sS -o r.tgz http://10.0.2.2:8889/RaphaelGPU.kext.tar.gz && tar xzf r.tgz && printf '%s\n' '$PW' | sudo -S -p '' sh -c '
  rm -rf /Library/Extensions/RaphaelGPU.kext
  cp -R /tmp/RaphaelGPU.kext /Library/Extensions/
  chown -R root:wheel /Library/Extensions/RaphaelGPU.kext /Library/Extensions/Lilu.kext
  chmod -R 755 /Library/Extensions/RaphaelGPU.kext /Library/Extensions/Lilu.kext
  kmutil create -n aux -a x86_64 -z --kdk $KDK_GUEST \
    -B /System/Library/KernelCollections/BootKernelExtensions.kc \
    -S /System/Library/KernelCollections/SystemKernelExtensions.kc \
    -A /Library/KernelCollections/AuxiliaryKernelExtensions.kc \
    -r /Library/Extensions -b as.vit9696.Lilu -b as.rgpu.RaphaelGPU -x 2>&1 | tail -12
  echo \"--- aux KC contents ---\"
  kmutil inspect -A /Library/KernelCollections/AuxiliaryKernelExtensions.kc 2>&1 | grep -iE \"rgpu|lilu|Raphael\" | head
'" 2>&1 | tail -20
