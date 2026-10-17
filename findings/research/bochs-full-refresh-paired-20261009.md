# Candidates352/353: same-image full-refresh comparison

Candidate353 run `8b32ccd1e303a4b3fa845aaeded1d885`, metal-196,
build1.0.353 (`fd23737808864f59be3614eba2bbbf46`), MODE2#292, bootba51b3c6.
Same diagnostic QEMU image945eea90, SPICE60, guest O2 presenter368a69ad,
manager5.1.0, fixture and observers as352. The Bochs full-refresh property is
absent, so its default is OFF. Driver behavior is unchanged. Native Metal,
WindowServer and display probe pass. Awake assertions are retained.

## Paired observations

Each independent60-second AppKit fixture completes; manager sampling lasts30s.
Rates are sampled distinct updates, not GPU FPS or host scanout. Full/ROI names
refer to the observer; ROI does not change the display transport.

| Case | OFF delivery/s | ON delivery/s | OFF draw calls/s | ON draw calls/s | OFF QEMU cores | ON QEMU cores |
|---|---:|---:|---:|---:|---:|---:|
| Native, full |49.918|44.186|52.631|47.266|0.956|0.751|
| Native, ROI |49.188|50.084|52.365|53.501|0.689|0.515|
| HiDPI, full |23.531|31.758|46.080|37.168|0.803|0.465|
| HiDPI, ROI |22.363|34.882|43.952|38.463|0.725|0.453|

Selected steady presenter windows reproduce the expensive OFF writes:

| Geometry | OFF lock / row / worker ms | ON lock / row / worker ms |
|---|---:|---:|
|1920x1080|0.649 / 4.042 / 4.703|0.637 / 0.371 / 1.019|
|3840x2160 (1080 HiDPI)|3.744 / 16.381 / 20.138|4.404 / 1.477 / 5.893|

Selection matches352:4.9–5.5s windows, >=50frames, zero excluded-mode frames,
HiDPI only after first native window; OFF24native/23HiDPI windows. These phase
windows are not precisely aligned to the observer windows. Draw rates match first
and last observed token IDs to guest DRAW timestamps, not presentation timestamps.
QEMU CPU covers its whole identity-bound host process, including vCPU/display
threads; not manager CPU, total host CPU or encoder-only cost. Sampling padding
and all raw artifact hashes are retained in the adjacent evidence JSON.

The OFF comparison restores the row-copy cost while using the same image and
presenter. Alongside the isolated KVM dirty-write test and352's16 successful
full-byte frame checks, this supports VGA dirty tracking as the large write-cost
source. Enabling full refresh improves HiDPI delivery in this setup and lowers
measured QEMU CPU in all four cases. Native delivery does not improve uniformly.
The AppKit producer itself varies and does not sustain60 draws/s; this pair does
not establish a60Hz ceiling, broad smoothness, atomic frames, or all-GUI support.
OFF invalid samples after first valid are10/17 native and90/89 HiDPI; ON18/7 and
47/33. Concurrent updates remain observable; full refresh is not atomic publication.

## Function, capture and cleanup

Normal desktop is visible in actual virt-manager after fixtures, with wallpaper
and application windows in `run/c353-final-desktop.png`. This screenshot is not
broad transparency/application qualification. Closing the viewer leaves the exact
VM alive. No guest binary rebuild or TCC consent change is needed in353; normal
presenter remains installed with the source diagnostic flag absent.

Capture CORE_PROBE_PASS, earliest_failure=null. Outer shutdown records
exited-after-guest-request. Both EOF hooks immediately stop (~0.316s), refusing
original PID113 stateZ with two tasks; completion_reason=not-sole-task. Terminal
receipt is absent, so no clean controller completion claim. GPU recovery is
recovered/authorizes_launch=true. Cycle and VM stopped; host remains awake.
Candidate354 will persist early guest shutdown observations and bounded task
state diagnostics, without relaxing the capture-loss gate.

The first353 attempt failed before QEMU/VFIO exposure because the prepared
build-identities file lacked its schema/path/hash expansion. MODE2#291 occurred,
but no GPU ledger launch was consumed. The failed metadata/log are preserved;
expanded identities passed the real build-input validator before retry#292.

1189 host tests pass, eight skips. Checked-in kext/manifest now match353.
Default QEMU/profile remain unchanged: full refresh is an explicit diagnostic
option requiring the pinned image and SPICE60. General desktop/performance,
lifecycle durability, resize/input coverage, console audio, install durability
and VirtualBox remain separate roadmap work.

[Paired data and receipts](bochs-full-refresh-paired-evidence-20261009.json) ·
[ON source-frame checks](bochs-full-refresh-native-20261009.md) ·
[KVM causal test](kvm-dirty-pair-20261009.md).
