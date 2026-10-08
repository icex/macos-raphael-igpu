#include "../src/ConsoleTmrSafety.hpp"
#include <cassert>
#include <map>
struct IO {
    std::map<uint32_t,uint32_t> regs{{0x36b6,0x800c6},{0x36c0,1},{0x3802,0x100}};
    unsigned reads=0;
    uint32_t read(uint32_t reg) { ++reads; return regs.at(reg); }
};
int main() {
    assert(RaphaelConsoleTmr::held(0x80000,1,0x100)); // observed held state after333
    assert(!RaphaelConsoleTmr::held(0x90000,1,0x100)); // enable must still be clear
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
