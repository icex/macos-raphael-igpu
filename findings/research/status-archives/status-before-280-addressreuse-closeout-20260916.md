# Live status — 2026-09-16

**Candidate 280 passes the expanded M5 texture, reclamation and GPU-event checks.**
The reproduced Screen Sharing transparency defect remains fixed. Full desktop,
independent-host-boot/crash recovery and physical display qualification remain open.

## Current host / guest

Guest is **stopped** after run `5a2f13feed4b7922fd6d109860befda0`, candidate 280 /
card metal-127 / attempt textures, MODE2 #158, eighteenth exposure on host boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. GPU `0000:7b:00.0` remains vfio-pci with
`power/control=on`. Results:
`/home/bogdan/macos-vm/run/candidate-280-attempt-textures-results`.

Functional checks pass; identity/capture valid, 387 critical records with zero loss.
Shutdown: `exited-after-guest-request`. Schema 6 recovery is `recovered`,
`authorizes_launch=true`, CP_STAT=0, active_after=0, forced_inactive=0.
Overall **CORE_PROBE_PASS**. Three completed candidate 280 runs now have clean
shutdown and authorizing recovery on this host boot.

## Verified changes and tested scope

- **Texture recreation:** 144 measured cases / 131,031,576 pixels, zero pixel or
  padding errors. Private, managed and IOSurface-backed BGRA8/RGBA8 textures at
  1024×1024 and 1003×769; one sequential and two concurrent distinct-seed clients.
  Each process returns from a 13,377,536-byte peak to its 614,400-byte allocation
  baseline after every measured case.
- **Global accounting:** free VRAM responds to pressure and returns within 532,480
  bytes of its starting value after clients exit. In-use VRAM/GART usage return to
  ranges containing their starting values; non-reusable orphan counters stay zero.
  This is bounded backing-memory evidence, not GPU-VA or long-duration leak proof.
- **Synchronization:** 32 cross-queue shared-event rounds / 33,554,432 values pass.
  Consumer submitted before producer; no CPU completion wait between submissions.
- **Prior buffer checks:** 32 measured rounds / 134,217,728 values, exact allocation
  return. Earlier feedback rendering passes 48 cases / 5,280,000 pixels, including
  concurrent clients. Native animated panels are clean in raw RFB captures, and
  the user reported no more corruption.
- **Capture/lifecycle:** candidate 280 completed runs retain 398, 370 and 387 records
  without loss; bounded routine logging preserves all strict failure/recovery gates.
- **Codecs:** hardware H.264 and HEVC encode/decode pass in their documented scope.
  Original seven sustained cases / 9,600 frames and later 120-frame checks remain
  separate evidence. Explicit decoder GPU-ID selection still fails; automatic
  required-hardware selection works. Main10/chroma/concurrent codecs remain open.
- **PerfPowerServices:** corrected QEMU observed on five fresh guest boots on one
  host boot; latest 0.0% CPU / 0.77 seconds cumulative after memory/event workloads.
- **Host suite:** 938 tests OK, 3 skipped. The driver binary is unchanged this run.

Driver build `51bfd732cf824249b70981f0c36fe314`; executable SHA256
`7d06082f35959f900b5c59cb5f6d9e2efc67df13e935d338d7783524df63259b`.
QEMU image `sha256:51cbd7dcdbad2d6492ce83a263e9854c28620d67a1ea12ebc0562c6fab2605ad`.
[New tests, global-counter analysis and limits](findings/research/texture-memory-and-events-20260916.md),
[artifact hashes](findings/research/texture-memory-and-events-evidence-20260916.json),
[visual fix](findings/research/feedback-decompression-20260916.md),
[buffer reclamation](findings/research/resource-reclamation-20260916.md).

## Remaining work

1. GPU virtual-address reclamation, longer pressure tests, broader formats/hazards.
   Existing native allocateLargeBlocks failure messages predate these passing
   workloads; correlate failed requests with callers/fallbacks before attributing
   them to capacity, fragmentation or leaks. This path remains unresolved.
2. Longer ordinary desktop use; M7 independent-host-boot and crash/closure testing.
   Historical candidate 278 OpenGL hang and live-validation crash remain unresolved.
3. Physical DCN output and performance qualification after correctness gates.

No main merge/push before full desktop proof. Additional exposure requires a
named-boot allowance and fresh successful MODE2 through tools/cycle.py.
No vfio→amdgpu cycling. [Roadmap](docs/ROADMAP.md).
