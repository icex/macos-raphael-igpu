# Candidate345: native explicit SPICE refresh experiment

Status: prepared for testing; this document alone records no native result.

Candidate343 is the delivered stock-QEMU baseline with a visible native Metal
virt-manager desktop and retained native guest-shutdown receipt. Candidate342
measured about29.82 manager-buffer token updates/s at1080p and18.50 at1080HiDPI.
Those samples include observer cost and occasional intermediate region updates.

Candidate344's compression-off software A/B isolates QEMU's nongl30ms default:
stock explicit60 has no effect; the opt-in patched listener reaches about60
sampled tokens/s with an acknowledged60/s producer. Default behavior is unchanged.
The separate single-rectangle experiment is diagnostic and is **not** included
in this native image. [Software evidence](spice-refresh-ab-20261009.md).

## Exact experimental change

Fresh QEMU10.1.2 archive plus only the explicit nongl refresh patch is built
inside the existing pinned VM image, with KVM, SPICE, VNC and slirp enabled.
A derived image replaces only `/usr/sbin/qemu-system-x86_64`; native guest driver
source remains unchanged. [Image, source and build hashes](native-refresh-image-20261009.json).
This is an experimental patched-QEMU profile, not a change to the delivered
stock-QEMU baseline or a claim of stock60Hz console support.

The exact manifest option `CONSOLE_REFRESH=60` selects this experiment. It is
forwarded through systemd/container launch, bound into admission before domain
creation and independently checked before paused-domain resume. The planner
retains libvirt's owned private SPICE socket and adds only the supplemental
`-spice max-refresh-rate=60` argument. QEMU's SPICE option group merges options;
the full generated argv and running graphics topology must match exactly.
Default profiles gain no supplemental argument. Unknown rates, changed endpoints,
GL/network additions, stale identities or mismatched admission still refuse.

## Native discriminator

After isolated conversion and full host checks, run metal-190 through cycle.py.
Verify native Metal, awake desktop and actual manager connection, then use the
same bounded token fixture and in-process sampler as342 at native1080p and
1080HiDPI. Record producer draws, valid unique tokens, incomplete samples and
sampling overhead separately. Improvement at640×480 in software does not predict
native4K throughput. No QMP screendump or forced refresh during measurement.

Close the viewer, verify the same guest is alive, and request harness shutdown.
Require valid capture, actual libvirt terminal receipt and authorizing GPU recovery.
Keep partial-region sampling distinct from source-copy races and final host scanout.
This experiment cannot qualify every application, crash path or independent boot.
