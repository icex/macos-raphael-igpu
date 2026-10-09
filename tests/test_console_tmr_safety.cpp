#include "../src/ConsoleTmrSafety.hpp"
#include <cassert>
#include <map>
struct IO {
    std::map<uint32_t,uint32_t> regs{{0x36b6,0x800c6},{0x36c0,1},{0x3802,0x100}};
    unsigned reads=0, writes=0; bool rejectWrite=false;
    void write(uint32_t reg,uint32_t value) { ++writes; if(!rejectWrite)regs[reg]=value; }
    uint32_t read(uint32_t reg) { ++reads; return regs.at(reg); }
};
static IO cold() {
    IO io;io.regs[0x36b6]=0x90000;io.regs[0x3802]=0;
    io.regs[0x36a3]=0;io.regs[0x36a4]=0;
    for(unsigned c=0;c<2;++c) for(auto r:{0x3665+c,0x366d+c,0x3675+2*c,0x3676+2*c})io.regs[r]=0;
    for(unsigned r=0;r<3;++r) for(auto a:{0x364e + 2*r,0x364f+2*r,0x365e + r})io.regs[a]=0;
    return io;
}
int main() {
    IO empty=cold();
    assert(RaphaelConsoleTmr::holdEmptyFirmware(empty));
    assert(empty.regs[0x36b6]==0x80000 && empty.regs[0x3802]==0x100);
    // Any code mapping, firmware identity, inaccessible read or running CPU
    // refuses this separate cold path before any write.
    for (auto entry:cold().regs) {
        if(entry.first==0x36b6 || entry.first==0x3802 || entry.first==0x36c0)continue;
        for(auto value:{1u,UINT32_MAX}) {
            IO bad=cold();bad.regs[entry.first]=value;
            assert(!RaphaelConsoleTmr::holdEmptyFirmware(bad) && bad.writes==0);
        }
    }
    for(auto r:{0x36b6,0x3802,0x36c0}) {
        IO bad=cold();bad.regs[r]=UINT32_MAX;
        assert(!RaphaelConsoleTmr::holdEmptyFirmware(bad) && bad.writes==0);
    }
    IO runningCold=cold();runningCold.regs[0x36c0]=0;
    assert(!RaphaelConsoleTmr::holdEmptyFirmware(runningCold) && runningCold.writes==0);
    IO noWrite=cold();noWrite.rejectWrite=true;
    assert(!RaphaelConsoleTmr::holdEmptyFirmware(noWrite));
    empty.regs[0x366d]=0x80000001;
    assert(!RaphaelConsoleTmr::emptyFirmware(empty));

    assert(RaphaelConsoleTmr::held(0x80000,1,0x100)); // observed held state after333
    assert(!RaphaelConsoleTmr::held(0x90000,1,0x100)); // enable must still be clear
    IO resetEnabled;resetEnabled.regs[0x36b6]=0x90000;
    assert(RaphaelConsoleTmr::disableWhileReset(resetEnabled));
    assert(resetEnabled.writes==1 && resetEnabled.regs[0x36b6]==0x80000);
    assert(RaphaelConsoleTmr::disableWhileReset(resetEnabled) && resetEnabled.writes==1);
    for(auto reg:{0x36b6,0x36c0,0x3802}) {
        IO bad;bad.regs[reg]=UINT32_MAX;
        assert(!RaphaelConsoleTmr::disableWhileReset(bad) && !bad.writes);
    }
    for(auto reg:{0x36c0,0x3802}) {
        IO bad;bad.regs[reg]=0;bad.regs[0x36b6]=0x90000;
        assert(!RaphaelConsoleTmr::disableWhileReset(bad) && !bad.writes);
    }
    IO rejected;rejected.regs[0x36b6]=0x90000;rejected.rejectWrite=true;
    assert(!RaphaelConsoleTmr::disableWhileReset(rejected));
    IO io; unsigned calls=0;
    auto psp=[&]() { ++calls; return 7u; };
    assert(RaphaelConsoleTmr::replace(false,io,psp)==2);
    assert(!calls && !io.reads); // no hardware access without memory ownership
    for(auto reg:{0x36b6,0x36c0,0x3802}) {
        IO bad; bad.regs[reg]=UINT32_MAX;
        assert(RaphaelConsoleTmr::replace(true,bad,psp)==2 && !calls);
    }
    IO running; running.regs[0x36b6]|=0x10000;
    assert(RaphaelConsoleTmr::replace(true,running,psp)==2 && !calls);
    IO noReset;noReset.regs[0x36c0]=0;
    assert(RaphaelConsoleTmr::replace(true,noReset,psp)==2 && !calls);
    IO noInterface;noInterface.regs[0x3802]=0;
    assert(RaphaelConsoleTmr::replace(true,noInterface,psp)==2 && !calls);
    assert(RaphaelConsoleTmr::replace(true,io,psp)==7 && calls==1);
    // A successful prior check never caches authorization across a state change.
    io.regs[0x36c0]=0;
    assert(RaphaelConsoleTmr::replace(true,io,psp)==2 && calls==1);
}
