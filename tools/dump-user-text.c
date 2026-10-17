#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
int main(int argc,char **argv) {
    if(argc!=3)return 2;
    void *handle=dlopen(argv[1],RTLD_LAZY|RTLD_LOCAL);
    if(!handle){fprintf(stderr,"dlopen: %s\n",dlerror());return 3;}
    for(uint32_t i=0;i<_dyld_image_count();i++) {
        const char *name=_dyld_get_image_name(i);
        if(!name||strcmp(name,argv[1]))continue;
        const struct mach_header_64 *h=(const void *)_dyld_get_image_header(i);
        if(h->magic!=MH_MAGIC_64||h->cputype!=CPU_TYPE_X86_64)return 4;
        const uint8_t *at=(const void *)(h+1); const uint8_t *end=at+h->sizeofcmds;
        if(h->sizeofcmds>16384||h->ncmds>256)return 4;
        for(uint32_t j=0;j<h->ncmds;j++) {
            if(at+sizeof(struct load_command)>end)return 4;
            const struct load_command *lc=(const void *)at;
            if(lc->cmdsize<8||at+lc->cmdsize>end)return 4;
            if(lc->cmd==LC_SEGMENT_64&&lc->cmdsize>=sizeof(struct segment_command_64)) {
                const struct segment_command_64 *s=(const void *)lc;
                if(!strncmp(s->segname,"__TEXT",16)) {
                    if(s->vmsize<32||s->vmsize>32*1024*1024)return 4;
                    FILE *f=fopen(argv[2],"wb");if(!f)return 5;
                    int ok=fwrite((const void *)(s->vmaddr+_dyld_get_image_vmaddr_slide(i)),1,s->vmsize,f)==s->vmsize;
                    return fclose(f)||!ok?5:0;
                }
            }
            at+=lc->cmdsize;
        }
    }
    return 6;
}
