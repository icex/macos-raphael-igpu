# Live status — 2026-09-15

Candidate 254 run `20736d213cddcb1d180d59795e3bd3a0` confirmed the secure DPG
CGC_GATE correction executed. The desktop probe passed; hardware H264 still
stalled without encoded output. PSP/decryption is an unproven hypothesis.

Artifacts: `/home/bogdan/macos-vm/run/candidate-254-results/`.
Build: `c781b5da6a7143dd98567f8ff107080c`.
Shutdown was forced; recovery receipt reports recovered/GC quiesced.
Host-after: VM stopped, vfio-pci, power pinned on, boot
`c369c74e-96ff-4c21-ae85-80ccb269f7d2`. Prelaunch MODE2 receipt 107;
no post-run MODE2. The one-run candidate-254 allowance has been consumed.
Verify live host state again before any further hardware work.

Candidate 255 is a source-audit build, not deployed or hardware-tested. It adds
MEC partial-halt rollback, SDMA inaccessible-read rejection, DPG route
prerequisite checks, Boolean VMM ABI correction and conservative wait decoding.
See [audit](findings/research/source-assumption-audit-20260915.md) for evidence,
coverage limits and remaining assumptions. Next encoder observation should
identify the exact native register wait before another loading-mode change.

No main merge/push. Original source checkout and candidate-253 files untouched.

## Validation of candidate 255

- Host suite: 931 tests run, OK, 3 skipped. Log:
  /home/bogdan/macos-vm/run/candidate-255-host-tests.log.
- All 21 standalone C++ test fixtures compiled with -Wall -Wextra -Werror and
  executed successfully. This includes MEC partial-halt and wait-decoder cases.
- Kext build succeeded (existing compiler/deprecation and linker warnings).
  Log: /home/bogdan/macos-vm/run/candidate-255-build.log.
- Built source commit: c190572e74b6e1a01181cbfa7ce53b07df61f951 (clean).
  Build ID: c333c450275142d2b7ca0ec1f68d1c51.
  Archive: /home/bogdan/macos-vm/run/candidate-255-dist/RaphaelGPU-1.0.255-experimental.zip.
- No candidate-255 hardware execution. Final read-only host check: same boot,
  vfio-pci, power/control=on, no QEMU. No runtime correctness claim for 255.

## Candidate 255 allowance (launch 70)
One launch on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2 after fresh MODE2, candidate 1.0.255 /
metal-101. Hardware validation of gpt6's six source-audit fixes (MEC halt rollback, SDMA
inaccessible-read rejection, DPG route prerequisites, Boolean VMM ABI, WAIT_REG_MEM64 decoding).
VCN DPG behavior identical to candidate 254; the VCN VCPU wall is expected to reproduce.
Manual same-boot reuse with --manual-reuse --ack-risk. Stop after codec result or first stall.
