# Candidate 185 VMID1 evidence checklist

Date: 2026-09-10. This is an offline interpretation aid for `metal-018`; it
does not predict that either prior fault will recur. Candidate 183 remains the
functional comparison because candidate 184 never launched.

## Admit the evidence before interpreting it

- Confirm the sealed candidate-185 run/build identity, numeric nonce, card and
  `rgpuvmdiag=1`, `rgpuvmroot=4`, `rgpusubmit=1` boot arguments. Use VMID1
  records only from the authoritative, checksum-valid COM2 CR2 selection.
- Require the exact running launch contract, including `GENERIC_GRAPHICS=off`,
  one `-vga none`, one `-display none`, no generic graphics device alias, and
  explicit COM1/COM2 topology. A boot or readiness difference under this new
  topology is a launch-topology observation, not a VM page-table result.
- Treat malformed records, more than two distinct status/address pairs,
  capture loss, conflicting identity, or incomplete terminal evidence as an
  observation failure. Do not fill missing fields from candidate 183.

## Check each known pair independently

The two candidate-183 pairs and their decoder-checked fields are:

| Pair | Expected decode | Prior workload correlation |
|---|---|---|
| `0x101b3a @ 0x400900000` | VMID 1, CID 13 / SDMA0, walker 5, permission `0x3`, mapping 1, read, non-atomic | pending `SDMA0_PAGE`; zero IB consumption was observed |
| `0x1009ba @ 0x401180000` | VMID 1, CID 4 / CPF, walker 5, permission `0xb`, mapping 1, read, non-atomic | pending GFX command buffer; its full IB was later reported consumed |

For every emitted pair, first verify that `vmid`, `cid`, `walker`,
`permission`, `mapping`, `rw`, and `atomic` agree with the raw status. Pair the
header, both views, and entries by the exact `(status, fault-va)` key; record
absence of either known pair as unobserved, not fixed.

Then record the header without normalizing it:

- raw `ctl`, `root`, `start`, and `end`;
- `aperture`, `context-stable`, and `address-in-context`;
- whether `start <= end` and whether the fault VA actually lies in that range.

`context-stable=0`, invalid bounds, out-of-context VA, zero/unreadable root, or
`aperture=0` identifies a context/programming or observability boundary before
an entry-level conclusion. Compare the raw root with both the published MC
framebuffer range and physical BAR range. Preserve its low attribute bits; do
not classify a merely similar numeric address as requiring MC conversion.

For **both** `relative` and `absolute` views, retain `valid`, `complete`, and
`count`, followed in order by every entry's `level`, `index`, `table`, `raw`,
decoded `entry-addr`, and `V/S/X/R/W/P/TF`, `mc2pa-eligible`, and
`child-mc2pa`. The useful outcomes are:

1. Exactly one view gives a complete valid chain while the other stops or is
   invalid. That selects the observed indexing convention for this pair. The
   first divergent index/raw entry is the narrow follow-up boundary.
2. Both views stop at the same invalid zero entry under a stable, in-range
   context. That is evidence of an absent/unpublished mapping at the observed
   time, but not by itself evidence of a conversion defect.
3. A reachable entry has `S=1` or `P=1`. It is ineligible for the framebuffer
   MC-to-physical rule even if its address resembles the MC range. A non-SYSTEM,
   non-PDE-as-PTE entry (`mc2pa-eligible=1`) still needs its raw address domain
   compared with the MC and physical apertures; eligibility alone does not show
   that conversion was necessary or performed.
4. Neither view reaches a valid chain despite a stable, in-range context and a
   readable aperture. Prefer a VMID1 root/programming/publication/invalidation
   hypothesis over attributing this to candidate 183's VMID2 child conversion.
5. Both views appear complete and valid. Keep the indexing result ambiguous and
   correlate later engine/workload progress; do not choose one because its
   decoded entries look more plausible.

The worker reads the fault pair after it was latched, reads context registers
before and after two walks, and reads page-table entries sequentially. Even
`context-stable=1` proves only that those seven context registers matched across
the worker operation. The relative and absolute walks are not atomic with each
other or with GPU table updates. Different raw entries can therefore reflect a
real lifetime transition. Do not label every zero, domain difference, or
relative/absolute disagreement as MC conversion failure without repeatable raw
address and attribute evidence at the same mapping lifetime.

## Functional comparison with candidate 183

Evaluate launch, native readiness, and Metal execution as separate steps:

- First establish that the no-generic VM reaches the guest and the candidate-185
  identity. Failure before driver/native records primarily tests the changed
  QEMU topology.
- Compare candidate 183's reached boundary: native accelerator/engine startup,
  active recovery lease and pool exclusion, non-null disjoint VMM arena and both
  native allocators, exact mode-4 entry gate, returned source-operand conversion,
  constructed physical child PDE, and subsequent VMID2 BAR walk. A missing or
  regressed prerequisite is the earliest regression even if VMID1 diagnostics
  later appear.
- VMID1 diagnostic presence is optional and must not gate native readiness or
  probe admission. If readiness reaches the unchanged gate, compare the single
  45-second Metal probe by its identity-bound result and command-buffer
  completion. Device enumeration, Metal 3 advertisement, library/pipeline/queue
  creation, or shader compilation alone is not acceleration success.
- Candidate 183 produced no valid Metal probe verdict. A valid completed
  compute/render result is new progress; the same faults or a later KIQ/stop
  timeout without a completed command remains a functional failure. For the CPF
  pair especially, prior full IB consumption means the latched fault cannot be
  equated automatically with a permanently unconsumed command.

Finally preserve shutdown, recovery, host-fault, and frozen raw-byte evidence.
Those determine safety and reuse, while the VMID1 rows diagnose the guest
translation boundary; neither substitutes for the other.
