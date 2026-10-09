# Candidate352 diagnostic Bochs build and pixels

The optional full-refresh patch builds on pristine pinned QEMU10.1.2 with KVM,
TCG and SPICE enabled. Only the explicit-refresh patch and Bochs diagnostic patch
were applied; the separate single-rectangle experiment was excluded. Existing
research binaries, container images, native VM and GPU were untouched.

Three software qtest cases passed: property absent/default, explicit off, explicit
on. Each verifies1,094,400 pixels across640×480 phase0/phase1 and800×600 phase2;
each frame is captured a second time without guest writes and must remain exact.
All three cases produce identical screenshot hashes. Explicit QOM property
readback confirms false/true. QMP quit yields exit0 in every case. The new helper
option does not change normal device arguments when omitted.

This validates serialized software pixels, static content and resize, not native
macOS, simultaneous writes, sustained SPICE delivery, migration, or KVM Bochs
write cost. The KVM-capable build is ready for the latter discriminator, but the
pixel test intentionally uses paused TCG/qtest. The earlier standalone KVM RAM
result remains separate evidence. No diagnostic container image was built.

Reproduction uses existing `extract_qemu_archive` from
`tools/build-spice-refresh-ab.py` on the pinned archive, then applies the two
patches with `patch -p1`. Configure/build exact flags, archive/patch/binary/log
hashes and all pixel results are retained in the adjacent evidence JSON. This
host used PYTHONPATH `~/macos-vm/run/research/qemu-smc-20260916/python`, adding its
bin directory to PATH for Meson/Ninja. Source/build are separate new directories
under `~/macos-vm/run/c352-bochs-build/`; build with ninja-j4, no system install.

```
python3 -B tools/qemu-console-smoke.py --qemu /path/to/new/qemu-system-x86_64 --output default.json
python3 -B tools/qemu-console-smoke.py --qemu /path/to/new/qemu-system-x86_64 --bochs-full-refresh off --output off.json
python3 -B tools/qemu-console-smoke.py --qemu /path/to/new/qemu-system-x86_64 --bochs-full-refresh on --output on.json
```

Existing console host tests:94 pass, five optional extension skips. Full project
suite not rerun for this isolated research validation. Source diff check passes.
