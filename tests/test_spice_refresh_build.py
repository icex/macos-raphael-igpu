import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('refresh_build',Path(__file__).resolve().parents[1]/'tools/build-spice-refresh-ab.py')
build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)


class SourceExtractionTests(unittest.TestCase):
    def extract(self,members):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        root=Path(temporary.name);archive=root/'source.tar';destination=root/'out';destination.mkdir()
        with tarfile.open(archive,'w') as tar:
            for member,data in members:
                tar.addfile(member,io.BytesIO(data) if data is not None else None)
        build.extract_qemu_archive(archive,destination)
        return destination
    def link(self,name,target,kind=tarfile.SYMTYPE):
        member=tarfile.TarInfo(name);member.type=kind;member.linkname=target
        return member,None
    def test_pristine_exception_skipped_regular_file_and_relative_link_preserved(self):
        regular=tarfile.TarInfo('qemu-10.1.2/configure');regular.size=5
        root=self.extract([(regular,b'hello'),self.link(build.EDK2_X11_LINK,build.EDK2_X11_TARGET),self.link('qemu-10.1.2/relative','configure')])
        self.assertEqual((root/'qemu-10.1.2/configure').read_bytes(),b'hello')
        self.assertTrue((root/'qemu-10.1.2/relative').is_symlink())
        self.assertEqual((root/'qemu-10.1.2/relative').read_bytes(),b'hello')
        self.assertFalse((root/build.EDK2_X11_LINK).is_symlink())
    def test_changed_exception_target_rejected(self):
        with self.assertRaises(tarfile.FilterError):
            self.extract([self.link(build.EDK2_X11_LINK,'/another/location')])
    def test_changed_exception_type_rejected(self):
        with self.assertRaises(tarfile.FilterError):
            self.extract([self.link(build.EDK2_X11_LINK,build.EDK2_X11_TARGET,tarfile.LNKTYPE)])
    def test_other_absolute_symlink_rejected(self):
        with self.assertRaises(tarfile.AbsoluteLinkError):
            self.extract([self.link('qemu-10.1.2/other',build.EDK2_X11_TARGET)])
    def test_relative_escape_link_rejected(self):
        with self.assertRaises(tarfile.LinkOutsideDestinationError):
            self.extract([self.link('qemu-10.1.2/escape','../../outside')])
    def test_path_traversal_regular_member_rejected(self):
        member=tarfile.TarInfo('../outside');member.size=1
        with self.assertRaises(tarfile.OutsideDestinationError):self.extract([(member,b'x')])

if __name__=='__main__':unittest.main()
