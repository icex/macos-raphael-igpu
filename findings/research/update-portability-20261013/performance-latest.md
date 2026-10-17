# Latest macOS15 versus26: matched GPU performance

Same candidate490 driver and exact native benchmark binary on15.8.1/24H32
and26.7.1/25G241, UID501, frozen QEMU pins v15, same boot/hardware,12GiB VM,
GFX clock request2200MHz, background display3840x2160/1920x1080 points at60Hz.
Two warmup batches and ten measured batches per workload; medians below.

| Metric |15.8.1 |26.7.1 |26 relative to15 |
| --- | ---: | ---: | ---: |
| GPU render fps | 2762.31 | 2784.71 | +0.81% |
| Wall render fps | 2704.40 | 2726.86 | +0.83% |
| GPU FP32 GFLOP/s | 283.50 | 283.56 | +0.02% |
| Wall FP32 GFLOP/s | 281.44 | 281.43 | -0.00% |

Render:1280x1024 BGRA8 offscreen target; fullscreen ramp plus20,000 small
triangles,64 frames per command buffer.736 ramp pixel checks and4,504 expected
yellow triangle-band samples pass on both. GPU fps uses command-buffer GPU
execution duration; wall fps additionally includes encoding,submission and waits.
It is throughput for this workload, not desktop/game FPS or full-field4K120.

Compute:131,072 threads,16 FP32 lanes,256 dependent fused multiply-add iterations,
eight dispatches per batch; FMA counts as two floating point operations. Fast
math disabled.8,176 CPU-reference checks and all-output finite checks pass on
both; zero mismatches. GFLOP/s is this arithmetic workload's achieved rate,
not a claim of peak performance or a general application/ML benchmark score.

The results are effectively equal: render difference<1%, compute difference
~0.02%. One paired boot comparison supports this workload conclusion, not a
statistical ranking of the operating systems. Earlier root per-frame-wait tests
(4–14fps on locked Tahoe sessions) used different submission/session conditions;
they do not establish a comparable GPU slowdown. Latest batched UID501 test also
shows similar wall throughput. Unlocked Tahoe presentation FPS remains unqualified.

Identity: benchmark SHA25660d6f6a04372cd213980900c2de73a465f32a9b59ff0ddb69755db05d68849d4;
driver SHA256242c97440e4c89925f40727870a7a0610cce860612cd1ad4c60ac98bb7301d83.
Runs:15.8.1 `4bf08281df4d0237ac86e8a215757ec6`,26.7.1
`28cd33c3c81c78c3c80c00b09b3aad06`. Both core probes, native shutdown and ordinary
recovery pass. Native binary built with macOS15 deployment minimum, then copied
and hash-checked unchanged. Source: tools/gpu-performance.m includes the existing
desktop probe's audited shaders; no benchmark self patching or emulation.
Raw samples: performance-24h32.json and performance-25g241.json beside this report.

A preceding15.8.1 attempt panicked in mcache.bigcl before benchmark execution;
its cause is unproven and it is excluded from timing data, not erased. Forced
shutdown left an enabled SDMA input. Complete reviewed MODE2/noqueue
requalification passed with immutable original evidence; bounded retry passed.
This remains a guest reliability observation, not full crash qualification.
Original15.8.1 disk is restored; no older-version testing or Vulkan work was done.
