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
