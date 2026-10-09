/* Isolated 16-bit guest. Wait for a serial byte, then request ACPI S5.
 * QEMU hw/acpi/core.c: sleep-enable + sleep-type0 -> GUEST_SHUTDOWN.
 * No guest filesystem exists; this does not establish macOS clean shutdown.
 */
.code16
.global _start
_start:
    cli
    xor %ax,%ax
    mov %ax,%ds
    mov %ax,%ss
    mov $0x7c00,%sp
    mov $0x3f8,%dx
    mov $'R',%al
    out %al,%dx
wait_input:
    mov $0x3fd,%dx
    in %dx,%al
    test $1,%al
    jz wait_input
    mov $0x3f8,%dx
    in %dx,%al
    mov $0x604,%dx
    mov $0x2000,%ax
    out %ax,%dx
halt:
    hlt
    jmp halt
.org 510
.word 0xaa55
