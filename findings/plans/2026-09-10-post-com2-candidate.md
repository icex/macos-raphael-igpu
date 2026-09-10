# Post-COM2 VMID1 Diagnostic Candidate Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare one exactly authorized candidate 184 / metal-017 launch on the current recovered boot, using dedicated COM2 capture and `rgpuvmdiag=1`, with no generic QEMU graphics adapter.

**Architecture:** Keep the reviewed candidate-183 functional path and add only the already implemented observation-only VMID1 fault walk plus dedicated COM2 transport. Make absence of a generic adapter an authenticated manifest/launcher/running-identity property, then use the existing schema-3 one-run authority to bind the recovered predecessor, current ledger preimage, fresh run ID, staged boot disk, exact harness, and one 180-second launch.

**Tech Stack:** C++ macOS kext, Python admission/classification tools, Bash Docker/QEMU launcher, OpenCore staging, schema-3 recovery, QEMU 10.1.2.

**Spec:** `findings/plans/2026-09-10-dedicated-critical-transport.md`, `findings/research/2026-09-10-post183-fault-boundary.md`, and `findings/research/2026-09-10-vfio-display-capability.md`.

## Global constraints

- This document is a plan. It authorizes no build publication, staging, VM/container launch, VFIO operation, reset, recovery, or device access.
- The user prohibits every generic QEMU graphics adapter. The next manifested run must contain `-vga none` and must reject `-vga vmware`, `VGA`, `vmware-svga`, `qxl`, `virtio-vga`, `bochs-display`, and `ramfb`.
- Do not claim a visible Raphael desktop. No verified Raphael-to-QEMU display plane exists.
- Preserve schema-3 recovery and the five pinned recovery helpers. Dedicated COM2 is authoritative; no COM1 fallback or repair is allowed.
- Preserve the 180-second container/launch cap, 45-second Metal probe, one-run policy, no automatic retry, and existing cleanup refusal rules.
- Do not extend the same-boot launch ceiling. The current ledger is one of three; a failed launch still consumes its reservation.
- The mandatory stalled-cycle review has already run. The unresolved GPU-cycle count remains six until reviewed hardware evidence demonstrates progress.

## Verified planning baseline

Read-only checks on 2026-09-10 established:

- live boot ID `73ad3355-80a7-48f1-a8dd-e6f770b41de8`;
- no running Docker container;
- active inhibitor PID 3777, label `Raphael GPU hardware qualification`, covering `sleep:idle` in block mode;
- ledger `/home/bogdan/macos-vm/run/used-gpu-boots/73ad3355-80a7-48f1-a8dd-e6f770b41de8.json`, schema 2, `max_launches=3`, one row for GUI-183 run `4661e574bbd5695d00176d85bfa87325`, SHA-256 `2f715f2067a57cf502ae61d64a745121fd385556b055ad36f04480fadf000b83`;
- canonical recovery receipt `/home/bogdan/macos-vm/run/vfio-recovery/73ad3355-80a7-48f1-a8dd-e6f770b41de8/4661e574bbd5695d00176d85bfa87325.json`, byte-identical to the archived recovery-migration copy, SHA-256 `d2e2fad9244033002bdd3643e72049e9b4f4b858080aa8fa0cadd91d095ad367`, with `status=recovered` and `authorizes_launch=true`;
- live harness remains pre-COM2: live `macos-vm.sh` SHA-256 `0cb9b3becd83cd90f4af2cdf29194e400fb38724e172533169fd4bdbb24b9ba7`; repository source is `d7da2c608ea00a3969df2426770a069ffbbe4d701ce0c9f695e28bff5b9a1903`;
- live `vm-entry.sh` SHA-256 `13912a2b14cc02100c7e1178869fa6c3e1721c1864000d1108de78005333a388` copies the image's `Launch.sh` unchanged with respect to graphics;
- an inert `docker create --network none --entrypoint /bin/true` inspection of the already-local pinned image `sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c` (container never started and exact CID removed) found `/home/arch/OSX-KVM/Launch.sh` SHA-256 `ae6050750f4ba26fbe85785da909b8f7d34fab064b6539d9a3f1903abf3fe302`; its graphics shape contains exactly one `-vga` option, exactly `-vga vmware`, and no `-display` option;
- the last actual QEMU argv contained `-vga vmware -display gtk,gl=on` and therefore does not satisfy the new request.
- the reviewed COM2 plus VMID1 source milestone is committed locally on `dev` at `d421120`; candidate work must start from that commit and include only subsequently reviewed admission/launcher changes.

## Unresolved evidence

`-vga none` removes the generic VMware device. It does not create Raphael scanout.
COM2 port I/O, the VMID1 worker, serial parsing, HTTP guest-agent command path,
and the Metal probe have no direct code dependency on VMware VGA. However, no
macOS run in this project has shown that OVMF/OpenCore, macOS graphics matching,
WindowServer, native accelerator startup, or the current probe-readiness markers
behave identically with no emulated VGA. The first authorized candidate run would
be the discriminating observation and may fail before probe readiness. That is a
real result, consumes the reserved ledger row, and does not authorize a retry.

The pre-implementation launcher lacked graphics identity and manifest sealing;
Tasks 1–2 below close those source gaps. The reviewed runtime files still must be
deployed and hashed, and the candidate worktree must be built and staged before
the contract can authorize a launch.

## Tasks 1–2 independent review result

Tasks 1 and 2 are implemented in the working tree and independently reviewed.
The pinned image inspection established the real source shape before the entrypoint
contract was finalized: image `sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c`
contains `Launch.sh` SHA-256
`ae6050750f4ba26fbe85785da909b8f7d34fab064b6539d9a3f1903abf3fe302`,
with one `-vga vmware` and zero `-display` tokens. The final implementation
checks that exact shape, supplies one authenticated `-display none`, replaces
the VGA token with `none`, rejects the reviewed generic-device aliases, omits
`/dev/dri`, and verifies the narrow running graphics identity without recording
the secret-bearing full argv.

The candidate card and staging path preserve the candidate-183 functional boot
arguments, add `rgpuvmdiag=1` exactly once, carry the COM2 and no-generic launch
contracts into staging, and keep VMID1 fault-walk evidence optional for probe
readiness. The additive classifier matches the C++ producer's integer widths,
literal-zero formatting, decoded status fields, and page-entry bit layout;
invalid observed context remains diagnostic data while malformed known records
produce capture loss.

Final review ran 615 Python tests successfully with one explicit existing skip.
`git diff --check`, Python compilation, shell syntax, the five recovery-helper
comparisons against `d109910`, and the driver-source comparison against `d421120`
all passed. Both bundle version fields parse as `1.0.184`. No build, staging,
deployment, VM, QEMU, device, or sudo action occurred. Tasks 3–6 remain required
before any launch.

---

### Task 1: Make generic-adapter absence a sealed launcher contract

**Files:**
- Create: `tools/vm-entry.sh` from the exact reviewed live source
- Modify: `tools/macos-vm.sh`
- Modify: `tools/vm-supervision.py`
- Modify: `tools/experiment.py`
- Modify: `tests/test_experiment.py`
- Modify: `tests/test_vm_supervision.py`
- Modify: `tests/test_redeploy_lifecycle.py`
- Test: add a focused shell fixture for `tools/vm-entry.sh`

**Interfaces:**
- Consume manifest launch option `GENERIC_GRAPHICS=off`.
- Produce final QEMU arguments containing exactly `-vga none`, no generic display device, and an explicit no-window backend such as `-display none` for this diagnostic run.
- Produce `running-identity.json.graphics_args` sufficient to prove those facts without exposing the Apple SMC key.

- [x] Add failing tests that require `GENERIC_GRAPHICS=off` to pass from `experiment.py` through `vm-supervision.py` and `macos-vm.sh` into the container entrypoint.
- [x] Add a failing sanitized entrypoint fixture derived from the pinned image `Launch.sh` shape (source SHA-256 `ae6050750f4ba26fbe85785da909b8f7d34fab064b6539d9a3f1903abf3fe302`): exactly one `-vga vmware` token and no `-display` token. Do not retain the complete source because it contains the Apple SMC key. Require the generated argv to contain exactly one `-vga none` and no `vmware`, `VGA`, `qxl`, `virtio-vga`, `bochs-display`, or `ramfb` device.
- [x] Add refusal cases for a missing default VGA token, multiple VGA tokens, unknown graphics mode, and generic graphics injected through `EXTRA`.
- [x] Check in the reviewed entrypoint source, replace the exact `-vga vmware` token only after proving it occurs once, and select `-display none` for the headless diagnostic mode. Do not add `ramfb`.
- [x] Add `GENERIC_GRAPHICS` to the supervisor's explicit environment allowlist. Do not accept graphics policy through arbitrary `EXTRA`.
- [x] Add `vm-entry.sh` to `current_identity().harness_sha256`, staging identity checks, one-run policy identity checks, and deployment/hash verification.
- [x] Extend `running_identity` to retain only the graphics-related argv values and make `validate_running` require the manifested `-vga none` shape and reject every listed generic device.
- [x] Run the focused entrypoint, supervision, experiment, one-run, staging and redeploy lifecycle tests once after the implementation stabilizes. Review the exact generated argv without launching QEMU; do not repeat the 132-second tiny-guest gate unless collector, supervisor, UART topology, or formatter code changes.

### Task 2: Define the exact candidate-184 experiment contract

**Files:**
- Create: `experiments/metal-017.json`
- Modify: `tools/stage-candidate.py`
- Modify: `tests/test_stage_candidate.py`
- Modify: classifier tests only if the existing VMID1 records are not already decoded and exposed

**Interfaces:**
- Candidate version: `1.0.184`.
- Experiment ID: `metal-017`.
- Requested diagnostic: `rgpuvmdiag=1`.
- Functional arguments retain candidate 183's `rgpuvmroot=4` and normal submission path.
- Transport object is the exact COM2 contract from `tools/critical-transport.py`.

- [x] Write the card with `critical_replay_schema=2`, `recovery_lease_schema=3`, the exact `critical_replay_transport` object, `critical_replay_tolerance=terminal-prefix`, and `recovery_critical_replay_tolerance=terminal-prefix-open`.
- [x] Require `rgpuvmdiag=1`, `rgpuvmroot=4`, `rgpucr2uart=2`, numeric run nonces, the existing functional baseline, 180-second exposure, and probe only after native readiness.
- [x] State the hypothesis narrowly: for at most two distinct VMID1 fault pairs, compare relative and absolute walks without modifying tables or invalidation state. Require fault VA, context bounds/stability, root/entry addresses, raw entries and decoded attributes.
- [x] Preserve candidate-183 functional requirements so the unchanged Metal probe can run only if the existing classifier reaches `PROBE_NOT_RUN`. Treat absence of the new fault samples as inconclusive if no matching VMID1 fault occurs; do not manufacture a fault to obtain them.
- [x] Change `stage-candidate.py`'s candidate/card validation from its old fixed `rgpusubmit=1` assumption to the exact `metal-017` value and ensure the requested diagnostic is inserted exactly once. Keep `rgpusubmit=1` as part of the existing functional path.
- [x] Add exact card, boot-argument, unknown/duplicate diagnostic, transport symmetry, and old-card compatibility tests.

### Task 3: Produce and independently review immutable candidate artifacts

**Files:**
- Existing build tools and a new isolated candidate-184 worktree
- Outputs under new `/home/bogdan/macos-vm/run/candidate-184*` paths only
- Create a new build verification report under `findings/research/`

**Interfaces:**
- Produce one clean committed source identity, KDK build, candidate directory, distribution archive, build manifest and build-identities record.

- [ ] Re-run focused tests for files changed after `d421120`. The already passed COM2/VMID1 sanitizer and tiny-guest suites need not repeat when their source and helper hashes are unchanged. Run one final full Python suite, shell syntax check, route-domain check and exact-KDK preflight against the candidate commit.
- [ ] Verify the five recovery helper hashes remain byte-identical to the canonical values embedded in the recovered receipt path.
- [ ] Create an isolated candidate-184 worktree from one reviewed commit; require clean `git status` before build and staging.
- [ ] Build with the pinned 24G830 KDK and pinned Docker image `sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c`.
- [ ] Freeze source tree, binary, Info.plist, archive, build-manifest, build log, toolchain and KDK hashes. Record `physical_tested=false`.
- [ ] Have independent reviewers compare the built source to the approved COM2 and VMID1 designs and inspect the no-generic-graphics argv fixture.

### Task 4: Deploy the reviewed harness without launching

**Files:**
- Source: reviewed runtime files `tools/macos-vm.sh`, `tools/vm-entry.sh`, `tools/vm-supervision.py`, and `tools/sercat.py`
- Destination: exact corresponding `/home/bogdan/macos-vm/` paths

**Interfaces:**
- Produce a live harness whose hashes exactly match candidate-184 identity inputs.

- [ ] Recheck boot ID, absence of active/pending VM ownership, exact ledger bytes, exact canonical receipt bytes, and inhibitor immediately before deployment.
- [ ] Copy only the four reviewed runtime harness files through an explicit file-by-file transaction with preimage hashes and rollback copies. Deploy `redeploy.sh` only if a separately reviewed runtime dependency requires it. Keep `experiment.py`, `classify-run.py`, `critical-transport.py`, and `stage-candidate.py` in the complete candidate worktree: their repository-relative imports and `build-support` paths make standalone copies under `/home/bogdan/macos-vm` invalid and unnecessary. Do not invoke `redeploy.sh`, QEMU, or any device helper.
- [ ] Verify every destination hash and run `py_compile`/`bash -n` on the deployed copies.
- [ ] Verify historical defaults remain `CRITICAL_SERIAL=off` and generic graphics enabled. Verify only the exact manifested candidate selects `CRITICAL_SERIAL=on` and `GENERIC_GRAPHICS=off`; both deployed scripts must be byte-identical to the source pinned for the candidate.

### Task 5: Stage and prepare one exact manifest

**Files:**
- Input: `experiments/metal-017.json`, candidate-184 build identities, current OpenCore images
- Output: new candidate-184 staging paths and one new manifest path under `/home/bogdan/macos-vm/run/`

**Interfaces:**
- Produce a fresh 32-hex run ID and boot arguments containing exactly one each of `rgpuvmdiag=1`, `rgpuvmroot=4`, `rgpucr2uart=2`, `rgpusubmit=1`, `rgpurnlo`, and `rgpurnhi`.
- Manifest launch options must include `GENERIC_GRAPHICS=off`; the authenticated entrypoint derives the exact `-display none` backend from that option.

- [ ] Run `stage-candidate.py` from the clean candidate worktree only after its exact candidate version, card ID, commit, boot ID, card SHA-256, build-identities SHA-256 and image ID have been independently reviewed.
- [ ] Verify the private raw image, generated qcow2, final published OpenCore image and live config all agree before accepting `staging.json`.
- [ ] Run the candidate worktree's `experiment.py prepare` with the live VM directory and staging-selected run ID, then freeze the resulting manifest without launching.
- [ ] Verify manifest/card transport symmetry, schema 3, candidate directory, build identity, bootdisk hash, COM2 validator hash, all harness hashes including `vm-entry.sh`, launch options, maximum duration and probe duration.
- [ ] Verify no `-vga vmware` or generic-device option can enter through the manifest, launcher environment, `EXTRA`, or image entrypoint transformation.

### Task 6: Create a fresh one-run same-boot authority

**Files:**
- Create: `/home/bogdan/macos-vm/run/one-run-qualification-authorities/73ad3355-80a7-48f1-a8dd-e6f770b41de8/policy.json`
- Create: one activation named for the new candidate-184 run ID in the same directory
- Use: `tools/one-run-qualification.py`

**Interfaces:**
- Bind ledger preimage SHA-256 `2f715f2067a57cf502ae61d64a745121fd385556b055ad36f04480fadf000b83`, prior run `4661e574bbd5695d00176d85bfa87325`, and canonical recovery receipt SHA-256 `d2e2fad9244033002bdd3643e72049e9b4f4b858080aa8fa0cadd91d095ad367`.
- Keep `from_max_launches=3`, `to_max_launches=3`, `additional_launches=0`, and `automatic_retry=false`.

- [ ] Freeze the exact new card, manifest, output path, experiment helper, one-run helper, design, recovery helpers, candidate and harness identities in a new policy. Do not reuse an old policy or activation.
- [ ] Preserve two independently named receipt inputs as required by the one-run design. Use the live canonical path above for the helper's canonical lookup. After confirming the archived source `findings/experiments/metal-016-183-gui-73ad3355/recovery-migration/raw/canonical-receipt.json` and live canonical file both hash to `d2e2fad9244033002bdd3643e72049e9b4f4b858080aa8fa0cadd91d095ad367`, create one write-exclusive byte-for-byte copy of that archived source under a candidate-184 authority-input directory inside `/home/bogdan/macos-vm/run/`; set the new relative path as `prior_run_receipt_path` with a null member and record both source paths as provenance. This is archival evidence replication, not a fresh recovery or a reconstruction. Do not point at `gui183-recovery-result.json`: its receipt is nested two levels deep, while the supported helper accepts at most one top-level member.
- [ ] Create a `stage=ONLY` activation bound to the policy hash, manifest hash, new run ID, current ledger preimage, prior run/recovery IDs and both receipt hashes.
- [ ] Invoke the supported `one-run-qualification.py create` command once with the exact VM directory, boot ID, prior run, VM-relative receipt copy, card, VM-relative manifest/output paths, purpose, and `--additional-launches 0`; record its policy and activation hashes. The helper has no separate read-only authorization CLI. Let `experiment.py run` validate that immutable pair under its locks immediately before reservation rather than inventing or repeating an unsupported preflight command.

### Task 7: Final admission and single launch sequence

**Files:**
- Input: reviewed manifest, policy and activation
- Output: one new `metal-017-184` evidence directory

**Interfaces:**
- Invoke the candidate worktree's `experiment.py run` against the live VM directory with both exact `--one-run-policy-sha256` and `--one-run-activation-sha256` values. No other launch-authority mode may be supplied.

- [ ] Immediately before execution, refresh boot ID, exact ledger/receipt/manifest/harness hashes, no active container, no pending reservation, inhibitor, watchdog/pstore state, driver identity, reset-method state and VFIO accessibility through the existing admission functions. Any mismatch refuses the launch.
- [ ] Confirm the final source-generated QEMU contract is `-vga none`, explicit COM1 index 0, explicit COM2 index 1, and no generic display device. Do not promise a visible window.
- [ ] Reserve exactly one ledger row atomically and start the supervised launcher under the unchanged 180-second cap. The launcher starts QEMU so its Unix sockets exist; the supervisor then arms both collectors, verifies exact CID/channel ready tokens, bootstraps the guest agents, verifies the collectors again, and only then publishes supervision readiness. Do not claim collectors connect before QEMU starts.
- [ ] Require one exact build-bound `RGPU_UART_READY` line before probe admission. Parse CR2 only from `critical.log`; scan COM1 only through the narrow lifecycle path.
- [ ] Run the unchanged 45-second Metal probe only if existing native readiness reaches `PROBE_NOT_RUN` with time for probe and cleanup. Missing readiness under no-VGA is evidence, not permission to relax the gate.
- [ ] On any identity, capture, guest, host or timeout failure, request bounded guest shutdown when allowed, stop the exact CID, run normal schema-3 recovery from COM2, and emit a non-authorizing result if recovery or retirement is incomplete.
- [ ] Freeze `serial.txt`, `critical.txt`, both hashes, QEMU graphics/UART identity, probe, shutdown, recovery, host journal and final verdict. Update `status.md` with ledger now two of three and unresolved-cycle count seven unless reviewed evidence demonstrates meaningful progress past the VMID1 boundary.
- [ ] Do not retry automatically. A second launch requires a new reviewed hypothesis, new run identity and new authority, and remains subject to the remaining one-of-three numerical capacity plus successful recovery.

## Acceptance before any launch

Every task through Task 6 must be complete and independently reviewed. In
particular, the current recovered receipt and one-row ledger are necessary but
not sufficient authority; the fresh policy and activation are mandatory. The
no-generic-graphics property must be present in the card/manifest, applied by the
authenticated entrypoint, propagated only through explicit supervisor settings,
and verified from the running QEMU argv. If the operator's goal still requires a
visible Raphael desktop, stop before Task 7: current evidence provides no such
presentation route.
