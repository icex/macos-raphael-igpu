# Candidate 428: native virt-manager clipboard and USB

Date: 2026-10-10. This report qualifies the tested QEMU/libvirt/virt-manager
configuration, not every VM manager or USB device.

## Identity and configuration

- Run: `817dfe19b8e46522c6b350fb21dc0bd4`; card `metal-224`.
- Driver source: `68f247c745fd5d73a268f856ed472270f139a7cf`.
- Build: `3b413b25e1ce4f7eb6bb8e1a27384d7c`; executable SHA256
  `39aabe6038a5e5cb6f086e44ed51530d0abacb8c249a9cad30cc46be7cddbf72`.
- Container: `56bc1ed490779e9e268988e7581fb138c4c334278a590bf256ff2df538425c28`.
- Runtime identity confirms two `usb-redir` devices and eight direct USB2/USB3
  xHCI ports (`qemu-xhci.p2=8`, `qemu-xhci.p3=8`). The automatic hub which blocked
  candidate 421 enumeration is avoided. Existing keyboard/tablet/audio remain
  separate devices. SPICE refresh remains explicitly 60; snapshot pool is enabled.
- The isolated USB-enabled, pointer-corrected SPICE client and guarded launcher
  disable automatic USB attachment. The user selected the tested devices.

## Clipboard: four fresh X11 cases

`c428-x11-tests/events.jsonl` records the actual manager's GtkClipboard offers
and matching guest-to-host observations. Guest `pbcopy`/`pbpaste` receipts are
`c428-x11-{h2g,g2h}-{ascii,unicode}.txt`. Fresh host-to-guest ASCII (47 bytes) and
Unicode/multiline (89 bytes) match; guest-to-host ASCII and Unicode/multiline also
match at the host. This uses the existing manager connection, not a second
SPICE client. Synthetic tokens establish text transfer, not file clipboard support.

Earlier reconnect and Wayland/background automation artifacts are retained.
Background delivery could be delayed, so they do not replace the four fresh
`GDK_BACKEND=x11` controls or establish equivalent Wayland behavior.

## USB: actual guest enumeration and scoped I/O

The selected Kingston DataTraveler `0951:1666` appears in macOS as USB3
`super_speed`, disk5. The probe reads 1,048,576 bytes twice and obtains identical
SHA256 `c819744d6c462f7bdb6e347976b9ff9c90aeaa219f6a740472088aa702055a58`.
The probe reports zero writes; this does **not** mean the OS could not write:
macOS mounted its ExFAT volume writable. Initial and later eject attempts fail
because volumes remain in use; the retained inventory identifies Spotlight
processes with files open. Clean storage eject is not qualified by this run.

The selected Arctis Nova 7X `1038:22a5` enumerates in macOS. Its exact-device
stereo output probe records 288,768 frames at 48,000 Hz, peak 0.02,
`format_error=0` and unchanged defaults. These are output callbacks, **not an
endpoint audibility or microphone test**.

The normal chooser disconnect reports `connected=false`; Linux audio/HID
ownership returns on that path. An earlier abrupt viewer stop left interfaces
detached and required explicit restoration. The restoration receipt records
`snd-usb-audio` for interfaces 0–2 and `usbhid` for 3–5. Do not equate normal
chooser detach with arbitrary viewer-crash recovery. The physical device belongs
to the machine running the SPICE viewer; remote access to that viewer does not
by itself forward a USB device from the remote computer.

## Window modes and capture

The manager records settled allocations of 1280×720, 1101×703 and 1600×900 at
GDK scale 1. Independent guest mode-result/presenter logs confirm those modes,
including returning to 1101×703, and awake assertions remain present. This
qualifies these changes, not all resize sequences, Retina policy or refresh rates.

The hardware probe verdict is `CORE_PROBE_PASS` with no earliest failure. It is
separate from the above desktop/USB evidence. Critical replay retains terminal
snapshot 18 with 367 records, zero corrupt lines, and incomplete snapshot 14
with 945 chunks and no END. Capture is therefore not described as perfect.

## Shutdown and recovery

The private lifecycle log observes an identity-bound guest shutdown (event 6,
detail 1). Nevertheless both capture hooks report `immediate-stop`, without
deferral, after about 0.458 seconds. No private `terminal.json` exists. The
reconciled shutdown outcome is **`capture-abort-after-request`**, retaining the
original `exited-after-guest-request` observation and
`private_terminal_verified=false`. It is not a clean native-controller exit.

GPU recovery reports `status=recovered` and `authorizes_launch=true`. Functional
progress and authorizing recovery do not erase the capture abort or establish
viewer-crash USB recovery.

## Remaining work and evidence

The current transport is bounded to 3840×2160 and the reviewed virtual profile
uses 60 Hz. Standard Retina 1080-logical/4K and 1440-logical/5K modes, explicit
2× window policy and 120 Hz need coherent capacity, mode and pacing changes.
Physical HDMI qualification does not qualify those virtual paths. Prior 402
performance remains the baseline; no new throughput claim is made here.

The adjacent evidence manifest hashes the selected existing run artifacts;
original logs and failed attempts are retained under `/home/bogdan/macos-vm/run`.
No user data, USB serial number or clipboard contents are copied into this report.
