# Restartable snapshot host extension — candidate394, 2026-10-09

Implemented software-only host protocol; no guest bridge/native qualification is
claimed here. The legacy research patch is unchanged. Apply
`patches/qemu-10.1.2-bochs-snapshot-restart.patch` after the existing Bochs snapshot
patch (and the existing full-refresh prerequisite). Its dry-run against the retained
candidate372 tree passes. The new property is opt-in, default false:
`bochs-display,x-debug-snapshot=on,x-debug-snapshot-restart=on`.
Restart without snapshot fails device realization.

## Contract

- Legacy property absent: magic0x52534731,0x30-byte register window and one-shot
  behavior remain unchanged. Restart property: magic0x52534732,0x38-byte window.
- Requested epoch at0x30 is RW; active epoch at0x34 is RO. ARM is accepted only
  in available/retired state, requested==active+1, active!=UINT32_MAX.
- ARM clears dimensions, ACK/error, pending and published sequence bookkeeping,
  discards pending storage, installs the new epoch and enters armed state.
  Lifetime publication/replacement counters remain cumulative.
- Armed dimension/commit/RETIRE writes require requested==active!=0. Bad epochs
  set error5 without changing dimensions, ACK or pending output. ARM while armed
  is also rejected with error5. Existing sequence/geometry errors stay3/4.
- RETIRE discards pending output and restores ordinary BAR0 fallback behavior.
  Fresh epoch sequences begin1. Existing BQL serialization, immutable host copy,
  latest-pending policy and migration refusal remain.

This protocol is **not protection against old direct BAR writers**. Deployment
requires the proposed guest private RAM descriptors and a fixed host bank/control
mapping unavailable to userspace. Root owns that independent bridge implementation.
The sealed presenter ABI does not need an epoch field: the bridge owns translation.

## Actual device/model checks

`tools/qemu-snapshot-smoke.py --restart` drives a real isolated QEMU10.1.2 device
through qtest and reads complete QMP screen dumps; it does not duplicate the device
state machine. The existing invocation without the flag checks legacy behavior.
Both use paused TCG with no KVM, guest disk, network device or physical GPU.

Final receipts under `/home/bogdan/macos-vm/run/c394-restart-snapshot/`:

- `restart-v3/result.json`:15 full-image checks; refused missing prerequisite,
  zero/skipped/UINT32_MAX requested initial epochs, armed re-ARM, active-register
  write, stale dimensions/commit/RETIRE with unchanged pending+ACK, duplicate
  sequence, oversize frame, retirement with pending cancellation, epoch2 sequence1,
  odd801×601 output, overwrite-after-ACK isolation and ordinary fallback.
- `legacy-v3/result.json`:11 full-image checks retain one-shot behavior.
- Both assert migration fails with `pre-save failed: bochs-display`; QEMU exits0.
- `provenance.json` records retained source, resulting binary and oracle hashes.
  Fresh isolated configure uses x86_64-softmmu, SPICE/TCG enabled, KVM/docs/guest-agent/
  downloads/werror disabled; build uses isolated ninja -j4. No global binaries or
  images were replaced.

The first odd-width oracle run failed because QEMU10.1.2 `ui/ui-qmp-cmds.c::ppm_save`
writes pixman's aligned RGB24 row stride, including padding. This was initially
misattributed to destination surface stride; that inference was retracted.
`ui/console.c::qemu_create_displaysurface` explicitly uses width*4. A temporary row-copy
change was removed; the host snapshot copy is unchanged. The corrected oracle checks
exact header/serialized length and every RGB pixel using the actual aligned row stride,
without treating padding as image pixels. Earlier failed artifacts remain retained
as `restart/` and `restart-v2/`; these are not passing controls.

The active==UINT32_MAX overflow branch is source-reviewed, not reached by billions
of real epoch transitions. These tests do not establish guest memory ordering,
private-descriptor lifetime, native restart/death cleanup, SPICE client delivery,
full desktop atomicity or performance. Those remain integration requirements.

## Final hashes

- `/home/bogdan/macos-vm/run/worktrees/candidate-394/findings/research/patches/qemu-10.1.2-bochs-snapshot-restart.patch`: `93be1e7f4af4c70c8109d66cf45dbc0cc11b1cf9d1f2603ea1a92e412adfe68b`
- `/home/bogdan/macos-vm/run/worktrees/candidate-394/tools/qemu-snapshot-smoke.py`: `16722a796a961803bf080b8607e4f38fd9c0adf0cc810215b064f3200121474f`
- `/home/bogdan/macos-vm/run/c394-restart-snapshot/build/qemu-system-x86_64`: `c6df41f5d07a8edcad6615a17f8c582d1c5abd00792b966a4bc01791dc5a68ba`
- `/home/bogdan/macos-vm/run/c394-restart-snapshot/restart-v3/result.json`: `669c8a15137cba1941432a57759696eb3ce9ce05be9441516af8a63a97ab59bf`
- `/home/bogdan/macos-vm/run/c394-restart-snapshot/legacy-v3/result.json`: `741d54cfc41a8384479516c265950cf717f5ffcfb1858b786c5d6ddca2bb5032`
- `/home/bogdan/macos-vm/run/c394-restart-snapshot/qemu-10.1.2/hw/display/bochs-display.c`: `ed0078b002b947ede79cf83b4cdfd5253cc0031021b1ca2b607912353e763b21`
- `/home/bogdan/macos-vm/run/c372-changed-bbox/qemu-10.1.2/hw/display/bochs-display.c`: `bac68a27f0f9a312a36880832d471b6735c1f350c0d8da2944b79bd93099a2c8`
