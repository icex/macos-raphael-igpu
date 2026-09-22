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
