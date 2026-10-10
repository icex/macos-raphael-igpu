# Live status — 2026-10-10 — 4K QEMU performance

Only full-field4K performance active; keep host viewer normal1440×900/GDK1,
no auto input grabs/USB redirection. Other roadmap work halted. Host awake.

438/metal232 run683a808b91d8c4fa8655e0b3f6077eea CORE_PROBE_PASS, sourceGPU
unchanged d1deade..., build4de0edff55ad4cdb9543eeac776c0f96. Image646b5fc... rebuilds
matchingSPICE0.16.0 with environment-gated Unix LZ4 research support.25 upstream
tests passed for baseline and patched;1550hosttests passed8skipped before run.

A explicitOFF control, Retina1920×1080logical/3840×2160backing scale2/source60,
normal1440×900GDK1: localized55.83–56.30, full-field22.89/22.75 clientIDs/s versus
45.79/45.51 QEMUcreate/dequeue commands/s.0 queue-busy skips.38startup-invalid,
0post-start-invalid,1duplicate. Raw behavior reproduces437 traced controls.

B intendedLZ4 trial excluded: viewer geometry changed2160×1381 after readiness,
observer stopped sampler-error before valid token. Owned viewer/source stopped.
Runtime QEMU environment receipt shows RGPU_SPICE_UNIX_LOSSLESS MISSING despite
imageENV=1: libvirt sanitizes its environment. Thus438 never exercised compression,
and its bytes/performance cannot qualify LZ4. No pixel-integrity trial performed.
Next: use explicit clientLZ4 preference itself as the narrow research opt-in,
keeping all other Unix preferences raw; retest same compiled server OFF/LZ4.
No broader environment passthrough or host safety changes are needed.

Guest-requested shutdown, natural capture exits, private terminal verification;
stopped-container reconciliation inspection unavailable/mismatched retained.
Recovery recovered/authorizes_launch=true. Original runner preserved. No VM up.
Artifacts ~/macos-vm/run/candidate-438-results/,c438-fourk-a-pipeline-analysis.json,
c438-qemu-spice-runtime-env.json and c438-fourk-b-cadence.jsonl.summary.json.

Sustained4K Retina60 deliveredFPS remains unqualified. No comparable historical
regression established. No new milestone published; dev e240b38... CI38040411149
green, main unchanged. Native framebuffer investigation remains disabled/paused.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-439-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
