# Candidate 437: isolate full-field QEMU delivery cost

Candidate 436 B/C repeat approximately 25–27 decoded IDs/s for full-field 4K,
55–57 localized, source approximately 60. Valid source is scale 1, not Retina.
Only 4K performance is active; host viewer remains normal 1440×900/GDK1.

Exact helper microbenchmark at ~/macos-vm/run/c437-bbox-microbenchmark.json:
localized median 1.011→0.686 ms, all-pixels-different 0.00649→0.01015 ms,
equal 0.547→0.501 ms. Host synthetic sequential timings are not VM performance.
This rejects border chunking as a supported full-field fix. Its exact helper
patch and brute-force equivalence tests are retained OFFLINE, not in this image.

The isolated image applies only opt-in trace events atop candidate402 pool QEMU.
Diff timing is separate from update creation. Allocation includes update structs;
mirror stage includes drawable metadata/pixman image setup plus source→mirror;
bitmap stage includes mirror→bitmap and destination-image release. Refresh timing
separates graphic_hw_update from lock/update work and records a queue-busy skip.
Server command dequeue records its timestamp and dimensions: this is not client
delivery. All extra clocks are gated by trace enablement, except existing clocks.
Trace output itself adds diagnostic overhead; compare phase-interior source,
server and client rates within the instrumented trial, retain uninstrumented
control separately. Do not infer full-frame integrity from decoded tokens.

Build provenance: ~/macos-vm/run/c437-qemu-inputs.json; container has no devices,
network none, user1000, all capabilities dropped. Baseline source remains intact.
Compiled QEMU 10.1.2; new image pinned by content ID. No hardware result yet.

## Completed hardware evidence

Run649d6aba0f68c810c2a86cfbb594470d, build b858e981c0af4fb58c982cfd5e4aa820,
unchanged GPU source d1deade..., cardmetal-231, MODE2 reset332. CORE_PROBE_PASS.
A/C source remained logical1920×1080, scale2, backing3840×2160, nominal60.
Normal1440×900/GDK1 viewer, explicitSPICE60. These are Retina trials, not the
scale1 candidate436 comparison. Do not claim a regression from their lower rates.

A client full-field phase interiors22.82/23.02 unique IDs/s while QEMU create and
server dequeue45.19/44.81 commands/s, localized about56 at both stages. Refresh
about49/s; queue-busy skips0. Full-field means: diff688/693us, mirror/setup
2149/2180us, bitmap/cleanup2072/2063us. A71startup-invalid,0post-start,1duplicate.
The duplicate is retained; unique counts exclude it. Background updates span
3840×2112; token band localized rectangles560–576×48. No frame-integrity claim.

C preferred-compression7(LZ4) client23.12/23.50, server44.46/45.12 commands/s;
localized54.89–56.01 at both stages. C30startup-invalid,0post-start/duplicate.
Display-channel received747.42/758.48MB/s during full-field interiors.
B never connected (incorrect GI enum ImageCompression instead of ImageCompress);
owned viewer and source stopped, timings excluded. C used reviewed protocol enum7.

A/C clock receipt verifies host/container monotonic offsets both0 despite
different time-namespace inodes. Phase interiors inferred from observed client
IDs with1s margins, not guaranteed upstream phase bounds. Analyzer requires qid0,
rejects post-start corruption, discards operations crossing interval end, and
never subtracts guest draw clocks from host clocks. Counts are events; no unique
command IDs establish latency. Setup and cleanup costs are inclusive, create_us
overlaps nested stages and trace writes. Tracing itself has cost.

Primary source discovery: retained upstream spice0.16.0 source at
~/macos-vm/run/c380-server-study/spice-0.16.0/server/dcc-send.cpp:439 bypasses
dcc_compress_image whenever red_stream_get_family is AF_UNIX. dcc.cpp:884 accepts
client preferred codecs, but that cannot override this transport-specific bypass.
The source archive/provenance is retained in c380-server-study/build-manifest.json;
it is matching-version source, not distribution-identical binary proof. Next test
will compare otherwise matched compiled baseline/opt-in server libraries and
explicit OFF/LZ4 client preferences. Do not assume preference means compression.

Artifacts: ~/macos-vm/run/c437-fourk-{a,c}-pipeline-analysis.json,
c437-lz4-c-byte-analysis.json, c437-shared-clock.json; raw source/client/trace and
requested-codec/channel-byte metrics retained. Artifact hashes in analysis.
Guest-requested shutdown, natural capture exits, private terminal verification;
stopped-container inspection reconciliation unavailable/mismatched. Recovery
authorizes_launch=true. No runner killed, no reboot or native driver activation.
