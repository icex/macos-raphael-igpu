# Candidate 443: moving GL output holds; start-relative pacing adds refreshes, not delivery

Only full-field 4K performance is active; other roadmap work stays on hold. The host
viewer was a normal 1440x900 window (GDK1, X11) throughout, with no fullscreen, input
grabs or automatic USB. The host awake blocker was retained.

## Setup

Build `bd869353edd843aebb3b2edfd3728a6b` (1.0.443, card metal-237), GPU source digest
`d1deade…` unchanged. Same boot `ba51b3c6…` as 441. 442 was paused by the user during boot
before any viewer or source ran; 443 carries its mapped GL-token decoder forward.

Client: exact 441 private spice-gtk 0.42 raw-primary GtkGLArea prefix (`RGPU_RAW_TEXTURE=1`,
raw transport, loaded libraries verified from `/proc/<pid>/maps` each window). Source:
Retina 1920x1080 logical / 3840x2160 backing, ~60 draws/s, mixed 20 s localized/full-field
phases. Three cycles, A-B-A, each with a fresh MODE2 reset (338-340):

| Cycle | Server image | Pacing | Run |
|---|---|---|---|
| a | 439 `085d8ac…` | default completion-relative | `b45679d76040a93ce89b15b4be3951ee` |
| b | 440 `8f4271b…` | 17 ms callback-start | `7d4fec2b2d4ed596e28e261377d8a6ef` |
| c | 439 `085d8ac…` | default completion-relative | `5fa9236a4d79c40e45c851a41e130f49` |

## 1. Moving GL-output integrity (diagnostic, excluded from performance)

Per cycle, 100 readback requests of the actual GtkGLArea FBO while the moving token source
ran, decoded with `tools/console-gl-token.py` (paired nonce/CRC tokens at mapped samples).
Geometry was checked first: primary 3840x2160 uncropped, FBO 1440x900, content 1440x810 at
y=45, GL child active.

All three cycles: 100/100 completed, 100 valid, 0 invalid, 0 missing, 100 distinct strictly
increasing sequences. That is 300/300 valid sampled frames. Scope: sampled moving frames carry
the correct fresh token at mapped positions after GPU scaling. This is not every-frame integrity,
text or filtering quality versus Cairo GOOD, or a displayed-FPS measurement.

During the moving windows the client logged ~56-60 GL renders/s in localized phases and ~35-42/s
in full-field phases (`RGPU_RAW_GL timing`); these are renders issued, not scanout.

## 2. Coordinated performance: GL default vs start-relative

The viewer started first and was confirmed stable at 1440x900 for 5 s; then a 120 s source started
(the source binary accepts at most 120 s). The 100 s observer window starts at the first valid
token, so it ended ~18 s before the source in every cycle (`TOKEN_DONE` captured each time). Readback
was off. The standard pipeline analyzer accepted all three records without the source-overlap
workaround 441 needed.

Full-field phase interiors (client unique decoded IDs/s · server command dequeues/s · refresh/s):

| Cycle | Pacing | Phase 1 | Phase 3 |
|---|---|---|---|
| a | default | 41.77 · 41.77 · 48.0 | 41.45 · 41.51 · 47.9 |
| b | start-relative | 39.40 · 41.40 · 58.1 | 37.83 · 40.78 · 58.2 |
| c | default | 38.61 · 38.84 · 46.8 | 39.44 · 39.66 · 46.9 |

Localized phases were 56.1-57.0 IDs/s in all cycles. Queue-busy was 0 everywhere.

Findings:

- **The 441 GPU-scaling gain repeats.** Default GL full-field is 38.6-41.8 IDs/s in two cycles,
  versus 441's same-boot Cairo 23.7-23.9, with clean source-overlapping windows.
- **Start-relative pacing is not a material delivery gain with the GL client.** It raises
  full-field refresh from ~47-48/s to ~58/s, but dequeued commands stay at 40.8-41.4/s (default
  38.8-41.8) and client IDs are 37.8-39.4/s, inside or below the default range. The a-to-c drift
  between the two default cycles (~2-3 IDs/s) is as large as any arm difference.
- Under default pacing the client keeps up with the server (client ≈ dequeue within 0.25/s).
  Under start-relative pacing the client trailed dequeues by 2-3/s; this is one cycle and is
  recorded, not explained.
- **The remaining full-field ceiling is upstream of the client and of the refresh timer**: ~40
  commands/s are dequeued regardless of 47 or 58 refreshes/s. Mean server create cost was
  3.7-5.5 ms per full-field update (mirror 2.2-3.0 ms, bitmap 2.3-2.7 ms).

Not established: sustained 4K60, displayed-frame FPS, whole-frame motion integrity, input/cursor/
crop/resize/fallback behaviour with this renderer, or the cause of the refresh-to-command gap.

## Lifecycle

All three runs: `CORE_PROBE_PASS`, `exited-after-guest-request`, natural console/critical captures,
private terminal verified, the known "stopped container inspection unavailable or mismatched"
reconciliation warning retained, recovery `recovered` with `authorizes_launch=true`. Guest test
jobs removed after each window; VM and viewers gone afterwards.

Operator error, set aside: cycle a's first performance window requested a 165 s source. The
binary rejects anything over 120 s (exit 2, empty log), so the observer saw no valid token. It is
kept under `run/c443-a-void-perf1/` and is not a measurement.

## Next discriminator

Find where full-field refreshes fail to become commands. Compare per-phase guest presenter
publications (sealed presenter log) with QEMU dirty-region/command creation at the same timestamps.
That shows whether the ~40/s ceiling is the guest's full-field publication rate or QEMU's
update-to-command path. No further pacing work is justified by this data.

Evidence: [console-gl-pacing-evidence-20261010.json](console-gl-pacing-evidence-20261010.json)
(per-cycle phases, readback counts, lifecycle, artifact hashes); `~/macos-vm/run/c443-*`,
`candidate-443{,-attempt-start-b,-attempt-default-c}-results/`; operator files in the
candidate-443 `.research/` (driver `c443-drive.py`, managers, plists).
