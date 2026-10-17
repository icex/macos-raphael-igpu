# Candidate361: default application audio and continuous pointer entry

Run4078e49c09b0a4fa591ca4a6df2511ca, metal-201, MODE2#297,
build1ab964d9844d4dd5aa4acd20b139d2c3, runHEAD6cdffc0. Same explicit
full-refreshON image and signedO2 presenter as358.
[Hashed artifacts](console-default-audio-input-evidence-20261009.json).

## Default application audio

Guest default and system outputs are exact QEMU USB device95 before and after;
the user-visible name is `Audio Output - Disabled`, but that name does not describe
the measured function. No device/default changes. Ordinary `/usr/bin/afplay`
plays the CPU-generated6s stereo WAV through its default output, bounded by an
inherited12s alarm. afplay exit0; no device selector or custom HAL callback.

Host capture still selects only exact VM stream/client into an owned null sink.
WAV SHA2b70ee2ac064fe2cdd8d59025849b90233ed7fba0c8cf660807c0eec317d17aa
passes left997.11Hz and right1498.53Hz, both-channel phase, silence and no clipping.
RMS about0.004333/0.004325, opposite-only channels zero. Capture/restoration exit0;
independent postcheck verifies exact original stream route/volume/mute/defaults and
owned sink/module absence. This extends358 from explicit HAL output to an ordinary
application's default output. It does not prove endpoint audibility, all applications,
audio/video synchronization, SPICE audio (disabled), or the separate HDMI path.

## Continuous pointer entry

Actual virt-manager5.1 window resizes1288x909→1000x760; guest remains1080HiDPI.
A host menu was inadvertently opened during pointer positioning, then dismissed
with Escape before guest input. Continuous relative uinput movements cross from
outside the canvas into it; the GTK trace retains enter and multiple motion events
before the first guest press. Last approach motion at66639.950837697 has widget
position78.777,82.449. First guest click is152.46,70.47 logical, inside the48px
fixture target centered153.6,86.4. All five targets and exact tokenRGPUC4DD6ED8
pass, zero misses, zero guest mode changes. Later within-canvas moves/clicks use
the Computer Use pointer path and each has real motion in the trace. Keyboard
uses bounded host uinput events to the verified focused window, not clipboard.

This positively distinguishes ordinary continuous entry from358's enter+button
without motion, which clicked the old guest position. It does not erase that
failure or prove stationary-pointer resize, all pointer backends, automatic guest
resolution following, or every window size. No driver or viewer patch was applied.

## Capture and cleanup

CORE_PROBE_PASS, earliest_failure=null. Real terminal guest-shutdown and
process_exited=true. Both capture hooks naturally complete~0.394s; critical
recv-reset remains distinct from console cleanEOF. Both hooks find completed
process state; pending-worker event wait remains native-unexercised. GPU recovery
recovered/authorizes_launch=true; viewer close preserves exact VM before harness
stop-requested. Host stays awake; no reboot/rebind.1241 host tests/8skip passed
before exposure; build/card deep validation and dry-run passed.

Next: reproducible optimized helper installation, first-use/second-boot consent
and update rollback; retain performance/atomicity and broader manager workstreams.
