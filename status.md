# Live status — 2026-09-16

Candidate282 is testing a targeted fix for4K Sunshine encoder stalls. Its guarded
allocation-diagnostic sampling patch is installed; generated-pattern4K codec checks pass. User now reports1080p60 and4K20–30FPS;
post-fix stream timing is not yet independently captured.
The transparency fix and prior codec/Metal passes retain their documented scopes.
Full desktop, physical output and release qualification remain open.

## Current host / guest

- Boot: `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`; GPU0000:7b:00.0 on vfio-pci,
  power/control=on. No vfio→amdgpu cycling.
- Run: `560b1d7e8fea56b2c6f52fd7644d23f8`, candidate282/metal130, MODE2#175,
  exposure32. Its named-boot allowance is consumed; no further exposure authorized.
- Build: `7a26b1a2f6694ae88ed889105de30bc7`; executable SHA256
  `9c7e5dffc64fef69e874ea3c8e7b940e9761caf53e31400d2dc68d1591724fc2`.
- ALLOCLOG guarded=1 installed=1; native import stub resolves to expected kprintf.
  Baseline Metal probe completed. Capture ongoing; final validity and cleanup pending.
- Retina restored manually:1920x1080 logical/3840x2160 backing,2x,60Hz.
  Login agent exited0 but backing reverted1080p after boot; persistence remains open.
- Sunshine742 uses hardware-only VideoToolbox. LAN server192.168.0.43:48989,
  webhttps://192.168.0.43:48990; existing LAN-only UFW rules retained.
  Relay and guest share the existing supervised deadline; no unlimited session.

Candidate281 stopped cleanly with CORE_PROBE_PASS, valid capture and schema6
recovery authorizing relaunch. Its patch reported installed=0 because it compared
the import stub directly with kernel kprintf. User still observed3–4FPS.
Candidate282 validates the stub destination before changing only this diagnostic
CALL. Native allocation/retry/false returns/counters and global logging are unchanged.
[Investigation](findings/research/allocation-log-thunk-20260916.md).

## Current blocker and next observation

Prior active4K stream completed43 encoder submissions in12 seconds, matching the
reported3–4FPS. Native allocation failures averaged about1.9ms despite much faster
allocation primitives. Diagnostic logging is the testable hypothesis, not yet a
proven root cause. Two4K HEVC checks pass24+60 frames,689,188,500 luma samples checked, maximum error2.
Under the second workload, failed allocation calls average41–60us; the prior
active stream averaged~1.9ms. Workload differences prevent a streaming speedup claim.
User now observes1080p60 and4K20–30FPS after the installed patch, confirming
a substantial practical improvement.4K60 remains open; no published exact CPU
encoder FPS ceiling was found. Separate capture/conversion/encode timings next.
[Hardware capability check](findings/research/9800x3d-streaming-capabilities-20260916.md).
[Baseline evidence](findings/research/sunshine-performance-20260916.md).

## Verified progress

| Area | Evidence and scope |
|---|---|
| Managed texture ownership | 96 cases;111,658,032 pixel comparisons; synchronized CPU writes and retained LOAD color contents, zero mismatches |
| Cross-process GPU events | Typed XPC import;33 consumer-first transfers,25,453,131 correct pixels |
| Two-process IOSurface | 32 bidirectional GPU-copy rounds;49,363,648 pixels, zero mismatches; host completion orders transfers |
| Depth/stencil/MSAA | 128 cases at1×/4× and64×64/1003×769;49,625,792 correct pixels |
| Main10 decode | 32 frames, 720p/1080p, 71,884,800 full-plane luma/chroma samples, exact software-reference match |
| Buffer/address reuse | 512 measured rounds, 2,147,483,648 correct values; all 6,144 measured address assignments reused earlier ranges; allocation returns exactly to 544,768 bytes |
| Larger allocations | 192 MiB live resources, four measured rounds, 67,108,864 correct values, exact allocation return |
| Native reclaim | 81 traced calls: 41 true, 40 false; all 40 false returns followed by same-thread/map success; 1,525 internal wire failures observed |
| GPU fences | 128 untracked blit/compute/blit rounds, 134,217,728 correct values; prior cross-queue shared-event checks also pass |
| Native desktop | Three minutes of moving/resizing native material windows; four clean raw RFB captures |
| Safari | Two-minute transparency/blur/scrolling page; three clean captures plus clean desktop after larger-buffer pressure |
| Stock QEMU / PerfPowerServices | OpenCore/VirtualSMC fix passes two guest boots,0.0% CPU, latest0.86s; prior patched-QEMU evidence retained separately |
| Host regression | 965 tests OK, three skipped |

Earlier texture recreation (144 cases / 131,031,576 pixels), feedback rendering
(48 cases / 5,280,000 pixels), and hardware H.264/HEVC encode/decode retain their
separately documented passing scopes. Explicit decoder GPU-ID selection remains
a selection limitation on the built-in topology; automatic required-hardware selection works.

Prior qualified280 driver build `51bfd732cf824249b70981f0c36fe314`; executable SHA256
`7d06082f35959f900b5c59cb5f6d9e2efc67df13e935d338d7783524df63259b`.
Current stock QEMU image `sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c`.
Default experiment pin now selects this stock image. VirtualSMC1.3.7/gen2 and the
exact OpenCore DSDT ownership patch are required; prior media backups remain available.
[Address/desktop qualification](findings/research/address-reclaim-desktop-20260916.md),
[artifact hashes](findings/research/address-reclaim-desktop-evidence-20260916.json),
[native retry analysis](findings/research/allocation-retry-analysis-20260916.md),
[visual fix](findings/research/feedback-decompression-20260916.md).


## Remaining roadmap

1. Measure/fix4K remote delivery; preserve crisp Retina60Hz, then qualify login
   persistence.90/120Hz modes remain unproven. Screen Sharing RAW black captures
   are not a universal oracle for the user-visible Retina desktop.
2. Guest-crash/command-channel failure, repeated lifecycle and independent-host-boot
   qualification. One abnormal-QEMU-close/recovery/relaunch sequence has scoped evidence.
3. Broader applications, render hazards, interprocess synchronization and page-table
   release beyond cached address reuse. Historical direct OpenGL hang and live Metal
   validation crash remain unresolved; no blind reruns.
4. Physical DCN output, other hypervisors and measured performance/release qualification.

StockQEMU10.1.2/OpenCore/VirtualSMC1.3.7 works in the tested setup; two guest boots
verified0.0% PerfPowerServices CPU. Independent-host-boot durability remains open.
HEVC automatic required-hardware decode works; explicit GPU-ID selection remains
limited on this topology. Main10 decode passes scoped cases, encoder supports Main8.
[Roadmap](docs/ROADMAP.md), [setup](docs/stock-qemu-smc.md).

After each verified milestone update README/status/roadmap/current docs and push dev,
then fast-forward the clean local dev checkout. Do not push main without new authorization.
Licensing/provenance work remains tracked in[the audit](findings/research/licensing-audit-20260916.md).
The previous state and consumed allowances are[archived](findings/research/status-archives/status-before-allocation-thunk-20260916.md).
