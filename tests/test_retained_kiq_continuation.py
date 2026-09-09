import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def load_tool():
    path = ROOT/'tools/retained-kiq-continuation.py'
    spec = importlib.util.spec_from_file_location('retained_kiq_continuation', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RetainedKiqContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tool = load_tool()

    def scan(self, pq_status=1):
        tool = self.tool
        compute = []
        for selector in tool.COMPUTE_SELECTORS:
            row = {'selector':selector, 'active':0,
                   'pq_doorbell_control':0x80000000 if selector in (9, 521) else 0}
            if selector == 9:
                row['host_kiq'] = {'dequeue':0, 'rptr':0,
                                   'wptr_lo':0, 'wptr_hi':0}
            compute.append(row)
        graphics = {'pipes':[
            {'selector':0, 'active':0, 'doorbell_status':0,
             'wptr':0, 'wptr_hi':0},
            {'selector':1, 'active':0, 'doorbell_status':0,
             'wptr':0, 'wptr_hi':0}],
            'final_default':{'completed':True, 'value':0}}
        one = {
            'compute':compute, 'graphics':graphics,
            'globals':{
                'cp_stat':0, 'cpc_busy':0, 'me_cntl':0x15000000,
                'mec_cntl':0x50000000, 'pq_wptr_poll_cntl':0,
                'pq_status':pq_status, 'doorbell_range_lower':0,
                'doorbell_range_upper':0, 'sdma0_cntl':0,
                'sdma0_f32_cntl':1, 'sdma0_gfx_rb_cntl':0x20,
                'sdma0_gfx_ib_cntl':0x100, 'sdma0_status':1,
                'sdma0_page_rb_cntl':0x80840020,
                'sdma0_page_ib_cntl':0x100,
                'sdma0_rlc0_rb_cntl':0x20, 'sdma0_rlc0_ib_cntl':0x100,
                'sdma0_rlc1_rb_cntl':0x20, 'sdma0_rlc1_ib_cntl':0x100,
            },
        }
        return {'passes':[one, copy.deepcopy(one)],
                'selector_writes':[{'completed':True} for _ in range(137)],
                'final_default':{'attempted':True, 'completed':True, 'value':0}}

    def evidence(self, contract):
        tool = self.tool
        boot, prior = contract['boot_id'], contract['prior_run_id']
        recovery = {
            'schema':5, 'status':'incomplete', 'authorizes_launch':False,
            'boot_id':boot, 'prior_run_id':prior,
            'recovery_id':contract['historical_recovery_id'],
            'commands':[
                {'command':0x30000, 'response':0x80030000, 'confirmed':True},
                {'command':0xc0000, 'response':0x800c0000, 'confirmed':True}],
            'gc_quiesce':{
                'status':'quiesced', 'gfx_needs_unmap':True,
                'gfx_retirement_confirmed':False,
                'graphics_pipes_after_retirement':{
                    'pipes':[{'selector':0, 'active':0, 'doorbell_status':0},
                             {'selector':1, 'active':0, 'doorbell_status':0}]},
            },
        }
        sequence = 0x667b2f65
        _, expected_mqd = tool.OBSERVER.expected_images(sequence)
        mqd = bytearray(expected_mqd)
        for index, value in tool.MQD_STATUS_WRITEBACK:
            mqd[index*4:index*4+4] = value.to_bytes(4, 'little')
        observation = {
            'schema':1, 'kind':'retained-host-kiq-observation',
            'status':'observed', 'authorizes_launch':False,
            'authorizes_recovery':False, 'authorizes_cleanup':False,
            'boot_id':boot, 'run_id':prior,
            'device':{
                'analysis':{'sequence':sequence, 'ring_exact':True,
                            'mqd_exact':False, 'stored_wptr':0x100,
                            'stored_wptr_expected':0x100,
                            'current_report':0x100, 'current_fence':sequence,
                            'fence_matches_sequence':True},
                'ranges':[{'name':'mqd', 'passes':[{
                    'data_hex':bytes(mqd).hex()}, {'data_hex':bytes(mqd).hex()}]}],
            },
        }
        idle = {'schema':1, 'status':'failed', 'authorizes_launch':False,
                'authorizes_recovery':False, 'authorizes_cleanup':False,
                'boot_id':boot, 'run_id':prior}
        prepare = {'schema':1, 'status':'failed', 'authorizes_launch':False,
                   'authorizes_recovery':False, 'authorizes_cleanup':False,
                   'boot_id':boot, 'run_id':prior,
                   'transaction':{'writes':[
                       {'offset':0x4d08, 'before':0x101, 'value':0x100,
                        'posted':0x100, 'completed':True},
                       {'offset':0x4ce0, 'before':0x80840021,
                        'value':0x80840020, 'posted':0x80840020,
                        'completed':True},
                       {'offset':0xc8fc, 'before':0x100, 'value':0,
                        'posted':0x100, 'completed':False}]}}
        doorbell = {'schema':1, 'status':'failed', 'authorizes_launch':False,
                    'authorizes_recovery':False, 'authorizes_cleanup':False,
                    'boot_id':boot, 'run_id':prior,
                    'transaction':{'doorbell_writes':[{
                        'attempted':True, 'barrier':0x200, 'completed':True,
                        'index':0, 'offset':0, 'sequence':0,
                        'store_completed':True, 'width_bits':64, 'value':0}],
                        'interim_samples':[{'active':0, 'mec_cntl':0x50000000,
                                            'wptr_lo':0, 'wptr_hi':0}],
                        'after':self.scan(3)}}
        closure = {'schema':1, 'kind':'retained-kiq-global-doorbell-close',
                   'status':'completed-nonauthorizing',
                   'authorizes_launch':False, 'authorizes_recovery':False,
                   'authorizes_cleanup':False, 'boot_id':boot, 'run_id':prior,
                   'transaction':{
                       'status':'global-doorbell-gate-closed-nonauthorizing',
                       'authorizes_launch':False, 'authorizes_recovery':False,
                       'authorizes_cleanup':False,
                       'writes':[{'attempted':True, 'before':3, 'completed':True,
                                  'observed_before':3, 'offset':0xc2e0,
                                  'posted':1, 'sequence':0,
                                  'store_completed':True, 'value':1}],
                       'after':self.scan(1)},
                   'postflight':{'doorbell_proof':{'preparation_proof':{
                       'scanner_proof':{'base':{
                           'journal_cursor':'closure-cursor'}}}}}}
        return {'recovery':recovery, 'receipt':copy.deepcopy(recovery),
                'observation':observation, 'idle':idle, 'preparation':prepare,
                'doorbell_zero':doorbell, 'global_close':closure}

    def setup_vm(self, directory):
        tool = self.tool
        vm = Path(directory)/'vm'; repo = Path(directory)/'repo'
        vm.mkdir(); repo.mkdir()
        contract = copy.deepcopy(tool.FIXED_CONTRACT)
        contract['evidence'] = {}
        for name, value in self.evidence(contract).items():
            relative = Path('run/evidence')/(name+'.json')
            path = vm/relative; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, sort_keys=True))
            contract['evidence'][name] = {
                'path':str(relative),
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
        ledger = {'schema':2, 'boot_id':contract['boot_id'], 'max_launches':3,
                  'launches':[
                      {'run_id':contract['first_run_id']},
                      {'run_id':contract['prior_run_id'],
                       'prior_run_id':contract['first_run_id'],
                       'recovery_id':contract['startup_recovery_id'],
                       'attempt_id':contract['startup_attempt_id']} ]}
        ledger_path = vm/'run/used-gpu-boots'/(contract['boot_id']+'.json')
        ledger_path.parent.mkdir(parents=True); ledger_path.write_text(
            json.dumps(ledger, sort_keys=True)+'\n')
        contract['ledger_sha256'] = hashlib.sha256(ledger_path.read_bytes()).hexdigest()
        spec = json.loads((ROOT/'experiments/metal-009.json').read_text())
        manifest = {
            'boot_id':contract['boot_id'], 'run_id':'c'*32,
            'build_id':'d'*32, 'source_commit':'e'*40,
            'built_from_commit':'e'*40, 'source_sha256':'1'*64,
            'binary_sha256':'2'*64, 'info_sha256':'3'*64,
            'bootdisk_sha256':'4'*64, 'candidate_directory':'run/candidate-176',
            'max_seconds':180, 'gpu':True, 'source_clean':True, 'spec':spec,
        }
        manifest_path = vm/'run/metal-009-176-manifest.json'
        manifest_path.write_text(json.dumps(manifest, sort_keys=True)+'\n')
        for relative in tool.SOURCE_PATHS:
            path = repo/relative; path.parent.mkdir(parents=True, exist_ok=True)
            if relative == 'experiments/metal-009.json':
                path.write_bytes((ROOT/relative).read_bytes())
            else:
                path.write_text(relative+'\n')
        source_hashes = tool.source_hashes(repo)
        seal = {
            'schema':1, 'kind':'reviewed-candidate176-retained-kiq-seal',
            'approved_for_one_launch':True,
            'boot_id':contract['boot_id'], 'prior_run_id':contract['prior_run_id'],
            'next_run_id':manifest['run_id'], 'target_version':'1.0.176',
            'manifest_path':'run/metal-009-176-manifest.json',
            'manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'build_id':manifest['build_id'], 'source_commit':manifest['source_commit'],
            'source_sha256':manifest['source_sha256'],
            'binary_sha256':manifest['binary_sha256'],
            'info_sha256':manifest['info_sha256'],
            'bootdisk_sha256':manifest['bootdisk_sha256'],
            'ledger_sha256':contract['ledger_sha256'],
            'evidence_sha256':{name:row['sha256']
                               for name,row in contract['evidence'].items()},
            'source_hashes':source_hashes,
        }
        seal_path = vm/'run/retained-kiq-continuation-seal.json'
        seal_path.write_text(json.dumps(seal, sort_keys=True)+'\n')
        host = tool.test_host_fixture(contract['boot_id'])
        return (vm, repo, contract, manifest_path, seal_path, host,
                hashlib.sha256(seal_path.read_bytes()).hexdigest(),
                source_hashes['tools/retained-kiq-continuation.py'])

    def test_unsealed_production_contract_refuses(self):
        tool = self.tool
        self.assertIn('candidate seal is not configured',
                      tool.contract_errors(tool.FIXED_CONTRACT, None))

    def test_exact_chain_creates_and_revalidates_one_use_receipt(self):
        tool = self.tool
        with tempfile.TemporaryDirectory() as temp:
            vm, repo, contract, manifest, seal, host, seal_sha, tool_sha = \
                self.setup_vm(temp)
            output = vm/'run/retained-kiq-continuations'/contract['boot_id']/(
                contract['prior_run_id']+'.json')
            cursors = []
            receipt = tool.authorize_once(
                vm, manifest, seal, output, tool_sha, seal_sha,
                contract=contract, source_root=repo,
                loaded_source_sha256=tool_sha,
                host_reader=lambda cursor=None:(
                    cursors.append(cursor) or copy.deepcopy(host)),
                id_factory=iter(('f'*32, 'e'*32)).__next__, now=lambda:123.0)
            self.assertEqual(cursors, ['closure-cursor'])
            self.assertTrue(receipt['authorizes_launch'])
            self.assertEqual(receipt['next_run_id'], 'c'*32)
            self.assertEqual(tool.validate_receipt(
                receipt, vm, contract['boot_id'], contract['prior_run_id'],
                'c'*32, json.loads(manifest.read_text()), manifest,
                contract=contract, source_root=repo,
                host_reader=lambda cursor=None:copy.deepcopy(host)), [])
            with self.assertRaises(FileExistsError):
                tool.authorize_once(
                    vm, manifest, seal, output, tool_sha, seal_sha,
                    contract=contract, source_root=repo,
                    loaded_source_sha256=tool_sha,
                    host_reader=lambda cursor=None:copy.deepcopy(host))

    def test_artifact_manifest_source_ledger_and_host_changes_fail_closed(self):
        tool = self.tool
        with tempfile.TemporaryDirectory() as temp:
            vm, repo, contract, manifest, seal, host, seal_sha, tool_sha = \
                self.setup_vm(temp)
            output = vm/'run/retained-kiq-continuations'/contract['boot_id']/(
                contract['prior_run_id']+'.json')
            receipt = tool.authorize_once(
                vm, manifest, seal, output, tool_sha, seal_sha,
                contract=contract, source_root=repo,
                loaded_source_sha256=tool_sha,
                host_reader=lambda cursor=None:copy.deepcopy(host),
                id_factory=iter(('f'*32, 'e'*32)).__next__)

            cases = []
            artifact = vm/contract['evidence']['global_close']['path']
            cases.append(('artifact', artifact, artifact.read_bytes()+b'\n'))
            cases.append(('manifest', manifest, manifest.read_bytes()+b'\n'))
            source = repo/tool.SOURCE_PATHS[0]
            cases.append(('source', source, source.read_bytes()+b'changed'))
            proof_source = repo/'tools/kiq-recovery-proof.py'
            cases.append(('proof-source', proof_source,
                          proof_source.read_bytes()+b'changed'))
            ledger = vm/'run/used-gpu-boots'/(contract['boot_id']+'.json')
            cases.append(('ledger', ledger, ledger.read_bytes()+b'\n'))
            for label, path, changed in cases:
                with self.subTest(label=label):
                    original = path.read_bytes(); path.write_bytes(changed)
                    errors = tool.validate_receipt(
                        receipt, vm, contract['boot_id'], contract['prior_run_id'],
                        'c'*32, json.loads(manifest.read_text().splitlines()[0]),
                        manifest, contract=contract, source_root=repo,
                        host_reader=lambda cursor=None:copy.deepcopy(host))
                    self.assertTrue(errors)
                    path.write_bytes(original)

            bad_host = copy.deepcopy(host); bad_host['residual_units'] = ['rgpu-launch-x']
            self.assertIn('fresh host residual launch units', tool.validate_receipt(
                receipt, vm, contract['boot_id'], contract['prior_run_id'],
                'c'*32, json.loads(manifest.read_text()), manifest,
                contract=contract, source_root=repo,
                host_reader=lambda cursor=None:bad_host))

    def test_reviewed_seal_hash_and_unique_identifiers_are_required(self):
        tool = self.tool
        with tempfile.TemporaryDirectory() as temp:
            vm, repo, contract, manifest, seal, host, seal_sha, tool_sha = \
                self.setup_vm(temp)
            output = vm/'run/retained-kiq-continuations'/contract['boot_id']/(
                contract['prior_run_id']+'.json')
            with self.assertRaisesRegex(tool.ContinuationError,
                                        'reviewed seal hash'):
                tool.authorize_once(
                    vm, manifest, seal, output, tool_sha, '0'*64,
                    contract=contract, source_root=repo,
                    loaded_source_sha256=tool_sha,
                    host_reader=lambda cursor=None:copy.deepcopy(host))
            self.assertFalse(output.exists())
            with self.assertRaisesRegex(tool.ContinuationError,
                                        'identifiers are invalid'):
                tool.authorize_once(
                    vm, manifest, seal, output, tool_sha, seal_sha,
                    contract=contract, source_root=repo,
                    loaded_source_sha256=tool_sha,
                    host_reader=lambda cursor=None:copy.deepcopy(host),
                    id_factory=lambda:'f'*32)
            self.assertFalse(output.exists())

    def test_malformed_seal_manifest_and_receipt_fail_closed(self):
        tool = self.tool
        contract = copy.deepcopy(tool.FIXED_CONTRACT)
        self.assertTrue(tool.contract_errors(contract, {'source_hashes':None}))
        self.assertTrue(tool._manifest_errors([], b'[]', {}, contract))

        with tempfile.TemporaryDirectory() as temp:
            vm, repo, contract, manifest, seal, host, seal_sha, tool_sha = \
                self.setup_vm(temp)
            output = vm/'run/retained-kiq-continuations'/contract['boot_id']/(
                contract['prior_run_id']+'.json')
            receipt = tool.authorize_once(
                vm, manifest, seal, output, tool_sha, seal_sha,
                contract=contract, source_root=repo,
                loaded_source_sha256=tool_sha,
                host_reader=lambda cursor=None:copy.deepcopy(host),
                id_factory=iter(('f'*32, 'e'*32)).__next__)
            receipt['host_proof'] = []
            errors = tool.validate_receipt(
                receipt, vm, contract['boot_id'], contract['prior_run_id'],
                'c'*32, json.loads(manifest.read_text()), manifest,
                contract=contract, source_root=repo,
                host_reader=lambda cursor=None:copy.deepcopy(host))
            self.assertIn('sealed host proof', errors)

    def test_final_hardware_semantics_reject_pointer_page_and_all_ones(self):
        tool = self.tool
        contract = copy.deepcopy(tool.FIXED_CONTRACT)
        values = self.evidence(contract)
        self.assertEqual(tool.evidence_errors(values, contract), [])

        pointer = copy.deepcopy(values)
        for observed in pointer['global_close']['transaction']['after']['passes']:
            target = next(row for row in observed['compute']
                          if row['selector'] == 9)
            target['host_kiq']['wptr_lo'] = 0x100
        self.assertIn('final selector 9 state',
                      tool.evidence_errors(pointer, contract))

        page = copy.deepcopy(values)
        for observed in page['global_close']['transaction']['after']['passes']:
            observed['globals']['sdma0_page_rb_cntl'] |= 1
        self.assertIn('final SDMA state', tool.evidence_errors(page, contract))

        inaccessible = copy.deepcopy(values)
        for observed in inaccessible['global_close']['transaction']['after']['passes']:
            observed['globals']['mec_cntl'] = 0xffffffff
        self.assertIn('final CP/ingress state',
                      tool.evidence_errors(inaccessible, contract))

    def test_creation_rejects_fault_since_the_closure_cursor(self):
        tool = self.tool
        with tempfile.TemporaryDirectory() as temp:
            vm, repo, contract, manifest, seal, host, seal_sha, tool_sha = \
                self.setup_vm(temp)
            output = vm/'run/retained-kiq-continuations'/contract['boot_id']/(
                contract['prior_run_id']+'.json')
            seen = []
            bad = copy.deepcopy(host)
            bad['journal_faults'] = ['vfio failed after closure']
            with self.assertRaisesRegex(tool.ContinuationError,
                                        'fresh host journal faults'):
                tool.authorize_once(
                    vm, manifest, seal, output, tool_sha, seal_sha,
                    contract=contract, source_root=repo,
                    loaded_source_sha256=tool_sha,
                    host_reader=lambda cursor:(seen.append(cursor) or bad))
            self.assertEqual(seen, ['closure-cursor'])
            self.assertFalse(output.exists())
if __name__ == '__main__':
    unittest.main()
