#include <stdint.h>

/* QEMU's x86 -kernel loader recognizes this Multiboot v1 header. */
__attribute__((section(".multiboot"), used))
static const uint32_t multiboot_header[] = {
    0x1badb002u, 0x00000000u, 0xe4524ffeu
};

extern const unsigned char _binary_payload_bin_start[];
extern const unsigned char _binary_payload_bin_end[];

static inline void out8(uint16_t port, uint8_t value) {
    __asm__ volatile("outb %0, %1" : : "a"(value), "Nd"(port));
}

static inline uint8_t in8(uint16_t port) {
    uint8_t value;
    __asm__ volatile("inb %1, %0" : "=a"(value) : "Nd"(port));
    return value;
}

static void uart_init(uint16_t base) {
    out8(base + 1, 0x00); /* IER: polling only. */
    out8(base + 3, 0x80); /* DLAB. */
    out8(base + 0, 0x01); /* 115200 baud divisor. */
    out8(base + 1, 0x00);
    out8(base + 3, 0x03); /* 8-N-1. */
    out8(base + 2, 0xc7); /* Enable and clear FIFO. */
    out8(base + 4, 0x03); /* DTR and RTS. */
}

static void uart_putc(uint16_t base, uint8_t value) {
    while ((in8(base + 5) & 0x20) == 0) {}
    out8(base, value);
}

static void uart_write(uint16_t base, const char *text) {
    while (*text) uart_putc(base, (uint8_t)*text++);
}

void guest_main(void) {
    static const char ready[] =
        "RGPU_UART_READY v=1 b=0123456789abcdef0123456789abcdef port=2\n";
    static const char malformed_a[] =
        "console-noise RGPU_CR2 v=1 b=broken s=not-a-snapshot ";
    static const char malformed_b[] =
        "AMDRadeon dump interleave RGPU_END2 without-fields\n";
    const unsigned char *cursor = _binary_payload_bin_start;
    const unsigned char *end = _binary_payload_bin_end;
    uint32_t interval = 0;

    uart_init(0x3f8);
    uart_init(0x2f8);
    uart_write(0x2f8, ready);
    uart_write(0x3f8, "COM1-BEGIN\n");
    while (cursor != end) {
        uart_putc(0x2f8, *cursor++);
        if (++interval == 97) {
            uart_write(0x3f8, malformed_a);
            uart_write(0x3f8, malformed_b);
            interval = 0;
        }
    }
    uart_write(0x3f8, "COM1-END\n");
    out8(0xf4, 0x2a);
    for (;;) __asm__ volatile("hlt");
}

__attribute__((naked, section(".text.entry"), noreturn))
void _start(void) {
    __asm__ volatile(
        "cli\n"
        "mov $stack_top, %esp\n"
        "call guest_main\n"
        "1: hlt\n"
        "jmp 1b\n");
}

__attribute__((section(".bss.stack"), aligned(16)))
unsigned char stack[16384];
__asm__(".global stack_top\nstack_top = stack + 16384");
