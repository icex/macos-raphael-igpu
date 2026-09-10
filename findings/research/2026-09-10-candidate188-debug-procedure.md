# Candidate 188 debug procedure

This is a command recipe for coordinator review. Do not execute until the coordinator
has audited the clean worktree, build identity record, host boot, and one-run
authority. It performs no automatic retry and does not imply Metal success.

## Build from the private clean worktree

Confirm the worktree is clean and record its exact commit before building:

```sh
cd /home/bogdan/macos-vm/run/worktrees/candidate-188
git status --porcelain
git rev-parse HEAD
python3 -B tools/build-release.py \
  --toolchain /home/bogdan/macos-vm/build \
  --output /home/bogdan/macos-vm/run/candidate-188-dist \
  --debug-symbols
```

The build must produce the release archive and
`candidate-188-dist/debug-symbols/{RaphaelGPU.dSYM,build-kext-debug.sh,debug-manifest.json}`.
Retain the generated `build-manifest.json`, debug manifest, archive, build log,
and the candidate build identity JSON. The manifests must bind the executable
and dSYM UUID, executable/DWARF hashes, exact debug flags, private script hash,
debug source hash, and equal canonical input hashes before and after the build.

## Stage after independent identity review

Use the exact commit, card digest, identity-record digest, and pinned Docker
image recorded by the build review. The current card digest is
`1bb8a0bcb6bbe8567417a1ce2908f1c52622f457a6296385e4223285e1444843`; replace
the placeholder identity/image values only with reviewed values.

```sh
cd /home/bogdan/macos-vm/run/worktrees/candidate-188
python3 -B tools/stage-candidate.py --execute \
  --candidate-version 1.0.188 --card-id metal-021 \
  --expected-commit <candidate-188-commit> \
  --expected-boot-id 3bca3e47-1f28-4f78-af00-5dbf76b00620 \
  --expected-card-sha256 1bb8a0bcb6bbe8567417a1ce2908f1c52622f457a6296385e4223285e1444843 \
  --expected-identities-sha256 <candidate-188-build-identities-sha256> \
  --image-id sha256:<reviewed-docker-image-digest> \
  --lilu-bundle /home/bogdan/macos-vm/run/headless-lilu-verified-53b5a19812e6/Lilu.kext \
  --expected-lilu-executable-sha256 53b5a19812e66eeea3d3b874fe642f441cbfeccd171fb5ba05dc2e0ced3b8887 \
  --expected-lilu-info-sha256 6714fee51444238c0540814729767485572441435bcf36a158571cf78317a669 \
  --expected-lilu-build-manifest-sha256 e5d2554d29658699dd9535a9b8dd38ca9aae5aa5a12f65508b083d3c519cf378
```

Staging must be from the clean candidate worktree and must leave the exact
candidate 187 rollback/readback protections intact. It creates the run ID and
prepared manifest; do not launch from an unreviewed or manually edited record.

## Prepare the run manifest

After staging has produced the reviewed manifest and run ID, prepare exactly
once with the same VM directory and card specification:

```sh
python3 -B tools/experiment.py prepare \
  --vm-dir /home/bogdan/macos-vm \
  --spec /home/bogdan/src/macos-raphael-igpu/experiments/metal-021.json \
  --output /home/bogdan/macos-vm/run/metal-021-188 \
  --run-id <32-lowercase-hex-run-id>
```

The card requires the existing headless/no-graphics topology plus `GDB=on`.
The 180-second exposure, 45-second probe gate, COM2 critical transport,
recovery lease, and cleanup gates remain unchanged. GDB observations are
diagnostic evidence only: VMID1 correlation and any native mapping result must
be established by the captured evidence rather than assumed.
