# Driving an AMD Raphael iGPU with Apple's Navi 2x kexts

Target: AMD Granite Ridge / Raphael integrated GPU, PCI `1002:13c0` rev `0xcb`
(GC 10.3.6, MP0+MP1 13.0.5, SDMA 5.2.6, DCN 3.1.x, VCN 3.x, 2 CUs, 512 MB carve-out,
128-bit DDR5). Host CachyOS; guest macOS Sequoia 15.7.9 build 24G830 under QEMU/KVM,
device handed over with `vfio-pci` and spoofed as `1002:73ff` (Radeon RX 6600, Navi 23).

## Status

Development paused at the user's request on 2026-09-07 after testing 1.0.158.
The VM is stopped and research agents are halted. Real Metal execution remains
unproven; the next proposed PSP response-address diagnostic has not been implemented.

### Candidate 1.0.158: EOP writes traced; execution remains blocked

The bounded XQ3 trace observed native EOP low/high/control writes and activation.
The low write used the expected register `0x322e`, value `0xf40b7068`, client
`0xb`, flag 1, and last observed native selector 9 from the same context. ACTIVE
was zero. Both framebuffer and native GC read paths returned EOP zero immediately
before and after the write. Activation subsequently changed ACTIVE to 1 while
EOP stayed zero. This narrows the failure to the write/access state at that
boundary; it does not establish hardware locking or an undocumented clearing rule.
The real Metal compute test still failed with zero completed work.
[Complete trace, verification timing and results](metal-tests/20260907T202943Z-28df30cb/notes.md).

Mode2 now preserves native MEC halt bits in all three write helpers, including
failure cleanup. Legacy suppression remains confined to older modes. Long GART
diagnostics are split so they no longer lose their newline to the log buffer limit.

The earlier retained-host-IC diagnosis has another concrete counterexample:
this run's requested TMR maps to physical `[0x85f400000,0x85fe00000)`, and CPC
IC `0x85f904000` lies inside it at offset `0x504000`. MEC LOAD_IP_FW reports
success, while AUTOLOAD_RLC reports BUSY. Actual response firmware destinations
and submitted-image identity are the next observations needed; unchanged IC
addresses alone cannot distinguish new loading from retention. The TMR lies
beyond the current 256 MiB BAR mapping and must not be read through that mapping.

### Candidate 1.0.157: root and queue addresses validated; KIQ still times out

Native memory validation now checks `+0x50 == GC FB_LOCATION_BASE`, `+0x58 == GC
FB_OFFSET`, and `+0x60 == +0x50 - +0x58`. The earlier relocation assumption is
explicitly isolated to legacy modes. The live run accepted the native fields,
validated the entire `0x202008`-byte flat page table at BAR0+`0xfdfc000`, and
completed a genuine KIQ dequeue in 50 microseconds. MQD/EOP MC arguments remained
`0xf40b706000` / `0xf40b706800`. Native startKIQ returned zero; EOP readback stayed
zero and the first 32-dword submission timed out with RPTR zero.

The physical GART walker and QEMU guest-RAM reads now agree in the same run:
ring VA `0xffbfea0000` maps to guest PA `0x440744000`, containing SET_RESOURCES
and the completion WRITE_DATA packet at dwords 16–20. The poll/report page maps
to `0x450eea000`; `+0x50` holds WPTR 32, while `+0x40` (stamp) and `+0x48` (RPTR)
remain zero. This verifies the software data behind the GART entries, not that
the GPU fetched it. HQD_ERROR `0x100` was already present before dequeue;
its persistence does not prove a new fault from this candidate.

The probe waited for the final native power-up result before running. It found
Metal 3, compiled shaders, and failed the first compute command with the same
`e00002bd` error. Zero values/pixels or completed command buffers were verified.
The exact VM was stopped before its 180-second cap; host logs contain only VFIO
reset/reset-done for this run. [Full evidence](metal-tests/20260907T200936Z-2e1a5b6f/notes.md).

The remaining halt filter's "halting is one-way" rationale is unsupported. All
three filters log their first interceptions, and the only interception in this
run occurs **after** the KIQ stamp timeout. Removing it cannot explain or repair
this run's initial failure. Do not confuse that stale comment with measured cause.

An independent firmware comparison also corrected the assumption that matching
payload lengths imply matching MEC code. HWLibs descriptor `0xd6fc48` points to
Apple's `0x414b0`-byte payload at `0xe602c0`, SHA-256
`af522dc8b71597f4e5e2e5144debbc6b3f50c29e50389e0d54f1c1c4fa29ff18`.
The same-length code portion of Linux `gc_10_3_6_mec.bin` (file offset `0x100`)
has SHA-256 `d8f69e198f8b8607eb35069148100f639b0523c9518fb99f87e6fea421ead2b8`.
Their executable interiors and separate jump tables differ. This establishes a
compatibility question, not a cause of the observed stall or a validated firmware fix.
Linux's direct-load/backdoor paths use GTT GPU addresses for CP_CPC_IC_BASE; PSP
autoload skips those assignments. The retained PSP address being outside the
relocated MC aperture alone therefore does not establish that it is invalid.

### Candidate 1.0.156: native physical root corrected; queue guard rejects

The exact HWLibs binary already implements the physical-root conversion. Its void
`_vm_10_1_get_uma_physical_fb_offset` at `0x33370` stores the physical base at `vm+0x210`.
The UMA branch reads GC FB_OFFSET (falling back to MMHUB); the non-UMA path queries a
memory range and can leave zero. Native page-table initialization at `0x37441..0x37449`
then computes `primaryTableMC - logicalFramebufferBase + physicalFramebufferBase`.
Correcting the native field preserves Apple's register programming and invalidation order.

`rgpuptb=2` calls the original getter, then accepts only the active VM10.3.4 caller
(`0x33edc`, return `0x33ee1`), an original GC10.3.6 discovery record, coherent logical
base/size and GC registers, and a native physical field of zero or the correct value.
It writes only `vm+0x210`. It neither changes global UMA flags nor manually writes PTB.
The getter's exact RIP-free 14-byte prologue is checked before routing. Read-only logs
report the resulting native root and invalidate requests. The GART walker now converts
physical roots to BAR0 offsets, checks the full inclusive table and 48-bit VA range,
and accepts zero software `reserved` when the logical relocation is consistent.

Two further corrections to the historical notebook: EOP_CONTROL 6 is intentional for
Apple's 512-byte KIQ EOP allocation (`startKIQ` at `0x8e6de`, HWLibs `0x152fd..0x15337`).
The earlier FB base `0x840000000` was explicitly established by `rgpufb=1` in archived
`serial-152404.log`; it was not the arrival state of the latest run. That experiment
remains disabled. The candidate builds and passes preflight and address fixtures.

The supervised live run validated the getter and read back Apple's native root
`0x84fdfc001`. It also disproved the plugin's interpretation of `AMDHWMemory+0x58`:
that field became `0x840000000`, causing the queue and walker guards to reject.
The full source chain is `vm_query_mc_address_range` (`0x1e52b..0x1e53a`) exporting
`vm+0x210` to output `+0x18`, then `_ipi_gvm_set_memory_attributes`, TTL framebuffer
services, and `AMDHWMemory::initVRAMInfo` (`0x52808..0x52823`). The result is physical
base at `+0x58` and MC-minus-physical delta at `+0x60`, not the earlier "reserved"
interpretation. The original review missed this query wrapper export.

XQ2 refused startKIQ, so this run does not establish queue behavior with the repaired
root. The test queried Metal before initialization completed and reported device absent;
zero work completed. The exact VM was stopped before its cap and the host remained
responsive. See [full logs and timing limitations](metal-tests/20260907T195407Z-b3d20f94/notes.md).
The next candidate must explicitly validate these native memory fields and wait for
the driver power-up outcome before issuing the probe.

### 2026-09-07 continuation: real Metal execution test fails

Metal 3 enumeration and a creatable `MTLDevice` are established; successful Metal GPU
execution is not. This section supersedes the older hardware-lock, malformed-NOP, and
virgin-VFIO recommendations later in this historical notebook.

Candidate 1.0.155 was loaded and automatically tested at 21:48 local time. It compiled
the Metal shaders, then failed its first compute command with command-buffer status 5,
`MTLCommandBufferErrorDomain` code 1, underlying `e00002bd` (`kIOReturnNoMemory`).
Zero computed values or rendered pixels were verified. The persisted guest log confirms
the KIQ stamp timeout at 21:47:52.406. See the [actual probe output and run notes](metal-tests/20260907T184850Z-d61f1805/notes.md).

This attempt also exposed a host-tooling lifetime bug: detached `sercat.py` and the
background `sleep` watchdog disappeared after the launch tool exited. Serial stopped
before the XQ2 diagnostics, so this run cannot establish whether address preparation
completed. The exact VM was explicitly stopped. A subsequent GPU-less test established
that user-systemd serial capture survives the caller and a timer stops the exact container
at its absolute deadline. The supervision fix subsequently passed 28 tests, independent
review, and a complete GPU-less launch with post-launch service verification. It is deployed.

The supervised repeat at 22:22 local time also failed the native Metal test (zero completed
commands), but captured the missing diagnostics. `XQ2: preparation complete` followed a real
50-microsecond dequeue. Native startKIQ returned zero; EOP stayed zero, EOP_CONTROL stayed 6,
and the subsequent submission stalled at RPTR 0 / WPTR 32 with HQD_ERROR `0x100` (PQ UTCL1).
The old doorbell-8 experiment is gone. The exact container was stopped before its cap;
the host remained responsive. Full evidence is in [this run directory](metal-tests/20260907T192249Z-17682a58/).

This repeat arrived with FB_LOCATION_BASE `0xf400000000`, FB_OFFSET `0x840000000`, and
software `reserved=0`. The old PTB repair rejected zero `reserved` and left CTX0 PTB at
`0x0fdfc001`. A further source correction is necessary: VRAM page-directory entries use
**physical carveout addresses**, while MQD addresses use the MC aperture. Linux's
`amdgpu_gmc_pd_addr` → `gmc_v10_0_get_vm_pde` → `amdgpu_gmc_vram_mc2pa` chain explicitly
performs this conversion before `gfxhub_v2_1_init_gart_aperture_regs` programs CTX0.
The two bases happened to coincide in the earlier `0x840` runs, hiding that distinction.
For the captured table offset, the expected physical root is `0x84fdfc001`, independent
of the MC aperture relocation. Implementing and validating that correction is the next
step; it has not yet established that the rest of KIQ initialization will execute.

Primary source: [Linux GFX10 page-directory conversion](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c),
[root PDE construction](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/amdgpu_gmc.c),
and [GFXHUB register programming](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/gfxhub_v2_1.c).

Re-reading the exact Apple binaries exposed several problems in the experiments:

- `AMDKIQHWChannel::getKIQFrame` initializes **32 dwords**, and `submitKIQFrame` commits
  that count. The first frame contains SET_RESOURCES (`0xc006a000`), padding, and a
  completion WRITE_DATA packet at **dwords 16–20**. `0xffff1000` is a valid single-dword
  NOP; Linux's GFX10 KIQ ring uses the same special NOP. The plugin's doorbell write of
  **8** excluded the completion stamp. Apple was not confusing byte and dword counts.
- `repairMqdPointers` ran after the original submission had timed out and returned its
  failure. It could not repair that power-up attempt. The initial KIQ HQD is programmed
  directly; continuous restoration from the MQD has not been demonstrated.
- Apple programs EOP before checking/dequeuing an active KIQ, whereas Linux programs it
  afterward. Physical-function `WREG32_SOC15_RLC` writes use ordinary MMIO; the special
  RLC path is for supported SR-IOV VFs. An RLC indirect-write requirement is unsupported.
- The archived `serial-205047.log` contains `HQD_ERROR=0x80100`, identifying
  `PQ_UTCL1_ERROR | TC_UTCL1_ERROR`. A clear global fault latch is insufficient to declare
  queue translation healthy, especially when the plugin explicitly clears that latch.
- `startRlc` still wrote `0xaaaaaaaa` and `0xbbbbbbbb` into queue base registers without
  restoring them, despite CP surgery being disabled. That selector test and its scratch
  write test have been removed. They neither established selector behavior nor belonged
  in normal bring-up. No causal link to the host hangs has been proven.

Evidence locations in the exact build's disassembly: x6000 `0x5c716`/`0x5c788`
(submission/frame allocation), `0x8e3ec` (SET_RESOURCES), `0x8e43e`/`0x8e4fd`
(advance 0x40 bytes to the stamp), `0x8e62a` (WRITE_DATA), `0x8e670` (startKIQ).
HWLibs `0x1522f..0x15337` programs EOP before the ACTIVE check at `0x15402` and
dequeue request at `0x15433`. Compare upstream `gfx_v10_0_kiq_init_register`,
`gfx_v10_0_ring_insert_nop_compute`, and `soc15_common.h`'s RLC macro definitions.

The opt-in `rgpumqd=2` candidate validates queue selector 2/1/0, the complete MQD/EOP
allocation, software-to-MC relocation, and image contents before changing the queue.
It then requires genuine dequeue completion within 50 ms, updates the MQD image, and
calls native startKIQ with corrected MC addresses. It fails closed on mismatch or timeout.
It disables legacy post-timeout repair and conflicting reset/cache/aperture experiments.
The earlier XL forced-ACTIVE success is disabled in this mode, including during TTL init;
therefore a run that never logs `XQ2: preparation complete` has not tested the address fix.
Basic RLC start and the existing `rgpuptb=1` correction remain enabled.

`tools/metal-test.py` and `tests/metal_probe.m` now provide automatic execution validation.
The native program compiles in the GPU-less Sequoia guest using its installed Command Line
Tools. Its negative control returns a failed verdict when the Navi23 device is absent.
A positive result requires three completed compute passes with 196,608 correct integers
and an offscreen render/readback of 4,096 coordinate-encoded pixels, with fresh random input
each run. It checks Metal command-buffer status, managed-resource synchronization, a fresh
run ID, and the actual guest process exit status. Compilation and execution are separate
so compilation need not consume GPU exposure time. Permits, delivery expiry, bounded waits,
and cancellation cleanup prevent treating a timed-out command as safely completed.

Host inspection in this continuation found amdgpu owning the iGPU, watchdog and
hardlockup panic sysctls enabled, and the pstore backend set to `efi_pstore`. The discrete
GPU drives the enabled host display. A temporary systemd idle/sleep inhibitor is held for
the work session. No boot configuration change or VFIO-from-boot override is needed.

### Historical ATOM/VBIOS bring-up

**The ATOM/VBIOS stage is solved.** `AMDRadeonX6000_AmdRadeonControllerNavi23::start()`
now succeeds and the GPU brands itself as a Navi 23:

```
[GPUCAP] refresh() --- Family: 143, Device: 0xff00, revNo: 15, pciRevNo: cb, emuRevNo: 75.
[GPUCAP] refresh() --- Mem Size: FB: 512 MB, Aper: 256 MB, Reg Aper: 512 KB.
[GPUCAP] refresh() --- Mem Config: Width: 128, Type: GDDR6.
[GPUCAP] refresh() --- FB Base: 0x100000000, Top: 0x100000000, Offset: 0.
[GPUCAP] refresh() --- Branding - family: "Radeon"; device: "Navi23"; model: "AMD Radeon Navi23".
```

`Width: 128` and `Type: GDDR6` are values synthesised by `mkrom.py`, which is the proof
the driver is parsing the grafted tables. `FB: 512 MB` is read from real hardware and
agrees with the host (`amdgpu ... VRAM: 512M`, `RAM width 128bits DDR5`).

The blocker is now several layers deeper. TTL's SWIP clients initialise in sequence and the
failure has moved through three of them:

| SWIP client | state |
|---|---|
| `BGM` | **complete** — every stage of `bgm_create`, plus VBIOS init and GDDR6 memory training |
| `GVM` | **complete** — UMC, VM, HDP and ATHUB all resolve handlers |
| `PSP` | SW_INIT **complete** |
| `SMU` | SW_INIT **complete** |
| `PSP` HW_INIT | **complete** — TOC accepted (`tmr_size=0xa00000`), TMR established, every firmware blob loads with status 0 |
| `SMU` HW_INIT | current blocker — "SMU init/power-up failed". Apple implements only `smu_9_0*`/`smu_11_0*`; this silicon needs `smu_13_0_5`. |

Getting here took, in order: OpenCore kext injection so the patches land before `start()`;
removing a self-inflicted conflict between the two patch mechanisms; the ASIC capability entry;
the UMC version; and — before any of it could be read at all — a diagnostics channel that
survives both concurrent serial writers and the absence of `logd`.

## Method

Measurement is the whole game here, and two instruments matter:

- **`log show --predicate 'senderImagePath CONTAINS "AMD"'`** in the guest. These kexts log
  through `os_log`; an early pass that read only the serial console wrongly concluded
  "nothing beyond the wrangler runs", when in fact the entire stack loads.
- **Serial with `debug=0x108`.** The ATOM asserts and the whole AMD TTL COS assert stream go
  through `kprintf`, which reaches the 16550 only when `DB_KPRT` (0x8) is set in `debug`.
  Boot-args are now `-v keepsyms=1 tlbto_us=0 vti=9 serial=3 debug=0x108`. This removes the
  need to log in between experiments and is what makes iteration tolerable.

Static analysis uses the **Kernel Debug Kit for build 24G830**, which ships the real Mach-O
binaries. On an installed system every AMD kext bundle is a stub: the code is prelinked into
`SystemKernelExtensions.kc` and `/System/Library/Extensions` has nothing to disassemble.

Recipe that works on Linux:

```sh
llvm-objdump --macho -d --x86-asm-syntax=intel --no-show-raw-insn <bin> > out.asm
```

Two gotchas: `--start-address` is ignored for Mach-O (dump once, slice by address), and rip
displacements are printed **unresolved** — the target is `next_insn_addr + disp`. The ATOM
classes carry no symbols at all, but every one of them is identifiable from the
`__PRETTY_FUNCTION__` string its `ASSERT` macro passes, and `llvm-objdump` helpfully
annotates those string loads (`## literal pool for: "..."`).

## How the VBIOS actually reaches the driver

`AMDRadeonX6000_AmdBiosParserHelper::readAtomBios` (VMA `0x170b4`) tries exactly two sources:

1. `readEfiAtomBiosImage` (`0x17188`) — reads the **`ATY,bin_image`** OSData property off the
   GPU's `IOPCIDevice`. Checked first; wins outright when present and valid.
2. `readPciAtomBiosImage` (`0x17294`) — the PCI expansion ROM. It starts with
   `extendedConfigRead32(0x30)` and **returns NULL immediately if that register reads 0**.

QEMU's `romfile=` populates the expansion ROM BAR, but **that path is dead in this VM**:
`info pci` reports `BAR6: 32 bit memory (not mapped)` for the passed-through device, because
EDK2's PciBus driver allocates an option-ROM BAR only transiently during enumeration and then
releases the resource. The same is true of the emulated VGA and NIC. So config offset 0x30
reads 0 and Apple gives up without reading a byte. **Delivery must be `ATY,bin_image`.**

Both readers copy at most `0x10000` bytes, and `validateAtomBiosImage` (`0x17062`) requires:

- `img[0..1] == 55 AA`
- `img[2]` (size in 512-byte blocks) non-zero and `<= len`
- 8-bit sum of zero over `img[2] * 512` bytes

`AmdAtomFwHelper` then sets `m_biosSize = img[2] << 9`, and its bounds-checked accessor
(`0x547e0`) refuses any table crossing that limit. **Apple can therefore never see more than
64 KiB of VBIOS**, which incidentally means a real 1 MB discrete Navi 23 ROM cannot be
injected at all — only its first legacy image could.

## The ATOM fix

`AmdAtomFwServices::initializeAtomDataTable` builds its data-table objects from the **master
data table**, whose offset is `ATOM_ROM_HEADER + 0x20` (here `0x0210`). Two slots are
`0x0000` in an APU ROM, and each trips `ASSERT(0 != tableOffset)`:

| slot | master-data index | byte in ROM | wanted by |
|---|---|---|---|
| PSP directory | 9 (`sw_datatable9`) | `0x0226` | `AmdAtomPspDirectory::createPspDirectory` (`0x58320`) |
| `vram_info`   | 28                 | `0x024c` | `AmdAtomVramInfo::createVramInfo` (`0x59860`) |

> **Correction to an earlier version of this document.** It blamed
> `atom_rom_header_v2_2.pspdirtableoffset` (ROM `0x01ae`). That field *is* zero, but **Apple
> never loads it** — no instruction in the kext reads it. Patching it changes nothing; the
> live slot is master-data index 9. This cost one full boot cycle to discover.

The parsers are undemanding, which is what makes a graft viable:

`createPspDirectory(helper, tableOffset)` requires `format_revision == 2`. `content_revision`
1 selects `AmdAtomPspDirectory_V2_1` and requests **`0x414` bytes**; anything else selects
`_V2_6` and requests `0x424`. The body starts after the 4-byte ATOM common header and is the
ordinary AMD PSP directory: `$PSP` magic, checksum, **`num_entries` as a u32 at body+0x08**,
`additional_info`, then 16-byte entries from body+0x10 (`type`, `size`, `addr`). The entry
walker (`0x587f0`) returns immediately when `num_entries == 0`, so **an empty directory is
legal** and no real firmware payload is needed.

`createVramInfo(helper, tableOffset)` accepts `format_revision == 2` with
`content_revision` 3 (`0x358` bytes), 4 (`0x3d8`), 5 (`0x558`) or 6 (`0x358`) — **not v3.0**.
For v2.6 the module count is a u8 at `+0x14` (must be `<= 0x0f`) and modules start at `+0x18`
with stride `0x34`. Of each module, `getVramInfo` (`0x5a116`) reads exactly:

| module offset | meaning |
|---|---|
| `+0x00` (u32) | memory size |
| `+0x16` | ext_memory_id |
| **`+0x17`** | **memory_type** |
| **`+0x18`** | **channel_num** |
| **`+0x19`** | **channel_width** — memory width is `channel_num << channel_width` |
| `+0x1c` | vendor rev id |

And `AMDRadeonX6000_AmdAsicInfo::populateMemoryConfig` (`0x3bd54`) is trivial: it fails only
if memory type or memory width is **zero**. There is no enum validation whatsoever.

`mkrom.py` therefore appends to the 44544-byte Raphael dump:

- an `atom_vram_info` v2.6 at `0xae00` — 1 module, `memory_type = 0x70` (GDDR6),
  `channel_num = 8`, `channel_width = 4` (→ 128-bit)
- a PSP directory v2.1 at `0xb160` with `num_entries = 0`

then rewrites the two u16 master-data slots, pads to `0xb600` (91 blocks, comfortably under
the 64 KiB ceiling) and fixes the checksum byte at `0x21` so the image sums to zero again.
`ocprop.py` injects the result as `ATY,bin_image` under `PciRoot(0x0)/Pci(0x6,0x0)`.

Note the device path: the pre-existing `PciRoot(0x1)/Pci(0x1F,0x0)` entry in this config is
**never applied** — the guest still reports the ISA bridge's native `device-id = <18290000>`.
`PciRoot(0x0)` is correct, confirmed both by `acpi-path = IOACPIPlane:/_SB/PCI0/SF8@1f0000`
and by OVMF booting from `PciRoot(0x0)/Pci(0x4,0x0)/Sata(...)`.

## The ceiling, measured

```
[Accel] --- Before TTL:initialize() - BootLoader Version=0x00420024, POST Code=0xffffffff, Ready=0xffffffff
AMD Error: [0:6:6] Error SW_IP_CLIENT_ID__BGM: event_id=0xc00c0203 ... type=3 hw_id=0
AMD TTL COS: ASSERT FUNCTION: ipi_bgm_create   FILE ../../../src/ipi/ipi_bgm.c   LINE 180
AMD TTL COS: ASSERT REASON:   Call to bgm_create was unsuccessful!
AMD TTL COS: ASSERT FUNCTION: IpiValidateTopology  FILE ../../../src/ipi/ttl_ipi.c  LINE 616
AMD TTL COS: ASSERT REASON:   pBgmContext is null!
panic(cpu 2 ...): "[0:6:0][PPLIB] Failed to send PPLIB IRI to Accelerator. TTL Error Message: {...BGM...}"
```

`bgm_create` (HWLibs VMA `0x232ee0`) brings the IP blocks up in order and logs one error id per
stage, so the id names the stage exactly:

| event id | stage | discovery id |
|---|---|---|
| `0xc00c0201` | `bcs_create` | — |
| `0xc00c0202` | `ipconfig_create` | — |
| **`0xc00c0203`** | **`bif_ip_create`** | `0x42` |
| `0xc00c0204` | `bio_create` | `0x3d` |
| `0xc00c0205` | `mp0_ip_create` | `0x4b` |
| `0xc00c0206` | `sem_ip_create` | `0x21` |
| `0xc00c0207` | `smuio_ip_create` | — |
| `0xc00c0208` | `vbs_create` | — |

`ipconfig_create` **succeeded**, and that is the decisive fact: it reads the PCI config space
*and* parses the silicon's real **IP discovery table**, and every IP constructor then dispatches
on `get_hw_revision(major, minor, rev)` = `major<<16 | minor<<8 | rev` (VMA `0x234440`, verified).
**HWLibs therefore drives itself off Raphael's actual IP versions, not off the spoofed PCI id.**
No VBIOS graft and no device-id patch can reach it.

### This chip's IP versions

Read from `/sys/bus/pci/devices/0000:7b:00.0/ip_discovery/die/0/<IP>/0/{major,minor,revision}`,
which exists only while `amdgpu` owns the device:

| IP | version | | IP | version |
|---|---|---|---|---|
| **NBIF** | **7.3.0** | | GC | 10.3.6 |
| PCIE | 6.0.0 | | DMU (DCN) | 3.1.5 |
| **MP0 (PSP)** | **13.0.5** | | SDMA0 | 5.2.6 |
| MP1 (SMU) | 13.0.5 | | OSSSYS | 5.2.1 |
| MP2 | 13.0.5 | | MMHUB / ATHUB | 2.4.1 |
| SMUIO | 13.0.10 | | UMC | 9.5.0 |
| THM / CLKA / FUSE | 13.0.4 | | HDP | 5.2.0 |
| DF | 4.0.1 | | IOHC | 7.0.1 |

### Gate 1 — NBIF: a real bug we can legitimately patch

`bif_ip_create` (`0x239931`) calls `get_hw_revision` with `rev` forced to 0 and accepts exactly:

| version | handler | | version | handler |
|---|---|---|---|---|
| 2.3 | `nbio2_3_initialize` | | 7.0 | `nbio7_0_initialize` |
| 2.5 | `nbio7_0_initialize` | | 7.2 | `nbio7_2` / `nbio7_2_1` (rev) |
| 3.3 | `nbio3_3_initialize` | | 7.4 | `nbio7_4_initialize` |
| 4.3 | `nbio4_3_initialize` | | 7.5 | `nbio7_2_1` / `nbio7_2` |
| 5.0 | `bif50_initialize` | | 7.6 | `nbio7_4_initialize` |
| 6.1 / 6.2 | `bif6_1` / `bif6_2` | | 7.7 | `nbio7_7_initialize` |

**7.3 is missing** — that is why stage 03 fails. It is a gap, not an incompatibility: Linux's
`amdgpu_discovery.c` maps `IP_VERSION(7, 3, 0)` onto `nbio_v7_2_funcs`, the same handler Apple
already has. So widening the 7.2 compare to 7.3 is a legitimate one-immediate patch:

```
0x239a84:  41 81 ff 00 02 07 00   cmp r15d, 0x70200
        →  41 81 ff 00 03 07 00   cmp r15d, 0x70300
```

The find pattern `4181ff000207000f85e8feffff` is **unique** in the binary. It is staged (disabled)
in `config.plist` as an OpenCore `Kernel > Patch` against
`com.apple.kext.AMDRadeonX6000HWLibs`, which needs no compiler and no kext.

### Gate 2 — MP0: the absolute wall

`mp0_ip_create` (`0x244083`) passes the **real revision** through and gates on:

```
244103:  call  _get_hw_revision
244108:  mov   ecx, eax
24410c:  add   ecx, 0xfff50000      ; ecx -= 0xB0000
244112:  cmp   ecx, 0xd  ; ja fail
244117:  mov   edx, 0x38a1
24411c:  bt    edx, ecx  ; jae fail   ; 0x38a1 = bits {0,5,7,11,12,13}
24412e:  jmp   _mp0_11_0_0_initialize
```

Accepted: **MP0 11.0.{0, 5, 7, 11, 12, 13}, and nothing else.** Ours is 13.0.5, so
`0xD0005 - 0xB0000 = 0x20005 > 0xd` → rejected.

A sweep of **all seven** HWLibs plugins:

```
AMDRadeonX6000HWLibs  mp0=[_mp0_11_0_0_initialize]  psp13=0  smu13=0  gc=[_gc_10_3_4_get_fw_constants]
AMDRadeonX6100/6200/6300/6700HWLibs   same single mp0, psp13=0, smu13=0
AMDRadeonX6800/6810HWLibs             same single mp0, psp13=0, smu13=0
```

**There is exactly one PSP implementation in the entire Sequoia AMD stack and it is MP0 11.0.x.**
No PSP-13 symbols, no SMU-13 symbols, and only `gc_10_3_4` microcode. Switching plugins changes
nothing.

That is a categorically different wall from the VBIOS one. The VBIOS stage failed because
Apple's code wanted **data** that an APU ROM does not carry — so the data could be synthesised.
Here the **code does not exist**: PSP 13 and SMU 13 differ from PSP 11 / SMU 11 in bootloader
command set, register bases and message tables. Forcing `mp0_11_0_0_initialize` onto MP0 13.0.5
would be pointing the wrong protocol at a live security processor that is part of the CPU SoC and
shared with the running host — and even if it survived, MP1/SMU 13.0.5, UMC 9.5.0 and DCN 3.1.5
each hit the same "no implementation" gate immediately after.

Getting past this means porting AMD's PSP-13, SMU-13 and DCN-3.1.5 drivers into a closed-source
kext. That is the NootedRed-class project, and the ChefKiss maintainers have had exactly this
open for RDNA 2 APUs since 2023.

### Gates 3 and 4 — GC and SMU are exact-match rejections too

An earlier draft of this document guessed that GC would be "close" because 10.3.6 and Navi 23's
10.3.4 are both RDNA 2. That was wrong. HWLibs' GC dispatch `_gc_init_fcn_ptr_list` (VMA `0x8ea1`)
accepts exactly GC {8.0.10, 9.0.1, 9.2.1, 9.4.0, 10.1.0, 10.1.1, 10.1.10, 10.3.0, 10.3.2, 10.3.4,
10.3.5}. **GC 10.3.6 falls off the very first range check** (`lea eax,[r14-0xa0300]; cmp eax,6;
jb`) and lands on `gc_assertion("Invalid hc version", gc_internal.c:609)`. There is no generic
10.3.x fallback and no `gc_10_3_6` anything in the KDK; `_gc_set_fw_entry_info` (`0xa108`) is
narrower still — blobs exist only for 10.3.0 and 10.3.4.

Power is the same shape, and it is where the current PPLIB panic already sits: `_smu_get_hw_version`
(`0x726ac`) *knows* the 13.0.x enum (13.0.5 → 18), but `_smu_init_function_pointer_list`
(`0x72b33`) caps at enum 10 and asserts `"Unsupported hw version!"`. Apple's build carries the
enumeration for SMU 13 and none of the implementation.

And the firmware can never be delivered even in principle: the complete Navi 23 blob set *is*
present (CP ME/PFP/CE/MEC, RLC + LX6 IRAM/DRAM + TOC + SRLIST, SDMA 5.2.4, MES 10.3.4,
SMU 11.0.12, PSP SOS/sys_drv/key_database), but every blob carries a `$PS1` PSP-signed header and
is loaded **by the GPU's own PSP** — which here is the SoC's, running v13, for which Apple has no
code at all.

### Where the IP versions come from — and why they cannot be forged

`ipconfig_create` (`0x244ec1`) is an almost instruction-for-instruction clone of Linux's
`amdgpu_discovery.c`: it reads `mmIP_DISCOVERY_VERSION` (dword register `0x16A00`) and
`create_discovery_tbl` (`0x245550`) dispatches on it — **1** → hardcoded base table with versions
read from *registers*, **2** → the Linux-style binary in VRAM, **3** → hardcoded plus RSMU.

The v2 path reads `mmRCC_CONFIG_MEMSIZE`, computes `pos = (memsize << 20) - 0x10000`
(`DISCOVERY_TMR_OFFSET`) and pulls 64 KB through `mmMM_INDEX`/`mmMM_INDEX_HI`/`mmMM_DATA`,
validating `BINARY_SIGNATURE 0x28211407`, `"IPDS"` and `"HARV"` with their checksums.

**On this chip that region is unreadable.** A 2 MB dump of the top of the carve-out
(`findings/hw/vram_tail.bin`, taken through `debugfs/amdgpu_vram`) reads **all `0xff` at
`512 MB - 64 KB`** — it is inside the PSP's Trusted Memory Region. Since macOS's
`ipconfig_create` nevertheless *succeeded*, it must be taking the version-1 or version-3 path,
i.e. reading IP versions out of **registers**. So the "write a synthetic Navi 23 discovery table
into VRAM" idea is dead twice over: the memory is protected, and it is not where the versions are
being read from anyway. Faking them would mean hooking the register-read helper from a kext.

The same all-ones behaviour explains a live defect: `AmdAsicInfoNavi2::populateDeviceInfo`
(Framebuffer `0x3b252`) reads `mmRCC_DEV0_EPF0_STRAP0` at dword index `0xD31`, gets
`0xFFFFFFFF`, and reports `Device: 0xff00, revNo: 15, emuRevNo: 75` — and emuRev 75 falls outside
DAL's Dimgrey window [60,69] *and* outside `dc_clk_mgr_create`'s valid NV range [40,69].

### Full per-IP verdict

Chip column is this silicon's real IP-discovery values, read from
`/sys/bus/pci/devices/0000:7b:00.0/ip_discovery/die/0/<IP>/0/{major,minor,revision}` — which,
contrary to an earlier note here, **is readable with no driver bound at all**, so this measurement
needs neither `amdgpu` nor root.

| Apple id | IP | Chip | Verdict | Gate |
|---|---|---|---|---|
| `0x42` | NBIF | **7.3.0** | **FAIL** (current blocker) | `_bif_ip_create` `0x239931` |
| `0x3d` | PCIE | 6.0.0 | pass | `_pcie_ip_create` `0x2464f1` |
| `0x4b` | MP0 / PSP | **13.0.5** | **FAIL** | `_mp0_ip_create` `0x244083` |
| `0x21` | OSSSYS / SEM | 5.2.1 | pass | `_sem_ip_create` `0x24a569` |
| `0x07` | SMUIO | **13.0.10** | **FAIL** (13.0.6/7 only) | `_smuio_ip_create` `0x2497a4` |
| `0x0b` | GC / GFX | **10.3.6** | **FAIL** | `_gc_init_fcn_ptr_list` `0x8ea1` |
| — | GMC / VM | **10.3.6** | **FAIL** | `_vm_ip_version_mapping` `0x115c9e0` |
| `0x46` | UMC | **9.5.0** | **FAIL** (fatal in `mc_sw_init`) | `_mc_ip_version_mapping` `0x115c430` |
| `0x22` | HDP | 5.2.0 | pass | `_hdp_ip_version_mapping` `0x115c750` |
| `0x1c` | ATHUB | **2.4.1** | **FAIL** — off by one revision (2.4.0 accepted) | `_athub_ip_version_mapping` `0x115d9a0` |
| `0x1b` | MMHUB | **2.4.1** | **FAIL** — no `mmhub_2_4` code exists | symbol survey |
| `0x27` | DF | **4.0.1** | **FAIL** | `_df_create` `0x21d8` |
| `0x04` | MP1 / SMU | **13.0.5** | **FAIL** — enum known, no fn-ptr list | `_smu_init_function_pointer_list` `0x72b33` |
| `0x23` | SDMA0 | 5.2.6 | pass (generic 5.2 path for rev ≥ 6) | `_sdma_init_function_pointer_list` `0x5e871` |
| `0x0c` | VCN | 3.1.2 | pass | `engine_init_pfn_ptr` |
| — | JPEG | 3.1.2 | **FAIL** (2.0/2.2 only) | `jpeg_engine_init_pfn_ptr` |
| `0x10` | DMU / DCN | **3.1.5** | **FAIL** — resource-pool ceiling is dcn302 | `dc_create_resource_pool` `0xb31b4` (Framebuffer) |

**5 pass, 11 fail.** Failure order along the real bring-up: NBIF → MP0 → SMUIO → then the SWIP
layer: GC, VM, UMC, ATHUB, MMHUB, SMU, DF, DCN.

Some of these are one-immediate byte patches (NBIF 7.3, ATHUB 2.4.1→2.4.0, MP0/SMUIO/GC/VM/UMC
routing). Three are not patches at all, because no implementation exists to route to:
**MMHUB 2.4**, **SMU 13** (`_smu_init_function_pointer_list` caps at enum 10 and asserts
`"Unsupported hw version!"`), and **DCN 3.1.5** (DAL's 16-entry resource-pool jump table stops at
dcn302). DCN is the least painful of the three to live without — the guest desktop can stay on
QEMU's emulated adapter — but MMHUB and SMU sit directly in the compute path.

### Delivery: what it took to get a byte patch into a live AMD kext

**This works now.** Both m1 patches apply at runtime, confirmed from the guest's own log:

```
rgpu: @ registered 2 kexts (Loaded flag set)
rgpu: @ kext callback: index=1 hwlibs=1 fb=2 addr=ffffff7fa99d4000 size=28327936
rgpu: @ HWLibs loaded, mask=0x1
rgpu: @ APPLIED  m1 bif_ip_create: accept NBIF 7.3.0
rgpu: @ kext callback: index=2 hwlibs=1 fb=2 addr=ffffff7fa96b5000 size=3244032
rgpu: @ Framebuffer loaded, mask=0x1
rgpu: @ APPLIED  m1 doGPUPanic: do not panic on TTL failure
```

The `doGPUPanic` patch has a measurable effect: **`panics: 0`**, where every previous boot with
the GPU attached died in `doGPUPanic`. The guest now survives a TTL failure and stays usable,
which is what makes reading the driver's `os_log` with the GPU attached possible at all. The
guest also now enumerates the device fully — `Chipset Model: AMD Radeon Navi23`,
`VRAM (Total): 512 MB` (that VRAM line was previously absent).

The mechanism is a Lilu plugin (`RaphaelGPU.kext`) cross-compiled entirely on Linux, installed
into the guest's `/Library/Extensions` and linked into the **Auxiliary** kernel collection
beside Lilu. Getting there required, in the order each error revealed the next:

| # | symptom | actual cause |
|---|---|---|
| 1 | patch had no effect | OpenCore `Kernel > Patch` cannot reach `SystemKernelExtensions.kc` |
| 2 | plugin never ran | Lilu self-disables on Darwin 24; needs `-lilubetaall` |
| 3 | `Invalid Parameter` | **not the binary.** `RaphaelGPU.kext` declares `as.vit9696.Lilu` in `OSBundleLibraries`, and `Lilu.kext` was `Enabled=false` in `Kernel > Add`, so the dependency could not resolve. Enable **both** and injection succeeds. |
| 4 | `Failed to bind '_lilu'` | Lilu must exist **on disk**; `kmutil` resolves only on-disk repositories |
| 5 | `Missing Developer Kit` | a build-matched KDK must be installed **in the guest** |
| 6 | `Read-only file system` | `kmutil install --update-all` wants the sealed volume; build only `-n aux` |
| 7 | `Failed to bind '___cxa_atexit'` | **real bug**: kernel has no `__cxa_atexit`; use `-fno-c++-static-destructors` |
| 8 | every redeploy silently no-op | **`kmutil` dedupes by bundle id + version** — a fixed `CFBundleVersion` produced a byte-identical collection (same UUID) and the guest kept loading the first binary. Bump the version every build. |

Prerequisites for the AuxKC route: `csrutil` with Kext Signing **disabled**; kexts `root:wheel`;
`-lilubetaall`; a guest-installed KDK matching the build.

### The AuxKC is the wrong delivery vehicle — use OpenCore injection

The Auxiliary collection loads **after** the collections holding the AMD stack, so
`AmdRadeonControllerNavi23::start()` has already run and failed before a plugin in the AuxKC
can patch anything. Measured on one boot: `rgpu start` at serial line 1189, `[GPUCAP]` (i.e.
`start()` already running) at 1211, the BGM failure at 1309, and our HWLibs patch landing at
1459 — about 200 lines too late. The only patch that ever worked from there was `doGPUPanic`,
purely because that call site happens to be reached *after* 1459.

Two escape attempts failed and are worth recording:

- **`onPatcherLoad`** never fired at all, because Lilu's patcher initialises before an AuxKC
  plugin's `pluginStart` registers the callback.
- **`requestProbe(0)`** on the GPU's `IOPCIDevice` (milestone `p1`) produced no re-match: zero
  `reprobe` lines and still exactly one `[GPUCAP] refresh()` block. IOKit does not re-run
  `start()` for a driver that is already attached.

The fix is to stop working around the load order and put **both** `Lilu.kext` and
`RaphaelGPU.kext` in `Kernel > Add` so OpenCore injects them into the **boot** collection —
which is what Lilu is designed for and how WhateverGreen patches these same AMD kexts. With
that, `rgpu start` moves to line 129 and every patch lands before `TTL::initialize()`:

```
 129  rgpu: @ start, patch mask=0x981
1182  rgpu: @ APPLIED  m1 doGPUPanic
1200  rgpu: @ SKIPPED  m1 bif_ip_create (R1 already remaps this version)
1205  rgpu: @ route check_pcie_link_status -> ok
1221  [0:6:0] [Accel] >>> Calling TTL::initialize()
```

`esp-kext.sh` pushes a freshly built bundle into the ESP image; `oc-inject.py on|off|list`
toggles the `Kernel > Add` entries.

**Do not patch from `onPatcherLoad` even once you load early.** `loadKinfo()` there maps the
kext's *file* so symbols can be solved, but leaves its running address at 0, and the one-argument
`applyLookupPatch(patch)` dereferences exactly that address. It page-faults with `CR2=0`, `RDI=0`
inside `KernelPatcher::applyLookupPatch+0x28e`. Patch from the kext-load callback instead.

### The two patch mechanisms cancel each other out

Every `m2`…`m7` byte patch widens a version gate so this chip's *real* version is accepted.
`r1` solves the same problem from the opposite side: it rewrites the version Apple *sees* to
one already accepted. Enabling both is not additive, it is destructive — `r1` handed
`bif_ip_create` 7.2.0 while `m1a` had just patched the comparison to demand 7.3.0, so the
compare missed and BIF failed with `bif_ip_create returned 1`. `RPatch` now carries an
`r1Conflict` flag and such patches are skipped, loudly, when `r1` is on. Removing that one
conflict moved the failure **eight stages** down the ladder.

### `*_ip_version_mapping` cannot be reached by a byte search

`m5`, `m6` and `m7` rewrite rows of the mapping tables, and their find patterns include the
row's 8-byte function pointers. Those addresses appear in the kext's `DYSYMTAB` **local
relocation** list (`locreloff`/`nlocrel` — note these are fields 16 and 17 of the command, not
14 and 15), so the kernel collection rebases them at load and the pattern can never match at
runtime. The version fields alone are not unique enough to search on. These rows need a
computed-address edit off the kext base, not `applyLookupPatch`. `milestones.py verify` cannot
catch this: it checks uniqueness in the on-disk KDK, where the values are still unrelocated.

### Inside `bgm_create`: the stage ↔ `event_id` ladder

`event_id=0xc00c02NN` in the `SW_IP_CLIENT_ID__BGM` error is not a generic "BGM failed" code.
`bgm_create` (`0x232f2e`) loads a distinct id into `esi` on each stage's failure branch, so the
id names **exactly which call returned nonzero**. Read off the disassembly:

| `event_id` | failing call | lookup id |
|---|---|---|
| `0xc00c0202` | `ipconfig_create` | — |
| `0xc00c0203` | `bif_ip_create` | `0x42` NBIF |
| `0xc00c0204` | `bio_create` | `0x3d` PCIE |
| `0xc00c0205` | `mp0_ip_create` | `0x4b` MP0 |
| `0xc00c0206` | `sem_ip_create` | `0x21` |
| `0xc00c0207` | `smuio_ip_create` | `0x07` SMUIO |
| `0xc00c0208` | `vbs_create` | — |
| `0xc00c0209` | `smuio_sw_init` | — |
| `0xc00c020a` | `bif_ip_sw_init` | — |
| `0xc00c020b` | `bio_sw_init` | — |

This turns every boot into a precise position on the ladder instead of a guess. Fixing the
`m1a`/`r1` conflict moved it from `0xc00c0203` straight to `0xc00c020b`, i.e. MP0 13.0.5,
SEM, SMUIO 13.0.10, the whole VBIOS path (`vbs_create`, `vbs_hw_init`, GDDR6 memory training),
`smuio_sw_init` and `bif_ip_sw_init` **all pass**. The earlier write-up called MP0 "the absolute
wall"; with `r1` in place it is not one.

### This chip's real IP table, as Apple resolves it

`d1` hooks `ipconfig_get_ip_discovery_info` and dumps Apple's internal table on the first call.
Apple's ids are its own, not the discovery `hw_id`s. All 19 entries:

| id | version | | id | version | | id | version |
|---|---|---|---|---|---|---|
| `0x42` | 7.3.0 NBIF | | `0x1c` | 2.4.1 ATHUB | | `0x4c` | 0.0.0 |
| `0x3d` | 6.0.0 PCIE | | `0x27` | 4.0.1 | | `0x4d` | 0.0.0 |
| `0x07` | 13.0.10 SMUIO | | `0x4b` | 13.0.5 MP0 | | `0x4f` | 0.0.0 |
| `0x21` | 5.2.1 | | `0x04` | 13.0.5 | | `0x0c` | 3.1.2 |
| `0x0b` | 10.3.6 GC | | `0x23` | 5.2.6 SDMA | | `0x10` | 3.1.5 |
| `0x1b` | 2.4.1 MMHUB | | `0x24` | 0.0.0 | | | |
| `0x22` | 5.2.0 | | `0x46` | 9.5.0 UMC | | | |

**Read this table from `os_log`, not from serial.** Serial output from other CPUs interleaves
mid-line: `id=0x3d` arrived split as `id=0x 3` with the `d` starting the next line, and reading
it as `0x3` produced a confident, entirely wrong conclusion that PCIE was absent from this chip
and a patch built on that premise. `pcie_ip_create` opens with `cmp dword ptr [rsi], 0x3d` — had
the id really been missing, that would have dereferenced NULL and panicked, which it never did.
When a dump contradicts the code's own control flow, suspect the instrument first.

### Past the ladder: the ASIC capability table

Clearing the BGM stages is not sufficient. `ipi_bgm_create` also calls
`ttlSetDeviceCapabilityEntry` → `DevGetDeviceInfoEntry` (`0xaf0e0`), which walks a static
`_DeviceCapabilityTbl` (VMA `0x557240`, 269 entries, stride `0x50`) and requires **three**
keys to agree:

| offset | key | wildcard |
|---|---|---|
| `+0x10` | PCI device id | — |
| `+0x18` | **internal** revision id (`ttlSetInternalRevisionId`) | `0xdeadcafe` |
| `+0x20` | **external** revision id (`ttlSetExternalRevisionId`) | `0xdeadcafe` |

A miss makes `ttlSetDeviceCapabilityEntry` log `Could not find device info table entry!`
(`ttl_device.c:587`) and `ipi_bgm_create` abort with `Failed to create bgm context. Cleaning
up.` — with **no `event_id` at all**, which is why this failure looks like nothing when you
grep only for `0xc00c02NN`.

The table's last entries are the interesting ones:

```
 261  family 0x8f  devid 0x73ff  internal 0  external 0x40
 ...
 268  family 0x8f  devid 0x73ff  internal 0  external 0xcb
```

`0xcb` **is this chip's real PCI revision**, and `[GPUCAP]` reports `pciRevNo: cb`. So Apple
already ships an exact capability entry for the identity we present; only the *internal*
revision id can be missing it. Milestone `x2` routes `DevGetDeviceInfoEntry` to log all three
keys and, on a miss, retry with the internal revision values Apple's own table actually uses —
which is preferable to editing Apple's table, because a wildcard there would apply to every
`0x73ff` in the system.

### The PCIe root port: OVMF gets it right, macOS undoes it

`check_pcie_link_status` needs one of device-info slots 3, 1 or 7 to expose a PCIe capability
offset, and all three read 0:

```
rgpu: @ check_pcie_link_status -> 1  (pcie cap offset: dev3=0x0 dev1=0x0 dev7=0x0)
```

The cause is topological. `-device vfio-pci,...,bus=pcie.0` makes the GPU a **Root Complex
Integrated Endpoint**, which has no link and therefore no link registers, so the correct fix
looks like putting it behind a `pcie-root-port`. That does produce the right topology — the GPU
lands on bus 1 behind the port — but it is **not usable**, and the reason is worth recording
because the failure mode is silent: the AMD driver simply never matches.

Polling `info pci` across the boot shows why:

```
15:52:28  rp0 pref=[0x800000000, 0x8101fffff]      gpu unmapped BARs = 0    <- OVMF, correct
15:53:18  rp0 pref=[0xfffffffffff00000, 0x000fffff] gpu unmapped BARs = 3    <- macOS took over
```

OVMF sizes and programs the bridge window correctly (256 MiB + 2 MiB of prefetchable space at
32 GiB, every BAR mapped); macOS's PCI configurator then disables the window and unmaps every
BAR. Tested with and without QEMU's resource-reservation hints
(`io-reserve`/`mem-reserve`/`pref64-reserve`), with `hotplug=off`, and with `npci=0x2000` — the
teardown happens in all four. The GPU therefore stays directly on `pcie.0` and the missing link
registers are handled in the driver (`x1`) instead. Do not reintroduce the root port without
solving the teardown first; `macos-vm.sh` carries this warning at the device line.

### Two more SWIP clients cleared: GVM, and how the readout was fixed first

With the ASIC capability entry found, BGM completes and the failure moves to the next SWIP
client. The error text names it:

```
TTL Event source_id=2 event_id=0x900c0401 : swip_client_id=5 : (SW_IP_CLIENT_ID__GVM, EVENT__SW_INIT)
ASSERT logSwipFailure:       GVM init/power-up failed
ASSERT TlsExecuteIpEntrySeq: SWIP init/power-up failed
```

`gvm_sw_init` (`0x192f4`) runs `mc_sw_init` → `vm_sw_init` → `hdp_sw_init` → `athub_sw_init`
and returns the first nonzero, with **no per-stage event id**, so the id alone cannot say
which failed. All four resolve handlers through one chokepoint, `gvm_get_ip_function`
(`0x19258`), whose table argument identifies the caller unambiguously:

| table offset | symbol |
|---|---|
| `+0x115c430` | `_mc_ip_version_mapping` |
| `+0x115c750` | `_hdp_ip_version_mapping` |
| `+0x115c9e0` | `_vm_ip_version_mapping` |
| `+0x115d9a0` | `_athub_ip_version_mapping` |

Tracing it named the failure in one boot:

```
gvm_get_ip_function(9.5.0 fn=0 tbl=+0x115c430 n=18) -> MISS
```

**UMC.** The host's own IP discovery reports `UMC 9.5.0` and Apple's table has no 9.5.0 row.
The fix is not a guess: `gmc_v10_0_set_umc_funcs` wires UMC for `IP_VERSION(8, 7, 0)` and
nothing else across all of Navi 2x — the offset constant is literally
`UMC_V8_7_PER_CHANNEL_OFFSET_SIENNA` — so 8.7.0 is what a real Navi 23 reports and what
Apple's Navi 23 support is written against. With `UMC 9.5.0 -> 8.7.0` added to `r1`, all four
resolve and GVM completes:

```
gvm_get_ip_function(8.7.0  fn=0 tbl=+0x115c430) -> ok      UMC
gvm_get_ip_function(10.3.4 fn=0 tbl=+0x115c9e0) -> ok      VM
gvm_get_ip_function(5.2.0  fn=0 tbl=+0x115c750) -> ok      HDP
gvm_get_ip_function(2.4.0  fn=0 tbl=+0x115d9a0) -> ok      ATHUB
```

### A lazy remap is not enough — rewrite the table itself

`r1` originally rewrote a version inside the accessor, on the way out of
`ipconfig_get_ip_discovery_info`. That cannot work for UMC, because `mc_sw_init` never calls
the accessor:

```
1aaec: cmp dword ptr [r15 + rax - 0x10], 0x46      ; walk the entries directly, stride 0x260
```

It scans a copy of the ipconfig entries itself, and nothing anywhere looks UMC up through the
accessor, so a lazily-rewritten version never reached it. `r1` now applies every remap to the
whole ipconfig table the first time it is seen, so accessor and direct walker agree.

### Do not route a function whose prologue has a rip-relative operand

This one produced a completely false conclusion and is worth stating plainly.
`DevGetDeviceInfoEntry`'s prologue is:

```
af0e0: push rbp; mov rbp,rsp; lea rcx,[rip + _DeviceCapabilityTbl]; ...
```

The `lea` sits inside the bytes Lilu overwrites to install its jump. Lilu's trampoline copies
the displaced instructions to a new address **without rewriting rip-relative displacements**,
so calling the "original" through it loads a garbage table pointer and every lookup misses —
including `(0x73ff, 0, 0xcb)`, which is a verbatim entry in the table. The log said
`no entry at any revision` while the entry was sitting right there on disk.

Check the first 16 bytes of anything before routing it. Of the five functions this work
routes, only that one is unsafe:

```
ttlSetDeviceCapabilityEntry    55 48 89 e5 41 57 41 56 ...   safe
DevGetDeviceInfoEntry          55 48 89 e5 48 8d 0d 55 ...   RIP-RELATIVE lea
check_pcie_link_status         55 48 89 e5 41 57 41 56 ...   safe
ipconfig_get_ip_discovery_info 55 48 89 e5 8b 4f 1c 48 ...   safe
bif_ip_create                  55 48 89 e5 41 57 41 56 ...   safe
gvm_get_ip_function            55 48 89 e5 41 56 53 45 ...   safe
```

The fix is to route the **caller** instead. `ttlSetDeviceCapabilityEntry` is safe to route, and
re-calling it with a different internal revision redoes the whole side effect — it stores the
entry at `ttl+0xe8` and rebuilds the HWIP→SWIP mappings — rather than half of it.

### Fixing the timing broke the instrument: deferred diagnostics

Moving the plugin into the boot collection cost us the only reliable log channel, and both
remaining ones fail on their own:

- **Serial** receives everything, but other CPUs write to the 16550 concurrently and our lines
  come out shredded mid-character. This is what turned `id=0x3d` into `id=0x 3` plus a stray
  `d` on the next line.
- **`os_log`** is atomic per line, but the plugin now runs long before `logd` exists, so
  nothing logged during driver start-up ever reaches the unified log. `log show` returns
  nothing for it, correctly, and looks exactly like the plugin not running.

So every diagnostic line is now buffered in the kext (`RLOG`) and the whole buffer is
re-emitted from a thread at t+75 s, once userspace is up. Nothing else is writing to serial by
then, so that copy is clean, ordered and greppable:

```sh
tr -d '\r' < run/serial.log | sed -n '/deferred diagnostics:/,/deferred diagnostics end/p'
```

This is what made the last four findings readable at all; every earlier attempt at a multi-line
dump was unusable.

### PSP and SMU: past the last version gate, into HW_INIT

With MP0 and MP1 remapped the whole **software** init sequence completes — BGM, GVM, PSP
and SMU all pass `EVENT__SW_INIT` — and the failure moves to `EVENT__HW_INIT`.

Two gates fell first, both by the same "present what a real Navi 23 reports" rule:

- **MP0/PSP.** `psp_asic_type_init` (`0x4e08d`) dispatches on the MP0 version. For major 13
  it accepts **only minor 0, revisions 0-3**; this chip is 13.0.5, so it returns 1 and PSP's
  SW_INIT fails. Its major-11 branch is the Navi 2x family, and upstream `psp_v11_0` handles
  11.0.7 / 11.0.11 / 11.0.12 / 11.0.13 — Sienna Cichlid, Navy Flounder, Dimgrey Cavefish,
  Beige Goby. Navi 23 *is* Dimgrey Cavefish, so `MP0 -> 11.0.12`.
- **MP1/SMU.** `smu_get_hw_version` (`0x726ac`) maps the version to an internal enum and
  `smu_init_function_pointer_list` (`0x72b33`) handles only enum `<= 0xa`, asserting
  "Unsupported hw version!" above it. Decoding both jump tables: `13.0.5 -> enum 0x12`
  (unsupported), `11.0.12 -> enum 0x9`. The enum order across the 11.0.x table is exactly
  Sienna Cichlid (11.0.7 → 6), Navy Flounder (11.0.11 → 8), Dimgrey Cavefish (11.0.12 → 9),
  Beige Goby (11.0.13 → 0xa), which confirms the reading.

### Firmware comes from the IORegistry, keyed by device type

HW_INIT then failed on a missing asset, not a gate:

```
AMD Error: Firmware PP_SMC_UCODE_SBIN not found in directory, for deviceId 0x000073ff
```

`AmdTtlServices::getFirmware` resolves a blob through `AMDFirmwareDirectory::getFirmware`,
keyed on **`_AMD_DEVICE_TYPE`**, and then reads the actual bytes out of an **IORegistry
property** whose name the directory record carries. HWLibs calls `putFirmware` exactly nine
times, covering five device types:

| `_AMD_DEVICE_TYPE` | registered |
|---|---|
| `0x3`, `0x4`, `0x5` | `PP_SMC_UCODE_SBIN`, `ativvaxy_nv.dat` |
| `0x6` | `PP_SMC_UCODE_SBIN`, `ativvaxy_vcn3.dat` |
| `0x8` | `ativvaxy_vcn3.dat` only |

Tracing the lookup shows we present device type **`0x8`** — which Apple deliberately gives
**no SMU image**, because on that part the SMU microcode comes from the VBIOS via PSP rather
than from the driver (hence the companion property name `SMU_FalconEnableSideLoading` on the
types that do side-load). `smu_get_fw_constants` already handles that case:

```
709fd: test byte [smu+0x2d8], 1      ; skip firmware constants entirely
70a10: call smu_set_fw_entry_info_from_file
70a17: je   success
70a19: rcx = [smu+0x7a8]             ; else fall back to the driver's own source
70a2f: call rcx
```

and `smu_set_fw_entry_info_from_file` returns 2 without even looking when bit `0x40` of that
flags word is set. `x4` returns 2, so the fallback is used — the documented "no file firmware
for this part" answer rather than an error. That cleared the SMU failure entirely.

That the firmware is fetched from IORegistry properties is worth keeping in mind: it means a
blob **can** be supplied from outside, the same way `ATY,bin_image` supplies the VBIOS.

### The actual wall: Apple ships only a PSP 11.0 implementation

What remains is not a version gate and not a missing asset:

```
psp_hardware_initialization finished loading PSP FWs
[DRIVER] psp_ring_create: KM ring creation failed
AMD Error: cosWaitForFunc: Timeout while waiting for function     (x20)
```

The PSP mailbox handshake times out. The reason is structural. `psp_init_pfn_ptr` (`0x4e2d4`)
installs the PSP function pointers, and **every one of them is `*_11_0`**:

```
$ grep -oE "_psp_(ring|bootloader)_[a-z0-9_]*_(9_0|10_0|11_0|12_0|13_0)" hwlibs.nm | ...
     20 11_0
$ grep -cE "_psp_[a-z0-9_]*_13_0" hwlibs.nm
0
```

There is exactly one PSP generation in the whole kext. So Apple can only drive an **MP0 11.0**
mailbox, while this silicon's PSP is **MP0 13.0.5** — and the host's own kernel confirms what
it really needs:

```
amdgpu 0000:7b:00.0: detected ip block number 3 <psp_v13_0_0> (psp)
amdgpu 0000:7b:00.0: detected ip block number 4 <smu_v13_0_0> (smu)
amdgpu 0000:7b:00.0: reserve 0xa00000 from 0xf41e000000 for PSP TMR
```

The asic-type gate makes this airtight. `psp_init_pfn_ptr` accepts only
`asicType <= 0xf` **and** `bt 0xff60, asicType`, i.e. types {5, 6, 8, 9, 10, 11, 12, 13, 14,
15}; and `psp_asic_type_init` maps 13.0.0 → `0x14`, 13.0.1 → `0xf`, 13.0.2 → fail,
13.0.3 → `0x13`. Only 13.0.1 survives both — and it still receives the 11_0 pointers. There
is no path through Apple's code that speaks the 13.0 PSP protocol.

**But the seam is clean.** Apple dispatches its entire PSP through a function-pointer table at
fixed offsets in the PSP context, all filled in one place:

| offset | pointer | | offset | pointer |
|---|---|---|---|---|
| `+0x7da0` | `ring_init` | | `+0x7df8` | `bootloader_load` |
| `+0x7da8` | `ring_enable_interrupt` | | `+0x7e00` | `bootloader_unload` |
| `+0x7db0` | `ring_create` | | `+0x7e08` | `bootloader_load_sysdrv` |
| `+0x7db8` | `ring_stop` | | `+0x7e10` | `bootloader_load_sos` |
| `+0x7dc0` | `ring_destroy` | | `+0x7e18` | `bootloader_set_ecc_mode` |
| `+0x7dc8` | `ring_read_hw_status_regs` | | `+0x7e20` | `bootloader_time_table` |
| `+0x7dd0` | `ring_km_submit` | | `+0x7e28` | `reset` |
| `+0x7dd8` | `ring_km_response` | | `+0x7e30` | `security_feature_caps_set` |
| `+0x7de0` | `ring_km_trap_notify` | | `+0x7e38` | `bootloader_is_sos_running` |
| `+0x7de8` | `ring_um_submit` | | `+0x7e40` | `query_mp0_ras_status` |
| `+0x7df0` | `ring_um_get_status` | | `+0x7e48` | `hdp_flush` |

So the next step is no longer version archaeology: it is to **implement `psp_v13_0` in the
plugin** — port Linux's `psp_v13_0.c` ring and mailbox code — and overwrite those pointers
after `psp_init_pfn_ptr` runs. That is a bounded target (about fifteen functions against a
small upstream file), and it is the first point in this whole effort where new driver code is
actually required rather than a redirection to code Apple already ships.

### What the PSP mailbox actually does — measured, not inferred

Before concluding anything about Apple's PSP generation, the plumbing was checked by routing
`psp_cgs_read_register` and `psp_cgs_write_register`. Those resolve an IP-relative index
against a per-instance base kept in the PSP context:

```
516e1: add esi, dword ptr [rdi + 4*rdx + 0x5c]     ; index += base[instance]
```

The result rules out every plumbing explanation:

```
psp_read(idx=0x91 ...) base=0x16000 abs=0x16091 -> 0x006018ea     C2PMSG_81, sOS heartbeat
psp_read(idx=0x91 ...)                          -> 0x00601d2a     ... incrementing
psp_read(idx=0x7a ...) base=0x16000 abs=0x1607a -> 0x00420024     C2PMSG_58, tOS version
psp_read(idx=0x80 ...) base=0x16000 abs=0x16080 -> 0x80020115     C2PMSG_64
psp_write(idx=0x85 ...) <- 0x0fbff000                             C2PMSG_69, ring lo
psp_write(idx=0x86 ...) <- 0x000000f4                             C2PMSG_70, ring hi
psp_write(idx=0x87 ...) <- 0x00001000                             C2PMSG_71, ring size
psp_write(idx=0x80 ...) <- 0x00020000                             GFX_CTRL_CMD_ID_INIT_GPCOM_RING
psp_read(idx=0x80 ...)                          -> 0x80020115     unchanged
psp_read(idx=0x85 ...)                          -> 0x0fbff000     read-back OK
```

- The MP0 base `0x16000` is **correct** — `MP0_BASE__INST0_SEG0` is `0x00016000` in both
  `dimgrey_cavefish_ip_offset.h` and `yellow_carp_offset.h`.
- The C2PMSG register numbers are **identical** between MP0 11.0 and MP0 13.0.5:
  `mmMP0_SMN_C2PMSG_64` and `regMP0_SMN_C2PMSG_64` are both `0x0080`, `_69` both `0x0085`.
  Apple's 11.0 code writes exactly the registers upstream's v13 code writes, in the same
  order, with the same command encoding. So the earlier assumption that this was a
  register-layout mismatch was **wrong**.
- The **PSP is alive**: `C2PMSG_81` is a monotonically incrementing heartbeat (upstream's
  `psp_v13_0_is_sos_alive` tests exactly this register), and `C2PMSG_58` returns a real tOS
  version.
- **Writes reach the device**: `C2PMSG_69/70/71` read back precisely what was written.
- But `C2PMSG_64` **never changes**, before or after the command write. It holds
  `0x80020115` throughout: response bit set, command field `0x2`
  (`GFX_CTRL_CMD_ID_INIT_GPCOM_RING`), status `0x0115` in the low 16 bits
  (`GFX_CMD_STATUS_MASK`).

So the mailbox is not broken and not misaddressed. The PSP holds an unacknowledged
`INIT_GPCOM_RING` response with a non-zero status, and does not consume a new doorbell write.
Both upstream and Apple gate ring creation on `(C2PMSG_64 & 0x8000ffff) == 0x80000000`, i.e.
status **zero**, so with `0x0115` stuck there the wait can never pass — which is precisely the
observed `psp_ring_create: KM ring creation failed` plus twenty `cosWaitForFunc` timeouts.

Two candidate explanations remain, and they are distinguishable:

1. **Stale state.** The iGPU is never reset between VM restarts, and this session restarted the
   guest dozens of times. The first attempt that reached this code would have left exactly this
   value, and every later boot inherits it. Note that the ring address written back,
   `0xf4_0fbff000`, sits in the same GPU-MC range as the host kernel's own
   `reserve 0xa00000 from 0xf41e000000 for PSP TMR`.
2. **A platform-owned PSP.** On an APU the PSP is the SoC's security processor, already running
   platform-loaded tOS, and it may simply refuse to hand its GFX ring interface to a second
   driver.

Distinguishing them needs a genuinely fresh PSP, which means a **host reboot** — not a driver
rebind: `gpu-bind.sh` records that a `vfio-pci -> amdgpu -> vfio-pci` cycle leaves the bind
wedged in uninterruptible sleep with only a reboot to recover, so that route must not be taken.
On the first boot after a host restart, the very first `psp_read(idx=0x80)` in the deferred
diagnostics answers it: `0x80000000` (or any status-zero value) means the state was stale and
ring creation should now proceed; `0x80020115` again means the PSP is genuinely refusing.

This is the single most useful clue for whoever continues: **`C2PMSG_64` does not change on
write while its immediate neighbours do.**

### The stale-PSP trap, and why one host reboot bought exactly one boot

The `C2PMSG_64 = 0x80020115` wall was **stale state**, confirmed from the host. On a fresh
boot with `amdgpu` still bound, the mailbox is clean, and it stays clean through the handover:

```
amdgpu bound      C2PMSG_64 -> 0x80020000   status 0   (amdgpu's own INIT_GPCOM_RING)
after vfio bind   C2PMSG_64 -> 0x80030000   status 0   (DESTROY_RINGS: amdgpu tore it down)
```

So `amdgpu` cleans up properly on unbind. The guest does not: QEMU is killed outright, so the
GPCOM ring it created is never destroyed. And Apple's `psp_ring_create_11_0` only calls
`psp_ring_stop` on its **TEE** path — for ring type 2 it branches at `0x5bf5e` straight to
`0x5bfc7` and issues `INIT_GPCOM_RING` against a ring that already exists. Upstream's
`psp_v11_0_ring_create` calls `psp_v11_0_ring_stop` unconditionally, which is why upstream
never hits this. Result: exactly one guest boot works per host reboot.

**No reboot is needed to recover.** Two fixes, either sufficient:

- `gpu-quiesce.sh` (host, root) mmaps BAR5 and issues `GFX_CTRL_CMD_ID_DESTROY_GPCOM_RING`.
  It clears the mailbox in ~2 ms. `redeploy.sh` runs it after stopping the VM and
  `gpu-restore.sh` before handing the device back to `amdgpu`.
- Milestone `x7` does the same from **inside the guest**, needing no root at all, by routing
  `psp_ring_create_11_0` and destroying first.

One trap worth stating, because it made the fix look like it worked when it did not: **a
status-0 mailbox does not mean there is no ring.** After a boot that reached `ENABLE_INT`,
`C2PMSG_64` reads `0x80050000` — clean by every "ready" test — while that boot's ring is
still alive. Gating the destroy on a non-zero status therefore skips it exactly when it is
needed. Destroy unconditionally. (And when polling for the response, mask bit 31 off before
comparing the command field, or the wait always runs to timeout.)

### Where the firmware actually comes from, and what the PSP will accept

With a clean mailbox, `INIT_GPCOM_RING` and `ENABLE_INT` both return status 0 and the KM ring
works. `psp_np_fw_load` then submits IP firmware, and this is where it stops.

Apple is **not** short of firmware. `psp_np_fw_init(psp, descriptors, count)` receives 18
descriptors of 40 bytes, via an OS-side callback at `[ttlGetExtSvcs() + 0x2a0]`:

| field | meaning |
|---|---|
| `+0x00` | `0x28`, the struct size |
| `+0x04` | firmware type |
| `+0x10` | kernel VA of the firmware bytes |
| `+0x18` | size |

The sizes total ~1.7 MB and include three ~263 KB blobs — the full Navi 23 IP firmware set,
with real pointers into a kext. So the earlier guess that an empty VBIOS PSP directory starved
it was wrong.

`psp_print_fw_load_failure_msg`'s jump table gives Apple's own type names, and
`psp_np_fw_load` indexes that table with `type - 1` (`53ab8: lea eax, [r15 - 0x1]`), so the
family is type `0x17` GPM / `0x18` SRM / `0x19` CNTL. Getting that off-by-one wrong is why a
first attempt at declining them silently did nothing.

What the Raphael PSP does with Navi 23 microcode, measured:

| type | blob | result |
|---|---|---|
| `0x01` | CP CE | **loads** (status 0) |
| `0x19` | RLC restore list CNTL | rejected, `0x8000030a` |
| `0x0b` | RLC FW | rejected, `0x80000203` |

`psp_np_fw_load` aborts on the first failure, so only the first item is ever confirmed good.
It accepts a Navi 23 CP CE blob and refuses the RLC ones. That is consistent with RLC being
the most ASIC-bound of the set: the restore lists are register lists describing GC 10.3.4's
register file, and this chip is GC 10.3.6.

Milestone `x8` declines the restore-list family (upstream loads them only when the RLC header
declares them, so that is a supported configuration; the cost is no GFXOFF power-gating).
That moves the failure from the CNTL list to the RLC microcode itself with a different status,
which is progress in position but leaves the same question: this PSP will not take Navi 23 RLC.

The correct answer is almost certainly to hand it **Raphael's own** RLC firmware —
`/lib/firmware/amdgpu/gc_10_3_6_rlc.bin` is signed for this silicon — by rewriting the
descriptor's `+0x10`/`+0x18` to point at bytes the plugin carries. That is the next step, and
it is the first one that requires supplying data rather than redirecting Apple's own code.

### Iterating without paying for a boot

A guest boot costs ~90 s, and most wasted cycles in this work were bad constants or patches
that could never match — all statically checkable. `preflight.py` asserts, in under a second,
that every `kOff*` constant still equals the address of the symbol its comment names, that no
routed function has a rip-relative operand in its first 16 bytes, and that every find pattern
is still unique in the KDK. `esp-kext.sh` refuses to ship if it fails. Dropping `-c` from the
`qemu-img convert` in `redeploy.sh` took the deploy step from ~35 s to 7 s, and the dump delay
is now tunable with `rgpudump=<ms>` rather than baked in.

### PSP HW_INIT completes: it was the TOC all along

The RLC rejections were a red herring, and so was every theory built on them. Substituting
this chip's own signed RLC firmware changed nothing, because RLC was never the problem.

The break came from reading the **per-command response status**, not just the commands. Apple
marshals every PSP command through `psp_cmd_km_buf_prep` (`0x524e9`), which writes into the
GPCOM buffer at `psp + slot*0x38 + 0x760`; `psp_gfx_resp` sits at buffer `+864`. Recording the
previous command's status when the next one is marshalled gives the whole transcript:

```
cmd[00] LOAD_TOC   addr=0xf40fc00000 size=0x600    -> 0x8000030a   tmr_size=0
cmd[01] SETUP_TMR  addr=0xf41fe00000 size=0x0      -> 0xffff0006   TEE_ERROR_BAD_PARAMETERS
cmd[02] LOAD_ASD                    size=0x29100   -> 0x00000007
cmd[03] LOAD_TA                     size=0x2100    -> 0
cmd[05] LOAD_IP_FW type 18 SMU      size=0x3b200   -> 0
cmd[06] LOAD_IP_FW type 22 CNTL     size=0x250     -> 0x0000000f
```

One root failure, everything else a consequence: **LOAD_TOC is rejected, so `tmr_size` comes
back 0, so SETUP_TMR is handed size 0 and fails, so there is no TMR** — and the firmware loads
that need one fail. Decoding the PSP `sys_drv` images that HWLibs itself embeds gives the
codes their meaning: `0x8000030a` is the IP-firmware loader's *"unrecognised firmware type"*,
returned before address, size or signature is examined, and `0x80000203` is *"required context
not initialised"*, returned before the request is parsed at all. Neither was ever a signature
verdict.

The fix is the same identity substitution, one layer up. HWLibs holds **two** 0x600-byte `$PS1`
TOC containers and `psp_tmr_init` takes its TOC from runtime fields (`psp+0x3588` pointer,
`psp+0x3580` size), so which one is submitted cannot be read statically:

| symbol | `$PS1` fw_type |
|---|---|
| `_aPSP_TOC_SIGNED` @ `0x1155d40` | `0x0000200e` |
| `_TOC_TABLE` @ `0xeb80f0` | **`0x00000000`** |

`_TOC_TABLE`'s FW ID is **zero**, and `0x8000030a` is exactly "unrecognised firmware type".
Replacing both with the payload of this chip's own `psp_13_0_5_toc.bin` (offset `0x100`, length
`0x600`, fw_type `0x0101200e`, version 3, same signing key, **same size**) is milestone `xb`:

```
XB: _aPSP_TOC_SIGNED fw_type 0x200e ver 0 -> 0x101200e ver 3 : substituted
XB: _TOC_TABLE       fw_type 0x0   ver 0 -> 0x101200e ver 3 : substituted
cmd[01] LOAD_TOC  -> status=0x00000000  tmr_size=0xa00000
cmd[02] SETUP_TMR addr=0xf41f400000 size=0xa00000 -> status=0x00000000
```

`tmr_size = 0xa00000` is the same value the host kernel reports for itself
(`reserve 0xa00000 from 0xf41e000000 for PSP TMR`), which is a good independent check that the
TOC was understood rather than merely accepted.

With the TMR established, **every** firmware blob loads with status 0 — the whole RLC family
including the two whose sizes had to change, and all of the CP microcode:

```
type 22 CNTL 0x250   -> 0     type  8 RLC_G  0x6200  -> 0
type 20 GPM  0x600   -> 0     type  1 CP_ME  0x40400 -> 0
type 21 SRM  0x4480  -> 0     type  3 CP_PFP 0x40380 -> 0
type 26 IRAM 0x10200 -> 0     type  2 CP_CE  0x40400 -> 0
type 48 DRAM 0x10200 -> 0     type  4 CP_MEC 0x414b0 -> 0
type 25 RLC_P 0x2200 -> 0
type 27 GLOBAL_TAP_DELAYS 0x300 -> 0x8000030a
```

The tap delays are the one remaining rejection and they are *supposed* to be rejected:
`gc_10_3_6_rlc.bin` is header **v2_2**, whose layout stops before the v2_4 tap-delay fields, so
this chip has no such firmware, and upstream only registers them when a v2_4 header declares
them (`amdgpu_rlc.c`). Declining them (`xd`) is what upstream does. With that,
**`psp_np_fw_load` reports no failures at all and PSP HW_INIT completes** — the PSP then goes
on to `EVENT__HW_UNINIT`, which only happens after it initialised.

Two corrections to earlier entries in this document, both from this work:

- Apple's fw type `0x01` is **SMU**, not CP CE. `psp_np_fw_load` indexes the failure-message
  table with `type - 1`, and index 0 is "SMU FW". So the blob that loaded on the very first
  attempt was the SMU firmware.
- `_psp_cmd_km_fw_id_map` (`0x52b90`, table at `0x3cddb4`) translates Apple's internal enum to
  upstream's wire `GFX_FW_TYPE` **correctly** — `0x0b`→8 RLC_G, `0x17`→20, `0x18`→21,
  `0x19`→22, `0x1a`→26, `0x1b`→48. There was never a wire-type mismatch to find.

### The next wall: SMU HW_INIT, and a latent Apple bug on the way to it

The failure is now `SW_IP_CLIENT_ID__SMU, EVENT__HW_INIT` — "SMU init/power-up failed" — which
is the wall this document predicted from the other direction: `smu_init_function_pointer_list`
implements only `smu_9_0*` and `smu_11_0*`, and this silicon needs `smu_13_0_5`.

Getting there exposed a genuine bug in Apple's cleanup, worth recording because it kills the
machine rather than the driver:

```
cosReleaseMemoryHandle(this, handle):
    b3674: test rdi, rdi / je   ...     ; checks `this`
    b3679: test rsi, rsi / je   ...     ; checks `handle`
    b367e: mov  rax, qword ptr [rsi]    ; handle's vtable -- NOT checked
    b3684: call qword ptr [rax + 0x28]
```

It null-checks both arguments and then dereferences the vtable pointer inside the handle
without checking it. On the SMU failure path that pointer is null, so the guest panics with
`RAX=0, CR2=0x28` in `smu_cos_release_mem_handle`. Milestone `xe` supplies the missing check,
which restores the survivable-boot property that `m1`'s `doGPUPanic` patch provides for PPLIB —
without it there is no way to read anything back out of a boot that gets this far.

### Measure with the right instrument, or you will read false zeros

Most wrong turns in this work came from broken measurement, not from the system:

- Lilu plugin `SYSLOG` and the AMD drivers' messages go to **`os_log`**, not serial. Only Lilu's
  early `config:`/`api:` lines and `kprintf` reach the 16550.
- `log show --last Nm` returns **nothing** when N is less than guest uptime, because the
  interesting lines are emitted at boot. Derive the window from `kern.boottime`.
- `dwarfdump`, `shasum` and `strings` are absent without Command Line Tools and exit empty.
  Use `openssl dgst -sha256` and `grep -a`, which are in base macOS.
- `tail -N` on a log will silently cut the lines you need. Read the whole set, then filter.
- A `screendump` that fails leaves the *previous* frame on disk, so a screenshot helper will
  hand back a stale image unless it deletes the target first and fails loudly.

`guest-log.sh rgpu|amd` and the verdict logic in `autorun.sh` now encode all of this.

### The milestone ladder

`milestones.py` holds the patch set, re-verifies every find-pattern against the KDK before it will
deploy, and toggles them as named milestones so each experiment is one command:

```sh
./milestones.py list            # what is staged and what each milestone predicts
./milestones.py only m1         # clear the NBIF gate + defang the PPLIB panic
./redeploy.sh                   # rewrite the ESP, restart, drain serial
tr -d '\r' < run/serial.log | grep -E 'c00c02|ASSERT|GPUCAP|Accel'
```

`m1` also injects `CFG_NO_PP` as a device property. `AmdProjectFeatures::readRegistryProperties`
computes that feature bit as `(value == 0)` — inverted — and `AmdPowerPlayHelper::powerUp`
(`0x101a0`) then skips `handleCriticalError`, so a TTL failure only logs instead of panicking.
**Do not also inject `@0,name`:** `readProjectName` uses it to select the `ATY,Henbury` sub-dict,
whose `aty_config` sets `CFG_NO_PP=false` and is `setProperty`'d onto the same `IOPCIDevice`
before the read-back. The belt-and-braces alternative is the verified one-byte edit to
`doGPUPanic` (`0x4e6f9`, `je` displacement `0x48` → `0x1b`), which `m1` also carries.

Each milestone states its expected outcome in advance so the boot is a real test rather than a
fishing trip: `m1` should move the BGM stage code from `0xc00c0203` to `0xc00c0205`.

The ladder, in the order the failures are actually encountered:

| set | gate | change | risk |
|---|---|---|---|
| **m1** | `bif_ip_create` `0x239a84` | `cmp 0x70200` → `0x70300`, so NBIF 7.3.0 reaches `nbio7_2_initialize` | low — Linux maps 7.3.0 to the same driver |
| **m1** | `doGPUPanic` `0x4e6f9` (+ `CFG_NO_PP`) | `je` disp `0x48` → `0x1b`, so a TTL failure logs instead of panicking | none, and it is what makes iteration possible |
| **m2** | `mp0_ip_create` `0x24410c` | `add ecx, 0xfff50000` → `0xfff2fffb`, so MP0 13.0.5 lands on bit 0 and reaches `mp0_11_0_0_initialize` | **highest** — PSP-11 protocol at a security processor shared with the running host |
| **m3** | `smuio_ip_create` `0x249a08` | `cmp 0xd0007` → `0xd000a`, so SMUIO 13.0.10 uses the `smuio13_0_7_*` handlers | low-ish — same 13.0.x generation |
| **m4** | `_gc_init_fcn_ptr_list` `0x8f38` | `cmp eax, 6` → `7`, widening 10.3.0–10.3.5 to include 10.3.6 | low — one byte, routes to the shared GFX10 pointers that already serve 10.3.4 |
| **m5** | `_vm_ip_version_mapping` `0x115cc88` | 10.3.5 row → 10.3.6 | low — Linux drives 10.3.0–10.3.6 with one GMC implementation |
| **m6** | `_mc_ip_version_mapping` `0x115c610` | 10.0.0 row → UMC 9.5.0 | **real guess** — borrows an 11.x-era handler for a DDR5 APU UMC; but `mc_sw_init` fails outright without a match |
| **m7** | `_athub_ip_version_mapping` `0x115da18` | 2.4.0 → 2.4.1 | trivial — one revision byte; 2.4.0 already shares its handler with 1.3.1 |

The `*_ip_version_mapping` tables are arrays of
`{ u16 major; u16 minor; u16 rev; u16 pad; void *fn[4]; }` on a 40-byte stride, matched **exactly**
on all three version fields by `_gvm_get_ip_function` (`0x19258`). The layout was confirmed by the
HDP table, which contains an exact `5.2.0` row matching this chip. So each table gate is one
version field repointed at a handler that already exists — no new code.

### Correction: MMHUB is not a separate gate

An earlier pass in this document listed **MMHUB 2.4** among the blocks that need new code,
sourced from a symbol survey (`no _mmhub_2_4* exists`) rather than a decoded gate. That was
overstated. There is **no MMHUB version check anywhere in HWLibs** — no
`_mmhub_ip_version_mapping` table (unlike `mc`, `vm`, `hdp` and `athub`, which all have one) and
no version compare. The mmhub initialiser is called from *inside* a VM/GMC handler:

```
359aa:  lea  rax, [rip + _vm_hw_capabilities_10_3_1]
359ec:  call _gc_10_3_1_initialize_registers
359f4:  call _mmhub_2_3_0_initialize_registers
359fc:  call _vm_10_3_initialize_system_domain
```

So MMHUB is selected *implicitly* by whichever row `vm_ip_version_mapping` picks. Apple ships
`mmhub_2_0`, `2_1_0`, `2_2_0` and `2_3_0`; this chip is 2.4.1. That makes MMHUB a
**wrong-but-adjacent implementation** problem, not an absent-code problem — a much better
position, and `m5` will settle it empirically since it retargets the 10.3.5 row (whose handler is
the one Navi 23's 10.3.4 also uses).

Remaining genuinely-needs-code, then, is **SMU 13** and **DF 4.0.1**, plus DCN 3.1.5 / JPEG which
are skippable in a VM. `_df_create` (`0x21d8`) checks the IP id at `+0xc == 0x27` and an instance
count at `+0x10 == 1` before reaching `_dcs_get_hw_revision`, so its version switch sits past that
— not decoded yet, deliberately: it only matters if m1–m7 all clear, and that hinges on the
riskiest rung (MP0-11 code driving MP0 13.0.5). Measure first.

That covers **8 of the 11 failing gates** as declarative OpenCore patches. What is left genuinely
needs code: **MMHUB 2.4** (no `mmhub_2_4` symbol exists), **SMU 13**
(`_smu_init_function_pointer_list` `0x72b33` caps at enum 10), **DF 4.0.1**, and **DCN 3.1.5** /
**JPEG 3.1.2** which are both skippable in a VM. That is the Lilu-plugin work, ported from Linux's
`mmhub_v2_4.c` and `smu_v13_0_5_ppt.c`.

**Conclusion.** Metal on this iGPU is not reachable by configuration; it needs code for three
IP blocks Apple never shipped (MMHUB 2.4, SMU 13, and DCN 3.1.5 if display is wanted). That is a
driver-porting project against Linux's `mmhub_v2_4.c`, `smu_v13_0_5_ppt.c` and `dcn31`, delivered
as a Lilu plugin — the shape NootedRed uses for Vega APUs. It is bounded, because the shader ISA
is gfx10.3, the same family as Navi 23, so Apple's existing closed Metal shader compiler works
unchanged. That single fact is what makes the iGPU the tractable target.

For contrast, the RX 9070 XT is **not** reachable by the same route: there is zero `gfx12`/`gc_12`
code anywhere in the AMD stack, and the blocker is not the kext but the Metal shader compiler in
Apple's closed userspace bundle, which emits gfx10 ISA. RDNA 4 would need an LLVM backend inside
a binary we cannot rebuild.

## What Apple ships, and what it does not

`AMDRadeonX6000HWLibs` (the generic plugin, and the one actually in use here — the log sender
confirms it) **embeds complete PSP-signed firmware** for the ASICs it supports; it does not
extract firmware from the VBIOS. For Navi 23 that means `gc_10_3_4_{ce,me,mec,pfp,rlc,...}_ucode`,
`navi23_smc_firmware`, `psp_bootloader_{load,load_sysdrv,load_spl,load_sos}_11_0` and
`psp_bootloader_is_sos_running_11_0`. Independently, Apple's default `aty_properties` for both
the Navi 21 and Navi 23 personalities set **`DalEnablePspFwLoad = 0`** and
**`PP_EnableUploadFirmware = 0`** — macOS does not upload PSP or SMU firmware to these cards
at all; it relies on the board's own POST. That is why the grafted PSP directory only has to
*parse*.

Encouragingly, the driver already reads live values out of this chip's security processor —
`BootLoader Version = 0x00420024` and, in an earlier run, `PSP TOS Version = 13.39.0.17`,
which is a genuine Raphael PSP version. The MP0 mailbox registers line up.

`CAIL_ASIC_CAPS_TABLE` in `AMDRadeonX6810HWLibs` (VMA `0x4478d0`) holds 507 entries of 40
bytes in 5 families and is byte-identical across all seven HWLibs variants. It contains **no
APU device id at all** — no Raven, Picasso, Renoir, Cezanne, Van Gogh, Rembrandt, Phoenix or
Raphael. Family 143 (Navi) covers exactly 24 discrete ids. This is why the real `0x13c0` never
matches and why the `0x73ff` spoof is load-bearing. `PhwRenoir_*` APU power management is
compiled in and dead for the same reason.

## Tooling this produced

- `mkrom.py` — grafts the PSP directory and `vram_info` tables onto the APU ROM; all field
  layouts taken from the disassembly, not guessed.
- `ocprop.py` — edits the OpenCore `config.plist` (device properties, boot-args). Note the
  file begins with XML comments *before* the declaration, which `plistlib` refuses, so the
  leading comment block is split off and restored verbatim.
- `redeploy.sh` — one command: rebuild ROM, inject, rewrite the ESP, restart the VM, start the
  serial drain. The ESP is reached without `guestfish` (absent here): the container's
  `qemu-img` converts `OpenCore.qcow2` to raw into the shared `run/` mount, and `mcopy` from
  host `mtools` edits the FAT partition at offset 1048576 (found by parsing the GPT).
- `guest-connect.sh` — logs in and bootstraps the `gx` command channel.
- `xref2.py` — resolves rip-relative operands in an `llvm-objdump` listing and prints
  cross-references to a given address, with the enclosing symbol.
- `kcsym.py`, `kdk/pbzx.py`, `sercat.py`, `gpu-bind.sh` / `gpu-restore.sh`, `sweep.sh`.
- `build/` — a working **Mach-O kext cross-compiler on Linux**: clang plus cctools-port ld64
  (`-kext -static`) producing a genuine `MH_KEXTBUNDLE` with `_kmod_info`, against
  MacKernelSDK and Lilu 1.6.8. `ld64.lld` cannot do this; `cctools` must be configured with
  `-std=gnu17`; and `kmod_info.c` must be hand-written because Xcode normally generates it.
  This is the fallback if a binary patch to the version dispatches becomes necessary.

## The host-side trap that looks like a guest hang

Passing this iGPU to QEMU **NULL-derefs the host kernel** unless the device is pinned awake first:

```
BUG: kernel NULL pointer dereference, address: 00000000000005d0
Comm: qemu-system-x86   RIP: down_write+0x20/0x60
  vfio_pci_core_runtime_resume <- rpm_resume <- __pm_runtime_resume
  <- vfio_pci_core_enable <- vfio_pci_open_device <- vfio_df_open
```

It presents as a *guest* problem and is not one: QEMU becomes a zombie (`ZNsl <defunct>`), the
docker container still reports "Up" because nothing reaps it, and the guest emits **zero** serial
bytes — indistinguishable from a boot hang until you read `journalctl -k`. Then it is
unrecoverable: `power/runtime_status` sticks at `resuming` and anything needing the device's PM
lock blocks uninterruptibly — confirmed with
`pid=... stat=D  sh -c echo 0000:7b:00.0 > /sys/bus/pci/drivers/vfio-pci/unbind`. Wrapping the
write in `timeout` does not help, because `timeout` cannot kill a D-state task. Only a reboot
recovers the device.

Trigger condition: the device must be runtime-**suspended** when QEMU opens it. It is, after a
fresh boot, because it drives no display (the dGPU does). On 2026-09-05 the same sequence worked
purely because the iGPU happened to still be awake in D0 from earlier use.

Fix, now enforced in three places: a udev rule
(`ACTION=="add|bind" ... ATTR{power/control}="on"` for `1002:13c0`), an explicit
`echo on > power/control` in `gpu-bind.sh` *after* the bind (vfio-pci re-enables runtime PM on
probe), and an `autorun.sh` preflight that refuses to boot unless it reads `on`. Note
`amdgpu.runpm=0` on the kernel cmdline is irrelevant here — that governs amdgpu's runtime PM, not
vfio-pci's.

## Traps hit along the way

- `slide=0` in boot-args stops the guest booting.
- Any key or click sent to the OpenCore picker cancels its auto-boot timeout permanently.
  `ShowPicker=false` does not help either; known-good is `ShowPicker=true` with `Timeout=45`
  and no input during unattended boots.
- Sequoia's "click wallpaper to show desktop" swallows stray clicks and hides every window.
  Drive the GUI through Spotlight (`sendkey meta_l-spc`) instead of clicking the desktop.
- `pkill -f <script>` matches the agent's own shell command line and kills the session
  (exit 144). Use `pgrep` plus PID filtering.
- The AMD kexts in `/System/Library/Extensions` are stubs; use the KDK.

## Panic survivability (RE session, KDK 24G830)

Panic site: `AMDRadeonX6000_AmdRadeonController::doGPUPanic(const char*, ...)` @ FB VMA **0x4e5b0**
(vtable slot +0x8a8 of `__ZTV40AMDRadeonX6000_AmdRadeonControllerNavi23` @ 0x298080).
Reached from `AmdPowerPlayHelper::powerUp` (0x101a0) -> `handleCriticalError` (0x10470) -> vtable +0x8a8.
Gate: `if (this->[0x7948] != NULL) call it(  [0x98], 3, "%s", msg ) and RETURN; else panic()`.
  - +0x7948 is NULL from `initializeInternals` (0x4ba68) and is only ever set by
    `AmdRadeonController::setAttribute(attr=2, fnptr)` (0x4e91c, jumptable case 2 -> 0x4ea64),
    and only while still NULL. NOT settable from a plist / DeviceProperties / boot-arg.
  - FB kext parses NO boot-args at all (`llvm-nm -u` shows only `_panic`).
  => panic is effectively unconditional from userland's point of view.

The kill switch is upstream: `CFG_NO_PP`.
  `AmdProjectFeatures::readRegistryProperties` (0xc5fa) @0xc79d:
      out=0; getRegistryProperty(pciDevice, "CFG_NO_PP", &out, 8); bit8 = (out == 0)
  `supportsFeature(8)` (0xc2fc, jumptable @0xc424 case 8 -> 0xc3ee) returns exactly that bit8.
  `AmdPowerPlayHelper::initWithController` @0xfa95 does
      this->[0x28f8] = controller->getFeatures()->supportsFeature(8)
  `powerUp` @0x101c0 calls isSupported() (0xfc92 = [0x28f8]==1 && [0x68]!=0); if false it logs
  "[PPLIB] powerUp() ??? SKIP: Not Supported." and @0x10240 `cmp byte [rbx+0x28f8],1 / jne 0x10276`
  skips handleCriticalError entirely -> returns 0xe00002c7, NO PANIC.
  Controller-level caller (0x4d612) treats that as a warning: "Power Play Initialization Failed
  (Safe-Mode?)" and continues at 0x4d6cf.

Property plumbing (answers "can I inject it?"): YES.
  `AmdRegistryUtilities::getRegistryProperty(IORegistryEntry*, char*, void*, size)` @0x3aa40 =
  `entry->vtable[0x2b8](name)` (IORegistryEntry::getProperty(const char*)) + parseOSObjectValue.
  The entry is `AmdProjectFeatures->[0x20]` = `controller->getPciDevice()` = the IOPCIDevice.
  Same for HWLibs' PP_*/SMU_* keys: `AmdPowerPlayHelper::AppleMcilGetRegister` @0x116ce reads
  `helper->[0x58]` (= getPciDevice()) `->getProperty(key)`.
  CAVEAT: `AmdProjectFeatures::populateGenericConfig` (0xc4ca) / `populateProjectConfig` (0xc544)
  COPY the personality's `aty_config` + `aty_properties` dicts ONTO the IOPCIDevice with
  setProperty (block @0xccbd) BEFORE readRegistryProperties runs. The project dict is selected by
  `readProjectName()` (0x4bc7c) = IOPCIDevice property **"@0,name"**. The Navi23 personality's
  sub-dict "ATY,Henbury" contains `CFG_NO_PP = false` -> injecting @0,name="ATY,Henbury" would
  CLOBBER an injected CFG_NO_PP. Top-level aty_config has no CFG_NO_PP, so leaving @0,name unset
  is safe.

Byte patch that keeps TTL running but makes the panic a kprintf (doGPUPanic @0x4e703, file off == VMA):
  Find    4C 8B 83 48 79 00 00 4D 85 C0 74 48
  Replace 4C 8B 83 48 79 00 00 4D 85 C0 74 1B      (je 0x4e74d[panic] -> je 0x4e720[IOFreeData])
  Unique in the binary (single hit @0x4e6f9).

Other levers found:
  - `-amd_no_dgpu_accel` boot-arg, `AMDGraphicsAccelerator::probe` @0x1664 (acc kext): *score=-1,
    return NULL, UNLESS the device has IOPCITunnelled==true. Blocks Metal accel only; does NOT
    stop the panic (messageAccelerator @0x4f038 returns 0xe00002c7 when controller->[0x7960]==NULL
    and that still reaches handleCriticalError).
  - `-x` (safe boot) is read by `AmdTtlServices::initialize(_TtlLibraryInitializationInput*)`
    @0xb5962 -> "TTL Interface: Safeboot detected. Boot mode minimal." -> `ttlDevGetBaseSwipSeq`
    (0xafb64) picks `dev->[0xe8]+0x30` (minimal SWIP seq) instead of `+0x28` (normal).
    `IpiValidateTopology` @0xa01f6 uses it. Different, shorter IP-create sequence.
  - `-amd_simnow` boot-arg, `AmdTtlServices::initialize()` @0xb5d3c -> "TTL Interface: Enabling
    emulation." (RacerN/SimNow), sets bit 0x1 in the TTL init flags word.
  - IOPCIDevice property **"ATY,EFIVersion"** (@0xb5cf9, getProperty recursive) sets bit 0x200 in
    the same TTL init flags word.
  - `amd_gpu_debug_policy=<u32>` boot-arg OR IORegistry "GpuDebugPolicy" ->
    `AMDRadeonX6000_AMDHardware::initGpuDebugPolicy` @0x6f2ba (acc kext).
  - Neither AMDRadeonX6000HWLibs nor AMDRadeonX6000HWServices imports `_panic`; the accelerator
    has only 3 assert-panics. The FB's doGPUPanic is the ONLY panic in this failure.

Kernel (KDK kernel, x86_64):
  `panicDebugging = 1` iff `debug_boot_arg != 0 && kernel-debugging-permitted` (@0xffffff8000ae87af).
  When panicDebugging != 0 the panic path SPINS FOREVER (@0xffffff80002ec9f6 -> pause loop);
  when 0 it calls `PEHaltRestart(4|9)` = reboot (@0xffffff80002eca1e).
  Serial kprintf requires `debug=0x8` (DB_KPRT): PE_kputc = pal_serial_putc only if
  `debug_boot_arg & 8` (@0xffffff8000af45e6). => debug=0x8 gives serial output but ALSO makes
  panics hang instead of rebooting. Pick one.
  `panic_restart_timeout=<sec>` is parsed (@0xffffff8000af293f) and exposed as a sysctl, but has
  NO reader anywhere else in this x86_64 kernel -> it does not shorten the panic reboot on Intel.

### TTL::initialize() completes: the SMU was never ours to drive

`SW_IP_CLIENT_ID__SMU, EVENT__HW_INIT` was the last TTL gate, and it fell without a single
byte of ported SMU-13 code. Reading the chain rather than guessing is what made that possible:

```
smu_internal_hw_init      0x72d46  -> [smu+0x6c8]
smu_11_0_7_internal_hw_init 0x7f3af -> smu_11_0_7_core_hw_init   0x83977
                                     -> smu_11_0_7_check_fw_status 0x805fd
                                     -> smu_11_0_7_check_fw_version 0x8055b
                                     -> smu_11_0_7_send_message(3)  0x806ac
```

`smu_11_0_7_send_message` and `smu_11_0_7_wait_for_response` name their registers in the
clear:

| use | Apple register index | Navi 2x name |
|---|---|---|
| message | `0x282` | `MP1_SMN_C2PMSG_66` |
| parameter | `0x292` | `MP1_SMN_C2PMSG_82` |
| response | `0x29a` | `MP1_SMN_C2PMSG_90` |

This silicon does not have its SMU mailbox there. Upstream `smu_v13_0_5_ppt.c` uses
`MP1_C2PMSG_2 / _33 / _34`, and working the SOC15 arithmetic through
(`0xbee142 + 0xb00000/4`, plus `MP1_BASE` segment 0 = `0x16000`, times 4) puts them at SMN
bytes **`0x3b10508` / `0x3b10984` / `0x3b10988`** — the Zen SMU aperture, not the GPU's MMIO
window at all. Hence every message times out at `PP_WaitOnRegisterTimeout` (2000 ms, and
`0x7d0` in the `cosWaitForFunc` dumps is exactly that) and `check_fw_version` logs a
"mismatch" whose version argument was never read.

Retargeting those registers is mechanically possible — `smu_cgs_read_register` (`0x70dd1`)
compares the resolved byte address against `[smu+0x2cc]`, which `smu_sw_init` sets to
`0x80000`, and falls through to an indirect SMN accessor at `[[smu+8]+0xc0]` for anything
above it. It is also the wrong thing to do. On an APU the SMU is the *platform's* power
controller — it governs the CPU cores of the machine this VM is running on, it was brought up
by the x86 firmware long before macOS existed, and its PPSMC message enum has nothing to do
with Navi 2x's. Putting Navi 2x message ids on that mailbox is not a debugging step.

Apple already has a name for a GPU whose power management belongs to somebody else.

#### smu_config_name_mapping: 36 injectable settings

`smu_read_config_space` (`0x72840`) reads its whole configuration by *name* out of an
IORegistry property, through `smu_cos_read_config_setting` ->
`AmdTtlServices::cosReadConfigurationSetting` (`0xb4a50`) -> `IORegistryEntry::getProperty`
-> `getOSObjectData`. The name table is `_smu_config_name_mapping` at `0x13a7a70`: a 4-byte
header then 36 entries of `{ char name[0x100]; u32 default; u32 id; }`, stride `0x108`.

| name | default | -> context |
|---|---|---|
| `SMU_DisableMmhubPowerGating` | 0 | |
| `SMU_DisableAthubPowerGating` | 0 | |
| `SMU_DisableACG` | 0 | |
| `SMU_EnableFwLoading` | 0 | |
| `SMU_DisallowedFeatures` (8 bytes) | 0 | `+0x2f8` |
| `SMU_MemoryPoolSize` | 0 | |
| `SMU_ToolsLogSpaceSize` | 0x19000 | |
| `PP_LogLevel` | 0 | `+0x308` |
| `PP_LogSource` | 0xff7fffff | `+0x30c` |
| `PP_WaitOnRegisterTimeout` | 0x7d0 | `+0x310` |
| `PP_Run_DcBTC` | 1 | |
| `PP_SclkDpmDisabled` | 0 | `+0x318` |
| `PP_MclkDpmDisabled` | 0 | `+0x31c` |
| `PP_SocclkDpmDisabled` | 0 | `+0x320` |
| `PP_PcieDpmDisabled` | 0 | `+0x324` |
| `PP_DisableULV` | 0 | `+0x328` |
| `PP_GfxOffControl` | 1 | `+0x32c` |
| `PP_DisallowedVBIOSPPTableFwdstate` | 0 | |
| `PP_OverrideNumberOfUclkStates` | 0 | |
| **`PP_PhmUseDummyBackEnd`** | **0** | **`+0x338`** |
| `SMU_ActivityMonitorTable` | 0 | |
| `PP_PMLogGfxClkSource` | 3 | `+0x340` |
| `PP_PMLogPreDsWorkloadsMask` | 0 | |
| `PP_EnableDummyPstateTable` | 1 | `+0x348` |
| `SMU_PPtableSource` | 0 | |
| `PP_EnableSTBLogging` | 1 | `+0x350` |
| `SMU_IgnoreSmuIfVersion` | 0 | |
| `PP_GfxDcsSupport` | 1 | |
| `SMU_EnableVCNPG` | 1 | `+0x35c` |
| `SMU_EnableJPEGPG` | 1 | `+0x360` |
| `SMU_EnableISPPG` | 1 | `+0x364` |
| `SMU_Enable_eGPU_USB_WA` | 0 | |
| `SMU_Power_Throttle_Indicator_Threshold` | 0x50 | |
| `SMU_Thermal_Throttle_Indicator_Threshold` | 0x5a | |
| `SMU_Current_Throttle_Indicator_Threshold` | 0x50 | |

`PP_PhmUseDummyBackEnd = 1` lands in `[smu+0x338]`, and `smu_init_function_pointer_list`
(`0x72b33`) then calls `smu_update_function_pointers` (`0x73a2f`) *after* the 11_0_7 list is
built. That overwrites hw_init, notify_event, fullscreen, soft_table, overdrive, thermal,
fan, dpm, power, ips, azalia, ulv, gfx_off, system_features, i2c, power_feature_caps, pm_log
and notify_number_of_displays with `dummy_smu_*` stubs that return 0. Nothing downstream is
left to time out.

**But the property does not arrive.** Injected as `OSData` on `PciRoot(0x0)/Pci(0x6,0x0)`
alongside the working `ATY,bin_image`, `[smu+0x338]` still read back 0 — TTL's COS context
resolves a different `IORegistryEntry` (`ctx+8`) than the IOPCIDevice the Framebuffer's
`AmdRegistryUtilities` uses. Worth chasing later, since 36 settings hang off it. For now the
plugin calls `smu_update_function_pointers` directly, which is exactly what the property
would have caused and is idempotent — it only stores pointers.

One hardware call survives the dummy back end: `dummy_smu_internal_hw_init` (`0x738c2`)
still calls `[smu+0x798]`, which the 11_0_7 list set to `smu_11_0_7_dummy_hw_init`
(`0x7f4d7`) — and that goes straight back into `check_fw_status`. `smu_update_function_pointers`
does not clear the slot, and nothing else in the SMU context reads it, so milestone **`xf`**
nulls it. `dummy_smu_internal_hw_init` then returns 0 on its own at `0x73952`.

Measured, first boot with `xf`:

```
XF: smu_init_function_pointer_list -> 0  hw_version=9  flags=0x0010
    PP_PhmUseDummyBackEnd=0  asic_dummy_hw_init=0xffffff7f91e534d7
XF: calling smu_update_function_pointers directly -> 0
XF: cleared [smu+0x798] so the dummy back end makes no hardware call
XF: hw_init is now 0xffffff7f91e478c2 (dummy_smu_internal_hw_init)
...
[0:6:0] [Accel] <<< TTL::initialize() Completed successfully.
==== TTL =====
SE=1, SA/SE=1
numActiveRB=1, enabledRbMask=0x00000001, max=1
numActiveCU=2, max=2, total=2
[0:6:0]: CWSR is enabled
Accelerator successfully registered with controller.
```

`hw_version=9` independently confirms the jump-table decode (`11.0.12` -> enum 9 -> the
`smu_11_0_7` list, which then swaps in `smu_11_0_12_get_ucode_consts` and
`smu_11_0_12_check_fw_version`). And **`SE=1, numActiveCU=2`** is this iGPU's real
topology read back out of the GC block — 1 shader engine, 2 CUs, 1 RB. Nothing about that
comes from the spoofed device id or the grafted VBIOS; the graphics core was initialised and
enumerated itself.

### The next wall: the framebuffer aperture is empty

TTL is up and the accelerator registered, but PowerPlay cannot initialise on a dummy SMU
("Failed Power Play Initialization", "PowerUp Failed. Shut back down."), which `m1`'s
`doGPUPanic` patch turns into a log line. macOS proceeds to use the GPU anyway — WindowServer
submits a command buffer — and dies here:

```
[0:6:0]: AMD ERROR! Failed to allocate size:65536.
         There is 0 free memory remaining, and 0 fixed-free memory remaining.
panic: Kernel trap, type 14 = page fault, CR2 0x0, RDI 0x0
  AMDRadeonX6000: AMDAccelResource::BatchPrepareMappings + 0x1ee
  AMDRadeonX6000: AMDAccelResource::BatchPrepare + 0xf3
  IOAcceleratorFamily2: IOAccelCommandQueue::processCommandBuffer + 0x2f8
```

The allocator has nothing to hand out, and the reason is one line up in GPUCAP:

```
[GPUCAP] refresh() --- Mem Size: FB: 512 MB, Aper: 256 MB, Reg Aper: 512 KB.
[GPUCAP] refresh() --- FB Base: 0x100000000, Top: 0x100000000, Offset: 0.
```

`FB Top == FB Base`, so the framebuffer *range* is zero bytes wide even though the size field
says 512 MB. Those come from the MC/GMC framebuffer-location registers
(`MC_VM_FB_LOCATION_BASE` / `TOP`), which live in MMHUB — and `r1` currently reports **MMHUB
2.4.1 as 2.3.0**, a version whose register offsets are not this chip's. That is the leading
hypothesis and the next thing to measure, not assume; `2.4` was already flagged in this
document as one of the two blocks Apple never shipped code for.

### Past TTL: the accelerator, the framebuffer aperture, and the graphics ring

With TTL up, the failure moves out of HWLibs entirely and into `AMDRadeonX6000`, the
accelerator. Four separate things had to be fixed to get from "accelerator attaches, then
panics" to "the graphics core is initialised and the command processor is being fed".

#### The framebuffer aperture: Apple reads MMHUB, this part programs GFXHUB

`GPUCAP` reported `FB Base: 0x100000000, Top: 0x100000000` -- a zero-wide range -- so the
VRAM allocator had nothing and WindowServer's first command buffer page-faulted in
`AMDAccelResource::BatchPrepareMappings`.

`AmdAsicInfoNavi2::populateXGmiConfig` (`0x3b3e0`, Framebuffer) reads five raw MMIO dword
indices: `0x1a867` xgmi cntl, `0x1a868` xgmi size, `0x1a86c` FB base, `0x1a86d` FB top,
`0x1a857` FB offset -- MMHUB at Apple's base `0x1a800` with the MMHUB 2.0 offsets
`0x6c/0x6d/0x57`. Scanning both hub windows in one boot settled it:

```
0x1a86c=0x100  0x1a86d=0       0x1a857=0        <- MMHUB: not programmed
0x295c=0xf400  0x295d=0xf41f   0x2947=0x840     <- GFXHUB: correct
```

`0xf400 << 24` and `(0xf41f << 24) | 0xffffff` are exactly the host kernel's
`VRAM: 512M 0x000000F400000000 - 0x000000F41FFFFFFF`, which also pins Apple's GC segment-0
base at `0x1260` (`0x295c - 0x16fc`, and `0x2947 - 0x16e7` agrees). Milestone **`xg`**
takes the GFXHUB copy. This is *not* the MMHUB version remap: the read never goes through
TTL's IP dispatch.

#### PowerPlay: "unsupported" is still a failure

Fixing the aperture changed nothing, because `AMDHWMemory::enableAllocations` was never
reached. The accelerator's own progress bitfield says so:

```
ttlPowerUp : 0    accelPowerUpHW : 0    hardwarePowerUp : 0
powerUpHWEngines : 0    startHWEngines : 0
```

`AmdPowerPlayHelper::powerUp` (`0x101a0`) calls `handleCriticalError("PowerUp Failed. Shut
back down.")` and then `vtable+0x198` -- powerDown -- whenever PPLIB init fails while
`[this+0x28f8]` is 1. Clearing that flag takes Apple's own "SKIP: Not Supported" path and
avoids the powerDown, but it returns `kIOReturnUnsupported`, and the accelerator counts
that as failure just as much as an error. Milestone **`xi`** clears the flag *and* reports
success: on this part the GPU is powered and clocked by the platform SMU before macOS
exists, which is what "powered up" has to mean.

#### A register-base mistake worth recording

`AMDHWMemory::initVRAMInfo` hands two per-pool sizes to `enableAllocations`
(`canAllocate` indexes them as `[this + 8*pool + 0x40]`), and `AMDHWMemory::init` clamps
`[0x48] = min([0x48], [0x40])`, so `[0x40]` is the total and `[0x48]` the CPU-visible
aperture -- 512 MB against a 256 MB BAR0 (`Memory at fc20000000 [size=256M]`, no resizable
BAR capability). Every Navi 2x Mac has a BAR as large as its VRAM, so `enableAllocations`'
equal-sizes path is the one Apple ships; milestone **`xh`** equalises on the smaller value
so the two-argument `IOAccelMemoryAllocator::init_pool(base, size)` is used.

Then the register reads. Chasing "why is the RLC not running" produced this:

```
RLC_CNTL=0  RLC_STAT=0  RLC_RLCS_BOOTLOAD_STATUS=0     <- WRONG, and plausible
```

which is exactly the kind of wrong that costs a day. SOC15 register offsets are
`base_table[BASE_IDX] + reg`, and **`RLC_*` and `SCRATCH_REG0` are `BASE_IDX 1`, not 0**.
HWLibs says so in the clear: `gc_reg_offset(table, reg, base_idx)` at `0xb197` is
`reg + table[base_idx]`, and `gc_enter_rlc_safe_mode_10_3` passes `0x4c00` with
`base_idx 1`. GC segment 1 is `0xa000`. With the right base:

```
RLC_CNTL=0x1  RLC_RLCS_BOOTLOAD_STATUS=0xc0000001  RLC_GPM_STAT=0xc0016 -> 0x140016
SCRATCH_REG0: wrote 0xa5a5a5a5, read back 0xa5a5a5a5
```

The RLC is running, its bootload completed, and register writes work. The control
experiment is what caught it: a 16-bit-looking truncation (`0xa5a5a5a5` reading back as
`0xa5a5`) was the giveaway that the address was wrong, not the write path.

#### Where it stands: the KIQ does not complete

`AMDGraphicsAccelerator::powerUpHW` reaches `enableAllocations` only after
`hardware->powerUp()`, which needs `powerUpHWEngines`, which fails on engine 0, PM4.
`AMDGFX10PM4Engine::doStart(false)` gets this far:

```
initComputeMQD(ring=4)                 -> 1        ok
startKIQ(0xf40b706000, 0xf40b706800)   -> 0        ok
submitSetResourcesPacket -> submitKIQFrame -> waitForHwStamp(1) -> 0   TIMEOUT
```

and the graphics core's state across that timeout is:

```
before:  GRBM_STATUS=0x3028      CP_STAT=0  CP_CPF_STATUS=0          VM_FAULT_STATUS=0
after:   GRBM_STATUS=0xa0003028  CP_STAT=0  CP_CPF_STATUS=0x88008001 VM_FAULT_STATUS=0
         CP_ME_CNTL=0  CP_MEC_CNTL=0  RLC_CNTL=0x1  CP_CPC_STATUS=0
```

So: the CP is unhalted, the RLC is up, the ring lives inside the real framebuffer, the
doorbell makes GRBM assert GUI_ACTIVE and the CP fetcher go busy -- and there is **no VM
fault** (the `0x881` seen earlier was latched from before; clearing
`GCVM_L2_PROTECTION_FAULT_CNTL` bit 0 first leaves it at 0 through the timeout). The
compute pipe never reports activity (`CP_CPC_STATUS=0`), which is where the KIQ lives.

## The KIQ blocker, fully characterised

`TTL::initialize()` completes and the accelerator registers, then
`AMDGFX10PM4Engine::doStart` fails because `AMDHWChannel::waitForHwStamp(1)` times out on
the first KIQ submission. Everything else fails downstream of that: `powerUpHWEngines`
returns 0, no engine is powered, and when WindowServer submits a command buffer
`AMDHWVMM::endVMPTUpdate` dereferences null.

What the hardware says, measured with the KIQ's own `GRBM_GFX_CNTL` selector:

| register | value | meaning |
|---|---|---|
| `CP_HQD_ACTIVE` | 1 | the queue is live |
| `CP_MQD_BASE_ADDR` | `0xf40b706000` | in VRAM, and exactly `startKIQ`'s first argument |
| `CP_HQD_PQ_BASE(_HI)` | `0xFFBFEA0000` | inside context 0's GART window |
| `CP_HQD_PQ_CONTROL` | `0xc030860d` | 64 KB ring, `PRIV_STATE`, `KMD_QUEUE` |
| `CP_HQD_PQ_DOORBELL_CONTROL` | `0xc0000000` | offset 0, `DOORBELL_EN=1`, **`DOORBELL_HIT=1`** |
| `CP_HQD_PQ_WPTR_LO` | `0x20` | 32 dwords submitted |
| `CP_HQD_PQ_RPTR` | 0 | nothing consumed, ever |
| `CP_HQD_VMID` | 0 | |
| `CP_HQD_PERSISTENT_STATE` | `0xbe05300` | `PRELOAD_SIZE=0x53`, upstream's constant |
| `CP_HQD_ERROR` | 0 | no UTCL1 error on any client |
| `CP_HQD_HQ_STATUS0` | `0xc0000000` | `QUEUE_IDLE` set |
| `CP_MEC_ME2_HEADER_DUMP` | `0xdefNdefN` | fill pattern: no packet header ever fetched |
| `CP_CPC_STATUS` | `0xa0000002` | `MEC2_BUSY` |
| `CP_MEC2_INSTR_PNTR` | a real address | MEC2 is executing |
| `CP_MEC_CNTL` | 0 | neither MEC halted |
| `CP_PQ_STATUS` | `0x3` | `DOORBELL_ENABLE` set |
| `GCVM_CONTEXT0_CNTL` | `0x1555401` | enabled, depth 0, retry cleared by us |
| `GCVM_CONTEXT0_PAGE_TABLE_BASE` | `0x0fdfc001` | valid bit set, table at FB offset `0x0FDFC000` |
| `GCVM_CONTEXT0_PAGE_TABLE_START/END` | `0xffbfa00`/`0xffffe00` | GART `0xFFBFA00000..0xFFFFE00000` |
| `GCMC_VM_MX_L1_TLB_CNTL` | `0x1d59` | `ENABLE_L1_TLB=1`, `SYSTEM_ACCESS_MODE=3` |
| `GCVM_L2_CNTL` | `0xc0603` | `ENABLE_L2_CACHE=1` |
| `GCVM_INVALIDATE_ENG0_REQ/ACK` | `0x2f80001`/`0x10001` | a full VMID-0 invalidate was issued **and acked** |
| `GCVM_L2_PROTECTION_FAULT_STATUS` | 0 throughout | |
| `RCC_DEV0_EPF0_RCC_DOORBELL_APER_EN` | `0x1` | at `0xd20 + 0xc0`; `BIF_DOORBELL_APER_EN` set |

So the doorbell store reaches the queue (`DOORBELL_HIT`), the aperture is enabled at the
NBIO, the CP's own doorbell gate is open, the microengine is running, the ring lives at a
translatable address, and the MEC still decides there is nothing to run.

Ruled out, each by measurement rather than by argument:

- **The doorbell not reaching the device.** BAR2 is assigned (QEMU reports 2 MB at
  `0xf0000000`), `AMDHardware::mapDoorbellMemory` maps it via config offset `0x18` and
  stores the mapping's virtual address at `[hwObj+0x528]`; writing index 0 by hand from the
  plugin sets `DOORBELL_HIT` and changes nothing else.
- **`BIF_DOORBELL_APER_EN` never being set.** `_nbio7_2_enable_doorbell_aperture` runs with
  `enable=1` and the register reads back 1. (The dispatcher is
  `_bif_doorbell_aperture_control`, which calls `[ctx+0x378]`; the `_bifNN_*` variants are
  not the ones wired up on this part, the `_nbioN_M_*` family is.)
- **A VM translation failure on the ring.** Context 0 covers the ring, `PAGE_TABLE_BASE`
  carries its valid bit, L1 TLB and L2 are enabled, and `GCVM_CONTEXT0_CNTL` bit 7
  (`RETRY_PERMISSION_OR_INVALID_PAGE_FAULT`) has been cleared so a bad page reports instead
  of retrying silently. No fault is ever raised, and `CP_HQD_ERROR` stays 0.
- **The MECs never being started.** Performing upstream's
  `gfx_v10_0_cp_compute_enable` edge by hand -- halt both, invalidate the instruction
  cache, unhalt -- restarts MEC2 (its instruction pointer changes) and changes nothing.
- **Missing microcode.** `CP_{PFP,ME,CE,MEC_ME1,MEC_ME2}_UCODE_ADDR/DATA` read back real
  instruction words in all five engines.
- **`CP_HQD_HQ_STATUS0.DB_UPDATED_MSG_EN`.** Setting it sticks and changes nothing; and
  upstream's `gfx_v10_0` never writes that register at all -- it appears in `gfx_v10_0.c`
  only inside a register-dump table.

One asymmetry is left, and it is where the next experiment goes. The MEC's authoritative
write pointer for a doorbell queue comes from memory, at
`CP_HQD_PQ_WPTR_POLL_ADDR = 0xFFBFDE0050`, with the read-pointer report at
`0xFFBFDE0048` -- both in the GART, i.e. in guest system memory reached through the GFXHUB
page tables and then the host IOMMU. If the GPU reads zeros there, every observation above
is exactly what follows: the doorbell wakes the engine, the engine reads a write pointer of
0, concludes the queue is empty, sets `QUEUE_IDLE` and goes back to sleep, touching neither
the ring nor the report address, raising no fault and logging no error.

A secondary oddity points the same way. Writes through this plugin's register accessor land
for `CP_HQD_QUANTUM`, `CP_HQD_IB_CONTROL` and `CP_HQD_HQ_STATUS0`, but
`CP_HQD_EOP_BASE_ADDR` and `CP_PQ_WPTR_POLL_CNTL` silently keep their old values -- even
with `CP_HQD_ACTIVE` forced to 0 first, which is the state upstream reprograms an HQD in.
EOP stays 0 while `CP_HQD_EOP_CONTROL` reads 6, so Apple did size an EOP buffer it never
gave an address to.

## What the KIQ is actually waiting for

`CP_CPC_STALLED_STAT1` and its siblings name the stall exactly, and they change the shape of
the problem:

    CP_CPC_STALLED_STAT1 = 0x210000   MEC2_DECODING_PACKET | MEC2_WAIT_ON_ROQ_DATA
    CP_CPC_BUSY_STAT     = 0x8080000  MEC2_MESSAGE_BUSY | MEC2_PIPE1_BUSY
    CP_CPF_BUSY_STAT     = 0x48460000
    CP_CPF_STALLED_STAT1 = 0
    CP_STALLED_STAT1/2/3 = 0          the graphics side is not stalled at all
    CP_BUSY_STAT         = 0

So the queue *is* dispatched -- on MEC2 pipe 1, the pipe the `GRBM_GFX_CNTL` walk found --
the microengine has begun decoding a packet, and it is blocked waiting for the ring fetch to
return. `UTCL2IU_WAITING_ON_FREE`, `UTCL2IU_WAITING_ON_TAGS`, `UTCL1_WAITING_ON_TRANS` and
`GCRIU_WAITING_ON_FREE` are all clear, so it is not waiting on address translation: the read
was issued and the data never came back. The CP fetcher (`CPF`) is busy and not
back-pressured, which is a fetch in flight that never completes.

Two things follow, and the second was a surprise.

**The queue programming is not the problem.** The MQD image in VRAM and the HQD register
file disagree on four fields, and copying the image into the registers with the MECs halted
and `CP_HQD_ACTIVE` cleared resolves three of them and changes nothing:

| field | MQD | register | after copy |
|---|---|---|---|
| `cp_hqd_eop_base_addr` | `0xf40b7068` | 0 | still 0 -- refuses every write |
| `cp_hqd_eop_control` | `0x8` | `0x6` | still `0x6` |
| `cp_hqd_pq_control` | `0xd130860d` | `0xc030860d` | `0xd130060d` |
| `cp_hqd_persistent_state` | `0xbe05301` | `0xbe05300` | `0xbe05300` |

Of those, two are not discrepancies at all: `CP_HQD_PQ_CONTROL` bit 15 is `PQ_EMPTY`, a
read-only status bit Apple captured into the image, and `CP_HQD_PERSISTENT_STATE` bit 0 is
`PRELOAD_REQ`, a self-clearing request. `CP_HQD_EOP_BASE_ADDR` genuinely will not take a
write, from Apple or from here, active or inactive, MECs running or halted.

**It is not the GPU's path to guest system memory either.** That was the obvious suspect:
every structure this stack has been proven to read -- the PSP ring, the TMR, the MQD, the
page tables, the RLC clear-state buffer -- lives in the framebuffer, which the hardware
reaches through the FB aperture and `GCMC_VM_FB_OFFSET` with no DMA at all, while the KIQ
ring is the first thing it is asked to fetch from guest RAM through a `SYSTEM|SNOOPED` PTE.
And the data is genuinely there: reading the guest-physical pages the GART names, from the
host with QEMU's `xp`, shows the write-pointer word holding `0x20` at
`0x44b639050` and the ring holding a real `PACKET3_SET_RESOURCES` at its base
(`0xc006a000 0x0028ffff 0xffffffff 0 ...`, opcode `0xA0`, seven payload dwords).

So the ring was moved into VRAM: an unused framebuffer page was filled with that same
packet followed by `PACKET2` no-ops, the ring's GART PTE was rewritten to point at it with
`SYSTEM` and `SNOOPED` and the MTYPE bits cleared, and the GFXHUB TLB was invalidated
(`GCVM_INVALIDATE_ENG0_REQ = 0x00f80001`, acked immediately) -- all *before* the frame is
submitted, because once `MEC2_WAIT_ON_ROQ_DATA` is set the fetch is already outstanding and
no invalidate retries it. The PTE reads back `0xff00071` and the stall is unchanged.

A CP fetch that never returns from VRAM is not a memory-visibility problem. It points at the
path between the CP and the GL2/UTCL2 complex, which is also the one piece of the GFXHUB
that has never been verified against upstream field by field: `GCVM_L2_CNTL` reads
`0xc0603`, `GCVM_L2_CNTL3` reads `0x80120007` where upstream's `gfxhub_v2_1_init_cache_regs`
asks for `BANK_SELECT = 9` and `L2_CACHE_BIGK_FRAGMENT_SIZE = 6` (this reads 7 and 2), and
`GCVM_L2_CNTL2`, `CNTL4` and `CNTL5` have not been compared at all. The RLC never
acknowledging safe mode and the 37 timed-out `_vm_10_1_is_eng_ack` waits are consistent with
the same region being misconfigured.

Recorded as a negative result: programming the GFXHUB L2 exactly as
`gfxhub_v2_1_init_cache_regs` does changes nothing. `GCVM_L2_CNTL` goes `0xc0603 -> 0x80e01`
(fragment processing off, default-page-out-to-system-memory on, PDE fault classification
off), `GCVM_L2_CNTL3 -> 0x80130009` (`BANK_SELECT` 9, `L2_CACHE_BIGK_FRAGMENT_SIZE` 6),
`GCVM_L2_CNTL4 -> 0x1` and `GCVM_L2_CNTL5 -> 0x3fe0` from their documented defaults with
`VMC_TAP_PDE/PTE_REQUEST_PHYSICAL` and `L2_CACHE_SMALLK_FRAGMENT_SIZE` cleared, followed by
a full invalidate -- every value reads back exactly as intended, and
`CP_CPC_STALLED_STAT1` stays at `0x210000`.

So the fetch stall survives: a correct queue, a correct ring in either VRAM or system
memory, a working doorbell, translation not implicated, and an L2 configured byte for byte
like upstream's.

## The stall predates Apple entirely

Sampled from inside `submitKIQFrame`, *before* the original call, with a ring in VRAM holding
a correct `PACKET3(PACKET3_SET_RESOURCES, 6)` plus `PACKET2` no-ops and the doorbell rung
with the right dword count:

    XK: hand-run +500us: rptr=0 wptr=0x8 stalled=0x210000 cpf_busy=0x48460000

`CP_CPC_STALLED_STAT1` is already `0x210000` before Apple submits anything. So none of it is
about Apple's packet, about whether its write pointer is a dword or a byte count, or about
where the ring lives. MEC2 is wedged before the accelerator gets a turn.

The obvious candidate was the dequeue in `_gc_create_kiq_queue_10_3`, which milestone `xl`
papers over with upstream's manual `CP_HQD_ACTIVE = 0`: forcing a queue inactive underneath
an unfinished dequeue would leave the engine in it, and `CP_CPF_BUSY_STAT`'s
`HQD_EOP_FETCHER_BUSY` and `HQD_ROQ_EOP_BUSY` are what a dequeue draining to the end-of-pipe
queue looks like. Hooking `_gc_cgs_write_register_ext2` and dropping every
`CP_HQD_DEQUEUE_REQUEST` write disproves it: on a cold GPU the drop fires exactly once, and
*after* `TTL::initialize() Completed successfully` -- it is Apple's `startKIQ` doing the
dequeue, not TTL's, because on a freshly reset device TTL finds no live HQD to dequeue in the
first place. The stall is there anyway.

Which leaves TTL's own KIQ, created inside GC HW_INIT, as the first queue this MEC is asked
to run -- and it is the first packet fetch on this engine that never completes. Everything
Apple does afterwards queues behind it.

One inference to retract: `CP_MEC_ME2_HEADER_DUMP` returning `0xdef0def0`, `0xdef2def2`,
`0xdef4def4`, `0xdef6def6` in sequence is a *read-triggered counter*, incrementing by two per
access, not a stale header. "The MEC has never fetched a packet header" was never a sound
reading of it.

## Correction: the CP "stall" bits are the state the GPU arrives in

Instrumenting `_gc_cgs_write_register_ext2` to sample `CP_CPC_STALLED_STAT1` after every GC
register write, and to keep a short history of the writes preceding the first non-zero read,
gives this:

    XK: last writes before the wedge: 0xc200=0
    XK: CP_CPC_STALLED_STAT1 went 0 -> 0x210000 on write reg=0xc200 val=0 client=0xb
    XK: at wedge: CPC_BUSY=0x8080000 CPF_BUSY=0x48460000 CP_STAT=0x84028000
                  MEC_CNTL=0 HQD_ACTIVE=0 EOP=0_00000000 eop_ctl=0

The history holds a single entry, so `GRBM_GFX_INDEX = 0` is the *first* GC write the stack
makes -- a routine broadcast-select -- and the register already reads `0x210000` on the very
first sample. `CP_MEC_CNTL` is 0 (nothing halted) and `CP_HQD_ACTIVE` is 0 (no queue exists
yet). There was never a transition to catch.

So `MEC2_DECODING_PACKET | MEC2_WAIT_ON_ROQ_DATA`, together with `CP_CPF_BUSY_STAT`'s
`HQD_EOP_FETCHER_BUSY` and `HQD_ROQ_EOP_BUSY`, is the state this CP is in *before the guest
driver touches it* -- inherited from amdgpu's MODE2 reset and vfio-pci's reset, or simply
this part's idle signature. It is not evidence of a wedge, and three conclusions built on
reading it as one are hereby withdrawn:

- that the engine was stalled waiting for a ring fetch to return;
- that the end-of-pipe queue was what it was waiting on, and therefore that
  `CP_HQD_EOP_BASE_ADDR` reading 0 was the root cause;
- that halting the MECs is one-way on this part. With all three GC write helpers filtered,
  no halt write is issued before the bits are already set, so the `0x50000000` seen earlier
  was pre-existing state and not something TTL wrote.

What survives is narrower and still true: the KIQ's read pointer never advances, no packet is
consumed, and `waitForHwStamp` times out. The eliminations from the previous sections stand,
because each was tested against that symptom rather than against the status bits -- the
doorbell reaches the HQD, translation is configured and faults when told to, the MQD matches
the register file, the packet and write pointer are verifiably in the pages the GART names,
the L2 is programmed exactly as upstream does, and relocating the ring into VRAM changes
nothing.

The instrument to trust from here is the read pointer and the ring contents, not
`CP_CPC_STALLED_STAT1`.

## Why the command processor never executes: its instruction cache is an unreachable address

> **Corrected 2026-09-07.** This section originally concluded that the instruction-cache
> bases hold the *host amdgpu's* addresses, left behind because amdgpu had the device first.
> That was wrong, and acting on it cost two host hard-hangs. The addresses are written by
> the **guest's own PSP**, and the reason the microengines never execute is an aperture
> mismatch, not stale state. See "Correction: BASE != OFFSET" below. The measurements in
> this section stand; only the attribution changed.

`CP_MEC2_INSTR_PNTR` sampled sixteen times over 320 us reads `0x310` with zero changes;
`CP_MEC1_INSTR_PNTR` reads `0x10000`, the same value the halted PFP, ME and CE report. The
microengines are not executing. And a `PACKET3_WRITE_DATA` packet of our own -- placed in a
ring in VRAM, with the doorbell rung with the correct dword count, storing `0xcafebabe` into
a framebuffer page we then read back -- never lands either. So nothing about Apple's software
was ever implicated: this queue does not run because the engine does not run.

The reason is in three registers:

    CP_CPC_IC_BASE = 0x8_5f904000    CP_PFP_IC_BASE = 0x8_5f87c000
    CP_ME_IC_BASE  = 0x8_5f8c0000    CP_CPC_IC_BASE_CNTL = 0x10 (ADDRESS_CLAMP)

On GFX10 a microengine does not run out of internal RAM. It fetches through an instruction
cache whose base upstream programs in `gfx_v10_0_cp_compute_load_microcode`. These values are
the *host* driver's: the host's `GCMC_VM_FB_OFFSET` is `0x840000000`, so `0x85f904000` is
carveout offset `0x1f904000`, and under the host's identity FB mapping that number served as
both MC and physical address. The guest's FB aperture sits at MC `0xf400000000`, so the
address the CP is locked to resolves to nothing at all here. `GFX_CMD_ID_AUTOLOAD_RLC`, which
is what would have reprogrammed it on the PSP path, answers `TEE_ERROR_BUSY`.

And it cannot be rewritten. Five paths were tried and all were ignored: the framebuffer
accessor plain, with `GRBM_GFX_INDEX` broadcasting all SEs/SHs/instances, inside an
`RLC_SAFE_MODE` request, with both MECs halted, and through TTL's own
`_gc_cgs_write_register_ext2` with the GC client id. A bit-toggle probe puts the lock in
sharp relief:

| register | |
|---|---|
| `CP_MEC_CNTL` | writable |
| `CP_ME_CNTL` | writable |
| `SCRATCH_REG0` | writable |
| `GCMC_VM_FB_LOCATION_BASE` / `TOP` | writable |
| `GCVM_CONTEXT0_PAGE_TABLE_START` / `END` | writable |
| `GCMC_VM_SYSTEM_APERTURE_LOW` | writable |
| **`CP_CPC_IC_BASE_LO`** | **locked** |
| **`CP_HQD_EOP_BASE_ADDR`** | **locked** |
| **`CP_PQ_WPTR_POLL_CNTL`** | **locked** |

The locked set is exactly the addresses the command processor fetches from -- its microcode,
its end-of-pipe buffer, its write pointer -- which is what a secure PSP would take ownership
of once it has autoloaded the engines. It also explains, retrospectively, every write in this
investigation that silently failed to stick.

### Pointing the microcode at the register instead

Since the register cannot move, the memory can. MC-to-physical through the FB aperture is
`physical = MC - GCMC_VM_FB_LOCATION_BASE + GCMC_VM_FB_OFFSET`, `FB_OFFSET` is fixed at the
real carveout base `0x840000000`, and `BASE` is settable in 16 MB steps. Setting
`BASE = 0x850000000` (with `TOP` at `BASE + 512 MB - 1`, and the system aperture moved to
match) puts the locked `0x85f904000` at aperture offset `0x0f904000` -- 249 MB in, inside the
256 MB BAR0 window, so the CPU can write it, and clear of both the GART page table at
`0x0fdfc000` and everything Apple allocates lower down. Done from `populateXGmiConfig`, before
`TTL::initialize`, so every address Apple and TTL derive is consistent with the new window;
Apple programs the MMHUB copies of those registers rather than the GFXHUB ones, so nothing
downstream overwrites it.

`TTL::initialize()` still completes with the aperture moved, and `GPUCAP` reports
`0x850000000..0x86fffffff`. This chip's own `gc_10_3_6_mec.bin` payload (0x41830 bytes, now
embedded by `mkrlcfw.py` alongside the RLC firmware) is copied there and reads back byte for
byte, and the rest of upstream's loader runs: `CP_CPC_IC_OP_CNTL.INVALIDATE_CACHE` (completes
immediately), `CP_CPC_IC_BASE_CNTL` with VMID 0 / CACHE_POLICY 0 / EXE_DISABLE 0 /
ADDRESS_CLAMP 1, and the jump table -- 0xe0 dwords from payload dword 0x1052c, i.e. byte
0x414b0, which is *exactly* the size of Apple's Navi 23 MEC blob, confirming Apple ships the
microcode without a jump table and this file carries both -- written into MEC1's internal RAM
through `CP_MEC_ME1_UCODE_ADDR/DATA`, then the halt-to-unhalt edge.

The engines still do not start. Also checked and not the cause: graphics power gating
(`RLC_PG_CNTL` already 0, `RLC_GPM_STAT` reporting `GFX_POWER_STATUS`, `GFX_CLOCK_STATUS` and
`GFX_PIPELINE_POWER_STATUS` all set) and clock gating (`RLC_CGCG_CGLS_CTRL` 0).

So the CP is owned by the PSP for the life of this reset, and the remaining lever is to make
the PSP itself start it -- which means getting `AUTOLOAD_RLC` past `TEE_ERROR_BUSY`. The one
untried input to that is the ASD: `LOAD_ASD` is the other PSP command that still fails, with
status 0x7, and this chip's own `psp_13_0_5_asd.bin` has never been substituted for Apple's.

## A PSP MODE1 reset from inside the guest is acknowledged and does nothing

`rgpureset=1` issues `GFX_CTRL_CMD_ID_MODE1_RST` to `MP0_C2PMSG_64` before the PSP ring is
created, following `psp_v13_0_mode1_reset`. The mailbox handshake succeeds:

    XQ: MODE1 reset requested; C2PMSG_64=0x80010000
    XQ: MODE1 reset: C2PMSG_33=0x80000000 after 0ms (complete); C2PMSG_64 now 0x80070000

Bit 31 of `C2PMSG_33` comes back set, the command is echoed in `C2PMSG_64`, `TTL::initialize()`
still completes afterwards, and the host is unaffected -- so the risk that motivated putting
this behind its own boot-arg did not materialise. But it accomplishes nothing:

    XP: IC bases: CPC=0x8_5f904000 cntl=0x10 op=0x2 | PFP=0x8_5f87c000 | ME=0x8_5f8c0000
    XP: icache prime never completed after 50000us
    XP: MEC2 instr pntr over 16 samples: 0x310 ... (0 changes) MEC1=0x10000

The instruction-cache bases are byte-identical to before the reset. Had the PSP re-run its
bootloader and re-autoloaded the graphics firmware it would have chosen its own addresses, so
the graphics block was not reset at all -- the PSP acknowledged a command it did not carry
out, which is consistent with a guest that does not own the device asking for an ASIC-wide
reset through it.

That closes the last in-guest route. The command processor is the PSP's for the life of the
reset, and the only way to get one this guest can drive is to make sure amdgpu never claims
the device: `tools/enable-early-vfio.sh`.

## Three host hangs, no evidence, and why

The host has hard-hung twice during this work. Both times the signature is identical and
uninformative:

- the journal stops mid-line, with no shutdown sequence -- a hard hang or reset, not a stop
- no panic, no oops, no BUG, no machine-check anywhere in the surviving log
- `/sys/fs/pstore` empty, so no dmesg tail was persisted
- **`journald`'s `SyncIntervalSec` was the default five minutes**, so up to five minutes of
  kernel log was sitting in RAM when the machine died, and went with it

What differs between the two is only how long each configuration lasted:

| configuration | survived |
|---|---|
| amdgpu binds the iGPU at boot, `gpu-bind.sh` hands it over afterwards | ~33 VM launches over three hours (boot -3, 01:22) |
| vfio-pci claims it from boot, so it reaches the guest exactly as the firmware left it | **53 seconds into the first launch** (boot -1, 12:39) |

The second one is worth being precise about, because the obvious reading is wrong twice over.

The tempting conclusion was that this plugin's register surgery did it -- moving the
framebuffer aperture, rewriting the L2 and the GART, halting microengines. It cannot be
that: `run/serial.log` from the crashed boot ends at `BdsDxe: starting Boot0001` after 304
bytes, so the guest never reached XNU and none of that code ran.

But nor can the guest be said to have hung *there*. `sercat.py` wrote with `buffering=0` and
no `fsync`, so the bytes sat in the page cache until btrfs committed, and the last tens of
seconds of guest output died with the host. "The log stops at X" proves nothing unless the
writer fsyncs. The only honest statement is that the last *durably recorded* guest output
was OpenCore starting, and where it went after that is unknown.

Root cause: **undetermined, and not determinable from what was captured.** Two crashes
produced no diagnostic information at all. Everything below is about not being in that
position a third time.

### The third hang, and what it ruled out

2026-09-07 14:21, the first launch after a reboot, with the iGPU on vfio-pci from boot.
`sercat.py`'s fsync and journald's 1s sync were both active, so for the first time the
timeline is trustworthy to the second:

    14:20:07.634  vfio-pci 0000:7b:00.0: resetting / reset done
    14:21:17.559  last host journal entry (a routine UFW block; these arrive every ~18 s)
    14:21:21.743  last guest serial byte, fsynced
    14:21:35      the next periodic UFW block never arrives
    14:22:09      next boot

So the host was alive at 14:21:21.743 and dead within ~14 s of it, and **still logged
nothing** -- which retires the explanation that satisfied the second crash. journald was no
longer holding five minutes of log in RAM; the kernel simply never said anything. The reason
is on the command line: `nowatchdog`, with `nmi_watchdog`, `watchdog`, `hardlockup_panic` and
`hung_task_panic` all reading 0, while the kernel is built with
`CONFIG_HARDLOCKUP_DETECTOR_PERF=y`, `CONFIG_SOFTLOCKUP_DETECTOR=y` and
`CONFIG_DETECT_HUNG_TASK=y`. Three crashes' worth of "no evidence" has been a configuration
choice. `tools/enable-lockup-capture.sh` reverses it.

**A refuted hypothesis, recorded because the correlation was seductive.** The guest's last
two lines before the host died were

    dccg2_get_dccg_ref_freq:89   BREAK_TO_DEBUGGER point !!!.
    hubbub2_get_dchub_ref_freq:565 BREAK_TO_DEBUGGER point !!!.

which is DCN display-hub initialisation -- a fabric master, on an APU, being programmed by a
driver that thinks the block is Navi 23 (DCN 2.x/3.0) when Raphael is DCN 3.1.5. A plausible
way to wedge a fabric, arriving four seconds before the host died. It is not the cause:
**116 of the 149 archived runs contain those exact two lines** and did not hang the host.
They are simply where every run's log ends, because the display path is where the driver
gives up and stops printing. A last-line correlation is worth nothing until you check the
base rate.

That also means the third hang came *after* the guest had reached the same quiescent end
state that runs reach routinely. There is no guest-side milestone that predicts the hang, so
there is nothing to stop at -- only elapsed exposure to bound.

### Correction: BASE != OFFSET, and the instruction-cache bases were never amdgpu's

The one thing this crash bought. With amdgpu confirmed never to have bound the device this
boot (`journalctl -k -b | grep -c 'amdgpu 0000:7b:00.0'` == 0), the plugin's pre-TTL report
fires twice in the same run, and the first one is empty:

    XR: pre-TTL: IC bases CPC=0_00000000   cntl=0x10 op=0   | PFP=0_00000000   | ME=0_00000000
    XR: pre-TTL: IC bases CPC=0x8_5f904000 cntl=0x10 op=0x2 | PFP=0x8_5f87c000 | ME=0x8_5f8c0000

The registers start at zero and acquire those values during the **guest's** initialisation.
They are not host residue, and `enable-early-vfio.sh` -- whose entire rationale was that
they were -- has been disabled in place with the refutation written into its header. Two
host hangs to disprove the reason for taking the risk.

What writes them is the guest's own PSP during firmware autoload, and it writes
**host-physical** addresses, because the PSP runs against the real memory map:

    0x8_5f904000 - 0x840000000 = 0x1f904000   -> 505 MB into a 512 MB carveout

505 MB into 512 MB is exactly where firmware parks CP microcode. The address is real and the
microcode behind it is real. The problem is that the CP dereferences that register as an
**MC** address, through a GMC that Apple's driver has programmed for the guest's BAR0
window:

    GCMC_VM_FB_LOCATION_BASE = 0xf400000000     GCMC_VM_FB_OFFSET = 0x840000000
    MC -> phys = MC - BASE + OFFSET

    0x8_5f904000 as MC  ->  phys 0xff1c9f904000     nowhere
    MC that reaches it  ->  0xf41f904000

`BASE != OFFSET`, so every physical address the PSP programmed is unreachable through the
guest's own aperture. That is why autoload reports complete (`RLC_RLCS_BOOTLOAD_STATUS`
`0xc0000001`), both MECs are unhalted (`CP_MEC_CNTL = 0`), and the instruction pointers still
never move (`MEC2 = 0x44c`, 16 samples, 0 changes; `MEC1 = 0x44a`): the engines are alive and
idling, fetching from an address that does not resolve.

This is **not** the experiment already recorded under "Pointing the microcode at the register
instead". That one moved `FB_LOCATION_BASE` so the locked address would land on microcode the
*plugin* wrote and verified by readback. The correction says the PSP's own microcode is
already at physical `0x8_5f904000` and is genuinely correct -- so the move to make is
`GCMC_VM_FB_LOCATION_BASE = GCMC_VM_FB_OFFSET = 0x840000000`, an identity map onto the
carveout, which is how the host itself runs the GMC. Then every PSP-programmed physical
address is self-consistent and no register needs to be written that the PSP has locked.

Open question before trying it: Apple's driver reads `FB_LOCATION_BASE` back and derives its
own MC allocations from it, and BAR0 is at `0xf400000000` in the guest. Under an identity map
MC == phys and CPU-visible BAR0 offsets are `MC - 0x840000000`, which stays consistent *if*
the driver uses the base it reads rather than the BAR address it was given. That is the thing
to check in `AMDHWVMM` before spending a boot on it.

Implemented as boot-arg `rgpufb` in plugin 1.0.138, deliberately not a mask bit and
deliberately not behind `rgpucp`: `rgpufb=1` is the identity map and writes no microcode and
touches no CP register, `rgpufb=2` is the old `0x850000000` relocation, `0` (default) leaves
Apple's programming alone. `relocateFbAperture` now reads `FB_OFFSET` at runtime rather than
assuming `0x840000000`, and reports where the locked IC base resolves to so the arithmetic
is checkable from the log instead of from this document.

Open question before trying it: Apple's driver reads `FB_LOCATION_BASE` back and derives its
own MC allocations from it, and BAR0 is at `0xf400000000` in the guest. Under an identity map
MC == phys and CPU-visible BAR0 offsets are `MC - 0x840000000`, which stays consistent *if*
the driver uses the base it reads rather than the BAR address it was given. Worth checking in
`AMDHWVMM` first, though the run itself answers it: a driver that used the BAR address would
fail visibly in TTL init, not silently.

### Result: the identity map works, and it changes nothing for the CP

Run 2026-09-07 15:14, kext 1.0.138, `rgpufb=1`, amdgpu-first configuration.

The aperture move took and Apple's driver accepted it, which answers the open question above
-- the driver uses the base it reads back, not the BAR address it was handed:

    XP: rgpufb=1: FB aperture 0xf400..0xf41f (offset 0x840) -> 0x840..0x85f
    GPUCAP refresh() --- FB Base: 0x840000000, Top: 0x85fffffff, Offset: 0x840000000
    TTL::initialize() Completed successfully
    Accelerator successfully registered with controller

So `MC == physical` across the carveout, and `CP_CPC_IC_BASE = 0x8_5f904000` now resolves to
physical `0x8_5f904000`, the page the PSP's own autoloaded microcode is on. And:

    XR: post-TTL: BOOTLOAD 0x4e8d=0xc0000001 (complete=1) RLC_CNTL=0x1 RLC_STAT=0
    XR: post-TTL: MEC2 instr 0x44c ... 0x44c (0 changes -> not executing) MEC1=0x44a CP_MEC_CNTL=0

Identical instruction pointers to every previous run, zero movement across 16 samples, both
engines unhalted. **Address translation was never what stopped the command processor.** The
`BASE != OFFSET` mismatch was real and is worth having fixed, but it was not the blocker, and
the hypothesis in the previous section is refuted as far as the CP is concerned.

One thing to log about the log itself: the `XP: rgpufb=1` line reports "locked IC base 0 now
resolves to physical 0" because `relocateFbAperture` runs from `populateXGmiConfig`, before
the PSP has written the instruction-cache bases. The line is cosmetically wrong and cannot be
used to check the arithmetic; the `XR: post-TTL` report is the one that can.

Also worth recording, because it nearly went down as a breakthrough: the guest panics with a
NULL dereference in `AMDHWVMM::endVMPTUpdate`, reached from `WindowServer` through
`IOAccelCommandQueue::submit_command_buffers` -> `AMDAccelResource::BatchPrepareMappings`.
Seeing WindowServer submit real command buffers looks like enormous progress. It is not new:
**66 of the 149 archived runs reach exactly that panic.** Check the base rate before
believing a stack trace is a milestone -- the same mistake as the DCN correlation above.

### The CP microcode-fetch registers are read-only to the guest

Runs 2026-09-07 15:26 and 15:33, kexts 1.0.139 through 1.0.141, `rgpufb=1 rgpuic=1`.

With the address finally resolving, the obvious question was whether the instruction cache
can be made to prime. `CP_CPC_IC_OP_CNTL` carries `PRIME_ICACHE` (bit 4) and `ICACHE_PRIMED`
(bit 5), and post-TTL it reads `0x2` -- invalidate-complete set, prime never even requested.

The first two attempts at this test were worthless and are recorded as such. Both polled
`INVALIDATE_CACHE_COMPLETE` while that bit was **already set on entry**, so the loop exited
at zero microseconds having proved nothing, and a prime that then failed could not be
distinguished from a register that ignores writes. The third attempt added the controls that
make the answer mean something, and the answer is unambiguous:

    XP: controls: writes-land=0 (base_cntl 0x10 ^bit24 -> 0x10) complete-bit-cleared=0
                  | MEC_CNTL 0 -> halted 0x50000000
    XP: INVALIDATE completed after 0us | PRIME request-stuck=0 (op=0x2) NEVER COMPLETED
    XP: MEC2 0x44c..0x44c (0 changes) MEC1 0x44a..0x44a (0 changes) -> still not executing

Read the controls first:

  - `CP_CPC_IC_BASE_CNTL` is `0x10`; writing `0x10 ^ (1<<24)` leaves it `0x10`. Ignored.
  - `CP_CPC_IC_OP_CNTL` is `0x2`; writing it with bit 1 cleared leaves it `0x2`. Ignored.
  - Setting bit 4 (`PRIME_ICACHE`) does not stick either -- `request-stuck=0`, still `0x2`.
  - `CP_MEC_CNTL` is `0`; writing `0x50000000` reads back `0x50000000`. **Accepted.**

That last line is the control that matters. Writes from the plugin do reach this block --
`CP_MEC_CNTL` is in it and takes them -- so "the writes are ignored" is a property of these
specific registers and not of how the plugin gets at them. `CP_CPC_IC_BASE_LO/HI`,
`CP_CPC_IC_BASE_CNTL` and `CP_CPC_IC_OP_CNTL` are read-only to the guest; `CP_MEC_CNTL`,
three registers away, is not. And the "INVALIDATE completed after 0us" above is void: the
completion bit was never cleared, so observing it set proves nothing.

So the position is not that priming fails. **The guest cannot issue the command at all.** The
entire register group that configures where the microengines fetch their microcode is
hardware-protected for the life of the reset, which is what one would expect of the registers
that decide what code runs on the GPU, and it is consistent with `GFX_CMD_ID_AUTOLOAD_RLC`
answering `TEE_ERROR_BUSY`. This retires the whole family of approaches that try to get the
CP running by programming registers from the guest: the aperture is right, the microcode is
there, and the fetch configuration is not ours to touch.

**Where that leaves the CP.** The agent that primes the instruction caches and releases the
microengines on a healthy GFX10 is the RLC, and it reports enabled but idle in every run:

    RLC_CNTL=0x1   RLC_STAT=0   RLC_SAFE_MODE=0   RLC_RLCS_BOOTLOAD_STATUS=0xc0000001

`RLC_CNTL` bit 0 is `RLC_ENABLE`, so it is switched on; `RLC_STAT = 0` means no RLC thread is
busy -- not `RLC_BUSY`, not `RLC_GPM_BUSY`, not any of the three thread bits. Compare the `xl`
milestone, which treats `RLC_STAT == 0x25` (`RLC_BUSY | RLC_GPM_BUSY | RLC_THREAD_0_BUSY`) as
a live RLC. Bootload reports complete, but the microcontroller that would act on it looks
like it is not running. That is the next thing to characterise, and it is a different kind of
question from the ones answered so far: not "can we write this register" but "why is the
RLC's GPM idle after a successful autoload".

### Correction: the microengines DO execute, and the RLC is running

Both of the conclusions in the two sections above are wrong in their strongest form, and the
correction came from finally reading the registers properly.

**The RLC is running.** `rgpurlc=1` (kext 1.0.142) dumps it, and at probe time:

    RLC_CNTL=0x1  RLC_STAT=0x25  RLC_GPM_STAT=0x140017  RLC_SAFE_MODE=0
    RLC_SRM_CNTL=0x3  CSIB_ADDR_LO=0xfbc7000  CSIB_LEN=0x3b8
    RLC_RLCS_BOOTLOAD_STATUS=0xc0000001

`RLC_STAT = 0x25` is `RLC_BUSY | RLC_GPM_BUSY | RLC_THREAD_0_BUSY` -- precisely the value the
`xl` milestone treats as a live RLC. The save/restore machine is enabled and the clear-state
indirect buffer is programmed. The earlier `RLC_STAT = 0` readings that prompted "the RLC's
GPM is idle after a successful autoload" were sampled at a different moment; they were not
wrong, they were unrepresentative.

**Every RLC register is writable**, with `SCRATCH_REG0` and `CP_MEC_CNTL` as positive
controls:

    SCRATCH_REG0    0x00000000 ^0xa5a5a5a5 -> 0xa5a5a5a5   WRITABLE
    CP_MEC_CNTL     0x00000000 ^0x10000000 -> 0x10000000   WRITABLE
    RLC_CNTL        0x00000001 ^0x00000008 -> 0x00000009   WRITABLE
    RLC_SAFE_MODE   0x00000000 ^0x00000002 -> 0x00000002   WRITABLE
    RLC_PG_CNTL     0x00000000 ^0x00004000 -> 0x00004000   WRITABLE
    RLC_SRM_CNTL    0x00000003 ^0x00000002 -> 0x00000001   WRITABLE

So there is no protected RLC domain. The lock found earlier is narrow: it covers
`CP_CPC_IC_BASE_LO/HI`, `CP_CPC_IC_BASE_CNTL` and `CP_CPC_IC_OP_CNTL` and nothing else that
has been tried.

**Do not cycle RLC_ENABLE.** `rgpurlc=2` arms it and it is destructive: `RLC_STAT` went
`0x25` -> `0x5` with the bit cleared -> `0x0` after setting it again, and stayed 0 for the
rest of the run. Re-enabling the F32 does not restart it -- the microcontroller has to be
reloaded, which only the PSP can do -- so the cycle stops the one part of the block that was
working, and it moved the microengines not at all.

**The microengines executed and parked.** This is the reinterpretation that matters. The
program counters are *not zero*:

    CP_MEC1_INSTR_PNTR  0x44a      CP_PFP_INSTR_PNTR  0x2aa
    CP_MEC2_INSTR_PNTR  0x44c      CP_ME_INSTR_PNTR   0xea3
                                   CP_CE_INSTR_PNTR   0x37

A cold device -- the virgin vfio-from-boot run, before TTL -- reads `0` for all of them. So
every engine fetched and ran on the order of a thousand instructions of its boot sequence and
then stopped at a fixed address. The label in the log, `(0 changes -> not executing)`, means
"not advancing right now"; it has been read throughout this document as "never ran", and that
is wrong. **The command processor is alive and idle, not dead.**

Which moves the question from "why will the CP not fetch" -- it did fetch, and the icache
lock is consistent with the PSP having already set the fetch up correctly and having no
reason to let anyone change it -- to "why does no work ever reach the parked engines". That
is queue and doorbell territory, which is software we control, and it is a much better place
to be than a hardware lock.

### A new observability channel: read the registers from the host, through BAR5

`tools/hostregs.py` mmaps `/sys/bus/pci/devices/0000:7b:00.0/resource5` and reads the same
registers the in-guest plugin reads, using the same SOC15 arithmetic (byte offset =
`(base + reg) * 4`, GC segment 0 at `0x1260`, segment 1 at `0xa000`; every register of
interest is inside the 512 KB aperture, so none need the indirect PCIE index/data path).

It works **whatever driver owns the device** -- confirmed against `vfio-pci` -- needs no
guest, and reads only. Every register value this project had collected until now came from
inside the guest, where nothing works, while the same silicon runs correctly under amdgpu a
few seconds after every boot. That reference has never been read, and it is the obvious way
to settle whether `0x44a` is the normal idle park or a wrong one.

Baseline, device on vfio-pci immediately after a guest run, showing the identity map
surviving the guest and the parked counters matching what the guest reported:

    GRBM_STATUS 0xa0003028   GRBM_STATUS2 0x10008008   CP_STAT 0
    CP_MEC_CNTL 0            CP_CPF_BUSY_STAT 0x40000000
    CP_CPC_IC_BASE = 0x85f904000
    FB_LOCATION_BASE = 0x840000000   FB_OFFSET = 0x840000000

**Still to capture: the same dump with amdgpu bound and working.** Take it immediately after
a boot, before `gpu-bind.sh`, so amdgpu has initialised the device from scratch -- do NOT
reach it by handing a dirty GPU back with `gpu-restore.sh`, both because amdgpu would be
re-initialising a device whose GMC the guest has rewritten, and because rebinding to
vfio-pci afterwards is the cycle that wedges the device until a reboot.

### The endVMPTUpdate wall, and getting past it

This is the panic that actually stopped Metal, and it was our bug, not Apple's.

`WindowServer` submits a command buffer, `IOAccelCommandQueue` reaches
`AMDAccelResource::BatchPrepareMappings`, and `AMDHWVMM::endVMPTUpdate` dereferences NULL.
The faulting instruction, at symbol + 0x13, matching the panic's `RDI=0` and `CR2=0`:

    589ea: dec dword ptr [rdi + 0x3c]      nesting counter; work only when it reaches 0
    589ed: je   0x589f0
    589f9: mov  rdi, qword ptr [rdi + 0x28]    the DMA paging channel   -> NULL
    589fd: mov  rax, qword ptr [rdi]           FAULT
    58a00: call qword ptr [rax + 0x140]

`beginVMPTUpdate` is just `inc dword ptr [rdi + 0x3c]; ret`, so the two are a balanced pair
and the counter is not the problem.

`m_0x28` is written in **exactly one place in the whole kext**:
`AMDHWVMM::setMemoryAllocationsEnabled(true)` at `0x579a3`, immediately after it creates a
channel and immediately before it casts the same pointer to
`AMDRadeonX6000_AMDDMAHWChannel` and stores that at `m_0x30`. The creation sits behind an
idempotency guard:

    57930: test esi, esi
    57932: je   0x57a7b        enable == false -> teardown path
    57938: cmp  qword ptr [rbx + 0x20], 0x0
    5793d: jne  0x57ba8        m_0x20 already set -> skip creation entirely

Two hypotheses followed, and hooking the function refuted both. `AMDHWVMM::init` also writes
`m_0x20`, so the guard looked like the suspect -- but measurement says `m_0x20 = 0` after
init, so the guard is wide open. And the function is only ever called with **enable = 0**:

    XV: AMDHWVMM::init(iface=..., flags=2) -> 1 | m_0x18=0xffffff94e67c5800 m_0x20=0 m_0x28=0
    XV: setMemoryAllocationsEnabled(0) entry: m_0x20=0 m_0x28=0 m_0x30=0 nest(0x3c)=0

Nobody passes true, so the `je` takes the teardown branch and the channel is never built.

**Static analysis could not name the caller**, and the attempt to do so was a dead end worth
recording: `setMemoryAllocationsEnabled` is virtual, at vtable index 41 (`[rax + 0x148]`), and
slot `0x148` is also used by `AMDHWEngine`, `AMDHWChannel`, `AMDBltMgr` and others, so "who
calls `[rax+0x148]`" is unanswerable from the disassembly. `AMDHardware::startHWEngines` looked
like the caller and is not -- it null-checks the receiver and tests `al`, which is an engine's
slot. Capturing `__builtin_return_address(0)` in the hook and reporting it as an `x6+offset`
settled it immediately:

    AMDGFX10VMM::init +0x1b                          -> AMDHWVMM::init
    AMDHardware::setMemoryAllocationsEnabled(b) +0x88 -> AMDHWVMM::...(b)     only ever false
    AMDRTHardware::setVirtualSpaceReady(b) +0x111     -> AMDHWVMM::...(true)  fires correctly

So the outer `AMDHardware::setMemoryAllocationsEnabled(true)` is never reached, because it
sits on the powerUp path that fails -- while its vtable neighbour `setVirtualSpaceReady`
(index 40, `[rax + 0x140]`, immediately before `0x148`) *is* called with true.

`rgpuvmm=3` borrows that ordering and drives the missing call from there. It works:

    XV: setVirtualSpaceReady(1) | m_0x20=0 m_0x28=0  [caller x6+0x5e1c3]
    XV: driving setMemoryAllocationsEnabled(true) from here
    XV: after forced enable: m_0x20=0xffffffa18897e000 m_0x28=0xffffffa656343400
        m_0x30=0xffffff9cbceb5000 -> DMA PAGING CHANNEL PRESENT

**No panic.** The guest crossed the wall that ended every previous run and continued into
userspace with the AMD stack alive:

    AGDCC: ... AMDRadeonX6000_AmdGpuWrangler
    AGDCC: ... AMDRadeonX6000_AmdAgdcServices / AppleGraphicsDevicePolicy
    IOSurfaceRootUserClient::set_gpu_policy_dict
    com.apple.MTLCompilerService running

Read `AMFI: [non-fatal] unable to accelerate context` carefully: that is AMFI's own trust
cache message, not GPU acceleration, and it is not evidence either way.

**This is a graft, not a repair.** The honest fix is to make `ttlPowerUp` genuinely succeed so
`AMDHardware::setMemoryAllocationsEnabled(true)` is reached the normal way; milestone `xi`
only *reports* powerUp success, which is enough for the accelerator to register but not to
produce the allocation setup that follows. What the graft proves is that the rest of the
stack is sound once the channel exists, which isolates the remaining problem to the powerUp
path.

### A stale PSP ring stops the guest in firmware, and 304 bytes is not what it looked like

The run before this one produced a 304-byte serial log ending at `BdsDxe: starting Boot0001`,
with the host perfectly healthy. `QUIESCE=1` fixed it outright:

    gpu-quiesce: destroy all rings: 0x80010000 -> 0x80030000 after 7 ms
    gpu-quiesce: destroy GPCOM ring: 0x80030000 -> 0x800c0000 after 1 ms

which is what `redeploy.sh`'s own comment already said it was for -- use it when the guest
cannot get far enough to run milestone `x7`, and a firmware-stage hang is exactly that.

Worth re-reading the first two host crashes in this light. Both left 304-byte logs and that
was taken as "the guest never got far", but neither had `sercat.py`'s fsync, so the byte count
was a floor rather than a measurement. A genuine 304 now means the guest really did stop in
OVMF -- and here the cause was a recoverable stale ring, not anything fatal.

### CORRECTED: the VBIOS does have a display object info table, at index 22

> **This section's original conclusion was wrong.** It claimed the VBIOS has no display
> object info table, because index 16 of the master data table reads `0x0000`. Index 16 is
> not `displayobjectinfo`. The real `atom_master_list_of_data_tables_v2_1` order puts
> `displayobjectinfo` at **index 22**, `dce_info` at 27, `vram_info` at 28 -- only the last
> two of which I had right, and `vram_info` by coincidence. Index 22 reads `0x2284`, and
> there is a perfectly good `display_object_info_table_v1_4` there. The plan to synthesise
> one from scratch was unnecessary. What follows is corrected; the mistake is left visible
> because a wrong table index produced a confident, entirely false structural claim.

    display_object_info_table_v1_4 @0x2284  size=205 rev=1.4
    supporteddevices=0x0688  number_of_path=6

    path[0] objid=0x340c type=3 enum=4 id=0x0c HDMI_TYPE_A  enc=0x211e device_tag=0x0400 DFP3
    path[1] objid=0x0000 (empty)                            enc=0x221e device_tag=0x0000
    path[2] objid=0x3113 type=3 enum=1 id=0x13 DISPLAYPORT  enc=0x2120 device_tag=0x0008 DFP1
    path[3] objid=0x3213 type=3 enum=2 id=0x13 DISPLAYPORT  enc=0x2220 device_tag=0x0080 DFP6
    path[4] objid=0x3313 type=3 enum=3 id=0x13 DISPLAYPORT  enc=0x2121 device_tag=0x0200 CV2
    path[5] objid=0x7103 type=7 id=0x03                     enc=0x0000 device_tag=0x0000

`atom_display_object_path_v2` is **16 bytes** (seven `uint16_t` plus two `uint8_t`), not 24 --
getting the stride wrong on the first read produced garbage for paths 1, 3, 4 and 5 and made
the table look corrupt when it is not.

It matches amdgpu's connector list one-for-one: `HDMI_TYPE_A enum 4 / DFP3` is amdgpu's
`HDMI-A-3` (the port the monitor is on), and the three DisplayPorts are `DP-3`, `DP-4`,
`DP-5`. `supporteddevices = 0x0688 = 0x008|0x080|0x200|0x400`, exactly the four real device
tags -- so the firmware itself does not count the two tagless entries as devices.

**The bug is two paths with `device_tag == 0`**: the empty `objid=0x0000` entry and the
`objid=0x7103` one that amdgpu exposes as `Writeback-2`. amdgpu tolerates them. Apple asserts
on precisely them, in `populateConnectorEntry`.

`mkrom.py` now drops any path whose `device_tag` is zero, compacts the array in place and
reduces `number_of_path`, leaving the records that follow the array untouched -- the offsets
inside each entry point at those records absolutely, so moving whole 16-byte entries keeps
them valid. `--keep-dead-display-paths` restores the old behaviour.

Result, measured:

    device_tag assert     1 -> 0     gone
    connectorCount assert 0 -> 0     never fired
    framebuffers          3 -> 4     FB:0..FB:3, matching the four kept paths

### The next display blocker is the DCN version, not the connector table

The connector fix was necessary and is not sufficient. All four framebuffers still report
`Driver is offline`, and the driver now gets further before failing -- which is the progress:

    dccg2_get_dccg_ref_freq:89     BREAK_TO_DEBUGGER
    hubbub2_get_dchub_ref_freq:565 BREAK_TO_DEBUGGER
    generic_reg_wait:513           BREAK_TO_DEBUGGER   x4, one per framebuffer

The four `generic_reg_wait` timeouts are new: previously the driver gave up before attempting
to bring the pipes up. Apple's code is DCN 2.x/3.0 (it thinks this is Navi 23) and the silicon
is DCN 3.1.5, so the register offsets it waits on are not the ones that move. That is the
display-path work memory has always listed as future, and it is a large job -- reconciling a
whole display block's register map -- not a one-line graft.

### The original claim that a monitor cannot work is superseded

The earlier text said no cabling could help because the driver had no way to know a connector
exists. Half right: the connector table was being rejected, not absent. With it accepted, the
driver enumerates four connectors and tries to light them up. It still cannot, for the DCN
reason above.



A real monitor was connected to the iGPU's HDMI port. It stays dark, and the reason is not
the cable, the port, or hotplug -- the guest was rebooted with the display attached from the
start and nothing changed.

    ATOM: AmdAtomObjectInfo_V1_4::populateConnectorEntry(atom_display_object_path_v2 *,
          AtomConnectorEntry &) const: ASSERT(0 != object->device_tag)
    [0:6:0] [FB:0] AmdRadeonFramebuffer::setCursorImage() !!! Driver is offline.
    [0:6:0] [FB:1] ... [FB:2] ...

The master data table says why. Dumping all 35 entries of `atom_master_list_of_data_tables`
at `0x210`:

    [16] displayobjectinfo        0x0000   <-- absent
    [21] dce_info                 0x0000   <-- absent
    [27] dispdevicepriority_info  0x05e8
    [28] vram_info                0x0000   <-- absent, which is why mkrom.py grafts one
    [30] integratedsysteminfo     0x06bc   (v2.2, 1024 bytes)

There is no display object info table at all, so Apple's parser is reading an absent table,
every `device_tag` is zero, and no connector survives. All three framebuffers then report
offline. No amount of cabling fixes that: the driver has no way to know a connector exists.

Note the pattern -- `vram_info` is absent too, and `mkrom.py` already synthesises and grafts
one. The display fix is the same shape: build a `display_object_info_table_v1_4` with at
least one valid `atom_display_object_path_v2`, and graft it at index 16. Apple's framebuffer
kext carries a second assert, `ATOM: %s: ASSERT(0 != connectorCount)`, so an empty table is
rejected as firmly as an absent one.

What is NOT yet known is the correct content. On an APU the real topology comes from
`integratedsysteminfo` plus IP discovery, which Apple's Navi 23 driver never consults, and
this chip's `integratedsysteminfo` is v2.2 and mostly zeroes in its leading fields. Scanning
the ROM for connector-shaped object ids (`type nibble 3`) returns only noise -- random 16-bit
patterns match the mask. Object ids must not be guessed: a wrong `atom_display_object_path_v2`
fails as memory corruption, not as an error.

The reliable source is amdgpu's own view of this silicon, which does enumerate connectors on
this board. Capture it with the iGPU bound to amdgpu, immediately after a boot and before
`gpu-bind.sh`:

    ls -l /sys/class/drm/ | grep -i card            # which card is the iGPU
    for c in /sys/class/drm/card*-*/; do echo "$c $(cat $c/status) $(cat $c/enabled)"; done
    journalctl -k -b | grep -iE 'amdgpu 0000:7b:00.0.*(connector|display|dcn|link)'

together with `tools/hostregs.py`, which still needs its amdgpu-bound reference dump.

### The display blocks everything else, including verifying Metal

Worth stating plainly, because it reorders the remaining work. There is no way into the guest
right now:

  - the command agent is a shell loop that has to be typed into a logged-in Terminal by
    `drive.py` screen automation, so it needs a rendered display and does not survive a boot
  - `guest-login.sh` drives the emulated display, checking screen brightness to find the
    login window -- and the emulated framebuffer freezes at kernel time 0.097 s, because
    `debug=0x108` moves the console to serial and macOS then hands the display to the AMD
    framebuffer, which is offline
  - port 50922 accepts connections, but that is only docker-proxy listening; the guest's
    sshd answers `Connection closed`, so Remote Login is not enabled

So `system_profiler`, a Metal device query, or any functional compute test are all
unreachable until a display works. Metal itself may well be fine -- the accelerator
registers, the DMA paging channel now exists, `MTLCompilerService` is running, and nothing
panics -- but "may well be fine" is not a measurement, and it will not become one from the
kernel log alone.

Do not read `AMFI: [non-fatal] unable to accelerate context` as evidence either way. That is
AMFI's own trust-cache message and has nothing to do with GPU acceleration.

### Metal enumerates: "Metal Support: Metal 3", measured from inside the guest

A root command channel now survives a boot with no login and no display, which is what made
this measurable at all. From inside the guest, with the iGPU passed through:

    system_profiler SPDisplaysDataType
      AMD Radeon Navi23
        Chipset Model: AMD Radeon Navi23      VRAM (Total): 512 MB
        Device ID: 0x73ff                     Revision ID: 0x00cb
        ROM Revision: 102-RAPHAEL-008
        Metal Support: Metal 3

    MTLCreateSystemDefaultDevice() -> name=AMD Radeon Navi23, lowPower=0, headless=0,
                                      recommendedMaxWorkingSetSize=268435456
    IOClass = AMDRadeonX6000_AMDNavi23GraphicsAccelerator
    IOMatchCategory = IOAccelerator

So the userspace half is in place: macOS advertises the part as a Metal 3 device and hands out
a real `MTLDevice`. That is enumeration, not execution, and the two must not be conflated.

### The accelerator's own counters name the remaining blocker

`ioreg -rc AMDRadeonX6000_AMDNavi23GraphicsAccelerator` exposes
`PerformanceStatisticsAccum`, which is the most useful diagnostic found in this project:

    surfaceCount = 19    textureCount = 105    context2DCount = 4
    gartUsedBytes = 4874240        inUseSysMemoryBytes = 4874240
    vramFreeBytes = 0              inUseVidMemoryBytes = 0
    HWChannel GFX   | Commands Submitted = 0, Completed = 0
    HWChannel KIQ   | Commands Submitted = 0, Completed = 0
    HWChannel SDMA0 | Commands Submitted = 0, Completed = 0
    HWChannel SDMA1 | Commands Submitted = 0, Completed = 0
    Device Utilization % = 0       recoveryCount = 0

The driver allocates freely in GART and creates surfaces, textures and 2D contexts -- but the
VRAM heap holds **zero bytes** and **not one command has ever reached any hardware channel**,
not from a Metal command queue and not from WindowServer.

That reframes the parked microengines. `MEC1 = 0x44a`, `MEC2 = 0x44c`, unhalted and static, was
read for a long time as a hardware problem, and the `CP_CPC_IC_BASE*` registers genuinely are
read-only to the guest. But idle engines are exactly what one expects when **there is no work
to fetch because there is no VRAM to build rings in**. The icache lock may be no obstacle at
all: the PSP configured fetch correctly and has no reason to let anyone change it.

### VRAM: 0 -> 256 MB, by calling AMDHWMemory::enableAllocations

`AMDHWMemory::enableAllocations` (x6+0x52a1e) populates the VRAM heap, takes no arguments
beyond `this`, and is never called -- the XH hook logs `initVRAMInfo` every boot while
"enableAllocations entry" never appears, because it sits downstream of the ttlPowerUp failure
that milestone `xi` only *reports* as success.

It gates on two pool pointers, and this is the part that had never been checked:

    52a2b: mov rdi, qword ptr [rdi + 0x68]   ; pool A, null-tested
    52a38: cmp qword ptr [rbx + 0x70], 0x0   ; pool B

The XH hook's long-standing "pool0/pool1" log is the *sizes* at +0x40/+0x48, a different
thing. Boot-arg `rgpumem=1` reports the real pointers before anything acts on them:

    XH: initVRAMInfo -> 1 base=0xf400000000 ... size0=0x20000000 size1=0x10000000
        | poolA(0x68)=0xffffff98da673500 poolB(0x70)=0xffffff98da673580
    XM: AMDHWMemory::setVirtualSpaceReady(1) | size0=0x10000000 size1=0x10000000
        poolA=0xffffff98da673500 poolB=0xffffff98da673580  [caller x6+0x529df]

Both pools are real, so the call would do work rather than bail. `rgpumem=2` then makes it,
from `AMDHWMemory::setVirtualSpaceReady(true)` -- the memory-side twin of the VMM hook the
paging-channel graft already uses. Measured result:

    vramFreeBytes  0  ->  268435456      (256 MB)
    no panic, accelerator still registers, no "There is 0 free memory remaining"

That is the first time this GPU has had a usable VRAM heap under macOS.

**Still zero submissions.** `HWChannel GFX/KIQ/SDMA* Commands Submitted` remain 0,
`inUseVidMemoryBytes` is still 0, and `ioreg -rc IOAccelerator` reports **no**
`IOAccelCommandQueue` user clients. So VRAM being available has not by itself caused anything
to be dispatched. Next question is why no client opens a hardware queue.

### Measuring Metal needs a real toolchain; JXA cannot do it

`clang`, `swift`, `swiftc`, `xcrun` and `python3` all exist in the guest but are bare
xcode-select stubs -- "No developer tools were found" -- so nothing compiles.

JavaScript for Automation gets partway: `ObjC.import('Metal')` works,
`MTLCreateSystemDefaultDevice()` returns a device, `d.name`, `d.isHeadless`,
`d.recommendedMaxWorkingSetSize` all read correctly, and `d.newCommandQueue` yields a live
queue. It then dead-ends: `q.commandBuffer` reports `typeof function` but calling it throws
`TypeError: Object is not a function`. JXA cannot dispatch `MTLCommandQueue`'s protocol
methods, so no command buffer can be created, committed or waited on from AppleScript.

The guest does have working internet (github 200, swscan 404 = reachable), and
`softwareupdate -l` offers "Command Line Tools for Xcode-16.4" (861 MB), which installs
headlessly after
`touch /tmp/.com.apple.dt.CommandLineTools.installondemand.in-progress`. That is the route to
a genuine compute-kernel test rather than device enumeration.

### The guest command channel, made permanent

The deadlock was: the agent had to be typed into a logged-in Terminal, login needed a rendered
display, and the display needs DCN 3.1.5 work. Broken by booting **without** passthrough --
where the EFI framebuffer renders the login window normally (screen mean brightness 1171 ->
46562) -- logging in once, and installing the agent as a LaunchDaemon:

    /usr/local/bin/rgpu-agent.sh          the poll loop, root
    /Library/LaunchDaemons/as.rgpu.agent.plist   RunAtLoad + KeepAlive

`/Library` is not SIP-protected, so this installs with sudo alone. It starts before any login
and needs no display, verified under passthrough with a nonce: agent answered as **root** at
guest uptime 54 s. SSH was the wrong target by comparison --
`systemsetup -setremotelogin` demands Full Disk Access and `com.openssh.sshd` is not loaded as
a service.

### Correction: the "304-byte OVMF hangs" were my own watchdog, not the guest

Several runs produced a 304-byte serial log ending at `BdsDxe: starting Boot0001`, which was
recorded as a stale-PSP-ring firmware hang that `QUIESCE=1` fixed. That is wrong.

`redeploy.sh`'s exposure watchdog originally matched the container by **name**, so a watchdog
left over from an earlier launch tore down whatever VM was running when it woke. Three were
found still sleeping (`78161`, `101027`, `122299`) from pre-fix launches; one fired 90 seconds
into a launch that had been given `RGPU_MAX_SECONDS=900`, and the giveaway was a
"RGPU_MAX_SECONDS=300 reached" line in a log belonging to the 900 s run. The guest was never
hanging -- the container was being destroyed while still in firmware. `QUIESCE=1` appearing to
fix it was coincidence.

The watchdog now captures the container id and exits harmlessly if another run owns the name.
Note when clearing strays: killing the `sleep` alone makes the parent subshell fall straight
through to `docker rm -f`, so the parent must be killed first.

### The page-table base was not an MC address, and the CP was never hardware-locked

The single most useful measurement in this project, and it retires a theory several sections
above rest on.

`XJ: before RLC start` had been printing `VM_FAULT_STATUS=0xd33 addr=0_0f40fdfc` all along.
Decoded, that is a GPU page fault at `0xf40fdfc000` -- and `0x0fdfc000` is where the GART page
table lives. The GPU was faulting trying to read its own page directory.

Three addresses exist for that one page, and the driver uses the wrong two:

    AMDHWMemory base     (+0x50) = 0xf400000000    the guest BAR0 address
    AMDHWMemory reserved (+0x58) = 0xebc0000000
    base - reserved              = 0x840000000     == GFXHUB FB_LOCATION_BASE, exactly

    base + off      = 0xf40fdfc000   BAR-relative     <- what faulted
    reserved + off  = 0xebcfdfc000   what was in CTX0 PAGE_TABLE_BASE
    (base-reserved) + off = 0x84fdfc000   the real MC address, inside the aperture

`reserved` is the correction term that turns a BAR-relative address into an MC address. On a
discrete GPU `FB_OFFSET` is 0, `base == reserved == 0`, and all three collapse to the same
number -- which is exactly why nothing upstream has ever tripped over this. On this APU they
diverge by `0xebc0000000`.

Both hubs, measured, because they disagree:

    GFXHUB  base=0x840 top=0x85f offset=0x840     the hub the CP and GART actually use
    MMHUB   base=0x100 top=0     offset=0         unconfigured
    GPUCAP  FB Base 0x840000000                   Apple's own view agrees with GFXHUB

**The first version of this fix was wrong and the guard caught it.** The initial theory was
"the register is short by FB_OFFSET, add it back". Report-only mode printed the arithmetic and
refused: `addr + FB_OFFSET` lands *outside* the aperture. The correct derivation needs
`reserved` from AMDHWMemory, and the repair now cross-checks that `base - reserved` equals the
GFXHUB framebuffer base before it writes anything. Boot-arg `rgpuptb=1`; `rgpuptb=0` reports
only.

Applied, measured, and it holds:

    XT: fillVMRegisters: base-reserved=0x840000000 (matches GFXHUB base: 1)
    XT: fillVMRegisters: VRAM offset=0xfdfc000 -> correct MC=0x84fdfc000
                         addr outside=1 want inside=1
    XT: fillVMRegisters: rewrote CTX0 ptb 0xebcfdfc001 -> 0x84fdfc001, reads back OK
    XT: programAndInvalidateVM: not reserved-relative, leaving it alone   (x5, guard holding)
    XM: post-TTL: CTX0 ptb=0x8_4fdfc001                                  (repair persists)

**What this retires.** "Why the command processor never executes" and everything built on the
`CP_CPC_IC_BASE*` lock can now be read differently. Those registers are genuinely read-only to
the guest -- that measurement stands, with positive controls -- but they were never the
obstacle. The PSP had configured microcode fetch correctly all along. The engines parked at
`MEC1=0x44a` / `MEC2=0x44c` because a page table the GPU could not address meant nothing
reachable existed to fetch.

### But the driver never submits, so the CP is not the current blocker either

With the page table repaired and the fault cleared, the accelerator's counters are unchanged:

    HWChannel GFX | Commands Submitted = 0, Completed = 0     (KIQ, SDMA0, SDMA1 likewise)
    vramFreeBytes = 268435456   inUseVidMemoryBytes = 0
    Device Utilization % = 0    recoveryCount = 0

`Commands Submitted` is a *software* counter incremented by the driver on submission. Zero
means the driver never dispatches anything, which is upstream of the hardware entirely. So
`wptr=8, rptr=0` on the me2 queues is leftover queue-setup state from KIQ initialisation, not
client work waiting to be consumed -- an important re-reading of a number that looked like
evidence of a stalled fetch.

That returns the blocker to the powerUp chain. `AMDHardware::startHWEngines` is routed and
never logs an entry, so the hardware channels are never started and `submitCommandBuffer` is
never reached. The chain remains:

    ttlPowerUp fails (0xe00002c7, milestone xi only *reports* success)
      -> accelPowerUpHW / hardwarePowerUp / powerUpHWEngines / startHWEngines never run
      -> channels never started
      -> no submissions, on any channel, ever

`rgpuvmm=3` and `rgpumem=2` grafted around two of the consequences (the DMA paging channel and
the empty VRAM heap) and both worked, which is what made the page-table bug visible at all.
Neither addresses the cause.

### The whole powerUp chain, traced to one failure: the KIQ stamp timeout

Every "graft around a consequence" in this document leads back to a single point. Traced by
hooking each level and reading the return values, not by guessing:

    Stamp Timeout for KIQ Submission!
      AMDGFX10KIQHWChannel::startKIQ (x6+0x8e670)  submits MAP_QUEUES, waits, times out
      AMDGFX10PM4Engine::powerUp     (x6+0x6816a)  -> 0
      AMDHardware::powerUpHWEngines  (x6+0x6fe9a)  -> 0   engine 0 PM4
      AMDHardware::powerUp           (x6+0x701ba)  -> 0
      AMDGFX10Hardware::powerUp      (x6+0x73e68)  -> 0
      AMDNavi23Hardware::powerUp     (x6+0x99618)  -> 0
      AMDGraphicsAccelerator::powerUpHW            -> 0
        => AMDHWMemory::enableAllocations never called   (VRAM heap empty)
        => AMDHardware::startHWEngines never runs        (channels never started)
        => HWChannel * Commands Submitted = 0            (nothing ever dispatched)

The branch structure was decoded rather than assumed. `AMDNavi23Hardware::powerUp` fails on
either (a) the superclass returning false or (b) `[this+0x3b0]` failing a cast to
`AMDPM4HWEngine`; measurement shows the PM4 engine object is present
(`[this+0x3b0]=0xffffff99b39cb400`), so it is (a). `AMDHardware::powerUp` needs both
`AMDGFX10Hardware::setVMRegisters` (vtable 0x608) and `AMDHardware::powerUpHWEngines`
(vtable 0x618) to return true, and the plugin's own engine walk pins it on engine 0:

    XJ: engine 0 PM4 at 0xffffff99b39cb400 vtable=... powerUp -> 0

So the KIQ blocker documented much earlier in this file was never a side issue. It is *the*
blocker, and everything else recorded here -- the missing DMA paging channel, the empty VRAM
heap, the wrong page-table base -- are consequences or independent bugs found on the way to it.
Three of those were worth fixing on their own merits and are fixed; none of them makes the GPU
execute.

**Correction, and it matters.** An earlier note in this document read `wptr=8, rptr=0` on the
me2 queues as "leftover queue-setup state, not stalled client work", on the grounds that
`Commands Submitted` is a software counter reading zero. That was wrong. Those eight dwords
*are* the KIQ MAP_QUEUES packet that `startKIQ` submits, and `rptr=0` means the command
processor genuinely never consumed it. `Commands Submitted` is zero because it counts *client*
submissions through the started channels, which never start -- precisely because this KIQ
packet is never consumed. The CP failing to fetch is the real blocker, not an artefact.

**What the page-table repair did and did not buy.** `rgpuptb=1` is correct and holds: CTX0's
page-table base was `reserved`-relative (`0xebcfdfc000`) instead of an MC address
(`0x84fdfc000`), the repair sticks, the guard declines every later call, and
`VM_FAULT_STATUS` goes to 0. It did not make the CP consume the KIQ packet. The obvious next
question is whether the *contents* of that page table are wrong in the same way -- the KIQ ring
sits at MC `0xffbfea0000`, inside CTX0's range `0xffbfa00000..0xffffe00000`, so its PTE has to
be walked and checked. `walkGart()` already exists in the plugin for exactly this.

### The same address bug again, in the MEC's own pointers -- and the wall behind it

Two more instances of the BAR-relative-instead-of-MC confusion, both in registers the
microengine uses directly, plus a tooling bug that had been hiding them.

**`walkGart` had never walked anything.** It used the page-table base as a BAR0 *offset*. With
`ptb` at `0x84fdfc000` and the aperture 256 MB long, its bounds check could never pass, so
every call printed "outside the 256 MB BAR0 aperture" and no PTE was ever read. Fixed to
subtract `GCMC_VM_FB_LOCATION_BASE` first. Same class of mistake as the page-table base
register itself: an MC address and an aperture offset are not interchangeable.

With that fixed, the page table's *contents* check out, which rules out the obvious follow-up
to the base repair:

    XN: ring va=0xffbfea0000 idx=0x4a0 pte@fb+0xfdfe500 = 0x30002bb9e0077
        -> pa 0x2bb9e0000  flags VALID SYSTEM SNOOPED READ WRITE
    XN: rptr report / wptr poll -> pa 0x2bba60000  VALID SYSTEM SNOOPED READ WRITE

**`dumpMqd` had the same defect** and so had never once read the descriptor. Fixed to accept
all three address forms and report which it got. The MQD then reads:

    XN: mqd va=0xf40b706000 is BAR-relative, offset 0xb706000 -> correct MC 0x84b706000
    XN: MQD@fb+0xb706000: header=0xc0310800 mqd_base=0xb706000 active=0x1 vmid=0
    XN: MQD: pq_base=0xffbfea00 rptr=0 doorbell_ctl=0x40000000 pq_control=0xd130860d
    XN: MQD: eop_base=0xf40b7068 eop_control=0x8 wptr_lo=0 wptr_hi=0

So `CP_MQD_BASE_ADDR` and the MQD's `eop_base` are both BAR-relative, outside the
`0x840000000..0x85fffffff` aperture. `pq_base` (`0xffbfea00 << 8`) is a GART VA and correct.
The MEC reloads the HQD from `CP_MQD_BASE_ADDR`; a descriptor it cannot read is a queue that
never really runs.

`rgpumqd=1` repairs registers **and** the in-VRAM image, since the image is what the engine
restores from -- repairing only registers is futile and is the documented reason writes to
`CP_HQD_EOP_BASE_ADDR` "do not stick". Measured:

    XQ: MQD_BASE   0xf40b706000 -> 0x84b706000    register and image both repaired
    XQ: EOP image  0xf40b706800 -> 0x84b706800    image repaired
    XQ: EOP register wrote 0x84b7068, reads back 0    DID NOT STICK
    XQ: rptr still 0 after 100 ms (wptr=0x8)          engine still not consuming

**The wall.** `CP_HQD_EOP_BASE_ADDR` reads 0 and refuses writes even with the MQD base now
correct, and the engine still does not consume the KIQ MAP_QUEUES packet. So the KIQ stamp
timeout survives every address repair made so far. What is left to try, in order of cheapness:

  - dequeue the queue first (`CP_HQD_DEQUEUE_REQUEST`) so the HQD is writable, repair, requeue
  - check whether the HQD must be written through the RLC's indirect path (`RLCG_INDIRECT` /
    `WREG32_SOC15_RLC*` in upstream) rather than the plugin's `fbWrite`, which would also
    explain the `CP_CPC_IC_BASE*` "read-only" result
  - confirm the MEC is actually reloading from the repaired MQD rather than a stale copy

**What is now known to be sound**, and should not be re-investigated: GART page-table base and
contents, the ring VA and its PTE, the DMA paging channel, the VRAM heap, the connector table,
Metal enumeration. Each of those was a real bug or a real gap, all are fixed, and none of them
is what stops the GPU executing.

### A hypothesis this raises about the hangs themselves

Not established, and recorded as a hypothesis rather than a finding, but it fits better than
anything before it.

`FB_LOCATION_BASE != FB_OFFSET` does not only affect the CP. It is the framebuffer aperture
translation for **every** fabric master behind the GFXHUB -- CP, SDMA, and the DCN display
hub. Any MC address a master emits inside `[BASE, TOP]` is translated as `MC - BASE + OFFSET`
and goes straight to DRAM through the host's memory controller, because on an APU the
framebuffer is a DRAM carveout and this path is not the PCIe path the IOMMU polices. With
`BASE = 0xf400000000` and `OFFSET = 0x840000000` the mapping is only meaningful for addresses
the guest's driver generated; anything a master emits that the *firmware* generated -- which
is exactly what the PSP writes -- lands somewhere else entirely.

That would produce precisely the signature we have: a hard hang at unpredictable timing,
only ever with the iGPU passed through, with nothing in the kernel log because the kernel's
own pages are what got written. It also explains why the amdgpu-first configuration survived
~50x longer without being safe: the difference would be which stale firmware-era addresses
happen to be sitting in the masters' registers when the guest starts, not whether the hazard
exists.

If it is right, `rgpufb=1` is not only the route to a working command processor, it is the
mitigation -- an identity map is the configuration the host itself runs, so every physical
address any master emits is self-consistent. If it is wrong, the run costs one boot and the
lockup detectors will finally have something to say about it. Either way it is the next
thing to do, and it should be done with `tools/enable-lockup-capture.sh` already applied.

### What is in place now

**Passthrough is opt-in.** `./redeploy.sh` now runs the guest with no passthrough; `--gpu`
asks for it. It used to be the other way round, which meant `autorun.sh` -- a loop that calls
`./redeploy.sh` with no arguments -- held the iGPU across dozens of unattended launches. That
is the shape of the first crash: ~33 launches over three hours with nobody at the machine.
`autorun.sh` now needs `AUTORUN_GPU=1` and says which mode it is in, because a GPU-less rung
cannot produce a verdict about the graphics core and the log should not imply otherwise.

**The virgin-iGPU configuration is refused outright, with no override.** The old
`RGPU_ALLOW_VIRGIN_IGPU=1` escape hatch is gone: it existed for one experiment, the
experiment ran twice, it cost two hangs, and it disproved its own premise. Exposure survived
was ~100 minutes of guest runtime in the amdgpu-first configuration against 53 s and ~74 s
in the virgin one -- about fifty times, for the same number of crashes. Not a mechanism, but
far too large to be luck, and the virgin path buys nothing.

**Exposure is capped.** `RGPU_MAX_SECONDS` (default 300) stops the container and releases the
device. Since the third hang came after the guest reached its normal quiescent state, there
is no milestone to stop at -- elapsed time is the only thing left to bound, and bounding it in
the script beats trusting whoever is driving to remember.

`sercat.py` fsyncs every chunk. At a few hundred kilobytes per boot the cost is nothing, and
it is the difference between knowing where the guest was and guessing.

`tools/enable-diagnostics.sh` sets `SyncIntervalSec=1s` and `Storage=persistent`. Active
now, no reboot: the kernel log is durable to within a second of a hang instead of losing up
to five minutes. This is the change that matters.

It does *not* get pstore working, and the first version of the script that claimed to was
wrong. This kernel has `CONFIG_EFI_VARS_PSTORE=y` together with
`CONFIG_EFI_VARS_PSTORE_DEFAULT_DISABLE=y`, so `efi_pstore` is compiled in and inert:
`/sys/module/pstore/parameters/backend` reads `(null)`, and `modprobe efi_pstore` is a no-op
because there is no module to load. Turning it on needs `efi_pstore.pstore_disable=0` on the
kernel command line, which is a boot-config change on a Secure Boot install with hash-pinned
images. The script now detects the null backend and says so, printing the exact change as a
decision rather than writing a `modules-load.d` drop-in that looked like it had done
something. And it would only help for a hang the kernel notices -- a fabric-level lockup
that stops the CPU dead leaves nothing either way.

`tools/disable-early-vfio.sh` reverts the early binding, restoring the configuration that
lasted three hours rather than 53 seconds. Nothing is given up by reverting: the host died
before the guest kernel loaded, so that boot never revealed whether the command processor
would have been usable.

`tools/enable-lockup-capture.sh` is the change the third hang argues for, and the one still
waiting on a reboot. It drops `nowatchdog` from `KERNEL_CMDLINE[default]` and adds
`nmi_watchdog=1 hardlockup_panic=1 efi_pstore.pstore_disable=0 panic=20`, so a wedged CPU
panics instead of hanging silently, the dmesg tail lands in EFI variables and survives the
power cycle, and the box reboots itself instead of needing the reset button. It edits the
command line only -- no kernel is signed and no image is regenerated, so Secure Boot and
Limine's blake2b pinning are not involved; `limine-update` rewrites `limine.conf` and the
previous command line is backed up beside it.

If the failure stops the CPUs or wedges the fabric outright this changes nothing, which is a
real possibility given the signature. But the hard-lockup detector fires from a performance
counter NMI, which reaches a CPU spinning with interrupts disabled -- the case that is
invisible today and the most useful thing left to learn.

### 2026-09-08: PSP placement is verified and KIQ executes

The PSP response structure settles the firmware-address question.  `psp_gfx_resp.fw_addr`
is populated for the recorded CP `LOAD_IP_FW` responses; Linux retains that value as the firmware's
TMR address.  The added trace records the submitted source and returned destination without
reading protected TMR memory.  In the first clean run:

```
LOAD_IP_FW type=4 source=0xf40fc00000/0x414b0 -> tmr=0xf41f904000
IC bases CPC=0x8_5f904000  PFP=0x8_5f87c000  ME=0x8_5f8c0000
```

Those instruction-cache values are the same TMR placement expressed through the active
GFXHUB mapping.  They are not retained host-amdgpu addresses.  All firmware loads reported
status zero and nonzero destinations where applicable (some firmware types return zero).
These measurements refute the stale-host-address diagnosis; they do not establish that
every firmware payload is compatible with later workloads.

The same run finally proves that the command processor and KIQ execute.  Each native setup
frame advances the selected KIQ read pointer to its write pointer (`0x20`, `0x40`, `0x60`),
with no GFXHUB VM fault; `waitForHwStamp` succeeds.  The previous claim that MEC never
executed is withdrawn.  Metal still fails on its first command buffer (`MTLCommandBuffer`
status 5, internal error `e00002bd`), so Metal enumeration remains insufficient evidence of
acceleration.

Subsequent runs encountered an active KIQ (`RPTR=0x86, WPTR=0xa0`) whose dequeue did
not complete within 50 ms. The guard refused to overwrite the live descriptor. Graceful
guest shutdown is a recovery hypothesis, not a demonstrated repair. Linux's use of KIQ
UNMAP_QUEUES for other queues does not by itself establish a KIQ self-teardown protocol.

### 2026-09-08: diagnostic corrections and bounded shutdown

The clean 1.0.159 run reaches `TtlCreateHybridEngine` failure status 4 after successful
KIQ setup. `AMDHardware::startHWEngines -> 0` and `powerUpHW -> 0` mean failure.
`_TtlCreateHybridEngine` at 0x9876b returns 4 both when `_ttlIsHwAvailable` is false
and when the selected GC/SDMA hybrid-queue creation routine fails. Status 4 alone
cannot distinguish those paths. `_ttlIsHwAvailable` at 0xafa40 rejects any set bit
in `dev+0xb0 & 7`; bit 2 is a blocking flag, not a required READY flag.

Experimental builds 1.0.160/161 placed HWLibs offsets for hybrid-engine diagnostics
in the X6000 route table, adding the wrong binary base. A successful route operation
did not prove the intended function was hooked. Missing diagnostics from those runs
cannot establish callback caching or log loss. Those hooks were removed in the retained
1.0.159 source. Raw runs remain archived but are excluded from causal conclusions.
The old offset/prologue preflight did not check route-table binary ownership. The new
`route-domains.py` checks the current installDiagnostics and processKext scopes against
the offsets' binary annotations; preflight and release builds now call it. Regression
tests reproduce the wrong-HWLibs-offset-in-X6000-table error. This is a targeted static
check, not a general C++ data-flow analysis.

The supervisor now requests ACPI `system_powerdown` through the exact container's QEMU
monitor, checks the peer process inside that container's PID namespace, and observes
exit for a bounded grace interval. The original hard deadline remains armed, and a
nonresponsive guest is force-stopped at the end of the interval. A saved container
identity with a different StartedAt is refused. Automatic bounded runs attempt shutdown
30 seconds before the original container deadline. Container exit after an ACPI request
is recorded as such; it is not proof of native queue unmapping or host safety.

### 2026-09-08: guarded hybrid diagnostic staged as 1.0.162

`rgpuhybrid=1` (off by default) routes `_TtlCreateHybridEngine` only from the HWLibs
load callback, after checking its first 19 bytes and the first 14 bytes of the read-only
`_ttlIsHwAvailable` helper. The wrapper samples availability before the native call,
logs request engine type when available, and preserves the native return. Logging is
capped at eight calls. It makes no MMIO writes. Availability is a snapshot; concurrent
state changes remain possible before the original routine checks it again.

Local compilation, route-domain regression tests and 24G830 KDK preflight pass.
**No passthrough run has tested this candidate.** The VM harness build directory holds
1.0.162; its ESP still holds verified 1.0.159. The last GPU session's KIQ did not dequeue,
and the GPU-less ACPI experiment required force-stop. A clean host boot and a fresh
amdgpu-first handoff are needed for the planned next validation; do not cycle drivers
or force-clear the existing HQD to obtain it. The optional diagnostic must be explicitly
enabled and the candidate injected before that bounded test.

### 2026-09-08: the false second SDMA object is the native startup failure

Candidates 1.0.163 and 1.0.164 replaced the ambiguous status-4 observation with a
sequenced native call record. All KIQ stamps complete. SDMA type 10/index 0 and type
11/index 0 resolve and return status 0 against discovered counts `1,0,0,0`. The next
request, type 10/index 1, has no instance; selection returns null before the instance
callback and `AMDHardware::startHWEngines` returns false.

X6000 produces the invalid request itself. Navi23 `allocateHWEngines` at `0x9977c`
always constructs two SDMA objects. Generic initialization passes their array indices;
`AMDGFX10SDMAEngine::init` at `0x6b7b2` subtracts one and stores global indices 0 and 1.
The generic start loop at `0x6ffd2` has a minimum bound of two, so the Navi23 capability
field cannot represent Raphael's single discovered SDMA instance. Aliasing index 1 to
index 0 would collide with the two valid queue handles already owned by the first object.

Candidate 1.0.165 therefore adds an off-by-default `rgpusdma=1` compatibility boundary.
After all five X6000 routes resolve and the original GC 10.3.6 discovery is observed, it
releases the false second object before generic initialization. It starts only the native
first object, preserves its Boolean result and reproduces the native trace bit. Native
loops retain cleanup ownership and skip the null slot. The full ABI, evidence, regression
domain and next acceptance result are in `findings/hybrid-cause.md`.

The spoofed `0x73ff` PCI ID is also a real Navi23 ID, so it is not a sufficient repair
scope. Candidate 1.0.165 additionally requires the byte-exact `rgpu,raphael-target`
OSData marker on the same IOPCIDevice as the grafted `ATY,bin_image`. `ocprop.py` adds or
removes those properties together at the selected OpenCore path, and the experiment
coordinator checks the marker both while preparing and immediately before launch. The
discovery wrapper scans every table it sees for the original GC 10.3.6 version before
remapping, avoiding dependence on which GPU's table is queried first.

### 2026-09-08: owner repair exposes X6000's residual SDMA1 channel assumption

Hybrid-003 hardware-tested candidate 1.0.165. `TTL::initialize()` completed, the false
second SDMA object was released, and `AMDHardware::initializeHWEngines` returned 1. The
guest then trapped in `createAccelChannels(bool)+0x278` before engine start. At X6000
relative `0x26e7`, a virtual `getHWChannel` call returned null; `0x26f0` immediately
dereferenced that result. The panic registers agree: `RAX=0`, `R14=0`, `CR2=0`.

The exact chain is `createAccelChannels` channel type 2 →
`AMDRTHardware::getHWChannel` → engine enum 2 →
`AMDHardware::getHWChannel(engine, ring)` at `0x7097c`. The last function indexes
`hardware + 0x3b0 + 8*engine`, so enum 2 reads the intentionally empty `+0x3c0` slot.
This is a higher-layer Navi23 topology assumption revealed by the correct physical-owner
repair, not a new HWLibs discovery failure.

Candidate 1.0.166 adds a sixth exact X6000 route. It maps engine enum 2 to enum 1 only
after the byte-marked Raphael hardware object owns the verified one-instance repair.
The native method still selects and returns the real SDMA0 ring; every other engine,
hardware object and pre-repair call is unchanged. This matches NootedRed's one-SDMA APU
channel mapping and does not fabricate a second discovery instance or force success.

The original coordinator classified the early panic as missing evidence because critical
records were not replayed before the crash. The classifier now parses exact live `CRLOG`
records, retains fail-closed build/route checks, recognizes the first symbolicated panic
frame and terminates exposure after a decisive result. The corrected immutable evidence
is in `findings/experiments/hybrid-003-165/`.

Metal enumeration remains the strongest userspace state; no compute or render command has
completed correctly. Hybrid-004 must observe the `2 -> 1` channel mapping, preserve KIQ and
native engine results, and pass the checked compute/render probe before core acceleration
can be claimed.

### 2026-09-08: rootless PSP cleanup replaces the reboot development loop

The iGPU advertises only the PCI `bus` reset method. Bus 7b also contains the host CCP/PSP,
two xHCI controllers and audio functions, so a bridge or bus reset is not a safe per-GPU reset.
The original interpretation of vfio-pci's `resetting` / `reset done` messages was wrong. Legacy
VFIO calls the PCI reset path on device acquisition and may call it again on close. The active
method was `bus`, so these transactions invoked an unsafe shared-bus reset.

After a one-time privileged handoff disables every PCI reset method, root is unnecessary for the
cleanup itself. `/dev/vfio/31` is owned by the experiment user,
so `tools/vfio-recover.py` opens the legacy VFIO container/group, obtains the device fd and maps
only BAR5. It refuses an active QEMU, a wrong device/group/driver, enabled PCI bus mastering, a
host fault or a nonlatest prior run. It unconditionally sends `DESTROY_RINGS` and
`DESTROY_GPCOM_RING`, closes VFIO, rechecks bus mastering and stores an immutable receipt.
The ordered boot ledger consumes that receipt once before a later launch and initially permits
at most three launches in one host boot.

The first transaction ran after candidate 1.0.165 panicked and was force-stopped. Without sudo,
rebind or reboot it recorded the following, but the implicit reset makes attribution impossible:

```
PCI_COMMAND             0x0003 -> 0x0003  (bus master clear)
DESTROY_RINGS           0x80010000 -> 0x80030000  after 7 polls
DESTROY_GPCOM_RING      0x80030000 -> 0x800c0000  after 1 poll
host kernel faults      none
```

This proves only that the PSP commands were acknowledged after VFIO's implicit reset. Hybrid-004
then consumed that now-obsolete schema-1 receipt on the same host boot. Apple reinitialized the
PSP, candidate 166 completed the SDMA channel remap, all hybrid creations returned status zero,
native engine start and power-up returned 1, and KIQ stamps advanced through at least 21. No host
fault occurred. A second post-stop recovery returned the same exact PSP acknowledgements and kept
bus mastering disabled, but it also used the implicit reset path. Schema-2 admission rejects both
historical receipts.

The live coordinator did not run the Metal probe because it mixed later unsequenced direct log
lines into an already complete structured snapshot and called the resulting line-number gaps
capture loss. The structured snapshot itself covers sequences 0 through 62 with zero dropped or
truncated records and reclassifies as `PROBE_NOT_RUN`. The parser now treats that complete prefix
as authoritative while preserving raw records only as the pre-snapshot panic fallback. The third
and final launch under the initial same-boot ceiling tests actual Metal execution.

### 2026-09-08: PSP cleanup is insufficient after full engine startup

The third launch consumed the second PSP-only receipt. Candidate 166 again initialized the
repaired topology, completed hybrid creation for engines 12 and 13, and advanced the first three
KIQ stamps. The next `waitForHwStamp(1)` returned zero before the Metal probe ran. Its timeout
snapshot found sixteen active ME2 HQD selections across all four pipes. Half retained the prior
KIQ ring/MQD with RPTR equal to WPTR `0x60`; the others referenced the second queue image. The
previous fully started guest had been force-stopped, and its driver lifecycle hooks never ran.
Destroying PSP rings therefore cannot establish a reusable GC state.

The subsequent panic is not the earliest failure. `wrapWaitStamp` walked every HQD and emitted a
large serial dump from a native path that can hold a spin lock; the backtrace reaches
`lck_spinlock_timeout_set_orig_ctid` before recursive trap handling. That instrumentation is
removed. The classifier now retains a terminal live KIQ failure before a panic without splicing
unsequenced serial line numbers into the complete structured prefix.

The recovery transaction now follows the bounded GFX10 shutdown order from Linux: disable KIQ
pointer polling, request HQD dequeue while MEC still runs, stop SDMA context switching/ring/IB,
halt physical SDMA0, halt graphics CP and both MECs, then disable doorbells and clear only stuck
HQDs after the halt readback. It proves all selectors inactive before destroying the PSP rings.
The exact-container shutdown path also falls back to its already peer-verified ACPI powerdown
instead of immediately killing QEMU when the root agent transport is absent.

The first live implementation failed closed at the SDMA halt readback. It had incorrectly treated
the generated register header's `base address: 0x4980` comment as the live base. Both Apple's
`sdma_5_2_stop_engine` and Linux's discovery-based access use base index zero plus register
`0x2a`; the live segment-zero base is `0x1260`, so BAR5 byte offset `0x4a28` is correct. With that
correction, validation against the stopped third-run state cleared `AUTO_CTXSW_ENABLE`,
`RB_ENABLE`, and `IB_ENABLE`, set `F32_CNTL.HALT`, read back the CP/MEC halt masks, proved zero
active HQDs, and received `0x80030000`/`0x800c0000` for PSP teardown. PCI command stayed `0x0003`,
the device stayed on vfio-pci, no sudo or driver rebind was used, and the kernel recorded no
fault.

That conclusion needed one more correction. The kernel interval contained `vfio-pci ...
resetting` and `reset done` because `vfio_pci_core_enable()` calls `pci_try_reset_function()`
when a legacy VFIO device fd is acquired; the close path may reset again. The only enabled method
was `bus`. This means the shared APU bus was reset before BAR5 inspection, and `active_before = 0`
cannot prove the transaction cleared the prior HQDs. The live record still validates the corrected
SDMA offsets, writes/readbacks and PSP acknowledgements after that reset.

Candidate 168 fixes the lifecycle boundary instead of treating those messages as harmless. During
the one privileged amdgpu-to-vfio handoff, `gpu-bind.sh` writes an empty value to the root-owned
`reset_method` attribute and verifies it before granting user access to the VFIO group. Both launch
admission and rootless recovery refuse any nonempty or unreadable reset method. Recovery receipts
use schema 2, record the empty state before and after, and reject any target-device reset message.
The three-launch ceiling still prevented using the confounded validation as permission for a
fourth launch; a fresh boot must prove reset-free cleanup and warm reinitialization.

### 2026-09-08: a torn serial read, not the SDMA patch, contaminated the CP

Candidate 169 (`d1058f1`, build `c9d63d2aabf742cf92616cb91ba8aa27`) repairs only the
measured SDMA paging-IB address projection. X6000 builds opcode `SDMA_OP_INDIRECT` with an
address such as `0x400100000`, the low 36 bits of a buffer in the `0xf400000000` software
framebuffer aperture. The wrapper recognizes only that exact projection and restores the
validated MC aperture, yielding `0x840100000`, before the native 0x200-byte template copy.

The first candidate-169 run (`b3d6720b7c58406ea3089c6ef16e60f6`) did not test that repair.
It initialized the one-instance SDMA topology and advanced KIQ stamps 1, 2 and 3. A direct
`waitForHwStamp(1) -> 0` was followed by `waitForHwStamp(4) -> 1` and a successful
`submitKIQFrame`; the later success proves the earlier generic wait result was not a terminal
KIQ failure. While the next structured snapshot was being printed, the coordinator read the
file between writes. Python's `splitlines()` treated the unterminated tail as a complete replay;
its partial payload differed from the earlier sequence and was classified as a conflicting
replay. The coordinator then force-stopped QEMU while the driver was still inside its KIQ path,
before any `AMDHardware::stopHWEngines` or `powerOffHWEngines` event. No `SD: IB template`
record had occurred.

The following warm launch (`557c33d2a4164c0a919b5cde3d1cbd84`) therefore began with
`CP_STAT=0x80008200`, `CP_CPC_STATUS=0xa0000082` and `CP_CPF_BUSY_STAT=0x48460002`. Its first
KIQ ring stopped at RPTR 0 / WPTR 0x20 and `powerUpHWEngines` returned zero. The rootless
post-stop transaction found the same active HQD through eight aliased selectors, could not
dequeue it, halted the engines and force-cleared ACTIVE. It nevertheless wrote a schema-2
`recovered` receipt because the old validator checked only halt bits and ACTIVE.

Read-only legacy-VFIO access after that transaction, with `reset_method` empty and no QEMU
running, measured the actual retained state:

```
CP_STAT              0x80008200
CP_CPC_BUSY_STAT     0x08080000
CP_ME_CNTL           0x15000000
CP_MEC_CNTL          0x50000000
SDMA0_F32_CNTL       0x00000001
```

The halt bits are real, but they do not clear the command processor's outstanding internal
work. A recovery receipt now authorizes reuse only with zero dequeue timeouts, zero forced
ACTIVE clears, `CP_STAT == 0` and `CP_CPC_BUSY_STAT == 0`. An incomplete transaction is retained
as evidence with `status=incomplete` and `authorizes_launch=false`. Existing receipts lacking
these observations fail closed.

Two changes prevent the harness from creating the same state again. The classifier ignores the
final serial fragment until its newline is present and prefers the explicit `submitKIQFrame`
result over generic `waitForHwStamp` calls. The coordinator requests the identified guest's shutdown, then peer-verified ACPI
powerdown, before exact-CID force-stop on runtime capture or observation errors. Identity mismatch
and host-kernel faults retain the immediate stop path. In the driver, a partial
`AMDHardware::powerUpHWEngines` failure now invokes Apple's own `powerOffHWEngines` while QEMU's
DMA mappings still exist. The exact 24G830 implementation dispatches engine power-off through
vtable slot 0x140; PM4 power-off tail-calls its stop method at slot 0x150. This is the earliest
native cleanup point that still owns the KIQ ring, MQD and writeback mappings.

No host reset, driver rebind or privileged command was used for this analysis. The current boot's
three-launch ceiling is exhausted and its CP is measurably non-idle, so candidate 169's SDMA
address repair still requires one clean-boot hardware experiment.

### 2026-09-08: candidate 170 isolates the SDMA paging packet address

Candidate 170 (`40a2ffb`, build `c8328a6c1f75442399b62276ed7d65aa`) ran once after a fresh
amdgpu-to-vfio handoff with PCI reset methods disabled. Native hybrid creation, engine start and
accelerator power-up returned success. KIQ submissions continued through at least stamp 34 and
`VM_FAULT_STATUS` remained zero. The first decisive failure was instead the shared SDMA0 paging
channel timing out with hardware queue 1 stopped at:

```
IB: ENABLED, GPUAddress = 0x0000000400100020,
    ConsumedSize = 0, RemainSize = 0x70
```

The candidate-169/170 repair never touched that value. Every invocation observed the fixed
channel template address `0xffbfde011c`, which is outside either framebuffer aperture and was
correctly left unchanged. The assumption that `channel+0x138` contained the paging IB was wrong.

Exact disassembly of Sequoia 24G830 `AMDRadeonX6000` establishes the complete producer/consumer
chain. `AMDAccelChannel::submitBuffer` at `0xb83e` zeros a 0xe8-byte
`AMD_SUBMIT_COMMAND_BUFFER_INFO`, copies the primary command descriptor GPU address into offset
`+0x58` at `0xbacc`/`0xbad0`, and appends further entries at stride 0x28. The count at `+0x14` is
the descriptor count plus one. `AMDGFX10SDMAChannel::commitIndirectCommandBuffer` at `0x66e06`
copies its fixed 0x200-byte template, then reads the count at `+0x14`; after adding 0x4c to the
submit pointer it reads `[pointer+0xc]`, exactly the original `+0x58`, and advances by 0x28 per
entry. It stores each qword into the emitted SDMA INDIRECT frame before submitting it natively.

The first candidate-171 implementation would have repaired `submitInfo + 0x58 + 0x28*i` before
calling the original encoder. It was withheld before hardware use after checking the reference
packet semantics. Linux's `sdma_v5_2_ring_emit_ib` places the IB's VMID in the SDMA INDIRECT
header, then emits the full low and high halves of `ib->gpu_addr`. Candidate 170 identifies the
stalled submission as WindowServer VMID 2. The measured `0x400100020` is therefore a GPU virtual
address under VMID 2; changing it to MC physical `0x840100020` while retaining VMID 2 would mix
address spaces. [Linux v6.12 SDMA 5.2 source](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/sdma_v5_2.c#L251-L284).

The corrected candidate 171 is read-only at both boundaries. It records flags, VMID, count and
the first two addresses from the exact submit-info layout. It also records nonzero-VMID requests
to `programAndInvalidateVM`. Driver callbacks only append bounded raw copies; a dedicated kernel
thread later reads the selected GC 10.3 context control, root, start and end registers and formats
the serial records. This is an asynchronous hardware snapshot, not proof that the register state
was identical at callback time. The classifier accepts it only when the request and snapshot have
the same nonzero root and both ranges contain a submitted IB address. VMID 2 has its own bounded record budget; the
old first-16-call diagnostic captured only context-0 initialization and never observed the
WindowServer mapping. Context control has stride one, while root/start/end low/high pairs have
stride two, as confirmed against `gc_10_3_0_offset.h`.

Candidate 170 also exposed a diagnostic correctness defect: a success record for every KIQ
submission filled all 128 critical slots, dropping the later failure evidence. Candidate 171
retains every native failure but caps routine successful KIQ submit and stamp records at eight
each. SDMA and VM observations are similarly bounded. Hosted fixtures cover the immutable submit
layout, VM request parsing, per-context register strides, invalid counts, success-budget
exhaustion and classifier handling of the raw SDMA paging timeout.

The candidate-170 shutdown was forced after the classifier detected overflow. Reset-free recovery
found nine active HQD selections; eight dequeue attempts timed out and required post-halt ACTIVE
clears. `CP_STAT` and `CP_CPC_BUSY_STAT` remained nonzero, so the receipt is explicitly incomplete
and cannot authorize a second launch on this boot. No host kernel fault was recorded.

### 2026-09-08: candidate 171 moves the first failure back to SDMA paging

Candidate 171 (`d41b565`, build `dd7aa16feabf45d5afec671d2e778ba8`) completed the native
one-instance startup path: KIQ stamps 1 through 6 completed, the surviving SDMA0 engine started,
`AMDHardware::startHWEngines` returned 1, and `AMDGraphicsAccelerator::powerUpHW` returned 1.
The first terminal hardware event was instead serial line 3189:

```
[0:6:0]: HW Channel 12 SDMA0_PAGE is occupied by channel 34 stamp 1
```

The KIQ stamp 28 timeout did not occur until line 10713, after channel restart attempts. The old
classifier compared the later structured KIQ record with an unsequenced raw SDMA line and called
KIQ the earliest failure. It now records raw terminal KIQ positions separately and lets the first
raw terminal event select the subsystem. Reclassification is intentionally inconclusive at
`sdma_vm_context_missing`: the requested observation did not occur.

That missing record identifies the wrong observation boundary. `AMDHWVMM::assignVMID` builds an
`AMD_VM_INVALIDATE_INFO`, but the paging channel calls
`AMDGFX10SDMAChannel::writeVMProgramPacket`. That method invokes the VMM vtable slot for
`AMDGFX10VMM::prepareVMInvalidateRequest`, copies a 0xc8-byte channel template, and patches the
prepared register/value fields into the SDMA command stream. The CPU-side
`programAndInvalidateVM` method is not part of this path and therefore never reached the old hook.
Its absence says nothing about whether the SDMA packet programmed VMID 2 correctly.

Candidate 172 routes `prepareVMInvalidateRequest` at exact 24G830 offset `0x6249c`. Its first 16
bytes contain only the normal push/move prologue, with no RIP-relative operand or branch. The
wrapper calls the native encoder first, then copies the 0x28-byte source request and all 21 output
dwords into an eight-slot append-only buffer. It does no MMIO, formatting, allocation, lock or
wait in the callback. The existing dedicated thread emits the copy later. This is a read-only
experiment; Apple remains the sole owner of packet construction and submission.

The Linux comparison narrows what the capture can show. `gmc_v10_0_set_gfxhub_funcs` selects
`gfxhub_v2_1_funcs` for both GC 10.3.4 (Navi23 / Dimgrey Cavefish) and GC 10.3.6 (Raphael).
Upstream has no separate 10.3.4 or 10.3.6 GC register header; the whole family uses
`gc_10_3_0_offset.h`. Both Dimgrey Cavefish and Yellow Carp/Raphael-family discovery tables place
GC segment 0 at `0x1260` and segment 1 at `0xa000`. A broad GFXHUB-layout rewrite is therefore not
supported by the reference. The next run must compare Apple's actual register indices and values
with the shared Linux layout and change only a measured mismatch.

Candidate 171 also supplied the first fully authorizing reset-free cleanup after complete native
startup. Rootless recovery found two active HQDs and dequeued both on their first poll, force-cleared
none, read `CP_STAT=0` and `CP_CPC_BUSY_STAT=0`, halted SDMA, and confirmed both PSP teardown
commands. PCI reset methods stayed empty and the host journal cursor did not advance. This permits
one targeted same-boot candidate-172 launch without an amdgpu rebind or host reboot; the next
launch still depends on another equally strict recovery receipt.

### 2026-09-09: candidate 173 isolates the VMID-2 page-directory address domain

24G830 `getPDEValue` retains address bits 47:6 and adds VALID, but performs no framebuffer
MC-to-physical conversion. Linux `gmc_v10_0_get_vm_pde` performs that conversion for every
non-SYSTEM, non-leaf PDE. The candidate-172 boundary therefore exposes a high-confidence root
defect: a logical `0xf4...` page-directory root must be presented to GFXHUB as the matching
physical `0x84...` address.

Candidate 173 gates the mutation on `rgpuvmroot=1`, the byte-exact Raphael marker, hub 0, VMID 2,
reprogram enabled, known VALID/CACHE flags, and an address inside the published framebuffer
aperture. The wrapper copies all 0x28 caller bytes to its stack, repairs only the copy, calls Apple,
then copies all 21 output dwords into a bounded observation. No MMIO, logging, allocation, sleep or
lock is added to this callback. `setVMRegisters` also now uses the pointer-width return ABI shown by
its 24G830 implementation.

The root-only repair is not yet claimed complete. Apple's child PDE producer may emit the same
logical domain. A worker correlates the prepared request with its VMID-2 SDMA submit and walks
`0x400100000`, `0x4000c0000` and `0x400200000` via BAR0. It decodes PDE/PTE flags and translates
only non-SYSTEM non-leaf table pointers for CPU inspection. It never rewrites a child PDE, leaf
address or submitted GPU virtual address. A `raw=0xf4... child-mc2pa=1` result selects child-PDE
production as the next fix; physical children instead direct investigation to the recorded actual
invalidate engine and SDMA UTCL/XNACK/page state. No response-mode or firmware change is included.

The earlier walker misdecoded `PAGE_TABLE_BLOCK_SIZE` as the width of every level. Linux programs
that field as the leaf width minus 9; `ctrl=0x3b` therefore means a 16-bit leaf with 9-bit
intermediate directories, and the three `0x400...` targets use root index 64 ([GFXHUB 2.1 source](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/gfxhub_v2_1.c)).

The first corrected-walker launch stopped before QEMU because Python `mmap.flush()` translated to
an unsupported `msync(2)` on the VFIO BAR0 device mapping and returned `EINVAL` after the exact
PENDING reservation bytes were assigned. The transport now relies on its existing explicit HDP
flush, posted BAR read and reservation readback; a one-shot continuation is limited to the pinned
prelaunch evidence and consumes a durable boot/run marker before reopening VFIO.

Invalidate semaphore registers are not safe diagnostic samples. Linux's CPU flush path documents
that a semaphore read returning one acquires ownership and releases it by writing zero
([`gmc_v10_0.c`](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L276-L306));
its ring path uses the same acquire-before-invalidate and release-after-invalidate protocol
([ring implementation](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L373-L405)).
Diagnostics therefore leave decoded semaphore values explicitly unread while retaining request
and acknowledge reads. This removes an acquisition risk; it does not establish that a diagnostic
read caused any earlier GPU fault.

### 2026-09-09: candidate 174 refuses KIQ startup without a BAR0 mapping

The controlled candidate-174 continuation loaded build
`b60df7448ea24106ae4300f6760cb171` and reached PM4 engine initialization. The serial mux split
one diagnostic across lines 2918 and 2920; together it reads `XQ2: preflight failed: BAR0 mapping
unavailable`. The following intact line reads `XQ2: startKIQ refused: preflight or genuine
dequeue failed`. The PM4 engine then returned zero, the live-mapping partial cleanup returned one,
and both `powerUpHWEngines` and accelerator `powerUpHW` returned zero.

This is a startup refusal, not an SDMA execution result. No KIQ submit, SDMA VM programming,
VMID-2 callback or page-table walk ran, so candidate 173's root repair and corrected walker remain
untested on hardware. The classifier's `sdma_vm_program_missing` label describes the later missing
observation but is not the earliest concrete boundary. The guest honored the shutdown request and
halted cleanly. Rootless recovery failed closed because the guest had never activated the exact
host-KIQ lifetime reservation; that receipt does not authorize another launch. The immutable
record is archived in [metal-007-174-prelaunch-continuation](experiments/metal-007-174-prelaunch-continuation/notes.md).

The pending BAR0-startup repair follows ownership visible in the 24G830 X6000 binary:
`AMDHWMemory::init` stores its interface owner at `self+0x10`, and `AMDHardware::init` stores its
`IOPCIDevice` at the same offset. The mapping helper can therefore use the memory object's owner
before the later global hardware pointer is published, then call the established PCI-map and
map-virtual-address vtable entries. Failed or unavailable attempts remain retryable; only a valid
address is cached. Offline validation compiled the complete kext and passed the early-owner,
retry, activation-before-range-population and KDK route/offset checks. This repair has not run on
hardware and does not promote candidate 174 to a successful-startup baseline.

### 2026-09-09: startup-only cleanup succeeds; candidate 175 remains untested

The reviewed one-shot cleanup for candidate 174's exact no-queue stopped state completed on the
actual device without a reset, driver rebind or launch. Both complete HQD scans found no active
queue or enabled doorbell, both graphics pipes were inactive with their doorbells disabled, and
the immediate pre-write SDMA state was accessible, idle and disabled. The transaction halted the
already-idle CP and SDMA engines, received exact PSP responses `0x80030000` and `0x800c0000`, then
consumed the PENDING reservation last. PCI command remained 3, reset methods remained empty, and
the captured host journal interval contained no new message or fault.

The authorizing schema-4 receipt SHA-256 is
`a511e06af4fcdc07961bfc3f9dd0a83e340ee866086ed84b99f558978f28b175`. It binds the unchanged
launch-ledger preimage plus unique recovery and attempt IDs, so it permits one later reservation
and cannot be replayed. This result proves only the bounded startup/no-queue cleanup for that
state. It does not prove normal recovery after a fully started guest, warm reinitialization,
candidate 175 startup, or Metal execution.

Candidate 175 packages the already offline-validated BAR0 early-owner/retry repair. Relative to
candidate 174, this is the only guest behavior change: mapping can use the owner published at
`AMDHWMemory+0x10` before the later global hardware pointer exists, failed attempts remain
retryable, and only a valid mapping is cached. The `rgpuvmroot=1` diagnostic and all functional
boot arguments remain unchanged so a future controlled run can first require KIQ startup, then
resume the still-unresolved VMID-2 root, SDMA submission and page-table observations. Candidate
175 has not yet run on hardware, and full Metal acceleration remains unproven.
