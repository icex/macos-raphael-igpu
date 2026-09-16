// Native AppleSMC user-client enumeration. Never reads key values or OSK data.
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#include <signal.h>
#include <unistd.h>
static void expired(int s) { (void)s; _exit(124); }
int main(void) {
    signal(SIGALRM, expired); alarm(60);
    io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault,
                                                      IOServiceMatching("AppleSMC"));
    io_connect_t connection = IO_OBJECT_NULL;
    if (!service || IOServiceOpen(service, mach_task_self(), 0, &connection)) return 2;
    IOObjectRelease(service);
    unsigned failures = 0;
    for (uint32_t index = 0; index < 8; index++) {
        uint8_t input[168] = {0}, output[168] = {0};
        input[42] = 8;
        memcpy(input + 44, &index, sizeof(index));
        size_t length = sizeof(output);
        kern_return_t kr = IOConnectCallStructMethod(connection, 2, input,
                                sizeof(input), output, &length);
        uint32_t key = 0; memcpy(&key, output, sizeof(key));
        printf("index=%u kernel=0x%x result=0x%02x size=%zu key=0x%08x\n",
               index, kr, output[40], length, key);
        fflush(stdout);
        if (kr || length < 48 || output[40] != (index < 6 ? 0 : 0xb8)) failures++;
    }
    IOServiceClose(connection);
    printf("failures=%u\n", failures);
    return failures ? 1 : 0;
}
