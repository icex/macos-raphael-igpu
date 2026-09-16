# Live status — 2026-09-16

**Candidate 280 passes longer buffer/address, explicit GPU-fence and broader desktop checks.**
The reproduced transparency corruption remains fixed. Native allocation errors were
traced to successful reclaim/retry under pressure; the message alone is not a
reproduced correctness blocker. Full desktop and physical display acceptance remain open.

## Current host / guest

Guest is **stopped** after run `dd5c30a35fea14f9be511dee92ff85be`, candidate 280 /
metal-127 / attempt addressreuse, MODE2 #159, nineteenth exposure on host boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. GPU `0000:7b:00.0` remains vfio-pci,
`power/control=on`. Results:
`/home/bogdan/macos-vm/run/candidate-280-attempt-addressreuse-results`.

Identity/capture valid: 372 critical records, zero loss. Guest-request shutdown;
schema 6 recovery `recovered`, `authorizes_launch=true`, no retained host faults.
Overall **CORE_PROBE_PASS**. Four candidate 280 runs now have clean shutdown and
authorizing recovery on this host boot.

## Verified progress

| Area | Evidence and scope |
|---|---|
| Buffer/address reuse | 512 measured rounds, 2,147,483,648 correct values; all 6,144 measured address assignments reused earlier ranges; allocation returns exactly to 544,768 bytes |
| Larger allocations | 192 MiB live resources, four measured rounds, 67,108,864 correct values, exact allocation return |
| Native reclaim | 81 traced calls: 41 true, 40 false; all 40 false returns followed by same-thread/map success; 1,525 internal wire failures observed |
| GPU fences | 128 untracked blit/compute/blit rounds, 134,217,728 correct values; prior cross-queue shared-event checks also pass |
| Native desktop | Three minutes of moving/resizing native material windows; four clean raw RFB captures |
| Safari | Two-minute transparency/blur/scrolling page; three clean captures plus clean desktop after larger-buffer pressure |
| PerfPowerServices | 0.0% CPU, latest 1.04 s cumulative; corrected QEMU on six guest boots, all on one host boot |
| Host regression | 938 tests OK, three skipped |

Earlier texture recreation (144 cases / 131,031,576 pixels), feedback rendering
(48 cases / 5,280,000 pixels), and hardware H.264/HEVC encode/decode retain their
separately documented passing scopes. Explicit decoder GPU-ID selection remains
unresolved; automatic required-hardware selection works. No new codec claim this run.

Driver build `51bfd732cf824249b70981f0c36fe314`; executable SHA256
`7d06082f35959f900b5c59cb5f6d9e2efc67df13e935d338d7783524df63259b`.
QEMU image `sha256:51cbd7dcdbad2d6492ce83a263e9854c28620d67a1ea12ebc0562c6fab2605ad`.
[Latest qualification](findings/research/address-reclaim-desktop-20260916.md),
[artifact hashes](findings/research/address-reclaim-desktop-evidence-20260916.json),
[native retry analysis](findings/research/allocation-retry-analysis-20260916.md),
[visual fix](findings/research/feedback-decompression-20260916.md).

## Next work / remaining gates

1. Explicitly recorded, supervisor-owned QEMU closure; retain strict classification,
   capture and recovery rules. Implementation under review in candidate-280-closure.
2. Guest-crash/command-channel failure and independent-host-boot qualification.
3. Broader applications, formats, render hazards and interprocess synchronization;
   page-table release beyond cached address reuse; reclamation performance cost.
4. Physical DCN output and measured performance. Historical direct OpenGL hang and
   live-validation crash remain unresolved; do not repeat without diagnosis.

No main merge/push before full desktop proof. Another exposure needs a named-boot
allowance and fresh MODE2 through tools/cycle.py. No vfio→amdgpu cycling.
[Roadmap](docs/ROADMAP.md).

## Next exposure allowance — supervised QEMU closure

One additional exposure (twentieth) on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed` is authorized for candidate 280 /
metal-128 / attempt closure, unchanged driver/QEMU. Fresh MODE2 must show
CP_STAT=0 and RLC_CNTL=0; all existing admission, capture, host-fault, deadline
and cleanup gates remain active, up to 6000 seconds.

After the native core probe passes and interactive-ready is recorded, use the
supervisor's predeclared `intentional-close` action. It validates exact CID and
StartedAt plus same-results manifest/probe/readiness identity, writes a single-use
request, authenticates the QEMU monitor peer, sends HMP quit and records stop proof.
No Docker kill/stop fallback belongs to this action. The coordinator retains its
existing INVALID-on-closure classification and attempts strict recovery normally.
This is an abnormal QEMU-closure experiment, never a clean guest shutdown.
Hypothesis: authenticated retained leases permit queue/firmware cleanup after
QEMU exits; falsified by missing/invalid capture, incomplete cleanup, forced HQD
clears, nonzero CP status or a non-authorizing recovery receipt.
