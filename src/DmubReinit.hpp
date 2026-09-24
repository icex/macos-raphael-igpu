#pragma once
#include <stdint.h>
namespace RaphaelDmubReinit {
constexpr uint64_t Begin=0x7f000000, End=0x7f106000;
struct Window { unsigned cw; uint32_t offset, bytes; };
static constexpr Window Windows[] = {
    {0,0x7f000000,0x3a540}, {1,0x7f03a600,0xa0000},
    {3,0x7f0da600,0xae00}, {4,0x7f0e5500,0x4000},
    {5,0x7f0e9600,0x10040}, {6,0x7f0f9700,0xc880}
};
struct Inputs {
    bool reserved=false, tmrValid=false;
    uint64_t limit=0, total=0, mc=0, physical=0, tmr=0, tmrBytes=0;
    const uint32_t *code=nullptr, *bios=nullptr;
    unsigned codeBytes=0, biosBytes=0;
};
struct Result {
    unsigned phase=0, error=0, queries=0;
    bool touched=false, inaccessible=false, held=false, success=false;
    bool stopAck=false, stopDone=false, stopWait=false;
    uint32_t faultFetch=0, faultWrite=0;
};
inline bool overlap(uint64_t a,uint64_t n,uint64_t b,uint64_t m) {
    return n && m && a<b+m && b<a+n;
}
// Transport exposes register read/write, bounded FB write/read, delayUs and phase.
// No dynamic allocation, exceptions, firmware registration, or PSP command writes.
template<class IO> Result run(const Inputs &in, IO &io) {
    Result r;
    auto phase=[&](unsigned n) { r.phase=n; io.phase(n); };
    auto rd=[&](uint32_t reg) {
        uint32_t v=io.read(reg);
        if (v==0xffffffffu) { r.inaccessible=true; r.error=2; }
        return v;
    };
    auto wr=[&](uint32_t reg,uint32_t value,uint32_t mask=0xffffffffu) {
        if (r.inaccessible) return false;
        io.write(reg,value);
        const auto back=rd(reg);
        if (r.inaccessible || ((back^value)&mask)) { r.error=3; return false; }
        return true;
    };
    auto rmw=[&](uint32_t reg,uint32_t mask,uint32_t value) {
        const auto old=rd(reg);
        return !r.inaccessible && wr(reg,(old&~mask)|(value&mask),mask);
    };
    auto poll=[&](uint32_t reg,uint32_t mask,uint32_t value) {
        for (unsigned n=0;n<10000;n++) {
            const auto v=rd(reg);
            if (r.inaccessible) return false;
            if ((v&mask)==value) return true;
            io.delayUs(10);
        }
        return false;
    };
    auto hold=[&]() {
        if (r.inaccessible) return false;
        return rmw(0x36c0,1,1) && rmw(0x3802,0x100,0x100) &&
               rmw(0x36b6,0x10000,0);
    };
    auto fail=[&]() {
        if (!r.error) r.error=4;
        if (r.touched && !r.inaccessible) r.held=hold();
        return r;
    };
    phase(1);
    if (!in.reserved || !in.tmrValid || in.limit!=0x7e000000 ||
        in.total!=0x80000000 || in.mc!=0xf400000000ull ||
        in.physical!=0x7e0000000ull || in.tmr<in.mc || !in.tmrBytes ||
        in.tmrBytes>in.total || in.tmr-in.mc>in.total-in.tmrBytes ||
        in.tmr-in.mc+in.tmrBytes>in.limit || !in.code || !in.bios ||
        in.codeBytes!=0x3a520 || in.biosBytes!=0xae00) {
        r.error=1; return r;
    }
    for (const auto &w:Windows) {
        uint64_t a=rd(0x3675+2*w.cw); a|=uint64_t(rd(0x3676+2*w.cw))<<32;
        const uint32_t b=rd(0x3665+w.cw)&0x1fffffff, top=rd(0x366d+w.cw);
        if (r.inaccessible) return r;
        if (!(top&0x80000000) || (top&0x1fffffff)<b) {r.error=1;return r;}
        uint64_t n=uint64_t(top&0x1fffffff)-b+1, off=0;
        unsigned matches=0;
        const uint64_t domains[]={in.mc,in.physical};
        for (auto base:domains) {
            if (n<=in.total && a>=base && a-base<=in.total-n) {off=a-base;matches++;}
        }
        if (matches!=1 || overlap(off,n,Begin,End-Begin)) {r.error=1;return r;}
    }
    const auto pending=rd(0x36b8), control=rd(0x36b6), reset=rd(0x36c0);
    if (r.inaccessible) return r;
    if (!(control&0x10000) || reset&1 ||
        ((pending&0xf0000000) && pending!=0x10010000)) {r.error=1;return r;}
    // The caller already made a fresh baseline query and skips a responsive FW.
    phase(2);
    io.write(0x36b8,0x10020000);
    r.stopAck=poll(0x36b8,0xffffffffu,0x20000);
    r.stopDone=poll(0x36aa,0xffffffffu,0xdeaddead);
    r.stopWait=poll(0x36b6,0x100000,0x100000);
    if (r.inaccessible) return r;
    phase(3); r.touched=true;
    if (!(r.held=hold())) return fail();
    const uint32_t clear[]={0x3697,0x3696,0x369f,0x369e,0x369b,0x369a,0x36a3,0x36b8};
    for (auto reg:clear) if (!wr(reg,0)) return fail();
    phase(4);
    // Write each dword once, then compare it immediately and again in a full pass.
    auto expected=[&](uint64_t off) {
        if (off<Begin+in.codeBytes) return in.code[(off-Begin)/4];
        if (off>=0x7f0da600 && off<0x7f0da600+in.biosBytes)
            return in.bios[(off-0x7f0da600)/4];
        return uint32_t(0);
    };
    for (uint64_t off=Begin;off<End;off+=4) {
        const auto v=expected(off);
        if (!io.memoryWriteRead(off,v)) {r.error=5;return fail();}
    }
    for (uint64_t off=Begin;off<End;off+=4)
        if (io.memoryRead(off)!=expected(off)) {r.error=5;return fail();}
    phase(5);
    if (!rmw(0x368e,0x10000,0x10000)) return fail();
    for (const auto &w:Windows) {
        const uint64_t addr=(w.cw<2?in.physical:in.mc)+w.offset;
        const uint32_t base=w.cw<<24;
        if (!wr(0x3675+2*w.cw,uint32_t(addr)) ||
            !wr(0x3676+2*w.cw,uint32_t(addr>>32)) ||
            !wr(0x3665+w.cw,0x60000000u|base,0x1fffffff) ||
            !wr(0x366d+w.cw,0x80000000u| (base+w.bytes-(w.cw<2?1:0))))
            return fail();
        if (w.cw==1 && !rmw(0x368e,0x13f00,0x2000)) return fail();
    }
    const uint64_t trace=in.mc+0x7f0e9600;
    if (!wr(0x3658,uint32_t(trace)) || !wr(0x3659,uint32_t(trace>>32)) ||
        !wr(0x3662,0x8001003f)) return fail();
    phase(6);
    const uint32_t mailbox[][2]={{0x3694,0x64000000},{0x3695,0x2000},
        {0x369c,0x64002000},{0x369d,0x2000},{0x3698,0xa0000010},
        {0x3699,0x10030},{0x36b1,0x80},{0x36b2,0}};
    for (const auto &p:mailbox) if (!wr(p[0],p[1])) return fail();
    if (!rmw(0x3802,0x100,0) || !rmw(0x36b6,0x90000,0x90000) ||
        !rmw(0x36c0,1,0)) return fail();
    r.held=false;
    phase(7);
    if (!poll(0x36a3,3,3)) return fail();
    for (unsigned q=0;q<3;q++) {
        io.write(0x36b8,0x10010000);
        if (!poll(0x36b8,0xffffffffu,0x10000) || rd(0x36aa)!=0x05003500)
            return fail();
        r.queries++;
        io.delayUs(10000);
    }
    r.faultFetch=rd(0x368c); r.faultWrite=rd(0x368d);
    if (r.inaccessible || r.faultFetch || r.faultWrite) return fail();
    phase(8); r.success=true; return r;
}
}
