/* Native negative control, ONLY after a successfully armed snapshot owner exits.
 * No pixel reads/writes or raw register access. Not an independent RETIRE readback.
 * clang -O2 console_snapshot_retired.c -framework IOKit -framework CoreFoundation
 */
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOKitLib.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc != 2 || strcmp(argv[1], "--expect-retired")) return 2;
    io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault,
        IOServiceMatching("RaphaelConsole"));
    if (!service) return 3;
    CFTypeRef property = IORegistryEntryCreateCFProperty(service,
        CFSTR("SnapshotProtocol"), kCFAllocatorDefault, 0);
    int protocol = 0;
    int supported = property && CFGetTypeID(property) == CFNumberGetTypeID() &&
        CFNumberGetValue((CFNumberRef)property, kCFNumberIntType, &protocol) && protocol == 1;
    if (property) CFRelease(property);
    if (!supported) { IOObjectRelease(service); return 4; }
    io_connect_t connection = IO_OBJECT_NULL;
    kern_return_t opened = IOServiceOpen(service, mach_task_self(), 0, &connection);
    IOObjectRelease(service);
    if (opened != KERN_SUCCESS) { printf("open=%x\n", opened); return 5; }
    kern_return_t armed = IOConnectCallScalarMethod(connection, 1, NULL, 0, NULL, NULL);
    mach_vm_address_t address = 0;
    mach_vm_size_t length = 0;
    kern_return_t mapped = IOConnectMapMemory64(connection, 1, mach_task_self(),
        &address, &length, kIOMapAnywhere);
    if (mapped == KERN_SUCCESS)
        IOConnectUnmapMemory64(connection, 1, mach_task_self(), address);
    if (armed == KERN_SUCCESS)
        IOConnectCallScalarMethod(connection, 3, NULL, 0, NULL, NULL);
    kern_return_t closed = IOServiceClose(connection);
    int passed = armed == kIOReturnNotReady && mapped == kIOReturnNotReady && closed == KERN_SUCCESS;
    printf("SNAPSHOT_RETIRED passed=%d arm=%x staging_map=%x close=%x scope=bridge-regrant-refusal\n",
        passed, armed, mapped, closed);
    return passed ? 0 : 6;
}
