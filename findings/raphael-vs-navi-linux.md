# Raphael versus Navi23 in AMDGPU

Status: source comparison complete for the current startup boundary. The implementation
reference is Linux v6.12, matching the repository's pinned source corpus. Host discovery
comes from the current machine and reports the physical Raphael IP versions; it is not
inferred from the spoofed PCI identity. Later Linux revisions must be checked before using
new upstream behavior as an implementation requirement.

## Why Navi23 is a useful but incomplete model

Raphael and Navi23 are both RDNA 2, so they share the GFX10.3 instruction set and much of
the GC, GMC and SDMA programming model. They are not the same topology. AMD documents the
AM5 integrated part as one WGP / two CUs with shared DDR5 and up to four displays, while a
representative Navi23 board, the RX 6600, has 28 CUs, a 128-bit GDDR6 interface and 32 MiB
of Infinity Cache. These are operational differences in memory placement, cache capacity,
engine count, power management and display control rather than shader-ISA differences.

Primary specifications:

- [AMD Ryzen Embedded 7000 product brief](https://www.amd.com/content/dam/amd/en/documents/products/embedded/ryzen/ryzen-embedded-7k-product-brief.pdf)
- [AMD Ryzen Embedded family table](https://www.amd.com/en/products/embedded/ryzen.html)
- [AMD Radeon RX 6600 specifications](https://www.amd.com/en/products/graphics/desktops/radeon/6000-series/amd-radeon-rx-6600.html)
- [AMD RDNA 2 ISA reference](https://docs.amd.com/api/khub/documents/Et~wpu9g~Ffl7d9q0QZ~Og/content)
- [Apple's supported eGPU configurations](https://support.apple.com/en-ie/102363)
- [Apple Mac Pro (2019) GPU specifications](https://support.apple.com/en-us/118461)

Linux models a GPU as discovered IP blocks and walks each block's lifecycle operations.
That structure is the key lesson for this project: the PCI-device spoof selects Apple's
Navi23 object graph, but each physical Raphael IP block still needs its own measured
topology and compatibility decision. See Linux's [IP-block lifecycle documentation](https://docs.kernel.org/gpu/amdgpu/driver-core.html)
and [queue model](https://docs.kernel.org/gpu/amdgpu/driver-core.html#gfx-compute-and-sdma-overall-behavior).

## The macOS-supported reference set

Apple publicly supports Navi21-class RX 6800/6900 and W6800X/W6900X products, and
Navi23-class RX 6600 XT and W6600X products. These give two useful reference points in
Apple's X6000 stack. Navi21 is the large end of RDNA 2 and Navi23 is the closest Apple
target by size, but both are discrete GPUs with dedicated GDDR6 and a last-level cache.
Neither has Raphael's UMA ownership or single discovered SDMA instance.

Linux's firmware-name decoder independently maps GC 10.3.0 / SDMA 5.2.0 to Sienna
Cichlid (Navi21), GC 10.3.2 / SDMA 5.2.2 to Navy Flounder (Navi22), and GC 10.3.4 /
SDMA 5.2.4 to Dimgrey Cavefish (Navi23). Raphael reports GC 10.3.6 / SDMA 5.2.6.
The generic family selection groups 10.3.0, 10.3.2 and 10.3.4 as discrete `AMDGPU_FAMILY_NV`,
while 10.3.6 receives its own family and the `AMD_IS_APU` flag. This is why a successful
Navi23 dispatch is evidence for shared instruction/register architecture, while it cannot
establish memory, engine-count, power or display compatibility.

| Reference | Apple evidence | Linux GC / SDMA identity | Topology relevant here |
|---|---|---|---|
| Navi21 | RX 6800/6900 eGPU and W6800X/W6900X MPX support | 10.3.0 / 5.2.0, Sienna Cichlid | Large discrete design; 60–80 CUs in Apple's MPX products, dedicated GDDR6, Navi21-specific golden settings |
| Navi22 | Useful intermediate Linux implementation; not used as the project's Apple support claim | 10.3.2 / 5.2.2, Navy Flounder | Same common GFX10/SDMA backends with another per-ASIC golden/firmware set |
| Navi23 | RX 6600 XT eGPU and W6600X MPX support; the class used by this project | 10.3.4 / 5.2.4, Dimgrey Cavefish | 32 CUs in W6600X, dedicated GDDR6, 32 MiB last-level cache; Apple's object graph assumes two SDMA objects |
| Raphael | No native Apple driver identity; explicitly marked and spoofed by this project | 10.3.6 / 5.2.6, APU-specific family | 2 CUs, shared DDR5 UMA, Linux assigns zero MALL capacity, one discovered SDMA instance, DCN315 |

## Block comparison and decisions

| Block | Physical Raphael | Apple-facing Navi23 | Linux relationship | Project decision and next trigger |
|---|---|---|---|---|
| GC / shaders | GC 10.3.6, 1 WGP / 2 CUs | GC 10.3.4, many more CUs | Both select `gfx_v10_0`, but 10.3.6 has its own golden-register table, TSC registers and APU power-gating cases | Keep Navi23 dispatch plus Raphael firmware substitutions because KIQ executes. If M4 reaches a graphics/compute hang after valid submission, compare the exact failed register path with the 10.3.6 golden table before adding any write. |
| SDMA | SDMA 5.2.6, discovery count 1 | SDMA 5.2.4; Apple's class constructs two physical-engine objects | Both select `sdma_v5_2`. Linux loops over `adev->sdma.num_instances`. KFD exposes 2 queues per 5.2.6 engine and 8 per 5.2.4 engine. | Candidate165 removes the false second Apple object. Hybrid-003 then proved X6000 still requests that engine while building accelerator channels; candidate166 maps that request to the surviving SDMA0 object, matching the one-engine/two-queue distinction. |
| GFXHUB / MMHUB | GC 10.3.6 + MMHUB 2.4.1, UMA | GC 10.3.4 + MMHUB 2.3.0, discrete VRAM | `gmc_v10_0` uses `gfxhub_v2_1` for both GC revisions and `mmhub_v2_3` for MMHUB 2.3.0/2.4.0/2.4.1. Native APU setup has a distinct aperture path, but Linux suppresses that override under passthrough. | Keep the established BAR-relative-to-MC corrections because register/fault/readback evidence proves them; Linux alone does not prove that guest repair. Linux uses a 1 GiB GART for 10.3.6 but 512 MiB by default for Navi23; test address range and page-table depth before changing Apple's size. |
| Last-level cache | Linux assigns zero MALL capacity for GC 10.3.6 | 32 MiB MALL/Infinity Cache for GC 10.3.4 | `gmc_v10_0` sets 32 MiB only for 10.3.4 and falls through to zero for 10.3.6; this is a driver capability value, not proof that no cache exists in silicon. | Do not advertise or reserve Navi23's 32 MiB cache solely from the spoofed identity. If Apple derives allocation or coherency behavior from it, patch the specific capability only after observing a failure. |
| PSP / MP0 | 13.0.5 | 11.0.12 | Different PSP generations and firmware containers | Continue using the physical chip's TOC/RLC payloads while satisfying Apple's dispatch. Do not issue Navi23 reset/power assumptions to the SoC PSP without a bounded, source-backed proof. |
| SMU / MP1 | 13.0.5, SoC mailbox also governs host resources | 11.0.12, discrete-GPU SMU | Different message protocols and power tables | Keep Apple's dummy SMU backend. Retargeting Navi23 messages to Raphael's host SMU is excluded because it can affect CPU/fabric state. Revisit only with a guest-safe proxy design and exact message translation. |
| UMC | 9.5.0, shared DDR5 topology | 8.7.0, GDDR6 topology | The Navi2 GMC path has UMC 8.7 support, while the physical discovery reports a different controller generation | Keep the minimum version mapping required for Apple's object creation, but treat reported width/type/RAS data as synthetic. Validate actual GPU-address behavior through GFXHUB and independent readback. |
| NBIF / PCI presentation | NBIF 7.3.0, integrated function | NBIF 7.2.0, discrete PCIe device | Linux maps 7.3.0 and 7.2.x to the same NBIO 7.2 functions | Existing remap is supported. The macOS PCI-link bypass stays limited to the absent virtual capability; KIQ proves the core doorbell route. Investigate atomics only if a specific Metal/compute operation fails there. |
| Display | DCN/DMU 3.1.5 with integrated clocks, watermarks and PHY topology | Navi23 DCN 3.0-family display path | Linux has dedicated `dcn315` resource, IRQ, clock and SMU files. Its resource counts, PHY routing and APU clock/watermark protocol differ structurally from the discrete path. | Keep physical display outside the M4 headless Metal gate. Treat M6 as a structural DCN315 port, beginning with one 1080p60 test target after headless Metal; do not assume one register patch is sufficient. |
| VCN/video | VCN 3.1.2 | Navi23 VCN 3.x variant | Same broad generation, separate firmware/capability details | Defer decode/encode until compute, render and lifecycle gates pass. Metal completion does not establish video acceleration. |

Primary implementation references:

- [Linux v6.12 IP discovery selection](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/amdgpu_discovery.c)
- [Linux v6.12 GFX10 implementation and GC-specific golden settings](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/gfx_v10_0.c)
- [Linux v6.12 GMC10 implementation](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c)
- [Linux v6.12 SDMA 5.2 implementation](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/sdma_v5_2.c)
- [Linux v6.12 KFD topology selection](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdkfd/kfd_device.c)
- [Linux v6.12 firmware-name/IP identity mapping](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/amdgpu_ucode.c)
- [Linux v6.12 PSP 13 implementation](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/psp_v13_0.c)
- [Linux v6.12 Raphael SMU backend](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/pm/swsmu/smu13/smu_v13_0_5_ppt.c)
- [Linux DCN315 resource implementation](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/display/dc/resource/dcn315/dcn315_resource.c)
- [Linux DCN315 clock/SMU implementation](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/display/dc/clk_mgr/dcn315/dcn315_clk_mgr.c)

## What changes now

The comparison independently supports the measured SDMA repair: Linux derives the number
of physical engines from IP discovery, and its SDMA setup and lifecycle loops use that
`num_instances` value rather than assuming Navi23's count. Fixed register/IRQ cases and
maximum bounds still exist. The source also shows that aliasing Apple's SDMA1 object onto
SDMA0 would be wrong because engine count and queues per engine are separate dimensions.

Candidate 1.0.171 reached native startup and then stalled SDMA0 paging on a VMID 2 IB. It also
proved that reset-free recovery can dequeue the remaining HQDs and return an idle CP without a
PCI reset or amdgpu rebind. Candidate 1.0.172 adds no compatibility write. It captures the exact
VM program request Apple encodes into the SDMA stream.

The shared backend is now checked down to its address basis: Navi23/Dimgrey Cavefish and the
Raphael-family discovery data both place GC segment 0 at `0x1260` and segment 1 at `0xa000`, and
Linux uses the single `gc_10_3_0_offset.h` layout for GC 10.3.4 and 10.3.6. Broad register
translation is therefore excluded unless the captured Apple packet itself demonstrates a wrong
index or value. The next observation order is fixed:

1. Preserve the native command-buffer status, engine and fault domain.
2. If submission never advances, identify PM4, SDMA or VM before reading registers.
3. If compute advances but data is wrong, test the UMA address conversion and cache mode.
4. If compute passes but render fails, compare GC 10.3.6 shader/graphics state.
5. Only after offscreen rendering passes, begin the separate DCN315 display port.
