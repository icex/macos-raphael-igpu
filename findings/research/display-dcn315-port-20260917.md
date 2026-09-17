# Physical display: porting Apple's display core to Raphael DCN 3.1.5 — 2026-09-17

**Status:** research complete. Candidates 285/286 are built. The first hardware run froze the host
before the display core ran, and the cause is fenced off in candidate 286
([crash analysis](dcn315-dmcub-host-crash-20260917.md)). HDMI output is blocked on DMCUB (see
"Blocker" below). This document consolidates three research threads (Apple display core internals,
DCN 3.0.2 vs 3.1.5 functional differences, live host register state). Their scratch reports were
lost with `/tmp` in the reboot; the facts below were carried over from them.

Tags: **[V]** verified in a binary, a source file, the Raphael VBIOS or a live register read.
**[I]** inferred.

## 1. What Apple's framebuffer actually is

`AMDRadeonX6000Framebuffer` (24G830) embeds AMD's Linux Display Core, **DC 3.2.145**. That version
sits between Linux v5.14 (3.2.141) and v5.15 (3.2.149) **[V]**.

| Item | Address / value |
|---|---|
| Resource pools present | DCN 2.0, 2.1 (APU), 3.0, 3.02. No DCN 3.1.x. [V] |
| `dc_create_resource_pool` | 0xb31b8. Switch: 12 = DCN2.0 0xb14f6, 13 = DCN2.1 0x15ed6b, 14 = DCN3.0 0xcc8ef, 15 = DCN3.02 0x118ac3 [V] |
| `resource_parse_asic_id` | 0xb3084. Family 0x8f: rev [0x3c,0x46) → 15; [0x28,0x3c) → 14; anything else → 12. Family 0x8e rev 0x91..0xEF → 13 [V] |
| Raphael today | The unreadable strap gives `hw_internal_rev` 75, so the **DCN 2.0 (Navi 10) pool** is built. That explains `dccg2_*` / `hubbub2_*` and 16× `generic_reg_wait:513`, then `No EDID read.` and every framebuffer "Driver is offline" [V] |
| `dc_create` | 0xfea5e, called from `AmdDalServices::initialize` 0x65e06 with `init_data` = `AmdDalServices+0x598`. `hw_internal_rev` is at `init_data+0x0c`, sourced from `AmdAsicInfo::getEmulatedRevisionNum` 0x3bb02. Do not hook that accessor; it is global [V] |
| `dc_hardware_init` | 0xff053 → `hwss.init_hw` (`dcn30_init_hw` 0x106567) [V] |
| Register I/O | `dm_read_reg_func` 0x1105e9 → thunk 0x6dcb8; writes → thunk 0x6dca6 (483 call sites). The DMUB register callbacks 0x888a4/0x888b8 go through the same `cgs_device` slots: +0x40 read, +0x48 write, +0x28 context [V] |
| `generic_reg_wait` | 0x110bd7(ctx, reg, shift, mask, expected, delay_us, tries, func, line) [V] |
| Clock manager | `dc_clk_mgr_create` 0x184ce8. Family 0x8f rev 0x28..0x45 → `dcn3_clk_mgr_construct` 0xf986a (funcs 0x2bb7b8: update_clocks 0xf99dd, init_clocks 0xf93ad, enable_pme_wa 0xf9d54). `update_clocks` returns at once when `smu_present` (clk_mgr+0x1c4) is 0 [V] |
| DALSMC mailbox | send 0x8fee2, wait 0x90550. Message 0x1628a, argument 0x16273, response 0x16274, polled 200001 × 10 µs [V] |
| Renoir clk_mgr | `rn_clk_mgr_construct` 0x130a47. Mailbox 0x1629b/0x16293/0x16283 (C2PMSG_91/83/67) [V] |
| DDC / EDID | Hardware `DC_I2C` engine (`dce_i2c_submit_command` 0x175394). DDC1 registers 0x5358..0x5372. GPIO translate/factory for dcn30: 0x127ce0 / 0x10ada1. `No EDID read.` comes from `dc_link_detect_helper` 0x16f799 (at 0x16fd62) [V] |
| DMUB command tables | `bios_parser2` `transmitter_control` 0x1390a7/0x139228, `set_pixel_clock` 0x139468, `enable_disp_power_gating` 0x139800. They go to DMUB when `ctx->dmub_srv` is set and `dc+0x259` (`debug.dmub_command_table`, 1 on dcn302) is set; otherwise to the ATOM interpreter 0x5c470 [V] |
| DMCUB service | `createDmcubService` 0x884e2 → init 0x886cc (requires family 0x8f; DMUB asic = 3 + rev∈[0x3c,0x46)) → `hw_init` 0x888cc → `dmub_srv_hw_init` 0xd702a. If the ready check fails it destroys the service, and `dcn30_init_hw` then dereferences NULL `ctx->dmub_srv` at 0x106d91 [V] |
| Struct offsets | `dc`: ctx +0x308, res_pool +0x3e8, clk_mgr +0x3f0, `debug.dmub_command_table` +0x259. `dc_context`: cgs +0x18, asic_id +0x28, dce_version +0x50, dmub_srv +0x88. `dc_dmub_srv`: 0x68 bytes, dmub +0, ctx +0x58 [V] |
| HWLibs DMCU service | `_dmcub_set_fw_entry_info` 0x7a38 registers PSP DMCUB firmware only for DCN 3.0.x (strap 0x358a bit 16); DCN 3.1.x loads nothing. **Do not change this: see the crash analysis.** [V] |

## 2. Raphael silicon facts

- **VBIOS 102-RAPHAEL-008 has no display command tables [V].** Its ATOM master command list has only
  `asic_init`, `enabledisppowergating`, `getsmuclockinfo` and unnamed functions 6/19/22/53/66. It has
  no `dig1transmittercontrol`, `setpixelclock`, `digxencodercontrol`, CRTC or I2C/AUX tables. HDMI
  PHY and pixel-PLL programming exist only inside the DMCUB firmware (`DMUB_CMD__VBIOS` sub-types).
  Linux has no native TMDS PHY code for DCN 3.x either.
- **DCN reference clock is 24 MHz** (VBIOS `dce_info`: dce/i2c/dpphy refclk 2400 ×10 kHz, boot DISPCLK
  625 MHz). `dccg2_init` hard-codes 100 MHz timebases, and `hubbub2_get_dchub_ref_freq` asserts a
  40–60 MHz range [V].
- **Live host read (boot `7ee81442`, iGPU idle on vfio-pci) [V]:**
  - `HPD0_DC_HPD_INT_STATUS` SENSE=1 (the HDMI dummy plug), `DC_HPD_EN`=1.
  - DMCUB_CNTL ENABLE=1 with the timer ticking, `SCRATCH0`=0 (firmware not ready).
  - CW0/CW1 at `0x8_5e300000`/`0x8_5e33a600` (outside the carve-out); CW3 holds a VBIOS copy at VRAM
    +0x4a0000; CW4–CW6 are zero.
  - DOMAIN0–3 and DOMAIN16–18 gated.
  - OTG0 disabled with a leftover 4400×2250 timing.
  - `DENTIST_DISPCLK_CNTL`=0x001f1616 (divider 5.5, about 654 MHz), DPPCLK divider 0.
- **DMCUB firmware:** `dcn_3_1_5_dmcub.bin` version 0x05003500 (the same value the live `SCRATCH1`
  reported); a signed `$PS1` image in the same format as Apple's `_atidmcub_instruction_dcn30` [V].

## 3. DCN 3.0.2 → 3.1.5 differences that matter

**Registers:**
- Same base segments. 5,327 of 5,642 shared names keep their index [V].
- Translation must be by **name** with a drop list, never by address. Examples of 3.0.2 addresses
  that land on a *different* live 3.1.5 register:
  - `REFCLK_CNTL` → `DCCG_GATE_DISABLE_CNTL4`
  - `DCHUBBUB_GLOBAL_TIMER_CNTL` → `DCHUBBUB_ARB_FRAC_URG_BW_NOM_D`
  - `DOMAIN4..7` → DSC `DOMAIN16..18`
  - `DOMAIN9_PG_STATUS` → `DC_IP_REQUEST_CNTL`
  - `VTG0_CONTROL` → `SURFACE_CHECK1_ADDRESS_MSB`

**Pipes:** 3.1.5 has 4 pipes and 3 DSC; 3.0.2 has 5 and 5. Every instance-4 register is absent [V].

**Moved fields [V]:**
- `ODMx_OPTC_DATA_SOURCE_SELECT` (NUM_OF_OUTPUT_SEGMENT [3:2]→[9:8], SEG0..3 [11:8]..→[19:16]..);
  without the permutation `optc3_set_odm_bypass` blanks the output.
- `HUBPRET_CONTROL` (DET_BUF_PLANE1_BASE_ADDRESS, PACK_3TO2).
- `DMCUB_CNTL.SOFT_RESET` moved to `DMCUB_CNTL2`.
- Widened but compatible: OTG_OUT_MUX, DCCG_AUDIO_DTO_SEL, PHYxSYMCLK_FORCE_SRC_SEL.

**Power domains [V]:** 3.1.5 gates a whole pipe per DOMAIN i (0..3) and has no DPP domain. 3.0.2 uses
HUBP i = DOMAIN 2i and DPP i = DOMAIN 2i+1.

**Component table** (S = same, R = registers only, F = functional difference):

| Component | Class | What to do |
|---|---|---|
| clk_mgr | **F** | Replace: Raphael PMFW display mailbox, never DENTIST writes (below) |
| dccg | F (small) | Reference frequency 24 MHz; skip dccg2 100 MHz timebases and `REFCLK_CNTL` |
| hubbub | F | Reference frequency; `dcn31_init_crb` (DET0 ≥ 3 segments); APU system context (`hubbub31_init_dchub_sys_ctx`, `dcn21_dchvm_init`); watermark layout |
| hubp | R | Field remap only |
| dpp, opp, stream encoder, gpio (HPD/DDC), aux, i2c | S | — |
| optc | F | ODM select permutation; drop `OTG_BLANK_DATA_COLOR*` |
| mpc | R | Output CSC moved; RMU2 and instance 4 absent |
| dio link encoder | S (→ DMUB) | TMDS enable goes through `transmitter_control` |
| clock source | S (→ DMUB) | `set_pixel_clock` |
| hwseq init | F | Domain renumbering; disable `apply_idle_power_optimizations` (DMUB MALL) |
| audio | S + small F | Clear `DCCG_AUDIO_DTO_SEL` bit 6; power up `VPG0_VPG_MEM_PWR`; PME message 0x0D |

**Raphael display PMFW mailbox** (`dcn315_smu.c`) [V]:
- Message ID written indirectly to SMN 0x3B1050C (`MP1_C2PMSG_3`) through BAR5 0x38/0x3C
  (`PCIE_INDEX2`/`DATA2`); parameter in `C2PMSG_37` (BAR5 0x58994); response in `C2PMSG_38` (0x58998).
- Messages: GetPmfwVersion 2, SetDispclkFreq 4 (MHz), SetDppclkFreq 6, SetHardMinDcfclkByFreq 7,
  SetMinDeepSleepDcfclk 8, UpdatePmeRestore 0x0D, SetDisplayIdleOptimizations 0x12 (0 = PHY refclk on).
- The Navi DALSMC IDs mean different things here (DALSMC 0x11 = VBIOSSMC `TransferTableDram2Smu`).
- PMFW owns DENTIST on 3.1.x.
- **Caution:** this is the SMU that also governs the CPU. Treat any guest message as host-crash risk
  and agree it with the user first.

**HDMI TMDS DMUB commands in DC order** (64-byte records, type 128 `DMUB_CMD__VBIOS`) [V layout]:
1. `DIGX_ENCODER_CONTROL`(0).
2. `SET_PIXEL_CLOCK`(2): `pixclk_100hz`, `pll_id` 20, HDMI mode 3.
3. `DIG1_TRANSMITTER_CONTROL`(1): phy 0, action 1, digmode 3, 4 lanes, `symclk_10khz`, hpdsel 1.

HPD and EDID need no DMUB.

## 4. Implemented (candidate 285 → 286, branch `candidate-286`)

- **Translation tables:** `tools/gen-dcn-translation.py` generates `src/DcnTranslationTable.hpp` from
  the Linux headers: 307 moves, 1484 drops, 2 ambiguous (audio/VGA aliases, untranslated), 9 field
  remaps, the pipe-domain renumbering and the DMCUB register list. `src/DcnTranslation.hpp` and
  `tests/test_dcn_translation.cpp` hold the lookup and tests.
- **`rgpudcn=<mask>`** (1 trace, 2 translate, 4 DCN 3.02 pool, 16 inert `dc_dmub_srv` guard):
  - `dc_create` interposes the `cgs_device` slots, then (only if interposed) sets rev 60.
  - The DALSMC mailbox is emulated as "SMU absent".
  - DMCUB is fenced: `CC_DC_PIPE_DIS` reads with DC_DMCUB_ENABLE cleared, DMCUB writes are dropped.
  - Bit 8 (guest DMCUB firmware) is refused.
  - `generic_reg_wait` is named in the log. `dc_hardware_init` logs DMCUB state read-only.
- **`rgpuvd120=1`:** the 98-byte CoreDisplay 120 Hz COW patch in WindowServer (COW guard window raised
  to 128 bytes). Not yet run.
- **`tools/dcn-state-probe.py`:** read-only DCN register dump over user-owned VFIO (needs the GPU on
  vfio-pci and no QEMU running).
- **Hardware results:**
  - metal-133 (285) froze the host during PSP init.
  - metal-134 (286) is staged but not run. The expected outcome is DCN 3.02 pool init plus EDID over
    DDC1, with no picture (DMCUB absent).

## 5. Blocker and options for tomorrow

HDMI output needs DMCUB running Raphael firmware, and the guest must not start it (crash). Options,
none tried:

1. **Run metal-134** (needs `sudo ~/macos-vm/gpu-bind.sh` and user agreement). It verifies
   translation, HPD/EDID and mode enumeration safely.
2. **Learn DMCUB's windows under a working amdgpu.** The iGPU initializes under amdgpu at host boot, so
   a read-only root dump (e.g. `umr` or debugfs `amdgpu_dm_dmub_fw_state`) can show whether CW0/CW1 are
   TMR/VRAM or host RAM, and what state amdgpu's unbind leaves. That decides whether a DMCUB owned by
   the host's amdgpu (never touched by the guest) could stay usable after the handoff.
3. **Keep host-loaded DMCUB alive across the vfio handoff.** Avoid the amdgpu DMUB reset, then attach
   the guest DMUB service to the running firmware without reset or reload. The inbox/outbox and
   CW4–CW6 windows would need to be re-pointed into guest-owned VRAM. Untested anywhere; needs a
   design review with the user because DMCUB reaches memory through a secure unit.
4. **PMFW clock manager** (after 2/3): VBIOSSMC `SetDisplayIdleOptimizations(0)`, `SetDispclkFreq`,
   `SetDppclkFreq`, DPP DTO; no DENTIST writes.
5. **Remaining functional hooks:** `dcn31_init_crb`/DET, APU system context, ODM permutation already
   done, 24 MHz reference, 4-pipe caps.
