# Complete libvirt console plan, before runtime integration

The previous goal turn made progress: it proved the KVM CPU mapping without VFIO.
This iteration adds tools/libvirt-console-plan.py. It plans a transient paused
libvirt domain from the fully expanded native launcher argument vector. It never
starts QEMU, opens a GPU, or authorizes resume. The existing hardware runner and
published driver remain unchanged.

The strict input profile retains native device order, GPU slot6, Bochs slot7,
firmware order, OpenCore snapshot mode, guest disk, USB/Pulse audio, UART0/1,
HMP monitor and debugger. XML owns memory/vCPU and the single CPU definition;
QEMU type globals retain the two properties verified in the prior KVM test.
The LAN NIC is pre-created with a hubport; its external backend must be injected
while CPUs are paused. There is no fallback launch or implicit domain restart.

The real vm-entry.sh was executed in a network-none/no-device image fixture with
a fake qemu recorder, dummy SMC key and /dev/null in place of the LAN descriptor.
This exposed two inaccurate draft assumptions: HMP uses -chardev/-mon, and this
pinned image selects OVMF_VARS.fd, even for stock container-local NVRAM. The final
planner accepts the observed arguments. No macOS disk or GPU was opened.

libvirt11.9 domxml-to-native preserves exact device and drive order and capture/HMP
arguments, emits one CPU, and starts paused. The full VFIO XML was converted only,
never created or launched. Generated differences needing an explicit runtime
contract include the private libvirt monitor, silent audio1 backend, SPICE
seamless-migration=on, omitted default gl=off, -no-shutdown, mem-lock=off,
seccomp options and the disabled iTCO watchdog action. Existing direct-QEMU
contracts have not been widened to accept these.

## Guest UUID versus run ownership

Native QEMU has no -uuid; system/globals.c declares zero-initialized qemu_uuid.
A nonzero per-run libvirt UUID would change that guest-visible identity. Trying
zero hwuuid did not fix it: libvirt11.9 virUUIDIsValid treats all-identical-byte
UUIDs as invalid and falls back to domain UUID. That failed conversion remains
in c341-full-native-v2.txt.

The plan therefore uses zero domain UUID and a unique run-derived name and XML
metadata. A separate CPU-only KVM launch confirms query-uuid remains zero and
CPUs remain prelaunch/paused. That transient test was destroyed and its container
stopped normally. Runtime ownership MUST bind domain name, run metadata, PID and
start time, and container identity. UUID alone is insufficient. A preexisting
zero-UUID domain in the isolated session must refuse creation; never adopt it.

## Validation and next boundary

Five contract tests reject changed GPU/CPU/console/FD profiles, device/firmware
reordering, duplicate options and added devices. Full host suite:1,038 tests
pass,3 skipped; after the UUID adjustment all five targeted tests pass again.
This is still planning and emulator configuration evidence, not a macOS lifecycle
milestone. No new physical-GPU run occurred and no GPU ledger entry was consumed.

Next: a single-owner transient-domain controller that validates plan digest and
manifest intent, creates paused, verifies actual CPU/device/domain/container
identity, injects the exact inherited LAN descriptor, validates again, then resumes.
Injection/identity failure must leave CPUs unexecuted and destroy only the owned
domain. Guest poweroff, manager Force Off, double-Stop and viewer disconnect must
be distinct events with normal harness capture/cleanup. on_reboot=destroy currently
means supervised shutdown/recovery, not transparent guest reboot support.

Artifacts (under ~/macos-vm/run):
- c341-native-argv-fixture/expanded-argv.json SHA256 15325fb297b0b3de835e237270f0a33e1d70fbfd13889bbd1828356d35033ed2
- c341-libvirt-full-plan-v3.json SHA256 10e7eb7f80a49b8b3c3b5b7f3826b50fae88bfdb89110afaf599aa07429e953f
- c341-full-native-v3.txt SHA256 b3b0093c6a72d1496a11acc3e483c68f133143dc06e21d24e764a13f8803f258
- c341-zero-uuid-proof.json SHA256 40e42aae83e016e45f65880e97a425e3b6c46d8fa9927d1a542cd5e9e28698f3
- c341-planner-host-tests.log SHA256 ebba7f9ff0763073b0aab2c0ae3d636568acc32b24355264371995fd57f4d51d
