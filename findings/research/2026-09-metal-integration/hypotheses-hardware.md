# Hardware/Linux blocker hypotheses after candidate178-A/B

**Date:** 2026-09-09  
**Evidence baseline:** candidate178-A and B, exact project commit `ef326108b868a00efb292e481ea2efb866205efa`, macOS 24G830 X6000 and IOAcceleratorFamily2 disassembly, upstream-stable Linux v7.2.3 commit `58e7295cfecaddec94629160386412e0f2b1e8fe`, and the running `7.2.3-1-cachyos-bore` host.

This is a ranked set of ten concrete blocker classes. It is an elimination plan, not a request for ten GPU launches. Offline source/ABI/disassembly work comes first. One future bounded observation should answer several adjacent questions only when object/route gates make the fields safe to read.

Candidate178-A and B establish the common boundary: 483 and 531 final map failures respectively, all `backing-pte`, with capacity/VA/unknown zero, prepare count zero, accelerator batch count zero, flags `0xb13`, GPUVA `0x4000c0000` unchanged, and `submitBuffer=0`. Three same-boot cleanup/reinitialization transitions—176→177, 177→178-A and 178-A→178-B—completed with authorizing schema-6 receipts and clean host evidence. This makes a transient hardware-lock or failed-retirement explanation weak. The absence of submit means execution, interrupt and display issues remain untested.

## Ranked matrix

| Rank | Blocker | Current status | Phase needed | Smallest discriminator |
|---:|---|---|---|---|
| 1 | IOAccel backing/wiring preparation fails | Active, strongest immediate branch | `backing-pte` | Distinguish superclass `prepare` return from commit return |
| 2 | PTE commit uses the wrong physical/DMA/MC address domain | Active if commit is entered | `backing-pte` | Capture backing class, leaf address basis and SYSTEM bit at one safe commit callsite |
| 3 | Navi23 heap/domain policy is wrong for Raphael UMA | Active if backing allocation/wiring fails | `backing-pte` | Record requested size/alignment/storage/backing class and chosen heap; compare with APU policy |
| 4 | PTE cacheability/coherency or TLB invalidation policy is wrong | Conditional on commit or later data/fault symptom | commit/post-submit | Decode exact PTE flags and invalidation target; compare against backing type |
| 5 | Client page-table hierarchy/root is inconsistent | Conditional on commit | `backing-pte` or VM fault | Decode root, level, coverage and leaf walk for GPUVA `0x4000c0000` offline |
| 6 | Spoofed Navi23 MALL/capability budget causes an unsupported allocation | Conditional, lower than backing-domain evidence | backing allocation | Identify a concrete 32 MiB cache-related request/capability before any patch |
| 7 | GC10.3.4 firmware/golden assumptions fail on GC10.3.6 execution | Open downstream | after first submit | Offline diff exact programmed state; observe first user queue hang/fault before correction |
| 8 | SDMA engine/queue/page-update topology is still mismatched | Open downstream | commit/page update/post-submit | Identify actual ring/engine/VMID used; compare one-engine/two-queue physical topology |
| 9 | VMID/PASID/IH/fence completion routing fails | Open downstream | after first submit | Correlate one submitted sequence with VMID/PASID, IH entry and fence retirement |
| 10 | DCN315 presentation resources/clocks/IRQs are absent or mis-modeled | Open much later | after headless render | Prove offscreen render first, then audit one 1080p60 resource/clock/IRQ path |

## H01 — backing or wiring preparation fails before PTE commit

**Claim.** `IOAccelMemoryMap` has an assigned GPUVA, but its superclass/backing preparation cannot create or wire the memory descriptor needed for GPU mapping.

**Supporting evidence.** Both candidate178 runs leave assigned bit 0 and GPUVA unchanged across every observed final false return. Exact IOAcceleratorFamily2 disassembly shows superclass failure does not clear either field. The combined classifier therefore places all 1,014 failures in backing preparation or commit. The Metal result is deterministic NoMemory before submit.

**Evidence against / limit.** No current trace distinguishes the superclass return from `AMDAccelMemoryMap::commitIntoGPUPageTable`. The 483/531 counts include unassociated background calls; only the probe result and temporal workload make a probe relationship plausible. Clean recovery says nothing about an IOKit memory descriptor.

**Source/offset.** IOAcceleratorFamily2 24G830 SHA-256 `1700f3...`: base prepare `0x52c08`, cold failure `0x58308`, commit call `0x52c84`; X6000 SHA-256 `2e364270...`: AMD prepare `0x3b3fe` and batch wrapper `0x6550`.

**Smallest safe test.** Offline, locate the shortest already-gated X6000 callsite that sees both superclass and commit return values. In one future bounded run, count only return class and request size/alignment/backing type. Do not hook the unsafe `0x3b3fe` entry, whose displaced span contains an outward short branch.

**Decision.** Accept if superclass returns false and commit is never reached for the failing map. Refute as the immediate branch if underlying backing preparation succeeds, the exact `AMDAccelMemoryMap::commitIntoGPUPageTable` method at X6000 `0x3b4d2` is entered, and that commit returns false; the enclosing/base prepare will then also return false.

**STOP/keep-open.** STOP functional memory changes until this split is measured. Keep H02–H05 open.

## H02 — PTE commit receives an address in the wrong domain

**Claim.** Apple's commit path encodes a CPU physical, guest physical/DMA, MC, or BAR-relative address incompatible with its SYSTEM/VRAM choice for the Raphael APU under VFIO.

**Supporting evidence.** Linux deliberately distinguishes TT roots, which use DMA addresses, from VRAM roots, which use a GPU offset followed by MC-to-physical conversion. In GMC10, SYSTEM is part of both PTE/PDE semantics. Raphael is an APU under passthrough while Apple's class is Navi23 discrete. That is exactly where an address-domain choice can diverge despite shared page-table format.

**Evidence against / limit.** The project already repaired and read back VMID0/GART and executes host KIQ, so a universal MC/BAR translation defect is refuted. The open claim is client-map-specific. Commit entry/return and leaf bytes have not yet been observed.

**Source/offset.** Linux stable v7.2.3 `amdgpu_gmc.c:112–149`; `gmc_v10_0.c:421–522,650–720`. Primary source: [GMC10 implementation](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L421-L522).

**Smallest safe test.** If commit is the failing subcall, capture immutable scalar inputs: map size, backing-domain enum, root/level, leaf address before masking, and flags. Decode the target leaf offline and compare it with the memory descriptor's address basis. No MMIO or page-table write is needed to establish inconsistency.

**Decision.** Accept only if the selected address basis contradicts the selected SYSTEM/VRAM domain or points outside the owned backing extent. Refute if address, ownership, alignment and domain agree and commit fails before encoding it.

**STOP/keep-open.** STOP any proposed constant address offset unless ownership and domain are proven. Keep cache/hierarchy hypotheses open if the address basis is consistent.

## H03 — discrete Navi23 heap placement is unsuitable for Raphael UMA

**Claim.** The spoofed Navi23 path requests or pins a discrete-VRAM resource where Raphael needs pageable/system GTT backing, or reports a heap capacity that cannot satisfy the actual backing request.

**Supporting evidence.** Linux v7.2.3 marks GC10.3.6 as `AMD_IS_APU`, does not resize the framebuffer BAR, gives it a distinct native aperture path, caps APU GTT to system RAM, and sets `apu_prefer_gtt` when real VRAM is smaller. KFD redirects nominal local allocations into GTT under that policy. Navi23 remains discrete. Candidate178 fails precisely at backing/PTE preparation.

**Evidence against / limit.** Linux KFD policy is not Apple's private ABI. The 512 MiB carve-out and current 256 MiB BAR do not prove the failing map exceeds either. Existing device enumeration and compilation show many allocations already succeed.

**Source/offset.** Linux stable v7.2.3 `amdgpu_discovery.c:3099–3189`; `gmc_v10_0.c:683–720`; `amdgpu_ttm.c:2153–2194`; `amdgpu_amdkfd_gpuvm.c:1675–1753`. Primary source: [APU GTT sizing](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_ttm.c#L2153-L2194).

**Smallest safe test.** First identify the exact backing request size, alignment, storage mode and selected heap in the failing superclass call. Compare that single request with reported Apple heap totals and owned carve-out/system-memory ranges. An offline forced-policy unit fixture is preferable before any guest run.

**Decision.** Accept if a valid system-backed request is rejected only after selecting an incompatible discrete/local heap, or if the chosen heap's real owned extent cannot cover the request. Refute for the observed map if the backing descriptor is prepared successfully and commit alone fails.

**STOP/keep-open.** Do not globally relabel all VRAM as system memory. Any correction must be specific to the demonstrated allocation class.

## H04 — PTE coherency, cache type, validity, or invalidation is wrong

**Claim.** A correct backing address is encoded with wrong SYSTEM/SNOOPED/MTYPE/VALID semantics or is not made visible by the correct hub/VMID invalidation.

**Supporting evidence.** GMC10 uses explicit PTE bits: physical page 47:12, MTYPE 50:48, executable 4, snooped 2, system 1, valid 0. Current Linux derives SYSTEM/SNOOPED from the backing resource and forces UC for coherent/ext-coherent/uncached BO flags. GART enable flushes both MMHUB and GFXHUB. UMA system memory makes these choices consequential.

**Evidence against / limit.** Candidate178 fails before submit and may fail before any PTE is written. Current VMID0/GART and KIQ operation show at least one translation/coherency path works. Linux's policy informs the audit but does not define Apple's encoding contract.

**Source/offset.** Linux stable v7.2.3 `gmc_v10_0.c:421–522,727–745,919–953`; `amdgpu_ttm.c:1423–1474`; `gfxhub_v2_1.c:190–269`. Primary source: [TTM PTE/PDE flags](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_ttm.c#L1423-L1474).

**Smallest safe test.** Only after proving commit is entered, decode the intended/actual leaf flags and the invalidation request for the same client VMID. Compare with backing cacheability. An offline decoder and captured bytes can decide most cases without a write.

**Decision.** Accept if the same owned backing is marked as VRAM/non-system when it is DMA/system, lacks required snoop/coherency, or invalidates the wrong hub/VMID. Refute if no leaf write occurs or flags and invalidate target are consistent.

**STOP/keep-open.** STOP cache-bit experiments based solely on NoMemory. Keep open for a commit false, VM fault, or post-submit stale-data symptom.

## H05 — client page-table root, level, or coverage is inconsistent

**Claim.** VMID0 is sound, while the per-client root or hierarchy cannot cover GPUVA `0x4000c0000`, has wrong depth/alignment, or is committed into the wrong VM context.

**Supporting evidence.** Linux treats VMID0 separately from graphics VMIDs 1–7 and configures three levels/48-bit VA for both GC10.3.4 and 10.3.6. A working VMID0 GART therefore does not prove every client root. The observed GPUVA is stable and suitable for an offline walk.

**Evidence against / limit.** Apple GPUVA allocation succeeds, which suggests its software aperture contains the address. No client page-table bytes/root mapping have yet been tied to the failing map. Linux's exact depth may differ from Apple's chosen software model while remaining hardware-valid.

**Source/offset.** Linux stable v7.2.3 `gmc_v10_0.c:792–813,869–877`; `gfxhub_v2_1.c:123–151,260–305`; `amdgpu_vm.c:2390–2440`. Primary source: [GMC VM sizing](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L792-L813).

**Smallest safe test.** Capture the client root, selected VMID, depth/block size and intended leaf location at commit; walk `0x4000c0000` offline against owned page-table extents. Reuse existing page-table dump machinery only if its ownership gates cover that root.

**Decision.** Accept if the GPUVA indexes outside an owned table, depth/root differs from the programmed client context, or a required level is absent/misaligned. Refute if the complete walk resolves to an owned leaf and commit fails before the walk.

**STOP/keep-open.** Do not change VMID0/GART root based on a per-client failure. Preserve the already proven host KIQ path.

## H06 — Navi23 MALL capability creates an unsupported allocation/budget

**Claim.** Apple's Navi23 identity advertises or reserves a 32 MiB last-level cache resource absent from Linux's GC10.3.6 capability model, causing backing preparation or budgeting to fail.

**Supporting evidence.** Linux assigns 32 MiB MALL to GC10.3.4 and zero to GC10.3.6. AMD documents Infinity Cache as a distinct global cache in RDNA 2 discrete products. A spoofed identity can expose a capability unrelated to the actual APU.

**Evidence against / limit.** Linux's zero is a software capability value, not proof that Raphael silicon has no cache. No observed Apple request has been tied to 32 MiB, MALL flags, or a cache reservation. Stable nonzero GPUVA does not support or refute this claim.

**Source/offset.** Linux stable v7.2.3 `gmc_v10_0.c:774–790`; exact Navi23 and Raphael golden settings in `gfx_v10_0.c:3507–3544,3618–3641`. AMD [RDNA 2 architecture brief](https://www.amd.com/content/dam/amd/en/documents/products/graphics/workstation/rdna2-explained-radeon-pro-W6000.pdf).

**Smallest safe test.** Audit the Apple capability/heap fields and failing allocation request offline. Search for a concrete 32 MiB-derived budget or no-allocate flag. Do not suppress a capability until one request depends on it.

**Decision.** Accept if backing failure is caused by a cache/MALL-specific allocation or exact 32 MiB budget unavailable on the physical target. Refute as immediate cause if ordinary backing succeeds and commit fails for unrelated address/flags.

**STOP/keep-open.** Keep at lower priority than H01–H05. Reject broad “Raphael has no cache” claims.

## H07 — GC10.3.4 firmware or golden state fails on GC10.3.6 user work

**Claim.** After mapping succeeds, a Navi23-specific command-processor/golden-register assumption prevents Raphael from executing user compute/render work.

**Supporting evidence.** Linux has separate GC10.3.4 and 10.3.6 golden tables and GC10.3.6 firmware names. The local golden diff has one identical row and 42 differing/absent rows, including address, GL2/UTCL1 and CP controls. KFD also assigns GC10.3.6 a distinct no-atomic firmware threshold.

**Evidence against / limit.** The project uses physical Raphael firmware substitutions, KIQ stamps retire, engines start, and both candidate178 runs stop before `submitBuffer`. An execution-time shader or user-queue firmware fault cannot precede zero submit. This does not globally exclude a firmware-derived capability or initialization value from influencing pre-submit backing policy.

**Source/offset.** Linux stable v7.2.3 `gfx_v10_0.c:3507–3544,3618–3641,3984–3987`; `amdgpu_ucode.c:1383–1450`; `kfd_device.c:192–220`.

**Smallest safe test.** Offline diff the exact registers the guest programs against Linux's two golden tables and retain only fields on the eventual failed execution path. After first submit, observe queue/fence/VM fault before any new write.

**Decision.** Accept when a real submitted queue stalls/faults at a register or firmware contract that differs for GC10.3.6. Refute for a passing compute submission; keep render-specific settings open until render.

**STOP/keep-open.** Do not touch firmware/golden settings while submit remains zero.

## H08 — SDMA page-update or queue topology is mismatched

**Claim.** The one physical SDMA engine is represented correctly at startup, but page-table update, paging ring, or queue selection still assumes Navi23's engine/queue topology.

**Supporting evidence.** Linux obtains engine count from IP discovery, loops over it, and gives SDMA5.2.6 two KFD queues per engine versus eight for SDMA5.2.4. Apple originally constructed two physical-engine objects; the project has already removed/aliased that false topology. Linux VM updates can use SDMA and explicitly synchronize when switching to CPU updates.

**Evidence against / limit.** Candidate178 native SDMA/engine startup and schema-6 shutdown pass. No submit occurs, and backing prepare may fail before SDMA participates. Restoring SDMA1 would contradict physical discovery.

**Source/offset.** Linux stable v7.2.3 `amdgpu_discovery.c:1591–1604`; `sdma_v5_2.c:739–760,1308–1346`; `kfd_device.c:68–122`; `amdgpu_vm.c:2590–2720,3217–3224`.

**Smallest safe test.** Determine offline whether the failing commit uses CPU or SDMA page-table updates. If SDMA, capture chosen engine/ring/VMID and completion result from an existing safe wrapper; compare against the discovered one-engine/two-queue topology.

**Decision.** Accept if commit targets a nonexistent engine/queue or fails waiting for a page-update job on it. Refute for the immediate failure if CPU commit returns false before scheduling SDMA; keep execution SDMA open later.

**STOP/keep-open.** Never synthesize a second physical engine. Stop on any page-ring timeout or incomplete retirement.

## H09 — VMID/PASID/IH or fence completion routing fails

**Claim.** A command can eventually be submitted, but its completion interrupt/fence is attributed to the wrong VMID, PASID, ring, or source and never retires.

**Supporting evidence.** Linux reserves different VMID ranges, uses 16-bit PASIDs, 8-DWORD IH entries, and decodes client/source/ring/VMID/timestamp/PASID. GC10.3.x shares a broad interrupt class, but the context values remain per queue. Apple is running a spoofed device with repaired topology.

**Evidence against / limit.** Host KIQ fences and recovery retirement work. That is a privileged host path and cannot prove a guest user queue completion. No user submit means this hypothesis has not been exercised.

**Source/offset.** Linux stable v7.2.3 `gmc_v10_0.c:869–877`; `kfd_device.c:125–220`; `navi10_ih.c:500–620`; `amdgpu_ih.c:209–295`.

**Smallest safe test.** After the first actual submit, assign one trace sequence at queue emission and observe its VMID/PASID, one decoded IH entry, and the matching fence retirement. Avoid PID claims based on a kernel-worker pointer.

**Decision.** Accept if a submitted sequence produces an interrupt/fence with mismatched routing or no completion despite an advancing ring. Refute for a clean compute completion; revisit per engine only when another queue class is used.

**STOP/keep-open.** Remain untested while `submitBuffer=0`. Stop on terminal queue timeout or unretired work.

## H10 — DCN315 presentation path is structurally missing

**Claim.** Headless Metal can eventually work, while physical desktop presentation fails because Raphael's DCN315 resource, clock, watermark, PHY and IRQ model differs from Navi23's discrete display path.

**Supporting evidence.** Linux carries dedicated `dcn315` resource construction, IRQ service, clock manager, DDR5/LPDDR5 watermark and SMU clock paths. The project target uses shared DDR5 and DCN 3.1.5; Navi23's Apple personality models a discrete GPU.

**Evidence against / limit.** The current failure is headless and pre-submit. A last visible display log cannot establish causation. No offscreen render has completed, so display has not become the active blocker.

**Source/offset.** Linux stable v7.2.3 `display/dc/resource/dcn315/dcn315_resource.c:869–950,2018–2352`; `display/dc/clk_mgr/dcn315/dcn315_clk_mgr.c:638–728`; project [Raphael/Navi Linux audit](/home/bogdan/src/macos-raphael-igpu/findings/raphael-vs-navi-linux.md).

**Smallest safe test.** Complete and verify headless compute, then offscreen render pixels. Only afterward map one 1080p60 display route's required timing generator, plane, PHY, clocks, watermark and IRQ source offline before a bounded display test.

**Decision.** Accept when offscreen render passes but a specific DCN315 resource/clock/IRQ prerequisite is absent or wrongly routed. Refute for a working physical presentation target; do not infer it from headless completion alone.

**STOP/keep-open.** Keep untested until offscreen render. Do not retarget Navi23 SMU commands to the Raphael SoC mailbox.

## Eliminated premises and ordering rules

The following premises must not return as blockers without new contradictory evidence:

- A host fault/reset or dirty recovery was recorded during candidate178-A/B: neither interval records one and both have authorizing schema-6 recovery. This does not exclude every persistent hardware-state effect; it makes a hardware-lock causal claim unsupported by the available evidence.
- Candidate178's final failure is the `>0x3ff` capacity branch: both runs recorded count zero and capacity zero.
- Candidate178's final failure is GPUVA allocation/reclaim: both runs retained assigned bit 0 and the same nonzero GPUVA; VA count is zero.
- GPUVA zero itself means failure: flag `0x20` permits legal assigned zero.
- GC IP 10.3.4 implies compiler target `gfx1034`: Linux maps it to `gfx1032`; GC 10.3.6 maps to `gfx1036`.
- A broad shader incompatibility, IH failure, SDMA completion failure or DCN last log explains the current NoMemory: user submission is still zero.
- Retargeting Navi23 SMU messages to Raphael is a safe diagnostic: it can affect SoC-wide host resources and remains excluded.

Work H01 first. If superclass backing succeeds, close H01 for the observed map and move directly to H02/H04/H05 using the same captured commit evidence. If superclass backing fails, prioritize H03, then H06. Only after `submitBuffer` becomes nonzero should H07–H09 move into the active set. H10 begins only after verified offscreen rendering.
