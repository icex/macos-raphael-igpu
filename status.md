# Live status — 2026-10-10

## Candidate 410: software registry exchange complete, stopped

Boot G UUID `f9c1de4d-ca93-4a04-a830-a122143c2745`, source `89db9fb`, uses stock
VMSVGA, eight CPUs and RealTSCOffset; no GPU/VFIO. Root verified the desktop,
`C410_STATUS0` and awake assertions, then removed the owned awake job before shutdown.
The FAT exchange returned nine fresh files with valid receipt/hash checks. Original
409 `/tmp` artifacts were absent; they were not recovered.

Fresh GFX0 is `15ad:0405`, class `030000`, at PCI `0:2.0`. BAR0 is I/O base
`0x6030`, length `0x10`; BAR1 is memory base `0xe0000000`, length 64 MiB;
BAR2 is memory base `0xe4400000`, length 2 MiB. Active `Display_boot` /
`IONDRVFramebuffer` and two framebuffer user clients remain attached.
`IOFBMemorySize=8294400` corresponds to 1920×1080×4. This is attachment/resource
evidence, not exclusive ownership or accelerated presentation.

The original controller result retains `error_type=VBoxCallError`: a main-loop
state query lost its direct console during natural exit. A 0×0 screenshot refusal
is also retained. Independent events prove S5 at 202.287588 s, OFF at 202.291376 s
and TERMINATED at 202.343239 s, before the 300 s deadline. The exact UUID was absent
about 80 s before the deadline. Unregister succeeded once, `exchange_closed=true`,
with no `cleanup_error`. No controller fix or receipt rewrite was made in 410.

Evidence: [native report](findings/research/virtualbox-fat-exchange-native-20261010.md)
and its 22-artifact hash manifest. The 410 suite passed 1486 tests, with 8 skipped.
[Prior 409 status](findings/research/status-archives/status-before-candidate410-20261010.md)
is archived.

## Remaining work and delivery

Root owns the next software test; no VM is active from 410. The next implementation
must preserve bounded exact-identity handling of the transient main-loop read,
and establish explicit boot-framebuffer ownership before transport writes.
VirtualBox acceleration, FIFO publication and exclusive aperture ownership remain
unimplemented/unqualified. PerfPowerServices CPU use and sustained stability remain
open. QEMU 402 pool progress and imperfect CR2 capture remain separately recorded.

The last verified published baseline, dev
`59422dae6683550b7027dd8fe53fb7801f33bbcd`, has hosted test/build success
(Actions `37995939729`). The checked-in binary is the exact tested 402 executable
with its canonical manifest. Candidate 414 integrates 410 results, 412 ownership
analysis and 411/413 experimental DMA patches. Host VBox is
unchanged; no patch was deployed.

The integrated 414 suite passed 1487 tests in 56.379 s, with 8 skipped. All 22
native 410 artifact hashes and the exact 402 binary/manifest were reverified.
Main is unchanged; this status grants no launch admission.
