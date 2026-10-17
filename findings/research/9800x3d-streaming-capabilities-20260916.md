# Ryzen9800X3D streaming capability check — 2026-09-16

Live host identity: AMD Ryzen7 9800X3D, PCI1002:13c0 revisioncb at0000:7b:00.0
(Granite Ridge Radeon Graphics). macOS Navi23 identity is compatibility presentation,
not physical RX6600 hardware. User reports DDR5-6000; active DRAM rate/channel
population was not independently measured in this read-only investigation.

## Official sources

- [AMD9800X3D specifications](https://www.amd.com/en/products/processors/desktops/ryzen/9000-series/amd-ryzen-7-9800x3d.html): two graphics cores at2200MHz; two DDR5 channels;
  official two-DIMM memory supportDDR5-5600, EXPO supported.2200MHz is a specification,
  not a measured current clock in the macOS guest.
- [AMD AMF hardware table](https://github.com/GPUOpen-LibrariesAndSDKs/AMF/wiki/GPU-and-APU-HW-Features-and-Support): Granite Ridge has one VCN block (table labels3.0).
  VCN3.0/3.1 supports4:2:0 H2648-bit encode up to4K, HEVC8/10-bit encode up to8K,
  and AV1 decode up to8K, without AV1 encode. The table does not publish an exact
 9800X3D HEVC4K FPS guarantee. Resolution support is not throughput.

The local Linux IP-discovery archive reports UVD/VCN3.1.2 for this device:
linux-baseline-20260913-boot95ac6099-557f-41cd-9206-cde5282516eb.raw.txt lines389/431.
Preserve this distinction from the coarser vendor table; both versions share its
codec capability row. Hardware HEVC10-bit capability does not imply current macOS
support: our tested native encoder exposes Main8 only.

## Memory calculation and limits

Assuming dual64-bit channels actually operating at6000MT/s, peak theoretical
bandwidth is6000e6*16=96GB/s, shared with CPU and other users. This is not measured
or dedicated GPU bandwidth. One4K60 BGRA pass is1.990656GB/s; one NV12 pass is
0.746496GB/s. Multiple reads/writes, conversion, cache behavior and allocation cost
increase traffic. These numbers do not establish that the actual GPU path is free
of bandwidth bottlenecks, but do not support a simple DDR5-6000-implies4K30 cap.

## Current observation and conclusion

After candidate282 logging fix, user reports1080p60 and4K20–30FPS, up from3–4FPS.
This is user-observed streaming, not an independently instrumented post-fix stream.
The generated4K HEVC tests encoded/flushed60frames in1.565685s including CPU pattern
production (~38.3FPS), so there is no universal hard30FPS encode cap under all
settings. Pattern/bitrate differ from Sunshine and this does not prove4K60 streaming.

Keep4K60 as an investigation target. Separate capture/conversion, encode submission
and callback completion, memory reclaim, and actual engine clocks before declaring
a silicon ceiling. A native Linux/Windows same-settings baseline would distinguish
hardware from this macOS stack; the old Linux test was720p, not4K throughput proof.
No new hardware run, reset, clock modification or driver rebind was performed.
