#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
int main(int argc, char **argv) {
    if (argc != 3) { fprintf(stderr, "usage: segdump image-path outdir\n"); return 2; }
    void *h = dlopen(argv[1], RTLD_LAZY | RTLD_LOCAL);
    if (!h) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 1; }
    for (uint32_t i = 0; i < _dyld_image_count(); ++i) {
        const char *name = _dyld_get_image_name(i);
        if (strcmp(name, argv[1]) != 0) continue;
        const struct mach_header_64 *mh = (const struct mach_header_64 *)_dyld_get_image_header(i);
        intptr_t slide = _dyld_get_image_vmaddr_slide(i);
        printf("image %s header %p slide %#lx\n", name, (void *)mh, (long)slide);
        const struct load_command *lc = (const struct load_command *)(mh + 1);
        for (uint32_t c = 0; c < mh->ncmds; ++c, lc = (const struct load_command *)((const char *)lc + lc->cmdsize)) {
            if (lc->cmd != LC_SEGMENT_64) continue;
            const struct segment_command_64 *seg = (const struct segment_command_64 *)lc;
            printf("segment %s vmaddr %#llx vmsize %#llx fileoff %#llx\n", seg->segname,
                   seg->vmaddr, seg->vmsize, seg->fileoff);
            const struct section_64 *sec = (const struct section_64 *)(seg + 1);
            for (uint32_t s = 0; s < seg->nsects; ++s)
                printf("  section %s,%s addr %#llx size %#llx\n", sec[s].segname, sec[s].sectname,
                       sec[s].addr, sec[s].size);
            if (strcmp(seg->segname, "__TEXT") && strcmp(seg->segname, "__DATA_CONST") &&
                strcmp(seg->segname, "__DATA") && strcmp(seg->segname, "__AUTH_CONST")) continue;
            char path[1024];
            snprintf(path, sizeof(path), "%s/%s.bin", argv[2], seg->segname);
            FILE *f = fopen(path, "wb");
            if (!f) { perror(path); continue; }
            fwrite((const void *)(seg->vmaddr + slide), 1, seg->vmsize, f);
            fclose(f);
        }
        return 0;
    }
    fprintf(stderr, "image not found among %u\n", _dyld_image_count());
    return 1;
}
