# Candidates 447–448: plug-free iGPU display through an AMD DC virtual sink

Goal (user, 2026-10-11): the iGPU drives its own display and QEMU shows it directly, with no
mirror, no second display and no HDMI plug. 446 showed that the HDMI path cannot work without
the display firmware (PHY/FRL clocks unprogrammed, 121 Hz, no fetch).

## Design

Apple's 24G830 DAL keeps AMD DC's virtual signal (0x200). Reverse engineering of the
framebuffer kext is in [the plan](igpu-virtual-sink-plan-20261011.md). Stream enable returns
early for that signal (no PHY, link training or DMCUB), and resource mapping gives it the DP DTO
clock source. `rgpuvirtualsink=1` (requires `rgpudcn` + `rgpudcncold`, no console):

- `dc_link_detect` (0x16f799) reports the first HDMI connector as connected to a
  `dc_sink_create` sink with signal 0x200 and a built-in 128-byte EDID ("Raphael VD", 8 bpc,
  3840×2160@60 and 2560×1440@60 CVT-RB, 1920×1080@60/120). Every other connector reports
  disconnected.
- DCN3 `program_pix_clk` (0xc90a1) presents the virtual stream as DP for the call, so only the
  DP DTO registers are written (not VBIOS SetPixelClock). It corrects `clk_mgr` dprefclk from
  Navi23's 730 MHz to Raphael's 600 MHz.
- After `dc_hardware_init`: `DCHUBBUB_GLOBAL_TIMER_ENABLE` (Linux `dcn31_init_hw`; Apple's
  DCN3.02 init never sets it). Once DET0 is 3 segments, COMPBUF is set to 13 segments (Linux
  `hubbub31_program_compbuf_size`).

## Results (same boot, dummy HDMI adapter still attached but ignored)

| Run | Change | Outcome |
|---|---|---|
| 447 `69c67242…` | virtual sink + DTO path | One sink (link 0, 0x340c), three DP connectors disconnected; 533.25 MHz via DP DTO; OTG 4000×2222 at **49.4 Hz** (modulo 730,000,000); HUBP made no requests; flips never latched; probe hung. Forced stop; recovery authorized reuse. |
| 448 `aba7858f…` | + global timer, 600 MHz DTO reference, COMPBUF 13 | **CORE_PROBE_PASS**, `windowserver_accelerator_client=true`. macOS shows exactly one display, "Raphael VD", Metal 3, 3840×2160 backing / 1920×1080 HiDPI, **60 Hz**, mirror off. OTG measured **59.99 Hz**. WindowServer 0.6% CPU. With the display awake, three surfaces flipped in 3 s and the latched address matched (`ARGB2101010`, `SW_64KB_R_X`, outside BAR0). No underflow. |

The idle display slept (`IODisplayWrangler` power state 1, pipe power-gated) until a
user-activity assertion woke it.

Lifecycle 448: guest-request shutdown (`exit-unverified-after-request`), native recovery
recovered, `authorizes_launch=true`.

## Not yet done

- QEMU does not show this display yet. The scanout is tiled 10-bit in the carve-out, beyond
  the 256 MiB BAR0, and BAR0 reads are uncached (~22 MB/s, 445). It needs a per-flip GPU copy
  into guest-visible RAM read by a QEMU console that belongs to the vfio device, with no
  guest-visible display device.
- Keep the display awake while a viewer is attached. Pointer/keyboard mapping onto the single
  display. 120 Hz modes need a DisplayID/CTA extension for 4K120.
- The dummy plug is ignored by design and can be removed.
