# Live status — 2026-10-10 — full-field4K QEMU performance

Only 4K performance active; other roadmap work on hold. Host viewer stays normal,
1440×900/GDK1; no automatic input grabs or USB redirection. Host awake blocker up.

439/metal233 run0b1d233c6a38a5fa92d30e1296164cba CORE_PROBE_PASS. GPU source
unchanged d1deade..., build9020975c77324d2eb31486f8a44e9b46, MODE2334. Runtime
image085d8ac... maps exact reviewed SPICE library fde040d7...; QEMU437 unchanged.
Unix effectiveLZ4 permitted; default/OFF/other codecs remain raw. Under pinned
serverOFF configuration this is client opt-in. No broader environment pass-through.

C valid traced Retina60 /1920logical→3840backing scale2: localized55.83–56.06,
full-field23.47/23.50 client IDs/s versus44.33/43.11 create/dequeue commands/s.
48startup-invalid,0post-start/duplicates; full-field queue-busy91/109. Native live
client request supported (preference cap true), bytes~195MB/s versus prior raw
~747MB/s. This does not materially improve full-field delivery or identify actual
wireLZ4 versus losslessLZ fallback. Stored session preference alone is not receipt.

D untraced rawX11, with45s userspace profiler: full-field27.04, localized55.68/56.02.
E untraced rawWayland: full-field24.39, localized54.44/55.14. Both60s observations,
actual Retina geometry/source60,0post-start invalid/duplicates; short final phases
excluded. Sequential host activity/profile differences prevent regression/gain
claims. Backend switch did not solve sustained60. Perf exact ELF/raw offsets
retained; original function names wrongly resolve libc and are excluded. Mixed
sample attribution shows QEMU main Pixman stores/comparisons and vCPU copying,
not proof of CPU saturation or downstream cause.

Full3840×2160 RGB comparisons: controlled color pattern and dedicated high-entropy
pattern exactly match stable QEMU before/after snapshots (8,294,400pixels each).
High-entropy center4095unique/4096pixels, stddev~74 eachchannel. This qualifies
server→client RGB for those static images, not guest→capture, alpha, moving-frame
integrity, physical scanout or GPUFPS. The first late entropy attempt captured
ordinary desktop instead; explicitly excluded from high-entropy qualification.
A window-lock attempt and B API-name/no-source diagnostic yield no throughput.

Guest-requested shutdown, natural capture exits, private terminal verification;
stopped-container inspection reconciliation unavailable/mismatched retained.
Recovery recovered/authorizes_launch=true. No VM running, original runner preserved.
Artifacts ~/macos-vm/run/candidate-439-results/,c439-fourk-c-pipeline-analysis.json,
c439-fourk-{d,e}-analysis.json,c439-static-stage0-check.json,c439-entropy-check.json,
c439-lz4-c-byte-analysis.json and retained raw/ELF/profile provenance.

Next discriminator: QEMU gui_update schedules the next refresh from completion,
adding work to16ms interval (observed~49full/~58local). Test callback-start pacing
with skipped missed ticks and a conservative17ms SPICE60 period so no configured
rate is exceeded. Exact60 will require finer-resolution/fractional scheduling if
this is useful. It remains a hypothesis, not a fixed display or achieved target.
1552hosttests8skip,25upstreamSPICEtests passed before439. No new milestone published.
Last dev e240b38... has green hostedCI38040411149; main unchanged. Sustained4K60
remains unqualified. Native framebuffer/120/5K work remains disabled/on hold.
