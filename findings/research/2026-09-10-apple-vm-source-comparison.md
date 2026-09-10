# Apple and community VM source comparison (2026-09-10)

## Question and source hierarchy

This review asks whether public Apple material or established macOS AMD patching
projects independently specify the address-domain repair now implemented for
Raphael roots and entries. It does not use application-facing Metal documentation
as a hardware page-table specification.

The evidence has four distinct levels:

1. **Officially documented:** public Apple developer documentation describes
   resource placement and CPU/GPU visibility. Public XNU/IOKit source describes
   generic memory descriptors and DMA mappings.
2. **Public community code:** NootedRed, NootRX, and WhateverGreen show concrete
   reverse-engineered compatibility techniques, but are not Apple specifications.
3. **Disassembled fact:** the pinned 24G830 AMDRadeonX6000 binary is the
   authority for the private Apple ABI and encoder behavior used by this project.
4. **Unresolved:** no reviewed public source identifies Raphael's required Apple
   VMID-to-root policy or proves that repairing a VMID1 root yields working Metal.

Research was network-read-only and repository-read-only. No implementation,
build, staging, VM, GPU, device, media, or privileged operation was performed.

## What Apple officially documents

Apple's [storage-mode guidance for Intel and AMD GPUs](https://developer.apple.com/documentation/metal/choosing-a-resource-storage-mode-for-intel-and-amd-gpus)
states that Macs may use unified or discrete memory models, that shared resources
reside in system memory accessible to CPU and GPU, and that private-resource
placement differs by memory model. Apple's
[`storageModeShared` documentation](https://developer.apple.com/documentation/metal/mtlresourceoptions/storagemodeshared)
also says shared mode is the default for buffers on integrated GPUs. These are
resource semantics exposed to Metal applications. They support keeping UMA and
discrete placement assumptions separate, but say nothing about `MC_VM_FB_OFFSET`,
GFXHUB PTB register encoding, PDE/PTE bits, VMIDs, or AMDRadeonX6000's private ABI.

Apple publishes
[XNU at `f6217f891ac0bb64f3d375211650a4c1ff8ca1ea`](https://github.com/apple-oss-distributions/xnu/tree/f6217f891ac0bb64f3d375211650a4c1ff8ca1ea)
and
[IOGraphics at `76285384ff0ce63965a21b8023bf6d7e447fcc19`](https://github.com/apple-oss-distributions/IOGraphics/tree/76285384ff0ce63965a21b8023bf6d7e447fcc19).
Those were the `main` revisions resolved during this review. XNU's
`IOMemoryDescriptor`, `IODMACommand`, and `IOMapper` code covers generic kernel
memory preparation and device DMA/IOMMU address generation. IOGraphics exposes
framebuffer interfaces. The reviewed public trees do not contain
`AMDRadeonX6000`, `AMDHWVMM`, `AMDGFX10VMM`, `IOAcceleratorFamily2` implementation,
or AMD GFX10 page-table construction. Consequently an `IODMACommand` segment or
an `IOMemoryDescriptor` physical segment must not be equated automatically with
the address expected in a GFXHUB PDE/PTE.

The negative finding is bounded: the Apple OSS catalog and relevant current XNU
and IOGraphics trees were searched, rather than claiming Apple has never published
related material anywhere. No public Apple source found in that scope defines the
hardware-level conversion implemented here.

## Exact Apple binary: authoritative private behavior

The pinned 24G830 binary is
`/home/bogdan/macos-vm/kdk/x/System/Library/Extensions/AMDRadeonX6000.kext/Contents/MacOS/AMDRadeonX6000`;
symbol and instruction evidence is frozen in `/home/bogdan/macos-vm/re/x6000.nm`
and `x6000.asm`.

Disassembly establishes:

* `AMDGFX10VMM::prepareVMInvalidateRequest` at `0x6249c` reads hub at info
  `+0`, VMID at `+4`, invalidation range at `+8/+0x10`, root at `+0x18`, flags
  at `+0x20`, and compares the reprogram byte at `+0x24` to exactly one. When
  reprogramming, it copies the root into prepared PTB words at `+4/+0xc`.
* `AMDGFX10VMM::getPDEValue` at `0x629c6` retains address bits 47:6 and adds
  level-dependent attributes and VALID.
* `AMDGFX10VMM::getPTEValue` at `0x62a14` retains address bits 47:12 and derives
  SYSTEM, SNOOPED, permissions, fragment, MTYPE and traversal attributes from
  its private arguments.
* `AMDHWVMContext::updateContiguousPTEsWithDMAUsingAddr` at `0x55cda` receives
  destination, count, source, template, and increment in that order. Its ABI
  carries no explicit hub or VMID.

These facts validate the wrapper layouts, masks, exact reprogram predicate, and
argument order. They do not by themselves say that an address supplied by Apple's
allocation path is in the wrong domain on Raphael. That conclusion comes from the
combination of live register/capture evidence and the hardware address relationship.

## NootedRed: relevant UMA precedent, not a GFX10 rule

Local revision: `d53df4aae8c669a422fec0afa3a654228c9cfe52` from
[ChefKissInc/NootedRed](https://github.com/ChefKissInc/NootedRed/tree/d53df4aae8c669a422fec0afa3a654228c9cfe52).

NootedRed explicitly reads `MC_VM_FB_OFFSET` and converts it to bytes in
[`NRed.cpp`](https://github.com/ChefKissInc/NootedRed/blob/d53df4aae8c669a422fec0afa3a654228c9cfe52/NootedRed/NRed.cpp#L83-L124).
Its X5000 compatibility path wraps Apple's `AMDHWMemory::adjustVRAMAddress`; when
Apple returns an adjusted value, it adds the captured framebuffer offset in
[`X5000.cpp`](https://github.com/ChefKissInc/NootedRed/blob/d53df4aae8c669a422fec0afa3a654228c9cfe52/NootedRed/X5000.cpp#L358-L363).

This is strong public community evidence that Apple's discrete-oriented AMD path
can require explicit framebuffer-offset compensation on an AMD APU. It also warns
against assuming all Apple-returned addresses already share one domain. It is not
the same operation as the Raphael fix: NootedRed targets older X5000/GFX9-era
integrated GPUs, patches `adjustVRAMAddress`, and adds an offset in that function's
particular domain. It neither implements `AMDGFX10VMM::prepareVMInvalidateRequest`
nor defines Raphael PDE/PTE or client-VMID policy. The source itself labels the
stored `fbOffset` and this adjustment area with TODO/investigation caveats.

The useful comparison is conceptual: both projects observe a gap between Apple's
assumed AMD memory topology and an APU framebuffer aperture. The arithmetic and
hook direction cannot be copied between them without tracing each native ABI.

## NootRX and WhateverGreen: scope limits

Local NootRX revision: `350257011423b33b22a35751f489975e3a614f30` from
[ChefKissInc/NootRX](https://github.com/ChefKissInc/NootRX/tree/350257011423b33b22a35751f489975e3a614f30).
NootRX provides Navi 20-series compatibility patches, including Navi23 identity,
firmware, capability, and golden-register handling. In the reviewed revision it
does not implement or route `AMDHWVMM`, `AMDGFX10VMM`, `getPDEValue`,
`getPTEValue`, or `prepareVMInvalidateRequest`, and it does not provide a UMA
framebuffer-offset rule. Navi23 support is therefore useful for discrete baseline
behavior but is not evidence that a Raphael APU should inherit Navi23 address
placement unchanged.

Local WhateverGreen revision: `0762cecc2a70054cd4dc3cf4d08979aca6acd9bb`
from [acidanthera/WhateverGreen](https://github.com/acidanthera/WhateverGreen/tree/0762cecc2a70054cd4dc3cf4d08979aca6acd9bb).
WhateverGreen's AMD work primarily patches device properties, framebuffer/display
behavior, naming, policy, and selected hardware quirks. Its reviewed code does not
define the X6000 AMD GPUVM root/PDE/PTE ABI. It demonstrates that precise,
build-aware binary routing is normal in this ecosystem, but it supplies no oracle
for the current conversion.

Absence claims here are limited to the pinned local revisions and searches for the
named VM classes/functions plus PDE/PTE, GART, framebuffer-offset, and UMA terms.

## Comparison with the current Raphael fix

The current implementation in `src/GpuVmDiagnostics.hpp` does the following:

* applies root repair only to hub 0 client contexts VMID 1 through 15;
* leaves VMID0 on the established legacy GART path;
* requires native reprogram byte exactly one;
* rejects SYSTEM and unsupported root attributes;
* converts only roots inside the published framebuffer MC aperture, using
  `physical = FB_OFFSET + (address - FB_BASE)`;
* preserves already-physical and unrelated addresses; and
* leaves the native encoder responsible for preparing and programming registers.

This is compatible with Apple's exact private input layout and encoder, and it is
consistent with NootedRed's broader evidence that APU framebuffer-offset handling
may differ from Apple's supported discrete path. No public Apple or community
source reviewed here independently proves the VMID 1--15 policy. That policy rests
on GFX10 context architecture, independent Linux evidence, and the project's live
captures; it should be described that way.

Likewise, public Metal UMA documentation supports distinguishing system and local
resource placement, but it does not prove that a non-SYSTEM Apple PTE source must
be translated with `MC_VM_FB_OFFSET`. The mode-4 entry conversion remains justified
by captured source/template values, live aperture registers, resulting page-table
contents, and hardware behavior, with the exact binary defining ABI only.

## What remains unresolved

* A native hub-0 VMID1 `prepareVMInvalidateRequest` entry/return capture is still
  needed to prove the faulting root traverses this hook, carries an accepted flag
  form, and becomes `0x84b6ff000` in prepared output.
* No reviewed source maps an `AMDHWVMContext *self` to a specific hub/VMID. Mode 4
  therefore cannot attribute aggregate entry conversions to the faulting VMID.
* The CPU walker deliberately aliases MC-form table addresses through the physical
  framebuffer window. Its readable leaf is not proof that GFXHUB passed the root.
* Successful root preparation would establish only that the CPU-side prepared
  data contains the expected root. The live GPU PTB register, invalidation, page
  walk, and execution must each be observed separately. Acceptance still requires
  progress beyond the VMID1 fault and the project's existing cleanup and host-safety
  evidence.

The next test should remain the bounded, authenticated native VMID1 prepare capture
already specified in the mapping audit. Public source research narrows the claims;
it does not replace that discriminating observation.
