# Raphael/GC 10.3.6 initialization sequence: Linux versus macOS

## Evidence from Linux AMDGPU

Linux selects `gfxhub_v2_1` for GC IP 10.3.6 and programs VM context page-table base as separate low/high 32-bit registers using the VM hub's context stride. It programs GART start/end in 4 KiB units, then initializes the system aperture, TLB, L2 cache, identity aperture, VMID configuration, and invalidation engine in that order. See [`gfxhub_v2_1.c`](https://codebrowser.dev/linux/linux/drivers/gpu/drm/amd/amdgpu/gfxhub_v2_1.c.html#L123-L152) and the cache setup at [lines 209–258](https://codebrowser.dev/linux/linux/drivers/gpu/drm/amd/amdgpu/gfxhub_v2_1.c.html#L209-L258).

Linux's GFX10 VM entry path converts every non-system VRAM PDE/PTE from MC address to physical aperture address before writing it. The conversion is explicit in `gmc_v10_0_get_vm_pde`, which calls `amdgpu_gmc_vram_mc2pa`; system PTEs are left in system address space. It also applies the GFX10 fragment/translation-further flags at the correct page-directory levels. See [`gmc_v10_0.c`](https://codebrowser.dev/linux/linux/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c.html#L472-L492).

For an APU, Linux does not treat the PCI BAR aperture as ordinary discrete-GPU VRAM. `gmc_v10_0_mc_init` obtains the real VRAM size, keeps the PCI aperture parameters, and on x86 APU paths can use the GFXHUB framebuffer offset as the aperture base. The VRAM/GART locations are then calculated from the GFXHUB framebuffer location. See [`gmc_v10_0.c`](https://codebrowser.dev/linux/linux/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c.html#L700-L746).

Linux's KIQ selection has a hardware-specific restriction: it avoids MEC2 pipes 2/3 and requires queue ID 0 because clock-gating save/load commands are valid only there. This is a concrete candidate for checking against our hybrid engine remap. See [`amdgpu_gfx.c`](https://codebrowser.dev/linux/linux/drivers/gpu/drm/amd/amdgpu/amdgpu_gfx.c.html#L269-L301).

The Linux v10 compute MQD is a fixed structure and HQD loading begins at `CP_MQD_BASE_ADDR`; the HQD register window extends through the EOP/wptr fields. See [`v10_structs.h`](https://codebrowser.dev/linux/linux/drivers/gpu/drm/amd/include/v10_structs.h.html#L675-L710) and [`amdgpu_amdkfd_gfx_v10.c`](https://codebrowser.dev/linux/linux/drivers/gpu/drm/amd/amdgpu/amdgpu_amdkfd_gfx_v10.c.html#L208-L224).

## What this says about cycle 014

The cycle-014 root repair is consistent with Linux's MC-to-physical rule: the VMID-2 root was changed from `0xf40b6f3000` to `0x84b6f3000`, and converted child entries point into the `0x84...` physical aperture. However, the serial summary reports `physical=0` and many `invalid-template`/`omitted-child` entries. That does not prove the root is wrong; it means the observer saw no producer classified as an already-physical address and that many Apple-produced entries were filtered by template/producer policy.

The decisive new issue is the allocation sequence. Linux allocates the GART table in VRAM, establishes its MC/GPU address, programs the hub registers, and only then enables the GART. Apple submits while thousands of backing callbacks are rejected (`233 true`, `7035 false`) and large 8–36 MiB requests exceed the currently free pool. A small one-command submission is the correct next discriminator because it preserves the current VM programming while removing large resource-allocation pressure.

The KIQ log also shows the queue preflight's MQD/EOP values, followed by HQD reads with `EOP=0` after preparation. Linux's HQD load writes the complete MQD register window from a known structure. We should therefore capture every write/read pair for the EOP, PQ, RPTR, and MQD fields in the small test; this can distinguish a failed allocation path from a queue programming path without another speculative register rewrite.

## macOS source boundary

Apple's AMD graphics kexts and HWLibs are closed source. Apple's public open-source release index only points to release packages; it does not publish the AMD kext implementation ([Apple Open Source releases](https://opensource.apple.com/releases/)). The exact macOS sequence must therefore come from the local KDK disassembly and runtime traces already recorded in `findings/GPU-RE.md`. Public Hackintosh documentation is useful only for display policy: WhateverGreen recommends obtaining connector data from the VBIOS and treating custom connectors as a correction for physical topology, not as a substitute for VM/GFX initialization ([FAQ Radeon](https://github.com/acidanthera/WhateverGreen/blob/master/Manual/FAQ.Radeon.en.md#when-and-how-should-i-use-custom-connectors)). It also documents connector priority as a display-selection aid ([same FAQ](https://github.com/acidanthera/WhateverGreen/blob/master/Manual/FAQ.Radeon.en.md#how-can-i-change-display-priority)). Nothing there supports injecting a generic EDID as a fix for the cycle-014 KIQ timeout.

## Revised sequence to test

1. On a fresh boot, keep the existing GFXHUB root repair and all safety/recovery gates unchanged.
2. Run the new one-thread, 4-byte Metal probe only.
3. Record allocator request/free-pool pairs and the exact backing result for that probe.
4. Walk the probe IB and fence PTEs, including every PDE/PTE MC-to-physical conversion and template flags.
5. Capture the complete HQD write/read window, especially `CP_MQD_BASE_ADDR`, `CP_HQD_EOP_BASE_ADDR`, PQ base, RPTR, and WPTR.
6. Compare fence completion and `CP_CPC_STALLED_STAT2` with cycle 014.

If the small submission completes, allocator pressure or fragmentation is implicated. If it still stalls while backing succeeds and all PTEs are valid, focus on HQD/EOP programming and KIQ queue selection. Do not add EDID/HPD spoofing, change PTE semantics, or move the pool in the same experiment; each would destroy the discrimination.
