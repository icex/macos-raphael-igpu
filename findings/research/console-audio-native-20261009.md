# Candidate358: isolated console stereo delivery and pointer-event diagnosis

Run775fc7e86900090204edd78ae20f34a4, metal-200, MODE2#296,
build0594131c7f974cc0bfd5f2e0513961a3, runHEAD5105052. Same full-refreshON
QEMU image, SPICE60 and signedO2 presenter as356. [Hashed raw artifacts](console-audio-native-evidence-20261009.json).

## Audio observed

Compiled exact guest sourceSHA5818aac1953f46a8c46d1eabd3707e2b068f10079ec3ad2d480feba148e18fd4,
executableSHAb24e8f4a34c774b9b58ed928fad474ed6ce82426ace212cab3fdc764e3a0a239.
Read-only enumeration finds QEMU stereo USB UID
`AppleUSBAudioEngine:QEMU:QEMU USB Audio:1-0000:00:01.0-3:1`, device95.
The initial host attempt failed on missing module index in pactl JSON before
route state creation or any mutation. Corrected tool547c6b3 uses authoritative
short inventory IDs and retains multiline arguments;17 focused tests pass.
This host-only tool was run explicitly from candidate360, not silently substituted
into the pinned358 launch or capture harness.

Second attempt routes only exact VM stream to owned null sink and captures that
monitor with per-stream selection. The6s exact-device HAL tone exits0,48000Hz,
288768 callback frames, format_error0, guest defaults unchanged. Captured WAV
SHAe94be88601b3cac126b50b953255c59747a0900275f16c572fdb37905ee7d3be
passes left997.14Hz, right1498.57Hz and both phases. Left RMS0.004333,
right0.004325; opposite-only channel RMS0. Silence and clipping checks pass.
Host route restoration returns success. A separate read-only check verifies exact
stream/client lifetime, original sink, unchanged volume/mute/defaults and absence
of the owned module/sink. No user/global/microphone recording or default-route
writes. This proves explicit-device macOS USB→QEMU→Pulse sample delivery and
channel order, not default-application output, endpoint audibility or HDMI.

## Resize input discriminator

Actual virt-manager5.1 under KWin/Wayland, with a read-only GTK event observer,
resizes1288x909→1000x760. At65966.571s GTK receives enter, then button press at
65966.601s, with no motion event between. Guest clicks the old top-left location
and opens the Apple menu; this lies outside the fixture and its counter does not
count the failure. After Escape and a real relative-mouse movement, GTK motion
arrives at66015.143s. All five targets and exact token then pass; no guest mode
changes,1920x1080logical/backing_scale2. The aggregate transition remains failed
despite fixture passed=true; retain host trace and screenshot context.

Official spice-gtk0.42 source downloaded from
https://www.spice-space.org/download/gtk/spice-gtk-0.42.tar.xz supports the observed
mechanism: enter_event ignores crossing coordinates; motion_event sends absolute
position; button_event transforms position only to reject out-of-bounds clicks,
then sends button state without a position update. This is a client event-order
boundary, not evidence of bad guest scaling math. Next use continuous real pointer
motion across the boundary and test resize under a stationary pointer separately.
Do not patch the driver or claim universal real-mouse failure from teleport input.

## Capture and cleanup

CORE_PROBE_PASS, earliest_failure=null; actual controller terminal is genuine
identity-bound guest-shutdown/process_exited=true. GPU recovery recovered and
authorizes_launch=true. Viewer close preserves exact VM. Shutdown uses harness
stop-requested only. No reboot/rebind.1236 host tests/8skip and staging87 passed
before exposure; parser repair separately17 tests. Checked-in binary updates and
broader default-output, continuous-motion and installation qualification remain.
