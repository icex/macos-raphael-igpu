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
