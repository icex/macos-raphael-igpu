# Run-scoped one-run qualification authorities

Date: 2026-09-10

## Implemented boundary

New authority creation writes the policy exclusively at
`run/one-run-qualification-authorities/<boot-id>/<run-id>.policy.json`. The
activation remains the existing run-scoped `<run-id>.json`. Creation still uses
exclusive mode, so recreating either authority for the same run refuses without
overwriting it.

Authorization derives the run ID from the supplied manifest. If that run's
scoped policy exists, it is the only policy considered. A malformed, mismatched,
or wrongly hashed scoped file cannot fall back to the legacy file. If the scoped
file is absent, authorization reads the historical `<boot-id>/policy.json` path
for compatibility with already sealed authorities. Reservation repeats this
selection and includes the selected policy bytes and path in the immutable-input
check, so creation of a scoped file after legacy authorization is a concurrent
change.

The policy and activation schemas did not change. All manifest, run, output,
ledger-preimage, receipt, helper, source, cap, timeout, retry, and live-gate
comparisons remain in place. The candidate-184 live authority and activation
were not read, moved, deleted, rewritten, or recreated during this source-only
work.

## Regression evidence

`python3 -m unittest tests.test_one_run_qualification` passed 13 tests. The new
coverage proves:

- two unconsumed authorities for distinct runs on one boot coexist;
- a second create for the same run refuses through exclusive creation;
- a present invalid scoped policy cannot fall back to a valid legacy policy;
- wrong-run policy content and wrong hashes refuse;
- two authorizations pinned to one ledger preimage cannot both reserve after the
  first ledger result is written;
- a legacy policy remains readable when no scoped policy exists.

`python3 -m py_compile tools/one-run-qualification.py
tests/test_one_run_qualification.py tools/experiment.py` and `git diff --check`
for those files also passed. These checks used temporary files and mocked host
hooks only. No live policy, authority, activation, ledger, VM, QEMU process,
device, build, staging transaction, or deployment was created or changed.
