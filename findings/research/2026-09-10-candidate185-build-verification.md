# Candidate 185 build verification

Scope: offline candidate artifact production for audited commit
`c499829dd134402dc9f7227363740720c1a89a15` (`1.0.185` / `metal-018`). No
staging, authority creation, VM, QEMU, device, sudo, deployment, or recovery
action was performed. Candidate-184 artifacts remain untouched.

## Source and static checks

The detached worktree is `/home/bogdan/macos-vm/run/worktrees/candidate-185`,
at the exact audited commit, and was clean before and after build. The exact
24G830 route and preflight checks passed against the candidate source and local
pinned KDK, including route ownership, symbol/prologue checks, recovery-v2/v3
ordering, and milestone pattern uniqueness. The candidate card is
`experiments/metal-018.json`, SHA-256
`1718fc26ffd45550cf9d0187c697af80abeff3ac29ec58ec3899657c6c43985a`.

The build used the pinned toolchain `/home/bogdan/macos-vm/build`, firmware
input hash `c152bb08862f62b4ddef1bdf717be56935d4a8f6d214bd05a96237eccbed982c`,
and KDK build 24G830. No source or runtime files were changed during build.

## Build artifacts

The one approved build command was:

```text
python3 -B tools/build-release.py --toolchain /home/bogdan/macos-vm/build \
  --output /home/bogdan/macos-vm/run/candidate-185-dist
```

The archive is
`/home/bogdan/macos-vm/run/candidate-185-dist/RaphaelGPU-1.0.185-experimental.zip`
with SHA-256
`58dbfbd4535f3bd3b12848fae798443f130eaad478f49b5f78ec3945c2675308`.
It extracts to `/home/bogdan/macos-vm/run/candidate-185` and contains a real
x86_64 `MH_KEXT_BUNDLE` (`0xfeedfacf`, CPU `0x01000007`, filetype 11,
subtype `0x00000003`). The build manifest records source-clean `true`,
`metal_execution_verified=false`, and `verified_playable_games=0`.

The frozen identity record is
`/home/bogdan/macos-vm/run/candidate-185-build-identities.json`; it records
source, archive, manifest, log, executable, Info.plist, card, toolchain and
24G830 KDK identities, with `physical_tested=false`.

## Next reviewed staging command

After independent review of the identity record and candidate paths, stage only
from the clean candidate worktree using the candidate-specific pins and the
reviewed Docker image:

```text
python3 -B tools/stage-candidate.py --execute \
  --candidate-version 1.0.185 --card-id metal-018 \
  --expected-commit c499829dd134402dc9f7227363740720c1a89a15 \
  --expected-boot-id 73ad3355-80a7-48f1-a8dd-e6f770b41de8 \
  --expected-card-sha256 1718fc26ffd45550cf9d0187c697af80abeff3ac29ec58ec3899657c6c43985a \
  --expected-identities-sha256 6862ecf47dc09ff30dad5ae391ef63b52a696163c14cdff9804722a08df7f51e \
  --image-id sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c
```

This report and the artifacts are build verification outputs only; no staging or
launch authority is implied by the build itself.

## Staging preparation record

The reviewed staging transaction completed once from the clean candidate-185
worktree with the recorded commit, card, build-identities and pinned image
identity. It generated run ID `2ef50dc9d8b466c5f2521208b5ba87ea` and preserved
candidate-185 backups. The staging record SHA-256 is
`22c9c90dce52a7e8259cf763487fc25ac36c220cf02f9849d9d7b1c35337aa05`.

The prepared manifest is
`/home/bogdan/macos-vm/run/metal-018-185-manifest.json`, SHA-256
`e23b8013bbc8ecdc4374dedc0e89afd6b63287ba1c35450515b59c828e8cafd1`.
It retains the 180-second exposure, 45-second probe cap, schema-2 COM2
transport, schema-3 recovery, and `GENERIC_GRAPHICS=off`; its output path
`run/metal-018-185` remains absent. A separate run-scoped stage-only authority
was created after this preparation and has not been used for a launch.

The build log contains 43 warning lines, equal to candidate 184's 43; no new
warning category was observed. Candidate-184 build, staging, manifest,
authority, and output artifacts remain byte-for-byte untouched.
