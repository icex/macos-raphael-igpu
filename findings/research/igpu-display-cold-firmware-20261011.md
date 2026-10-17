# Candidates 445–446: display engine without the host's display firmware

Goal (user, 2026-10-11): the iGPU drives its own display and QEMU shows that output directly,
with no mirror, no second display and eventually no HDMI plug.

## Recovery after 445 without a reboot

445's native recovery failed only because the accelerator never claimed its lease. The
documented stopped-device path (`tools/mode2-noqueue-recover.py`: inspection, then `--execute`)
recovered the device on the same boot (schema 9, `authorizes_launch=true`, no kernel faults),
and 446 was admitted from that receipt.

## 445 root cause: firmware-identity reservation

445's critical records show `HOSTRESERVE: invalid framebuffer or DMCUB identity … boot=0
held=0` and `refusing PSP TMR init`, so TTL failed. After many MODE2 cycles this boot, the
host-loaded display firmware (DMCUB) is empty (CPU in reset, no windows). 330 had run with it
still held from the host's amdgpu (`CNTL=0x800c6`). Only the console path knew how to hold an
empty image.

## 446: `rgpudcncold=1`

Opt-in, refused together with the console or with any guest DMCUB
load/reinit/resume/query. It reuses the console's empty-firmware hold and reservation plan
and routes PSP TMR init through the same reserved-memory/held-firmware proof. Card metal-240 =
445 minus `rgpudmubpsp/reinit/resume/query`, plus `rgpudcncold=1`. Build
`7894395e8b304bb4aa138557a0532703`, MODE2 348, run `92a8ce9475c6f3a57fe37fa82b32efdc`.

- Fixed: `DCNCOLD` accepted; `CONSOLE: empty firmware reset hold=1`; native tail reserved;
  `TTL::initialize() Completed`; `XH2 POOL state=ACTIVE`; GPU submissions ran.
- New blocker: the desktop stalled after ~1,237 command buffers; the Metal probe never
  completed (`probe_completion_missing`).
  - The IH ring was healthy: RPTR followed WPTR at ~121 entries/s.
  - HUBP0 had been programmed with surface `0xf4323d0000` (ARGB2101010, `SW_64KB_R_X`, 3840×2160,
    ~803 MiB into the carve-out, outside BAR0). `SURFACE_INUSE=0`, no flip pending, no
    outstanding requests, `UNDERFLOW_STATUS=3`: the pipe had stopped fetching, so flips never
    completed.
  - OTG0 timing was CTA 4K60 (4400×2250), but its frame counter advanced at 121 Hz. The pipe is
    in 2-pixels-per-clock mode (`OTG_H_TIMING_DIV_MODE=1`, OPTC data format 2) with
    `OTG0_PIXEL_RATE_CNTL=0x8000c000` (DIO FIFO error bits set), DP DTO and DTBCLK DTO
    unprogrammed, and `HDMISTREAMCLK_CNTL=0`.
  - DAL chose HDMI 2.1 FRL for 4K 10 bpc. The transmitter/encoder VBIOS commands that the
    running firmware executed in 330 (24 delivered) are log-only here, so the PHY and FRL
    stream clocks were never configured.
  - `COMPBUF` is at its reset default 2 segments (`0x40202`), versus 13 left by amdgpu in 330.
- Lifecycle: interactive stop → guest could not answer (agent stuck in the probe) → forced
  stop; native recovery `recovered`, `authorizes_launch=true`.

## Direction for the no-plug display

Physical HDMI needs the display firmware or our own PHY/FRL programming, and it isn't what the
user wants anyway. AMD DC's virtual signal type (as Linux amdgpu uses for a forced-on
connector via an emulated sink) takes the pixel clock from the DP DTO and needs no PHY, link
training or DMCUB, while OTG/HUBP scan out normally. Next candidate:

- emulate a virtual sink with our own EDID (8 bpc, standard 60/120 Hz modes) on a connector
  with no HPD;
- program the remaining DCN31-only state ourselves (COMPBUF = 16 − DET segments).

QEMU then needs a guest-RAM copy of the tiled scanout. The surface is tiled, 10-bit (unless the
EDID limits it to 8 bpc) and outside BAR0.
