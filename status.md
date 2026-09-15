# Live status — 2026-09-16

## Current result

Offscreen Metal passes; full desktop/display and hardware codecs remain unqualified.
Candidate271 identified an earlier decode blocker in our compatibility policy:
`wrapPpPowerUp` clears PowerPlay support (+0x28f8), so its readiness check rejects
AMDVA's pre-context clock request. This supersedes claims that all failures are
below the driver or that driver options are exhausted. Candidate272 removes this early rejection; the first real decode submission now hangs.
Encoder remains unresolved.

| Area | Evidence | Remaining issue |
|---|---|---|
|Offscreen Metal|271:1000 frames, zero sampled mismatches,24 readback cases pass|Not full desktop qualification|
|Hardware decode|272: decoder created, hardware selected; first DecodeFrame stalls|VCN0Dec stamp1 never completes|
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
Eleven exposures recorded/allowance11 used. Pre-QEMU staging refusals consume none.
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


## Candidate272 result: native no-DPM path reaches hardware decode

Run`cc4abd9fd50b3183b84ba6dd82392cb6`,build`89f8e8c3be8449eb89935901cc5332ec`,
source39a7a53,HEAD0765c12,MODE2 reset131. Results`run/candidate-272-results`.
- Exact image guard and COW delivery pass for decoder helper pid737: UUID and8bytes
  match; protect/write/restore/verify all0. All six kernel routes pass.
- Native video newContext: codec3,channel8,1280x720,scheduler0,client0,pm0;
  capability=true,creation0,id1,startEngine0. No early00c00053 rejection.
- VideoToolbox decoder creation0, UsingHardwareAcceleratedVideoDecoder=true.
  First DecodeFrame never returns; deadline90s,exit124,no decoded callbacks.
  Native channel13 VCN0Dec stamp1 hangs and guest attempts repeated GPU restart.
- VCN real SMU power response1,PGFSM wait0,PSP submit successful; these native
  successes do not establish firmware/queue execution.
- Offscreen1000frames and24readback cases pass before codec workload; valid
  CORE_PROBE_PASS is scoped to that desktop probe. No HWencoder was requested.
  Software encoding produced3samples; no separate decode control after dirty stall
  (271's clean software control remains the reference).
- Shutdown forced, recovery recovered,no recovery kernel messages. Same boot,
  vfio/on, no QEMU after cleanup. Full937tests passed,3skipped. Not merged/pushed.

**Dispatch correction:** prior shared CreateVcnContext21ba0 does not cover AMDVA's
selector104. Exact table1607a0 and Navi10 vtable16c618 map100→2892c,104→49292,
106→49632.272 adds guarded video HWInfo and newContext hooks. This corrects older
claims of comprehensive context trace coverage.

Next: inspect actual decoder-ring submit, pointers, address translation and packet
format against Linux. A native decoder workload has now reached the hardware ring;
initialization alone is no longer the only decoder evidence. Capability correction
is validated through creation/start, not functional decoding. Do not revive dead-
VCPU or exhausted-driver claims from register read sentinels.
