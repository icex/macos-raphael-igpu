# Candidate 298: discriminate the zero inbox read

Candidate 297 run f877ded2ff28ffbbfe241275270db0b3 read zeros from the last
four inbox slots and refused delivery. Raw SMU probe after recovery answered OK.

Hypothesis: the validated CGS read path or indirect addressing prevents observing
VRAM. Falsifier: raw and validated reads both reproduce nonzero BAR words but the
inbox remains zero; that would point away from generic indirect access failure.

Exact 24G830 framebuffer disassembly: dalAtomReadRegister32 at 0x4a054 dispatches
through context+0x30, vtable+0x148 (readValidateReg32). hwReadReg32 at 0x1c9ba
(vtable+0x140) loads BAR mapping+0x38 at index*4. writeReg32 at 0x1c946 writes
the same mapping. readValidateReg32 at 0x1ca34 calls validateHwState, which has a
saved-register fallback. This establishes a path difference, not its involvement.
Linux reference amdgpu_device.c:717 implements MM_INDEX offset|0x80000000,
MM_INDEX_HI offset>>31, MM_DATA. Candidate 297 uses that sequence.

298 compares raw and CGS reads after raw index writes, logs selector readback,
compares first BAR words and up to four nonzero words in its first 64KiB, then
samples the inbox. Selectors are restored after this diagnostic. It writes no
VRAM and the card disables DMUB delivery. Trace cap reduced from 6000 to 600;
all identity, capture, shutdown and recovery gates remain enabled.

Next: if the controls match, audit inbox backing/address domains and host handoff
lifetime. If raw matches and CGS differs, use raw reads for the indirect path with
appropriate selector serialization and restoration before any delivery experiment.

## Result

Both paths reproduce four nonzero BAR words. At four inbox header addresses,
raw MM_DATA is 0xffffffff and CGS returns 0; so the validated accessor masks failed
reads, but bypassing it does not make the inbox reachable. The inbox stayed disabled.
Clean guest-request shutdown completed. CR2 count=512/drop=5 prevented recovery
and same-boot reuse despite a successful subsequent SMU probe. See live status.

## Linux and Apple source audit; candidate 299 prepared

Linux `gmc_v10_0.c:693-703` uses PCI BAR0 normally, but on native x86 APU
(non-passthrough) replaces that aperture with get_mc_fb_offset and real VRAM size.
Thus the host journal's BAR=2048MiB does not establish a 2GiB PCI BAR; live sysfs
still exposes 256MiB. No resource0_resize file is exposed on this host.
`amdgpu_device.c:717-752` confirms the MM_INDEX/HI/DATA sequence used here.
`amdgpu_device_aper_access` prefers the CPU aperture and applies HDP coherency;
`amdgpu_device_vram_access` falls back to MM_INDEX only beyond that aperture.
Native APU success therefore does not validate this guest's high-offset MM path.

Linux `amdgpu_dm_dmub.c:654-674` allocates the DMUB region BO and records both
CPU and GPU addresses. `dmub_dcn31.c:191-218` programs CW3/CW4 directly from GPU
addresses, unlike the separately translated firmware CW0/CW1. Subtracting GFXHUB
FB_BASE for the inbox is source-supported; applying CW0's physical translation
to CW4 would not be justified by this code. The host TMR reservation on boot
90122d1c is fb+0x7e000000, size 0xa00000; inbox fb+0x7fae5400 lies beyond it.
That does not establish the exact hardware access policy for the inbox.

Apple 24G830 `AMDRadeonX6000Framebuffer` disassembly at 0x4a054/0x4a06a and
0x1c9ba/0x1ca34 establishes raw versus validated reads; candidate 298 verifies
that distinction live. HWLibs `_hdp_5_0_initialize_aperture` at 0x3a65d and
`_hdp_5_0_3_initialize_aperture` at 0x3ae2a clear aperture registers through
_gvm_write_register; register-index table decoding is still required before
attributing the failure to those writes. No speculative HDP change is applied.

Candidate 299, metal-147, adds read-only samples around 256MiB and at higher
in-range VRAM offsets (excluding the host TMR). Ordinary serial retains detailed
indirect checks, register/window dumps and command payloads; critical summaries,
readback failures and recovery records stay in CR2. This reduces optional record
pressure without enlarging the buffer or relaxing capture/recovery gates.
Built and 1004 host tests OK, dry-run clean; NOT launched. Launcher:
`~/macos-vm/run/c299-launch.sh`. Boot 90122d1c still lacks 298's recovery receipt;
user reboot and gpu-bind are required before the next cycle.
