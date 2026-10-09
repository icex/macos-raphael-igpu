# Candidate401: single-vCPU timekeeping discriminator (not executed)

BootB reaches userspace but panics on CPU6 with invoke0xf8faf2a44 preceding runnable0xf8faf8032 by21998 absolute-time units. Public XNU11417.140.69 `osfmk/kern/sched_prim.c:3216–3228` compares the recount snapshot's mach time with the incoming thread's last_made_runnable_time. This matches the assertion's semantics; the installed11417.140.69.711.44 kernel reports line3242, so exact source/binary identity is not asserted. diskarbitrationd is the current task, not a proven AHCI cause.

## Actual bootB settings, not proposed defaults

Selected nonsecret VBox.log lines establish8vCPUs, VirtTSCEmulated at4294967295Hz, host calibration4699997773Hz, multiplier1, TSCTiedToExecution=false and TSCNotTiedToHalt=false. TSC mode switching is allowed; RDTSCP and invariantTSC are exposed. The source of the extracted lines remains the private full VBox log; no key/serial values are printed or copied into this report.

Pinned VirtualBox7.2.18 commit14841851fa211c7faf615978ba385d59947236c6:

- TMR3.cpp:381–414 defines supported string modes VirtTSCEmulated/RealTSCOffset/Dynamic. Lines391–398 explicitly explain Dynamic SMP's uncoordinated switching/backwards-time risk and default SMP to emulated.
- Lines459–469 calibrate host frequency and clamp emulated/Dynamic frequencies>=4GHz to0xffffffff, forcing emulated. This explains the observed4.295GHz value without an invented user override.
- TMAllCpu.cpp:495–523 selects the raw clock, subtracts a per-vCPU offset and enforces monotonicity with **per-vCPU** u64TSCLastSeen. That is not proof of a cross-vCPU ordering guarantee.

Thus simply requesting emulated TSC repeats bootB's observed mode. RealTSCOffset exists but is not yet selected as a fix, and the deprecated UseRealTSC option is explicitly rejected by current source.

## Smallest next test

Create fresh independent bootC descendants from the verified baseline plus bootB's approved loader changes. Change only configured vCPUs8→1; retain Intel i7-6700K CPU profile, EFI/SMC/device-property override, AHCI ports and all other inputs. The existing loader has no Darwin24 AMD kernel patch needing an8-core patch count. Do not change storage layout simultaneously to avoid confounding the first test.

Before interpreting the result, confirm VBox.log still reports VirtTSCEmulated4294967295Hz and unchanged CPUprofile. Source predicts the high-frequency clamp keeps the single-vCPU path emulated even though the initial default selection may beDynamic; actual log is authoritative. If mode/frequency differs, report the extra change rather than calling this an isolated CPU-count comparison.

Observe beyond the prior~66.8-second userspace failure within the existing<=300second controller, with UART and actual VBox screenshot. Passing means forward progress/no repeated monotonicity assertion during that bounded window; desktop requires visible usable desktop separately. A positive supports a cross-vCPU contribution, not root-cause proof or a production single-core performance solution. A repeat on oneCPU narrows attention to the clock conversion/source/profile rather than SMP alone. Cleanup must retain the exact owned poweredoff/unregistered result.

No VM registration/start, CPU stress, physical-device call, guest mutation or clock-mode change was performed for this audit. Root owns the next execution; candidate399 hardware measurements remain separate.
