# Candidate 184 locked launch-options propagation

Date: 2026-09-10

The first candidate-184 invocation was refused before reservation or QEMU with
`one-run qualification refused: harness_sha256,launch_options`. The ledger stayed
at one of three and the recovered predecessor receipt stayed unchanged.

The immediate cause was a missing argument at the locked identity recheck.
`run_one` passed the sealed no-generic-graphics options to its first
`current_identity` call, but `reserve_candidate179_qualification` called the same
function without `launch_options_expected`. The warm reservation path had the
same omission.

Both locked paths now pass:

- the manifest run ID;
- the manifest recovery lease schema; and
- `launch_options(manifest)`, preserving the exact
  `BOOTDISK_MODE=custom`, `NVRAM=stock`, `GENERIC_GRAPHICS=off` object.

No identity comparison, authorization, ledger, receipt, recovery, launch, or
cleanup rule was relaxed. The regression drives the real one-run adapter through
the reservation function and observes the exact options at both identity reads.
A locked warm-reservation regression supplies a mismatched historical graphics
option and verifies refusal occurs before `replace_json`, which is the ledger
write boundary.

`python3 -m unittest tests.test_experiment` passed 96 tests. No VM, QEMU, device,
build, staging, retry, policy-pin, receipt, or ledger action was performed.
