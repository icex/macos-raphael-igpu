# Candidate-194 reseal hash audit

Offline read-only audit, 2026-09-13. The failing test is
`Candidate188ResealTests.test_candidate194_reseal_pins_current_card_and_experiment_hashes`
in `tests/test_stage_candidate.py`. It compares the historical profile's
`experiment_sha256` with the current working tree's `tools/experiment.py`.

The card comparison is valid today: `experiments/metal-028.json` hashes to the
profile's pinned `e634925a...c47090`. The experiment comparison is the failure:
the profile pins `ee39d602...de800c`, while the current edited file hashes to
`86a8d950...39bf9`. The pinned digest is a real historical Git blob at commit
`3f47ab7eca52265a9f294200022213d354651e45`, confirming this is intentional
historical provenance rather than a corrupt profile.

Minimal principled repair: retain the historical profile digest and admission
semantics. Change the test to validate that the pinned digest resolves to the
immutable historical Git blob (or a checked-in historical fixture), rather than
requiring the mutable current helper to equal it. Do not repin the profile to
the current dirty helper and do not weaken admission. A future candidate must
record its own source/helper digest in a new profile.

EDID cross-check: the saved Raphael HDMI-A-3 binary is 256 bytes, SHA-256
`b7b277f882e5fa7df2ca542dee25d7684456a93e0bbd6a7ae3cf31e71da82bc5`, with
base and extension checksums both zero modulo 256.
