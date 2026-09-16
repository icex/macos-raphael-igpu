# Render-target feedback corruption — 2026-09-16

Candidate277 run a169e87a3b282ebb6552150a77a9c232, corrected QEMU, WindowServer166.
The simplified feedback test checked after twelve iterations and masked corruption.
A single-pass custom-shader control reproduces green pixels on the shared diagonal:
private storage, native barrier: 222 bad pixels; broader barrier:226. Splitting the
encoder or calling textureBarrier:0 bad. Managed/IOSurface cases:0 bad. Each case
checks110000pixels. Native installed fragment specialization has a separate consistent
four-byte discrepancy; do not count its18000 baseline mismatches as the desktop bug.

## Exact local source evidence

AMDRadeonX6000MTLDriver UUID906f11a3-9daf-35bd-b8ea-cfd2160fae1a,
under /home/bogdan/macos-vm/re/decompiled-24G830/AMDRadeonX6000MTLDriver-full/functions:
- 7ffb08d66dd7 memoryBarrierWithScope passes second argument0.
- 7ffb08d66a77 textureBarrier passes0xff.
- 7ffb08d66a97 amdMtl_HWL_TextureBarrier skips expansion for argument0, otherwise
  expands compressed attachments and clears compression flags before the barrier.
- 7ffb08d66ac3 TEST ESI,ESI; SETZ DL; OR DL,DIL combines that skip with the
  existing per-encoder already-expanded bit. Replace SETZ DL with XOR DL,DL; NOP,
  retaining the existing guard and expansion machinery. Module offset0x173ac3.

## Live intervention and restoration

feedback-code-apply.txt verifies guarded bytes85f60f94c24008fa changed to
85f630d2904008fa in WindowServer only, then detached before captures.
feedback-code-active-{0,1}.png show clean native panels. feedback-code-restore.txt
verifies original bytes restored; feedback-code-restored.png reproduces diagonals.
This establishes a bounded intervention on the native defect. Old menu-bar damage
outside the animated reproducer can remain until redrawn; fresh-guest qualification
is still required. No full desktop claim yet.

Earlier register-interposition debugger attempt stalled during debugger stop;
SIGINT did not release it, guest-side SIGTERM to LLDB detached debugserver and
resumed the same WindowServer166. No QEMU/coordinator termination or GPU reset.
A revised callback-stop trace hit88 barriers, changed84, and detached normally;
its screenshot timing is not sufficient evidence of active intervention. The
subsequent static byte intervention/restoration is the decisive controlled test.

All artifacts above are in candidate-277-attempt-smcpmio-results. Candidate279
implements the exact byte change through the existing UUID/path/byte-guarded,
task-private COW mechanism. Fresh-run result pending.

## Candidate279 fresh guest

Run3f5d8049506b1164b29292988b0eacb5, MODE2#154, build
eb7ebdfeb3d1440c99601da45ce83069, executable
e9d918e94bc5d8e1f20d636ff65cf078d46ac0848650565f878bdec2f8fe5aee.
Automatic COW logs report protection/write/restore/verification all0, including
WindowServer. Desktop Metal baseline passed. Single-pass custom control passed
all12cases (1,320,000pixels, zero mismatches above2.1bytes; maxerror1byte).
120-frame HEVC and120-frame H.264 hardware encode/decode passed, maxlumaerror0/1.
PerfPowerServices PID152 was0.0% CPU/0.76s cumulative on this second corrected-QEMU
guest boot. User reported no longer seeing corruption in ordinary Screen Sharing.

The first three fresh-guest panel captures are **not valid panel qualification**:
Safari obscures the first, and the backdrop obscures/moved panels in the others.
A floating-panel capture variant was prepared but the supervisor stopped the VM
before it produced images. Controlled native A/B captures from the previous guest,
fresh279 pixel checks, and the user's observation support the fix; additional
unobstructed fresh-guest captures and longer desktop qualification remain open.

Overall run INVALID/capture_loss: CR2 reached512records and reported8drops by
snapshot0xd. Supervisor raised definitive critical capture loss during interactive
inspection and requested guest shutdown. Guest exited-after-guest-request; recovery
strictly refused the lossy capture. No successful recovery is claimed. This is a
separate logging/lifecycle blocker, now the immediate next task.

Mesa's RadeonSI implementation independently documents disabling DCC when a
texture is both a sampler and color buffer (si_update_ps_colorbuf0_slot):
https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa/+/418c4cfa6708a0e0b1175e72fb8fd27d3ca1615a/src/gallium/drivers/radeonsi/si_descriptors.c
This corroborates the mechanism; the exact Apple byte change is grounded in the
local decompilation and reversible hardware tests above.
