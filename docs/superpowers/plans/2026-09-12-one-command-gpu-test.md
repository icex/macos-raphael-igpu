# One Command GPU Test Implementation Plan

> **For agentic workers:** execute inline with reviewed checkpoints.

**Goal:** Reduce a GPU cycle to one user command while preserving build identity, capture, cleanup, and status evidence.

**Architecture:** Add `tools/run-gpu-test.py` as a thin orchestrator around the existing prepared-manifest runner. It owns a user-level `systemd-inhibit --what=idle` child, invokes the existing experiment runner, and records a compact status entry. Existing supervisor and coordinator never create or require sleep inhibitors.

**Tech Stack:** Python 3, existing `tools/experiment.py`, `systemd-inhibit`, JSON and Markdown evidence.

## Global Constraints

- No sudo is required for the normal test command.
- No VM launch occurs in dry-run mode.
- Existing identity, ledger, recovery, and host checks remain authoritative.
- No merge or push to main before desktop Metal qualification.

### Task 1: One-command wrapper

**Files:**
- Create: `tools/run-gpu-test.py`
- Test: `tests/test_run_gpu_test.py`

- [ ] Add CLI accepting `--vm-dir`, `--manifest`, `--output`, `--dry-run`, and `--ack-risk`.
- [ ] In normal mode run `systemd-inhibit --what=idle --mode=block` around `tools/experiment.py run`.
- [ ] Emit the child JSON verdict unchanged and append a compact row to `status.md`.
- [ ] In dry-run validate paths and print the exact command without launching.

### Task 2: Regression coverage

- [ ] Test command construction, dry-run behavior, inhibitor placement, and status append formatting.
- [ ] Run focused and full Python suites.

### Task 3: Documentation

- [ ] Document the one-command invocation and the fact that sleep is handled outside the supervisor.
- [ ] Update `status.md` with the implementation and offline test evidence.
