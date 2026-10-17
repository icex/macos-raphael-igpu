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
git worktree add /home/user/macos-vm/run/worktrees/candidate-231 -b candidate-231
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
| run | `run-gpu-test.py`, which wraps `experiment.py run` in a user-level `systemd-inhibit --what=sleep:idle` and appends the verdict to `status.md` |

Useful flags: `--attempt NAME` for an isolated retry namespace, `--skip-tests` when the suite
has just run, `--allow-dirty` for a deliberately uncommitted experiment.

A same-boot launch on a previously used host boot is admitted automatically: there is no flag
and no `status.md` allowance note. The MODE2-reset + recovery-receipt teardown protocol is the
proven safety boundary, so preflight always runs the reset, and the next `experiment.py run`
is admitted whenever the immediately prior run on this boot left a valid recovery receipt
(`authorizes_launch=true`), on top of the unchanged host identity, amdgpu initialization,
capture, shutdown, and cleanup checks. A successful MODE2 reset alone does not authorize
reuse — a missing or invalid recovery receipt still refuses the launch.

The installed desktop shortcut starts the pinned inhibitor container before
preflight and holds a real logind sleep/idle block through the complete cycle,
including recovery. Normal exit, failed startup and systemd service cleanup
stop that container. No persistent development blocker is needed to start the
shortcut, and host sleep is available again after the session finishes.

The ordinary desktop card sets `session=desktop`, `startup_workload=none`,
`max_seconds=0` and `interactive_hold_seconds=0`. Only that explicit desktop
mode admits no exposure timer or session expiry. It runs until the user closes
or shuts down macOS; capture, host-fault and identity failures retain their
abort paths. Startup still skips host tests. Experiment cards remain bounded.
It waits under supervision for desktop use and shutdown without invoking a
guest probe. The shortcut also passes `--skip-tests` for the host regression
suite. Compatibility identity verification, capture, the exposure deadline,
producer quiesce and recovery remain mandatory. `DESKTOP_SESSION_COMPLETE`
records this lifecycle without claiming a functional probe pass. Experiment
cards keep the default `startup_workload=probe`.

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

A launcher failure with completely empty serial and critical captures can also
use the existing schema8 stopped-queue qualification via
`tools/cycle.py --candidate N --card metal-NNN --attempt retry --noqueue-reuse PRIOR_RESULTS`.
This names prior evidence, not an admission override: the experiment checks the
latest failed run and unchanged ledger, performs a fresh complete stable queue
scan under its locks, and binds the proof to the new manifest before reservation.
Normal receipt-based reuse still needs no option. Historical ledger launch counts
do not replace these checks. This path does not reconstruct or fabricate a missing
guest ownership lease or claim the failed guest ran successfully.

If ordinary recovery fails or ends incomplete and the guest is confirmed stopped, use the bounded
MODE2/no-queue path. Inspect first (no reset or PSP commands):

```sh
python3 -B tools/mode2-noqueue-recover.py --vm-dir ~/macos-vm \
  --run-dir ~/macos-vm/run/candidate-N-results \
  --output ~/macos-vm/run/candidate-N-noqueue-inspection.json
```

Use `--execute` with a new output filename for cleanup. It runs the existing SMU
MODE2 reset, disables the OSSSYS 5 IH DMA enables with posted readback, then
requires stationary IH pointers over five spaced samples and two complete stable scans of all 64 compute HQDs,
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

Candidate 515 and later require IH evidence in schema-9 MODE2 recovery or the
schema-10 normal recovery receipt. The independent DMA guard must release its
VFIO descriptor with a valid shutdown proof before normal recovery opens the
device. See [IH DMA lifetime repair](ih-dma-lifetime.md).

### Experimental DMCUB PSP reload

Candidate314 verifies the opt-in combination `rgpudmubreinit=1`,
`rgpudmubresume=1`, `rgpudmubpsp=1` from a checked held-reset state. It loads
signed firmware using native PSP, verifies placement within the recorded guest
TMR, initializes reserved mailbox windows and requires fresh version replies.
These arguments alone do not establish HDMI output or a general restart path.
Use the current candidate card and harness; preserve all recovery checks.
See [the firmware evidence](../findings/research/dmcub-psp-load-20260924.md).

## Physical-screen observations

Before every physical display test, run `tools/guest-display-awake.sh` **inside
macOS**, through the existing guest command relay. Keep its assertion output with
the run. Require `PreventUserIdleDisplaySleep=1` and user activity, then verify
HDMI enable and the active mode through the existing QEMU mapping. A requested
mode or online display alone does not prove that an awake stream is active.
The launchd-owned caffeinate job is bounded to6000seconds and survives relay exit;
it does not replace the harness deadline or shutdown. Repeat before a later test
if its assertion has expired. Do not interpret a sleeping display as black output.

If coordinator or recovery-tool source changes invalidate a stopped-device
receipt, rerun the same complete no-queue recovery against the latest exposed
run with a fresh output filename. The original receipt remains immutable;
success publishes a distinct requalification bound to its hash. Admission selects
the newest requalification and validates every identity, scan, teardown and
single-use check normally. An invalid newest receipt never falls back to an older
success. This does not grant reuse from a reset ACK alone.

An authorizing schema-6/10 receipt can also be upgraded through this path when
the run's recovery object matches its immutable canonical receipt and its full
original GC/SDMA/PSP proof validates against the original manifest. The tool
still performs fresh MODE2, IH shutdown and complete queue/host scans; it never
rewrites the earlier receipt or treats its missing IH coverage as a current proof.
