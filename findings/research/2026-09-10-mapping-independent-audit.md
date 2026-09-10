# Independent mapping and ABI audit (2026-09-10)

## Scope and evidence

The initial audit was offline and read-only except for this report. After its defect
was independently confirmed, the coordinator separately authorized the bounded
implementation recorded below. No VM, GPU, device, `sudo`, reset, media, driver
build, or staging operation was performed. I audited
`src/GpuVmDiagnostics.hpp`, `src/VmEntryUpdate.hpp`, the mapping wrappers in
`src/RaphaelGPU.cpp`, their C++ fixtures, the pinned 24G830 X6000 disassembly at
`/home/bogdan/macos-vm/re/x6000.asm`, its symbol map, and frozen candidate 181--188
serial evidence. Comments and tests were treated as claims, not authorities.

## Result

The native wrapper ABIs and the decoded invalidate-info layout are consistent with
the exact binary. The active root policy is nevertheless wrong for the observed
failure: it repairs and records only VMID2, while the hardware fault repeatedly
occurs in VMID1. Candidate 188 consequently converted the addresses stored below
roots but left the faulting VMID1 root itself in the framebuffer MC domain. The
current CPU walker silently aliases that root into the physical aperture, so its
later zero leaf is not evidence that the GPU reached that leaf.

The entry-update wrapper also has no hub, VMID, or owning-context input. Mode 4
therefore rewrites every qualifying non-SYSTEM framebuffer source handled by every
`AMDHWVMContext` instance. That broad behavior may be necessary for all client
contexts, but it cannot establish that a particular update belongs to VMID1 or
VMID2, and it makes a per-VMID repair policy impossible at this call boundary.

## Proven defect: the faulting VMID is excluded

`src/GpuVmDiagnostics.hpp:249-307` parses an invalidate request correctly, then
`src/GpuVmDiagnostics.hpp:266` returns `WrongVmid` unless `vmid == 2`. The wrapper
still invokes native code, but with the original unmodified root. Independently,
`src/RaphaelGPU.cpp:4145-4150` retains prepared requests only when hub is zero and
VMID is 2. Thus VMID1 is both unmodified and unobserved at the only routed native
boundary that carries hub, VMID, root, and reprogram state together.

Candidate 188 frozen evidence at
`/home/bogdan/macos-vm/run/metal-021-188-continuation-output/serial.txt:2299`
reports VMID1, fault VA `0x400580000`, live root `0xf40b6ff000`, control `0x3b`,
and status `0x101b3a`. In the same run, lines 2253--2255 show VMID2 root
`0xf40b6f3000` transformed to and programmed as `0x84b6f3000`. Lines 2268--2270
show 158 mode-4 conversions below roots, including child table sources such as
`0xf40b6f4000 -> 0x84b6f4000`. These facts form a direct counterexample to the
implemented policy: the known translation rule is applied to VMID2 and subordinate
entries, but not to the root of the context that faults.

This is not an inference from a decoded CPU walk. The live VMID1 PTB register itself
contains the MC-form root. With cached aperture registers base `0xf400`, top
`0xf41f`, offset `0x840`, the same arithmetic already accepted for VMID2 maps it to
`0x84b6ff000`. Whether native prepare receives that VMID1 request, and whether the
GPU succeeds after conversion, still require capture; the existing gate guarantees
that current code will never perform that conversion.

The tests preserve the defect. `tests/test_gpu_vm_diagnostics.cpp:128-184`
explicitly expects VMIDs 0, 3, and 16 to be rejected and describes VMID2 as the
only eligible VMID. It has no positive VMID1 root case. Passing this fixture proves
conformance to the historical experiment, not conformance to the current hardware
failure.

## Native ABI and offsets verified

The following wrapper declarations match the x86-64 C++ ABI and pinned binary:

* `prepareVMInvalidateRequest` at X6000 `0x6249c` receives `self` in RDI,
  prepared output in RSI, info in RDX, and the Boolean alternate selector in ECX.
  It reads hub at info `+0`, VMID at `+4`, range at `+8/+0x10`, root at `+0x18`,
  flags at `+0x20`, and reprogram at `+0x24`. When reprogram is one it copies the
  complete root low/high dwords into prepared output `+4/+0xc`. Its last write is
  at `+0x50`, so the wrapper's 0x54-byte observation is sufficient.
* `getPDEValue` at `0x629c6` has `(self, uint32 level, uint64 address)` and masks
  address with `0x0000ffffffffffc0` before adding VALID and level attributes.
* `getPTEValue` at `0x62a14` has `(self, uint32 level, uint64 address,
  uint32 flags, uint32 fragment)`. Its flags-to-SYSTEM derivation agrees with the
  wrapper: input bit 3 produces output bit 1. It masks the address to bits 47:12.
* `updateContiguousPTEsWithDMAUsingAddr` at `0x55cda` receives destination in RSI,
  count in RDX, source in RCX, template in R8, and increment in R9. Call sites
  returning at `0x559dc`, `0x55a72`, and `0x561f6` agree with the leaf, child, and
  unmap labels in `src/VmEntryUpdate.hpp:40-45`. `RaphaelGPU.cpp:4213-4230`
  forwards those six arguments in the correct order and modifies only source.

No ABI mismatch was found in these four wrappers. The guarded prologue checks are
useful build-identity defenses, although they verify only entry bytes and cannot
validate downstream semantic assumptions.

Two lower-priority semantic mismatches remain in the invalidate decoder. At
`0x624cd`, native code compares byte `info[0x24]` to exactly 1 and skips all root
programming when it is any other value. `observeInvalidateRequest` at
`src/GpuVmDiagnostics.hpp:323` instead treats every nonzero byte as true, and
`prepareInvalidateInfo` can consequently report and attempt a repair for value 2
although native will ignore the root. Tests cover only zero and one. Add values 2
and 255 and require `NotReprogrammed`; this is a proven decoder mismatch, though
no frozen run shows a noncanonical value.

Also, fields `info+8` and `info+0x10` are the invalidation range consumed by
`encodeInvalidationRange` at `0x62554`; when reprogramming, native obtains the
programmed context START and END from `self+0xaa0` and `self+0xaa8` at
`0x6250b-0x6254d`. The `InvalidateRequest.start/end` names and logs can therefore
be read incorrectly as the context bounds. Rename them to `invalidateStart` and
`invalidateEnd`, or document the distinction and keep reporting the live context
registers separately. This is diagnostic terminology, not evidence of a wrong
native call.

## Ungated global conversion and attribution gap

`RaphaelGPU.cpp:4220-4228` activates mode 4 solely from a global boot mode, global
Raphael marker, and global framebuffer snapshot. The routed function's ABI contains
no VMID or hub. The `self` object is available, but the wrapper neither identifies
it nor correlates it with a prepared request. As a result:

1. every valid, non-SYSTEM source in the framebuffer MC aperture is converted,
   regardless of the target VM context;
2. samples label only the native caller offset, not context, VMID, or hub;
3. 158 conversions in candidate 188 do not prove that any converted entry is on
   the VMID1 faulting path; and
4. extending the root gate without correlating `self` risks repairing roots for a
   different hub/context family on future calls.

The tests use a synthetic lambda (`tests/test_vm_entry_update.cpp:101-139`) and
prove argument order plus arithmetic, but contain no two-context counterexample.
They cannot detect cross-context rewriting or establish the Apple object-to-VMID
relationship.

This is an evidence/containment defect rather than proof that one of the observed
mode-4 rewrites corrupted a mapping. Frozen runs show converted and SYSTEM calls,
not the owning `AMDHWVMContext` or its VMID.

## Walker limitations that affect conclusions

`physicalTableAddress` at `src/GpuVmDiagnostics.hpp:358-367` intentionally accepts
either physical-aperture or MC-aperture table addresses and maps the latter into the
CPU-visible physical carveout. That is appropriate for offline inspection, but it
means a successful CPU read through `0x84b6ff000` says nothing about whether GFXHUB
can dereference the programmed `0xf40b6ff000`. Candidate 188's raw zero at leaf
index 1408 therefore cannot locate the first GPU failure. The root can fail before
the PDE read.

The control geometry for the observed `0x3b` is internally consistent: depth is
one and block-size encoding seven gives a 16-bit leaf index; relative VA
`0x580000` selects root index zero and leaf index 1408. No geometry error was found
for that case. The fixture coverage of deeper synthetic layouts does not validate
hardware reads for those layouts.

`decodePageTableEntry` reports PTE/PDE flag meanings from the expected GFX10 format,
but the root validator accepts only root attributes 0, 1, or 5. This is conservative
and fits captured VMID2 roots; there is not yet a captured native VMID1 prepare
record proving the VMID1 attribute form. Do not weaken that flag check speculatively.

## Ordering and concurrency review

Framebuffer fields are stored before `cachedFbPublished` with a release store at
`RaphaelGPU.cpp:5932-5938`; readers acquire the published flag before relaxed field
loads. This one-time publication pattern is ordered correctly. The append-only
observation buffer release-publishes each completed slot, and reporting cursors do
not advance past a reserved-but-not-ready slot, so I found no lost-slot race there.

There is still a temporal evidence gap. Entry updates can occur before any prepared
request and are globally rewritten; prepared observations are independently stored
after the native call; and no common event sequence ties update, root program,
invalidation, and later fault for VMID1. Therefore existing logs do not prove that
the observed child/PTE updates completed before the invalidation associated with
the faulting context. Native code probably supplies its own ordering, but the
instrumentation does not demonstrate it.

## Discriminating tests before another hardware cycle

1. At the existing GDB `wrapVmmPrepare` boundary, capture entry and return for
   hub 0 / VMID1 / reprogram 1: original 0x28-byte info, native info, prepared
   root words, `self`, thread, and return order. This directly tests whether the
   live `0xf40b6ff000` root arrived through the routed method and whether a local
   conversion would become `0x84b6ff000` in prepared words.
2. Add an offline fixture with otherwise identical VMID1 and VMID2 requests. The
   intended policy must be stated explicitly: if both client VMIDs use framebuffer
   roots, both should convert under the same hub/reprogram/flag/aperture checks.
   Retain negative hub, SYSTEM, unknown-flag, already-physical, and non-reprogram
   cases.
3. Derive a read-only `AMDHWVMContext self -> owning VMM/context/VMID` relationship
   from exact disassembly or debugger memory before adding a per-context mode-4
   gate. Then test two distinct synthetic self identities so a VMID1 update cannot
   be attributed to VMID2.
4. Capture one update-to-invalidate sequence for the same identified context:
   update call arguments and return, prepare entry/return, programmed PTB, and
   invalidate request/ack order. This distinguishes a bad root from a stale or
   unordered page-table image.
5. For the current fault, compare GPU-visible behavior with CPU aliasing kept
   conceptually separate. Acceptance is progress beyond the current faulting
   boundary or a changed walker-error/fault address after an authenticated VMID1
   root conversion; a CPU walk alone is not acceptance.

## Recommended implementation direction

First make the prepare observer retain bounded hub-0 VMID1 records even while
mutation remains disabled. Use the authenticated native capture to determine the
VMID1 flag form and prove that its root follows the same MC-to-physical rule. Then
extend a shared client-root eligibility predicate to the demonstrated VMID set,
rather than replacing `vmid == 2` with an unconstrained condition. Keep SYSTEM,
attribute, reprogram, marker, aperture, and overflow gates. Separately add context
identity to mode-4 observations before treating aggregate conversions as evidence
about the faulting VMID.

Independent Linux review subsequently confirmed hub 0 VMIDs 1 through 15 as the
client-context set, with VMID0 on its separate legacy GART path. The coordinator
selected one shared root policy for every enabled root-repair mode because the
root address domain is a property of the client context, while modes 2--4 differ
only in subordinate-entry experiments. This deliberately changes the historical
modes' client-root eligibility; comparisons must account for it. The implementation
was driven by a failing fixture for the captured case: VMID1 root `0xf40b6ff000`, base `0xf400`,
top `0xf41f`, offset `0x840`, expected native root `0x84b6ff000`; plus VMID0 and
wrong-hub negative cases. The routed prepare path is used by direct programming as
well: the exact binary reaches vtable slot `+0x220` at `0x627f3`, so the fix should
stay at this common boundary rather than patching one caller.

The red run failed specifically at the candidate-188 VMID1 conversion assertion.
After the minimal helper change, the focused C++14 UBSAN and C++17 ASAN+UBSAN runs
passed, followed by all nine C++ UBSAN CI fixtures. The implementation also changed
the decoder predicate from nonzero to exactly one and added a byte-value-two
regression. `vmid2Programs` and its correlation consumers remain intentionally
VMID2-only; the separate VMID1 observation limitation above is unresolved.
