#include <cassert>
#include <vector>
#include "../src/VcnPlatformPower.hpp"
struct Bus {
    uint32_t response=1, version=RaphaelVcnPower::ExpectedVersion, fail=0;
    unsigned delays=0;
    std::vector<uint32_t> messages, addresses, values;
    uint32_t read(uint32_t address) { return address==RaphaelVcnPower::Response?response:version; }
    void write(uint32_t address,uint32_t value) {
        addresses.push_back(address);values.push_back(value);
        if(address==RaphaelVcnPower::Response)response=value;
        if(address==RaphaelVcnPower::Message) {messages.push_back(value);response=value==fail?0xfd:1;}
    }
    RaphaelVcnPower::Result run(bool cycle=false, uint32_t vcnClockMHz=0, bool query=false, uint32_t gfxClockMHz=0, uint32_t dcnClockMHz=0) {
        return RaphaelVcnPower::enable([&](uint32_t a){return read(a);},
            [&](uint32_t a,uint32_t v){write(a,v);},[&](){++delays;},cycle,vcnClockMHz,query,gfxClockMHz,dcnClockMHz);
    }
};
int main() {
    Bus good;auto r=good.run();assert(!r.error);assert((good.messages==std::vector<uint32_t>{2,6}));
    assert((good.addresses==std::vector<uint32_t>{0x3b10984,0x3b10988,0x3b10508,0x3b10984,0x3b10988,0x3b10508}));
    assert((good.values==std::vector<uint32_t>{0,0,2,0,0,6}));
    for(uint32_t pre:{0u,0xffffffffu,0xfcu}) {Bus bad;bad.response=pre;r=bad.run();assert(r.error==1);assert(bad.messages.empty());assert(bad.addresses.empty());assert(bad.delays==(pre==0?1000u:0u));}
    Bus wrong;wrong.version=0x123456;r=wrong.run();assert(r.error==3);assert((wrong.messages==std::vector<uint32_t>{2}));
    Bus query;query.fail=2;r=query.run();assert(r.error==2);assert((query.messages==std::vector<uint32_t>{2}));
    Bus cycle; r=cycle.run(true); assert(!r.error && r.downResponse==1);
    assert((cycle.messages==std::vector<uint32_t>{2,5,6}));
    Bus down; down.fail=5; r=down.run(true); assert(r.error==5 && r.downResponse==0xfd);
    assert((down.messages==std::vector<uint32_t>{2,5}));
    Bus wrongCycle; wrongCycle.version=0; r=wrongCycle.run(true); assert(r.error==3);
    assert((wrongCycle.messages==std::vector<uint32_t>{2}));
    Bus power;power.fail=6;r=power.run();assert(r.error==4);assert(r.response==0xfd);
    const uint32_t V1200=1200u<<16;
    // Full clocks: VCLK 1200 (<<16), DCLK 1028, GFX 2200, then telemetry.
    Bus full; r=full.run(false,1200,true,2200,1028); assert(!r.error);
    assert((full.messages==std::vector<uint32_t>{2,6,7,17,7,17,21,15,16,16}));
    assert((full.values==std::vector<uint32_t>{0,0,2, 0,0,6, 0,V1200,7, 0,V1200,17, 0,1028,7, 0,1028,17,
                                              0,2200,21, 0,0,15, 0,0,16, 0,1,16}));
    assert(r.clockMinResponse==1 && r.clockMaxResponse==1 && r.dclkMinResponse==1 &&
           r.dclkMaxResponse==1 && r.gfxMinResponse==1 && r.gfxclkResponse==1);
    // A refused VCN minimum is non-fatal and suppresses its maximum; later requests still go out.
    Bus badClk; badClk.fail=7; r=badClk.run(false,1200,false,2200); assert(!r.error);
    assert(r.clockMinResponse==0xfd && r.clockMaxResponse==0 && r.gfxMinResponse==1);
    assert((badClk.messages==std::vector<uint32_t>{2,6,7,21}));
    // Query alone.
    Bus queryOnly; r=queryOnly.run(false,0,true); assert(!r.error);
    assert((queryOnly.messages==std::vector<uint32_t>{2,6,15,16,16}));
    // A refused GFX request is recorded and non-fatal.
    Bus badGfx; badGfx.fail=21; r=badGfx.run(false,0,false,2200); assert(!r.error);
    assert((badGfx.messages==std::vector<uint32_t>{2,6,21})); assert(r.gfxMinResponse==0xfd);
    // Default call never sends clock messages.
    Bus plain; r=plain.run(); assert((plain.messages==std::vector<uint32_t>{2,6}));
    assert(r.gfxMinResponse==0 && r.clockMinResponse==0 && r.dclkMinResponse==0);
}
