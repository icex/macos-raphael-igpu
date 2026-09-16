# Sunshine / Moonlight remote desktop

Sunshine is an optional alternative to macOS Screen Sharing. The current guest has
[Sunshine v2026.914.233613](https://github.com/LizardByte/Sunshine/releases/tag/v2026.914.233613)
installed from the official Intel DMG. Hardware-only VideoToolbox startup probes
find H.264 and HEVC Main8. **Both codecs are enabled** (`hevc_mode=2`), as
requested by the user. The earlier H.264-only comparison with Moonlight-Qt
reached user-reported 4K60, described as better rather than
perfect, with about 40 FPS when moving over a transparent Safari window. An
active server trace averages ~55 submissions/s with occasional long calls. The client and codec changed together, so this does not prove a client-only
fix. Sustained 4K60 and input latency remain unqualified.
[Current evidence](../findings/research/moonlight-qt-h264-20260916.md).

Foundation-sunshine was investigated, then the user cancelled replacement. The
original app, pairing and LAN settings remain. No Foundation app was installed.
macOS support is experimental; gamepad support is unavailable in this build.

A log message such as `Minimum FPS target ~30fps` is Sunshine's default idle-frame
fallback for a 60 FPS request, not a 30 FPS cap. Measure moving content and
separate server submissions from delivered frames. Simple-frame encoder-only
results do not establish desktop performance.

## Experimental driver diagnostic budget

Candidate282 adds the opt-in OpenCore boot argument `rgpualloclog=1`. It samples
one guarded native allocation-failure diagnostic (first8, then every1024 with a
cumulative count), preserving allocation/retry behavior and other logging.
The startup record must show `ALLOCLOG: guarded=1 installed=1`; `installed=0`
means no change was applied. Omit the argument to retain the original logging.
This is the active performance experiment, not a qualified streaming-speed claim.

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

Keep `hevc_mode=2` to advertise HEVC Main8 alongside H.264. Select the desired
codec in Moonlight. The temporary `hevc_mode=1` comparison disabled advertisement;
it did not mean the GPU lacked HEVC support.

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
that LAN address; another device has paired and streamed, with latest user observations of1080p60 and4K20–30FPS. The relay is bounded by the active experiment’s deadline; consult `status.md` and its supervision receipt.
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

Candidate282's streaming investigation ended with valid capture, a clean
guest-request shutdown and authorizing recovery. Motion performance remains
open; the final120FPS-request/60Hz-display trace requires a matching4K60 control.
[Final evidence](../findings/research/safari-motion-20260916.json).

The follow-up capturefix3 run builds the original upstream Sunshine with the
scoped GPU-buffer lock patch. Its separate “Sunshine Capture Fix” app needs its
own macOS Screen Recording and input permissions. The original signed app was
restored after that permission denial; HEVC remains enabled. No measured
performance gain is claimed. [Build/rollback evidence](../findings/research/sunshine-capturefix-build-20260916.json).
