# Live status — 2026-09-16

Boot2508eb6d-ddf3-497d-9774-00a7ecebe3ed, GPU0000:7b:00.0 vfio-pci, power/control=on.
Candidate277 driver1.0.277 retains working HEVC hardware decode. Candidate278
linear-swizzle change rejected. Full desktop unqualified: native transparent
colored panels still show green/purple diagonal corruption; isolated probes pass.

Last run ec5d03f7433ad8f4151f35644c5e38c9/smcfinal tested image2ada1bb2323f.
Baseline passed. PerfPowerServices still busy: enumeration incorrectly waited for
length byte. Corrected PMIO implementation responds after four index bytes;
isolated protocol checks pass. Persistent fix NOT yet verified. No service disabling.
Normal guest-request shutdown, recovery recovered/authorizes_launch=true/CP_STAT=0.
Results: candidate-277-attempt-smcfinal-results. Earlier smcverified admission
refusal and staging failures consumed no exposure. Details in perfpower research note.

## Fourteenth exposure allowance

Standing user fix-and-continuously-test authorization covers one additional run
on boot2508eb6d-ddf3-497d-9774-00a7ecebe3ed, attempt smcpmio, unchanged candidate277
and card metal-124. Corrected emulator image51cbd7dcdbad2d6492ce83a263e9854c28620d67a1ea12ebc0562c6fab2605ad.
Fresh MODE2, maximum6000s, interactive hold5400s, all identity/capture-fatal/host-fault/
shutdown/recovery aborts preserved. Verify native SMC enumeration and CPU without
process modification, then continue transparency. No direct OpenGL workload.

RUNNING a169e87a3b282ebb6552150a77a9c232/smcpmio, MODE2#152. Image51cbd7dc
and binaryd52b825bd310a392f3d189948f58b3772833a26060b202e2d43a4175f20203f8
verified. Native SMC user-client test passes indices0..5 and end-of-list0xb8 at6,7.
PerfPowerServices PID152 CPU0.0%, cumulative0.67s, no debugger/process changes.
Startup sample no longer contains getAllKeys/SMCGetKey loop. Sustained monitoring
and service-restart repeat pending. Baseline completed; cleanup pending.
