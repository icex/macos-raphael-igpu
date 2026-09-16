# Sunshine / Moonlight remote desktop

Sunshine is an optional alternative to macOS Screen Sharing. The current guest has
[Sunshine v2026.914.233613](https://github.com/LizardByte/Sunshine/releases/tag/v2026.914.233613)
installed from the official Intel DMG. Hardware-only VideoToolbox startup probes
find H.264 and HEVC Main8. Actual4K Moonlight playback works but currently delivers only3–4FPS.
Native encode/reclamation stalls are under investigation; this is not yet a faster
replacement for Screen Sharing. macOS support is experimental; gamepad support is
unavailable in this build.

## Guest setup

Download the `Sunshine-macOS-x86_64.dmg` asset, open it and copy Sunshine.app to
Applications. The tested asset SHA256 is
`764b11674babac0cd838c2883359207a481c462f355ccbfd1ec91f6d44672101`.
Launch it from the logged-in desktop and grant macOS capture/input permissions
when prompted. Configure your own web credentials; credentials are not part of
this repository. Quit Sunshine before merging these settings into
`~/.config/sunshine/sunshine.conf`, then launch it again:

```ini
sunshine_name = Raphael macOS
port = 48989
encoder = videotoolbox
vt_software = disabled
vt_realtime = enabled
hevc_mode = 2
av1_mode = 1
origin_web_ui_allowed = lan
upnp = disabled
```

This separate port family avoids the default host Sunshine ports. The web UI is
`https://GUEST_OR_FORWARDING_HOST:48990`; accept the local server certificate for
that address. In Moonlight, manually add `HOST_LAN_IP:48989`, then enter Moonlight's
pairing PIN in Sunshine's web UI. Choose Desktop, SDR and initially 3840×2160 at60FPS.
Use the client's90/120FPS options for later measurements if available; these do
not change the currently observed60Hz macOS display timing. Do not add obsolete
`fps` or `resolutions` keys: the tested Sunshine version does not parse them.

For the current headless topology, run `tools/install-remote-retina.sh --install`
as the logged-in macOS user, with `tools/remote-retina.m` alongside it and Xcode
Command Line Tools installed. It configures1920×1080 logical pixels with3840×2160
backing at60Hz and installs a login helper. User-visible output is confirmed in
one running session; fresh-login persistence remains to be verified.

## QEMU networking

For a direct QEMU process using the [example config](../examples/qemu/macos-q35.cfg),
add these entries **inside the existing `[netdev "network"]` section**, replacing
`HOST_LAN_IP` with the host's LAN address:

```ini
hostfwd = "tcp:HOST_LAN_IP:48984-:48984"
hostfwd = "tcp:HOST_LAN_IP:48989-:48989"
hostfwd = "tcp:HOST_LAN_IP:48990-:48990"
hostfwd = "tcp:HOST_LAN_IP:49010-:49010"
hostfwd = "udp:HOST_LAN_IP:48998-:48998"
hostfwd = "udp:HOST_LAN_IP:48999-:48999"
hostfwd = "udp:HOST_LAN_IP:49000-:49000"
```

Keep the existing SSH/Screen Sharing entries. This changes networking only; retain
the documented VFIO supervision and cleanup. On Docker bridge networking, QEMU
binds inside the container: use `0.0.0.0` there and publish the same TCP/UDP ports
on the host LAN address when creating the container. Docker cannot add published
ports to an already-running container.

The development setup uses identity-checked QEMU monitor `hostfwd_add` rules and
`tools/sunshine-lan-relay.py` for the current container instead of restarting it.
The relay forwards the same port family, expires with the supervised interactive
session, and stops when the exact container instance disappears. It does not
modify router forwarding or enable UPnP. Refer to `--help` for receipt and address
arguments; its output receipt must be separate from the VM supervision input.

## Evidence limits

The Retina user sees crisp output while standard vncdotool RAW captures are black;
that capture path is not an adequate oracle for Apple's Retina Screen Sharing
presentation. Reducing Screen Sharing quality improved responsiveness. Neither
that observation nor a process's0%GPU counter identifies every render/encode path.
Sunshine's explicit hardware-only setting and encoder logs give a separate encoder
check; actual streamed output and Moonlight statistics are the next verification.

Current development session: Moonlight `192.168.0.43:48989`, web UI
`https://192.168.0.43:48990`. The API and authenticated web endpoint respond through
that LAN address; another device has paired and streamed, but only3–4FPS was reported. This live relay expires at21:55:14 Europe/Bucharest on2026-09-16.
[Evidence hashes](../findings/research/sunshine-lan-20260916.json).

## Host firewall

The current host uses UFW. Guest streaming needs its own rules, separate from a
host Sunshine server's default479xx ports. The following rules are now active;
substitute your interface, LAN subnet and host address on another installation:

```sh
ufw allow in on enp9s0 proto tcp from 192.168.0.0/24 to 192.168.0.43 port 48984,48989,48990,49010 comment 'Raphael guest Sunshine control and web UI'
ufw allow in on enp9s0 proto udp from 192.168.0.0/24 to 192.168.0.43 port 48998,48999,49000 comment 'Raphael guest Sunshine stream'
```

These require administrator privileges. On this development host they were applied
through a short-lived privileged container, without host sudo. UFW confirms both
rules active. They persist across boots; the streaming relay still expires with
the VM session. Access from another LAN device remains the end-to-end check.
