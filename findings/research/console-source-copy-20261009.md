# Candidate350: real capture copy cost and incomplete zombie cleanup

Run `1c54d03f095e5c8617423c7ebb17445b`, metal-193, build1.0.350,
MODE2#288 on bootba51b3c6. Native Metal/WindowServer/display checks pass.
Driver and explicit SPICE60 image unchanged. Default image remains stock.

## Synthetic copy experiment

CPU malloc and CPU-owned IOSurface/CVPixelBuffer sources are copied to RAM or the
existing exclusive Bochs WC mapping, never a physical Raphael BAR.12 cases per
size/target include four source/method pairs over three rounds (first warmup),
with reversed order on round1. Readback checks every destination pixel outside
timing. RAM controls pass at1080p and4K. First1080p console attempt fails on the
IOSurface-contiguous warmup with54,537 mismatching pixels and exits4 before mode
programming. Its QEMU screenshot remains1280×800 and is not a1080p oracle.
The mismatch remains **unexplained**, not attributed to memcpy or the GPU.

Subsequent4K console cases and a repeated1080p run as GUI501 pass all12 cases;
independent QEMU screenshots match8,294,400 and2,073,600 expected RGB pixels.
One intervening root-context attempt exits3 without stage detail; repeating as
the logged-in local user succeeds. Do not infer its exact failure stage.
Steady4K CPU-owned IOSurface row copies take3.022/3.191ms; contiguous copies
4.072/4.102ms (only two observations each). These do not support a contiguous-copy
optimization. Source buffers are filled immediately before each case and readback
changes cache state; this is a discriminator, not a bandwidth benchmark.
The standalone synthetic probe was compiled with-O2; the actual presenter used
the existing installer flags without-O2. This additional difference prevents
attributing their timing gap solely to source storage. The next within-presenter
diagnostic preserves those presenter flags for both copy paths.

Stopping the normal console agent also destroys its virtual display. That can
activate a fallback display writer, but1280×800 alone does not establish who wrote
the54,537 pixels. Next repeat with independently owned virtual display, no presenter,
source verification and stable display topology. Exclusive user-client ownership
does not itself exclude all other framebuffer writers.

## Permission recovery and actual captured-frame timing

Candidate348's instrumented presenter is installed as a supplementary diagnostic
on this350 run. SourceSHA256d94b47c7c8b7dff47568f9d2d38d04025caa37448cccd2df06d949fda2ab5666;
signed executableSHA256de0a747c981ca84f200cf02b704e0205e36965bdccc3b3b57be31e00c9723c22.
Source is brought into this branch after the run, preserving original build identity.
The original approved bundle is retained under/var/tmp/c350-approved-before-timing.app.

The user cannot access Settings, but the previously tested guest Screen Sharing
UI route is available. Only this app's ScreenCapture consent is reset with tccutil;
the exact /Users/bogdan/Applications/Raphael Console.app is then added through
normal System Settings UI, including its normal authentication dialog. No TCC DB
or policy modification. The app's enabled entry is captured and successful
CONSOLE_TIMING/frame output after restart verifies renewed permission.348's TCC
blocker is therefore resolved for this signed diagnostic build.

The same60-second moving AppKit fixtures and30-second ROI samples observe48.482
native and16.267HiDPI distinct tokens/s. Both fixtures complete and the actual
manager desktop returns; display-awake assertions pass. Counts remain sampled
buffer delivery, not GPU fps or scanout. Native rate variation and intermediate
token samples remain; no speedup claim from instrumentation.

Selected full5-second presenter windows exclude mode-transition frames and require
at least50 steady frames. HiDPI windows are selected after the native phase;
these are not exactly clock-aligned to the30-second observer windows:

| Phase | Native1080p weighted mean ms | HiDPI weighted mean ms |
|---|---:|---:|
| Queue |0.023|0.024|
| Buffer lock |0.735|3.446|
| Row copy |4.054|16.074|
| Store fence |below0.001 rounding|below0.001 rounding|
| Unlock |0.005|0.005|
| Worker total |4.801|19.532|

13 native windows/3043 frames;15 HiDPI windows/1294 frames. These are wall times,
not CPU utilization. Actual captured-frame copy is much slower than the owned
synthetic source in these observations, but source memory/cache/producer effects
are not isolated. Next compare direct SCK→WC, SCK→preallocatedRAM and RAM→WC with
controlled ordering and the same stride; GPU blitting is not yet justified.

## Capture and teardown

CORE_PROBE_PASS, earliest_failure=null. Outer shutdown: exited-after-guest-request.
GPU recovery: recovered, authorizes_launch=true. VM/cycle stopped, host awake.
**Native terminal.json absent again.** Both EOF hooks refuse originalPID112 in
stateZ and immediately stop the container (~0.391s). The strict completed-zombie
helper returned false; existing receipts do not identify which predicate failed.
This does not prove a fully completed process was rejected.347/348's already-reaped
passes did not qualify the new branch. Next add predicate-specific refusal data
before choosing bounded waiting; preserve live-worker refusal and original deadline.

1178 local host tests pass,8 skipped before this run. Dev277ff81's hosted tests and
macOS build are green.350 remains local pending follow-up; main is unchanged.
[Artifact identities](console-source-copy-evidence-20261009.json).
