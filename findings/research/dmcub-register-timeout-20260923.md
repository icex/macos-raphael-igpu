# Retained DMCUB register timeout, 2026-09-23

After 307 retry, host capture in `~/macos-vm/run/c307-retained-dmcub-state/`
read CW4/5/6 twice through MM_INDEX with selectors restored. All bytes matched
between snapshots. Trace contains 367 entries; last entry code34/param2. Its
private enum is not decoded, so do not assign it a power-state meaning.

FW-state at CW6+0x580 includes repeated tuples 14/60039b07/5ecf. These initially
looked like an exception record, but installed firmware disassembly instead
connects them to register-interface timeout reporting. **Do not report Xtensa
exception 14 from this tuple.** Generic exception enum14 is not evidence for
this private structure's meaning.

Installed `dcn_3_1_5_dmcub.bin.zst`, uncompressed SHA in the existing code-reference
JSON, version05003500: code starts file512, linked at60000000. Capstone6 Xtensa
provides partial disassembly; unsupported instructions are not silently decoded.

- 60034208 reads the RBBMIF_INT_STATUS fields via generic register-get helper
  60039b04. Constant60008354 points to60006bd0; its field20c contains5ffcd908,
  register3642. 60034255..60034271 writes `(saved_mask <<31)|40000000`, then
  `(saved_mask <<31)`, i.e. timeout ACK pulse preserving mask.
- 60034278 writes its two arguments via the register table600045d0 fieldsb0/b8,
  which resolve to SCRATCH13/SCRATCH15. Caller60020c10 passes the record's
  PC and 16-bit register index. Register5ecf resolves to
  DCIO_UNIPHY1_UNIPHY_MACRO_CNTL_RESERVED15; 60039b07 is in generic register-get.
- Captured scratch12=80000000, scratch13=60039b07, scratch14=80, scratch15=5ecf.
  Scratch12 bit31 is also set by firmware6002f94c..6002f955; it is not enough
  to identify an exception, instruction fault, or safe firmware restart.

Live RBBMIF_INT_STATUS=b000e808, CLIENTS_DEC=8: timeout address3a02
(DCHUBBUB_TEST_DEBUG_DATA), OP=1, RDWR_STATUS=1, MASK=1. This current timeout
is distinct from the retained UNIPHY report. Some diagnostic reads can themselves
set register-interface error flags; capture is not proof of the original cause.

308 tests exactly one source-backed timeout acknowledgement before its first
GPINT query, only for version05003500 and one of the two recorded addresses.
It preserves MASK and does not touch DMCUB enable/reset, firmware bytes, IRQ
controls, scratch registers or ring pointers. Hypothesis: an unacknowledged
register-interface timeout prevents mailbox progress. GPINT still timing out
after a successful ACK rejects the ACK as a sufficient remedy.

308 result: ACK readback c0000000 then80000000, clients cleared from8 to0.
GPINT still times out. This rejects acknowledgement alone as sufficient, without
establishing what originally caused the retained PHY timeout. CORE_PROBE_PASS,
clean shutdown, ordinary recovery authorizes reuse.

## Candidate 309 and stopped-device comparison

Fresh GPINT writes (including after accepted SMU display wake) still timed out.
Run `4f5412a582419991778ee5d78dff4dc9` passed the Metal core probe and
exited-after-guest-request; recovery authorizes the next same-boot launch.

`~/macos-vm/run/c309-retained-dmcub-state/` contains two stopped-device
read-only captures. CW4, CW5 and CW6 are byte-identical to the capture after307.
All sampled registers also match except TIMER_CURRENT. GPINT1 interrupt enable
is set (register3685=800); CNTL has PWAIT_MODE_STATUS clear. This does not
establish a live firmware instruction stream. No firmware reset/load occurred.

The last trace entry can now be interpreted more precisely using the exact
installed firmware: dispatcher600099c6 uses table60001010 indexed by command
type. Its entry128 (60001210) branches to60009ae5, which calls60011d84.
That function logs code33 with header subtype, dispatches the subtype, then
logs code34 at60011db6 with the same subtype and zero second parameter.
Linux dmub_cmd.h identifies type128/subtype2 as VBIOS_SET_PIXEL_CLOCK.
Thus final code34/param2 marks that handler returning, not an identified
power-state event or an exception. The retained inbox entry at1d40 is
80020010/00000000/14000f01/ff000000: a zero pixel-clock request.
This locates the last recorded activity in display teardown but does not
identify which later handoff operation stopped mailbox progress.

The local Linux reference unloads the PSP TMR in psp_hw_fini and frees the
DMUB buffer in amdgpu_dm_fini. It is a newer reference kernel than the running
host; these source paths are supporting hypotheses, not a captured handoff.
Further testing must distinguish that ownership transition from MODE2 and
early guest initialization; another query-only guest variant will not do so.

## Candidate 310: restore the prior host DCFCLK request

The retained clock-notification command at inbox1cc0 has dispclk480000,
dppclk472470, dcfclk1000000 and deep-sleep-dcfclk33709 kHz. The final
notification at1d80 changes dcfclk to1000 kHz. Linux dcn315_update_clocks
exits idle before restoring hard-min DCFCLK; our previous helper only exited
idle. Candidate310 adds native VBIOS SMU command7/argument1000 MHz after
version625300 and a successful command12/argument0.

Run9ce06c40d7c3535e535d2b136e3fd95c, MODE2#233: SMU response1 and returned
argument1000; subsequent fresh GPINT request still TIMEOUT. Metal probe and
capture passed; guest-requested shutdown and ordinary recovery succeeded.
CW4/5/6 in ~/macos-vm/run/c310-retained-dmcub-state remain byte-identical
to309 and307. Clock restoration alone is not sufficient.

The running host and guest discovery identify MP0/MP1 13.0.5. The local Linux
reference selects psp_v13_0 with boot_time_tmr=false for13.0.5, so
psp_skip_tmr returnsfalse for this non-VF device and psp_hw_fini submits
TMR unload. This is a specific firmware-ownership hypothesis, not proof of
exact execution on kernel7.2.5 or proof that DMCUB restart is safe.

Per the user's instruction, candidate310 remains a local candidate branch.
Neither dev nor remote dev was advanced after the instruction to hold delivery
until progress. Firmware reset/load remains prohibited pending clarification;
ordinary same-boot cleanup is working and does not itself require a reboot.
