# Candidate358: VM-only console audio qualification tools

Prepared offline; neither the guest probe nor host route/capture has been run
against a live VM or Pulse server. The guest source still needs compilation and
execution on macOS. No USB audio delivery or listening result is claimed.

The existing profile uses `usb-audio,audiodev=hda,bus=xhci.0` with a Pulse backend;
SPICE audio is disabled. This is separate from the physical330 HDMI audio result.
`guest-audio-route.swift default` uses substring selection and changes defaults;
its other non-list modes can create an aggregate. This probe does neither.

## Components

- `tools/console-audio-tone.c`: CoreAudio HAL output explicitly selects exactly
  one QEMU-manufactured USB device by supplied exact UID and two output channels.
  It generates its own CPU samples: initial silence, left997Hz, right1499Hz,
  both, and trailing silence, with ramps and0.02 peak (~−34dBFS). It runs6s,
  has a12s process alarm, disables input, closes its AudioUnit and verifies both
  default-output IDs are unchanged. No microphone, screen capture, GPU/Metal or
  default-device setter is used. Listing devices is separate from playing.
- `tools/console-audio-capture.py`: explicit opt-in host capture/restore/analyze.
  It verifies the running receipt's exact CID/start and namespace/PID/start using
  selected proc facts only, then selects one Pulse stream/client matching the
  run name, namespacePID, CID hostname prefix, QEMU binary and `hda` media name.
  Stream object serial, volume/mute, original sink identity and global defaults
  are retained and checked. PipeWire `pipewire.sec.pid` is deliberately not used
  as QEMU identity: for a Pulse client it identifies the pipewire-pulse proxy.

Capture creates a unique owned null sink and moves only that VM sink-input.
The recorder explicitly selects both the owned monitor and `--monitor-stream`
for that exact sink-input, rather than a global/default monitor or microphone.
The null sink keeps tones off the original listening endpoint. An exclusive
sink check detects foreign occupants; capture stops on route/identity/default
changes. No command sets default sink/source or stream volume/mute.

The durable route record precedes mutations. Cleanup verifies the same stream
and original sink before returning it, confirms the owned sink is empty, and
unloads only the matching owned moduleID/arguments. Lost create/move replies
are reconciled from the owned nonce/module/sink observations. Replaced objects,
foreign occupants or missing original sink fail closed and retain `route.json`
for explicit recovery; the tool does not move arbitrary streams or overwrite
concurrent user changes. Re-running `restore` is idempotent after success.
Capture duration is8–20s, with a40s main deadline and15s cleanup deadline.

## Intended owner-run sequence (not executed)

1. Compile the guest C source with AudioToolbox/CoreAudio/CoreFoundation. Run
   `--list`, pin the exact QEMU USB UID, and retain source/binary hashes.
2. Run host `capture --running <libvirt-run/running.json> --output <new-private-dir>
   --seconds 12`. Wait for `ready.json`, published only after actual monitor bytes
   and route verification. Then invoke the guest probe `--uid <exact-UID>`.
   Do not start the tone before the host has diverted and verified the stream.
3. Let both bounded tools finish. Require guest exit0/defaults unchanged and
   host route.json `restored=true`; inspect original stream/sink/defaults again.
4. Run host `analyze --output <capture.wav>`. Analysis checks the ordered tones,
   frequency peaks within5Hz, active RMS, low opposite-channel leakage, no
   clipping and inter-tone/leading/trailing silence. It preserves WAV hash and
   numerical phase evidence. A failure is not silently accepted as audio success.
5. If capture exits before successful restoration, inspect its retained state;
   `restore --output <dir>` may only restore the exact still-matching owned route.
   Missing/replaced original objects need owner review, not fallback-to-default.

These tools can establish macOS USB→QEMU→Pulse sample delivery, channel order
and bounded restoration. They do not establish physical endpoint audibility,
HDMI audio, arbitrary applications, all VM managers, or long-term audio stability.
The actual PipeWire compatibility of per-stream monitoring, guest HAL compilation,
route lifecycle and sample analysis still require the owner's bounded live test.

## Offline checks

`tests/test_console_audio_capture.py` uses a fake backend; it never invokes
Pulse or Docker. Tests cover ambiguous/replaced streams, replaced original
sink/module/VM, foreign sink occupants, lost create/move replies and exact
restoration without global/default/volume writes. Synthetic stereo WAV tests
accept the intended sequence and reject swapped/leaking/silent/noisy captures.
These tests qualify transaction and decoder logic only, not actual audio APIs.
