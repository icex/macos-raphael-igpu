# Project instructions

- Goal: correct, usable macOS desktop Metal acceleration on the Raphael iGPU, with a watchable
  display path and repeatable cleanup after guest crashes or QEMU closure.
- Read [status.md](status.md) and verify live host/repository state before hardware work.
- Read [docs/host-safety.md](docs/host-safety.md) before the first run. Those rules are not
  optional: no vfio-pci → amdgpu cycling within a boot, `power/control=on` pinned, no sudo on the
  normal path.
- Run experiments with `tools/cycle.py` (see [docs/running-an-experiment.md](docs/running-an-experiment.md)).
  Work in a candidate worktree under `~/macos-vm/run/worktrees/`, never in the `~/src` checkout.
- Keep host safety, identity checks, recovery, and regression checks intact. The host suite
  (`python3 -B -m unittest discover -s tests`) must stay green.
- Update `status.md` after every hardware run with evidence and the blocking issue. Keep it to
  live state; move superseded entries to `findings/research/status-archives/`.
- Do not consume a GPU ledger entry when a launch fails before QEMU/VFIO opens; record launches
  once exposure begins. Extending a boot's allowance needs an explicit note naming the boot id.
- Do not merge or push to `main` until full desktop acceleration is demonstrated.
- Allow up to 6000 seconds per authorized run, with manual stop when appropriate; preserve
  host-fault, identity, capture-fatal, shutdown, and cleanup abort paths.
- Some documents are load-bearing: `tools/experiment.py` and the qualification tools hash the
  designs under `docs/superpowers/specs/` as `design_sha256` contracts. Do not delete or edit
  them casually — the regression suite enforces their digests.
