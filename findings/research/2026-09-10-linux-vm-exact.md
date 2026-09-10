# Exact Linux GC 10.3.6 GPUVM comparison

Date: 2026-09-10. Scope: offline source and repository analysis only. No VM,
device access, `sudo`, reset, media, build, test, or implementation change was
performed. Existing project tests were treated as claims to audit, not as
authority.

## Source pin and provenance

The authoritative comparison is Linux stable tag `v7.2.3`: annotated tag
object `296e02a60bcb8223c12ebf58feeb69961f4608c1`, peeled commit
`58e7295cfecaddec94629160386412e0f2b1e8fe`. Both were resolved directly with
`git ls-remote https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git`.
Every file cited below in the local cache byte-matched a fresh download from
the tagged `gregkh/linux` GitHub mirror. Relevant SHA-256 values are:

| File | SHA-256 |
|---|---|
| `gmc_v10_0.c` | `a873c4474b85ebc56437e78de07998629004f932e2eedc9d3f54289e23bf9cb0` |
| `gfxhub_v2_1.c` | `94b1a294f030020ba2e71849a0762430e6d66839e3ddeee1129bb9862369fe86` |
| `mmhub_v2_3.c` | `d119efc78edcefdc830fd41f0538c5c756f3ec5876bfa8f7089498d6e4af829e` |
| `amdgpu_gmc.c` | `3455c27f0d6f32ab1ee1afc6dd109d2805618855ebb15bdc6b1672e29707c79e` |
| `amdgpu_vm.c` | `7dbbf815f5d8ecc8f7c96f2b18c9d27b6633853da4d6268f087d26df0a70e526` |
| `amdgpu_vm.h` | `77e800c81b2efb28d279aba03385b0c06289999e8f71afcedf1ee9ace160b2dd` |
| `amdgpu_ttm.c` | `5bdb0b4c29afcef22cac3967ac535a15c110c0197e486e089c9c65edc6081374` |

Primary URLs use the immutable tag: [GMC10](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c), [GFXHUB 2.1](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gfxhub_v2_1.c), [MMHUB 2.3](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/mmhub_v2_3.c), [generic GMC](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_gmc.c), [VM](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_vm.c), [VM definitions](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_vm.h), and [TTM flags](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_ttm.c).

## Actual Raphael selection

GC IP `10.3.6` takes `gmc_v10_0`, and `gmc_v10_0_early_init` installs all
three relevant function tables. The GC switch selects `gfxhub_v2_1_funcs` for
10.3.6; MMHUB IP 2.3.0, 2.4.0, or 2.4.1 selects `mmhub_v2_3_funcs`; the GMC
table supplies `gmc_v10_0_get_vm_pde`, `gmc_v10_0_get_vm_pte`, and both flush
paths ([gmc_v10_0.c lines 546-619](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L546-L619)). This confirms that using GFXHUB 2.1 and MMHUB 2.3 for Raphael is correct.

For 10.3.6 Linux selects a 256 TiB/48-bit VM, `num_level=3`, and a 9-bit PT
block ([gmc_v10_0.c lines 792-814](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L792-L814)). Generic sizing makes that four hardware lookup levels (`num_level + 1`), root level PDB2, block size 9 ([amdgpu_vm.c lines 2395-2439](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_vm.c#L2395-L2439)). GFXHUB and MMHUB program VMIDs 1-15 with exactly that depth and `PAGE_TABLE_BLOCK_SIZE = block_size - 9`, hence encoded block size zero ([gfxhub_v2_1.c lines 295-325](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gfxhub_v2_1.c#L295-L325), [mmhub_v2_3.c lines 272-306](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/mmhub_v2_3.c#L272-L306)). The local extraction of depth from bits 2:1 and block size from bits 6:3 is consistent with the register fields already used by the project; a four-step walk for depth 3 is consistent with Linux.

## Address and flag rules

Linux derives directory flags from the backing resource. TT, doorbell,
preemption, and MMIO-remap directories are `SYSTEM`; cached TT is also
`SNOOPED`. VRAM directories are not `SYSTEM` and can be `SNOOPED` when cached
([amdgpu_ttm.c lines 1423-1451](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_ttm.c#L1423-L1451)). A root BO in TT starts from its DMA address; one in VRAM starts from its GPU/MC offset. Both go through the ASIC PDE callback, including the root call with level `-1`; the returned flags are ORed into the PTB value ([amdgpu_gmc.c lines 112-149](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_gmc.c#L112-L149)).

The exact GC10 rule is:

```
if (!(flags & PDE_PTE) && !(flags & SYSTEM))
    addr = mc_addr - vram_start + vram_base_offset;
```

`amdgpu_gmc_vram_mc2pa` is precisely that subtraction/addition
([amdgpu_gmc.c lines 1193-1202](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_gmc.c#L1193-L1202)); the guard and subsequent level transforms are [gmc_v10_0.c lines 454-474](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L454-L474). Thus:

- Ordinary non-SYSTEM directory pointers, including a VRAM root, are MC-to-physical converted.
- SYSTEM directory pointers retain their DMA/physical address.
- A PDE used as a large PTE (`PDE_PTE`, bit 54) retains its supplied data-page address; it is not a child-table pointer.
- With `translate_further`, PDB1 gets BFS 9 unless it is a large PDE-as-PTE. At PDB0, a large PDE-as-PTE has bit 54 cleared; an ordinary directory entry gets `TF` (bit 56), meaning the PTE-form entry is treated as another PDE. Bit definitions are [amdgpu_vm.h lines 57-87](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/amdgpu_vm.h#L57-L87).
- Ordinary PTE address conversion occurs before this ASIC flag-only callback, according to the backing placement. `gmc_v10_0_get_vm_pte` changes executable, MTYPE, no-allocate and PRT attributes; PRT becomes invalid SYSTEM+SNOOPED+LOG ([gmc_v10_0.c lines 477-522](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L477-L522)). It is inaccurate to describe this callback itself as performing VRAM `mc2pa` conversion.

## Root programming and invalidation

Both hub `setup_vm_pt_regs` functions write the complete already-encoded 64-bit
PTB value directly to the context low/high pair ([gfxhub_v2_1.c lines 123-135](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gfxhub_v2_1.c#L123-L135), [mmhub_v2_3.c lines 111-122](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/mmhub_v2_3.c#L111-L122)). There is no second conversion at register write. VMID0 GART initialization obtains the converted/flagged value through `amdgpu_gmc_pd_addr` first.

The ring flush path emits, in order, PTB low, PTB high, then invalidate request
and ACK wait for that VMID; MMHUB additionally acquires/releases its invalidate
semaphore ([gmc_v10_0.c lines 359-404](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L359-L404)). The CPU path flushes HDP first, uses invalidate engine 17, writes the request generated for the selected VMID and flush type, waits for the VMID ACK bit, and uses a semaphore only for MMHUB ([lines 235-319](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L235-L319)). Linux does not establish that engine 0 or VMID0 is interchangeable with the faulting VMID1. Startup explicitly flushes VMID0 on both hubs only after their GART setup ([lines 930-953](https://github.com/gregkh/linux/blob/v7.2.3/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c#L930-L953)).

“Emits in order” is the supported claim. These separate packet writes do not prove
that the GPU observes the 64-bit root update atomically between its low and high
halves.

## Pinned X6000 geometry evidence

The local 24G830 disassembly `/home/bogdan/macos-vm/re/x6000.asm` supplies
Apple-specific facts that differ materially from Linux:

- `AMDGFX10VMM::init` at `0x6202e` calls the superclass with argument 2, sets
  context start `self+0xaa0 = 0x400000000`, end `self+0xaa8 = 0x2400000000`, and
  stores the qword `0x100000003` at `self+0xb30`. Therefore `self+0xb30=3` and
  `self+0xb34=1`; the accessor at `0x597b6` returns the latter as the native VMPT
  depth/count value. It initializes three 0x20-byte level descriptors beginning at
  `self+0xab0`.
- The descriptor loop at `0x620fc-0x6216f` computes the dword at descriptor `+8`
  from the logarithm of each descriptor's first qword. For descriptor index 1,
  whose first qword is `0x10000`, the computed value is 16.
- `getPDEValue` at `0x629c6` increments its input level. When that value equals
  `self+0xb34`, it loads descriptor `+8`, adds 20, and shifts the result left 59;
  for input level 0 this encodes `(16+20) mod 32 = 4` in BFS bits 63:59. This
  exactly explains captured `0x200000084b700001`: BFS4, converted-or-unconverted
  address bits, and VALID. When incremented level is greater than the native value,
  it instead adds bit 56 (TF). It always masks directory addresses to bits 47:6
  and adds VALID.
- `getPTEValue` at `0x62a14` masks addresses to bits 47:12, places the fragment
  argument in bits 11:7, derives SYSTEM bit 1 from input flag bit 3, and sets bit
  54 when `self+0xb34 > input level`. Other input flags control snoop/access,
  executable/MTYPE, and bit 58. These transformations are Apple evidence; their
  names should not be inferred solely from Linux when the surrounding geometry
  differs.
- The observed live control described as depth 1/block 7 is consistent with the
  native `self+0xb34=1`, but the disassembly reviewed here does not itself prove
  that the control-register block field is derived from a descriptor in the same
  way assumed by the diagnostic walker.

### Geometry intentionally left undecided

The following cannot be safely chosen from current evidence:

1. Whether Apple's depth value 1 means two total memory lookups, or whether TF
   introduces an additional lookup outside that simple count.
2. Whether BFS4 changes the index width, mapped fragment size, next-table size, or
   only a cache/block hint at the captured level.
3. Whether a TF entry's address points to a conventional 4 KiB PTB and, if so,
   which VA bits select its entry.
4. Whether `PAGE_TABLE_BLOCK_SIZE=7` means a 16-bit leaf index for this Apple
   configuration. That is the local helper's formula, not a result derived from
   the X6000 routines above.
5. Whether table indices are absolute VA indices or relative to Apple's nonzero
   context start.
6. Whether the captured BFS4 entry was produced at the exact native level assumed
   by the current `level` labels. The encoder explains the bits, but the retained
   capture does not retain the call's level argument.
7. Large-page coverage and physical-offset calculation for PDE-as-PTE entries;
   the current diagnostic stops at such an entry without proving its mapped span.

Until these are resolved by exact call-level capture, further X6000 disassembly,
or authoritative hardware documentation, an unsupported/incomplete result is the
only defensible TF walker behavior.

## Comparison with this project

### Proven defects or exact semantic mismatches

1. **TF is a declared walker limitation, not a demonstrated programming defect.**
   `GpuVmDiagnostics.hpp:441` returns with `complete=false` when bit 56 is set.
   Linux defines TF as “PTE is handled as PDE” and deliberately sets it on an
   ordinary PDB0 directory entry. Therefore the helper cannot complete a
   Linux-style depth-3 walk through that entry. Because it reports the result as
   incomplete, this is conservative unsupported handling rather than false success
   or wrong hardware programming. It becomes a defect only if a caller interprets
   that incomplete result as a missing leaf or terminal translation. Implementing
   TF descent still requires exact Apple geometry evidence; Linux's semantic name
   alone does not establish the next-table indexing rules for Apple's tree.

2. **The functional root conversion is scoped to VMID2, while the observed fault is
   VMID1.** `GpuVmDiagnostics.hpp:266` rejects every VMID except 2, and
   `RaphaelGPU.cpp:4145-4150` stores only hub-0/VMID2 prepared requests. Linux applies
   the root PDE conversion by backing type, independent of user VMID. If VMID1's
   non-SYSTEM root `0xf40b6ff000` is an MC address in the published framebuffer
   aperture, leaving it programmed unchanged diverges from Linux's required root
   address. The scope mismatch is proven; whether the captured root is truly an MC
   address rather than already physical still depends on the live aperture values.

3. **The `getPDEValue` wrapper cannot implement Linux's SYSTEM/PDE-as-PTE guard.**
   `RaphaelGPU.cpp:4185-4191` passes `system=false` and has no flags argument, so mode
   2 converts every in-aperture address before the native encoder. Linux expressly
   skips conversion for SYSTEM directories and PDE-as-PTE data mappings. This mode
   is unsafe as a general Linux-equivalent conversion. The later mode-4
   `updateEntries` wrapper does inspect encoded SYSTEM and is closer to the relevant
   update boundary, but it still needs producer/ABI evidence to distinguish child
   directories from large mappings.

4. **Project prose overstates the PTE callback.** `GpuVmDiagnostics.hpp:501-505`
   says Linux applies `amdgpu_gmc_vram_mc2pa` to every VRAM PTE. In v7.2.3 the ASIC
   `get_vm_pte` callback performs flag transformations only. VRAM PTE addresses do
   ultimately need the physical address appropriate to their placement, but that
   conversion occurs in the generic mapping/update pipeline before this callback.
   This distinction matters when matching Apple's callback boundary.

### Correct or defensible pieces

- `physicalBase + (mc - mcBase)` matches `mc_addr - vram_start +
  vram_base_offset`, provided the cached FB base and offset really correspond to
  those Linux quantities.
- Refusing root conversion when SYSTEM is set matches Linux. Preserving VALID and
  CACHE/SNOOPED low bits across address conversion also matches the fact that Linux
  ORs flags into the converted root.
- The local four-level indexing formula for depth 3/block 0 gives 9-bit indices at
  shifts 39, 30, 21 and 12, consistent with Linux's configured 48-bit, four-level,
  9-bit layout only for Linux's normal directory encoding. It does not consume the
  per-entry BFS field. The captured entry `0x200000084b700001` has BFS value 4
  (bits 63:59), while Linux forces BFS 9 at PDB1 for an ordinary translated-further
  hierarchy. That mismatch means upstream does not prove the current Apple walk's
  level labels or shifts. Context-relative indexing is likewise not established by
  Linux; it remains an Apple-specific hypothesis based on captured layout.
- Treating PDE-as-PTE as terminal is directionally correct. The diagnostic does not
  calculate the mapped physical byte, so its fixed 4 KiB address mask does not yet
  prove a wrong final translation, but it cannot validate large-page alignment or
  fragment coverage.
- Refusing to traverse SYSTEM child tables through BAR0 is a sound visibility
  limitation, provided reports say “unobservable from BAR” rather than “invalid.”

### Unproven hypotheses requiring capture, not more unit fixtures

- VMID1 root `0xf40b6ff000` needs conversion to `0x84b6ff000`. This follows only if
  the original lies in the current MC aperture, the latter lies in its physical
  aperture, and the root lacks SYSTEM/PDE-as-PTE. Capture the original info object,
  native prepared output, live FB base/top/offset, and live PTB for hub 0/VMID1.
- Apple's VM flags bit 3 exactly maps to encoded SYSTEM for every update producer.
  Existing disassembly supports it for the observed PTE path, not necessarily every
  directory or large-page producer.
- The `updateEntries` call-site offsets remain stable and uniquely identify leaf,
  child, and unmap operations in the exact deployed binary. Authenticate them
  against its UUID and disassembly before a functional rewrite.
- Apple's nonzero context start changes page-table indices to `VA-start`. Linux
  programs user VM starts at zero, so upstream cannot prove that Apple-specific
  rule.

## Actionable next implementation review

Before another GPU cycle, relabel the offline model and tests so TF is explicitly
reported as an unsupported incomplete boundary and add a distinct outcome for
SYSTEM tables that cannot be read through BAR. Do not implement TF descent until
the exact Apple binary or authoritative hardware documentation establishes how
TF, BFS, PAGE_TABLE_DEPTH, PAGE_TABLE_BLOCK_SIZE, and the current level combine;
the captured BFS4 entry is affirmative evidence that the Linux BFS9 hierarchy
cannot simply be copied. Then make the prepared-request capture retain hub-0/VMID1 and report original,
native prepared, live PTB, flags, and aperture arithmetic. Do not generalize mode-2
`getPDEValue` conversion; it lacks the attributes Linux uses to decide conversion.
The Linux-equivalent root policy is hub-0 client VMIDs 1-15, selected by the
root's domain rather than a special VMID number; VMID0 should stay on the project's
separate GART/legacy path. Apply that broad client-VMID policy only behind the
existing reprogram, target, aperture, known-attribute, non-SYSTEM, and in-MC-range
guards. Supporting only VMIDs 1 and 2 would fix the two observed clients but would
remain an arbitrary divergence from Linux. Conversely, do not synthesize VALID:
Linux normally ORs VALID into its root, but Apple's exact ABI has been observed
copying a zero-attribute root directly into PTB, and Linux cannot justify changing
unseen Apple attributes.

For any functional client root change, preserve the native sequence: encode/convert
the root before PTB programming, write both halves, issue a request for VMID1 at
all required levels, and wait for the VMID1 ACK on the correct GFXHUB engine. The
existing native prepare/program path should remain responsible for ordering unless
exact disassembly proves it does not.

The best discriminating observation is the VMID1 prepare boundary already proposed
in `status.md`. It can prove or reject the root-domain hypothesis without interpreting
a reconstructed BAR walk as the hardware's first failure.

## Independent review of the proposed root-policy patch

The later offline patch was reviewed without modifying it. Its functional guards
match the recommended policy: hub 0, client VMID 1-15, reprogram byte exactly one,
confirmed target and aperture, known attributes, non-SYSTEM root, and complete MC
aperture containment. It excludes VMID0, preserves zero attributes, and does not
synthesize VALID. The comment saying all client VMIDs “use the same
framebuffer-backed page-table root address domain” is broader than Apple evidence:
the code remains safe because each request must independently pass the non-SYSTEM
and MC-range guards, but the comment should describe eligibility rather than assert
the backing of every Apple client context.

Offline verification passed: 689 Python tests with 3 skipped, and the focused C++
fixture compiled with `-std=c++17 -Wall -Wextra -Werror` and passed. The Python log
is `/tmp/linux-vm-exact-unittest-20260910.log`, SHA-256
`06c0c54c15c40aae9a27de28845cca506d5920592179d98cabff258cc6474558`.
