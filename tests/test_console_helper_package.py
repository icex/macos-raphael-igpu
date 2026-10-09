import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile
ROOT=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('package_console',ROOT/'tools/package-console-helpers.py')
tool=importlib.util.module_from_spec(s);s.loader.exec_module(tool)

class PackageTests(unittest.TestCase):
    def test_exact_archive_manifest_and_repeatability(self):
        with tempfile.TemporaryDirectory() as directory:
            a=Path(directory)/'a.zip';b=Path(directory)/'b.zip'
            manifest=tool.package(ROOT,a);tool.package(ROOT,b)
            self.assertEqual(a.read_bytes(),b.read_bytes())
            with zipfile.ZipFile(a) as z:
                self.assertEqual(set(z.namelist()),{Path(n).name for n in tool.FILES}|{'console-helper-manifest.json'})
                self.assertEqual(json.loads(z.read('console-helper-manifest.json')),manifest)
                for name,value in manifest['files'].items():
                    raw=z.read(name);self.assertEqual(len(raw),value['bytes']);self.assertEqual(hashlib.sha256(raw).hexdigest(),value['sha256'])
                self.assertEqual(z.getinfo('install-console-desktop.sh').external_attr>>16,0o100755)
            with self.assertRaises(ValueError):tool.package(ROOT,a)
    def test_missing_or_symlinked_source_refused_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);subprocess.run(['git','init','-q',str(root)],check=True)
            subprocess.run(['git','-C',str(root),'-c','user.name=test','-c','user.email=test@example.invalid','commit','-qm','empty','--allow-empty'],check=True)
            (root/'tools').mkdir();(root/tool.FILES[0]).symlink_to(ROOT/tool.FILES[0])
            output=root/'out.zip'
            with self.assertRaisesRegex(ValueError,'symlinked'):tool.package(root,output)
            self.assertFalse(output.exists())

    def test_packaged_installer_verifier_refuses_tampering(self):
        script=(ROOT/'tools/install-console-desktop.sh').read_text()
        verifier=script.split("<<'PYVERIFY'\n",1)[1].split('\nPYVERIFY',1)[0]
        receipt=script.split("<<'PYRECEIPT'\n",1)[1].split('\nPYRECEIPT',1)[0]
        compile(receipt,'installer receipt','exec')
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'source.zip';tool.package(ROOT,archive)
            extracted=root/'inputs';extracted.mkdir()
            with zipfile.ZipFile(archive) as z:z.extractall(extracted)
            import sys
            ok=subprocess.run([sys.executable,'-c',verifier,str(extracted)],capture_output=True,text=True)
            self.assertEqual(ok.returncode,0,ok.stderr)
            (extracted/'console-presenter.m').write_text('tampered')
            bad=subprocess.run([sys.executable,'-c',verifier,str(extracted)],capture_output=True,text=True)
            self.assertNotEqual(bad.returncode,0);self.assertIn('hash mismatch',bad.stderr)

    def test_receipt_payload_produces_parseable_hash_bound_json(self):
        from unittest.mock import patch
        import sys
        script=(ROOT/'tools/install-console-desktop.sh').read_text()
        receipt=script.split("<<'PYRECEIPT'\n",1)[1].split('\nPYRECEIPT',1)[0]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);app=root/'app';support=root/'support';support.mkdir()
            for name in ('MacOS/console-presenter','Helpers/virtual-display-server','Helpers/console-display-layout'):
                binary=app/'Contents'/name;binary.parent.mkdir(parents=True,exist_ok=True);binary.write_bytes(name.encode())
            def command(args,**kwargs):
                if args[0]=='codesign':return 'CDHash=0123456789\ndesignated => identifier org.raphaelgpu.console'
                return 'mock compiler/sdk'
            with patch.object(sys,'argv',['receipt',str(app),str(ROOT/'tools'),str(support)]), patch('subprocess.check_output',side_effect=command):
                exec(compile(receipt,'installed receipt','exec'),{})
            value=json.loads((support/'build-provenance.json').read_text())
            self.assertEqual(value['optimization'],'-O2')
            self.assertEqual(value['sources']['console-install-transaction.py'],hashlib.sha256((ROOT/'tools/console-install-transaction.py').read_bytes()).hexdigest())
            for name,digest in value['binaries'].items():
                self.assertEqual(digest,hashlib.sha256((app/'Contents'/name).read_bytes()).hexdigest())
