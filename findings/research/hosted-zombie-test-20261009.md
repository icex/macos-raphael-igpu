# Hosted zombie test portability correction

Hosted CI run 37919315108 on dev13a5f6f failed its real pthread zombie
fixture on Ubuntu/Python3.12: listing `/proc/5057/fd` raised EACCES after the
worker was killed. The retained log is
`~/macos-vm/run/candidate-347-hosted-ci-failure.log`. This is a test expectation
failure: the production proof correctly refuses unknown descriptor visibility.

Candidate349 changes only the test. The live-worker negative remains required.
After confirming only the original leader remains, a direct fd-directory probe
selects one of two explicit assertions: readable and empty requires positive
completion proof; EACCES/EPERM on that exact directory requires the production
helper to raise the matching permission error. Other exceptions and mismatched
paths are failures, not skips. A synthetic fd-denial test also exercises this
refusal on hosts whose real fixture is readable. No production authorization,
process scanning or capture cleanup rule changes.

Seven focused zombie tests pass locally. Hosted CI must be rerun after integration;
a local pass does not establish the hosted environment result.
