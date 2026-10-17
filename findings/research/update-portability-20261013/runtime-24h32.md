# macOS 15.8.1 update compatibility — candidate486, 2026-10-13

Observed run `4d8855d4b09389190beed0794d1ba4a1`, host boot
`2e377991-b6d2-4fe5-81dd-fd6afe9999f7`, compiled source
`1123584ce6d16d6a0e2a777d47fa4a9349e51e13`, build
`346c68aad1da425085095d74fc796325`. Guest is **15.8.1 / 24H32**.
Artifacts: `~/macos-vm/run/candidate-486-results/`.

- All 163 audited kernel sites resolve at runtime: framebuffer 25, HWLibs 73,
  X6000 65. The moved VM child return is discovered at X6000+0x55a8a;
  logs retain that actual address and the observer checks the verified KC map.
- Changed Metal and VA image UUIDs are accepted through structural discovery,
  with the texture flag derived from named metadata and private COW preserving
  other defaults. The deprecated texture boot argument uses this same path.
- CORE_PROBE_PASS, Metal 3 on AMD Radeon Navi23; display and WindowServer use
  that same accelerator. Offscreen: 1000 frames, 865.04 fps at 1280x1024,
  20001 triangles/frame, 0 failed buffers and 0 sampled pixel mismatches.
- Main readback matrix: 24 cases / 45,496,320 pixels. Two driver-only children:
  12 cases each / 7,888,896 pixels each; neither applies an application patch.
  Combined **61,274,112 pixels**, zero mismatches and zero unwritten pixels.
- Console-user window: 481 submitted buffers, 0 failures, ~120 fps presentation,
  800x600 drawable readback checks 46,112 values with zero wrong values.
  Two self-captures match all four color quadrants and show the moving bar at
  different positions. This is a small window test, not full-field 4K120 stress.
- QEMU's actual host window visibly shows the macOS desktop in a whole-desktop
  portal screenshot (`host-desktop-qemu-visible.jpg`). The portal's targeted
  crop uses inconsistent logical/physical coordinates on this 1.5x KDE display;
  the incorrect crop is not evidence of a blank VM and is not retained as proof.
- Root screen-recording preflight is false; parent whole-desktop/window pattern
  checks are not qualified. Console-user self-captures and drawable checks pass.
- Native shutdown: exited-after-guest-request, QEMU die event exit 0, both capture
  channels clean EOF; recovery **recovered, authorizes_launch=true**. No host
  fault was reported. This verifies a clean run/reuse boundary, not universal
  crash recovery or a fresh-host-boot qualification of this updated driver.

Update admission is automatic: when the stopped disk or discovery contracts
change, cycle.py starts a GPU-less guest, captures its current kernel collections
and userspace text under a revocable nonce, compiles the exact probe, checks the
production locators, requests identity-bound native shutdown, and seals the
stopped disk proof. Saved build labels cannot authorize exposure. Unsupported,
ambiguous or changed instruction/ABI contracts refuse admission before VFIO.

No per-build UUID or running-address table was added. The audited contracts
support compatible code families; arbitrary future private Apple ABI changes
are not guaranteed. Real 24G830 and 24H32 offline inputs pass 326 kernel-site
checks and the production userspace locator. The same driver now also passes live
15.7.9/24G830 (runtime-24g830.md). A third live 15.x version is required before
Tahoe by user priority;
its installer is retained, and no Tahoe installation or qualification occurred.
