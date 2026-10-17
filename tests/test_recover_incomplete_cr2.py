import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tests.test_critical_replay import snapshot_lines

ROOT = Path(__file__).resolve().parents[1]

def load():
    path = ROOT/'tools/recover-incomplete-cr2.py'
    spec = importlib.util.spec_from_file_location('recover_incomplete_cr2', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

class RecoverIncompleteCr2Tests(unittest.TestCase):
    def test_actual_candidate190_builds_proof_without_writing(self):
        run=Path.home()/'macos-vm/run/metal-024-190'
        if not run.exists(): self.skipTest('candidate190 evidence unavailable')
        before={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
                for p in run.iterdir() if p.is_file()}
        proof=load().build_proof(run)
        after={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
               for p in run.iterdir() if p.is_file()}
        self.assertEqual(before,after)
        self.assertEqual(proof['lease_seed']['source_snapshots'],list(range(4,13)))
        self.assertFalse(proof['authorizes_launch'])
        self.assertEqual(proof['classification_unchanged'],'INVALID')

    def test_actual_candidate190_schema6_receipt_uses_manifest_helper_binding(self):
        vm=Path.home()/'macos-vm'; run=vm/'run/metal-024-190'
        if not run.exists(): self.skipTest('candidate190 evidence unavailable')
        tool=load(); proof=tool.build_proof(run)
        receipt_path=(vm/'run/vfio-recovery'/proof['boot_id']/(proof['run_id']+'.json'))
        if not receipt_path.exists(): self.skipTest('candidate190 receipt unavailable')
        receipt=json.loads(receipt_path.read_text()); manifest=json.loads((run/'manifest.json').read_text())
        experiment=tool.load('experiment')
        # recovery_helpers_sha256 is candidate-190's own frozen record (in both
        # the real receipt and its manifest): it names the helper files as they
        # were that boot, and legitimately no longer matches
        # proof['current_recovery_helpers_sha256'] once a helper is
        # deliberately updated (e.g. tools/vfio-recover.py's
        # UMA-size-dependent CONFIG_MEMSIZE detection). Rebind both -- same
        # paths, live values -- so this test still proves everything else
        # about the frozen receipt validates under current logic, without
        # asserting helper bytes are frozen forever.
        current = proof['current_recovery_helpers_sha256']
        self.assertEqual(set(receipt['recovery_helpers_sha256']), set(current))
        self.assertEqual(set(manifest['recovery_helpers_sha256']), set(current))
        rebound = dict(receipt, recovery_helpers_sha256=current)
        rebound_manifest = dict(manifest, recovery_helpers_sha256=current)
        self.assertEqual(
            tool.receipt_errors(experiment,rebound,proof,rebound_manifest,vm),[])
        self.assertEqual(experiment.validate_reuse_receipt(
            receipt,proof['boot_id'],proof['run_id'],vm),['recovery_receipt'])

    def test_execute_requires_reviewed_hash_and_writes_attempt_first(self):
        tool = load()
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp); proof = directory/'proof.json'
            proof.write_text('{"schema":1}\n')
            digest = hashlib.sha256(proof.read_bytes()).hexdigest(); seen=[]
            result = tool.execute_once(directory, proof, digest,
                lambda: seen.append((directory/'attempt.json').exists()) or
                        {'schema':6, 'status':'recovered', 'authorizes_launch':True},
                lambda receipt: [])
            self.assertEqual(seen, [True]); self.assertEqual(result['status'], 'complete')
            with self.assertRaises(FileExistsError):
                tool.execute_once(directory, proof, digest, lambda: None, lambda r: [])

    def test_wrong_review_hash_makes_no_files(self):
        tool = load()
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp); proof=directory/'proof.json'; proof.write_text('{}\n')
            with self.assertRaisesRegex(ValueError, 'reviewed proof'):
                tool.execute_once(directory, proof, '0'*64, lambda: None, lambda r: [])
            self.assertFalse((directory/'attempt.json').exists())

    def test_invalid_receipt_is_preserved_and_fails(self):
        tool=load()
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp); proof=directory/'proof.json'; proof.write_text('{}\n')
            digest=hashlib.sha256(proof.read_bytes()).hexdigest()
            receipt={'schema':6,'status':'incomplete','authorizes_launch':False}
            result=tool.execute_once(directory,proof,digest,lambda:receipt,
                                     lambda value:['recovery_receipt'])
            self.assertEqual(result['status'],'failed'); self.assertEqual(result['recovery'],receipt)

    def test_seed_refuses_conflict_abort_partial_unknown_and_index_change(self):
        tool=load(); replay=tool.load('critical-replay'); build='0'*32
        base=['BUILD: identity='+build,'XH2 OWNED nonce=a','gap',
              'XH2 POOL state=ACTIVE nonce=b','XH3 LIFETIME state=VALID nonce=c']
        cases=[]
        changed=base.copy(); changed[3]+='x'; cases.append((snapshot_lines(base,4,build)[:-1]+snapshot_lines(changed,5,build)[:-1],'conflicting'))
        cases.append((snapshot_lines(base+['XH2 ABORT reason=x'],4,build)[:-1],'ABORT'))
        unknown=base+['XH3 UNKNOWN']; cases.append((snapshot_lines(unknown,4,build)[:-1],'malformed'))
        long=base+['XH2 ABORT '+'x'*180]; lines=snapshot_lines(long,6,build)[:-1]
        lines=[x for x in lines if ' r=0005 p=01/' not in x]; cases.append((lines,'partial'))
        shifted=['prefix']+base; cases.append((snapshot_lines(base,4,build)[:-1]+snapshot_lines(shifted,5,build)[:-1],'index changed'))
        for lines,error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError,error):
                tool.recovery_lease_seed(''.join(lines),build,replay)

if __name__ == '__main__': unittest.main()
