# Driving an AMD Raphael iGPU with Apple's Navi 2x kexts

Target: AMD Granite Ridge / Raphael integrated GPU, PCI `1002:13c0` rev `0xcb`
(GC 10.3.6, MP0+MP1 13.0.5, SDMA 5.2.6, DCN 3.1.x, VCN 3.x, 2 CUs, 512 MB carve-out,
128-bit DDR5). Host CachyOS; guest macOS Sequoia 15.7.9 build 24G830 under QEMU/KVM,
device handed over with `vfio-pci` and spoofed as `1002:73ff` (Radeon RX 6600, Navi 23).

## Status

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
