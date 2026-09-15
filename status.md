# Live status — 2026-09-16

## Current result

**Offscreen Metal passes; hardware H264 remains unresolved through candidate269.**
All263–269 passed1000 offscreen frames with zero sampled pixel mismatches and the
24-case readback matrix. All hardware encoders selected GVA hardware, accepted
frames0/1, stalled on frame2, produced no callbacks and hit probe deadline124.
CORE_PROBE_PASS covers the desktop probe, not the separate codec probe.

| Candidate | Observed intervention | Result |
|---|---|---|
|263|Native inactive decoder ring initialized before pause|Pause ACK failed|
|264|Shared allocation/window4096bytes|Same; inherited pause4 confounds freshness|
|265|Preinit unpause4→0|New pause ACK still failed|
|266|Shared buffer moved to VRAM|Same|
|267|Shared flags f47→b40|Same|
|268|PSP mode0, native SRAM ownership, zero firmware/stack placeholders|All guards and firmware-loaded query pass; same pause/frame2 stall|
|269|PGFSM core-on config2a2a9aa5, real waitpassed and status2aaa8aa0|Same pause/frame2 stall; core-on condition alone insufficient|

268 follow-up hardware-decode probe never reached decoder creation: it stalled
at software encoder creation after the hardware encoder hang. This is dirty-state
behavior, not evidence that hardware decode fails. Fresh decode-first result is recorded below.

## Identity and cleanup

Boot `c782d007-ca85-409b-9cf5-ff12c1a8c6d5`, GPU0000:7b:00.0 on vfio-pci,
power/control=on, PCI reset methods disabled. Native Linux baseline preceded the
user-authorized Linux→VFIO handoff. **No amdgpu rebind this boot.**

- 267: run1127597f31560ab35dbaf46baa05cdad, build589d40a85f0c4333be158bdba134dbb3, source1bf1578, MODE2 reset124.
- 268: run7a6e65cd000f2d91b6635d7758194477, build4ff2486909654de18c323ccf5c115ccd, source094ee6f, MODE2 reset125.
- 269: run00d58c289223e0a5f8ba31e8aef089aa, build99b9deda82244b30917ce489f98654df, sourceef0554a, MODE2 reset126.
- Results `/home/bogdan/macos-vm/run/candidate-N-results`; source corresponding candidate worktrees.
- All seven harness verdicts CORE_PROBE_PASS; critical capture and identity validated.
  All shutdowns forced, not clean guest shutdowns; all recovery receipts recovered.
- 268 full host suite937tests OK, three skipped. Initial software-allocation fixture
  was updated to verify native ownership and refusal without context mutation.
- Nine launches recorded this boot (including269 decode-first and270). Earlier staging/fixture prelaunch refusals did
  not consume launches. No merge or push.

## Display evidence and remaining scope

267 has an AMD-backed1280x1024 display and WindowServer accelerator client.
Window drawable readback11616 sampled pixels, wrong0; two own-window captures
match quadrant patterns and show moving bar spans241..280→44..83. Whole-display
window-region captures show wallpaper only, screen_capture_preflight=false;
zero nonzero-time presentations. Capture privacy versus actual desktop composition
remains unresolved. 268 also has a correct drawable readback. Screen Sharing
responds on host127.0.0.1:5900 with RFB003.889; no external frame qualification yet.
Watchable external desktop, physical scanout, codecs and long-run lifecycle remain
unqualified; do not equate offscreen success with completion.

## Fresh decoder result: 269 attempt decode-first / metal-116

Run `57a26a17253fc749f2d996dd4c51505b`, same binary/build as269, MODE2 reset128.
No hardware encoder request in this attempt. Results:
`/home/bogdan/macos-vm/run/candidate-269-attempt-decode-first-results`.

- Offscreen Metal:1000 frames, zero sampled mismatches;24 readback cases passed.
- Required decoder GPU registryID test returned-12906. **Retracted as a valid
  built-in GPU test:** exact guest SDK restricts that selector to removable/eGPU.
- Corrected unpinned required-hardware H264 and HEVC decoder creation returns-12913;
  H264 also fails as console UID501 and with explicit Baseline profile.
- AppleGVA logging: ATI plugin selected, then `ctx_info.error = a` during initial
  SPS/PPS/context setup. No observed VCN initialization call during these tests.
  The temporary enableSyslog preference was restored (sync=1).
- Software H264 control passes3 decoded frames,2675475 luma values, maxerror1.
  Initial control falsely counted unsupported hardware-status property(-12900) as
  failure; corrected control allows that only for explicitly software decode.
- Capture/identity: verdict valid=true, CORE_PROBE_PASS for desktop probe; terminal
  critical capture accepted. **Overall acceleration remains unqualified.**
- Shutdown `exited-after-guest-request` (unlike prior encoder-hung forced exits);
  recovery `recovered`, no recovery kernel messages, same boot and vfio/on state.
- Earlier reset127 staging refusal was before QEMU; no launch consumed. Isolated
  attempt copy was prepared explicitly before the successful reset128 launch.

Current blocker for decode is AMD plugin context creation. Analyze exact
AMDRadeonVADriver2 from the already captured24G830 cache to locate error10 before
another hardware candidate. Encoder's pause/packet-execution failure remains
separate; Linux performs a decoder-ring command test before encoder startup,
whereas our existing decoder-first hook only initializes the ring. That packet
experiment is unimplemented and needs native ownership/commit/drain qualification.
Do not equate either failure with proven dead silicon or exhausted driver options.

Boot allowance9 has been used; a further launch needs a boot-named extension note
and all ordinary gates. No amdgpu rebind this boot, merge or push.

Linux reference: `/home/bogdan/macos-vm/run/worktrees/linux-vcn-baseline/findings/research/linux-vcn-baseline-20260915.md`.
Linux H264/HEVC encode/decode and600 validated H264 frames passed. Working Linux
also reads cache/reset/LMA registers asffffffff and UVD_STATUS asdeadbeef; these
values do not prove a dead VCPU. No claim that driver-level options are exhausted.

## Candidate270 result: context trace / metal-117

Run `e8fadcb4f04102cad6a99f3dfc5838d3`, build`b730ff90153b45a0ae2e3ebc10f16f97`,
source571ddfb, MODE2 reset129. Ninth exposure this boot; no hardware encoder request.
All four hooks routed (StartEngine serial line interleaved; raw bytes retained).
Hardware H264 decoder creation still-12913; no create/capability/start hook entries.
Software control passes3 frames,2675475 luma values,maxerror1. Temporary gvaDebug
preference restored(sync1). Offscreen1000frames and24readback cases pass.
Capture/identity valid=true, CORE_PROBE_PASS covers desktop only; guest-requested
exit, recovery recovered,no recovery kernel messages. Results`run/candidate-270-results`.

**Trace limitation:** the sendPMCommand caller filter omitted earlier video-context
calls at28d1d/28e4f. AMDVA VAVcnDecoder::setupPowerState calls setClocks before
CreateVcnContext; its0x102 userclient request can fail independently. No claim that
all kernel decoder work is absent. Candidate271 extends this observational filter
and records bounded request headers and real results; no functional VCN changes.

AMDVA exact cache image independently extracted;2872 functions exported,zero export
failures, under`run/research/decoder-context-20260916`. The error10 producer is not
yet identified; absence of a literal10 in selected AMDVA paths does not prove
kernel/firmware origin. AppleGVA copies an event9 error payload verbatim.

## Next authorized run:271 early video PM trace

Extend allowance9→10 on boot`c782d007-ca85-409b-9cf5-ff12c1a8c6d5` under the user's
continued-testing instruction. Add earlier video-context PM callers to270 trace,
request header and native result observations; no functional VCN change. Preserve
all identity/capture/reset/host-fault/shutdown/recovery gates and max6000s. Require
all four critical route guards, unpinned hardware decode before any encoder request,
manual stop after observations.270 recovery verified; no amdgpu rebind or merge/push.
