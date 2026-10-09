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
Asynchronous settings/layout settlement was the next discriminator. The v3
results below supersede this initial failure for the tested single request,
while preserving this failed attempt.

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

## V3: bounded asynchronous settlement

Source `0e76973` passed the full host suite (1422 tests, eight skipped,
55.302 seconds, root receipt). `c385-stage-guest-v3.txt` records native compile
and ABI success. `c385-install-v3.txt` records successful addon installation,
bootstrap, and the same unchanged capture application/receipt/signature hashes
above. Earlier diagnostic log lines embedded before the install boundary are
not results from the new holder.

`c385-newmode-v3-observation.txt` now records a **single**2468×1484 request
returning status0, changed:true, dynamic_mode_added:true, exact physical2468×1484
and logical1234×742 at display4128836. The observation retains transient origin
and fallback behavior before settlement; its later samples confirm the requested
geometry at origin0. Holder2668 and presenter2745 are this installed version's
processes; they differ from the earlier holder/presenter because installation
restarted the owning launcher. The claim is stable ownership during the request,
not unchanged process IDs across upgrades.

The actual manager's `c385-manager-resize-v3.jsonl` requests a new1402×960
viewport and records matching settled monitor map and pixbuf1402×960. Root's
agent/input-preparation review confirms first-request success and subsequent
idempotent success. These are additional bounded native results, not yet the
more-than-eight-size eviction qualification.

## Post-resize input attempt is inconclusive

The input fixture retained `step:0` and `missed:0` in
`c385-input-inconclusive.txt`. ComputerUse reported a successful uinput click,
and a relative evdev movement/click was also attempted, but neither established
receipt in the guest fixture. The scroll tool failed because ydotool was absent
before producing input. Zero recorded misses with zero progress is **not** a
passing mapping test or proof of a guest input defect. Root explicitly stopped
its owned fixture; the final independent mode remained1402×960, logical701×480,
origin0. Prior candidate361 input qualification remains separate and cannot be
reused as proof of this new arbitrary-size transition.

## Native eviction, audio, and input isolation controls

`c385-manager-resize-lru.jsonl` has eleven completed surface records matching
all requested sizes:1402,1404,1406,1408,1410,1412,1414,1416,1418,1402,1440 pixels
wide, each960 high. `c385-lru-modeaudit.log` independently enumerates the mode
table: at most eight dynamic geometries, oldest2468×1484 evicted, then1402×960
evicted and successfully re-added. The agent's geometry mode results succeed;
count0 monitor requests remain explicit unsupported refusals and are not failed
valid-geometry applications. This qualifies the bounded eviction/revisit behavior
for that sequence, not all resize rates or all window managers.

`c385-audio-resize-result.txt` passes the isolated VM USB/QEMU/Pulse probe at
48kHz, peaks997.14 and1498.57Hz, with the opposite channel silent in the individual
channel phases. `c385-audio-restored-independent.json` independently confirms
sink, volume, mute, defaults, and removal of the owned module. This proves sample
delivery and restoration, not endpoint audibility or HDMI audio.

The input diagnosis now has a stronger control than the earlier inconclusive
attempt. `c385-continuous-input.jsonl` records actual GTK motion/buttons over
five targets, while the guest fixture remained at step0 with the resize agent
running. Root then stopped **only** exact resize-agent PID2744
(`c385-agent-stop-control.txt`). With the same viewer, holder2668 and
presenter2745, `c385-agent-off-input-result.txt` records five target hits, zero
misses and exact text `RGPU82ACD141`. This supports the agent-connected path as
the cause of missing pointer delivery in this configuration, rather than a
coordinate mapping failure inferred solely from tool reports.

The input fixture's overall `passed` remains **false**: it recorded one startup
screen notification with the same720×480 logical size and backing scale2.
Preserve that verdict. The narrower five-hit/text result is valid evidence, not
a replacement full-fixture pass. Source inspection identifies SPICE's default
agent-mouse diversion of type1 messages, for which this resize-only guest agent
has no mouse handler. An explicit `agent-mouse=off` profile is being prepared for
the next candidate; it has not been qualified by stopping the current agent.

## Remaining acceptance

The new-mode, settled manager surfaces, bounded LRU eviction/revisit, and isolated
audio controls above pass their narrow checks. Candidate385's packaged resize
agent is **not yet fully usable alongside pointer input**. Next qualify the
explicit mouse-routing correction with the agent still running, including actual
manager corner/center input and text after non-table resize. Then qualify a
subsequent guest boot with installed startup, reconnect, resize, audio, and clean
recovery. Current-run shutdown/recovery is pending in this draft; no complete
persistent arbitrary-resize milestone is claimed.
