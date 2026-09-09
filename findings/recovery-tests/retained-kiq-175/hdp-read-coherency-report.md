# Raphael VFIO BAR0 HDP read-coherency audit

Date: 2026-09-09
Scope: offline source analysis and unit-tested recovery helper change only. No GPU, VFIO device, VM, reset, rebind, staging, or privileged operation was used.

## Conclusion

A missing HDP read-cache invalidation is a correctness gap in the host-KIQ completion poll when it reads GPU-produced RPTR-report and fence words through the VFIO-mapped PCI BAR0 aperture. Linux invalidates HDP and executes a full memory barrier before a PCI aperture read. VFIO only gives the userspace VMA noncached page protection; it does not perform AMD HDP invalidation.

This finding does not establish why candidate 175 failed to observe its fence. The packet may have failed, been delayed, or completed without BAR0 visibility. The retained failure also lost the exact terminal HQD-RPTR/report/fence tuple, so stale HDP remains a plausible cause rather than a demonstrated cause.

## Raphael register provenance

The retained discovery summary at `/home/bogdan/macos-vm/findings/hw/ip_discovery.txt:33` reports `HDP 5.2.0`. Its SHA256 is `c470672042aad359ec155a769edbf9a85f28fbbaac41d3a4ca5c97fcc00b066d`.

The binary discovery table was extracted read-only from `/home/bogdan/macos-vm/findings/hw/amdgpu_debugfs.txt` into `/tmp/raphael-ip-discovery.bin` (1032 bytes; SHA256 `50673a15f69f05f45ff73fde28eb60b18d35f0a75828456050008d9cc8113f96`). Its checksummed IP-v4 record for HWID 41, instance 0, version 5.2.0 has segment bases `0xf20` and `0x0240a400`.

Linux v6.12 [`amdgpu_discovery.c`, HDP dispatch](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/amdgpu_discovery.c) selects `hdp_v5_0_funcs` for HDP 5.2.0. [`hdp_v5_0.c`, `hdp_v5_0_invalidate_hdp`](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/hdp_v5_0.c) writes 1 to `mmHDP_READ_CACHE_INVALIDATE` on the direct, non-ring path. [`hdp_5_0_0_offset.h`, `mmHDP_READ_CACHE_INVALIDATE`](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/include/asic_reg/hdp/hdp_5_0_0_offset.h) gives relative dword `0xd1`, base index 0; [`soc15_common.h`, `SOC15_REG_OFFSET` and direct access macros](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/soc15_common.h) adds the discovered base. The resulting BAR5 byte offset is `(0xf20 + 0xd1) * 4 = 0x3fc4`. [`hdp_5_0_0_sh_mask.h`, invalidate mask](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/include/asic_reg/hdp/hdp_5_0_0_sh_mask.h) defines bit 0 as the invalidate trigger.

Current upstream at commit `893e11787f78e43b534e252249ac3fff4d1333f8` also performs a same-register posting read after the direct write in [`hdp_v5_0_invalidate_hdp`](https://github.com/torvalds/linux/blob/893e11787f78e43b534e252249ac3fff4d1333f8/drivers/gpu/drm/amd/amdgpu/hdp_v5_0.c). AMD commit [cf424020e040](https://github.com/torvalds/linux/commit/cf424020e040be35df05b682b546b255e74a420f) added that posting read to ensure the write reaches the device. A later flush-specific change does not remove the same-register invalidate read.

## Aperture and ordering semantics

Linux v6.12 [`amdgpu_device_aper_access`](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/amdgpu_device.c) calls `amdgpu_device_invalidate_hdp`, then `mb()`, then `memcpy_fromio` for aperture reads. Its write direction has the inverse role: CPU-to-VRAM copy, `mb()`, then HDP write-cache flush. The existing `flush_hdp` therefore cannot substitute for invalidation before reading a GPU-produced fence.

The x86 bare-metal APU skips in [`amdgpu_device_flush_hdp` and `amdgpu_device_invalidate_hdp`](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/amdgpu_device.c) correspond to a different aperture path. [`gmc_v10_0_mc_init`](https://github.com/torvalds/linux/blob/v6.12/drivers/gpu/drm/amd/amdgpu/gmc_v10_0.c) initially uses PCI BAR0, but for an x86 APU outside passthrough it replaces `aper_base` with the physical framebuffer offset and expands it to real VRAM size. Our VFIO userspace mapping remains the PCI resource, so the native direct-DRAM exception does not justify skipping HDP invalidation.

VFIO v6.12 [`vfio_pci_core_mmap`](https://github.com/torvalds/linux/blob/v6.12/drivers/vfio/pci/vfio_pci_core.c) maps the PCI BAR with `pgprot_noncached`. This prevents ordinary CPU write-back caching but supplies no AMD HDP operation. Consequently `clflush`, `mmap.flush`, and `msync` are not substitutes for the device invalidate.

On the audited x86_64 host, Linux `arch/x86/include/asm/io.h:47-67` implements aligned `readl/writel` as native-width `mov` operations with compiler memory clobbers; `arch/x86/include/asm/barrier.h:8-24` defines the strict full barrier. The helper mirrors this with aligned native-width ctypes u32 access, a same-register posting read, and C11 seq_cst `atomic_thread_fence(5)` on ordinary memory. The local `/usr/lib/libatomic.so.1` implementation is `lock orq $0,(%rsp); ret`: it fences through the stack and does not issue an atomic RMW to MMIO.

## Frozen offline change and verification

`tools/vfio-recover.py` SHA256: `d4e4994885ad8300b89f96ae78a7098e872b64055cc8123146959d2a66c39e21`

`tests/test_vfio_recover.py` SHA256: `627cbc52971cc62f3fb032e1490d4bc9634e100d5f327e63eb7d13b60a090f0a`

The dependency and x86_64 gate resolve before any VFIO device open. Each host-KIQ completion poll reads the selected HQD RPTR, writes 1 to BAR5 offset `0x3fc4`, reads that register back, rejects `0xffffffff`, executes the ordinary-memory full fence, then reads the BAR0 report and fence. Failure evidence retains the invalidate count and last proof. The successful schema-5 receipt shape remains unchanged.

Verification command:

```sh
python3 -m unittest tests.test_vfio_recover
python3 -m py_compile tools/vfio-recover.py tests/test_vfio_recover.py
git diff --check -- tools/vfio-recover.py tests/test_vfio_recover.py
```

Result: 62/62 tests passed. Log: `/home/bogdan/macos-vm/run/hdp-invalidate-vfio-recover-tests.log`; SHA256 `103dcc1f6bc90213c2b4f7a43f2392253c89a172a303ee63393ac96492f813c6`.

The new tests cover the discovery-derived offset, native-u32 alignment and bounds, store/posting-read/fence order, all-ones fail-closed behavior, dependency failure before `os.open`, stale-HDP visibility, and preservation of existing recovery receipt validation.
