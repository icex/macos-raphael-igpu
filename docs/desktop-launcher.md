# Desktop launcher: macOS on the Raphael iGPU

The default local disk is **macOS 26.7.1 / 25G241**. The shortcut uses release
514 / metal-318 with QEMU pins v18: smooth 120 Hz window drags, VRAM that no longer fills, an
aspect-locked QEMU window, the USB picker, clipboard and audio. To roll back to 506, rerun the
installer from `worktrees/candidate-506` with
`--release 506 --card metal-310 --pins experiments/pins-igpu-display-v15.json`. The original
15.8.1 disk is preserved as `~/macos-vm/rollback/macos-15.8.1-24H32.img`.
`~/macos-vm/default-os.json` records the selection; the launcher boots the active
`~/macos-vm/mac_hdd_ng.img`. Driver compatibility is inspected dynamically.

Both latest releases pass rendering/self-capture/native cleanup checks. Unlocked
Tahoe presentation FPS remains unqualified; matched offscreen GPU and FP32
throughput is essentially equal. [Evidence](../findings/research/update-portability-20261013/performance-latest.md).

One shortcut, **macOS (Raphael iGPU)**, starts macOS in QEMU's window with the iGPU's own
display (Retina, up to 120 Hz), clipboard sharing, USB redirection and audio. It uses the
same safety cycle as every run: writeback/SDMA quiesce, MODE2 reset, staged release kext,
GPU ledger, guest shutdown and a recovery receipt for the next start. There is no session
limit: it runs until macOS shuts down or you choose **Shut down macOS**.

## One-time host setup

1. Do NOT set `amdgpu.virtual_display` for the iGPU. amdgpu must load its own display
   firmware image at boot; the guest takes that image over. With the parameter the platform's
   image stays, and the launcher refuses to start (that image crashed the host in 481). Remove
   it with `sudo sed -i 's/ amdgpu.virtual_display=0000:7b:00.0,1//' /etc/default/limine &&
   sudo limine-update`; it takes effect on the next boot.
2. GPU hand-off without a password, from the desktop session only:
   `sudo tools/install-desktop.sh --system` (root-owned `/usr/local/libexec/rgpu-gpu-bind`,
   no arguments, plus a polkit rule naming exactly that file for the desktop user).
3. Shortcuts: `tools/install-desktop.sh --release 514 --card metal-318
   --pins experiments/pins-igpu-display-v18.json` from the release worktree. It also installs
   the release's `tools/vm-entry.sh` as `~/macos-vm/vm-entry.sh` (QEMU audio and window
   options), keeping the previous copy as `vm-entry.sh.before-<release>`.

## Use

> **2026-10-15:** release 514 is installed. VRAM stays free in long sessions (the cache of
> freed VRAM allocations is released under pressure), and the QEMU window snaps to the
> display's aspect about 150 ms after a resize, following the dragged edge. Known issue: audio
> can go silent while windows move or scroll at about 120 fps.
>
> **2026-10-14 (evening):** release 509 was installed. Window drags reach QEMU's window at the
> full 120 Hz, VRAM no longer fills with cached allocations, and clipboard and the QEMU
> **Machine › USB Devices…** menu work. The BIOS UMA frame buffer is 4 GB.
>
> **2026-10-14:** release 506 is installed and macOS 26.7.1 is the default. Weather,
> the Memoji picker and other 3D content no longer freeze the desktop. If a session never
> reaches the login window, the guest panicked early (an open host-level issue): choose
> **Shut down macOS** and start again.
>
> **2026-10-13:** release 490 was installed and macOS 26.7.1 became the default.
> The same driver also supports the retained 15.8.1 rollback disk. Existing
> session and display preferences are retained; normal use still requires login.


- Fresh boots need nothing else: no `gpu-bind`, no suspend (verified with 483).

- Start from the application menu or the desktop icon; a notification confirms progress and
  the outcome. `raphael-macos stop|status` from a terminal.
- The host stays awake while macOS runs (the run holds a sleep/idle block itself).
- Resolution: pick it in macOS Displays (standard Retina steps at 120 Hz); the window
  scales it. Fullscreen: Ctrl+Alt+F.
- Clipboard: plain text both ways (the guest agent's clipboard preference must be on). After
  updating the guest support package, `start-console.sh` keeps the agent running on the iGPU
  display; until then a user LaunchAgent (`org.raphaelgpu.clipboard`) runs it.
- USB: QEMU's **Machine › USB Devices…**, the shortcut's **USB devices…** action, or
  `tools/rgpu-usb.sh list | attach VID:PID | detach | status`.
- Diagnostics: `tools/rgpu-top.sh` (GPU busy, free VRAM, CPU per second) and
  `tools/rgpu-window-test.sh` (window-drag stress: frames reaching QEMU, macOS present times,
  allocation failures).
- Logs: `~/macos-vm/run/raphael-macos-<attempt>.log`.

The installed QEMU v20 image initially fits the guest desktop resolution into
the current monitor's work area and keeps a visible host pointer. It does not
override maximized or fullscreen windows; the guest mode stays unchanged.

On the current Tahoe default, use logical **1920×1080** (3840×2160 pixels)
at 60 or 120 Hz (120 Hz verified with release 509). The observed logical 2048×1152 scaled mode can freeze QEMU
frame updates while SSH and guest input remain alive. Returning to the working
mode restores the display without restarting the VM; other scaled modes remain
unqualified. See the [interactive evidence](../findings/research/update-portability-20261013/interactive-scaled-mode.md).
