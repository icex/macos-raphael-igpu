# GPU-less QEMU/GDB qualification

Date: 2026-09-10. Scope was private media, no VFIO/DRI, no host GPU, no sudo,
no reset or rebind, and no canonical-media mutation. This is debugger-plumbing
evidence, not a GPU experiment or a recovery receipt.

## Debug artifact

The private `-O2 -g -gdwarf-4` cross-build is retained at:

`/home/bogdan/macos-vm/run/debug-symbols-187-20260910T154947Z-08911110`

Its tracked source digest equals production candidate 187
`db511634c6d292ef3a65285e56bd5cf5f9e03cf4c20680a27b96c46a18f2e9b0`,
but it deliberately has a separate build identity and UUID. Executable SHA-256
is `bc9417815e8223909d64a754ae319d6a6280f09d1fcd76f650bf5bff87c1f39b`;
executable and dSYM UUID are `474EF697-FC28-3BA2-83A4-763D76C8E200`.

GNU GDB 17.2 reads source information from
`RaphaelGPU.dSYM/Contents/Resources/DWARF/RaphaelGPU`, not from the linked
executable's Mach-O debug map. Offline proof resolves `wrapGfx10PowerUp` to
source line 5645 and `pluginStart` to line 6342, with location ranges for
`self`, `r`, and plugin-start locals. `-O2` means locations can be discontinuous
or optimized out and source stepping can jump.

## Runtime attempts

The first preserved attempt is under
`/home/bogdan/macos-vm/run/gdb-qualification-20260910T160000Z`. It added
`slide=0`, failed OpenCore `StartImage`, and used a software breakpoint at an
unmapped kernel address. It proves only reset-vector attachment and is invalid
as kernel breakpoint evidence.

The sole corrected attempt is under
`/home/bogdan/macos-vm/run/gdb-qualification-20260910T190000Z/vm/run`.
It used the known-booting OpenCore image and config byte-for-byte, an empty run
directory, no VFIO/DRI arguments, and a 180-second supervisor. Exact CID:
`9624ae0e77ff3be0b483110d91b2a30f2c8bfcaeebaefc47782f0c0f2a293af4`.
Shutdown reports `already-stopped`, and no VM remained after the deadline.

Fresh serial proves Darwin 24.6.0 boot, KASLR slide `0x18000000`, and plugin
build `68b28f81b7d5404cb69a7baf2f6117c5`; it has no prior `StartImage` failure.
GDB attached at reset (`RIP=0xfff0`), resumed, and was interrupted after paging
at mapped kernel RIP `0xffffff801853c429`, with `CR0.PG=1`, `CR3=0x1ced0000`,
and coherent instruction bytes.

The KDK link address for `_mach_absolute_time` is `0xffffff80004509e0`.
Adding the reported slide produced `0xffffff80184509e0`, where GDB accepted a
hardware breakpoint. Runtime bytes there begin `e4 7d 00 31 c0 e8`; the pinned
KDK prologue begins `55 48 89 e5 48 8d`. A bounded search of the expected
runtime kernel-text interval did not find the exact KDK prologue. The hardware
breakpoint therefore targeted the wrong runtime address and did not hit.

The runtime-byte mismatch establishes only that symbol binding is unverified.
An additional kernel-collection/fileset relocation is the leading hypothesis,
but a different guest kernel binary or runtime patch could produce the same
observation. The next step is offline validation of the actual guest kernel
collection/fileset UUID and segment mapping against the pinned KDK, followed by
a runtime-byte signature check. Only then can a later authorized method use
`hbreak`, capture registers and stack memory, execute `si`, and resume. The
corrected attempt timed out before that mapping was derived. It proves a kernel
interrupt plus register and memory inspection; it does not prove a named kernel
breakpoint, single-step, or resume. No further attempt is authorized by this
report.

Primary evidence: `gdb-transcript.log`, `serial.log`, `critical.log`,
`supervision.json`, `shutdown-debugger.json`, and `vm-launch.log` in the
corrected run directory.
