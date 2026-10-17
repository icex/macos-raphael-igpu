# Live status — 2026-10-14 — Tahoe desktop freeze fixed (release 506)

Host boot fe3ff623-670b-4cfc-bc58-1cda4a0258a3. No VM is running. GPU 0000:7b:00.0 is on
vfio-pci with power/control=on. The latest receipt is
run/candidate-506-attempt-d20261014152105-noqueue-recovery.json (recovered,
authorizes_launch=true, kernel_faults=[]). The desktop launcher is release 506 / metal-310;
the previous 490 config is kept at run/release.conf.before-506-20261014.

## Fixed: Tahoe desktop freeze

Root cause: Apple's GFX10 Metal defaults enable GE parameter-cache oversubscription
(`allowGePcAllocOverSub`, `GE_PC_ALLOC = OVERSUB_EN | 512 lines`, sized for Navi2x). Raphael
has 256 parameter-cache lines, so attribute-heavy late-Z draws deadlock SC/DB/SPI. Weather's
map and the Memoji picker trigger it. The resulting GPU restart storms wedged VCN, which
caused the hardware-encoder stall. The minimal reproducer hangs on 15.8.1 as well; Tahoe's
apps are simply the first to reach it.

The kext clears the flag in every Metal client through the dynamic `ge-pc-oversub`
userspace family. The bit index comes from the image's own Objective-C layout, and the
pattern is unique on both 26.7.1 and 15.8.1. There is no build allowlist. The fix is on by
default; `rgpupcoversub=1` restores Apple's setting for A/B tests. Evidence:
[findings/research/tahoe-gfx-deadlock-20261014.md](findings/research/tahoe-gfx-deadlock-20261014.md).

Verified on 26.7.1 / 25G241:
- **505 s2:** CORE_PROBE_PASS. The Weather map, Maps and Chess render at 4K. VideoToolbox
  HEVC and H.264 hardware encode with hardware decode passed (1200 frames each). Ordinary
  recovery authorized.
- **506, 40-minute soak:** 48/48 deadlock-case passes and 10/10 hardware encodes, with 0 hang
  dumps, 0 GPU restarts and 0 panics. The CR2 log stayed lossless (422/512). Ordinary
  recovery authorized.

The CR2 critical log has a 512-record lifetime budget. Tahoe's video contexts used to push
it past that limit within minutes, aborting sessions through the capture-fatal path.
Routine VCN-context, SDMA-remap and submission-trace records are now ordinary after the
first few; failures stay critical.

Host suite: 1630 tests pass, 8 skipped.

## Open: guest kernel corruption (not the GPU)

About one guest boot in four panics or hangs early, GPU-less compatibility guests included.
Observed failures:
- APFS prologues: `apfs_check_and_alloc_alt_name+0x6` invalid opcode,
  `apfs_vnop_getxattr+0xe` page fault.
- A strcmp GPF and a corrupted vtable.
- A guest `shasum` of SystemKernelExtensions.kc that disagreed with the uploaded bytes.
- Hangs with seven vCPUs spinning on a global (`tlbto_us=0`).

Host logs show no MCE/EDAC, bad-page or btrfs checksum errors; the host has non-ECC RAM, so
silent errors would not appear. The host runs kernel 7.2.9 with `kvm_amd avic=Y`.
Distinguishing host RAM from a KVM regression needs a memory test, `kvm_amd.avic=0`, or the
LTS kernel. All of these are host changes and need the user's go-ahead.

This blocked the end-to-end launcher check. The first launcher attempt stopped before
GPU exposure because its GPU-less refresh guest panicked. The manual retries then hung at
shutdown and were refused by the identity check before one sealed. The second launcher
boot panicked before any GPU work. An early guest panic leaves the runner waiting for
capture, so cancel with SIGTERM to `experiment.py`, then run
`tools/mode2-noqueue-recover.py`.

## Next

- Resolve the host-level guest corruption, then repeat the launcher session.
- The scaled-mode QEMU freeze (logical 2048×1152) remains open.

Run history for candidates 494–506:
[status-archives/20261014-tahoe-gfx-deadlock-fix-runs.md](findings/research/status-archives/20261014-tahoe-gfx-deadlock-fix-runs.md).
The paused status from before the fix:
[status-archives/status-before-tahoe-fix-20261014.md](findings/research/status-archives/status-before-tahoe-fix-20261014.md).
