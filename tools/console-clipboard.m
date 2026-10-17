// External support helper: never part of the sealed capture application.
// Binary stdout: int64 changeCount, uint32 status (0 unchanged,1 text,2 unavailable), UTF-8.
#import <AppKit/AppKit.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#define TEXT_LIMIT 65536
static int emit(NSInteger count, uint32_t status, NSData *data) {
    int64_t value = count;
    if (fwrite(&value, sizeof(value), 1, stdout) != 1 ||
        fwrite(&status, sizeof(status), 1, stdout) != 1) return 4;
    if (data && fwrite(data.bytes, 1, data.length, stdout) != data.length) return 4;
    return fflush(stdout) ? 4 : 0;
}
int main(int argc, const char **argv) {
    @autoreleasepool { @try {
        if (argc != 3 || (strcmp(argv[1], "read") && strcmp(argv[1], "write"))) return 2;
        errno = 0; char *end = NULL; long long expected = strtoll(argv[2], &end, 10);
        if (errno || !*argv[2] || *end || expected < -1 || getuid() == 0 || getuid() != geteuid()) return 2;
        alarm(2); // Parent deadline is shorter; also bound a standalone invocation.
        NSPasteboard *board = NSPasteboard.generalPasteboard;
        NSInteger count = board.changeCount;
        if (!strcmp(argv[1], "read")) {
            // -1 establishes a baseline without reading existing clipboard contents.
            if (expected == -1 || count == expected) return emit(count, 0, nil);
            NSString *text = [board stringForType:NSPasteboardTypeString];
            if (text.length > TEXT_LIMIT) return emit(count, 2, nil);
            NSData *data = [text dataUsingEncoding:NSUTF8StringEncoding allowLossyConversion:NO];
            if (board.changeCount != count) return 3;
            if (!data || data.length > TEXT_LIMIT || memchr(data.bytes, 0, data.length)) return emit(count, 2, nil);
            return emit(count, 1, data);
        }
        unsigned char bytes[TEXT_LIMIT + 1]; size_t size = fread(bytes, 1, sizeof(bytes), stdin);
        if (ferror(stdin) || size > TEXT_LIMIT || memchr(bytes, 0, size)) return 2;
        NSString *text = [[NSString alloc] initWithBytes:bytes length:size encoding:NSUTF8StringEncoding];
        if (!text || expected < 0 || board.changeCount != expected) return 3;
        // AppKit has no atomic compare-and-set. Recheck immediately before taking
        // ownership; setString fails if another owner intervenes after clear.
        NSInteger owned = [board clearContents];
        if (![board setString:text forType:NSPasteboardTypeString] || board.changeCount != owned) return 3;
        return emit(owned, 0, nil);
    } @catch (NSException *exception) { (void)exception; return 4; } }
}
