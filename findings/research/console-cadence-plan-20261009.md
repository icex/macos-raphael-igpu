# Bounded visible-token manager cadence probe

Offline candidate342 implementation. No guest build, GUI launch, live connection or hardware test was performed during preparation. The next native cycle must first close the controller-terminal receipt race observed during341d shutdown; this probe does not change lifecycle behavior.

## What this measures

`tests/console_cadence_token.m` draws a fullscreen borderless AppKit window on the main display without changing its mode. It requests redraws at60Hz and embeds a supplied64-bit nonce, a monotonically increasing32-bit draw ID and CRC32 in two identical binary tiles. Tiles sit64logical pixels below the top edge to avoid the menu bar. IDs count actual `drawRect` calls, not GPU presentations or scanout. Every draw and monotonic timestamp is logged. The process closes its own window and exits after the supplied1–120seconds, with a separate10second alarm margin.

`tools/console-manager-cadence.py` runs the extracted virt-manager launcher in its own process, installs a GLib sampling callback, and locates exactly one existing SpiceDisplay widget. It reads that widget's pixbuf; it does not establish a second SPICE connection. It checks magenta borders, multiple interior pixels per bit, magic, nonce, checksum and matching duplicate tokens. Native and2× scaling are supported. Backward IDs are rejected; duplicate and skipped draw IDs are recorded. Wrong geometry, partially updated or stale wrong-run content does not count as a valid token.

The default30second measurement begins on the first valid token, with a60second acquisition deadline. Every sample, error and sampling duration is retained as JSONL; the summary reports sampled unique-token rate, duplicates, invalid samples and longest observed stale interval. Sampling stops automatically; the manager window stays open and VM ownership is unchanged. Closing the viewer early yields an incomplete measurement summary.

This measures **sampled decoded-manager buffer cadence**, a sampling lower bound. It is not host compositor scanout, GPU FPS, complete delivered-frame accounting or absolute guest-to-host latency. Full pixbuf copying and synchronous sample logging impose observer overhead, especially at4K; retain actual sample durations/gaps and compare native1080p before1080HiDPI. Requested interval is not achieved sample rate. Skipped IDs may arise before capture, in transport, or simply between samples and cannot independently identify frame drops.

## Safe next-run procedure

1. Use a newly admitted supervised native cycle with display-awake assertions, correct Metal/WindowServer identity and one main capture display. Keep fixed resolution throughout each measurement. Do not launch a second virt-manager process or another viewer during sampling; an existing D-Bus manager instance could receive the CLI request and leave the instrumented process without a window.
2. Compile the guest fixture using the guest SDK: `xcrun clang -fobjc-arc -fblocks tests/console_cadence_token.m -framework AppKit -o /var/tmp/console-cadence-token`. This remains uncompiled in offline preparation.
3. Launch the instrumented viewer from the host desktop session. Use the existing private extracted package prefix and active run's socket/name. Choose a fresh nonce and new output path:

```sh
GDK_BACKEND=x11 python3 tools/console-manager-cadence.py \
  --manager-prefix /home/bogdan/macos-vm/run/c341-virt-manager/root/usr \
  --nonce 4e17f992a04b368c --seconds 30 --interval-ms 16 \
  --output /home/bogdan/macos-vm/run/ACTIVE-cadence.jsonl -- \
  --connect 'qemu+unix:///session?socket=ACTIVE_PRIVATE_SOCKET' \
  --show-domain-console 'ACTIVE_DOMAIN_NAME'
```

The wrapper uses private keyfile settings and package library/schema paths. Substitute current identities; it deliberately has no VM create, start, resume, destroy or recovery operations. Exact domain XML/identity must be checked by the outer harness as for the existing manager test.

4. Within the acquisition deadline, launch `/var/tmp/console-cadence-token 4e17f992a04b368c 60` in the **logged-in guest GUI session**. A one-shot LaunchAgent with `RunAtLoad=true`, `KeepAlive=false`, those exact `ProgramArguments`, and bounded stdout/stderr paths avoids the previous SSH/no-TTY failure. Do not use a KeepAlive restart loop. Retain both guest logs and host raw samples.
5. Confirm the summary reason is `completed`, a matching `TOKEN_DONE` exists, and inspect representative visible tokens/pixels. Preserve sampling overhead and invalid samples. Complete shutdown/recovery through the harness; no performance number overrides those gates.

## Offline validation

Six synthetic decoder tests cover valid1×/2× tokens with padded stride, wrong nonce, different valid redundant tiles, torn cell, checksum corruption and duplicate/gap/backward sequence handling. Wrapper help parses without connecting to a display. Full host suite:1113 tests pass,3 skipped (`/home/bogdan/macos-vm/run/c342-cadence-tests.log`). Live compile, placement, instrumentation and cadence results remain unqualified.
