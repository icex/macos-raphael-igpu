# Candidate 184 guest contract implementation

## Scope

Task 2 of `findings/plans/2026-09-10-post-com2-candidate.md` was implemented from
baseline `d421120` without building, staging, launching a VM, accessing a device,
changing a version file, or committing. The implementation defines candidate
`1.0.184` / `metal-017`, preserves the candidate-183 functional arguments, and
adds the reviewed VMID1 diagnostic and dedicated COM2 transport.

## Contract

- The new card requests exactly `rgpuvmdiag=1`, retains `rgpusubmit=1` and
  `rgpuvmroot=4`, and selects `rgpucr2uart=2` through the exact COM2 transport
  object. Numeric recovery nonces remain mandatory.
- Candidate `1.0.184` is paired only with `metal-017`. The narrow supported
  diagnostic table also preserves every reviewed `rgpusubmit=1` pair from
  `1.0.180` / `metal-013` through `1.0.183` / `metal-016`. Unknown and mixed
  pairs are rejected.
- The exact launch contract is `BOOTDISK_MODE=custom`, `NVRAM=stock`, and
  `GENERIC_GRAPHICS=off`. Staging metadata retains that object unchanged for
  later manifest and launcher validation.
- The existing 180-second run cap, 45-second probe, terminal-prefix tolerances,
  recovery requirements, and native-readiness probe gate are unchanged.
- VMID1 fault records are conditional diagnostic observations. Their absence is
  inconclusive and does not prevent the existing native-readiness path from
  reaching `PROBE_NOT_RUN`.
- Removing the generic graphics adapter and selecting a headless backend changes
  launch topology. The card explicitly identifies boot, native readiness, and
  probe admission as unobserved confounds while preserving the functional driver
  path.

## VMID1 extraction

`classify-run.py` now exposes the existing CR2 formatter records as typed
`vmid1_fault_walk`, `vmid1_fault_walk_view`, and
`vmid1_fault_walk_entry` rows. It accepts C `%#x`/`%#llx` zero output (`0`) as
well as `0x...`, bounds record counts and integer widths, and checks the decoded
status fields against the emitted VMID, CID, three-bit walker, four-bit
permission, mapping, write, and atomic values. More than two distinct
status/fault-VA pairs is definitive capture loss.

Entry rows are checked against `decodePageTableEntry`: raw flag bits and the
level-sensitive decoded address must equal the emitted fields. The runtime-only
child-conversion field remains an observation rather than a value inferred from
the raw entry.

Invalid observed hardware state remains diagnostic data: a zero root, disabled
or reversed context, and an invalid PTE are retained. The header separately
reports `context_bounds_valid`, and `address_in_context` must agree with the
actual inclusive comparison. Malformed records which claim one of the known
VMID1 formats produce a definitive `capture_loss`; unrelated and absent records
do not change functional or probe verdict logic.

One test compiles a temporary C++ fixture against the production
`GpuVmDiagnostics.hpp`, invokes `decodeFaultStatus` and
`decodePageTableEntry`, formats fields with the production `printf` conversion
shape, and sends its output through the unchanged CR2 snapshot formatter into
the classifier. It covers observed statuses `0x101b3a` and `0x1009ba`, literal
zero fields, nonzero V/R/W and S/P/TF combinations, walker value 5, and
permission value `0xb`. Other tests cover
malformed and internally inconsistent rows, bounds/counts, invalid context, the
two-pair cap, every historical card from 180 through 183, exact boot arguments,
launch metadata, and fault-absence probe behavior.

## Verification

Command:

```text
python3 -m unittest tests/test_stage_candidate.py tests/test_classify_run.py
```

Result: 89 tests passed in 0.304 seconds.

`git diff --check` passed for the five implementation/test files and the new
experiment card.
