"""Compile exact added transaction functions with bounded PGM/ioctl substitutes.
This is not a full VBox build, PGM lifetime proof or physical-device test.
"""
from pathlib import Path
import shutil,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
class DmaTransactionTests(unittest.TestCase):
 def test_extracted_transaction_faults(self):
  cc=shutil.which('c++')
  if not cc:self.skipTest('C++ compiler unavailable')
  if not Path('/usr/include/linux/iommufd.h').exists():self.skipTest('Linux IOMMUFD UAPI headers unavailable')
  patch=(ROOT/'findings/research/patches/virtualbox-7.2.18-vfio-dma-transaction.patch').read_text()
  added='\n'.join(x[1:] for x in patch.splitlines() if x.startswith(('+',' ')) and not x.startswith('+++'))
  functions=added[added.index('/** Successful extents'):added.index('static int pciVfioConfigPassthroughRead')]
  begin=added.index('                if (u32Value & RT_BIT(2))')
  end=added.index('                /* Check whether the INTx config changes.',begin)
  guard=added[begin:end]
  harness=r'''
#include <cassert>
#include <cstdlib>
#include <cstdint>
#include <cerrno>
#include <vector>
#include <linux/vfio.h>
#include <linux/iommufd.h>
#define VINF_SUCCESS 0
#define VERR_PGM_INVALID_GC_PHYSICAL_ADDRESS -90
#define VERR_PGM_PHYS_PAGE_RESERVED -91
#define VERR_NOT_FOUND -92
#define VERR_NO_MEMORY -10
#define VERR_INVALID_STATE -11
#define VERR_IO_GEN_FAILURE -12
#define RT_FAILURE(x) ((x)<0)
#define RT_SUCCESS(x) ((x)>=0)
#define LogRel(x) ((void)0)
#define RT_BIT(x) (1U<<(x))
#define _4G 20
#define _4K 4
using RTGCPHYS=uint64_t;
using PPDMDEVINS=void*;
using PGMPAGEMAPLOCK=int;
struct VFIOPCI {bool fVfioLegacy=true,fGuestRamMapped=false,fGuestRamMapFailed=false;int iInstance=0;struct {int iFdVfioContainer=1;}VfioGroup;struct {int iFdIommu=2;unsigned idIommuHwpt=3;}IommuFd;};
using PVFIOPCI=VFIOPCI*;
int pageError=0;uint64_t errorAt=8;bool allHoles=false;
int failMap=0,failAlloc=0,unmapMode=0,mapCalls=0,allocCalls=0,live=0,locks=0;
std::vector<uint64_t> undo;
void* RTMemAlloc(size_t n){if(++allocCalls==failAlloc)return nullptr;++live;return malloc(n);}
void RTMemFree(void*p){--live;free(p);}
int RTErrConvertFromErrno(int e){return -e;}
int fakeIoctl(int,unsigned long op,void*p){
 uint64_t addr;
 if(op==VFIO_IOMMU_UNMAP_DMA){auto*u=(vfio_iommu_type1_dma_unmap*)p;addr=u->iova;if(unmapMode==2)u->size=0;}
 else {assert(op==IOMMU_IOAS_UNMAP);auto*u=(iommu_ioas_unmap*)p;assert(u->ioas_id==3);addr=u->iova;if(unmapMode==2)u->length=0;}
 undo.push_back(addr);if(unmapMode==1){errno=EIO;return -1;}return 0;
}
#define ioctl fakeIoctl
int pciVfioMapRegion(PVFIOPCI,RTGCPHYS,uintptr_t,size_t){return ++mapCalls==failMap?-77:0;}
uint64_t PDMDevHlpMMPhysGetRamSizeAbove4GB(PPDMDEVINS){return 0;}
int PDMDevHlpPhysGCPhys2CCPtr(PPDMDEVINS,uint64_t a,int,void**p,int*){if(allHoles)return VERR_PGM_INVALID_GC_PHYSICAL_ADDRESS;if(pageError&&a==errorAt)return pageError;if(a==8)return VERR_PGM_INVALID_GC_PHYSICAL_ADDRESS;*p=(void*)(uintptr_t)(a>=12?0x9000+(a-12)*2:0x1000+a);++locks;return 0;}
void PDMDevHlpPhysReleasePageMappingLock(PPDMDEVINS,int*){--locks;}
'''
  bme='int physicalWrites=0; int bme(PVFIOPCI pThis,unsigned u32Value){PPDMDEVINS pDevIns=nullptr;int rc=0;'+guard+'++physicalWrites;return rc;}\n'
  main=r'''
void reset(){pageError=0;errorAt=8;allHoles=false;failMap=failAlloc=unmapMode=mapCalls=allocCalls=live=locks=0;undo.clear();}
int main(){
 reset();VFIOPCI bad;failMap=2;assert(bme(&bad,4)==-77&&physicalWrites==0);assert(bme(&bad,4)==VERR_INVALID_STATE&&physicalWrites==0);assert(bme(&bad,0)==0&&physicalWrites==1);
 reset();VFIOPCI good;assert(bme(&good,4)==0&&physicalWrites==2);
 reset();VFIOPCI empty;allHoles=true;assert(bme(&empty,4)==VERR_NOT_FOUND);assert(!empty.fGuestRamMapped&&empty.fGuestRamMapFailed&&mapCalls==0);
 for(int e:{VERR_PGM_PHYS_PAGE_RESERVED,-98}){reset();VFIOPCI p;pageError=e;int writes=physicalWrites;assert(bme(&p,4)==e);assert(physicalWrites==writes&&!p.fGuestRamMapped&&p.fGuestRamMapFailed&&live==0&&locks==0);}
 reset();VFIOPCI partial;pageError=VERR_PGM_PHYS_PAGE_RESERVED;errorAt=16;assert(bme(&partial,4)==pageError);assert(undo.size()==1&&undo[0]==0&&!partial.fGuestRamMapped&&live==0&&locks==0);
 for(bool legacy:{true,false}) {
  reset();VFIOPCI p;p.fVfioLegacy=legacy;assert(pciVfioIommuGuestRamMap(&p,nullptr)==0);assert(p.fGuestRamMapped&&!p.fGuestRamMapFailed);assert(mapCalls==3&&undo.empty()&&live==0&&locks==0);assert(pciVfioIommuGuestRamMap(&p,nullptr)==0&&mapCalls==3);
  for(int fail:{1,2,3})for(int mode:{0,1,2}) {
   reset();VFIOPCI q;q.fVfioLegacy=legacy;failMap=fail;unmapMode=mode;assert(pciVfioIommuGuestRamMap(&q,nullptr)==-77);assert(!q.fGuestRamMapped&&q.fGuestRamMapFailed);assert(undo.size()==size_t(fail-1));if(fail==3){assert(undo[0]==12&&undo[1]==0);}assert(live==0&&locks==0);int before=mapCalls;assert(pciVfioIommuGuestRamMap(&q,nullptr)==VERR_INVALID_STATE&&mapCalls==before);
  }
  for(int fail:{1,2,3}) {
   reset();VFIOPCI q;q.fVfioLegacy=legacy;failAlloc=fail;assert(pciVfioIommuGuestRamMap(&q,nullptr)==VERR_NO_MEMORY);assert(mapCalls==fail-1&&undo.size()==size_t(fail-1));assert(live==0&&locks==0&&!q.fGuestRamMapped);
  }
  reset();VFIOPCI q;q.fVfioLegacy=legacy;unmapMode=2;assert(pciVfioUnmapRegion(&q,4,4)==VERR_IO_GEN_FAILURE);
 }
}
'''
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'test.cpp').write_text(harness+functions+bme+main)
   built=subprocess.run([cc,'-std=c++17','-Wall','-Wextra','-Werror',str(p/'test.cpp'),'-o',str(p/'test')],capture_output=True,text=True)
   self.assertEqual(built.returncode,0,built.stderr)
   subprocess.run([str(p/'test')],check=True,timeout=5)
