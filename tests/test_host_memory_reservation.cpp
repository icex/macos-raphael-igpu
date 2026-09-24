#include "../src/HostMemoryReservation.hpp"
#include <cassert>
using namespace RaphaelHostMemory;
int main() {
    constexpr uint64_t mc=0xf400000000ULL, phys=0x7e0000000ULL, total=0x80000000;
    Window retired[]={{phys+0x7d900000,0x3a520},{phys+0x7d93a600,0xc5ae0},
        {mc+0x7fada600,0xae01},{mc+0x7fae5400,0x4001},
        {mc+0x7fae9400,0x10041},{mc+0x7faf9500,0xc881}};
    Plan held{};
    assert(plan(mc,phys,total,0x10000000,0x200000,retired,6,held));
    assert(held.limit==0x7c000000);
    assert(plan(mc,phys,total,0x10000000,0x200000,retired,6,held,true));
    assert(held.limit==0x7e000000);
    retired[0]={UINT64_MAX-4,8};
    assert(!plan(mc,phys,total,0x10000000,0x200000,retired,6,held,true));
    Window w[]={{phys+0x7e300000,0x3a520},{mc+0x7fae5400,0x4000}};
    Plan p{};
    assert(plan(mc,phys,total,0x10000000,0x200000,w,2,p));
    assert(p.limit==0x7e000000 && p.reserved==0x2000000 && p.additional==0x1e00000);
    // Native 10MiB TMR below the preserved tail cannot overlap either window.
    assert(p.limit-0xa00000+0xa00000 <= 0x7e300000);
    assert(plan(mc,phys,total,0x10000000,0x4000000,w,2,p));
    assert(p.limit==0x7c000000 && p.additional==0);
    w[1]={mc+0x2e5400,0x4000};
    assert(!plan(mc,phys,total,0x10000000,0,w,2,p));
    w[1]={mc+total-1,2};
    assert(!plan(mc,phys,total,0x10000000,0,w,2,p));
    w[1]={UINT64_MAX-4,8};
    assert(!plan(mc,phys,total,0x10000000,0,w,2,p));
    assert(!plan(mc,phys,total,0,0,w,2,p));
    assert(!plan(mc,phys,total,0x10000000,total+1,w,2,p));
    assert(!plan(mc,phys,total,0x10000000,0,w,1,p));
}
