# Live status — 2026-09-15

**Not fixed:** visible desktop corruption and hardware encoding remain unresolved.

Verified finding: the native multimedia memory-mapping initializer used the wrong
register layout. Candidate 240 corrects it, but desktop corruption and the hardware
H.264 hang persist. A common cause remains unproven; hardware HEVC is unverified
after these fixes.

Worktree /home/bogdan/macos-vm/run/worktrees/candidate-242 (vcn-vcpu-reset).
Latest launch56/cardmetal-088 runc188e14450359a635305c44f13983599,
source0ce1766, build4c5268c76b5f46918d6ee1b3d82d85c9. Results:
/home/bogdan/macos-vm/run/candidate-242-results/.
Hostbootc369c74e-96ff-4c21-ae85-80ccb269f7d2; prelaunchMODE2reset92.
Guestboot4036BF8A-A1CF-46FB-9F72-A46D2EE57DED; registry4294968027.

## Latest functional evidence

Desktop Metal probe passes. H264 hardware encoder selected; frames0/1 accepted,
third submit hangs/no encoded output. Native VCN firmware-ready wait still times
out despite static initializer returning0. No HEVC test on stalled engine.
Native reset hook delivered: requested0ff00200 ->1ff00200; immediate and10ms
readback1ff00200. Native code later releases reset. SMU PowerUpVcn response1 and
correct version625300 still verified. Reset assertion is insufficient too.
Post-submit snapshot: VCPU_CNTL0ff00200/status0; code-cache BAR bothffffffff;
correct MMHUB GART retained, fault0. Firmware query/context addressf41f400000 was
verified in52/54/55, so all-ones register readback does not prove bad placement.
Artifacts serial.txt, h264-hardware.jsonl, mmhub-vcn-after-h264.jsonl, probe.json.

## Verified repair versus unresolved scope

Candidate240 runtime-selected native MMHUB2.3 initializer fixes a real native GART
initialization error: Apple VM10.3 hardcoded2.1 offsets. Hardware now has enabled
MMHUBCTX0 with correct physical root/range; native invalidation table is corrected.
This is separate from X6000 paging-table/root-domain repair233. Neither fixes VCN
firmware startup or visible corruption on its own.
Latest raw Linux TigerVNC screenshot240 shows persistent diagonal green/purple
Safari/menu corruption before encoding:
/home/bogdan/macos-vm/run/candidate-240-results/tigervnc-corruption.jpg.
Format/CPU/quad/sampling/derivative probes pass12 small cases each; these are not
WindowServer/Safari qualification. Common cause with VCN remains unproven.
Earlier software H264/HEVC three-frame luma roundtrips pass. Hardware HEVC/alpha
remain unverified after fixes. CORE_PROBE_PASS is only the small desktop probe.

## Cleanup and repository

Stopped through interactive stop-requested. Shutdown forced (not clean guest
shutdown); harness recovered. VM stopped. FinalMODE2reset93 CP_STAT0/RLC_CNTL0.
Same hostboot, vfio-pci retained, power/control on, inhibitor active; no host reboot.
No host fault in kernel capture. SSH master closed; no agent-opened VNC remains.
Host regression suite: 928 tests ran, 3 skipped, no failures. Build succeeded.
No further launch allowance.
No merge/push to main; original ~/src checkout remains untouched, including its
pre-existing status.md edit. Candidate worktree status is authoritative.

## Next work

Stop adjacent startup-patch experiments: correct GART, accepted platform power
request and observed VCPU reset did not establish firmware readiness. Obtain a
known-good VCN startup/register baseline or trace the firmware boot path before
another hardware change. Keep attempted power/reset changes opt-in; they are not
validated encoder fixes. Investigate actual desktop capture/compositing workload
separately; current synthetic probes have failed to reproduce the visible artifact.
See findings/research/mmhub-native-gart-20260915.md, vcn-platform-power-20260915.md,
vcn-vcpu-reset-20260915.md. Superseded status is archived.

## Candidate 243 allowance (launch 57)

One launch57 on boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2`, candidate 1.0.243 /
card `metal-089`, via `tools/cycle.py` after a fresh MODE2 reset (next #94), host on
`vfio-pci` with `power/control=on`, `--manual-reuse --ack-risk`, max 6000 s, all abort
paths armed. Authorized by the user ("always launch and test... test it continuously
until all are fixed"; iGPU teardown script available as host safety net).

Purpose: read-only VCN VCPU boot diagnostic. Candidate 243 keeps every candidate-242
correction active and adds only a `_internal_cgs_read_register` readback of the
firmware-cache BAR (0x43c/0x43d), the sibling NC0 BAR (0x438/0x439), UVD_STATUS,
POWER_STATUS, SOFT_RESET and VCPU_CNTL right after native `static_initialize` returns.
No register writes, no reset. It decides whether the VCPU firmware-cache window is
actually latched (VCPU boots from garbage) or the 0xffffffff snapshot readback is only
a secure-register artifact, redirecting the encoder search accordingly.

## Candidate 244 allowance (launch 58)

One launch58 on boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2`, candidate 1.0.244 /
card `metal-090`, via `tools/cycle.py` after a fresh MODE2 reset (next #95), host on
`vfio-pci` with `power/control=on`, `--manual-reuse --ack-risk`, all abort paths armed.
Authorized by the user ("always launch and test... test it continuously until all are
fixed"; iGPU teardown script available as host safety net).

Purpose: settle the candidate-243 result. Candidate 243 read the VCN VCPU cache-window
BAR (0x43c/0x43d) and soft-reset (0x84) as 0xffffffff after static_initialize while the
sibling NC0 BAR read correctly and the VCPU never reached UVD_STATUS==2. Candidate 244
reads those registers back immediately after each native write (before reset release),
read-only, to decide a dropped write (block held inaccessible -> real root cause) from a
register that only reads 0xffffffff once secured (benign -> firmware authentication).

## Candidate 245 allowance (launch 59)

One launch59 on boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2`, candidate 1.0.245 /
card `metal-091`, via `tools/cycle.py` after a fresh MODE2 reset, `--manual-reuse
--ack-risk`, all abort paths armed. Authorized ("test continuously until all fixed").

Purpose: candidate 244 proved the VCPU-core registers (cache BAR 0x43c, soft-reset 0x84)
read 0xffffffff at write time while the sibling NC0 BAR is fine and the VCPU never boots.
That is the signature of the VCN core power domain staying gated. Candidate 245 reads
UVD_PGFSM_STATUS/POWER_STATUS and the dead core registers back at the PGFSM config write
to decide a fixable power-domain fault from a firmware/PSP wall. Read-only.

## Candidate 246 allowance (launch 60)

One launch60 on boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2`, candidate 1.0.246 / card
`metal-092`, via `tools/cycle.py` after a fresh MODE2 reset, `--manual-reuse --ack-risk`,
all abort paths armed. Authorized ("test continuously until all fixed").

Purpose: decisive dual-path read. Apple's cgs read returns 0xffffffff for the VCN VCPU
cache BAR (0x43c/0x43d) and soft-reset (0x84) while the VCPU never boots, power on, firmware
loaded to the TMR. Read the same registers via the kext direct-MMIO accessor (fbRead, abs
0x823c etc.) to tell a blind Apple readback (write landed, firmware reachable, fault
downstream) from a genuinely unreachable register. Read-only.

## Candidate 247 allowance (launch 61)

One launch61 on boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2`, candidate 1.0.247 / card
`metal-093`, via `tools/cycle.py` after a fresh MODE2 reset, `--manual-reuse --ack-risk`,
all abort paths armed. Authorized by the user (chose the targeted bounded probe over a
Linux reference capture).

Purpose: locate the real VCN VCPU cache-BAR/soft-reset registers. Both access paths read
0xffffffff at Apple's seg1 base 0x7e00 while NC0/STATUS are fine. Bounded read-only probe:
dump Apple's VCN segment-base table (ctx memory) and probe the cache/soft-reset offsets at
each sane segment base, plus a small seg1 neighbor scan for the TMR address. No writes.

## Candidate 248 allowance (launch 62) — DPG FIX ATTEMPT

One launch62 on boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2`, candidate 1.0.248 / card
`metal-094`, via `tools/cycle.py` after fresh MODE2, `--manual-reuse --ack-risk`, all
abort paths armed. Authorized ("test continuously until all fixed").

Root cause (candidates 243-247 + web research): Raphael is an APU whose VCN needs DPG mode;
Apple uses the Navi23 static path whose 0x43c cache-BAR write never lands, so the VCPU never
boots. Candidate 248 adds rgpuvcndpg=1: forces EnableVCNDPG+EnableVCNSecureLoad so
engine_init_pfn_ptr selects _engine_3_0_dpg_secure_initialize (0x943cf) instead of static
(0x930f8); keeps PSP firmware load (mode 0); decouples SMU PowerUpVcn from the static flag.
Success = VCPU boots (UVD_STATUS==2, no cosWaitForFunc timeout) and H264 hw encode emits frames.

## Candidate 249 allowance (launch 63) — corrected DPG fix

One launch63 on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2, candidate 1.0.249 / card metal-095,
via tools/cycle.py after fresh MODE2, --manual-reuse --ack-risk. Authorized ("test until fixed").
Fixes candidate 248's routing gate (hooks were gated on vcnStaticEnabled and never installed under
rgpuvcndpg). Now the DPG path gets the config forcing, SMU PowerUpVcn, and VCNS/VCNC diagnostics.
Success = initializer=+943cf (dpg_secure), VCPU boots (UVD_STATUS==2, no cosWaitForFunc timeout),
H264 hw encode emits frames.

## Candidate 250 allowance (launch 64) — DPG-unsecure

One launch64 on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2, candidate 1.0.250 / card metal-096,
after fresh MODE2, --manual-reuse --ack-risk. Authorized ("test until fixed"). Candidate 249
engaged dpg_secure but its secure DPG-SRAM firmware (VCN0_RAM type 49) loaded to tmr=0x0 (our
firmware is not Apple-signed-secure). Candidate 250 forces mode=1 -> dpg_unsecure_initializer so
the driver programs the DPG SRAM from the supplied firmware and DMA-commits (Linux indirect SRAM).
Success = initializer=+93ec1, VCPU boots, H264 hw encode emits frames.

## Candidate 251 allowance (launch 65) — hybrid DPG (decompilation-guided)

One launch65 on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2, candidate 1.0.251 / card metal-097,
after fresh MODE2, --manual-reuse --ack-risk. Authorized ("test until fixed"). From KDK 24G830
HWLibs decompilation: dpg_secure writes cache BAR=0 (needs Apple-signed secure fw), dpg_unsecure
writes it from ctx+0x2c0 but only in mode=1 which skips the firmware-loaded wait that fills
ctx+0x2c0. Fix: keep mode=0 and override ctx+0x3f8 to dpg_unsecure_initialize (0x93ec1) so the
cache window is programmed from the real TMR address via the DPG LMA window. Success = VCPU boots,
H264 hw encode emits frames.
