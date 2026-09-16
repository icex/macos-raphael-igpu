# Live status — 2026-09-16

**Visual fix implemented and reproduced:** candidate279 expands compressed render
targets before Metal feedback reads. Controlled native panels become clean with
the patch and corrupt again after restoration. Fresh279 passes the previously
failing pixel test; user reports no more Screen Sharing corruption. Full desktop
and physical display qualification remain open.

## Current host / guest

Guest is **stopped**. Run3f5d8049506b1164b29292988b0eacb5, candidate279/cardmetal-126,
MODE2#154, fifteenth exposure on host boot2508eb6d-ddf3-497d-9774-00a7ecebe3ed.
GPU0000:7b:00.0 remains vfio-pci, power/control=on. Results:
`/home/bogdan/macos-vm/run/candidate-279-results`.

The supervisor detected critical capture overflow and requested shutdown. Guest
exited-after-guest-request. Overall INVALID/capture_loss; recovery refused with
`CR2 snapshot reports loss`. **No clean recovery receipt.** Independent MODE2#154
had passed before this run; it does not establish post-run recovery.

## Verified current changes

- **Transparency:** exact driver UUID/byte-guarded three-byte COW repair, preserving
  the per-encoder expansion guard. Fresh279 feedback check12cases/1,320,000pixels,
  zero bad pixels; maxerror1byte. Desktop Metal baseline passed.
- **Codecs:** fresh120-frame HEVC and120-frame H.264 hardware encode/decode passed,
  maxlumaerror0/1. Original seven sustained cases/9,600frames remain evidence in
  their scope. Explicit decoder GPU-ID selection still fails; automatic hardware
  selection works. Main10/arbitrary-media/chroma/concurrency remain unqualified.
- **PerfPowerServices:** corrected QEMU enumeration works on two guest boots on
  this host boot; latest PID152 at0.0% CPU/0.76s cumulative. Earlier normal service
  restart also passed. No service disabling or guest security change.
- **Host regression suite:**937tests OK,3skipped.

Driver build eb7ebdfeb3d1440c99601da45ce83069; executable SHA256
`e9d918e94bc5d8e1f20d636ff65cf078d46ac0848650565f878bdec2f8fe5aee`.
QEMU image `sha256:51cbd7dcdbad2d6492ce83a263e9854c28620d67a1ea12ebc0562c6fab2605ad`.
[Mechanism, decompiled sources, scope and limitations](findings/research/feedback-decompression-20260916.md),
[artifact hashes](findings/research/feedback-decompression-evidence-20260916.json).

## Current blockers / next work

1. Stop routine diagnostics exhausting the512-record critical buffer while retaining
   all required identity, fatal, recovery and lifecycle evidence. Do not relax the
   loss detector or manufacture a successful recovery receipt.
2. Repeat unobstructed native-panel capture, longer normal desktop use and complete
   shutdown/recovery after that correction. First279 panel captures were obscured;
   the follow-up capture was interrupted by the supervisor.
3. Complete M5 concurrency/reclamation and M7 independent-host-boot/crash coverage,
   then physical DCN output and performance qualification.

Historical candidate278 OpenGL hang and live validation crash are not marked fixed.
No main merge/push until full desktop proof. New exposure needs a named-boot
allowance and fresh successful MODE2 through tools/cycle.py. No vfio→amdgpu cycling.
[Roadmap](docs/ROADMAP.md).

## Candidate280 one-run allowance

Standing instructions authorize the sixteenth exposure on host boot
2508eb6d-ddf3-497d-9774-00a7ecebe3ed, candidate280/cardmetal-127, to validate bounded
routine diagnostics and the279 visual fix. Prior279 guest shut down normally but
its lossy capture supplies no recovery receipt. Use documented manual-reuse/ack-risk
with fresh MODE2 requiring CP_STAT=0 and RLC_CNTL=0. Preserve all identity, capture-
fatal, host-fault, shutdown and recovery checks; max6000seconds with manual stop
after bounded visual, codec and process-recreation checks. Host937tests pass3skipped.

First280 attempt rejected before QEMU because the stage version parser ended at279.
Extended only to the reviewed280/card127 pair and tested its boundary. MODE2#155
passed CP_STAT=0/RLC_CNTL=0; no launch/ledger entry consumed.
