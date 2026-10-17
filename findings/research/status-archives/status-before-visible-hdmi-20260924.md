# Live status — 2026-09-24

## Candidate318 first attempt: early FIPS panic; same-boot recovered

Run6f4c3b2d2bb525c6c622baaa9560eaa0, MODE2#244, source19f6e6e.
macOS FIPS Kernel POST Failed(-2074) in corecrypto at uptime0.36seconds;
only corecrypto listed, no Raphael startup. Display hypothesis untested.
Pre-identity capture remained pending, so used authenticated vm-supervision
shutdown on this exact CID/StartedAt; outcome forced. Runner remained intact.
Artifacts run/c318-panic-supervised-shutdown.json and candidate-318-results.
Separate stopped-device MODE2/noqueue recovery: c318-panic-noqueue-recovery.json,
schema9 recovered/authorizes_launch=true. No reboot or host driver rebind.
Retry same build in isolated attempt-pattern namespace; wake assertion must be
verified before physical observation.1020 tests OK (3 skipped), build/card valid.

## Candidate317 completed: awake mode tests; clean capture and recovery

Run2721c4fb410589d075ecccbe1046bea5, MODE2#243, source601a89e.
Firmware passed3 fresh replies. DRAM policy readback1032 with active OTG,
restores1033 when off. Awake assertion verified (`UserIsActive=1` and
`PreventUserIdleDisplaySleep=1`); HDMI enabled. Native1080p120 then1080p60
selected successfully;60Hz disables scrambling. DPG0_CONTROL0, SURFACE_INUSE0,
HUBP timeout2/underflow1 persisted. AVMUTE status0. User confirmed317 awake60Hz still black with signal; earlier316 observation
also confirmed black with signal.
Core probe passed; final verdictCORE_PROBE_PASS. Critical replay complete with
no loss. Guest exited-after-guest-request; recovery status=recovered and
authorizes_launch=true. Stopped through harness for318 output-pattern test.
Artifacts run/c317-scanout.json, c317-awake-60hz.txt, c317-awake-helper-check.txt.

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

