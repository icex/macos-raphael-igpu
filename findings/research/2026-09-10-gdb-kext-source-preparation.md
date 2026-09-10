# GPU-less kext source-debug preparation

The initial preparation was offline. The separately authorized GPU-less runtime
qualification is recorded below. Neither stage exposed VFIO/DRI, used sudo, or
modified canonical media or driver source.

`tools/gdb-kext-source.py` generates the bounded GDB command file after a fresh
serial log supplies the runtime kernel `__TEXT` base. The prior qualification
proved that runtime Mach-O segment commands already contain relocated virtual
addresses. The helper therefore validates the live `__TEXT` base and size,
finds live `__DATA`, and derives `_kmod` from the KDK-authenticated `0x214938`
offset within that segment. It reads at most 64 KiB of any Mach-O header and
walks at most 256 packed `kmod_info` records, rejecting cycles, malformed
headers, the wrong bundle name, or a UUID mismatch.

The authenticated target is the existing `-O2 -g -gdwarf-4` Raphael artifact:

- executable SHA-256: `bc9417815e8223909d64a754ae319d6a6280f09d1fcd76f650bf5bff87c1f39b`
- executable/dSYM UUID: `474EF697-FC28-3BA2-83A4-763D76C8E200`
- source target: `RaphaelGPU.cpp:532`, in the recurring GPU-less
  `criticalDumpThread` snapshot loop

Before loading the dSYM, the generated script compares the live first 16 bytes
of `criticalDumpThread` with the artifact. It loads all dSYM sections with the
authenticated kmod base, requires line 532 to resolve to one address, installs
one hardware breakpoint, prints locals/registers/stack, performs a top-level
`si`, records the PC change, and detaches so execution resumes. It makes no
claim that a GPU initialization wrapper runs in the GPU-less guest.

The debug bundle was copied transactionally into private ESP media at
`/home/bogdan/macos-vm/run/gdb-source-kext-prep-20260910T204500Z`. A QCOW-to-raw
conversion was staged in a temporary file, the bundle was replaced there, and
the resulting QCOW was converted back to raw for readback. Executable and plist
readbacks match their inputs byte-for-byte. The prepared private OpenCore QCOW
SHA-256 is `a4e7131c86b6392b026134c7a0ee0e7d2d16cfacd0572ccd23e860bac2e4bac0`.
The adjacent KDK executable copy, kept away from the unsupported DWARF5 dSYM,
has SHA-256 `04a501246caf768356f4090a8fd662daf5bbc949993353526c66771f5ba1d8e4`.
Full hashes are in `staging-sha256.txt` in that preparation directory.

Five focused unit tests cover relocation arithmetic, bounded Mach-O parsing,
successful kmod authentication, wrong-UUID and cyclic-list rejection, and the
generated command ordering. Offline GDB also resolves line 532 after applying a
synthetic dSYM offset; evidence is `gdb-offline-source-load.txt`.

## GPU-less qualification result

One subsequently authorized 180-second GPU-less run used the prepared private
media. Fresh serial reported KASLR `0xa400000` and kernel `__TEXT` at
`0xffffff800a6e8000`, again demonstrating the `0xe8000` KC offset. The guarded
kmod walk authenticated `as.rgpu.RaphaelGPU` at `0xffffff800e47c000` with UUID
`474EF697-FC28-3BA2-83A4-763D76C8E200`, and the live function bytes matched.

GDB resolved the requested source line to the sole executable SAL at
`0xffffff800e481411`; because of `-O2`, it reports that address as source line
542 within `criticalDumpThread`. The hardware breakpoint hit. `info locals`,
registers, and stack memory were captured; several scalar locals were optimized
out. A top-level `si` advanced RIP from `0xffffff800e481411` to
`0xffffff800e481413`. Detach resumed the guest. Exact CID
`1b42c450dbeb7ce5211fc0a4a1d4bc63f95b903eeb7630fd5cd44176ccd14e56`
received an ACPI request and was forcibly stopped after the bounded grace
period. No VM remained, and all final evidence hashes verify.

Runtime evidence is under the private preparation directory's `vm/run/`.
Debugger pauses alter timing, so this run cannot establish the natural UART
failure mechanism or any GPU initialization behavior.
