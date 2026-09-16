# Live status — HEVC capability investigation, candidate 276

Boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, GPU on vfio-pci, power/control=on,
no QEMU at start. User explicitly requested fixing HEVC decode and repeated testing.
Allowance extended on this named boot by one exposure (fifth total), for candidate
276 capability diagnostics with fresh MODE2, manual-reuse + ack-risk, up to 6000s,
and all identity, capture, host-fault, shutdown and recovery gates retained.
Further runs require a new recorded evidence-based allowance before exposure.

Candidate 276 retains candidate 275 GPU behavior. It adds a read-only probe of the
exact AppleGVA IORegistry lookup and Metal service identities.
Hypothesis: the decoder's selected service cannot see IOGVAHEVCDecode. Falsifier:
that exact service returns the property in the failing decoder process.

Correction: 5cb7876d's supposed HEVC hardware decode success was a hardware encode
plus explicitly SOFTWARE decode (archived embedded source sets EnableHardware...
VideoDecoder to NO). Hardware HEVC decode has no demonstrated success in reviewed
captures. AppleGVA capability lookup failure is observed; topology flakiness and
impossibility of a bounded driver fix are unproven. H.264 decode and both encoders
have positive three-frame evidence. Full desktop/display and sustained codecs
remain unqualified. No main merge or push.

Previous state: findings/research/status-archives/status-before-hevc-audit-fix-20260916.md.

Prelaunch: MODE2 #138 clean; staging refused unregistered candidate/card pair.
No QEMU/VFIO launch; no exposure ledger entry consumed. Added exact 276/metal-123
card registration with unchanged safety contract.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-276-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`

## Candidate 276 observed result

Run `84e8479030e7d41098a3751309dc2d26`, fifth exposure of boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`, MODE2 #139 clean.
`candidate-276-results/capability-lookup-output.txt`: only named display found is
IOResources/IOKitRegistryCompatibility/display, all HEVC property searches null.
Actual GPU service is PCI0/AppleACPIPCI/S30@6; Metal enumerates ONE device, and its
accelerator has the complete HEVC capability dictionary. This directly refutes
the claim that the actual PCI node is already named display.
`hevc-baseline-output.txt`: hardware-required HEVC create fails -12913, and -12906
with explicit registry ID; no decoded frames. The post-log wrapper omitted its
exit marker (shell exit before marker), so process status is not qualified by that
artifact; the recorded create failures are explicit.
Functional baseline CORE_PROBE_PASS; guest-requested shutdown, recovered receipt,
and no GPU/host fault was reported; host-kernel-messages.json includes network messages.
Next: rename only the exact marked Raphael PCI node S30 to GFX0 in IOService plane,
then repeat lookup and hardware-required decode. No topology redesign indicated.
