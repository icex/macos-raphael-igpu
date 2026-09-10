# Candidate 184 build verification

Scope: offline candidate artifact production for commit
`ec02aacea85fe5d652b5da0cee2e8eda344ef278` (`1.0.184` / `metal-017`). No VM,
QEMU, device, sudo, staging, deployment, or recovery action was performed.

## Source and static checks

The detached worktree is `/home/bogdan/macos-vm/run/worktrees/candidate-184`,
at the exact reviewed commit, and was clean before build. `src/` is byte-
identical to the already verified `d421120` source. The five recovery helpers
match the canonical receipt exactly:

| Helper | SHA-256 |
|---|---|
| `tools/critical-replay.py` | `8e0332d763be3fb6e31d5877ad78711c8673e8f5aeae56ba4989248947554b61` |
| `tools/kiq-recovery-proof.py` | `16af9cd9b5e807a44e0e28d6b6005840b9d720c50df2ce757b820dd5d3de0398` |
| `tools/recovery_lease_v2.py` | `445544dd52f30cf32838472d2d248d69ea1cd3e703c8f580ecef6491238aa7d2` |
| `tools/recovery_lifetime_v3.py` | `61ab64bec086d0c358a05b57f893bc6267b94d9b6f431bed100de13a9d0fbcea` |
| `tools/vfio-recover.py` | `3616a938db007c84ecae6048bfd83100902759a328dda92c1d5394801e2d288e` |

`route-domains.py` passed. The exact-KDK 24G830 preflight passed against the
candidate source and pinned local KDK: all route symbols/prologues, recovery
ordering and milestone pattern uniqueness checks passed. The previously
completed focused contract verification remains 89 tests passed; the final
full Python suite was already recorded as 615 passed with one existing skip and
was not rerun here per the candidate procedure.

## Build artifacts

The one approved command was:

```text
python3 -B tools/build-release.py --toolchain /home/bogdan/macos-vm/build \
  --output /home/bogdan/macos-vm/run/candidate-184-dist
```

The archive is
`/home/bogdan/macos-vm/run/candidate-184-dist/RaphaelGPU-1.0.184-experimental.zip`
with SHA-256
`78f5b478093ffd60b298b685640ddf01f6bf5cf63eabf8411af8bb40e2bdc761`.
It extracts to `/home/bogdan/macos-vm/run/candidate-184` and contains a real
x86_64 `MH_KEXT_BUNDLE` (`0xfeedfacf`, CPU `0x01000007`, filetype 11,
subtype `0x00000003`). The build manifest records source-clean `true`,
`metal_execution_verified=false`, and `verified_playable_games=0`.

The complete frozen identity record is
`/home/bogdan/macos-vm/run/candidate-184-build-identities.json`; it records
source, archive, manifest, log, executable, Info.plist, card, toolchain and
24G830 KDK identities, with `physical_tested=false`.

These artifacts are build verification outputs only. They are not staged,
deployed, published, or authorized for a hardware launch by this task.
