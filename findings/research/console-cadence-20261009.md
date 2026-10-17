# Candidate342: native manager cadence and refused terminal grace

Run `00bad24a728429d67f21519fb472a563`, metal-188,1.0.342,
build24d88f85ac304af5a7502bb73ca411c0, source360db9ae286a3f57cabd21c09bf32621b6135fe4.
Executable SHA31c774ca80e033dc9d01675e7e388ebef243d6a6a103c02655098ee1362c6ca8.
Same host bootba51b3c6, MODE2#283; ordinary341d recovery admitted the run.
Native driver source is unchanged. Full host suite:1,128 pass,3 skipped.

## Observed native function

The paused libvirt launch, exact process/configuration/network proof and host
resume permit pass. Native desktop Metal completes with WindowServer ownership.
Global capabilities now list x86_64 and the real emulator: the daemon PATH fix
transfers successfully to the native profile. Actual virt-manager renders the
1920×1080 native and3840×2160 HiDPI desktop. The exact guest-only mode selector
returns matched=1 for each. Awake assertions remain active. Domain XML is byte
identical before/after the manager connection; closing the viewer leaves the
original CID/start running. Both token fixtures finish and the desktop returns.
Input and LAN were independently qualified on341d; they were not remeasured here.

## Sampled actual manager-buffer delivery

The sampler runs inside the same virt-manager process and reads its SpiceDisplay
pixbuf; it opens no additional SPICE connection. Each sample validates the fresh
nonce, CRC32, cell consistency and two matching token copies. Its16ms requested
interval is not a promise of60fps. Each60-second guest fixture increments draw
IDs in AppKit drawRect; these IDs are not GPU presentation timestamps.

| Observation | Native1080p | 1080HiDPI |
|---|---:|---:|
| Captured pixels |1920×1080|3840×2160|
| Measurement duration |30.010s|30.006s|
| Unique valid tokens |895|555|
| Sampled unique updates/s |29.82|18.50|
| Median sample cost |2.24ms|5.28ms|
| Median unique-token gap |32.11ms|64.21ms|
| 95th percentile unique-token gap |64.23ms|96.35ms|
| Longest observed stale interval |96.38ms|128.47ms|
| Invalid samples after first valid |8|18|
| Guest60-second total AppKit draws |3028|1993|

This is a sampling lower bound for decoded-manager-buffer updates, not GPU FPS,
host compositor scanout, complete delivered-frame accounting or absolute latency.
The sampler itself copies pixels and costs CPU time. Skipped draw IDs may originate
before capture, during transport or between samples; they do not independently
count dropped frames. Native8 and HiDPI18 post-start samples have torn-cell or
checksum failures. They disprove universal complete-token delivery, not all desktop
pixel correctness. Raw samples retain invalid entries and sampling duration.

A source-supported hypothesis is that QEMU10.1.2 nongl SPICE uses the default30ms
refresh timer, scheduled after refresh work. The existing max-refresh-rate option
is used in the GL refresh branch, so adding that flag to the current gl=off profile
is not an established fix. Separately, console-presenter copies complete SCK frames
row-by-row into the live framebuffer. Its fence orders writes but supplies no atomic
frame-commit/consumer acknowledgement. This can produce mixed generations in a
concurrent reader; an isolated A/B is needed to localize the observed partial tokens.
Do not trade higher update rate for more tearing without measuring both.

Local source reviewed: `run/research/qemu-smc-20260916/qemu-10.1.2`:
ui/spice-display.c SHA f63dea0feed37fef74f021fa271c9446d891ef8f9c65a2bea83cd13424fae8ed;
ui/console.c SHA fea1100dd5d376b762451c6c639b2dffdd666cab7b4e9a6903769560ab0cbe9a;
include/ui/console.h SHA cd5cba3de893ec04a3e46163332bbddb4d4afd54c813bac9a7e118017473af6f.
These facts explain a plausible ceiling, not a completed causal performance test.

## Capture, shutdown and remaining defect

Capture is valid CORE_PROBE_PASS, earliest_failure=null. The critical producer
quiesces with the existing terminal-prefix acceptance policy. Outer shutdown
records exited-after-guest-request. Native GPU recovery is recovered and
`authorizes_launch=true`. The VM is stopped; host sleep:idle inhibition remains.

**The native libvirt terminal receipt is still absent.** Both capture-exit hooks
record RuntimeError, deferred=false, immediate-stop, about0.342s elapsed. They
never entered the bounded grace. Retained module hashes and plan/paused/resume/
running bindings match. The safe wrapper did not retain the failing inspection
stage, so original-QEMU lifetime, process-scan permissions and Docker-exec races
remain distinguishable hypotheses. The two successful software S5 tests did not
establish this native outcome. Preserve that failure rather than reporting clean
controller exit from the independent GPU recovery result.

Production also starts a container SSH helper absent from the small software
fixture. Candidate343 investigates its root-process permissions and whether this
unused daemon can be omitted without affecting QEMU's separate guest SSH forwarding.
No new grace or reboot is justified merely by the missing receipt.

A separate nonfatal virt-manager default-pool attempt used a client-local XDG path
inside the container, failed permissions and undefined the pool. Guest domain XML
was unchanged. Prefer explicit private pool configuration over changing host-path
permissions. No claim of full VM-manager lifecycle, atomic presentation, automatic
resize, VirtualBox support or general desktop/performance qualification is made.

[Selected outcomes and artifact hashes](console-cadence-evidence-20261009.json).
Private launch/XML files are retained locally and hashed, not published.
