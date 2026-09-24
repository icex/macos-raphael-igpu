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
    uint32_t memoryWriteRead(uint64_t off,uint32_t value) {
        assert((regs[0x36c0]&1) && (regs[0x3802]&0x100) && !(regs[0x36b6]&0x10000));
        assert(off>=Begin && off<End && !(off&3));uploads++;
        mem[(off-Begin)/4]=value;
        return failure==2 && uploads>=9 ? value^1 : value;
    }
    bool loadPsp(uint64_t a,unsigned n) {
        assert(a==0xf47f000000ull && n==0x3a720);
        if (failure==8) return false;
        for (unsigned cw=0;cw<2;cw++) {
            uint64_t addr=0x85d900000ull+cw*0x100000;
            if (failure==9) addr=0x85f900000ull;
            regs[0x3675+cw*2]=uint32_t(addr);regs[0x3676+cw*2]=uint32_t(addr>>32);
            regs[0x3665+cw]=cw<<24;
            regs[0x366d+cw]=0x80000000u|(cw<<24)|(cw?0xc5adf:0x3a51f);
        }
        if (failure==10) regs[0x36c0]=0;
        return true;
    }
    void delayUs(unsigned) {}
    void phase(unsigned p) {phaseNow=p;}
};
int main() {
    std::vector<uint32_t> code(0x3a520/4,0x12345678), bios(0xae00/4,0xabcdef12);
    bios[0x2d40/4]=0xffffffffu; // Legitimate data, not an MMIO failure sentinel.
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
    { IO io(0);auto normal=in;normal.resumeHeld=true;
      auto r=run(normal,io);assert(!r.success && io.writes.empty());
    }
    { IO io(0); auto held=in; held.resumeHeld=true;
      io.regs[0x36c0]=1;io.regs[0x3802]=0x100;io.regs[0x36b6]=0x800c6;
      auto r=run(held,io);assert(r.success && r.resumedHeld && io.starts==1);
      for (auto p:io.writes) assert(!(p.first==0x36b8 && p.second==0x10020000));
    }
    { IO io(0);io.regs[0x36c0]=1;io.regs[0x3802]=0x100;io.regs[0x36b6]=0x800c6;
      auto r=run(in,io);assert(!r.success && io.writes.empty());
    }
    { std::vector<uint32_t> signedCode(0x3a720/4,0xffffffffu);
      for (unsigned f: {0u,8u,9u,10u}) {
        IO io(f);auto psp=in;psp.pspLoad=true;psp.signedCode=signedCode.data();psp.signedBytes=0x3a720;
        auto r=run(psp,io);
        if (!f) {assert(r.success && io.starts==1 && r.queries==3);}
        else {assert(!r.success && r.held && io.starts==0);}
        for (auto w:io.writes) {
          assert(w.first!=0x368e); // No secure-control writes or CW0/1 reprogramming.
          assert(w.first!=0x3675 && w.first!=0x3676 && w.first!=0x3677 && w.first!=0x3678);
        }
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
