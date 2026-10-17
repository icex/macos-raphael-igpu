#include "TextureDiagParser.hpp"
#include <cassert>
#include <fstream>
#include <iterator>
#include <vector>
using namespace RaphaelTextureDiag;
struct Input { const std::vector<uint8_t> *image; };
static bool readImage(void *opaque, uint64_t address, void *out, size_t size) {
    auto &image=*static_cast<Input *>(opaque)->image;
    if(address<0x100000 || address-0x100000>image.size() || size>image.size()-(address-0x100000))return false;
    memcpy(out,image.data()+address-0x100000,size);return true;
}
static void synthetic() {
    std::vector<uint8_t> image(0x40000);
    Input input {&image};
    auto target=kTextureTarget;enableDynamic(target);
    const auto &site=*target.dynamicSite;
    // Move the constructor across a streaming-read boundary and derive a new
    // metadata bit. No historical image UUID or instruction offset is consulted.
    const size_t start=0x1000+65536-40;
    memcpy(image.data()+start,site.bytes,site.length);
    const char metadata[]="{AMD_DeviceSettings=\"prefix\"b26\"enableTexturePipeBankXor\"b1}";
    memcpy(image.data()+0x23000,metadata,sizeof(metadata));
    Result found {};
    assert(discoverDynamic(readImage,&input,0x100000,0x1000,0x20000,0x23000,sizeof(metadata),target,found));
    assert(found.instructionAddress==0x100000+start+site.targetDelta);
    const uint64_t original=u64(found.liveInstruction+2),replacement=u64(found.replacementInstruction+2);
    assert((original^replacement)==(1ULL<<26));
    memcpy(image.data()+start+site.targetDelta,found.replacementInstruction,target.instructionSize);
    Result clear {};
    assert(discoverDynamic(readImage,&input,0x100000,0x1000,0x20000,0x23000,sizeof(metadata),target,clear));
    assert(clear.alreadyPatched);
    memcpy(image.data()+0x4000,site.bytes,site.length);
    Result duplicate {};
    assert(!discoverDynamic(readImage,&input,0x100000,0x1000,0x20000,0x23000,sizeof(metadata),target,duplicate));
    memset(image.data()+0x4000,0,site.length);
    Result absent {};
    assert(!discoverDynamic(readImage,&input,0x100000,0x1000,0x20000,0,0,target,absent));
    // The GE parameter-cache family shares the constructor but targets its second
    // default mask; both patches coexist and neither disturbs the other's immediate.
    image.assign(image.size(),0);
    auto gePc=kGePcOversubTarget;enableDynamic(gePc);
    assert(gePc.dynamicSite && gePc.settingField && gePc.dynamicSite->targetDelta!=site.targetDelta);
    memcpy(image.data()+start,gePc.dynamicSite->bytes,gePc.dynamicSite->length);
    const char settings[]="{AMD_DeviceSettings=\"low\"b27\"enableTexturePipeBankXor\"b1"
        "\"mid\"b14\"allowGePcAllocOverSub\"b1}";
    memcpy(image.data()+0x23000,settings,sizeof(settings));
    Result gePcFound {};
    assert(discoverDynamic(readImage,&input,0x100000,0x1000,0x20000,0x23000,sizeof(settings),gePc,gePcFound));
    assert(gePcFound.instructionAddress==0x100000+start+gePc.dynamicSite->targetDelta);
    assert((u64(gePcFound.liveInstruction+2)^u64(gePcFound.replacementInstruction+2))==(1ULL<<42));
    memcpy(image.data()+start+gePc.dynamicSite->targetDelta,gePcFound.replacementInstruction,10);
    Result textureAfterGePc {};
    assert(discoverDynamic(readImage,&input,0x100000,0x1000,0x20000,0x23000,sizeof(settings),target,textureAfterGePc));
    assert(textureAfterGePc.instructionMatch &&
           (u64(textureAfterGePc.liveInstruction+2)^u64(textureAfterGePc.replacementInstruction+2))==(1ULL<<27));
    memcpy(image.data()+start+site.targetDelta,textureAfterGePc.replacementInstruction,10);
    Result gePcAfterTexture {};
    assert(discoverDynamic(readImage,&input,0x100000,0x1000,0x20000,0x23000,sizeof(settings),gePc,gePcAfterTexture));
    assert(gePcAfterTexture.alreadyPatched);
    // A longer alternative must match across the last byte of a streaming chunk.
    image.assign(image.size(),0);
    auto feedback=kFeedbackTarget;enableDynamic(feedback);
    assert(feedback.dynamicSite->alternativeCount);
    const auto &alternative=feedback.dynamicSite->alternatives[0];
    const size_t crossing=0x1000+65536-1;
    memcpy(image.data()+crossing,alternative.bytes,alternative.length);
    Result current {};
    assert(discoverDynamic(readImage,&input,0x100000,0x1000,0x20000,0,0,feedback,current));
    assert(current.instructionAddress==0x100000+crossing+alternative.targetDelta);
    memcpy(image.data()+crossing+alternative.targetDelta,current.replacementInstruction,
           feedback.instructionSize);
    Result patchedFeedback {};
    assert(discoverDynamic(readImage,&input,0x100000,0x1000,0x20000,0,0,feedback,patchedFeedback));
    assert(patchedFeedback.alreadyPatched);
    // Even when different families each occur once, two target addresses refuse.
    memcpy(image.data()+0x3000,feedback.dynamicSite->bytes,feedback.dynamicSite->length);
    Result ambiguousFamilies {};
    assert(!discoverDynamic(readImage,&input,0x100000,0x1000,0x20000,0,0,feedback,ambiguousFamilies));
}
int main(int argc,char **argv) {
    if(argc==1){synthetic();return 0;}
    assert(argc==2);
    std::ifstream stream(argv[1],std::ios::binary);
    std::vector<uint8_t> image((std::istreambuf_iterator<char>(stream)),{});
    assert(image.size()>32);
    Input input {&image};
    uint64_t codeOffset=0,codeSize=0,metadataOffset=0,metadataSize=0;
    size_t at=32;
    for(unsigned i=0;i<u32(image.data()+16);i++) {
        auto cmd=image.data()+at; auto size=u32(cmd+4);
        if(u32(cmd)==0x19&&!strncmp(reinterpret_cast<const char *>(cmd+8),"__TEXT",16)) {
            auto vm=u64(cmd+24);
            for(unsigned j=0;j<u32(cmd+64);j++) {
                auto section=cmd+72+80*j;
                if(!strncmp(reinterpret_cast<const char *>(section),"__text",16)) {codeOffset=u64(section+32)-vm;codeSize=u64(section+40);}
                if(!strncmp(reinterpret_cast<const char *>(section),"__objc_methtype",16)) {metadataOffset=u64(section+32)-vm;metadataSize=u64(section+40);}
            }
        }
        at+=size;
    }
    const Target *targets[] = {&kTextureTarget,&kFeedbackTarget,&kGePcOversubTarget,&kVcnDpmTarget,&kVcnPresetValueTarget,&kVcnPresetHevcGateTarget,&kVcnPresetAvcGateTarget};
    const bool metal=metadataSize!=0;
    for(unsigned i=0;i<7;i++) {
        if((i<3)!=metal)continue;
        auto target=*targets[i];enableDynamic(target);assert(target.dynamicSite);
        Result result {};
        assert(discoverDynamic(readImage,&input,0x100000,codeOffset,codeSize,metadataOffset,metadataSize,target,result));
        assert(result.compatible&&result.found&&(result.instructionMatch||result.alreadyPatched));
        auto position=result.instructionAddress-0x100000;
        auto pristine=image;
        memcpy(image.data()+position,result.replacementInstruction,target.instructionSize);
        Result patched {};
        assert(discoverDynamic(readImage,&input,0x100000,codeOffset,codeSize,metadataOffset,metadataSize,target,patched));
        assert(patched.compatible&&patched.alreadyPatched&&!patched.instructionMatch);
        image=pristine;
        // Native object-access mutation fails even when the short patch bytes remain.
        image[position+target.dynamicSite->length-target.dynamicSite->targetDelta-1]^=0x80;
        Result changed {};
        assert(!discoverDynamic(readImage,&input,0x100000,codeOffset,codeSize,metadataOffset,metadataSize,target,changed));
        image=pristine;
    }
}
