# Live status — 2026-09-16

**Candidate 280 passes bounded visual, codec, memory and cleanup checks.** The
reproduced Screen Sharing transparency defect and routine critical-log exhaustion
are fixed. Full desktop and physical display qualification remain open.

## Current host / guest

Guest is **stopped** after run `0795287602bef3497900423ebc89a178`, candidate 280 /
card metal-127 / attempt reclamation, MODE2 #157, seventeenth exposure on host boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. GPU `0000:7b:00.0` remains vfio-pci with
`power/control=on`. Results:
`/home/bogdan/macos-vm/run/candidate-280-attempt-reclamation-results`.

Functional checks passed; identity/capture valid, 370 critical records with no loss.
Shutdown: `exited-after-guest-request`. Recovery: schema 6 / `recovered`,
`authorizes_launch=true`, CP_STAT=0, active_after=0, no forced HQD clears.
Overall **CORE_PROBE_PASS**. Both completed candidate 280 runs now have clean
shutdown and authorizing recovery; this does not qualify crash or independent-boot recovery.

## Verified changes and scope

- **Transparency:** guarded feedback expansion repair retained. Fresh 280 raw RFB
  captures show clean animated native panels. Four distinct-seed processes (two
  sequential, two concurrent) pass 48 cases / 5,280,000 pixels, with zero mismatches
  and maximum error 1 byte. Fresh 279 passed the original 12 cases; user reported
  no more corruption. Longer ordinary desktop use remains unqualified.
- **Memory:** 32 measured allocate/copy/release rounds after three warmups, 48 MiB
  live resources per round. All 134,217,728 measured values match; process-local
  Metal allocation returns from 50,974,720 to exactly 544,768 bytes every round.
  Global VRAM/backing/VA reclamation and broader resource types remain open.
- **Capture:** routine serial detail retained, successful COW critical samples
  bounded, all failures still critical. Strict loss/recovery gates unchanged.
  Completed 280 runs retain 398 and 370 records with no loss.
- **Codecs:** first 280 run passes 120-frame HEVC and 120-frame H.264 hardware
  encode/decode, maximum luma error 0/1. Original seven sustained cases / 9,600
  frames remain separate evidence. Explicit decoder GPU-ID selection still fails;
  automatic required-hardware selection works. Main10/chroma/arbitrary media and
  concurrent codecs remain unqualified.
- **PerfPowerServices:** corrected QEMU observed on four fresh guest boots on one
  host boot. Latest 0.0% CPU / 0.74 seconds cumulative after memory workload.
- **Host regression suite:** 938 tests OK, 3 skipped.

Driver build `51bfd732cf824249b70981f0c36fe314`; executable SHA256
`7d06082f35959f900b5c59cb5f6d9e2efc67df13e935d338d7783524df63259b`.
QEMU image `sha256:51cbd7dcdbad2d6492ce83a263e9854c28620d67a1ea12ebc0562c6fab2605ad`.
[Visual mechanism](findings/research/feedback-decompression-20260916.md),
[capture correction](findings/research/critical-record-overflow-20260916.md),
[first 280 evidence](findings/research/candidate-280-qualification-20260916.json),
[memory method and limits](findings/research/resource-reclamation-20260916.md),
[reclamation evidence](findings/research/resource-reclamation-evidence-20260916.json).

## Remaining work

1. Global backing/VA accounting, texture/IOSurface recreation and broader M5
   synchronization coverage beyond passing process-local buffers and BGRA8 feedback.
2. Longer ordinary desktop interaction; M7 independent-host-boot and crash/closure
   qualification. The historical candidate 278 OpenGL hang and live-validation
   crash remain unresolved diagnostic paths.
3. Physical DCN output and performance qualification after correctness gates.

No main merge/push before full desktop proof. Additional exposure requires a
named-boot allowance and fresh successful MODE2 through tools/cycle.py.
No vfio→amdgpu cycling. [Roadmap](docs/ROADMAP.md).

## Next bounded run allowance

The user requests the next roadmap items. Authorize the eighteenth exposure on
host boot2508eb6d-ddf3-497d-9774-00a7ecebe3ed, candidate280/cardmetal-127, attempt
textures: private/managed/IOSurface texture recreation, two pixel formats and two
sizes, CPU-checked upload/readback through two host-ordered queues, distinct-seed
sequential/concurrent processes, and observational global accounting samples.
Prior run has an authorizing recovery receipt. Require fresh MODE2 with CP_STAT=0
and RLC_CNTL=0; preserve all capture, host-fault, identity and cleanup aborts. Maximum
6000seconds, manual stop after bounded tests. No driver change or main push.


Same eighteenth exposure: texture checks passed. Extend the bounded workload to
32 GPU shared-event rounds on two queues (consumer submitted first, 12 MiB live
buffers, 20-second GPU deadline) and read-only post-client-exit global statistics.
This uses the same current280 binary, supervision and original run deadline.
