# Candidate385: arbitrary resize investigation (in-progress draft)

This is a partial native investigation, not an arbitrary-resize or persistence
qualification. Root owns live run `01813fa6d947219cf4c4e04f8e7592a4`.
The source/card was frozen at `2acb02a`, driver build source `41307cc`, build ID
`399fe6c3c07d4d65abecf0da412d5cf8`. Later user-space fixes are distinct from that
kernel build. Shutdown, recovery, final audio/input, and next-boot results are
pending in this draft.

## Additive installation and ownership

`run/c385-install-v2.txt` records successful addon installation and bootstrap,
without replacing or resigning the capture application. Before/after application
hash is `220903bce08c51789c3e28756ba7bc87bc7ad74ba4321c8b27ec74601833ffaa`;
capture receipt hash is
`71645d7a2815d92354b859b8ee76dba10b37a34fe1b700a14b00093490c42105`;
CDHash/designated requirement remains
`8ccc8ab340e60bc61e8cedafe53b1dd05553d4fe`. Ordinary capture resumed at 3840×2160.
This is an existing-user addon update, not a first-user consent test.

The initial agent exited on an invalid holder inventory. Actual Darwin lsof
output in `c385-inventory-probe-v2.txt` includes both `p1846` and `f3`; querying
the tty and callout together can return exit1 even with a tty holder. Separate
per-node queries return tty exit0 with that holder and callout exit1 empty.
Parser correction `c5df61c` follows this observed schema; accepting an unknown
or competing holder is not implied. The probe closed its own descriptor and
finished exit0 with empty final inventory.

## Actual manager observations

The wrapper records requested logical viewport, actual GDK scale, monitor map,
and a pixbuf ten seconds after viewport readiness. Readiness means window
allocation readiness, not guest mode completion. The broken GI primary-surface
ABI remains explicitly unavailable; monitor metadata and pixbuf dimensions are
separate observations.

| Artifact | Actual GDK scale | Requested viewports | Settled pixbuf and monitor sizes |
|---|---:|---|---|
| `c385-manager-resize.jsonl` | 1 | 1234×742, 1280×720, 1920×1080 | 1234×742, **1600×900 mismatch**, 1920×1080 |
| `c385-manager-resize-2x.jsonl` | **1** | same | 1234×742, 1280×720, 1920×1080 |

The second filename and attempted environment do not establish GDK2. Both
observed sessions used GDK1, so these are physical sizes equal to the logical
viewport, not the planned 2468×1484/2560×1440/3840×2160 comparison. The first
non-table size required a repeated request before success; a finished wrapper
record alone does not mean every requested mode matched.

`c385-agent-reconnect.txt` retains the client-disconnected event followed by
new requests and successful exact readbacks, including idempotent duplicates.
It also retains prior refusals and a zero-monitor refusal. Independent current
mode after reconnect is 1920×1080 pixels, 960×540 logical, origin0, display4128836.
The stable holder1261, presenter1336, and display4128836 in the baseline/observer
capture support in-place operation over those observations; they do not prove
all future transitions preserve ownership.

## Single new-mode failure and output attribution

`c385-newmode-observation.txt` is a direct single 2468×1484 request. It returned
status4, `passed:false`, `dynamic_mode_added:true`, with actual1920×1080.
Subsequent display observations never reached2468×1484: the owned display's
origin temporarily moved to x960, then fell back to1280×720. The display ID
remained4128836. This is a concrete failure of initial dynamic mode application,
not evidence that an error response can be treated as successful resize.
Asynchronous settings/layout settlement is the next discriminator; its fix is
in progress and not qualified by these artifacts.

`c385-resize-final-state.txt` contains delayed output from a previous observer
whose35-second duration exceeded its30-second GX timeout. Its filename must not
be interpreted as evidence from the subsequently intended command.
`c385-resize-fresh-current.txt` has independent fresh markers
`C385_FRESH_AFTER_RESIZE` / `C385_FRESH_DONE`, current1920×1080 and corresponding
presenter polling/capture dimensions. This separates the fresh check from the
stale command output.

Root visually inspected `c385-resize-desktop.png`: readable Settings application,
but large UI under actual GDK1. It establishes a visible desktop at that point,
not pointer-coordinate correctness, arbitrary resize reliability, or60Hz.

## Remaining acceptance

Require a single new non-table request to settle successfully with exact
independent CG readback and manager surface agreement. Then exercise more than
eight distinct dynamic sizes, revisit an evicted size, preserve the active mode,
and verify unchanged holder/presenter identity. Repeat actual corner/center input
and a text token after resize. Finally qualify reconnect and a subsequent guest
boot with installed startup, default application audio, and clean recovery.
No persistent arbitrary-resize milestone is claimed yet.
