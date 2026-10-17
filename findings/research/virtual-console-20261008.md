# QEMU window with accelerated macOS desktop — October8

## Observed capability

Candidate336, run `201412ad0f4bafdc61ad3dde81d38037`, boots on hostba51b3c6
without a reboot after the console-restart investigation. Native desktop Metal
probe passes with WindowServer accelerator ownership. The ScreenCaptureKit
presenter copies the virtual display into Bochs VRAM. Independent QEMU capture
shows actual application windows, menu bar and Dock at3840×2160 backing pixels
(1920×1080 logical). A local TigerVNC window connects to that QEMU socket.
This is VM-console presentation, not macOS Screen Sharing used as the output.

QEMU-console mouse input opens the Finder menu at the expected location. Keyboard
input into a dedicated Cocoa test window returns exact `RGPU336`, including an
explicit Shift modifier. The first injection of uppercase key symbols without
Shift produced lowercase; the corrected physical-key sequence passes. No user
document was used for the typing test. Display-awake assertions were checked.

The guest's normal Screen Recording settings were enabled for the experimental
presenter and then the packaged `org.raphaelgpu.console` app through System
Settings UI and its ordinary authentication. No TCC database was edited. Existing
Screen Sharing was used only to complete this setup. AppleScript UI inspection
timed out; its result is not evidence of GPU failure.

## Restart diagnosis

333b crossed the prior host-hang boundary: DMCUB held, memory reserved, PSP unload
returned0. Native Metal and three synthetic color phases passed; each phase
verified921,600 pixels in the guest. QEMU phases0 and2 independently matched all
1,843,200 pixels. Guest-request shutdown and authorizing recovery passed.

333c safely refused an old exact held-control value.334's checksummed capture
then showed enable still set under asserted CPU/interface reset (CNTL0x90000).
335 followed Linux dmub_dcn31_reset's already-reset disable step and read back
CNTL0x80000, but refused stale mailbox windows at MC+0x4a0000..0x4bf600.
336 validates all six ranges, preserves secure CW0/1, and retires only stale
mailboxes in console mode while both resets remain asserted. The immediate
pre-PSP check still requires reset and disable proof. Physical-display rules
remain unchanged.333c/334/335 each shut down through the guest; their missing
native lease pools required the bounded no-queue recovery path, which authorized
reuse without reboot. See the separate332 host-hang investigation for limits on
attributing the original hardware fault.

## Artifacts

Under `~/macos-vm/run/`:

- `candidate-336-results/probe.json`, manifest, identity and captures.
- `c336-desktop-main.ppm`: application windows in QEMU framebuffer.
- `c336-qemu-input-menu.png`: Finder menu opened through QEMU input.
- `c336-qemu-keyboard-shift.png`, `c336-input-and-capture-result.txt`: exact input.
- `c336-packaged-desktop.ppm`, `c336-packaged-result.txt`: installed app output.
- `c333-console-pixel-result.json`, `c333-console-metal-guest-result.txt`: exact
  synthetic presentation check, separate from the actual desktop observation.

## Scope still open

One working desktop does not qualify all Metal APIs, games, arbitrary crashes,
long-running frame pacing or audio in the QEMU window. Capture requests60Hz but
actual throughput/latency has not been measured. The current transport copies
pixels through CPU memory. Resize coordination, libvirt/virt-manager lifecycle,
release signing and independent-host-boot repeatability remain open. VirtualBox
needs a separate GPU transport because its current Linux PCI passthrough is absent.
Candidate336 first run shut down through the guest and recovered with
`authorizes_launch=true` and a valid CORE_PROBE_PASS. Repeat336b, run
`a4b743f14436d22521c6e627ab20476c`, automatically recreated the virtual display,
restored main-display layout, retained the packaged Screen Recording consent and
started capture at login. Its fresh native Metal probe passed. No manual guest
helper startup was used on that boot. The three-minute material workload completed2,062 event-loop iterations. Sampled
QEMU captures show rendered material effects, and capture continued through the
workload. These samples do not prove tear-free output or a delivered frame rate.
The serial capture contains no new panic or reported VM fault. Repeat shutdown
was `exited-after-guest-request`; recovery was `recovered`, `authorizes_launch=true`,
with valid CORE_PROBE_PASS. The VM is stopped. Artifacts include
`c336-b-material-{1,2}.ppm`, `c336-b-material-result.txt`,
`c336-b-after-material.ppm` and `candidate-336-attempt-b-results/`.

[Artifact hashes](virtual-console-evidence-20261008.json).
