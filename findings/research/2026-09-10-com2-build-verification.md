# COM2 guest isolated build verification

Date: 2026-09-10

Scope: offline exact-KDK preflight, route checks, and an isolated cross-build of
the current combined COM2 guest and reviewed VMID1 diagnostic source. No version
file, candidate output, release package, staging tree, VM, QEMU process, device,
GPU, recovery state, or privileged operation was changed.

## Source and input identity

The build read the current repository `src` directory directly. SHA-256 identities:

```text
RaphaelGPU.cpp       3adfef1145156cd6e358e39a6bc9784845647317ca5a7ba5c39b38c05a918101
CriticalUart.hpp     2fa1febc6d4307bd31eeecccc94f5347dba71eeb95026a2bf147127e7ddf54ee
GpuVmDiagnostics.hpp d81465b35917d6f60d0ac869b44dead64d2eec692cc20029f2e0b563575a3855
CriticalReplay.hpp   6f43686e00766d468326dfd018a97861e892686c8259d122e4a115d344e965ba
test_critical_uart   4ec0c28dcb425f91c1f98eb369a4700acc4fd10d73816824bbbbcca7a1c43729
all src cpp/hpp manifest (sorted sha256 stream)
                      07c94dd2c92f03fec446842f5b5c69b1bf9a9b288071b54ed6a71e01f1614c5d
```

Exact 24G830 KDK binary identities:

```text
AMDRadeonX6000       2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e
AMDRadeonX6000HWLibs 9a10fe21b61437fba11bad2c2221307317ddd02893a82a7d753317879682786d
AMDRadeonX6000Framebuffer
                      0f4b79b62fa66bbf5a907274d1f5442aeda4ba4ee4b67c216c01757dee7e4505
```

Toolchain identity was clang 22.1.8 targeting x86_64 Linux. Supporting hashes:

```text
x86_64-apple-darwin-ld
  3ab8d589163c1727cfd5d2d76f74710199b35643fc72a21125b14538fc0c8e76
MacKernelSDK libkmod.a
  7a751671bbe96c9c7b5416078df600b768c00c0dc5178d8acd8f52539c7ccd4e
Lilu plugin_start.cpp
  9ebc54138b05bebc86d78479209f3a6fdafedb5b732be190cc449b6b82e6ebf
```

## Route and exact-KDK preflight

The standalone ownership check was read first and run directly:

```sh
python3 tools/route-domains.py src/RaphaelGPU.cpp
```

Result: exit 0, `route binary ownership: passed`.

For exact-KDK preflight, `/tmp/rgpu-com2-preflight.QaouAG` contained copies of
the current preflight, route, and milestone scripts plus symlinks to current
`src`, the existing KDK extraction, and existing nm data. The executed command was:

```sh
python3 /tmp/rgpu-com2-preflight.QaouAG/preflight.py
```

Result: exit 0. Every listed constant except the pre-existing explicitly reported
`kOffVmmInit` symbol-name skip matched its symbol offset. All routed prologues were
accepted. Recovery-v2/v3 ordering, VM callback safety, VM entry callback safety,
VM correlation, and pointer-width setVMRegisters ABI checks passed. All eight
milestone byte-pattern checks passed with one original match and no replacement
present. Final output:

```text
preflight: route scopes checked, constants checked, prologues checked,
recovery-v2/v3 ordering checked, patterns unique
```

The first harness attempt used a symlink for `preflight.py`; Python resolved
`__file__` to the repository tools directory and correctly refused a missing KDK
at that derived location. Replacing only the temporary script links with copies
gave the isolated layout above. This setup failure did not compile or alter source.

## Isolated cross-build

The build root `/tmp/rgpu-com2-build.cg8aCZ` contained symlinks to the existing
cctools, MacKernelSDK, and Lilu resource directories. `BUILD` redirected every
object and output into that temporary root. No existing output directory was used.

```sh
BUILD=/tmp/rgpu-com2-build.cg8aCZ tools/build-kext.sh \
  /home/bogdan/src/macos-raphael-igpu/src \
  RaphaelGPU as.rgpu.RaphaelGPU 1.0.0
```

Result: exit 0. Compile and ld64 completed. `file` identified the result as:

```text
Mach-O 64-bit x86_64 kext bundle, flags:<NOUNDEFS|DYLDLINK|TWOLEVEL>
```

The executable is 253,656 bytes with SHA-256:

```text
07dfbdd366e98efee62bcd668ef2977bb1a88dd53791767db8c3da968b2fe006
```

The compiler reported 40 existing Lilu `routeFunction` deprecation warnings.
The C compilation also reported the build script's existing unused
`-nostdinc++`/C-only `-fapple-kext` warnings, and ld64 reported the existing absent
`/System/Library/Frameworks/` search directory. There were no COM2, VMID1,
compilation, undefined-symbol, or link errors. `rlc_fw.h` was absent, so this was
the source configuration with RLC substitution disabled, matching preflight's
explicit report.

This verifies source compatibility and exact-24G830 static route assumptions. It
does not install or execute the kext and provides no Metal, guest UART ownership,
GPU execution, cleanup, or host-reuse evidence.

## Production-configuration addendum

The 253,656-byte build above intentionally established the checked-in source's
fallback configuration without generated headers. It is retained as a separate
source-only result. A second isolated build verified the production configuration
used by `tools/build-release.py`.

The release verifier was imported without calling its packaging entry point, and
its read-only `verify_toolchain` function was run against
`/home/bogdan/macos-vm/build` and the checked-in `build-support/inputs.json`:

```text
verify_toolchain: pinned SDK and Lilu resource trees passed
```

The pinned values were:

```text
MacKernelSDK tree   39036632f485a027f8b75fe5a8cfb18fab79d5c7531adae9dc165096e7e14666
Lilu resources tree a68cdd008793057f22512c87911463d2145861fb3268ed9840fceb709fb67a0b
```

`src` was copied to `/tmp/rgpu-com2-production-src.TtxOO8`. The compressed
`build-support/rlc_fw.h.gz` was expanded only there and verified before use:

```text
rlc_fw.h c152bb08862f62b4ddef1bdf717be56935d4a8f6d214bd05a96237eccbed982c
```

That equals `firmware_header_sha256` in `inputs.json`. A temporary production-shaped
identity header contained exactly:

```c
#define RGPU_BUILD_ID "00112233445566778899aabbccddeeff"
```

Its SHA-256 is
`08c7660257dc0bd84d477f906b14a817b812fc13102e73b8e4d5edc662d61b2f`.
The release verifier's tree-digest algorithm measured the complete temporary
production source tree, including both generated headers, as:

```text
c6e15ddb0a78c0e2b6d3346bbc257a4281e3446f06ed25821041b64a1c5ecaf9
```

The exact-KDK preflight was rerun against this temporary source before and after
the build. Its source, route, ABI, prologue, and milestone checks exited 0. The
post-build firmware check reported:

```text
rlc firmware       ok (177104 bytes embedded; 3/3 probes found)
preflight: route scopes checked, constants checked, prologues checked,
recovery-v2/v3 ordering checked, patterns unique
```

The production-shaped build command was:

```sh
BUILD=/tmp/rgpu-com2-production-build.JGAUYY tools/build-kext.sh \
  /tmp/rgpu-com2-production-src.TtxOO8 \
  RaphaelGPU as.rgpu.RaphaelGPU 1.0.0
```

Result: exit 0, with the same known warning classes described for the source-only
build and no compile, undefined-symbol, or link failure. The temporary executable
is a 725,552-byte x86_64 Mach-O kext bundle. Its SHA-256 is:

```text
03293912e45393f53bbe89cf50bd589d669d41fdbb243fcdc7b5cf86d9cf6d89
```

`strings` found the exact temporary build identity in the executable. No release
packaging function was called, no Info.plist or repository version was edited, and
no existing build or candidate output was used.

Focused regression commands after the production build were:

```sh
g++ -std=c++17 -O1 -Wall -Wextra -Werror -fsanitize=address,undefined \
  tests/test_gpu_vm_diagnostics.cpp -o /tmp/gpu-vm-diagnostics-test && \
  /tmp/gpu-vm-diagnostics-test
g++ -std=c++17 -O1 -Wall -Wextra -Werror -fsanitize=address,undefined \
  tests/test_critical_uart.cpp -o /tmp/critical-uart-test && \
  /tmp/critical-uart-test
```

Both exited 0; the VMID1 fixture printed `GPU VM diagnostic fixtures passed`.
