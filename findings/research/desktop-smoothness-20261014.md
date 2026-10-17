# Desktop smoothness: VRAM cache and scanout copy (releases 507–509, 2026-10-14)

## Symptom

On release 506 at 3840×2160 / 120 Hz (logical 1920×1080), dragging windows was visibly
choppy in QEMU's window, with occasional stalls of a quarter second. Neither the GPU (30–60 %
busy) nor WindowServer (about half a core) was saturated.

## Measurement

`tools/rgpu-window-test.sh` runs `tools/rgpu-window-stress.m` in the logged-in guest session:
one to three large windows with changing content move continuously and are resized every two
seconds, so WindowServer composites and allocates new window surfaces the way a drag does. A
small CAMetalLayer window moves too and records every drawable's `presentedTime`. The host
reads, for the same interval, the kext's SDMA copy rate (frames reaching QEMU's window),
Apple's `AMD ERROR! Failed to allocate` lines, WindowServer CPU and the accelerator's
VRAM/orphan statistics. `tools/rgpu-top.sh` gives a per-second view.

## Cause 1: Apple's reusable-allocation cache filled VRAM (fixed in 508)

`IOGraphicsAccelerator2::start` initialises `IOAccelOrphanedMemoryPool` (freed GPU
allocations kept for reuse) with a limit of `hw.memsize / 4` and prunes only above it. On the
14 GB guest that is 3.67 GB (`0xdac00000`), independent of VRAM. With 4 GB of UMA VRAM the
cache held 3.4 GB in 6,663 allocations while 16 MB remained free, and WindowServer surface
allocations failed (698 in one minute), with app-side stalls up to 235 ms. Raising the BIOS
carve-out from 2 GB to 4 GB only delayed the same state.

Release 508 routes the exported symbol
`IOAccelOrphanedMemoryPool::init(IOGraphicsAccelerator2*, unsigned long long, unsigned int)`
and lowers a finite limit to `min(rgpuorphanmb, VRAM / 4)`, 512 MB by default;
`rgpuorphanmb=0` keeps Apple's value. The unlimited non-reusable pool is unchanged. On 26.7.1
the kext logged `limit 0xdac00000 -> 0x20000000`. Pruning releases an allocation only once its
GPU events have completed, so the cache settles near 1.7 GB rather than 512 MB; over a 10-minute
three-window stress it stayed bounded, VRAM kept about 1.5 GB free and no allocation failed.

**Not sufficient in real use.** After about 40 minutes of the user's own session on 509
(Photos, Safari, Mail), the cache held 3.18 GB in 1,534 allocations, 14 MB were free and 1,092
allocations had failed; a 20-second drag test then measured 350 failures, 103 presented fps,
p99 25 ms and a worst frame of 66 ms. Every pruning path (`pruneReusableOrphanedMemory`,
`releaseOrphanedMemory`) only calls `IOAccelMemory::pruneOrphanedMappings`, which releases a
mapping when `IOAccelMemoryMap::testEvent` reports its GPU event complete; the memory is freed
with its last mapping. Allocations whose events never test complete therefore stay cached
regardless of the limit.

**The real VRAM cache (fixed in 512).** The accelerator initialises two orphan pools. The 508
clamp hit the first (finite limit `hw.memsize / 4`, aged), which the periodic collector prunes:
it is the system-memory pool. The second is initialised with an unlimited limit and age 0, is
pruned by no collector, and is emptied only by `unwireAllVidMemory` and the sleep path
(`releaseOrphanedMemory`): it holds freed VRAM. A read-only `IOAccelMemoryMap::testEvent`
diagnostic (510, `rgpuevdiag=1`) logged no failing tests, consistent with that pool never being
walked. Release 511 routes the exported `IOAccelOrphanedMemoryPool::addMemory` and
`AMDRadeonX6000_AMDHWMemory::allocateLargeBlocks` and calls the pool's exported
`releaseOrphanedMemory` for the VRAM pool after an allocation failure or at most every 30 s,
inside `addMemory` (the lock context Apple's collectors use). A security review found that 511
released after Apple's `addMemory`, which could free the allocation being added while its caller
still held it; 512 releases first. With 512 a three-window stress kept the cache near 350 MB
with 2.5 GB free and no allocation failures; `rgpuvidorphan=0` disables it.

## Cause 2: the scanout copy dropped frames (fixed in 509)

With allocation failures gone the window was still choppy. The Metal probe showed macOS
presenting at 120.0 fps (p99 8.35 ms, max 8.6 ms) while the kext copied only 9 frames per
second into QEMU's window. The copier treated a frame as new only when the scanout address
differed from the last copied one, and skipped polls while a flip was pending. macOS rotates
two or three buffers, so after one missed flip every later frame matched the copied address and
waited for the 100 ms refresh.

Release 509 samples the scanout address on every 1 ms poll, including while a copy is in
flight, marks any change dirty and copies dirty frames, including a pending flip's already
rendered surface.

| Release (120 Hz, 25–60 s runs) | Frames reaching QEMU's window | macOS presents | Allocation failures | App stalls > 50 ms |
| --- | ---: | ---: | ---: | ---: |
| 507, 3 windows | 33.8 fps (13 worst 10 s) | — | 698 | 14 (worst 235 ms) |
| 508, 1 window | 9.2 fps | 120.0 fps, p99 8.35 ms | 0 | 0 |
| 509, 1 window (×2) | 119.9 fps | 119.9 fps, p99 8.4 ms | 0 | 0 |
| 509, 3 windows | 119.9 fps | 119.8 fps, p99 8.3 ms | 0 | 1 |

The user confirmed the desktop feels smooth on 509. Background Photos analysis
(`mediaanalysisd`) can occupy half of the GPU for a while after installs and lowers results
taken during that time.

## Also in these releases

- 507: guest clipboard on the iGPU display. QEMU's built-in vdagent closes its port after a
  second capability announcement, and the guest agent replied to QEMU's request after its own
  announcement; it now announces once. `start-console.sh` also keeps the clipboard agent running
  when there is no console bridge. Pins v16 restore QEMU's Machine › USB Devices… menu, and
  the launcher gains a **USB devices…** action.
- 507: the desktop Metal probe casts `CGImageAlphaInfo` explicitly; Xcode 26.5's clang, which
  became the guest's `xcrun` default, rejected the implicit conversion under `-Werror`.
- `tools/rgpu-display-mode.m` lists display modes; setting a mode from the command line is
  refused on the virtual display (`CGDisplaySetDisplayMode` error 1000).

## QEMU window aspect (510, user-confirmed)

QEMU image c510 (pins v17+) enables the zoom-to-fit aspect snap for the iGPU display
(`RGPU_SNAP_ASPECT=1`) and makes it follow the axis the user changed: a width change sets the
height, a height change sets the width, 150 ms after the resize settles. Tested through KWin
scripting: 1300×500 settled at a 1111×625 picture, width 1000 at 992×558, height 450 at 688×387,
all 16:9; the user confirmed resizing works. A live window-manager aspect hint is not used
because KWin made corner drags stick with it.

## Open: audio silence while macOS composites at about 120 fps

A 440 Hz tone played with `afplay` in the guest and recorded from the host sink monitor
(`pw-record -P '{ stream.capture.sink=true }'`) has no gaps at idle and none under 20 s of
offscreen GPU load, but during the three-window stress at 3840×2160 / 120 Hz (QEMU window 104
fps, macOS presenting 107 fps) 22 of 30 s were silent, with short bursts at each periodic
resize. QEMU's main thread was 2.8 % busy, PipeWire counted no errors, `coreaudiod` logged no
overloads, an xHCI trace showed a steady ~1042 isochronous packets per second, and QEMU's
usb-audio (513 counts odd-sized and dropped packets) dropped none. These counters establish
continued packet flow, not silent packet contents: they do not measure sample amplitudes. The
origin of the silence remains unresolved. Not fixed by a 256 ms usb-audio buffer with 80 ms PulseAudio
latency (510), 48 kHz audio output or accepting variable packet sizes (513). The display copy's
1 ms poller costs about 17 µs per tick (514 statistics). The failing state needs the user's
monitor on: with the host display off the virtual sink starts at 5120×2880 / 60 Hz and macOS
presents almost nothing, so audio stays clean. Release 514's card metal-319 caps the copy at
30 per second (`rgpusdmamaxfps`) to separate copy rate from compositing load in the next run.
