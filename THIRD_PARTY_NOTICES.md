# Licensing and third-party notices

Original contributions by icex and contributors are licensed under BSD-3-Clause,
see [LICENSE](LICENSE). This grant covers only rights held by those contributors.
Third-party code, firmware, copied excerpts and combined binaries retain their
applicable upstream terms; the project licence does not relicense them. A file's
presence in this repository is not a representation that its entire contents
were independently authored or that every distribution question is resolved.

## Components

| Component / use | Terms and retained notices | Source |
|---|---|---|
| Lilu 1.6.8 startup code compiled into RaphaelGPU, headers, and headless-init patch | BSD-3-Clause; [full notice](LICENSES/Lilu-BSD-3-Clause.txt). `plugin_start.cpp` additionally credits Copyright © 2016–2017 vit9696. | [Pinned Lilu](https://github.com/acidanthera/Lilu/tree/1.6.8); startup source in `Lilu/Library/plugin_start.cpp` |
| MacKernelSDK headers and linked `libkmod.a` | [APSL-2.0](LICENSES/APSL-2.0.txt) and per-file notices; [kmod notices](LICENSES/MacKernelSDK-kmod-NOTICES.txt). This is not a claim that every SDK header has identical terms. | [Pinned SDK source](https://github.com/acidanthera/MacKernelSDK/tree/05094e5e88cec7caedbfb35e8449ed0db94bf95b), including `Library/kmod` |
| AMD RLC/MEC/ME/PFP/CE/TOC firmware in `build-support/rlc_fw.h.gz`; VCN firmware in `src/VcnFirmware.hpp` | Proprietary, redistributable binary firmware under [AMD licence](build-support/LICENSE.amdgpu); not BSD-licensed or open-source microcode. | [Exact-byte upstream provenance](findings/research/firmware-provenance-20260916.json) |
| `patches/qemu/10.1.2-applesmc-key-enumeration.patch` | Upstream `hw/misc/applesmc.c` is LGPL-2.1-or-later, not merely QEMU's project-wide GPL label. The patch's modifications are offered under LGPL-2.1-or-later; upstream context retains its terms. [Licence](LICENSES/QEMU-LGPL-2.1.txt), [notice](LICENSES/QEMU-applesmc-NOTICE.txt). | [QEMU v10.1.2 file](https://github.com/qemu/qemu/blob/v10.1.2/hw/misc/applesmc.c) |
| Linux AMDGPU implementation references and excerpts in source/research | Retain the [AMD MIT-style notices](LICENSES/Linux-AMDGPU-NOTICES.txt) for the reviewed files. Hardware facts alone do not establish copied implementation. This is not a blanket MIT designation for Linux. | Linux v6.12 `drivers/gpu/drm/amd/amdgpu/{gmc_v10_0.c,sdma_v5_2.c,amdgpu_gmc.c,gfx_v10_0.c}` ([source directory](https://github.com/torvalds/linux/tree/v6.12/drivers/gpu/drm/amd/amdgpu)) |

The Lilu patch modifies boot-policy initialization to support a headless guest.
The QEMU patch adds AppleSMC key enumeration. Their upstream copyright notices
remain applicable. Distributing a full modified Lilu or QEMU executable requires
review of that full product and its corresponding source/notice obligations;
these patch notices alone do not cover every component of either executable.

Build/runtime dependencies such as Clang/LLVM, cctools-port, QEMU, OpenCore,
Python, Pillow and vncdotool are not relicensed here. Using a tool does not by
itself mean its code is incorporated into the driver. If those dependencies or
VM/container images are redistributed, inventory that distribution separately.

## Binary distribution and open issues

Source Code of the MacKernelSDK Covered Code is available under APSL-2.0 from
[commit 05094e5e88cec7caedbfb35e8449ed0db94bf95b](https://github.com/acidanthera/MacKernelSDK/tree/05094e5e88cec7caedbfb35e8449ed0db94bf95b).
Preserve per-file notices and applicable source availability. APSL §2.3 also
requires a notice in executable code; documentation alone does not establish
that requirement is met. The SDK's kmod source headers contain an additional
Apple OS-licence restriction. Its effect on this use remains a legal-review item.

The existing release script includes `docs/releases.md` and
`build-support/LICENSE.amdgpu`. The former now contains the original-code, Lilu,
SDK and reviewed Linux notices in full, so future builds include those documents
without changing packaging code. This does not update old ZIPs, tags or the
tracked `kext/bin/RaphaelGPU`, and does not insert a notice inside an executable.

KDK byte-pattern replacement and wider source provenance remain research-only.
Read [the audit](findings/research/licensing-audit-20260916.md) before claiming
licence compliance for a release. No source licence grants permission to run
macOS contrary to its applicable licence or resolves all third-party rights.
