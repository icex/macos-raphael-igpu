# macOS desktop virtual-display research (2026-09-11)

This is an offline design note. It does not establish that the guest image or
RaphaelGPU supports a virtual display.

## What the available APIs establish

Apple's public ScreenCaptureKit API captures displays, applications, or windows
through `SCShareableContent`, `SCContentFilter`, and `SCStream`. A display stream
delivers `CMSampleBuffer` frames backed by IOSurface; the documented sample
requires macOS 15 or later, Screen Recording permission, and an app restart
after the first permission grant. It also requires checking frame status for
`SCFrameStatus.complete` before using a frame. See [Apple's macOS capture sample](https://developer.apple.com/documentation/screencapturekit/capturing-screen-content-in-macos)
and [ScreenCaptureKit overview](https://developer.apple.com/documentation/screencapturekit).

`CGVirtualDisplay` is not in the public CoreGraphics documentation located for
this review. A stronger implementation reference is Chromium's macOS test
utility, which explicitly says its interfaces were generated from CoreGraphics
binaries. It creates a `CGVirtualDisplayDescriptor`, sets a dispatch queue,
name, color primaries, pixel bounds, physical size, vendor/product/serial
identity, then constructs `CGVirtualDisplay`; it applies a
`CGVirtualDisplaySettings` object containing HiDPI, rotation, and a 60 Hz
`CGVirtualDisplayMode`. Chromium waits for the display-added notification,
sets the mode synchronously, retains the display in a process-global map, and
waits for removal during teardown. Its code also documents a first-removal
workaround and currently returns the API as unavailable when it detects a
headless environment. See [Chromium's implementation](https://chromium.googlesource.com/chromium/src/+/HEAD/ui/display/mac/test/virtual_display_util_mac.mm)
and its [test header declarations](https://chromium.googlesource.com/chromium/src/+/HEAD/ui/display/mac/test/virtual_display_mac_util.mm).
This remains an undocumented/private API: ABI, entitlement requirements,
descriptor schema, and availability on macOS 15.7 / 24G830 are unverified.
The Chromium source is implementation evidence, not an Apple SDK contract.

Apple Remote Desktop documents a different virtual-display concept for a High
Performance screen-sharing connection: the authenticated user can receive one
or two virtual displays, and the remote session can select resolution and
arrangement. However, Apple explicitly limits High Performance screen sharing
to cases where **both Macs are Apple silicon** running macOS Sonoma 14 or
later. That excludes this Intel guest/host route. Standard screen sharing may
still provide access to a logged-in desktop, but the documentation does not
promise a virtual display or GPU-backed composition for this topology. See
[Apple's High Performance requirements](https://support.apple.com/guide/remote-desktop/use-high-performance-screen-sharing-apdf8e09f5a9/mac),
[Remote Desktop control and observe](https://support.apple.com/guide/remote-desktop/choose-how-to-control-and-observe-apd4f46319e/mac),
and [Apple screen sharing](https://support.apple.com/en-gb/guide/mac-help/mh14066/26/mac).

## Implications for this VM

The repository's reviewed GPU launch uses `GENERIC_GRAPHICS=off` and QEMU
`-display none`. Its `gui-observation.py` validates a host-side QEMU GTK window,
which is unavailable in that topology and would not prove WindowServer's
renderer in any case. `guest-login.sh` uses the existing screenshot and input
channel to detect login/desktop appearance; it has no renderer or GPU
provenance assertion. No VNC or guest virtual-display implementation exists in
the repository.

The current candidate-194 probe proves offscreen Metal work only. A desktop
result requires a separate display-producing path and evidence that the guest
WindowServer compositor submitted work to RaphaelGPU. A screenshot or a
ScreenCaptureKit frame alone cannot establish that: the test must record the
display identity, WindowServer/Metal device identity, and changing-frame
evidence from the same logged-in session. ScreenCaptureKit's required
Screen Recording permission and restart behavior must be part of the guest
login procedure; remote-control permission is a separate concern.

## Minimal future qualification proposal

1. First qualify a no-GPU guest access/display path with a reversible virtual
   display or documented screen-sharing session. Record login identity, display
   mode/ID, session type, and capture permission state. Keep the QEMU generic
   adapter disabled during any subsequent GPU test.
2. Add a guest presentation helper that draws a deterministic changing pattern
   in a window for several frames, reports its selected `MTLDevice` registry
   identity, and timestamps each frame. Capture the same display with
   ScreenCaptureKit, accepting only complete frames, and verify that successive
   frames differ at the expected regions and cadence.
3. Correlate the helper's device identity with WindowServer/IORegistry evidence
   and the RaphaelGPU serial diagnostics. A visible frame without this
   correlation is presentation evidence only, not proof of accelerated desktop
   composition.
4. Bound the test and cleanup like existing experiments: one logged-in session,
   fixed resolution, short capture duration, no manual debugger attachment,
   and a frozen capture plus host/recovery receipt. Test a copy path separately
   if the virtual-display service performs composition or transport outside the
   guest GPU.

The Chromium route gives a concrete lifecycle to reproduce in a macOS test
helper, but remains an SPI hypothesis requiring ABI and entitlement validation.
Apple's High Performance Remote Desktop virtual-display route is unsuitable for
this Intel target. Standard screen sharing, guest-local `CGVirtualDisplay`, or a
different guest display service must be evaluated separately; none is currently
implemented or verified here.
