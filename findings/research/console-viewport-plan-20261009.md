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
exact keyboard text and no guest screen-parameter changes. Ready snapshots also
retain partial keyboard text to verify input as it lands. Atomic ready/result files are exclusive per attempt.
Duration is bounded to10–600seconds with an independent alarm, and no successful
result follows timeout. Run as the logged-in user using a bounded LaunchAgent;
boot it out afterward and verify the normal presenter desktop remains visible.

Qualification sequence, not yet run:

1. Compile the fixture in the guest and retain source/executable hashes. Verify
   mode and display-awake assertions. Open the actual manager on the admitted run.
2. At an ordinary window size, click targets using the visible host screenshot,
   then type the fresh token into the focused fixture using actual key events.
   Do not use clipboard-based type_text: SPICE clipboard sharing is disabled. Record actual host window
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

Preparation follow-up: fixture compiles successfully with guest clang/AppKit in
355; source SHA256ad00f4a9d137f2fa6d6fed0d04bb4aedabacf7869985333f8b008eb8c527574b,
executable11047a8e328cd042982b16032ab8a313c51f84363eda365d04d71ad0602ec386.
It was not executed. Actual Computer Use window listing succeeds through KWin.
Use exact title and PID selectors: KWin window IDs exceed JavaScript safe integer
precision. Avoid clipboard-based typing in the VM; use real key events and verify
partial guest text. Native356 must first incorporate the reviewed peer-reset
shutdown correction prompted by355.
