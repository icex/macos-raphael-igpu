#include "../src/DmubReinit.hpp"
#include <cassert>
#include <map>
#include <vector>
#include <utility>
using namespace RaphaelDmubReinit;
struct IO {
    std::map<uint32_t,uint32_t> regs;
    std::vector<uint32_t> mem=std::vector<uint32_t>((End-Begin)/4);
    std::vector<std::pair<uint32_t,uint32_t>> writes;
    unsigned failure=0, uploads=0, starts=0, phaseNow=0;
    IO(unsigned f):failure(f) {
        regs[0x36b6]=0x900c6; regs[0x36b8]=0x10010000;
        for (auto w:Windows) {
            uint64_t a=(w.cw<2?0x7e0000000ull:0xf400000000ull)+0x7e300000+w.cw*0x10000;
            regs[0x3675+2*w.cw]=uint32_t(a);regs[0x3676+2*w.cw]=uint32_t(a>>32);
            regs[0x3665+w.cw]=w.cw<<24;
            regs[0x366d+w.cw]=0x80000000|(w.cw<<24)|0xfff;
        }
    }
    uint32_t read(uint32_t reg) {
        if (failure==6 && phaseNow>=3 && !writes.empty()) return 0xffffffff;
        if (failure==3 && phaseNow==5 && reg==0x3675) return regs[reg]^4;
        return regs[reg];
    }
    void write(uint32_t reg,uint32_t v) {
        writes.emplace_back(reg,v);
        if (failure==1 && reg==0x36c0 && v==1) return;
        regs[reg]=v;
        if (reg==0x36c0 && v==0) {
            starts++;
            if (failure!=4) regs[0x36a3]=3;
        }
        if (reg==0x36b8 && v==0x10010000 && starts && failure!=5) {
            regs[reg]=0x10000; regs[0x36aa]=failure==7?0xdead:0x05003500;
        }
    }
    uint32_t memoryRead(uint64_t off) {
        assert(off>=Begin && off<End && !(off&3));
        return mem[(off-Begin)/4];
    }
    bool memoryWriteRead(uint64_t off,uint32_t value) {
        assert((regs[0x36c0]&1) && (regs[0x3802]&0x100) && !(regs[0x36b6]&0x10000));
        assert(off>=Begin && off<End && !(off&3));uploads++;
        mem[(off-Begin)/4]=value;
        return failure!=2 || uploads<9;
    }
    void delayUs(unsigned) {}
    void phase(unsigned p) {phaseNow=p;}
};
int main() {
    std::vector<uint32_t> code(0x3a520/4,0x12345678), bios(0xae00/4,0xabcdef12);
    Inputs in; in.reserved=true;in.tmrValid=true;in.limit=0x7e000000;in.total=0x80000000;
    in.mc=0xf400000000;in.physical=0x7e0000000;in.tmr=in.mc+0x7d600000;in.tmrBytes=0xa00000;
    in.code=code.data();in.codeBytes=0x3a520;in.bios=bios.data();in.biosBytes=0xae00;
    for (unsigned f=0;f<8;f++) {
        IO io(f);auto r=run(in,io);
        if (!f) {
            assert(r.success && r.queries==3 && !r.held && io.starts==1);
            assert(io.regs[0x3675]==0x5f000000 && io.regs[0x3676]==8);
            assert(io.regs[0x367d]==0x7f0e5500 && io.regs[0x367e]==0xf4);
            assert(io.regs[0x366d]==0x8003a53f && io.regs[0x3671]==0x84004000);
            assert(io.memoryRead(Begin)==code[0]);
            assert(io.memoryRead(0x7f0da600)==bios[0]);
            assert(io.memoryRead(0x7f0e5500)==0);
        } else {
            assert(!r.success);
            if (f==6) { assert(r.inaccessible); assert(io.writes.size()==1); }
            if (f==2 || f==3) { assert(!io.starts); assert(r.held); }
            if (f==4 || f==5 || f==7) {assert(io.starts==1);assert(r.held);}
        }
    }
    for (unsigned f=0;f<6;f++) {
        auto bad=in; IO io(0);
        if (f==0) bad.tmr=in.mc+Begin;
        if (f==1) bad.reserved=false;
        if (f==2) bad.mc=0;
        if (f==3) bad.codeBytes--;
        if (f==4) bad.tmrBytes=~uint64_t(0);
        if (f==5) {io.regs[0x3675]=uint32_t(in.physical+Begin);io.regs[0x3676]=uint32_t((in.physical+Begin)>>32);}
        auto r=run(bad,io);assert(!r.success && io.writes.empty() && !io.uploads);
    }
}
