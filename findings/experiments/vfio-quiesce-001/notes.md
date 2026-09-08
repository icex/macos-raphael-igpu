# Rootless full-engine quiesce validation

Date: 2026-09-08. Host boot: `851d35df-7e63-4154-b70b-5cfa044913d6`.
Source guest run: `5b0cf5a6c14b427ab05449f290b3c960` (the third candidate-166 launch).

This validation did not start a VM and does not authorize another launch. The boot's
three-launch ceiling was already exhausted.

The first attempt failed closed because `SDMA0_F32_CNTL` used `0x4980` from the generated
Navi register header's base-address comment. Apple `sdma_5_2_stop_engine` addresses SDMA0 as
hardware block `0x23`, base index zero, register `0x2a`; Linux resolves the same operation
through IP discovery. Raphael's live segment-zero base is `0x1260`, making the BAR5 byte
offset `(0x1260 + 0x2a) * 4 = 0x4a28`.

With the corrected discovery base, the rootless VFIO transaction reported:

- `SDMA0_CNTL.AUTO_CTXSW_ENABLE`: cleared (`0x400c3` to `0xc3`)
- `SDMA0_GFX_RB_CNTL.RB_ENABLE`: cleared (`0x80888021` to `0x80888020`)
- `SDMA0_GFX_IB_CNTL.IB_ENABLE`: cleared (`0x101` to `0x100`)
- `SDMA0_F32_CNTL.HALT`: set (`0` to `1`)
- graphics CP halt readback: `0x15000000`
- MEC1/MEC2 halt readback: `0x50000000`
- active HQDs after cleanup: zero
- PSP destroy-all-rings response: `0x80030000`
- PSP destroy-GPCOM response: `0x800c0000`
- PCI command before/after: `0x0003`; bus mastering stayed disabled

The device remained bound to vfio-pci and no sudo or amdgpu rebind was used. The full
machine-readable record is [evidence.json](evidence.json).

This record does **not** prove full quiescence. Linux's legacy VFIO open and close paths call the
PCI reset machinery, and the iGPU exposed only the `bus` method. The kernel's `resetting` / `reset
done` messages therefore identify an implicit shared-bus reset, not harmless close telemetry.
That reset happened before BAR5 inspection, so `active_before = 0` cannot be attributed to this
transaction. The record does validate the corrected SDMA offsets and their readbacks, plus both
PSP responses, after the reset. Candidate 168 now requires `reset_method` to be empty before any
VFIO open and rejects these reset messages. A new reset-disabled run must establish cleanup and
warm reinitialization.
