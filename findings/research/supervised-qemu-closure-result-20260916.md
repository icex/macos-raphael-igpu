# Supervised QEMU closure — 2026-09-16

Run `042d7770f42059319cda491e50396bd8`, candidate280/metal-128, MODE2#161,
twentieth exposure on boot `2508eb6d-ddf3-497d-9774-00a7ecebe3ed`.
Results: `/home/bogdan/macos-vm/run/candidate-280-attempt-closure-results`.

- Functional: existing desktop validator passes the nonce-bound probe; all reported
  render/readback mismatch counts are zero. This is not physical display proof.
- Action: supervisor HMP quit, exact CID/start and manifest bound; receipt confirms
  stopped. Shutdown receipt says already-stopped. This was not clean guest shutdown.
- Capture: strict classifier rejects an incomplete transport line in snapshot14.
  Recovery's existing terminal-prefix-open policy independently authenticates complete
  snapshot13, 374 records, zero corrupt lines. No classification relaxation was made.
- Recovery: schema6 recovered/authorizes_launch=true; five active queues dequeued,
  zero dequeue timeouts/forced clears, active_after=0, CP_STAT=0. Stale graphics
  ring retired through host KIQ (fence confirmed), graphics proof complete.
  Recovery kernel_messages is empty; full host journal retains network messages.
- Overall: INVALID, identity_or_route_missing/capture_loss, termination because exact
  supervised container stopped. Positive cleanup evidence is separate from qualification.

Before action, the supervisor check was corrected to read the real transport envelope:
exact result nonce, successful result, device, transport and exit marker. Original
synthetic fixture had an incorrect top-level passed field. 948 host tests pass (3 skipped),
including refusal of unbound/failed probe envelopes. Driver/QEMU binaries unchanged.

Next discriminating observation: fresh MODE2 plus ordinary desktop/core probe and
clean guest shutdown after this abnormal closure. Guest panic, command-channel failure,
repetition and independent host boots remain open.
