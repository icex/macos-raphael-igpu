# Accelerated desktop in a VM manager console

The requested target is a macOS desktop in the VM manager's console, with Raphael
Metal rendering and no physical HDMI connection. Screen Sharing/Moonlight alone
does not meet that target. Native Metal/WindowServer ownership, real virt-manager
mouse/keyboard input and bridged LAN traffic pass. The same-image353 OFF/352 ON
comparison improves sampled1080HiDPI delivery from22–24 to32–35updates/s with an
opt-in Bochs full-refresh property; native1080p does not improve uniformly.
Candidate356 completes native reset shutdown with a real controller terminal
and authorizing recovery; the pending-worker wait remains native-unexercised.
Normal/fullscreen input pass, but the small-window transition retains two misses.
Partial-region samples, automatic resize, other frontends and VirtualBox remain
open. This is not qualified60Hz delivery.
[Current paired evidence](../findings/research/bochs-full-refresh-paired-20261009.md).
Candidate332's unsafe TMR experiment remains withdrawn.

## Architecture under test

Raphael VFIO remains the renderer. A guest CGVirtualDisplay supplies a desktop;
ScreenCaptureKit copies complete BGRA frames to a separate presentation-only
`bochs-display` PCI device. Stock QEMU presents that device through its ordinary
VNC/SPICE/GTK console; input uses QEMU's existing USB keyboard/tablet. This adds
CPU framebuffer copies, not a second 3D renderer. Sampled delivery is measured below;
full-frame throughput, scanout and latency remain unqualified.

The opt-in `rgpuconsole=1` service matches only QEMU 1234:1111, class 038000,
checks its VBE identity and bounded BARs, and never enables bus mastering. Only
local users can open its exclusive client. Userspace maps only the presentation
VRAM; mode-setting accepts bounded geometry, not arbitrary register writes.
The physical Raphael BARs are never exposed through this client.

The VNC profile selects `VM_CONSOLE=bochs` alongside `GENERIC_GRAPHICS=off`: the exact
Bochs device at guest slot7 and Unix socket `/run/vm/console-vnc.sock` are verified
in the running argv. Existing no-console experiments retain their exact contracts.
Slot6 remains Raphael. All GPU ownership, deadlines, capture and recovery checks
remain required. No existing hashed design contract is changed.

## Qualification sequence

1. Stock-QEMU software-only transport: exact BGR/RGB pixels, changing frames,
   stride and resize. `tools/qemu-console-smoke.py` passed on QEMU11.1.1, checking
   1,094,400 pixels at640×480 and800×600. This opens no physical GPU.
2. Guest bridge enumeration and bounded memory/mode requests; reject invalid
   geometry, mismatched hardware and concurrent ownership.
3. Fresh Raphael Metal probe plus WindowServer device identity, virtual-display
   identity, complete capture frames and independent QEMU console screenshots.
4. Moving desktop, QEMU mouse/keyboard input, clean logout/login persistence and
   resize. Capture throughput and latency separately from advertised refresh.
5. libvirt/virt-manager lifecycle integration, preserving one-way VFIO binding
   (`managed=no`) and identity-bound cleanup. Then other QEMU frontends.

## Hypervisor boundaries

QEMU and libvirt can expose a physical PCI device and a separate console device.
Candidates341–347 test native accelerated macOS through virt-manager, including
native guest-shutdown terminal receipts on343 and347. Broader lifecycle coverage remains open.
VirtualBox7.2.18 is installed on this host, but upstream removed Linux PCI
passthrough in6.1; its normal macOS virtual display is not a Raphael GPU.
Supporting VirtualBox would require a different GPU transport/driver or restoring
suitable passthrough in the hypervisor. This project cannot promise it through a
configuration option or its existing Radeon patch alone.

Sources: [QEMU Bochs implementation](https://gitlab.com/qemu-project/qemu/-/blob/v10.1.2/hw/display/bochs-display.c),
[libvirt domain format](https://libvirt.org/formatdomain.html),
[VirtualBox PCI passthrough removal](https://forum.virtualbox.org/wiki/Changelog-6.1).

## Window launcher and current hardware evidence (October8)

Set `RUN_RESULTS` to the active experiment results directory. From the Linux
desktop session, open that supervised VM with:

```sh
python3 tools/console-window.py --state "$RUN_RESULTS/supervision.json"
```

This connects TigerVNC to QEMU's presentation socket. It verifies the exact running
container/start time and console selection. Closing the viewer disconnects the
window only; the experiment supervisor still owns shutdown and recovery.
The presenter follows guest mode changes. Automatic host-window resize requests
remain disabled until they can be coordinated with macOS mode selection. This is QEMU's VM console, not macOS Screen Sharing.

`tools/console-metal-probe.m` generates three1280×720 color-bar phases on Raphael,
checks921,600 pixels per phase, then copies the verified buffer into Bochs VRAM.
Candidate333 run `a7fa79a29559deb6a80bedfb6ac658b1` completed all three phases.
Independent QEMU screenshots of phases0 and2 each match all921,600 pixels.
This demonstrates Metal-to-console presentation, not a captured desktop or
measured frame rate. The viewer connected successfully on the Linux desktop.

The CGVirtualDisplay helper creates1920×1080 logical/3840×2160 backing pixels.
`console-presenter` additionally requires macOS Screen & System Audio Recording
permission. The initial333 executable was denied with-3801. Normal guest settings
resolved it; the packaged app now uses org.raphaelgpu.console and permission
survived the next guest boot. See the installer below.

Desktop capture, main-display selection and mouse/keyboard mapping pass on336.
Remaining: resize coordination, measured performance and broader cleanup coverage.
VirtualBox support remains a separate unimplemented transport problem.

## Install the guest console desktop

Copy these files into one directory in the macOS guest: `install-console-desktop.sh`,
`console-presenter.m`, `console-display-layout.m`, and `virtual-display-server.m`.
With Command Line Tools installed, run as the logged-in user:

```sh
bash install-console-desktop.sh
launchctl bootstrap gui/$(id -u) "$HOME/Library/LaunchAgents/org.raphaelgpu.console.plist"
```

Enable **Raphael Console** in Privacy & Security → Screen & System Audio Recording.
If the initial start exited before consent, restart it with:

```sh
launchctl kickstart gui/$(id -u)/org.raphaelgpu.console
```

The installer builds an ad-hoc-signed app under `~/Applications` and a user
LaunchAgent. It runs only when the Bochs `RaphaelConsole` service exists, creates
the virtual display, mirrors the other guest displays to it for correct absolute
input mapping, and starts the presenter. This session-only layout resets when
its virtual display disappears. The launcher holds display-awake assertions.
Each presentation session is bounded to6000seconds for experimentation; this
is not yet an unlimited daily-use service. Logs are under
`~/Library/Application Support/RaphaelGPU/console/`. Ad-hoc app rebuilds may need
renewed macOS consent; release signing remains future work.

The host still launches and owns the VM through the experiment harness. Installing
these guest helpers does not transfer lifecycle ownership to a GUI, reset the GPU,
or permit concurrent VM-manager launches. A full libvirt lifecycle integration
remains required before managing this VM directly through virt-manager.

## Candidate338 helper follow-up

The presenter now subscribes to display changes, updates ScreenCaptureKit output
size, and programs the console only after a complete frame matches that size.
Guest native1080p and1080HiDPI transitions have observed matching QEMU frame sizes.
This is guest-driven mode following, not automatic resizing when a host window
is dragged. A720HiDPI request settled to native720p and remains unqualified.

The installer selects `RGPU_CONSOLE_CACHE=wc` for the Bochs framebuffer only.
`default` remains available for comparison. Sampled4K lock/copy times fell from
about86ms to12–15ms. The reported `copied_fps` counts ScreenCaptureKit frames copied
to console memory, not viewer delivery or display refresh. Static content and
other capture clients affect it. A later final-helper workload measured only
8–9 copied fps; a fresh guest repeat reaches10–16 copied fps during moving content.
Overall throughput is unresolved. Current single-buffer copies are not atomic
frame presentation and may tear; frame pacing and end-to-end latency remain open.

When replacing this ad-hoc-signed executable, stale capture consent may still
appear enabled. If necessary, reset only this app's permission with
`tccutil reset ScreenCapture org.raphaelgpu.console`, then add the new
`~/Applications/Raphael Console.app` in Screen & System Audio Recording.
An unchanged installed app retained consent across the tested guest boot.

Sources: [Apple mode-selection lifetime](https://developer.apple.com/documentation/coregraphics/cgdisplaysetdisplaymode(_:_:_:)),
[ScreenCaptureKit configuration updates](https://developer.apple.com/documentation/screencapturekit/scstream/updateconfiguration(_:completionhandler:)),
and [XNU user-mapping options](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/iokit/Kernel/IOUserClient.cpp#L2047).

## SPICE and post-resume initialization (October9)

Candidate340 renders the native accelerated1080HiDPI desktop through the exact
`VM_CONSOLE=bochs-spice` profile. Use the supervised SPICE viewer:

```sh
python3 tools/console-spice-window.py --state "$RUN_RESULTS/supervision.json"
```

This requires GTK3 and the SpiceClientGLib2.0 and SpiceClientGtk3.0 introspection bindings.
The only display endpoint is a user-owned local Unix socket; network SPICE, GL,
clipboard sharing, USB redirection and guest resize are disabled. Existing USB
sound uses the established PulseAudio path; SPICE audio is disabled. The viewer
focuses its display widget. Closing it leaves the VM under harness ownership.

Native Metal/WindowServer ownership,3840×2160 desktop output, keyboard modifiers
and mouse coordinates pass. A180-second moving-material workload completes2,066
event iterations. These are functional observations, not60fps console delivery.
Clean guest shutdown and ordinary native recovery succeed on two340 runs.
The repeat automatically restores the approved presenter and HiDPI desktop.

The `rgpuconsolecold=1` opt-in handles only reset-held, entirely empty executable
firmware windows with validated memory ranges and successful native allocator
accounting. It retains immediate pre-PSP checks and does not start DMCUB. This
is not general host suspend/resume qualification. Other firmware states retain
the established guarded path or refuse. See
[driver evidence](../findings/research/console-empty-firmware-20261009.md) and
[input/capture artifact hashes](../findings/research/console-spice-native-evidence-20261009.json).

## Native virt-manager result (October9)

Candidate341d launches one transient native macOS domain through a private libvirt
session, paused until the host verifies identity, inherited macvtap and capture
readiness. The actual virt-manager5.1.0 console renders the accelerated desktop.
Exact keyboard text and field-local mouse coordinates pass through the manager;
closing its window leaves the same container/domain running. Domain XML before
and after connection is identical. LAN packets reach the gateway through en2.

The outer harness records valid capture, guest-request exit and authorizing GPU
recovery. However, critical serial EOF invokes its container stop guard before
libvirt persists terminal.json. This historical result is not a natural
controller-exit pass; candidate343 below supersedes the missing-receipt blocker. A global capabilities warning also exposes inherited PATH
shim contamination; candidate342 fixes that discovery in isolated daemon tests.
GNOME Boxes has only software-pattern evidence and may rewrite imported domains;
do not substitute that for a native Boxes qualification.

System Information shows two devices: AMD Radeon Navi23 reports2GB and performs
native Metal work; QEMU's1234:1111 Display reports56MB of presentation framebuffer.
That56MB is not the renderer's memory limit. System Information's console mode
metadata can differ from the presenter's measured3840×2160 pixels; neither proves
refresh-rate delivery. The180-second workload's2,386 iterations are AppKit events,
not viewer frames. [Evidence and limits](../findings/research/libvirt-native-console-20261009.md).

## Measured manager-buffer delivery (candidate342)

The in-process sampler reads the actual virt-manager SpiceDisplay buffer; it
opens no second SPICE connection. Fixed-mode30-second observations:

| Mode | Unique valid tokens | Sampled updates/s | Median sample cost | Invalid token samples after first valid |
|---|---:|---:|---:|---:|
| Native1920×1080 |895|29.82|2.24ms|8|
| 1080HiDPI /3840×2160 |555|18.50|5.28ms|18|

These are sampled lower bounds, not GPU fps, complete delivered-frame accounting,
host scanout or absolute latency. Invalid cell/checksum samples demonstrate that
complete atomic tokens are not guaranteed. Both60-second guest fixtures finish
and normal desktop rendering returns. The native capabilities warning is fixed;
on342 controller EOF grace refuses and loses terminal.json, while outer capture,
guest-request exit and GPU recovery pass. A failed automatic storage-pool setup
is also retained in the manager logs; it does not rewrite the guest domain.
[Raw outcome, limits and next tests](../findings/research/console-cadence-20261009.md).

## Native terminal receipt (candidate343)

Candidate343 closes the missing receipt case on one native guest shutdown.
Omitting unused container SSH allows strict exited-QEMU inspection to complete;
both EOF handlers record natural-container-exit and the actual controller writes
its bound guest-shutdown terminal.json. Capture and authorizing GPU recovery
pass. Guest SSH still answers through QEMU's independent forwarded port.
No process-visibility check, original deadline or live-QEMU immediate-stop path
is relaxed. Native crash/forced-closure and independent-boot coverage remain open.
[Result and exact artifacts](../findings/research/libvirt-native-terminal-20261009.md).

## Experimental refresh result (candidate345)

An opt-in QEMU nongl refresh patch increases sampled actual-manager delivery to
49.993updates/s at1080p and22.529 at1080HiDPI. Full-pixbuf observation costs
2.257/5.330ms and incomplete token samples remain; these rates are not GPU fps.
The normal desktop returns and capture/GPU recovery pass. Native terminal.json
is lost when the strict exit checker encounters QEMU already in stateZ. That
reaping timing remains a lifecycle blocker despite343's successful shutdown.
Default pins remain stock; use `experiments/pins-spice60.json` for this experiment.
[Results, exact artifacts and limits](../findings/research/native-refresh-20261009.md).

## Candidate347 paired observer and lifecycle result

The actual manager accepts the optional checked ROI observer. Fresh30-second
full/ROI samples observe30.497/30.323updates/s at native1080p and19.664/25.198
at1080HiDPI. Median sampling cost drops from2.228to1.363ms and5.222to1.452ms.
This measures observer impact in one sequential pair; partial tokens remain,
and345's50updates/s native result is not reproduced. These are not GPU fps,
complete-frame throughput or scanout. Default observer remains full pixbuf.

The normal desktop returns and actual controller guest-shutdown/process-exit
receipt, natural container exit, valid capture and authorizing GPU recovery pass.
The new completed-zombie path is software-tested but not exercised in this run:
both native hooks observe QEMU already reaped. Broader lifecycle remains open.
The subsequent351–353 experiments split that combined HiDPI lock/copy interval.
[Full results and artifacts](../findings/research/console-roi-native-20261009.md).

## Same-image full-refresh OFF/ON comparison (353/352)

The same experimental QEMU image, approved O2 presenter, explicitSPICE60 and
30-second actual virt-manager sampling protocol are used with the diagnostic
Bochs property absent (OFF,353) or on (352). Default image pins remain unchanged.

| Case | OFF updates/s | ON updates/s | OFF / ON QEMU CPU cores |
|---|---:|---:|---:|
| Native1080p, full observer |49.918|44.186|0.956 /0.751|
| Native1080p, ROI observer |49.188|50.084|0.689 /0.515|
| 1080HiDPI, full observer |23.531|31.758|0.803 /0.465|
| 1080HiDPI, ROI observer |22.363|34.882|0.725 /0.453|

Selected steady guest row-copy windows fall from about16ms to1.5ms atHiDPI.
These windows are not precisely aligned with the viewer sampling interval.
Full refresh disables only Bochs VGA dirty tracking and updates the whole surface
at each existing refresh; migration logging remains intact. It can increase
static display work, so measured QEMU-process savings do not establish total
host CPU savings. The whole QEMU process includes vCPU and display threads;
manager CPU is excluded. This is one sequential same-host-boot comparison,
not independent repeats. Producer draw cadence varies and does not sustain60/s.

Updates count valid sampled token regions, not complete frames, GPU fps or
scanout. Invalid token samples remain in every case.352 and353 have valid capture and
authorizing recovery, but strict EOF inspection catches an original zombie with
a remaining task and the native controller terminal receipt is missing. Earlier
343/347 clean shutdowns do not close this race. Broader crash/reconnect, resize,
console audio and other-manager qualification remain separate.
[Exact artifacts, copy timings and lifecycle scope](../findings/research/bochs-full-refresh-paired-20261009.md).


## Native reset shutdown and viewport input (356)

Candidate356 preserves the critical collector's recv-reset104 error separately
from console clean EOF. Both capture hooks find the original QEMU process already
reaped and observe natural container exit in about0.373s. The actual controller
terminal reports guest-shutdown and process_exited=true; final critical bytes/hash
match the quiesce ACK, CORE_PROBE_PASS is valid and GPU recovery authorizes reuse.
The new event-bound pending-worker wait is **not** exercised by these native hooks.
An independent task watcher sees a transient zombie leader with a live KVM worker;
that observation does not establish which branch the hooks took.

| Actual virt-manager viewport | Input result |
| --- | --- |
| Normal1288×909 | Five corner/center targets and exact keyboard token pass; zero misses. |
| Fullscreen1920×1080 | Five targets and exact token pass; zero misses. |
| Small1000×760 after resizing | Two initial clicks arrive at the prior guest center; all targets/token later delivered after pointer reentry/motion. Retained as failed. |

The guest stays at1920×1080 logical with backing scale2 throughout. This proves
neither automatic guest-mode resize nor a repaired coordinate transition. The
small-window cause remains undetermined; automation motion/enter and viewer state
need discrimination. Closing the viewer preserves the exact VM and reopening
shows the desktop. Console USB audio and other-manager qualification remain open.
[Run identity, artifacts and limits](../findings/research/libvirt-reset-native-20261009.md).
