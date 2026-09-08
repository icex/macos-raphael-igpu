# Game compatibility

Updated 2026-09-08, hardware-tested driver 1.0.170, candidate 1.0.171, macOS Sequoia 15.7.9 (24G830), Raphael iGPU
spoofed as Navi23 under QEMU/VFIO.

**Verified playable games: 0.** No individual game has a recorded compatibility test.
No title is listed as supported, and untested titles are not being labeled failures.
Metal 3 enumeration alone does not establish game compatibility.

| Workload | Result | Evidence |
|---|---|---|
| Native engine startup | Pass on candidate 170; hybrid engines and power-up succeed, KIQ advances through at least stamp 34 | Candidate 170 serial evidence |
| Native Metal compute probe | Not reached; candidate 170 timed out on the first SDMA0 paging submission | Candidate 170 serial evidence |
| Native offscreen rendering probe | Not reached | Same experiment |
| Individual games | Not tested | No game test records exist |

A supported entry will require a named game and version, graphics backend, guest/driver
versions, resolution/settings, actual rendered gameplay, observed duration and linked
logs/results. Record crashes, rendering defects and performance separately. Passing the
small Metal probe is a prerequisite for game testing, not proof that games work.

Game qualification is currently deferred. The active target is correct Metal compute,
offscreen rendering, and accelerated desktop composition through the VM display.
