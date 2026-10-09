# Candidate341: container-local lifecycle closes the container

## Observed result

The real container-local backend now follows both guest-requested poweroff and
external libvirt destruction through QEMU exit to container exit0. The former
idle-libvirtd-container ambiguity is removed in these isolated tests. This does
not yet connect libvirt to the GPU harness or qualify accelerated macOS there.

Two separate transient TCG guests use the paused transaction, a valid isolated
TAP, and a512-byte boot program on a16MiB test disk. The program reports readiness
over UART, waits for a byte, then writes ACPI sleep-enable/type0. QEMU's local
`hw/acpi/core.c:acpi_pm_cnt_write` maps that to GUEST_SHUTDOWN. It contains no OS or
filesystem, so this cannot be called clean macOS/APFS shutdown.

- Guest shutdown: run0019930be693bee31292bb90304670d2. libvirt STOPPED/SHUTDOWN is
  captured before the terminal receipt. QEMU exits, controller stops its daemon,
  and Docker reports natural exit0.
- Manager Force Off: runb2e723171fe00ff2fc34181f735f2b9c. An independent host virsh
  client destroys the domain. libvirt STOPPED/DESTROYED is captured, QEMU exit is
  independently checked, and Docker again reports natural exit0.

The two cases have distinct reasons. Neither infers clean shutdown merely from
an absent domain or Docker stopping. Captured namespace identities include init
start ticks: the kernel reused a namespace inode, but start ticks differ.

## Implementation and ownership boundary

`tools/libvirt-console-local.py` is an importable backend, with no launch CLI.
It subscribes to Python libvirt lifecycle events before creation, uses libvirt's
resume API for the state transition, and retains the exact inherited TAP FD.
It reads QEMU PID/start identity in the container namespace. The existing host
supervisor remains responsible for full CID/StartedAt, absolute exposure limit,
serial drains, GPU recovery and admission. Namespace PID values are not host PIDs.

The bounded monitor keeps the original deadline, preserves guest-shutdown versus
manager-destroyed versus unknown, and requires process exit separately. Event
reader failure cannot disable identity-based cleanup. A bounded callback drain
avoids losing a late STOPPED event. Domain/process disappearance between reads
is reconciled only with typed disappearance and exact process-exit evidence.

## Fixture failures and fixes

All attempts were isolated software VMs with no KVM, VFIO or host NIC access.

- The host assembler adds a GNU property section. Copying only .text produces
  the intended512-byte boot sector; the first invalid build attempt exited before
  VM launch. Dropping root also requires the target user's real HOME for libvirt.
- Without Docker `--init`, orphan libvirt probe processes remained zombies and
  caused a40-second termination delay. That attempt was stopped by its external
  bound/stop path without a normal transaction receipt; it is not a clean pass.
  `--init` is required for the new launch profile.
- The disk fixture needed snapshot mode for writable IDE presentation and explicit
  ACPI/bootindex. With a single512-byte disk, the BIOS still never loaded0x7c00;
  register and memory captures showed it halted in firmware. Padding the same
  boot sector to16MiB reached the UART checkpoint and ACPI poweroff.
- The first actual poweroff exposed QEMU vanishing before libvirt's registry
  settled. The controller now reconciles that observed race without weakening
  identity checks. The next guest-shutdown and Force Off tests pass.

Earlier failed attempts remain under `~/macos-vm/run/c341-lifecycle-guest*` and
in their stopped Docker containers. No test VM remains active. The host
sleep:idle blocker remains active.

## Reproduction and remaining work

Sources: [boot program](libvirt-poweroff-guest-20261009.S),
[container bootstrap](libvirt-local-lifecycle-bootstrap-20261009.py),
[controller test](libvirt-local-lifecycle-smoke-20261009.py).
Build with `as --32`, then `objcopy -O binary -j .text`; append zeros to16MiB.
Use the pinned image3a3c82c7, networknone, `--init`, only `/dev/net/tun` and
CAP_NET_ADMIN; bootstrap drops to uid/gid1000 before libvirt or QEMU runs.
TEST_STOP_MODE chooses guest-shutdown or manager-destroyed. For the second case,
wait for ready.json and destroy that exact run-name via the private Unix session.
The successful test mount paths and full container IDs are in the evidence.

The production backend intentionally refuses network admission until given a
reviewed native-profile TAP provenance/topology verifier. Full native generated
argv verification, vm-entry and manifest integration, outer supervisor identity
correlation, SPICE disconnect/reconnect and the actual GPU cycle are still next.
The existing native GPU launch path is unchanged. Full host suite:1,063 tests
pass,3 skipped (`run/c341-lifecycle-host-tests.log`).

[Captured evidence](libvirt-local-lifecycle-evidence-20261009.json).
