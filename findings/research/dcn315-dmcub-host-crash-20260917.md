# Host freeze from guest DMCUB firmware registration — 2026-09-17

Candidate 285 / metal-133 froze the whole host about eight seconds into the
guest boot. The guest reached HWLibs TTL/PSP initialization; the display core
never ran. The only new behaviour that executed was the registration of
Raphael's DMCUB firmware for PSP (`rgpudcn` bit 8). That path is removed and the
guest can no longer program DMCUB.

## Evidence

- **Boots.** `7ee81442` ended 16:06:21 (last journal line). The next boot,
  `365fcd4e`, started 16:12:28 after a manual power cycle.
- **Nothing recorded the failure.**
  - No kernel message in the final seconds.
  - No pstore record (`efi_pstore` enabled, `hardlockup_panic=1`, `panic=20`, yet no
    automatic reboot).
  - No MCE, APEI or BERT record on the next boot.
  - No AMD-Vi, vfio or AER message.

  Together this points to a platform freeze, not a kernel panic.
- **Launch.** Container `251669a2` started 16:06:14.6 after a successful MODE2
  reset `#188`. OpenCore left boot services at 16:06:29 guest time (the host
  journal flush trails real time).
- **Serial (`run/serial.log`).**
  - The plugin logged `rgpudcn=0x1f` and installed the display-core routes
    (`generic_reg_wait`, `dc_create`, `dc_hardware_init`) and
    `_dmcub_set_fw_entry_info`.
  - HWLibs then printed `AMD Error: Firmware atidmcub_raphael.dat not found in
    directory` and `Unable to get firmware atidmcub_raphael.dat`: the expected
    file miss before `_dmcub_load_fw` uses the staged buffer. This proves the
    registration ran.
  - The last output is the TTL IP table, `gvm_get_ip_function`, and an AMDLOG
    `psp_hardware_initialization finished loading PSP FWs`.
  - No `DCN: dc_create` line exists, so register translation never executed.
- **Critical records.** They stop at the route installs (records are flushed in
  batches).
- **Prior runs.** Around 186 same-boot runs with the same configuration minus
  `rgpudcn` were stable.

## Mechanism (inferred, not reproduced)

- **Code and data windows outside the carve-out.** DMCUB executes from PSP-owned
  windows. After the host's amdgpu session, a read-only probe showed:
  - `DMCUB_REGION3_CW0` / `CW1` at `0x8_5e300000` / `0x8_5e33a600`, outside the
    VRAM carve-out `0xf4_00000000–0xf4_7fffffff`;
  - `DMCUB_SEC_CNTL.DMCUB_MEM_UNIT_ID = 0x20`.
- **What loading can do.** Loading or starting DMCUB firmware through PSP from the
  guest can therefore do one of two things:
  - wedge PSP/SMU, which is platform firmware shared with the host CPU;
  - let DMCUB reach host memory through its secure unit, bypassing the IOMMU.

  Either explains a silent whole-machine freeze. Deliberately reproducing it
  would violate the host-safety rule against provoking host lockups, so the exact
  step (PSP load versus DMCUB release) is not isolated.

## Changes

- **Firmware path removed.** The `rgpudcn` bit 8 path (embedded
  `dcn_3_1_5_dmcub.bin`, HWLibs `_dmcub_set_fw_entry_info` route) is gone, and the
  bit is refused.
- **DMCUB fenced off while the DCN 3.02 pool is active:**
  - `CC_DC_PIPE_DIS` reads with `DC_DMCUB_ENABLE` cleared, so Apple's
    `dmub_srv_has_hw_support()` fails and the DMUB service never initializes
    hardware;
  - every DMCUB register write is dropped and logged.
- **Pool change tied to interposition.** The DCN 3.02 pool (which brings Apple's
  DMUB service) is selected only after the `cgs_device` interposition that enforces
  the fence is in place. `rgpudcn` bits 2 and 4 must be set together.
- **Guest boundary.** HDMI transmitter and pixel-clock programming need DMCUB on
  Raphael (the VBIOS has no command tables). That work cannot proceed from the
  guest until DMCUB's windows and boot path are shown to stay inside
  guest-reachable memory, without a guest-initiated DMCUB start.
