# Same dynamic driver on macOS 15.7.9 — 2026-10-13

Candidate486 / metal-280 / run `96cb263761cb05390978eb05efdbb4a6`, compiled
source `1123584ce6d16d6a0e2a777d47fa4a9349e51e13`, same binary/build as 24H32.
Host boot `2e377991-b6d2-4fe5-81dd-fd6afe9999f7`.
Artifacts: `~/macos-vm/run/candidate-486-attempt-24g830r2-results/`.

The independent backup clone contains a prepared Tahoe base volume alongside a
sealed 15.7.9 snapshot. Mounting that exact snapshot read-only confirms 24G830;
GPU-less live inspection also observes 15.7.9/24G830 and validates its actual
collections and userspace text. The base-volume label never authorizes launch.
Its existing root agent initially was not loaded. Sudo authentication failed;
no root change or GPU exposure occurred in that first attempt. A temporary
LaunchDaemon on the clone bootstraps the existing agent if absent; a working
CPU-only clone performed that narrow offline repair after snapshot/disk checks.
The original backup and original 15.8.1 user disk are preserved.

- Fresh disk-bound compatibility proof resolves all 163 sites before MODE2/VFIO.
- CORE_PROBE_PASS; Metal 3 and WindowServer/display use the same Navi23 device.
- Main and two driver-only children check 61,274,112 pixels: zero mismatches or
  unwritten pixels. Driver-only children do not self-patch.
- Offscreen 1000 frames: 1759.30 fps, zero failed buffers/sampled mismatches.
  This is a different run configuration/load, not a controlled speed comparison.
- Console user UID501: ~119.50 fps, 477 presented frames, zero failed buffers or
  missing drawables. Drawable readback checks 46,112 values, all correct.
- Both self-captures match quadrants and show distinct moving-bar spans
  [553,632] and [153,232]. Root whole-screen permissions remain a separate limit.
- Bounded session stopped through the harness stop-request file. Native shutdown
  exits-after-guest-request; QEMU exit 0. Recovery recovered, authorizes_launch=true.

This is the second live macOS 15 version for the same dynamic driver. Installer
inputs for 15.7.7/24G720 and 15.8/24H23 also pass the 163-site kernel catalog and
six production userspace patch contracts without changes (see installer-matrix.json).
Those offline checks do not count as live GPU qualification. Per user instruction,
qualify 15.8 live as the third version before proceeding to macOS 26 and its updates.
