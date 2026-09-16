// Native provider + bounded key enumeration. Does not read key values.
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#include <signal.h>
#include <unistd.h>
#include <string.h>

static void expired(int sig) { (void)sig; _exit(124); }
static BOOL query(io_connect_t connection, uint32_t index, uint32_t *key, uint8_t *result) {
    uint8_t input[168] = {0}, output[168] = {0};
    input[42] = 8;
    memcpy(input + 44, &index, sizeof(index));
    size_t size = sizeof(output);
    kern_return_t kr = IOConnectCallStructMethod(connection, 2, input, sizeof(input), output, &size);
    if (kr != KERN_SUCCESS || size != sizeof(output)) return NO;
    memcpy(key, output, sizeof(*key));
    *result = output[40];
    return YES;
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc != 2 || strcmp(argv[1], "VirtualSMC") != 0) return 2;
        signal(SIGALRM, expired); alarm(60);
        io_iterator_t iterator = IO_OBJECT_NULL;
        if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("AppleSMC"), &iterator)) return 3;
        io_service_t service = IOIteratorNext(iterator), extra = IOIteratorNext(iterator);
        IOObjectRelease(iterator);
        if (!service || extra) {
            if (service) IOObjectRelease(service);
            if (extra) IOObjectRelease(extra);
            fprintf(stderr, "expected exactly one AppleSMC service\n"); return 4;
        }
        io_registry_entry_t parent = IO_OBJECT_NULL;
        io_name_t parentClass = {0};
        uint64_t registryID = 0;
        BOOL providerOK = IORegistryEntryGetParentEntry(service, kIOServicePlane, &parent) == KERN_SUCCESS;
        providerOK = providerOK && IOObjectGetClass(parent, parentClass) == KERN_SUCCESS;
        providerOK = providerOK && strcmp(parentClass, "VirtualSMC") == 0;
        providerOK = providerOK && IORegistryEntryGetRegistryEntryID(service, &registryID) == KERN_SUCCESS;
        if (parent) IOObjectRelease(parent);
        if (!providerOK) {
            IOObjectRelease(service); fprintf(stderr, "AppleSMC is not attached to VirtualSMC\n"); return 5;
        }
        io_connect_t connection = IO_OBJECT_NULL;
        kern_return_t opened = IOServiceOpen(service, mach_task_self(), 0, &connection);
        IOObjectRelease(service);
        if (opened) return 6;
        NSMutableArray *keys = [NSMutableArray array];
        NSMutableSet *unique = [NSMutableSet set];
        BOOL passed = YES, ended = NO;
        uint32_t count = 0;
        for (uint32_t index = 0; index < 4096; index++) {
            uint32_t key = 0; uint8_t result = 0;
            if (!query(connection, index, &key, &result)) { passed = NO; break; }
            if (result == 0xb8) { ended = YES; count = index; break; }
            if (result != 0 || key == 0) { passed = NO; break; }
            NSString *hex = [NSString stringWithFormat:@"%08x", key];
            if ([unique containsObject:hex]) { passed = NO; break; }
            [unique addObject:hex]; [keys addObject:hex];
        }
        passed = passed && ended && count > 0;
        // Repeat valid entries and terminal responses: no cursor leakage or wraparound.
        for (uint32_t index = 0; passed && index < count; index++) {
            uint32_t key = 0; uint8_t result = 0;
            passed = query(connection, index, &key, &result) && result == 0 &&
                [[NSString stringWithFormat:@"%08x", key] isEqual:keys[index]];
        }
        uint32_t ends[] = {count, count + 1, UINT32_MAX};
        for (unsigned n = 0; passed && n < 3; n++) {
            uint32_t key = 0; uint8_t result = 0;
            passed = query(connection, ends[n], &key, &result) && result == 0xb8;
        }
        IOServiceClose(connection);
        NSDictionary *record = @{@"passed": @(passed), @"provider": @"VirtualSMC",
            @"apple_smc_registry_id": @(registryID), @"key_count": @(count),
            @"keys_hex": keys, @"end_result": ended ? @"0xb8" : @"not-observed",
            @"key_values_read": @NO};
        NSData *json = [NSJSONSerialization dataWithJSONObject:record options:NSJSONWritingSortedKeys error:nil];
        if (!json) return 7;
        fwrite(json.bytes, 1, json.length, stdout); putchar('\n'); fflush(stdout);
        return passed ? 0 : 1;
    }
}
