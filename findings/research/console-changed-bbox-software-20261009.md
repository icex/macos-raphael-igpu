# Candidate372 software changed-rectangle result

**Observed:** one changed-pixel bounding rectangle reconstructs complete client
images correctly and dramatically reduces SPICE update area for localized token
changes. Software cadence at4K remains limited by this qtest producer; no native
performance gain or60Hz result is claimed.

[Design/source audit](console-changed-bbox-plan-20261009.md) ·
[Artifact manifest](console-changed-bbox-software-evidence-20261009.json).
All processes are owned isolated TCG software QEMU instances: no KVM, guest OS,
physical GPU, native manager connection or deployed-helper changes.

## Correctness

The5 focused tests compile the actual patch header and pass (0.067s), including
stride/padding, all channels/corners, bounds refusal and120 full reconstructions.
An isolated QEMU build of the additional patch succeeds. Separate copies retain
changed-bbox and full-bbox control binaries built with the same source/compiler
configuration; baseline was rebuilt by reversing only this additional patch.

`tools/spice-snapshot-pixels.py` connects one offscreen SpiceDisplay and checks
all RGB pixels, not only token regions. Eight phases pass: black first image,
all corners with independent RGB colors, separated changes, return to black,
identical black, resize to800x600 black, resize to4K black, and4K corners/center.
The identical phase produces no client invalidation. New-primary full update
is required so black pixels are initialized; the host primary uses `g_malloc`.
QEMU exits0 and raw invalidations are retained.

The unchanged snapshot QMP oracle also passes ACK→overwrite staging/BAR0→full
pixel preservation through4K/resize, pending replacement counts, invalid sequence
and terminal lease rejection. Legacy/default colored pixel control passes.
Migration default save succeeds and snapshot opt-in save explicitly fails as
before. These controls do not qualify incoming migration or native reset.
Unsupported-format fallback is conservative in source; this software run tests
the actual32-bit snapshot format, not all possible legacy pixel formats.

## Transport-area and token controls

Atomic qtest producer, explicit SPICE60, image compression off,15s per intact
case, observer8ms. All results retain initial token0 separately from producer
records1..N; distinct sampled IDs may include that initial image.

| Geometry/path | Producer records | Distinct IDs | Valid / invalid samples | Mean invalidation area (pixels) |
|---|---:|---:|---:|---:|
|640x480 full bbox|900|900|1863 /0|307200|
|640x480 changed bbox|900|899|1862 /0|7149.65|
|3840x2160 full bbox|100|100|1665 /0|8294400|
|3840x2160 changed bbox|102|102|1860 /0|108310.59|

Mean rectangle area falls97.7% at640x480 and98.7% at4K, including required full
initialization. These are observed client invalidation areas, not measured wire
byte counts or whole-host CPU cost. No smaller rectangles are sent separately:
there is still exactly one update encompassing every changed pixel.

The full-width ASCII qtest write path limits4K producer output to6.64/6.79
records/s. Thus observed6.67/6.8 distinct IDs/s cannot establish useful60Hz
performance or its absence. Native production writes are materially different.
The software discriminator here proves reduced transport area without sacrificing
observed reconstruction/token integrity, not native throughput improvement.

The5s deliberately mismatched-token negative retains560 invalid samples and31
unique valid IDs. Zero invalids in intact controls therefore did not result from
disabling torn-token detection. Retained manager/client frames are still not
host scanout qualification; actual macOS testing belongs to the parent owner.

## Provenance and next step

Host research binaries:

- changed bbox `ee0cb8cd35615ffbcc978073669c7dfcb2e00b04dda2d9a244a7eeeebbfdc526`
- full bbox control `e92ecaff014fff470957f1747e622118d2e70cb2b2c2c254fe718404a8d96892`

The isolated tree copied the audited370 QEMU10.1.2 tree and adds only
`qemu-10.1.2-spice-changed-single-bbox-research.patch`. Existing trees/images are
unchanged. Build logs, complete pixel hashes, raw samples/producer events,
cleanup receipts and rectangle analysis live under`run/c372-changed-bbox`.
GTK offscreen/Wayland warnings are retained; these are software widgets, not
claims that a real manager window was operated.

The helper compares all4 bytes, including unused X. If a native source or pixman
normalizes X differently, it can conservatively enlarge update area; it cannot
omit changed RGB pixels. Measure native rectangle area before attributing any
remaining performance issue solely to transport. Snapshot commit still includes
allocation/copy/free and multiple MMIO/BQL waits. Ownership, fencing, immutable
storage and one-shot staging lifetime remain unchanged.

Next is a separately built/pinned compatible experimental container image and
parent-owned native qualification against370. A source-backed expected reduction
is not a measured native gain. No optimization of snapshot memory reuse is part
of this change.
