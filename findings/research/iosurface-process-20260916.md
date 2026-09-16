# Two-process IOSurface visibility — 2026-09-16

Run `2afa3401a71e99091aa8bdbd14c50fa7`, candidate280/metal-127/iosurfaceprocess,
MODE2#165, twenty-fourth exposure on host boot
`2508eb6d-ddf3-497d-9774-00a7ecebe3ed`. Driver and QEMU unchanged.

One 1003×769 BGRA8 IOSurface with 4096-byte rows is independently imported by
parent PID719 and exec'd child PID720, on Metal registry ID4294968085.
32 bidirectional rounds pass:24,681,824 pixels checked in each direction,
49,363,648 total, zero mismatches. Surface ID3 matches in both processes.
The child exits normally with wait status0 and is reaped by its parent.

Each process has its own Metal device, queue, imported managed texture and managed
upload/readback buffers. Parent uploads a changing per-pixel hash, waits for GPU
completion, then sends a pipe token. Child GPU-copies to synchronized readback,
checks every active pixel, uploads a different hash, waits, and acknowledges.
Parent reads and checks that reverse transfer. No CPU writes to surface memory.
Pipe messages validate magic, round and PID; waits are bounded and process timeout
is180 seconds, with bounded child termination/reaping on errors.

The supplied 24G830 decompilation at7ffb08d6446a shows an IOSurface texture import
path that obtains IOAccel shared connection/resource information and invokes method
0x102. A branch tests isIOSurfaceSharedMetalTexture (7ffb08d60234), which checks
surface metadata for kAMDMTL_isSharedTexture. These distinct native paths are why
this result is limited to the public IOSurface import used here; runtime branch
instrumentation was not performed. No private metadata or native patch was added.

Scope: host-completion-ordered cross-process GPU visibility. This is not GPU-only
interprocess shared-event synchronization, sandboxed XPC sharing, concurrent writes,
render-target compression visibility, every format, independent host boots, or a
performance benchmark. Global IOSurface lookup is deprecated (the SDK emits one
warning); this short-lived test contains synthetic pixels only. Modern Mach-port
transport remains a separate coverage item.

PerfPowerServices PID152:0.0% CPU,0.73s cumulative, tenth measured guest boot using
the corrected QEMU image, all on one host boot. Host regression remains948 tests
OK/3 skipped; only this standalone probe and documentation changed since that run.

Lifecycle: baseline CORE_PROBE_PASS, valid capture370 records/snapshot6.
Guest-request shutdown; schema6 recovered/authorizes_launch=true, CP_STAT=0,
active_after=0, forced_inactive=0, dequeue_timeouts=0, kernel_messages=[].
[Artifact hashes and probe summary](iosurface-process-evidence-20260916.json).
