# Live status — 2026-10-10 — native EDID admission correction

Candidate432 runf21b838b06160ead592e3d93edfd5fa9 refused before creating the
libvirt/QEMU domain: systemd supervisor omitted CONSOLE_EDID, so exact paused
plan validation detected the default Bochs device instead of native1440p120.
No guest output; wrapper INVALID/identity_or_route_missing. Serial/critical empty,
no native recovery receipt. Existing stopped/noqueue admission is the next retry
path; no receipt or ledger is fabricated. MODE2 resets325/326 passed.

The supervisor forwarding gap is fixed with an actual emitted-command test.
432 GPU source remains unchanged; signed presenter is unchanged. Native120 EDID
acceptance and actual VBL cadence are untested. Host stays awake, vfio-pci and
power/control=on. Candidate430 baseline/results below remain valid.

Candidate430 attempt b, run3c4adbc6a0588d091ba5c367ffc9809b, completed.
Extra virtual display at1920×1080 logical /3840×2160 backing reports120Hz,
with correct picture/colors. Actual test source clock was60Hz; real-client
cadence was about60/s for localized changes and27/s for full-screen changes.
True120fps delivery remains unqualified. macOS Displays exposes the existing
AppleBochVGAFB85Hz metadata, not evidence of the requested transport cadence.

Removing both holder and presenter produced a black window. Keeping the original
signed presenter, explicitly capturing only the existing native display, produced
correct1920×1080 desktop and changing fixture images in actual virt-manager
screenshots. Metal probe passed all48 parent/child readback cases; window drawable
readback also matched. Parent desktop-capture preflight was false, so its capture
result is separate. The holder is unnecessary for this1080p output, but native
CVDisplayLink ran30Hz despite the85Hz label. Native modes lack4K and120Hz;
arbitrary Retina resize and5K transport remain unfinished.

Capture: valid CORE_PROBE_PASS. Shutdown: guest request sent, bounded grace expired,
forced stop; not a clean guest shutdown. Recovery: recovered, authorizes_launch=true.
Host remains awake; GPU stays vfio-pci with power/control=on. No GPU VM is running.
Evidence: ~/macos-vm/run/candidate-430-attempt-b-results/ and
[holder comparison](findings/research/console-holder-comparison-20261010.md).

Next: evaluate native QEMU EDID mode configuration before changing Apple code;
retain the working holder until Retina sizing/refresh requirements are covered.
Candidate431 has uncommitted offline64MiB/5K snapshot-capacity work, not launched.
A future native-only support option must preserve clipboard, resize and restoration.

Published dev/origin/dev is e240b38ae1d878d429369e41ab5b1179108c2a26:
clipboard/GUI USB milestone and checked-in1.0.428 binary; hosted CI38040411149
passed test/build. Main unchanged at861ba5e. Candidate430 remains local research;
1533 host tests passed (8 skipped) before this run. VirtualBox remains deferred.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-432-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-432-attempt-b-results`
- Verdict: `INCONCLUSIVE`
- Boundary: `probe_completion_missing`
