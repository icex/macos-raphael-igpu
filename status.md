# Live status — 2026-10-10

## Candidate 409: stock VMSVGA software desktop, stopped

BootF UUID `77338280-20ea-4365-8e8d-59486e64be2c`, launched source `9a02f8a`,
uses explicit stock VMSVGA with 3D/GPU/NIC disabled. Actual macOS desktop and
Terminal appeared around 107 seconds. Later framebuffer.png verifies owned awake
assertions; initial awake.png lacked them during startup. Fallback screenshot
shows Display_boot / IONDRVFramebuffer registered, matched and active. This is
attachment evidence, not exclusive writer ownership or accelerated presentation.

Inventory was not successful: first keyboard transfer timed out with partial
shell input; retry executed but failed because ioreg returned a dictionary root.
The helper now supports dictionary/list roots, with meaningful tests. Raw 2.1 MB
plist and conformance output remain guest-only. Stopped 7-Zip inspection stopped
at a roughly 274 GB APFS member; no bulk extraction occurred. Next discriminator
is a small isolated FAT exchange disk, followed by offline inventory analysis.

Natural shutdown is verified: awake job removed, ACPI S5 257.041716 s, OFF
257.044244 s, TERMINATED 257.085832 s; result poweroff/unregistered true on first
attempt. Exact UUID absence was independently verified about 18 s before deadline.
No retained UART panic/monotonicity marker. This is software-only, not Metal/VFIO.

Report: `findings/research/virtualbox-vmsvga-discovery-native-20261010.md` and
companion manifest. Prior status archived as status-before-candidate409-20261010.md.
Corrected integrated host suite: 1480 tests passed, 8 skipped, 56.132 seconds.
The corrected helper is not yet guest-qualified. Root owns later VM launches.

## Published milestone and remaining work

Dev `59422dae6683550b7027dd8fe53fb7801f33bbcd` is pushed and verified; hosted
Actions 37995939729 test/build passed, release skipped. It includes tested 402
pool binary and 406 eight-CPU software VBox qualification. Main is unchanged.
New 409 results remain local pending reviewed milestone delivery. Actual VBox
accelerated transport, framebuffer ownership handoff, sustained SMP stability,
PerfPowerServices CPU load, full-field 4K at 60 Hz and first-user console-only
installation remain open. The native GPU and software VBox runs are stopped.
