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

The blocker is now one layer deeper, inside `AMDRadeonX6000HWLibs`. See "Current blocker".

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
