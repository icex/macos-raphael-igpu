# Game compatibility

Updated 2026-09-08, driver 1.0.159, macOS Sequoia 15.7.9 (24G830), Raphael iGPU
spoofed as Navi23 under QEMU/VFIO.

**Verified playable games: 0.** No individual game has a recorded compatibility test.
No title is listed as supported, and untested titles are not being labeled failures.
Metal 3 enumeration alone does not establish game compatibility.

| Workload | Result | Evidence |
|---|---|---|
| Native Metal compute probe | Failed on first command buffer; zero completed submissions | [Clean-run verdict](../findings/metal-tests/20260908T052603Z-8dad7535/result.json) |
| Native offscreen rendering probe | Not reached after compute failure | Same verdict |
| Individual games | Not tested | No game test records exist |

A supported entry will require a named game and version, graphics backend, guest/driver
versions, resolution/settings, actual rendered gameplay, observed duration and linked
logs/results. Record crashes, rendering defects and performance separately. Passing the
small Metal probe is a prerequisite for game testing, not proof that games work.
