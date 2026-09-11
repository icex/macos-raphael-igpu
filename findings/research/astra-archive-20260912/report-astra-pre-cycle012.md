# Astra review after candidate 193

2026-09-11. Reviewed repository commit `dc12b7ed8ede098183676064e0828513a75f944a`
and the refreshed authoritative opening of `status.md`. This is the mandatory
review after actual GPU attempts **191, 192, 193**. The unresolved execution
streak remains **14**. Completion and assessment of this review start a new
three-attempt batch; they do not reset that streak or expand a host-boot budget.
Recorded current boot `f828eb26-9cb7-4fac-bff2-bc87515fa2ba` has consumed **1/3**
launches. Remaining capacity is not authorization to launch.

Scope: offline file/source inspection and read-only, in-memory replay using the
existing parser/classifier. Only this report was written. No VM, device access,
sudo, recovery, reset, build, implementation edit, or test-suite execution.
The prior report is preserved at
`findings/research/2026-09-11-candidate193-pre-astra/report-astra.md`; independently
verified SHA-256:
`ded9fb9162731d48d90bbc3b3872d495e85b253a240f67b23da338681b1f27f1`.

**Repair the actual mode-5 diagnostic producer and verify its complete consumer
path offline, then run the existing native Metal probe with the otherwise
unchanged candidate-193 A1 correction.** Candidate 193 did not test that
correction's GPU effect. Its authenticated pre-shutdown snapshot already contains
a decisive integration failure; the final incomplete capture masks it in the
published verdict. A new GPU hypothesis or general transport redesign is not
needed to fix this demonstrated blocker.

## What the batch established

Run directories below are under `/home/bogdan/macos-vm/run/`.

| Attempt and run ID | Demonstrated result | Remaining boundary |
|---|---|---|
| 191 / `20187457d3e5ad837617f89efa477219` / `metal-025-191` | Complete CR2 snapshot 7, 300 records. Native probe enumerated, compiled, committed, then timed out at 5 seconds | Zero completed command buffers, compute rounds, values, or pixels. Recovery incomplete |
| 192 / `575d67d557b07f98b186c0cfb024fcbd` / `metal-026-192` | Complete CR2 snapshot 6, 306 records. Same first-completion timeout. Actual faulting client VMID11 observed with MC-valued root | Root writer and fault-time causality unproven. Recovery incomplete |
| 193 / `a02f2b4e09e1a0319615d410c6965afb` / `metal-027-193` | Mode-5 gate and A1 route installed. Complete snapshot 4 contains mode-4 update summaries. Guest-requested shutdown and schema-6 recovery succeeded | Probe absent. A1 callback output absent. Final snapshot 5 cut off; formal verdict `INCONCLUSIVE / identity_or_route_missing`, evidence `capture_loss` |

193's successful cleanup is useful but not recovery qualification after the
failed workload in 191/192. Those receipts report three initially active HQDs,
including ME1/pipe0/queue0, and failure consuming graphics UNMAP_QUEUES followed
by failed host-KIQ WPTR clear. 193 reports two initially active MEC HQDs and no
probe. Different exercised queue state prevents attributing improved cleanup
to A1 repair. Preserve the incomplete receipts and all existing reuse gates.

## P0: the driver and classifier disagree about the active mode

`src/RaphaelGPU.cpp:5435`, in `publishPendingVmEntryUpdates`, emits the literal
`VM: entry-update mode=4` whenever `vmRootFixMode >= 4`.
`tools/classify-run.py:944,987` requires both the entry gate and update summaries
to report **5** when the card requires `map_process_root`. Candidate 193 enables
that contract. The observed mismatch follows directly from committed source;
it is not a theory about GPU execution.

I replayed each complete CR2 prefix without altering frozen files, using
`critical-replay.parse` and `classify_probe_readiness`:

| Complete snapshot | Exclusive byte end in original critical.txt | Records | Readiness result |
|---|---:|---:|---|
| 0 | 3,108 | 1 | `INCONCLUSIVE / identity_or_route_missing` |
| 1 | 11,292 | 23 | `INCONCLUSIVE / recovery_lease_pool_missing` |
| 2 | 19,476 | 23 | Same |
| 3 | 27,660 | 23 | Same |
| 4 | 194,410 | 283 | **`INVALID / vmid2_entry_update_state`** |

Snapshot 4's update records at sequences **145, 236, 263, 274, 275** all report
mode 4. A1 evidence consists only of the installed route at sequence 3.
A discriminating counterfactual changed only those decoded update modes to 5
in memory: the same readiness classifier returned **`PROBE_NOT_RUN` with no
earlier failure**. This is diagnostic evidence identifying the contract defect,
not permission to rewrite or reclassify the historical run as valid.

Required repair before another GPU attempt:

1. Emit the actual selected mode from the bulk-update publisher; retain mode-4
   conversion behavior and the strict mode-5 consumer requirement.
2. Exercise the **actual production formatter/publisher** with mode 4 and mode 5,
   pass its resulting records through the real parser/readiness classifier with
   the relevant card, and assert the exact expected outcome. If extracting a
   small shared formatter is needed, make production use that same formatter.
   Handwritten dictionaries or an independently copied format string do not
   test this boundary.
3. Retain a negative check showing gate 5/update 4 is rejected. Use the frozen
   snapshot-4 bytes as an immutable reproduction or a provenance-bound fixture.
   Verify corrected output has no newly hidden readiness blocker. Run relevant
   source/KDK/build and regression gates before staging once.

## P1: the coordinator discards why it decided to stop

At `tools/experiment.py:2812`, live readiness is classified; a decisive result
can end the polling loop after two seconds. After shutdown, the code rereads
the entire capture and replaces `result` at line 2904. No durable record binds
the earlier decision to the bytes and snapshot used for it.

193's final 258,838-byte capture ends mid-line after snapshot 5 record `008e`.
The parser correctly refuses a final complete-capture claim. The separate
recovery replay authenticates snapshot 4/count 283 and reports a later open
attempt with 397 valid chunks and a truncated tail. Recovery's restricted
`terminal-prefix-open` acceptance is not a valid replacement for functional
capture acceptance.

The supported causal explanation is that the mode mismatch produced a decisive
readiness refusal, shutdown interrupted a subsequent replay, and final
reclassification obscured the original failure. This is a **strong inference**:
the exact pre-shutdown verdict is reproducible and guest shutdown occurs at
08:01:41, far before the 180-second exposure cap. However, no persisted live
decision proves which polling iteration triggered shutdown. Do not promote
this reconstruction into an observed timestamped decision.

Add a small, bounded decision record when readiness becomes decisive and when
shutdown is selected: build/run/CID, selected verdict and stage, snapshot/count,
exact capture-prefix byte length and SHA-256, decision time, and stop reason.
Keep final capture quality and cleanup/recovery outcomes separately. A later
loss must not erase the earlier proven refusal, and the earlier prefix must
never certify absent later workload results. A mocked orchestration regression
should feed complete decisive evidence followed by a truncated shutdown tail
and verify both findings survive, with no probe or second launch.

This narrow diagnostic preservation is strongly recommended for the next
candidate. **P0 is the essential probe-readiness prerequisite.** Do not postpone
the functional attempt for a generalized verdict schema, parser relaxation,
collector rewrite, larger buffers, longer deadlines, or a new debugger system.
191 and 192 demonstrated complete transport under the failed probe; 193's tail
alone does not reestablish the earlier fsync/backpressure diagnosis.

## The remaining GPU hypothesis: independent A1 root programming

192's sequence 289 records VMID11, fault `0xb0093b`, VA `0x400300000`, context
root `0xf40b709000`, stable surrounding context, and worker-after-latch timing.
The relative CPU walk reads the physical alias `0x84b709000`, finds child
`0x200000084b763001`, then a zero entry at index 768. The absolute interpretation
finds a zero root entry at index 64. These are non-atomic CPU views after the
fault, not proof that the GPU reached either invalid entry. Repairing that
child speculatively would skip the still-unproven root domain again.

I directly inspected the cached exact KDK disassembly in
`/home/bogdan/macos-vm/re/x6000.asm`:

- `fillMapProcessPacket` at `0x8edce` constructs A1 header `0xc00ea100`, passes
  the supplied root through a memory-helper virtual call, stores the returned
  qword at packet `+8` (`0x8ee51`), and returns packet `+0x40`. Its ABI matches
  the wrapper's root, trap-base, queue-count, PASID and stack flags arguments.
- `AMDHWMemory::adjustVRAMAddress` at `0x53b78` subtracts `self+0x60` only inside
  its configured interval. `initVRAMInfo` stores `base - physical` in that
  field at `0x52820..0x52823`. Frozen 192 serial line 1853 explicitly reports
  base `0xf400000000`, physical `0x840000000`, delta **`0xebc0000000`**, size0
  `0x20000000`, size1 `0x10000000`. Treating `+0x60` as the MC base was wrong.
  The observed MC root lies outside the ordinary adjustment interval.
- The run-list producer calls A1 at `0x9029b`, then the separate A6 VM-aperture
  builder at `0x902aa`. This path does not pass an invalidate-info structure
  through the existing `prepareVMInvalidateRequest` wrapper.

Cached primary Linux v6.12 source independently supports the address-domain
rule: `amdgpu_gmc.c:127` obtains the root through the ASIC PDE callback and
retains root attributes; `gmc_v10_0.c:491` converts non-SYSTEM, non-PDE-as-PTE
pointers with `amdgpu_gmc_vram_mc2pa`; `amdgpu_amdkfd_gpuvm.c:487` uses that
hardware root address. These files are under
`/home/bogdan/macos-vm/run/research/metal-integration-20260909/cache/linux-v6.12/drivers/gpu/drm/amd/amdgpu/`.
Linux supports the conversion, not copying its page-table geometry into Apple.
The prior root-path report cites `kfd_packet_manager_v9.c`, which was absent
from the searched local cache; I did not independently inspect that file or
fetch new sources during this offline review.

The native-first, aperture-guarded A1 correction therefore remains a reasonable
single behavioral experiment. It changes packet `+8` after native construction,
with cached target/aperture checks and bounded recording. Current evidence does
**not** prove that A1 supplied 192's faulting VMID11, that every relevant root
writer is covered, or that root correction alone produces GPU completion.
Generalizing invalidate eligibility to VMIDs 1–15 did not establish coverage of
this independent producer. This ownership error recurred despite being flagged
in earlier review; keep an explicit root-writer/caller/evidence map.

## Why the offline gates missed an avoidable GPU attempt

The reported 728 Python tests, 17 sanitizer fixtures and exact-KDK build/preflight
check useful properties, but their coverage stopped at separate layers:

- Arithmetic fixtures exercise root conversion and byte preservation.
- KDK checks qualify offsets, prologue spans, route guards and callback order.
- `tests/test_classify_run.py:1692` fabricates an already decoded **mode-5** update
  dictionary, so it cannot discover what the production publisher actually emits.
  Its positive A1 assertions only exclude `map_process_root` from a failure name;
  an unrelated earlier refusal could satisfy that weak assertion.
- Neither fixture reaches production emission through parsing to the exact
  candidate's readiness outcome, and finalization does not retain its first
  decisive input. Passing test counts consequently overstated readiness for
  hardware integration.

Use assertions about the complete intended outcome and negative controls at the
changed boundary. Do not add another large collection of dictionary variants
as a substitute for that integration test. A byte-exact formatter-to-parser
check is cheaper and more discriminating than another failed exposure.

Documentation also needs a small correction: README still describes candidate
178's pre-submission `NoMemory` boundary; the roadmap calls itself authoritative,
contains an old next experiment, and says review after three **valid** experiments.
The standing rule is three **actual GPU attempts**, including invalid captures.
Point current-state language to `status.md` and retain the old material as
history. Within status, timestamp historical preparation claims consistently;
193's dated preparation paragraph still says no cycle has occurred even though
its later run section records one. Do not use old narrative text as admission.

## Revised discriminating test and decision tree

After coordinator and implementation-agent assessment, P0 completion, current
host/receipt/budget admission, and immutable staging, admit one bounded attempt
with the same reviewed headless configuration, dynamic GDB availability,
`GENERIC_GRAPHICS=off`, mode 5, 180-second exposure and unchanged 45-second native
probe. No automatic retry and no pre-probe debugger dependency.

**Hypothesis:** Apple's independent A1 producer can pass an MC-aperture root to
GFXHUB unchanged; mode 5 converts that actual packet field to the corresponding
physical address and may permit the first Metal command to complete.

Before the probe require authenticated build/route/native-start/readiness and
consistent mode-5 publication. Do **not** require a workload-generated A1 sample
before starting the workload. Route installation is pre-workload evidence;
actual input/native/final root and PASID are conditional observations.

| Next observation | Meaning and permitted next investigation |
|---|---|
| Identity, capture, mode or route refusal | A1 functional hypothesis untested. Repair that exact observation defect offline; no unchanged retry |
| Complete probe, A1 native MC root converted to physical, client context physical if faulted | Actual producer correction observed. If compute still fails, correlate the faulting client and earliest packet/table/completion boundary |
| A1 corrected but actual faulting client still has an MC root | Coverage or later overwrite hypothesis. Follow that client's writer/run-list identity before changing table contents |
| Probe fails and A1 output is absent or dropped | No negative conclusion about A1 correctness. Check whether the path ran and whether bounded retention omitted it; distinguish caller coverage from publication loss |
| Physical root with continuing fault | Root-domain advancement only. Correlate the same client's table geometry, update, invalidate and fault; worker-time zero entries alone do not establish cause |
| GPU results progress but user completion fails | Investigate fence/interrupt/completion routing using matched submission evidence |
| Three compute rounds, four completed buffers, 196,608 expected values and 4,096 expected pixels, clean exit | First functional compute/render milestone; subsequently qualify repeatability, lifecycle and actual desktop presentation |

Allocate no fixed three-launch sequence in advance. Reassess after each actual
result; invoke the mandatory review after three attempts regardless of whether
capture was valid. A physical-root observation does not reset the unresolved
**execution** streak while first command completion still fails. Recovery,
reinitialization and desktop composition remain distinct acceptance gates.

## Frozen evidence verification

Independently recomputed 193 hashes match the authoritative status:

- `critical.txt`: `d8b7f2eb5ca1d1a0d1a5b9130aad440200068f6629169854b2d5526d4aa49130`
- `serial.txt`: `27514348eb803178ab0b4c7c282de7d59ab643e24e794443686a1f64b4e304d8`
- `verdict.json`: `01987196b14c47057672b690715ca7e01cf9dc9a5ffd00d5aaa32ad4b5bdaacc`
- `recovery.json`: `b4d05ccc18f9305dcf42b5b3f9819821333e84851d9b80b4dd4c83c37cda06ba`

The receipt records schema 6, `recovered`, `authorizes_launch=true`, the expected
boot/run, and empty reset methods. This review did not rerun hardware recovery
or its complete validator. No frozen result was modified. Desktop Metal and
repeatable cleanup after the failing Metal workload remain unproven.
