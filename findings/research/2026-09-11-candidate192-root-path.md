# Candidate 192 VMID11 root-path audit

## Result

Candidate 192 makes the unconverted VMID11 root the leading fault cause.  Exact
KDK code identifies an independent MES `MAP_PROCESS` root producer which the
current `prepareVMInvalidateRequest` repair cannot affect, and resolves its
native conditional address adjustment.  Frozen runtime fields explain why the
native helper leaves the MC root unchanged.  Mode 5 now applies a narrowly
guarded post-fill correction and retains bounded evidence; hardware effect is
unobserved.

No hardware action was performed for this audit.

## Frozen evidence

The complete CR2 snapshot in
`/home/bogdan/macos-vm/run/metal-026-192/events.jsonl` records, at sequence 289,
VMID 11 fault status `0xb0093b`, VA `0x400300000`, and a stable worker-time root
`0xf40b709000`.  The context range contains the VA.  The relative walk uses the
BAR-visible alias `0x84b709000`, finds a valid level-1 entry
`0x200000084b763001`, then finds an invalid level-0 entry at index 768.  The
absolute walk instead finds an invalid level-1 entry at index 64.

This comparison is meaningful only if the GPU consumes the physical-aperture
root.  The conversion established elsewhere in the same capture is
`0xf40b709000 -> 0x84b709000`.  Sequence 105 independently shows
`0x84b709000` as the address in a valid VMID2 leaf entry, so it is a real
physical page in the captured tables rather than an address invented by the
offline walker.  The two CPU walks show what the physical root page contains;
they do not prove the GPU reached it.  Consequently the invalid relative child
is not yet evidence that child repair is the first failure.

Status `0xb0093b` differs from candidate 191's `0xb0093a` in the retained
additional-status bit, while preserving VMID 11, CID 4/CPF, walker error 5,
permission bits 3, mapping error, and read/non-atomic classification.  It does
not change the root-path conclusion.

## What the existing repair proves and omits

`src/RaphaelGPU.cpp` `wrapVmmPrepare` calls
`RaphaelVm::prepareInvalidateInfo` on every observed request and passes the
copied request to the native virtual method.  The helper in
`src/GpuVmDiagnostics.hpp` accepts hub 0 VMIDs 1 through 15, requires byte
`info+0x24` to equal one, rejects SYSTEM/unknown attributes, and converts an MC
aperture root to the physical aperture.  However, the recorder deliberately
retains only VMID2 observations.  Candidate 192 consequently proves one VMID2
repair and contains no record establishing whether VMID11 entered this method,
was rejected, or was subsequently overwritten.

The pinned KDK disassembly gives two useful exact constraints:

* `AMDGFX10VMM::prepareVMInvalidateRequest` at `x6000.asm:6249c` compares
  `[info+0x24]` to **exactly** 1 at `0x624cd`.  When equal, it copies the entire
  input root qword from `info+0x18` into prepared words at `0x624ed..0x624f8`.
  It does not mask PDE flags first.  Therefore the wrapper's exact-one predicate
  matches native behavior.  An incoming root with upper encoded attributes
  could be rejected by the helper, but there is no captured VMID11 input that
  demonstrates this; it remains a hypothesis.
* `AMDGFX10SDMAChannel::writeVMProgramPacket` at `0x67410` is not an
  established bypass.  It resolves the VMM object through vslot `+0x2e8` and
  calls vslot `+0x220` with the same `AMD_VM_INVALIDATE_INFO`, alternate=1, at
  `0x67473..0x67484`, before patching its packet template.  This is consistent
  with the same prepare virtual method and should not be named as the cause
  without a vtable/runtime correlation.

## Exact independent programming path

`AMDGFX10HIQHWChannel::fillMapProcessPacket` at `x6000.asm:8edce` builds a
64-byte packet with header `0xc00ea100` (`PACKET3_MAP_PROCESS`, opcode A1).
It preserves the caller's first 64-bit argument in `r12`, obtains a hardware
helper through vslot `+0x2d8`, passes that unmodified argument to the returned
object's vslot `+0x200`, then writes the 64-bit result directly to packet offset
`+0x8` (`0x8eddc`, `0x8ee35..0x8ee51`).  The concrete Navi23 object resolves
that slot to `AMDHWMemory::adjustVRAMAddress(unsigned long long)` at `0x53b78`.
That method returns its argument unchanged unless it falls in the configured
interval beginning at `self+0x60`; inside that interval it returns
`argument - self+0x60`.  The interval length is
`*(uint32_t *)(self+0x1b8) * *(uint64_t *)(self+0x40)`.  `initVRAMInfo` at
`0x527a4` obtains a provider structure and initializes `self+0x60` as provider
field `+0x00` minus field `+0x18` (`0x52800..0x52823`); it initializes the size
factor at `+0x1b8` to one and may replace it from a hardware getter
(`0x5272d..0x52755`).  Candidate-192 serial line 1853 supplies provider values
`0xf400000000` and `0x840000000`, hence `self+0x60 = 0xebc0000000`, plus sizes
`0x20000000` and `0x10000000`.  Thus the earlier assumption that `self+0x60`
was the MC base was false.  The frozen `0xf40b709000` lies outside the ordinary
native adjustment interval and is returned unchanged.  The A1 builder neither constructs
`AMD_VM_INVALIDATE_INFO` nor calls `prepareVMInvalidateRequest`.
The upstream Linux GFX9 KFD packet manager independently identifies this exact
A1 field: `pm_create_map_process` assigns `qpd->page_table_base` to the
MAP_PROCESS packet's page-table-base low/high words.  Its GPUVM setup obtains
that value from `amdgpu_gmc_pd_addr(vm->root.bo)`, i.e. the hardware page-
directory address, rather than from an invalidate request.  See Linux v6.12
`drivers/gpu/drm/amd/amdkfd/kfd_packet_manager_v9.c` lines 32-84 and
`drivers/gpu/drm/amd/amdgpu/amdgpu_amdkfd_gpuvm.c` around line 487.  Linux is
corroboration for packet semantics; the pinned Apple instructions above remain
the evidence for the actual guest path.

The adjacent `fillMapProcessVMPacket` at `0x8ee98` is a different A6 packet. It
gets values through VMM vslots `+0x1a0/+0x1a8`, page-shifts them, and writes
packet offsets `+0x18/+0x1c` and `+0x10/+0x14`.  On this disassembly alone those
fields should be treated as VM aperture bounds, not mislabeled as the process
root.  Capturing A6 is useful context but A1 offset `+0x8` is the critical root
candidate.

The run-list producer calls `fillMapProcessPacket` at `0x9029b`, immediately
calls `fillMapProcessVMPacket` at `0x902aa`, then appends MAP_QUEUES packets.
`AMDGFX10UserQueueManager::onVMIDUpdate` at `0x90918` rebuilds and resubmits the
run list when the VMID changes.  This is direct evidence of a process-VM root
programming route outside the current invalidate wrapper.  It is a plausible
source of the VMID11 live PTB, although the frozen capture does not prove the
A1 packet contained an encoding of `0xf40b709000` or identify which assigned
VMID consumed it.

This boundary was already called out in the pre-186 Astra review
(`findings/research/astra-reviews/2026-09-10-post186-180456/report-astra-before186.md`,
lines 185-200): candidate 181 associated probe PASID 1 / VMID9 with an MC-valued
VMPD and UQ/MAP_PROCESS diagnostics, and the review warned that the invalidate
callback did not necessarily own that separate root path.  Generalizing the
helper's VMID gate from VMID2 to VMIDs 1..15 removed one eligibility exclusion,
but did not establish call-path coverage.  Candidate 192 now exposes that same
methodology gap directly: eligibility for every client VMID is irrelevant when
the UQ producer never calls the helper.

`AMDGFX10Hardware::setVMRegisters` at `0x74320` should not be used as the next
root-writer hypothesis: its native body only computes/caches and returns a
pointer; it does not itself emit a PTB write.

## Implemented offline candidate

Mode 5 retains all mode-4 bulk entry conversion and adds a native-first wrapper
for `fillMapProcessPacket`.  It requires the exact A1 header, native return
`packet+0x40`, published Raphael aperture and explicit mode 5.  It converts only
packet qword `+8` when its address is in the MC aperture and attributes are the
already accepted 0, 1 or 5 forms.  SYSTEM, unknown flags, physical, offset,
outside, malformed and overflow cases pass through.  A bounded lock-free record
contains input/native/final roots, supplied PASID, header, return validity,
repair result and reason; the worker publishes it and capped drop summaries.

The static and frozen evidence justify correcting a raw MC value in this
hardware PTB field without requiring a VMID-specific invalidate record.  They
do not prove A1 wrote candidate 192's faulting VMID11 or that this is the final
fault cause.  The next capture must show route installation and the bounded A1
record; a physical worker-time root would establish advancement.  A remaining
MC root would imply another writer or later overwrite.

Offline validation passed the ASan/UBSan VM fixture, including flags 0/1/5,
cross-check against invalidate arithmetic, both aperture edges, overflow,
SYSTEM/high flags, physical/offset/outside roots, malformed inputs and nonzero
byte sentinels outside `+8`.  Exact-KDK preflight passed the constant, actual
17-byte prologue, route and callback order/safety checks.  A scratch-only
cross-build produced an x86_64 Mach-O kext bundle with SHA-256
`ea722df7aa486ecc63a2526e26010c8a7e352c7a7d7c01bdde74f3bce740163f`.
