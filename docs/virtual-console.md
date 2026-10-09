# Accelerated desktop in a VM manager console

The requested target is a macOS desktop in the VM manager's console, with Raphael
Metal rendering and no physical HDMI connection. Screen Sharing/Moonlight alone
does not meet that target. Native Metal/WindowServer ownership, real virt-manager
mouse/keyboard input and bridged LAN traffic pass. The same-image353 OFF/352 ON
comparison improves sampled1080HiDPI delivery from22–24 to32–35updates/s with an
opt-in Bochs full-refresh property; native1080p does not improve uniformly.
Candidate356 completes native reset shutdown with a real controller terminal
and authorizing recovery. Candidate364 exercises the bounded shutdown-wait branch
in both hooks before natural exit; broader lifecycle coverage remains open.
Normal/fullscreen input pass. Candidate361 also passes continuous pointer entry
into1000×760; earlier enter-without-motion failures remain distinct.
Partial-region samples, automatic resize, other frontends and VirtualBox remain
open. This is not qualified60Hz delivery.
[Current paired evidence](../findings/research/bochs-full-refresh-paired-20261009.md).
Candidate361 verifies ordinary afplay default USB audio through QEMU/Pulse with
isolated stereo capture and exact route restoration; endpoint audibility, other
applications and A/V synchronization remain unqualified. Candidate366 retains existing-user startup and consent on the next guest boot;
its paced source reaches60 draw calls/s without qualified60Hz output.
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

Use the source ZIP produced by `tools/package-console-helpers.py`: installer,
transaction coordinator, three Objective-C sources, notes and hash manifest.
See [package requirements and recovery](console-helper-install.md).
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
or permit concurrent VM-manager launches. The tested private libvirt integration
retains harness ownership; arbitrary GUI lifecycle actions remain unqualified.

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
shows the desktop. Console USB audio was still unqualified in356; the scoped358
result follows below. Other-manager qualification remains open.
[Run identity, artifacts and limits](../findings/research/libvirt-reset-native-20261009.md).


## Explicit console audio and first pointer entry (358)

The exact QEMU USB HAL device delivers a bounded stereo tone through QEMU's
Pulse output. An owned null sink captures only that VM stream; measured left
997.14Hz and right1498.57Hz, channel separation and silence pass. The original
stream route, volume/mute and defaults are restored, and the owned sink/module
are removed; a separate read-only verification confirms restoration. SPICE audio
remains disabled. This proves explicit-device sample delivery, not ordinary
application default output, endpoint audibility or the separate330 HDMI path.

The first host controller attempt failed before mutation because Pulse JSON
module entries lacked indices. The corrected inventory parser uses authoritative
short-list IDs, preserving multiline arguments and refusing malformed/ambiguous
records. The successful host tool is separately identified as547c6b3.

The1000×760 input fixture later passes all five targets and its token, but an
earlier enter+button without motion opens the guest Apple menu outside the
fixture. Its passed=true result therefore does **not** qualify the full resize
transition. Actual motion restores correct coordinate mapping. Stock spice-gtk0.42
source supports this event-order mechanism; continuous pointer entry and
resize under a stationary pointer remain separate discriminators.

Capture is CORE_PROBE_PASS; genuine guest-shutdown/process-exited terminal and
authorizing GPU recovery both pass. No pending-worker native qualification or
broader crash-lifecycle result is inferred from this run.
[Identity and hashed evidence](../findings/research/console-audio-native-20261009.md).


## Default application audio and continuous entry (361)

Ordinary `/usr/bin/afplay`, without device selection or a custom HAL callback,
plays a bounded stereo WAV through the existing default QEMU USB output. Isolated
VM-only Pulse capture passes997.11Hz left/1498.53Hz right, both-channel phase,
silence and clipping checks. Guest default/system output stay unchanged; exact
host route, volume/mute/defaults and owned sink/module removal are independently
verified. The guest's device label `Audio Output - Disabled` does not describe
this measured behavior. Endpoint audibility, other applications and A/V sync
remain unqualified; SPICE audio remains off and HDMI330 is separate.

After a real virt-manager resize1288×909→1000×760, continuous relative pointer
entry produces GTK motion before the first guest click. Five targets and exact
keyboard token pass with zero misses and no guest mode changes (1080HiDPI).
This is a positive control for continuous entry, not a fix for358's enter/button
without motion. Stationary-pointer resize, all input backends and automatic guest
resolution following remain open. No driver/viewer patch was applied.

CORE_PROBE_PASS, genuine guest-shutdown/process-exited terminal and authorizing
recovery pass. Both hooks complete naturally in about0.394s, preserving critical
recv-reset versus console clean EOF. They find completed process state; the
pending-worker event wait was still native-unexercised in361;364 follows below.
The next planned qualification was
reproducible optimized helper installation, first use/second boot and rollback.
[Exact identities and hashed artifacts](../findings/research/console-default-audio-input-20261009.md).


## Existing-user installer and bounded shutdown wait (364)

The source package compiles/signs all three helpers with O2 in macOS, verifies
signatures and records provenance before publication. Active-session installation
refuses without target changes. Sixteen transaction tests pass using disposable
macOS directories, including interruption/recovery and exclusive renames; this is
not power-loss testing of the actual installed app.

The changed ad-hoc app initially receives TCC-3801. Normal System Settings consent
renewal restores actual capture; the transient stale/corrupt framebuffer during
permission failure remains a user-facing limitation. Identical-package reinstall
produces the same complete app, three binaries and CDHash, and restarts without
renewal. Correct desktop and default afplay stereo/restoration pass. Input is not
rerun. Next guest boot was unqualified in364;366 supplies the scoped result below.
Fresh-user and unattended deployment remain unqualified.

Both native capture receipts record shutdown_event_wait=true, then natural exit
in about0.411s. Bound guest SHUTDOWN precedes the distinct recv-reset/clean-EOF
boundaries by1.25/1.29ms. Genuine guest-shutdown/process-exited terminal and GPU
recovery authorize reuse. This supersedes the earlier native-unexercised limit:
one positive branch exercise, with initial task IDs not separately retained,
is not universal race closure or repeated lifecycle qualification.
[Exact run and50 hashed artifacts](../findings/research/console-install-native-20261009.md).


## Next guest boot and source-cadence ABBA (366)

The existing installed console app automatically starts on the next guest boot,
with unchanged presenter hash and fresh3840×2160 capture without another consent
change. Awake assertions and final actual-manager desktop screenshot pass. This is
existing-user guest-boot persistence, not independent host boot, fresh-user consent
or console-only setup. Audio and input are not rerun.

At1080HiDPI, installed presenter/full-refreshON/SPICE60 and the manager ROI observer
stay constant. Four70s source runs each supply a30s analyzed observer interval:

| Source order | Draw calls/s | Valid unique manager IDs/s | Invalid/samples |
| --- | ---: | ---: | ---: |
| Baseline A |33.063|23.633|336/1816|
| Prerendered B |60.000|35.300|442/1550|
| Prerendered C |60.001|24.900|959/1756|
| Baseline D |53.647|25.967|826/1784|

Pre-rendering/display-link pacing changes source supply, but repeat variation and
partial tokens prevent a stable speedup or60Hz claim. DRAW records drawing calls,
not completed composition; manager sampling is a buffer-region lower bound, not
GPU FPS or scanout. Presenter tail timing is not aligned to this analyzed window.
Next inspect actual readonly SCK source nonce/CRC before normal VRAM writes to
separate source validity from downstream candidates.

Capture CORE_PROBE_PASS, genuine guest-shutdown terminal and authorizing recovery
pass. Both hooks finish naturally about0.451s with shutdown_event_wait=false;
this does not repeat364's pending-worker branch exercise.
[Exact artifacts and scope](../findings/research/console-cadence-native-20261009.md).


## Capture-source token diagnostic (368 native result)

An opt-in `RGPU_CONSOLE_TOKEN_NONCE` (exact16hex) checks the two matching token
regions directly in each processed, readonly-locked ScreenCaptureKit source
before normal framebuffer copying. It waits up to60s for the first valid token,
then counts a fixed30s window, including invalid and duplicate processed samples.
No full-frame copy or transport change is introduced. Busy-dropped callbacks,
upstream uncaptured frames, destination correctness and scanout are outside scope.
An invalid source sample does not stop or change ordinary presentation.

Candidate368 compiles and installs this diagnostic natively; changed ad-hoc signing
requires normal Screen Recording renewal. Complete 30-second windows have 1,742/1,742
HiDPI and 1,738/1,738 native valid processed source samples. The manager still sees
633/1,065 and 35/1,116 invalid samples inside intervals bracketed by valid interior
source IDs. Corrupted manager IDs are not trusted; clocks are not synchronized.
This narrows beyond the checked source regions, without identifying one downstream
stage, proving source stability after checking, or establishing whole-frame atomicity.
Both runs restore the original LaunchAgent and ordinary capture; final manager
desktop, guest shutdown and recovery pass. Audio/input are not rerun.
[Native result and limitations](../findings/research/console-source-token-native-20261009.md)
· [Timing and error categories](../findings/research/console-source-token-plan-20261009.md).
