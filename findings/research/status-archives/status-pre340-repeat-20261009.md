# Live status — 2026-10-09

## Candidate340: native accelerated SPICE desktop after host resume

Run `892ec42661ae367e299f60d55c9da9ee`, metal-186, build1.0.340,
same bootba51b3c6, MODE2#276. The opt-in empty-firmware path verifies reset-held
empty code windows, native memory accounting and the pre-PSP guard. Native desktop
Metal passes, with WindowServer accelerator ownership. SPICE shows3840×2160
pixels/1080HiDPI; a180-second material workload completes2,066 event iterations.
Separate SPICE input checks receive exact text RGPU336 and a click at(295,130)
inside the test field. Guest display/system awake assertions remain active.
Copied-frame samples are not viewer fps; performance remains open.

Capture: valid CORE_PROBE_PASS, no earliest failure. Shutdown:
exited-after-guest-request. Ordinary native recovery: authorizes_launch=true.
VM stopped; no reboot/rebind. Results: candidate-340-results. The real host
sleep:idle inhibitor remains active across development. The next run repeats
this build on the same boot after tightening the harness to require both scopes;
full VM-manager lifecycle integration remains unqualified.
[Evidence](findings/research/console-spice-native-evidence-20261009.json) ·
[Driver scope](findings/research/console-empty-firmware-20261009.md).

## Candidate339 SPICE transport: desktop visible; native init refused after resume

Run `74b5d9f71656c2d3492fd0972bc7c2a1`, metal-185, unchanged336 driver,
339 harness, same bootba51b3c6. SPICE client captures the3840×2160 desktop and
awake assertions pass. This does not establish accelerated output: HOSTRESERVE
refuses DMCUB boot=0, CNTL=0, processor reset=1, interface control=0. Native PSP
TMR replacement remains correctly blocked. No native Metal probe runs.
The attempted moving-material workload did not start (nohup console-detach error).

Capture is complete but verdict INVALID/recovery_lease_pool_missing; native
ownership was never published. Explicit identity-bound guest shutdown returns
exited-after-guest-request (`c339-explicit-guest-shutdown.json`); the runner then
records already-stopped. Ordinary lease recovery refuses the missing record.
Supported no-queue recovery succeeds with authorizes_launch=true, no kernel
faults (`c336-e-noqueue-recovery.json`). VM stopped; no reboot or rebind.
Results: `candidate-336-attempt-e-results`; images `c339-guest-spice-desktop.png`.

The first preparation failed after MODE2#274 because the attempt artifact copy
was absent, before QEMU/VFIO exposure; no launch was recorded. The corrected
attempt uses MODE2#275. The host had resumed from KDE suspend at08:35 EEST.
A verified session-wide sleep:idle inhibitor now spans development. Next: inspect
the stopped firmware/windows and source-supported handling of post-suspend state;
do not relax memory reservation or the immediate pre-PSP held-reset proof.
[Investigation](findings/research/console-spice-manager-20261009.md).

## Candidate338 helpers on336: console mode following; throughput open

Latest run `89af08fc3479528d08a7ef7bea0d0956` (metal-184, same host bootba51b3c6)
automatically restores the approved presenter, virtual display and awake assertion.
An uninterrupted three-minute moving-material test completes2,061 event iterations.
Active five-second samples report10.12–16.09 copied fps (median11.095); these are
ScreenCaptureKit-to-memory counts, not viewer fps. Full-rate delivery is unqualified.

The preceding336c run verifies native1080p/1080HiDPI mode following and QEMU
keyboard input with Shift. Explicit write combining passes independent GPU color
bars and1,843,200 QEMU pixel comparisons. Isolated memory copies improve, but a
late-session workload fell to8–9 copied fps; its cause remains unresolved.
A720HiDPI request settled to native720p and is not qualified as HiDPI.

Capture: valid CORE_PROBE_PASS. Shutdown: exited-after-guest-request.
Automatic recovery refused because the separate software-only libvirt test QEMU
was still active. After stopping it, the ordinary native-lease recovery path
succeeds: recovered, authorizes_launch=true. Original refusal remains unchanged.
Retry receipt: `~/macos-vm/run/c336-d-native-recovery-retry.json` (also registered
under run/vfio-recovery for the exact latest run). A generic legacy CLI attempt
before the correct native retry refused its nonce check and is not GPU-failure evidence.
Results: `candidate-336-attempt-d-results`; hardware VM stopped. No reboot/rebind.

[Helper tests and limits](findings/research/console-resize-copy-20261008.md).

## Candidate336: accelerated macOS in a QEMU window

Run `201412ad0f4bafdc61ad3dde81d38037`, metal-184, host bootba51b3c6.
Native desktop Metal probe passes with WindowServer accelerator ownership.
QEMU's own console shows the virtual desktop at1920×1080 logical/3840×2160 pixels,
including application windows, menu bar and Dock. Mouse clicks and keyboard input
with Shift pass through QEMU's input path. Display-awake assertions are verified.

Normal System Settings UI granted Screen Recording to the presenter, then the
packaged org.raphaelgpu.console app. The installed user LaunchAgent creates the
virtual display, makes it primary, and starts capture on console-enabled profiles.
Repeat run `a4b743f14436d22521c6e627ab20476c` automatically restored the desktop
and retained capture permission at login. A three-minute material-window workload
completed 2,062 event-loop iterations; sampled QEMU captures show rendered effects
and capture continued. This does not measure delivered frame rate or prove tear-free output.
Both336 runs shut down through the guest and recovered with authorizing receipts.
Latest results: `candidate-336-attempt-b-results`; VM stopped. The helpers remain
bounded to6000seconds; sustained performance, resize, arbitrary VM managers and
unlimited daily use are not qualified.

Capture artifacts: ~/macos-vm/run/c336-desktop-main.ppm,
c336-qemu-input-menu.png, c336-qemu-keyboard-shift.png,
c336-input-and-capture-result.txt and c336-packaged-desktop.ppm.
The harness reports valid CORE_PROBE_PASS. Shutdown: exited-after-guest-request.
Recovery: recovered, authorizes_launch=true. Results: candidate-336-results.

Restart corrections preserve mandatory reservation and immediate pre-PSP DMCUB
reset/disable proof.335 verifies disable under existing reset;336 retires validated
stale guest mailbox ranges while retaining secure firmware storage.333c/334/335
refused safely and recovered through the supported no-queue path. The original
332 host-hang build remains withdrawn. No host reboot or amdgpu rebind occurred.

[Console setup](docs/virtual-console.md) ·
[Prior investigation status](findings/research/status-archives/status-before-console-desktop-20261008.md).

## Candidate330: correct HiDPI120 picture and HDMI audio

The user confirms correct colors and audible audio through the Samsung Odyssey
G95NC headphone/audio output. Awake macOS reports 1920×1080 logical / 3840×2160
pixels at 120 Hz. Audio device identity, default routing and successful playback
survive the tested HiDPI 120→60→120 switches without rerouting.

- Build: 1.0.330, source `933d60d9535cbfc7fea8f0709c29b4e502b54cef`, metal-178.
- Executable SHA-256: `20a1e10a123d42e89442e7e0ca096aef180e50c60c575bdbd50b7c1a4bc6235c`.
- Run: `433b6f803c826755d20396e08a011a2a`; artifacts: `~/macos-vm/run/candidate-330-results/`.
- Capture/identity: valid `CORE_PROBE_PASS`; no guest panic or DMUB delivery timeout.
- Shutdown: `exited-after-guest-request`; GPU recovered with `authorizes_launch=true`.
- Audio teardown: PCI command 2, bus mastering/DMA disabled, no errors.
- Host kernel capture: networking/firewall messages only; no recorded GPU/host fault.
- Final state: VM stopped; both functions remain on vfio-pci. No reboot or rebind.

The September publication on main contains the tested330 build. The current dev
binary is336, tested on the console path; its physical HDMI path has not been
independently rerun. That end-of-day stop is historical; work resumed on October5.

Logs are not error-free: startup CAIL, DMUB capability-query and early GFXHDA
assertions remain, as do recurring PSP/HDCP status 4 errors. The FRL audio
framebuffer-event assertion is absent on330. Protected-content playback, arbitrary
hotplug/sleep, independent-host-boot durability and broader desktop qualification
remain open; the tested picture/audio path has no remaining observed blocker.

[Setup](docs/hdmi-status.md) ·
[Investigation and scope](findings/research/hdmi-hidpi120-20260924.md) ·
[Artifact hashes](findings/research/hdmi-hidpi120-evidence-20260924.json) ·
[Prior live status](findings/research/status-archives/status-before-hidpi120-audio-20260924.md).

## Verified progress

| Area | Evidence and scope |
|---|---|
| Managed texture ownership | 96 cases;111,658,032 pixel comparisons; synchronized CPU writes and retained LOAD color contents, zero mismatches |
| Cross-process GPU events | Typed XPC import;33 consumer-first transfers,25,453,131 correct pixels |
| Two-process IOSurface | 32 bidirectional GPU-copy rounds;49,363,648 pixels, zero mismatches; host completion orders transfers |
| Depth/stencil/MSAA | 128 cases at1×/4× and64×64/1003×769;49,625,792 correct pixels |
| Main10 decode | 32 frames, 720p/1080p, 71,884,800 full-plane luma/chroma samples, exact software-reference match |
| Buffer/address reuse | 512 measured rounds, 2,147,483,648 correct values; all 6,144 measured address assignments reused earlier ranges; allocation returns exactly to 544,768 bytes |
| Larger allocations | 192 MiB live resources, four measured rounds, 67,108,864 correct values, exact allocation return |
| Native reclaim | 81 traced calls: 41 true, 40 false; all 40 false returns followed by same-thread/map success; 1,525 internal wire failures observed |
| GPU fences | 128 untracked blit/compute/blit rounds, 134,217,728 correct values; prior cross-queue shared-event checks also pass |
| Native desktop | Three minutes of moving/resizing native material windows; four clean raw RFB captures |
| Safari | Two-minute transparency/blur/scrolling page; three clean captures plus clean desktop after larger-buffer pressure |
| Stock QEMU / PerfPowerServices | OpenCore/VirtualSMC fix passes two guest boots,0.0% CPU, latest0.86s; prior patched-QEMU evidence retained separately |
| Host regression | 1028 tests OK, three skipped |

Earlier texture recreation (144 cases / 131,031,576 pixels), feedback rendering
(48 cases / 5,280,000 pixels), and hardware H.264/HEVC encode/decode retain their
separately documented passing scopes. Explicit decoder GPU-ID selection remains
a selection limitation on the built-in topology; automatic required-hardware selection works.

Prior qualified280 driver build `51bfd732cf824249b70981f0c36fe314`; executable SHA256
`7d06082f35959f900b5c59cb5f6d9e2efc67df13e935d338d7783524df63259b`.
Current stock QEMU image `sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c`.
Default experiment pin now selects this stock image. VirtualSMC1.3.7/gen2 and the
exact OpenCore DSDT ownership patch are required; prior media backups remain available.
[Address/desktop qualification](findings/research/address-reclaim-desktop-20260916.md),
[artifact hashes](findings/research/address-reclaim-desktop-evidence-20260916.json),
[native retry analysis](findings/research/allocation-retry-analysis-20260916.md),
[visual fix](findings/research/feedback-decompression-20260916.md).


## Remaining roadmap

1. QEMU console resize, measured frame pacing/input latency, and supervised
   libvirt/virt-manager integration. Automatic guest-login startup passes one repeat.
   Sustained4K remote delivery and input latency; preserve crisp Retina60Hz,
   then qualify login persistence. Remote90/120Hz delivery remains unproven;
   physical Samsung HiDPI120 now works.
2. Guest-crash/command-channel failure, repeated lifecycle and independent-host-boot
   qualification. Existing clean stops do not qualify every failure mode.
3. Broader applications, render hazards, interprocess synchronization and page-table
   release. Historical direct OpenGL hang and live Metal validation crash remain open.
4. HDCP, DisplayPort, broader monitors, other hypervisors and measured
   performance/release qualification. Samsung HDMI picture/audio have scoped passes.

StockQEMU10.1.2/OpenCore/VirtualSMC1.3.7 works in this tested setup;
PerfPowerServices was0.0% CPU on two guest boots. Automatic required-hardware HEVC
decode works; explicit GPU-ID selection remains limited. Main10 decode has scoped
passes; hardware encode is Main8. [Roadmap](docs/ROADMAP.md).


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-336-attempt-e-results`
- Verdict: `INVALID`
- Boundary: `recovery_lease_pool_missing`


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-340-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
