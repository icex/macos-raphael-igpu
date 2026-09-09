# Raphael, Navi 2x and Linux: a memory-path audit for Metal integration

**Research date:** 2026-09-09  
**Scope:** AMD Raphael/Granite Ridge iGPU (`1002:13c0`) versus the Navi23 identity used by macOS 15.7.9 build 24G830, with Navi21 and Linux-supported RDNA 2 APUs as counterexamples.  
**Current tested source:** project commit `ef326108b868a00efb292e481ea2efb866205efa`.  
**Current failure boundary:** candidate178-A and 178-B reach native engine startup, allocate the same stable GPU virtual address, and fail all observed final `AMDAccelMemoryMap::prepare` retries in the backing/PTE part of preparation before `submitBuffer` is called.

## Executive conclusions

Candidate178-A and candidate178-B materially narrow the immediate failure. Their final settled summaries are:

```text
A: process=162/162/162 mappings=483/483/483 prepare=486/486/486
   map=483/483/483 submit=0/0/0
   map-phase: total=483 capacity=0 va=0 backing-pte=483 unknown=0
B: process=178/178/178 mappings=531/531/531 prepare=534/534/534
   map=531/531/531 submit=0/0/0
   map-phase: total=531 capacity=0 va=0 backing-pte=531 unknown=0
sample: pre=0/0/0xb13/0x4000c0000 post=0/0/0xb13/0x4000c0000
```

In both runs, the first two stored samples and the lifetime counters agree. The accelerator batch count is zero, each map prepare count is zero, the assigned flag bit 0 remains set, and the raw GPUVA remains `0x4000c0000`. Under the audited 24G830 disassembly, this excludes the batch-capacity fast-fail and final-retry GPUVA allocation/reclaim paths for these 1,014 failures across two separately approved runs. It places the immediate investigation after GPUVA assignment, in `IOAccelMemoryMap::prepare`'s backing preparation or page-table commit. It does **not** identify the exact failing subcall, and it does not prove that every background call belongs to the Metal probe; the trace has no safe issuer/PID association and bounded buffers dropped detailed rows.

Linux provides a useful architectural reference, not a macOS implementation oracle. Current upstream-stable code deliberately treats GC 10.3.6 as an APU, gives it a 1 GiB GART instead of Navi23's default 512 MiB, does not assign Navi23's 32 MiB MALL capacity, and changes APU memory-placement policy when system GTT is larger than carved-out VRAM. At the same time, Linux sends both GC 10.3.4 and 10.3.6 through the same GMC10, GFXHUB2.1 and GFX10 backends and uses the same Navi10 PTE/PDE format. This combination makes the most likely immediate class a **policy/address-domain mismatch at backing or PTE commit**, rather than a wholly incompatible address-translation unit.

The safest next evidence is one bounded observation at the already-selected final prepare failure: distinguish failure of the superclass/backing preparation from failure of `AMDAccelMemoryMap::commitIntoGPUPageTable`. If commit is reached, capture the map size, backing-memory type/domain, page-table object/root, leaf physical or DMA address basis, and PTE flags before changing behavior. Do not alter the assigned GPUVA: successful zero GPUVA is legal when flag `0x20` is set, and candidate178 has a nonzero assigned GPUVA anyway.

Capacity and VA allocation are downgraded as observed causes for both candidate178 runs. Firmware/golden settings, SDMA execution, IH completion, shader ISA, and DCN remain untested downstream risks because no user command buffer has been submitted.

## Evidence and limits

### Direct project evidence

The frozen A run is `/home/bogdan/macos-vm/run/metal-011-178-a`. Its manifest SHA-256 is `a2929c4a03d3302e64f80b278e5f7d8cf24210aa6a89e2ae6953ef02957e5540`; serial SHA-256 is `c4a877508517dc78402e0b82c42dd5a2a20113a90965a27f92f5b0b6d7ac918c`; probe SHA-256 is `076bbc22f0922827ab1d8eda362fa13dea80e2118ab58a1e3e33d76b47e4e743`. The probe has the exact run ID, one complete stage sequence, status 5 / `e00002bd`, and zero completed command buffers, compute rounds, checked values, and render pixels. The shutdown outcome is `exited-after-guest-request`.

A's run-local schema-6 recovery receipt has SHA-256 `e696db64544372dd986df8319c9bd931bf7e2e81a0c89db4ea0eaebeb34a4fd5`; its canonical receipt has SHA-256 `528a400f4c059bb150ed98f480434599e27fbe3648fc9b6b4f635d6f47b24f4e`. The serialized bytes differ, while parsed JSON values are equal. The production `validate_recovery_receipt_v6` returns no errors. Status is `recovered`, `authorizes_launch` is true, and the 32 archived host messages have no GPU/VFIO/AER/IOMMU/reset/timeout/lockup/panic match. This validates lifecycle reuse; it does not establish graphics correctness.

Candidate178-B independently reproduces the phase under the same binary/configuration/probe: 531 of 531 final map failures are `backing-pte`, with capacity/VA/unknown all zero, stable flags `0xb13`, stable GPUVA `0x4000c0000`, and `submitBuffer=0`. Its run receipt SHA-256 is `ea9f41341b5d0f5ff08f7ef72ee44bd052c2a823ebeaae267c57798b5dd789d5`; canonical receipt SHA-256 is `fc1c08c831cd0b95862ae397f0ac60f09e312bba6316bac67c9cceae609e956c`. Parsed JSON values are equal while serialized bytes and hashes differ. `validate_recovery_receipt_v6` returns no errors, shutdown is `exited-after-guest-request`, and the terminal same-boot ledger is schema 4 at 6/6 (`810570...`), with no seventh launch authorized.

The evidence now includes three reviewed warm cleanup/reinitialization transitions in the same host boot: candidate176→177, 177→178-A, and 178-A→178-B. Every transition retained immutable receipts/history and reached a clean authorizing schema-6 recovery. This sharply reduces a stale allocator caused solely by failed cleanup as the explanation for the repeated map failure. It does not prove that an internal Apple pool is initialized correctly, because the same deterministic initialization defect can survive clean hardware retirement and reappear after each fresh guest boot.

The exact phase classifier derives from local 24G830 disassembly:

- `batchMemoryMapPrepare`, X6000 file offset `0x6550`, has a capacity fast-fail only when the count at accelerator `+0x1fb0` is **greater than** `0x3ff`.
- `AMDAccelMemoryMap::prepare`, X6000 file offset `0x3b3fe`, invokes GPUVA allocation before superclass/backing preparation and page-table commit.
- `IOAccelMemoryMap::allocGPUVirtualAddress`, IOAcceleratorFamily2 file offset `0x52aca`, writes map `+0x98` and sets flags bit 0 only on success.
- The superclass prepare failure paths at `0x52c08` and cold `0x58308` do not clear the assigned bit or GPUVA. Explicit free at `0x52b34` does.
- IOAcceleratorFamily2 base prepare makes its downstream virtual commit call at `0x52c84`; the exact X6000 override `AMDAccelMemoryMap::commitIntoGPUPageTable` is at `0x3b4d2`. Outer X6000 fallback paths may retry after freeing system or video maps, so the snapshots describe the **final retry**, not the first attempt.
- Flags bit `0x20` makes assigned GPUVA zero a legal successful state. Raw GPUVA alone never classifies failure.

The preserved design audit is [memory-map-phase-design.md](/home/bogdan/src/macos-raphael-igpu/findings/experiments/metal-010-177/memory-map-phase-design.md). Candidate177's prior boundary and correlation limits are in [notes.md](/home/bogdan/src/macos-raphael-igpu/findings/experiments/metal-010-177/notes.md).

### Linux source provenance

Three tagged source sets are cached below this report. Tag objects and peeled commits were resolved; this audit did not perform GPG signature verification, so “tagged” does not mean signature-verified:

| Source | Tag object | Peeled commit | Use |
|---|---|---|---|
| Torvalds Linux v6.12 | `06090c9b622a7e1f797e775db4c035e0d779b76e` | `adc218676eef25575469234709c2d87185ca223a` | Historical comparison only |
| Upstream stable v7.2.3 | `296e02a60bcb8223c12ebf58feeb69961f4608c1` | `58e7295cfecaddec94629160386412e0f2b1e8fe` | Current authoritative source comparison |
| CachyOS `cachyos-7.2.3-2` | `2723369da6b60ebb8828be229b25c78757baad72` | `e2f03349d0321aa61885daab8c5a63ff3a4402a9` | Distribution-source cross-check |

The running kernel is `7.2.3-1-cachyos-bore`. Its installed `amdgpu.ko.zst` SHA-256 is `557044d4f68b51b1b83d56645e526538e84aeba2431100f5d132dcde09ba4d9e`, vermagic is `7.2.3-1-cachyos-bore SMP preempt mod_unload`, and module source version is `8331A8BCCC301E625356433`. Package metadata identifies Linux CachyOS 7.2.3-1, built from the CachyOS 7.2.3-2 source tag. For the implementation files used below, the CachyOS tag and upstream-stable v7.2.3 bytes match. That identifies the relevant source semantics strongly, although it is not a reproducible-build proof of the installed compressed module.

The older `/home/bogdan/macos-vm/ref/linux` corpus is mixed. For example, its `gc1036/amdgpu_discovery.c` byte-matches exact tagged v6.12, while `mmhub24/gmc_v10_0.c` SHA-256 `69b5db...` does not byte-match exact tagged v6.12 and resembles later code. This report uses the newly cached exact tagged sources for version claims. The upstream [v7.2.3 release archive](https://www.kernel.org/pub/linux/kernel/v7.x/) and [CachyOS release script](https://github.com/CachyOS/linux-cachyos/blob/master/tag-release.sh) provide external provenance.

Selected upstream-stable v7.2.3 file hashes:

| File | SHA-256 |
|---|---|
| `amdgpu_discovery.c` | `2a53ce988fe75f16a00bd010c5c199449596936d7869223e65fc39917ae52be8` |
| `gmc_v10_0.c` | `a873c4474b85ebc56437e78de07998629004f932e2eedc9d3f54289e23bf9cb0` |
| `gfxhub_v2_1.c` | `94b1a294f030020ba2e71849a0762430e6d66839e3ddeee1129bb9862369fe86` |
| `mmhub_v2_3.c` | `d119efc78edcefdc830fd41f0538c5c756f3ec5876bfa8f7089498d6e4af829e` |
| `amdgpu_gmc.c` | `3455c27f0d6f32ab1ee1afc6dd109d2805618855ebb15bdc6b1672e29707c79e` |
| `amdgpu_ttm.c` | `5bdb0b4c29afcef22cac3967ac535a15c110c0197e486e089c9c65edc6081374` |
| `amdgpu_object.c` | `ff98c136a7c1dfa54d9847cdcdb2f6046291c307f47f0451fe9491df17fdf7b2` |
| `sdma_v5_2.c` | `9bee44cfb45798f2192031994b19f053ba8ab4c14660e1947c3e7da9d7bcefb8` |
| `gfx_v10_0.c` | `39de93ff6255423855ad3434d415d867b55dc0c0c268410fba3950af9355a473` |
| `kfd_device.c` | `6b4d5ee4854c4a85a652887b04f65066e793ae035e9db6559c1eeeea04a21985` |
| `amdgpu_amdkfd_gpuvm.c` | `056526f4ab32c898fb6b3659c28e75921bf776da490214bc7537d9e519e024a3` |
| `navi10_ih.c` | `465cdd203c48d2b35d8ac954354be24eee2b366b96fd11cb90607a1e93ff8563` |

## Hardware identities and useful counterexamples

| Property | Navi21 / Sienna Cichlid | Navi23 / Dimgrey Cavefish | Raphael / GC 10.3.6 | Linux-supported APU counterexample |
|---|---|---|---|---|
| Role here | Large discrete RDNA 2 control | macOS-facing spoof/class | Physical target | Van Gogh / Yellow Carp show that shared GFX10.3 does not imply discrete allocation policy |
| GC / compiler target | GC 10.3.0 / `gfx1030` | GC 10.3.4 / `gfx1032` | GC 10.3.6 / `gfx1036` | GC 10.3.1 maps to `gfx1033`; 10.3.3 maps to `gfx1035` |
| Memory | Dedicated GDDR6 | Dedicated GDDR6; RX 6600 has 8 GiB | 512 MiB firmware carve-out backed by shared DDR5 UMA | Carved-out local memory plus system GTT |
| Linux GART default | 512 MiB | 512 MiB | 1 GiB | 1 GiB for GC 10.3.1/3/6/7 |
| Linux MALL value | 128 MiB | 32 MiB | 0 | 0 unless explicitly listed |
| SDMA | 5.2.0, discrete queue policy | 5.2.4, eight KFD queues/engine | 5.2.6, two KFD queues/engine; one discovered engine on this host | Integrated variants use two KFD queues/engine |
| Hub backends | GMC10 + GFXHUB2.1 | GMC10 + GFXHUB2.1; MMHUB2.3 | GMC10 + GFXHUB2.1; MMHUB2.4.1 routed through MMHUB2.3 backend | Same broad hub backends where IP versions match |

AMD's [RX 6600 specification](https://www.amd.com/en/products/graphics/desktops/radeon/6000-series/amd-radeon-rx-6600.html) documents the discrete Navi23-class 8 GiB GDDR6/32 MiB Infinity Cache design. AMD's [RDNA 2 ISA reference](https://www.amd.com/content/dam/amd/en/documents/radeon-tech-docs/instruction-set-architectures/rdna2-shader-instruction-set-architecture.pdf) describes the instruction architecture. Neither document specifies macOS IOKit allocation policy for a spoofed APU.

### GC IP version is not the compiler-target suffix

Linux maps hardware IP 10.3.4 to compiler target `100302` (`gfx1032`) and hardware IP 10.3.6 to `100306` (`gfx1036`). It maps 10.3.1 to `gfx1033` and 10.3.3 to `gfx1035`. This table is explicit in [`kfd_device.c` lines 379–416](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdkfd/kfd_device.c#L379-L416). LLVM's [AMDGPU usage guide](https://llvm.org/docs/AMDGPUUsage.html) groups `gfx1030` through `gfx1036` under the generic `amdgpu10.3` processor, while still listing per-target features.

Therefore “Navi23 is GC 10.3.4” does not mean its shader target is `gfx1034`, and the numeric difference alone does not prove the Metal shader blob is invalid on Raphael. A specific unsupported instruction or feature bit must be shown by offline blob disassembly. In any event, candidate178 fails before command submission, so shader execution cannot be its immediate cause.

## Address translation and memory domains

### Shared mechanism, different policy

Linux routes both GC 10.3.4 and 10.3.6 through `gmc_v10_0`, `gfxhub_v2_1`, and the GFX10 driver. MMHUB IP 2.3.0, 2.4.0, and 2.4.1 all select `mmhub_v2_3`. See [`gmc_v10_0.c` lines 579–609](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L579-L609). Both revisions get a 256 TiB, 48-bit VM layout with three page-table levels and 9-bit blocks; VMID 0 is system, graphics/compute uses VMID 1–7, and KFD uses VMID 8–15 ([lines 792–813](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L792-L813), [869–877](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L869-L877)).

That common implementation is strong evidence that a completely different Raphael page-table encoding is unlikely. It does not make Navi23's heap sizing, aperture, backing placement, cache policy, or firmware behavior transferable.

### APU aperture and GART distinctions

`gmc_v10_0_mc_init` does not resize the framebuffer BAR on an APU. In native, non-passthrough x86 mode it replaces the PCI aperture with the MC framebuffer base and real VRAM size; under passthrough it intentionally preserves the PCI BAR view. It assigns a 1 GiB GART to GC 10.3.1/3/6/7 and 512 MiB by default, including Navi23 ([`gmc_v10_0.c` lines 683–720](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L683-L720)). This is directly relevant: the physical target is an APU exposed through VFIO, and Apple's driver believes it is a discrete Navi23.

The Linux 1 GiB value is not permission to enlarge Apple's current guest GART. It is evidence that supported software does not assume the Navi23 size for GC 10.3.6. The current guest has already established a working VMID0/GART root and host KIQ execution; the remaining failure is a client map. Any size change must follow a measured out-of-range allocation or page-table boundary, not the Linux constant alone.

### PTE and PDE format

GMC10's documented source encoding is:

- PTE physical page base in bits 47:12; memory type in 50:48; executable bit 4; snooped bit 2; system bit 1; valid bit 0.
- PDE physical base in bits 47:6; coherent bit 2; system bit 1; valid bit 0.
- A non-system VRAM PDE address is converted from MC to physical address; alignment violations are fatal in Linux.
- PRT mappings become system+snooped+logged and invalid. Coherent, externally coherent, or uncached BO flags force UC MTYPE in current v7.2.3.

The definitions and transformations are in [`gmc_v10_0.c` lines 421–522](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L421-L522). Root BOs backed by TT use a DMA address, while VRAM roots use a GPU offset and then the GMC conversion; the generic implementation is in [`amdgpu_gmc.c` lines 112–149](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_gmc.c#L112-L149).

This yields three distinct candidate178 backing/PTE subproblems that must not be collapsed:

1. **Backing or wiring failure:** the IOAccel superclass cannot obtain/prepare a memory descriptor before any PTE commit.
2. **Address-domain failure:** commit receives a CPU physical, DMA/IOMMU, MC, or BAR-relative address where the chosen system bit expects another domain.
3. **Encoding/cache/invalidation failure:** the address is right, while system/snoop/MTYPE/valid flags, hierarchy depth, root, or TLB invalidation is wrong.

The first fails before commit. A commit rejection can also propagate as the same outer `prepare` false, so the current observation cannot select between them. Address/encoding claims require evidence that `AMDAccelMemoryMap::commitIntoGPUPageTable` was entered and returned false, or a later VM fault/data-coherency symptom.

### System, GTT and VRAM backing are not interchangeable

Current v7.2.3 constructs page-directory flags from the actual TTM memory resource. TT/doorbell/preempt/MMIO-remap memory gets the SYSTEM bit; cached TT gets SNOOPED; cached VRAM may also be SNOOPED ([`amdgpu_ttm.c` lines 1423–1451](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_ttm.c#L1423-L1451)). VRAM and GTT remain separate placement domains even on an APU.

Linux v7.2.3 additionally caps APU GTT to physical RAM and sets `apu_prefer_gtt` when real VRAM is smaller than GTT ([`amdgpu_ttm.c` lines 2153–2194](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_ttm.c#L2153-L2194)). KFD then redirects nominal local allocations to GTT in that mode ([`amdgpu_amdkfd_gpuvm.c` lines 1675–1753](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_amdkfd_gpuvm.c#L1675-L1753)). This KFD choice is not an Apple prescription. It is a supported counterexample showing that an RDNA 2 APU may need allocation policy unlike a Navi23 discrete GPU even though both use GFX10.3 page tables.

The version matters. The exact v6.12 code lacks this current APU preference path and uses an older `get_vm_pte` interface. Claims about the running 7.2.3 host must use the v7.2.3 bytes above.

## Cache, coherency and MALL

Linux assigns 32 MiB MALL to GC 10.3.4 but falls through to zero for GC 10.3.6 ([`gmc_v10_0.c` lines 774–790](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L774-L790)). AMD describes Infinity Cache as a global last-level cache in its [RDNA 2 workstation architecture brief](https://www.amd.com/content/dam/amd/en/documents/products/graphics/workstation/rdna2-explained-radeon-pro-W6000.pdf). Linux's zero is a driver capability value and does not alone prove the silicon contains no cache. It does prove that upstream software refuses to assume Navi23's 32 MiB budget for GC 10.3.6.

This is potentially relevant in two ways:

- Apple's spoofed Navi23 capability could reserve or budget a cache-backed resource the physical APU does not expose.
- A system-memory mapping could need SYSTEM/SNOOPED/MTYPE choices different from a dedicated-VRAM map, and v7.2.3 explicitly derives those from backing type and BO coherency flags.

Candidate178's pre-submit false does not yet prove either. First identify whether backing preparation or commit fails. If the failure is backing allocation and a size/capability request aligns with a 32 MiB assumption, MALL advertising becomes testable. If commit fails, record leaf flags and address domain before changing cache policy.

## Firmware, queues and execution hazards

### GC firmware and golden registers

Linux uses the same broad GFX10.3 backend but keeps distinct firmware names and golden-register tables for GC 10.3.4 and 10.3.6. In current `gfx_v10_0.c`, Navi23's table begins at file lines 3507–3544 and Raphael's at 3618–3641; selection chooses the Raphael table explicitly near 3984. The local prior diff found only one identical row and 42 differing or absent rows, including address-configuration, GL2/UTCL1 and command-processor controls.

This is a serious **post-submit** risk. An execution-time shader or user-queue fault is not the current NoMemory cause because `submitBuffer` is never called. A firmware-derived capability or initialization value could still influence pre-submit allocation, so that narrower possibility is not excluded. Native KIQ stamps and engine start show that the current firmware/golden combination can execute the tested privileged startup path. That does not establish user compute or render execution.

The source names GC10.3.6-specific CE/PFP/ME/MEC/MEC2/RLC blobs; upstream's original GC10.3.6 GMC support commit is [a142606d5433](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=a142606d5433c9bfc68c0f40ba32c2e05ad75d09). The existing project decision to keep physical Raphael firmware while satisfying Apple's higher-level dispatch is consistent with this evidence.

### SDMA topology

Linux discovery increments `adev->sdma.num_instances` from discovered SDMA IP instances, and `sdma_v5_2` loops over that count when loading firmware and constructing rings. KFD assigns two queues per SDMA5.2.6 engine but eight per SDMA5.2.4 engine ([`kfd_device.c` lines 68–122](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdkfd/kfd_device.c#L68-L122)). Candidate178's one-engine topology repair and channel remap match the physical target's discovered one-instance evidence.

Startup and schema-6 shutdown prove the currently exercised SDMA/GC lifecycle path. No user submit means page-table update jobs, paging rings, and completion synchronization for a client workload remain untested. A later SDMA failure must be localized to the actual engine/ring/VMID; restoring a fictitious second physical engine would contradict both discovery and Linux's count-driven design.

### VMID, PASID, IH and fences

All GFX10.3 KFD devices use the same broad version-10 event-interrupt class, 16-bit PASID capability, and 8-DWORD IH entries; GC10.3.6 has a distinct no-atomic firmware threshold (`14` rather than the other GC10.3 default `92`) in [`kfd_device.c` lines 192–220](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdkfd/kfd_device.c#L192-L220). Linux's `navi10_ih` consumes ordered ring entries containing client/source/ring/VMID/timestamp/PASID and has explicit overflow recovery.

These differences matter after actual queue work. Host KIQ retirement is strong lifecycle evidence, while it is not a substitute for guest user-queue interrupt and fence completion. Do not diagnose IH from the lack of submit, and do not treat the current kernel-worker thread token as the Metal process PID.

## Desktop and presentation

Raphael uses a dedicated DCN315 stack in Linux, including its own resource construction, IRQ service, clock manager, DDR5/LPDDR5 watermark tables, and SMU clock calls. Navi23 uses a discrete display path. This makes physical display a structural port after headless rendering works. The current last visible guest log is not proof that DCN caused a pre-submit `AMDAccelMemoryMap::prepare` failure.

The safe sequence is:

1. Complete one headless compute submission and completion.
2. Complete an offscreen render with verified pixels.
3. Only then inspect DCN315 resource counts, clocks, watermarks, PHY routing and display interrupts for one bounded 1080p60 target.

No Navi23 SMU request should be retargeted to the Raphael SoC mailbox merely to advance display; that mailbox also governs host fabric and CPU-adjacent resources.

## Candidate178 decision tree

This tree states what the phase observation proves and the smallest next distinction. A phase describes the final native retry.

| Final phase | Proven by snapshot | Smallest next measurement | Correction threshold | Stop / keep-open rule |
|---|---|---|---|---|
| `capacity` | accelerator count before call is `>0x3ff`; map prepare was not entered | Observe count increment/decrement owner and last retained map; no hardware register access | Fix lifetime accounting only if a missing decrement or leak is demonstrated | STOP further GPU runs if the count grows monotonically without retirement; keep hardware hypotheses open but untested |
| `virtual-address` | result false, final assigned bit clear, counts legal | Observe allocator request size/alignment/range and whether free-to-alloc retry runs | Adjust aperture/allocator policy only when the exact request is outside a measured legal range or reclamation fails | Never use GPUVA zero alone; bit `0x20` permits legal assigned zero |
| `backing-pte` | result false with final assigned bit set; candidate178-A has stable nonzero GPUVA and all 483 failures here | First distinguish superclass/backing false from commit false. If commit: capture size, backing type, address-domain, root/level and leaf flags | Change one policy only after the failing subcall and inconsistent field are identified | This is the **active immediate branch**. STOP broad firmware/SDMA/DCN mutation while submit remains zero |
| `unknown` | impossible count transition, assigned-bit clearing, malformed state, or unclassified result | Preserve raw snapshot and audit concurrency/lifetime; expand observation only for the impossible transition | No functional correction until classifier invariant is explained | STOP interpretation and further functional changes if unknown is nonzero |
| success | native map prepare succeeds | Observe first `submitBuffer`, completion/fence, and any VM fault | Move to execution-only hypotheses in order | Reopen firmware/SDMA/IH only after actual submit; DCN only after offscreen render |

Candidate178-A and B both select `backing-pte`: 483 and 531 failures respectively, with identical sampled flags/GPUVA and no submit. This makes a transient allocator or stale same-boot state less likely, while it still does not associate every background call with the probe. The next experiment should distinguish backing preparation from commit rather than repeat the same phase observation.

## Recommended investigation order

1. **Offline disassembly:** map the exact 24G830 superclass-prepare and commit call returns to safe callsites; identify fields already available without dereferencing ungated objects.
2. **One bounded diagnostic, only if needed:** record which of those two subcalls is false, plus request size/alignment and backing class. Preserve the existing route and object gates.
3. **If superclass/backing fails:** compare heap/domain/capability choice against APU semantics, especially carved-out VRAM versus pageable system backing and any assumed MALL budget. Test one small allocation class offline or in a future finite run.
4. **If commit fails:** decode the exact client root and leaf entry offline. Check address basis (DMA/system vs MC/VRAM), alignment, hierarchy depth, SYSTEM/SNOOPED/MTYPE/VALID bits, and whether the right hub/VMID is invalidated.
5. **If prepare succeeds and submit begins:** then inspect GC10.3.6 firmware/golden state, SDMA update/completion, VMID/PASID/IH/fence routing, and shader-target features in that order.
6. **After headless render succeeds:** begin DCN315/presentation work.

### Explicit stopping thresholds

- **STOP and preserve the run** on any host fault/reset, guest panic, capture loss, invalid schema-6 recovery receipt, failed PSP confirmation, nonretired queue, or `unknown` phase.
- **STOP broad mutation** while `submitBuffer=0`; firmware, shader, IH and DCN theories are downstream.
- **STOP allocator changes** when final assigned bit is set and stable, unless a separate measured request demonstrates an allocator defect.
- **Keep backing/domain/PTE hypotheses open** until superclass versus commit is distinguished.
- **Keep downstream execution hypotheses untested**, rather than calling them ruled out, until a real user command buffer is submitted.

## What is ruled out, downgraded, or still open

| Claim | Status | Basis |
|---|---|---|
| Recorded host fault/reset during A/B; hardware lock as the NoMemory cause | No recorded event; causal hardware-lock claim unsupported | clean cursor-bounded host evidence and recovered schema-6 receipts do not exclude every persistent hardware-state effect |
| Batch count capacity caused A/B failures | Ruled out for observed final retries | 1,014 failures, count 0, capacity phase 0 |
| Final GPUVA allocation/reclaim caused A/B failures | Ruled out for observed final retries | assigned bit remains set; GPUVA `0x4000c0000` stable; VA phase 0 |
| GPUVA zero is inherently invalid | Refuted generally | IOAF flag `0x20` permits legal assigned zero; A is nonzero anyway |
| Backing preparation or PTE commit caused A/B | Proven only as a combined branch | every classified final retry is `backing-pte`; subcall unresolved |
| Wrong memory domain or PTE flags caused A/B | Strong hypothesis, not proven | Linux APU/discrete policy differs; exact Apple subcall/entry not yet captured |
| GC10.3.6 and Navi23 use unrelated page-table hardware | Downgraded | Linux shares GMC10/GFXHUB/PTE format |
| Navi23 MALL assumptions are safe on Raphael | Unsupported | Linux assigns 32 MiB vs 0 |
| Firmware/golden, SDMA completion, IH, shader ISA cause current A failure | Not current causes | no submit; remain downstream risks |
| DCN/last-log behavior causes current A failure | Not current cause | failure is headless pre-submit; DCN remains future structural work |
| SMU retarget is a safe shortcut | Excluded | distinct SoC/discrete protocols and host-wide effects |

## Primary sources

- Linux stable v7.2.3 [`amdgpu_discovery.c`](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_discovery.c), [`gmc_v10_0.c`](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c), [`gfxhub_v2_1.c`](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gfxhub_v2_1.c), [`mmhub_v2_3.c`](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/mmhub_v2_3.c), [`amdgpu_ttm.c`](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_ttm.c), [`amdgpu_object.c`](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_object.c), [`amdgpu_amdkfd_gpuvm.c`](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_amdkfd_gpuvm.c), [`kfd_device.c`](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdkfd/kfd_device.c), [`sdma_v5_2.c`](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/sdma_v5_2.c), [`gfx_v10_0.c`](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gfx_v10_0.c), and [`navi10_ih.c`](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/navi10_ih.c).
- Linux kernel [AMDGPU driver core](https://docs.kernel.org/gpu/amdgpu/driver-core.html) and [AMDGPU documentation index](https://docs.kernel.org/gpu/amdgpu/index.html).
- LLVM [AMDGPU usage and processor table](https://llvm.org/docs/AMDGPUUsage.html).
- AMD [RDNA 2 ISA](https://www.amd.com/content/dam/amd/en/documents/radeon-tech-docs/instruction-set-architectures/rdna2-shader-instruction-set-architecture.pdf), [Radeon RX 6600 specifications](https://www.amd.com/en/products/graphics/desktops/radeon/6000-series/amd-radeon-rx-6600.html), and [RDNA 2 workstation architecture brief](https://www.amd.com/content/dam/amd/en/documents/products/graphics/workstation/rdna2-explained-radeon-pro-W6000.pdf).
- Project-local measured architecture baseline: [Raphael versus Navi23 in AMDGPU](/home/bogdan/src/macos-raphael-igpu/findings/raphael-vs-navi-linux.md), [GPU reverse-engineering record](/home/bogdan/src/macos-raphael-igpu/findings/GPU-RE.md), and [roadmap](/home/bogdan/src/macos-raphael-igpu/docs/ROADMAP.md).

## Research limitations

Apple's X6000 and IOAcceleratorFamily2 code is proprietary and only locally disassembled; function names, offsets and branch semantics are derived from the exact 24G830 binaries, while data-structure meanings beyond observed accesses remain reverse-engineered. Linux's driver shows a supported implementation for the same physical IP but does not define Apple's private ABI. The current phase trace samples final retry state and aggregate counts; detailed buffers saturate, background calls cannot be tied safely to the probe PID, and no user command buffer reaches hardware. Accordingly, this report ranks the next distinction and downstream risks without claiming the specific backing or PTE defect is already known.
