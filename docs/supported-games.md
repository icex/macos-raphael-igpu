# Game compatibility

Updated 2026-09-16; hardware baseline RaphaelGPU1.0.280, macOS Sequoia24G830,
Raphael iGPU presented through the Navi23 driver under QEMU/VFIO.

**Verified playable games: 0.** No named game has a recorded compatibility test.
Untested games are neither supported nor known failures.

Metal compute, offscreen rendering, texture/buffer copies, bounded depth/stencil
and color-MSAA resolve, and sampled remote-desktop composition pass their scoped
checks. These are prerequisites, not game compatibility evidence. The historical
direct OpenGL probe hang remains unresolved; do not repeat without diagnosis.

A supported entry needs the game/version, graphics backend, exact guest/driver
build, resolution/settings, rendered gameplay, duration, frame times, defects and
linked raw results. Correctness and cleanup must be recorded separately.
[Current evidence and remaining gates](ROADMAP.md), [live state](../status.md).
