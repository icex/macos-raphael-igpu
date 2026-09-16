# Live status — 2026-09-16

Host boot2508eb6d-ddf3-497d-9774-00a7ecebe3ed. GPU0000:7b:00.0 remains vfio-pci,
power/control=on. Colorrepro run9695b71b4eb9db3f8b99eb42e8814970 is stopped:
shutdown exited-after-guest-request, recovery recovered/authorizes_launch=true,
CP_STAT=0. Artifacts: candidate-277-attempt-colorrepro-results. Baseline Metal pass;
full desktop qualification fails because green/purple backdrop corruption persists.

Use candidate277 driver1.0.277 (SHA1e50cf16c8ac4333a84b84321394cce07b28c94947e1264aa5b86463b588b17a).
Candidate278 linear-swizzle driver change is rejected; do not run its OpenGL probe.
HEVC hardware decode is fixed by exact PCI IOService S30→GFX0 rename, tested9600
frames across two guest boots. Main10/concurrency/arbitrary-media scope remains open.

Colorrepro: half gradients and installed narrow-blur shaders pass12cases each,
including offset viewport. Plain-alpha windows look clean; native colored backdrop
still fails. Filter merging/dirty regions controls did not fix it. Metal validation
crashed in CoreDisplay initialization and supplies no verdict on the corruption.
All temporary flags restored; validation environment unset. Details and artifacts:
candidate278 findings/research/transparency-live-composition-20260916.md.

PerfPowerServices100% CPU is a nonterminating SMC-key enumeration: QEMU10.1.2
rejects command0x12. A one-time correct end-of-list return stops the loop while
leaving the service alive. QEMU patch and isolated I/O protocol tests are complete;
persistent fresh-guest verification pending. See perfpower-smc-enumeration-20260916.md.

## Superseded staging-only image pin

Run5cb87082deebc345879d0c3192d39f8d (smcfix) actually launched original image3a3c82c79bc4,
because experiment prepare read IMAGE rather than cycle pins. CPU loop reproduced;
this is not a test of the patch. Baseline CORE_PROBE_PASS, guest-request shutdown,
recovery recovered/authorizes_launch=true. Two prior staging failures did not
reach QEMU/VFIO and consumed no exposures. Cycle now explicitly passes its pinned
image to prepare; regression coverage checks that handoff.

## Next exposure allowance

Standing user instruction to fix and continuously test authorizes thirteenth exposure
on boot2508eb6d-ddf3-497d-9774-00a7ecebe3ed, candidate277/card metal-124, attempt
smcverified. Same kext; derived image2ada1bb2323f4eefe430a9ea5f0e2f65cad6914aca4f9364c50b0ec3d694654c
replaces QEMU with10.1.2 plus SMC enumeration. Fresh MODE2; maximum6000seconds,
5400second interactive hold, all identity/capture-fatal/host-fault/shutdown/recovery
aborts retained. Verify PerfPowerServices from startup without debugger changes,
then resume native transparency diagnosis. No direct OpenGL workload.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-277-attempt-smcfix-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
