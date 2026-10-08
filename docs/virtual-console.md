# Accelerated desktop in a VM manager console

The requested target is a macOS desktop in the VM manager's console, with Raphael
Metal rendering and no physical HDMI connection. Screen Sharing/Moonlight alone
does not meet that target. Candidate336 now presents the accelerated desktop through QEMU's console at
1920×1080 logical /3840×2160 backing pixels. Native Metal readbacks and
WindowServer accelerator ownership pass. QEMU-console mouse clicks and keyboard
input (including Shift) work. This is a scoped QEMU result: sustained frame rate,
automatic resize, other frontends and VirtualBox are not qualified.
[Run evidence and limitations](../findings/research/virtual-console-20261008.md).
Candidate332's unsafe TMR experiment remains withdrawn.

## Architecture under test

Raphael VFIO remains the renderer. A guest CGVirtualDisplay supplies a desktop;
ScreenCaptureKit copies complete BGRA frames to a separate presentation-only
`bochs-display` PCI device. Stock QEMU presents that device through its ordinary
VNC/SPICE/GTK console; input uses QEMU's existing USB keyboard/tablet. This adds
CPU framebuffer copies, not a second 3D renderer. Throughput and latency need
measurement, especially at HiDPI resolutions.

The opt-in `rgpuconsole=1` service matches only QEMU 1234:1111, class 038000,
checks its VBE identity and bounded BARs, and never enables bus mastering. Only
local users can open its exclusive client. Userspace maps only the presentation
VRAM; mode-setting accepts bounded geometry, not arbitrary register writes.
The physical Raphael BARs are never exposed through this client.

The harness selects `VM_CONSOLE=bochs` alongside `GENERIC_GRAPHICS=off`: the exact
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
Their configuration support is not yet a tested macOS lifecycle result.
VirtualBox7.2.18 is installed on this host, but upstream removed Linux PCI
passthrough in6.1; its normal macOS virtual display is not a Raphael GPU.
Supporting VirtualBox would require a different GPU transport/driver or restoring
suitable passthrough in the hypervisor. This project cannot promise it through a
configuration option or its existing Radeon patch alone.

Sources: [QEMU Bochs implementation](https://gitlab.com/qemu-project/qemu/-/blob/v10.1.2/hw/display/bochs-display.c),
[libvirt domain format](https://libvirt.org/formatdomain.html),
[VirtualBox PCI passthrough removal](https://forum.virtualbox.org/wiki/Changelog-6.1).

## Window launcher and current hardware evidence (October8)

From the Linux desktop session, open the active supervised VM with:

```sh
python3 tools/console-window.py --state ~/macos-vm/run/candidate-333-attempt-b-results/supervision.json
```

This connects TigerVNC to QEMU's presentation socket. It verifies the exact running
container/start time and console selection. Closing the viewer disconnects the
window only; the experiment supervisor still owns shutdown and recovery.
Automatic remote resize is disabled until guest mode/capture changes can be
coordinated. This is QEMU's VM console, not macOS Screen Sharing.

`tools/console-metal-probe.m` generates three1280×720 color-bar phases on Raphael,
checks921,600 pixels per phase, then copies the verified buffer into Bochs VRAM.
Candidate333 run `a7fa79a29559deb6a80bedfb6ac658b1` completed all three phases.
Independent QEMU screenshots of phases0 and2 each match all921,600 pixels.
This demonstrates Metal-to-console presentation, not a captured desktop or
measured frame rate. The viewer connected successfully on the Linux desktop.

The CGVirtualDisplay helper creates1920×1080 logical/3840×2160 backing pixels.
`console-presenter` additionally requires macOS Screen & System Audio Recording
permission. The current333 executable is `/private/var/tmp/c333-console-presenter`;
its denied TCC entry explains the capture error-3801. Enable it in the guest's
Privacy & Security settings, then restart the presenter. Future packaging must
provide a stable application identity rather than a new per-experiment path.

Remaining: desktop capture, selecting the virtual display as the sole desktop,
mouse/keyboard mapping, resize coordination, performance and repeated cleanup.
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
