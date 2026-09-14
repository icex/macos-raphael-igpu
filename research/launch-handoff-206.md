# Candidate 206 launch handoff

For a fresh candidate-206 attempt, keep the build source pin and coordinator HEAD distinct:

1. Build once from the clean source commit `B`. The archive manifest and card source fields must identify `B` and the source tree digest.
2. Pin `experiments/metal-040.json` to `B`, then make the card-only coordinator commit `C`. Do not rebuild after this pin.
3. Extract the archive into `run/candidate-206`, create the build identity record, and use `stage-candidate.py` from the resolved candidate-206 worktree with `--expected-commit C`. The staged identity still records source commit `B`; `--expected-identities-sha256` must be the fresh attempt identity digest.
4. Pass the Lilu bundle directory itself, ending in `Lilu.kext`, not its parent. Its sibling `build-manifest.json` supplies the Lilu manifest digest.
5. Staging writes the isolated attempt `staging.json` and staged boot/config artifacts. Then run `experiment.py prepare` with the card, fresh 32-hex run ID, attempt name, VM directory, and a new output path. The prepare output is the executable run manifest.
6. Run with that prepared output manifest: `experiment.py run --vm-dir ... --manifest .../manifest.json --output ... --manual-reuse --ack-risk`. `--run-id` and `--attempt` are prepare-only options; passing either to `run` is rejected. A staging `staging.json` is not the prepared run manifest.

Reference prepared manifests from the working flow: `/home/bogdan/macos-vm/run/candidate-205-attempt-stamp205early-results/manifest.json` and `/home/bogdan/macos-vm/run/candidate-205-attempt-stamp205memory-results/manifest.json`.

The candidate-206 staging attempt used run ID `8ee1b86dd47abb4c717eb2d704a835ad`; its staging transaction succeeded, but no hardware launch was made from the staging record.
