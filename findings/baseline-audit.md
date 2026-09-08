# Fixed baseline audit — 2026-09-08

This audit supersedes historical claims that the CP is locked, that all framebuffer
addresses should be converted to physical addresses, or that Metal enumeration proves
execution. The reference is source/tag `627cdabc534c49a98b6d3ad8ce7e79e22c4b5066`
(1.0.159), with raw evidence in `metal-tests/20260908T052603Z-8dad7535`.
It completed three native KIQ stamps and engine power-up; hybrid creation returned 4,
`startHWEngines` returned **false**, and the first Metal command failed.

Diagnostic 1.0.162 was introduced in `1aee08f` and merged by `d6e320a`.
The current 1.0.163 successor adds append-only diagnostic storage and a unique
per-build marker. Its immutable prepared manifest will record exact source, bundle,
KDK and ESP hashes before any hardware experiment. Neither candidate is hardware-proven.

## Enabled configuration and mutations

Functional baseline: `rgpu=0xfffa5981 rgpuvmm=3 rgpumem=2 rgpuptb=2 rgpumqd=2`.
Diagnostic addition: `rgpuhybrid=1`; deferred replay begins at `rgpudump=40000`.
HWL means 24G830 HWLibs; FB means Framebuffer; X6 means AMDRadeonX6000.
All hooks also alter executable routing and timing; rows list additional effects.

| Enabled selector | Owner / boundary | Writes or changed result | Reason / cleanup consequence |
|---|---|---|---|
| m1 | FB doGPUPanic | Branch patch avoids panic on TTL failure; HWL version gate skipped under r1 | Preserve failed guest for evidence; does not turn initialization into success |
| d1 | HWL IP/TTL callbacks | Diagnostic reads and route installation | Legacy dumps are not a proof of GPU work |
| r1 | HWL IP discovery and mapping | Rewrite discovered version triples and rebuild mappings | Reuse Navi23 backends; does not establish all backend registers compatible |
| x1 | HWL PCIe link check | Return success for absent PCIe capability | APU has no discrete PCIe link; no link training/cleanup |
| x2 | HWL ttlSetDeviceCapabilityEntry | Retry capability match ignoring internal revision | Changes software capability selection; original errors otherwise preserved |
| x4 | HWL SMU firmware selection | Select fallback for missing file | No CPU SMU mailbox retargeting |
| x7 | HWL psp_ring_create | Destroy stale GPCOM ring before original creation | PSP mailbox writes; relies on previous owner's masters being stopped |
| x9 | HWL psp_np_fw_init | Replace RLC descriptor payloads with Raphael firmware | PSP subsequently loads firmware; allocation lifetime remains native |
| xa | HWL PSP command preparation | Read previous response and command metadata | CPU memory observation; no fabricated PSP status |
| xb | HWL signed TOC data | Replace both embedded TOC containers | Establish correct TMR requirement (10 MB); teardown remains relevant |
| xc | HWL psp_tmr_init | Call psp_tmr_unload before native init | PSP DESTROY_TMR command; necessity not independently proven; retained for this baseline |
| xd | HWL firmware capability | Decline absent tap-delay types | Raphael RLC v2_2 has no such payload |
| xe | HWL cosReleaseMemoryHandle | Return 0 for handle with null vtable | Avoid observed null dereference; skipped release may leak invalid failed-init resource |
| xf | HWL SMU function pointers | Install dummy backend, clear residual hardware-init callback | Avoid wrong GPU mailbox and especially host CPU SMU; dummy power management |
| xg | FB populateXGmiConfig | Populate software aperture fields from GC FB registers | Reads MMIO; source of correct MC base/top; no aperture relocation |
| xh | X6 initVRAMInfo | Set both pool sizes to their smaller nonzero value | 256 MB CPU-visible pool; prevents inverted range |
| xi | FB PowerPlay support | Report unsupported PowerPlay | Prevent failed power management powering device down; changes lifecycle |
| xj | X6 hardware power/start chain | Replace powerUpHWEngines loop, native per-engine calls and results; omit trace-bit update | Detailed audit below; other routed calls preserve native return |
| xk | FB/X6 startRlc, KIQ diagnostics | RLC CGCG=0, PG_CNTL=0, CNTL enable; clear VM fault latch; disable context0 retry; selector writes | **Active intervention**, not just tracing; no CP surgery when its boot arg is absent |
| xl | HWL autoload/predicate/write hooks | Accept alternate autoload predicates; tolerate safe-mode timeout | Mode2 preserves real HQD dequeue failure and disables forced ACTIVE clear; safe-mode behavior still changed |
| rgpuvmm=3 | X6 VMM readiness/allocation | Invoke allocation enable; clear m_0x20 guard if paging channel absent | Removes null channel path; teardown of partial allocations still unqualified |
| rgpumem=2 | X6 memory readiness | Invoke enableAllocations once if both pool objects exist | Creates allocator state earlier; cannot establish engine startup |
| rgpuptb=2 | HWL physical-base getter; X6 invalidation observation | Set vm+0x210 to physical FB_OFFSET before native GART programming | Preserves native context0 PTB programming; post-invalidation legacy rewrite disabled |
| rgpumqd=2 | X6 prepareKiq/startKIQ | Validate full image; disable wptr polling/doorbell; real dequeue; write planned MQD/EOP only after inactive | 50 ms timeout refuses start; never force HQD inactive; MC pointers stay MC |
| rgpuhybrid=1 | HWL TtlCreateHybridEngine | Read availability before native call; read request type only when valid/available | Capped eight observations; unchanged arguments/results; snapshot can race native check |
| rgpudump=40000 | Plugin logging thread | CPU record copies / serial output | Timing intervention; critical drop/truncation is explicit |
| -v, keepsyms=1, serial=3, debug=0x108 | Guest kernel | Verbose serial, symbols, debug behavior | Required evidence path; not GPU functionality |
| tlbto_us=0, vti=9, -lilubetaall | Guest/OpenCore/Lilu baseline | Existing guest boot compatibility options | Kept unchanged; not evidence of host watchdog settings |

Off: p1/reprobe, x8/restore-list suppression, old version-gate m2–m7, raw PSP
register trace x5, extra descriptor dump x6, `rgpucp`, `rgpureset`, `rgpuic`,
`rgpurlc`, and framebuffer relocation. Mode2 rejects incompatible legacy experiments.

## Power-up trace-field investigation

Native X6 `powerUpHWEngines` at `0x6fe9a` loops over 11 engine pointers at
`self+0x3b0+8*i`, calls virtual offset `0x138`, tests AL, and stops on failure.
The replacement preserves that loop and its low-byte Boolean result. Native
`0x6ff26..0x6ff41` additionally sets/clears bit `0x100` in a **16-bit** field at
`handler->virtual[0x178]()+8`. It is not a hardware register.

Resolved the actual handler vtable: `AMDHWHandler` at `0x16f698`, address point
`+0x10`, slot `0x178` points to `0x4b3ba`. This getter returns
`handler[0x10]+0x1e88`, the accelerator's driver-state trace structure. The changed
field is therefore accelerator+`0x1e90`. `dumpDriverStateTrace` (`0x2aa6`) formats
`writeDriverStateTraceDiagnosisReport` and prints it. Direct references to this
field include trace updates and tests of **bit 0x40**, not the omitted bit 0x100.
This establishes a diagnostic consumer; it is not exhaustive alias analysis of
all indirect consumers. Do not use the omitted bit as a cause or repair it together
with the hybrid observation. Retain this known baseline difference in the manifest.

## Observability side effects and limits

`dumpMecQueues` writes selectors to inspect different queues. `CP_MEC_ME2_HEADER_DUMP`
increments on read; it is not a packet header. `wrapKiqSubmit` clears fault evidence
before submission and disables retry: an absent later fault does not prove the
earlier boot was fault-free. `startRlc` changes gating registers even with CP surgery
off. None of these is removed incidentally in hybrid-001.

The new record store is fixed-size, append-only, and allocated in kext static storage.
Only a slot owner writes its payload; release/acquire publication exposes complete
records. Producers never wait on an interrupted producer. Readers do not mutate
slots or hold locks across formatting, MMIO or serial I/O. The regular and critical
stores have independent overflow/truncation counts. Critical replay lasts a bounded
18 snapshots; serial loss can still occur and must remain INCONCLUSIVE.

## First experiment

`experiments/hybrid-001.json` asks where native hybrid creation first fails after
KIQ setup. Availability-before plus return 4 distinguishes **suspicions**, not causal
proof: state may change between the added read and native branch. If available=1,
the next investigation is the selected GC/SDMA callback. If available=0, investigate
the producer of native blocking flags. Missing critical records never mean “not called.”

Fresh host reference is archived in `host-boots/23aedc74-6a57-4321-94f0-ae91d0e79354`.
The kernel is 7.2.3-1-cachyos-bore; cached Linux references are v6.12 and must not be
silently treated as that running kernel. pstore listing was denied and is **unknown**.
No VFIO launch has occurred in this boot as of this audit's initial preparation.
