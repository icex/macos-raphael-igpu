from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DynamicCallerIdentityTests(unittest.TestCase):
    def test_production_inverse_locator_preserves_actual_caller_and_child_semantics(self):
        source=(ROOT/'src/RaphaelGPU.cpp').read_text()
        start=source.rindex('static size_t imageReference(')
        end=source.index('static bool discoverImageSites(',start)
        function=source[start:end]
        program=r'''
#include <cassert>
#include <cstdint>
#include "KernelSiteCatalog.hpp"
#include "VmEntryUpdate.hpp"
using mach_vm_address_t=uintptr_t;
#define arrsize(a) (sizeof(a)/sizeof(a[0]))
static uintptr_t siteImageBases[3]={0x10000000,0x20000000,0x30000000};
static bool siteImageReady[3]={true,true,true};
static uintptr_t siteAddresses[arrsize(RaphaelKernelSites::catalog)]={};
''' + function + r'''
int main() {
 for(size_t i=0;i<arrsize(RaphaelKernelSites::catalog);++i) {
  const auto &site=RaphaelKernelSites::catalog[i];
  siteAddresses[i]=siteImageBases[site.image]+site.reference+0x123;
 }
 const uintptr_t actual=siteImageBases[2]+0x55a72+0x123;
 const auto key=imageReference(siteImageBases[2],actual);
 assert(key==0x55a72);
 auto decision=RaphaelVm::prepareEntryUpdate(true,0xf400,0xf41f,0x840,key,
       0x840001000,1,0xf400002000,0x2000000000000001ULL,0);
 assert(decision.producer==RaphaelVm::UpdateProducer::Child);
 assert(decision.domain==RaphaelVm::UpdateDomain::Converted);
 decision.callerOffset=actual-siteImageBases[2];
 assert(decision.callerOffset==0x55b95);
 assert(imageReference(siteImageBases[0],actual)==SIZE_MAX);
 siteImageReady[2]=false;
 assert(imageReference(siteImageBases[2],actual)==SIZE_MAX);
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp=Path(directory)/'caller.cpp';binary=Path(directory)/'caller'
            cpp.write_text(program)
            subprocess.run(['c++','-std=c++14','-Wall','-Wextra','-Werror','-I',str(ROOT/'src'),
                            str(cpp),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
