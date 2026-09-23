#include "../src/DisplayIdlePower.hpp"
#include <cassert>
#include <vector>
#include <utility>
using namespace RaphaelDisplayPower;
int main() {
 for (unsigned fault=0;fault<5;fault++) {
  uint32_t response=fault==1?0:1,argument=0;
  std::vector<std::pair<uint32_t,uint32_t>> writes;
  auto read=[&](uint32_t a) { assert(a==Response || a==Argument); return a==Response?response:argument; };
  auto write=[&](uint32_t a,uint32_t v) {
   writes.emplace_back(a,v);
   if(a==Response) response=v;
   else if(a==Argument) argument=v;
   else { assert(a==Message); assert(v==2 || v==0x12);
    response=fault==2?0:1;
    if(v==2) argument=fault==3?0xdead:0x625300;
    if(v==0x12 && fault==4) response=0xff;
   }
  };
  auto r=exitIdle(read,write,[](){},0x625300);
  if(fault==0) { assert(r.wakeResponse==1); assert(writes.size()==6); assert(writes[4].second==0); }
  if(fault==1) assert(writes.empty());
  if(fault==2 || fault==3) { assert(writes.size()==3); assert(r.wakeResponse==0); }
  if(fault==4) assert(r.wakeResponse==0xff);
 }
}
