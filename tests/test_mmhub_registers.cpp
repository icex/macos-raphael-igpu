#include <cassert>
#include <cstring>
#include "../src/MmhubRegisters.hpp"
#include "../src/GpuVmDiagnostics.hpp"

int main() {
    using namespace RaphaelMmhub;
    // Literal addresses decoded from launch45's VMPT IB and the MMHUB2.3 header.
    assert(registerAt(12+2*7,false)==0x1392f);
    assert(registerAt(12+2*7,true)==0x1a950);
    assert(registerAt(124+6*5+2,false)==0x138e9);
    assert(registerAt(124+6*5+3,false)*4==0x4e3ec);
    assert(registerAt(124+6*5+2,true)==0x1aa31);
    assert(registerAt(124+6*5+3,true)==0x1aa32);
    assert(registerAt(123,true)==0x1a74f); // last context control
    assert(registerAt(213,true)==0x1aa88); // last engine semaphore
    uint32_t table[kWords], before[kWords];
    for(size_t i=0;i<kWords;i++) table[i]=registerAt(i,false);
    memcpy(before,table,sizeof(table));
    assert(repair(table,sizeof(table),false,true)==Result::Disabled);
    assert(repair(table,sizeof(table),true,false)==Result::Disabled);
    assert(repair(table,sizeof(table)-4,true,true)==Result::Invalid);
    assert(!memcmp(table,before,sizeof(table)));
    for(size_t bad=0;bad<kWords;bad++) {
        memcpy(table,before,sizeof(table)); table[bad]^=1;
        uint32_t corrupt[kWords]; memcpy(corrupt,table,sizeof(table));
        assert(repair(table,sizeof(table),true,true)==Result::Mismatch);
        assert(!memcmp(table,corrupt,sizeof(table)));
    }
    memcpy(table,before,sizeof(table));
    assert(repair(table,sizeof(table),true,true)==Result::Repaired);
    assert(repair(table,sizeof(table),true,true)==Result::AlreadyCorrect);
    uint8_t info[0x28]={};
    uint32_t hub=1, vmid=2; uint64_t root=0xf41b09c000ULL;
    memcpy(info,&hub,4); memcpy(info+4,&vmid,4); memcpy(info+0x18,&root,8); info[0x24]=1;
    const auto denied=RaphaelVm::prepareInvalidateInfo(info,sizeof(info),true,true,0xf400,0xf41f,0x840);
    assert(!denied.repaired && denied.reason==RaphaelVm::RootRepairReason::WrongHub);
    const auto fixed=RaphaelVm::prepareInvalidateInfo(info,sizeof(info),true,true,0xf400,0xf41f,0x840,true);
    assert(fixed.repaired && fixed.nativeRoot==0x85b09c000ULL);
    uint64_t retained=0; memcpy(&retained,info+0x18,8); assert(retained==root);
    vmid=0; memcpy(info+4,&vmid,4);
    assert(!RaphaelVm::prepareInvalidateInfo(info,sizeof(info),true,true,0xf400,0xf41f,0x840,true).repaired);
    vmid=2; hub=2; memcpy(info+4,&vmid,4); memcpy(info,&hub,4);
    assert(!RaphaelVm::prepareInvalidateInfo(info,sizeof(info),true,true,0xf400,0xf41f,0x840,true).repaired);
}
