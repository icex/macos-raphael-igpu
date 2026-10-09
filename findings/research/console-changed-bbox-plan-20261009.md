# Candidate372: one rectangle containing all changed pixels

Software-only draft from candidate370 `7f202822fae359aaafc4812b41e0752594797473`.
No guest, host helper, image or native configuration change; no QEMU build while
candidate370 is active. This patch is an additional experimental image patch,
applied after the existing snapshot and single-bounding-box patches. Existing
stock/default images remain unchanged.

## Observation and hypothesis

Candidate370's actual HiDPI presenter reports roughly4.0–4.3ms buffer lock,
2.0–2.2ms staging row copy,10.0–10.8ms snapshot commit and16.3–16.8ms worker total.
Commit includes several MMIO exits, possible BQL waits, host surface allocation,
copy and previous pending release; it is not measured host memcpy time alone.
The valid source sample rate exceeds observed distinct manager token delivery.
This draft tests one downstream cost, not every possible bottleneck.

Each immutable surface replacement marks the whole4K surface dirty. The current
single-bounding-box diagnostic emits that full rectangle even when only the
small token region changes. `qemu_spice_create_one_update` allocates a bitmap and
copies surface→mirror→bitmap, so every such update copies/transports33.18MB.
The original QEMU dirty algorithm compares against the mirror but emits multiple
32-pixel-wide updates; that approach reintroduces the independently observed
intermediate-region token sampling problem.

Hypothesis: preserving one update while shrinking it to the union of all changed
pixels reduces SPICE allocation/copy/transport and BQL contention for localized
changes. It may improve manager cadence and possibly guest commit elapsed time.
A moving/full-screen workload may still require the full frame; no universal
60Hz improvement is predicted. Merely observing zero invalid tokens is not full
pixel or host scanout qualification.

## Narrow implementation

`qemu-10.1.2-spice-changed-single-bbox-research.patch` adds a small pure C helper
and changes only the experimental SPICE rectangle selection. Source staging,
SFENCE, synchronous snapshot ACK, one-shot lease, immutable host image lifetime,
latest-pending replacement and all capture/recovery paths remain untouched.

For matching packed little-endian32-bit xRGB source and mirror, the helper checks
positive geometry through3840x2160, row strides/storage lengths and dirty bounds.
It compares each row's pixels, excluding padding; changed rows find their first
and last differing4-byte pixel. One union rectangle encloses every changed pixel.
Different source/mirror strides are supported. No source or mirror is modified
while scanning. Exactly one existing `qemu_spice_create_one_update` follows, or
none if the region is identical. Unsupported format/geometry or failed bounds
checks conservatively send the full surface. Changes in the unused x byte can
cause extra traffic, never omission of a changed RGB pixel.

The existing mirror represents pixels in previously generated ordered QXL
updates, not client acknowledgement. It is updated by the existing pixman copy
only when generating the new rectangle. Intermediate pending host snapshots may
be dropped; the comparison still uses the last generated client image. The
bounding rectangle includes all differences, so untouched pixels remain equal.
No tiled publication or mutable surface reuse is introduced.

A new mirror is NOT sufficient initialization evidence: host primary storage
uses `g_malloc`. Therefore a `diff_mirror_initialized` flag forces a full first
update after every full geometry/format switch, even when pixels are black and
compare equal to fresh mirror contents. Only actual update generation sets the
flag. Same-size/format immutable surface swaps retain it. BQL plus the existing
SPICE lock protects the scan/publication sequence as in candidate369's audit.

## Small offline tests already permitted

`tests/test_spice_changed_bbox.py` extracts and compiles the exact helper header
embedded in the patch, then tests unchanged pixels with differing/padded strides,
each corner/channel including final pixel, separated regions returning one union,
invalid bounds/short storage/overflow refusal, and120 deterministic successive
reconstructions where applying only the returned rectangle exactly reproduces
the source. This does not compile QEMU integration or prove client initialization.

## Required next software proof after the native cycle stops

1. Apply the additional patch to an isolated copy of the370 source, compile only
   there, and retain the original snapshot+full-bbox binary as control.
2. Repeat immutable ACK/overwrite/resize and default legacy pixel controls.
3. Actual offscreen SPICE full-pixel reconstruction: black first frame, sparse
   separated changes, edge pixels, unchanged repeat, resize and format fallback.
   Confirm first full-frame initialization and no omitted unchanged black areas.
4. Same atomic qtest token producer, explicit SPICE60/compression off, full-bbox
   versus changed-bbox, first at640x480 then4K/scale2. Retain raw tokens, invalid
   categories, producer ACK times, publication/replacement counts and measured
   invalidation rectangle area. Initial token0 is separate from producer records.
5. Repeat deliberate mismatched-token negative: intact comparisons must not turn
   the decoder into a false pass. Retain QEMU exits and exact binary/patch hashes.

Use existing display invalidation rectangles to measure changed area before
adding instrumentation. If commit remains dominant, a subsequent narrow QEMU
aggregate can separate allocation/copy/free from SPICE bitmap generation and
show how much of guest commit elapsed time lies outside the COMMIT handler.
Do not recycle current or published pixman storage without a separate lifetime
proof merely to remove allocations.
