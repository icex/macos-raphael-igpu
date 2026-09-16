# Managed texture ownership and retained LOAD — 2026-09-16

Candidate 280 run `964787995e1a5e34fcc7b651ae6c716b` (MODE2 reset 170,
exposure 28) ran the new [texture ownership probe](../../tests/texture_ownership_probe.m)
on the same host boot. The driver was unchanged. Each of two independent
processes used fresh managed textures for every case, covering RGBA8 and BGRA8
at 64×64 and 1003×769. Each seed completed 48 cases across three controls:
LOAD-only, CPU-partial-update-only, and CPU-partial-update plus retained LOAD.

The probe has an independent CPU oracle with explicit BGRA channel ordering. It
GPU-rendered an initial pattern, synchronized the managed texture before the
CPU half-texture `replaceRegion` update, then used a separate retained
`MTLLoadActionLoad` pass where applicable. Final texture→managed-buffer copies
used explicit synchronization; active pixels and 256-byte row-padding sentinels
were checked. Every case reported `initial bad=0`, `gpu_copy_bad=0`,
`cpu_read_bad=0`, and `padding_bad=0` for seeds 41 and 709. Each output reports
48 cases, 18,609,672 case pixels, and 55,829,016 pixel comparisons (three
readbacks per case). The initial synchronization/readback is present in every
control. This establishes the tested managed ownership transition and retained
LOAD scope; it does not qualify same-pass feedback, IOSurface, depth/stencil, or
desktop rendering.

The API boundary follows Apple’s [Synchronizing a managed resource in
macOS](https://developer.apple.com/documentation/metal/synchronizing-a-managed-resource-in-macos).
Outputs: `ownership-seed41-output.txt` and `ownership-seed709-output.txt` in
`/home/bogdan/macos-vm/run/candidate-280-attempt-ownership-results/`.

The visually inspected 1920×1080 System Settings, Activity Monitor, and Dock
capture was clean. The first capture helper assertion failed before connection;
the corrected class-property assertion succeeded on retry, with no render
failure. Cleanup is complete: `CORE_PROBE_PASS`, `valid=true`, 384 critical
records at snapshot 11, guest-request exit, schema-6 recovery with
`authorizes_launch=true`, `CP_STAT=0`, `active_after=0`, forced clears/timeouts
all zero, and `kernel_messages=[]`. Systemd is inactive/dead with exit 0; only
the inhibitor container remains.

[Artifact hashes and aggregate results](texture-ownership-evidence-20260916.json).
