# Candidate 383: native SPICE agent transport and bounded existing-mode resizing

Final idempotent-agent run passes; VM lifecycle receipts remain pending. Candidate384
contains the offline diagnostic helpers exercised inside the root-owned383 VM;
this is not a separate384 hardware launch or an installed persistent resize agent.

## Identity and transport

Native run `c23d74d98b192d4a33a08376d9a64811`, driver1.0.383, build
`42a989b30403424e97098f562d46651e`, source
`777bf28521f2acdf5eeabb9fd9dc619ac0a3e9af`, executable SHA-256
`23562757b59cdd0b75a177caf49211cf688584bc780f744d2a85953673db73d8`.
Actual launch agent-channel arguments and both capture UARTs were validated after
the supervisor argument-verification correction. No snapshot lease was armed;
ordinary presentation and existing capture consent were retained.

`c383-guest-inventory.txt` shows an active AppleVirtIOConsole service, active
IOSerialStreamSync child with AppleVirtIOAgentDevice=true/namecom.redhat.spice.0,
and active IOSerialBSDClient exporting tty/cu aliases. This is live attachment,
not just a matching personality. Root inspected holders before the probe.
`c383-port-probe.txt` runs as UID501, opens only the exact tty, requests TIOCEXCL,
and proves an independent nonroot second open returns EBUSY(16). It reads/writes
zero device bytes and exits0; post-close lsof reports no holder. The result does
not independently exclude a pre-existing privileged owner or prove cu-alias
exclusion.

`c383-handshake.txt` records a successful zero-feature capability exchange with
the actual manager connected: RX36/TX72 bytes, one request1 capability announcement
with word217207 after the initial request write, request0 response sent, no
residual parser bytes, exit0 and no holder after closing. This proves compatible
bidirectional transport, not nonce-authenticated freshness, clipboard or resizing.

## Controls and bounded-agent mistakes retained

The first observe-only agent accepted capability traffic but refused the
zero-monitor8-byte and single-monitor32-byte requests under the original strict
28-byte parser. The corrected parser recognizes count1, flags0..3 and exact28/32
lengths; physical millimeter hints are recorded and explicitly ignored. Unsupported
count/depth/layout/geometry still replies ERROR. No unsupported display creation,
input, clipboard or DPI feature is advertised or performed.

The initial observe run ended with the whole-agent TimeoutError rather than a
normal finish. Its descriptor closed. The revised loop reserves1second cleanup,
keeps the original hard deadline, and refuses fresh work after a late select wakeup.
A later60second session run emits a bounded finish at59.048seconds; scheduling
rounding is a hypothesis for the original timeout, not a measured root cause.

Root initially used `launchctl submit`, which restarted the bounded diagnostic and
left the port busy. This was an orchestration mistake, not evidence of a driver
leak. Root removed only the owned submitted jobs; `c383-monitor-submit-removal.txt`
records empty tty/cu holder scans. Subsequent runs use explicit one-shot LaunchAgent
plists. No arbitrary existing guest agent was stopped to obtain ownership.

## Helper lifetime and session mode changes

The initial helper called CGDisplaySetDisplayMode and verified its immediate
readback. Apple's documentation makes that setter application-lifetime scoped;
a short-lived successful setter is not sufficient persistence evidence.
[Apple setter documentation](https://developer.apple.com/documentation/coregraphics/cgdisplaysetdisplaymode(_:_:_:))

Importantly, `c383-mode-old-setter-control.txt` still reads2560×1440 in an immediate
independent process after the old setter exits. It therefore does **not** prove
an immediate revert. Earlier presenter and viewer dimensions drifted away from
requested modes; those observations do not isolate reversion timing or rule out
other display/mirroring interactions. Later independent current-mode output in
`c383-monitor-session-bootstrap.txt` returns1280×720, establishing eventual drift,
but not attributing every transient to setter exit. Also the artifact named
`c383-mode-lifetime-control.txt` raced a source copy: its recorded SHA9968f167…
is the **session** helper, not the old setter. Classify by source hash, not filename.

The replacement configures only the unique vendor0x5250/model0x3453 display using
Begin/ConfigureDisplayWithDisplayMode/CompleteForSession, cancels on configuration
failure, and verifies physical width/height, mode ID, target identity and origin0.
It creates no display and changes no other display's origin or mirror relationship.
Session lifetime follows the documented
[kCGConfigureForSession contract](https://developer.apple.com/documentation/coregraphics/cgconfigureoption/forsession).

`c383-monitor-session-mid.txt` records actual manager requests for2560×1440 and
3840×2160, matching helper results at logical1280×720/1920×1080 respectively.
Presenter logs independently show2560×1440 copies, capture_resize3840×2160 and
subsequent3840×2160 copies. Independent --current reads3840×2160 after setter exit.
Root reviewed `c383-resize-session.png` as a readable actual-manager desktop.
This qualifies a bounded existing-mode request path, not arbitrary resize or a
frame-rate/continuous resize-stability result.

The first session variant still reconfigured duplicate exact-mode requests and
three helper calls timed out at5seconds. These ERROR replies remain in the record;
three other applications succeeded. The corrected helper compares current mode
ID, physical geometry, origin and identity, skips redundant transactions, and
still performs fresh readback. The final40second native test now passes:
`c383-monitor-idempotent-complete.txt` finishes normally at39.028seconds, exit0,
seven monitor requests/five verified applications, no TimeoutExpired, and no port
holder after exit (TTY_HOLDERS=1 is the lsof exit status, not a holder count).
The two refusals are a zero-monitor configuration and an initial rate-limited
duplicate. Successful redundant requests report changed=false; actual transitions
report changed=true. There are no pending transmit/parser bytes at finish.

`c383-manager-resize-idempotent.jsonl` confirms actual manager logical allocations
1280×720 then1920×1080 at GDK2. After each10second settle, both monitor-map and
pixbuf area dimensions are respectively2560×1440 then3840×2160. Metadata at the
initial viewport-ready events still reflects the preceding guest mode, which is
expected asynchronous ordering and is retained. Independent guest current mode
and later presenter polling remain3840×2160 after agent exit. Primary C-struct
metadata remains unavailable rather than fabricated from the broken GI fields.

## Invalid GI primary metadata is not surface evidence

`c383-manager-resize-session.jsonl` contains invalid get_primary field values.
Installed spice-gtk0.42 GIR declares the format enum as a pointer, although the C
ABI uses a4-byte enum. For example16492674416672 equals(3840<<32)|32: the reported
format combines real width and format, shifting subsequent reported fields.
These records cannot qualify independent primary geometry. The new wrapper
removes that GI call and explicitly reports primary unavailable due to ABI mismatch.
Monitor-map metadata remains separate. get_pixbuf copies the selected canvas area
without viewport scaling, but earlier1280×720/5120×2880 area observations do not
alone establish correct end-to-end source geometry. No pointer arithmetic repairs
are presented as independent evidence.

## Audio and restoration

The first audio capture returned exit1 during cleanup, with `owned sink still
occupied` and restored=false. Root performed an explicit owned-route restoration
retry; `c383-audio-restored-independent.json` verifies sink, volume, mute, defaults
and module removal. This initial cleanup failure is not relabeled a first-pass
success.

The guarded reconciliation retest passes capture exit0,48kHz stereo997/1499Hz,
zero opposite-channel RMS, and independent route/volume/mute/default/module cleanup
checks. See `c383-audio-reconciliation-result.txt` and its independent JSON.
Scope is USB/QEMU/Pulse sample delivery, not endpoint audibility or physical HDMI.

## Remaining boundaries

Final idempotent-agent result and post-agent holder scan pass. Ordinary desktop
close and VM terminal/capture/recovery receipts remain pending. No permanent installer,
login-agent integration, arbitrary resolution creation, multi-monitor placement,
stationary-pointer resize or new input/60Hz qualification is claimed. Physical330
HDMI evidence is separate. Hosted CI for dev447131e is green; that does not qualify
these later candidate384 edits or this run's broader desktop acceptance.
