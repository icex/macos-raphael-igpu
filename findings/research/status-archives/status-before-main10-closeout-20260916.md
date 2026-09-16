# Live status — 2026-09-16

**Candidate 280 passes longer buffer/address, explicit GPU-fence and broader desktop checks.**
The reproduced transparency corruption remains fixed. Native allocation errors were
traced to successful reclaim/retry under pressure; the message alone is not a
reproduced correctness blocker. Full desktop and physical display acceptance remain open.

## Current host / guest

Guest **stopped** after run `1606212a998d81718fa354e19c4efdaa`,
candidate280/metal-127/postclosure, MODE2#162, twenty-first exposure on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. GPU remains vfio-pci, power/control=on.
Desktop probe passes; raw RFB desktop capture appears clean. Guest-request shutdown,
schema6 recovered/authorizes_launch=true, CP_STAT=0, no forced clears/timeouts or
recovery host faults. Overall **CORE_PROBE_PASS**.

This follows run `042d7770f42059319cda491e50396bd8`'s authenticated QEMU quit and
successful recovery of five active queues plus the graphics ring. That earlier run
remains **INVALID** due interrupted terminal capture; complete snapshot13/374 records
authenticated recovery. One abnormal-closure/relaunch/workload/clean-shutdown sequence
is demonstrated; broader M7 qualification remains open.
[Lifecycle evidence](findings/research/supervised-qemu-closure-result-20260916.md).

## Verified progress

| Area | Evidence and scope |
|---|---|
| Buffer/address reuse | 512 measured rounds, 2,147,483,648 correct values; all 6,144 measured address assignments reused earlier ranges; allocation returns exactly to 544,768 bytes |
| Larger allocations | 192 MiB live resources, four measured rounds, 67,108,864 correct values, exact allocation return |
| Native reclaim | 81 traced calls: 41 true, 40 false; all 40 false returns followed by same-thread/map success; 1,525 internal wire failures observed |
| GPU fences | 128 untracked blit/compute/blit rounds, 134,217,728 correct values; prior cross-queue shared-event checks also pass |
| Native desktop | Three minutes of moving/resizing native material windows; four clean raw RFB captures |
| Safari | Two-minute transparency/blur/scrolling page; three clean captures plus clean desktop after larger-buffer pressure |
| PerfPowerServices | 0.0% CPU, latest 0.72 s cumulative; corrected QEMU on seven measured guest boots, all on one host boot |
| Host regression | 948 tests OK, three skipped |

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

1. Continue guest-crash/fallback and repeated lifecycle qualification; one post-closure workload now passes.
2. Guest-crash/command-channel failure and independent-host-boot qualification.
3. Broader applications, formats, render hazards and interprocess synchronization;
   page-table release beyond cached address reuse; reclamation performance cost.
4. Physical DCN output and measured performance. Historical direct OpenGL hang and
   live-validation crash remain unresolved; do not repeat without diagnosis.

No main merge/push before full desktop proof. Another exposure needs a named-boot
allowance and fresh MODE2 through tools/cycle.py. No vfio→amdgpu cycling.
[Roadmap](docs/ROADMAP.md).

## Active offline work

Using the supplied decompilation plus matching native assembly to trace physical
display initialization. Current injected ROM contains four nonzero display paths;
empty published framebuffer properties do not prove an empty ATOM table. Boot parser
reads EFI properties from the PCI service; trace boot-display selection before patches.
Next codec qualification is Main10 with actual 10-bit luma/chroma readback; untested.
One additional exposure (twenty-second) on boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed` is authorized for unchanged candidate280 /
metal-127 / attempt main10. Hypothesis: advertised Main10 decode produces the same
10-bit420 luma/chroma as software decoding of the identical stream. Test software
encode first, then hardware encode if successful, up to16frames/case. Probe has a
180s process alarm; standard6000s supervisor, fresh MODE2, capture/identity/host-fault
and cleanup guards remain intact. First compile the probe before codec execution.
Unsupported format, selection failure or any CPU mismatch falsifies this scoped
case; do not infer failure of previously passing Main8. No vfio→amdgpu cycling.

Current Main10 run `f846abef4a573a0059fbe0ecdd28ecfc` is **running** after
MODE2#163, twenty-second exposure. The allowance is consumed. Probe/codec execution
and cleanup outcomes remain pending; driver and QEMU binaries unchanged.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-280-attempt-main10-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
