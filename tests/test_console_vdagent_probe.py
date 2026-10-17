"""Execute real fork/pipe probe control flow against an isolated fake device backend."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
static int exclusive=0;
static const char *scenario(void) {return getenv("PROBE_CASE");}
static uid_t fake_uid(void) {return !strcmp(scenario(),"root") ? 0 : 501;}
static int fake_lstat(const char *path,struct stat *s) {
 if(strcmp(path,"/dev/tty.com.redhat.spice.0")) abort();
 memset(s,0,sizeof(*s));s->st_mode=!strcmp(scenario(),"symlink")?S_IFLNK:S_IFCHR;
 s->st_dev=7;s->st_ino=123;s->st_rdev=9;return 0;
}
static int fake_fstat(int fd,struct stat *s) {
 (void)fd;fake_lstat("/dev/tty.com.redhat.spice.0",s);
 if(!strcmp(scenario(),"replaced"))s->st_ino=124;
 return 0;
}
static int fake_open(const char *path,int flags) {
 if(strcmp(path,"/dev/tty.com.redhat.spice.0"))abort();
 if((flags&(O_RDWR|O_NONBLOCK|O_NOCTTY|O_CLOEXEC|O_NOFOLLOW))!=(O_RDWR|O_NONBLOCK|O_NOCTTY|O_CLOEXEC|O_NOFOLLOW))abort();
 if(exclusive && strcmp(scenario(),"exclusivity-ignored")) {errno=EBUSY;return -1;}
 return open("/dev/null",O_RDWR|O_CLOEXEC);
}
static int fake_ioctl(int fd,unsigned long request,...) {
 (void)fd;if(request!=TIOCEXCL)abort();
 if(!strcmp(scenario(),"unsupported")){errno=ENOTTY;return -1;}
 exclusive=1;return 0;
}
#define geteuid fake_uid
#define getuid fake_uid
#define lstat fake_lstat
#define fstat fake_fstat
#define open fake_open
#define ioctl fake_ioctl
#include "console-vdagent-probe.c"
'''

class VdagentProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cc=shutil.which('cc')
        if not cc:raise unittest.SkipTest('C compiler unavailable')
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        (cls.root/'harness.c').write_text(HARNESS)
        cls.binary=cls.root/'probe'
        subprocess.run([cc,'-std=gnu11','-Wall','-Wextra','-Werror','-I',str(ROOT/'tools'),str(cls.root/'harness.c'),'-o',str(cls.binary)],check=True,capture_output=True)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def run_case(self,case,stage,passed=False):
        import os
        result=subprocess.run([str(self.binary)],env=dict(os.environ,PROBE_CASE=case),capture_output=True,text=True,timeout=12)
        self.assertEqual(result.returncode,0 if passed else 2,result.stderr)
        value=json.loads(result.stdout);self.assertEqual(value['stage'],stage)
        self.assertEqual(value['passed'],passed)
        self.assertEqual(value['device_bytes_read'],0);self.assertEqual(value['device_bytes_written'],0)
        return value
    def test_independent_child_open_is_refused(self):
        import errno
        self.assertEqual(self.run_case('pass','exclusive-second-open-refused',True)['second_open_errno'],errno.EBUSY)
    def test_ioctl_success_without_exclusion_is_not_a_pass(self):
        self.assertEqual(self.run_case('exclusivity-ignored','exclusive-not-demonstrated')['second_open_errno'],0)
    def test_unsupported_ioctl_does_not_attempt_handshake(self):
        import errno
        self.assertEqual(self.run_case('unsupported','exclusive-unsupported-or-refused')['errno'],errno.ENOTTY)
    def test_identity_replacement_refused(self):self.run_case('replaced','identity-changed')
    def test_symlink_refused(self):self.run_case('symlink','not-character-device')
    def test_root_cannot_qualify_nonroot_exclusivity(self):self.run_case('root','requires-ordinary-nonroot-uid')

if __name__=='__main__':unittest.main()
