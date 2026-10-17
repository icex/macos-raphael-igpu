#include "RelativeBranch.hpp"
#include <cassert>
using namespace RaphaelRelativeBranch;
static int32_t delta(const uint8_t *bytes) {int32_t value;memcpy(&value,bytes+2,4);return value;}
int main() {
 const uint8_t old[]={0x0f,0x84,0x80,0,0,0};uint8_t patched[6]{};
 assert(redirectJe(old,0x1eca,0x1fd2,patched)&&delta(patched)==0x102);
 assert(redirectJe(old,0x13eb,0x1507,patched)&&delta(patched)==0x116);
 assert(redirectJe(old,0x2000,0x1000,patched)&&delta(patched)==-0x1006);
 assert(patched[0]==0x0f&&patched[1]==0x84);
 const uint8_t other[]={0x0f,0x85,0,0,0,0};assert(!redirectJe(other,0x1000,0x2000,patched));
 assert(!redirectJe(old,UINTPTR_MAX-4,0x1000,patched));
 assert(!redirectJe(old,0x1000,0x1006+uint64_t(INT32_MAX)+1,patched));
 assert(redirectJe(old,uint64_t(INT32_MAX)+20,25,patched)&&delta(patched)==INT32_MIN);
 assert(!redirectJe(old,uint64_t(INT32_MAX)+21,25,patched));
 assert(!redirectJe(nullptr,0x1000,0x2000,patched));
}
