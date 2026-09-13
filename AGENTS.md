# Project instructions

- Goal: functional macOS desktop Metal acceleration on the Raphael iGPU, with repeatable cleanup after guest crashes or QEMU closure.
- Read `status.md` and verify live host/repository state before hardware work.
- Keep host safety, identity checks, recovery, and regression checks intact.
- Update `status.md` after every hardware run with evidence, a brief progress table, and the blocking issue.
- Use `gpt-5.6-luna` with medium reasoning for routine implementation, testing,
  and reviews when available; the coordinator audits their work. Use Astra only
  when the user explicitly requests it.
- Do not merge or push to `main` until full desktop acceleration is demonstrated.
- The normal test path must require no sudo: sleep inhibition runs externally as a user-level `systemd-inhibit --what=idle` process.
- Do not consume a GPU ledger entry when a launch fails before QEMU/VFIO opens; record launches once exposure begins.
- User preference for future authorized runs: allow up to 6000 seconds, with manual stop when appropriate; preserve host-fault, identity, capture-fatal, shutdown, and cleanup abort paths.
