# 4K / Retina feasibility: metadata passes, desktop default fails

Candidate280, stock QEMU10.1.2, macOS15.7.9/24G830; run
`aaa3f63204f17d12bcb4a8d855774cf1`, MODE2#171/exposure29 on host boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. Driver unchanged.
[Artifact hashes](remote-retina-evidence-20260916.json).

The user requested a bounded4K usability investigation, then1080p HiDPI as the
default and60/90/120Hz options. This approach is **not qualified for default use**.

## Observed sequence

- The first probe's ABI guard incorrectly passed Objective-C strings as C strings.
  It refused before a display mutation. Corrected, compiled with warnings fatal,
  and kept that failed output separately.
- A temporary `CGVirtualDisplay` accepts native3840×2160, then1920×1080 HiDPI.
  While temporary ID4128836 is online/active, `CGDisplayCopyDisplayMode` returns
  no public mode. Removing it restores fallback ID1104977160 with the requested
  dimensions. The original lifecycle probe therefore returns failure, not success.
- Separate public CoreGraphics/AppKit inventory verifies1920×1080 logical,
  3840×2160 pixel backing and2× scale on the fallback. A fresh standard RFB capture
  exports1920×1080, with a visibly correct desktop at that point. This does not
  establish transport of all4K backing pixels to the viewer.
- Requested90Hz and120Hz virtual settings are accepted, but the restored desktop
  reports60Hz in both cases. Higher refresh rates are **not verified**.
- A one-shot helper reproduced Retina fallback setup and public-mode selection.
  A per-user RunAtLoad LaunchAgent was installed to select it at login, as requested.
  Metadata still reports success. The user subsequently saw black; a fresh RAW RFB
  capture independently confirms black. WindowServer PID166 and its start time
  remain unchanged; no new WindowServer crash report was found.
- The helper was booted out and its plist renamed with a `.disabled-black-screen`
  suffix. Public selection of ordinary1080p failed. A normal supervised shutdown
  completed and schema6 recovery authorized relaunch, all CP/active/forced/timeout
  counters0 and no host kernel messages. Baseline restoration is a separate run.

Repeated allocation failures request33,423,360 bytes (3840×2176×4), including
reports with62MB free plus272MB fixed-free. Their appearance is correlated with
the failure, not proof of a primary allocator bug or a GPU performance ceiling.
Prior pressure tests showed successful reclaim/retry; that outcome must not be
transferred to this failing desktop workload without tracing it.

## Qualification and next discriminator

The initial Metal baseline is `CORE_PROBE_PASS` and strict capture is valid;
that does **not** make this Retina workload pass. The producer acknowledged
444 records, snapshot18.
The failed [helper/installer](retina-prototype-20260916/README.md) is archived as
research, not distributed as a current setup utility. No Retina LaunchAgent should
remain enabled. Keep ordinary remote desktop as the baseline.

Next isolate a single4K managed/IOSurface allocation and actual render/readback
from repeated display reconfiguration, then observe native backing/reclaim results
for the failing WindowServer surfaces. Distinguish fallback-display metadata,
actual GPU pixels, RFB-exported pixels and client frame delivery. Do not infer
60/90/120FPS streaming from a virtual mode's nominal refresh rate.

The provided decompiled bundle covers AMD/Metal/video binaries, not CoreGraphics
or SkyLight. The private display API shape was checked against the existing
project inventory probe and [Chromium's implementation](https://chromium.googlesource.com/chromium/src/+/HEAD/ui/display/mac/test/virtual_display_util_mac.mm);
runtime signatures were checked before calls. No external implementation was copied.

## Native source lead and restored baseline

The size33423360 error occurs9,138 times in the final serial artifact. Ordinary
free values span5,017,600–110,247,936 bytes; fixed-free is272,560,128 throughout.
These are log occurrences, not a count of independently identified outer requests.
The supplied24G830 decompilation locates the message in
`AMDHWMemory::allocateLargeBlocks` at0x531b6: attempted strategies fail before
logging and returning false. `allocateNonContiguous` at0x52e4a reaches
`IOAccelMemoryAllocator2::allocPages`. Indirect-call ABI/constraints and outer
wire/reclaim retries still require instruction-level and runtime validation.
Free-byte totals alone do not establish an available allocation in the required
range/alignment. Earlier reclaim successes do not establish success here.

Restore run `2456747451ac073cf5fa0ea1657590cf`, MODE2#172/exposure30 on the same
host boot, passes the initial Metal baseline. A fresh public inventory shows
1280×1024/60Hz/1× and ordinary1920×1080 in the mode list. Fresh RAW capture is
visibly correct; the user independently confirmed normal desktop. launchd reports
no `org.raphaelgpu.remote-retina` service and no active plist exists. The guest is
left available under the original supervision/deadline; final capture/shutdown/
recovery for the restore session remain pending as of this record. No further
display mutations are part of the restore allowance.
