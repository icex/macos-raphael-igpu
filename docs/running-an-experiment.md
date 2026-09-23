# Running an experiment

The loop is:

```
change code  ->  test & preflight  ->  run the QEMU experiment  ->  check the result  ->  update status.md
```

`tools/cycle.py` is the single entry point for the middle three steps. Everything derivable
from the repository and the host is derived automatically; only the values that cannot be
(the staged boot image, the verified Lilu bundle, the device identity) live in
`experiments/pins.json`.

## 1. Change code

Work in the candidate worktree, not the `~/src` checkout:

```sh
git worktree add /home/bogdan/macos-vm/run/worktrees/candidate-231 -b candidate-231
```

Commit before running — the cycle refuses a dirty worktree unless you pass `--allow-dirty`,
because the run's identity is pinned to `HEAD`.

## 2. Build and record the identity

```sh
tools/build-release.py --toolchain ~/macos-vm/build \
    --output ~/macos-vm/run/candidate-231-dist --debug-symbols
```

Then write `~/macos-vm/run/candidate-231-build-identities.json` describing the build
(version, `source_commit`, archive and executable digests). `stage-candidate.py` verifies every
field, so a mismatch stops the cycle before the GPU is touched.

Write the experiment card as `experiments/metal-0NN.json` and commit it.

## 3. Test, preflight and run

```sh
# review the plan without touching the device
tools/cycle.py --candidate 231 --card metal-079 --dry-run

# the real thing
tools/cycle.py --candidate 231 --card metal-079
```

`cycle.py` performs, in order, aborting before any GPU exposure if a gate fails:

| Step | Gate |
|---|---|
| preflight | GPU is on `vfio-pci`; idle-inhibitor container is up; worktree is clean and at a known commit; the card and build-identities exist; the host regression suite passes |
| MODE2 reset | fresh receipt with `CP_STAT=0` and `RLC_CNTL=0` — numbered automatically, never overwriting an earlier one |
| stage | `stage-candidate.py --execute` with the derived commit/boot-id/card/identity digests and the pinned image and Lilu hashes |
| prepare | `experiment.py prepare` against the staged run id |
| run | `run-gpu-test.py`, which wraps `experiment.py run` in a user-level `systemd-inhibit --what=idle` and appends the verdict to `status.md` |

Useful flags: `--attempt NAME` for an isolated retry namespace, `--skip-tests` when the suite
has just run, `--allow-dirty` for a deliberately uncommitted experiment.

A same-boot launch on a previously used host boot is admitted automatically: there is no flag
and no `status.md` allowance note. The MODE2-reset + recovery-receipt teardown protocol is the
proven safety boundary, so preflight always runs the reset, and the next `experiment.py run`
is admitted whenever the immediately prior run on this boot left a valid recovery receipt
(`authorizes_launch=true`), on top of the unchanged host identity, amdgpu initialization,
capture, shutdown, and cleanup checks. A successful MODE2 reset alone does not authorize
reuse — a missing or invalid recovery receipt still refuses the launch.

The cycle returns nonzero for a launcher failure or an `INVALID`/missing wrapper verdict.
A completed experiment may still have a blocking functional verdict; inspect the result JSON.

## 4. Check the result

The final JSON names the verdict, the manifest and the results directory. Logs land in
`~/macos-vm/run/candidate-231-{stage,prepare,run}.log`; artifacts in
`~/macos-vm/run/candidate-231-results/`.

For a deeper look use `tools/classify-run.py`, and `tools/decode-hang-dump.py` when the run
produced a hang dump.

## 5. Update status.md

`run-gpu-test.py` appends the verdict automatically, but the ledger entry is written by hand:
what was tested, what the evidence shows, and what the next discriminating test is. Keep
`status.md` short — it is live state, not a diary. Older entries belong in
`findings/research/status-archives/`.

## Boot arguments

Set by the experiment card, not by hand. The ones that currently matter:

| Argument | Effect |
|---|---|
| `rgpunobin=1` | disable Navi23-sized DPBB binning; without it the graphics ring hangs on the first desktop draw |
| `rgpusdmacfg=2` | hold `SDMA0_GB_ADDR_CONFIG` at Raphael's `0x42`; without it the desktop is tile-permuted |
| `rgputexdiag=2` | clear `enableTexturePipeBankXor` per Metal process; without it managed-texture copies are wrong by one bit at 64 px |
| `rgpugolden=1`, `rgpuhangdump=1` | diagnostics: golden-register sweep and hang capture |

`-lilubetaall` is mandatory on Sequoia or Lilu disables itself and takes the plugin with it.

## The ledger

Every launch is recorded in `run/used-gpu-boots/<boot>.json` as an audit trail — it never
refuses a launch by count. Record launches only once VFIO exposure begins — an abort before
QEMU starts is not a launch and must not consume a ledger entry. Same-boot reuse goes through
the automatic MODE2 reset and the prior run's recovery receipt; there is no allowance note and
no flag.

## Safety

Read [host-safety.md](host-safety.md) before the first run. The short version: the iGPU must be
initialised by `amdgpu` during the current boot, must never be cycled back to `amdgpu` within a
boot, and must have `power/control=on` pinned before anything opens it.

### Recovery when the guest never published a usable lease

If ordinary recovery fails and the guest is confirmed stopped, use the bounded
MODE2/no-queue path. Inspect first (no reset or PSP commands):

```sh
python3 -B tools/mode2-noqueue-recover.py --vm-dir ~/macos-vm \
  --run-dir ~/macos-vm/run/candidate-N-results \
  --output ~/macos-vm/run/candidate-N-noqueue-inspection.json
```

Use `--execute` with a new output filename for cleanup. It runs the existing SMU
MODE2 reset, then requires two complete stable scans of all 64 compute HQDs,
both graphics pipes, polling/doorbells, and all supported SDMA inputs. GC must
already be halted and idle, and SDMA halted/idle with every input disabled.
Only then does it send the existing PSP DESTROY_RINGS and DESTROY_GPCOM_RING
commands and repeat the scans. It never borrows an older lease or writes guest
VRAM, queue state, doorbells, or DMCUB controls. A nonzero inactive doorbell range
alone is not an enabled doorbell: global polling/status and every queue's
control must independently be disabled.

The schema-9 receipt binds the latest failed run, boot, unchanged ledger,
original artifacts and recovery sources. Normal admission validates and consumes
it once; original failed receipts remain unchanged. A reset ACK alone does not
produce this receipt. Any active queue, inaccessible read, enabled SDMA input,
PSP timeout, host fault or identity mismatch refuses authorization.
