# Bridged LAN NIC, Apple Screen Sharing High Performance mode and client size — 2026-09-22

**[V]** verified live on candidate 286 (run `f64ae47b` then the `lan` retry), boot `67ab8c3f`.

## What blocked High Performance mode
- Apple Screen Sharing "High Performance" (HEVC over UDP, iPadOS/macOS 26 clients) hands the
  stream to the FaceTime transport (`avconferenced`, RTP on UDP 5900/5901 both ways). It
  advertises the guest's own address; behind QEMU user-mode NAT that is `10.0.2.15`, so the
  client's packets never arrive and the guest logs `audio streamDidRTPTimeOut` until the
  viewer drops. Port forwards, a host relay and a UFW rule were all tried and are not enough [V].
- Standard mode (TCP 5900, RealVNC or Apple client in standard mode) works behind NAT [V].

## Fix: a second guest NIC bridged on the LAN
- Host (root, per boot): `ip link add link enp9s0 name rgpu-lan type macvtap mode bridge`,
  `ip link set rgpu-lan up`, `chown <user> /dev/tapN` (N = ifindex). The launcher detects
  `rgpu-lan`, passes the node into the container, and `vm-entry.sh` opens it and adds
  `-netdev tap,id=lan0,fd=3 -device vmxnet3,netdev=lan0,mac=<macvtap MAC>` [V].
- A macvtap delivers unicast only for its own MAC: with a different guest MAC the guest saw
  broadcasts only (RX == mcast counters). The guest NIC now takes the macvtap's MAC [V].
- Guest: `networksetup -detectnewhardware`, service "Ethernet 2" set manual
  `192.168.0.44/24` router `192.168.0.1`, and put first in the service order so the primary
  address and default route are the LAN ones; the NAT NIC stays for the host-side plumbing
  (agent 10.0.2.2:8888, serial, loopback VNC/SSH) [V]. Host <-> guest over the macvtap does
  not work (macvtap limitation); the host uses 127.0.0.1:5900.
- After that, High Performance mode streams (no RTP timeouts) [V]. No host port publishing,
  relay or firewall rule is needed for the guest; the earlier LAN port publishing was reverted.

## Client resolution
- The guest's screen is the headless fallback display (model `virt`) with 9 fixed modes; the
  client-resolution option needs the client's size in that list and loops when it is absent [V].
- A persistent `CGVirtualDisplay` with 21 HiDPI modes (`tools/virtual-display-server.m`) came
  up as main display with a real picture, but ScreenCaptureKit reported ~989 ms per-frame
  latency and every Screen Sharing session (standard or HP) timed out [V]. Kept as an
  experiment only.
- Working route: `remote-retina --size WxH` (new) makes the fallback adopt WxH HiDPI through the
  temporary-display trick; `1180x820` (11-inch iPad) gives a 2360x1640 backing with a real
  picture [V]. Use it with the client-resolution option off.

## Evening results (22:10) — what streams and what does not [V]
- **Works:** RealVNC (standard RFB) at .44; Moonlight video and audio at .44 (Sunshine as a
  keep-alive login agent, `audio_sink = BlackHole 2ch`, BlackHole default output, microphone
  permission granted by the user in System Settings); guest sound to the host speakers via the
  USB device (when it is the default output).
- **Apple Screen Sharing (iPadOS 26 client):** High Performance streamed twice (20:34, 20:52),
  both right after a login with the display at 1920x1080 Retina and with **Mac login** auth.
  Every session with the VNC password is standard mode and fails (tiled OpenCL codec sends
  nothing after the first frame; the client shows "waiting for first screen update" or the
  session-select login screen). After any display mode switch (remote-retina --size, Sunshine
  changing the mode for a Moonlight client) the daemon describes the screen in pixels
  (e.g. `global rect 0 0 2064 2752`) instead of points and the client drops; only a
  WindowServer restart (logout) cleared it, twice. The client-resolution option never works.
- **Apple client audio:** the system-audio tap fails in coreaudiod with
  `HALS_MetaDevice: hasNonTapInputStream == false` regardless of the default output device
  (USB, multi-output, BlackHole) and of a default input (BlackHole). Open.
- **Session length:** harness caps raised from 6000 s to 43200 s (experiment.py admission,
  hold_interactive_session, stage-candidate) so a manual test session lasts 12 h.
- **Auto-login:** configured since Sep 11 (`autoLoginUser` + kcpassword) but does not fire
  after a `killall -HUP WindowServer`; the password had to be typed through the QEMU monitor
  (`tools/drive.py type ... enter`).
- **Login default** set back to `--configure` (1920x1080 Retina), the only state in which High
  Performance mode has streamed; the iPad size is a manual `--size 1376x1032` afterwards.

Next: find why the daemon's scale goes stale after a mode switch (compare `SLSDisplay`
properties before/after; try switching the mode before screensharingd starts, or restart
screensharingd *and* the ScreensharingAgent's parent session), and the tap input-stream
requirement (a real input device, e.g. QEMU usb-audio with a capture endpoint, may satisfy it).

## 22:20 — virtual display as a login agent: same ~1.2 s capture latency [V]
`virtual-display-server --serve` bootstrapped in `gui/501` (proper session, RunAtLoad) came up
as main display 1920x1080@2x with a real picture, but ScreenCaptureKit again reported
`latency count 1023 min 1192 ms max 1193 ms avg 1152 ms` and every Apple session dropped. So
the launch domain was not the cause. Working theory: the CGVirtualDisplay's frame pacing (VBL)
is not driven under the RaphaelGPU kext (compare the fallback display, whose capture is
immediate), so frames arrive on a ~1 Hz fallback timer. This is the engineering item behind
"client resolution": until a virtual display paces frames, the guest cannot offer arbitrary
modes to Apple's client. The agent plist is parked as
`org.raphaelgpu.virtual-display.plist.disabled-capture-latency`.
Also: with the legacy VNC password enabled, Apple's iPad app authenticates with it
(`authProtocol 2`) and runs standard mode (codec 1011); it used RSA/Mac login only when the
server offered no VNC password... Sequoia refuses the DH method (type 30) that third-party iOS
VNC apps use, so the VNC password must stay enabled for them.

## 22:45 — where the virtual display's 1.2 s comes from, and where it does not [V]
- `tools/guest-vbl-probe.swift` (CVDisplayLink on the main display): fallback display = 30 Hz
  nominal (33.3 ms), callbacks every 33 ms, output lead 49 ms; virtual display = 60 Hz, callbacks
  every 16.7 ms, output lead 24 ms. Display-link timing is fine on both, so the 1.2 s is not VBL.
- CoreDisplay `VFBGetVBLTiming` (decompiled, 0x7ff80407ee4b) synthesises VBL from
  `SLSCurrentRealTime()` with period 1/30 s for the fallback and 1/int(modeTable[cur]+0x24) when
  the VFB flag +0x308 is set (60 for CGVirtualDisplay). No time-base offset there either.
- The Screen Sharing agent's "latency" string is `SCStreamMetricCaptureLatencyTime`, a
  ScreenCaptureKit per-frame metric (capture time minus the frame's display time). ~1.19 s,
  constant, only on the virtual display. Next: a ScreenCaptureKit probe (needs the Screen
  Recording permission once) printing that metric and the sample presentation timestamps on
  both displays, then WindowServer's frame stamping for VFB presents.

## Physical display: why metal-134's hook did not attach [V]
`wrapDcCreate` reads `dc_init_data.cgs_device` (+0x30 → `AmdDalServices+0x650`, confirmed in
the decompiled `AmdDalServices::initialize`/`FUN_00065814`) and checked its read/write slots
(+0x40/+0x48) against `>= 0xffffff8000000000`. In this guest the AMD kexts' code lives in the
auxiliary collection (`vtable=0xffffff7f99...` in the serial log) while the framebuffer routes
were at `0xffffff8010...`; HWLibs' cgs register functions fail the check, so translation stayed
off. Candidate 287 (`8629b9b`, card `metal-135`, launch `run/c287-launch.sh`) accepts
`>= 0xffffff7f80000000` and logs the raw slots. Not run yet: the GPU is held by the user's
12-hour test session.

## 2026-09-23 — UDP verified end to end; MacBook audio is a platform limit [V]
- UDP echo on the bridged NIC: packets from the MacBook (192.168.0.25) to 192.168.0.44:5902
  arrived in the guest and the reply came back (`/tmp/udp-echo.log`). No NAT, no forwards.
- The MacBook's Screen Sharing app (7.0.0, macOS 27) negotiates the standard TCP session
  (`viewer->mode 1`) and creates no audio stream. Apple documents that High Performance screen
  sharing (the only mode with audio) requires both Macs to be Apple silicon; the guest
  identifies as an Intel Mac. The iPad app uses its own audio stream path and streamed in High
  Performance mode at host resolution on 2026-09-22 once the guest had its LAN address.
- Audio capture on the guest side needs a default output device with an input side: the
  multi-output aggregate fails CoreAudio's "no non-reference input stream" check; BlackHole 2ch
  as default output and input is the working configuration. `gpu-bind.sh` now creates the
  `rgpu-lan` macvtap itself, so the LAN NIC no longer needs separate root commands per boot.
