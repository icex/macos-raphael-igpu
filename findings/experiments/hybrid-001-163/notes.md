# Hybrid experiment 001 — 2026-09-08

**Result: HYBRID_QUEUE_SUSPECTED. Full Metal is still unavailable.**
This is a valid diagnostic experiment, not a passing acceleration test.
Source b340140, candidate 1.0.163 build `90fc73c8b2e74ad79ecc2db3eb85ad4c`,
boot `23aedc74-6a57-4321-94f0-ae91d0e79354`. The immutable manifest binds
source, executable, KDK, bootdisk, configuration, QEMU image and guest probe.

The one-way amdgpu-to-VFIO handoff completed and post-handoff kernel capture
contained no matching host faults. QEMU used only the intended iGPU. The guest
loaded the exact build and its HWLibs route entry guards matched. All 21 critical
records were present; critical dropped=0/truncated=0. The separate regular buffer
dropped 314 entries explicitly; do not infer absence from that ordinary replay.

| Critical order | Observation |
|---|---|
| 3–4 | HY type12, available1, status0 |
| 5 | KIQ stamp1 passes |
| 6–7 | HY type13, available1, status0 |
| 8–11 | Further KIQ stamps pass; powerUpHWEngines returns1 |
| 12–13 | HY type10 (SDMA), available1, status0 |
| 14–15 | HY type11 (SDMA), available1, status0 |
| 16–17 | HY type10 (SDMA), available1, status4 |
| 18–19 | startHWEngines and accelerator powerUpHW return0 (false) |

No Metal probe was submitted: the native startup prerequisite failed. There are
still zero verified Metal compute/render completions. GC queue creation and KIQ
setup succeeded again on this fresh amdgpu-first boot, but this does not validate
warm reuse or all engine execution.

The native X6000 SDMA start loops over both rings per engine, then
AMDHardware::startHWEngines advances to the next engine. Its loop count is
2*(hardware+0xc2)+2: at least two SDMA engines. SDMA init writes each request's
engine index from enum(engine)-1. This makes a request for the absent second
instance the leading explanation, not yet the measured rejecting branch.
Cached IP discovery metadata enumerates only HWID42/instance0, SDMA5.2.6;
HWIDs43/68/69 are absent. See sdma-discovery.json, captured from software sysfs
metadata after handoff without raw register access. The older flat IP snapshot
only reads instance0 and by itself would not prove the instance count.

The coordinator observed the result, retained its predefined short tail, requested
ACPI shutdown, then confirmed exact-CID forced stop after the 20-second grace.
The guest emitted a nested kernel panic during that interval (serial line3188);
its printed `System shutdown begun: NO` prevents claiming native teardown. A
similar nested panic occurred GPU-less. Its root cause is unresolved and cannot
be attributed to SDMA from this sequence. Host boot ID remained unchanged,
watchdogs and sleep inhibition remained active, and no matching host kernel
fault was captured. Protected pstore contents remain unknown.

**Next:** hybrid-002 on a fresh host boot. Candidate164 records the actual native
SDMA lookup for index1/type0 at the verified hybrid caller. A null return proves
the child takes its missing-instance branch. A present instance with occupied
slots or a later callback failure requires following that branch instead.
Do not alias engine1 to engine0, return fake success, add nonexistent instances,
change firmware, or retry this used boot. Lifecycle reuse is not qualified.
