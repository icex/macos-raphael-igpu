"""Compile the actual holder table/admission function; no AppKit runtime claim."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class ModeLimitsTests(unittest.TestCase):
    def test_actual_modes_and_geometry_match_snapshot_domain(self):
        compiler=shutil.which('cc')
        if not compiler:self.skipTest('C compiler unavailable')
        source=(ROOT/'tools/virtual-display-server.m').read_text()
        begin=source.index('static const unsigned kSnapshotMaxWidth=')
        end=source.index('static void emit',begin)
        actual=source[begin:end]
        test=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <math.h>
ACTUAL
int main(void) {
 for(unsigned scale=1;scale<=2;scale++) {
  assert(kDefaultModes[0][0]*2==3840 && kDefaultModes[0][1]*2==2160);
  for(size_t i=0;i<sizeof(kDefaultModes)/sizeof(kDefaultModes[0]);i++) {
   unsigned w=kDefaultModes[i][0]*2/scale,h=kDefaultModes[i][1]*2/scale;
   assert(modeFitsSnapshot(w,h,scale));
   assert(w*scale<=3840 && h*scale<=2160);
   for(size_t j=0;j<i;j++)assert(kDefaultModes[i][0]!=kDefaultModes[j][0]||kDefaultModes[i][1]!=kDefaultModes[j][1]);
  }
  assert(modeFitsSnapshot(3840/scale,2160/scale,scale));
  assert(!modeFitsSnapshot(3840/scale,2304/scale,scale));
  assert(!modeFitsSnapshot(3456/scale,2234/scale,scale));
  assert(!modeFitsSnapshot(3840/scale+1,2160/scale,scale));
  assert(!modeFitsSnapshot(3840/scale,2160/scale+1,scale));
  assert(!modeFitsSnapshot(0,0,scale));
 }
 assert(!modeFitsSnapshot(1920,1080,0));assert(!modeFitsSnapshot(1920,1080,3));
 assert(refreshMatches(60,60));assert(refreshMatches(120,120));
 assert(refreshMatches(59.94,60));assert(refreshMatches(119.88,120));
 assert(!refreshMatches(60,120));assert(!refreshMatches(120,60));
 assert(!refreshMatches(0,60));assert(!refreshMatches(NAN,60));assert(!refreshMatches(INFINITY,120));
 assert(!refreshMatches(59.49,60));assert(!refreshMatches(120.51,120));
 assert(!refreshMatches(90,90));
 return 0;
}
'''.replace('ACTUAL',actual)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);(path/'modes.c').write_text(test)
            subprocess.run([compiler,'-std=c11','-Wall','-Wextra','-Werror',str(path/'modes.c'),'-o',str(path/'modes')],check=True,capture_output=True)
            subprocess.run([str(path/'modes')],check=True,timeout=5)

if __name__=='__main__':unittest.main()
