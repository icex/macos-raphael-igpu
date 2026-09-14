# Current status — Raphael iGPU Metal acceleration

Updated: 2026-09-13. This file is a concise operational summary. Detailed
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

Updated 2026-09-13 after candidate 212. The former "KIQ blocker" is a graphics
ring hang on the first WallpaperSequoia desktop draw; KIQ, HIQ, SDMA and the
small Metal compute probe all work (full audit:
`findings/research/gfx-ring-hang-misattributed-as-kiq-20260913.md`). Candidates
210 (baseline), 211 (Linux GC 10.3.6 golden registers) and 212 (hang dump) all
stall the same way: the PFP has consumed the whole 0xd10-dword IB of channel 35
stamp 8 and waits on the ME; the ME is parked (instruction pointer static) with
a WAIT_REG_MEM as its newest packet; `CP_STALLED_STAT2=0x230000`, no VM fault.
Same-boot relaunch is now reboot-free through `tools/smu-mode2-reset.py`.

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

## Candidate 203 automatic VRAM discovery (offline, 2026-09-13)

Candidate 203 implements runtime VRAM capacity discovery from the GFXHUB FB
base/top registers and the mapped BAR length. The shared helper validates
zero/reversed/high-bit bounds, arithmetic overflow, BAR visibility, and native
provider pool totals/visible sizes. Native pool fields are preserved; recovery
and diagnostics use the discovered visible bound, while native VMM validation
uses the logical total and selects the primary or secondary cursor from the
provider pool pair. Invalid discovery fails closed before allocation enable.

Offline evidence:

| Check | Result | Evidence |
|---|---|---|
| C++ recovery lease/helper fixtures | passed | `/tmp/test_recovery_lease` |
| Recovery/lifetime Python tests | 32 passed | `python3 -m unittest discover -s tests -p 'test_recovery*.py'` |
| Authentic preflight | passed | `/tmp/preflight-203d.out` |
| Release build | passed | `/home/bogdan/macos-vm/run/capacity-auto-offline-203d/RaphaelGPU-1.0.203-experimental.zip` |

Artifact SHA-256: `e4d79c67a5e289748244b3189e890102f3de22afeb322fe5d74229f8b67a3713`.
No QEMU or hardware run was performed, so this remains offline implementation
evidence and does not change the desktop acceleration qualification verdict.

## Candidate 204 hardware run (2026-09-13)

The single approved candidate-204 invocation used the prepared manifest,
external user-level idle inhibition, headless `GENERIC_GRAPHICS=off`, and no
override or retry. It returned `INVALID` before reservation or launch because
the archival identity check failed with `familiar container identity changed
while archiving`. The candidate output contains no serial or critical bytes, and
no candidate-204 QEMU/VFIO exposure occurred. The QEMU log and CID file found
under the shared run directory are stale artifacts from prior runs (their
timestamps predate this invocation) and are not candidate-204 evidence. No
capacity, native VMM range/pool, Metal, or probe observation was reached.

Evidence is retained under
`/home/bogdan/macos-vm/run/candidate-204-results/` including the manifest,
verdict, capture hashes, events, host snapshots, and shutdown record. Host-after
remains safe: boot `2f77212f-34f5-4905-ba66-d8c68a860d78`, `vfio-pci`, device
accessible and pinned awake, no active VM, no kernel fault, and the inhibitor
still active. No candidate-204 recovery ownership or receipt exists. The
blocking issue is stale container identity during prelaunch archival validation;
no second launch is authorized.

| Area | Result | Blocking issue |
|---|---|---|
| Candidate 204 launch | refused before reservation or exposure | stale container identity during archival validation |
| Guest serial / critical | 0 / 0 bytes | capture producer readiness absent |
| Capacity / VMM / Metal | unobserved | run stopped before guest evidence |
| Cleanup / host | safe; no VM; VFIO accessible | no recovery receipt because no launch |

## Candidate 204 retry hardware run (2026-09-13)

After the prelaunch archival failure was corrected, the approved retry reached
QEMU/VFIO with fresh supervision evidence. Supervisor CID
`a6df8582e104f32b8fb0d97aa6bc7e7cda731e3ae94abea2d838ba97fefa8860` started at
`2026-09-13T14:09:20.042410301Z` (`17:09:20` local); both serial and critical
collectors became ready. Runtime capacity discovery succeeded with
`rawTotal=0x20000000`, `BAR=0x10000000`, provider pools `512 MiB/256 MiB`.
Native VMM selected `0x1b000000..0x1f400000`, matching the predicted range, and
the recovery lease was `0xfaf3000..0xfb08000`, disjoint from it. Both pools were
active after lease subtraction.

The run reached native accelerator start and real Metal activity, but the small
Metal probe timed out after 5 seconds with `completed_command_buffers=0` and
`values_checked=0`. The bounded verdict is valid `BASELINE_BLOCKED` at the KIQ
boundary. Recovery completed host cleanup but is schema-6 `incomplete` and
`authorizes_launch=false`: graphics ring cleanup was not confirmed
(`gfx_ring_clean=false`, `gfx_retirement_confirmed=false`), although the lease
and lifetime records were unchanged and SDMA shutdown completed. No second run
is authorized on this boot.

Evidence is retained under
`/home/bogdan/macos-vm/run/candidate-204-retry-results/`, including serial
(523019 bytes), critical (1043298 bytes), probe, verdict, recovery, shutdown,
and host-after records. Host-after is safe: `vfio-pci`, accessible and pinned
awake, no active VM, no kernel fault, and the external inhibitor remains active.

| Area | Result | Blocking issue |
|---|---|---|
| Capacity discovery | passed | — |
| Native VMM | passed; actual range matched prediction | — |
| Metal probe | device `AMD Radeon Navi23`, Metal 3; timeout | KIQ baseline block; 0 completed buffers |
| Recovery / cleanup | host safe; SDMA quiesced | graphics retirement unconfirmed |

## Candidate 208 hardware probe (2026-09-13)

Candidate 208 run `5577d1bc03ccc5505eaf234cd32f2077`, CID
`c05e4541f6c7d868f2f84e757ce90b940ec38ee404bc5c4ee36c41049aefb4d3`, boot
`2f77212f-34f5-4905-ba66-d8c68a860d78`, build
`c7a87c58b9bd4175964a95ff8c8de00c` reached the contained mode-3 native probe.
GDB authenticated entry, native boundary, and first return; native returned
`0xe00002bc` and `native_reached=true`. Serial showed the native call cleared
MEC halt (`MEC=0`) while leaving `ACTIVE=1`, `RPTR=0`, `WPTR=0x20`, and `EOP=0`;
the wrapper recontained MEC at `0x50000000` and returned failure. This falsifies
the assumption that Apple leaves MEC halted through native start. Shutdown
completed after the manual coordinator stop; host-after remained VFIO-bound,
accessible, and sleep-inhibited. Recovery failed closed because no exact ACTIVE
pool record was available. No Metal submission occurred.

## Candidate 212 graphics-ring hang dump (2026-09-13)

Run `c1dfbb3e252bdacb986e3fca140c6754`, card `metal-046` (commit `cc84356`),
source `f9d083f`, build `d21d79e4731f42a3824ba96015b326d5`, boot
`c369c74e-96ff-4c21-ae85-80ccb269f7d2`, launch 3 of 3 on the ledger with the
manual-reuse override after SMU MODE2 reset receipt `run/mode2-reset-2.json`
(reset OK; `RLC_CNTL 1 -> 0`, `RLC_BOOTLOAD_STATUS -> 0`). Boot arguments as
candidate 211 plus `rgpuhangdump=1`. Evidence: `run/candidate-212-results/`,
decoded in `findings/research/candidate212-gfx-hang-dump.md`.

- Verdict `BASELINE_BLOCKED/kiq` (classifier label for the HIQ unmap timeout).
  Small Metal probe **passed** (`completed_command_buffers=1`). Recovery schema 6
  `recovered`; shutdown `exited-after-guest-request`; host after: vfio-pci,
  device accessible, sleep inhibited, no active VM.
- The hang dump fired once at the first stalled KIQ observation:
  `RB0 RPTR=0x1fb1` static for 50 ms, `WPTR=0x2180`, `CP_STAT=0x94079200`,
  `CP_STALLED_STAT2=0x230000`, `GRBM_STATUS_SE0=0xed400000`,
  `PA_SC_FIFO_SIZE=0`, PFP instruction pointer looping (`0xb21->0xb20`), ME
  (`0x619`) and CE (`0x61b`) static, VM fault 0.
- Ring: per-frame `COND_EXEC`, `COPY_DATA`, `WRITE_DATA VGT_EVENT_INITIATOR=0x16`,
  `SET_UCONFIG_REG CP_WAIT_REG_MEM_TIMEOUT=0`,
  `WAIT_REG_MEM (CP_COHER_STATUS & 0x80000000) == 0`, then
  `INDIRECT_BUFFER 0x4001d0000 len 0xd10 vmid 3` (the stuck IB, 7x larger than
  the 0x1e0-dword frames before it). RPTR sits right after that IB packet.
- `CP_IB1_BASE=0x4001d0000`; Apple's own restart report says the IB was
  consumed to the end (`RemainSize=0`) and prints its first 0x100 dwords.
  `CP_*_HEADER_DUMP` reads newest first: the five oldest ME entries match the IB
  packets at dwords 0xe3..0xf4 exactly, so the ME's newest packet is a `WAIT_REG_MEM`
  located after IB dword 0x100, preceded by `WRITE_DATA` and opcode 0x49.
- The kext could not read the IB itself: VMID 3's page-table root
  `0x85b01e000` lies beyond the 256 MiB CPU-visible BAR (`physical FB
  0x840000000`). Ring pages (GART, SYSTEM) read correctly.

| Candidate | Change | GFX ring | Compute probe | Recovery |
|---|---|---|---|---|
| 210 | baseline, first launch on fresh boot | stall ch35 stamp 8 | timeout | incomplete |
| 211 | GC 10.3.6 golden registers | same stall | passed | incomplete |
| 212 | read-only hang dump | same stall; ME in WAIT_REG_MEM inside IB | passed | recovered |

Blocking issue: the ME never satisfies a `WAIT_REG_MEM` inside WallpaperSequoia's
first 0xd10-dword draw IB. Next: candidate 213 prints the whole pending command
buffer through Apple's `mapCmdBuffers` from the restart report path and
evaluates every `WAIT_REG_MEM` target (register value or GART memory) plus the
`CP_COHER_*`/`CP_ME_COHER_*` registers.

## Boot-launch ledger extension for candidate 213 (2026-09-13)

The ledger for boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2` is exhausted (three
launches: candidates 210, 211, 212). The user authorized extending it with an
explicit note. Candidate 213 is launch 4 on this boot, taken through the
`--manual-reuse --ack-risk` override, which appends a `manual_override` row and
leaves `max_launches` at 3. Precondition: a fresh SMU MODE2 reset receipt
(`run/mode2-reset-3.json`) showing `RLC_CNTL=0` and `CP_STAT=0` immediately
before staging; host must still be vfio-pci and accessible. No launch beyond
this one is covered by this note.

## Candidate 213 pending command buffer capture (2026-09-13)

Run `f9e798c8ecba24f88f3dd6551405bdfa`, card `metal-047` (commit `9ce67d2`),
source `73448a0`, build `b93f5ae673b14cfc9aca7bd8f140345c`, boot `c369c74e`,
launch 4 under the ledger extension above, after MODE2 reset receipt
`run/mode2-reset-3.json` (`RLC_CNTL 1 -> 0`, `CP_STAT=0`). Evidence:
`run/candidate-213-results/`.

- Verdict `CORE_PROBE_PASS` (no functional boundary): the HIQ unmap waits
  retired this time and the only KIQ stamp timeout came during shutdown. Probe
  passed; recovery schema 6 `recovered`; shutdown `exited-after-guest-request`;
  host after vfio-pci and accessible. This is not a graphics fix.
- The graphics ring stalled identically (`RPTR=0x1fb1`, `WPTR=0x2180`, IB
  `0x4001d0000` length 0xd10). New registers: `CP_COHER_STATUS=0`,
  `CP_COHER_START_DELAY=0x20`, `CP_ME_COHER_CNTL=0x287fc3`,
  `CP_WAIT_REG_MEM_TIMEOUT=0`; ME instruction pointer moved `0x5e8->0x619`
  (a polling loop), PFP `0xb21` static.
- The report route matched and captured the whole IB (`size=0xd10`, exactly one
  WAIT_REG_MEM). The worker printed 419 lines in one burst while Apple's report
  and HWLibs TTL asserts were logging; the console dropped most of them and the
  wait lines never arrived. 70 lines survived intact (dwords 0x0-0x1f7 and
  0x270-0x2a7): full context state, the depth target, VS/PS program addresses,
  `VGT_PRIMITIVE_TYPE=0x11` and the first `DRAW_INDEX_AUTO` (3 vertices) at
  0x1e8. The wait lies outside the recovered ranges.

| Candidate | Change | GFX ring | Probe / verdict | Recovery |
|---|---|---|---|---|
| 212 | hang dump | stall; ME in WAIT_REG_MEM | passed / BASELINE_BLOCKED | recovered |
| 213 | IB capture via mapCmdBuffers | same stall; wait not printed | passed / CORE_PROBE_PASS | recovered |

Blocking issue unchanged. Candidate 214 changes only the output: each wait and
the 24 dwords before it are logged at capture time, and the worker prints the
buffer after a 3 s settle, 20 ms per line, with per-line checksums, twice.

## Boot-launch ledger extension for candidate 214 (2026-09-13)

Candidate 214 is launch 5 on boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2`, again
through `--manual-reuse --ack-risk` under the user's authorization to extend the
ledger with an explicit note. Candidates 212 and 213 each recovered cleanly
(schema 6 `recovered`) and the host stayed vfio-pci and accessible. Precondition:
MODE2 reset receipt `run/mode2-reset-4.json` with `RLC_CNTL=0` and `CP_STAT=0`
immediately before staging. This note covers this one launch only.

## Candidate 214 stuck-wait capture (2026-09-14)

Run `8dd3e23ce282fc9856e68c2a91a6a1d8`, card `metal-048` (commit `54fd0b7`),
source `8049d8a`, build `277b643dab5a4529b7a67710a54c468e`, boot `c369c74e`,
launch 5 under its ledger note, after `run/mode2-reset-4.json`. Verdict
`CORE_PROBE_PASS`; probe passed; recovery `recovered`; shutdown
`exited-after-guest-request`; host after vfio-pci, accessible, no active VM.
Evidence: `run/candidate-214-results/`; full IB decode in
`findings/research/candidate214-stuck-ib-decoded.txt` (all 0xd10 dwords, every
line checksum verified).

- The ME is parked in the IB's only `WAIT_REG_MEM` at dword 0xbcf: memory
  `0x400001000 == 0x11111115`, poll 10 ms. It follows `WRITE_DATA` of 4 to the
  same address and opcode 0x49 (`0x514, 0x20000000, 0x400001000, 0x11111115`),
  the same deferred fence packet the kernel emits after every ring IB. With
  `QU_STALLED_ON_EOP_DONE_PULSE` and the whole 3D pipeline busy, this is a
  pipeline-flush sync point: the fence is written only when the draws before it
  finish, and they never do.
- Draws before the wait: a depth-clear screen triangle (binning off), then DPBB
  on (`PA_SC_BINNER_CNTL_0=0x19ffe00c`) for three instanced indexed draws
  (`DRAW_INDEX_2` 0x3300, 0x22c8 and 0x96c0 indices, 111 instances) into a 4x MSAA
  1280x1024 target with HTILE depth, then another screen triangle.
- `GRBM_STATUS3` shows `PH_BUSY` with `GL1CC`, `GL2CC` and `UTCL1` idle, which
  weakens a GL2 cache explanation.
- Apple's restart report shows the gfx CP running Apple's Navi 23 microcode
  (ME 0x40, PFP 0x58, CE 0x24, MEC 0x5c) under this chip's RLC (0x1f). GC 10.3.6
  has its own CP microcode family (ME 0x0e, PFP 0x12, CE 0x03), same signing key,
  same payload sizes.

| Candidate | Change | GFX ring | Probe / verdict | Recovery |
|---|---|---|---|---|
| 213 | IB capture | stall; wait lost to console | passed / CORE_PROBE_PASS | recovered |
| 214 | capture-time wait log, paced print | stall; wait decoded, full IB recovered | passed / CORE_PROBE_PASS | recovered |

Blocking issue: the 3D pipeline never finishes WallpaperSequoia's first large
draw. Candidate 215 tests two single-variable hypotheses from one binary:
`rgpucpfw=1` loads gc_10_3_6 PFP/ME/CE microcode through the PSP (card
`metal-049`), and `rgpunobin=1` sets `PA_SC_ENHANCE_1.DISABLE_SC_BINNING`
(card `metal-050`).

## Boot-launch ledger extension for candidate 215 cpfw (2026-09-14)

Candidate 215 with card `metal-049` (`rgpucpfw=1`) is launch 6 on boot
`c369c74e-96ff-4c21-ae85-80ccb269f7d2`, through `--manual-reuse --ack-risk`
under the user's standing instruction to keep testing until desktop Metal works
and to extend the ledger with explicit notes. Candidates 212-214 each recovered
cleanly. Precondition: MODE2 reset receipt `run/mode2-reset-5.json` with
`RLC_CNTL=0` and `CP_STAT=0` immediately before staging. If the PSP rejects the
substituted microcode, the run is recorded as a bring-up failure and the next
launch reverts to Apple's microcode. This note covers this one launch.

## Candidate 215 cpfw attempt (2026-09-14)

Run `6c517734679ca1b5dd44d042f8e070f6`, card `metal-049` (commit `4dc4fc5`),
source `2c735c3`, build `ed6e7160b03142709a0b566b8683da9a`, launch 6 under its
ledger note, after `run/mode2-reset-5.json`. The microcode swap did **not**
happen: `X9C: 0 of 3 graphics CP microcode descriptors replaced`. Apple's
embedded CP payloads carry fw_type `0x01012001/2/3` (read from the KDK HWLibs
binary), while linux-firmware's carry `0x81012001/2/3`; the matcher required the
full value. The run is therefore a baseline repeat: same stall
(`RPTR=0x1eb1`, same WAIT_REG_MEM at IB dword 0xbcf), probe passed, recovery
`recovered`, host after vfio-pci and accessible. Verdict `INCONCLUSIVE/
identity_or_route_missing` came from capture loss (the COM2 critical replay was
cut mid-record at shutdown), not from the kext. New readings at the stall:
`PA_SC_ENHANCE=0x8000009`, `PA_SC_ENHANCE_1=0x40c2000` (binning not disabled),
`PA_SC_ENHANCE_2=0x820`, `PA_PH_INTERFACE_FIFO_SIZE=0x18`, `PA_PH_ENHANCE=0x1000`,
`PA_SC_BINNER_TIMEOUT_COUNTER=0x800`.

Candidate 216 matches on the low 16 bits of fw_type plus the $PS1 magic and
payload length, and logs every CP-sized descriptor.

## Boot-launch ledger extension for candidate 216 cpfw (2026-09-14)

Candidate 216 with card `metal-051` (`rgpucpfw=1`, fixed matcher) is launch 7
on boot `c369c74e-96ff-4c21-ae85-80ccb269f7d2`, through `--manual-reuse
--ack-risk` under the user's standing instruction to keep testing. Candidate 215
recovered cleanly. Precondition: MODE2 reset receipt `run/mode2-reset-6.json`
with `RLC_CNTL=0` and `CP_STAT=0` immediately before staging. This note covers
this one launch.

## Candidate 216 gc_10_3_6 CP microcode (2026-09-14)

Run `07fddb4109a00e886baacb8ecfed2211`, card `metal-051` (commit `d145a75`),
source `304d4ad`, build `14b0fa714e2f4feda48bef5e2851fa61`, launch 7 after
`run/mode2-reset-6.json`. All three descriptors were replaced
(`X9C: 3 of 3`: Apple ME/CE/PFP `0x0101200x` -> gc_10_3_6 `0x8101200x`), the PSP
accepted every load (no FAILED responses) and TTL initialization completed. The
new microcode ran (instruction pointers PFP `0xbf4`, ME `0x5ca->0x5f9`, CE
`0x624`, all different from Apple's), yet the graphics ring stalled identically:
`RPTR=0x1fb1`, `WPTR=0x2180`, same ME/PFP header history, same WAIT_REG_MEM at IB
dword 0xbcf, `CP_STALLED_STAT2=0x230000`. The probe passed; recovery
`recovered`; host after vfio-pci and accessible. Verdict `INCONCLUSIVE/
identity_or_route_missing` again from COM2 capture loss at shutdown (215 and 216;
214 was clean), to be investigated separately.

Result: the CP microcode family is not the cause. The pipeline itself does not
finish the draws.

## Boot-launch ledger extension for candidate 216 nobin attempt (2026-09-14)

The same 1.0.216 binary with card `metal-052` (`rgpunobin=1`,
`PA_SC_ENHANCE_1.DISABLE_SC_BINNING`, Apple microcode) runs as launch 8 on boot
`c369c74e` from attempt namespace `run/candidate-216-attempt-nobin`, through
`--manual-reuse --ack-risk` under the user's standing instruction. Precondition:
`run/mode2-reset-7.json` with `RLC_CNTL=0` and `CP_STAT=0` before staging. This
note covers this one launch.

## Candidate 216 nobin attempt: the desktop stall is gone (2026-09-14)

Run `e8f281ed848e998a103f37d6d2be2c2a`, card `metal-052`, same 1.0.216 binary
(build `14b0fa714e2f4feda48bef5e2851fa61`) from `run/candidate-216-attempt-nobin`,
launch 8 after `run/mode2-reset-7.json`. `rgpunobin=1` wrote
`PA_SC_ENHANCE_1 0x40c2000 -> 0x40c2008` (readback confirmed) before RLC start;
Apple's CP microcode.

- **No graphics stall.** No hang dump fired, no `HW Channel 0 GFX is occupied`,
  no Apple GPU restart report, no pending command buffer capture, and **zero**
  KIQ stamp timeouts for the whole run, shutdown included (every earlier desktop
  run had them). Submission counters kept climbing through the run
  (`SUB: summary process=107 submit=1518`, still increasing at shutdown) with the
  console session active (`IOConsoleUsers ... sm 0xe0000255`).
- The small compute probe passed; recovery `recovered`; shutdown
  `exited-after-guest-request`; host after vfio-pci and accessible.
- Verdict `INCONCLUSIVE/identity_or_route_missing` is capture loss: the COM2 replay
  was cut mid-line at shutdown (`CR2 has an incomplete transport line`), the same
  as 215 and 216. The reviewed producer quiesce (`critical_replay_quiesce` plus
  `rgpucr2quiesce=1`) exists but no recent card selected it.

Cause (independent adversarial review of the candidate 214 IB, confirmed by this
run): WallpaperSequoia's draws enable deferred pixel binning with state sized for
Navi 23: `PA_SC_BINNER_CNTL_1.MAX_ALLOC_COUNT=340` (Mesa uses 84 for Raphael's
256-line parameter cache), `GE_PC_ALLOC` oversubscription of 511 lines, 16x16 bins
and 32 persistent states per bin. A binning batch can then wait for cache space
that is only freed when the batch ends, which matches the ME waiting on the
pipeline-flush fence with the whole 3D pipeline busy and no fault.

| Candidate | Change | GFX ring | Probe / verdict | Recovery |
|---|---|---|---|---|
| 215 | cpfw (matcher missed) | stall | passed / INCONCLUSIVE (capture) | recovered |
| 216 | gc_10_3_6 CP microcode | stall | passed / INCONCLUSIVE (capture) | recovered |
| 216-nobin | DISABLE_SC_BINNING | **no stall, 0 KIQ timeouts** | passed / INCONCLUSIVE (capture) | recovered |

Next: candidate 217 keeps `rgpunobin=1`, adds a 5-second gfx ring progress sampler
(`XR:` lines) as positive evidence that desktop work completes, and selects the
COM2 quiesce so the verdict is not lost to capture timing. Performance refinement
(clamping MAX_ALLOC_COUNT instead of disabling binning) comes after qualification.

## Boot-launch ledger extension for candidate 217 (2026-09-14)

Candidate 217 (`metal-053`) is launch 9 on boot `c369c74e`, through
`--manual-reuse --ack-risk` under the user's standing instruction. Precondition:
`run/mode2-reset-8.json` with `RLC_CNTL=0` and `CP_STAT=0` before staging. This
note covers this one launch.

## Candidate 217: desktop graphics completes on the device (2026-09-14)

Run `466d7235b807a40bdcaa38351d777e37`, card `metal-053` (commit `ac1c8de`),
source `3903f29`, build `2216360d7f0e4e77931e8cceab6aaf72`, launch 9 after
`run/mode2-reset-8.json`. Boot arguments: `rgpunobin=1 rgpugolden=1
rgpuhangdump=1 rgpucr2quiesce=1`. Evidence: `run/candidate-217-results/`.

- **Desktop graphics work completed on the Raphael GPU for the whole run.** The
  40 progress samples (5 s apart, from 30 s after plugin start) show the gfx ring
  advancing `0 -> 0x1000 -> 0x9600 -> 0xa780 -> 0xa880 -> 0xa980 -> 0xac00 ->
  0xaf00 -> 0xb080` (8 advances) and **drained on every sample**
  (`RPTR == WPTR`, `CP_STAT=0`, `GRBM_STATUS=0x3028`, `CP_STALLED_STAT2=0`),
  well past the old stall at `WPTR=0x2180`. No hang dump, no GPU restart report.
  The small compute probe passed.
- The run did not end cleanly. The COM2 quiesce request was written after the
  probe, but the kext's COM2 worker exits 180 s after start, so no ACK came and
  the harness waited for its 6000-second cleanup boundary. After about 20 idle
  minutes the guest entered ACPI sleep (`acpi_sleep_kernel`), one KIQ stamp timed
  out during that transition (`waitForHwStamp(5) -> 0`, after all 40 samples),
  and the coordinator stopped the run with SIGTERM (the supported manual stop).
  Shutdown was `forced` (guest agent unreachable while asleep); recovery schema 6
  `incomplete`; verdict `INVALID` (experiment cancelled). Host after: vfio-pci,
  accessible, sleep inhibited, no active VM.

| Candidate | Change | GFX ring | Probe / verdict | Recovery |
|---|---|---|---|---|
| 216-nobin | DISABLE_SC_BINNING | no stall | passed / INCONCLUSIVE (capture) | recovered |
| 217 | + progress sampler, quiesce | 40/40 drained, 8 advances | passed / INVALID (cancelled) | incomplete (forced) |

Blocking issue for a clean verdict: the quiesce contract outlives the COM2 worker.
Candidate 218 keeps the COM2 control path polling after the replay window (up to
6000 s, 10 ms polls, no replay traffic) and answers a late request with one fresh
caught-up snapshot and the ACK.

## Boot-launch ledger extension for candidate 218 (2026-09-14)

Candidate 218 (`metal-054`) is launch 10 on boot `c369c74e`, through
`--manual-reuse --ack-risk` under the user's standing instruction. Candidate 217's
recovery was incomplete after a forced shutdown, so the precondition is a MODE2
reset receipt `run/mode2-reset-9.json` showing `RLC_CNTL=0` and `CP_STAT=0`, and a
probe receipt showing the mailbox still answers. This note covers this one launch.

## Candidate 218 and the missing quiesce forwarder (2026-09-14)

Run `4307f1498444b5d1f7c9b37b52f04d28`, card `metal-054` (commit `d6ace9e`),
build `10cce4d85456402cb9bb469b3da3077d`, launch 10 after `run/mode2-reset-9.json`.
The desktop again completed all graphics work (40/40 progress samples drained,
ring up to `0xc580`, no stall), the probe passed, and the run again idled until a
SIGTERM stop (forced shutdown, recovery `incomplete`, verdict `INVALID`). The kext's
late quiesce responder was never exercised: the deployed collector
`~/macos-vm/sercat.py` (10 Sep) predates the quiesce forwarding that the branch's
`tools/sercat.py` has, so `RGPUQ2` was never written to COM2. The deployed
supervisor already passes `VM_SERIAL_CID`. `~/macos-vm/sercat.py` was replaced with
the branch copy (old copy kept as `run/sercat.py.backup-pre-quiesce-20260914`; the
diff only adds the request forwarder); the manifest's harness hashes pick this up
at the next prepare.

Sleep-path finding for M7: in both 217 and 218 the idle guest began system sleep
about three minutes after the desktop settled; Apple's `AMDHardware::powerOff`
issued KIQ frames and the second timed out (`waitForHwStamp(5) -> 0`, KIQ RPTR
`0x80 -> 0x86` of `0xa0`), before `acpi_sleep_kernel`. Normal shutdown (216-nobin)
had no KIQ timeout. Guest sleep is not part of the qualification path; a later
lifecycle item is to disable guest sleep or fix the powerOff KIQ path.

## Boot-launch ledger extension for candidate 218 attempt q2 (2026-09-14)

The same 1.0.218 binary and card `metal-054` run from
`run/candidate-218-attempt-q2` as launch 11 on boot `c369c74e`, through
`--manual-reuse --ack-risk`, now with the quiesce forwarder deployed. Precondition:
`run/mode2-reset-10.json` with `RLC_CNTL=0` and `CP_STAT=0`. This note covers this
one launch.

## Candidate 218 attempt q2: first clean desktop run (2026-09-14)

Run `192d54f3313678079546c75ef0b2bfbc`, card `metal-054`, 1.0.218 build
`10cce4d85456402cb9bb469b3da3077d` from `run/candidate-218-attempt-q2`, launch 11
after `run/mode2-reset-10.json`, with the quiesce forwarder deployed.

- **Verdict `CORE_PROBE_PASS`** with no functional boundary (valid capture).
- Desktop session active; graphics ring advanced and drained on every sample
  (`RPTR=WPTR=0xb380` at the last sample before shutdown), **zero** hang dumps,
  GPU restart reports or KIQ stamp timeouts.
- Small Metal compute probe passed.
- COM2 quiesce acknowledged 5.7 s after the request (snapshot 6, 336 records,
  `run/candidate-218-attempt-q2-results/critical-quiesce.json`).
- Shutdown `exited-after-guest-request`; recovery schema 6 **`recovered`**; host
  after vfio-pci, accessible, no active VM.

| Candidate | Change | GFX ring | Probe / verdict | Recovery |
|---|---|---|---|---|
| 217 | nobin + sampler + quiesce (no forwarder) | drained | passed / INVALID (cancelled) | incomplete |
| 218 | late quiesce responder (no forwarder) | drained | passed / INVALID (cancelled) | incomplete |
| **218-q2** | **collector forwards quiesce** | **drained, 0 stalls** | **passed / CORE_PROBE_PASS** | **recovered** |

Next: repeat this exact binary and card twice (attempts q3, q4) for three
consecutive clean bounded lifecycle cycles (M7), then the full compute+render
probe (M5, needs a GPU-less guest compile of `tests/metal_probe.m`), WindowServer
composition evidence and display output (M6), and a binning clamp in place of the
global disable.

## Boot-launch ledger extensions for candidate 218 attempts q3 and q4 (2026-09-14)

Two repeats of the q2 configuration run as launches 12 and 13 on boot `c369c74e`,
each from its own attempt namespace, through `--manual-reuse --ack-risk` under the
user's standing instruction. Each is preceded by its own MODE2 reset receipt
(`run/mode2-reset-11.json`, `run/mode2-reset-12.json`) showing `RLC_CNTL=0` and
`CP_STAT=0`. A failure in q3 stops the series for diagnosis before q4.

## Candidate 218 attempts q3 and q4: three consecutive clean desktop cycles (2026-09-14)

Same 1.0.218 binary (build `10cce4d85456402cb9bb469b3da3077d`) and card `metal-054`,
launches 12 and 13 after `run/mode2-reset-11.json` and `run/mode2-reset-12.json`.

| Attempt | Run | Verdict | Recovery | Shutdown | Quiesce | Stalls / KIQ timeouts |
|---|---|---|---|---|---|---|
| q2 | `192d54f3313678079546c75ef0b2bfbc` | CORE_PROBE_PASS | recovered | guest request | ACK | 0 |
| q3 | `a3462068ca82c43c847f7bb86c348132` | CORE_PROBE_PASS | recovered | guest request | ACK | 0 |
| q4 | `e638416a1e8d28f0eac219707b193d16` | CORE_PROBE_PASS | recovered | guest request | ACK | 0 |

Every attempt ran the logged-in desktop with the gfx ring draining on every sample
(last samples `0xb380`, `0xab00`, `0xc280`), passed the compute probe, and left
the host on vfio-pci and accessible. These are three consecutive bounded lifecycle
cycles on one host boot, each separated only by the reboot-free SMU MODE2 reset.

Next: the full native probe (compute plus render readback) through card
`metal-055` on the same binary, using the native guest binary recorded in
`run/guest-identity.json.backup-20260911T153036Z`.

## Boot-launch ledger extension for the native probe attempt (2026-09-14)

The 1.0.218 binary with card `metal-055` runs from `run/candidate-218-attempt-native`
as launch 14 on boot `c369c74e`, through `--manual-reuse --ack-risk` under the
user's standing instruction, after `run/mode2-reset-13.json`. `run/guest-identity.json`
is switched to the native probe identity for this run (the small-probe identity is
kept as `run/guest-identity.json.small-metal-20260914`). This note covers this one
launch.

## Native Metal probe passes on the running desktop (2026-09-14)

Run `89743ccaa7bb8abbcf310d35bdb12f22`, card `metal-055` (commit `4735c36`), 1.0.218
build `10cce4d85456402cb9bb469b3da3077d` from `run/candidate-218-attempt-native`,
launch 14 after `run/mode2-reset-13.json`, with the logged-in desktop session active
and `rgpunobin=1`.

- `RGPU_METAL_RESULT passed=true device="AMD Radeon Navi23" metal3=true
  compute_rounds=3 compute_values_checked=196608 render_pixels_checked=4096
  completed_command_buffers=4`, `RGPU_EXIT 0`.
- Verdict `CORE_PROBE_PASS` (valid capture), recovery `recovered`, shutdown
  `exited-after-guest-request`, COM2 quiesce ACK, zero stalls or KIQ timeouts, gfx
  ring drained on every sample.

This is the full M4/M5 acceptance probe that candidate 194 passed only on an idle
graphics ring; it now passes while WindowServer and WallpaperSequoia render on the
same device.

| Run | Probe | Verdict | Recovery |
|---|---|---|---|
| 218-q2/q3/q4 | small compute | CORE_PROBE_PASS x3 | recovered x3 |
| 218-native | compute x3 + render readback | CORE_PROBE_PASS | recovered |

Remaining for full desktop acceleration: WindowServer composition evidence on this
device and a display path (M6), binning clamp instead of the global disable
(performance), and the guest sleep-path KIQ timeout in `AMDHardware::powerOff` (M7).

## Desktop evidence probe prepared GPU-less (2026-09-14)

A supervised GPU-less guest session (container `b7cf3623...`, only `/dev/kvm`, no
VFIO device, no ledger entry) compiled `tests/desktop_metal_probe.m` with `-Werror`
at `/var/tmp/rgpu-desktop-metal-731329b936529aba/probe` (source sha256 `731329b9...`,
binary sha256 `1c48101a...`). Without a GPU it correctly reports `no Metal device`.
The guest showed `WindowServer` running and user `bogdan` on the console, and
`pmset` system sleep of 1 minute (display sleep 10), which explains the sleep entries
in long idle GPU runs. The session was shut down through the supervisor. New profile
`desktop-metal` (validator `tools/desktop-metal-test.py`) requires a completed compute
command on the Navi23 device and records display-to-device mapping and IOAccelerator
user clients without gating on them.

## Boot-launch ledger extension for the desktop evidence attempt (2026-09-14)

The 1.0.218 binary with card `metal-056` runs from `run/candidate-218-attempt-desktop`
as launch 15 on boot `c369c74e`, through `--manual-reuse --ack-risk` under the user's
standing instruction, after `run/mode2-reset-14.json`. `run/guest-identity.json` is
switched to the desktop probe identity for this run. This note covers this one launch.

## macOS desktop composition runs on the Raphael GPU (2026-09-14)

Run `464d4d8e40988d6ca567d693b4317924`, card `metal-056` (commit `4e0e77f`), 1.0.218 build
`10cce4d85456402cb9bb469b3da3077d` from `run/candidate-218-attempt-desktop`, launch 15
after `run/mode2-reset-14.json`. Evidence: `run/candidate-218-attempt-desktop-results/probe.json`.

- **Active display on this device.** `CGGetActiveDisplayList` returns one main display,
  1280x1024, and `CGDirectDisplayCopyCurrentMetalDevice` for it returns the same
  `AMD Radeon Navi23` device (registry id `4294968028`) that the probe's Metal
  compute ran on.
- **The desktop is a client of this GPU.** `AMDRadeonX6000_AMDNavi23GraphicsAccelerator`
  (the probe's Metal device) holds IOAccelerator user clients created by WindowServer
  (22), WallpaperSequoia, loginwindow, Finder, the Dock extra, ControlCenter,
  NotificationCenter, Spotlight, System Settings, Terminal, Safari, TextInputMenuAgent,
  avconferenced and the probe itself.
- Compute command completed; verdict `CORE_PROBE_PASS`; recovery `recovered`; shutdown
  `exited-after-guest-request`; COM2 quiesce ACK; zero stalls or KIQ timeouts.

Together with the drained graphics ring on every sample and the native probe's
render readback, this shows WindowServer composition and application Metal rendering
executing on the passed-through Raphael iGPU with `rgpunobin=1`.

| Milestone | Evidence | Status |
|---|---|---|
| Desktop graphics completes on the device | 218-q2/q3/q4/native/desktop gfx ring samples | done |
| M4/M5 compute + render readback on live desktop | 218-native: 196,608 values, 4,096 pixels | done |
| M6 WindowServer composition on this device | 218-desktop: main display's Metal device, WindowServer clients | done (driver evidence) |
| M6 changing frames captured from the display | not yet | open |
| Physical HDMI output under macOS | not verified | open |
| Clean bounded lifecycle, 3 consecutive | 218-q2/q3/q4 (plus native, desktop) | done on one boot |
| Binning clamp instead of global disable | not yet | open (performance) |
| Guest sleep path (`AMDHardware::powerOff` KIQ timeout) | 217/218 | open |

## Boot-launch ledger extension for the frame-capture attempt (2026-09-14)

Two more GPU-less sessions (containers `dafa56c7...`, `0442291c...`; no VFIO device,
no ledger entry) recompiled the desktop probe with frame capture (source sha256
`6180ef81...`, binary sha256 `e8a7d058...`; the first compile failed because
`CGDisplayCreateImage` is unavailable in the macOS 15 SDK and is now resolved with
`dlsym`). The 1.0.218 binary with card `metal-057` runs from
`run/candidate-218-attempt-capture` as launch 16 on boot `c369c74e`, through
`--manual-reuse --ack-risk` under the user's standing instruction, after
`run/mode2-reset-15.json`. This note covers this one launch.

## Composited desktop frames captured from the Raphael-driven display (2026-09-14)

Run `0f527b57f4296b64b653dcfde8a2d480`, card `metal-057` (commit `fef552b`), 1.0.218 build `10cce4d8...`, launch 16
after `run/mode2-reset-15.json`. Verdict `CORE_PROBE_PASS`, recovery `recovered`,
shutdown `exited-after-guest-request`, quiesce ACK, zero stalls.

- Main display 1280x1024 again driven by the Raphael Metal device; WindowServer holds
  accelerator clients.
- `CGDisplayCreateImage` returned full frames (1280x1024, 5,084,047 of 5,242,880
  bytes non-zero) despite `CGPreflightScreenCaptureAccess=false` for the root probe.
- Console-user `screencapture` succeeded (exit 0, 1,768,443-byte PNG).
- Both capture pairs were identical one second apart: the logged-in desktop was idle.

Next: open a window between captures to show changing composited frames, and emit
small JPEG thumbnails for visual confirmation.

## Boot-launch ledger extension for the window-animation attempt (2026-09-14)

GPU-less session `38522378...` (no VFIO device, no ledger entry) compiled the
animation probe (source sha256 `d9e30715...`, binary sha256 `46f3f898...`). The
1.0.218 binary with card `metal-058` runs from `run/candidate-218-attempt-anim` as
launch 17 on boot `c369c74e`, through `--manual-reuse --ack-risk` under the user's
standing instruction, after `run/mode2-reset-16.json`. This note covers this one
launch.


## Window animation changes the composited frame; thumbnails are JPEG-limited (2026-09-14)

Run `26ca4438c9e954643fb8edb7c80db2b3`, card `metal-058` (commit `1d5ce50`), 1.0.218 build
`10cce4d8...`, launch 17 after `run/mode2-reset-16.json`. Verdict `CORE_PROBE_PASS`,
recovery `recovered`, shutdown `exited-after-guest-request`, quiesce ACK (snapshot 5,
340 records), no stall lines.

- Root `CGDisplayCreateImage` frames changed when Calculator opened (hash `3de4dfba...`
  before, `30cb745e...` after); `animation_frames_changed=1`.
- The two console-user `screencapture` thumbnails (320 px, JPEG quality 40) show the
  Sequoia wallpaper only. Their blockiness peaks exactly on the 8 and 16 pixel JPEG grid,
  so it is compression, not rendering corruption. They differ only in the top 32 rows
  (the menu bar switching to Calculator); the Calculator window itself is absent because
  `screencapture` in the user session has no Screen Recording grant.
- Serial log: the AMD framebuffer logs `No EDID read.` and an AGDP port 1 Insert event.
  The 1280x1024 display is therefore not identified as the Samsung panel on the iGPU
  HDMI port; physical scan-out is unverified.

Next: probe v4 renders a known color pattern in a user-session `CAMetalLayer` window and
checks it pixel by pixel in the root display capture, measures presentation rate and
offscreen render throughput with readback, and records display identity and framebuffer
registry details.

## Boot-launch ledger extension for the probe v4 attempt (2026-09-14)

GPU-less session `dcb404fc...` (no VFIO device, no ledger entry) compiled desktop probe
v4 (source sha256 `dad42cd4...`, binary sha256 `245eddf9...`) and smoke-ran it: without a
GPU it reports `no Metal device`, and its window child starts in the console session
through `launchctl asuser 501`. The 1.0.218 binary with card `metal-059` runs from
`run/candidate-218-attempt-v4` as launch 18 on boot `c369c74e`, through
`--manual-reuse --ack-risk` under the user's standing instruction, after
`run/mode2-reset-17.json`. This note covers this one launch.


## Probe v4: the desktop renders, but tiles land in the wrong places (2026-09-14)

Run `143790d68ea9d9d6e4242d2cf3dddf51`, card `metal-059` (commit `21de6cd`), 1.0.218 build
`10cce4d8...`, launch 18 after `run/mode2-reset-17.json`. Verdict `CORE_PROBE_PASS`,
recovery `recovered`, shutdown `exited-after-guest-request`, quiesce ACK.

- **The display is macOS's virtual display.** Vendor `0x756e6b6e` ("unkn"), model
  `0x76697274` ("virt"), built-in, 60 Hz, 8 modes. All four
  `AMDRadeonX6000_AmdRadeonFramebuffer` instances report `display-type NONE`,
  `connector-type 0`, `port-number -1` and no `IODisplay` child. WindowServer composites
  on the Raphael GPU into this virtual display; nothing reaches a physical connector.
- **Rendering is corrupted in a tile pattern.** The root display capture at JPEG quality
  0.85 and full resolution still shows the wallpaper as roughly 64-pixel blocks with
  stippled 8-pixel sub-blocks, so the earlier blockiness was not compression.
- **Offscreen readback confirms it.** 1,000 frames of a 1280x1024 BGRA8 ramp plus 20,000
  triangles completed (0.37 ms GPU per frame, no failed command buffers), but 718 of 736
  checked pixels were wrong. The per-frame uniform (blue) was exact on every sample; red
  and green, which encode fragment position, show the correct values of positions
  displaced by whole multiples of 8 pixels (for example pixel (3,200) holds (19,56)).
  The native probe's 64x64 RGBA8 position test still passes, so small targets render
  correctly.
- **Window test.** The console-session `CAMetalLayer` child submitted 366 frames with no
  missing drawables and no failed command buffers, but reported 0 presented frames; the
  root capture shows wallpaper at the window rectangle (other apps' windows are excluded
  without a Screen Recording grant), so the window pattern check is inconclusive.
- `GB_ADDR_CONFIG` already reads Raphael's `0x42` before the golden write, so the
  tile-pipe configuration is not the difference.

Working hypothesis: Apple's command stream enables binning for large passes
(`PA_SC_BINNER_CNTL_0=0x19ffe00c`, 16x16 bins) while `rgpunobin=1` sets
`PA_SC_ENHANCE_1.DISABLE_SC_BINNING`; primitives are then placed with bin offsets the
scan converter never applies. Apple's own unbinned mode (`BINNING_MODE=3`, legacy scan
converter, `0x19fc0003`) is used for small passes, which render correctly.
Next: find where Apple's user-space driver decides to bin, and force its legacy
scan-converter mode instead of disabling binning underneath it.

## Apple's Metal driver has a settings file that turns binning off (2026-09-14)

GPU-less session `1b69a3a8...` (no VFIO device, no ledger entry) loaded
`AMDRadeonX6000MTLDriver` from the dyld shared cache with a small segment dumper
(`tools/guest-segdump.c`) and disassembled its `__TEXT` on the host. The driver reads
`/AmdMtlSettingsFile.txt` (`key = value` lines, `;` comments) in every process that loads
it, mapping names such as `allowPrimBatchBinning` (bit 41 of its feature word, also set
by the environment variable `AMD_ENABLE_PRIM_BATCH_BINNING`), `allowGePcAllocOverSub`
(bit 42), `allowNGGMode`, `allowDCC`, `allowHTile` and `allowRBPlus`.

Guest change (persistent, reversible by deleting both files): `/private/etc/AmdMtlSettingsFile.txt`
contains `allowPrimBatchBinning = 0`, and `/private/etc/synthetic.conf` links
`/AmdMtlSettingsFile.txt` to it (stitched immediately with `apfs.util -t`; readable by
`nobody`).

## Boot-launch ledger extension for the settings-file attempt (2026-09-14)

The 1.0.218 binary with card `metal-060` (desktop probe v4 unchanged, `rgpunobin=1` kept)
runs from `run/candidate-218-attempt-nobatch` as launch 19 on boot `c369c74e`, through
`--manual-reuse --ack-risk` under the user's standing instruction, after
`run/mode2-reset-18.json`. This note covers this one launch.


## Settings-file attempt: no effect; the parser is dead code (2026-09-14)

Run `415effc60ef97b24c6bb3d4dc208f7cf`, card `metal-060` (commit `868d024`), 1.0.218 build
`10cce4d8...`, launch 19 after `run/mode2-reset-18.json`. Verdict `CORE_PROBE_PASS`,
recovery `recovered`, shutdown `exited-after-guest-request`.

- The offscreen readback was bit-identical to launch 18 (frame hash `8b276dc2f0e4f99a`,
  718 of 736 samples wrong) and the desktop JPEG unchanged, so the corruption is
  deterministic and the file changed nothing.
- Disassembly explains it: the `/AmdMtlSettingsFile.txt` parser at `x+0x10d400` in the
  driver's `__TEXT` has no callers in this release build. The live path is the
  environment reader called from device settings initialization, which maps
  `AMD_ENABLE_PRIM_BATCH_BINNING` (atoi & 1) to bit 41; bit 41 is consumed when the
  command writer emits binning flush events.
- The window child this time submitted only 42 frames in 4.4 s (366 before) and again
  reported no presented frames.

Next: desktop probe v5 re-runs the offscreen test and a new exact pixel-identity matrix
(64² to 1280x1024, BGRA8/RGBA8, triangle/quad) in child processes with
`AMD_ENABLE_PRIM_BATCH_BINNING=0` and `=1`, and runs the window child as uid 501 with its
own drawable readback and window self-capture. The inert settings file and
`/etc/synthetic.conf` are removed from the guest.

## Boot-launch ledger extension for the probe v5 attempt (2026-09-14)

GPU-less session `a21b96d7...` (no VFIO device, no ledger entry) compiled desktop probe
v5 (source sha256 `92083f68...`, binary sha256 `857af140...`), confirmed its render child
and its window child (now running as uid 501 through `sudo -n -u #501`) start and fail
cleanly without a GPU, and removed `/private/etc/AmdMtlSettingsFile.txt` and
`/private/etc/synthetic.conf`. The 1.0.218 binary with card `metal-061` runs from
`run/candidate-218-attempt-v5` as launch 20 on boot `c369c74e`, through
`--manual-reuse --ack-risk` under the user's standing instruction, after
`run/mode2-reset-19.json`. This note covers this one launch.


## Probe v5 attempt: shader library failed to compile in the guest (2026-09-14)

Run `9d05b1c1cbc5b8cb47d6f6d73897a131`, card `metal-061` (commit `d13b0c2`), 1.0.218 build
`10cce4d8...`, launch 20 after `run/mode2-reset-19.json`. Verdict `EXECUTION_FAILED`
(`first_submission`): the probe exited 1 with `compute pipeline or queue creation failed`
before any GPU work, because v5 had added the identity shaders to the single shared
Metal library and that library no longer compiled (the probe did not record the
compiler message). Recovery `recovered`, shutdown `exited-after-guest-request`; the GPU
and harness were healthy. Probe v5.1 compiles the compute check, the render shaders
and the identity shaders as three separate libraries and records any compiler error
text.

## Boot-launch ledger extension for the probe v5.1 attempt (2026-09-14)

GPU-less session (no VFIO device, no ledger entry) compiled desktop probe v5.1 (source
sha256 `dcf3d5d4...`, binary sha256 `c688b235...`). The 1.0.218 binary with card
`metal-062` runs from `run/candidate-218-attempt-v51` as launch 21 on boot `c369c74e`,
through `--manual-reuse --ack-risk` under the user's standing instruction, after
`run/mode2-reset-20.json`. This note covers this one launch.


## Probe v5.1: every 8x8 tile is rendered correctly but placed wrongly; binning is not the cause (2026-09-14)

Run `9d05b1c1...` directory `run/candidate-218-attempt-v51-results`, card `metal-062`
(commit `bb1b294`), 1.0.218 build `10cce4d8...`, launch 21 after `run/mode2-reset-20.json`.
Verdict `CORE_PROBE_PASS`, recovery `recovered`, shutdown `exited-after-guest-request`.
All three shader libraries compiled.

| Target | Format | Geometry | Wrong pixels | 8x8 tiles internally exact |
|---|---|---|---|---|
| 64x64 | BGRA8 | triangle | 3,840 of 4,096 | 64 of 64 |
| 256x256 | BGRA8 | triangle | 64,512 of 65,536 | all |
| 1280x1024 | BGRA8 / RGBA8 | triangle / quad | 1,290,240 of 1,310,720 | all 20,480 |

- Identical results in-process and in child processes with
  `AMD_ENABLE_PRIM_BATCH_BINNING=0` and `=1`: primitive batch binning is not involved.
- Each pixel value is exact for some position; whole 8x8 tiles are moved. The tile map
  (`findings/research/candidate218-v51-block16-displacement-map.json`) is linear over
  GF(2) in the tile-coordinate bits. For example destination tile x bit 2 takes source
  tile y bit 0, destination y bit 2 takes source x bit 0, and destination x bit 3 takes
  source x bit 3 xor y bit 3.
- The window child (uid 501) presented 311 frames; `presentedTime` is always 0 on the
  virtual display. Its own drawable readback had 3,051 of 11,616 quadrant samples wrong,
  and its window self-capture matched only at the quadrant centers.
- The earlier native probe's 64x64 RGBA8 position test still differs from this one only
  in its readback path (Managed buffer plus `synchronizeResource`, versus a Shared
  buffer here) and clear color, so the permutation may be in the GPU-to-CPU copy rather
  than in rendering.

Next: probe v6 reads the same rendered texture back through a Shared buffer, a Managed
buffer, a Managed texture and a texture-to-texture blit, and repeats the native probe's
exact render.

## Boot-launch ledger extension for the probe v6 attempt (2026-09-14)

GPU-less session (no VFIO device, no ledger entry) compiled desktop probe v6 (source
sha256 `28c7b7cc...`, binary sha256 `74e92988...`). The 1.0.218 binary with card
`metal-063` runs from `run/candidate-218-attempt-v6` as launch 22 on boot `c369c74e`,
through `--manual-reuse --ack-risk` under the user's standing instruction, after
`run/mode2-reset-21.json`. This note covers this one launch.

## Probe v6: rendering is correct; CPU-visible texture layouts are permuted (2026-09-14)

Run in `run/candidate-218-attempt-v6-results`, card `metal-063` (commit `0c0a5ea`), 1.0.218
build `10cce4d8...`, launch 22 after `run/mode2-reset-21.json`. Verdict `CORE_PROBE_PASS`,
recovery `recovered`, shutdown `exited-after-guest-request`.

| Size | Read back through | Wrong pixels |
|---|---|---|
| 64x64 | Private texture to Shared buffer | 3,840 of 4,096 |
| 64x64 | Private texture to Managed buffer, synchronize | 0 |
| 64x64 | Private texture to Managed texture, synchronize | 0 |
| 64x64 | Render into Managed texture, synchronize | 0 |
| 1280x1024 | Private texture to Shared buffer | 1,290,240 |
| 1280x1024 | Private texture to Managed buffer, synchronize | 0 |
| 1280x1024 | Private texture to Managed texture, synchronize | 1,310,720 |
| 1280x1024 | Render into Managed texture, synchronize | 1,310,720 |

The GPU renders the identity image exactly; only paths that expose texture memory
layout to the CPU are permuted. AMD's GFX10 address library (Mesa
`src/amd/addrlib/src/gfx10/gfx10addrlib.cpp`) selects swizzle patterns and the pipe-bank
xor from `GB_ADDR_CONFIG.NUM_PIPES`. In Apple's kernel, `AMDHWAlignManager2::init`
(`x6+0x6032a`) builds `ADDR_CREATE_INPUT` (size `0x70`) with `regValue.gbAddrConfig` from
hardware-info offset `0xa0`, and `AMDAccelDevice::getHardwareInfo` copies the same
`0x204`-byte block to user space. Discrete Navi2x boards report `GB_ADDR_CONFIG` 0x44
(16 pipes); Raphael reads 0x42 (4 pipes). Swizzle environment switch found in the
Metal driver: `AMD_MTL_ALLOW_VAR_SWIZZLE_MODES` (bit 59, only honored when a
hardware-info capability bit allows it).

## Candidate 219: correct the address library's gbAddrConfig (2026-09-14)

Commit `54e0c63`, build `0556fc2275ad46d8bbd7a93e8992d7e3`. `rgpuaddrcfg=2` routes
`AMDHWAlignManager2::init` (18-byte position-independent prologue guard), logs the
hardware-info block (`XA:` lines) and the live `GB_ADDR_CONFIG`, and replaces
hardware-info `gbAddrConfig` with the live value before the address library is created.
Suite: 892 tests OK.

## Boot-launch ledger extension for candidate 219 (2026-09-14)

Candidate 219 (card `metal-064`, desktop probe v6) runs from `run/candidate-219` as
launch 23 on boot `c369c74e`, through `--manual-reuse --ack-risk` under the user's
standing instruction, after `run/mode2-reset-23.json`. This note covers this one launch.
A first staging attempt consumed `run/mode2-reset-22.json` and stopped before launch with
`candidate card contract mismatch` (the card lacked `rgpuaddrcfg=2` in its functional
boot arguments); no VM started.


## Candidate 219: Apple's hardware info already carries GB_ADDR_CONFIG 0x42 (2026-09-14)

Run `211670e5721a59d3bdc879da56cd7ca2`, card `metal-064` (commit `46b350f`), build `0556fc2275ad46d8bbd7a93e8992d7e3`,
launch 23 after `run/mode2-reset-23.json`. Verdict `CORE_PROBE_PASS`, recovery
`recovered`, shutdown `exited-after-guest-request`.

- The `AMDHWAlignManager2::init` route matched and ran once:
  `hwinfo gbAddrConfig=0x42` equals the live register, `numRasterPipe=1`,
  `numShaderPipes=2`, `backendDisables=0`, `noOfBanks=0`, `noOfRanks=0`. Nothing was
  replaced.
- The readback matrix is identical to launch 22: Shared-buffer copies and 1280x1024
  Managed-texture synchronizes are still tile-permuted; the GPU copy into a Managed
  buffer is exact.
- Conclusion: the kernel address library is configured for Raphael's 4 pipes. The
  kernel has one address-library instance (`AMDGFX10AlignManager` subclasses
  `AMDHWAlignManager2`), and the Metal driver carries no address-library code of its
  own. The permutation therefore comes from a hardware path that disagrees with the
  4-pipe patterns, not from Apple's configuration.

Next candidates, cheapest first: the sampler-side swizzle enable
(`LDS_CONFIG.VGPR_SWIZZLE_EN`, bit 1, reads 0 on Raphael; Navi23 uses
`SQ_CONFIG.VGPR_SWIZZLE_EN`, bit 12), and forcing linear layouts for CPU-visible
textures through `AMDHWAlignManager2::getPreferredSwizzleMode2`.

## Candidate 220: swizzle diagnostics and gated layout knobs (2026-09-14)

Commit `03bcb0a`, build `448a00cbbb2747709efa448483427fc3`. The decoded WindowServer stream
from candidate 214 programs its 1280x1024 color target with `CB_COLOR0_ATTRIB3=0x4dc6c000`
(`COLOR_SW_MODE` 27, variable-block rotated xor) and depth with `DB_Z_INFO` `SW_MODE` 24.
New default-off knobs: `rgpuswlog=1/2` (log `getPreferredSwizzleMode2`, optionally return
linear), `rgpuhwcapclr=<mask>` (clear hardware-info bits at `0xcc`), `rgpuvgpr=1/2/3` (set
`LDS_CONFIG` or `SQ_CONFIG` `VGPR_SWIZZLE_EN` before RLC start, or log both). Two build
attempts failed before this one: the route-ownership check needed an `[x6]` annotation, and
two declarations were out of order (`run/candidate-220-build-failed-*.log`). Suite 893 OK.

## Boot-launch ledger extension for candidate 220 logging run (2026-09-14)

Candidate 220 with card `metal-065` (logging only: `rgpuswlog=1`, `rgpuvgpr=3`) runs from
`run/candidate-220` as launch 24 on boot `c369c74e`, through `--manual-reuse --ack-risk`
under the user's standing instruction, after `run/mode2-reset-25.json`. This note covers
this one launch. A first staging attempt consumed `run/mode2-reset-24.json` and stopped
before launch because `stage-candidate.py` accepted versions only up to 1.0.21N; the
pattern now allows 1.0.2[0-4]N. No VM started.

## Candidate 220 logging run: preferred swizzle modes 22 and 27 (2026-09-14)

Run `6ddc61ca1a9a9d92a9ba7c611838f50e`, card `metal-065`, build of commit `03bcb0a`, launch 24 after
`run/mode2-reset-25.json`. Verdict `CORE_PROBE_PASS`, recovery `recovered`, shutdown
`exited-after-guest-request`. Readback matrix unchanged from launch 22.

- `getPreferredSwizzleMode2` route matched. Apple's input layout is size, flags, mode,
  resource type, format, bits per pixel, width, height. RGBA8 surfaces of 64x64 and
  1280x24 get mode 22; 1280x1024, 400x300, 715x625, 249x249 and 161x161 get mode 27
  (Mesa numbering: 22 `64KB_D_X`, 27 `VAR_R_X`). WindowServer's decoded target also used 27.
- `SQ_CONFIG` reads `0x180070` (Linux's Navi23 golden value) and `LDS_CONFIG` `0x20`; both
  `VGPR_SWIZZLE_EN` bits are clear.

## Boot-launch ledger extension for the linear-swizzle run (2026-09-14)

Candidate 220 with card `metal-066` (`rgpuswlog=2`: every preferred swizzle request returns
linear) runs from `run/candidate-220-attempt-linear` as launch 25 on boot `c369c74e`,
through `--manual-reuse --ack-risk` under the user's standing instruction, after
`run/mode2-reset-26.json`. This note covers this one launch.


## Linear preferred swizzle fixes drawables, not Metal textures (2026-09-14)

Run `d0dff0852eba7ea550c16063b57e4be9`, card `metal-066`, launch 25 after `run/mode2-reset-26.json`. Verdict
`CORE_PROBE_PASS`, recovery `recovered`, shutdown `exited-after-guest-request`.

- With `getPreferredSwizzleMode2` returning linear, the window child's own
  `CAMetalLayer` drawable readback became exact (0 of 11,616 wrong; 3,051 before).
- Probe-created Metal textures were unchanged (identity matrix, readback matrix and
  offscreen ramp all still permuted), so user space selects texture layouts itself.
- Metal driver settings defaults (decoded from `x+0x13a700` in its `__TEXT`; bit order
  from the `AMD_DeviceSettings` type encoding, confirmed by bits 41 and 59):
  `enableTexturePipeBankXor` (bit 27), `enableBlitDMA` (29) and `enableDMAPaging` (31)
  are hard-coded on; `linearSwizzleTextures` (36) is hard-coded off. None depends on
  kernel hardware info.

Next: desktop probe v7 patches one of those constants in child processes (clear 27,
clear 29, set 36) before creating the Metal device and reruns the readback matrix.

## Boot-launch ledger extension for the probe v7 attempt (2026-09-14)

GPU-less session (no VFIO device, no ledger entry) compiled desktop probe v7 (source sha256
`efd5d209...`, binary sha256 `3e10527e...`) and smoke-ran a patch child: the driver site
bytes matched, byte `0xff -> 0xf7` was written through a copy-on-write protection change,
and the process kept running. Candidate 220 with card `metal-067` runs from
`run/candidate-220-attempt-v7` as launch 26 on boot `c369c74e`, through
`--manual-reuse --ack-risk` under the user's standing instruction, after
`run/mode2-reset-27.json`. This note covers this one launch.

## Probe v7: linearSwizzleTextures makes every readback exact (2026-09-14)

Run `a55387fabb5d03ad9966ddad7f011db3`, card `metal-067`, launch 26 after `run/mode2-reset-27.json`. Verdict
`CORE_PROBE_PASS`, recovery `recovered`, shutdown `exited-after-guest-request`. Each child
patched one byte of its own `AMDRadeonX6000MTLDriver` settings constant before creating
the device.

| Variant | 64 Shared | 64 Managed tex | 1280 Shared | 1280 Managed tex | 1280 render into Managed |
|---|---|---|---|---|---|
| none (in-process) | 3,840 | 0 | 1,290,240 | 1,310,720 | 1,310,720 |
| clear `enableTexturePipeBankXor` (27) | 3,840 | 0 | 1,290,240 | 0 | 0 |
| clear `enableBlitDMA` (29) | 0 | 0 | 0 | 1,310,720 | 1,310,720 |
| set `linearSwizzleTextures` (36) | 0 | 0 | 0 | 0 | 0 |

(Managed-buffer copies were exact in every variant.)

An adversarial review (Mesa addrlib rebuilt with configuration overrides) reproduced the
measured permutation exactly on all 20,480 tiles and the 256/512/1024 histograms as
hardware writing with the `GB_ADDR_CONFIG` 0x42 layout (4 pipes, 1 packer) while the
reader decodes with a 16-pipe, 16-packer layout, in modes 24/27. It also pointed out
that NootedRed programs `GB_ADDR_CONFIG_READ` with the same value as `GB_ADDR_CONFIG`.

## Candidate 221: mirror GB_ADDR_CONFIG into GB_ADDR_CONFIG_READ (2026-09-14)

Commit `6427fbb`, build `e3b0881d653d4c95bee06a2e263b6f22`. `rgpugbread=1` logs both registers
before RLC start; `rgpugbread=2` copies `GB_ADDR_CONFIG` into `GB_ADDR_CONFIG_READ`
(seg0 `0x13e2`). Suite 894 OK. This is a layout-register test for rendering correctness,
not the earlier golden-register ring-hang hypothesis.

## Boot-launch ledger extension for candidate 221 (2026-09-14)

Candidate 221 with card `metal-068` (`rgpugbread=2`, kernel swizzle override off, probe v7)
runs from `run/candidate-221` as launch 27 on boot `c369c74e`, through
`--manual-reuse --ack-risk` under the user's standing instruction, after
`run/mode2-reset-28.json`. This note covers this one launch.

## Candidate 221: GB_ADDR_CONFIG_READ already mirrors 0x42 (2026-09-14)

Run `aa4fb1f5eb4d5301a60aee551a9fa534`, card `metal-068`, launch 27 after `run/mode2-reset-28.json`. Verdict
`CORE_PROBE_PASS`, recovery `recovered`, shutdown `exited-after-guest-request`. The log shows
`GB_ADDR_CONFIG=0x42 GB_ADDR_CONFIG_READ 0x42 -> 0x42`; nothing changed and the readback
matrix and patch-child results repeat launch 26.

A second adversarial review (Python port of Mesa's GFX10 swizzle address model, 10,816
writer/reader pairs) found one exact match on all 5,120 sampled blocks: bytes laid out
with the 4-pipe (0x42) `64KB_R_X` pattern and decoded with the 16-pipe/16-packer pattern
(0x444). It also corrects the mode names used above: 27 is `ADDR_SW_64KB_R_X` (a VAR
mode would be 31), and pipe-independent modes (linear, `S`/`D` without `_X`) cannot
mismatch.

Disassembly of the Metal driver's own address-library creation (`x+0xae4d`) shows it
takes `gbAddrConfig` as a 32-bit value from hardware-info offset `0xa4`, while the kernel
stores the value as a 64-bit field at `0xa0` whose upper half is 0. User space therefore
passes 0 ("use the chip default"), which is the Navi 16-pipe layout.

## Candidate 222: gbAddrConfig at hardware-info offset 0xa4 (2026-09-14)

Commit `973a9fc`, build `52a7042d8dfd4cee8d01adeada7f81c0`. `rgpuaddrcfg=3` writes the live
`GB_ADDR_CONFIG` into `hwinfo[0xa4]` at `AMDHWAlignManager2::init`, before any user-space
copy. Desktop probe v8 (source `0d796050...`, binary `224b9341...`, compiled GPU-less; its
new `gbaddr42` child patched the user-space load to `mov $0x42,%eax` and survived) keeps
`gbaddr42` and `linearswizzle1` children as controls. Suite 894 OK.

## Boot-launch ledger extension for candidate 222 (2026-09-14)

Candidate 222 with card `metal-069` runs from `run/candidate-222` as launch 28 on boot
`c369c74e`, through `--manual-reuse --ack-risk` under the user's standing instruction,
after `run/mode2-reset-29.json`. This note covers this one launch.


## Candidate 222 launch 28: guest hung inside TTL initialization (2026-09-14)

Run `1c9bf40f1d03419269a1f9eb471feb90`, card `metal-069`, launch 28 after `run/mode2-reset-29.json` (reset receipt normal:
`CP_STAT=0`, `RLC_CNTL=0`, `GB_ADDR_CONFIG=0x42`). Verdict `INVALID`
(`recovery_lease_pool_missing`), recovery `failed` (missing XH2 ownership record), shutdown
`forced` (guest identity transport failed), no probe. Serial stops after the RLC firmware
table restore inside `TTL::initialize()`, followed by nine `cosWaitForFunc` timeouts; in
launch 23 the same boot reached `TTL::initialize() Completed` about 300 lines later and only
then ran `AMDHWAlignManager2::init`. The new `rgpuaddrcfg=3` route therefore never ran
(no `XA: hwinfo` line), so this failure is not attributable to it. Host after: vfio-pci,
accessible, no active VM.

## Boot-launch ledger extension for the candidate 222 retry (2026-09-14)

The same 1.0.222 binary and card `metal-069` run again from
`run/candidate-222-attempt-retry1` as launch 29 on boot `c369c74e`, through
`--manual-reuse --ack-risk` under the user's standing instruction, after a fresh
`run/mode2-reset-30.json` whose probe and reset receipts must show `CP_STAT=0` and
`RLC_CNTL=0`. This note covers this one launch.

## Candidate 222 retry: hwinfo[0xa4] and the user-space address library are not the reader (2026-09-14)

Run `2e652a24d3f26484d9e1b38fa0a861d1`, card `metal-069`, launch 29 after `run/mode2-reset-30.json`. Verdict
`CORE_PROBE_PASS`, recovery `recovered`, shutdown `exited-after-guest-request`; the TTL hang of
launch 28 did not recur. The route logged `hwinfo[0xa4] 0 -> 0x42`. The readback matrix,
offscreen ramp and window drawable were unchanged, and the `gbaddr42` child (user-space
address-library input forced to 0x42) was also unchanged, while `linearswizzle1` stayed
exact. The 16-pipe decoder is therefore neither the kernel nor the Metal driver's own
address-library instance.

Lilu's user patcher cannot deliver `linearSwizzleTextures` as is: it reads patch targets
from files on disk, and `AMDRadeonX6000MTLDriver` exists only in the dyld shared cache.

## Candidate 223: SDMA address configuration (2026-09-14)

Commit `c6fb3b1`, build `ff31430d502741908dee09587a212693`. The failing paths are exactly the
ones probe v7 fixed by disabling Apple's blit DMA and its pipe-bank xor layouts, which
points at the SDMA copy engine and its own register pair `SDMA0_GB_ADDR_CONFIG` /
`SDMA0_GB_ADDR_CONFIG_READ` (GC seg0 `0x1e`/`0x1f`; NootedRed programs both for APUs).
`rgpusdmacfg=2` logs the pair and copies `GB_ADDR_CONFIG`'s fields into both before RLC
start, at `AMDHWAlignManager2::init` and on each gfx progress sample. Suite 895 OK.

## Boot-launch ledger extension for candidate 223 (2026-09-14)

Candidate 223 with card `metal-070` runs from `run/candidate-223` as launch 30 on boot
`c369c74e`, through `--manual-reuse --ack-risk` under the user's standing instruction, after
`run/mode2-reset-31.json`. This note covers this one launch.


## Candidate 223: SDMA address configuration was 0x444; the desktop now renders correctly (2026-09-14)

Run `3d505f831ad1dfd6a2bad9da231558f2`, card `metal-070` (build of commit `c6fb3b1`), launch 30 after
`run/mode2-reset-31.json`. Verdict `CORE_PROBE_PASS`, recovery `recovered`, shutdown
`exited-after-guest-request`.

- Before RLC start and at `AMDHWAlignManager2::init` both SDMA registers read 0x42. By the
  first gfx progress sample (about 30 s after start) Apple's SDMA bring-up had set
  `SDMA0_GB_ADDR_CONFIG` and `SDMA0_GB_ADDR_CONFIG_READ` to **0x444** (16 pipes, 16
  packers: the Navi23 value). The sampler rewrote both to 0x42.
- Results after the correction:

| Check | Before (launch 29) | Now |
|---|---|---|
| 64x64 Private to Shared buffer | 3,840 wrong | 0 |
| 1280x1024 Private to Shared buffer | 1,290,240 wrong | 0 |
| 1280x1024 Managed texture synchronize (both paths) | 1,310,720 wrong | 1,310,720 wrong |
| Offscreen ramp readback | 718 of 736 wrong | 0 of 736 |
| Window child drawable readback | 3,051 of 11,616 wrong | 0 |

- The root display capture now shows the correct Sequoia wallpaper and menu bar
  (`findings/research/candidate223-desktop.jpg`), and the window's self-capture shows the
  exact quadrant pattern and moving bar (`findings/research/candidate223-metal-window.jpg`).

Remaining: large Managed-texture synchronize is still permuted (the `linearswizzle1` child
fixes it), and the correction must happen as soon as Apple writes 0x444 rather than from the
30-second sampler.

## Candidate 224: SDMA address configuration corrected at every commit (2026-09-14)

Commit `dae6a16`, build `34ec10bcdb3142418dba640a54f20fff`. `rgpusdmacfg=2` now also restores the
SDMA pair before every SDMA indirect-buffer commit (logged only when it changes), after
`startHWEngines` and after `powerUpHW`. Suite 895 OK.

## Boot-launch ledger extension for candidate 224 (2026-09-14)

Candidate 224 with card `metal-071` runs from `run/candidate-224` as launch 31 on boot
`c369c74e`, through `--manual-reuse --ack-risk` under the user's standing instruction, after
`run/mode2-reset-32.json`. This note covers this one launch.


## Candidate 224 result: 0x444 appears after power-up, outside SDMA commits (2026-09-14)

Run `83f22b0ddc2c1d231283d05c4a89cb0c`, card `metal-071`, launch 31 after `run/mode2-reset-32.json`. Verdict
`CORE_PROBE_PASS`, recovery `recovered`, shutdown `exited-after-guest-request`. Results match
launch 30: Shared-buffer copies, offscreen ramp (0 of 736) and window drawable exact; 1280x1024
Managed-texture synchronize still permuted (fixed only by the `linearswizzle1` child).

The SDMA pair read 0x42 before RLC start, at `AMDHWAlignManager2::init`, after
`startHWEngines` and after `powerUpHW`, and the per-commit check never logged a change; the
first gfx progress sample again found **0x444** and restored 0x42. The write therefore
happens after accelerator power-up and not on the SDMA commit path (firmware or a power-state
register restore are candidates).

## Candidate 225: SDMA address-config watchdog (2026-09-14)

Commit `499c142`, build `2c53dd545c814b95a281d67998c79907`. With `rgpusdmacfg=2` a watchdog thread
polls the SDMA pair every 50 ms for 600 s (then every second), restores 0x42 immediately and
logs the first 16 corrections with elapsed time and RLC/CP/GRBM/SDMA state. Suite 895 OK.

## Boot-launch ledger extension for candidate 225 (2026-09-14)

Candidate 225 with card `metal-072` runs from `run/candidate-225` as launch 32 on boot
`c369c74e`, through `--manual-reuse --ack-risk` under the user's standing instruction, after
`run/mode2-reset-33.json`. This note covers this one launch.


## Candidate 225: Apple writes SDMA 0x444 once, during HWLibs init (2026-09-14)

Run `46c8f81af2087ab005ad64362a4ecadd`, card `metal-072`, launch 32 after `run/mode2-reset-33.json`. Verdict
`CORE_PROBE_PASS`, recovery `recovered`, shutdown `exited-after-guest-request`.

- The watchdog corrected the SDMA pair exactly once, about 13 s after its thread started,
  right after the `pre-TTL` register report and the HWLibs `GTrace synchronization point`
  lines (before `TTL::initialize` and RLC start): `0x444 -> 0x42` with RLC off
  (`RLC_CNTL=0`, `RLC_PG_CNTL=0`, `CP_STAT=0`). No further rewrite occurred in the rest of
  the run, and every later check (before RLC start, align manager, engine start, power-up,
  progress samples) read 0x42.
- Readbacks match launch 31: Shared-buffer copies, offscreen ramp and window drawable exact.
- 1280x1024 Managed-texture synchronize is still wrong on every pixel (1,310,720), with
  different displacements from the SDMA permutation (launch 22 top displacements
  (16,112), (-16,-112), (-16,16), each on 1/16 of pixels). Probe v7's
  `enableTexturePipeBankXor=0` child fixed exactly these paths, so this is a separate
  pipe-bank xor mismatch and likely also affects Managed-texture uploads.

Next: desktop probe v9 adds Managed-texture upload checks and displacement maps for the
Managed paths.
