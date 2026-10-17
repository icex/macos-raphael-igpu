# Audio dropout revalidation — 2026-10-15

The earlier release-513/514 report described 22 silent seconds during a
30-second 3840×2160/120 Hz three-window stress, with a guest 440 Hz `afplay`
tone and host PipeWire sink capture. Its reported isochronous packet rate and
zero drops measured packet timing/length, not sample amplitudes. The raw WAV
from that report is unavailable in the retained VM tree, so its timing and
sample path cannot be reanalysed. No audio implementation change was made in
release 515. The v19 QEMU image adds the VFIO DMA lifetime guard to the prior
display/audio image; these checks do not identify why the earlier symptom
occurred.

## Current controlled repeats

All runs used the installed release-515 `metal-321` guarded launcher on host
boot `ee006810-2a60-4378-b4de-8d673b8c3f00`. Host audio was recorded with
`pw-record` from the selected Navi HDMI/DP sink monitor at 48 kHz, 16-bit
stereo. A 1 ms window counted as silence below 30% of the steady tone RMS.
The QEMU stream node itself was not used as the recording target.

| Attempt | Playback and load | Captured result | Lifecycle |
| --- | --- | --- | --- |
| `d20261015135005` | One `afplay` tone; 30 s three-window stress at 4K/120 | Clean 70 s single-source capture, zero silent 1 ms windows after startup; 120 fps QEMU/macOS | CORE_PROBE_PASS, native exit, guard released, schema-9 recovery authorized |
| `d20261015140130` | One 300 s `afplay` tone; 240 s three-window stress at 4K/120 | 289.98 s capture, zero silent 1 ms windows after startup; 440 Hz dominated all 281 measured one-second active windows; mean 119.7 fps QEMU/macOS | Same native/guard/recovery result |
| `d20261015141057` | Foreground Cocoa `AVAudioPlayer` window; 60 s three-window stress and 20 alternating QEMU host-window resize requests at 4K/120 | 99.97 s capture, zero silent 1 ms windows after startup; mean 120 fps QEMU/macOS | Same native/guard/recovery result |

The first session also had a clean 5K/120 tone/window stress and a 5K/120
host-window resize repeat. An overlapping-tone 4K trial is retained but is
not used as clean playback evidence. QuickTime could not be tested: its open
dialog blocked automation, and the trial app was closed without claiming
playback. In the third session the custom Cocoa player started without a
dialog and produced a host sink signal before load. Its source and WAVs are
kept only under `~/macos-vm/run/audio-diag-20261015/`.

The 300 s capture, WAV SHA-256 and exact silence counts are in
`soak-515/analysis.json`; presentation counters are in
`soak-515/window-stress.json`. The corresponding foreground artifacts are in
`foreground-515/`. Product run verdict, shutdown, guard and separate recovery
receipts are in `~/macos-vm/run/candidate-515-attempt-<attempt>-results/`.
All three runs left only the idle inhibitor running; GPU binding, power pin
and host KVM settings were unchanged.

## Interpretation and limit

The previously reported dropout did not reproduce in those bounded synthetic
tests. Their X11 resize requests took effect nearly instantly and did not
represent the user's gradual side drag. The manual reproduction below
supersedes any inference that audio is stable under window resizing. The
layer dropping samples remains unidentified. Existing USB packet counters
measure packet timing and length, not payload amplitudes.

## Manual reproduction after the controlled repeats

The user reported Safari audio hanging for about one second on fast scrolling
and worse audio when slowly dragging a QEMU window edge for 2–3 seconds. The
automated X11 resize script also temporarily made the guest cursor invisible;
the cursor returned after the script stopped.

In installed-515 attempt `d20261015142454`, the user performed manual edge
drags while Safari played. The host sink WAV
`~/macos-vm/run/audio-diag-20261015/manual-slow-515/sink-monitor.wav` contains
near-silent intervals of 1.98 and 2.00 seconds aligned with size changes in
`window-geometry.csv`. Safari media can itself contain silence, so this alone
does not identify the audio layer. The user then paused Safari audio and
repeated the action while one 440 Hz `afplay` source played. Its separate
144.99-second sink capture in `manual-tone-515/` has exact digital zeros in
several intervals, including two of 1.99 seconds. The first begins at about
11:33:21.465 UTC, 0.084 seconds after the first logged geometry change. The
guest `afplay` process remained alive; the user heard the tone stop. Fast
Safari scrolling did not interrupt the tone in that pass. Guest display
remained at 3840×2160 backing / 120 Hz after the resize.

QEMU's preexisting `buffer empty` counter advanced at ~100 callbacks per
second before the drag but at 21–56 per second during its worst interval.
This is consistent with a main-loop stall, but the counter is cumulative and
does not show USB payload amplitudes or identify the blocking call. A
diagnostic QEMU build now logs those amplitudes, callback gaps and GTK EGL
flush durations; it is not an audio fix. Its local patch and build artifacts
are in `~/macos-vm/run/audio-diag-20261015/`. The current run's normal guest
shutdown, guard release and separate schema-9 recovered/authorizing receipt
are in `run/candidate-515-attempt-d20261015142454-results/`.

## Instrumented manual drag

Attempt `d20261015144021` used a local image of the same QEMU v19/guard
source with diagnostic logs only. The 5K/120 guest again played a single
440 Hz `afplay` tone, and the user dragged the QEMU window side. The host
sink WAV has 2.477 seconds of near-zero audio starting about 11:45:31.655
UTC. QEMU logged 1000 nonzero USB packets/s before the drag, then a 2012 ms
gap and very few nonzero samples. Its audio callback still ran with an empty
queue, though gaps of 30–146 ms appeared. The guest's `coreaudiod` log at
14:45:31 local time records missed deadlines and safety overload, an
AppleUSBXHCI isochronous enqueue failure, and USB audio-engine stop/restart.
These are in `instrumented-515/qemu-timestamped.log`,
`guest-audio-resize.log`, `window-geometry.csv` and `sink-monitor.wav`.

EGL swap blocked for 0.8–1.0 s during early desktop startup, but the
11:45:31–34 audio gap has no comparably long logged swap. That prevents
attributing this dropout to one EGL swap call. Frequent resizing may still
deprive QEMU/guest audio work of its deadlines; the initial scheduling cause
is not yet proved. The desktop remained responsive; the hardware-cursor
overlay disappeared after the manual resize. No scripted window resizing ran
in this attempt. The run ended with requested native guest exit, schema-2
guard release and separate schema-9 recovered/authorizing receipt in
`run/candidate-515-attempt-d20261015144021-results/`.

## Failed 200 ms presentation hold and cursor evidence

Attempt `d20261015145005` used local image `rgpu-qemu:c516-resize-hold`,
derived from guarded QEMU with a 200 ms display presentation hold after UI
size changes and a forced cursor import on resume. The user again slowly
dragged the QEMU window side. The 440 Hz tone still had 0.880 s and 2.004 s
exact-zero intervals and the QEMU USB packet log had a 2009 ms gap. The first
hold began at 11:53:50.180 UTC, after the critical gap had started. This
rejects the UI-notification hold as a sufficient audio fix. The cursor also
disappeared, so forced reimport did not solve that bug. Artifacts are under
`~/macos-vm/run/audio-diag-20261015/resize-hold-515/`.

While the cursor was invisible, read-only inspection of QEMU's `rgpu-display`
memfd showed metadata `enabled=1`, 256×256 with nonzero alpha pixels and a
plausible position. The missing pointer is downstream of the guest's shared
cursor buffer. QEMU GTK sets a blank host cursor for absolute input and
relies on its own cursor overlay. A host cursor fallback is a candidate,
not a proven resolution. The supervised launcher then requested shutdown;
the run exited with CORE_PROBE_PASS/returncode 0, guard release and a separate
`recovered/authorizes_launch=true` schema-9 receipt in
`run/candidate-515-attempt-d20261015145005-results/`.

## Fitted window, visible cursor, and priority discriminator

Attempt `d20261015145931` used a local diagnostic QEMU image with a one-time
guest-resolution window fit capped by GDK's monitor work area and a host
cursor fallback. At the 5120×2880 desktop mode QEMU chose a 3608×2064 window
inside the 7584×2112 work area. The user confirmed that it fit and that the
pointer remained visible after a slow side resize. These are positive results
for this local image only; it has not replaced the installed release.

The same slow drag still stopped the tone. The host sink WAV has exact-zero
intervals near 2 s beginning about 12:13:26.331, 12:13:28.830 and
12:13:33.739 UTC. QEMU logged guest USB packet gaps of 1997–2027 ms. The
guest log contains `coreaudiod` missed deadlines, AppleUSBXHCI isochronous
enqueue failures and repeated audio engine restarts.

Host Ananicy applies its packaged `Heavy_CPU` rule to `qemu-system-x86_64`:
nice 9 and best-effort I/O priority 7. A one-time process-only renice to 0
was later reset by Ananicy. A bounded privileged-container command then kept
only this owned QEMU process and its threads at nice 0 during the actual drag;
its per-step log is in `nice0-fit-cursor-515/priority-maintenance.log`. The
same packet gaps and exact-zero audio persisted. Per-thread schedstat during
12:13:26–37 showed less than 11 ms per second of combined vCPU runnable wait
and less than 2 ms per second of main-thread runnable wait in most seconds.
This rejects nice 9 as a sufficient explanation. It does not identify the
guest scheduling or xHCI fault. No host policy or KVM setting was changed.

The launcher requested shutdown, QEMU exited with CORE_PROBE_PASS/returncode
0, the schema-2 guard released, and the separate schema-9 MODE2/no-queue
receipt recorded `recovered/authorizes_launch=true` in
`run/candidate-515-attempt-d20261015145931-results/`. The user subsequently
made slow-resize audio lower priority and asked to focus on Safari scrolling
and more critical guest application activity.

## Safari fast scrolling versus Picture in Picture

Installed-515 attempt `d20261015151631` used the local fit/cursor diagnostic
image at 5120x2880/120 Hz. The user reproduced YouTube music stutter while
fast-scrolling the normal Safari page. The quiet 997 Hz `afplay` pilot was
inaudible beneath the music to the user, but its spectral amplitude persisted
through the reported stutter in the host sink capture. QEMU's USB audio packet
stream remained near 1000 packets/s with no matching long transport gap.
This separates the Safari media symptom from the guest-wide USB audio halt
observed during slow QEMU-window resizing.

Guest unified logs from 15:21:15–50 show the same WebKit media player changing
`setViewportVisibility` 17 times as the video moved into and out of view,
20 `flushVideoIfNeeded` calls, 13 renderer `stall` calls and repeated
`AudioQueuePause`/`AudioQueueStart`. One sequence begins at 15:21:20.188 with
`IntersectingViewport`, `flushVideoIfNeeded layerRequiresFlush:true`, renderer
stall and `AudioQueuePause`; at 15:21:20.282 it became `NotVisible`. This
repeated during the user's fast scroll. The WebKit GPU process reached 172%
CPU in one sample while guest `coreaudiod` stayed low. These are correlated
events, not proof of why WebKit chose to tear down or flush the renderer.

The user then placed the same video in Safari Picture in Picture and
fast-scrolled the same page, reporting no stutter or audio halt. The PiP
transition is logged at guest 15:26:08.628 as `VisibleInPictureInPicture`.
There are no later viewport/flush/renderer-stall/AudioQueuePause events for
that player in the captured 15:26:08–35 interval. Earlier entries in that
PiP capture include the transition and other media players, so whole-file
event counts cannot be compared directly with the normal-scroll interval.
The user comparison and same-player timeline support a visibility-triggered
Safari playback interruption. The current WebKit source has a visibility
path that can change renderer acceleration and flush video on re-entry;
the installed Safari binary has not been matched to that exact source
revision.

In the next supervised run, the user played the same YouTube video in Brave
and fast-scrolled the page for 20–30 seconds without stutter. This is a
listening observation, without a synchronized Brave audio capture. It makes
a general guest audio-transport fault less likely for this workload, while
leaving Safari's exact trigger and other apps unqualified. The user classified
the Safari fast-scroll symptom as a known low-priority issue. Picture in
Picture or Brave are observed working paths for the tested page.

Artifacts: `safari-scroll-515/{sink-monitor.wav,qemu-timestamped.log,
guest-procs.log,guest-webkit-scroll.log}` and
`safari-pip-515/{sink-monitor.wav,sink-monitor-2.wav,
guest-webkit-pip.log,qemu-timestamped-2.log}` under
`~/macos-vm/run/audio-diag-20261015/`. Supervised shutdown was normal:
wrapper CORE_PROBE_PASS/returncode 0, schema-2 guard released, original
recovery incomplete, separate schema-9 MODE2/no-queue receipt
`recovered/authorizes_launch=true` in
`run/candidate-515-attempt-d20261015151631-results/`. No QEMU remains and
`power/control=on`.
