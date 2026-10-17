# Live status — 2026-10-14 — paused by user; Tahoe desktop regression unresolved

User requested a pause. No VM, GPU experiment, or launch supervisor is running.
No further hardware work is authorized by this status entry; a later explicit
resume is required. Host boot2e377991-b6d2-4fe5-81dd-fd6afe9999f7, GPU0000:7b:00.0
remains vfio-pci with power/control=on. Latest separate recovery receipt
run/candidate-494-vmabi4-requalification.json validates with errors=[],
authorizes_launch=true and kernel_faults=[]. Ordinary recovery for that run is
still immutable incomplete/non-authorizing. Do not confuse these two receipts.

## Current failure

User reports latest15.x was usable and26.x freezes. Latest retained versions:
15.8.1/24H32 and26.7.1/25G241. Earlier matched candidate490 offscreen render/
compute and readback passes do not establish an unlocked Tahoe desktop.
The active disk is26.7.1; latest15.8.1 remains in rollback. Do not test older releases.

Latest hardware run: candidate494 vmabi4, run0b504695909175c6fd2974d807c3c1bb,
results run/candidate-494-attempt-vmabi4-results. The native desktop Metal probe
passes (CORE_PROBE_PASS), but normal desktop interaction/remote access is unqualified.
First pending client is VTEncoderXPCServ PID808, Video channel15 VCN0EncLLQ stamp1;
graphics ring advances/drains. An earlier cosWaitForFunc timeout resolves to
25G241 HWLibs _wait_for_vcn_response (+0x8036e). Its request contains engine,
segment, register, expected value and mask; the actual failed fields remain missing.
Video-context teardown later holds the global accelerator mutex, blocking desktop
resource creation. This is a failure boundary, not a proven firmware root cause.

A distinct earlier candidate493 earlygate run859837b1298120ac07a14850eb389c37
had Weather PID496/VMID4 graphics stall BEFORE encoder creation, with no HEVC
hardware decode contexts. Thus video teardown and HEVC selection do not explain
all failures. Do not discard the earliest graphics-stall evidence.

Candidate494 captured first requests for VMIDs1..8: raw reprogram byte1 and roots
repaired to physical addresses. Native26 tests bit0 whereas our helper tests ==1;
that mismatch is not supported as this run's cause. Guarded MMHUB table repair
succeeds on15/26. Encode3_0_submit_frame retains queue fields/arithmetic; observed
binary differences are relocated references/call displacements.

## Preserved work and configuration

Candidate494 worktree/branch contains diagnostics and a recovery admission fix;
compiled source22a52be949e0dee37cd352d4f5addeef56be0e2c,
build6d37de612f5f49b1bad5f52db4639b59. No verified GPU repair is integrated into dev.
Candidates491-493 SDMA retry/HEVC gates are unverified and are not the default fix.
CoreMedia preference restored to original absence; Sunshine encoder=videotoolbox.
Apple sign-in OpenCore patches, authorized SSH key, guest data and identity retained.
The GPU run used experiments/pins-igpu-display-v15.json (frozen QEMU38193017...).
Use explicit matching pins; default pins.json selects a different image.

Two uncaptured candidate494 attempts provide no native regression evidence.
One cancellation consumed a launch reservation despite lacking usable capture;
its original ledger/artifacts remain. Full MODE2/noqueue recovery now accepts a
strictly bound uncaptured cancellation record, then still requires the same
complete idle scans, PSP teardown and live host/kernel checks. Audit that change
before reuse; do not remove ledger entries or fabricate recovery/shutdown evidence.
Latest full host suite:1626 tests pass,8 skipped. No GPU milestone/CI delivery claimed.

## Next investigation on an explicit resume

Capture the failed _wait_for_vcn_response request fields and native caller before
changing handshake behavior, then compare against latest15.x successful encoder
startup. Audit the retained Weather graphics stall separately. Correct the driver,
with dynamic instruction/ABI discovery rather than build allowlists or version
thresholds. Verify native Metal pixels, sustained usable desktop, hardware encoding,
remote display, and supervised shutdown/recovery. Xcode installation, QEMU close
confirmation and remaining remote-access work stay deferred until GPU stability.

Detailed evidence and Claude prompt: docs/claude-tahoe-regression-handoff.md.
Earlier status is preserved in findings/research/status-archives/.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-494-attempt-novmm-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

Run98f8268b740bb85961009586b1cb5138 (card metal-294, same candidate494 driver,
26.7.1, OpenCore Tahoe hv_vmm sysctl swap disabled) panicked 4.7 s into guest boot,
before RaphaelGPU loaded: page-fault write in APFS VolumeBSDClient MetaClass::alloc.
No GPU or hv_vmm conclusion. SIGTERM cancellation forced stop; ordinary recovery
failed (no critical producer). MODE2/noqueue recovery: recovered, authorizes=true,
errors=[], kernel_faults=[] (run/candidate-494-novmm-noqueue-recovery.json).
Third unexplained early guest memory panic this boot (488, perf15v2): stale GPU
DMA after MODE2 (VCN state survives reset) is a hypothesis under test.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-494-attempt-novmm2-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`

Retry run (novmm2, card metal-294, hv_vmm_present=1 confirmed in guest) booted cleanly.
Native start logged stale UVD_DPG_PAUSE=4 (cleared by VCNUP), then the same
_wait_for_vcn_response request n=2 failed: HWLibs+0x8e254, VCN bank1 reg0x14
(UVD_DPG_PAUSE), expected 0x8 mask 0x8 = NJ_PAUSE_DPG_ACK after REQ. Same request
succeeds on 15.8.1 and 26.7.1 in all clean pre-21:43 runs (caller +0x94db1 on 24H32).
Sunshine's VTEncoder became the first pending client; a standalone Metal probe then
blocked before device use (accelerator lock). No GFX hang before the VCN failure
(the one dump had GRBM idle and an empty ring). Stopped via stop file; guest
acknowledged the request but the stop was forced. Ordinary recovery incomplete;
MODE2/noqueue recovered, authorizes=true (run/candidate-494-novmm2-noqueue-recovery.json).
Conclusion: on this host boot the VCN DPG pause handshake is broken by state that
survives MODE2 (first broken by earlygate's Weather GFX hang); any Tahoe desktop with
a hardware encoder freezes until VCN is reset. hv_vmm A/B remains untested.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-495-results`
- Verdict: `INCONCLUSIVE`
- Boundary: `probe_completion_missing`

Candidate495 metal-295 (rgpuvcnstalecycle=1, hv_vmm swap disabled): native start
found UVD_DPG_PAUSE=4; SMU PowerDownVcn/PowerUpVcn both answered 1, yet DPG_PAUSE
still read 4 (POWER_STATUS 0x905, PGFSM 0x2aaa8aa0) and the n=2 NJ pause ACK wait
timed out again. Hypothesis rejected: an SMU VCN power cycle does not clear the
persistent state. Apple's "Trying to restart GPU" path after earlygate's Weather
GFX hang is the first point after which every VCN start fails. Stopped by stop file;
forced; ordinary recovery incomplete; MODE2/noqueue recovered, authorizes=true
(run/candidate-495-noqueue-recovery.json). Guest Sunshine LaunchAgent temporarily
renamed *.disabled-gfx-diag-20261014 so GFX-hang diagnostics can run without the
broken encoder start; restore after diagnosis. Not a fix.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-495-attempt-gfx1-results`
- Verdict: `INCONCLUSIVE`
- Boundary: `probe_completion_missing`

Candidate495 attempt gfx1 (no Sunshine LaunchAgent, hv_vmm swap disabled): a login
VTDecoder (codec4, 584x584) started VCN, hit the same failed NJ pause ACK, and the
Metal probe again blocked before device use. On this boot any VCN use wedges the
accelerator. Forced stop; MODE2/noqueue recovered, authorizes=true
(run/candidate-495-gfx1-noqueue-recovery.json). Next: read-only VCN firmware/status
snapshot at the failed ACK (candidate496) to find the state that survives MODE2.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-496-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`

Candidate496 metal-296 (read-only VCN snapshot; hv_vmm swap disabled; no Sunshine):
a login VTDecoder (codec4 584x584, the Weather widget's video) started VCN; init read
POWER_STATUS 0x906 and the decoder ring never advanced (RPTR0/WPTR stale 0x80 at entry),
followed by repeated "Trying to restart GPU". No encode pause handshake ran, so no
snapshot. Decoder-ring entry pointers across runs show VCN healthy through 8d6e2dc9
(entry RPTR=WPTR=0x1540 in 491-recover1), then 491-recover1's decoder stopped at
RPTR 0x40/WPTR 0x100 before Weather's GFX hang; every later session is broken. The
persistent VCN damage follows 8d6e2dc9's 359 GPU restarts/forced stop and survives
MODE2 and SMU VCN power cycles. Host reboot requested to restore a clean VCN.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-496-attempt-fresh1-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

Fresh host boot fe3ff623 (iGPU bound rootless via pkexec helper), candidate496
metal-297, run in candidate-496-attempt-fresh1-results. hv_vmm_present=1 verified in
guest. Results, separately:
- VCN clean: Sunshine encoder NJ pause ACK succeeds (pause 0xc), stop/start cycles pass;
  healthy reference UVD_SCRATCH1=0x0412100f/0x04121015 (read-only snapshot).
- Metal MSAA/depth/stencil matrix (1/2/4/8 samples x color/depth/depth+stencil, 2000
  instanced triangles 1024^2) all PASS with correct pixels.
- Opening Weather hangs the GFX ring within 10 s: GRBM 0xe7f10028, CP_STAT 0x94038600,
  IB1 BUFSZ 0x24c0, PFP 0x653 / ME 0x9d6 - identical to earlygate. The Darwin25
  hv_vmm sysctl swap is therefore NOT the cause; the hang is a deterministic Weather
  (VectorKit map: stencil fill + discard, 4x EQAA) draw sequence.
- Hang-dump flood caused critical replay loss; harness ended with guest-requested
  shutdown (exited-after-guest-request), ordinary recovery refused (CR2 loss);
  MODE2/noqueue recovered, authorizes=true (run/candidate-496-fresh1-noqueue-recovery.json).


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-496-attempt-fresh2-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

fresh2: VCN still healthy after fresh1's single Weather hang (NJ pause ACKs pass).
Controlled reproducer found with a standalone Metal probe (run/tahoe-diag-20261014/
pc_probe.m): 64x64 indexed grid, 4 float4 varyings, 4x MSAA, Depth32Float_Stencil8 with
stencil Invert, fragment discard -> GFX hang with the same GRBM 0xe7f10028 signature;
same with 1 varying, and 4 varyings without MSAA/stencil, PASS. Draw state: DB_EQAA
0x302222, DB_SHADER_CONTROL 0x50, PA_SC_AA_CONFIG 0x3020c002, SPI_PS_IN_CONTROL 4,
GE_PC_ALLOC 0x3ff, DB_Z_INFO ITERATE_256. Session ended by hang-dump capture loss;
guest-requested shutdown; MODE2/noqueue recovered, authorizes=true.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-496-attempt-fresh3-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

fresh3 panicked at serial line 40 (earliest kernel boot, GPF in strcmp with a stack slot
overwritten by boot-argument text) before RaphaelGPU loaded; cancelled via runner
handler, forced stop, MODE2/noqueue recovered, authorizes=true. Fourth unexplained early
guest memory corruption (488, perf15v2, novmm, fresh3); stale GPU DMA after MODE2 from an
engine MODE2 does not reset (VCN) remains a hypothesis, not yet tested.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-496-attempt-fresh4-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

fresh4 bisection (run/tahoe-diag-20261014/gfx_bisect.m, 64x64 grid, 4 float4 varyings,
4x MSAA, Depth32Float_Stencil8): MSAA only, +discard, +D/S, +stencil Invert, +D/S+discard
all PASS; stencil Invert + discard together HANG (GRBM 0xe7f10028). Minimal trigger =
stencil write + fragment kill under MSAA (late per-sample stencil update). Session ended by
hang-dump capture loss; guest-requested shutdown; MODE2/noqueue recovered, authorizes=true.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-497-results`
- Verdict: `BASELINE_BLOCKED`
- Boundary: `kiq`

Candidate497 metal-298 (read-only GC config snapshot, 127 registers at pre-TTL, before
RLC start, post-TTL, after RLC start and first hang; run/tahoe-diag-20261014/
c497-config-table.txt). Native init changes only golden fields (GE_PC_CNTL grant bits,
DB_DEBUG3, PA_CL_ENHANCE) plus our DISABLE_SC_BINNING; Raphael's reset-default
GE_PC_CNTL.PC_SIZE=0x200 matches the UMD's GE_PC_ALLOC=0x3ff, ruling out parameter-cache
oversubscription. DB_CREDIT_LIMIT drops 0x410013ff -> 0x41001005 at the hang (DB credits
held). Minimal stencil+discard MSAA probe hang reproduced. Guest-requested shutdown;
ordinary recovery recovered, authorizes=true. PAL applies the same workaround set to
Raphael and Navi23; suspect remains chip-derived per-draw DB state (4x ITERATE_256 with
DECOMPRESS_ON_N_ZPLANES=0) - next: sample-count bisection.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-498-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

Candidate498 metal-299: v1 stencil+discard (no MSAA) PASS, v4 HANG. Harvest/topology
registers at hang equal reset defaults: one active WGP (CC_GC_SHADER_ARRAY_CONFIG
0xfffe0000), no user CU/RB/SA disable, VS/PS CU masks full, LATE_ALLOC_VS 0, PS/VS max
wave IDs default. DB_CREDIT_LIMIT is a live counter: SC quad credits 0 at the hang (DB
holds every quad). Native init differs from Linux 10.3.6 golden in GE_PC_CNTL:
0x200 -> 0x280200 (Navi23 golden WAVES_WITH_NO_GRANT=0xA), which Linux leaves 0 on
Raphael. Hypothesis: un-granted VS waves fill the single WGP and deadlock against
late-Z PS waves. Next: candidate499 restores WAVES_WITH_NO_GRANT=0 (rgpupcgrant=1).


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-499-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

Candidate499 metal-300 (rgpupcgrant=1): GE_PC_CNTL 0x280200 -> 0x200 before RLC start,
still 0x200 at the hang. v1 stencil+discard PASS, v4 HANG; DB SC quad credits again 0.
Hypothesis rejected: Navi23 WAVES_WITH_NO_GRANT is not the deadlock cause. Session ended
by stop file; guest-requested shutdown; ordinary recovery refused (CR2 capture loss).


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-501-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

Candidate501 metal-302: wave-dump positive control works - a spinning PS (c8,v4,s1,spin)
shows resident PS waves on SIMD0 with loop PCs. Therefore the 0-wave result at the
stencil-write+discard hang is real: no shader wave is resident; the deadlock is in fixed
function (SC/DB/SPI/CB with DB quad credits exhausted). Mesa/Linux comparison: CAM remap
targets, PA_SC_SHADER_CONTROL, DB_SHADER_CONTROL and wave size match; no KMD-side
difference found yet. Next: same reproducer on macOS 15.8.1 with the same driver.

Matched-OS test setup: active disk temporarily swapped to a btrfs reflink copy of
rollback/macos-15.8.1-24H32.img; the 26.7.1 disk is renamed ~/macos-vm/active-26.7.1-hold.img
(inode 10150199, recorded in run/tahoe-diag-20261014/active-26-disk-identity.txt) and must
be restored after the test. Same candidate501 driver, same probe.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-501-attempt-mac15-results`
- Verdict: `BASELINE_BLOCKED`
- Boundary: `kiq`

Matched OS result (attempt mac15, 15.8.1/24H32 clone, same candidate501 driver and probe):
v1 stencil+discard PASS, v4 stencil Invert + discard HANG - identical to 26.7.1. The
desktop freeze is therefore not a Tahoe regression: it is a latent Raphael fixed-function
deadlock (SC/DB/SPI, no resident waves) that Tahoe's apps reach (Weather map stencil fill,
Memoji avatar picker during iCloud setup); the user's 15.x sessions never ran them.
Guest-requested shutdown; ordinary recovery recovered, authorizes=true. Active 26.7.1
disk restored (inode 10150199, size and mtime identical); 15.8.1 clone kept at
run/tahoe-diag-20261014/macos-15.8.1-clone-after-mac15-test.img (reflink).


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-502-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

Candidate 502 / metal-303 (rgpuknobs=0xff, group A: stencil quad summation, QC stencil
mask summation, resumm-to-single-stencil, SUMM_SQUADS, fast stencil, PREZ/POSTZ dtile
conflict stall, quad coherency stall, dual-quad-in-BC off). All eight fields written after
RLC start and still held at the first hang dump. Not a fix: the GPU hung with the same
signature (CP_STAT 0x94038600, DB_CREDIT_LIMIT 0x4100101f) within a minute of login. Confounded
again: Weather relaunched at login (pid 572 at 13:10:35, the noweather agent did not stop
it) and the v1 control timed out behind that hang. Verdict INVALID/identity_or_route_missing
is a harness artifact of mine: a leftover serial-capture loop from the plain-guest panic
diagnosis held serial.sock for the first boot seconds (early serial preserved in
run/tahoe-diag-20261014/plain-serial-1300.log). Guest-requested exit; ordinary recovery
CR2 loss -> mode2-noqueue-recover recovered, authorizes=true
(run/candidate-502-noqueue-recovery.json).

GPU-less plain guest instability (new evidence for the open guest-corruption issue):
two compat-refresh boots of 26.7.1 with no GPU attached froze within a minute of the
compat command (all vCPUs in kernel; one in a post-panic pause/jmp loop, seven polling a
global at boot-KC+0x2dfbb2; tlbto_us=0 in boot-args) and a third hung at "syncing
disks... Killing all processes"; the fourth sealed. GPU DMA cannot explain these. Host
kernel 7.2.9 (since 2026-10-12 20:33), kvm_amd avic=Y.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-502-attempt-b-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

Candidate 502 attempt b / metal-304 (rgpuknobs=0x3f00, group B: DB full-tile wave break
mode 1, SC LPOV/FPOV wave breaks, coarse full-tile wave break, DB AUTO_FLUSH_QUAD,
ONE_FREE_IN_FLIGHT; all held at the hang). Clean A/B this time (Weather killed from SSH
before login): v1 stencil+discard PASS (2.1 ms), v4 stencil Invert+discard HANG. Not a fix.
Hang decode: ME is only polling CP_COHER_STATUS for an ACQUIRE_MEM after the four draws
(ME_WAITING_ON_REG_READ_DATA, SURF_SYNC_NEEDS_IDLE_CNTXS); SC/PA/BCI/SPI/SX/DB/CB busy, 0
waves. The draw runs Apple's legacy VS pipeline with GE_PC_ALLOC=0x3ff (oversubscribed,
512 lines) while Mesa sizes Raphael's parameter cache at 256 lines -> candidate 503.
Verdict INVALID/identity_or_route_missing (no capture interference this time); guest
exit, CR2 loss -> noqueue recovered, authorizes=true
(run/candidate-502-attempt-b-noqueue-recovery.json).


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-503-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

Candidate 503 / metal-306 (rgpunopcoversub=1) - ROOT CAUSE FOUND. The per-process COW
cleared allowGePcAllocOverSub (bit 42, derived from the image's AMD_DeviceSettings layout)
at the dynamically located second default-mask movabs (26.7.1 text+0x13a5db) in every
Metal client (WindowServer first). Results, same boot, same driver otherwise:
v1 and v4 stencil Invert + discard PASS (2.7/2.3 ms; v4 hung on every earlier run on 26.7.1
and 15.8.1), plus eft, v8, v16 4x MSAA + depth write, v28 4x, 512x512 grid v28 4x,
1024x1024 grid v16 8x + depth write, stencil-only: all PASS, 0 hang dumps. Weather opened
(no kill loop) and ran 25 s with 0 hang dumps and 0 GPU restarts; its HEVC background
decode reached VCN (VCNQ rptr/wptr advancing - VCN not wedged on this boot).
Mechanism: Apple's GFX10 defaults turn on GE parameter-cache oversubscription with
GE_PC_ALLOC = OVERSUB_EN | 512 lines (Navi2x sizing) and no VS late alloc; Raphael has
256 PC lines (Mesa pc_lines for Van Gogh/Rembrandt/Raphael). Heavy attribute exports with
late-Z (stencil write + discard) then deadlock SC/DB/SPI with no resident waves.
Session end: the interactive hold aborted on definitive CR2 loss - the 512-record
critical log overflowed (snapshot 10: count 512, drop 6) after Weather's VCN records;
my per-process GEPC lines had taken 34 critical records (now budgeted to 4 successes in
candidate 504). Guest exit clean (GPU idle, CP_STAT 0); CR2 loss -> noqueue recovered,
authorizes=true (run/candidate-503-noqueue-recovery.json).


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-504-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

Candidate 504 / metal-307 (GE PC oversubscription cleared by default, no boot-arg).
The temporary noweather LaunchAgent was removed from the guest at SSH-up (moved to
/var/tmp/org.raphaelgpu.diag.noweather.plist.removed-20261014). Weather opened at login
by itself (pid 614) - the exact login scenario that hung the GPU in 501-split and 502 -
and the session ran with 0 gfx hang dumps and 0 GPU restarts; GEPC patched every Metal
client at text+0x13a5db. Session ended after ~4 min by the interactive capture-fatal
path: the 512-record CR2 budget overflowed again (count 512, drop 4). Every category is
bounded, but their sum exceeds 512 once Tahoe apps open video decode contexts
(VCNCTX 37 records, SD remap 16). Candidate 505 keeps only the first four successful
VCNCTX pairs and SD remaps critical (failures stay critical), ~36 records of headroom.
Clean guest exit; CR2 loss -> noqueue recovered, authorizes=true
(run/candidate-504-noqueue-recovery.json). Host suite on 504: 1626 tests, one source
contract (test_vcn_preset_source lock condition) updated for the new gate.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-505-results`
- Verdict: `INVALID`
- Boundary: `identity_or_route_missing`

Candidate 505 / metal-308 (first attempt): guest kernel panic 2 min into boot, before any
GPU work - invalid opcode at com.apple.filesystems.apfs apfs_check_and_alloc_alt_name+0x6
during root mount (kernel code corrupted in guest RAM). Same unexplained class as 488,
perf15v2, novmm, fresh3, eft2 and today's GPU-less plain-guest panics/hangs. The runner
never reached the interactive hold (critical UART pending until the 6000 s deadline), so
stop-requested had no effect; SIGTERM to experiment.py took the cancellation path: forced
shutdown, ordinary recovery refused (no XH2 ownership record), noqueue recovered,
authorizes=true (run/candidate-505-noqueue-recovery.json). Host suite on 505: 1630 tests OK.
Host evidence: no MCE/EDAC, bad-page or btrfs csum errors; KSM off; zram swap 1.3 GB
used; kvm_amd avic=Y. The plain-guest hang (7 vCPUs spinning on a global, tlbto_us=0)
looks like lost TLB-shootdown IPIs -> next: A/B with kvm_amd.avic=0 (needs root/reboot).


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-505-attempt-s2-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`

Candidate 505 attempt s2 / metal-308 - FIRST FULLY CLEAN 26.7.1 CYCLE SINCE THE TAHOE UPDATE.
Verdict CORE_PROBE_PASS; guest-requested exit; ORDINARY recovery recovered,
authorizes=true (no noqueue fallback); CR2 lossless (count 495, drop 0).
Functional: Weather opened at login and stayed up (VectorKit precipitation map drawn,
verified from a 3840x2160 ARGB2101010 scanout dump of the rgpu-display region); Maps and
Chess (SceneKit 3D) rendered; reproducer suite incl. v4 stencil+discard, eft, 8x MSAA
1024x1024 grid, stencil-only: all PASS; 0 gfx hang dumps, 0 GPU restarts.
Hardware video: VideoToolbox hevc.gva and h264.gva encoders (IsHardwareAccelerated=1),
1200 frames 1920x1080 each, hardware decoder selected, 0 errors, max luma error 1
(tests/video_codec_sustained_probe.m, GPU registry 0x100000372); VCN not wedged.
Sunshine running; Screen Sharing listening on 5900 (host cannot reach the macvtap LAN
address itself, so no client-side stream test from the host).
Remaining risk: CR2 at 495/512 - submission-trace records (SUB trace/commit/summary,
unused by the classifier) can still push a long session over; candidate 506 trims them.


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-506-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`

Candidate 506 / metal-309 - 40-minute desktop soak, CLEAN. Guest soak script
(run/tahoe-diag-20261014/soak.sh) cycled Weather/Maps/Chess/Photos and re-ran the deadlock
cases (v4 stencil Invert+discard, 512x512 v16 4x) every ~50 s: 48/48 PASS; HEVC and H.264
hardware encode + hardware decode (600 frames 1080p each) every ~5 min from the host: 10/10
PASS (GPU registry ID changes per boot - read it from MTLDevice). 0 gfx hang dumps, 0 GPU
restarts, 0 panics over 42 min guest uptime; CR2 flat at 403 records during the soak, 422
lossless at exit. Stop request -> guest-requested exit, CORE_PROBE_PASS, ORDINARY recovery
recovered, authorizes=true. Final scanout dump: animated wallpaper/screen saver after idle.

Desktop launcher switched to release 506 / metal-310 (tools/install-desktop.sh; previous
config backed up at run/release.conf.before-506-20261014, rollback = rerun the installer
from worktrees/candidate-490 with --release 490 --card metal-286). Launcher verification is
blocked by the open guest-corruption issue, not the GPU: attempt d20261014151209 aborted
before exposure (GPU-less compat guest panicked: same 1+7 vCPU spin signature as this
morning); a manual refresh hung at "syncing disks"; the next one was refused because the
guest's own shasum of SystemKernelExtensions.kc (16b9c57c...) differed from the uploaded
bytes (c29d75fc..., identical to the earlier upload) - in-guest data corruption caught by
the identity check; the fourth sealed. Launcher attempt d20261014152105 then panicked during
guest boot before GPU work (page fault at apfs_vnop_getxattr+0xe; earlier today
apfs_check_and_alloc_alt_name+0x6). Cancelled with SIGTERM (forced shutdown; ordinary
recovery refused: no critical producer readiness), noqueue recovered, authorizes=true.
