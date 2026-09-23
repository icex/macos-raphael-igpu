# DCN 3.1.5 display core: first hardware init, and the EDID read that returned 0xFF — 2026-09-23

**[V]** verified live (candidate 287, card metal-135, run attempt `b3`, boot `c0abc1a2`).

## Host freeze #2 (12:56, boot 67ab8c3f) — before the display code ran
The first candidate 287 launch froze the host about 8 s into the guest boot. The serial log
(`run/candidate-287-results/crash-evidence/`) ends mid-line in the IP-discovery/PSP firmware
phase; no `DCN: cgs` line, so the display hook never ran. No kernel message, no pstore. This
is the same phase as the candidate 285 freeze that was attributed to the DMCUB registration;
candidate 287 contains no DMCUB code. Common factor now: that host boot had been **suspended
overnight with the iGPU on vfio-pci** (first sleep in that state). Working rule: after a host
suspend, reboot before any GPU run. The same candidate booted cleanly on the fresh boot.

## What the display core did on hardware [V]
- `cgs` slots: read `0xffffff7f8eaff054`, write `...06a` (auxiliary collection) → interposed.
- `dc_create`: family 0x8f, `hw_internal_rev 75 -> 60`, DCN 3.02 pool built.
- `dc_hardware_init` ran to completion: 538 trace lines at that point, 108087 dropped accesses
  (DCN 3.0.2 registers with no 3.1.5 equivalent), 393 unique registers; 34 named waits, none
  fatal; no guest panic, no host fault; Metal desktop came up, USB audio and LAN as before.
- DMCUB was left untouched and reads `CNTL=0x1900c6 SCRATCH0=0x43` before and after init:
  boot status BOOTED|MAILBOX_READY|DETECTION_REQUIRED — the host driver's firmware from this
  boot is still running. DALSMC message 2 was answered "failed" by the emulated mailbox.
- Detection: `DC_GPIO_HPD_*` programmed, `HPD0_DC_HPD_INT_STATUS = 0x660eb012` (sense = 1, the
  dummy plug on HDMI). The DP connectors' AUX transactions (`DP_AUX2/3/4`) time out (240 tries),
  expected with nothing attached. The HDMI EDID read used the hardware I2C engine on DDC1:
  `DC_GPIO_AUX_CTRL_5` keeps `DDC_PAD1_I2CMODE=1`, `DC_GPIO_DDC1_MASK=0xcf401010`
  (CLK/DATA PD_EN, STR), `DC_I2C_DDC1_SPEED` prescale 0x78 threshold 2, SETUP enable+time limit
  3, transaction START/STOP/STOP_ON_NACK count 1, DATA index-write 0xa0, `SW_STATUS=4`
  (SW_DONE), then the read transaction returned `DC_I2C_DATA = 0x2ff01` → data byte **0xFF**
  → DAL logs "No EDID read." All four connectors stay `display-type NONE` in IOKit.
- VBIOS (`igpu-vbios.rom`, object table v1.4, gpio_pin_lut v2.1): HDMI path uses I2C
  line_mux 0 (gpio id 0x90 = `DC_GPIO_DDC1_A` 0x5d91) and HPD pin 1 (bit 0 of
  `DC_GPIO_HPD_A`, the `HPD0_*` registers). So DAL picked the same line the host driver would.
  DDC GPIO and DC_I2C register indices are identical in the 3.0.2 and 3.1.5 headers; only
  `DC_I2C_INTERRUPT_CONTROL` lost its fields and `DC_GPIO_HPD_EN/MASK` gained RX_HPD fields.

## Why 0xFF (open)
The engine completed without a NACK stop but read bus-idle 0xFF: the EEPROM did not answer.
Candidates: the I2C reference clock (DAL's prescale assumes the Navi xtal; Raphael's reference
is 100 MHz, so the bus may run ~4x faster than intended), the pad pull configuration
(`PD_EN` bits), or a pad/power enable that DCN 3.1 needs and DCN 3.0 code never writes. The
decisive evidence is the host driver's register values after it reads the plug's EDID:
`DC_I2C_DDC1_SPEED/SETUP`, `DC_GPIO_DDC1_MASK/A/EN`, `DC_GPIO_AUX_CTRL_5`, and whether
`/sys/class/drm/card*-HDMI-A-*/edid` is non-empty on the host at all. That needs a host reboot
(the GPU is on vfio-pci) and then `tools/dcn-state-probe.py --regs '^DC_I2C_DDC1|^DC_GPIO_DDC1|^DC_GPIO_AUX_CTRL_5'`
after `gpu-bind.sh` and before any guest run.

## Root-cause candidate for the 0xFF: I2C engine memory in forced light sleep [I→V pending]
- The VBIOS `dce_info` v4.4 gives `i2c_engine_refclk_10khz = 2400` (24 MHz): DAL's prescale
  0x78 = 120 → exactly 100 kHz. The clock is right.
- Linux's DCN 3.1 init (`hwss/dcn31/dcn31_hwseq.c`): "Power on DIO memory (AFMT HDMI) and set
  I2C to light sleep" via `dio->mem_pwr_ctrl`, and `dce_i2c_hw.c` clears
  `DIO_MEM_PWR_CTRL.I2C_LIGHT_SLEEP_FORCE` before a transaction, waits for
  `DIO_MEM_PWR_STATUS.I2C_MEM_PWR_STATE == 0`, and sets the force again after it. The host
  driver ran before the handoff, so the engine memory is left in forced light sleep.
- Apple's DCN 3.0 I2C path never touches `DIO_MEM_PWR_CTRL`: zero accesses in the trace. A
  sleeping engine memory explains a transaction that "completes" (`SW_DONE` already set) with
  0xff data. Register indices and fields are identical in both headers (0x539d/0x539e).
- Candidate 288 (`rgpudcn` bit 32, card metal-136 with `rgpudcn=55`) clears the force, sets
  `I2C_LIGHT_SLEEP_DIS`, polls the state after `dc_hardware_init`, and logs before/after.

## Candidate 288 result (13:24): the I2C memory was not asleep [V]
`DCN: DIO I2C memory: CTRL 0 -> 0x2, STATUS 0xf8 -> 0xf8 after 0 polls`: `I2C_LIGHT_SLEEP_FORCE`
was already 0 and `I2C_MEM_PWR_STATE` 0 (powered; only the DP A–E memories sleep). The EDID read
still returned 0xff. Hypothesis rejected. Note the tracer logs only the first two accesses per
register, so the I2C transaction (GO write, status polls, data reads) is mostly invisible;
candidate 289 logs every access in the DC_I2C and DIO/GPIO pad blocks.
