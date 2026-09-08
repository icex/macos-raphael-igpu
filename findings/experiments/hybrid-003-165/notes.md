# Hybrid experiment 003 — 2026-09-08

**Result: the owner-level SDMA repair completed TTL initialization, then exposed an
X6000 channel-table assumption and panicked the guest before engine start. Full Metal
is still unavailable.** This was a bounded physical experiment using source
`5727e7d`, candidate 1.0.165 build `69ba1ae965234124a3506f8820923da2`, and host boot
`851d35df-7e63-4154-b70b-5cfa044913d6`.

The exact candidate loaded, all five topology routes matched, and
`TTL::initialize()` completed. The repair then released the false SDMA1 object and
native `AMDHardware::initializeHWEngines` returned 1:

```
SD: topology applied: discovered=1 kept=SDMA0 removed=SDMA1 before initialize
SD: AMDHardware::initializeHWEngines -> 1 (topology-applied=1)
```

The next accelerator stage trapped at runtime `AMDRadeonX6000` base plus `0x26f0`,
reported as `createAccelChannels(bool)+0x278`, with `RAX=0`, `R14=0` and `CR2=0`.
The exact 24G830 disassembly shows:

```
26e7: call qword ptr [rax + 0x320]  ; IAMDHWInterface::getHWChannel(...)
26ed: mov  r14, rax                ; returned NULL
26f0: mov  rax, qword ptr [rax]    ; fault
```

`createAccelChannels` uses static channel type 2. `AMDRTHardware::getHWChannel`
converts one of those requests to engine enum 2, and
`AMDHardware::getHWChannel(engine, ring)` indexes engine slot
`hardware + 0x3b0 + 8*engine`. Engine 2 is the detached `+0x3c0` SDMA1 slot, so the
native lookup correctly returns null. The higher accelerator layer assumes the Navi23
second engine still exists and dereferences the result without checking it.

This does not invalidate the measured one-instance topology. It identifies the next
compatibility boundary: after removing the false physical engine, X6000 channel
requests for SDMA1 must resolve to the surviving SDMA0 engine. NootedRed uses this same
low-level mapping for one-SDMA AMD APUs. It is distinct from fabricating a second TTL
instance or forcing a successful hybrid return; the surviving native engine still
selects its own ring and creates the real channel.

The initial coordinator verdict was `INCONCLUSIVE` because the guest panicked before
the delayed `RGPU_EVENT` replay and the classifier ignored live `CRLOG` lines. The
retained `verdict-original.json` records that instrumentation failure. The corrected
classifier accepts only exact live build/route/topology records, recognizes the
symbolicated panic, and now reports the run as valid `GUEST_PANIC` at
`createAccelChannels+0x278`. Missing build or route identity still remains
inconclusive.

The Metal probe was never started. The guest could not service the authenticated
shutdown request after panicking, so the supervisor force-stopped only the identified
container. The host retained the same boot ID, VFIO ownership, watchdog state, sleep
inhibitor and power pin. Its captured kernel delta contains the normal VFIO reset and
network teardown, with no host fault. This boot remains consumed and must not be reused
for another physical experiment.

**Next:** candidate 1.0.166 routes the exact
`AMDHardware::getHWChannel(engine, ring)` entry under the existing Raphael gate. Once
the repaired owner exists, engine 2 requests map to engine 1 and all other engine IDs
remain unchanged. The next run must record that `2 -> 1` mapping, survive channel
creation, preserve KIQ/hybrid/native start results, and only then run the checked Metal
compute/render probe.
