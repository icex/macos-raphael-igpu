# Guest display helper (iGPU display in QEMU's window)

With `VM_CONSOLE=igpu` and `rgpuwbdisplay=1`, the macOS display follows the QEMU window.
Each window size gives one display with two choices:

- **HiDPI (default):** standard Retina steps (16:9 1920x1080/2560x1440, 16:10
  1920x1200/2560x1600, 21:9 2560x1080, 32:9 3840x1080, 3:2 1920x1280/2160x1440, 4:3
  1920x1440/2048x1536) are all listed in Displays. Pick one in Displays; macOS remembers it
  and QEMU scales it into the window (centred, black bars when the shapes differ). Opt-in:
  `rgpufollow=1` makes a window resize pick the step nearest window/1.33 points, and
  `RGPU_SNAP_ASPECT=1` (QEMU environment) snaps the window to the mode's aspect. 120 Hz with `rgpuodm=2` and `rgpusdmacopy=2` (candidate 474) when the host is.
- **Low DPI, exact fit:** the window's pixel size at 1x, shown 1:1, at 120 Hz when the host
  monitor refreshes at 100 Hz or more and the size fits the display pipes (all four with ODM).

Install once in the guest (as root, from `guest/display-helper`): `sh install.sh`.
Switch: `sudo defaults write /Library/Preferences/org.raphaelgpu.display dpi low` (or `high`);
the choice applies at the next window resize (a request made before login is applied once
a user logs in). Log: /var/log/rgpu-display-helper.log.
macOS 15.7 ignores /Library/Displays overrides, so HiDPI at arbitrary exact sizes is not
available.

## QEMU v20 window fit and cursor

The guarded v20 QEMU image applies
`patches/qemu/10.1.2-gtk-auto-fit-host-cursor.patch` after the v19 DMA guard.
`RGPU_AUTO_FIT=1` resizes a realized, non-maximized GTK window when the guest
scanout mode changes. It preserves the mode's aspect and caps the window to the
current monitor's GDK work area, allowing for window chrome and a 48-pixel
margin. It does not change the guest resolution or override fullscreen and
maximized windows. The image also sets `RGPU_HOST_CURSOR=1`: GTK displays its
host pointer for absolute input instead of relying on the QEMU GL cursor
overlay, which had sometimes become invisible after a resize.

At the 5120x2880/120 Hz desktop, QEMU logged a 3608x2064 fitted window in a
7584x2112 work area. The user confirmed the fit and visible pointer in the
clean image. This is window/input evidence, not a fix for the audio halt that
can still occur during a slow manual edge drag. Build binary SHA-256
`a3d8d946571aa0a41b8768f55be1961abb7add121edd5d445e2cc09a8a3aca09`,
image ID `sha256:7785dc54e21d619219008e361d8393b1d7baa16f6e2ea9a92318e1940db94a3c`,
pins `experiments/pins-igpu-display-v20.json`. The source tree is
`~/macos-vm/run/c515-qemu-runtime/qemu-10.1.2` at `08325543f` plus the v19
guard patch and the v20 GTK patch. Docker build uses the pinned
`sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c`
base image, replaces only `/usr/sbin/qemu-system-x86_64`, and enables the two
environment variables above.
