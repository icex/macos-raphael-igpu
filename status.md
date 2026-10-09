# Live status — 2026-10-10

## Candidate410: software registry exchange complete, stopped

BootG UUID `f9c1de4d-ca93-4a04-a830-a122143c2745`, source `89db9fb`, uses stock
VMSVGA, eight CPUs and RealTSCOffset; no GPU/VFIO. Root verified the desktop,
C410_STATUS0 and awake assertions, then removed the owned awake job before shutdown.
The FAT exchange returned nine fresh files with valid receipt/hash checks. Original
409 `/tmp` artifacts were absent; they were not recovered.

Fresh GFX0 is15ad:0405/class030000 at0:2.0. BAR0 I/O6030/10, BAR1 memory
e0000000/64MiB and BAR2e4400000/2MiB. Active Display_boot/IONDRVFramebuffer and
two framebuffer user clients remain attached; IOFBMemorySize8294400 corresponds
to1920×1080×4. This is attachment/resource evidence, not exclusive ownership or
accelerated presentation.

Original controller result retains error_type=VBoxCallError: a main-loop state
query lost its direct console during natural exit. A0×0 screenshot refusal is
also retained. Independent events prove S5 at202.287588s, OFF202.291376s and
TERMINATED202.343239s, before300s. Exact UUID absent about80s before deadline;
unregister succeeded once, exchange_closed=true, no cleanup_error. No controller
fix or receipt rewrite was made in410.

Evidence: [native report](findings/research/virtualbox-fat-exchange-native-20261010.md)
and its22-artifact hash manifest. 1486 tests pass,8 skipped. Prior409 status is
archived under status-archives/status-before-candidate410-20261010.md.

## Remaining work and delivery

Root owns the next software test; no VM is active from410. Next implementation
must preserve bounded exact-identity handling of the transient main-loop read,
and establish explicit boot-framebuffer ownership before transport writes.
VirtualBox acceleration, FIFO publication and exclusive aperture ownership remain
unimplemented/unqualified. PerfPowerServices CPU use and sustained stability remain
open. QEMU402 pool progress and imperfect CR2 capture remain separately recorded.

Dev59422dae6683550b7027dd8fe53fb7801f33bbcd has hosted test/build success
(Actions37995939729); checked-in binary is exact tested402 with canonical manifest.
Candidate414 integrates410 results,412 ownership analysis and411/413 experimental
DMA patches locally for review. Host VBox is unchanged; no patch was deployed.
Integrated414 host suite: Ran 1487 tests in 56.379s  OK (skipped=8).
The22 native410 artifact hashes and exact402 binary/manifest were reverified. Main unchanged; status grants
no launch admission.
