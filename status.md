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
