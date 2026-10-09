# Own-buffer copy discriminator (candidate350)

`tools/console-copy-probe.m` uses no Metal, ScreenCaptureKit, desktop capture or
physical GPU mapping. It creates aligned malloc memory and an owned CPU-filled
IOSurface wrapped in a CVPixelBuffer. Its `ram` target never opens an IOKit
client; `console` uses the existing exclusive RaphaelConsole memory0 contract,
explicit WC mapping and checked mapped length. The driver restricts that client
to the emulated Bochs presentation BAR. The root run owner must stop the existing
presenter before console ownership and restore its approved bundle afterward.

Compile in the guest (not yet performed):

```
xcrun clang -fobjc-arc -O2 tools/console-copy-probe.m -framework Foundation -framework IOSurface -framework CoreVideo -framework IOKit -o /tmp/console-copy-probe
/tmp/console-copy-probe ram 1920 1080 0
/tmp/console-copy-probe ram 3840 2160 0
/tmp/console-copy-probe console 1920 1080 10
/tmp/console-copy-probe console 3840 2160 10
```

Each invocation runs three rounds of four cases: malloc/owned IOSurface × row
copies/one contiguous copy. Round0 is warmup; subsequent rounds reverse order.
Contiguous copies require exact source stride; padded layouts explicitly skip
that case. Fill/allocation/readback are outside timed windows. Every case reports
phase, size, stride, bytes, lock/copy/SFENCE/unlock/total wall time and verifies
all destination pixels through volatile reads. Malloc lock/unlock numbers are
empty timing overhead controls. Fixed pixel pattern is opaque BGRA with R=(x+
37*phase)%256, G=(y+71*phase)%256, B=(x XOR y XOR phase)%256. COPY_READY reports
the actual final phase for an independent QEMU screenshot pixel oracle; console
mode programming occurs only after the matrix. Guest readback is not independent
viewer validation. Readback itself can be slow and changes cache state; compare
only this fixed protocol, not its times against unmatched historical tests.

Alarm bounds the whole process to60 seconds; optional final hold is0–15 seconds.
Twelve timing records maximum avoid continuous logging. Unexpected lock/map/
geometry failures or pixel mismatches exit nonzero. Default SIGALRM terminates
if blocked; the existing outer harness remains responsible for recovery. No
production presenter or driver behavior changes. A fast owned IOSurface does
not reproduce or exclude GPU-producer/SCK synchronization costs. Row versus
contiguous improvement here would justify a later measured presenter experiment,
not an immediate throughput or atomic-presentation claim.

Offline validation is source review and git diff --check only: this Linux host
has no available macOS SDK for these frameworks. Compilation and native execution
remain explicitly pending under root-owned supervised testing; no TCC bypass.
