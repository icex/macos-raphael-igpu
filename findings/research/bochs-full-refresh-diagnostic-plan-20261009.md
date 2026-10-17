# Candidate352: optional Bochs full-refresh diagnostic

Prepared patch `patches/qemu-10.1.2-bochs-full-refresh-diagnostic.patch` adds
`bochs-display,x-debug-full-refresh=on` (default false, construction-time device
property). It skips enabling ONLY DIRTY_MEMORY_VGA on the Bochs VRAM and sends a
full surface update at each existing graphics refresh. Mode validation, surface
replacement, geometry/offsets, endian handling and refresh scheduling are unchanged.
Default branch remains the original dirty-snapshot path. No live toggle, physical
GPU behavior, CPU dirty-logging capability or global memory client is altered.

Source basis in pinned QEMU10.1.2: bochs-display.c enables the VGA logging client
at realize and snapshots/clears it on ordinary updates; system/memory.c
memory_region_set_log changes the VGA client bit/count only. Migration's global
logging and other clients remain independent. The patch does not disable migration
tracking or skip RAM migration; migration can therefore reintroduce write logging
and its cost. No migration runtime qualification is claimed. This debug property
is not migrated guest state: source/destination must use the same explicit device
configuration for any future migration test. Do not use it as a migration bypass.

Full updates deliberately trade dirty tracking for additional host display work,
including static frames. SPICE may copy/compress/queue more pixels and increase
CPU/bandwidth/latency. Full update is not atomic publication; the source remains
concurrently writable, and ordinary SPICE rectangle splitting remains. Keep the
single-rectangle diagnostic patch OUT of this comparison.

Software validation before any native admission:

1. Build two binaries from the pinned pristine archive with only the existing
   explicit-refresh patch common to both, then this Bochs patch on the second.
   Enable KVM for the paired-write guest. Existing build-spice-refresh-ab.py
   disables KVM, so do not silently reuse its result for KVM qualification.
2. Verify absent/explicit-off property follows the original path. Run the same
   software Bochs pixel/stride/mode-change oracle with off/on; verify complete
   screenshots including static frames and changing row-dependent patterns.
   TCG/qtest suffices for correctness but not dirty-write cost causality.
3. With an isolated own KVM guest (no physical GPU), compare paired8/33MB Bochs
   writes and logged dirty-clear events under off/on, same60 refresh, viewer and
   image-compression=off. Repeat30 refresh separately. Preserve elapsed host/guest
   write times, host CPU and observed token delivery; avoid screenshot polling
   during timing because it can trigger a graphics update.
4. Require returned desktop pixels and bounded natural cleanup in every case.
   A faster guest write with overloaded SPICE is a measured tradeoff, not success.

Only patch generation and `patch --dry-run` against pinned Bochs source have run.
No QEMU build, image mutation, device launch or native/hardware test was performed.
Existing standalone KVM result supports pursuing this discriminator but cannot
qualify this unbuilt patch.
