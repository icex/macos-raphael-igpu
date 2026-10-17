# Tahoe scaled-mode copy freeze — 2026-10-15

## Current reproduction

Installed release 515, metal-321, guarded QEMU pins v20, run
`6bf1f855012317e8a887781506f4f41b` (attempt `d20261015154833`) on the
current host boot. The initial display was logical 2560x1440, physical
5120x2880 at 120 Hz. The guest's CoreGraphics mode list contained logical
2048x1152 / physical 4096x2304 at 120 Hz. A direct
`CGDisplaySetDisplayMode` call returned generic error 1000 without changing
the mode; that is not a failed hardware trial. A session-scoped
`CGConfigureDisplayWithDisplayMode` call then selected the target successfully
at 12:52:46 UTC. A timed restore was armed before switching.

The virtual-sink timing stayed 5120x2880, while the active desktop surface
switched to 4096-pixel pitch. The SDMA copy path logged four rejected surfaces:
`fmt=8 sw=27 dcc=0 pitch=4096 for 5120x2880`. Its next two 10-second
windows had **zero copied frames**. The guest remained reachable over SSH,
and CoreGraphics still reported the scaled mode. At 12:53:11 UTC the session
helper restored logical 2560x1440 / physical 5120x2880 at 120 Hz; the copy
path then republished `geometry 5120x2880 fmt 8 pitch 5120`. This reproduces
the prior candidate-490 failure on the guarded current release, without
evidence of a guest-wide GPU execution hang.

Local evidence: `~/macos-vm/run/scaled-mode-diag-20261015/` contains the mode
list, helper source and return values, timestamps, full serial log, QEMU
display log and restore record. The source of the refusal is
`src/RaphaelGPU.cpp::sdmaTick`: it takes copy width/height from active output
timing and rejects any source pitch narrower than that output width. The
rejection prevents an out-of-bounds tiled copy; it must remain until a
validated source geometry replaces the output timing in the copy packet.
Guest-requested shutdown then produced CORE_PROBE_PASS/returncode 0, schema-2
guard release, original recovery incomplete, and separate schema-9
MODE2/no-queue `recovered/authorizes_launch=true` in
`run/candidate-515-attempt-d20261015154833-results/`. No QEMU remains and
`power/control=on`.

## Next discriminator

AMD's [DCN3 register header](https://codebrowser.dev/linux/linux/drivers/gpu/drm/amd/include/asic_reg/dcn/dcn_3_0_3_offset.h.html)
places `DCSURF_PRI_VIEWPORT_START` and `DIMENSION` at HUBP offsets `0x5e9`
and `0x5ea`. The [Linux HUBP viewport programming
path](https://kernel.googlesource.com/pub/scm/linux/kernel/git/krzk/linux/+/d5c243989fb0cb03c74d7340daca3b819f706ee7/drivers/gpu/drm/amd/display/dc/dcn10/dcn10_hubp.c)
writes the source viewport width and height there; the fields are 14 bits at
bit 0 and bit 16. Read and log these registers for the active HUBP and its
ODM partners in both 5120x2880 and 4096x2304 modes, along with the source
pitch and output timing. This should distinguish a full 4096x2304 surface
from per-pipe crops or another scaler arrangement. Only then derive bounded
source copy geometry and keep the existing address/buffer bounds checks.
The follow-up must also check that QEMU presents the right aspect and cursor,
and that normal 5K/120 scanout, shutdown, guard release and recovery remain
intact.

## Viewport discriminator — candidate 517, metal-322

Run `dd7922903fe898f0dd0013b40b9fb212` measured all four HUBP primary
viewports. In normal mode, their X ranges cover 0..5120 with height 2880 and
pitch 5120. In scaled mode they cover 0..4096 with height 2304 and pitch 4096:
pipe 0 `0+1026`, pipe 2 `1022+1028`, pipe 3 `2046+1028`, pipe 1
`3070+1026`. The few-pixel overlaps are ODM seams. This establishes that
the viewport registers carry the actual scanout source geometry and explains
the existing `pitch < output width` refusal. Restoring the original mode
republished 5120x2880. Evidence: `run/candidate-517-results/serial.txt`.

The run's wrapper was `INVALID` because I requested guest shutdown directly
through the macOS UI during the interactive hold instead of writing the
supervisor's `stop-requested` file. That ended the serial capture service
before the supervisor's shutdown path (`forced-after-shutdown-error`), despite
an earlier complete probe. The DMA guard reported released; ordinary recovery was incomplete and
separate stopped-device schema-9 recovery reported `recovered` and
`authorizes_launch=true`. Treat the viewport observation as diagnostic evidence,
not a successful functional or shutdown qualification.

## Candidate 518 scaled source copy

Run `dbcd1eead4a5bd7c37d1293be61c682c`, metal-323, uses the four validated
viewports when the source pitch is narrower than output timing. The guest
selected logical 2048x1152 / physical 4096x2304 at 120 Hz; the copy path
published `geometry 4096x2304`, and 10-second windows copied 207, 100, 113,
and 100 frames. QEMU's host log reported the 4096x2304 guest geometry in a
3608x2064 window within the 7584x2112 work area. Restoring 5K republished
5120x2880, with continued frames. CORE_PROBE_PASS, supervisor requested guest
shutdown, schema-2 guard released. Ordinary recovery was incomplete; separate
schema-9 stopped-device recovery succeeded and authorized reuse. Evidence:
`run/candidate-518-results/`, `run/vm-launch.log` and
`run/candidate-518-auto-restore.log`.

The per-frame success diagnostic wrote hundreds of ordinary serial messages.
Remove that diagnostic before delivery; the geometry transition and periodic
frame counts already prove the source selection.

## Candidate 519 and installed release

Candidate 519 removes the per-frame success log. Supervised run
`c416a847497fc62c3fe1a6ec6a6e7858` (metal-324) passed the Metal probe.
At logical 2048x1152 / physical 4096x2304 / 120 Hz it published 4096x2304,
with 157, 99 and 101 frames in successive 10-second windows and no rejected
surface. QEMU fitted it to 3608x2064 in the 7584x2112 work area. A timed
restore returned to 5120x2880 and copying continued. The supervisor's stop
file led to guest-requested exit, released the DMA guard, and separate
schema-9 stopped-device recovery authorized reuse.

The installed `raphael-macos` launcher was updated to release 519/card
metal-324/pins v20, preserving the prior config as `release.conf.before-519`.
Its attempt `d20261015161621`, run `635a7bb73b41a07bf2409156bc613f64`,
passed the Metal probe and guest-mode window fit, then its normal `stop`
command produced guest-requested exit, released the guard and obtained an
authorizing schema-9 recovery receipt. No QEMU remained. Raw evidence:
`run/candidate-519-results/`,
`run/candidate-519-attempt-d20261015161621-results/`,
`run/raphael-macos-d20261015161621.log`.

Hosted CI for exact `dev` commit `9a7802f74643600953902459aff563d2cdd3fe5c`
passed its test and build jobs in run 38741944813; the release job was
skipped on the `dev` push.
