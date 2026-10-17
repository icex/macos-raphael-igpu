# Candidate341: native configuration and macvtap verification foundation

## Configuration

The new pure verifier rebuilds the plan from its private expanded native argv,
then compares every observed QEMU argument in order. It independently specifies
the libvirt11.9/QEMU10.1 machine, CPU, memory, topology, UUID, SPICE, watchdog,
monitor, sandbox and audio defaults around the exact original peripherals,
serial/HMP endpoints, disks and native network arguments. JSON fields reject
duplicates. Error messages never print private AppleSMC arguments.

A fresh domxml-to-native conversion matches. The offline conversion uses domain
ID-1 and a monitor path; the comparison explicitly projects only those two fields
to their runtime forms. No full native domain was created, and no VFIO opened.
This is complete conversion compatibility, not live accelerated macOS proof.
The separately captured earlier KVM CPU properties also pass the new checker;
that is a recheck of existing one-vCPU evidence, not a new CPU/hardware run.

The native backend compares actual KVM status, CPU-index/socket/core/thread and
unique QOM paths, and queries properties by those paths. Expensive CPU property
queries occur at initial admission, resume/process changes and every30seconds;
the200ms lifecycle loop still observes argv/PID/status. This avoids roughly100
QOM requests per second for a4-vCPU VM. Console throughput is not measured here.

## Host macvtap versus the software TAP

Linux reference238650ef6c7c7cca08e032527329424c9fbd70e5, local checkout
`~/src/ref/linux`, establishes these distinctions:

- `drivers/net/macvtap.c:150–185`: tap<ifindex> is the name, but the character
  device minor is allocated independently.
- `drivers/net/tap.c:448–476,943–958`: TUNGETIFF returns the attached interface
  name/flags or ENOLINK; default queue flags include VNET_HDR (0x5002).
- `drivers/net/tap.c:994–1009`: read-only SIOCGIFHWADDR obtains the actual attached
  device MAC, even when the caller's network namespace differs.
- `drivers/net/tap.c:1033–1042`: macvtap tap_fops lacks show_fdinfo. The iff field
  seen on isolated generic TAP belongs to `drivers/net/tun.c:3593–3627`.

The host read-only snapshot confirms rgpu-lan ifindex6 maps to `/dev/tap6`, but
its character device is major511/minor1. It records host network namespace,
interface MAC, lower-link identity, bridge kind/mode and sysfs/devnode mapping.
No host macvtap descriptor was opened for this snapshot.

The inherited-FD checker compares character rdev, TUNGETIFF name/flags and actual
SIOCGIFHWADDR MAC. After handoff, stat of the owned QEMU FD must match the original
container descriptor's rdev/inode/device. It never reopens that FD, which could
create another queue. Host node inode is deliberately not required to equal the
container's device-node inode. Production manifest binding and immediate host
revalidation are still required when integrating the launcher.

## Real software validation and corrected race

A real isolated two-NIC TCG guest verifies the native-shaped hub, LAN NIC and
separate user-mode NAT report with the new parser. The first run caught a brief
shutdown race: process scan no longer found QEMU, but its pinned PID had not yet
been reaped. The bounded reconciliation now waits for both registry absence and
exact process exit. Two subsequent runs each verify network attachment before
resume, report guest-shutdown, preserve process-exit evidence and exit their
containers naturally with status0. Neither opens host networking, KVM or VFIO.

This does not prove a live macvtap transfer: both repeat tests use an isolated
generic TAP. The actual inherited macvtap checks remain to be exercised in the
admitted native launch. No test VM remains active; the host sleep:idle blocker
remains active.

## Next integration boundary

These modules have no launch CLI. `vm-entry.sh`, the manifest/card contract and
host supervisor must now select and hash this exact profile, bind network/plan
identity to the run, retain the original absolute deadline and independently
correlate container/QEMU identity. The direct native GPU path remains unchanged.
Only then can the existing cycle harness qualify libvirt-managed macOS and its
SPICE console. No product milestone is claimed from these verifier tests alone.

Full host suite:1,077 tests pass,3 skipped.
[Evidence](libvirt-native-profile-evidence-20261009.json).
