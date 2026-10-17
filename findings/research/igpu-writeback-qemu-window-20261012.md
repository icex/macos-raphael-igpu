# Candidates 449–453: the iGPU's own display in QEMU's window

User priority (2026-10-11): the iGPU drives its display and QEMU shows that output directly:
one macOS display, no emulated adapter, no mirror, no HDMI plug, resizable with the window,
Retina at 1080p. Status here is measured on hardware; nothing below is claimed beyond it.

## Transport (449)

- Guest (`rgpuwbdisplay=1`, needs `rgpuvirtualsink`; src/WritebackDisplay.hpp): a 100 ms
  kernel poller reads the active OTG/ODM/MPC tree and programs DCN display writeback
  (DWB + MCIF_WB, A2R10G10B10, four-buffer ring) of the composited output. Buffers live in
  a 258 MiB RAM region QEMU places at guest-physical 0x4000000000 without describing it to
  the firmware; the GPU reaches it through an MMHUB/DCHUBBUB AGP window above the frame
  buffer (MC 0xF480000000 → IOVA 0x4000000000). It re-programs on mode changes, stops while
  the output is off and tickles the display wrangler while QEMU refreshes.
- QEMU (`vfio-pci,x-rgpu-display=on`, patches/qemu/10.1.2-vfio-rgpu-display.patch on the
  444 arm D series): the vfio device owns a graphic console; the buffers are exported as
  udmabuf dmabufs and shown by `-display gtk,gl=on` with no CPU copy. A 2 ms realtime poll
  of MCIF_WB_BUFMGR_STATUS (CUR_BUF counts buffers 1..4) presents the last completed buffer.
  The control page (version 1) carries the guest's geometry, QEMU's window size/refresh
  requests and a stop list QEMU applies on exit.
- Launcher: `VM_CONSOLE=igpu` (no `-vga`, GTK/GL window, udmabuf and /dev/dri passed in).

## Window following and Retina (450–453)

QEMU window-size requests (stable 1 s) become a runtime CVT-RB2 EDID (src/VirtualEdid.hpp),
the virtual sink is rebuilt, the link HPD interrupt is emulated, and `connectionChange`
commits the detected link status so IODisplay reads the new EDID. macOS only offers 2x
("looks like") modes for 4K-class panels: measured 3840x2160 and 3840x2400 yes; 3200x1800,
3280x2160, 3360x2100 no; a display override plist is not re-read on hotplug. 453 therefore
keeps the panel 3840 pixels wide with the window's aspect (height 1600–2400, 60 Hz within
the 600 MHz DP DTO) and offers no other 3840-wide mode, so macOS uses the new shape.
The EDID follows the 448 EDID macOS accepted (≈163 dpi, GTF-style range limits, −V sync);
the 450 EDID (218 dpi, range-limits-only) produced 1x-only modes reported at 0 Hz.

## Measurements

| Run | Result |
|---|---|
| 449 r2 `fee8d65d…` | CORE_PROBE_PASS; one display 1920x1080 HiDPI @60; desktop in QEMU's window (screenshot); 42–45 buffers/s presented (UI-tick polling + index bug) |
| 450 b3 `7558494c…` | CORE_PROBE_PASS; window 1280x720 → 2560x1440, later 3376x2160; resize chain verified; 45/s (buffer 4 rejected) |
| 451 `fe808a72…` | CORE_PROBE_PASS; 59.2–60.0 buffers/s; 2x modes only at 3840x2160 |
| 452 `0429d186…` | CORE_PROBE_PASS; 16:9 → "looks like 1920x1080" Retina by default; 60.0/s |
| 453 `343e8eee…` | 16:10 → 1920x1200 HiDPI (3840x2400), 16:9 → 1920x1080 HiDPI, 3:2 → 3840x2400 clamp; 59.99/s each; full-field motion 60.0 distinct frames/s (15 s) and 55.1/s in three 19 s phase-aligned windows |

Hardware buffer rotation sampled at ~9 kHz: CUR_BUF 1→2→3→4 every 16.7 ms.

## Safety (after the 2026-10-11 host freeze)

The host froze silently ~30 s into launching 450 after 449's guest ended with writeback
armed and its QEMU was SIGKILLed (no stop list). Not proven causal; treated as such:
`smu-mode2-reset --execute` now runs tools/writeback-quiesce.py first (clears DWB/MCIF_WB/FC
enables, parks the MPC DWB mux, closes AGP windows carrying our base, restores the MMHUB
system aperture) and refuses the reset on failure; the guest stops writeback and closes the
window on power-off/restart and stops writeback inherited from an earlier boot. Every
later run logged "writeback quiesce" and recovered with authorizes_launch=true; no IOMMU
faults on the host.

## Boot-state dependency

The working path holds an *empty* DMCUB (`rgpudcncold`), the state after a host
suspend/resume. On a fresh boot DMCUB still runs the host firmware; 450 b2 then had no
accelerator (TTL never claimed the lease) and writeback overflowed every frame with no data.
One host suspend/resume restored the working state. Fresh-boot support is open.

## Not established

120 Hz (4K needs ODM 2:1: one pipe's DTO tops at 600 MHz), corner-exact pointer mapping
(input works interactively; HMP `mouse_move` is relative-only and could not prove it), fresh
boot without suspend/resume, three consecutive clean (verified) shutdowns, Moonlight/HDMI
audio. Evidence: [JSON](igpu-writeback-qemu-window-evidence-20261012.json).
