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
