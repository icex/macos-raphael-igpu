# Preserve host DMCUB memory from the guest TMR

299 run b4ca8c0ec8070df1cf55970438b07ccd: guest wire SETUP_TMR uses
MC 0xf47f400000 / size 0xa00000, acknowledged success. Inbox CW4 is
MC 0xf47fae5400, inside that protected region. Raw CPU access returns all-ones,
while addresses above the PCI BAR boundary remain readable. This is direct
interval-overlap evidence and a causal hypothesis, not yet a successful fix.

24G830 sources/disassembly under ~/macos-vm/re/decompiled-24G830/HWLibs-full:
- gmmCbReserveFbMemory, b2950: adds 1MiB-rounded input size to self+0x4d0.
- gmmCbSetMemoryAttributes, b1590: memory type 0 with flag 1 sets total at
  self+0x498, nonvisible cursor at self+0x4c0 = total-reserved, and adds reserved
  to self+0x4c8. CPU-visible size is self+0x4a0. Total is not reduced.
- gmmCbAllocateLocalGpuMemoryInit, b16f0: nonvisible requests descend from
  self+0x4c0, add their consumption to self+0x4c8, and return MC base+cursor.
- psp_tmr_init, 52bbd: allocates the TOC-requested 10MiB TMR through the above
  native path (psp_cgs_alloc_memory type 2 = local nonvisible; type 1 is its
  native visible fallback). No firmware load patch is needed.

300 hooks b1590 with an exact entry check, surveys CW0/1/3/4/5/6 through raw
register reads, translates physical firmware offsets and MC mailbox offsets,
rounds the earliest window down to a 32MiB boundary, and requests the missing
native tail reservation through b2950. Total VRAM, hardware registers and recovery
lease rules remain unchanged. It checks the native cursor/accounting afterward;
PSP TMR init refuses if the guard is not ready. Windows below the visible BAR or
outside discovered VRAM are unsupported and fail closed. The allocation planner
has bounds/overflow and overlap tests. Card metal-148 keeps delivery disabled.

Expected on this boot: preserved tail 0x7e000000..0x80000000, guest TMR below
0x7e000000, then usable host ring headers. Firmware code is never loaded, started
or reset by this change. If prior guest TMR writes destroyed the inbox contents,
that hypothesis requires additional evidence; it does not establish a reboot requirement.

## 300 hardware result

Native reservation ready: tail 32MiB, additional 30MiB, cursor 0x7e000000,
accounted 32MiB. SETUP_TMR moved to MC 0xf47d600000 / 0xa00000. Inbox raw
reads changed from 0xffffffff to zero; the sampled old command headers read as zero. Erasure is not established.
CORE_PROBE_PASS, 419 critical records with no loss, clean guest shutdown and
authorizing recovery. The zero reads alone do not establish whether the inbox is writable. This run establishes reservation behavior and
removes the access denial; it does not establish HDMI output.

## Correction: reboot is not established as necessary

Candidate 300 has an authorizing recovery receipt and a successful post-run SMU
probe. The earlier request to reboot inferred erasure from zero reads and the
previous TMR overlap. Those observations do not establish either erasure or a
reboot requirement. Same-boot cycles remain admitted by the existing harness.
The current retained-header check is our diagnostic guard, not a firmware
requirement that old command bytes be nonzero. Investigate address/access and
ring validation without relaxing the firmware-load/start/reset prohibition.

## Candidate 302: validate an empty ring without retained commands

Local Linux dmub_cmd.h defines dmub_rb_empty as RPTR == WPTR. Its
dmub_rb_push_front copies a new 64-byte command at WPTR; dmub_srv.c
dmub_srv_fb_cmd_execute reads back pending commands before publishing WPTR.
There is no requirement for the previous command bytes to be nonzero.

302 retains the old-header check and adds a fallback only for an empty, aligned,
bounded CW4 inbox inside the verified native reservation, with a running timer
and initialized firmware status. It writes two complementary patterns to the
unsubmitted slot, reads every word, restores all 64 bytes, and checks restoration
and unchanged pointers. It never advances WPTR for this probe. Only a complete
pass enables command delivery. Every delivered command now reads back all 16
words before publication (previous code checked only its header). Failed checks
refuse delivery. No firmware load/start/reset or host rebind is introduced.

Hypothesis: old-header contents are an overly restrictive accessibility test.
Falsification: failed write/readback or restoration; successful readback followed
by a delivery timeout would instead establish accessible CPU memory without
proving a working firmware consumer. Candidate 301 was prepared but not launched.

## Candidate 303: independent firmware liveness query

302 proved inbox CPU access but RPTR did not consume the first 64-byte command.
A running hardware timer and retained SCRATCH0 bits are not proof that firmware
is executing its command loop. Linux dmub_srv_send_gpint_command with
DMUB_GPINT__GET_FW_VERSION=1 writes 0x10010000 to DATAIN1 and waits for
0x00010000 acknowledgment; dmub_dcn31_get_gpint_response reads SCRATCH7.
DCN315 offsets resolve to register indices 0x36b8 and 0x36aa.
303 queries before and after native display init, refuses a busy GPINT channel
or disabled/reset firmware, and never changes firmware execution controls.
Inbox delivery is disabled for this diagnostic. A GPINT ACK distinguishes a
responsive processor from an inbox-specific problem; timeout alone does not
identify the cause. No same-boot reset/restart of DMCUB is attempted.

## Candidate 304: exit display idle through the VBIOS SMU mailbox

Linux dcn315_clk_mgr.c enters mission mode with idle_info=0 through
dcn315_smu_set_display_idle_optimization. dcn315_smu.c uses message 0x12
and the separate VBIOS mailbox: message SMN 0x03b1050c (C2PMSG3), parameter
0x03b10994 (C2PMSG37), response 0x03b10998 (C2PMSG38). The latter two match
MP1 base 0x16000 + offsets 0x265/0x266 in mp_13_0_5_offset.h. These are not
the driver mailbox's message IDs or registers.

304 uses the existing identity-checked CGS SMN transport and VCN SMU lock.
It first queries VBIOS GetPmfwVersion=2 and requires the known 0x625300 firmware
version, then sends only SetDisplayIdleOptimizations(0). It attempts once, after
the normal VCN power setup has validated the transport. A successful response
triggers another GPINT version observation; a pending version query is polled
without replacing it. No firmware load/start/stop/reset or DMCUB control write.
Failure/timeout/version mismatch suppresses the wake request as appropriate.
Unit tests cover mailbox sequence, busy timeout, version timeout/mismatch and
wake rejection. This tests normal display power state, not firmware restoration.

## 303–304 results and remaining recovery boundary

303 GPINT GET_FW_VERSION timed out; 304 VBIOS SMU version and normal display-idle
exit both succeeded, but GPINT still timed out. CNTL=0x900c6 has ENABLE=1 and
PWAIT=0; CNTL2=0, SEC_CNTL=0x2000 has SEC_RESET_STATUS=0. Interrupt enable
0x800 includes GPINT1, and LS_WAKE_INT_ENABLE=0x900c80 includes that source.
These observations exclude disabled/reset firmware and the tested normal idle
exit as sufficient explanations, but do not identify an exact firmware failure.

The local original igpu-vbios.rom has master command table at 0xa470. Table
indices 4 (digxencodercontrol), 12 (setpixelclock), and 76 (dig1transmittercontrol)
have zero offsets. enabledisppowergating index13 exists at0xaa44. Thus Linux's
legacy ATOM route cannot supply all missing display commands on this VBIOS.
The documented remaining DMCUB recovery resets firmware, prohibited here.
Host reinitialization was requested after these checks, not from zero inbox bytes.

Before next delivery, audit existing wrapPspTmrInit: it unconditionally unloads
the old TMR under XC before native LOAD_TOC/setup. Host CW0/1 code/data are in
the host TMR at fb+0x7e300000; native reservation protects allocation but may
not preserve PSP TMR ownership. Query before/after that sequence to locate the
first loss of firmware responsiveness. Do not claim this hypothesis proven.

## Candidate 305 preparation

GPINT queries now use the existing audited raw AmdRegisterAccess vtable path,
which is available before DCN's CGS context is installed. Observations bracket
PSP TMR unload, native LOAD_TOC/allocation, SETUP_TMR and the early IP loads.
The LOAD_TOC function does not itself issue SETUP_TMR: decoded psp_tmr_init
(0x52bbd) performs TOC/allocation, psp_tmr_load (0x52dae) submits wire5 later.
Queries at the next buffer-preparation boundary observe prior wire5/IP results.
No PSP behavior is changed. Delivery additionally requires a fresh successful
GPINT version response, alongside the preserved reservation and ring readback.

Also audit the host handoff: local Linux psp_hw_fini calls psp_tmr_terminate on
unbind, while dm_sw_fini destroys the DMUB service. Thus a host reboot is not a
guarantee of retained firmware after handoff; early liveness evidence is required
before attributing a failure to guest PSP transitions. Existing retained scratch
registers and the hardware timer do not establish firmware command-loop health.

User observation for candidate 302: Samsung showed **No signal**. This confirms
the physical-output failure independently of its passing offscreen Metal probe.
