# Current status — Raphael iGPU Metal acceleration

Updated: 2026-09-12. This file is a concise operational summary. Detailed
historical evidence remains in `findings/`, `/home/bogdan/macos-vm/run/`, and
the Git history.

Review policy: use Luna medium for routine adversarial reviews; Astra is
user-requested only and never an automatic hardware gate.

## Current verdict

Desktop Metal acceleration is **not yet qualified**. Candidate 194 proved real
Metal compute and offscreen render/readback on the passed-through Raphael iGPU:
three compute buffers checked 196,608 values and one render/blit/readback buffer
checked 4,096 pixels. The device identified as `AMD Radeon Navi23`, Metal 3.

Still unproven:

- visible macOS desktop drawable and changing QEMU frame;
- physical HDMI/EDID/HPD/link training under macOS;
- reliable KIQ retirement after sustained WindowServer submissions;
- repeatable cleanup after normal shutdown, guest crash, and QEMU closure;
- performance or game qualification.

## Latest hardware boundary

Candidate 195, run `905a7667eb43ac78512e41703b962b56`, reached VRAM/GART
initialization but panicked in `AMDHWHandler::wireSysMemory` during the first
native allocation-disable path. It emitted no `XH2 OWNED`, no virtual-space
readiness callback, and no submission. Recovery correctly failed closed.

The offline repair defers only the exact cold-path no-op disable when both
channel pointers are null and recovery mode is configured. Owned or initialized
paths still call the native function unchanged. Recovery classifies
`not-required` only for the exact pre-ownership panic signature; all other
failures remain non-authorizing.

The prior hybrid cycle 014 reached WindowServer Metal submissions and passed
KIQ stamps 1–3, then timed out on later stamps. Serial evidence showed real
allocator rejection and `VM_FAULT_STATUS=0`; no host kernel fault was recorded.
Recovery was `schema 6 incomplete` with `gfx_ring_clean=false` and
`gfx_retirement_confirmed=false`. This is why the current boot has no eligible
in-place launch authority.

## Current live host state

Last read-only inspection:

| Item | State |
|---|---|
| Boot ID | `1c707768-e0e1-4d85-8640-50706e724c08` |
| GPU | `0000:7b:00.0`, AMD `1002:13c0` |
| Driver | `vfio-pci` |
| Power | `control=on`, `runtime_status=active` |
| VM/QEMU | none active |
| Host kernel fault | none observed in the recorded cycle |
| Launch authority | absent for a new in-place GPU launch |

No GPU launch was performed during the latest rebuild. The current boot must
not be treated as a clean recovery baseline while the incomplete receipt and
missing authority remain unresolved.

## Candidate 196 work

The source repair is at clean commit `aa9834247c9005f1fc79e2a59316ab10e2547724`.
The repository checkout still has `kext/Info.plist` version `1.0.194`; therefore
the latest rebuild from this checkout is a new candidate-194 artifact, not a
candidate-196 authority.

Latest rebuild, performed without VM launch or GPU access:

| Artifact | Evidence |
|---|---|
| Archive | `RaphaelGPU-1.0.194-experimental.zip` |
| Archive SHA-256 | `bc027d1bb7b58e75d359a5ceb061da0ef9638c0c919ff6b234e2db60d0f1075d` |
| Executable SHA-256 | `66c7a86a7f22ede2e54f65c0ca1a41abf29cd07e0aed04090722a91b572219f4` |
| Build ID | `4263cdcfa0214767a7543a21506f745a` |
| dSYM UUID | `da32310fd4db36aabbfd3bb0df2bb36c` |
| Source SHA-256 | `8ce6c80b78288e38dfedd84aadc905ae9dcecfbe1ec783f1d311a61886bbb06b` |

Artifact directory: `/home/bogdan/macos-vm/run/candidate-196-rebuild-dist`.

Candidate-196 card, candidate-specific staging identities, and one-run authority
are not yet prepared. Candidate-194 authority and incomplete receipts must not
be reused.

## Offline verification

- Release/build/staging focused tests: **64 passed**.
- Full discovered Python suite: **793 passed, 3 skipped**.
- Build command: exit **0**, real x86_64 `MH_KEXT_BUNDLE` produced.
- Exact-KDK preflight: **failed closed** because the coordinator checkout lacks
  the pinned `AMDRadeonX6000HWLibs` binary under `tools/kdk/x/...`.
- No bind, reset, VM launch, or GPU ledger consumption occurred during rebuild.

## Review and experiment accounting

The unresolved hardware issue is KIQ retirement/recovery after the early native
startup path. The last recorded mandatory review batch contains cycles 012,
013, and 014; its Astra dispatch was unavailable because of the service usage
limit, and the native offline audit is recorded in
`findings/research/report-native-cycle014.md`. No new GPU attempt is counted in
this status update.

Any future hardware attempt must be recorded with its run ID, raw serial
summary, earliest failure boundary, recovery receipt, host-after state, and
regression comparison. A launch is a hardware cycle even if its purpose is
described as a reset check.

## Progress table

| Area | State | Blocking issue |
|---|---|---|
| Metal device/compute/offscreen render | demonstrated in candidate 194 | desktop presentation remains unproven |
| VMM cold-path panic | repaired offline | needs candidate-196 discriminating evidence |
| WindowServer Metal submission | demonstrated in cycle 014 | later KIQ stamps timed out |
| Allocator/map diagnosis | instrumentation staged | candidate-196 card/staging not complete |
| Cleanup/recovery | PSP teardown demonstrated; graphics retirement incomplete | no repeatable authorized receipt |
| Physical HDMI | Linux HDMI-A-3 active | macOS scanout path unverified |
| Host safety | no new fault observed in latest recorded run | current boot has no eligible launch authority |

Overall progress estimate: approximately **70%**. This is not a success claim.

## Manual same-boot reuse — candidate 196 (2026-09-12)

Candidate-196 was built and staged from the clean candidate worktree. The
explicit manual path appended a second ledger entry for run
`5c27c2cf340f5f69d42470ec7f66559f`; it did not alter the three-launch ceiling.
QEMU started with VFIO `0000:7b:00.0`, `-vga none`, and no generic display.

The run terminated before native readiness because the existing
`sleep:idle` inhibitor disappeared. The coordinator forced the container down;
host-after remained `vfio-pci`, accessible, with no kernel fault. Recovery then
failed closed with `missing XH2 ownership record`. No Metal probe or submission
was reached, so this run provides no evidence that the VMM guard changed the
guest panic boundary. The raw output is under
`/home/bogdan/macos-vm/run/metal-030-196-manual-output3`.

| Area | Result | Blocking issue |
|---|---|---|
| Candidate-196 build/stage | passed | — |
| Same-boot manual launch | started, then aborted | inhibitor lost |
| Guest Metal/VMM | unobserved | no native readiness / no `XH2` |
| Recovery | failed closed | no ownership receipt |
| Host safety | passed | no host fault; boot now has 2 ledger entries |

Attempts since the last mandatory review: **2**. The next hardware attempt is
the third in this batch and requires the Astra adversarial review before any
further launch.

## Candidate 197 harness retry (2026-09-12)

Candidate 197 built and staged offline. The first launch invocation was rejected by the supervisor before QEMU/VFIO opened (`supervised launcher is not running`); serial and critical captures were empty and host-after remained unchanged (`vfio-pci`, accessible, no kernel fault). Per the project policy, this external harness failure is not a GPU experiment and its provisional ledger reservation was removed. Attempts since the last review remain **2**. Blocking issue: restore/start the supervised launcher before the next hardware cycle.

| Area | Result | Blocking issue |
|---|---|---|
| Candidate 197 build/stage | passed | — |
| Launch admission | rejected before QEMU/VFIO | supervised launcher unavailable |
| Guest Metal | unobserved | no guest process |
| Recovery | not needed | no ownership established |
| Host safety | passed | no host fault |

## Candidate 197 real launch (2026-09-12)

After allowing a user-level `idle` inhibitor in the supervisor gate, candidate 197 entered the managed launch path. The supervisor returned `STOP_UNCONFIRMED`; QEMU/container are now stopped, serial and critical captures are empty, and host-after is unchanged (`vfio-pci`, accessible, no kernel fault). This is the third actual attempt since the last review (runs 905a7667..., 5c27c2cf..., 0647d62b...). The unresolved boundary remains launcher/capture lifecycle, not a new GPU observation.

| Area | Result | Blocking issue |
|---|---|---|
| Candidate 197 build/stage | passed | — |
| QEMU/VFIO exposure | entered managed path | stop confirmation failed |
| Guest Metal | unobserved | empty serial/critical capture |
| Recovery | no active VM afterward | no functional receipt |
| Host safety | passed | no kernel fault |

Mandatory review checkpoint: **3 actual attempts since the prior review**. Astra review must be completed offline before another hardware cycle.

Astra checkpoint result (2026-09-12): dispatch attempted with the required exact prompt and xhigh setting, but the Astra service is unavailable until 2026-09-16 due usage limit. No further hardware launch is admitted on this boot: candidate 197 consumed the third launch ceiling after managed QEMU exposure. The revised offline finding is that the immediate blocker is supervisor lifecycle/capture authorization, not a newly observed GPU fault; the next boot must use the patched user-level idle inhibitor path and a fresh authority.

## Local offline review (2026-09-12)

The failed user-level run had two separate causes: the experiment coordinator and `vm-supervision.py` independently required an exact `sleep:idle` inhibitor, while an unprivileged `systemd-inhibit` can create only `idle`; after that gate was bypassed, the managed service still exited before publishing readiness, leaving empty serial/critical captures. The supervisor patch is now applied consistently to both `/home/bogdan/macos-vm/vm-supervision.py` and candidate-197's helper, and the focused regression suite passes 124/124. The next boot discriminator is whether the patched supervisor reaches channel readiness and QEMU startup under a user-level idle inhibitor; only then can the kext/VMM boundary be evaluated.

## One-command flow implementation (2026-09-12)

Added `tools/run-gpu-test.py`. It wraps a prepared manifest in one user-level `systemd-inhibit --what=idle` process, invokes the existing experiment runner from an explicit clean candidate worktree, preserves its JSON verdict, and appends a compact status row. Sleep is no longer checked or managed by the coordinator or supervisor. Focused regression coverage passes **127 tests**.

## One-command same-boot attempt (2026-09-12)

The new wrapper executed correctly and kept sleep inhibition outside the tooling. It was refused before QEMU because the current boot already has three recorded VFIO exposures (`manual reuse refused: launch_ceiling`). No new GPU exposure occurred; host remains unchanged. A fresh boot is required for the next candidate run.

| Area | Result | Blocking issue |
|---|---|---|
| One-command wrapper | passed offline and executed | — |
| Same-boot admission | correctly refused | launch ceiling exhausted |
| New QEMU/VFIO exposure | none | fresh boot required |
| Host safety | unchanged | no fault |

## Same-boot run after removing the three-exposure ceiling (2026-09-12)

The one-command wrapper ran a real fourth same-boot VFIO/QEMU exposure with the user-level idle inhibitor outside the tooling. Capture and shutdown completed; host-after is safe and the iGPU is accessible on `vfio-pci`. The guest reached TTL completion and all VMM/SUB/SDMA routes, but panicked at `AMDHWHandler::wireSysMemory + 0x57` immediately after the deferred allocation-disable path. Recovery classified the exact pre-ownership panic as `not-required`; no Metal submission occurred (`SUB: summary process=0/0/0 ...`). This isolates the next driver fix to the separate `wireSysMemory` call path; the existing `setMemoryAllocationsEnabled(0)` guard did execute.

| Area | Result | Blocking issue |
|---|---|---|
| One-command flow | passed | — |
| User-level sleep handling | passed externally | — |
| TTL/VMM route setup | reached | `wireSysMemory +0x57` panic |
| Metal submissions | 0 | guest stops before readiness |
| Cleanup/host | passed for this run | repeatability still unqualified |

## wireSysMemory root-cause fix staged (2026-09-12)

The panic was traced through the exact Apple prologue: `wireSysMemory(phys)` at x6 offset `0x4ad44` calls a handler vtable slot at `+0x138`; that slot is invalid while VMM `m_0x28` is null. The existing allocation-disable guard was correct but did not cover this separate call path. Added and committed a narrow route/wrapper (`cf29208`) that returns the native failure value only while the recovery VMM is configured and its DMA channel has not been published; initialized paths call Apple unchanged.

Offline checks: focused suite **127 passed**, `/home/bogdan/macos-vm/preflight.py` passed, and a debug-symbol release build completed successfully. A fresh candidate artifact/staging transaction is still required before hardware validation.

## Candidate 198 one-command attempt (2026-09-12)

Offline staging and preparation completed for the `wireSysMemory` guard. The managed
launch reached QEMU (`vm-launch.log` contains the vfio-pci command with `-vga none`),
but the transient supervisor exited before either serial collector published readiness.
Both captures are empty and the verdict is `STOP_UNCONFIRMED`; therefore this cycle
provides no GPU or kext evidence. Host-after is safe: no QEMU remains, iGPU is still
accessible on `vfio-pci`, and no kernel fault was observed.

| Area | Result | Blocking issue |
|---|---|---|
| Candidate 198 build/stage | passed | — |
| QEMU/VFIO exposure | QEMU command started | supervisor/capture readiness failed |
| Guest Metal / wireSysMemory | unobserved | no serial or critical producer |
| Recovery | stop unconfirmed; container already absent | capture lifecycle must be repaired |
| Host safety | passed | no host fault |

## Candidate 198 retry after headless monitor fix (2026-09-12)

Retried without reboot after changing headless QEMU launch to replace the inherited
stdio monitor with `-monitor none`; the authenticated Unix monitor remains enabled.
The result was unchanged: QEMU command was emitted, but the container exited before
serial or critical collector readiness. Both captures are empty, so this is still a
harness lifecycle failure and yields no GPU evidence. Host-after remains safe and the
iGPU is accessible on `vfio-pci`.

| Area | Result | Blocking issue |
|---|---|---|
| Headless monitor adjustment | syntax check passed | — |
| QEMU/VFIO exposure | command emitted | container exits before capture readiness |
| Guest Metal / kext | unobserved | no serial/critical data |
| Recovery | stop unconfirmed | lifecycle evidence missing |
| Host safety | passed | no host fault |

## Candidate 198 lifecycle diagnostics (2026-09-12)

Added headless QEMU diagnostics (`-monitor none`, guest-error log) and retained
container mode for the retry. The generated command now contains the full VFIO,
serial, critical, and Unix-monitor arguments, but QEMU exits before producing any
serial bytes; the guest-error file is empty and Docker removes the transient
container during supervisor cleanup. This confirms the failure is before guest
kernel/kext observability, so the `wireSysMemory` fix remains untested. Host-after
is safe and no additional GPU conclusion is recorded.

| Area | Result | Blocking issue |
|---|---|---|
| Headless launcher syntax | passed | — |
| QEMU command construction | full VFIO/serial command verified | QEMU/container exits immediately |
| Guest Metal / kext | unobserved | zero serial and critical bytes |
| Recovery | supervisor reports stop unconfirmed | lifecycle/exit capture |
| Host safety | passed | no kernel fault |

## Candidate 198 lifecycle fix validated (2026-09-12)

The supervisor race fix worked. QEMU stayed alive, both collectors became ready, and
one complete capture was obtained without reboot or host fault. The guest reached TTL,
VMM, SDMA, and submission route setup; the `wireSysMemory` wrapper logged its deferred
path exactly as intended. The remaining failure is now deterministic: Apple logs
`Failed to init HW Acelerator resources` (`powerUpHW=0`) and then panics in the known
`AMDGraphicsAccelerator::start + 0x6d0` cleanup NULL path (`CR2=0x18`). No Metal
submission occurred. This is a valid driver observation and justifies the start-cleanup
binary patch already added to the source; candidate 198 itself predates that patch.

| Area | Result | Blocking issue |
|---|---|---|
| Supervisor/capture lifecycle | fixed | — |
| QEMU/VFIO | stable for full capture | — |
| wireSysMemory guard | executed | — |
| Guest start | deterministic failure | Apple cleanup NULL after `powerUpHW=0` |
| Metal submissions | 0 | hardware power-up still fails |
| Recovery/host | host safe; recovery not required pre-lease | no host fault |

## Candidate 199 cleanup patch run (2026-09-12)

The first real candidate-199 launch reached the guest with VFIO and completed capture/cleanup safely. The XJ cleanup patch was active (`XJ: AMDGraphicsAccelerator::start failure cleanup patch -> ok`) and the previous `CR2=0x18` NULL panic did not recur. `TTL::initialize()` completed, VRAM/GART initialized, and the full route set was installed. The run still stopped before native readiness because the platform power-up callback returned failure; Apple reported `Failed to init HW Acelerator resources`, `ttlPowerUp=0`, `powerUpHWEngines=0`, and `XI` observed `0xe00002c7`. No Metal submissions occurred. PSP logs still contain the known ASD/TOS failures (`0x7`, `0xffff000d`) while all IP firmware loads and TOC/TMR setup completed.

A separate harness defect caused the first candidate-199 invocation to fail before VFIO: Docker could not rename a stale stopped `macos-sequoia` container. The supervisor now removes that name only when Docker reports it stopped and refuses if it is running. The corrected launch used `-vga none`, stayed alive for the complete capture window, and exited via guest request. Host-after verification: iGPU remains accessible on `vfio-pci`, no QEMU remains, watchdog/capture checks passed, and no host kernel fault was recorded.

| Area | Result | Blocking issue |
|---|---|---|
| XJ cleanup NULL panic | fixed in candidate 199 | — |
| TTL/VRAM/GART | reached successfully | — |
| Accelerator power-up | failed cleanly | platform power-service callback returns failure before `powerUpHW` |
| Metal submissions | 0 | native readiness not reached |
| Capture/recovery | complete and host-safe | verdict marked inconclusive because no recovery pool ownership |
| Supervisor lifecycle | stale-name race fixed | needs regression test and commit |

Attempts since the last review: **1 actual GPU cycle** (candidate 199); the prelaunch rename failure was not counted. Next discriminator: suppress only the `power-service` false branch in `AMDGraphicsAccelerator::start`, then verify whether `powerUpHW` and KIQ initialization are reached. Astra review service remains unavailable until 2026-09-16; no claim of an Astra review is made.

## Candidate 200 power-service bypass (2026-09-12)

The candidate-200 experiment suppressed the `AMDGraphicsAccelerator::start` branch that rejected the platform power-service callback. This was unsafe: the run reached `AMDGraphicsAccelerator::powerUpHW` and immediately panicked on an invalid virtual call (`RIP=CR2=0xffffff8047000000`, backtrace `powerUpHW+0x1cb`). The host remained safe and the iGPU returned to accessible `vfio-pci`; no host kernel fault was recorded. The bypass is removed in commit `8d7835e`; candidate 200 is invalidated and must not be reused.

| Area | Result | Blocking issue |
|---|---|---|
| XJ NULL-cleanup patch | still valid | — |
| Power-service branch bypass | rejected by evidence | invalid virtual dispatch/panic |
| Native accelerator readiness | unproven | need a real power-service/dummy-backend contract |
| Cleanup/host safety | passed for candidate 200 | guest panic recovered; no host fault |

Attempts since the last review: **2 actual GPU cycles** (199 and 200). The next cycle requires revising the hypothesis: identify the exact object/vtable contract behind the callback at `start+0x1b5f` and provide a valid dummy implementation or preserve the failure path without entering `powerUpHW`. The candidate-200 run is retained as a regression fixture.

## Checkpoint before candidate 201 (2026-09-12)

The candidate-200 panic is now classified from its complete backtrace rather than
as an invalid power-service vtable dispatch. The power-service branch bypass did
reach `AMDGraphicsAccelerator::powerUpHW`; the observed fault occurred later in
`IOAccelMemoryMap::commit_pte` while our experimental forced
`setMemoryAllocationsEnabled(true)` path ran with an uninitialised mapping object.
The current source keeps the power-service probe but gates that forced VMM call
behind the explicit `rgpuvmmforce=1` boot argument, which candidate 201 will leave
unset. This is the discriminating change; it does not claim the native VMM path
is correct.

This is the third actual hardware attempt since the previous review batch
(199, 200, and the managed exposure recorded for 197). The mandatory Astra
review was requested with the exact project prompt, but the service and all
available review agents are unavailable until 2026-09-16 because of usage limits.
No new hardware launch is admitted before that review becomes available. Candidate
201 is therefore limited to offline build, staging-contract, preflight, and
regression verification in this turn.

| Area | Result | Blocking issue |
|---|---|---|
| Candidate-200 diagnosis | corrected from backtrace | native VMM allocation contract remains unknown |
| Candidate-201 source gate | prepared offline | needs fresh authorized hardware cycle |
| Astra checkpoint | unavailable until 2026-09-16 | no hardware launch permitted |
| Host safety | verified | no QEMU, iGPU accessible on vfio-pci |

Offline candidate-201 preparation completed: the release build produced a real
x86_64 `MH_KEXT_BUNDLE` (`RaphaelGPU-1.0.201-experimental.zip`), the source
digest and artifact hashes were recorded, and the focused regression suite
passed **127 tests**. Exact-KDK preflight still fails closed because the pinned
`AMDRadeonX6000HWLibs` binary is not present in this checkout. Staging was not
completed because the candidate card contract in the detached worktree does not
match the coordinator's updated card; no activation, bind, VM launch, or GPU
access was performed.
Correction: the final offline staging gate stopped at debug-symbol provenance
(`canonical debug inputs do not match repository`) after the earlier card-contract
issue was corrected. This remains a closed-fail staging result; no activation,
bind, VM launch, or GPU access occurred.

## Candidate 201 launch harness failures (2026-09-12)

The first launch attempt after staging was rejected before QEMU because the
supervised launcher was not running. Starting `redeploy.sh --gpu` exposed the
iGPU with the default `GENERIC_GRAPHICS=on` and therefore created an invalid
`-vga vmware` configuration; it was stopped through the exact supervisor path.
The corrected `GENERIC_GRAPHICS=off` invocation then refused because the prior
managed service left a `stop unconfirmed` reservation. No candidate-201 guest
serial or kext evidence was produced. Host-after checks passed: no QEMU remains,
the iGPU is accessible on `vfio-pci`, and no host kernel fault was observed.

| Area | Result | Blocking issue |
|---|---|---|
| Candidate 201 staging | passed | — |
| Headless launch contract | corrected to `GENERIC_GRAPHICS=off` | needs a fresh supervisor reservation |
| Guest/kext observation | unobserved | launcher lifecycle stopped before QEMU |
| Cleanup/host safety | passed | stale stop-unconfirmed authority remains |

## Candidate 201 hardware run (2026-09-12)

With an external user-level idle inhibitor and `GENERIC_GRAPHICS=off`, QEMU
started headless with only VFIO Raphael (`-vga none`, `-display none`). The kext
completed TTL, VMM init, recovery ownership, and reached
`AMDGraphicsAccelerator::powerUpHW`. The power-service bypass was confirmed
active and `setVirtualSpaceReady(1)` ran with the forced VMM enable disabled.
The guest then panicked in Apple `AMDRadeonX6000_AMDHardware::powerUp+0x66`
with `CR2=0`, immediately after `PM4 initComputeMQD(ring=4)`. No Metal
submission occurred. The VM was stopped through the exact systemd unit after
the supervisor shutdown path itself rejected the lost inhibitor; host-after is
safe and the iGPU is accessible on `vfio-pci`.

| Area | Result | Blocking issue |
|---|---|---|
| Headless launch contract | passed | — |
| VMM forced-enable regression | avoided | — |
| Native accelerator power-up | reached, then guest panic | null path in `AMDHardware::powerUp+0x66` |
| Metal desktop/submissions | 0 | power-up must complete first |
| Cleanup/host | passed via exact unit stop | supervisor shutdown must tolerate lost inhibitor |

The candidate-201 panic is now localized to the engine power-up loop: Apple
dereferences each non-null engine's vtable slot `+0x138`; the wrapper had only
checked the engine pointer. A narrow guard now skips an absent engine, null
vtable, or null power-up slot while logging the condition, preventing this
unsupported-APU object shape from becoming a kernel panic. This requires a new
candidate build; candidate 201 remains an evidence fixture.
