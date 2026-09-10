# Candidate 183: post-conversion fault boundary

Date: 2026-09-10. Scope: offline analysis of the frozen candidate-183 and
candidate-183 GUI serial captures, current driver diagnostics, the local 24G830
KDK disassembly already identified by the project, and cached Linux GC 10.3
sources/register definitions. No VM, device, sudo, reset, recovery, staging,
build, or core-code action was performed. The raw verdict remains
`INCONCLUSIVE`; this note does not establish functional Metal.

## Result

Candidate 183 demonstrates that the corrected updater operand reaches memory:
the first child update at X6000 return site `x6+0x55a72` changes source
`0xf40b6f4000` to physical `0x84b6f4000`, constructs
`0x200000084b6f4001`, and a later VMID2 BAR walk reads that exact qword from
root `0x84b6f3000`. It also reads usable non-SYSTEM leaf PTEs for
`0x400100000` and `0x4000c0000`. This is real progress through the former child
address boundary.

It does **not** identify the later faulting translation. Both recurring hardware
faults decode as **VMID1**, whereas the diagnostic context snapshot and walk are
hard-coded to VMID2. The VMID2 walk therefore cannot validate or refute VMID1's
root, indexing, leaf PTEs, or SYSTEM attributes.

## Exact fault decode and capture correlation

The local Raphael/GC10.3 definition
`/home/bogdan/macos-vm/ref/linux/gc1036/asic_reg/gc_10_3_0_sh_mask.h:11563`
defines `MORE_FAULTS[0]`, `WALKER_ERROR[3:1]`,
`PERMISSION_FAULTS[7:4]`, `MAPPING_ERROR[8]`, `CID[17:9]`, `RW[18]`,
`ATOMIC[19]`, and `VMID[23:20]`. Applying those masks gives:

| Status/address | VMID | CID | Client | Walker | Permission | Mapping | RW | Atomic |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| `0x101b3a @ 0x400900000` | 1 | 13 | SDMA0 | 5 | `0x3` | 1 | 0 | 0 |
| `0x1009ba @ 0x401180000` | 1 | 4 | CPF | 5 | `0xb` | 1 | 0 | 0 |

The CID names come from cached Linux
`drivers/gpu/drm/amd/amdgpu/gfxhub_v2_1.c:37`: entry 4 is `CPF` and entry 13
is `SDMA0`. The first fault is recorded before clearing in original candidate
183 serial lines 6357 and 15608, and GUI serial line 3659. The driver dump ties
`0x400900000` to pending `SDMA0_PAGE`, `VMID = 1`, with zero IB consumption
(original lines 6680-6688 and 6968-6970; GUI lines 4147-4155 and 4438-4440).
The second fault is recorded at original lines 10319 and 19308 and GUI lines
7089-7098. The dump ties `0x401180000` to a pending GFX command buffer with
`VMID = 1` (original lines 11445-11453 and 11704-11708; GUI lines
10953-10961 and 11098-11100). Its full GFX IB was eventually reported consumed,
so the latched CPF fault and the later stop timeout must not be equated with a
proved permanently unconsumed workload.

The nonzero walker, permission, and mapping subfields show a translation fault;
the captures and register header do not provide semantic names for the encoded
walker value 5 or permission masks `0x3`/`0xb`. Assigning a PDE level or a single
missing permission from those numbers would be speculation.

## Relative indexing and SYSTEM attributes

Current `walkPageTables` subtracts `contextStart` at
`src/GpuVmDiagnostics.hpp:315`. For the observed VMID2 control `0x3b`
(depth 1, encoded block size 7), this makes the root index zero for addresses
near its start `0x400000000`. Candidate-183 original lines 10284-10302 read:

* root index 0: `0x200000084b6f4001`, child `0x84b6f4000`;
* leaf index 256 for `0x400100000`: `0x84af503f1`;
* leaf index 192 for `0x4000c0000`: `0x84ab505f1`;
* leaf index 512 for `0x400200000`: zero;
* leaf index 384 for `0x400180040`: `0x10000084b70c001` (`TF=1`).

Thus relative indexing is consistent with the captured VMID2 table layout, but
only for VMID2. Absolute indexing would select root index 64 for the first two
addresses under this geometry; that entry was not captured. The evidence does
not justify extending either conclusion to VMID1.

Candidate 183's updater classification also appears internally consistent for
the entries it observed. Original lines 6281-6284 report 206 conversions and
2426 SYSTEM pass-throughs; the later summary reports 347 conversions and 4514
SYSTEM pass-throughs. Example SYSTEM templates are
`0x3000000000077` (bit 1 set) with ordinary guest-physical sources, and they are
preserved. Linux `amdgpu_vm.h:57-81` defines VALID bit 0, SYSTEM bit 1,
PDE-as-PTE bit 54, and translate-further bit 56. Linux
`gmc_v10_0.c:454-473` converts a directory address only when neither PDE-as-PTE
nor SYSTEM is set. Candidate 183 correctly preserves SYSTEM entries, but the
capture has no VMID1 page-table walk, so it cannot prove the faulting entries
are correctly attributed. In particular, a VMID1 SYSTEM root/PTE must remain a
guest/system physical address and is not eligible for the framebuffer
MC-to-physical repair merely because its numeric value resembles another
domain. No VMID1 root or leaf attribute is currently observed.

## Smallest next discriminating driver experiment

Add one bounded, observation-only diagnostic at the existing pre-clear fault
site. Decode the latched VMID, and only for VMID1 snapshot that context's
`CNTL`, PTB low/high, START low/high, and END low/high registers. Walk the exact
latched address (`0x400900000` or `0x401180000`) twice during one worker pass
through the existing BAR mapping: once with `va - contextStart` and once with
absolute `va`. The reads are not an atomic page-table snapshot and tables may
change between them. Log only
the root index/raw entry and each subsequently reachable entry, including
VALID, SYSTEM, PDE-as-PTE, TF, R/W/X, decoded address, and whether an MC-to-PA
conversion would be eligible under Linux's `!PDE_PTE && !SYSTEM` rule. Do not
modify an entry, root, context register, invalidate request, or translation
policy in this candidate.

This one probe discriminates the two live hypotheses at the actual boundary:

1. Exactly one indexing form reaches a valid chain and exposes an attribute or
   address error. That selects a narrowly defined follow-up correction.
2. Neither form reaches a valid chain. The fault is at VMID1 root/programming or
   table publication/invalidation, rather than evidence against candidate 183's
   already observed VMID2 child conversion.

If both forms appear valid, retain both as ambiguous and use hardware progress
plus the fault-selected context geometry to choose a later test; do not select
the prettier walk. The test should run at most once per distinct latched
status/address pair so fault polling remains bounded.

## Confidence limits

High confidence: status-field decode, CID names, VMID1 identity, and the mismatch
between the faulting VMID and current VMID2 walk. Medium confidence: relative
indexing describes the captured VMID2 layout. Unresolved: VMID1 context root,
start, page-table contents, correct index convention, SYSTEM/PDE-as-PTE
attributes, and whether either fault is the first causal failure. The later KIQ
`doStop` timeout is a lifecycle symptom and does not supply those missing facts.
