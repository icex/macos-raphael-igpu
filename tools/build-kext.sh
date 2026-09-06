#!/usr/bin/env bash
# Cross-build a Lilu plugin kext for macOS x86_64 -- entirely on Linux.
#
#   ./build-kext.sh <SourceDir> <ProductName> <BundleId> [Version]
#
# Requires (all built/fetched under $BUILD by bootstrap-toolchain.sh):
#   cctools-inst/bin/x86_64-apple-darwin-ld   real Apple ld64 -- lld CANNOT do -kext
#   MacKernelSDK-master/                      kernel headers + libkmod.a
#   liludbg/Lilu.kext/Contents/Resources/     Lilu Headers/ + Library/plugin_start.cpp
set -euo pipefail
BUILD="${BUILD:-/home/bogdan/macos-vm/build}"
SRC="$1"; NAME="$2"; BUNDLE="$3"; VER="${4:-1.0.0}"
SDK="$BUILD/MacKernelSDK-master"
LRES="$BUILD/liludbg/Lilu.kext/Contents/Resources"
LD="$BUILD/cctools-inst/bin/x86_64-apple-darwin-ld"
OUT="$BUILD/out/$NAME"
rm -rf "$OUT"; mkdir -p "$OUT/obj" "$OUT/$NAME.kext/Contents/MacOS"

FLAGS=(-target x86_64-apple-macos10.15 -nostdinc -nostdinc++
  -I "$SDK/Headers" -I "$LRES"
  -DPRODUCT_NAME="$NAME" -DMODULE_VERSION="$VER" -DAPPLE_KEXT_ASSERTIONS=1
  -fapple-kext -fno-builtin -fno-common -fno-exceptions -fno-rtti
  -fno-asynchronous-unwind-tables -mkernel -O2
  # The kernel has no __cxa_atexit, so static objects must not register
  # destructors; without this the kext fails to link into a collection with
  # "Failed to bind '___cxa_atexit' ... could not find a kext which exports this symbol".
  -fno-c++-static-destructors
  -mmmx -msse -msse2 -msse3 -mssse3 -mfpmath=sse)

cat > "$OUT/obj/kmod_info.c" <<EOF
#include <mach/mach_types.h>
extern kern_return_t ${NAME}_kern_start(kmod_info_t *, void *);
extern kern_return_t ${NAME}_kern_stop(kmod_info_t *, void *);
extern kern_return_t _start(kmod_info_t *, void *);
extern kern_return_t _stop(kmod_info_t *, void *);
__attribute__((visibility("default")))
KMOD_EXPLICIT_DECL(${BUNDLE}, "${VER}", _start, _stop)
__private_extern__ kmod_start_func_t *_realmain = ${NAME}_kern_start;
__private_extern__ kmod_stop_func_t  *_antimain = ${NAME}_kern_stop;
__private_extern__ int _kext_apple_cc = __APPLE_CC__;
EOF

OBJS=()
clang   -c "$OUT/obj/kmod_info.c" -o "$OUT/obj/kmod_info.o" "${FLAGS[@]}" -std=gnu11
OBJS+=("$OUT/obj/kmod_info.o")
clang++ -c "$LRES/Library/plugin_start.cpp" -o "$OUT/obj/plugin_start.o" "${FLAGS[@]}" -std=c++17
OBJS+=("$OUT/obj/plugin_start.o")
for f in "$SRC"/*.cpp; do
  o="$OUT/obj/$(basename "${f%.cpp}").o"
  clang++ -c "$f" -o "$o" "${FLAGS[@]}" -std=c++17
  OBJS+=("$o")
done

"$LD" -arch x86_64 -kext -static -o "$OUT/$NAME.kext/Contents/MacOS/$NAME" \
      "${OBJS[@]}" -L "$SDK/Library/x86_64" -lkmod 2>&1 | grep -v 'Frameworks' || true

file "$OUT/$NAME.kext/Contents/MacOS/$NAME" | grep -q 'kext bundle' \
  || { echo "FATAL: not an MH_KEXT_BUNDLE" >&2; exit 1; }
echo "built $OUT/$NAME.kext  (add Contents/Info.plist next)"
