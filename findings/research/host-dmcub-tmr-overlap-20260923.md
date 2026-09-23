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
a fresh host boot may still be necessary; the header guard will not be bypassed.
