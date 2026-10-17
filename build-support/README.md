# Release build inputs

`rlc_fw.h.gz` is a compressed generated firmware header used by the release build.
It includes AMD GC 10.3.6 RLC/MEC/ME/PFP/CE firmware, PSP 13.0.5 TOC payload,
and two TOC find arrays historically extracted from KDK 24G830 HWLibs.
This repository is public. Calling these inputs private research does not grant
redistribution rights.

The 2026-09-16 audit found exact vendor-file matches for every array, including
both KDK-extracted patterns. See [firmware provenance](../findings/research/firmware-provenance-20260916.json)
and the [proposed vendor-only generation plan](../findings/research/licensing-audit-20260916.md).
AMD's binary firmware licence is included as `LICENSE.amdgpu`; the firmware is
not covered by the project's BSD licence. The VCN payload and its provenance are
recorded separately in `src/VcnFirmware.hpp` and `vcn-firmware.json`.

`inputs.json` pins the decompressed header SHA-256, SDK commit and Lilu version.
No firmware/generator code was changed by the licensing audit. The existing
`tools/mkrlcfw.py` still extracts TOC patterns from KDK and does not generate the
later CP arrays, so it is not yet a complete reproducer of the committed header.
Do not change the digest or substitute firmware merely to make a build pass.
