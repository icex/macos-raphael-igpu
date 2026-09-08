# Raphael iGPU acceleration implementation plan

> **For agentic workers:** Use the executing-plans skill to implement this plan task-by-task. Steps use checkbox syntax for tracking. Execution is inline by default; one owner controls all GPU/VM actions. Do not spawn hardware workers or start experiments from a research task.

**Goal:** replace trial-and-error bring-up with identifiable experiments that lead from the
current hybrid-engine failure to correct Metal workloads and a reliably usable VM.

**Architecture:** preserve Apple's Metal userspace and Navi23 stack, repair the smallest
measured Raphael incompatibility, and test real work through the existing native probe.
A single experiment runner coordinates the existing supervisor, immutable build identities,
structured evidence and stop conditions. Lifecycle/host-hang work is an independent gate.

**Tech Stack:** Python standard library, Bash, C++17 Lilu plugin, Objective-C/Metal probe,
QEMU/VFIO, user systemd, macOS 15.7.9 KDK 24G830, existing Linux cross-toolchain and GitHub CI.

**Spec:** [Authoritative roadmap](../../ROADMAP.md).

## Global constraints

- Preserve the roadmap's host boundaries, especially no driver cycling, virgin VFIO,
  forced HQD clear, MODE1 reset or host SMU retargeting.
- All initial experiments keep `RGPU_MAX_SECONDS=180`; current launch-service cap and
  full-CID hard timer remain armed. The first starts before Docker launch. Graceful
  shutdown is at most 20 seconds and must fit inside the original deadlines.
- One physical-GPU launch per host boot until lifecycle reuse is validated.
- No compiler setup or broad firmware/register dumps during GPU exposure.
- No host sudo for build, tests, manifests, ordinary logs or guest command transport.
- Repository paths are relative; the external harness is always an explicit `--vm-dir`.
- Existing 1.0.159 is historical evidence. 1.0.162 is a built, hardware-untested diagnostic.
- No task may claim Metal success from device enumeration, queue setup, a callback alone,
  `powerUpHW -> 0`, or a source/CI build.
- T1–T4 are implemented and validated offline and GPU-less. See
  `findings/gpueless-tests/163/coordinator/notes.md`; physical gates remain open.

## Task map and responsibilities

| Task | Owner | Hardware needed | Dependency | Deliverable |
|---|---|---|---|---|
| T1 | Driver investigator | No | Existing source/evidence | Audited fixed baseline and experiment card |
| T2 | Harness implementer | No | T1 | Immutable identities and fail-closed admission |
| T3 | Diagnostic implementer | No, then GPU-less | T1 | Reliable critical records and explicit missing-data verdicts |
| T4 | Harness implementer | GPU-less validation first | T2/T3 | One-run coordinator, bounded shutdown, no blind restart |
| T5 | Sole hardware operator | One controlled GPU run | T1–T4 and clean boot | Localized hybrid failure or explicit earlier blocker |
| T6 | Driver implementer | Only after offline checks | T5 | Minimal causally justified startup/submission repair |
| T7 | Test implementer/operator | Bounded GPU validation | T6 | Correct compute/render, memory and completion coverage |
| T8 | Lifecycle investigator/operator | GPU-less first, then gated GPU | T4; parallel to T5–T7 | Native teardown and evidence for warm reuse |
| T9 | Display/application investigator | After core execution | T7; T8 for repeated use | Desktop, DCN, application/performance qualification |

Owner names describe roles, not authorization to run simultaneous hardware tasks.
T1–T4 can use offline work while waiting for a reboot; T8 starts with GPU-less work.
Every task ends with a reviewed diff, relevant passing tests, evidence update and commit.
Keep the first batch small: reuse the existing 36 tests/supervisor/probe, add a thin
coordinator and a small critical-record buffer, and avoid new frameworks or a broad kext
rewrite. The record buffer and manifest are correctness controls, not a new logging or
orchestration platform.

## T1 — Freeze the facts and audit the baseline

**Files:** create `findings/baseline-audit.md`, `experiments/hybrid-001.json`;
read `src/RaphaelGPU.cpp`, `tools/milestones.py`, `findings/GPU-RE.md` and the clean-run
record; update `docs/ROADMAP.md` only when evidence changes.

- [x] Record exact source commit, bundle version/hash, KDK binary UUID/hash, firmware/input
  hashes and enabled boot arguments for both the historical reference and current candidate.
- [x] Make one row for every enabled patch/boot arg: intended effect, owning binary/function,
  actual memory/register writes, return changes, known reason, and cleanup impact.
- [x] Review `wrapHwEngPowerUp` against the native 24G830 loop: it replaces the loop and
  omits a progress-field write. Establish field consumers before calling it diagnostic-only.
- [x] Review `startRlc`, `wrapKiqSubmit`, `wrapGcCheckRegEq`, memory/allocation workarounds
  and timeout guards. Label reads with side effects; a logger can be an intervention.
- [x] Preserve proven address fixes. Disable/remove an obsolete behavior only in its own
  experiment after a source-backed reason; do not shrink the mask wholesale before T5.
- [x] Write the first experiment card with the following concrete content:

```json
{
  "id": "hybrid-001",
  "question": "Where does native hybrid creation first fail after KIQ setup?",
  "candidate_version": "1.0.163",
  "requested_diagnostic": "rgpuhybrid=1",
  "behavior_change": "none intended; capped availability observation only",
  "required_observations": ["loaded_build", "route_guards", "kiq_stamps", "hybrid_enter", "hybrid_exit", "engine_start"],
  "max_seconds": 180,
  "prerequisites": ["T2", "T3", "T4", "fresh_amdgpu_first_boot"],
  "repeat_policy": "no unchanged retry",
  "abort_on": ["identity_mismatch", "capture_loss", "kiq_dequeue_timeout", "host_fault"],
  "outcome_table": "docs/ROADMAP.md M2"
}
```

The preparation tool adds actual immutable hashes; the example intentionally contains no
invented hash. A prepare operation refuses to freeze a card with unresolved identities.
The functional baseline remains unchanged except for reviewed diagnostic changes.

**Acceptance:** another reader can identify every mutation in the baseline, reproduce the
configuration, and explain exactly what T5 can and cannot distinguish. Commit the audit
and prepared card before a GPU launch, without checking off T5.

## T2 — Make build and launch identity a single contract

**Files:** create `tools/experiment.py`, `tests/test_experiment.py`;
modify `tools/esp-kext.sh`, `tools/preflight.py`, `tools/redeploy.sh`,
`tools/metal-test.py` as needed; retain `tools/vm-supervision.py` as the sole supervisor.

**Interfaces to implement:**

```python
prepare(vm: Path, spec: Path, output: Path) -> dict
validate_identity(expected: dict, observed: dict) -> list[str]
admit(manifest: dict, host: dict, used_boots: set[str]) -> list[str]
```

`prepare` creates an immutable prelaunch JSON; postlaunch/result data go into separate
files, never edits to that manifest. Required identity keys: source commit and clean-tree
status; source/build-input/KDK hashes; executable and Info.plist hashes; exact ESP kext and
config hashes; boot args; QEMU image digest/version and relevant argv; guest OS build;
probe source/executable hash; host boot ID/kernel; device IDs/group/owner/PM; exposure cap.
Capture only selected metadata, never full Docker environments or credentials.

- [x] Write failing tests for wrong ESP executable, stale Info.plist, changed boot args,
  missing KDK identity, dirty source and intended GPU run that actually omits VFIO.
- [x] Write admission tests for missing watchdog evidence, virgin VFIO, a previous use of
  the same boot ID, an active VM and inaccessible host checks. Example contract:

```python
self.assertIn("binary_sha256", validate_identity(
    {"binary_sha256": "a" * 64}, {"binary_sha256": "b" * 64}))
self.assertIn("boot_already_used", admit(
    {"max_seconds": 180},
    {"boot_id": "boot-A", "amdgpu_initialized": True,
     "capture_ready": True, "watchdogs_verified": True,
     "device_pinned_awake": True, "active_vm": False}, {"boot-A"}))
```

- [x] Implement identity checks using allowlisted fields. Require all production fields;
  reduced dictionaries above exercise mismatch handling, not complete admission fixtures.
- [x] Treat protected-read denial as `unknown`; never report an empty pstore from permission
  denial. Existing logs and sysfs metadata suffice for most checks; justify any protected read.
- [x] Make staging transactional while no VM is running: back up ESP, insert bundle/config,
  read back and hash both; publish prepared manifest only after they match.
- [x] Embed/log a build identity that maps uniquely to the exact candidate. A version
  string alone cannot distinguish different binaries carrying that version. Bind the guest
  build marker to the staged image and reject unexpected loaded versions or fallback kexts.
- [x] Preserve original supervisor start/deadline identity in the run evidence. Acquire a
  per-VM experiment lock before preparation/launch/guest commands; no shared-file races.
- [x] Reserve the boot ID before opening VFIO. Once a launch could have touched hardware,
  failure/cancellation cannot erase that reservation; release it only if no access occurred
  is positively established. Never restart a supervised container in place.
- [x] Run the failing fixtures to green, exercise staging against disposable image fixtures,
  and commit. No live GPU run is required.

**Acceptance:** a mixed source/binary/ESP/guest experiment cannot produce a valid verdict
and prelaunch mismatches cannot open the iGPU. T2 does not reset any device.

## T3 — Make the critical observations trustworthy

**Files:** modify `src/RaphaelGPU.cpp`; create `src/DiagnosticRecords.hpp`,
`tests/test_diagnostic_records.cpp`, `tools/classify-run.py`, `tests/test_classify_run.py`.

**Interfaces:**

```python
classify(manifest: dict, events: list[dict], probe: dict | None) -> dict
# Returns {valid: bool, verdict: str, earliest_failure: str | None,
#          evidence: list[str], next_action: str}
```

Records carry experiment/build identity, sequence, stage, event kind, native result and
bounded payload. Use explicit dropped/overflow counters and a consistent snapshot method.
Formatting/flushing must not hold a lock while performing MMIO or a slow serial write.
Audit permitted execution/interrupt contexts before selecting the kernel synchronization
primitive. The existing unprotected `diagLen` and destructive dump are not a safe model.

- [x] Add a host-testable record buffer that proves no out-of-bounds write, torn record,
  duplicate sequence or unreported overflow under concurrent producers. Test a slow reader,
  full buffer and snapshot during append with real threads; use sanitizers when available.
- [x] Keep hot-path critical observations small: build identity, route guard, KIQ stamp,
  hybrid entry/exit, engine startup and first submission/completion. Retain detailed dumps
  only as opt-in bounded follow-ups with a documented discriminating purpose.
- [x] Extend hybrid tracing only if the current snapshot is insufficient: record the selected
  native child result at a verified safe caller boundary; do not route through an unsafe
  displaced branch/call or substitute a success value.
- [x] Write classifier fixtures for these exact cases:

| Fixture | Required verdict |
|---|---|
| Incorrect loaded build or route-guard failure | `INVALID`, no hardware conclusion |
| Missing/truncated required `HY` records | `INCONCLUSIVE`, not “hook not called” |
| KIQ dequeue timeout before hybrid creation | `BASELINE_BLOCKED` |
| KIQ succeeds; hybrid returns 4 with availability-before 0 | `HYBRID_UNAVAILABLE_SUSPECTED`, not proven flag cause |
| KIQ succeeds; hybrid returns 4 with availability-before 1 | `HYBRID_QUEUE_SUSPECTED`, not proven queue cause |
| Hybrid returns 0; engine start returns 0 | `STARTUP_FAILED_LATER` |
| Metal enumerates, no completed command buffer | `EXECUTION_FAILED` |
| Native startup succeeds, probe was not attempted | `PROBE_NOT_RUN` (execution unknown) |
| Correct nonce/output/pixels/exit and clean native results | `CORE_PROBE_PASS` |

Example assertions:

```python
self.assertEqual(classify(valid_manifest, kiq_timeout_events, None)["verdict"],
                 "BASELINE_BLOCKED")
self.assertNotEqual(classify(valid_manifest, enumeration_only_events, None)["verdict"],
                    "CORE_PROBE_PASS")
self.assertFalse(classify(wrong_loaded_build, successful_events, passing_probe)["valid"])
```

Define complete fixture dictionaries in the test file; these names are local test data,
not production APIs. Retain raw logs alongside parsed records. Archive legacy runs as
`legacy-evidence`: do not fabricate missing manifests to make them satisfy the new gates.

- [x] Check source/binary ownership, ABI, complete displaced instructions and entry guards
  before a new route. Test deliberately wrong offsets and missing stage records offline.
- [x] Run record-buffer/classifier tests and KDK preflight; verify a GPU-less boot produces
  reliable build/agent records. Commit before spending a GPU run.

**Acceptance:** unknown/invalid data cannot become success or a root-cause diagnosis.
Logging failures have their own visible result and cannot silently contaminate a run.

## T4 — Automate exactly one bounded experiment

**Files:** extend `tools/experiment.py`, `tests/test_experiment.py`,
`tools/redeploy.sh`, `tests/test_redeploy_lifecycle.py`, `tools/vm-supervision.py`,
`tests/test_vm_supervision.py`; reuse the existing native probe and guest channel.

**Proposed CLI:**

```sh
python3 -B tools/experiment.py prepare --vm-dir "$VM_DIR" --spec experiments/hybrid-001.json
python3 -B tools/experiment.py run --vm-dir "$VM_DIR" --manifest "$MANIFEST"
python3 -B tools/classify-run.py "$RUN_DIRECTORY"
```

`VM_DIR`, `MANIFEST` and `RUN_DIRECTORY` are explicit operator inputs supplied by the
prepare command's outputs; scripts must not embed a personal home path.

- [x] Write failing tests showing normal redeploy cannot `docker rm -f` a currently active
  named VM. Require its owned shutdown path or refusal before modifying disk/config.
- [x] Implement the coordinator state machine:

```text
PREPARED -> ADMITTED -> STARTED -> IDENTITY_VERIFIED -> TARGET_OBSERVED
         -> PROBE_IF_ELIGIBLE -> SHUTDOWN_REQUESTED -> STOP_CONFIRMED -> CLASSIFIED
any identity/capture/host error -> ABORT -> exact-CID stop -> CONTAMINATED
```

- [x] Reuse the supervisor's real deadlines. Work backward from the earlier launch-service
  cap as well as Docker StartedAt: start the probe only if its full deadline and cleanup
  reserve fit. Do not assume 45 seconds remain just because the serial marker arrived.
- [x] Use completion/readiness events rather than sleeps for guest readiness; a timeout
  reports which required event was missing. Precompile the probe in a GPU-less guest.
- [x] Run the Metal probe only if the experiment calls for it and native startup succeeded.
  Do not perform shader submissions solely to confirm a known startup failure again.
- [x] On a decisive failure, preserve a short predefined diagnostic tail, stop immediately,
  and mark the boot contaminated. Do not use the remaining cap for exploratory writes.
- [x] Test cancellation, stale command delivery, caller death, serial death, Docker failure,
  too-little-remaining-time and wrong CID. Ensure each path either confirms stop or emits
  an explicit unresolved-stop error; never silently fall through to another launch.
- [x] Test the entire state machine with fake Docker/systemd and a GPU-less guest before T5.
  Preserve ACPI's measured `forced` result; do not relabel it graceful.
- [x] Save `manifest.json`, `host-before.json`, `supervision.json`, `events.jsonl`, raw serial,
  probe output, `shutdown.json`, `host-after.json`, `verdict.json` and a brief decision note.
- [x] Run regression suite and commit the completed runner. Do not add an autorun loop.

**Acceptance:** one command executes at most one eligible experiment, reports the earliest
failure accurately, keeps deadlines intact and cannot silently launch another VM.

## T5 — Run the hybrid decision experiment after clean initialization

**Files:** consume prepared card/manifest; add one immutable directory under
`findings/experiments/`; update baseline audit and roadmap with the actual verdict.

- [x] After reboot, verify new boot ID/no VM/sleep inhibitor/host capture and amdgpu ownership.
- [x] Capture permitted reference metadata before the handoff. Do not run the old
  `capture-amdgpu-reference.sh` unreviewed: it also invokes raw register access.
- [x] Validate 1.0.162 or its reviewed successor and `rgpuhybrid=1` in the actual ESP.
  A staged build directory is not a deployed candidate.
- [x] Use the reviewed one-way handoff once if needed. Do not request sudo for subsequent
  build/launch/tests when existing device permissions already suffice.
- [x] Run the M2 experiment via T4, at most 180 seconds, with the probe precompiled.
- [ ] Apply the exact M2 decision table. If availability is suspected, identify the native
  state-bit writer and its event ordering. If queue creation is suspected, identify selected
  engine type, actual hardware instance and its callback return before changing behavior.
- [x] Stop, archive, classify and commit regardless of success or failure. Mark M2 complete
  only when a concrete native failing branch/callback is located; a snapshot is insufficient.

**Acceptance:** a valid run either narrows the first failure to a specific native operation
or establishes a named earlier blocker. An inconclusive run generates a better observation
plan; it does not justify a register patch.

## T6 — Repair the located cause, not the observed symptom

**Files:** modify the smallest section of `src/RaphaelGPU.cpp`; extend
`src/GartAddresses.hpp` / `src/KiqAddresses.hpp` only if the measured defect is an address
conversion; create `findings/hybrid-cause.md` with source/call evidence and regression.

This task deliberately does not prescribe a register value or “return success” patch:
the causal branch is not known. Its executable decision procedure is:

```text
availability rejection -> locate writer of each observed blocking bit -> establish
required native predecessor -> repair missing predecessor/order, not the bit itself

GC/SDMA callback failure -> decode type/instance/queue/allocation -> check actual chip
capability and data domains -> repair producer/dispatch or the proven incompatible backend

startup complete but no Metal progress -> follow first submission -> classify packet,
translation, fence-memory or interrupt/completion failure -> repair that boundary only
```

- [ ] Write down native function ABI, return semantics, argument fields and producer for
  the value being repaired; prove them from the 24G830 binary and pinned reference code.
- [ ] For pure transformations/dispatch, encode the failing captured case as a regression
  before implementing. Include unchanged valid inputs, overflow/range errors and failure
  cleanup; use real captured domains, not assertions that repeat the implementation.
- [ ] For ordering/lifecycle repairs, use an event-sequence fixture plus native before/after
  hardware evidence; a mocked “success return” is not acceptance.
- [ ] Implement one gated minimal repair; verify compile, route ownership, entry guards and
  required firmware before staging. Review changes to cleanup as carefully as initialization.
- [ ] Run the next distinct experiment only from an admitted state. Require native startup
  success plus actual user work; preserve all previous checked address/queue invariants.
- [ ] If three valid targeted experiments do not narrow the same blocker, review the
  backend boundary and evidence with the user. Do not change CPU/platform firmware as a shortcut.

**Acceptance:** a causal explanation predicts both the failure and successful execution;
the fix preserves native errors on genuinely invalid input and does not fake completion.

## T7 — Turn one working submission into tested acceleration

**Files:** extend `tests/metal_probe.m`, `tools/metal-test.py`,
`tests/test_metal_result.py`; create `tests/metal-matrix.json` and
`findings/feature-matrix.md`.

- [ ] Keep the existing full probe as the acceptance baseline: three rounds/196,608 integer
  comparisons, 4,096 pixel comparisons, actual completed status/no error, nonce and exit 0.
- [ ] Add explicit `copy`, `compute`, `render` and `all` diagnostic modes. A partial-mode pass
  must not satisfy the existing full-probe validator. Test this with saved result fixtures.
- [ ] Give every case input seed, expected operation, resource/storage mode, count, allocation
  budget, GPU/host deadlines and case ID; enforce M5's initial memory and time budgets.
- [ ] Introduce cases in order: copy/synchronization → compute → render → resource recreate
  → sequential processes → two clients. All results must be checked independently on CPU.
- [ ] Trace per-client VM mapping/invalidation and completion only when the failed case
  requires it. A context-0 GART fix does not prove per-process address spaces work.
- [ ] Record passed, failed, skipped and unsupported distinctly; do not silently omit an
  advertised feature that fails. Do not report broad Metal conformance from this small suite.
- [ ] Commit test additions and each demonstrated milestone with immutable run evidence.

**Acceptance:** M4/M5 gates pass on the actual GPU and failures are localizable to a case.

## T8 — Make shutdown and device reuse reliable

**Files:** extend `tools/vm-supervision.py`, `tools/experiment.py`, their tests;
add a minimal revocable request to the existing guest-agent transport; add narrowly
scoped native uninitialization observations to `src/RaphaelGPU.cpp` if needed.

- [x] First write GPU-less tests for guest-agent poweroff: exact guest/container identity,
  one command-channel lock, per-run permit, finite timeout, removal of pending commands,
  and refusal of a delayed command in a later VM. Never issue host `shutdown`/`reboot`.
- [x] Request `/sbin/shutdown -h now` through the installed root guest agent; avoid host
  sudo and interactive guest login. A request acknowledgment is not an exit verdict.
- [ ] Verify guest exit without forced container stop in a GPU-less run. Keep the existing
  independent cap/fallback even if the request transport blocks or returns success.
- [ ] Map Apple's teardown and Linux's corresponding required operations. KIQ controls
  other queues; their UNMAP_QUEUES does not alone establish KIQ self-teardown. Order PSP
  TMR/ring release after masters no longer reference those allocations.
- [ ] Observe clean native shutdown after a bounded GPU workload, without forcing register
  state. If teardown cannot run after partial startup, isolate that failure separately.
- [ ] Investigate host fault evidence per boot, including inaccessible/missing capture.
  Revalidate runtime-PM pinning and actual touched SoC resources; last-line correlation
  and amdgpu-first vs virgin survival times are not mechanisms or probabilities.
- [ ] Permit one warm restart only after the preceding teardown was observed and the new
  experiment is specifically testing lifecycle. One failure disables further warm reuse.
- [ ] Require three successful bounded cycles before enabling routine repeated experiments.
  No unconditional auto-resets or automatic hardware bisection.

**Acceptance:** shutdown/reinitialize is a measured lifecycle, not repeated forced kills;
M7's host-safety risk remains explicit until resolved or defensibly contained.

## T9 — Presentation, DCN, games and release

**Files:** extend `tests/metal_probe.m` or add a small Metal presentation test app;
update `findings/feature-matrix.md`, `docs/supported-games.md`, `docs/release-notes.md`;
add a dedicated DCN compatibility unit only when source mapping demonstrates its need.

- [ ] Prove actual WindowServer/device presentation with changing content and matching
  device/completion evidence; screenshots alone cannot establish GPU execution.
- [ ] Use the captured board topology to map DCN 3.1.5 objects/registers. Validate link,
  scanout address domains, clocks and bandwidth for one 1080p60 connector before others.
- [ ] Keep virtual-display rendering, direct physical display and video decode/encode
  statuses separate. Video acceleration is an additional feature, not a compute gate.
- [ ] Run the M8 independent-boot/core/lifecycle qualification without extending existing
  caps. Long-duration gaming/stress is a separate gated plan after host stability improves.
- [ ] Test named installed games only after core correctness. Report measured frame times,
  settings, actual gameplay, defects and duration; no unsupported compatibility predictions.
- [ ] Update the test-derived supported list and feature matrix; preserve failure evidence.
- [ ] Review/remove proven obsolete experimental hooks one at a time with regression runs.
  Consolidate hardware access into typed, documented units only as affected code is touched.
- [ ] Merge reviewed `dev` milestones into `main`; tag a source-built release only with
  truthful status. Hardware-untested builds stay experimental even when hosted CI is green.

**Acceptance:** each public claim links to evidence; a stable/full-acceleration claim requires
all corresponding roadmap gates, not just this task's packaging step.

## Execution checkpoints and handoff

At every checkpoint record:

```text
Task/milestone:
Changes (including diagnostic side effects):
Evidence and exact build/boot identity:
Earliest failure or verified capability:
Unknowns / excluded conclusions:
Stop/cleanup and host outcome:
Next experiment and why it is different:
```

First execution batch is T1–T4's offline/GPU-less work. After the user's reboot, capture
reference state before handoff, but do not open VFIO until the batch's admission and
observation gates pass. Hardware execution is not part of this planning turn.
