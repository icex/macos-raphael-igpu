# PerfPowerServices CPU loop: missing QEMU SMC enumeration

Run 9695b71b4eb9db3f8b99eb42e8814970, candidate277, colorrepro attempt.
PerfPowerServices PID152 consumed 100% CPU. The 4002-sample profile places the
busy thread in PLSMCMetricsAgent getAllKeys / SMCGetKeyFromIndex. Disassembly
shows it increments the index until libSMC returns -4; observed return was -3
at index 0x02312bdb. libSMC maps SMC result 0xb8 to -4, other nonzero results to -3.
QEMU10.1.2 applesmc.c defines enumeration command0x12 and BAD_INDEX0xb8 but
implements neither enumeration nor its terminal result.

One-shot diagnostic: at the verified return instruction, change one -3 return
to -4. PID152 leaves the loop and remains alive at0.0% CPU, cumulative CPU25:58.96
several minutes later. No service disabling or persistent guest patch. This
establishes the termination condition, not reboot durability.

Patch patches/qemu/10.1.2-applesmc-key-enumeration.patch implements command0x12,
four-byte big-endian index, four-byte key result, and0xb8 past the six existing
keys. Existing key reads and interrupted-command handshake are preserved.
It does not add sensor emulation or key metadata command0x13.

Standalone tools/qemu-smc-probe.py tests the emulated I/O ports without KVM,
VFIO or disks, with a dummy OSK. Checks enumeration, large/out-of-range indices,
existing key reads, error recovery and interruption. Original packaged QEMU
initially lacked the qtest accelerator; that launch failure is not protocol
evidence. Repeated both binaries with paused TCG and the qtest transport:
original fails the0x12 command acknowledgment; patched passes every check.

Build: official qemu10.1.2 source, same pinned base image
sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c.
Configure --prefix=/usr --target-list=x86_64-softmmu --disable-docs
--disable-werror --disable-guest-agent --disable-download --enable-slirp
--enable-kvm --enable-vnc; ninja -j4 qemu-system-x86_64. Only replacement binary
is copied into the derived image. Native guest cold-start verification pending.

Artifacts: /home/bogdan/macos-vm/run/research/qemu-smc-20260916/{build-prefix.log,
qtest-original.txt,qtest-patched.txt,image-build.log}; run results include
perfpower-sample.txt, perfpower-lldb.txt, perfpower-smc-implementation.txt,
smc-end-control.txt and perfpower-after.txt. No real OSK values are recorded.

Primary protocol references: https://gitlab.com/qemu-project/qemu/-/blob/v10.1.2/hw/misc/applesmc.c
and https://github.com/torvalds/linux/blob/master/drivers/hwmon/applesmc.c .

## First native verification rejected

Actual patched image2ada1bb2323f, binary1d48acdf..., run ec5d03f7433ad8f4151f35644c5e38c9
(smcfinal) still consumes CPU (~34%). Sampling still shows getAllKeys; index15
returns -3 after timeout. Initial patch incorrectly required a fifth length byte.
VirtualSMC kern_pmio.cpp provides the missing discriminator: command0x12 responds
after sizeof(SMC_KEY_INDEX), four bytes, unlike0x10 read-value. The Linux caller
writes an extra byte for compatibility; that is not a required PMIO argument.
Corrected patch completes enumeration on byte4; revised test sends exactly four
bytes and passes. Do not count the first isolated test as native qualification.
Source: https://github.com/acidanthera/VirtualSMC/blob/master/VirtualSMC/kern_pmio.cpp .
The service has not been disabled or patched in this guest. Native retest pending.
