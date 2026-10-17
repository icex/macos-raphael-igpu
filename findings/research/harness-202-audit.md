# Harness and provenance audit (2026-09-12)

Scope was offline and read-only with respect to the VM, VFIO device, and host. I
read `status.md`, inspected the coordinator checkout and candidate-201/202
worktrees, and correlated the recorded run artifacts from candidates 190–201.
No VM launch, reset, bind, sudo, staging transaction, commit, or hardware state
change was performed.

## Findings

### 1. “Clean” candidate worktrees are demonstrably dirty

`git status` in both candidate worktrees reports no changes, but `git ls-files
-v` marks the relevant paths with lowercase `h` (assume-unchanged). Comparing
the bytes with `git show HEAD:<path>` exposes the hidden edits:

| worktree | HEAD | files differing from HEAD | material difference |
|---|---|---|---|
| candidate-201 | `778a54b5b5d2a84153da718c3859531951e52a42` | `experiments/metal-035.json`, `kext/Info.plist`, `tools/experiment.py`, `tools/stage-candidate.py` | card source pin changed; bundle version changed 1.0.194→1.0.201; manual-reuse/idle edits copied in |
| candidate-202 | `3f47ab7eca52265a9f294200022213d354651e45` | `experiments/metal-036.json`, `kext/Info.plist`, `tools/stage-candidate.py` | card source commit changed; bundle version changed 1.0.194→1.0.202; candidate mapping edits copied in |

This defeats `verify_worktree_before_import()`, which trusts `git status
--porcelain`, and makes `stage-candidate.py`'s constant `source_clean: True`
an assertion rather than evidence. The recorded candidate-201/202 manifests
therefore cannot prove the source was clean.

The bounded repair now rejects `h` (assume-unchanged) and `S` (skip-worktree)
entries from `git ls-files -v` before importing candidate Python, while keeping
the exact-HEAD and ordinary porcelain-dirty checks. Focused temporary-git
worktree tests cover both hidden flags, an ordinary edit, and a clean tree.
The broader source-clean/digest policy remains a separate reviewed change; do
not manually set `source_clean`.

### 2. Card, source, and build commits are conflated

The build manifest uses `source_commit` for the candidate worktree commit, but
the card separately carries `raphael_source_commit`. Candidate-202 was built
with source digest `3b10220e…` and build/source commit `3f47ab7…`, while its
card at HEAD still named `45b0240…` as the Raphael source commit. The staged
working copy was then edited to say `3f47ab7…`. That commit changes card
metadata, not the Raphael source tree. Candidate-201 has the same pattern:
its HEAD card expected Raphael digest `7047142c…`/`a47d878`, while the hidden
working card was changed to `baa694c1…`/`778a54b…`.

Minimal repair: retain the existing separate source/coordinator provenance
helpers, but authenticate each input independently. Name the commits
separately (`raphael_source_commit`, `card_commit`, `harness_commit`) and bind
the card SHA-256 and exact card bytes used for staging. Do not treat a card
metadata commit as the Raphael source commit, and do not allow post-build card
editing without rebuilding/resealing the authenticated manifest.

### 3. The managed launcher failure was a lifecycle gate, not GPU evidence

The supervisor still contains two incompatible inhibitor assumptions. The
one-command wrapper creates a user-level `systemd-inhibit --what=idle` process,
but `vm-supervision.py:arm()` calls `logind_block_inhibited()` and requires an
exact `sleep:idle` block. Its collector path also wraps collectors in
`systemd-inhibit --what=sleep:idle` when not headless. An unprivileged caller
can provide `idle`; it cannot satisfy the exact combined scope expected here.
This explains the earlier prelaunch refusal and why the subsequent managed
attempts returned `STOP_UNCONFIRMED` with empty captures. The wrapper itself
also assumes stdout is JSON and only appends status after JSON parsing, so a
supervisor failure can lose the most useful structured error.

Minimal repair: make the wrapper-owned user-level `idle` inhibitor the sole
sleep policy; remove inhibitor checks and nested inhibitor wrappers from the
supervisor. Keep the absolute Docker `StartedAt` deadline and systemd service
cap. Make launcher failure emit a structured verdict/event even when readiness
is never published, and only classify exposure after QEMU/VFIO open.

Shutdown must remain independent of inhibitor state: use the authenticated
QEMU monitor ACPI request, observe the exact CID/start timestamp, then bounded
force-stop and verify host state. An inhibitor disappearing must never be the
reason shutdown or cleanup cannot run.

### 4. Exposure accounting is mostly correct but must be preserved through repair

The recorded sequence has one pre-open refusal (candidate-197 first invocation),
then actual or conservatively uncertain managed attempts for 195 (`905a7667…`),
196 (`5c27c2cf…`), 197 (`0647d62…`), and later same-boot records. A logged QEMU
command alone does not prove VFIO opened; classify such records as uncertain
until the journal proves the open/exposure boundary. The pre-open refusal has
empty captures and must not consume a GPU ledger entry. Once exposure is proven,
the attempt remains counted even if capture readiness fails;
`STOP_UNCONFIRMED` authorizes no recovery receipt and must not be silently
removed from accounting.

## Regression matrix (190 onward)

The common functional launch configuration through the relevant sequence is
headless (`GENERIC_GRAPHICS=off`), `rgpuvmroot=4` through 192, then `5` from
193 onward, `rgpudump=5000`, and `-liluheadless`. Candidate 194's successful
compute/offscreen result is the last qualified functional baseline; it does not
prove desktop presentation.

| candidate | observed boundary | verdict/evidence | harness/provenance interpretation |
|---|---|---|---|
| 190 | serial+critical capture; identity gate | INVALID | no usable identity claim |
| 191–192 | first submission reached | EXECUTION_FAILED | genuine guest evidence, later KIQ/submission failure |
| 193–194 | captures; route/readiness classification | inconclusive/invalid variants | identity/lease issues coexist with real guest evidence |
| 195 | native allocator-disable path panic | inconclusive with capture | real driver observation; no submission |
| 196 | managed/manual launch attempts, mostly empty or partial captures | invalid/inconclusive | inhibitor/lifecycle and identity churn; no VMM conclusion |
| 197 | one pre-open refusal, then managed `STOP_UNCONFIRMED`, later capture | invalid/inconclusive | pre-open attempt uncounted; managed exposure counted; no new GPU conclusion |
| 198 | repeated immediate supervisor/container exits, then one full capture | `STOP_UNCONFIRMED` then inconclusive | lifecycle race was real; later full capture reached `wireSysMemory` and then power-up failure |
| 199 | full capture, clean accelerator failure | inconclusive (`recovery_lease_pool_missing`) | real guest observation; provenance still says clean despite hidden-state risk |
| 200 | full capture, unsafe power-service bypass panic | inconclusive (`recovery_lease_pool_missing`) | real regression fixture; bypass correctly removed afterward |
| 201 | managed outputs are empty/invalid; separate final manual run panicked at `RIP=0x610ad` (serial.log), final supervisor CID `32f824…`, `critical_enabled=false` | INVALID / raw panic evidence | distinguish managed lifecycle failures from the later manual guest panic; candidate worktree was hidden-dirty |
| 202 | no hardware run recorded | — | staged only; card/source commit mismatch must be repaired before use; current source has re-added the power-service bypass and requires driver review |

The generic graphics topology is a confound: the qualified candidate-194
compute run used the headless path, while several older 194 diagnostic runs
used `GENERIC_GRAPHICS=on`. Candidate 195 onward generally uses `off`; do not
attribute differences in boot/readiness to driver changes without carrying the
launch option and boot arguments in the authenticated identity.

## Exact offline checks to require before implementation review

These are the smallest relevant checks, with no hardware access:

```sh
python3 -m unittest -q tests.test_run_gpu_test
python3 -m unittest -q tests.test_experiment tests.test_vm_supervision tests.test_stage_candidate
python3 -m py_compile tools/run-gpu-test.py tools/experiment.py tools/vm-supervision.py tools/stage-candidate.py
```

On the audited checkout, the wrapper tests pass (3 tests), while the combined
focused suite runs 203 tests and fails one provenance regression:
`test_candidate194_reseal_pins_current_card_and_experiment_hashes` detects
that the retained profile hash (`ee39d602…`) differs from the current
`tools/experiment.py` (`e79e0709…`). This is useful evidence of harness hash
churn, not a test to weaken. After the minimal repair, add focused tests for
assume-unchanged detection, card SHA binding, idle-only wrapper supervision,
structured pre-readiness failure, and pre-open versus post-open ledger
accounting, then rerun the same commands.

## Recommendation

Do not stage or launch candidate-202 yet. First repair provenance as one small
transaction (authenticated source/card/harness identities and honest clean-tree
detection), then repair the inhibitor/lifecycle boundary while preserving
CID/start-time shutdown and exposure accounting. Review those offline changes
against the exact checks above before any new hardware run.
