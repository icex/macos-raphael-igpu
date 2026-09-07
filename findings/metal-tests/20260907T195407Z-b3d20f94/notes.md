# Candidate 1.0.156: physical root repaired, queue guard rejects

The supervised VM started at 2026-09-07T19:52:39.92365616Z with a 180-second limit.
Guest boot time was 22:53:38 local. Exact container:
`9ea44fd15bd946e1115ba79aa95ac4116bc5ccd6624f58a0b01a22af65466b95`.
It was explicitly stopped after collecting the result, before the deadline. Host
kernel logs show VFIO reset/reset-done and no lockup, oops, or GPU fault messages.

The getter hook passed every live guard: caller `0x33ee1`, flags 0, logical base
`0xf400000000`, size `0x20000000`, GC base/top `0xf400..0xf41f`, offset `0x840`.
Native physical base 0 became `0x840000000`. Apple subsequently programmed CTX0
root `0x84fdfc001` itself, with no manual root-register repair.

`AMDHWMemory+0x58`, previously labelled `reserved`, consequently became
`0x840000000`. The plugin's GART walker and KIQ guard both require
`softwareBase - reserved == MCbase`, which now fails. XQ2 therefore refused
startKIQ before touching the queue; native MQD/EOP were already logical MC
`0xf40b706000` / `0xf40b706800`. This run does not test whether KIQ can execute
with the corrected physical root.

The automated probe returned a failed verdict because the Metal device was
absent when queried. It ran while initialization was still progressing; the
subsequent XQ2 rejection is the conclusive driver result. Zero GPU results were
verified. The next run should wait for the power-up outcome before invoking
the already prepared probe.

Source follow-up corrected the interpretation of `+0x58`: HWLibs query wrapper
`0x1e52b..0x1e53a` exports `vm+0x210` into memory-range output `+0x18`, which
flows through `_ipi_gvm_set_memory_attributes` and framebuffer memory services
to `AMDHWMemory+0x58`. It is the physical framebuffer base; `+0x60` is the
MC-to-physical delta. The earlier review missed this wrapper export.

See `serial.txt`, `candidate.json`, supervision metadata, and `guest-output.txt`.
