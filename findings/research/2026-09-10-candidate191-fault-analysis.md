# Candidate 191 first-submission fault analysis

## Result

The frozen run is valid and the Metal probe timed out with zero completed
command buffers. The first retained nonzero GFXHUB fault is
`status=0xb0093a addr=0x400300000`. This is **VMID 11**, so the current
VMID1-only recorder rejected the exact fault that needs a page-table walk. The
evidence proves a diagnostic coverage defect; it does not yet prove a root or
entry conversion defect.

Frozen inputs used here are
`/home/bogdan/macos-vm/run/metal-025-191/{events.jsonl,critical.txt,serial.txt,probe.json,recovery-replay.json}`.
Their SHA-256 values are respectively `d0ed8ac6...c95`, `d3ac2d3b...d71`,
`5c791de2...62d`, `c6936970...665`, and `063fa53c...041` as recorded directly
from the files. `verdict.json` reports `EXECUTION_FAILED` at
`first_submission`; `probe.json` reports zero completions and a five-second GPU
completion timeout.

## Exact status decode

The pinned Linux GC 10.3.0 definitions in
`/home/bogdan/macos-vm/ref/linux/gc1036/asic_reg/gc_10_3_0_sh_mask.h:11563-11582`
assign MORE bit 0, WALKER bits 1-3, PERMISSION bits 4-7, MAPPING bit 8, CID
bits 9-17, RW bit 18, ATOMIC bit 19, and VMID bits 20-23. Applying those masks
to `0xb0093a` gives:

```text
MORE=0 WALKER_ERROR=5 PERMISSION_FAULTS=3 MAPPING_ERROR=1
CID=4 RW=0 ATOMIC=0 VMID=11 VF=0 VFID=0
```

The field names establish a read-side, non-atomic mapping/walker fault in client
VMID 11. Linux's current primary `gfxhub_v2_1.c` client table maps CID 4 to
`CPF`, the command-processor front end:
<https://raw.githubusercontent.com/torvalds/linux/master/drivers/gpu/drm/amd/amdgpu/gfxhub_v2_1.c>.
It is therefore not an SDMA fault. The frozen records do not timestamp-correlate
it tightly enough to assign it to the Metal probe rather than another graphics
client such as WindowServer. The fields also do not identify which page-table
level or entry bit is wrong.

## What is known and what is missing

The pre-clear path reads the complete status and address before clearing the
latch (`src/RaphaelGPU.cpp:3647-3659`). It passes them to the bounded store, but
`FaultObservationStore::capture` rejects every VMID except 1
(`src/GpuVmDiagnostics.hpp:127-143`). The frozen `non-vmid1=1` counter is thus
an exact accounting of this VMID11 loss.

The repair policy itself accepts hub-0 client VMIDs 1 through 15
(`src/GpuVmDiagnostics.hpp:264-270`). However, `wrapVmmPrepare` retains prepared
request, original/native root, and sequence only when VMID equals 2
(`src/RaphaelGPU.cpp:4141-4151`). The frozen run consequently proves the VMID2
chain (`0xf40b6f3000 -> 0x84b6f3000`, prepared/live match) and global entry
conversion counts, but has no VMID11 original root, native root, prepared words,
live PTB, invalidate acknowledgement, PDE, or PTE. Global mode-4 samples cannot
be assigned to VMID11.

The exact 24G830 KDK analysis supporting the wrapper layout and the GC 10.3
register bank does not fill that gap. `contextRegisters(vmid)` already bounds
VMID below 16 and derives the documented per-context control/PTB/start/end
registers (`src/GpuVmDiagnostics.hpp:466-479`), while the worker is hard-coded
to context 1. Reading context 1 for a VMID11 fault would be wrong. No archived
VMID11 register snapshot exists from which to infer a conversion error.

## Discriminating observation change

Before any GPU behavior change, generalize the bounded diagnostic to client
VMIDs 1 through 15:

- Accept only decoded VMIDs 1..15 in the existing fixed-capacity fault store;
  retain the status and address unchanged. Preserve the existing VMID1 walk
  records so frozen parsers remain compatible, and add a generic client-fault
  schema for other VMIDs. Rename new rejection accounting to
  `non-client-vmid`; parsers must continue accepting the frozen `non-vmid1`
  spelling while requiring the new label for new generic-client captures.
- In the worker, derive `contextRegisters(decoded.vmid)`, reject an invalid
  context before MMIO, and read only that already-defined context bank. Snapshot
  control/PTB/start/end before and after the bounded walk and retain the existing
  stability and non-atomic-table qualifications.
- Extend the prepared-request observation from VMID2-only to a small bounded
  per-client record containing hub, VMID, original root, converted root,
  prepared root/words, and sequence. Correlate by VMID and order; do not claim
  thread or transaction identity without evidence.
- For the captured fault VA, emit the same bounded relative and absolute walks.
  This is observation-only: no new GPU write, retry, timeout relaxation, or
  speculative entry modification.

Do not add BAR reads to the pre-clear callback, which may run under unknown
driver locks. That callback should remain a lock-free status/address copy. The
worker-after-latch context read and table walk remain explicitly non-atomic; an
exact-time root snapshot before latch clear would be a separate audited feature,
not part of this minimum fix.

The minimum regression fixture feeds `0xb0093a/0x400300000`, proves it occupies a
slot as VMID11, proves VMID0 remains rejected, and supplies distinct
fake register values for contexts 1 and 11. It must assert that only the
VMID11 control/PTB/start/end addresses are read, that the reported root and
PDE/PTE walk derive from context 11, and that the before/after stability check
still detects mutation. VMID16 cannot be represented by the four-bit decoded
fault field; it remains only a direct `contextRegisters` input-boundary test.
A future prepared-request fixture should cover VMIDs 1, 2, 11, and 15 while
rejecting 0 and 16 and preserving the captured VMID2 behavior.

Only a fresh same-context VMID11 chain can discriminate among an unconverted
root, an unconverted child/page address, malformed permissions, or a different
failure. Candidate 191 alone authorizes none of those fixes.

## Implemented offline scope

The approved minimum observation change now accepts client VMIDs 1..15 in the
same two-slot store and selects the worker's context register bank from the
decoded status. VMID1 records retain their historical parser kinds; other
clients use `client_fault_walk`, `client_fault_walk_view`, and
`client_fault_walk_entry`. The parser enforces the same combined two-pair cap
across all client VMIDs. Callback work remains a status/address copy, and the
worker output still declares `worker-after-latch` and `tables-non-atomic`.

Per-client prepared-request correlation is deferred. Its current sequence and
storage are VMID2-owned; widening those semantics requires a separate review.
Accordingly, this implementation closes the proven VMID11 observation gap but
does not yet produce the full causal chain or establish a conversion defect.
