#!/usr/bin/env bash
# One-time: assemble a Linux -> macOS kext cross toolchain under $BUILD.
# Everything lands in $BUILD; nothing is installed system-wide, no root needed.
set -euo pipefail
BUILD="${BUILD:-/home/bogdan/macos-vm/build}"
mkdir -p "$BUILD"; cd "$BUILD"

# 1. Kernel headers + libkmod.a (acidanthera MacKernelSDK)
[ -d MacKernelSDK-master ] || { curl -sSL -o mksdk.tar.gz \
  https://github.com/acidanthera/MacKernelSDK/archive/refs/heads/master.tar.gz
  tar xzf mksdk.tar.gz; }

# 2. Lilu DEBUG release -- ships Contents/Resources/{Headers,Library/plugin_start.cpp}
#    Must match (or be older than) the Lilu.kext actually deployed in the ESP.
[ -d liludbg ] || { curl -sSL -o Lilu-DEBUG.zip \
  https://github.com/acidanthera/Lilu/releases/download/1.6.8/Lilu-1.6.8-DEBUG.zip
  mkdir -p liludbg && (cd liludbg && 7z x -y ../Lilu-DEBUG.zip >/dev/null); }

# 3. libBlocksRuntime + libdispatch: cctools-port build deps.
#    Arch ships both inside extra/libdispatch; extract the package, do not install it.
[ -d sysroot ] || { mkdir -p sysroot
  curl -sSL -o libdispatch.pkg.tar.zst "$(pacman -Sp libdispatch | tail -1)"
  tar -I zstd -xf libdispatch.pkg.tar.zst -C sysroot; }

# 4. Apple ld64 via cctools-port. THIS IS THE ONLY PART THAT MATTERS:
#    ld64.lld has no -kext, and a 64-bit kext MUST be MH_KEXT_BUNDLE.
#    -std=gnu17 is required: cctools uses `enum bool`, which C23 rejects.
if [ ! -x cctools-inst/bin/x86_64-apple-darwin-ld ]; then
  [ -d cctools-port ] || git clone --depth 1 https://github.com/tpoechtrager/cctools-port.git
  cd cctools-port/cctools
  export LDFLAGS="-L$BUILD/sysroot/usr/lib -Wl,-rpath,$BUILD/sysroot/usr/lib"
  export CPPFLAGS="-I$BUILD/sysroot/usr/include"
  export CFLAGS="-std=gnu17 -O2 -I$BUILD/sysroot/usr/include"
  export CXXFLAGS="-std=gnu++17 -O2 -I$BUILD/sysroot/usr/include"
  ./autogen.sh
  ./configure --prefix="$BUILD/cctools-inst" --target=x86_64-apple-darwin \
              --with-llvm-config=/usr/bin/llvm-config
  make -j"$(nproc)" && make install
fi
echo "toolchain ready: $BUILD/cctools-inst/bin/x86_64-apple-darwin-ld"
