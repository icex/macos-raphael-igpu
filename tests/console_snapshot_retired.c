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
    mach_vm_address_t legacy_address = 0;
    mach_vm_size_t legacy_length = 0;
    kern_return_t legacy = IOConnectMapMemory64(connection, 0, mach_task_self(),
        &legacy_address, &legacy_length, kIOMapAnywhere);
    kern_return_t legacy_unmap = kIOReturnNotReady;
    if (legacy == KERN_SUCCESS)
        legacy_unmap = IOConnectUnmapMemory64(connection, 0, mach_task_self(), legacy_address);
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
    int passed = legacy == KERN_SUCCESS && legacy_address != 0 &&
        legacy_length == 64ULL * 1024 * 1024 && legacy_unmap == KERN_SUCCESS &&
        armed == kIOReturnNotReady &&
        (mapped == kIOReturnNotReady || mapped == kIOReturnBadArgument) &&
        closed == KERN_SUCCESS;
    printf("SNAPSHOT_RETIRED passed=%d legacy_map=%x legacy_address=%llx legacy_length=%llu legacy_unmap=%x arm=%x staging_map=%x staging_address=%llx staging_length=%llu close=%x scope=bridge-regrant-refusal\n",
        passed, legacy, (unsigned long long)legacy_address,
        (unsigned long long)legacy_length, legacy_unmap, armed, mapped,
        (unsigned long long)address, (unsigned long long)length, closed);
    return passed ? 0 : 6;
}
