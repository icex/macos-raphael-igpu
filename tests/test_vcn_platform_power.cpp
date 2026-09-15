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
    RaphaelVcnPower::Result run(bool cycle=false) {
        return RaphaelVcnPower::enable([&](uint32_t a){return read(a);},
            [&](uint32_t a,uint32_t v){write(a,v);},[&](){++delays;},cycle);
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
}
