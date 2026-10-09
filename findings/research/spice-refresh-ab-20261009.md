# Software SPICE refresh A/B — 2026-10-09

Scope: fresh QEMU10.1.2, software TCG, Bochs640×480, no KVM, physical
GPU, macOS, host networking, production-image change or native qualification.
Parent retains sole ownership of native runs. Candidate344 contains research tools.

## Hypothesis and measured result

The nongl SPICE listener inherits QEMU's30ms refresh timer even when
`-spice max-refresh-rate=60` is specified. The small research patch records
whether the option was explicit, and applies `MAX(1,1000/rate)` to the nongl
listener only. No-option behavior and the GL path remain unchanged.

Exploratory sequential15s measurements (SPICE default compression), with
producer60.000 completed writes/s:

| Binary / option | Unique decoded tokens/s | Invalid after first token |
|---|---:|---:|
| Original / absent |33.333|8|
| Original /60 |33.400|6|
| Patched / absent |33.333|6|
| Patched /60 |59.867|15|

Every case completed900 acknowledged producer writes and QMP quit/exit0.
A final four-case series explicitly matches production `image-compression=off`;
its primary decoded rates are33.333/33.333/33.333/59.933 tokens/s,
respectively, with7/10/6/27 invalid samples. Producer cadence remains~60/s;
all four QEMU processes quit normally with exit0. Each run emits exactly one
MARK, versus5,003–8,147 region invalidations. See adjacent evidence JSON. The earlier
compression-default runs remain exploratory. This supports the nongl scheduling hypothesis. It does not measure Metal fps,
manager rendering, native1080p/HiDPI bandwidth, host scanout or absolute latency.
The interval is integer milliseconds (60 gives16ms); it is not exact VSYNC.
`max-refresh-rate=0` remains rejected by both binaries.

A repeated four-case run adds display-mark/invalidate logging; its raw receipts
are under `final-*`. The host unittest suite ran concurrently with that repeat,
so the initial A/B is the cleaner scheduling comparison. Timing is a sampled
lower bound; producer and sampling cost are retained individually.

## Pixel interpretation and negative control

The producer writes one full-width96-row token band through one qtest transaction.
`socket.sendall` is required: unbuffered makefile.write can perform a partial
large socket write. Both duplicated tokens carry nonce, sequence and CRC.
The sole client is a Gtk OffscreenWindow containing SpiceDisplay. A GLib8ms
sampler calls get_pixbuf; it creates no visible manager or second connection.

Invalid samples occur even with the serialized producer. They cannot establish
native concurrent-memcpy tearing or GPU corruption. QEMU
`ui/spice-display.c:qemu_spice_create_update` subdivides changes into32px-wide
rectangles and creates separate QXL_DRAW_COPY snapshots. SpiceClientGLib's
installed GIR describes `display-invalidate` as a rectangular buffer update,
not complete-frame publication. Its `display-mark` describes an expose marker.
An instrumented5s patched60 run observed299 unique tokens,2,711 invalidations,
and exactly **one** mark. MARK is not a per-frame completion oracle here.

A deliberately split producer writes mismatched duplicate IDs, waits20ms, then
writes the matching pair. Five-second original/patched60 cases each show558
invalid samples and62 valid samples, at~38.25 producer writes/s. That verifies
negative detection; these synthetic mismatches are not native driver evidence.
That discriminator is now complete: a separate **research-only** patch makes
one dirty-bounding-rectangle bitmap instead of 32px chunks, retaining patched60,
compression off and the serialized producer. Fifteen seconds yields 900 unique
IDs (60.000/s), 900 invalidations, one MARK and **zero invalid samples out of
1,861**; producer cadence is59.998/s and QEMU exits0 normally. Its median producer
transaction cost and sampler cost are recorded alongside the 32px control.
The matching 32px case produced27 invalid samples and8,147 invalidations.

This supports intermediate region application as the explanation for sampled
partial tokens in this controlled software pipeline. It neither proves native
source-buffer atomicity nor justifies a production single-rectangle change:
larger dirty snapshots may increase bandwidth/copy cost, especially at4K.
The diagnostic patch is separate from the explicit-refresh patch and not used
in any production image. To reproduce, apply it after the explicit-refresh
patch, rebuild the same target, and run the same `--rate 60 --seconds 15` smoke.
No timed runs overlapped the parent's native-compatible build.

## Reproduction and provenance

Use pristine `qemu-10.1.2.tar.xz`; source/binary/archive hashes and all evidence
hashes are in the adjacent JSON. Build requirements: C compiler, pkg-config,
Python, Meson/Ninja, glib, pixman and spice-server development files. Configure
explicitly enables SPICE/TCG and disables KVM/docs/guest-agent/downloads. This
host used existing research Meson1.9.1/Ninja1.13 via PATH/PYTHONPATH, gcc and the
installed libraries; no privileged package installation occurred.

```
python3 tools/build-spice-refresh-ab.py --archive /path/qemu-10.1.2.tar.xz --output /new/research/build
python3 tools/spice-refresh-smoke.py --qemu /new/research/build/qemu-original --bios-dir /new/research/build/qemu-10.1.2/pc-bios --output /new/results/original --seconds 15
```

Repeat with
`--rate 60`, then qemu-patched, with/without rate. `--split` is the negative
control. A working GTK backend with SpiceClientGtk3 is needed. GTK offscreen
Wayland emits nonfatal pointer/window warnings retained in logs.

SPICE initially remains stopped under `-S`; the fixture briefly continues then
stops a64KiB ROM containing only CLI/HLT/jump at its reset vector before programming
Bochs. No guest OS executes. QEMU stays paused during producer writes. There is
no QMP screendump or forced refresh during measurement. Startup failures/pilots
remain in the evidence directory with stopped-process cleanup receipts.

## Native portability follow-up (source review only)

Bochs exposes Y_OFFSET but no display-consumption completion acknowledgement.
A direct host surface can reference guest VRAM across refreshes; merely rotating
buffers cannot prove safe reuse while the host is delayed. QEMU's stock
virtio-gpu2D `TRANSFER_TO_HOST_2D` copies guest backing into host-owned pixman
storage before its response/used-ring notification, allowing a guest source
buffer reuse fence. `RESOURCE_FLUSH` updates the console, but neither command
proves complete SPICE client publication or scanout. A presentation-only
virtio-gpu transport could retain native Metal rendering; implementation and
compatibility remain untested. No transport replacement is justified solely by
these timer-sampled intermediate token failures.

Validation: full host suite1,139 tests pass,3 skipped; focused3 producer tests
pass. A new bounded alarm also protects the standalone smoke acquisition/cleanup.
