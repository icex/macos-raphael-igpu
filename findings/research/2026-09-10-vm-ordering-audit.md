# VM ordering and address-path audit (2026-09-10)

## Scope and conclusion

This was an offline, read-only audit of the current tree, the pinned Linux 6.12
source, the pinned 24G830 `AMDRadeonX6000` image, and frozen candidate-187
evidence. No VM, device, sudo, or implementation action was performed.

I found one proven unsafe publication design under changed or concurrent
generations: the framebuffer aperture and target marker are process-lifetime
latches with no teardown/reinitialization protocol. I did **not** find evidence
of a stale dereference or torn tuple in candidate 187/188: both observed aperture
publications contain the same values, and the native startup calls may be
serialized before VM use. I found no omitted direct
caller of the wrapped X6000 contiguous DMA update function. SDMA completion and
TLB-invalidation ordering remain unobserved, rather than demonstrated wrong.

## 1. Proven design hazard: aperture/identity state has no generation or reset

`src/RaphaelGPU.cpp:248-254` defines independent global atomics for target
identity, three aperture words, and a published boolean. `wrapFbXgmiConfig`
writes the three words and then release-stores `cachedFbPublished=true`
(`src/RaphaelGPU.cpp:5932-5938`). `isRaphaelHardware` independently
release-stores `raphaelTargetConfirmed=true` (`src/RaphaelGPU.cpp:4690-4694`).
There is no store of false to either latch after static initialization, and no
reset of the three aperture words, `asicInfo`, or `hwMemObject`; repository-wide
call-site searches establish this absence. `hwMemObject` is reassigned by
`wrapHwMemVram` (`src/RaphaelGPU.cpp:2534-2540`), but never invalidated.

The unsafe design is reachable because `wrapFbXgmiConfig` is not one-shot. Frozen
candidate-187 serial evidence invokes it twice, at
`findings/experiments/metal-020-187/raw/serial.txt:1376-1377` and
`:1907-1908`. Once the first publication is true, the second invocation updates
the three words while readers are permitted to consume them. Readers acquire the
already-true boolean and then independently relaxed-load the words at
`src/RaphaelGPU.cpp:4129-4137`, `:4165-4170`, `:4179-4182`, `:4220-4228`, and
`:4794-4809`. Release/acquire publishes the *first* tuple correctly; it does not
make later multiword replacement an atomic snapshot. A reader can therefore
observe a mixed old/new tuple if a later callback changes the aperture. After an
accelerator teardown/reinitialization, it can also accept a stale marker or stale
object pointer before the new instance republishes them.

The demonstrated 187 invocations both report `f400/f41f/840`, so no torn tuple or
stale-generation use is demonstrated in that run. The available source/evidence
also does not establish a teardown-to-later-dereference call sequence for the
stale object pointers. This is therefore a medium-severity robustness hazard
whose runtime manifestation remains unverified, not an evidence-backed
explanation of the current VMID1 fault.

Independent test: first establish whether native initialization guarantees a
single immutable aperture per loaded plugin instance. If that invariant holds,
an immutable once-only tuple is the minimal design: publish once and reject any
later different tuple. If repeat initialization is supported, use a small
generation-checked helper (odd generation while writing, even generation after
publication, or an immutable tuple exchanged by pointer). Run two writer generations with
distinct valid tuples while many readers snapshot; assert every accepted read is
exactly generation A or B. Add lifecycle tests that publish, invalidate, and
reinitialize with a different identity/aperture and assert no callback becomes
active between invalidation and the second publication. A source-level test must
also assert the actual stop/power-off path performs invalidation; arithmetic-only
unit tests cannot prove this.

## 2. No direct contiguous-update caller is omitted

The pinned 24G830 binary has exactly three direct calls to
`AMDHWVMContext::updateContiguousPTEsWithDMAUsingAddr` at `0x55cda`:

| return offset | native path | plugin label |
|---|---|---|
| `0x559dc` | leaf mapping | `Leaf` |
| `0x55a72` | child-directory mapping | `Child` |
| `0x561f6` | unmap/clear | `Unmap` |

Those offsets exactly match `src/VmEntryUpdate.hpp:40-45`. More importantly,
classification is not a whitelist gate: `wrapVmmUpdateEntries` calls
`prepareEntryUpdate` for every invocation and forwards the resulting source at
`src/RaphaelGPU.cpp:4213-4230`; an unknown caller is still converted when its
domain is eligible. Thus an omitted diagnostic label would not itself bypass
conversion. Full-image disassembly found only the three direct calls above.

The wrapper does not alter ordering: it synchronously calls the native function
before publishing observations (`src/RaphaelGPU.cpp:4229-4243`). The native
function emits the address/template through channel vslot `+0x330`, then tail-
calls vslot `+0x128` (`AMDRadeonX6000` `0x55cda-0x55e1a`). Frozen 187 evidence
shows converted child, leaf, and preserved SYSTEM updates at serial
`:2229-2231`, consistent with the wrapper boundary being reached.

Unknown: indirect calls through the virtual entry point and completely separate
CPU page-table writers are not excluded merely by enumerating direct `callq`
instructions. Independent test: build an offline Mach-O call-graph checker which
asserts the symbol address, all direct call sites, and all vtable references for
the pinned UUID, then disassemble every `AMDHWVMContext` map/unmap implementation
and inventory stores/copies to page-table memory. At runtime, compare a native
begin/end VM-update transaction counter against wrapper call counts; a changed
PT qword with no wrapper event discriminates a bypassing writer.

## 3. Root programming coverage is incomplete by design; no bypass is proven

The active command-stream route is `prepareVMInvalidateRequest`, not the legacy
`programAndInvalidateVM` hook. `wrapVmmPrepare` can alter the copied 0x28-byte
info before native packet preparation (`src/RaphaelGPU.cpp:4124-4144`). However,
it retains observations only when `hub==0 && vmid==2`
(`src/RaphaelGPU.cpp:4145-4151`), and `prepareInvalidateInfo` itself rejects every
VMID except 2 (`src/GpuVmDiagnostics.hpp:264-268`). This precisely explains why
the current VMID1 root `0xf40b6ff000` is neither converted nor retained; it is
already recorded in `status.md` and is not a new defect discovery.

The legacy wrappers call `repairPageTableBase` only after native
`fillVMRegisters` or `programAndInvalidateVM` returns
(`src/RaphaelGPU.cpp:4111-4121`). They therefore cannot establish that the
command-stream PTB write used the repaired value. Linux's reference ordering
emits PTB low/high and then a request/ack wait in one ring stream
(`linux-v6.12/.../gmc_v10_0.c:396-408`). This comparison supports observing the
prepared packet; it does not prove Apple's packet layout or execution.

Independent test: use the already planned guarded GDB breakpoint on
`wrapVmmPrepare` for hub 0 / VMID1 / reprogram 1. Capture original info, native
copy, prepared 0x54 bytes, and later live PTB. Add breakpoints on every write to
the VMID1 PTB low/high MMIO indices and record caller/RIP and transaction ID.
Acceptance requires the prepared root, actual PTB writes, and later live PTB to
agree; otherwise classify the earliest differing boundary. This is observational
and should precede any VMID1 repair.

## 4. SDMA update/fence/invalidation ordering is currently unknown

Linux makes the ordering requirements explicit. Its SDMA PTE/PDE packet carries
separate destination, flags, value, increment, and count
(`linux-v6.12/.../sdma_v5_2.c:1088-1116`). PDE updates are committed to a fence
stored as `vm->last_update` (`amdgpu_vm.c:816-858`). Submission-side VM flushes
optionally emit a pipeline sync, PTB programming/invalidation, and a fence
(`amdgpu_vm.c:642-745`). Direct CPU invalidation first flushes HDP, serializes the
invalidate engine, writes the request, and waits for the VMID ack
(`gmc_v10_0.c:250-333`). These are reference invariants, not proof that Apple
must use identical APIs.

Apple's `AMDHWVMM::endVMPTUpdate` calls paging-channel vslot `+0x140`; only if
that returns nonzero does it call `+0x158` and then `+0x160(0)`
(pinned binary `0x589ea-0x58a26`). The current tree does not identify these
slots with evidence or record their return/completion/fence values. The wrapper
records that native entry-update construction returned, which is earlier than
GPU execution. Candidate 187 then faults from SDMA0 with zero consumption, but
that does not distinguish a wrong root, missing entry, update not completed,
cache visibility failure, or invalidate ordering.

Independent test: statically identify the three channel slots from the concrete
channel vtable and disassemble them. Then, in one bounded observational run,
timestamp: last PTE/PDE emission, channel commit, completion/fence observation,
prepared invalidate packet, PTB register writes, invalidate request, matching
ack bit, first VMID1 submission, and first fault. Capture the written PT qword
both immediately after the completion boundary and after ack. The discriminating
outcomes are: (a) submission precedes completion/ack, an ordering defect; (b)
completion and ack precede submission but memory is stale, a visibility/address
problem; (c) memory and ordering are correct, shifting focus to root/context
programming or entry semantics. Do not infer completion from a wrapper return.

## 5. Address-domain checks retained

Linux defines Navi10 SYSTEM at bit 1 and PDE address bits 47:6
(`gmc_v10_0.c:440-470`), and its MC-to-physical helper is exactly
`mc_addr - vram_start + vram_base_offset`
(`amdgpu_gmc.c:1045-1053`). The plugin's mode-4 decision preserves SYSTEM and
unmap requests and converts only a valid non-SYSTEM source wholly within the
aperture (`src/VmEntryUpdate.hpp:47-119`). Frozen 187 samples demonstrate all
three relevant classes. I found no evidence-backed arithmetic defect in this
helper.

One evidence limitation remains: destination page-table addresses are forwarded
unchanged. The native DMA channel must already interpret those destinations in
the correct address domain. Candidate 187 proves packets were constructed, not
that every destination was reachable or that the GPU completed each write. The
ordering test above should capture destination reachability and post-fence qword
contents rather than introduce another conversion without proof.

## 6. Independent review of the proposed VMID1 rootfix

I reviewed the later worktree diff in `src/GpuVmDiagnostics.hpp`,
`src/RaphaelGPU.cpp`, and `tests/test_gpu_vm_diagnostics.cpp` independently of
the test assertions. I found no blocking defect in the functional change.

The native 24G830 encoder compares the reprogram byte to exactly one at
`prepareVMInvalidateRequest+0x31` (`0x624cd`) and skips root/PTB population when
it differs. Changing `observeInvalidateRequest` from nonzero to `==1` therefore
matches the native branch. Native `programAndInvalidateVM` calls VMM vslot
`+0x220` at `0x627e8-0x627f3`; the vtable-resolved target is the same prepare
function, so the copied input is on the actual root-programming path.

Expanding the eligible hub-0 set from VMID2 to VMIDs 1..15 is consistent with
Linux's explicit split: VMID0 is the kernel/GART address space and VMIDs 1..15
are client contexts (`gmc_v10_0.c:233-238`). Linux converts a non-SYSTEM,
non-PDE-as-PTE directory address with `amdgpu_gmc_vram_mc2pa`
(`gmc_v10_0.c:491-496`), whose arithmetic is
`mc_addr - vram_start + vram_base_offset` (`amdgpu_gmc.c:1045-1053`). The helper
continues to reject SYSTEM and unsupported attribute forms before conversion,
preserves accepted attributes, leaves already-physical/outside roots unchanged,
and edits only the private 0x28-byte stack copy. `wrapVmmPrepare` still performs
no MMIO, allocation, logging, lock, or wait. The diff does not change the
VMID2-only observation/correlation condition at `src/RaphaelGPU.cpp:4146-4151`,
so existing VMID2 correlation consumers are unaffected.

The new tests cover exact-one reprogramming, VMID0/16 exclusion, VMID1 and the
remaining client range, SYSTEM/unknown flags, already-physical/outside domains,
overflow, and preservation of the caller buffer. These are relevant boundaries,
but the loop over VMIDs 1..15 restates the policy rather than independently
proving native use of every context. The Linux VMID split and the native
VMID-indexed encoder provide the external support.

Two nonblocking evidence issues remain. First, the test comment that candidate
188 "captured the same address-domain defect" is stronger than the evidence:
188 captured an MC-form VMID1 root and a later fault; Linux supplies the policy
that motivates conversion, while hardware success is still unobserved. Second,
`observePreparedRequest` marks any structurally complete request valid and
computes `preparedRootMatches` even when `reprogram=false`
(`src/GpuVmDiagnostics.hpp:335-360`). Native prepare leaves the first 0x30 output
bytes untouched when the byte is not exactly one (`0x624cd-0x62550`). Thus a
non-reprogram VMID2 callback can publish stale/zero prepared words and a false
`prepared-match` diagnostic. `reportVmid2Runtime` logs that mismatch and may walk
`program.nativeRoot` (`src/RaphaelGPU.cpp:4945-4962`, `:4843-4855`), but the
classifier requires `reprogram` for coherent VM programs and checks
`prepared_match` only among records explicitly marked repaired
(`tools/classify-run.py:975-982`, `:1006-1018`). I found no present false abort
from this case. Add a unit fixture with a prefilled prepared buffer and
`reprogram=0`, and either mark prepared-root comparison unavailable or ensure
runtime correlation ignores that record. Severity: low diagnostic ambiguity,
not a blocker for the VMID1 rootfix.
