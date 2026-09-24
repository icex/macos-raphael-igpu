# Live status — 2026-09-24

## Candidate316 completed: native1080p120 programmed; capture overflow

Runb8e786fba900fe589729c5d3fdbb537d, MODE2#242, source81c08b6.
Initial modeset preceded firmware readiness; late reload passed3 queries.
A subsequent native CG session transaction selected1920x1080 pixel/logical120Hz;
OTG totals2199/1124 and15 delivered HDMI commands confirm new programming.
Physical observation was requested but no response yet; do not claim picture.
Bright paired colors readbackff00ff00, but DPG_CONTROL0 after active modeset:
the color-only diagnostic did not force an active test pattern. HUBP timeout/
underflow and zero SURFACE_INUSE persist. Probe passed; final verdictINVALID:
critical records reached512, dropped147 during inspection. Harness stopped it.
Guest exited-after-guest-request; ordinary recovery failed for replay loss.
Separate stopped-device recovery `run/c316-noqueue-recovery.json` recovered,
schema9 authorizes_launch=true. No reboot, sudo, runner kill or amdgpu rebind.
Evidence run/c316-color-scanout.json, c316-mode-trigger.txt, candidate-316-results.
First preparation failed before QEMU for missing card argument, fixed offline;
MODE2#241 passed with no exposure or ledger consumption.

Next317 uses Linux's force-SR-off policy only after firmware readiness while an
OTG is requested on, retaining the established startup/idle/P-state safeguard.
Bound successful repetitive critical summaries; all ordinary serial output and
critical failure records remain. No merge/push of316 diagnostic-only changes.

## Candidate315-watch completed: black signal; replay loss; same-boot recovered

Run3d5f576073db234cc14c2191991bf3ed, MODE2#240, source9886c30.
User confirms HDMI signal but black output after wake and manual resolution changes.
120Hz advertised for native1080p; programmatic mode transactions did not establish
an active120Hz mode. Latest report4K pixels/1920x1080 logical@60Hz.
DPG0_CONTROL41 with constant colors; HUBP0 timeout/underflow and SURFACE_INUSE0.
Core probe passed; final verdictINVALID from CR2 capture loss. Do not claim
complete capture. Guest exited-after-guest-request; ordinary recovery failed for
capture loss. Stopped-device MODE2/noqueue recovery completed separately:
`~/macos-vm/run/c315-watch-noqueue-recovery.json`, schema9, authorizes_launch=true.
No reboot, host sudo, runner kill or amdgpu rebind.

Candidate316 prepared on fresh fetched devca160d3: bright OPP0 blank-color diagnostic.
Source81c08b6, metal164.1020 host tests OK (3 skipped), build passed.
First316 preparation stopped before QEMU: card omitted diagnostic bootarg. Fixed
and validated offline. MODE2#241 passed; no hardware exposure/ledger entry.
Diagnostic changes color only, retaining native DPG control/status handshakes.
This tests downstream display output, not desktop scanout qualification.

## Candidate315: HDMI commands consumed; Samsung online; clean recovery

Run909d7c9412f825b8b7079f92b67f39be, metal163, source9886c30,
boot5074c0e5-b2f6-46da-99b2-299ba322b41e, MODE2#239.
Service `rgpu-candidate315-hdmi.service`; results
`~/macos-vm/run/candidate-315-attempt-hdmi-results/`.

- **Functional:** prior firmware held before TMR replacement; PSP reload/start
  again passed three fresh version queries. Empty inbox reversible verification
  passed.17 HDMI VBIOS commands consumed in10–820us, pointers both440, no timeout.
  Live OTG0 scanning; DIG0 HDMI/enable/symbol clock on; HPD0 high. Live macOS
  system_profiler now reports Odyssey G95NC online/main,3840x1080,1920x540 logical,
  about59Hz,30-bit color. User visual confirmation is pending; do not claim an
  observed physical picture yet. Core probe passed; offscreen1000frames,
  736 sampled pixels, zero mismatches. Broader desktop capture is not qualified.
- **Capture:** probe JSON complete; initial report caught the Samsung before
  attachment, but later ioreg and system_profiler show it present and online.
  Native nonfinite-report test passed in a separate GPU-less session.
- **Shutdown/recovery:** the300-second interactive inspection window expired;
  exited-after-guest-request and recovered/authorizes_launch=true. Final verdict
  CORE_PROBE_PASS. No stop file or forced shutdown was used.
- **Evidence:** `~/macos-vm/run/c315-live-dcn.json` (reads via QEMU's existing
  MMIO mapping, no new VFIO owner), `c315-live-displays.txt`,
  `c315-live-display-profile.json`, and the active run's serial/probe.
  The requested host9231ea43 trace contains relevant OTG activity but no matching
  DIG0/PHY programming, so it cannot supply a complete PHY comparison.
- **Next:** obtain the pending Samsung observation. If no picture, continue from
  this running state and compare timing/encoder/PHY configuration. HDMI audio
  follows picture: physical audio function7b:00.1 (1002:1640) is still host-owned
  by snd_hda_intel and is not passed to the guest; no audio binding changed.

1020 host tests OK (3 skipped); build/dry-run passed. First315 preparation stopped
before exposure for the new probe identity; MODE2#238 passed and no launch was
consumed. Supervised GPU-less compilation24G830 passed-Werror and the nonfinite
JSON test, then exited-after-guest-request. Current probe source8b4bc8cf71eb3eb9,
binaryebbde2976f4780a4; full identities in run/guest-identity.json, old one backed up.

The DMCUB startup milestone through314 is integrated/pushed and remote-verified
at dev345eded.315 remains on its fresh candidate branch; next repeat uses a longer screen-check window.
User explicitly authorized autonomous tests/resets, preserving host safety.
No reboot, sudo or same-boot amdgpu rebind was used.

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

1. Sustained4K remote delivery and input latency; preserve crisp Retina60Hz,
   then qualify login persistence.90/120Hz modes remain unproven.
2. Guest-crash/command-channel failure, repeated lifecycle and independent-host-boot
   qualification. Existing clean stops do not qualify every failure mode.
3. Broader applications, render hazards, interprocess synchronization and page-table
   release. Historical direct OpenGL hang and live Metal validation crash remain open.
4. Physical DCN output, other hypervisors and measured performance/release qualification.

StockQEMU10.1.2/OpenCore/VirtualSMC1.3.7 works in this tested setup;
PerfPowerServices was0.0% CPU on two guest boots. Automatic required-hardware HEVC
decode works; explicit GPU-ID selection remains limited. Main10 decode has scoped
passes; hardware encode is Main8. [Roadmap](docs/ROADMAP.md).

After milestones update current docs, integrate/push dev and synchronize the local
checkout. Do not push main without new authorization. Prior live entries are [archived](findings/research/status-archives/status-before-display-port-20260917.md)
and [earlier](findings/research/status-archives/status-before-night-close-20260916.md).


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-312-results`
- Verdict: `EXECUTION_FAILED`
- Boundary: `first_submission`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-313-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-314-results`
- Verdict: `EXECUTION_FAILED`
- Boundary: `first_submission`

The prior status entry briefly described the run as active just as its300-second
inspection deadline expired. It was corrected after reading the final receipts.
Next315-attempt-watch extends interactive hold to5000seconds within the unchanged
6000-second overall cap; no test/reset approval is requested. Physical-screen
observation is still pending, not inferred from software state.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-316-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`
