# Live status — 2026-10-09

## Candidate342: measured manager delivery; terminal receipt still missing

Run `00bad24a728429d67f21519fb472a563`, metal-188, build1.0.342,
MODE2#283 on bootba51b3c6. Native Metal and WindowServer ownership pass. Actual
virt-manager renders native1080p and1080HiDPI; domain XML stays unchanged and
closing the viewer leaves the original container running. Libvirt now advertises
x86_64 correctly, verifying the daemon PATH fix on the native profile.

Thirty-second in-process manager-buffer samples observe895 unique tokens at
1920×1080 (29.82/s) and555 at3840×2160 (18.50/s). This is a sampled delivery
lower bound, not GPU fps or host scanout. Median sample cost is2.24/5.28ms.
Eight native and18HiDPI samples after the first valid token fail cell/checksum
validation: complete atomic presentation remains open. Both60-second guest
fixtures finish (3,028/1,993 AppKit draws), and the normal desktop returns.

Capture: valid CORE_PROBE_PASS, no earliest failure. Outer shutdown:
exited-after-guest-request. GPU recovery: recovered, authorizes_launch=true.
VM/container stopped; host sleep:idle blocker remains active; no reboot/rebind.
**The libvirt terminal receipt is still absent.** Both EOF handlers record
RuntimeError/immediate-stop, deferred=false. Software S5 testing did not transfer
to this native result. Retained plan/receipt/module hashes match; the exact refusal
stage was not captured. Candidate343 investigates safe refusal diagnostics and
the production-only root SSH daemon before changing any admission criteria.

Performance follow-up: QEMU's nongl SPICE refresh uses its30ms default plus work;
that is a source-supported limiting candidate, not a completed causal A/B.
The presenter writes the live framebuffer row-by-row without an atomic frame
commit. Test cadence and partial-frame behavior independently in software first.
A nonfatal manager default-pool creation attempt also needs explicit private
configuration; it did not change domain XML.

Full host suite:1,128 tests pass,3 skipped. Checked-in executable/manifest match342.
[Evidence](findings/research/console-cadence-20261009.md) ·
[Artifact hashes](findings/research/console-cadence-evidence-20261009.json) ·
[Previous status](findings/research/status-archives/status-before-342-20261009.md).


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-343-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
