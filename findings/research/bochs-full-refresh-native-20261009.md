# Candidate352: opt-in full-refresh native result

Run `7904cfef4aaa37f79efe02f604d921ac`, metal-195, build1.0.352,
MODE2#290, bootba51b3c6. Driver source unchanged; pinned diagnostic image
`945eea905d337c7a3725ceab5d34175040e938a4eef97730ca14d43b92396196`
uses the exact admitted `x-debug-full-refresh=on` property at SPICE60.
Only Bochs VGA dirty tracking is disabled; migration logging remains intact.
Default image and profile are unchanged. Native Metal/WindowServer/display pass.

## Measured console delivery

Each60-second AppKit token fixture completes. Actual virt-manager5.1.0 is sampled
for30seconds at16ms intervals, with fresh nonce and the same full/ROI observers.

| Case | Distinct updates/s | Draw calls/s between observed IDs | QEMU CPU cores | Invalid samples after first valid |
|---|---:|---:|---:|---:|
| Native, full observer |44.186|47.266|0.751|18|
| Native, ROI observer |50.084|53.501|0.515|7|
| HiDPI, full observer |31.758|37.168|0.465|47|
| HiDPI, ROI observer |34.882|38.463|0.453|33|

These are delivery lower bounds, not GPU FPS, host scanout or smoothness ratings.
Producer rates come from matching first/last observed sequence IDs to the guest
DRAW log; these are AppKit draw events, not presentation timestamps. The producer
itself does not sustain60 draw calls/s, especially in HiDPI, so these tests cannot
establish a60Hz console ceiling. ROI changes observer overhead; it is not a driver
optimization. QEMU CPU is its entire host process (vCPU/display threads), using
identity-bound `/proc/PID/stat` samples enclosing each observation window. It is
not total host CPU, manager CPU, or an encoder-only cost. No OFF CPU baseline yet.

The same approved O2 presenter from351 remains installed, SHA256
`368a69adb31ec9bcc317b6b3ddd4e01a11bee3dcf52ba785cd1e15c56ae45dbc`.
Selected5-second steady windows average native0.637ms CV lock +0.371ms row copy;
HiDPI4.404+1.477ms. Selection requires>=50frames,4.9–5.5seconds,
excluded_mode_frames=0 and, for HiDPI, occurrence after first native window.
These windows are not precisely clock-aligned to the observer's30seconds.

After delivery measurement, source diagnostics are enabled without rebuilding or
renewing TCC. Eight retained-frame comparisons per geometry all pass full-byte
readback. HiDPI direct writes1.206–1.762ms and RAM→console1.192–1.464ms;
source→RAM0.957–2.372ms. Native first diagnostic direct write2.997ms is an outlier;
later direct writes0.275–0.532ms. Diagnostic readback/caching perturbs subsequent
samples, so it is not a throughput benchmark. Both paths and orders now write
cheaply, consistent with VGA dirty tracking causing the prior large penalty.
A353 same-image OFF baseline is prepared to isolate that setting in native use.

Normal LaunchAgent configuration is restored (diagnostic flag absent), capture
restarts and real manager desktop is visible; display-awake assertions verified.
The screenshot `run/c352-final-desktop.png` retains the flat teal background,
so no wallpaper/transparency qualification follows. Closing manager leaves the
same VM alive. Full refresh still permits concurrent partial-frame observations;
it is not atomic publication and may add static-frame display work.

## Capture and cleanup

CORE_PROBE_PASS, earliest_failure=null. Outer shutdown is
exited-after-guest-request; GPU recovery is recovered/authorizes_launch=true.
Native terminal receipt is **absent**. Both EOF hooks stop immediately (~0.370s)
with original PID113 stateZ: completion_reason=not-sole-task,
completion_task_count=2. This establishes why proof was refused: one other thread
still existed. It does not establish that the thread was harmless or that proof
should have accepted it. Preserve strict proof and investigate bounded shutdown
ordering separately. No clean native controller completion claim.

1188 host tests pass,8skip. VM/cycle stopped, host sleep:idle inhibitor retained.
Candidate remains local pending the controlled OFF comparison and milestone scope.
[Samples, timing windows and receipts](bochs-full-refresh-native-evidence-20261009.json).
