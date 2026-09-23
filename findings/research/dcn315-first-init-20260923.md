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

## Candidate 289 (13:50): the full transaction — the EDID address is NACKed [V]
With every DC_I2C access logged (`tools/dcn-trace-decode.py`): arbitration granted
(`REG_RW_CNTL_STATUS=1`), speed written 0x780202 (prescale 120, timing 2; the host had left
0x9600102 = prescale 150, timing 1), setup enable + time limit 3, transaction0 START/STOP/
STOP_ON_NACK count 1, data 0xa0 (index write), `DC_I2C_CONTROL = 1` (GO), then
`DC_I2C_SW_STATUS = 0x1104` = SW_DONE | SW_STOPPED_ON_NACK | SW_NACK0. Three attempts, all
NACK; DAL restores the host's speed value and releases the engine. The pad mask has
CLK/DATA MASK bits 0 (hardware mode), PD_EN set as Linux does, I2C pad mode on. VBIOS: the
board's only HDMI is path 0 (DDC line 1, HPD pin 1); the other paths are three DisplayPort
connectors and an unused entry. The host reads the plug's EDID (ddcutil found EDID on the
iGPU's I2C bus at boot; amdgpu logged a sink on HDMI-A-3), so the NACK is a guest-side
difference. Remaining suspects: I2C timing (Apple assumes a 12 MHz engine clock; Linux derives
prescale from `MICROSECOND_TIME_BASE_DIV`, and the host's value implies a different clock) and
something the host driver configures that DCN 3.0 code never touches. Candidate 290 (bit 64,
`rgpudcn=119`) replays the host's speed value on every DDC1 speed write and logs
`MICROSECOND_TIME_BASE_DIV`.

## Candidate 290 (14:15): the host's bus timing does not help; the engine clock matches [V]
`MICROSECOND_TIME_BASE_DIV = 0x120218` (time base 24 MHz, XTAL_REF_DIV 2, xtal ref selected):
Linux's `set_speed` gives prescale (24000/2)/100 = 120, exactly Apple's value, so the 0x96 the
host left behind was from a slower transaction, not a different clock. With the DDC1 speed
forced to the host's 0x9600102 the transaction still ends `SW_DONE|SW_STOPPED_ON_NACK|SW_NACK0`.
Every guest-side register the trace can show now matches the Linux sequence.
Next evidence must come from the host: `tools/host-ddc-trace.sh` (root, iGPU on amdgpu, i.e.
after a reboot and before gpu-bind) records the `amdgpu_dc_rreg/wreg` tracepoints while the
connector is re-detected, and `tools/dcn-trace-decode.py --host-trace` names the registers, so
the host's DDC read can be diffed against the guest's. Until then the display path stays
"initialised, no sink"; candidate 290 is a complete VM (audio, LAN, Metal) for daily use.

## 15:40 — EDID reads work; the earlier NACK was the plug, not the guest [V]
On the fresh boot c8a7ed8f (candidate 290, attempt lan2) the guest's boot-time DDC1 read
returned a valid 128-byte EDID from the dummy adapter (vendor "BBC", product 0x104, serial
0x99999999, 2018, one extension, checksum OK) and, after the user hot-plugged the Samsung, a
second detection read the Samsung's EDID (manufacturer bytes 4C 2D) plus extension blocks and
DDC/CI traffic at 0x37. The same transaction sequence had been NACKed on boot c0abc1a2 in every
run (287–290). Most likely the adapter's EEPROM was left mid-transaction by the host freeze that
morning and stayed locked until it was unplugged. Candidates 288–290 therefore tested
non-causes; their tooling (full I2C trace, decoder, host trace script) stays.
- After detection the framebuffer still publishes `display-type NONE` on every connector and
  no AppleDisplay appears. Init already logged "Error queuing DMUB command: status=4 / Error
  starting DMUB execution" from the inert `dc_dmub_srv`: the link path (DIG/PHY via DMUB
  command tables) is the next blocker, as predicted. The host-loaded DMCUB is still booted
  (`SCRATCH0=0x43`), which makes "attach DAL to the running firmware" the next design.

## 16:20 — survey of the DMCUB the host left running (candidate 291, read-only) [V]
- Alive: `DMCUB_TIMER_CURRENT` advances ~29k ticks/ms before and after DAL init; CNTL 0x900c6,
  SCRATCH0 0x43 (DAL_FW | MAILBOX_READY | 0x40) unchanged; no fault addresses latched.
- Inbox1 base 0x64000000 size 0x2000, WPTR = RPTR = 0x1bc0 (idle). Outbox1 0x64002000 idle.
- Windows (DMCUB space -> MC): CW0 inst [0,0x3a51f) and CW1 stack/data -> 0x8_5e30_0000 /
  0x8_5e33_a600 (outside the FB aperture: the PSP-loaded protected region); CW3 VBIOS
  fb+0x2da600, CW4 mailbox fb+0x2e5400, CW5 trace fb+0x2e9400, CW6 fw state fb+0x2f9500 — all in
  the first 3 MB of the carve-out and BAR0-visible. REGION4/5 point at the same trace/data.
- Ring dump missed: CWn_BASE/TOP omit the 0x60000000 prefix of the inbox address; fixed in 292.
- Compatibility: DMUB command header and the VBIOS command IDs/structs (encoder control 0,
  transmitter control 1, set pixel clock 2) are identical between Linux v5.14 (Apple's DC
  3.2.145 era) and current, so Apple-built commands should be accepted by the dcn315 firmware.

## Candidate 292 (built, not run): DMUB path hooks
Apple's dc_dmub_srv_cmd_queue 0x1b06de / execute 0x1b0756 / wait_idle 0x1b0797 are replaced.
`rgpudcn` 256 = log every command, report success, write nothing (card metal-140, 407). 512 adds
delivery of VBIOS-type commands into the live inbox1 ring (fb+0x2e5400) plus an INBOX1_WPTR
write, with a full-ring check, 100 ms RPTR wait and fail-closed disable on the first timeout.
Launch needs the user's go-ahead: the session's permission check refused to launch it.
