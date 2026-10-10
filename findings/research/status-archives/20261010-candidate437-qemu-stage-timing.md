# Live status — 2026-10-10 — 4K QEMU performance

Only full-field 4K QEMU performance is active. Keep the host viewer windowed
1440×900/GDK1, no automatic keyboard/mouse grabs or USB redirection; leave host
applications alone. Other roadmap work remains halted. Host awake blocker active.

Candidate437 / metal-231 / run649d6aba0f68c810c2a86cfbb594470d completed with
CORE_PROBE_PASS. GPU source unchanged d1deade..., source build d40ad74, build ID
b858e981c0af4fb58c982cfd5e4aa820. QEMU90328d6... adds gated pipeline timing only;
chunked-border optimization is offline and not applied. Actual source in trials
A/C stayed 1920×1080 logical /3840×2160 backing /scale2, approximately60 draws/s.

A traced Retina trial: localized56 IDs/s; full-field22.82/23.02 client IDs/s.
QEMU created/dequeued44.81–45.19 full-field commands/s with zero queue-busy skips.
Full-field mean diff0.69ms, setup/source→mirror2.15–2.18ms, mirror→bitmap/cleanup
2.06–2.07ms; refresh49/s. These overlapping wall costs include scheduling;
creation includes trace overhead. No per-frame latency or full-frame integrity
claim.71 startup-invalid tokens, zero post-start invalid, one duplicate.

C requested losslessLZ4 via native client preference; full-field23.12/23.50 IDs/s,
45-ish server commands/s, zero queue-busy skips.30 startup-invalid tokens, zero
post-start invalid/duplicates. Full-field display-channel traffic747–758MB/s.
Source spice0.16.0/server/dcc-send.cpp explicitly bypasses compression for AF_UNIX,
so a preferred codec alone is insufficient on our Unix socket. Next discriminator:
opt-in Unix losslessLZ4 with otherwise matched server/client control. No claim of
compression gain yet. B viewer enum error prevented connection; excluded.

Shutdown guest-requested exit, natural capture exits, private terminal receipts
verified; stopped-container inspection reconciliation unavailable/mismatched.
Recovery recovered/authorizes_launch=true; same-boot reuse possible. Original
runner retained. No VM currently running. Artifacts ~/macos-vm/run/candidate-437-results/,
c437-fourk-{a,c}-pipeline-analysis.json and c437-lz4-c-byte-analysis.json.

Prior scale1 controls436 and historical397/399/402/430 establish no comparable new
regression, approximately25–27 full-field client IDs/s. Traced scale2 runs are a
separate configuration. Sustained4K Retina60 delivered FPS remains unqualified.
1545 hosttests passed8skipped before437; three new analyzer tests passed afterward.
Last publisheddev e240b38... hostedCI38040411149 green; no new milestone published,
main unchanged. Native framebuffer disabled; its work remains on hold.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-438-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
