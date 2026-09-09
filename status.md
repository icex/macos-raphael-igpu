# Raphael iGPU: current technical status

**Standing escalation rule (2026-09-10):** after a fourth consecutive GPU test
cycle with the same unresolved issue, pause routine retries and obtain a
`gpt-6-astra` / `xhigh` adversarial review using the user's exact prompt. Archive
the previous report, review the new findings with implementation agents, and
record the revised experiment before resuming. The durable instructions and
counting rules are in [AGENTS.md](AGENTS.md). Builds and offline unit tests do
not count. Last hardware run remains **178-B**; no new hardware cycles have run
during the current report review. The inherited streak is **at least four cycles: 176, 177, 178-A, 178-B**, all
with no completed Metal command and `e00002bd`. The exact pre-submission boundary
is directly observed in 177 and 178-A/B; 176 has no downstream SDMA callback but
lacks the later submission observer. This conservative symptom-based trigger
is sufficient to request a fresh Astra review before any more hardware testing.
The original report is preserved in `findings/research/astra-reviews/2026-09-09-2138-original/`.
Current offline work corrects native recovery ownership and adds backing allocation
observations; it has not demonstrated functional progress or reset the streak.

Last updated: **2026-09-09 22:49 UTC**. Maintained by the coordinator after each hardware run,
material finding, implementation change, or review correction. This is the current review entry
point; older handoffs and chronological findings can contain superseded conclusions.

**Latest offline verification:** the frozen integration passes **449/449 Python
tests** and **12/12 C++ fixtures**, compiled with g++, warnings as errors,
ASan and UBSan. The coordinator read the combined results, checked the final diff,
and verified that the archived 178-B ledger and both receipt hashes match.
Whole-driver Apple-kext syntax and exact-KDK symbol/prologue preflight also passed
for the final guest code. Logs are preserved under
`findings/research/2026-09-metal-integration/candidate-179-offline-verification/`.
These are offline results, not evidence of Metal execution. The coordinator accepted the guest
implementation after checking exact owner guards before native pool mutation and
the native both-pool reserve ABI. See
`findings/research/2026-09-metal-integration/lease-v2-verification.md`.
Candidate metadata is now 1.0.179, and the new experiment card is `metal-012`.
The independent one-run policy is only offline code: no live authority or activation
has been created, and it does not itself approve a seventh launch. No new build,
deployment, GPU cycle, or ledger admission
has occurred; last hardware evidence remains 178-B and the streak remains at least four.
Next is one clean candidate build and a staging-only transaction. The existing
`redeploy.sh` is not a staging-only command and must not be used for this preparation.

**Work resumed:** the user supplied `report-astra.md` and `report.md` and requested
verification, fixes, and automated desktop Metal testing. Three agents are independently
checking native backing/commit dispatch, the allocator regression, and recovery ownership.
The last hardware action remains 178-B's validated cleanup. Fresh read-only checks confirm
the same host boot, vfio-pci binding, enabled watchdog/NMI/panic settings, and active sleep
inhibitor; no QEMU or experiment process was found. No sudo is needed for this investigation.

**Review priorities:** compare 171's reached paging submission with 178's pre-submit rejection;
verify the 240 MiB pool cap and duplicate initialization against actual allocator domains;
resolve the exact native backing/commit rejection. The reports' cap correlation is a strong
lead, not yet a controlled causal result. The proposed test that puts recovery scratch inside
Apple's allocatable heap is rejected: descriptor validation does not establish exclusive memory
ownership. Any functional experiment must preserve that ownership. Candidate179's earlier
commit-correlation design has been replaced by the bounded physical-backing observer.

**New static correction under independent review:** IOAcceleratorFamily2 24G830
`init_pool(unsigned long long, unsigned long long, unsigned long long)` at `0x1facc`
initializes the pool using its first numeric argument, then calls
`reserve(nullptr, second, third)`. It is not a start/end range initializer.
X6000's unequal branch at `0x52a71` therefore does not establish the claimed inverted
range. Both our existing equalization rationale and Claude's suggested field swap depend on
that incorrect interpretation. Agent verification is tracing zero-length reservations,
actual total/visible fields, and native allocation ownership before selecting a correction.
Evidence: local `/tmp/ioaccel.dis` lines 35537 onward and exact X6000 `0x52a1e` routine.
This is a static finding, not evidence that restoring capacity makes Metal work.

**Recovery ownership regression found offline:** independent review resolves the VMM
68 MiB request to `AMDHardware::appendToReservedVRAMOffset` (`0x72afe`), a top-down
reservation operation. The logged low address `191922176` is `0x0b708000` (Claude's
hex conversion was off by 8 KiB), yielding the inferred BAR-relative reservation
`[0x0b708000, 0x0fb08000)`. Existing descriptor and scratch at `0x0f000000` and
`0x0f100000` lie within that interval. The software pool cap cannot exclude an earlier
hardware reservation. Successful stopped-device cleanup does not establish non-overlap while
macOS runs. No further GPU transaction is being attempted until the ownership correction is
reviewed. Relocation above the VMM end is also unproven: top-down allocation means older
reservations may occupy that area. The report's “183 MiB consumed below MQD” inference is
unsupported for the same reason. Full address/owner publication remains part of the audit.

**Current result: Metal enumerates and shaders compile, but no Metal command buffer has completed.
Full desktop acceleration is not working.** Two runs of candidate 178 consistently locate the
observed rejection after GPU virtual-address assignment, in backing-memory preparation or
page-table insertion, before channel submission. The next task is to separate those two paths.

## Objective and live work

**Standing regression requirement (user, 2026-09-09):** every change must check for
regressions. Tests must cover the affected behavioral contract and failure cases, not only
source shape. Compare each hardware run with both its immediate baseline and the furthest
previously reached relevant stage (currently 171's client paging submission). Report a lost
stage explicitly; lifecycle success never substitutes for functional progress. Memory changes
must test allocator capacity, visible/total semantics, protected-range ownership, and repeated
initialization. Preserve historical raw verdicts and report functional interpretation separately.


The objective is correct Metal compute and rendering, then a usable accelerated macOS desktop
through the VM display, with repeatable GPU cleanup and reuse that protects the Linux host.
Gaming is outside the current focus. Do not infer an overall completion percentage from the
number of patches or the advertised Metal version.

- **Hardware:** stopped after 178-B; its normal recovery validates. No further hardware run is
  admitted by the completed two-run plan. Its terminal boot ledger is **6/6**; a new finite
  experiment must preserve that history and review fresh hardware prerequisites.
- **Implementation:** candidate 178 is an observation change, not a functional memory fix.
  The narrow `AMDAccelVidMemory::allocPhysical` observer is being implemented with production
  helper tests; the earlier commit-correlation design is superseded. Recovery lease implementation
  is authorized offline under the agreed immutable ownership and separate pool-status contract. No build or deployment has occurred.
- **Research:** Metal and Raphael/Navi/Linux reports are written. The combined list of exactly
  20 potential issues is written and cross-reviewed. Further research and the native
  commit-target analysis have resumed against both external reports.
- **Documentation:** candidate 178 archives and roadmap updates are written on `dev` and
  reviewed. Archive checksum and identity checks passed; small wording corrections are underway.
- **Integration:** no merge or push to `main` until full acceleration is demonstrated. No new
  release, push, or build was performed after the 178-A/B runs.

| Owner | Active responsibility |
|---|---|
| Coordinator | Reviews both reports, verifies host state, coordinates implementation; maintains this status |
| `lease_review` | Sol agent auditing/fixing guest lease, native ordering, and VMM arena diagnostics |
| `host_review` | Sol agent auditing host lease validation, regression comparisons, and host integration plan |
| `harness_v2` | Sol agent integrating prestaged nonce identity, canonical recovery records and VMM readiness |

`astra_stall_review` completed the required review; its report and accepted next
test are linked below. The guest helper's focused sanitizer fixture passes;
production integration and the full affected test suite remain in progress.

Implementation and testing are delegated to agents; the coordinator reviews their changes.
Other reviewers should provide sourced suggestions rather than start another VM or touch the GPU.

## Current implementation decision

**Fourth-cycle review complete:** the fresh [report-astra.md](report-astra.md)
has SHA-256 `5314d914023ea152ee54313f8bd3ec4bb80ba33ff8d1b6b87f70ef13b5500d3a`.
The coordinator read it in full and independently checked the VMM retry, arena
factory/reserve and null-allocator instruction intervals. Its H1 and minimum
functional experiment are accepted, with runtime attribution still conditional.
Guest/host agents are addressing the reported integration defects and will assess
the final report before hardware testing. The implementation sequence is recorded
in [the revised plan](docs/superpowers/plans/2026-09-10-native-vmm-arena.md).
No functional progress is yet measured, so the inherited streak remains at least
four; completion of this review does not reset it.

**Fresh adversarial finding (21:44 UTC, verification continuing):** native
`AMDHWVMM::setMemoryAllocationsEnabled` does not return when `VMM+0x20` is
non-null. Its `0x5793d` branch skips channel creation but reaches `0x57ba8`.
At `0x57bdc` it requests the full `0x4400000` arena at `VMM+0x50`, stores the
returned object at `+0x58`, and exits at `0x57d18` if null. The two page-table
allocators at `+0x78` and `+0x80` are created only after that succeeds. The
historically inferred arena ends at `0x0fb08000`, beyond our `0x0f000000`
software-pool cap. Astra resolved the service target through `AMDHWHandler`
`createVidMemoryWithPhysicalAddress` (`0x4ab86`) to
`AMDAccelVidMemory::withPhysicalAddress` (`0x3a830`), whose reserve-enabled
branch calls `AMDHWMemory::reserve` and returns null on failure. Separately,
`allocVMBlock` (`0x57ed2`) returns false immediately if `VMM+0x78` is null.
This is a concrete candidate explanation for absent mapping resources, stronger
than generic exhaustion; runtime allocator pointers still need verification.
Existing VMM route diagnostics will
record these fields in the corrected candidate. No new GPU result is claimed.

**Discriminating prediction:** if the top-down cursor is unchanged from 178-B,
the new 0x15000-byte lease is `[0x0faf3000,0x0fb08000)` and the following
68 MiB VMM arena becomes `[0x0b6f3000,0x0faf3000)`. These are source-derived
predictions, not measured addresses or mandatory hardcoded locations. Acceptance
uses the actual native allocation and full memory base. A final `XV2 VMM
phase=native enable=1` record must show non-null `arena`, `pool0`, and `pool1`
(`VMM+0x58/+0x78/+0x80`). If it never returns, the critical native-entry log
separates that stall from a returned null arena. Even all three non-null pointers
are only prerequisites: the unchanged probe must still complete correct GPU work.

Root and Astra independently also found the pending guest OWNED/POOL log nonce
order reversed relative to the host parser. Agents are correcting the producer
and adding a log-format contract test; matching binary fixtures alone missed it.
Root subsequently verified an allocator-enable ABI defect: its native tail target
`isDeviceValid` returns through `mov al`/`and al,1` (`0x7091b..0x7092d`), so
upper EAX bits are not a Boolean result. The lease wrapper must use the Boolean ABI
before treating enablement as successful. This is being corrected offline.

The first functional candidate will correct recovery ownership and remove the 240 MiB cap,
while retaining the 256/256 MiB equalization and `rgpuvmm=3` to avoid combining independent
hypotheses. The obsolete forced `AMDHWMemory::enableAllocations` call/route will be removed
as part of making native pool initialization authoritative. A dynamic, native-owned type-0
reservation is being designed before VMM/queue initialization; the exact same range must then
be excluded from both software pools before ordinary clients can allocate. Its launch-bound
nonce/locator must reach the host without occupying somebody else's VRAM. Host cleanup must
also handle a guest crash before final software-pool activation; missing ownership proof must
never authorize scratch writes. No fixed free gap has been assumed.

The independent observer uses exact 24G830 `AMDAccelVidMemory::allocPhysical` at `0x3aa76`,
not the compiler-generated base prepare helper. It preserves native behavior and records a
bounded set of allocation failures with independent live true/false completion counts. No
cross-call slot reuse, map/probe association, extra virtual invocation, or MMIO is introduced.
The root reviewed the helper/test and route/parser diffs. The agent reports 53 focused Python
tests, concurrent ASan/UBSan C++ fixtures, whole-driver syntax, route ownership, and exact
symbol/prologue checks passing. Review follow-ups added live replay preservation and sixth-route
readiness without requiring workload callbacks; periodic publication is being budgeted for the
full exposure. These are offline results, not native GPU acceptance. Restoring native 512/256 capacity is a subsequent separate functional experiment.

The v2 wire contract is now fixed for implementation: an immutable 80-byte OWNED record at
lease+0, and a separate 104-byte pool result at lease+0x100. The compact lease occupies
0x15000 bytes; scratch starts at +0x1000 and ends at +0x14004. Host and guest tests must agree
on every byte. Byte-identical log replay is not a new lease; conflicting identity/status is
rejected. The old v1 format remains readable only for historical receipts, never a fallback
for a new GPU launch. No ledger revision or device transaction has been performed.

## Reproducible target

| Item | Current value |
|---|---|
| Guest | macOS Sequoia **15.7.9**, build **24G830**, x86_64 |
| GPU | AMD Raphael, GC 10.3.6, physical PCI `1002:13c0` at `0000:7b:00.0` |
| Guest identity | Navi23 spoof `1002:73ff`; Metal name `AMD Radeon Navi23` |
| Host | CachyOS kernel `7.2.3-1-cachyos-bore` |
| Host boot ID | `5d6f45d0-4384-4340-b819-7751bc26ebb3` |
| GPU ownership | `vfio-pci`, IOMMU group 31; host display remains on the discrete GPU |
| QEMU | 10.1.2 |
| Branch | `dev`; documentation work is currently uncommitted |
| Candidate source commit | `ef326108b868a00efb292e481ea2efb866205efa` |
| Candidate version | RaphaelGPU **1.0.178** |
| Loaded build ID, both runs | `5908f278b80548d6b9c88e2e9a300ae5` |
| Driver executable SHA-256 | `0456ad80a694d0ccd1a9fa9297f77ba629af8a620e29c877baa710c8be1006a5` |
| Source digest | `cc44faa70f6ad2db0f202e8a831897f1f655784edbf7b8faba1d04ce490940ca` |
| Experiment card | [experiments/metal-011.json](experiments/metal-011.json) |

Both runs used identical driver, configuration, boot disk, boot arguments, and prepared probe.
Their predeclared manifests differ only by run ID. The VM exposure limit was 180 seconds and
the unchanged probe had a 45-second process budget.

```text
-v keepsyms=1 tlbto_us=0 vti=9 serial=3 debug=0x108 -lilubetaall
rgpudump=40000 rgpu=0xfffa5981 rgpuvmm=3 rgpumem=2 rgpuptb=2
rgpumqd=2 rgpuhybrid=1 rgpusdma=1 rgpuvmroot=1 rgpusubmit=1
```

These are evidence of the tested configuration, not instructions to launch it outside the
experiment coordinator.

## Progress and latest results

| Checkpoint | Evidence | Limit |
|---|---|---|
| OpenCore/Lilu injection and Navi23 matching | Exact loaded build verified | Does not prove execution |
| Native KIQ and engine startup | KIQ stamps 1, 2, 3; native engine/accelerator startup succeeds | KIQ completion is not a shader test |
| SDMA topology | One physical SDMA instance retained; residual channel mapping applied | Workload paging remains untested in these runs |
| Metal API and shader compilation | Expected device, Metal 3, library/pipeline/queue/buffer creation | API objects can exist before residency succeeds |
| Resource preparation | **Fails**, consistently in backing/PTE phase | Exact underlying rejecting callback still unknown |
| Channel submission | **Zero** observed `submitBuffer` entries | Work has not crossed this boundary |
| Compute correctness | **Zero** completed rounds or checked values | No passing compute result |
| Render correctness | **Zero** checked pixels | No passing offscreen render result |
| Desktop presentation | Not qualified | Separate surface/display integration remains |
| Normal cleanup and warm startup | Three measured cleanup-to-restart transitions on this boot | Not crash/force-close recovery or unrestricted reuse proof |

| Latest run | 178-A | 178-B |
|---|---|---|
| Run ID | `f103e47500ed4a06ae346df23250d95d` | `4a45f4a4c1dd49c69fab2dc37e2e4898` |
| Start, UTC | 2026-09-09 19:44:52 | 2026-09-09 19:52:41 |
| Startup and capture gates | Passed | Passed |
| Failed map preparations | 483 | 531 |
| Phase counts: capacity / VA / backing-PTE / unknown | 0 / 0 / 483 / 0 | 0 / 0 / 531 / 0 |
| Completed Metal command buffers | 0 | 0 |
| Probe status | 5 / `e00002bd` | 5 / `e00002bd` |
| Shutdown | `exited-after-guest-request` | `exited-after-guest-request` |
| Normal schema-6 recovery | Valid, errors `[]` | Valid, errors `[]` |
| Recorded host/IOMMU/reset fault | None | None |

The raw classifier result in **both** runs remains:

```json
{"verdict":"INCONCLUSIVE","earliest_failure":"sdma_vm_program_missing","warm_reuse":"recovered"}
```

That verdict is preserved. Its required downstream VM-program record is absent because the
observed work never reaches submission. The new phase diagnosis is a separate conclusion from
the trace; it does not turn the original run verdict into a Metal pass.

## Relevant captured evidence

Candidate 178-A retained these native callback snapshots:

```text
SUB: map-phase seq=6 class=backing-pte accel=0xffffff95185b1000 map=0xffffff904c593600 thread=0xffffff86b3670598 pre=0/0/0xb13/0x4000c0000 post=0/0/0xb13/0x4000c0000
SUB: map-phase-summary total=483 capacity=0 va=0 backing-pte=483 unknown=0 dropped=0/0/481/0
SUB: summary process=162/162/162 mappings=483/483/483 prepare=486/486/486 map=483/483/483 submit=0/0/0 dropped=3164/1582
```

Candidate 178-B repeated the same scalar map state on its own guest objects:

```text
SUB: map-phase seq=6 class=backing-pte accel=0xffffff9dcc264000 map=0xffffff98fdc98180 thread=0xffffff99009c70c8 pre=0/0/0xb13/0x4000c0000 post=0/0/0xb13/0x4000c0000
SUB: map-phase-summary total=531 capacity=0 va=0 backing-pte=531 unknown=0 dropped=0/0/529/0
SUB: summary process=178/178/178 mappings=531/531/531 prepare=534/534/534 map=531/531/531 submit=0/0/0 dropped=3484/1742
```

Here `pre` and `post` contain: batch prepared-map count / map prepare count / full map flags /
raw GPU virtual address. Flags bit 0 records an assigned GPU address. Both samples therefore
have an address before and after the failed native call; neither batch is at its capacity limit.

The unchanged probe reached:

```text
RGPU_METAL_STAGE enumerate
RGPU_METAL_STAGE compile_shaders
RGPU_METAL_STAGE compute
RGPU_METAL_STAGE commit
command failed: status=5 error=Error Domain=MTLCommandBufferErrorDomain Code=1
"Internal Error (e00002bd:Internal Error)"
```

Each run's complete nonce-bound JSON reports `passed=false`, `metal3=true`, and zero
`completed_command_buffers`, `compute_rounds`, `compute_values_checked`, and
`render_pixels_checked`. Guest exit is 1; transport exit is 0. `e00002bd` is the IOKit
`kIOReturnNoMemory` value; the Metal wrapper alone does not identify the particular allocator.

The first probe command uses two **256 KiB managed buffers**, `didModifyRange`, compute dispatch,
and a managed-resource synchronization blit. It is not an isolated shader-only workload.
See [tests/metal_probe.m](tests/metal_probe.m). A passing complete probe must check 196,608
compute values and 4,096 rendered pixels, with at least four completed command buffers.

Candidate 178-B also confirms that the global DMA paging channel exists before the failed work:

```text
XV: after forced enable: m_0x20=0xffffff9dcbef2000 m_0x28=0xffffff9dcbd3bc00 m_0x30=0xffffff98fecd6000 -> DMA PAGING CHANNEL PRESENT
XV: setMemoryAllocationsEnabled(1) exit:  m_0x20=0xffffff9dcbef2000 m_0x28=0xffffff9dcbd3bc00 m_0x30=0xffffff98fecd6000 -> DMA PAGING CHANNEL PRESENT
```

This contradicts a simple missing-global-paging-channel explanation. It does not establish that
every per-client page-table object is initialized correctly. Earlier log lines with null pointers
before enablement are not the final enabled state.

### Observation limits

- These are **final blocking phases after native retries**, not necessarily the first failure.
- Detailed samples are bounded and can overflow; atomic lifetime counters continue. The
  independent critical replay and worker validation passed in both runs.
- Object and kernel-thread tokens do not identify the issuing guest PID or probe nonce.
  Do not claim a retained background map is the probe's input or output buffer.
- Capacity and final VA acquisition are excluded as the blocking branch for the **observed
  failures**. Earlier recovered VA misses or unrelated allocation defects are not globally excluded.
- No downstream VM callback is evidence of an earlier stop, not proof that the VMID-2 root,
  PTE flags, SDMA, fences, shader ISA, or display path is correct.

## Exact implementation boundary and next diagnostic

Private offsets below are specific to the extracted **24G830** binaries, not stable APIs:

| Binary | SHA-256 |
|---|---|
| AMDRadeonX6000 | `2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e` |
| IOAcceleratorFamily2 | `1700f3badafbb9014d55b7f6ecde5cdff0d585bd1f0e143c9f8465e4466e5d35` |

The observed chain is:

```text
batchMemoryMapPrepare (X6000 +0x6550) -> false
  BatchPrepareMappings (+0x18256) -> zero mappings prepared
  BatchPrepare (+0x184d8) -> false
  enclosing command processing -> e00002bd
  submitBuffer -> never entered
```

Candidate 178 observes accelerator `+0x1fb0`, map `+0xc`, map flags `+0x10`, and raw GPUVA
`+0x98` through the existing safe wrapper. It preserves the native result and performs no MMIO,
allocation, waits, or formatted logging in that callback.
See [the phase design](findings/experiments/metal-010-177/memory-map-phase-design.md),
[src/SubmissionTrace.hpp](src/SubmissionTrace.hpp), and [src/RaphaelGPU.cpp](src/RaphaelGPU.cpp).

The current implementation observes `AMDAccelVidMemory::allocPhysical` at **`+0x3aa76`**,
ABI `bool(this)`, exact guarded entry `554889e5415741564155415453504883ec18`.
The callback captures the native result and proven scalar fields without altering allocation.
Four immutable failure samples are retained; live true/false completion counters continue
beyond sample saturation. The sixth route is required before this observer is armed.

Exact 24G830 backing dispatch verified by independent review:

```text
map+0x18 = retained IOAccelMemory* (IOAF init 0x5267e, store at 0x526ea)
IOAccelVidMemory::prepare -> IOAccelMemory::prepare (+0x28d6)
  backing vslot +0x1b0 -> IOAccelVidMemory::wire (+0x561c0)
  backing vslot +0x1e8 -> AMDAccelVidMemory::allocPhysical (X6000 +0x3aa76)
```

A false observed here proves this backing allocation operation rejected. A true result does
not prove that its enclosing map committed, and no sample is identified as a probe resource.
The existing outer backing/PTE phase counts remain separate. The observer records length at
backing+0x40, owner+0x110, allocation element+0x118, raw field+0x120, and flags+0x128.
Unproven placement/alignment semantics remain explicitly raw.

The [earlier candidate179 commit-correlation design](findings/research/2026-09-metal-integration/candidate179-design.md)
is **superseded and not implemented**. Review found that the last commit need not belong to
the final prepare retry, slot reuse was not protected for scanners, and equal counter snapshots
could still be partially accounted. The direct native backing observer avoids those mechanisms.
If backing succeeds but map preparation still fails, the next candidate boundary remains
`AMDAccelMemoryMap::commitIntoGPUPageTable` (+0x3b4d2): task mode selects task+0x260 vslot+0x120
or map+0x118 vslot+0x130. That route has not been added. The first branch can reach native VM
range checks before PTE work; no page-table correction is justified without a measured defect.

Do **not** route `AMDAccelMemoryMap::prepare` at `+0x3b3fe` with the existing trampoline:
its initial displaced span contains a relative branch outside that span. Do not replace native
false results with true, raise the `0x3ff` batch bound, or rewrite PTEs without a measured defect.

## Cleanup, repeatability, and host constraints

Measured cleanup-to-startup transitions are:

```text
candidate176 normal cleanup -> candidate177 successful startup
candidate177 normal cleanup -> candidate178-A successful startup
candidate178-A normal cleanup -> candidate178-B successful startup
candidate178-B -> normal validated cleanup, then stopped
```

Both 178 receipts record two genuine MEC queue dequeues, zero timeouts and forced inactive
clears, a completed temporary host-KIQ graphics retirement fence, final disabled/clean queue and
doorbell state, ordered SDMA shutdown, and both exact PSP ring-destruction acknowledgements.
PCI command remains 3 (bus mastering off), reset methods remain empty, and the recovery kernel
message interval is empty. Both raw/canonical receipt pairs validate under the current consumer
with `[]`; they are semantically equal JSON, **not identical serialized bytes**.

| Receipt | 178-A | 178-B |
|---|---|---|
| Recovery ID | `0975a837f47b47389c032cdb9a3e9a14` | `8fb71c4acf944fa3b6ee545dfb58a448` |
| Raw SHA-256 | `e696db64544372dd986df8319c9bd931bf7e2e81a0c89db4ea0eaebeb34a4fd5` | `ea9f41341b5d0f5ff08f7ef72ee44bd052c2a823ebeaae267c57798b5dd789d5` |
| Canonical SHA-256 | `528a400f4c059bb150ed98f480434599e27fbe3648fc9b6b4f635d6f47b24f4e` | `fc1c08c831cd0b95862ae397f0ac60f09e312bba6316bac67c9cceae609e956c` |

The terminal six-row ledger SHA-256 is
`8105707580a4d89b2e883be90730e1e84ad32f42e69a0310264f3e5431f0260f`.
B's receipt is cleanup evidence; it does **not** override the exhausted experiment policy.

This sequence does not prove recovery from every macOS panic, forced QEMU termination, or host
boot state. Historical host hangs remain unexplained. No finite test guarantees no future hang.

Standing constraints for every reviewer/operator:

- No extra VM launch, live VFIO inspection, MMIO experiment, reset, or manual recovery outside
  a separately reviewed experiment. Do not erase ledgers, receipts, or consumption history.
- Never cycle `vfio-pci -> amdgpu -> vfio-pci`; never use virgin-iGPU passthrough.
- Never use PCI/bus reset, PSP MODE1, GRBM soft reset, or retarget Apple's SMU messages to the
  host CPU's SMU. Preserve the host discrete GPU and sibling devices.
- Current tests and cleanup operate without sudo. Never use `sudo -n` authentication probes.
- No host kernel, Secure Boot, bootloader, `/etc`, or initramfs changes are part of this work.
- `rgpu-work-inhibit.service` is active; watchdog, NMI watchdog, and hardlockup panic read 1.
  Persistent one-second journaling and EFI pstore configuration pass the current capture gate.
  `pstore_files=null` means its contents were not established, not that pstore was empty.

## Evidence and review entry points

- [178-A archive](findings/experiments/metal-011-178-a/manifest.json),
  [events](findings/experiments/metal-011-178-a/events.jsonl),
  [probe](findings/experiments/metal-011-178-a/probe.json),
  [recovery](findings/experiments/metal-011-178-a/recovery.json).
- [178-B archive](findings/experiments/metal-011-178-b/manifest.json),
  [events](findings/experiments/metal-011-178-b/events.jsonl),
  [probe](findings/experiments/metal-011-178-b/probe.json),
  [recovery](findings/experiments/metal-011-178-b/recovery.json).
- [Roadmap](docs/ROADMAP.md) and [historical findings](findings/GPU-RE.md) now include both runs
  and the completed three-transition sample. [A notes](findings/experiments/metal-011-178-a/notes.md)
  and [B notes](findings/experiments/metal-011-178-b/notes.md) explain the retained raw verdicts.
- [Existing Linux comparison](findings/raphael-vs-navi-linux.md) and
  [candidate176 submission forensics](findings/experiments/metal-009-176/submission-failure-forensics.md).
- The [new hardware/Linux research](findings/research/2026-09-metal-integration/raphael-navi-linux.md)
  and [ten hardware hypotheses](findings/research/2026-09-metal-integration/hypotheses-hardware.md)
  are now in the repository. Review corrected the version label, distinguished tagged source
  from verified signatures, and removed a causal exclusion unsupported by the host logs.
  The combined research review is still open.
- The [Metal internals report](findings/research/2026-09-metal-integration/metal-internals.md),
  [Metal hypothesis analysis](findings/research/2026-09-metal-integration/hypotheses-metal.md),
  and [combined top-20 matrix](findings/research/2026-09-metal-integration/top-20-issues.md)
  are now available. The matrix is the intended canonical elimination order; its final review
  is checking virtual-call observation and guest-wiring versus host-IOMMU boundaries.
  Ranks 1 and 2 are the active sibling branches; downstream execution/display rows stay untested.
- Original research drafts and source caches remain under
  `$HOME/macos-vm/run/research/metal-integration-20260909/`.
- Original run directories remain `$HOME/macos-vm/run/metal-011-178-a` and
  `$HOME/macos-vm/run/metal-011-178-b`. Archived evidence is not to be rewritten.

Candidate178 passed 377 Python tests, the focused 72-test experiment/qualification/adversarial
set, C++ UBSan fixtures, whole-driver syntax checking, and exact-KDK preflight before the build.
Those checks establish the tested software properties, not GPU execution. New driver and test changes are present but have not been built or run on the GPU.

Useful external suggestions should name the exact source/build/function, explain how the
observed state can follow, identify contrary evidence, and specify the smallest observation
that would refute the hypothesis. Prioritize backing preparation versus PTE insertion. Keep
later VM/SDMA/ISA/display concerns in the roadmap until work can reach those boundaries.
Do not revive the superseded claims that a stale PSP ring is the entire problem, that KIQ cannot
execute, or that Metal enumeration already demonstrates acceleration.
