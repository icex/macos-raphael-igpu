import errno
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

P=Path(__file__).resolve().parents[1]/'tools/vbox-process.py'
S=importlib.util.spec_from_file_location('vbox_process_test',P)
M=importlib.util.module_from_spec(S);S.loader.exec_module(M)

class ProcessIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.proc=self.root/'proc'/'123';self.proc.mkdir(parents=True)
        self.bin=self.root/'bin';self.bin.mkdir();self.program=self.bin/'VirtualBoxVM';self.program.write_bytes(b'fixture');self.program.chmod(0o500)
        self.log=self.root/'vms'/'owned'/'Logs'/'VBox.log';self.log.parent.mkdir(parents=True)
        self.log.write_text('00:00:00.100000 Process ID: 123\n')
        self.stat='123 (VirtualBoxVM) '+' '.join(['S']+['0']*18+['456']+['0']*5)
        (self.proc/'stat').write_text(self.stat)
        (self.proc/'status').write_text('Uid:\t'+'\t'.join([str(os.getuid())]*4)+'\n')
        self.cmd=str(self.program).encode()+b'\0--comment\0owned\0--startvm\0exact-uuid\0'
        (self.proc/'cmdline').write_bytes(self.cmd)
        (self.proc/'exe').symlink_to(self.program)
    def read(self):
        return M.process_identity(self.root,'owned','exact-uuid',self.root/'proc',self.bin,os.getuid())
    def test_native_hardened_permission_and_explicit_evidence(self):
        linked=self.read();self.assertEqual(linked['evidence'],'kernel-executable-link')
        with patch.object(M.os,'readlink',side_effect=PermissionError(13,'hardened')):
            guarded=self.read()
        self.assertEqual(guarded['evidence'],'owned-session-log-and-process')
        self.assertEqual(guarded['pid'],123);self.assertEqual(guarded['starttime'],'456')
        with patch.object(M.os,'readlink',side_effect=PermissionError(errno.EPERM,'not EACCES')):
            with self.assertRaises(PermissionError):self.read()
        with patch.object(M.os,'readlink',side_effect=FileNotFoundError()):
            with self.assertRaises(FileNotFoundError):self.read()
    def test_log_binding_and_argv_refusals(self):
        for log in ['no pid\n','00:00:00.1 Process ID: 999\n','00:00:00.1 Process ID: 123\n00:00:00.2 Process ID: 123\n']:
            self.log.write_text(log)
            with self.assertRaises((ValueError,FileNotFoundError)):self.read()
        self.log.write_text('00:00:00.1 Process ID: 123\n')
        for cmd in [self.cmd.replace(b'exact-uuid',b'other'),self.cmd+b'--startvm\0exact-uuid\0',b'/foreign/VirtualBoxVM\0--startvm\0exact-uuid\0']:
            (self.proc/'cmdline').write_bytes(cmd)
            with self.assertRaises(ValueError):self.read()
    def test_credentials_executable_and_dead_process_refuse(self):
        (self.proc/'status').write_text('Uid:\t'+'\t'.join([str(os.getuid()+1)]*4)+'\n')
        with self.assertRaises(ValueError):self.read()
        (self.proc/'status').write_text('Uid:\t'+'\t'.join([str(os.getuid())]*4)+'\n')
        self.program.chmod(0o522)
        with self.assertRaises(ValueError):self.read()
        self.program.chmod(0o500)
        with patch.object(M.os,'readlink',return_value='/foreign/VirtualBoxVM'):
            with self.assertRaises(ValueError):self.read()
        (self.proc/'stat').write_text(self.stat.replace(') S ',') Z '))
        with self.assertRaises(ValueError):self.read()
    def test_pid_reuse_changes_pinned_token_and_log_symlink_refuses(self):
        first=self.read();(self.proc/'stat').write_text(self.stat.replace('456','789'))
        self.assertNotEqual(first,self.read())
        body=self.log.read_text();self.log.unlink();other=self.root/'other-log';other.write_text(body);self.log.symlink_to(other)
        with self.assertRaises(ValueError):self.read()

    def test_log_replacement_between_stat_and_open_refuses(self):
        other=self.root/'replacement';other.write_bytes(self.log.read_bytes())
        real_open=os.open
        def substitute(path, flags, *args, **kw):
            return real_open(other if Path(path)==self.log else path, flags, *args, **kw)
        with patch.object(M.os,'open',side_effect=substitute):
            with self.assertRaises(ValueError):self.read()

if __name__=='__main__':unittest.main()
