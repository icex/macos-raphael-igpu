# Live status — 2026-10-10

## Candidate403: eight-vCPU VirtualBox software desktop

BootD UUID `13212bff-697a-473d-b257-da83e7e463b9` reaches the actual macOS
desktop using RealTSCOffset at4699997773Hz. Root/report author viewed
screen-040.png. No retained UART panic/monotonicity marker. This couples clock
mode and frequency compared with400's eight-CPU emulated-clock panic; no exact
root-cause or sustained-stability claim.401 separately proved one-CPU input/awake.
No new403 input, awake or graceful-shutdown checks occurred. No physical GPU,
Raphael passthrough, Metal or accelerated VBox transport is qualified.

Controller deadline poweroff was followed by original cleanup_error=VBoxCallError.
After expected unregister-lock retries, showvminfo lost its direct console during
GUI teardown (VBOX_E_VM_ERROR0x80bb0003). Root later verified exact UUID/config
poweroff, unregistered it and confirmed list absence. Original result is intact;
cleanup is finally proven but was not natural guest shutdown.

A bounded controller correction retries only the exact transient state-query
error after an earlier full stopped identity observation, and requires fresh
identity/stopped proof before another unregister. Thirteen focused tests pass;
native qualification remains pending. No timeout or ownership gate is relaxed.
Evidence: findings/research/virtualbox-eight-cpu-real-tsc-native-20261010.md
and its ten-artifact hash manifest.

Both403 software VM and preceding399 GPU cycle are stopped; root owns later402
work independently. Dev milestone84159a9 was pushed and hosted test/build passed
run37993406232 (release skipped), exact tested399 binary. Main remains unchanged.
Next qualify eight-CPU input/awake and graceful shutdown, then resume source-led
VBox acceleration work separately from the QEMU accelerated-console path.
