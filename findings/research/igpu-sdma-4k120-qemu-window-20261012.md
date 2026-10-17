# Full 4K at 120 Hz in QEMU's window: SDMA scanout copy (candidates 460–464)

Date: 2026-10-12. Boot f4bdf4e0. Cards metal-254 … metal-258, QEMU pins v5/v6.

## Result

With `rgpusdmacopy=2` the kext copies each newly latched scanout surface, detiled, into
QEMU's four buffers with an SDMA0 RLC0 queue it owns, and fences the buffer index into
the control page. Display writeback is not used, so ODM 2:1 no longer limits the capture
to half a frame.

| run | functional | capture | shutdown/recovery |
|---|---|---|---|
| 460 | scanout surfaces DCC-free (HUBP 0x61a DCC_EN 0); clean 3840x2160 boot frame | stalled after 7 frames at the first ring wrap | CORE_PROBE_PASS, exited after guest request, recovered |
| 461 | 65 full frames across ring wraps | stopped by a 50 ms in-flight limit while Apple's SDMA0 IB held the engine | same |
| 462 | pixel-exact 4K desktop frames, 2.3 ms per copy | false colours: 8888 desktop advertised as 2101010 | same |
| 463 | correct colours; 3840x2160 @60: kext 600 copies/10 s, QEMU 59.0 presented/s | pointer missing (cursor plane not in the surface) | exited after guest request; recovery failed on CR2 capture loss, then mode2-noqueue-recover authorized |
| 464 r2 | 3840x2160 HiDPI ("looks like 1920x1080") @ OTG 119.98 Hz, ODM 2:1 | **120.0 presented and 120.0 content changes per second over 65 s of full-field Metal**; 1200 copies/10 s at 2.33 ms each | live at time of writing |

(464's first launch was refused at admission before QEMU started: 463's recovery receipt
was missing. No GPU exposure.)

## Fixes, in order

1. **Displayable DCC off (460).** Apple's Navi23 personality allocates DCC for scanout
   surfaces, which SDMA cannot read while detiling. The kext NOPs
   `or byte [accel+0x1f24],1` (`80 8b 24 1f 00 00 01`, matched by bytes) in
   `AMDGraphicsAccelerator::start`, matching the shipped Navi10 personality
   (`GPUDCCDisplayable = false`). Metal probe and WindowServer acceleration unchanged.
   Route A (DCC-aware SDMA copy) remains specified in ~/macos-vm/run/c460-dcc-scanout-copy-notes.md.
2. **Monotonic ring WPTR (461).** SDMA 5.x ring pointers are 64-bit byte counts the
   engine masks; a WPTR written below RPTR at the wrap stalls the queue.
3. **Progress-based hang detection (462).** Our queue shares SDMA0 with Apple's; one of
   their IBs held it for more than 50 ms. Only an RPTR stuck for 2 s counts as a hang.
4. **Pixel format (463).** HUBP DCSURF_SURFACE_CONFIG: 8 = ARGB8888 (desktop),
   10 = ARGB2101010 (boot). The copy publishes the matching fourcc.
5. **Hardware cursor (464).** The copy sees only the primary plane. The kext copies the
   cursor plane (HUBP CURSOR0, ARGB up to 256x256) with COPY_LINEAR to region +0x100000
   and publishes position/hot spot every poll (control page 0x188–0x1ac); QEMU overlays it
   with `dpy_gl_cursor_dmabuf`/`dpy_gl_cursor_position`, scaled with the frame. The copied
   image was verified (arrow with shadow, straight alpha); user confirmation on screen pending.
6. **Display helper retry.** Before login there is no console user; the helper now keeps
   the request and applies it after login (it selected 1920x1080@2x 120 Hz in 464).

Security: QEMU's BAR status/stop bounds checks use 64-bit arithmetic (413f1d7); cursor
fields are fetched once and bounded to 256x256 inside a fixed udmabuf.

Raw evidence: ~/macos-vm/run/candidate-46{0..4}*-results, c463-fullfield.json,
c464-fullfield-120.json, serial SDMACOPY lines.

## Candidates 465–468: exact fit, compact 1x, ODM 4:1, denser Retina

| run | functional | capture | shutdown/recovery |
|---|---|---|---|
| 465 | superseded before launch (letterboxing height cap) | — | — |
| 466 | window-exact aspect; exact 1x at 120 Hz up to the ODM budget (3448x2018@1x 120 Hz, OTG 119.98); even widths | user: cursor visible, resize follows | exited after guest request; recovery failed on CR2 loss (~10 resizes filled the 512-record critical log), mode2-noqueue-recover authorized |
| 467 | **ODM 4:1**: 5120x2880 @ OTG 119.98 Hz, ODM source 0x13200003 (4 segments), DET1-3 = 3, COMPBUF 4 | 5K120 full-field: 42.5 frames/s presented (copy 4.57 ms; the guest flips ~28-49/s, so rendering 14.7 MP on 2 CUs is the limit) ; macOS built no 2x modes for 4106-5186-wide panels | CORE_PROBE_PASS, verified exit, recovery authorized (per-resize records bounded) |
| 468 | 5120x2880 panel: "looks like 2560x1440" @2x 120 Hz; 5186x3036: 2593x1518 @2x 120 Hz | — | first boot: early macOS kernel panic before any kext loaded (NULL+0x150, as once at 457); stopped, noqueue recovery; r2 booted normally |

- ODM 4:1 is `force_odm_combine_4to1` (dc+0x244) in Apple's DAL, set for virtual streams
  above 1.18 GHz with `rgpuodm=2`; the pixel-clock capability reports 2.36 GHz.
- Retina for panels wider than 4095: the EDID base block must not claim its fallback DTD
  is native (feature byte 0x04 instead of 0x06) when no base DTD has the preferred size;
  macOS then takes the native size from DisplayID and builds 2x modes.
- Retina density: the panel is 2 x window / 1.33 (`rgpuretina=133`, 100..200), at least
  3840 wide, shrunk to fit 120 Hz on four pipes and a 64 MiB buffer.

## Candidates 469–474: standard Retina steps, window snaps to the guest aspect

User request: standard steps by aspect (1080p, 1440p, 1200p, ...), all listed in Displays,
QEMU scaling between them, and the window snapping to the aspect (no bars).

| run | functional | capture / window | shutdown/recovery |
|---|---|---|---|
| 469 | EDID with every step of six aspect classes (384 bytes, multi-block DisplayID) accepted; macOS built **no** 2x modes | QEMU aspect hint never updated (dmabuf mode changes skip the surface switch) | verified exit, recovered |
| 470 | base block led by a large DTD: **every step is a Retina mode at 120 Hz** (1920x1080, 1920x1200, 1920x1280, 1920x1440, 2048x1536, 2160x1440, 2560x1080, 2560x1440, 2560x1600, 3840x1080) | switching to 2560x1600 gave 5120x3200 @120 on four pipes; window hint still 16:9 | verified exit, recovered |
| 471 | same kext, QEMU diagnostics | **feedback loop**: kext chose the class from the window, QEMU reshaped the window from the mode, the guest toggled 16:9/16:10 until the window hit its minimum; stopped by booting out the helper | verified exit, recovered |
| 472 | class follows the guest's current mode; only a window-width change picks a step | no loop; QEMU hint base size wrong when maximized | guest shut down after the window was closed; verified exit, recovered |
| 473 | same kext; base size = menu bar | user: corner resize "barely moves" (KWin enforces a fixed-aspect hint on every motion; 5K minimum 1280x754) | verified exit, recovered |
| 474 | same kext; **no aspect hint: the window snaps to the guest aspect 300 ms after a resize**, minimum at most 640x360 | free resize to 2400x1000 snapped to a 2400x1350 picture (16:9); a 3907-wide window runs the 2560x1440 step at 119.97 Hz (5120x2880, ODM 4:1) | live |

Rules kept: macOS builds Retina modes from non-native EDID timings too, but only when the
base block's first DTD is large (preferred panel at 60 Hz, else 3840x2160@60). The kext's
aspect class must come from the guest mode, never the window, or the two feed back.

The host's LLVM was upgraded (22.1.8 -> 23.1.1) during 473's build; 473 onward are built
with clang 23.1.1.

## Candidates 475–476: user-chosen resolution, clean letterbox

- 475: DET/COMPBUF are read back from the registers on every change (474's tracked mask
  drifted to 22 of 16 segments after 4:1/2:1 switches: black right side, junk; a latched
  DCHUBBUB CONFIG_ERROR left COMPBUF_SIZE_CURRENT at 4, harmless with DCC scanout off).
  Window following is off unless `rgpufollow=1`: the all-steps EDID is installed once with a
  stable identity, macOS keeps the user's Displays choice, QEMU scales it into the window;
  aspect snap opt-in (`RGPU_SNAP_ASPECT=1`). User: "it works fine".
- 476: QEMU clears the window before drawing the centred picture, so letterbox bars are
  black instead of stale back-buffer contents. Verified exits for 474 and 475.

## Candidates 477–478: centred picture, boot output in the window

- 477: QEMU computed the letterbox offset but egl_texture_blit (always used with the cursor
  overlay) and egl_texture_blend ignored dst->x/y, so the picture sat at one edge; both now
  apply it. 477's first boot hit an early macOS kernel panic in the sandbox kext ("Taking
  non-sleepable RW lock with preemption enabled", pid 1 launchd); r2 booted normally.
  That is the third early-boot panic (457, 468, 477), each with a different signature, in
  about 30 boots with the same kext source booting cleanly otherwise: open reliability item.
- 478: rgpu-display attaches a ramfb, so OVMF, OpenCore and boot.efi draw into QEMU's window
  before the driver takes over (macOS has no ramfb driver: no second display). OpenCore now
  finds a GOP; it cannot set 1920x1080 on it, so boot screens use OVMF's default mode.
  User: centred letterbox and boot output "work fine".

## Candidate 479 (prepared, not yet run): clipboard, USB, safer forced stops

- Audio already works on the iGPU console (user confirmed): QEMU usb-audio on the host's
  PipeWire pulse server, default macOS output. Output only; no microphone.
- `CONSOLE_VDAGENT=on` on the direct iGPU console uses QEMU's `qemu-vdagent` (QEMU now built
  with `-Dgtk_clipboard=enabled`), so the guest's existing vdagent clipboard agent shares
  UTF-8 text with the GTK/host clipboard.
- `CONSOLE_USBREDIR=on` adds two `usb-redir` slots on owner-only Unix sockets in the run
  directory (no network listener; a security review rejected the first TCP design).
  `tools/rgpu-usb.sh list|attach VID:PID|detach|status` runs
  `tools/rgpu-usbredir-bridge.py`, which relays only the connection whose socket belongs to
  the `usbredirect` it spawned (unit-tested both ways).
- Fullscreen keeps the guest aspect (letterboxed, centred).
- 478 was force-stopped after the guest stopped answering; the SDMA copy queue (SDMA0
  RLC0) stayed enabled and the frozen vfio-recover wrote an immutable `incomplete` receipt,
  so this boot cannot be reused (host reboot required). 479's SDMA copy publishes QEMU's
  exit stop list (it published none), covering forced stops where QEMU exits normally.
