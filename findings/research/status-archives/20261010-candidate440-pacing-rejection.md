# Live status — 2026-10-10 — full-field4K performance

Only4K performance active, all other roadmap work on hold. Host viewer remains
normal1440×900/GDK1, no input grabs/automaticUSB. Awake inhibitor remains active.

440/metal234 run7735f915a55c10b180a6960fe8aeb5b4 CORE_PROBE_PASS, MODE2335,
build9cfef702a0db4472b509e1c69f2f8a63, unchanged GPU source d1deade.... Image8f4271...
adds bounded17ms callback-start pacing; same439SPICE, explicit rawOFF client.
Actual Retina1920logical/3840backing scale2/source~60,100s normalX11 viewer.

Pacing raised full-field refresh49→58.07/58.13 attempts/s, but creation/dequeue
44.26/44.10 and client21.94/21.88 IDs/s stayed limited. Localized55.58–56.26,
0queuebusy,13startup-invalid,0post-start-invalid,1duplicate. Timer scheduling is
not the dominant delivery fix;17ms is not exact60. No regression claim from this
sequential traced comparison under uncontrolled host activity. No pacing release.

439 verified native RGB pixel equality for static color/noise frames; compression
reduced bytes but no material cadence gain; Wayland alone no fix. Historical380
software evidence strongly links scaled Cairo cost with upstream pending opaque
replacement: 4K one-to-one draw1.70ms/42.55client vsscaled48.75ms/15.40client.
Different geometry/workload/transport prevents importing those rates as native.
Actual observed pixman sse2_blt preserves all4bytes; no X normalization in that path.

Next: independent optional raw-primary GtkGLArea renderer for hostGPU scaling,
retaining CPU decoded primary/ROI/get_pixbuf and original session/input/USB. The
existing DMABUF/EGL path cannot just be enabled for raw surfaces. Must qualify GL
output colors/orientation/crop/resize/fallback, not only CPU tokens. Preserve full
4K source and quality; no lower-resolution or nearest-filter substitution.

Guest-requested exit/natural captures/private terminal verified; stopped-container
inspection reconciliation unavailable/mismatched retained. Recovery recovered,
authorizes_launch=true; no VM running, original runner preserved. Artifacts
~/macos-vm/run/candidate-440-results/,c440-fourk-a-pipeline-analysis.json and rawlogs.
1555hosttests8skip before440. Docs/findings updated; no new milestone publication.
Dev e240b38... hostedCI38040411149 lastgreen, main unchanged. Sustained4K60 remains
unqualified; no native framebuffer/120/5K or other roadmap work resumed.
