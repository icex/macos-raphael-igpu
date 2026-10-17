#include "KernelSiteCatalog.hpp"
#include <cassert>
#include <cstring>
using namespace RaphaelKernelSites;
int main() {
    uint8_t image[256] {};
    const uint8_t code[] = {0x55,0x48,0x89,0xe5,0xe8,1,2,3,4,0x48,0x8b,0x87,0x31,5,0,0};
    const uint8_t mask[] = {255,255,255,255,255,0,0,0,0,255,255,255,255,255,255,255};
    Site site {0,0x1234,nullptr,0,0,code,mask,sizeof(code)};
    memcpy(image+48,code,sizeof(code)); image[54]=99;
    assert(unique(image,sizeof(image),32,128,site,0x100000)==0x100030);
    // Link displacement changes are admitted, native object-layout changes refused.
    image[60]=0x32; assert(!unique(image,sizeof(image),32,128,site,0x100000));
    image[60]=0x31;
    memcpy(image+80,code,sizeof(code)); assert(!unique(image,sizeof(image),32,128,site,0x100000));
    // Code-like bytes outside the executable range cannot satisfy discovery.
    assert(unique(image,sizeof(image),32,70,site,0x100000)==0x100030);
    assert(!unique(image,sizeof(image),48,55,site,0x100000));
    assert(!unique(image,sizeof(image),128,32,site,0x100000));
    assert(!unique(image,sizeof(image),0,300,site,0x100000));
    assert(!unique(image,sizeof(image),32,70,site,UINTPTR_MAX-16));
    assert(!matches(nullptr,sizeof(image),48,site));
    // Interior code can move within its owner, but never bind to another method.
    site.scopeEndSymbol = "nextMethod";
    assert(resolve(image,sizeof(image),32,128,site,0x100000,0x100020,0x100046)==0x100030);
    assert(!resolve(image,sizeof(image),32,128,site,0x100000,0x100020,0x100070));
    assert(!resolve(image,sizeof(image),32,128,site,0x100000,0x100020,0));
    assert(!resolve(image,sizeof(image),32,128,site,0x100000,0x100020,0x100090));
    site.scopeEndSymbol = nullptr;
    // Named entries cannot fall back to a matching unrelated function.
    assert(!resolve(image,sizeof(image),32,128,site,0x100000,0x100020));
    assert(resolve(image,sizeof(image),32,128,site,0x100000,0x100030)==0x100030);
    // Complete entry guards admit call relocation but reject layout drift.
    assert(covers(image,sizeof(image),48,site,sizeof(code)));
    assert(!covers(image,sizeof(image),48,site,sizeof(code)+1));
    site.targetDelta=4;
    assert(covers(image,sizeof(image),52,site,sizeof(code)-4));
    assert(!covers(image,sizeof(image),3,site,1));
    site.targetDelta=0;
    uint8_t after[sizeof(code)], replacement[sizeof(code)];
    memcpy(after,code,sizeof(code)); after[12]=0x32;
    assert(patchDelta(image+48,code,after,replacement,sizeof(code)));
    assert(replacement[6]==99 && replacement[12]==0x32);
    image[60]=0x33;
    memset(replacement,0xaa,sizeof(replacement));
    assert(!covers(image,sizeof(image),48,site,sizeof(code)));
    assert(!patchDelta(image+48,code,after,replacement,sizeof(code)));
    for (auto byte : replacement) assert(byte==0xaa);
    assert(!patchDelta(nullptr,code,after,replacement,sizeof(code)));
    // Compile every generated contract, including the alternative families.
    for (const auto &entry : catalog) {
        assert(entry.length && entry.targetDelta < entry.length);
        assert(!entry.alternativeCount || entry.alternatives);
        for (size_t n=0;n<entry.alternativeCount;++n) {
            const auto &variant=entry.alternatives[n];
            assert(variant.image==entry.image && variant.reference==entry.reference);
            assert(variant.length && variant.targetDelta<variant.length);
        }
    }
}
