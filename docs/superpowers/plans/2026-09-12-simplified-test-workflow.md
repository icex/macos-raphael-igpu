# Simplified GPU test workflow

## Goal

Make the normal discriminator one command while retaining the existing host
safety, candidate identity, launch budget, capture, shutdown, and recovery
gates. The command should produce a compact JSON result and point to expanded
logs only when a gate or guest boundary fails.

## Proposed flow

1. `tools/run-gpu-test.py` becomes the single entry point. It accepts a
   reviewed candidate worktree plus a diagnostic selection, starts the existing
   user-level `systemd-inhibit --what=idle` wrapper, and invokes the current
   staging/preparation and `experiment.py run` gates in order. It must stop at
   the first failed gate, preserve the gate name and error in JSON, and never
   treat a logged QEMU command as proof of VFIO exposure.

2. Preparation emits one immutable run directory containing the generated card
   copy, build manifest, staging record, and run manifest. The run manifest
   binds the exact source, card, harness, build, boot options, and run ID used;
   callers do not hand-edit hashes. Reuse existing source/build identity
   helpers and `stage-candidate.py` checks. If the source digest and build
   inputs are unchanged, reuse the existing verified build artifact; rebuild
   only when those inputs change. Any changed card or harness requires a new
   manifest and identity verification.

3. The wrapper prints a short summary (`gate`, `verdict`, `boundary`,
   `exposure_proven`, `run_id`, candidate/card/source identity, and artifact
   path) derived from the embedded manifest rather than directory names, and
   writes full serial, critical,
   event, recovery, shutdown, and host evidence under that immutable directory.
   Cleanup always targets the authenticated CID and `StartedAt`; recovery and
   ledger accounting remain the existing fail-closed paths. Append one compact
   status row only after the result is durably written.

## Reuse list

- `tools/run-gpu-test.py`: external idle inhibitor, CLI and summary surface.
- `tools/experiment.py`: admission, host snapshots, candidate identity,
  exposure accounting, probe gate, verdict and recovery classification.
- `tools/stage-candidate.py`: build/artifact/card validation and immutable
  staging publication.
- `tools/vm-supervision.py`: exact CID/start-time supervision, bounded timer,
  monitor shutdown, forced stop, and collector lifecycle.
- Existing `build-release.py` tree digest/build manifest and existing recovery
  helpers/receipt validators.

## Focused verification

Run the wrapper, staging, experiment, and supervisor tests first. Run the full
Python suite only after a milestone such as a new candidate identity, staging
contract, or lifecycle change. A hardware run remains one explicitly admitted
launch; pre-open failures consume no GPU ledger entry, while proven exposure
does. No gate is removed to shorten the command.

## Design contradiction to resolve before implementation

The current wrapper accepts an already prepared manifest, while staging still
requires explicit expected card and identity hashes. “No manual card/hash
chasing” therefore requires a small generator/orchestration layer that copies
reviewed inputs into the immutable run directory and computes expected hashes
before calling the existing validators. It must not weaken those validators or
silently convert a dirty/flagged worktree into a clean source claim.
