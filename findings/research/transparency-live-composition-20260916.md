# Live composition corruption, 2026-09-16

Not fixed. Evidence belongs to candidate277 run b92d134b7f4cfde7658852b446d594db,
results `/home/bogdan/macos-vm/run/candidate-277-attempt-capturepath-results/`,
unless stated otherwise. Research scripts and disassembly extracts are under
`/home/bogdan/macos-vm/run/research/transparency-20260916/`.

## Discriminating observations

* Raw libvncclient RFB capture reproduces green/purple diagonals without JPEG/HEVC.
* Candidate278 `native-screenshot.png` (real Shift-Cmd-3, including Safari) is clean;
  `raw-after-native-screenshot.png` remains corrupt. Root CLI screenshot omits app
  windows and is not a valid comparison.
* Current `surface38.png` reads ScreensharingAgent's DisplayStream CPU backing:
  already corrupt before RFB encoding.
* `flattened-gpu.png` reads Safari's Flattened Window IOSurface51 via a Metal blit:
  clean. `scanout1-gpu.png` reads CoreDisplay scanout IOSurface1 the same way:
  corrupt. Cross-process IOSurface lookup requires a WindowServer-exported Mach
  send right, copied into the readback probe. Direct WindowServer CPU mappings
  (`flattened.png`, `scanout1.png`) were black and cannot establish GPU contents.
  Readback waits for its own GPU command buffer, not an independently observed
  producer fence. The stable scene supports the comparison but is not frame atomic.
* Live Core Animation pipeline labels captured by an actual encoder breakpoint
  include half-precision blur, color matching, darken/lighten and premultiplied
  composition. Native SkyLight UberComposite observed options0 replay passes.
  Presence of AMD OpenGL in ScreenSharingAgent's mappings does not prove execution.

## Negative controls and limits

Candidate278 linearSwizzleTextures bit36 did not fix raw visual corruption; reject
that driver change. Half-filter blur (12 format/storage cases), CoreImage blur,
MSAA resolve, divergent fragments, render-pass load/blend, half fragment output,
constant half varying, derivatives and exact installed SkyLight composite shader
all pass. These are isolated tests, not complete coverage of live CA state.

Four temporary process-only controls did not fix the observed image and have been
restored with readback verification: ScreensharingAgent legacy fallback branch,
QuartzCore CA_DISABLE_INPLACE_SHADERS, get_pipeline_spec half-precision bit, and
CA_DISABLE_ENCODER_SHARING. Logs respectively `capture` control probe outputs,
`inplace-restore.txt`, `precision-float-restore.txt`, `sharing-restore.txt`.
Delivery was verified; actual affected runtime branches/pipelines were not traced.
No disk Apple binary, security setting or persistent preference changed.

Candidate278 OpenGL probe caused the first observed graphics stall: RPTR0x5c31,
WPTR0x3c5e80, CP_CE_HEADER c0008b00 then ffff1000, CP_STAT90018600;
no recorded VM fault. All GL pixels were wrong after the stall. Downstream KIQ
errors are not established as the primary cause. Supervised guest-request shutdown
and recovery succeeded. Do not rerun that workload before tracing its first draw.

## Independent outcomes

Function: HEVC fix retained; transparency remains wrong. Identity: exact 277 binary
SHA1e50cf16c8ac4333a84b84321394cce07b28c94947e1264aa5b86463b588b17a,
QuartzCore UUID2e431591-d52c-37fc-8fb8-049cdc01c2d7. Capture: raw and native images
plus synchronized readbacks have the limitations above. Cleanup at that observation was pending. The capturepath and colorrepro runs
later exited after guest request and recovered; the currently active run is
smcpmio/a169e87a3b282ebb6552150a77a9c232, whose cleanup is pending. Overall: desktop unqualified.

Next: bounded native CA surface export to identify the first corrupt intermediate.
Export may force synchronization and change behavior; preserve that observer limit.

## Follow-up controls

Native CA surface export: marked_surface breakpoint hit35 times; debug33 and its
context guard were temporarily enabled then restored. No images resulted because
this Metal context's read_surface vtable entry is the base stub returningNULL.
No claim of captured intermediates. A bounded render-pass capture dylib compiled
but WindowServer rejected its non-platform signature; no hook installed. LLDB JIT
compilation subsequently crashed inside the debugger AST importer, before install.
WindowServer stayed running (pid166); no capture files. Abandon that route for now.

Precision follow-up `precision-verified-trace.txt`: patch-site breakpoint hit1;
actual active CA labels switched Xh to Xc/full-precision variants. The contemporaneous
`raw-precision-verified.png` still contains corrupt pixels. Code restored and detach
verified. Some text/background rendering was still changing during this capture,
so do not use the frame for exact pixel comparison. Full precision is insufficient.

Next hypothesis: kernel DISABLE_SC_BINNING workaround and native binned draw state
are inconsistent. Existing September14 binning toggles tested tile permutations
before the SDMA layout correction, not this current transparency defect. A bounded
live bit41 control in WindowServer, with consumer breakpoint and restoration, will
test this distinct workload. This is not a claim of root cause.

Binning follow-up: `binning-verified-trace.txt` changed one real device setting and
hit UpdatePrimBatchBinning with bit41 cleared. `raw-binning-verified.png` remained
corrupt. Setting restored and detached. This control is insufficient.

## Actual Apple GPU capture obtained

WindowServer restarted with launchd MTL_CAPTURE_ENABLED=1, immediately unset after
launch. This temporary environment is not persistent. New WindowServer pid8543,
relogin succeeded. GPUToolsCapture loaded and supportsDestination2 returnedtrue.
`apple-capture-trace2.txt` proves start/stop success on CaptureMTLDevice wrapping
GFX10_MtlDevice AMD Radeon Navi23. Guest trace:
`/var/tmp/rgpu-pass-capture/desktop.gputrace`; host archive and extracted copy:
`/home/bogdan/macos-vm/run/research/transparency-20260916/desktop-trace.tar.gz`
and sibling desktop.gputrace. Captured under user-authorized current hold;
`raw-after-apple-capture.png` still corrupt. Resolution now1920x1080 after the desktop
service restart, so this is not a pixel-identical comparison with earlier1280x1024.

Two third-party offline parsers were inspected in the research directory. The Go
parser labels render encoders as compute and uses heuristics: do not rely on its
API-name output for this capture. The Python parser's fixed selectors partially
match, but its texture-file payload-offset assumptions do NOT match this build.
Our actual dump header has magic erutpac\0, version0x10002, offset256, then
64-bit level/format/width/height/depth/rowbytes/imagebytes fields. Decoded BGRA80
textures with checked bounds; contact sheets and individual images are under
trace-images/ and trace-iosurface/. These show actual resource data, not replay.

## Parameter cache hypothesis (not yet a fix)

Apple gfx10_HwInfoInitData derives hwinfo+0xac = min(numSE*512-1,1023).
InitStaticHwRegs uses it for GE_PC_ALLOC when settingsbit42 enables oversubscription.
For the present single-SE topology this yields0x3ff: OVERSUB_EN1,NUM_PC_LINES511.
Mesa ac_gpu_info identifies Raphael parameter cache256 lines vs Navi23 1024;
RADV allocates pc_lines/4 (possibly multiplied for NGG culling), rather than Apple’s
fixed512-line count. Bounded runtime test: clamp only static GE_PC_ALLOC to0x7f
(64 lines), trace WriteStaticHwRegs consumption, compare desktop, restore.
Sources: https://raw.githubusercontent.com/chaotic-cx/mesa-mirror/main/src/amd/registers/gfx103.json
https://raw.githubusercontent.com/chaotic-cx/mesa-mirror/main/src/amd/vulkan/radv_shader.c
https://chromium.googlesource.com/external/gitlab.freedesktop.org/mesa/mesa/+/5c3a6c938b8b5825615cf9df1755ec080425edef/src/amd/common/ac_gpu_info.c

Parameter cache result: `pcalloc-verified-trace.txt` confirms live original0x3ff,
clamp0x7f and WriteStaticHwRegs consumption. `raw-pcalloc-verified.png` still corrupt,
including a newly opened Finder sidebar. Restored and detached. This mismatch is
not established as the visual root cause; do not ship the clamp as a transparency fix.

## Controlled native reproducer

`tests/transparency_color_backdrop_probe.m` modifies the earlier gray backdrop test
to render animated RGB checker/gradients under four NSVisualEffectView materials.
`raw-colored-backdrop.png` reproduces corrupt diagonals inside all four materials,
while the underlying opaque checker is intact. This supersedes any inference that
native transparency passed from the gray-only test. No Safari content is required
for these four bad panels, though other apps remain visible behind the test window.
Next actual-workload capture: colored-backdrop.gputrace, one-second bounded capture.

`surface_indexed_blur_probe.m` adds shared indexed vertices to the CPU-verified blur
workload:12cases,1,582,092pixels,0failures,exit0. Indexed drawing alone is insufficient
to reproduce the native defect. Stop using basic probe success as desktop evidence.

## Capturepath closeout

Run b92d134b7f4cfde7658852b446d594db ended by guest request; recovery.json
reports recovered and CP_STAT=0. All temporary controls were restored.
Desktop trace is complete. Colored-backdrop trace start succeeded but stopping
was interrupted; metadata is missing and finalization was not verified. Its saved
archive is partial, not a replay-ready capture. Half-gradient probe was not run
because the interactive deadline guard refused it before execution.

## Colorrepro run follow-up

Run9695b71b4eb9db3f8b99eb42e8814970, candidate277 unchanged, MODE2#146.
Half-gradient and narrow220x500 half-gradient each passed12cases. Installed
QuartzCore narrow_blur_27_frag_lph replay with CPU-checked14tap weights also passed
12cases. These do not reproduce the live native effect.
Plain-alpha floating windows over moving colored backdrop look clean in
plain-alpha-visible.png. First plain-alpha capture had the panels obscured by
window ordering and is invalid for comparison; corrected probe uses floating level.
Verified CA_DISABLE_FILTER_MERGING consumer hit01, restored00, detached; stillbad.
First filter-merging attempt failed to launch with nohup and was baseline only.
Verified CA_DISABLE_INPLACE_SHADERS consumer hit01, restored00, detached; stillbad.
Later120-draw trace shows contextcaps0x1470000: bit13 already0, so in-place was
unsupported before that intervention. All120draws are triangles; source texture
objects differ from destination in sampled state slots0..7. No read errors, detached.
This does not exclude allocation aliasing or unsampled draws/resources.
Artifacts are candidate-277-attempt-colorrepro-results/{half-gradient,narrow-gradient,
native-narrow-blur}-output.txt and *verified-trace.txt, alias-trace.txt.

Native narrow blur at viewport(105,303,220,500) inside1280x1024 target also
passed12cases (native-offset-blur-output.txt). CA_DISABLE_DIRTY_REGIONS consumer
hit01, restored00/detached; dirty-region-disabled.png remains corrupt.
Intel create_pipeline_state calls runtime device compilation and the inspected
build has no consumer for CA_DISABLE_PRECOMPILED_PIPELINES; no toggle run.
Starting live Metal validation with documented MTL_DEBUG_LAYER1, error mode nslog,
MTL_SHADER_VALIDATION1 and report-to-stderr1 via temporary launchd environment.
Restart affects WindowServer only; environment is unset immediately afterward.
Sources: https://developer.apple.com/documentation/xcode/validating-your-apps-metal-api-usage
and https://developer.apple.com/documentation/xcode/validating-your-apps-metal-shader-usage .
Validation instrumentation changes shader execution; any changed appearance is
a diagnostic observation, not a production fix. Confirm activation before claims.

Validation activated in WindowServer2716 but crashed during CoreDisplay Metal
initialization before the reproducer. It automatically restarted as2774 without
validation; all temporary launchd variables were unset. Crash is objc_msgSend
from CoreDisplay::MetalDevice::GetGPUPassRenderPipelineState, possibly an
uninitialized NSError output (inference from disassembly, not established).
WindowServer-validation.ips and validation-failure-log.txt preserve evidence.
This attempt supplies no validation verdict on the original corruption.
PerfPowerServices investigation found an independent missing SMC enumeration
command; see perfpower-smc-enumeration-20260916.md. Visual corruption remains open.

## Current revalidation on corrected QEMU

Run a169e87a3b282ebb6552150a77a9c232/smcpmio retains candidate277. PerfPowerServices
CPU correction does not fix display artifacts: native-trace.png (raw RFB) shows
colored diagonal defects in all four native visual-effect panels. WindowServer
trace detached successfully. The first150-draw capture was dominated by another
window's960x640 surface; do not treat it as the affected panel trace. A focused
300-draw follow-up includes117 draws to1280x1024 plus downsample intermediates.
Artifacts native-draw-focused.{txt,json} include pipeline labels and vertex/state
bytes. First corrupt draw is not established; shader replay selection remains open.
