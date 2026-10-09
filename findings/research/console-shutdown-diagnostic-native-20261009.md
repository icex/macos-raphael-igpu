# Candidate 396: desktop and shutdown diagnostic qualification

Run `3048b197864060d823c97e47ecd64438`, launch source `0932ba8`, MODE2 316, build identity `ea436cef094b48a7bda10a964918b5a9`. Driver behavior is unchanged from the preceding private-buffer implementation except candidate version. This is a bounded regression run, not a new rendering/performance milestone.

## Functional observations

The installed helper automatically selected snapshot presentation and obtained ACKs (`c396-state.txt`). The actual manager resized to 1440×900 (`c396-manager-events.jsonl`, `c396-post-resize.txt`), with awake assertions verified. The hardware owner visually inspected `c396-desktop.png` as a readable desktop. Closing the owned viewer left the exact VM alive (`c396-viewer-close-alive.json`). No new audio, input-coordinate, sustained-motion, or full-frame integrity qualification is inferred from this run.

## Capture and shutdown

The verdict is valid `CORE_PROBE_PASS`, earliest failure null. Recovery replay selects snapshot 9, 365 records, terminal-prefix-open tolerance, zero corrupt lines and no incomplete snapshots. That is capture evidence, not a universal claim of complete logs.

`shutdown.json` reports `exited-after-guest-request` with `private_terminal_verified=true`. The private receipt establishes guest shutdown and process exit. Both bound capture hooks report `natural-container-exit`, deferred true, approximately 0.368 seconds; console is clean EOF, critical is recv-reset. Both report `shutdown_event_wait=false` and `completed_original_zombie=false`. The retained stopped-container inspection warning is consistent with automatic container removal; it is not erased. The independent Docker event history records exit 0 without container kill/stop actions. Recovery is `recovered`, `authorizes_launch=true`.

The original-PID-running refusal did **not** occur. Consequently the added running-task diagnostics were not exercised and this run does not establish that the intermittent capture-abort race is fixed. The prior 395 shutdown-wait reconciliation and 392 forced-abort negative remain separately preserved in `c396-shutdown-reconciliation-replay.json`; original receipts were not modified.

## Scope and evidence

Host regression suite after the dev merge: 1457 tests, 8 skipped, passed. The adjacent VirtualBox configuration-dispatch experiment is software-only and separate; it does not establish a VirtualBox macOS desktop or Raphael acceleration.

The accompanying `console-shutdown-diagnostic-native-evidence-20261009.json` hashes the bounded functional, capture, lifecycle and test artifacts. Raw artifacts remain external under `/home/bogdan/macos-vm/run/`.
