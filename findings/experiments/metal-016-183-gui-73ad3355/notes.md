# Candidate 183 fresh GUI boot observation

This is the fresh-boot manual-visible launch using candidate 1.0.183, run ID `4661e574bbd5695d00176d85bfa87325`, boot `73ad3355-80a7-48f1-a8dd-e6f770b41de8`, and manifest SHA `b78905e67974809e085849001514a6c934d314bc43de2e0ae71a26ddc5470c11`.

QEMU was launched with `-display gtk` and the current X11 environment was forwarded. The operator verified the QEMU process and launch arguments while it was active. No screenshot, window-title query, or other direct proof of window presence was obtained, so this archive records GUI visibility as launch-enabled rather than an observed window.

The run completed through the normal harness path with verdict `INCONCLUSIVE`, earliest failure `identity_or_route_missing`, and evidence `capture_loss`. Recovery failed with a missing CR2 chunk; no recovery receipt was produced. The serial contains RGPU_CR2 records for VM faults, mode-4 entry-update telemetry, VMID2 context snapshots, submission correlation, mapping summaries, and shutdown. It contains no confirmed desktop/loginwindow marker and does not establish functional Metal acceleration. No kernel panic marker was observed in the bounded marker scan. Formal acceptance remains the harness verdict only.

Post-run host facts were preserved: same boot, `vfio-pci`, device accessible, no active VM, sleep inhibitor active, reset methods empty, and device pinned awake. No retry, manual recovery, reset, or hardware action followed.
