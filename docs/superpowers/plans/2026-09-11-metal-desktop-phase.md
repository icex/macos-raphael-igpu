# Candidate 194 Metal Desktop Phase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one fail-closed candidate-194 experiment that proves Metal, a real Aqua user session, a held virtual display, and changing VNC-visible frames within the existing 180-second hardware exposure.

**Architecture:** Keep the driver artifact and recovery path unchanged. Precompile and hash-pin a small guest display probe during GPU-less staging, run it only in the resolved console user's launchd domain, and let `experiment.py` invoke it only after the existing authenticated Metal probe passes and at least 25 seconds remain for shutdown/recovery. Record virtual-display lifecycle, visible Metal drawable presentation, and independently observed remote-frame change as separate evidence levels; do not infer WindowServer compositor provenance.

**Tech Stack:** Python coordinator/unit tests, Objective-C CoreGraphics SPI probe, existing gx/nonce permit channel.

**Spec:** Approved coordinator design in the 2026-09-11 task handoff.

## Global Constraints

- Hardware exposure remains exactly 180 seconds; Metal probe remains exactly 45 seconds.
- Desktop hold is at most 30 seconds and starts only when 25 seconds remain afterward.
- Use exact candidate-194 binary identities; do not rebuild or modify the driver.
- No generic QEMU graphics, autologin, TCC mutation, capture-quiesce work, retry, or budget extension.
- No hardware execution before coordinator audit.

---

### Task 1: Held virtual display and Aqua proof

**Files:**
- Create: `tools/desktop-display.py`
- Create: `tests/desktop_display.m`
- Create: `tests/test_desktop_display.py`

**Interfaces:**
- Produces: `guest_command(nonce, source, expiry, hold_seconds)` and `validate_output(output, nonce)`.

- [ ] Write failing tests requiring GPU-less precompile plus binary hash pinning, resolved console UID, `loginDone`, `OnConsole`, a temporary per-user LaunchAgent in `gui/<uid>`, bounded hold, visible Metal drawable completion/presentation, and signal/normal removal of only the owned display while restoring any baseline display IDs.
- [ ] Run `python3 -m unittest tests.test_desktop_display` and confirm failure because the helper is absent.
- [ ] Implement separate prepare and nonce/expiry-bound run commands. The Objective-C probe creates one owned display, presents changing content through a visible Metal drawable on the selected registry ID, holds briefly, removes only its display, and reports baseline/final IDs plus presentation evidence without claiming compositor provenance.
- [ ] Run `python3 -m unittest tests.test_desktop_display` and confirm all tests pass.

### Task 2: Post-Metal coordinator gate

**Files:**
- Modify: `tools/experiment.py`
- Modify: `tests/test_experiment.py`

**Interfaces:**
- Consumes: `desktop-display.py` guest command and validator.
- Produces: `run_desktop_phase(vm, manifest, deadline)` and `desktop.json` evidence with distinct lifecycle, visible-drawable, and remote-frame observations.

- [ ] Write failing tests proving the phase is card-gated, requires a validated Metal pass, refuses insufficient time, preserves the 180/45 caps, and leaves 25 seconds for cleanup.
- [ ] Run the focused tests and confirm the new expectations fail.
- [ ] Add the narrow post-probe call and persist its receipt without changing readiness, shutdown, or recovery behavior.
- [ ] Run `python3 -m unittest tests.test_experiment` and confirm it passes.

### Task 3: Exact experiment profile and qualification

**Files:**
- Create: `experiments/metal-029.json`
- Modify: `tools/one-run-qualification.py` only if the new exact card fields require validation.
- Modify: `tests/test_one_run_qualification.py`

**Interfaces:**
- Produces: a fresh-card contract still pinned to `vm_max_seconds=180`, `probe_max_seconds=45`, one same-boot launch, and candidate `1.0.194`.

- [ ] Write failing qualification tests that accept only the desktop profile and reject generic graphics, cap changes, retry, missing desktop fields, or a different candidate identity.
- [ ] Add the card and the smallest profile-specific validation; retain the generic one-run schema and immutable hash binding.
- [ ] Run focused qualification tests, then `python3 -m unittest tests.test_desktop_display tests.test_experiment tests.test_one_run_qualification`.
- [ ] Run `python3 -m py_compile` and `git diff --check`; record that no live launch occurred.
