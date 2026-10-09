# Bounded manager viewport/input qualification

The console has existing point/keyboard observations; these do not establish
coordinate mapping across a resized host viewport. The presenter follows guest
mode changes, but automatic host-window requests to change guest resolution are
still disabled. This test distinguishes scaling an existing desktop from changing
its resolution. It must use actual virt-manager and host input, never substitute
raw SPICE inputs_position, QMP sendkey or macOS synthetic events as viewport proof.

`tests/console_viewport_probe.m` opens a visible borderless AppKit fixture on the
current main screen, without changing modes. A fresh eight-hex nonce identifies
one attempt. It requests five cyan targets: four near corners, then center, and
an exact nonce-bearing keyboard string. Every received mouse point, expected step,
miss and timestamp is retained; completion requires all five targets, no misses,
and exact keyboard text. Atomic ready/result files are exclusive per attempt.
Duration is bounded to10–600seconds with an independent alarm, and no successful
result follows timeout. Run as the logged-in user using a bounded LaunchAgent;
boot it out afterward and verify the normal presenter desktop remains visible.

Qualification sequence, not yet run:

1. Compile the fixture in the guest and retain source/executable hashes. Verify
   mode and display-awake assertions. Open the actual manager on the admitted run.
2. At an ordinary window size, click targets using the visible host screenshot,
   then type the fresh token into the focused fixture. Record actual host window
   and decoded-surface geometry, guest ready/result, and screenshots.
3. Resize the manager smaller, repeat with a fresh nonce; then fullscreen and
   repeat. Assert guest logical/backing mode remains unchanged unless a separate
   explicit guest-mode test requests otherwise. Avoid conflating GTK requested
   geometry with observed compositor geometry.
4. Return to the original viewport, restore normal desktop, close/reopen viewer,
   and prove the exact VM remains alive. Stop only through the experiment harness;
   retain capture, terminal and recovery receipts independently.

The Computer Use backend reports host input/window targeting available; AT-SPI
connection currently fails. Screenshot-based coordinates remain possible. Verify
actual window identity and focus before any input, and do not send fixture text
if focus is uncertain. User activity or extra clicks invalidate an attempt rather
than being silently ignored. This is a bounded visual/manual-protocol test;
compilation or a narrow input result is not broad UI/application qualification.

Candidate356 is preparation only, branched from completed354. It must incorporate
reviewed355 lifecycle changes/results before any build or hardware exposure.
