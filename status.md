# Live status — 2026-09-15

## Current result

**Candidate263 tested decoder-first initialization on macOS; hardware H264 still
stalls on frame2.** Native decoder initialization executed successfully before
the first pause, so this intervention is not a sufficient encoder fix.

- Boot `c782d007-ca85-409b-9cf5-ff12c1a8c6d5`; Raphael `0000:7b:00.0` now on
  `vfio-pci`, `power/control=on`, PCI reset methods disabled. Linux→VFIO handoff
  was explicitly requested; do not rebind to amdgpu again this boot.
- Candidate `1.0.263`, card `metal-109`, run `0c2f9fbdbbd63473ceae1905d381412d`,
  build `8d6ca8d6f132475cb4d881241a15fbc3`, built source `b124552`.
- Artifacts: `/home/bogdan/macos-vm/run/candidate-263-results`.
  Worktree: `/home/bogdan/macos-vm/run/worktrees/candidate-263`.
- Native decoder existed, inactive, owner/callback guards passed: ring65536bytes,
  GPU address `ff_bfdc5000`, callback +94fa3. RBC control changed `1101010c→11010110`,
  BAR `0_264000→ff_bfdc5000`; native initializer returned0. Ring pointers0.
  The old BAR was a retained Linux value, not evidence of fresh macOS decoder setup.
- Following pause wait +94db1 timed out, expected8/mask8 at register1:14.
  Encoder selected hardware, accepted frames0/1, stalled at2; probe deadline124,
  no encoded callbacks. Software control passed3frames with max luma error1.

## Separate qualification and cleanup

Desktop probe passed; harness verdict **CORE_PROBE_PASS**. This verdict does not
include the independently run encoder workload, which failed. Critical capture
survived this run with the publication correction included. Shutdown was
**forced**, not clean guest shutdown; recovery receipt **recovered**.
Only `rgpu-inhibit` remains running. MODE2 reset120 preceded the real launch.
Reset119 preceded a staging version-gate refusal; no QEMU/VFIO launch entry was
consumed by that refusal. New boot ledger now contains one launch.
Full host suite937tests OK, three skipped; staging gate tests also passed.

## Next discriminating test

Test the shared-memory window size separately: expand native-owned allocation
and programmed size from96 to4096bytes, matching Linux. Preserve decoder-first
setup, shared flags, allocation domain, firmware mode and all other behavior.
Check the runtime size and SRAM content before interpreting the result.

Linux baseline remains the working reference: H264/HEVC encode/decode and600
validated H264 frames. Working Linux also reads cache BAR/reset/LMA asffffffff;
these reads are not proof of a dead VCPU. Real SMU message6/address transport and
input firmware bytes match our macOS path. Details:
[Linux comparison](/home/bogdan/macos-vm/run/worktrees/linux-vcn-baseline/findings/research/linux-vcn-baseline-20260915.md).

Physical scanout and full desktop presentation remain unqualified. No merge/push.
Use candidate worktrees and cycle.py; preserve all safety, capture and cleanup gates,
6000secondmaximum, and explicit boot-named allowances. Prior Linux status is archived
in root `findings/research/status-archives/status-before-macos-linux-findings-20260915.md`.

## Candidate264 allowance

User authorized testing the Linux findings on macOS. Allow one further launch on
boot c782d007-ca85-409b-9cf5-ff12c1a8c6d5 for the4096byte shared-window hypothesis.
Candidate263 recovered; require fresh MODE2, pinned power, unchanged identity and
all capture/abort/cleanup gates. Max6000seconds; stop after first encoder stall or
verified output. This is the second launch in this boot, within ledger allowance3.
No amdgpu rebinding, reboot, merge or push.
