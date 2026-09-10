# Astra adversarial review after candidate 182

Date: 2026-09-10. Reviewer: gpt-6-astra, xhigh. Source reviewed:
`70b7f127ca0ddc6c8404eff48897001368d0acca`.

**The page-entry correction is applied at the wrong data-flow boundary.** Exact
24G830 callers deliberately pass zero to `getPDEValue` and `getPTEValue`, obtain
attribute templates, then supply the real address separately to an SDMA packet
builder. Candidate 182's earlier gate cannot correct those separately supplied
addresses. This mechanism is now verified in the KDK, not merely inferred from
zero samples. It explains why the chosen correction makes no conversions; it
does not by itself prove every observed GPU fault has this sole cause.

Full checked Metal work and desktop acceleration remain unproved. Keep the
unresolved SDMA/VM fault streak at **four actual cycles, 179–182**. Offline
findings do not reset it. This report is assessment input, not hardware admission.

## Scope and evidence quality

I read `status.md` first. This review used repository files, frozen captures,
local KDK bytes/disassembly and cached Linux source. I made no VM launch, device
access, reset, sudo invocation, build, staging change or implementation edit.
Only this report was written. No fresh full unit-test result is claimed.

I independently verified all **13** candidate-182 raw-file hashes against
`findings/experiments/metal-015-182/raw-sha256.txt`, and checked each repository
copy against its original in `/home/bogdan/macos-vm/run/metal-015-182/`.
The old report's archived SHA-256 remains
`5314d914023ea152ee54313f8bd3ec4bb80ba33ff8d1b6b87f70ef13b5500d3a`.

The reviewed X6000 executable is
`/home/bogdan/macos-vm/kdk/x/System/Library/Extensions/AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000`,
SHA-256 `2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e`.
Offsets below are virtual offsets in that exact binary. I resolved vtable entries
from Mach-O segment mappings and matched symbol names in
`/home/bogdan/macos-vm/re/x6000.nm`; instruction listings are in adjacent
`x6000.asm`.

Candidate 181's stopped-device root entry
`0x200000f40b6f4001` is recorded in its
[notes](findings/experiments/metal-014-181/notes.md). No standalone raw BAR dump
was supplied or located, and the coordinator confirmed not personally inspecting
that dump. Treat it as an inherited documented observation, **not a binary dump
independently reverified by this review**. The KDK mechanism and candidate-182
zero-address samples do not depend on upgrading that evidence.

## Ranked causes and limits

| Priority | Finding | Confidence and consequence |
|---|---|---|
| 1 | Real PDE/PTE addresses bypass the conversion hooks | Confirmed native call chain; the current functional intervention is ineffective on this path. Correct the entry-value operand at its real consumer. |
| 2 | Probe/user-queue page-directory roots have a separate unconverted path | Candidate 181's raw diagnostics identify probe VMID 9 and an MC-valued CTX9 root. VMID2-only root repair cannot establish full Metal sufficiency. Keep this as the next measured boundary, without bundling a broad VMID rewrite into the immediate experiment. |
| 3 | Live capture handling aborts on an END-bearing damaged replay that a later permitted replay can replace | Reproduced from frozen prefixes. The abort is fail-closed under current policy, but final-file parser tests do not establish a usable live experiment. |
| 4 | Correlation requirements suppress the promised walk | Source requires same-thread preparation/submission and other predicates; current records hide which failed. Missing walk is a measurement limitation, not proof of a new mapping regression. |
| 5 | Diagnostic geometry and remaining SDMA/VM attributes are not independently qualified | Relative indexing matches the documented native layout, but a fixture cannot prove hardware indexing. Translation, invalidation, synchronization and user-queue programming can remain later blockers. |

The original identity-gate timing explanation is insufficient and no longer the
leading cause. The observed wrappers have valid routes, correct argument register
placement, and zero inactive calls. There is no evidence here for an ABI shift
that accidentally reads the wrong argument; the callers actually zero that
argument. Exact prologues prove routing compatibility, not that the selected
argument carries the value needing repair.

## 1. Exact native producer-to-packet chain

`AMDGFX10VMM` vtable `0x176f78`, address point `+0x10`:

| Slot | Resolved target |
|---|---|
| `+0x1d8` | `getPDEValue` at `0x629c6` |
| `+0x1e0` | `getPTEValue` at `0x62a14` |

The implemented signatures in [RaphaelGPU.cpp](src/RaphaelGPU.cpp) correctly
place `this` in RDI, level in ESI, address in RDX; PTE flags use ECX and fragment
uses R8D. Native PDE encoding masks RDX at `0x629f8`. Native PTE encoding masks
RDX at `0x62a48`. This validates the ABI but also makes the following caller
instructions decisive.

### Leaf PTE path

Inside `AMDHWVMContext::mapVMPTE`, starting at `0x5560c`:

```text
0x55999  RDI = context+0x18 (VMM)
0x5599d  ECX = context+0x108 (VmMapFlags)
0x559ab  xor edx, edx
0x559ad  call VMM vslot +0x1e0           # getPTEValue(level, 0, flags, fragment)
0x559be  RSI += parent-table storage address
0x559c4  RCX = context+0xf8             # real page address, separate operand
0x559ce  R8 = RAX                      # returned attribute template
0x559d1  R9 = per-entry address increment
0x559d7  call updateContiguousPTEsWithDMAUsingAddr
```

Earlier, `0x557ad` obtains a backing segment's address. For non-SYSTEM memory,
`0x557bd..0x557e3` passes it through memory slot `+0x200`, then stores the result
at context `+0xf8`. Thus nonzero backing addresses exist without ever entering
`getPTEValue`'s RDX parameter.

### Child PDE path

```text
0x55a1e  R12 = child allocation's +0x20 address
0x55a39  call memory vslot +0x200
0x55a3f  R12 = returned address
0x55a4d  xor edx, edx
0x55a4f  call VMM vslot +0x1d8           # getPDEValue(level, 0)
0x55a55  EDX = 1                       # one entry
0x55a5d  RSI = destination parent entry
0x55a60  RCX = R12                     # real child address
0x55a67  R8 = RAX                      # returned attribute template
0x55a6a  R9 = 0                        # no increment for one child
0x55a6d  call updateContiguousPTEsWithDMAUsingAddr
```

This is the exact counterexample missing from the current tests: converting
zero before template creation leaves the separately supplied child unchanged.
The recorded candidate-181 qword is consistent with combining template
`0x2000000000000001` and child `0xf40b6f4000`; the physical-form child would be
`0x84b6f4000`, producing `0x200000084b6f4001` with the same attributes.
That consistency is not a new hardware read.

### What the existing native address adjustment actually does

`AMDHWMemory` vtable `0x172080 + 0x10 + 0x200` resolves to
`adjustVRAMAddress` at `0x53b78`. Its complete arithmetic is:

```text
base = memory+0x60
if base <= address < base + (memory+0x1b8) * (memory+0x40):
    address -= base
return address
```

It is conditional base subtraction; it does not implement Raphael's
`address - mcBase + physicalBase`. Its current object fields were not captured
here. Do not globally replace this helper merely because of its name: its other
callers and their expected address domains require separate proof.

### The final SDMA packet retains the real address

`updateContiguousPTEsWithDMAUsingAddr` begins at `0x55cda`. Its five numeric
arguments are destination, entry count, real entry-value address, template,
and increment. It saves RCX in R15 at `0x55cf3`, doubles the entry count at
`0x55d14`, and forwards the real address in R9 at `0x55d9e`/`0x55de6` to channel
vslot `+0x330`. R8 carries the template. The destination is independent.

The SDMA channel table `0x178c28 + 0x10 + 0x330` resolves to
`writeWritePTEPDECommand` at `0x6774a`. It emits:

| Packet byte offset | Operand |
|---|---|
| `+0x00` | Opcode `0x0c` |
| `+0x04/+0x08` | Destination address from RDX |
| `+0x0c/+0x10` | Template from R8 |
| `+0x14/+0x18` | Real entry-value address from R9 |
| `+0x1c/+0x20` | Increment from the stack argument |
| `+0x24` | Entry count minus one, derived from the dword count |

No MC-to-physical conversion occurs in this encoder. Cached Linux
`sdma_v5_2.c:1110` uses the same distinct destination/flags/value/increment
layout. `gmc_v10_0.c:454` converts non-SYSTEM directory addresses, and
`amdgpu_gmc.c:1199` defines the MC-to-physical arithmetic. These files are under
`/home/bogdan/macos-vm/run/research/metal-integration-20260909/cache/linux-stable-v7.2.3/drivers/gpu/drm/amd/amdgpu/`.
They support the domain distinction; they do not prove Apple's entire remaining
VM configuration works on Raphael.

**Correction boundary:** a reviewed wrapper at the contiguous-update function
can convert the real entry-value address while preserving the destination,
template, count and increment. The final packet emitter is another possible
observation boundary; do not implement both corrections. Check exact ABI and
displaced instructions for the selected route before using it.

At this boundary, SYSTEM is **encoded template bit 1**, not source
`VmMapFlags` bit 3. Preserve SYSTEM entries even if their numeric address overlaps
the MC interval. Preserve invalid/unmap operations, unrelated and already physical
addresses. Prove the whole arithmetic progression
`address + (count - 1) * increment` stays within the eligible aperture without
overflow before converting a batch; checking its first address alone is
insufficient. Count units differ between the two candidate boundaries. Never
translate the packet destination, submitted IB GPUVA, or flags merely because
another operand needs translation. Keep callback work bounded and free of MMIO,
allocation, waits and formatted logging.

## 2. A separate root path remains downstream

Candidate-181 raw [serial](findings/experiments/metal-014-181/serial.txt) lines
7339 and 9230 identify `Proc 387 probe, pasid 1, VMID 9`, VMPD
`0xf40b6f3000`. The register dump at lines 7782/9492 contains
`0x1679 = 0x0b6f3000`, `0x167a = 0xf4`: the CTX9 PTB low/high pair under the
established register stride. UQ/MAP_PROCESS diagnostics nearby also retain the
MC-valued root. These are native raw diagnostic records, not independently
checksummed CR2 register samples, so retain that provenance.

`prepareInvalidateInfo` in [GpuVmDiagnostics.hpp](src/GpuVmDiagnostics.hpp)
explicitly refuses VMIDs other than 2. A successful corrected paging path would
therefore not establish that the probe's user-queue root is fixed. The immediate
experiment should resolve the entry-value boundary first; if it advances, trace
the actual user-queue/MAP_PROCESS root producer and measure the active probe
VMID before another narrowly defined change. Do not infer that the SDMA prepare
callback necessarily owns that separate programming path.

## 3. Capture and experiment methodology

I replayed the actual candidate-182 capture prefixes through the current
`parse_serial(..., critical_replay_tolerance='terminal-prefix')`:

| Prefix ending at END record | Result |
|---|---|
| Physical line 3736, snapshot 0 | Accepted; 179 records |
| Line 7737, snapshot 1 | Accepted; 191 records |
| Line 11909, snapshot 2 | `CR2 snapshot has a missing chunk`, `definitive=True` |
| Line 13600, snapshot 3 | Accepted; 205 records |

Final snapshot 3 has 20,677 bytes, 589 chunks, CRC32 `0xd45cc729`, FNV1a64
`0x636a87f859b623b4`, zero dropped/truncated records. There are 69 earlier
corrupt lines. I reproduced acceptance with **open-attempt tolerance disabled**;
final acceptance is available under the functional terminal-prefix policy too.
This does not change the frozen `INVALID` verdict or retrospectively authorize
the probe.

`experiment.py:2411` aborts as soon as the third row is observed. The later clean
snapshot was unavailable at that decision, so aborting was consistent with its
current fail-closed rule. Nevertheless, calling this category irrecoverably
"definitive" is inconsistent with the replay protocol's ability to replace a
damaged attempt. Testing only final captures misses this live transition. Guest
crash diagnostics still interleave character-by-character with CR2 transport;
checksums detect damage but do not prevent that transport failure.

A narrowly reviewed host-only improvement can treat **only recoverable missing
chunks under the pinned terminal-prefix live policy** as pending while the
existing exposure deadline continues. Pending must provide no admissible events,
no probe launch, no fallback to a stale snapshot, and no additional exposure
budget. Only a subsequent snapshot accepted by the unchanged parser can restore
readiness. Valid-data conflicts, foreign/stale identity, changed prefixes,
aggregate checksum errors, reported overflow and ABORT remain fatal or
non-admissible. If sufficient evidence never arrives, finalization remains
incomplete. This bounded wait extends time under incomplete transport evidence,
so its exact control flow needs coordinator and implementation review before
hardware. It is not a broad tolerance relaxation.

Prefer keeping the receipt-bound `critical-replay.py` and other recovery helpers
unchanged for this control-flow repair. Altering their hashes affects whether the
existing receipt can be consumed; never rewrite a frozen receipt to compensate.

There is also an independent readiness problem. Running
`classify_probe_readiness` on snapshots 0, 1 and final 3 returns
`vmid2_entry_conversion_no_pde`. Native/background VM activity makes
`require_workload_outcomes` true, and the classifier then demands a converted PDE
at hooks that receive zero. Removing the capture abort alone would **not** have
made the current run probe-ready. Replace this ineffective evidence requirement
with the new real-address observation; do not merely relabel zero conversions a
success.

The final verdict combines two different facts: `earliest_failure` comes from a
final reclassification, while `verdict=INVALID` and `error` are overwritten by the
stored live abort at `experiment.py:2495..2504`. Record termination reason and
functional boundary separately so reviewers cannot mistake their ordering.

## 4. Correlation, walker and regression claims

`RaphaelGPU.cpp:5218..5246` requires matching thread tokens, temporal ordering,
VMID/range predicates, and a retained preparation. Its fallback still requires
the same thread. Candidate 182 has a complete VMID2 preparation covering
`0..0xffffffffffffffff`, followed by three valid SDMA submissions for
`0x400100000`, all reported with sequence zero and "no in-range program".
The observed range fits. The message collapses other possible rejection causes;
prepare thread tokens and submission event order are not emitted, so these
records cannot establish which predicate failed.

Before relying on this as acceptance, test the production matcher with native
initialization ordering, cross-thread preparation/submission, replacement of a
VMID context, and bounded-buffer saturation. Emit the rejected predicate and
minimal immutable identity/order fields. Do not pair events merely by nearest
sequence or matching VMID; that would manufacture causal evidence. A worker-side
snapshot of an identified live context can be useful descriptive evidence even
without submission correlation, but must be labelled accordingly.

The current walker subtracts context start. Its fixture deliberately places an
entry where that subtraction looks. This tests arithmetic and bounds, not the
hardware's interpretation. With control `0x3b`, start `0x400000000`, and the
first submitted IB, the absolute and relative views choose root entries 64 and
0 respectively. Preserve that uncertainty; label the current layout as an
inference until independently established. Zero-attribute native roots are a
separate, directly observed accepted root form. A CPU diagnostic that translates
an MC child to make it readable does not prove the GPU can follow that raw child.

| Checkpoint | Candidate 182 evidence | Regression limit |
|---|---|---|
| Startup, lease, VMM allocators, KIQ | Repeated in complete CR2 records | Retained baseline progress |
| VMID2 root | Prepared/live `0x84b6f3000`, matches | Root repair repeated |
| Entry conversion | PDE `0/0/183/0/0`; PTE `0/0/23/2410/0`; inactive `0/0` | Intervention ineffective; first eight samples per kind are zero, not proof that every address in every native path is zero |
| GPU fault | Prepared-phase `0x2009bb` at `0x400200000` | VM/SDMA failure persists; exact fault/IB causality not captured |
| Submission | Final native/background summary `43/43/0` | Not 43 probe submissions or completed buffers; do not compare it as inferior to 181's count 18 |
| Checked probe and desktop | No identity-bound probe result | Missing result under aborted exposure; no acceleration pass and no clean probe regression comparison |
| Cleanup | Receipt `13c92dcc904742ce8fd4de28a3fb1988`, recovered and authorizing | One successful forced-close cleanup; 181's failed graphics retirement remains a repeatability counterexample |

The outer recovery receipt is schema **6**, using the schema-3 lifetime/lease
recovery path. Its recovery-interval `kernel_messages` is empty. The full run's
`host-kernel-messages.json` contains **32** Docker/UFW messages, with no observed
GPU/IOMMU fault in that list. These are different intervals. Neither establishes
universal freedom from host crashes.

## 5. Tests and documentation that must change before the next cycle

The recorded 522 Python tests and 14 C++ sanitizer fixtures test substantial
software properties, but did not exercise the native composition that defeated
the correction. Add a small number of evidence-driven production-path tests:

1. **Template plus separate address.** Reproduce both exact KDK call shapes:
   zero address to getPDE/getPTE, nonzero source to the contiguous updater, then
   encoded SDMA packet. The current implementation must demonstrably retain the
   MC entry value; the selected correction must change only the appropriate value
   words. Include SYSTEM, unmap, physical/outside domains, aperture endpoints,
   multi-entry span overflow, and the two count units.
2. **Readiness using the actual 182 sequence.** Native VM activity precedes the
   user probe. Good startup cannot require a probe result before launch; actual
   faults and invalid gates cannot be ignored. Old template counters cannot be
   mandatory proof of new address conversion.
3. **Streaming capture, not only complete files.** Feed the archived 0/1/2/3
   prefixes through live decision logic. Verify pending never admits a probe or
   receipt, clean successor restores only verified evidence, and the unchanged
   deadline still terminates without a successor. Keep adversarial conflict,
   identity, overflow, ABORT and integrity fixtures fatal/non-admissible.
4. **Production correlation and capture coverage.** Test the actual matching
   predicates and distinguish rejected association from missing preparation.
   Exercise saturation and publication ordering, not just handcrafted matched
   records. A missing walk must not become a fabricated successful walk.

Correct the still-stale claims in candidate-181 notes, `docs/release-notes.md`
and the candidate-182 roadmap paragraph: the gate explanation was an untested
hypothesis, and the promised prepared-phase walk was not what the implementation
performed. Keep frozen manifests and raw evidence unchanged; add a superseding
interpretation. The current status already identifies several of these limits,
but older nearby prose remains misleading.

## One discriminating next experiment

**Hypothesis:** native SDMA PDE/PTE update packets embed framebuffer MC addresses
because the real entry-value operand bypasses the current conversion. Converting
that operand for valid non-SYSTEM entries should produce physical child/page
addresses and can advance execution beyond the present paging fault.

First complete the offline call-chain/ABI audit and tests above, fix the host
measurement blockers, and have the coordinator plus implementation agents assess
this report. Keep the existing lease, recovery gates, memory sizing, engine
topology, probe, and finite admission rules. Select **one** correction boundary
for the entry-value operand; do not combine it with speculative UQ root, shader,
connector, or global address-helper rewrites.

For a separately admitted single run, retain bounded samples of context/channel
identity, destination, source before/after, encoded template, count, increment,
address domain and resulting native packet fields. Require evidence that the
real MC source crossed the intended boundary, including a child PDE. Retain
SYSTEM/no-op observations as controls. Capture raw directory/leaf content through
the established safe worker path when the mapping identity is actually known;
keep inferred geometry and uncorrelated snapshots explicitly labelled.

| Result | Interpretation and next decision |
|---|---|
| Real MC source converts; native packet/raw entries agree; paging advances | Meaningful boundary progress. Run the unchanged checked probe if all existing admission/readiness conditions hold; then locate any next measured fault, including user-queue roots. |
| No eligible real source reaches the new boundary | Coverage/dispatch hypothesis fails. Investigate offline; do not rename the candidate and retry unchanged. |
| Input changes but emitted value or stored entry does not | The intervention is not on the final consumer, or updates do not execute. Separate packet construction from write completion before changing more VM state. |
| Correct raw physical entries exist but the same mapped address still faults | Address-domain correction alone is insufficient. Use the actual failing context and fault to discriminate geometry, permissions, invalidation and queue state. |
| Capture/correlation remains insufficient | No functional attribution. Apply the existing bounded stop and authenticated cleanup; no automatic retry. |

Correct compute values, rendered pixels and later real desktop presentation are
still required. A conversion counter, readable diagnostic walk, completed paging
packet, or successful cleanup is a milestone, not full acceleration.
