# QEMU console mode following and copy cost — October 8

Run `0e5cca1002e71c3b3f100166e6c2bd3f` uses the unchanged1.0.336 driver,
metal-184, host boot `ba51b3c6-9420-4510-af69-38a42b3c79c7`.
Guest helper development is on candidate338; the final presenter source is in
`607e68c`. This separates userspace changes from the already tested driver.
The harness reports valid CORE_PROBE_PASS, guest-requested shutdown, and recovered
with authorizes_launch=true. No host reboot or driver rebind occurred.

## Observed results

- Session-scoped1080HiDPI→native1080p→1080HiDPI changes produce independent
  QEMU framebuffers of3840×2160→1920×1080→3840×2160. The presenter stays running.
- A720HiDPI request first returns2560×1440, then settles to native1280×720.
  Do not qualify720HiDPI from the immediate API return. Final native720p capture
  is usable, but the scale fallback remains unexplained.
- Before explicit write combining, sampled4K lock/copy times are about86ms and
  the copied-frame counter reaches about11.6fps. Explicit write combining gives
  sampled12–15ms lock/copies and33–43 copied fps during the initial comparison.
  During the three-minute material workload, sampled copied rates are mostly
  21–24fps. Content cadence matters; none of these numbers measures viewer fps.
- The material workload completes2,187 event-loop iterations. Sampled QEMU
  images show the material effects; there is no new guest panic in serial.
  This is visual sampling, not a blur pixel oracle or a tear-free guarantee.
- The final bounded helper passes native1080p input (`RGPU336`, including Shift)
  and restores1080HiDPI. Its first material test was interrupted by presenter
  restart and is not an uninterrupted capture pass. A fresh180-second test with
  the final presenter/launcher completes1,525 event-loop iterations; capture
  continues, but sampled copied rates are only8–9fps with roughly18–22ms lock/copy
  times. That slower result prevents an overall throughput qualification. A fresh
  guest boot is the next discriminator; neither the bounded queue nor accumulated
  session state is established as its cause.
- Independent Metal color bars validate all921,600 GPU pixels in each of three
  phases. QEMU phases0 and2 each match921,600 expected pixels under write
  combining. The same independent captures also pass with explicit uncached
  mapping. Both probes exit0.
- The isolated3.7MB copy takes1.854/1.856ms after warm-up with write combining,
  versus235.191/231.256ms with explicit uncached mapping. A later `default` map
  remains fast (1.863/1.859ms), so default-after-write-combining is not an
  independent uncached control. The initial default mapping's exact cache type
  was not inspected. Do not equate it with the explicit uncached experiment.

## Corrections and implementation

The first resize probe used CGDisplaySetDisplayMode, whose changes revert when
its calling application exits. Its apparent immediate success was followed by
restoration and mirror changes. The probe now commits a session-scoped display
transaction, preserves virtual-primary mirroring, and reports the selected mode.
The separate later720HiDPI fallback still limits that case.

The presenter subscribes to display changes and polls current backing geometry.
It updates ScreenCaptureKit configuration, accepts only matching complete BGRA
frames, and sets the console geometry after the first matching frame is copied.
The final helper bounds pending work to one frame; additional callbacks are
counted as dropped rather than retained ahead of mode and shutdown handling.
All mapped-memory access and control operations share one serial queue. Explicit
SFENCE completes write-combined stores before mode programming/frame reporting.
Stop still has a hard process deadline and releases the client on exit.

The installer selects write combining for the emulated Bochs VRAM only. XNU's
IOUserClient mapping code permits the user cache-mode bits; this experiment
changes neither the physical Raphael mappings nor the kext. The single-buffer
transport still lacks an atomic display/presentation fence.

Screen Recording consent persists across a guest boot for an unchanged installed
app. Replacing the ad-hoc-signed executable invalidated it despite an enabled UI
switch. Resetting only org.raphaelgpu.console with tccutil, then adding the rebuilt
app through ordinary Settings UI, restored capture. No TCC database was edited.
During one failed file-dialog shortcut, Home was accidentally added; its new
ScreenCapture grant was immediately reset with tccutil before continuing.

An immediate LaunchAgent bootstrap after bootout failed; a later bootstrap after
teardown succeeded. The launcher also had a source-visible readiness race:
parent grep could observe the previous serving line before child redirection
cleared the log. The updated launcher clears the file before spawning and gives
the new virtual display a bounded20-second readiness wait. This race is a source
finding, not a demonstrated cause of every observed startup delay.

## VM manager scope

The host has GNOME Boxes and a shut-off `raphael-macos-boxes` session-libvirt
registration. Its emulator is a deliberate launch hold, with physical VFIO args
but no integrated GPU admission/cleanup. It was inspected, not started or
unblocked. QEMU-console desktop/input success does not qualify that lifecycle.

## Primary source references

- [Apple display-mode lifetime and mirror behavior](https://developer.apple.com/documentation/coregraphics/cgdisplaysetdisplaymode(_:_:_:)).
- [ScreenCaptureKit configuration updates](https://developer.apple.com/documentation/screencapturekit/scstream/updateconfiguration(_:completionhandler:)).
- [XNU11417 IOUserClient map options](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/iokit/Kernel/IOUserClient.cpp#L2047).
- [XNU cache-mode handling](https://github.com/apple-oss-distributions/xnu/blob/xnu-11417.140.69/osfmk/device/iokit_rpc.c).

## Selected artifacts

Under `~/macos-vm/run/`: `c338-{wc,uncached}-pixel-result.json`,
`c338-{wc,uncached}-result.txt`, the matching color-bar PPMs,
`c338-1080-{native-,}session.txt` and PPMs, `c338-input-result.txt`,
`c338-qemu-keyboard.png`, `c338-material-result.txt`, and
`c338-final-result.txt`/`c338-final-after.ppm`. The latter records the final
presenter and launcher hashes. Intermediate source revisions and comparisons
are retained separately; do not attach an early21–24fps rate to the final test.
