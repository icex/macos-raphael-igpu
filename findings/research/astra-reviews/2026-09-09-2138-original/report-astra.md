**Astra review — Raphael iGPU failure analysis, 2026-09-09**

Reviewed source: `ef326108b868a00efb292e481ea2efb866205efa` on `dev`, including the existing uncommitted status, roadmap, research, and candidate178 archives. Status evidence cut: **2026-09-09 20:18 UTC**, candidate **1.0.178**, guest **24G830**. This report is for other agents to challenge and extend. It does not authorize implementation or another experiment.

**Finding**

The current failure is a native resource-preparation rejection, before the observed channel-submission boundary. The driver assigns GPU virtual addresses, but a map cannot complete backing preparation/page-table commit. The enclosing batch fails, and Metal reports `e00002bd` with no completed work. The exact rejecting backing or commit operation is **still unmeasured**. Calling this proven physical-memory exhaustion, an SDMA execution failure, or a shader incompatibility would exceed the evidence.

I independently checked the phase observer, raw A/B evidence, and relevant exact-binary disassembly. The central diagnosis in [status.md](status.md) is supported. This review adds useful static detail: **`map+0x18` is an `IOAccelMemory*`; the superclass cold path has two explicit Boolean rejection gates; the retained flags select video-memory fallback; and a concrete native commit implementation can reject a VA interval before allocating or writing a PTE.** These facts sharpen the next investigation without a GPU run.

The project has made real startup and cleanup progress. Its remaining methodological problem is that much of the evidence establishes delivery, observation, and lifecycle correctness, while the functional rejection still sits behind unobserved native calls. More passing harness tests or another unchanged warm launch cannot identify that call by themselves.

**Scope and verification performed**

I read the current status, README, roadmap, baseline audit, relevant bring-up/experiment records, Metal/Linux research and hypothesis matrix, candidate179 design, driver observers and memory interventions, classifier, probe, selected regression tests, and CI workflow. I inspected existing disassembly and independently disassembled portions of the exact local X6000 and IOAcceleratorFamily2 binaries.

Read-only verification established:

| Check | Result |
|---|---|
| Candidate178-A archive hashes | All 27 `SHA256SUMS` entries match; no other regular files except the checksum list |
| Candidate178-B archive hashes | All 29 entries match; same coverage condition |
| A/B complete archived manifests | Differ only in `run_id` |
| Raw versus canonical recovery JSON | Semantically equal in each run |
| Current probe source | SHA-256 matches the recorded `f0fc0ced81fe70732c3491cff1557a83d85c9ccb8c18a6303f9070ae1f969d77` |
| Local X6000 executable | Matches `2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e` |
| Local IOAcceleratorFamily2 executable | Matches `1700f3badafbb9014d55b7f6ecde5cdff0d585bd1f0e143c9f8465e4466e5d35` |

I respected the recorded testing pause: no test suite, build, VM, live VFIO/MMIO transaction, reset, or recovery was launched. Historical claims of 377 Python tests, the focused 72-test set, C++ fixtures, syntax checks, and KDK preflight remain historical results reported by the project, not fresh test results from this review. Receipt equality and archive integrity are not a fresh execution of the recovery validator. Existing work was preserved; this report is the only added project file. I did not read the separately pending `report.md`.

**What the experiments actually establish**

| Observation | 178-A | 178-B | Interpretation |
|---|---:|---:|---|
| Failed outer map preparations | 483 | 531 | Repeated calls, not that many distinct resources or independent experiments |
| Capacity / final VA / backing-PTE / unknown | 0 / 0 / 483 / 0 | 0 / 0 / 531 / 0 | Final observed failure family is after assigned VA |
| Channel `submitBuffer` entries | 0 | 0 | No work crosses this instrumented boundary in captured summaries |
| Completed command buffers / checked values / checked pixels | 0 / 0 / 0 | 0 / 0 / 0 | No compute or render acceptance |
| Probe error | status 5, `e00002bd` | Same | Explicit failed workload, despite a diagnostic `INCONCLUSIVE` verdict |
| Shutdown / recorded recovery | Guest-requested exit / recovered | Same | Supports this bounded normal lifecycle |

Sources: [A events](findings/experiments/metal-011-178-a/events.jsonl), [B events](findings/experiments/metal-011-178-b/events.jsonl), [A probe](findings/experiments/metal-011-178-a/probe.json), [B probe](findings/experiments/metal-011-178-b/probe.json). A's final trace/phase events are 161/162; B's are 159/160. Ordinary and notable sample drops are explicit; they are not missing lifetime counters.

The retained maps have `prepareCount=0`, `batchCount=0`, flags `0xb13`, and GPUVA `0x4000c0000` before and after failure. The two detailed samples per run repeat the same map within that run. There is no probe PID/nonce association in those samples. The aggregate rejection and the probe result strongly agree, but the report must not name that map as the probe's input or output buffer.

Apple's public [IOReturn definitions](https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/iokit/IOKit/IOReturn.h) confirm the numeric `kIOReturnNoMemory` interpretation. That name does not reveal the underlying native Boolean failure: a caller can translate several rejected prerequisites into one generic error.

Three cleanup-to-startup transitions on one boot are useful lifecycle evidence. They are neither three independent cold starts nor tests of cleanup after successful rendering. Recovery after a busy, working graphics workload, a panic, or force termination remains a separate qualification problem.

**Additional exact-binary findings**

The following offsets refer to the hashed 24G830 images, not stable APIs. X6000 disassembly is available at `/home/bogdan/macos-vm/re/x6000.asm`. The IOAccelerator image inspected is `/tmp/kdk-forensics.HZuAtO/IOAcceleratorFamily2`; that temporary path is not a durable dependency for another reviewer. Re-extract the matching KDK member and verify its hash if necessary.

1. **Resolve `map+0x18`: backing object, not length.** In IOAcceleratorFamily2 `IOAccelMemoryMap::init(IOGraphicsAccelerator2*, IOAccelTask*, IOAccelMemory*, unsigned)` at `0x5267e`, `RCX` is saved into `R15` at `0x5268f`, then stored into `[map+0x18]` at `0x526ea`. The object is retained and passed to `IOAccelMemory::add_mapping` at `0x52705`. This proves the field's declared base type. It does not prove a particular live subclass or the object's residency.

   X6000's map vtable is `0x165e30`, with address point `+0x10`. Slot `+0x168` resolves to `0x3b47a`, the named `AMDAccelMemoryMap::getLength`. Slot `+0x170` resolves to `0x3b4d2`, `commitIntoGPUPageTable`. Thus the mode-1 commit receives an `IOAccelMemory*` and a separately obtained length. The prohibition on making an extra virtual call merely for logging remains correct.

2. **The superclass rejection gates are now explicit.** IOAcceleratorFamily2 `IOAccelMemoryMap::prepare` is at `0x52c08`. With zero prepare count and flags bit `0x4` clear, it calls its cold helper at `0x58308`. The retained `0xb13` flags satisfy that condition. The helper does:

   ```text
   backing = map->field_18
   backing->virtual[0x148]()      // prepare; false rejects before commit
   map->commit_pte()             // 0x52c84; false rejects after backing prepare
   increment map prepare count on success
   backing->virtual[0x150]()     // completion/release of temporary preparation
   ```

   More precisely, backing prepare is called at `0x58322`; its false branch is at `0x5832a`. `commit_pte` is called at `0x5832f`; its false branch is at `0x58336`. The cold helper uses an output byte plus its own control return, so routing it as a simple `bool(map*)` would be wrong. Do not instrument an internal compiler helper using a guessed ABI.

   `commit_pte` can skip the virtual commit for certain flag combinations, but the retained `0xb13` has neither bit `0x40` nor the applicable `0x20` bypass. At that state, backing prepare success leads to the virtual commit call at `0x52cb0`. The two different flag words must stay distinct: this is **map+0x10**, whereas X6000's commit failure marker is bit `0x40` at **map+0x138**.

3. **The retained map selects video-memory fallback.** X6000 `batchMemoryMapPrepare` tests map flags bit `0x10` at `0x65be`; `0xb13` takes the branch at `0x660c`. That invokes accelerator slot `+0x940`. The IOAccelerator video-map fallback at `0x3fc58` contains a target-map prepare retry at `0x3fd38`. In the map initializer, the video selector is derived from backing-memory flags bit `0x4` (`0x5273c..0x52749`). This is a concrete reason to prioritize video backing/placement if commit is never entered. It is not proof that managed storage is the cause, or that the retained resource belongs to Metal.

   IOAccelerator `IOAccelMemory::prepare` at `0x28d6` calls backing slot `+0x1b0` when the already-prepared flag is clear. `IOAccelVidMemory::wire` at `0x561c0` propagates the Boolean from slot `+0x1e8` called at `0x5621a`. Resolving the actual X6000 subclass and this allocation operation is a concrete offline follow-up for the pre-commit branch.

4. **A commit false need not mean bad PTE bits or exhausted memory.** The static `AMDHWVMContext` vtable at `0x173170`, address point `+0x10`, slot `+0x120`, contains `0x55e62`: `mapVA(unsigned long long, IOAccelMemory*, unsigned long long, unsigned long long, VmMapFlags)`. Its first checks reject `VA < context[+0x80]` and `VA+length > context[+0x88]`. These occur before the page-table walk/update. A VA allocated successfully by the task can still violate a separately configured context's range.

   This supplies a specific, refutable commit-side hypothesis: **task VA allocation and native VM-context bounds disagree**. It is conditional: candidate178 captured neither task mode nor target vtable/bounds. Resolve the actual target before attributing this method to the failed runtime call. Do not raise bounds without measuring the disagreement.

   The static `AMDHWGart` vtable's slot `+0x130` resolves to `0x51822`, `updatePageTable(IOAccelSysMemory*, unsigned long long, bool, bool)`. That is a concrete alternate-backend lead, not proof that the runtime alternate target has this class. X6000 map initialization stores its alternate target at `map+0x118` from a hardware getter at `0x3b2cf`; the base hardware getter resolves to `0x7395a` and returns hardware `+0x378`. Finish the constructor/actual-vtable chain before interpreting it as GART.

**Candidate179 design review**

The [proposed commit observer](findings/research/2026-09-metal-integration/candidate179-design.md) chooses a useful boundary. Its 17-byte X6000 entry span is consistent with the disassembly. Preserving the native return, avoiding extra virtual calls, bounding storage, and separating route readiness from workload activity are appropriate. I would resolve these issues before treating its output as causal evidence:

| Priority | Gap | Why it matters / required resolution |
|---|---|---|
| High | Last matched commit is not necessarily the final prepare attempt | The outer function can retry. An earlier attempt can reach commit and fail; a later attempt can fail backing before commit. Keeping only the final *observed commit* cannot identify the final *prepare attempt*. Label this as a commit rejection observed within the outer call unless attempt ordering is separately proven. Add a conceptual/test case for commit-false followed by pre-commit failure. Zero correlated commit entries remains the stronger upstream discriminator. |
| High | Reusable slot lifetime is underspecified | Release/acquire publication of `active` protects initial construction; it does not stop another thread from clearing/reusing a slot after a scanner sees `active`. Non-atomic context reads can race reuse; a scanner can also act on a different generation. Specify atomic identity/generation validation and ownership of every slot write. A new outer token helps only if readers validate it. Include a paused scanner plus slot-reuse case, not just a slot still in `claiming`. This is a design gap, not an observed defect in candidate178's append-only buffers. |
| High | Two identical counter snapshots can still be partially accounted | A producer can pause between entry/exit/result counter updates while both reads return the same vector. The status already flags this. Define valid in-flight relations or publish only vectors satisfying settled cross-counter invariants. A bounded worker must also disclose when no final coherent summary was published. |
| Medium | Absence of this override requires dispatch coverage | Zero entries means upstream failure only if the observed map dispatches to this routed X6000 override and capture spans its call. Prove the relevant vtable, preserve unknown handling, and keep global/unscoped calls separate. Do not infer probe identity from map/thread correlation. |

For the exact ordinary superclass path above, successful commit proceeds to successful map preparation; a `commit-true-outer-false` result deserves scrutiny of retries, cleanup, alternate dispatch, or correlation before inventing a new post-commit allocator. None of these observations justifies forcing a native false return to true.

**Methodology and documentation findings**

The recent experiments have strong provenance: exact builds, unchanged A/B manifests, independent critical replay, bounded exposures, and preserved raw verdicts. They correct earlier mistakes such as waiting for workload-generated diagnostics before starting the workload and confusing a later KIQ timeout with the first SDMA timeout. Those improvements should be retained.

However, the following gaps affect future decisions:

- **The automated verdict names a missing downstream record instead of the observed functional rejection.** In [classify-run.py](tools/classify-run.py), the `sdma_vm_program` requirement returns `INCONCLUSIVE / sdma_vm_program_missing` before final probe assessment. This is consistent with the frozen experiment card, but misleading as a headline. Preserve raw results; add a separate future interpretation field for observed failure boundary, workload result, capture completeness, and lifecycle result. Do not weaken Metal acceptance to make this diagnostic pass.
- **Do not turn repeat counts into independent causal support.** A/B repeat the same software stack on one recovered boot. The 1,014 failed outer calls include retries/background activity. This supports reproducibility of a failure family, not a statistical ranking of backing versus commit.
- **Earlier progression needs a regression audit.** [Candidate171](findings/experiments/metal-005-171/notes.md) reached a WindowServer SDMA paging submission; candidates176–178 stop before the instrumented channel boundary. These are different runs/resources and not a controlled regression proof. Still, audit changes between them before assuming the newest failure is an unavoidable next milestone. Relevant changes include recovery reservation/pool caps, early BAR mapping, initialization ordering, and added routes. Static audit comes before any historical-binary replay.
- **Allocator capacity is now 240 MiB, not simply 256 MiB.** Candidate178-B serial records both pool sizes as `0x0f000000` on both `enableAllocations` calls. [RecoveryReservation.hpp](src/RecoveryReservation.hpp) caps the heap while preserving a 256 MiB BAR. Documentation should distinguish physical carveout, mapped BAR, allocatable heap, and fixed hardware allocations. The existing GART overlap audit proves recovery-write disjointness, not correctness of all native consumers of the modified size fields.
- **Duplicate pool initialization remains a conditional suspect.** The serial really shows manual and later native `enableAllocations` on the same pools. The call into `init_pool` is real. But no live-allocation destruction has been demonstrated. Assigned GPUVA does not absolve a separate video-backing allocator, and recurrence after guest restart does not absolve a deterministic initialization bug. Capture an actual violated allocator invariant before changing it.
- **README and source comments are stale.** README's status centers on 171/173 and says warm validation is pending. Current source strings still say nothing else calls `enableAllocations`, contradicted by the same run's later native call. Make README point to `status.md`; qualify old comments as historical. Preserve archived logs unchanged.
- **The exact framework evidence needs durable provenance.** Current manifests pin X6000/HWLibs/Framebuffer, while the phase interpretation also depends on IOAcceleratorFamily2. Its hash is documented, but the locally extracted image is temporary. Preserve extraction instructions, hash, and small reviewed disassembly intervals as durable evidence. An exact-byte prologue match alone does not verify all assumed private-field semantics.

The [top-20 matrix](findings/research/2026-09-metal-integration/top-20-issues.md) is sensible as a dependency map. Its sibling branches are not yet competing diagnoses with measured likelihoods. Linux comparisons are useful to identify hardware contracts; they cannot determine Apple's selected private callback. Linux itself distinguishes shared IP implementations from SoC/platform-specific handling in its [driver architecture documentation](https://docs.kernel.org/gpu/amdgpu/driver-core.html). Avoid converting a Linux policy constant directly into an Apple patch.

**Tests: strengths and blind spots**

[metal_probe.m](tests/metal_probe.m) checks actual compute values, sentinel replacement, completion/error state, and every rendered pixel, with nonce/expiry-bound delivery. This is a meaningful acceptance test. Its first command nevertheless combines managed input/output buffers, inline constants, shader dispatch, and a synchronization blit. It cannot isolate which internal resource preparation failed. Keep it unchanged as the acceptance gate; a smaller differential workload belongs in a separately designed diagnostic after the native rejection is located.

[test_submission_trace.cpp](tests/test_submission_trace.cpp) exercises the production phase classifier, legal assigned-zero VA, capacity boundaries, inconsistent snapshots, and sample overflow. These validate the encoded rules. They cannot validate the disassembly-derived field meanings or reproduce a native resource rejection. Its submission-store exercise is single-threaded. The concurrent [diagnostic-record test](tests/test_diagnostic_records.cpp) exercises a different store; it does not validate the proposed reusable correlation slots or the actual multi-counter publication routine in `RaphaelGPU.cpp`.

Source-shape tests are useful guardrails for route gating and experiment-card drift, but string positions do not prove ABI correctness, native-call count under all control flow, or concurrency safety. CI's sanitizers and whole-driver compilation remain valuable; they do not execute Apple's native allocator or the GPU.

The parser also performs less semantic validation than its strict-looking text format suggests. `_decode_payload` accepts numeric summary triples without checking their relationships, and accepts a detailed phase label without recomputing it from pre/post fields. Phase totals are checked, but monotonicity and drop bounds are not comprehensively established by that check. This does **not** invalidate the coherent A/B records inspected here. Future tests should reject impossible records while allowing legitimate in-flight accounting, rather than demanding entry/exit equality at every sample.

**Recommended next work for reviewing agents**

1. Independently verify the IOAccelerator offsets and constructor/vtable deductions above against the pinned images. Determine the concrete backing subclass and native allocation call selected by the retained video-memory map. Resolve task-context construction and the actual alternate target. These are offline tasks.
2. Finish candidate179's slot-lifetime and counter-publication design. Narrow its language to what commit observation actually proves across retries. Preserve the zero-entry discriminator, unknown handling, and native behavior.
3. Audit the 171-to-176 source changes against the earlier paging evidence, including the 240 MiB heap intervention and double initialization. Produce a violated-invariant hypothesis or explicitly retain uncertainty; do not combine several speculative reversions.
4. If later authorized, use one diagnostic to choose between **backing prepare rejected** and **a correlated native commit rejected**. If pre-commit, follow the backing prepare/wire/allocation call. If commit-false, identify the actual backend, validate its VA interval and inputs, and follow its first rejecting predicate. Neither result alone licenses PTE rewriting.
5. Advance to VM programming, SDMA/queue consumption, fences, shader correctness, and presentation only as work reaches those boundaries. Keep the old SDMA failure open as a downstream concern. Treat warm recovery after successful GPU work as a new lifecycle qualification.

The terminal ledger is **6/6**. This review supplies no additional launch authority and makes no claim that the historical host hangs are solved. The actionable conclusion is a precise failure family and a substantially narrower native call graph—not a demonstrated functional fix.
