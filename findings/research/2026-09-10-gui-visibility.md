# GUI visibility investigation — `metal-016-183-gui-73ad3355`

## Scope and safety

This is an offline diagnosis plus a diskless QEMU display smoke test. No
macOS disk, VFIO device, GPU ownership transition, reset, sudo, or hardware
experiment was used. The smoke test used the existing `sickcodes/docker-osx`
image only as a container for QEMU, with TCG acceleration and an emulated VGA
device; it was stopped after the observation.

## Host display state

At investigation time the host was an active KDE Wayland session with
Xwayland available:

```text
XDG_SESSION_TYPE=wayland
XDG_CURRENT_DESKTOP=KDE
DISPLAY=:0
WAYLAND_DISPLAY=wayland-0
XAUTHORITY=/run/user/1000/xauth_qzyxFc
/tmp/.X11-unix/X0 (socket exists)
/run/user/1000/xauth_qzyxFc (readable, 2 Xauthority entries)
```

The supervision code (`vm-supervision.py`, SHA-256 recorded in the run
manifest) passes `DISPLAY`, `XAUTHORITY`, and `XDG_RUNTIME_DIR` through
`systemd-run --user`. It deliberately does not pass `WAYLAND_DISPLAY`; the
container therefore uses the mounted X11 socket and mounted Xauthority file,
not a container Wayland connection. `macos-vm.sh` validates both the X socket
and the cookie before launch, mounts them, and appends
`-display gtk,gl=on` when `GL=on`.

## Evidence from the prior run

The durable launcher log `/home/bogdan/macos-vm/run/vm-launch.log` preserves
the exact QEMU command generated for the run. Its final command included:

```text
-display gtk,gl=on
-device vfio-pci,host=0000:7b:00.0,...
-monitor stdio
```

The log has no `cannot open display`, GTK initialization failure, or QEMU
display-backend error. It does contain the normal accessibility-bus warning,
the normal AMD DRM file-description warning for `gl=on`, and a live QEMU
monitor banner. The run's manifest records only wrapper options and does not
record an X window ID, `_NET_WM_STATE`, geometry, workspace, or screenshot.
The agent events record serial/guest polling only. Thus the run proves QEMU
was launched with GTK arguments, but contains no proof that a user-visible
window was mapped, raised, on the current workspace, or still alive when the
user looked.

## Reproduction: diskless QEMU GUI smoke tests

Both tests used an explicit command, no disk and no passthrough:

```text
docker run --name <unique> --ipc=host --device /dev/dri \
  -v /tmp/.X11-unix:/tmp/.X11-unix:ro \
  -v /run/user/1000/xauth_qzyxFc:/tmp/smoke.Xauthority:ro \
  -e DISPLAY=:0 -e XAUTHORITY=/tmp/smoke.Xauthority \
  sickcodes/docker-osx:latest \
  qemu-system-x86_64 -name <unique> -machine q35,accel=tcg -m 256 \
  -nodefaults -display gtk,gl=on -device VGA -S -monitor none -serial none
```

The `gl=off` variant produced the same result. After three seconds, the live
X11 root client list contained a QEMU client (`0x1000009`), and querying that
window returned:

```text
WM_NAME(STRING) = "QEMU (rgpu-gui-smoke-20260910-glon) [Paused]"
_NET_WM_NAME(UTF8_STRING) = "QEMU (rgpu-gui-smoke-20260910-glon) [Paused]"
_NET_WM_STATE(ATOM) = _NET_WM_STATE_FOCUSED
```

The `gl=on` smoke log contained only the same accessibility warning, AMD DRM
warning, and Glycin sandbox warning; QEMU remained running and its window was
mapped and focused. The container was then stopped by its own test process and
no smoke QEMU remained. This is direct window-manager evidence, rather than
inference from process existence or command-line arguments.

## Diagnosis

There is no evidence that the launcher stripped or overrode `-display gtk`,
that the host X11 route was unavailable, or that GTK/gl=on categorically fails
in this desktop. The smoke test disproves those as general causes.

The exact failure cannot be reconstructed from the frozen `metal-016` run:
the harness did not capture window-manager state or a screenshot, and no
historical X client list is preserved. The demonstrated root cause is an
observability and launch-policy gap: the workflow called a GTK launch a
“visible launch” without requiring proof of a mapped user-visible QEMU window.
The user's report could therefore have been caused by a transient launch/exit,
window being minimized or on another virtual desktop, compositor placement,
or simply looking after the window had closed; the retained artifacts cannot
distinguish these possibilities.

## Bounded fix proposal

For any future manual GUI observation, add a host-side, launch-specific check
immediately after the container is identified: poll the X11 root
`_NET_CLIENT_LIST`, match the QEMU `_NET_WM_NAME` containing the unique launch
name, and record window ID, `WM_STATE`, `_NET_WM_STATE`, geometry, desktop, and
timestamp. Save a root/window screenshot while the QEMU process is live. Fail
the observation as “GUI unproven” if the matching window does not appear or
cannot be queried. A Wayland-native path could be added separately, but is not
required for the current Xwayland route. Do not treat the QEMU process, GTK
argument, or monitor banner as visibility evidence.

## Standalone observer implementation

The bounded observer is implemented in `tools/gui-observation.py` with focused
`unittest` coverage in `tests/test_gui_observation.py`. It uses argv-based
`xprop` and libX11 geometry queries, requires exactly one matching QEMU title,
normal `WM_STATE`, no hidden state, known current desktop, nonzero geometry
inside the X screen, and a freshly created cropped window screenshot. It
uses an explicit exact-title allowlist (`QEMU (name)`, `[Paused]`, or
`[Running]`) and never prefix-matches attacker-controlled suffixes. It
re-enumerates and re-reads the complete client list after the screenshot,
rejecting a second exact-title window or changed XID, and emits screenshot size, mtime,
and SHA-256. Existing screenshot output paths are rejected to prevent stale
evidence reuse. Missing, ambiguous, hidden, off-desktop, off-screen, zero
geometry, screenshot, or recheck evidence returns a nonzero status.

Validation:

```text
python3 -m unittest discover -s tests -p 'test_gui_observation.py' -v
Ran 7 tests ... OK (skipped=1)

GUI_OBSERVATION_SMOKE_COMMAND='<diskless Docker QEMU command>' \
  python3 -m unittest discover -s tests -p 'test_gui_observation.py' -v
Ran 7 tests ... OK
```

The live smoke used TCG, an emulated VGA device, `-display gtk,gl=off`, the
existing X11 socket/cookie, and no `/dev/dri`, VFIO device, or disk. It produced
an actual cropped 640x514 PNG; independent image inspection showed the QEMU
“Machine View” window and its guest display area. The recorded live observation
was `WM_STATE=Normal`, desktop `0`, current desktop `0`, geometry
`x=3567,y=867,width=640,height=514` on a `7680x2160` X screen, and
`reason=visible`. The smoke QEMU was terminated by the test's own process and
no process remained. This is GUI-path validation only and says nothing about
macOS boot or Metal functionality.

Archived smoke artifacts (copied without modification) are under this
directory: `smoke-window.png` SHA-256
`e008c3c5c85e18793f80e4b34afc086a22e9e9196eda418fee2b23483b831841`,
`smoke-result.json` SHA-256
`74b3091226b036b9c376ec8fc6adc0e5f1a6c17cba67a43ff0c0814754f17c71`, and
`smoke-qemu.log` SHA-256
`e5148e2ba3bb93072337ebf06f70605dd75a0ded0f94cb91dfa2010ee5e6c0ed`.

The focused observer suite now has 12 tests (one explicit live-smoke skip),
covering off-screen geometry, missing desktop metadata, stale screenshot
paths, finite argument validation, and real `xprop` equals/multiline fixtures.
The full suite was rerun without hardware and passed 566 tests with one skip;
the exact output is archived in `full-unittest.log`, SHA-256
`d1a599e8742a73313f3394e34483ff5290b5db0489bbe6d81bef35c5dbc0c951`.
