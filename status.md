# Live status — 2026-09-16

## Current result

Offscreen Metal passes; full desktop/display and hardware codecs remain unqualified.
Candidate271 identifies an earlier decode blocker in our compatibility policy:
`wrapPpPowerUp` clears PowerPlay support (+0x28f8), so its readiness check rejects
AMDVA's pre-context clock request. This supersedes claims that all failures are
below the driver or that driver options are exhausted. Encoder remains separate.

| Area | Evidence | Remaining issue |
|---|---|---|
|Offscreen Metal|271:1000 frames, zero sampled mismatches,24 readback cases pass|Not full desktop qualification|
|Hardware decode|271: PM00c00053 caller+28d1d returns e00002c7; create returns-12913|PowerPlay compatibility/readiness before VCN context|
|Software control|271:3 decoded frames,2675475 lumas,maxerror1|Pass|
|Hardware encode|263–269: hardware selected,frames0/1 accepted,frame2 hangs,no callbacks|Pause acknowledgment/packet execution unresolved|
|Display|267:AMD drawable and own-window readback correct|External/physical output and compositor capture unqualified|

## Latest run and cleanup

Candidate271/metal-118,run `39c0d61758f19ada2d7db6ee73c7570e`,
build `0ed4110244f64edcb88db82eed60b285`,source `dc42b9082e18bef4f6303caad6f75a4b5659d00d`,
HEAD07d4e74,MODE2 reset130. Four exact kernel route guards passed. No hardware
encoder request. Results `/home/bogdan/macos-vm/run/candidate-271-results`:
serial.txt,decode-control-hw-output.txt,decode-control-sw-output.txt,
decoder-framebuffers-hw-output.txt,verdict.json,shutdown.json,recovery.json.
Capture/identity valid, CORE_PROBE_PASS applies to desktop probe only.
Shutdown exited-after-guest-request; recovery recovered, no kernel messages.
Host suite937tests passed,3skipped. No merge/push.

Boot `c782d007-ca85-409b-9cf5-ff12c1a8c6d5`; GPU0000:7b:00.0 vfio-pci,
power/control=on, reset methods disabled, no QEMU after cleanup.
Ten exposures recorded/allowance10 used. Pre-QEMU staging refusals consume none.
Linux initialized GPU before the authorized handoff. No amdgpu rebind this boot.
Further exposure requires a boot-named allowance extension and all normal gates.

## Source-supported next step

Exact24G830 AMDVA VCNPowerManagement::isDpmSupported returns true unconditionally;
VAVcnDecoder::setupPowerState has a native unsupported-DPM path that destroys the
PM client and continues to context creation. Investigate matching that capability
to the actual Raphael backend, preserving native resource ownership and real VCN
power-up. Do not fake clock-response success or mark uninitialized PowerPlay ready.
The kernel bypass was needed for graphics startup; restoring its flag alone does
not initialize PPlib or completeInit. The existing comment claiming the support
flag is read only during powerUp is wrong.

AMDRadeonX6000Framebuffer-full and HWLibs-full contain full PowerPlay source.
AMDVA exports: `run/research/decoder-context-20260916/export-all-20260916`.
Native framebuffer instances are present; virtual-display mismatch is not shown.
AppleGVA error10 callback producer mapping remains incomplete; the observed native
PM failure already supplies a concrete earlier failure boundary.

## Linux reference and wider qualification

Linux reference `run/worktrees/linux-vcn-baseline/findings/research/linux-vcn-baseline-20260915.md`:
H264/HEVC encode/decode pass,600 H264 frames validated. Working Linux also reads
cache/reset/LMA asffffffff and UVD_STATUS asdeadbeef; these do not prove dead VCPU.
Linux boot ring test submits decoder packets before encoder; our hook currently
only initializes the native decoder ring. Packet experiment remains unimplemented.

267 own-window capture matches moving test patterns. Whole-display ROI captured
wallpaper with screen_capture_preflight=false; presentation timestamps allzero.
Privacy versus composition unresolved. Screen Sharing answers RFB; no externally
validated frames. Physical scanout, long-run lifecycle and hardware codecs remain
unqualified. Prior encoder-hung guests required forced shutdown;269 decode-first,
270 and271 exited after guest request. Superseded details are in status archives.
