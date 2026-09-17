import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import plistlib
import ast
import copy
import hashlib
import inspect
import re
import struct
import threading
import time
from unittest.mock import patch
from types import SimpleNamespace

from tests.test_critical_replay import BUILD as CR2_BUILD, snapshot_lines

ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = {
    'kind':'isa-serial', 'version':1, 'index':1, 'io_base':760,
    'baud':115200, 'socket':'run/critical.sock', 'capture':'critical.txt'}


class ExperimentTests(unittest.TestCase):
    def module(self):
        path = ROOT / 'tools/experiment.py'
        self.assertTrue(path.exists(), 'missing experiment admission tool')
        spec = importlib.util.spec_from_file_location('experiment', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_probe_profile_binds_allowlisted_source_digest(self):
        tool = self.module()
        profile = tool.probe_profile({'probe_profile': 'small-metal'})
        source = ROOT / 'tests' / 'small_metal_probe.m'
        self.assertEqual(profile['name'], 'small-metal')
        self.assertEqual(profile['source'], 'tests/small_metal_probe.m')
        self.assertEqual(profile['source_sha256'], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_probe_profile_defaults_to_full_native_probe(self):
        tool = self.module()
        profile = tool.probe_profile({})
        self.assertEqual(profile['name'], 'native-metal')
        self.assertEqual(profile['source'], 'tests/metal_probe.m')

    def test_probe_profile_rejects_unknown_profile_and_source_override(self):
        tool = self.module()
        with self.assertRaisesRegex(ValueError, 'unsupported probe profile'):
            tool.probe_profile({'probe_profile': 'unreviewed'})
        with self.assertRaisesRegex(ValueError, 'source path'):
            tool.probe_profile({'probe_profile': 'small-metal',
                                'probe_source': 'tests/metal_probe.m'})

    def test_probe_profile_rejects_manifest_digest_tampering(self):
        tool = self.module()
        profile = tool.probe_profile({'probe_profile': 'small-metal'})
        profile['source_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'binding changed'):
            tool.probe_profile({'probe_profile': profile})

    def test_post_probe_debug_contract_is_opt_in_and_pinned(self):
        tool = self.module()
        self.assertIsNone(tool.post_probe_debug_contract({}))
        generator = 'tools/gdb-kext-source.py'
        digest = hashlib.sha256((ROOT / generator).read_bytes()).hexdigest()
        spec = {'post_probe_debug': {
            'scenario': 'post-probe', 'generator': generator,
            'generator_sha256': digest,
            'kernel_symbols': 'run/kernel.symbols',
            'raphael_binary': 'run/RaphaelGPU',
            'raphael_dsym': 'run/RaphaelGPU.dSYM',
            'kernel_symbols_sha256': 'a' * 64,
            'raphael_binary_sha256': 'b' * 64,
            'raphael_dsym_sha256': 'c' * 64,
        }}
        self.assertEqual(tool.post_probe_debug_contract(spec), dict(
            spec['post_probe_debug'], budget_seconds=30,
            cleanup_reserve_seconds=25))

    def test_post_probe_debug_contract_rejects_unpinned_paths_or_scenario(self):
        tool = self.module()
        base = {'scenario': 'post-probe', 'generator': 'tools/gdb-kext-source.py',
                'generator_sha256': hashlib.sha256(
                    (ROOT / 'tools/gdb-kext-source.py').read_bytes()).hexdigest(),
                'kernel_symbols': 'run/kernel.symbols',
                'raphael_binary': 'run/RaphaelGPU',
                'raphael_dsym': 'run/RaphaelGPU.dSYM',
                'kernel_symbols_sha256': 'b' * 64,
                'raphael_binary_sha256': 'c' * 64, 'raphael_dsym_sha256': 'd' * 64}
        for mutation, message in (
                ({'scenario': 'unknown'}, 'scenario'),
                ({'kernel_symbols': '/tmp/kernel'}, 'kernel symbols path'),
                ({'generator': '/tmp/generator.py'}, 'generator path'),
                ({'generator_sha256': '0' * 64}, 'generator digest'),
                ({'kernel_symbols_sha256': 'short'}, 'kernel symbols sha256'),
                ({'extra': True}, 'fields')):
            bad = dict(base, **mutation)
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                tool.post_probe_debug_contract({'post_probe_debug': bad})

    def test_post_probe_debug_budget_is_strictly_before_cleanup_and_nonce_bound(self):
        tool = self.module()
        contract = {'scenario': 'post-probe', 'generator': 'tools/gdb-kext-source.py',
                    'generator_sha256': hashlib.sha256(
                        (ROOT / 'tools/gdb-kext-source.py').read_bytes()).hexdigest(),
                    'kernel_symbols': 'run/kernel.symbols',
                    'raphael_binary': 'run/RaphaelGPU',
                    'raphael_dsym': 'run/RaphaelGPU.dSYM',
                    'kernel_symbols_sha256': 'a' * 64,
                    'raphael_binary_sha256': 'b' * 64,
                    'raphael_dsym_sha256': 'c' * 64,
                    'budget_seconds': 30, 'cleanup_reserve_seconds': 25}
        plan = tool.post_probe_capture_plan(
            {'run_id': 'a' * 32, 'post_probe_debug': contract},
            {'deadline_epoch': 220, 'launch_deadline_epoch': 220}, now=160)
        self.assertEqual(plan['run_id'], 'a' * 32)
        self.assertEqual(plan['capture_deadline_epoch'], 175)
        self.assertEqual(plan['capture_window_end_epoch'], 190)
        self.assertEqual(plan['cleanup_deadline_epoch'], 220)
        for state in ({'deadline_epoch': 184, 'launch_deadline_epoch': 184},
                      {'deadline_epoch': 200, 'launch_deadline_epoch': 150}):
            with self.assertRaisesRegex(ValueError, 'budget'):
                tool.post_probe_capture_plan(
                    {'run_id': 'a' * 32, 'post_probe_debug': contract}, state, now=160)

    def test_post_probe_capture_persists_trigger_before_runner_and_binds_command(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm / 'run').mkdir()
            (vm / 'run/kernel.symbols').write_bytes(b'kernel')
            (vm / 'run/RaphaelGPU').write_bytes(b'binary')
            dwarf = vm / 'run/RaphaelGPU.dSYM/Contents/Resources/DWARF'
            dwarf.mkdir(parents=True); (dwarf / 'RaphaelGPU').write_bytes(b'dwarf')
            contract = {
                'scenario': 'post-probe', 'generator': 'tools/gdb-kext-source.py',
                'generator_sha256': hashlib.sha256(
                    (ROOT / 'tools/gdb-kext-source.py').read_bytes()).hexdigest(),
                'kernel_symbols': 'run/kernel.symbols',
                'raphael_binary': 'run/RaphaelGPU',
                'raphael_dsym': 'run/RaphaelGPU.dSYM',
                'kernel_symbols_sha256': hashlib.sha256(b'kernel').hexdigest(),
                'raphael_binary_sha256': hashlib.sha256(b'binary').hexdigest(),
                'raphael_dsym_sha256': hashlib.sha256(b'dwarf').hexdigest(),
            }
            manifest = {'run_id': 'a' * 32, 'build_id': 'b' * 32,
                        'boot_id': 'boot', 'spec': {
                            'probe_profile': 'small-metal',
                            'post_probe_debug': contract}}
            output = vm / 'evidence'; output.mkdir()
            (output / 'manifest.json').write_text(json.dumps(manifest))
            probe = {'run_id': 'a' * 32, 'output': 'RGPU_EXIT ' + 'a' * 32 + ' 124\n',
                     'transport_exit': 124}
            deadline = int(__import__('time').time()) + 200
            state = {'cid': 'c' * 64, 'deadline_epoch': deadline,
                     'launch_deadline_epoch': deadline}
            class Child:
                pid = 12345
                returncode = 0
                def communicate(self, timeout=None):
                    return '', ''
            with patch.object(tool.subprocess, 'Popen', return_value=Child()) as run:
                result = tool.run_post_probe_capture(vm, manifest, state, output, probe)
            self.assertEqual(result['status'], 'complete')
            self.assertTrue((output / 'probe-failure.json').is_file())
            self.assertTrue((output / 'post-probe-phase.json').is_file())
            args = run.call_args.args[0]
            self.assertIn('--scenario', args)
            self.assertEqual(args[args.index('--scenario') + 1], 'post-probe')
            self.assertLess((output / 'probe-failure.json').stat().st_mtime_ns,
                            (output / 'post-probe-phase.json').stat().st_mtime_ns)

    def test_post_probe_timeout_kills_group_and_records_exact_cid_detach_fallback(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm / 'run').mkdir()
            files = {'kernel.symbols': b'kernel', 'RaphaelGPU': b'binary'}
            for name, data in files.items(): (vm / 'run' / name).write_bytes(data)
            dwarf = vm / 'run/RaphaelGPU.dSYM/Contents/Resources/DWARF'; dwarf.mkdir(parents=True)
            (dwarf / 'RaphaelGPU').write_bytes(b'dwarf')
            gen = hashlib.sha256((ROOT / 'tools/gdb-kext-source.py').read_bytes()).hexdigest()
            contract = {'scenario':'post-probe', 'generator':'tools/gdb-kext-source.py',
                        'generator_sha256':gen, 'kernel_symbols':'run/kernel.symbols',
                        'raphael_binary':'run/RaphaelGPU', 'raphael_dsym':'run/RaphaelGPU.dSYM',
                        'kernel_symbols_sha256':hashlib.sha256(b'kernel').hexdigest(),
                        'raphael_binary_sha256':hashlib.sha256(b'binary').hexdigest(),
                        'raphael_dsym_sha256':hashlib.sha256(b'dwarf').hexdigest()}
            manifest = {'run_id':'a'*32, 'build_id':'b'*32, 'boot_id':'boot',
                        'spec':{'probe_profile':'small-metal','post_probe_debug':contract}}
            output = vm/'evidence'; output.mkdir(); (output/'manifest.json').write_text(json.dumps(manifest))
            probe = {'run_id':'a'*32, 'output':'RGPU_EXIT '+'a'*32+' 1\n', 'transport_exit':0}
            state = {'cid':'c'*64, 'deadline_epoch':time.time()+200,
                     'launch_deadline_epoch':time.time()+200}
            class Child:
                pid = 12345; returncode = -15; calls = 0
                def communicate(self, timeout=None):
                    self.calls += 1
                    if self.calls == 1: raise subprocess.TimeoutExpired('runner', timeout)
                    return '', ''
            class Debugger:
                def verify_port(self, cid): self.cid = cid
                def detach(self, gdb): return {'detached': True, 'returncode': 0}
            debugger = Debugger(); child = Child()
            with patch.object(tool.subprocess, 'Popen', return_value=child), \
                 patch.object(tool.os, 'killpg') as killpg, \
                 patch.object(tool, 'helper', return_value=debugger):
                result = tool.run_post_probe_capture(vm, manifest, state, output, probe)
            self.assertEqual(result['status'], 'failed')
            killpg.assert_called_once_with(child.pid, tool.signal.SIGTERM)
            fallback = json.loads((output/'post-probe-detach-fallback.json').read_text())
            self.assertTrue(fallback['detached']); self.assertEqual(fallback['cid'], state['cid'])

    def test_run_identity_check_uses_manifest_source_provenance(self):
        tool = self.module()
        self.assertIn('probe_spec=manifest', inspect.getsource(tool.run_one))

    def test_run_one_orders_post_probe_before_quiesce_and_shutdown(self):
        tool = self.module()
        source = inspect.getsource(tool.run_one)
        self.assertLess(source.index('run_post_probe_capture'),
                        source.index('quiesce_critical_producer'))
        self.assertLess(source.index('run_post_probe_capture'),
                        source.index('guest_shutdown.shutdown'))

    def test_current_identity_resolves_nested_manifest_source_provenance(self):
        tool = self.module()
        spec = {'raphael_source_sha256': 'a' * 64,
                'raphael_source_commit': 'b' * 40}
        self.assertEqual(tool.candidate_source_provenance({'spec': spec}),
                         (spec['raphael_source_sha256'],
                          spec['raphael_source_commit']))

    def test_candidate194_card_binds_small_probe_and_safety_contract(self):
        tool = self.module()
        card = json.loads((ROOT / 'experiments' / 'metal-028.json').read_text())
        self.assertEqual(tool.probe_profile(card), card['probe_profile'])
        self.assertEqual(card['candidate_version'], '1.0.194')
        self.assertEqual(card['max_seconds'], 180)
        self.assertTrue(card['run_probe_only_after_native_start'])
        self.assertEqual(card['recovery_lease_schema'], 3)
        self.assertEqual(card['critical_replay_schema'], 2)
        self.assertEqual(card['raphael_source_sha256'],
                         'c798dfd66c14c5d14160141586062ea5624f5314d14604f9d12abb40945e202d')
        self.assertEqual(card['raphael_source_commit'],
                         '52c751707c42ad037669872c081eb66bc4e2fd04')
        self.assertEqual(card['launch_options'], {
            'BOOTDISK_MODE': 'custom', 'NVRAM': 'stock',
            'GENERIC_GRAPHICS': 'off', 'GDB': 'on'})
        self.assertEqual(card['required_boot_flags'], ['-liluheadless'])

    def recovery_helper_hashes(self, schema=2):
        paths = [
            'tools/vfio-recover.py',
            'tools/recovery_lease_v2.py',
            'tools/kiq-recovery-proof.py',
        ]
        if schema == 3:
            paths += ['tools/critical-replay.py',
                      'tools/recovery_lifetime_v3.py']
        return {relative:hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()
                for relative in paths}

    def recovery_receipt(self, tool, prior='a'*32, recovery='b'*32):
        reservation = {
            'version':1, 'state':tool.RECOVERY_RESERVATION_ACTIVE,
            'heap_limit':tool.RECOVERY_HEAP_LIMIT,
            'reservation_start':tool.RECOVERY_RESERVATION_START,
            'scratch_start':tool.RECOVERY_SCRATCH_START,
            'reservation_end':tool.RECOVERY_RESERVATION_END,
            'run_id':prior, 'checksum':tool._recovery_checksum(prior),
            'consumed':True,
            'consume_hdp_flush':{'remap':0x7f000, 'posted_read':0x200},
        }
        active_observation = {key:value for key,value in reservation.items()
                              if key not in ('consumed', 'consume_hdp_flush')}
        def graphics_snapshot():
            def row(pipe):
                doorbell = 0
                return {
                    'intended_pipe':pipe, 'selector':pipe,
                    'rb0_active':0, 'rb1_active':0, 'active':0,
                    'doorbell_control':doorbell,
                    'doorbell_offset':doorbell & 0x0ffffffc,
                    'doorbell_status':doorbell & 0xc0000002,
                    'wptr':0, 'wptr_hi':0, 'base':0, 'base_hi':0, 'cntl':0,
                }
            return {'pipes':[row(0), row(1)],
                    'final_default':{'value':0, 'completed':True}}
        guard_snapshot = graphics_snapshot()
        before_snapshot = graphics_snapshot()
        after_snapshot = graphics_snapshot()
        final_snapshot = graphics_snapshot()
        regions = json.loads(json.dumps(tool.RECOVERY_BAR_REGIONS))
        return {
            'schema':5, 'status':'recovered', 'authorizes_launch':True,
            'boot_id':'boot-A', 'prior_run_id':prior, 'recovery_id':recovery,
            'device':'0000:7b:00.0', 'iommu_group':'31', 'driver':'vfio-pci',
            'pci_command_before':3, 'pci_command_after':3,
            'reset_methods_before':[], 'reset_methods_after':[],
            'bar5':dict(regions['5'], regions=regions), 'kernel_messages':[],
            'gc_quiesce':{
                'status':'quiesced', 'active_after':0,
                'dequeue_timeouts':0, 'forced_inactive':0,
                'cp_stat_after':0, 'cp_cpc_busy_after':0,
                'cp_me_after':0x15000000, 'cp_mec_after':0x50000000,
                'pq_wptr_poll_after':0, 'pq_status_after':0,
                'doorbell_range_lower_after':0, 'doorbell_range_upper_after':0,
                'sdma0_after':1, 'sdma0_cntl_after':0,
                'sdma0_rb_after':0, 'sdma0_ib_after':0,
                'gfx_ring_clean':True, 'gfx_retirement_confirmed':True,
                'graphics_pipe_proof_complete':True,
                'gfx_needs_unmap':False, 'gfx_was_stale':False,
                'host_kiq':{'status':'not-needed'}, 'reservation':reservation,
                'graphics_pipe_guard':{
                    'policy':'x6000-24G830-single-legacy-gfx-pipe-v1',
                    'reservation_before':active_observation,
                    'reservation_after':dict(active_observation),
                    'reservation_unchanged':True,
                    'pipe1_supported_state':True,
                    'snapshot':guard_snapshot,
                },
                'graphics_pipes_before':before_snapshot,
                'graphics_pipes_after_retirement':after_snapshot,
                'graphics_pipes_final':final_snapshot,
                'gfx_rb_active_after':0, 'gfx_rb_doorbell_after':0,
                'gfx_rb_wptr_after':0, 'gfx_rb_wptr_hi_after':0,
                'gfx_rb_base_after':0, 'gfx_rb_base_hi_after':0,
                'gfx_rb_cntl_after':0,
            },
            'commands':[
                {'command':0x00030000, 'response':0x80030000, 'confirmed':True},
                {'command':0x000c0000, 'response':0x800c0000, 'confirmed':True},
            ],
        }

    def host_kiq_receipt(self, tool, prior='a'*32):
        receipt = self.recovery_receipt(tool, prior)
        gc = receipt['gc_quiesce']
        fb = 0xf400000000
        physical_fb = 0x840000000
        gart_offset = 0x0e000000
        gc.update(gfx_needs_unmap=True, gfx_was_stale=True)
        before_pipe0 = gc['graphics_pipes_before']['pipes'][0]
        before_pipe0.update(rb0_active=1, active=1,
                            doorbell_control=0xc0000400,
                            doorbell_offset=0x400,
                            doorbell_status=0xc0000000)
        gc['host_kiq'] = {
            'status':'retired', 'selector':9, 'cleanup_confirmed':True,
            'gfx_active_after_unmap':0, 'gfx_active_before_scrub':0,
            'graphics_pipes_after_unmap':gc['graphics_pipes_after_retirement'],
            'packet_dwords':0x100, 'rptr_after':0x100,
            'fence_sequence':0x12345678, 'fence_after':0x12345678,
            'gfx_doorbell_offset':0x400,
            'hdp_flush':{'remap':0x7f000, 'posted_read':0x200},
            'reservation':gc['reservation'],
            'addresses':{
                'ring':fb+0x0f100000, 'mqd':fb+0x0f110000,
                'rptr':fb+0x0f111000, 'wptr':fb+0x0f111008,
                'eop':fb+0x0f112000, 'fence':fb+0x0f113000},
            'gart':{'control':1, 'root':physical_fb+gart_offset+1,
                    'start_page':0, 'end_page':0xff,
                    'physical_fb':physical_fb, 'bar_offset':gart_offset,
                    'size':0x800, 'active':True},
            'cleanup':{'mec_cntl':0x50000000, 'hqd_active':0,
                       'hqd_doorbell':0, 'hqd_rptr':0,
                       'hqd_wptr_lo':0, 'hqd_wptr_hi':0,
                       'pq_status':0, 'doorbell_range_lower':0,
                       'doorbell_range_upper':0, 'wptr_poll_cntl':0},
            'final_gate':{
                'active_after':0, 'cp_stat_after':0,
                'cp_cpc_busy_after':0, 'pq_wptr_poll_after':0,
                'pq_status_after':0, 'doorbell_range_lower_after':0,
                'doorbell_range_upper_after':0,
                'gfx_ring_clean':True, 'gfx_retirement_confirmed':True,
                'graphics_pipe_proof_complete':True},
        }
        return receipt

    def schema6_recovery_receipt(self, tool, prior='a'*32, recovery='b'*32):
        receipt = self.recovery_receipt(tool, prior, recovery)
        receipt['schema'] = 6
        gc = receipt['gc_quiesce']
        gc.update({
            'sdma0_before':0x20,
            'sdma0_cntl_before':0x00040021,
            'sdma0_rb_before':0x80840021,
            'sdma0_ib_before':0x101,
            'sdma0_page_ib_before':0x101,
            'sdma0_page_ib_after':0x100,
            'sdma0_page_rb_before':0x80840021,
            'sdma0_page_rb_after':0x80840020,
            'sdma0_status_before':1,
            'sdma0_status_after':1,
            'sdma0_shutdown_trace':[
                {'step':'disable-page-ib', 'register':0x4d08,
                 'before':0x101, 'written':0x100, 'readback':0x100},
                {'step':'disable-page-rb', 'register':0x4ce0,
                 'before':0x80840021, 'written':0x80840020,
                 'readback':0x80840020},
            ],
            'sdma0_rlc_inputs':[
                {'index':0, 'rb_before':0x200, 'rb_after':0x200,
                 'ib_before':0x100, 'ib_after':0x100},
                {'index':1, 'rb_before':0x204, 'rb_after':0x204,
                 'ib_before':0x104, 'ib_after':0x104},
            ],
        })
        return receipt

    def schema6_host_kiq_receipt(self, tool, prior='a'*32):
        receipt = self.host_kiq_receipt(tool, prior)
        page_proof = self.schema6_recovery_receipt(tool, prior)['gc_quiesce']
        receipt['schema'] = 6
        for key in ('sdma0_before', 'sdma0_cntl_before',
                    'sdma0_rb_before', 'sdma0_ib_before',
                    'sdma0_page_ib_before', 'sdma0_page_ib_after',
                    'sdma0_page_rb_before', 'sdma0_page_rb_after',
                    'sdma0_status_before', 'sdma0_status_after',
                    'sdma0_shutdown_trace', 'sdma0_rlc_inputs'):
            receipt['gc_quiesce'][key] = page_proof[key]
        return receipt

    def v2_critical_payloads(self, run_id):
        path = ROOT/'tools/recovery_lease_v2.py'
        spec = importlib.util.spec_from_file_location('lease_v2_experiment_fixture', path)
        lease = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lease)
        nonce = struct.unpack('<QQ', bytes.fromhex(run_id))
        descriptor = lease.make_ownership_descriptor(0x0a000000, *nonce)
        status = lease.make_pool_status(
            descriptor, state=lease.POOL_ACTIVE,
            pool0_before=0x0e000000, pool0_after=0x0dfeb000,
            pool1_before=0x0c000000, pool1_after=0x0bfeb000, reason=0)
        return [
            lease.format_owned_record(descriptor),
            lease.format_pool_record(status),
            'XV2 VMM phase=early enable=1 base=0 arena=0 pool0=0 pool1=0',
            'XV2 VMM phase=native enable=1 base=0xf405000000 '
            'arena=0x1234 pool0=0x2345 pool1=0x3456',
        ]

    def v2_schema6_receipt(self, tool, prior='a'*32):
        recovery = tool.helper('vfio-recover')
        wire = tool.helper('recovery_lease_v2')
        nonce = struct.unpack('<QQ', bytes.fromhex(prior))
        descriptor = wire.make_ownership_descriptor(0x08000000, *nonce)
        proof = {
            'schema':2, 'version':descriptor.version, 'state':descriptor.state,
            'lease_start':descriptor.lease_offset,
            'lease_end':descriptor.lease_end,
            'scratch_start':descriptor.scratch_offset,
            'scratch_end':descriptor.scratch_end,
            'run_id':prior, 'checksum':descriptor.checksum,
            'immutable':True, 'pool_readback':'absent', 'pool_status':None,
        }
        self.assertTrue(recovery.valid_v2_lease_proof(proof, prior))
        receipt = self.schema6_host_kiq_receipt(tool, prior)
        gc = receipt['gc_quiesce']
        gc['reservation'] = proof
        gc['graphics_pipe_guard']['reservation_before'] = proof
        gc['graphics_pipe_guard']['reservation_after'] = dict(proof)
        host_kiq = gc['host_kiq']
        host_kiq['reservation'] = proof
        fb_base = host_kiq['addresses']['ring'] - tool.RECOVERY_SCRATCH_START
        host_kiq['addresses'] = {name:fb_base + descriptor.lease_offset + offset
                                 for name, offset in {
                                     'ring':0x1000, 'mqd':0x11000,
                                     'rptr':0x12000, 'wptr':0x12008,
                                     'eop':0x13000, 'fence':0x14000}.items()}
        receipt['recovery_helpers_sha256'] = self.recovery_helper_hashes()
        return receipt

    def v3_schema6_receipt(self, tool, prior='a'*32):
        receipt = self.v2_schema6_receipt(tool, prior)
        old = receipt['gc_quiesce']['reservation']
        wire = tool.helper('recovery_lease_v2')
        lifetime = tool.helper('recovery_lifetime_v3')
        descriptor = wire.make_ownership_descriptor(
            old['lease_start'], *struct.unpack('<QQ', bytes.fromhex(prior)))
        pool = wire.make_pool_status(
            descriptor, state=wire.POOL_ACTIVE,
            pool0_before=0x0e000000, pool0_after=0x0dfeb000,
            pool1_before=0x0c000000, pool1_after=0x0bfeb000, reason=0)
        marker = lifetime.make_valid_marker(
            descriptor.pack(), pool.pack())
        proof = {
            'schema':3, 'lease_version':2, 'lifetime_version':3,
            'state':old['state'], 'lease_start':old['lease_start'],
            'lease_end':old['lease_end'], 'scratch_start':old['scratch_start'],
            'scratch_end':old['scratch_end'], 'run_id':prior,
            'checksum':old['checksum'], 'immutable':True,
            'pool_readback':'committed',
            'pool_status':{
                'state':pool.state,
                'pool0_before':pool.pool0_before,
                'pool0_after':pool.pool0_after,
                'pool1_before':pool.pool1_before,
                'pool1_after':pool.pool1_after,
                'reason':pool.reason, 'checksum':pool.checksum,
            },
            'lifetime_status':marker._asdict(),
            'lifetime_readbacks':{
                'authenticated':marker.pack().hex(),
                'pre_scratch':marker.pack().hex()},
        }
        gc = receipt['gc_quiesce']
        gc['reservation'] = proof
        gc['graphics_pipe_guard']['reservation_before'] = proof
        gc['graphics_pipe_guard']['reservation_after'] = copy.deepcopy(proof)
        gc['host_kiq']['reservation'] = proof
        receipt['recovery_lease_schema'] = 3
        receipt['recovery_helpers_sha256'] = self.recovery_helper_hashes(3)
        return receipt

    def test_identity_mismatches_and_missing_values_fail_closed(self):
        validate = self.module().validate_identity
        expected = dict(binary_sha256='a'*64, info_sha256='b'*64, boot_args='rgpu=1',
                        kdk_sha256={'HWLibs': 'c'*64}, build_id='candidate')
        self.assertEqual(validate(expected, dict(expected)), [])
        for key in expected:
            for value in (None, 'stale'):
                observed = dict(expected, **{key: value})
                self.assertIn(key, validate(expected, observed))

    def test_production_manifest_requires_all_identity_fields(self):
        check = getattr(self.module(), 'required_identity', None)
        self.assertIsNotNone(check, 'production identity completeness check missing')
        missing = check({'build_id': 'candidate'})
        for key in ('source_commit', 'kdk_sha256', 'binary_sha256', 'info_sha256',
                    'config_sha256', 'boot_args', 'image_id', 'probe_binary_sha256'):
            self.assertIn(key, missing)
        self.assertIn('recovery_lease_schema', check({
            'build_id':'candidate', 'gpu':True}))
        self.assertIn('recovery_helpers_sha256', check({
            'build_id':'candidate', 'gpu':True, 'recovery_lease_schema':2}))
        self.assertNotIn('recovery_lease_schema', check({
            'build_id':'candidate', 'gpu':True, 'recovery_lease_schema':3}))
        self.assertIn('recovery_lease_schema', check({
            'build_id':'candidate', 'gpu':True, 'recovery_lease_schema':4}))

    def test_schema6_v2_receipt_binds_dynamic_lease_and_exact_helpers(self):
        tool = self.module()
        prior = 'a'*32
        receipt = self.v2_schema6_receipt(tool, prior)
        helpers = receipt['recovery_helpers_sha256']
        self.assertEqual(tool.validate_recovery_receipt_v6(
            receipt, 'boot-A', prior, helpers), [])
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt_v6(
            receipt, 'boot-A', prior))
        stale = dict(helpers, **{'tools/vfio-recover.py':'0'*64})
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt_v6(
            receipt, 'boot-A', prior, stale))
        changed = copy.deepcopy(receipt)
        changed['gc_quiesce']['reservation']['lease_start'] += 0x100000
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt_v6(
            changed, 'boot-A', prior, helpers))
        stopped = copy.deepcopy(receipt)
        stopped['gc_quiesce']['stopped_wptr_doorbell_clear'] = {}
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt_v6(
            stopped, 'boot-A', prior, helpers))
        overlap = copy.deepcopy(receipt)
        gart = overlap['gc_quiesce']['host_kiq']['gart']
        gart['bar_offset'] = overlap['gc_quiesce']['reservation']['lease_start'] + 0x1000
        gart['root'] = gart['physical_fb'] + gart['bar_offset'] + 1
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt_v6(
            overlap, 'boot-A', prior, helpers))

    def test_schema6_v3_receipt_requires_lifetime_proof_and_exact_helpers(self):
        tool = self.module()
        prior = 'a' * 32
        receipt = self.v3_schema6_receipt(tool, prior)
        helpers = receipt['recovery_helpers_sha256']
        self.assertEqual(tool.validate_recovery_receipt_v6(
            receipt, 'boot-A', prior, helpers), [])
        for changed in (
                dict(receipt, recovery_lease_schema=2),
                dict(receipt, recovery_helpers_sha256={
                    **helpers, 'tools/recovery_lifetime_v3.py':'0' * 64}),
                dict(receipt, recovery_helpers_sha256={
                    key:value for key, value in helpers.items()
                    if key != 'tools/critical-replay.py'})):
            with self.subTest(keys=changed.keys()):
                self.assertIn('recovery_receipt',
                    tool.validate_recovery_receipt_v6(
                        changed, 'boot-A', prior, helpers))

    def test_gpu_run_refuses_manifest_without_supported_lease_before_evidence(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = {key:'fixture' for key in tool.IDENTITY_FIELDS}
            manifest.update(gpu=True, bootdisk_verified=True)
            path = root/'manifest.json'
            output = root/'evidence'
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'supported recovery lease'):
                tool.run_one(root, path, output)
            self.assertFalse(output.exists())

    def test_run_refuses_existing_output_without_changing_it(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = {key:'fixture' for key in tool.IDENTITY_FIELDS}
            manifest.update(
                gpu=True, bootdisk_verified=True, recovery_lease_schema=2,
                recovery_helpers_sha256=self.recovery_helper_hashes(),
                launch_options={'BOOTDISK_MODE':'custom', 'NVRAM':'stock'})
            path = root/'manifest.json'
            path.write_text(json.dumps(manifest))
            output = root/'evidence'
            output.mkdir()
            sentinel = output/'verdict.json'
            sentinel.write_bytes(b'frozen\n')
            with self.assertRaises(FileExistsError):
                tool.run_one(root, path, output)
            self.assertEqual(sentinel.read_bytes(), b'frozen\n')
            self.assertEqual(sorted(item.name for item in output.iterdir()),
                             ['verdict.json'])

    def test_requested_diagnostic_is_part_of_boot_identity(self):
        validate = self.module().boot_argument_errors
        baseline = ('-v rgpu=0xfffa5981 rgpuvmm=3 rgpumem=2 rgpuptb=2 '
                    'rgpumqd=2 rgpuhybrid=1 rgpusdma=1')
        self.assertEqual(validate(baseline, 'rgpusdma=1'), [])
        self.assertIn('requested_diagnostic',
                      validate(baseline.replace(' rgpusdma=1', ''), 'rgpusdma=1'))
        self.assertIn('requested_diagnostic',
                      validate(baseline.replace('rgpusdma=1', 'rgpusdma=0'), 'rgpusdma=1'))
        self.assertIn('functional_baseline',
                      validate(baseline.replace('rgpumqd=2', 'rgpumqd=1'), 'rgpusdma=1'))
        self.assertIn('retired_experiment', validate(baseline+' rgpureset=1', 'rgpusdma=1'))

    def test_v2_boot_nonce_is_little_endian_and_bound_to_explicit_run_id(self):
        tool = self.module()
        run_id = 'efcdab89674523011032547698badcfe'
        self.assertEqual(tool.recovery_nonce_words(run_id), (
            0x0123456789abcdef, 0xfedcba9876543210))
        baseline = ('-v rgpu=0xfffa5981 rgpuvmm=3 rgpumem=1 rgpuptb=2 '
                    'rgpumqd=2 rgpuhybrid=1 rgpusdma=1 '
                    'rgpurnlo=0x0123456789abcdef '
                    'rgpurnhi=18364758544493064720')
        self.assertEqual(
            tool.boot_argument_errors(baseline, 'rgpusdma=1', run_id), [])
        self.assertIn('recovery_nonce', tool.boot_argument_errors(
            baseline.replace('rgpurnhi=18364758544493064720', 'rgpurnhi=1'),
            'rgpusdma=1', run_id))
        self.assertIn('functional_baseline', tool.boot_argument_errors(
            baseline.replace('rgpumem=1', 'rgpumem=2'), 'rgpusdma=1', run_id))
        for duplicate in (
                'rgpurnlo=1 '+baseline,
                baseline+' rgpurnlo=0x0123456789abcdef'):
            self.assertIn('duplicate_boot_argument', tool.boot_argument_errors(
                duplicate, 'rgpusdma=1', run_id))
        for malformed in ('A' * 32, 'a' * 31, 'g' * 32):
            with self.subTest(run_id=malformed):
                with self.assertRaisesRegex(ValueError, 'run_id'):
                    tool.recovery_nonce_words(malformed)

    def test_gpu_prepare_requires_explicit_run_id_before_host_or_media_access(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = root / 'spec.json'
            spec.write_text(json.dumps({'candidate_version':'1.0.179'}))
            with self.assertRaisesRegex(ValueError, 'explicit run_id'):
                tool.prepare(root, spec, root/'manifest.json', gpu=True)

    def test_prepare_copies_card_pinned_replay_contracts(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            (vm / 'run').mkdir()
            card = {
                'id':'metal-015', 'candidate_version':'1.0.182',
                'requested_diagnostic':'rgpusubmit=1',
                'critical_replay_schema':2, 'recovery_lease_schema':3,
                'critical_replay_transport':TRANSPORT,
                'critical_replay_quiesce':{'version':1},
                'critical_replay_tolerance':'terminal-prefix',
                'recovery_critical_replay_tolerance':'terminal-prefix-open',
                'max_seconds':180,
            }
            spec = vm / 'card.json'
            spec.write_text(json.dumps(card))
            identity = {key:'fixture' for key in tool.IDENTITY_FIELDS}
            identity.update(source_clean=True,
                            boot_args=('rgpusubmit=1 rgpucr2uart=2 '
                                       'rgpucr2quiesce=1'),
                            launch_options={'BOOTDISK_MODE':'custom', 'NVRAM':'stock'},
                            recovery_helpers_sha256=self.recovery_helper_hashes(3))
            output = vm / 'prepared.json'
            with (patch.object(tool, 'host_snapshot', return_value={'active_vm':False}),
                  patch.object(tool, 'current_identity', return_value=identity),
                  patch.object(tool, 'verify_bootdisk'),
                  patch.object(tool, 'command', return_value='QEMU fixture')):
                prepared = tool.prepare(
                    vm, spec, output, gpu=True, run_id='0' * 32)
            self.assertEqual(prepared['critical_replay_tolerance'], 'terminal-prefix')
            self.assertEqual(prepared['critical_replay_quiesce'], {'version':1})
            self.assertEqual(prepared['recovery_critical_replay_tolerance'],
                             'terminal-prefix-open')
            self.assertEqual(prepared['spec'], card)
            self.assertEqual(json.loads(output.read_text()), prepared)

    def test_canonical_v2_records_are_extracted_before_recovery_without_tail_guessing(self):
        tool = self.module()
        serial = (
            'RGPU_RECORDS build=abc count=3 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n'
            'RGPU_EVENT build=abc seq=1 XH2 OWNED nonce=record\n'
            'RGPU_EVENT build=abc seq=2 XV2 VMM phase=native enable=1 base=0x1 arena=0x2 pool0=0x3 pool1=0x4\n'
            'RaphaelGPU rgpu: @ XH2 ABORT nonce=newer-terminal\n'
            'ordinary unterminated diagnostic')
        self.assertEqual(tool.canonical_v2_records(serial, 'abc'), [
            'XH2 OWNED nonce=record',
            'XH2 ABORT nonce=newer-terminal',
        ])

    def test_canonical_v2_records_allow_complete_direct_early_crash_evidence(self):
        tool = self.module()
        serial = (
            'RaphaelGPU rgpu: @ BUILD: identity=abc\n'
            'RaphaelGPU rgpu: @ XH2 OWNED nonce=early\n'
            'RaphaelGPU rgpu: @ XH2 ABORT nonce=early\n')
        self.assertEqual(tool.canonical_v2_records(serial, 'abc'), [
            'XH2 OWNED nonce=early', 'XH2 ABORT nonce=early'])

    def test_canonical_v2_records_reject_gap_beyond_old_129_record_check(self):
        tool = self.module()
        lines = ['RGPU_RECORDS build=abc count=131 dropped=0 truncated=0\n']
        lines.extend(
            f'RGPU_EVENT build=abc seq={seq} ordinary-{seq}\n'
            for seq in range(131) if seq != 130)
        with self.assertRaisesRegex(ValueError, 'canonical critical capture'):
            tool.canonical_v2_records(''.join(lines), 'abc')

    def test_canonical_v2_records_use_direct_wire_when_replay_crashes_mid_dump(self):
        tool = self.module()
        serial = (
            'RaphaelGPU rgpu: @ BUILD: identity=abc\n'
            'RaphaelGPU rgpu: @ XH2 OWNED nonce=direct\n'
            'RGPU_RECORDS build=abc count=131 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n'
            'RGPU_EVENT build=abc seq=1 XH2 OWNED nonce=direct\n')
        self.assertEqual(
            tool.canonical_v2_records(serial, 'abc'),
            ['XH2 OWNED nonce=direct', 'XH2 OWNED nonce=direct'])

    def test_canonical_v2_records_reject_incomplete_protocol_tail(self):
        tool = self.module()
        serial = (
            'RaphaelGPU rgpu: @ BUILD: identity=abc\n'
            'RaphaelGPU rgpu: @ XH2 OWNED nonce=direct\n'
            'RaphaelGPU rgpu: @ XH2 ABORT nonce=unterminated')
        with self.assertRaisesRegex(ValueError, 'incomplete protocol'):
            tool.canonical_v2_records(serial, 'abc')

    def test_canonical_v2_records_ignore_ordinary_unterminated_tail(self):
        tool = self.module()
        serial = (
            'RaphaelGPU rgpu: @ BUILD: identity=abc\n'
            'RaphaelGPU rgpu: @ XH2 OWNED nonce=direct\n'
            'ordinary partial line')
        self.assertEqual(tool.canonical_v2_records(serial, 'abc'), [
            'XH2 OWNED nonce=direct'])

    def test_canonical_v2_records_reject_mixed_direct_builds(self):
        tool = self.module()
        serial = (
            'RaphaelGPU rgpu: @ BUILD: identity=abc\n'
            'RaphaelGPU rgpu: @ XH2 OWNED nonce=direct\n'
            'RaphaelGPU rgpu: @ BUILD: identity=other\n')
        with self.assertRaisesRegex(ValueError, 'conflicting build'):
            tool.canonical_v2_records(serial, 'abc')

    def test_canonical_v2_records_reject_foreign_structured_wire(self):
        tool = self.module()
        serial = (
            'RGPU_RECORDS build=abc count=1 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n'
            'RGPU_RECORDS build=other count=1 dropped=0 truncated=0\n'
            'RGPU_EVENT build=other seq=0 XH2 ABORT reason=foreign\n')
        with self.assertRaisesRegex(ValueError, 'conflicting build'):
            tool.canonical_v2_records(serial, 'abc')

    def test_canonical_v2_records_bound_raw_input_before_parsing(self):
        tool = self.module()
        serial = ('RaphaelGPU rgpu: @ BUILD: identity=abc\n' +
                  'x' * (8 * 1024 * 1024))
        with self.assertRaisesRegex(ValueError, 'byte bound'):
            tool.canonical_v2_records(serial, 'abc')

    def test_manifest_serial_parser_selects_cr2_only_when_explicit(self):
        tool = self.module()
        calls = []
        classifier = SimpleNamespace(parse_serial=lambda serial, **kwargs:
                                     calls.append((serial, kwargs)) or [])
        tool.parse_manifest_serial(
            classifier, {'build_id':'a' * 32, 'critical_replay_schema':2}, 'new')
        tool.parse_manifest_serial(classifier, {'build_id':'legacy'}, 'old')
        self.assertEqual(calls, [
            ('new', {'critical_replay_schema':2, 'expected_build':'a' * 32}),
            ('old', {}),
        ])

    def test_transport_contract_is_symmetric_with_embedded_card(self):
        tool = self.module()
        manifest = {'critical_replay_schema':2,
                    'critical_replay_transport':TRANSPORT,
                    'spec':{'critical_replay_schema':2,
                            'critical_replay_transport':TRANSPORT}}
        self.assertEqual(tool.critical_replay_transport(manifest), TRANSPORT)
        tool.validate_manifest_replay_contract(manifest)
        for changed in (
                dict(manifest, spec={'critical_replay_schema':2}),
                dict(manifest, critical_replay_transport=dict(TRANSPORT, index=0))):
            with self.assertRaisesRegex(ValueError, 'critical replay transport'):
                tool.validate_manifest_replay_contract(changed)

    def test_producer_ready_is_unique_exact_and_build_bound(self):
        tool = self.module()
        build = 'a' * 32
        line = f'RGPU_UART_READY v=1 b={build} port=2\n'
        self.assertTrue(tool.critical_uart_ready(line, build))
        for capture in ('', line + line, line.replace('port=2', 'port=1'),
                        line.replace(build, 'b' * 32), line.rstrip('\n')):
            self.assertFalse(tool.critical_uart_ready(capture, build))

    def test_dedicated_recovery_refuses_complete_wire_without_ready_marker(self):
        tool = self.module()
        manifest = {'build_id':'a' * 32, 'critical_replay_schema':2,
                    'critical_replay_transport':TRANSPORT,
                    'spec':{'critical_replay_schema':2,
                            'critical_replay_transport':TRANSPORT},
                    'recovery_lease_schema':3}
        with self.assertRaisesRegex(ValueError, 'producer readiness'):
            tool.recover_v2(SimpleNamespace(), Path('/not-opened'), manifest,
                            'CR2 v=2 s=0 BEGIN\n')

    def test_running_identity_requires_exact_manifested_uart_topology(self):
        tool = self.module()
        manifest = {'image_id':'img', 'gpu':False, 'critical_replay_schema':2,
                    'critical_replay_transport':TRANSPORT}
        good = {'image_id':'img', 'vfio_args':[], 'serial_args':[
            'socket,id=rgpu_console,path=/run/vm/serial.sock,server=on,wait=off',
            'isa-serial,chardev=rgpu_console,index=0',
            'socket,id=rgpu_critical,path=/run/vm/critical.sock,server=on,wait=off',
            'isa-serial,chardev=rgpu_critical,index=1']}
        self.assertEqual(tool.validate_running(manifest, good), [])
        bad = copy.deepcopy(good)
        bad['serial_args'][-1] = 'isa-serial,chardev=rgpu_critical,index=0'
        self.assertIn('critical_uart_topology', tool.validate_running(manifest, bad))

    def test_quiesce_request_is_complete_before_publication_and_never_overwritten(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'request'
            payload = b'complete authenticated request\n'
            original_link = tool.os.link
            def observed_link(source, destination):
                self.assertFalse(target.exists())
                self.assertEqual(Path(source).read_bytes(), payload)
                original_link(source, destination)
                self.assertEqual(target.read_bytes(), payload)
            with patch.object(tool.os, 'link', side_effect=observed_link):
                tool.publish_request_once(target, payload)
            with self.assertRaises(FileExistsError):
                tool.publish_request_once(target, b'replacement')
            self.assertEqual(target.read_bytes(), payload)
            self.assertEqual(list(Path(temp).iterdir()), [target])

    def test_quiesce_producer_requires_matching_terminal_ack_and_removes_request(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm/'run').mkdir(); output = vm/'evidence'; output.mkdir()
            contract = {'version':1}
            manifest = {
                'build_id':CR2_BUILD, 'run_id':'a'*32,
                'critical_replay_schema':2,
                'critical_replay_transport':TRANSPORT,
                'critical_replay_quiesce':contract,
                'critical_replay_tolerance':'terminal-prefix',
                'spec':{'critical_replay_schema':2,
                        'critical_replay_transport':TRANSPORT,
                        'critical_replay_quiesce':contract},
            }
            state = {'cid':'c'*64}; now = [100.0]; verified = []
            lines = snapshot_lines(['BUILD: identity='+CR2_BUILD], snapshot=7)
            (vm/'run/critical.log').write_text(''.join(lines))
            request = vm/'run'/('critical-quiesce-'+'c'*64+'.request')
            ack = (f'RGPU_UART_QUIESCED v=1 b={CR2_BUILD} '
                   's=00000007 count=0001\r\n')
            def sleep(seconds):
                self.assertEqual(request.read_text(),
                    f'RGPUQ2 v=1 cid={"c"*64} b={CR2_BUILD} run={"a"*32}\n')
                with (vm/'run/critical.log').open('a') as stream: stream.write(ack)
                now[0] += seconds
            supervisor = SimpleNamespace(verify=lambda saved:verified.append(saved))
            monitor = SimpleNamespace(error=None)
            with patch.object(tool.time, 'time', side_effect=lambda:now[0]), \
                 patch.object(tool.time, 'sleep', side_effect=sleep):
                receipt = tool.quiesce_critical_producer(
                    vm, output, manifest, state, supervisor, monitor, 101)
            self.assertEqual((receipt['snapshot'], receipt['record_count']), (7, 1))
            self.assertEqual(receipt['critical_capture']['sha256'], hashlib.sha256(
                (''.join(lines)+ack).encode()).hexdigest())
            self.assertFalse(request.exists())
            self.assertEqual(json.loads((output/'critical-quiesce.json').read_text()),
                             receipt)
            self.assertTrue(verified)

    def test_quiesce_producer_fails_closed_on_ack_mismatch_or_deadline(self):
        tool = self.module()
        for mode in ('mismatch', 'deadline', 'monitor'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                vm = Path(temp); (vm/'run').mkdir(); output = vm/'evidence'; output.mkdir()
                contract = {'version':1}
                manifest = {
                    'build_id':CR2_BUILD, 'run_id':'a'*32,
                    'critical_replay_schema':2,
                    'critical_replay_transport':TRANSPORT,
                    'critical_replay_quiesce':contract,
                    'critical_replay_tolerance':'terminal-prefix',
                    'spec':{'critical_replay_schema':2,
                            'critical_replay_transport':TRANSPORT,
                            'critical_replay_quiesce':contract},
                }
                state = {'cid':'c'*64}; now = [100.0]
                capture = ''.join(snapshot_lines(
                    ['BUILD: identity='+CR2_BUILD], snapshot=7))
                if mode == 'mismatch':
                    capture += (f'RGPU_UART_QUIESCED v=1 b={CR2_BUILD} '
                                's=00000008 count=0001\r\n')
                (vm/'run/critical.log').write_text(capture)
                with patch.object(tool.time, 'time', side_effect=lambda:now[0]), \
                     patch.object(tool.time, 'sleep', side_effect=lambda seconds:
                         now.__setitem__(0, now[0]+seconds)):
                    with self.assertRaisesRegex(RuntimeError,
                            'does not match|missed cleanup boundary|host fault'):
                        tool.quiesce_critical_producer(
                            vm, output, manifest, state,
                            SimpleNamespace(verify=lambda saved:None),
                            SimpleNamespace(error=('host fault' if mode == 'monitor'
                                                   else None)), 100.2)
                self.assertFalse(any((vm/'run').glob('critical-quiesce-*.request')))
                self.assertFalse((output/'critical-quiesce.json').exists())

    def test_quiesced_capture_must_freeze_at_acknowledged_hash(self):
        tool = self.module(); capture = b'complete\r\nACK\r\n'
        receipt = {'critical_capture':{
            'byte_length':len(capture),
            'sha256':hashlib.sha256(capture).hexdigest()}}
        self.assertIsNone(tool.verify_quiesced_capture(receipt, capture))
        for changed in (capture+b'late', capture[:-1], b''):
            with self.assertRaisesRegex(RuntimeError, 'changed after'):
                tool.verify_quiesced_capture(receipt, changed)

    def test_no_generic_graphics_launch_options_and_running_argv_are_exact(self):
        tool = self.module()
        options = {'BOOTDISK_MODE':'custom', 'NVRAM':'stock',
                   'GENERIC_GRAPHICS':'off'}
        self.assertEqual(tool.launch_options({'launch_options':options}), options)
        manifest = {'image_id':'img', 'gpu':False, 'launch_options':options}
        observed = {'image_id':'img', 'vfio_args':[], 'serial_args':[],
                    'graphics_args':['-vga', 'none', '-display', 'none']}
        self.assertEqual(tool.validate_running(manifest, observed), [])
        for graphics in (
                ['-vga', 'vmware', '-display', 'none'],
                ['-vga', 'none', '-display', 'gtk'],
                ['-vga', 'none', '-display', 'none', '-device', 'virtio-vga'],
                ['-vga', 'none', '-vga', 'none', '-display', 'none']):
            with self.subTest(graphics=graphics):
                bad = dict(observed, graphics_args=graphics)
                self.assertIn('generic_graphics', tool.validate_running(manifest, bad))

    def test_historical_launch_options_remain_compatible(self):
        tool = self.module()
        old = {'BOOTDISK_MODE':'custom', 'NVRAM':'stock'}
        self.assertEqual(tool.launch_options({'launch_options':old}), old)
        with self.assertRaisesRegex(ValueError, 'launch options'):
                tool.launch_options({'launch_options':dict(old, GENERIC_GRAPHICS='on')})

    def test_debugger_launch_options_require_exact_gdb_on_no_graphics_contract(self):
        tool = self.module()
        expected = {'BOOTDISK_MODE':'custom', 'NVRAM':'stock',
                    'GENERIC_GRAPHICS':'off', 'GDB':'on'}
        self.assertEqual(tool.launch_options({'launch_options':expected}), expected)
        for bad in (dict(expected, GDB='off'), dict(expected, GDB='1'),
                    dict(expected, EXTRA='on'),
                    {'BOOTDISK_MODE':'custom', 'NVRAM':'stock', 'GDB':'on'}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, 'launch options'):
                tool.launch_options({'launch_options':bad})

    def test_critical_replay_manifest_selector_is_explicit_and_numeric(self):
        tool = self.module()
        self.assertIsNone(tool.critical_replay_schema({}))
        self.assertEqual(tool.critical_replay_schema(
            {'critical_replay_schema':2}), 2)
        for value in ('2', True, 1, 3):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'critical replay schema'):
                    tool.critical_replay_schema({'critical_replay_schema':value})

    def test_recovery_replay_selector_is_separate_and_card_pinned(self):
        tool = self.module()
        manifest = {
            'gpu':True, 'critical_replay_schema':2, 'recovery_lease_schema':3,
            'critical_replay_tolerance':'terminal-prefix',
            'recovery_critical_replay_tolerance':'terminal-prefix-open',
            'spec':{'recovery_critical_replay_tolerance':'terminal-prefix-open'},
        }
        self.assertEqual(tool.critical_replay_tolerance(manifest), 'terminal-prefix')
        self.assertEqual(tool.recovery_critical_replay_tolerance(manifest),
                         'terminal-prefix-open')
        self.assertIsNone(tool.validate_manifest_replay_contract(manifest))
        for value in ('terminal-prefix', True, 'lenient'):
            with self.subTest(value=value):
                changed = copy.deepcopy(manifest)
                changed['recovery_critical_replay_tolerance'] = value
                with self.assertRaisesRegex(ValueError, 'recovery critical replay tolerance'):
                    tool.validate_manifest_replay_contract(changed)
        changed = copy.deepcopy(manifest)
        changed['spec']['recovery_critical_replay_tolerance'] = 'different'
        with self.assertRaisesRegex(ValueError, 'does not match experiment card'):
            tool.validate_manifest_replay_contract(changed)
        changed = copy.deepcopy(manifest)
        changed.pop('recovery_critical_replay_tolerance')
        with self.assertRaisesRegex(ValueError, 'does not match experiment card'):
            tool.validate_manifest_replay_contract(changed)
        changed = copy.deepcopy(manifest)
        changed['spec'].pop('recovery_critical_replay_tolerance')
        with self.assertRaisesRegex(ValueError, 'does not match experiment card'):
            tool.validate_manifest_replay_contract(changed)

    def test_recovery_only_open_attempt_accepts_cutoff_and_keeps_classifier_closed(self):
        tool = self.module()
        terminal = ['BUILD: identity=' + CR2_BUILD,
                    'XH2 OWNED exact', 'XH2 POOL exact',
                    'XH3 LIFETIME state=VALID exact']
        later = terminal + ['VM: fault status=0x201b3b']
        serial = ''.join(snapshot_lines(terminal, snapshot=2) +
                         snapshot_lines(later, snapshot=3)[:-1])
        calls = []
        recovery = SimpleNamespace(
            parse_v2_lease_records=lambda records, run_id:
                calls.append(('parse', records, run_id)) or object(),
            recover=lambda vm, run_id, **kwargs:
                calls.append(('recover', vm, run_id, kwargs)) or {'status':'recovered'},
        )
        manifest = {
            'run_id':'0' * 32, 'build_id':CR2_BUILD, 'gpu':True,
            'critical_replay_schema':2, 'recovery_lease_schema':3,
            'critical_replay_tolerance':'terminal-prefix',
            'recovery_critical_replay_tolerance':'terminal-prefix-open',
            'recovery_helpers_sha256':self.recovery_helper_hashes(3),
            'spec':{'recovery_critical_replay_tolerance':'terminal-prefix-open'},
        }
        evidence = {}
        self.assertEqual(tool.recover_v2(
            recovery, Path('/not-opened'), manifest, serial, evidence),
            {'status':'recovered'})
        self.assertEqual(calls[0][1], ['XH2 OWNED exact', 'XH2 POOL exact'])
        self.assertEqual(evidence['tolerance'], 'terminal-prefix-open')
        self.assertEqual(evidence['open_attempt']['complete_records'],
                         ['VM: fault status=0x201b3b'])

        classifier_calls = []
        classifier = SimpleNamespace(parse_serial=lambda serial, **kwargs:
                                     classifier_calls.append(kwargs) or [])
        tool.parse_manifest_serial(classifier, manifest, serial)
        self.assertEqual(classifier_calls, [{
            'critical_replay_schema':2, 'expected_build':CR2_BUILD,
            'critical_replay_tolerance':'terminal-prefix'}])

    def test_recovery_only_open_attempt_rejects_conflict_and_abort(self):
        tool = self.module()
        terminal = ['BUILD: identity=' + CR2_BUILD,
                    'XH2 OWNED exact', 'XH2 POOL exact',
                    'XH3 LIFETIME state=VALID exact']
        manifest = {
            'run_id':'0' * 32, 'build_id':CR2_BUILD, 'gpu':True,
            'critical_replay_schema':2, 'recovery_lease_schema':3,
            'critical_replay_tolerance':'terminal-prefix',
            'recovery_critical_replay_tolerance':'terminal-prefix-open',
            'recovery_helpers_sha256':self.recovery_helper_hashes(3),
            'spec':{'recovery_critical_replay_tolerance':'terminal-prefix-open'},
        }
        recovery = SimpleNamespace(
            parse_v2_lease_records=lambda records, run_id: object(),
            recover=lambda *args, **kwargs: {'status':'recovered'},
        )
        conflict = list(terminal)
        conflict[1] = 'XH2 OWNED changed'
        serial = ''.join(snapshot_lines(terminal, snapshot=2) +
                         snapshot_lines(conflict, snapshot=3)[:-1])
        with self.assertRaisesRegex(Exception, 'conflicts with the terminal prefix'):
            tool.recover_v2(recovery, Path('/not-opened'), manifest, serial)

        aborted = terminal + ['XH2 ABORT reason=duplicate']
        serial = ''.join(snapshot_lines(terminal, snapshot=2) +
                         snapshot_lines(aborted, snapshot=3)[:-1])
        with self.assertRaisesRegex(ValueError, 'records an abort'):
            tool.recover_v2(recovery, Path('/not-opened'), manifest, serial)

    def test_recovery_only_selector_decodes_frozen_candidate181_capture(self):
        tool = self.module()
        archive = ROOT / 'findings/experiments/metal-014-181'
        manifest_raw = (archive / 'manifest.json').read_bytes()
        serial_raw = (archive / 'serial.txt').read_bytes()
        self.assertEqual(hashlib.sha256(manifest_raw).hexdigest(),
                         '738d2a4ade018a3e3721820dbc3f8ec5d38f442c6841486cf2a80445c33e3495')
        self.assertEqual(hashlib.sha256(serial_raw).hexdigest(),
                         '65fdf3f72412c077b0e2b478b04bbb32ce77002c6bc3c1fb1fed201c52025d2c')
        manifest = json.loads(manifest_raw)
        manifest['recovery_critical_replay_tolerance'] = 'terminal-prefix-open'
        manifest['spec'] = dict(
            manifest['spec'],
            recovery_critical_replay_tolerance='terminal-prefix-open')
        calls = []
        recovery = SimpleNamespace(
            parse_v2_lease_records=lambda records, run_id:
                calls.append((records, run_id)) or object(),
            recover=lambda *args, **kwargs: {'status':'recovered'},
        )
        replay_evidence = {}
        result = tool.recover_v2(
            recovery, Path('/not-opened'), manifest,
            serial_raw.decode('utf-8', errors='replace'), replay_evidence)
        self.assertEqual(result, {'status':'recovered'})
        self.assertEqual(replay_evidence['tolerance'], 'terminal-prefix-open')
        self.assertEqual(replay_evidence['snapshot'], 2)
        self.assertEqual(replay_evidence['count'], 164)
        self.assertEqual(replay_evidence['open_attempt']['snapshot'], 3)
        self.assertEqual(replay_evidence['open_attempt']['valid_chunks'], 37)
        self.assertFalse(any('ABORT' in record for record in
                             replay_evidence['open_attempt']['complete_records']))
        self.assertEqual(calls[0][1], manifest['run_id'])

    def test_only_definitive_cr2_capture_errors_abort_exposure(self):
        tool = self.module()
        pending = [{'kind':'capture_loss', 'reason':'CR2: snapshot is missing END',
                    'definitive':False}]
        corrupt = [{'kind':'capture_loss', 'reason':'CR2: snapshot CRC mismatch',
                    'definitive':True}]
        legacy = [{'kind':'capture_loss', 'reason':'conflicting replay'}]
        self.assertFalse(tool.definitive_capture_loss(pending))
        self.assertTrue(tool.definitive_capture_loss(corrupt))
        self.assertTrue(tool.definitive_capture_loss(legacy))

    def test_live_capture_state_never_admits_pending_evidence(self):
        tool = self.module()
        pending = [{'kind':'capture_loss',
                    'reason':'CR2: CR2 snapshot has a missing chunk',
                    'definitive':False}]
        fatal = [dict(pending[0], definitive=True)]
        abort = [{'kind':'recovery_lease_wire', 'raw':'XH2 ABORT reason=duplicate'}]
        self.assertEqual(tool.live_capture_state([]), 'complete')
        self.assertEqual(tool.live_capture_state(pending), 'pending')
        self.assertEqual(tool.live_capture_state(fatal), 'fatal')
        self.assertEqual(tool.live_capture_state(abort), 'fatal')

    def test_candidate182_recovery_receipt_remains_valid_with_sealed_helpers(self):
        tool = self.module()
        archive = ROOT / 'findings/experiments/metal-015-182/raw'
        manifest = json.loads((archive / 'manifest.json').read_text())
        receipt = json.loads((archive / 'recovery.json').read_text())
        self.assertEqual(tool.validate_recovery_receipt_v6(
            receipt, manifest['boot_id'], manifest['run_id'],
            manifest['recovery_helpers_sha256']), [])
        # The archived manifest's recovery_helpers_sha256 is a snapshot of the
        # helper files as they were when candidate-182 actually ran; it is not
        # asserted equal to today's tree, because a deliberate, reviewed change
        # to a recovery helper (e.g. tools/vfio-recover.py's UMA-size-dependent
        # CONFIG_MEMSIZE detection) legitimately moves those hashes. What must
        # keep working is that this frozen receipt still validates against its
        # OWN recorded hashes, which the assertion above already checks.
        self.assertEqual(set(self.recovery_helper_hashes(3)),
                         set(manifest['recovery_helpers_sha256']))

    def test_legacy_recovery_keeps_strict_unrelated_replay_conflict_gate(self):
        tool = self.module()
        run_id = '00112233445566778899aabbccddeeff'
        owned, active, *_ = self.v2_critical_payloads(run_id)
        recovery = tool.helper('vfio-recover')
        manifest = {
            'run_id':run_id, 'build_id':'abc',
            'recovery_lease_schema':2,
            'recovery_helpers_sha256':recovery.current_recovery_helpers_sha256(),
        }
        serial = (
            'RaphaelGPU rgpu: @ BUILD: identity=abc\n'
            f'RaphaelGPU rgpu: @ {owned}\n'
            f'RaphaelGPU rgpu: @ {active}\n'
            'RGPU_RECORDS build=abc count=2 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n'
            'RGPU_EVENT build=abc seq=1 ordinary intact\n'
            'RGPU_EVENT build=abc seq=1 ordinary transport-garble\n')
        with self.assertRaisesRegex(ValueError, 'conflicting replay'):
            tool.recover_v2(recovery, Path('/not-opened'), manifest, serial)

    def test_real_vfio_parser_rejects_active_then_later_abort(self):
        tool = self.module()
        recovery = tool.helper('vfio-recover')
        run_id = '00112233445566778899aabbccddeeff'
        owned, active, *_ = self.v2_critical_payloads(run_id)
        serial = (
            'RaphaelGPU rgpu: @ BUILD: identity=abc\n'
            f'RaphaelGPU rgpu: @ {owned}\n'
            f'RaphaelGPU rgpu: @ {active}\n'
            'RGPU_RECORDS build=abc count=3 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n'
            f'RGPU_EVENT build=abc seq=1 {owned}\n'
            f'RGPU_EVENT build=abc seq=2 {active}\n'
            'RaphaelGPU rgpu: @ XH2 ABORT reason=duplicate\n')
        records = tool.canonical_v2_records(serial, 'abc')
        self.assertEqual(records[-1], 'XH2 ABORT reason=duplicate')
        with self.assertRaisesRegex(recovery.RecoveryError, 'invalid native recovery lease'):
            recovery.parse_v2_lease_records(records, run_id)

    def test_v2_recovery_adapter_keeps_real_module_type_and_helper_hashes(self):
        tool = self.module()
        recovery = tool.helper('vfio-recover')
        run_id = '00112233445566778899aabbccddeeff'
        owned, active, *_ = self.v2_critical_payloads(run_id)
        manifest = {
            'run_id':run_id, 'build_id':'abc',
            'recovery_lease_schema':2,
            'recovery_helpers_sha256':recovery.current_recovery_helpers_sha256(),
        }
        serial = (
            'RGPU_RECORDS build=abc count=3 dropped=0 truncated=0\n'
            'RGPU_EVENT build=abc seq=0 BUILD: identity=abc\n'
            f'RGPU_EVENT build=abc seq=1 {owned}\n'
            f'RGPU_EVENT build=abc seq=2 {active}\n')

        def recover(vm, prior, *, lease_evidence, recovery_helpers_sha256):
            self.assertIsInstance(
                lease_evidence, recovery.RECOVERY_LEASE_V2.LeaseEvidence)
            self.assertEqual(prior, run_id)
            self.assertEqual(recovery_helpers_sha256,
                             manifest['recovery_helpers_sha256'])
            return {'status':'recovered'}

        with patch.object(recovery, 'recover', side_effect=recover):
            self.assertEqual(tool.recover_v2(
                recovery, Path('/not-opened'), manifest, serial),
                {'status':'recovered'})

    def test_v3_recovery_adapter_requires_complete_cr2_and_passes_schema(self):
        tool = self.module()
        run_id = '00112233445566778899aabbccddeeff'
        wire_records = ['XH2 OWNED exact', 'XH2 POOL exact']
        records = ['ordinary {:03d}'.format(index) for index in range(510)] + \
            wire_records
        evidence = object()
        calls = []
        recovery = SimpleNamespace(
            parse_v2_lease_records=lambda observed, nonce:
                calls.append(('parse', observed, nonce)) or evidence,
            recover=lambda vm, nonce, **kwargs:
                calls.append(('recover', vm, nonce, kwargs)) or
                {'status':'recovered'},
        )
        replay = SimpleNamespace(parse=lambda serial, build:
                                 {'records':records, 'build':build})
        manifest = {
            'run_id':run_id, 'build_id':'b' * 32,
            'critical_replay_schema':2, 'recovery_lease_schema':3,
            'recovery_helpers_sha256':self.recovery_helper_hashes(3),
        }
        with patch.object(tool, 'helper', return_value=replay):
            self.assertEqual(tool.recover_v2(
                recovery, Path('/not-opened'), manifest, 'cr2 wire'),
                {'status':'recovered'})
        self.assertEqual(calls[0], ('parse', wire_records, run_id))
        self.assertEqual(calls[1][3], {
            'lease_evidence':evidence,
            'recovery_helpers_sha256':manifest['recovery_helpers_sha256'],
            'recovery_lease_schema':3,
        })

        for bad_schema in (None, True, 1, 4):
            with self.subTest(schema=bad_schema):
                bad_manifest = dict(manifest, recovery_lease_schema=bad_schema)
                with self.assertRaisesRegex(ValueError, 'lease schema'):
                    tool.recover_v2(
                        recovery, Path('/not-opened'), bad_manifest, 'cr2 wire')

    def test_preownership_no_lease_requires_exact_zero_submission_panic(self):
        tool = self.module()
        serial = (
            'XV: AMDHWVMM::init(...) -> 1\n'
            'SUB: summary process=0/0/0 mappings=0/0/0 prepare=0/0/0 '
            'map=0/0/0 submit=0/0/0 dropped=0/0\n'
            'panic symbol: __ZN27AMDRadeonX6000_AMDHWHandler13wireSysMemoryEPvyjP11IOAccelTaskj + 0x57\n')
        self.assertTrue(tool.preownership_no_lease(serial))
        for changed in (
                serial.replace('submit=0/0/0', 'submit=1/0/0'),
                serial + 'XH2 ABORT reason=early\n',
                serial + 'XH3 LIFETIME state=VALID\n',
                serial.replace('wireSysMemory', 'other')):
            with self.subTest(changed=changed):
                self.assertFalse(tool.preownership_no_lease(changed))

    def test_raphael_target_marker_is_exact_and_bound_to_the_vbios_device(self):
        tool = self.module()
        check = getattr(tool, 'raphael_target_marked', None)
        self.assertIsNotNone(check, 'per-device Raphael identity check missing')
        path = 'PciRoot(0x0)/Pci(0x6,0x0)'
        config = {'DeviceProperties': {'Add': {path: {
            'ATY,bin_image': b'V' * 512,
            'rgpu,raphael-target': b'RGPU-RAPHAEL\x01'}}}}
        self.assertTrue(check(config))
        for value in (None, b'RGPU-RAPHAEL', b'RGPU-RAPHAEL\x00', 'RGPU-RAPHAEL\x01'):
            changed = {'DeviceProperties': {'Add': {path: dict(config['DeviceProperties']['Add'][path])}}}
            if value is None:
                changed['DeviceProperties']['Add'][path].pop('rgpu,raphael-target')
            else:
                changed['DeviceProperties']['Add'][path]['rgpu,raphael-target'] = value
            self.assertFalse(check(changed))
        wrong_path = {'DeviceProperties': {'Add': {'PciRoot(0x0)/Pci(0x7,0x0)':
                      config['DeviceProperties']['Add'][path]}}}
        self.assertFalse(check(wrong_path))
        no_vbios = {'DeviceProperties': {'Add': {path: {
                    'rgpu,raphael-target': b'RGPU-RAPHAEL\x01'}}}}
        self.assertFalse(check(no_vbios))
        short_vbios = {'DeviceProperties': {'Add': {path: {
            'ATY,bin_image': b'V' * 511,
            'rgpu,raphael-target': b'RGPU-RAPHAEL\x01'}}}}
        self.assertFalse(check(short_vbios))

    def test_ocprop_couples_target_marker_to_vbios_injection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output, rom = root/'config.plist', root/'out.plist', root/'rom.bin'
            source.write_bytes(plistlib.dumps({'DeviceProperties': {'Add': {}}}))
            rom.write_bytes(b'VBIOS')
            subprocess.run(['python3', str(ROOT/'tools/ocprop.py'), str(source),
                            '-o', str(output), '--vbios', str(rom)], check=True,
                           text=True, capture_output=True)
            config = plistlib.loads(output.read_bytes())
            props = config['DeviceProperties']['Add']['PciRoot(0x0)/Pci(0x6,0x0)']
            self.assertEqual(props['ATY,bin_image'], b'VBIOS')
            self.assertEqual(props['rgpu,raphael-target'], b'RGPU-RAPHAEL\x01')
            subprocess.run(['python3', str(ROOT/'tools/ocprop.py'), str(output),
                            '--drop-vbios'], check=True, text=True, capture_output=True)
            config = plistlib.loads(output.read_bytes())
            self.assertNotIn('PciRoot(0x0)/Pci(0x6,0x0)',
                             config['DeviceProperties']['Add'])

    def test_manifest_mode_must_be_explicit_boolean(self):
        check = self.module().required_identity
        for value in (None, 'false', 0, 1):
            self.assertIn('gpu', check({'gpu': value}))
        for value in (False, True):
            self.assertNotIn('gpu', check({'gpu': value}))

    def test_run_rejects_prepare_only_gpu_less_flag(self):
        result = subprocess.run(['python3', str(ROOT/'tools/experiment.py'), 'run',
                                 '--vm-dir', '/nonexistent', '--gpu-less'],
                                text=True, capture_output=True)
        self.assertIn('--gpu-less is only valid with prepare', result.stderr)

    def test_host_monitor_detects_fault_while_main_thread_is_blocked(self):
        tool = self.module()
        monitor_type = getattr(tool, 'HostMonitor', None)
        self.assertIsNotNone(monitor_type, 'continuous exposure monitor missing')
        interrupted = threading.Event()
        with patch.object(tool, 'kernel_updates', return_value=('next', ['Hardware Error'], ['Hardware Error'])):
            monitor = monitor_type('cursor', interrupted.set, interval=0.01)
            monitor.start()
            try: self.assertTrue(interrupted.wait(2), 'blocking operation suppressed host fault detection')
            finally: monitor.stop()
            self.assertTrue(monitor.error)
            self.assertEqual(monitor.error_kind, 'fault')
            self.assertIn('Hardware Error', monitor.messages)

    def test_host_monitor_distinguishes_capture_failure_from_kernel_fault(self):
        tool = self.module()
        published = []
        class PublicationMonitor(tool.HostMonitor):
            def __setattr__(self, name, value):
                if name == 'error' and value is not None:
                    published.append(getattr(self, 'error_kind', None))
                super().__setattr__(name, value)
        with patch.object(tool, 'kernel_updates', side_effect=RuntimeError('journal unavailable')):
            monitor = PublicationMonitor('cursor', lambda:None)
            monitor.poll()
        self.assertEqual(monitor.error_kind, 'capture')
        self.assertEqual(published, ['capture'])
        self.assertIn('capture failed', monitor.error)

    def test_failed_amdgpu_probe_is_not_completed_initialization(self):
        check = getattr(self.module(), 'amdgpu_initialized', None)
        self.assertIsNotNone(check)
        self.assertFalse(check('amdgpu 0000:7b:00.0: probe failed with error -22'))
        self.assertTrue(check('[drm] Initialized amdgpu 3.64.0 for 0000:7b:00.0 on minor 0'))
        self.assertFalse(check('[drm] Initialized amdgpu 3.64.0 for 0000:03:00.0 on minor 1'))

    def test_retained_initialization_requires_exact_same_boot_evidence(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            host = dict(boot_id='boot-A', kernel='kernel-A', device='1002:13c0',
                        driver='vfio-pci', iommu_group='31')
            snapshot = root/'host.json'
            snapshot.write_text(json.dumps(dict(host, amdgpu_initialized=True)))
            pin = root/'pin.json'
            pin.write_text(json.dumps({'snapshot':str(snapshot),
                                       'snapshot_sha256':tool.sha(snapshot.read_bytes())}))
            self.assertIsNotNone(tool.retained_amdgpu_initialization(host, '', pin))
            for key in host:
                changed = dict(host); changed[key] = 'different'
                self.assertIsNone(tool.retained_amdgpu_initialization(changed, '', pin))
            self.assertIsNone(tool.retained_amdgpu_initialization(
                host, 'amdgpu 0000:7b:00.0: probe failed with error -22', pin))
            snapshot.write_text('{}')
            self.assertIsNone(tool.retained_amdgpu_initialization(host, '', pin))
            pin.write_text('{}')
            self.assertIsNone(tool.retained_amdgpu_initialization(host, '', pin))

    def test_interactive_hold_preserves_capture_and_host_abort_paths(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'run').mkdir(); out = root/'out'; out.mkdir()
            (root/'run/serial.log').write_text(''); (root/'run/critical.log').write_text('')
            (out/'stop-requested').touch()
            manifest = {'run_id':'test', 'spec':{'interactive_hold_seconds':1800}}
            supervisor = type('S', (), {'verify':lambda self, state:None})()
            monitor = type('M', (), {'error':None})()
            with patch.object(tool, 'parse_manifest_captures', return_value=[]), \
                 patch.object(tool, 'live_capture_state', return_value='fatal'), \
                 patch.object(tool, 'write_once'), patch.object(tool.time, 'time', return_value=100):
                with self.assertRaisesRegex(RuntimeError, 'critical capture loss'):
                    tool.hold_interactive_session(root, manifest, {}, out, supervisor, monitor, None, 200)
                monitor.error = 'new host kernel fault'
                with self.assertRaisesRegex(RuntimeError, 'host kernel fault'):
                    tool.hold_interactive_session(root, manifest, {}, out, supervisor, monitor, None, 200)
                monitor.error = None
                with patch.object(tool, 'live_capture_state', return_value='complete'):
                    tool.hold_interactive_session(root, manifest, {}, out, supervisor, monitor, None, 200)

    def host(self):
        return dict(boot_id='boot-A', amdgpu_initialized=True, capture_ready=True,
                    watchdogs_verified=True, device_pinned_awake=True, active_vm=False,
                    driver='vfio-pci', device='1002:13c0', iommu_group='31',
                    device_accessible=True, reset_methods=[])

    def test_unknown_or_failed_host_gate_refuses_admission(self):
        admit = self.module().admit
        manifest = dict(max_seconds=180, boot_id='boot-A', source_clean=True,
                        vfio_device='0000:7b:00.0')
        self.assertEqual(admit(manifest, self.host(), set()), [])
        for key in ('amdgpu_initialized', 'capture_ready', 'watchdogs_verified',
                    'device_pinned_awake', 'device_accessible'):
            for value in (False, None):
                host = dict(self.host(), **{key: value})
                self.assertIn(key, admit(manifest, host, set()))
        for field, value in [('source_clean', False), ('vfio_device', None), ('max_seconds', 0)]:
            self.assertIn(field, admit(dict(manifest, **{field: value}), self.host(), set()))
        self.assertEqual(admit(dict(manifest, max_seconds=6000), self.host(), set()), [])
        self.assertIn('max_seconds', admit(dict(manifest, max_seconds=6001), self.host(), set()))
        self.assertIn('boot_already_used', admit(manifest, self.host(), {'boot-A'}))
        self.assertIn('active_vm', admit(manifest, dict(self.host(), active_vm=True), set()))
        self.assertIn('reset_method', admit(
            manifest, dict(self.host(), reset_methods=['bus']), set()))

    def test_boot_reservation_survives_failure_and_cannot_be_replaced(self):
        reserve = self.module().reserve_boot
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reserve(root, 'boot-A', 'first')
            with self.assertRaises(FileExistsError): reserve(root, 'boot-A', 'second')
            self.assertEqual(json.loads((root / 'boot-A.json').read_text())['launches'][0]['run_id'],
                             'first')

    def test_reserve_boot_has_no_launch_count_ceiling_given_a_valid_receipt(self):
        # The per-boot launch ceiling and the --manual-reuse/--ack-risk escape hatch
        # are gone. A same-boot reservation is admitted purely on a valid recovery
        # receipt for the immediately prior run, no matter how many launches the
        # ledger already records.
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); manifest_path = root/'manifest.json'
            manifest_path.write_text('{"run_id":"d"*32}\n')
            reserve = root/'boot-A.json'
            reserve.write_text(json.dumps({'schema':2, 'boot_id':'boot-A',
                                           'max_launches':3,
                                           'launches':[{'run_id':'a'}, {'run_id':'b'},
                                                       {'run_id':'c'*32}]})+'\n')
            receipt = self.recovery_receipt(tool, prior='c'*32, recovery='f'*32)
            tool.reserve_boot(root, 'boot-A', 'd'*32, receipt, None, manifest_path)
            launches = json.loads(reserve.read_text())['launches']
            self.assertEqual(len(launches), 4)
            self.assertEqual(launches[-1]['run_id'], 'd'*32)
            self.assertEqual(launches[-1]['recovery_id'], 'f'*32)
            self.assertNotIn('manual_override', launches[-1])

    def test_preexposure_failure_reconciliation_removes_only_proven_reservation(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); output = vm/'output'; output.mkdir()
            manifest = {'boot_id':'boot-A', 'run_id':'r'*32, 'source_commit':'c'*40}
            manifest_raw = json.dumps(manifest).encode(); (output/'manifest.json').write_bytes(manifest_raw)
            ledger = vm/'run/used-gpu-boots'/'boot-A.json'; ledger.parent.mkdir(parents=True)
            ledger.write_text(json.dumps({'schema':2, 'boot_id':'boot-A', 'max_launches':3,
                                          'launches':[{'run_id':'r'*32, 'reserved_epoch':1.0}]}))
            failure = SimpleNamespace(evidence={
                'schema':1, 'kind':'supervised-pre-exposure-failure', 'phase':'archive',
                'boot_id':'boot-A', 'run_id':'r'*32, 'source_commit':'c'*40,
                'manifest_sha256':tool.sha(manifest_raw), 'exposure_started':False,
                'systemd_invoked':False, 'docker_create_observed':False,
                'path':str(vm/'failure.json')})
            failure.evidence['error_type'] = 'RuntimeError'; failure.evidence['error'] = 'archive failed'
            (vm/'failure.json').write_text(json.dumps(failure.evidence))
            order = []
            original_replace = tool.os.replace
            def tracked_replace(source, destination):
                order.append('replace')
                return original_replace(source, destination)
            def tracked_fsync(path):
                order.append('fsync:'+Path(path).name)
            with patch.object(tool, 'active_launch_units', return_value=[]), \
                 patch.object(tool.subprocess, 'run', return_value=SimpleNamespace(stdout='', stderr='', returncode=0)), \
                 patch.object(tool.os, 'replace', side_effect=tracked_replace), \
                 patch.object(tool, 'fsync_directory', side_effect=tracked_fsync):
                audit = tool.reconcile_preexposure_failure(vm, output, manifest, failure)
            self.assertTrue(audit.is_file())
            self.assertFalse(ledger.exists())
            self.assertEqual(json.loads((output/'pre-exposure-ledger.json').read_text())['launches'],
                             [{'run_id':'r'*32, 'reserved_epoch':1.0}])
            self.assertTrue((output/'pre-exposure-ledger-original.json').is_file())
            self.assertLess(order.index('fsync:output'), order.index('replace'))
            self.assertGreaterEqual(order.count('fsync:used-gpu-boots'), 1)
            self.assertGreaterEqual(order.count('fsync:output'), 2)

    def test_preexposure_reconciliation_keeps_ambiguous_reservation(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); output = vm/'output'; output.mkdir()
            manifest = {'boot_id':'boot-A', 'run_id':'r'*32, 'source_commit':'c'*40}
            manifest_raw = json.dumps(manifest).encode(); (output/'manifest.json').write_bytes(manifest_raw)
            ledger = vm/'run/used-gpu-boots'/'boot-A.json'; ledger.parent.mkdir(parents=True)
            original = {'schema':2, 'boot_id':'boot-A', 'max_launches':3,
                        'launches':[{'run_id':'r'*32, 'reserved_epoch':1.0}]}
            ledger.write_text(json.dumps(original))
            failure = SimpleNamespace(evidence={
                'schema':1, 'kind':'supervised-pre-exposure-failure', 'phase':'archive',
                'boot_id':'boot-A', 'run_id':'r'*32, 'source_commit':'c'*40,
                'manifest_sha256':tool.sha(manifest_raw), 'exposure_started':False,
                'systemd_invoked':True, 'docker_create_observed':False,
                'path':str(vm/'failure.json')})
            failure.evidence['error_type'] = 'RuntimeError'; failure.evidence['error'] = 'ambiguous'
            (vm/'failure.json').write_text(json.dumps(failure.evidence))
            with self.assertRaisesRegex(ValueError, 'identity mismatch'):
                tool.reconcile_preexposure_failure(vm, output, manifest, failure)
            self.assertEqual(json.loads(ledger.read_text()), original)

    def test_prelaunch_continuation_is_exact_and_marker_is_single_use(self):
        tool = self.module()
        recovery = tool.helper('vfio-recover')
        boot = tool.PRELAUNCH_CONTINUATION['boot_id']
        run = tool.PRELAUNCH_CONTINUATION['run_id']
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); original = vm/'run/original'; original.mkdir(parents=True)
            manifest = {key:'fixture' for key in tool.IDENTITY_FIELDS}
            manifest.update(boot_id=boot, run_id=run, max_seconds=180, gpu=True,
                            source_commit='old', source_sha256='driver-tree',
                            source_clean=True, vfio_device='0000:7b:00.0',
                            candidate_directory='run/candidate-174',
                            spec={'candidate_version':'1.0.174'},
                            prelaunch_replacement_reason=
                                'remove unsafe SEM diagnostic reads and preserve bounded critical capture')
            original_manifest = dict(manifest)
            original_manifest.pop('prelaunch_replacement_reason')
            original_manifest['candidate_directory'] = 'run/candidate-173'
            original_manifest['spec'] = {'candidate_version':'1.0.173'}
            manifest_path = vm/'manifest.json'
            manifest_bytes = json.dumps(manifest).encode()
            manifest_path.write_bytes(manifest_bytes)
            original_manifest_bytes = json.dumps(original_manifest).encode()
            (original/'manifest.json').write_bytes(original_manifest_bytes)
            verdict = {'valid':False, 'verdict':'INVALID',
                       'error':'OSError: [Errno 22] Invalid argument'}
            (original/'verdict.json').write_text(json.dumps(verdict))
            old_host = dict(self.host(), boot_id=boot, sleep_inhibited=True)
            (original/'host-before.json').write_text(json.dumps(old_host))
            (original/'host-after.json').write_text(json.dumps(old_host))
            descriptor_sha = hashlib.sha256(recovery.host_kiq_reservation_descriptor(
                run, recovery.HOST_KIQ_RESERVATION_PENDING)).hexdigest()
            stages = []
            for request in ('0x3b64','0x3b65','0x3b67','0x3b68','0x3b66','0x3b6a'):
                stages.append({'operation':'ioctl','request':request,'status':'ok'})
            for length in (0x10000000, 0x200000, 0x80000):
                stages += [{'operation':'ioctl','request':'0x3b6c','status':'ok'},
                           {'operation':'mmap','length':length,'status':'ok'}]
            stages.append({'operation':'ioctl','request':'0x3b69','status':'ok'})
            proof_host = dict(boot_id=boot, active_vm=False, driver='vfio-pci',
                              device='1002:13c0', iommu_group='31', pci_command=3,
                              reset_methods=[])
            proof = {'schema':1, 'purpose':'locate prelaunch EINVAL without writes',
                     'boot_id':boot, 'run_id':run, 'constructor':'ok', 'failure':None,
                     'descriptor':{'exact_pending_match':True,
                         'expected_sha256':descriptor_sha, 'observed_sha256':descriptor_sha,
                         'expected_size':72, 'size':72},
                     'before':proof_host, 'after':proof_host, 'kernel_messages':[],
                     'pre_faults':[], 'post_faults':[], 'stages':stages}
            proof_path = vm/'proof.json'; proof_path.write_text(json.dumps(proof))
            ledger_dir = vm/'run/used-gpu-boots'; ledger_dir.mkdir(parents=True)
            ledger_path = ledger_dir/(boot+'.json')
            ledger_path.write_text(json.dumps({'schema':2, 'boot_id':boot,
                                               'launches':[{'run_id':run}]}))
            readiness = {'schema':1,
                'purpose':'bounded read-only prelaunch HDP readiness',
                'boot_id':boot, 'run_id':run, 'writes_permitted':False,
                'marker_created':False, 'constructor':'ok',
                'failure':'RuntimeError: HDP remap 0x385c != 0x7f000',
                'descriptor':{'run_id':run,
                              'state':recovery.HOST_KIQ_RESERVATION_PENDING},
                'hdp_remap_offset_register':0x385c, 'config_memsize':0x200,
                'config_memsize_valid':True, 'active_launch_units':[],
                'kernel_messages_before':[], 'kernel_faults_before':[],
                'failure_kernel_messages':[], 'failure_kernel_faults':[],
                'before_pci':proof_host, 'failure_after_pci':proof_host,
                'ledger_sha256':hashlib.sha256(ledger_path.read_bytes()).hexdigest()}
            readiness_path = vm/'run/prelaunch-readiness-e583a1b2.json'
            readiness_path.write_text(json.dumps(readiness))
            observed = dict(manifest, source_commit='new')
            current_recovery_host = dict(proof_host)
            recovery.host_state = lambda:dict(current_recovery_host)
            pinned = dict(boot_id=boot, run_id=run,
                original_manifest_sha256=hashlib.sha256(original_manifest_bytes).hexdigest(),
                replacement_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                proof_sha256=hashlib.sha256(proof_path.read_bytes()).hexdigest(),
                verdict_sha256=hashlib.sha256((original/'verdict.json').read_bytes()).hexdigest(),
                output_sha256=tool.evidence_digest(original)[0],
                readiness_sha256=hashlib.sha256(readiness_path.read_bytes()).hexdigest())
            with patch.object(tool, 'PRELAUNCH_CONTINUATION', pinned), \
                 patch.object(tool, 'helper', return_value=recovery), \
                 patch.object(tool, 'current_qemu_version', return_value='fixture'), \
                 patch.object(tool, 'active_launch_units', return_value=[]):
                evidence, got_ledger, raw = tool.validate_prelaunch_continuation(
                    vm, manifest_path, manifest, original, proof_path, observed,
                    dict(old_host), ('cursor', [], []))
                self.assertEqual(evidence['coordinator_commit'],
                                 tool.command(['git','-C',str(ROOT),'rev-parse','HEAD']))
                self.assertEqual(got_ledger, ledger_path)
                self.assertEqual(raw, ledger_path.read_bytes())
                marker = tool.prelaunch_continuation_marker(vm, boot, run)
                marker.parent.mkdir()
                tool.write_once(marker, evidence)
                with self.assertRaises(FileExistsError): tool.write_once(marker, evidence)

                (original/'supervision.json').write_text('{}')
                with self.assertRaisesRegex(ValueError, 'original_after_prelaunch'):
                    tool.validate_prelaunch_continuation(
                        vm, manifest_path, manifest, original, proof_path, observed,
                        dict(old_host), ('cursor', [], []))
                (original/'supervision.json').unlink()
                ledger_path.write_text(json.dumps({'schema':2, 'boot_id':boot,
                    'launches':[{'run_id':run}, {'run_id':'f'*32}]}))
                with self.assertRaisesRegex(ValueError, 'boot_ledger'):
                    tool.validate_prelaunch_continuation(
                        vm, manifest_path, manifest, original, proof_path, observed,
                        dict(old_host), ('cursor', [], []))
                ledger_path.write_text(json.dumps({'schema':2, 'boot_id':boot,
                                                   'launches':[{'run_id':run}]}))
                for field, value, error in (
                        ('active_vm', True, 'resume_active_vm'),
                        ('reset_methods', ['bus'], 'resume_reset_method'),
                        ('pci_command', 7, 'resume_bus_master')):
                    current_recovery_host[field] = value
                    with self.assertRaisesRegex(ValueError, error):
                        tool.validate_prelaunch_continuation(
                            vm, manifest_path, manifest, original, proof_path, observed,
                            dict(old_host), ('cursor', [], []))
                    current_recovery_host[field] = proof_host[field]
                observed['binary_sha256'] = 'changed'
                with self.assertRaisesRegex(ValueError, 'binary_sha256'):
                    tool.validate_prelaunch_continuation(
                        vm, manifest_path, manifest, original, proof_path, observed,
                        dict(old_host), ('cursor', [], []))
                observed['binary_sha256'] = manifest['binary_sha256']
                with patch.object(tool, 'current_qemu_version', return_value='changed'):
                    with self.assertRaisesRegex(ValueError, 'qemu_version'):
                        tool.validate_prelaunch_continuation(
                            vm, manifest_path, manifest, original, proof_path, observed,
                            dict(old_host), ('cursor', [], []))
                with patch.object(tool, 'active_launch_units',
                                  return_value=['rgpu-launch-stale.service']):
                    with self.assertRaisesRegex(ValueError, 'active_launch_units'):
                        tool.validate_prelaunch_continuation(
                            vm, manifest_path, manifest, original, proof_path, observed,
                            dict(old_host), ('cursor', [], []))

    def test_candidate188_prelaunch_continuation_accepts_only_exact_frozen_proof(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); original = vm/'original'; original.mkdir()
            boot = '3bca3e47-1f28-4f78-af00-5dbf76b00620'
            run = 'cb1d0aadd8186205d867a23fe175c336'
            old = {key:'fixed' for key in tool.IDENTITY_FIELDS}
            old.update(boot_id=boot, run_id=run, source_commit='old-commit',
                       source_sha256='driver-tree', candidate_directory='run/candidate-188',
                       harness_sha256={'macos-vm.sh':'old-launcher',
                                       'vm-supervision.py':'supervisor'},
                       gpu=True, max_seconds=180, source_clean=True,
                       vfio_device='0000:7b:00.0')
            for name, value in (
                    ('manifest.json', old),
                    ('verdict.json', {'valid':False, 'error':'RuntimeError: supervised launcher is not running'}),
                    ('host-before.json', {'boot_id':boot}),
                    ('host-after.json', {'boot_id':boot})):
                (original/name).write_text(json.dumps(value))
            new = copy.deepcopy(old)
            new['source_commit'] = 'reviewed-commit'
            new['harness_sha256']['macos-vm.sh'] = 'fixed-launcher'
            new['harness_sha256']['vm-supervision.py'] = 'fixed-supervisor'
            manifest_path = vm/'manifest.json'; manifest_path.write_text(json.dumps(new))
            ledger = vm/'ledger.json'
            ledger.write_bytes((json.dumps({'schema':2, 'boot_id':boot, 'max_launches':3,
                'launches':[{'run_id':run}]}, separators=(',', ':'))).encode())
            proof = {
                'schema':1, 'kind':'candidate188-x11-prelaunch', 'boot_id':boot,
                'run_id':run, 'original_manifest_sha256':tool.sha((original/'manifest.json').read_bytes()),
                'original_output_sha256':tool.evidence_digest(original)[0],
                'ledger_sha256':tool.sha(ledger.read_bytes()),
                'failing_launcher_sha256':'old-launcher',
                'supervisor_sha256':'supervisor',
                'launcher_log_sha256':'launcher-log',
                'docker_evidence_sha256':'docker-evidence',
                'evidence_inventory':{'launcher_log':'evidence/launcher.log',
                    'unit_journal':'evidence/journal.log',
                    'failing_launcher':'evidence/launcher.sh',
                    'failing_supervisor':'evidence/supervisor.py',
                    'docker_events':'evidence/docker.json',
                    'boot_ledger':'evidence/ledger.json'},
                'service':{'unit':'rgpu-launch-f356b4cfc9a0451a9afda1e4dfb206f0.service',
                           'invocation_id':'3d4b03acac054b10b63dd7a842db319f',
                           'pid':25105, 'start_us':1789060599622815,
                           'end_us':1789060599863115, 'exit_status':1,
                           'before_container_identification':True},
                'docker_events':{'since_us':1789060599500000,
                                 'until_us':1789060600100000,
                                 'stdout_sha256':tool.sha(b''), 'event_count':0},
                'replacement_manifest_sha256':tool.sha(manifest_path.read_bytes()),
                'repaired_launcher_sha256':'fixed-launcher',
                'repaired_supervisor_sha256':'fixed-supervisor',
                'coordinator_commit':'reviewed-commit'}
            proof_path = vm/'proof.json'; proof_path.write_text(json.dumps(proof))
            proof_sha = tool.sha(proof_path.read_bytes())
            observed = copy.deepcopy(new); observed['source_clean'] = True
            host = dict(self.host(), boot_id=boot, sleep_inhibited=True)
            pins = {'boot_id':boot, 'run_id':run,
                    'original_manifest_sha256':proof['original_manifest_sha256'],
                    'original_output_sha256':proof['original_output_sha256'],
                    'ledger_sha256':proof['ledger_sha256'],
                    'failing_launcher_sha256':'old-launcher',
                    'supervisor_sha256':'supervisor',
                    'launcher_log_sha256':'launcher-log',
                    'docker_evidence_sha256':'docker-evidence',
                    'unit_journal_sha256':'journal',
                    'evidence_inventory':proof['evidence_inventory']}
            evidence_dir = vm/'evidence'; evidence_dir.mkdir()
            (evidence_dir/'launcher.log').write_bytes(b'error: no X11 socket at /tmp/.X11-unix/X0\n')
            (evidence_dir/'journal.log').write_bytes(b'journal')
            (evidence_dir/'launcher.sh').write_bytes(b'old launcher')
            (evidence_dir/'supervisor.py').write_bytes(b'supervisor')
            docker_frozen = {'schema':1,
                'command':['docker','events','--since','2026-09-10T20:16:39.500+03:00',
                           '--until','2026-09-10T20:16:40.100+03:00','--format','{{json .}}'],
                'service_start_realtime_us':1789060599622815,
                'service_end_realtime_us':1789060599863115,
                'stdout_sha256':tool.sha(b''), 'events':[], 'exit_status':0}
            (evidence_dir/'docker.json').write_text(json.dumps(docker_frozen))
            (evidence_dir/'ledger.json').write_bytes(ledger.read_bytes())
            pins.update(launcher_log_sha256=tool.sha((evidence_dir/'launcher.log').read_bytes()),
                        unit_journal_sha256=tool.sha(b'journal'),
                        failing_launcher_sha256=tool.sha(b'old launcher'),
                        supervisor_sha256=tool.sha(b'supervisor'),
                        docker_evidence_sha256=tool.sha((evidence_dir/'docker.json').read_bytes()))
            old['harness_sha256']['macos-vm.sh'] = pins['failing_launcher_sha256']
            old['harness_sha256']['vm-supervision.py'] = pins['supervisor_sha256']
            (original/'manifest.json').write_text(json.dumps(old))
            proof['original_manifest_sha256'] = tool.sha((original/'manifest.json').read_bytes())
            proof['original_output_sha256'] = tool.evidence_digest(original)[0]
            pins['original_manifest_sha256'] = proof['original_manifest_sha256']
            pins['original_output_sha256'] = proof['original_output_sha256']
            proof.update(launcher_log_sha256=pins['launcher_log_sha256'],
                         docker_evidence_sha256=pins['docker_evidence_sha256'],
                         failing_launcher_sha256=pins['failing_launcher_sha256'],
                         supervisor_sha256=pins['supervisor_sha256'])
            proof_path.write_text(json.dumps(proof)); proof_sha = tool.sha(proof_path.read_bytes())
            with patch.object(tool, 'PRELAUNCH188_CONTINUATION', pins), \
                 patch.object(tool, 'ROOT', vm), \
                 patch.object(tool, 'active_launch_units', return_value=[]), \
                 patch.object(tool, 'command', return_value='reviewed-commit'):
                evidence, got_ledger, raw = tool.validate_prelaunch188_continuation(
                    vm, manifest_path, new, original, proof_path, proof_sha,
                    observed, host, ('cursor', [], []), ledger)
                self.assertEqual(evidence['kind'], 'candidate188-x11-prelaunch')
                self.assertEqual(got_ledger, ledger)
                self.assertEqual(raw, ledger.read_bytes())
                mutations = (
                    ('manifest', lambda: new.__setitem__('binary_sha256', 'changed')),
                    ('output', lambda: (original/'extra').write_text('changed')),
                    ('ledger', lambda: ledger.write_bytes(b'changed')),
                    ('proof', lambda: proof_path.write_text('{}')),
                    ('malformed-service', lambda: proof_path.write_text(json.dumps(
                        dict(proof, service=[])))),
                    ('malformed-docker-events', lambda: proof_path.write_text(json.dumps(
                        dict(proof, docker_events=[])))),
                    ('marker', lambda: (vm/'run/prelaunch-continuations'/
                        f'{boot}-{run}.json').parent.mkdir(parents=True, exist_ok=True) or
                        (vm/'run/prelaunch-continuations'/f'{boot}-{run}.json').write_text('{}')),
                )
                for label, mutate in mutations:
                    with self.subTest(label=label):
                        saved = (copy.deepcopy(new),
                                 {p.name:p.read_bytes() for p in original.iterdir()},
                                 ledger.read_bytes(), proof_path.read_bytes())
                        mutate()
                        with self.assertRaises(ValueError):
                            tool.validate_prelaunch188_continuation(
                                vm, manifest_path, new, original, proof_path, proof_sha,
                                observed, host, ('cursor', [], []), ledger)
                        new.clear(); new.update(saved[0])
                        for p in original.iterdir(): p.unlink()
                        for name, data in saved[1].items(): (original/name).write_bytes(data)
                        ledger.write_bytes(saved[2]); proof_path.write_bytes(saved[3])
                        marker = vm/'run/prelaunch-continuations'/f'{boot}-{run}.json'
                        marker.unlink(missing_ok=True)

    def test_run_continuation_consumes_marker_before_prepare_and_never_reserves_boot(self):
        tool = self.module()
        for mode in ('success', 'existing-marker', 'changed-ledger'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                vm = Path(temp); (vm/'run').mkdir()
                manifest = {key:'fixture' for key in tool.IDENTITY_FIELDS}
                manifest.update(build_id='abc', run_id='a'*32, max_seconds=180,
                    boot_id='boot-A', bootdisk_verified=True, gpu=True,
                    recovery_lease_schema=2,
                    recovery_helpers_sha256=self.recovery_helper_hashes(),
                    spec={'requested_diagnostic':'rgpusdma=1'},
                    launch_options={'BOOTDISK_MODE':'custom', 'NVRAM':'stock'},
                    source_clean=True, vfio_device='0000:7b:00.0',
                    candidate_directory='run/candidate-173', image_id='sha256:expected')
                path = vm/'prepared.json'; path.write_text(json.dumps(manifest))
                ledger_dir = vm/'run/used-gpu-boots'; ledger_dir.mkdir()
                ledger = ledger_dir/'boot-A.json'; ledger.write_bytes(b'ledger-original')
                events = []
                marker = tool.prelaunch_continuation_marker(vm, 'boot-A', 'a'*32)
                if mode == 'existing-marker':
                    marker.parent.mkdir(); marker.write_text('{}')

                class NoopMonitor:
                    error = None; error_kind = None; messages = []
                    def __init__(self, *args): pass
                    def start(self): pass
                    def stop(self): pass

                recovery = SimpleNamespace()
                supervisor = SimpleNamespace(
                    start_locked=lambda *args: (_ for _ in ()).throw(RuntimeError('stop after prepare')),
                    ManagedStopUnconfirmed=type('ManagedStopUnconfirmed',(RuntimeError,),{}))
                original_helper = tool.helper
                def helpers(name):
                    if name == 'vfio-recover': return recovery
                    if name == 'vm-supervision': return supervisor
                    return original_helper(name)
                original_write_once = tool.write_once
                def write_once(path_arg, value):
                    original_write_once(path_arg, value)
                    if Path(path_arg) == marker:
                        events.append(('marker', marker.name))
                        if mode == 'changed-ledger': ledger.write_bytes(b'ledger-changed')

                host = dict(self.host(), sleep_inhibited=True)
                continuation = {'schema':1}
                with patch.object(tool, 'current_identity', return_value=manifest), \
                     patch.object(tool, 'host_snapshot', return_value=host), \
                     patch.object(tool, 'kernel_updates', return_value=('cursor', [], [])), \
                     patch.object(tool, 'validate_prelaunch_continuation',
                         return_value=(continuation, ledger, b'ledger-original')), \
                     patch.object(tool, 'HostMonitor', NoopMonitor), \
                     patch.object(tool, 'helper', side_effect=helpers), \
                     patch.object(tool, 'write_once', side_effect=write_once), \
                     patch.object(tool, 'reserve_boot',
                         side_effect=AssertionError('continuation must not reserve boot')):
                    result = tool.run_one(vm, path, vm/('output-'+mode),
                                          vm/'original', vm/'proof.json')
                self.assertEqual(result['verdict'], 'INVALID')
                if mode == 'success':
                    self.assertEqual(events, [('marker', marker.name)])
                    self.assertEqual(ledger.read_bytes(), b'ledger-original')
                else:
                    self.assertEqual(events, [] if mode == 'existing-marker' else
                                     [('marker', marker.name)])

    def test_legacy_boot_reservation_accepts_one_matching_recovery_receipt(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
            prior, current = 'a'*32, 'b'*32
            (used/'boot-A.json').write_text(json.dumps(
                {'boot_id':'boot-A', 'experiment':prior}))
            receipts = vm/'run/vfio-recovery/boot-A'; receipts.mkdir(parents=True)
            receipt = self.recovery_receipt(tool, prior, 'c'*32)
            (receipts/(prior+'.json')).write_text(json.dumps(receipt))
            authorization, errors = tool.reuse_authorization(vm, 'boot-A', current)
            self.assertEqual(errors, [])
            self.assertEqual(authorization['recovery_id'], 'c'*32)
            tool.reserve_boot(used, 'boot-A', current, authorization)
            ledger = json.loads((used/'boot-A.json').read_text())
            self.assertEqual([row['run_id'] for row in ledger['launches']], [prior, current])
            self.assertEqual(ledger['launches'][1]['recovery_id'], 'c'*32)
            replay, replay_errors = tool.reuse_authorization(vm, 'boot-A', 'd'*32)
            self.assertIsNone(replay)
            self.assertIn('recovery_receipt', replay_errors)

    def test_candidate176_one_use_receipt_is_exact_third_ledger_entry(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
            first, prior, current = 'a'*32, 'b'*32, 'c'*32
            ledger = {'schema':2, 'boot_id':'boot-A', 'max_launches':3,
                      'launches':[{'run_id':first},
                                  {'run_id':prior, 'prior_run_id':first,
                                   'recovery_id':'1'*32, 'attempt_id':'2'*32}]}
            ledger_path = used/'boot-A.json'
            ledger_path.write_text(json.dumps(ledger)+'\n')
            manifest = {'boot_id':'boot-A', 'run_id':current,
                        'candidate_directory':'run/candidate-176'}
            manifest_path = vm/'run/metal-009-176-manifest.json'
            manifest_path.write_text(json.dumps(manifest)+'\n')
            receipt = {
                'schema':7, 'kind':'same-boot-retained-kiq-continuation',
                'status':'authorized', 'authorizes_launch':True,
                'boot_id':'boot-A', 'prior_run_id':prior,
                'next_run_id':current, 'recovery_id':'3'*32,
                'authorization_id':'4'*32,
                'ledger_sha256':hashlib.sha256(ledger_path.read_bytes()).hexdigest()}
            target = vm/'run/retained-kiq-continuations/boot-A'
            target.mkdir(parents=True); (target/(prior+'.json')).write_text(
                json.dumps(receipt)+'\n')
            calls = []
            continuation = SimpleNamespace(validate_receipt=lambda *args:
                calls.append(args) or [])
            original = tool.helper
            with patch.object(tool, 'helper', side_effect=lambda name:
                    continuation if name == 'retained-kiq-continuation'
                    else original(name)):
                authorization, errors = tool.reuse_authorization(
                    vm, 'boot-A', current, manifest, manifest_path)
                self.assertEqual(errors, [])
                self.assertEqual(authorization, receipt)
                tool.reserve_boot(used, 'boot-A', current, authorization,
                                  manifest, manifest_path)
            self.assertGreaterEqual(len(calls), 2)
            updated = json.loads(ledger_path.read_text())
            self.assertEqual([row['run_id'] for row in updated['launches']],
                             [first, prior, current])
            self.assertEqual(updated['launches'][2]['authorization_id'], '4'*32)
            self.assertEqual(updated['launches'][2]['recovery_id'], '3'*32)
            # No launch-count ceiling any more: a fourth same-boot launch is refused
            # only because it has no recovery receipt of its own, not by count.
            replay, replay_errors = tool.reuse_authorization(
                vm, 'boot-A', 'd'*32, manifest, manifest_path)
            self.assertIsNone(replay)
            self.assertEqual(replay_errors, ['recovery_receipt'])

    def test_candidate176_receipt_requires_helper_manifest_and_raw_ledger(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
            prior, current = 'b'*32, 'c'*32
            ledger_path = used/'boot-A.json'
            ledger_path.write_text(json.dumps({
                'schema':2, 'boot_id':'boot-A', 'max_launches':3,
                'launches':[{'run_id':'a'*32}, {'run_id':prior}]})+'\n')
            receipt = {'schema':7, 'recovery_id':'3'*32,
                       'authorization_id':'4'*32,
                       'ledger_sha256':hashlib.sha256(ledger_path.read_bytes()).hexdigest()}
            target = vm/'run/retained-kiq-continuations/boot-A'
            target.mkdir(parents=True); (target/(prior+'.json')).write_text(
                json.dumps(receipt))
            manifest = {'run_id':current}; manifest_path = vm/'manifest.json'
            manifest_path.write_text(json.dumps(manifest))
            continuation = SimpleNamespace(validate_receipt=lambda *args:
                                             ['retained_kiq_continuation_manifest'])
            original = tool.helper
            with patch.object(tool, 'helper', side_effect=lambda name:
                    continuation if name == 'retained-kiq-continuation'
                    else original(name)):
                authorization, errors = tool.reuse_authorization(
                    vm, 'boot-A', current, manifest, manifest_path)
                self.assertIsNone(authorization)
                self.assertIn('retained_kiq_continuation_manifest', errors)

                continuation.validate_receipt = lambda *args:[]
                ledger_path.write_bytes(ledger_path.read_bytes()+b' ')
                with self.assertRaisesRegex(
                        ValueError, 'retained_kiq_continuation_receipt'):
                    tool.reserve_boot(used, 'boot-A', current, receipt,
                                      manifest, manifest_path)

    def cap_revision_fixture(self, tool, vm):
        boot, prior, current = 'boot-A', 'a'*32, 'd'*32
        used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
        ledger = {'schema':2, 'boot_id':boot, 'max_launches':3,
                  'launches':[{'run_id':'8'*32, 'reserved_epoch':1.0},
                              {'run_id':'9'*32, 'reserved_epoch':2.0,
                               'prior_run_id':'8'*32, 'recovery_id':'1'*32},
                              {'run_id':prior, 'reserved_epoch':3.0,
                               'prior_run_id':'9'*32, 'recovery_id':'2'*32}]}
        ledger_path = used/(boot+'.json')
        ledger_path.write_text(json.dumps(ledger, indent=2)+'\n')

        receipt = self.schema6_host_kiq_receipt(tool, prior)
        receipt.update(boot_id=boot, recovery_id='c'*32,
                       kernel_cursor_after='s=x;i=10;b=boot-A;m=1')
        canonical = vm/'run/vfio-recovery'/boot/(prior+'.json')
        canonical.parent.mkdir(parents=True)
        canonical.write_text(json.dumps(receipt, indent=2)+'\n')
        run_copy = vm/'run/metal-009-176/recovery.json'
        run_copy.parent.mkdir(parents=True)
        run_copy.write_text(json.dumps(receipt, separators=(',', ':'))+'\n')

        manifest = {'boot_id':boot, 'run_id':current, 'max_seconds':180,
                    'source_clean':True, 'vfio_device':'0000:7b:00.0',
                    'gpu':True, 'candidate_directory':'run/candidate-177',
                    'experiment':'metal-010',
                    'spec':{'id':'metal-010', 'candidate_version':'1.0.177',
                            'requested_diagnostic':'rgpusubmit=1',
                            'max_seconds':180}}
        manifest_path = vm/'run/candidate-177-manifest.json'
        manifest_path.write_text(json.dumps(manifest, indent=2)+'\n')

        tool.CAP_REVISION_BOOT_ID = boot
        tool.CAP_REVISION_PRIOR_RUN_ID = prior
        tool.CAP_REVISION_RECOVERY_ID = receipt['recovery_id']
        tool.CAP_REVISION_LEDGER_SHA256 = hashlib.sha256(
            ledger_path.read_bytes()).hexdigest()
        tool.CAP_REVISION_CANONICAL_RECEIPT_SHA256 = hashlib.sha256(
            canonical.read_bytes()).hexdigest()
        tool.CAP_REVISION_RUN_RECEIPT_SHA256 = hashlib.sha256(
            run_copy.read_bytes()).hexdigest()

        authority = {
            'schema':1, 'kind':'same-boot-qualification-cap-revision',
            'boot_id':boot,
            'ledger_preimage_sha256':tool.CAP_REVISION_LEDGER_SHA256,
            'prior_run_id':prior, 'recovery_id':receipt['recovery_id'],
            'canonical_recovery_receipt_sha256':
                tool.CAP_REVISION_CANONICAL_RECEIPT_SHA256,
            'run_recovery_receipt_sha256':tool.CAP_REVISION_RUN_RECEIPT_SHA256,
            'range_audit_sha256':hashlib.sha256(
                (ROOT/'findings/experiments/metal-009-176/'
                 'recovery-gart-range-audit.md').read_bytes()).hexdigest(),
            'candidate176_consumer_sha256':
                tool.CAP_REVISION_CANDIDATE176_CONSUMER_SHA256,
            'candidate176_recovery_producer_sha256':
                tool.CAP_REVISION_CANDIDATE176_PRODUCER_SHA256,
            'design_sha256':hashlib.sha256(
                (ROOT/'docs/superpowers/specs/'
                 '2026-09-09-same-boot-qualification-cap-revision-design.md').read_bytes()).hexdigest(),
            'candidate177_experiment_py_sha256':hashlib.sha256(
                (ROOT/'tools/experiment.py').read_bytes()).hexdigest(),
            'candidate177_recovery_producer_sha256':hashlib.sha256(
                (ROOT/'tools/vfio-recover.py').read_bytes()).hexdigest(),
            'manifest_sha256':hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            'next_run_id':current, 'from_max_launches':3,
            'to_max_launches':4, 'additional_launches':1,
            'automatic_extension':False,
            'purpose':'m7-normal-recovery-qualification',
        }
        authority_path = (vm/'run/cap-revision-authorities'/boot/
                          (current+'.json'))
        authority_path.parent.mkdir(parents=True)
        authority_path.write_text(json.dumps(authority, indent=2)+'\n')
        authority_sha = hashlib.sha256(authority_path.read_bytes()).hexdigest()
        return (ledger_path, ledger, receipt, manifest, manifest_path,
                authority_path, authority_sha)

    def test_exact_cap_revision_preserves_three_rows_and_consumes_launch_four(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            (ledger_path, before, receipt, manifest, manifest_path,
             authority_path, authority_sha) = self.cap_revision_fixture(tool, vm)
            authorization, errors = tool.cap_revision_authorization(
                vm, manifest, manifest_path, authority_sha)
            self.assertEqual(errors, [])

            host = dict(self.host(), sleep_inhibited=True, pstore_files=None)
            vfio_host = {'boot_id':'boot-A', 'active_vm':False,
                         'driver':'vfio-pci', 'device':'1002:13c0',
                         'iommu_group':'31', 'pci_command':3,
                         'reset_methods':[]}
            recovery_tool = SimpleNamespace(
                host_state=lambda:vfio_host,
                validate_host_state=lambda state, boot:[])
            with patch.object(tool, 'host_snapshot', return_value=host), \
                 patch.object(tool, 'active_launch_units', return_value=[]), \
                 patch.object(tool, 'helper', return_value=recovery_tool), \
                 patch.object(tool, 'kernel_updates',
                              return_value=('s=x;i=11;b=boot-A;m=2',
                                            ['routine'], [])) as journal:
                cursor = tool.reserve_cap_revision(
                    ledger_path.parent, manifest['boot_id'], manifest['run_id'],
                    receipt, manifest, manifest_path, authorization)

            journal.assert_called_once_with('s=x;i=10;b=boot-A;m=1')
            self.assertEqual(cursor, 's=x;i=11;b=boot-A;m=2')
            after = json.loads(ledger_path.read_text())
            self.assertEqual(after['schema'], 3)
            self.assertEqual(after['initial_max_launches'], 3)
            self.assertEqual(after['max_launches'], 4)
            self.assertEqual(after['launches'][:3], before['launches'])
            self.assertEqual(len(after['launches']), 4)
            self.assertEqual(after['launches'][3]['run_id'], manifest['run_id'])
            self.assertEqual(after['launches'][3]['recovery_id'], receipt['recovery_id'])
            self.assertEqual(after['launches'][3]['cap_revision_authority_sha256'],
                             authority_sha)
            self.assertEqual(len(after['cap_revisions']), 1)
            revision = after['cap_revisions'][0]
            self.assertEqual({key:revision[key] for key in (
                'authority_sha256', 'ledger_preimage_sha256',
                'from_max_launches', 'to_max_launches',
                'additional_launches', 'purpose', 'kernel_cursor_before',
                'kernel_cursor_after', 'kernel_messages')}, {
                    'authority_sha256':authority_sha,
                    'ledger_preimage_sha256':tool.CAP_REVISION_LEDGER_SHA256,
                    'from_max_launches':3, 'to_max_launches':4,
                    'additional_launches':1,
                    'purpose':'m7-normal-recovery-qualification',
                    'kernel_cursor_before':'s=x;i=10;b=boot-A;m=1',
                    'kernel_cursor_after':'s=x;i=11;b=boot-A;m=2',
                    'kernel_messages':['routine'],
                })
            self.assertEqual(revision['host_gate']['pstore_files'], None)
            self.assertEqual(revision['vfio_gate'], vfio_host)

            replay, replay_errors = tool.cap_revision_authorization(
                vm, manifest, manifest_path, authority_sha)
            self.assertIsNone(replay)
            self.assertIn('cap_revision_ledger', replay_errors)

    def test_cap_revision_binds_authority_manifest_receipts_sources_and_preimage(self):
        cases = ('no-authority', 'authority-sha', 'authority-field',
                 'coordinator-source', 'producer-source', 'manifest',
                 'wrong-boot', 'wrong-candidate', 'wrong-version',
                 'wrong-card', 'wrong-diagnostic', 'wrong-deadline', 'wrong-mode',
                 'canonical-receipt', 'run-receipt', 'ledger',
                 'malformed-ledger', 'malformed-row',
                 'reused-run', 'reused-recovery', 'schema3-four-entries')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                tool = self.module(); vm = Path(temp)
                (ledger_path, _, _, manifest, manifest_path,
                 authority_path, authority_sha) = self.cap_revision_fixture(tool, vm)
                if case == 'no-authority':
                    authority_sha = None
                elif case == 'authority-sha':
                    authority_sha = '0'*64
                elif case == 'authority-field':
                    value = json.loads(authority_path.read_text())
                    value['automatic_extension'] = True
                    authority_path.write_text(json.dumps(value, indent=2)+'\n')
                    authority_sha = hashlib.sha256(authority_path.read_bytes()).hexdigest()
                elif case in ('coordinator-source', 'producer-source'):
                    value = json.loads(authority_path.read_text())
                    key = ('candidate177_experiment_py_sha256'
                           if case == 'coordinator-source'
                           else 'candidate177_recovery_producer_sha256')
                    value[key] = '0'*64
                    authority_path.write_text(json.dumps(value, indent=2)+'\n')
                    authority_sha = hashlib.sha256(authority_path.read_bytes()).hexdigest()
                elif case == 'manifest':
                    manifest_path.write_bytes(manifest_path.read_bytes()+b' ')
                elif case.startswith('wrong-'):
                    changed = copy.deepcopy(manifest)
                    if case == 'wrong-boot':
                        changed['boot_id'] = 'boot-B'
                    elif case == 'wrong-candidate':
                        changed['candidate_directory'] = 'run/candidate-178'
                    elif case == 'wrong-version':
                        changed['spec']['candidate_version'] = '1.0.178'
                    elif case == 'wrong-card':
                        changed['spec']['id'] = 'metal-011'
                    elif case == 'wrong-diagnostic':
                        changed['spec']['requested_diagnostic'] = 'rgpuvmroot=1'
                    elif case == 'wrong-mode':
                        changed['gpu'] = False
                    else:
                        changed['max_seconds'] = 181
                    authorization, errors = tool.cap_revision_authorization(
                        vm, changed, manifest_path, authority_sha)
                    self.assertIsNone(authorization)
                    self.assertTrue(errors)
                    continue
                elif case == 'canonical-receipt':
                    path = vm/'run/vfio-recovery/boot-A'/('a'*32+'.json')
                    path.write_bytes(path.read_bytes()+b' ')
                elif case == 'run-receipt':
                    path = vm/'run/metal-009-176/recovery.json'
                    path.write_bytes(path.read_bytes()+b' ')
                elif case == 'ledger':
                    ledger_path.write_bytes(ledger_path.read_bytes()+b' ')
                elif case == 'malformed-ledger':
                    ledger_path.write_text('[]\n')
                elif case == 'malformed-row':
                    ledger = json.loads(ledger_path.read_text())
                    ledger['launches'][1] = 'malformed'
                    ledger_path.write_text(json.dumps(ledger, indent=2)+'\n')
                else:
                    ledger = json.loads(ledger_path.read_text())
                    if case == 'reused-run':
                        ledger['launches'][0]['run_id'] = manifest['run_id']
                    elif case == 'reused-recovery':
                        ledger['launches'][0]['recovery_id'] = 'c'*32
                    else:
                        ledger.update(schema=3, initial_max_launches=3,
                                      max_launches=4, cap_revisions=[{}])
                        ledger['launches'].append({'run_id':'e'*32})
                    ledger_path.write_text(json.dumps(ledger, indent=2)+'\n')
                    if case == 'schema3-four-entries':
                        value = json.loads(authority_path.read_text())
                        value['ledger_preimage_sha256'] = hashlib.sha256(
                            ledger_path.read_bytes()).hexdigest()
                        authority_path.write_text(json.dumps(value, indent=2)+'\n')
                        authority_sha = hashlib.sha256(
                            authority_path.read_bytes()).hexdigest()
                authorization, errors = tool.cap_revision_authorization(
                    vm, manifest, manifest_path, authority_sha)
                self.assertIsNone(authorization)
                self.assertTrue(errors)

    def test_cap_revision_reservation_arguments_must_match_manifest(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            (ledger_path, _, receipt, manifest, manifest_path,
             _, authority_sha) = self.cap_revision_fixture(tool, vm)
            authorization, errors = tool.cap_revision_authorization(
                vm, manifest, manifest_path, authority_sha)
            self.assertEqual(errors, [])
            before = ledger_path.read_bytes()
            for boot, run in (('boot-B', manifest['run_id']),
                              (manifest['boot_id'], 'e'*32)):
                with self.subTest(boot=boot, run=run):
                    with self.assertRaisesRegex(ValueError, 'cap revision refused'):
                        tool.reserve_cap_revision(
                            ledger_path.parent, boot, run, receipt, manifest,
                            manifest_path, authorization)
                    self.assertEqual(ledger_path.read_bytes(), before)

    def test_cap_revision_rejects_fault_or_reset_before_writing_ledger(self):
        for message, faults in (
                ('Hardware Error', ['Hardware Error']),
                ('vfio-pci 0000:7b:00.0: resetting', [])):
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temp:
                tool = self.module(); vm = Path(temp)
                (ledger_path, _, receipt, manifest, manifest_path,
                 _, authority_sha) = self.cap_revision_fixture(tool, vm)
                before = ledger_path.read_bytes()
                authorization, errors = tool.cap_revision_authorization(
                    vm, manifest, manifest_path, authority_sha)
                self.assertEqual(errors, [])
                host = dict(self.host(), sleep_inhibited=True, pstore_files=None)
                recovery_tool = SimpleNamespace(
                    host_state=lambda:{'boot_id':'boot-A'},
                    validate_host_state=lambda state, boot:[])
                with patch.object(tool, 'host_snapshot', return_value=host), \
                     patch.object(tool, 'active_launch_units', return_value=[]), \
                     patch.object(tool, 'helper', return_value=recovery_tool), \
                     patch.object(tool, 'kernel_updates',
                                  return_value=('s=x;i=11;b=boot-A;m=2',
                                                [message], faults)):
                    with self.assertRaisesRegex(ValueError, 'cap revision refused'):
                        tool.reserve_cap_revision(
                            ledger_path.parent, manifest['boot_id'],
                            manifest['run_id'], receipt, manifest,
                            manifest_path, authorization)
                self.assertEqual(ledger_path.read_bytes(), before)

    def test_cap_revision_rejects_missing_reversed_or_raced_journal_boundary(self):
        cases = ('missing-start', 'missing-end', 'reversed', 'ledger-race')
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                tool = self.module(); vm = Path(temp)
                (ledger_path, _, receipt, manifest, manifest_path,
                 _, authority_sha) = self.cap_revision_fixture(tool, vm)
                authorization, errors = tool.cap_revision_authorization(
                    vm, manifest, manifest_path, authority_sha)
                self.assertEqual(errors, [])
                if case == 'missing-start':
                    receipt['kernel_cursor_after'] = None
                end = {'missing-end':None,
                       'reversed':'s=x;i=0f;b=boot-A;m=2'}.get(
                           case, 's=x;i=11;b=boot-A;m=2')
                def journal(_cursor):
                    if case == 'ledger-race':
                        ledger_path.write_bytes(ledger_path.read_bytes()+b' ')
                    return end, [], []
                host = dict(self.host(), sleep_inhibited=True, pstore_files=None)
                recovery_tool = SimpleNamespace(
                    host_state=lambda:{'boot_id':'boot-A'},
                    validate_host_state=lambda state, boot:[])
                before = ledger_path.read_bytes()
                with patch.object(tool, 'host_snapshot', return_value=host), \
                     patch.object(tool, 'active_launch_units', return_value=[]), \
                     patch.object(tool, 'helper', return_value=recovery_tool), \
                     patch.object(tool, 'kernel_updates', side_effect=journal):
                    with self.assertRaisesRegex(ValueError, 'cap revision refused'):
                        tool.reserve_cap_revision(
                            ledger_path.parent, manifest['boot_id'],
                            manifest['run_id'], receipt, manifest,
                            manifest_path, authorization)
                after = ledger_path.read_bytes()
                if case == 'ledger-race':
                    self.assertEqual(after, before+b' ')
                else:
                    self.assertEqual(after, before)

    def test_cap_revision_cursor_is_used_without_starting_a_new_journal_interval(self):
        tool = self.module()
        with patch.object(tool, 'reserve_cap_revision', return_value='fresh-cursor') as cap, \
             patch.object(tool, 'reserve_boot') as ordinary, \
             patch.object(tool, 'kernel_updates',
                          side_effect=AssertionError('must use reviewed interval cursor')):
            cursor = tool.reserve_launch_and_cursor(
                Path('/tmp/used'), 'boot-A', 'd'*32, {'schema':6},
                {'run_id':'d'*32}, Path('/tmp/manifest'), {'authority':{}})
        self.assertEqual(cursor, 'fresh-cursor')
        cap.assert_called_once()
        ordinary.assert_not_called()

    def test_cap_revision_api_refuses_prelaunch_continuation(self):
        tool = self.module()
        with self.assertRaisesRegex(ValueError, 'cap revision cannot use'):
            tool.run_one(Path('/nonexistent'), Path('/nonexistent-manifest'),
                         Path('/nonexistent-output'), Path('/prior-output'),
                         Path('/proof'), 'a'*64)

    def test_warm_qualification_api_requires_pair_and_refuses_mixed_modes(self):
        tool = self.module()
        calls = (
            ((), {'warm_qualification_policy_sha256':'a'*64}),
            ((), {'warm_qualification_activation_sha256':'b'*64}),
            ((), {'cap_revision_authority_sha256':'c'*64,
                  'warm_qualification_policy_sha256':'a'*64,
                  'warm_qualification_activation_sha256':'b'*64}),
            ((Path('/prior'), Path('/proof')), {
                'warm_qualification_policy_sha256':'a'*64,
                'warm_qualification_activation_sha256':'b'*64}),
        )
        for positional, keywords in calls:
            with self.subTest(positional=positional, keywords=keywords):
                with self.assertRaisesRegex(ValueError, 'warm qualification'):
                    tool.run_one(
                        Path('/nonexistent'), Path('/nonexistent-manifest'),
                        Path('/nonexistent-output'), *positional, **keywords)

    def test_candidate179_api_requires_pair_and_refuses_mixed_modes(self):
        tool = self.module()
        cases = (
            {'candidate179_policy_sha256':'a'*64},
            {'candidate179_activation_sha256':'b'*64},
            {'candidate179_policy_sha256':'a'*64,
             'candidate179_activation_sha256':'b'*64,
             'warm_qualification_policy_sha256':'c'*64,
             'warm_qualification_activation_sha256':'d'*64},
            {'candidate179_policy_sha256':'a'*64,
             'candidate179_activation_sha256':'b'*64,
             'cap_revision_authority_sha256':'c'*64},
        )
        for keywords in cases:
            with self.subTest(keywords=keywords):
                with self.assertRaisesRegex(ValueError, 'candidate179 qualification'):
                    tool.run_one(
                        Path('/nonexistent'), Path('/nonexistent-manifest'),
                        Path('/nonexistent-output'), **keywords)

    def test_candidate179_real_helper_run_adapter_reserves_once(self):
        from tests.test_candidate179_qualification import (
            Candidate179QualificationTests, BOOT, RUN)
        Candidate179QualificationTests.setUpClass()
        fixture = Candidate179QualificationTests(
            'test_authorizes_read_only_and_builds_exact_single_append')
        fixture.setUp()
        try:
            tool = self.module()
            candidate = fixture.helper
            candidate_authorize = candidate.authorize
            authorization_calls = []
            def traced_authorize(*args, **kwargs):
                result = candidate_authorize(*args, **kwargs)
                authorization_calls.append(result[1])
                return result
            candidate.authorize = traced_authorize
            manifest = fixture.manifest
            for key in tool.IDENTITY_FIELDS:
                if key != 'run_id':
                    manifest.setdefault(key, 'fixture')
            manifest.update(
                guest_build='24G830', vfio_device='0000:7b:00.0',
                launch_options={'BOOTDISK_MODE':'custom', 'NVRAM':'stock',
                                'GENERIC_GRAPHICS':'off'})
            fixture.manifest_path.write_text(
                json.dumps(manifest, sort_keys=True)+'\n')
            policy = json.loads(fixture.policy_path.read_text())
            policy.update(
                manifest_sha256=hashlib.sha256(
                    fixture.manifest_path.read_bytes()).hexdigest(),
                experiment_py_sha256=hashlib.sha256(
                    (ROOT/'tools/experiment.py').read_bytes()).hexdigest())
            fixture.policy_path.write_text(json.dumps(policy, sort_keys=True)+'\n')
            policy_sha = hashlib.sha256(fixture.policy_path.read_bytes()).hexdigest()
            activation = json.loads(fixture.activation_path.read_text())
            activation.update(
                policy_sha256=policy_sha,
                manifest_sha256=policy['manifest_sha256'])
            fixture.activation_path.write_text(
                json.dumps(activation, sort_keys=True)+'\n')
            activation_sha = hashlib.sha256(
                fixture.activation_path.read_bytes()).hexdigest()

            host = dict(self.host(), boot_id=BOOT, sleep_inhibited=True)
            prior = json.loads((fixture.vm/'run/vfio-recovery'/BOOT/
                                (candidate.PRIOR_RUN_ID+'.json')).read_text())
            cursor = prior['kernel_cursor_after']
            full_host = {
                'boot_id':BOOT, 'journal_cursor':cursor,
                'journal_messages':[], 'journal_faults':[],
            }
            retained = SimpleNamespace(
                collect_fresh_host=lambda before:full_host,
                host_errors=lambda value, boot, prefix='':[])
            recovery = tool.helper('vfio-recover')
            recovery.host_state = lambda:{'boot_id':BOOT}
            recovery.validate_host_state = lambda value, boot:[]
            recovered_evidence = []
            recovery.recover = lambda vm, prior_run_id, **kwargs: (
                recovered_evidence.append(kwargs) or {'status':'recovered'})
            classifier = SimpleNamespace(
                parse_serial=lambda serial:[],
                classify_probe_readiness=lambda *args:{
                    'valid':False, 'verdict':'INCONCLUSIVE'},
                classify=lambda *args:{'valid':False, 'verdict':'INCONCLUSIVE'})
            serial_payloads = ['BUILD: identity='+manifest['build_id'],
                               self.v2_critical_payloads(RUN)[0]]
            serial = (f'RGPU_RECORDS build={manifest["build_id"]} count=2 '
                      'dropped=0 truncated=0\n' + ''.join(
                          f'RGPU_EVENT build={manifest["build_id"]} seq={index} '
                          f'{payload}\n'
                          for index, payload in enumerate(serial_payloads)))
            def start_locked(*args):
                (fixture.vm/'run/serial.log').write_text(serial)
                return {'cid':'c'*64, 'deadline_epoch':280,
                        'max_seconds':180}
            supervisor = SimpleNamespace(
                start_locked=start_locked,
                verify=lambda state:None,
                ManagedStopUnconfirmed=type(
                    'ManagedStopUnconfirmed',(RuntimeError,),{}),
                stop_exact=lambda cid:None)
            shutdown = SimpleNamespace(shutdown=lambda *args, **kwargs:{
                'cid':'c'*64, 'outcome':'forced'})
            original_helper = tool.helper
            def helpers(name):
                return {
                    'candidate179-qualification':candidate,
                    'retained-kiq-continuation':retained,
                    'vfio-recover':recovery,
                    'classify-run':classifier,
                    'vm-supervision':supervisor,
                    'guest-shutdown':shutdown,
                }.get(name, original_helper(name))
            observed = {key:copy.deepcopy(value) for key, value in manifest.items()
                        if key not in ('run_id', 'recovery_lease_schema', 'spec',
                                       'gpu', 'max_seconds', 'experiment',
                                       'candidate_directory', 'vfio_device')}
            identity_run_ids = []
            identity_launch_options = []
            identity_probe_specs = []
            def current_identity(vm, candidate, requested_diagnostic, run_id=None,
                                 recovery_lease_schema=2,
                                 launch_options_expected=None, probe_spec=None):
                identity_run_ids.append(run_id)
                identity_launch_options.append(launch_options_expected)
                identity_probe_specs.append(probe_spec)
                return copy.deepcopy(observed)
            now = [100.0]
            class NoopMonitor:
                error = None; error_kind = None; messages = []
                def __init__(self, *args): pass
                def start(self): pass
                def stop(self): pass
            with patch.object(tool, 'helper', side_effect=helpers), \
                 patch.object(tool, 'current_identity', side_effect=current_identity), \
                 patch.object(tool, 'host_snapshot', return_value=host), \
                 patch.object(tool, 'active_launch_units', return_value=[]), \
                 patch.object(tool, 'running_identity', return_value={
                     'image_id':manifest['image_id'],
                     'vfio_args':['vfio-pci,host=0000:7b:00.0'],
                     'graphics_args':['-vga','none','-display','none']}), \
                 patch.object(tool, 'HostMonitor', NoopMonitor), \
                 patch.object(tool.time, 'time', side_effect=lambda:now[0]), \
                 patch.object(tool.time, 'sleep',
                              side_effect=lambda n:now.__setitem__(0, now[0]+100)):
                result = tool.run_one(
                    fixture.vm, fixture.manifest_path, fixture.output,
                    candidate179_policy_sha256=policy_sha,
                    candidate179_activation_sha256=activation_sha)

            self.assertEqual(result['warm_reuse'], 'recovered',
                             (result, authorization_calls))
            ledger = json.loads((fixture.vm/'run/used-gpu-boots'/
                                 (BOOT+'.json')).read_text())
            self.assertEqual(len(ledger['launches']), 7)
            self.assertEqual(ledger['launches'][-1]['run_id'], RUN)
            self.assertEqual(identity_run_ids, [RUN, RUN])
            self.assertEqual(identity_launch_options, [manifest['launch_options']] * 2)
            self.assertEqual(identity_probe_specs, [manifest, manifest])
            self.assertEqual(len(recovered_evidence), 1)
            self.assertIn('lease_evidence', recovered_evidence[0])
            self.assertEqual(recovered_evidence[0]['recovery_helpers_sha256'],
                             manifest['recovery_helpers_sha256'])
        finally:
            if 'candidate' in locals() and 'candidate_authorize' in locals():
                candidate.authorize = candidate_authorize
            fixture.tearDown()

    def test_warm_qualification_dispatch_uses_reviewed_cursor_only(self):
        tool = self.module()
        warm = {'stage':'A'}
        with patch.object(tool, 'reserve_warm_qualification',
                          return_value='fresh-cursor') as reserve, \
             patch.object(tool, 'reserve_cap_revision') as cap, \
             patch.object(tool, 'reserve_boot') as ordinary, \
             patch.object(tool, 'kernel_updates',
                          side_effect=AssertionError('must use warm interval cursor')):
            cursor = tool.reserve_launch_and_cursor(
                Path('/tmp/used'), 'boot-A', 'd'*32, {'schema':6},
                {'run_id':'d'*32}, Path('/tmp/manifest'), None, warm,
                Path('/tmp/output'))
        self.assertEqual(cursor, 'fresh-cursor')
        reserve.assert_called_once()
        cap.assert_not_called()
        ordinary.assert_not_called()

    def test_warm_reservation_revalidates_identity_host_and_exact_bytes(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
            manifest = {
                'boot_id':'boot-A', 'run_id':'d'*32,
                'candidate_directory':'run/candidate-178',
                'spec':{'requested_diagnostic':'rgpusubmit=1'},
                'image_id':'image', 'build_id':'build', 'source_sha256':'source',
                'bootdisk_sha256':'disk', 'source_clean':True,
                'vfio_device':'0000:7b:00.0', 'max_seconds':180,
                'launch_options':{'BOOTDISK_MODE':'custom', 'NVRAM':'stock',
                                  'GENERIC_GRAPHICS':'off'},
            }
            manifest_path = vm/'run/a.json'; manifest_path.write_text('{}\n')
            output = vm/'run/out'
            receipt = {'kernel_cursor_after':'s=x;i=10;b=boot-A;m=1'}
            identity = {key:manifest[key] for key in (
                'image_id', 'build_id', 'source_sha256', 'boot_id',
                'bootdisk_sha256', 'launch_options')}
            authorization = {
                'policy_sha256':'a'*64, 'activation_sha256':'b'*64,
                'receipt':receipt, 'policy_raw':b'p', 'activation_raw':b'a',
                'ledger_raw':b'l', 'manifest_raws':[b'm1', b'm2'],
                'receipt_raws':[b'r1', b'r2'],
                'candidate176_receipt_raws':[b'c1', b'c2'],
            }
            final = dict(authorization)
            full_host = {'boot_id':'boot-A', 'journal_cursor':'s=x;i=11;b=boot-A;m=2',
                         'journal_messages':['routine'], 'journal_faults':[]}
            capture_host = dict(self.host(), boot_id='boot-A', sleep_inhibited=True)
            vfio = {'boot_id':'boot-A', 'driver':'vfio-pci'}
            warm_tool = SimpleNamespace(
                authorize=lambda *args:(final, []),
                build_reservation=lambda *args:(used/'boot-A.json', {'schema':4}))
            retained = SimpleNamespace(
                collect_fresh_host=lambda cursor:full_host,
                host_errors=lambda host, boot, prefix='':[])
            recovery = SimpleNamespace(
                host_state=lambda:vfio,
                validate_host_state=lambda state, boot:[])
            original_helper = tool.helper
            def helpers(name):
                return {'warm-qualification':warm_tool,
                        'retained-kiq-continuation':retained,
                        'vfio-recover':recovery}.get(name, original_helper(name))
            with patch.object(tool, 'helper', side_effect=helpers), \
                 patch.object(tool, 'host_snapshot', return_value=capture_host), \
                 patch.object(tool, 'active_launch_units', return_value=[]), \
                 patch.object(tool, 'current_identity', return_value=identity), \
                 patch.object(tool, 'replace_json') as replace:
                cursor = tool.reserve_warm_qualification(
                    used, 'boot-A', manifest['run_id'], receipt, manifest,
                    manifest_path, output, authorization)
            self.assertEqual(cursor, full_host['journal_cursor'])
            replace.assert_called_once_with(used/'boot-A.json', {'schema':4})
            mismatch = dict(identity, launch_options={
                'BOOTDISK_MODE':'custom', 'NVRAM':'stock'})
            with patch.object(tool, 'helper', side_effect=helpers), \
                 patch.object(tool, 'host_snapshot', return_value=capture_host), \
                 patch.object(tool, 'active_launch_units', return_value=[]), \
                 patch.object(tool, 'current_identity', return_value=mismatch), \
                 patch.object(tool, 'replace_json') as refused_replace:
                with self.assertRaisesRegex(ValueError, 'launch_options'):
                    tool.reserve_warm_qualification(
                        used, 'boot-A', manifest['run_id'], receipt, manifest,
                        manifest_path, output, authorization)
            refused_replace.assert_not_called()

    def test_reuse_requires_latest_predecessor_and_a_valid_receipt(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
            runs = ['a'*32, 'b'*32, 'c'*32]
            ledger = {'schema':2, 'boot_id':'boot-A', 'max_launches':3,
                      'launches':[{'run_id':runs[0]},
                                  {'run_id':runs[1], 'recovery_id':'1'*32},
                                  {'run_id':runs[2], 'recovery_id':'2'*32}]}
            (used/'boot-A.json').write_text(json.dumps(ledger))
            receipt_dir = vm/'run/vfio-recovery/boot-A'; receipt_dir.mkdir(parents=True)
            wrong = {'schema':2, 'status':'recovered', 'authorizes_launch':True,
                     'boot_id':'boot-A',
                     'prior_run_id':runs[0], 'recovery_id':'3'*32,
                     'device':'0000:7b:00.0', 'iommu_group':'31', 'driver':'vfio-pci',
                     'pci_command_before':3, 'pci_command_after':3,
                     'reset_methods_before':[], 'reset_methods_after':[],
                     'kernel_messages':[],
                     'gc_quiesce':{'status':'quiesced', 'active_after':0,
                                   'dequeue_timeouts':0, 'forced_inactive':0,
                                   'cp_stat_after':0, 'cp_cpc_busy_after':0,
                                   'cp_me_after':0x15000000,
                                   'cp_mec_after':0x50000000,
                                   'pq_wptr_poll_after':0,
                                   'pq_status_after':0,
                                   'doorbell_range_lower_after':0,
                                   'doorbell_range_upper_after':0,
                                   'sdma0_after':1,
                                   'sdma0_cntl_after':0,
                                   'sdma0_rb_after':0,
                                   'sdma0_ib_after':0,
                                   'gfx_ring_clean':True,
                                   'gfx_retirement_confirmed':True,
                                   'gfx_needs_unmap':False,
                                   'gfx_was_stale':False,
                                   'host_kiq':{'status':'not-needed'},
                                   'gfx_rb_active_after':0,
                                   'gfx_rb_doorbell_after':0,
                                   'gfx_rb_wptr_after':0,
                                   'gfx_rb_wptr_hi_after':0,
                                   'gfx_rb_base_after':0,
                                   'gfx_rb_base_hi_after':0,
                                   'gfx_rb_cntl_after':0},
                     'commands':[{'command':0x00030000, 'response':0x80030000,
                                  'confirmed':True},
                                 {'command':0x000c0000, 'response':0x800c0000,
                                  'confirmed':True}]}
            (receipt_dir/(runs[2]+'.json')).write_text(json.dumps(wrong))
            # No launch-count ceiling any more: a fourth launch on this boot is
            # refused solely because the latest predecessor's receipt is invalid.
            authorization, errors = tool.reuse_authorization(vm, 'boot-A', 'd'*32)
            self.assertIsNone(authorization)
            self.assertEqual(errors, ['recovery_receipt'])

    def test_recovery_receipt_validation_fails_closed(self):
        tool = self.module()
        good = self.recovery_receipt(tool)
        self.assertEqual(tool.validate_recovery_receipt(good, 'boot-A', 'a'*32), [])
        native = json.loads(json.dumps(good))
        native['gc_quiesce']['reservation']['consume_hdp_flush']['remap'] = 0x385c
        self.assertEqual(tool.validate_recovery_receipt(native, 'boot-A', 'a'*32), [])
        native['gc_quiesce']['reservation']['consume_hdp_flush']['posted_read'] = 0x201
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            native, 'boot-A', 'a'*32))
        for key in ('remap', 'posted_read'):
            noninteger = self.recovery_receipt(tool)
            value = noninteger['gc_quiesce']['reservation']['consume_hdp_flush'][key]
            noninteger['gc_quiesce']['reservation']['consume_hdp_flush'][key] = float(value)
            self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                noninteger, 'boot-A', 'a'*32))
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            {key:value for key,value in good.items() if key != 'gc_quiesce'},
            'boot-A', 'a'*32))
        stale_gfx = json.loads(json.dumps(good))
        stale_gfx['gc_quiesce']['gfx_rb_active_after'] = 1
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            stale_gfx, 'boot-A', 'a'*32))
        recovered_stale_gfx = json.loads(json.dumps(good))
        reservation = recovered_stale_gfx['gc_quiesce']['reservation']
        fb = 0xf400000000
        recovered_stale_gfx['gc_quiesce'].update({
            'gfx_needs_unmap':True,
            'gfx_was_stale':True,
            'host_kiq':{'status':'retired', 'selector':9,
                        'cleanup_confirmed':True,
                        'gfx_active_after_unmap':0,
                        'gfx_active_before_scrub':0,
                        'graphics_pipes_after_unmap':
                            recovered_stale_gfx['gc_quiesce'][
                                'graphics_pipes_after_retirement'],
                        'packet_dwords':0x100,
                        'rptr_after':0x100,
                        'fence_sequence':0x12345678,
                        'fence_after':0x12345678,
                        'gfx_doorbell_offset':0x400,
                        'hdp_flush':{'remap':0x7f000, 'posted_read':0x200},
                        'reservation':reservation,
                        'addresses':{
                            'ring':fb+0x0f100000, 'mqd':fb+0x0f110000,
                            'rptr':fb+0x0f111000, 'wptr':fb+0x0f111008,
                            'eop':fb+0x0f112000, 'fence':fb+0x0f113000},
                        'gart':{'control':0, 'root':0, 'start_page':0,
                                'end_page':0, 'physical_fb':0x840000000,
                                'bar_offset':None, 'size':0, 'active':False},
                        'cleanup':{'mec_cntl':0x50000000, 'hqd_active':0,
                                   'hqd_doorbell':0, 'hqd_rptr':0,
                                   'hqd_wptr_lo':0, 'hqd_wptr_hi':0,
                                   'pq_status':0, 'doorbell_range_lower':0,
                                   'doorbell_range_upper':0, 'wptr_poll_cntl':0},
                        'final_gate':{
                            'active_after':0, 'cp_stat_after':0,
                            'cp_cpc_busy_after':0, 'pq_wptr_poll_after':0,
                            'pq_status_after':0, 'doorbell_range_lower_after':0,
                            'doorbell_range_upper_after':0,
                            'gfx_ring_clean':True,
                            'gfx_retirement_confirmed':True,
                            'graphics_pipe_proof_complete':True}},
        })
        before_pipe0 = recovered_stale_gfx['gc_quiesce'][
            'graphics_pipes_before']['pipes'][0]
        before_pipe0.update(rb0_active=1, active=1,
                            doorbell_control=0xc0000400,
                            doorbell_offset=0x400,
                            doorbell_status=0xc0000000)
        self.assertEqual(tool.validate_recovery_receipt(
            recovered_stale_gfx, 'boot-A', 'a'*32), [])
        recovered_stale_gfx['gc_quiesce']['host_kiq']['cleanup_confirmed'] = False
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            recovered_stale_gfx, 'boot-A', 'a'*32))
        for key, value in [('fence_after',0), ('gfx_doorbell_offset',0x800),
                           ('packet_dwords',6), ('reservation',{'consumed':True}),
                           ('hdp_flush',{'remap':0})]:
            broken = json.loads(json.dumps(recovered_stale_gfx))
            broken['gc_quiesce']['host_kiq']['cleanup_confirmed'] = True
            broken['gc_quiesce']['host_kiq'][key] = value
            self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                broken, 'boot-A', 'a'*32))

    def test_schema6_dispatch_accepts_new_proof_without_weakening_schema5(self):
        tool = self.module()
        schema5 = self.recovery_receipt(tool)
        schema6 = self.schema6_recovery_receipt(tool)

        self.assertEqual(tool.validate_recovery_receipt(
            schema5, 'boot-A', 'a'*32), [])
        self.assertEqual(tool.validate_recovery_receipt_v6(
            schema6, 'boot-A', 'a'*32), [])
        self.assertEqual(tool.validate_reuse_receipt(
            schema6, 'boot-A', 'a'*32), [])
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            schema6, 'boot-A', 'a'*32))

    def test_schema6_gart_excludes_recovery_writes_instead_of_reserved_heap(self):
        tool = self.module()
        receipt = self.schema6_host_kiq_receipt(tool)
        gart = receipt['gc_quiesce']['host_kiq']['gart']
        gart.update({
            'root':0x840000000 + 0x0fdfc000 + 1,
            'start_page':0xffbfa00,
            'end_page':0xffffe00,
            'bar_offset':0x0fdfc000,
            'size':0x202008,
        })

        self.assertEqual(tool.validate_recovery_receipt_v6(
            receipt, 'boot-A', 'a'*32), [])

        legacy = copy.deepcopy(receipt)
        legacy['schema'] = 5
        gc = legacy['gc_quiesce']
        for key in ('sdma0_page_ib_before', 'sdma0_page_ib_after',
                    'sdma0_page_rb_before', 'sdma0_page_rb_after',
                    'sdma0_status_before', 'sdma0_status_after',
                    'sdma0_shutdown_trace', 'sdma0_rlc_inputs'):
            gc.pop(key)
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            legacy, 'boot-A', 'a'*32))

    def test_schema6_gart_rejects_descriptor_and_host_kiq_write_spans(self):
        tool = self.module()

        def receipt_with_gart(offset, size):
            receipt = self.schema6_host_kiq_receipt(tool)
            gart = receipt['gc_quiesce']['host_kiq']['gart']
            gart.update({
                'root':gart['physical_fb'] + offset + 1,
                'start_page':0,
                'end_page':size // 8 - 1,
                'bar_offset':offset,
                'size':size,
            })
            return receipt

        for label, offset, size, accepted in (
                ('before-descriptor', 0x0efff000, 0x1000, True),
                ('descriptor', 0x0f000000, 0x8, False),
                ('after-descriptor', 0x0f001000, 0x8, True),
                ('before-host-kiq', 0x0f0ff000, 0x1000, True),
                ('host-kiq-start', 0x0f100000, 0x8, False),
                ('host-kiq-tail', 0x0f113000, 0x8, False),
                ('after-host-kiq', 0x0f114000, 0x8, True)):
            with self.subTest(label=label):
                errors = tool.validate_recovery_receipt_v6(
                    receipt_with_gart(offset, size), 'boot-A', 'a'*32)
                self.assertEqual(errors == [], accepted)

    def test_schema6_recovery_write_range_pins_match_producer(self):
        consumer = self.module()
        path = ROOT / 'tools/vfio-recover.py'
        spec = importlib.util.spec_from_file_location('vfio_recover_ranges', path)
        producer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(producer)
        scratch = producer.host_kiq_scratch_ranges()

        self.assertEqual(consumer.RECOVERY_V6_MUTATED_RANGES, (
            (producer.HOST_KIQ_RESERVATION_OFFSET,
             producer.HOST_KIQ_RESERVATION_SIZE),
            (min(start for start, _ in scratch),
             max(start + size for start, size in scratch) -
                 min(start for start, _ in scratch)),
        ))

    def test_schema6_accepts_only_disabled_host_kiq_doorbell_status(self):
        tool = self.module()
        hit_only = self.schema6_host_kiq_receipt(tool)
        cleanup = hit_only['gc_quiesce']['host_kiq']['cleanup']
        cleanup['hqd_doorbell'] = 0x80000000

        self.assertEqual(tool.validate_recovery_receipt_v6(
            hit_only, 'boot-A', 'a'*32), [])
        self.assertEqual(tool.validate_reuse_receipt(
            hit_only, 'boot-A', 'a'*32), [])
        self.assertEqual(cleanup['hqd_doorbell'], 0x80000000)

        legacy = self.host_kiq_receipt(tool)
        legacy['gc_quiesce']['host_kiq']['cleanup']['hqd_doorbell'] = 0x80000000
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            legacy, 'boot-A', 'a'*32))

        for label, value in (
                ('enabled', 0x40000000),
                ('hit-and-enabled', 0xc0000000),
                ('mode', 0x00000001),
                ('scheduler-hit', 0x20000000),
                ('negative', -1),
                ('wider-than-dword', 0x100000000),
                ('boolean', True),
                ('not-an-integer', None)):
            with self.subTest(label=label):
                broken = self.schema6_host_kiq_receipt(tool)
                broken['gc_quiesce']['host_kiq']['cleanup'][
                    'hqd_doorbell'] = value
                self.assertIn('recovery_receipt',
                              tool.validate_recovery_receipt_v6(
                                  broken, 'boot-A', 'a'*32))

        missing = self.schema6_host_kiq_receipt(tool)
        missing['gc_quiesce']['host_kiq']['cleanup'].pop('hqd_doorbell')
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt_v6(
            missing, 'boot-A', 'a'*32))

    def test_schema6_derives_stopped_wptr_proof_without_mutating_raw_receipt(self):
        tool = self.module()
        receipt = self.schema6_host_kiq_receipt(tool)
        fixture = json.loads((ROOT/'tests/fixtures/'
                              'stopped-wptr-clear-schema6-positive.json').read_text())
        receipt['gc_quiesce'].update(copy.deepcopy(fixture['gc_quiesce']))
        # The proof fixture isolates the stopped-pointer contract. Supply the
        # full producer GART shape required by the existing receipt validator.
        gart = self.schema6_host_kiq_receipt(tool)[
            'gc_quiesce']['host_kiq']['gart']
        evidence = receipt['gc_quiesce']['host_kiq']['evidence']
        evidence['gart'] = copy.deepcopy(gart)
        evidence['retired_before_cleanup']['gart'] = copy.deepcopy(gart)
        raw = copy.deepcopy(receipt)

        self.assertEqual(tool.validate_recovery_receipt_v6(
            receipt, 'boot-A', 'a'*32), [])
        self.assertEqual(receipt, raw)
        self.assertEqual(receipt['gc_quiesce']['host_kiq']['status'], 'failed')

        corrupted = copy.deepcopy(receipt)
        corrupted['gc_quiesce']['stopped_wptr_doorbell_clear'][
            'transition']['doorbell']['value'] = 1
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt_v6(
            corrupted, 'boot-A', 'a'*32))

        without_proof = copy.deepcopy(receipt)
        without_proof['gc_quiesce'].pop('stopped_wptr_doorbell_clear')
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt_v6(
            without_proof, 'boot-A', 'a'*32))

        legacy = copy.deepcopy(receipt)
        legacy['schema'] = 5
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            legacy, 'boot-A', 'a'*32))

    def test_schema6_rejects_inaccessible_or_unsafe_sdma_scalar_proof(self):
        tool = self.module()
        good = self.schema6_recovery_receipt(tool)

        for malformed in (None, [], 'invalid'):
            with self.subTest(malformed_gc=malformed):
                broken = dict(good, gc_quiesce=malformed)
                self.assertEqual(tool.validate_recovery_receipt_v6(
                    broken, 'boot-A', 'a'*32), ['recovery_receipt'])

        mutations = [
            ('missing-page-proof', ('sdma0_page_ib_before',), None),
            ('page-ib-enabled', ('sdma0_page_ib_after',), 0x101),
            ('page-rb-wrong-transition', ('sdma0_page_rb_after',), 0x80000000),
            ('status-not-idle', ('sdma0_status_after',), 0),
            ('status-inaccessible', ('sdma0_status_before',), 0xffffffff),
            ('status-negative', ('sdma0_status_before',), -1),
            ('f32-inaccessible', ('sdma0_after',), 0xffffffff),
            ('f32-wider-than-dword', ('sdma0_before',), 0x100000000),
            ('gfx-input-inaccessible', ('sdma0_rb_before',), 0xffffffff),
            ('boolean-is-not-register', ('sdma0_page_rb_before',), True),
        ]
        for label, path, value in mutations:
            with self.subTest(label=label):
                broken = json.loads(json.dumps(good))
                if label == 'missing-page-proof':
                    broken['gc_quiesce'].pop(path[0])
                else:
                    broken['gc_quiesce'][path[0]] = value
                self.assertIn('recovery_receipt',
                              tool.validate_recovery_receipt_v6(
                                  broken, 'boot-A', 'a'*32))

    def test_schema6_rejects_wrong_page_trace_or_rlc_observations(self):
        tool = self.module()
        good = self.schema6_recovery_receipt(tool)

        mutations = []
        reversed_trace = list(reversed(good['gc_quiesce']['sdma0_shutdown_trace']))
        mutations.append(('trace-order', ('sdma0_shutdown_trace',), reversed_trace))
        wrong_register = json.loads(json.dumps(
            good['gc_quiesce']['sdma0_shutdown_trace']))
        wrong_register[0]['register'] += 4
        mutations.append(('trace-register', ('sdma0_shutdown_trace',), wrong_register))
        wrong_readback = json.loads(json.dumps(
            good['gc_quiesce']['sdma0_shutdown_trace']))
        wrong_readback[1]['readback'] ^= 1
        mutations.append(('trace-readback', ('sdma0_shutdown_trace',), wrong_readback))
        extra_trace_key = json.loads(json.dumps(
            good['gc_quiesce']['sdma0_shutdown_trace']))
        extra_trace_key[0]['extra'] = 0
        mutations.append(('trace-exact-keys', ('sdma0_shutdown_trace',), extra_trace_key))

        for label, path, value in mutations:
            with self.subTest(label=label):
                broken = json.loads(json.dumps(good))
                broken['gc_quiesce'][path[0]] = value
                self.assertIn('recovery_receipt',
                              tool.validate_recovery_receipt_v6(
                                  broken, 'boot-A', 'a'*32))

        rlc_mutations = [
            ('missing-row', lambda rows: rows.pop()),
            ('wrong-index', lambda rows: rows[1].update(index=0)),
            ('extra-key', lambda rows: rows[0].update(extra=0)),
            ('changed-observation', lambda rows: rows[0].update(rb_after=0x204)),
            ('enabled-rb', lambda rows: rows[0].update(rb_after=0x201,
                                                       rb_before=0x201)),
            ('enabled-ib', lambda rows: rows[1].update(ib_after=0x105,
                                                       ib_before=0x105)),
            ('inaccessible', lambda rows: rows[0].update(ib_before=0xffffffff,
                                                         ib_after=0xffffffff)),
            ('boolean-register', lambda rows: rows[0].update(rb_before=False,
                                                             rb_after=False)),
            ('wider-than-dword', lambda rows: rows[0].update(rb_before=0x100000000,
                                                             rb_after=0x100000000)),
        ]
        for label, mutate in rlc_mutations:
            with self.subTest(label=label):
                broken = json.loads(json.dumps(good))
                mutate(broken['gc_quiesce']['sdma0_rlc_inputs'])
                self.assertIn('recovery_receipt',
                              tool.validate_recovery_receipt_v6(
                                  broken, 'boot-A', 'a'*32))

    def test_recovery_receipt_admission_mutation_checks_every_hardware_proof(self):
        tool = self.module()
        good = self.host_kiq_receipt(tool)
        self.assertEqual(tool.validate_recovery_receipt(good, 'boot-A', 'a'*32), [])

        def changed(path, value, *, mirror_reservation=False):
            receipt = json.loads(json.dumps(good))
            target = receipt
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            if mirror_reservation:
                receipt['gc_quiesce']['host_kiq']['reservation'] = json.loads(
                    json.dumps(receipt['gc_quiesce']['reservation']))
            return receipt

        # Receipt schemas are deliberately not backward-compatible: adding a
        # proof changes the version and older receipts fail closed.
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            changed(('schema',), 3), 'boot-A', 'a'*32))

        for index, expected in tool.RECOVERY_BAR_REGIONS.items():
            for field, value in expected.items():
                bad = (not value if type(value) is bool else value + 1)
                with self.subTest(area='region', index=index, field=field):
                    self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                        changed(('bar5','regions',index,field), bad),
                        'boot-A', 'a'*32))
        for field, value in tool.RECOVERY_BAR_REGIONS['5'].items():
            bad = (not value if type(value) is bool else value + 1)
            with self.subTest(area='bar5', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('bar5',field), bad), 'boot-A', 'a'*32))

        reservation_bad = {
            'version':2, 'state':0, 'heap_limit':0, 'reservation_start':0,
            'scratch_start':0, 'reservation_end':0, 'run_id':'c'*32,
            'checksum':0, 'consumed':False,
        }
        for field, bad in reservation_bad.items():
            with self.subTest(area='reservation', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','reservation',field), bad,
                            mirror_reservation=True), 'boot-A', 'a'*32))
        for field, bad in [('remap',0), ('posted_read',0xffffffff)]:
            with self.subTest(area='reservation-flush', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','reservation','consume_hdp_flush',field), bad,
                            mirror_reservation=True), 'boot-A', 'a'*32))

        host_bad = {
            'status':'failed', 'selector':8, 'cleanup_confirmed':False,
            'gfx_active_after_unmap':1, 'gfx_active_before_scrub':1,
            'packet_dwords':6, 'rptr_after':0, 'fence_sequence':0,
            'fence_after':0, 'gfx_doorbell_offset':0x800,
        }
        for field, bad in host_bad.items():
            with self.subTest(area='host-kiq', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','host_kiq',field), bad),
                    'boot-A', 'a'*32))
        for field, bad in [('remap',0), ('posted_read',0xffffffff)]:
            self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                changed(('gc_quiesce','host_kiq','hdp_flush',field), bad),
                'boot-A', 'a'*32))

        for field in ('ring','mqd','rptr','wptr','eop','fence'):
            value = good['gc_quiesce']['host_kiq']['addresses'][field]
            with self.subTest(area='addresses', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','host_kiq','addresses',field), value+4),
                    'boot-A', 'a'*32))
        gart_bad = {'control':0, 'root':0, 'start_page':2, 'end_page':0xfe,
                    'physical_fb':0x850000000, 'bar_offset':0x0e000004,
                    'size':0x808, 'active':False}
        for field, bad in gart_bad.items():
            with self.subTest(area='gart', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','host_kiq','gart',field), bad),
                    'boot-A', 'a'*32))
        cleanup_bad = {
            'mec_cntl':0, 'hqd_active':1, 'hqd_doorbell':1,
            'hqd_rptr':1, 'hqd_wptr_lo':1, 'hqd_wptr_hi':1,
            'pq_status':2, 'doorbell_range_lower':1,
            'doorbell_range_upper':1, 'wptr_poll_cntl':0x80000000,
        }
        for field, bad in cleanup_bad.items():
            with self.subTest(area='cleanup', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','host_kiq','cleanup',field), bad),
                    'boot-A', 'a'*32))
        for field, value in good['gc_quiesce']['host_kiq']['final_gate'].items():
            bad = (not value if type(value) is bool else value + 1)
            with self.subTest(area='final-gate', field=field):
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    changed(('gc_quiesce','host_kiq','final_gate',field), bad),
                    'boot-A', 'a'*32))
        for key, value in [('status','failed'), ('prior_run_id','c'*32),
                           ('pci_command_after',7), ('reset_methods_after',['bus']),
                           ('kernel_messages',['vfio-pci 0000:7b:00.0: resetting']),
                           ('commands',[{'confirmed':True}])]:
            self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                dict(good, **{key:value}), 'boot-A', 'a'*32))
        for key, value in [('dequeue_timeouts',1), ('forced_inactive',1),
                           ('cp_stat_after',0x80008200),
                           ('cp_cpc_busy_after',0x08080000)]:
            broken = dict(good)
            broken['gc_quiesce'] = dict(good['gc_quiesce'], **{key:value})
            self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                broken, 'boot-A', 'a'*32))

    def test_schema5_rejects_unsafe_or_missing_pipe_proof(self):
        tool = self.module()
        good = self.recovery_receipt(tool)

        def copy():
            return json.loads(json.dumps(good))

        for stage in ('graphics_pipe_guard', 'graphics_pipes_before',
                      'graphics_pipes_after_retirement', 'graphics_pipes_final'):
            with self.subTest(stage=stage, condition='active'):
                broken = copy()
                snapshot = (broken['gc_quiesce'][stage]['snapshot']
                            if stage == 'graphics_pipe_guard'
                            else broken['gc_quiesce'][stage])
                snapshot['pipes'][1].update(rb1_active=1, active=1)
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    broken, 'boot-A', 'a'*32))
            with self.subTest(stage=stage, condition='doorbell'):
                broken = copy()
                snapshot = (broken['gc_quiesce'][stage]['snapshot']
                            if stage == 'graphics_pipe_guard'
                            else broken['gc_quiesce'][stage])
                snapshot['pipes'][1].update(
                    doorbell_control=0x40000408, doorbell_offset=0x408,
                    doorbell_status=0x40000000)
                self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
                    broken, 'boot-A', 'a'*32))

        broken = copy()
        broken['gc_quiesce'].pop('graphics_pipes_before')
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            broken, 'boot-A', 'a'*32))
        broken = copy()
        broken['gc_quiesce']['graphics_pipe_guard']['reservation_after']['checksum'] ^= 1
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            broken, 'boot-A', 'a'*32))
        broken = copy()
        broken['gc_quiesce']['graphics_pipe_proof_complete'] = False
        self.assertIn('recovery_receipt', tool.validate_recovery_receipt(
            broken, 'boot-A', 'a'*32))

        # Off-diagonal ACTIVE cells have no source-backed meaning. Preserve them
        # as raw evidence without treating even all-ones as a pipe-1 claim.
        observed = copy()
        for key in ('snapshot',):
            observed['gc_quiesce']['graphics_pipe_guard'][key][
                'pipes'][1]['rb0_active'] = 0xffffffff
        for stage in ('graphics_pipes_before', 'graphics_pipes_after_retirement',
                      'graphics_pipes_final'):
            observed['gc_quiesce'][stage]['pipes'][1]['rb0_active'] = 0xffffffff
        self.assertEqual(tool.validate_recovery_receipt(
            observed, 'boot-A', 'a'*32), [])

    def test_startup_schema4_is_fallback_and_both_ids_are_single_use(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
            prior, current = 'a'*32, 'b'*32
            ledger = {'schema':2, 'boot_id':'boot-A', 'max_launches':3,
                      'launches':[{'run_id':prior}]}
            (used/'boot-A.json').write_text(json.dumps(ledger) + '\n')
            receipt = {'schema':4, 'recovery_id':'c'*32, 'attempt_id':'d'*32,
                       'ledger_sha256':hashlib.sha256(
                           (used/'boot-A.json').read_bytes()).hexdigest()}
            target = vm/'run/startup-noqueue-recovery/boot-A'; target.mkdir(parents=True)
            (target/(prior+'.json')).write_text(json.dumps(receipt))
            calls = []
            startup = SimpleNamespace(validate_receipt=lambda value, boot, run, root:
                (calls.append((value, boot, run, root)) or []))
            with patch.object(tool, 'helper', return_value=startup):
                authorization, errors = tool.reuse_authorization(
                    vm, 'boot-A', current)
                self.assertEqual(errors, [])
                self.assertEqual(authorization, receipt)
                tool.reserve_boot(used, 'boot-A', current, authorization)
            self.assertEqual([call[3] for call in calls], [vm, vm])
            updated = json.loads((used/'boot-A.json').read_text())
            self.assertEqual(updated['launches'][1]['recovery_id'], 'c'*32)
            self.assertEqual(updated['launches'][1]['attempt_id'], 'd'*32)

            # Either identity being present in a prior launch makes a new
            # startup receipt a replay.
            for field in ('recovery_id', 'attempt_id'):
                replay = dict(receipt, recovery_id='e'*32, attempt_id='f'*32)
                replay[field] = updated['launches'][1][field]
                replay['ledger_sha256'] = hashlib.sha256(
                    (used/'boot-A.json').read_bytes()).hexdigest()
                with patch.object(tool, 'helper', return_value=startup):
                    with self.assertRaisesRegex(ValueError, 'startup_noqueue_receipt'):
                        tool.reserve_boot(used, 'boot-A', '1'*32, replay)

    def test_startup_schema4_rechecks_raw_ledger_before_reservation(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp)
            used = vm/'run/used-gpu-boots'; used.mkdir(parents=True)
            prior = 'a'*32
            path = used/'boot-A.json'
            path.write_text(json.dumps({'schema':2, 'boot_id':'boot-A',
                                        'max_launches':3,
                                        'launches':[{'run_id':prior}]}) + '\n')
            receipt = {'schema':4, 'recovery_id':'c'*32, 'attempt_id':'d'*32,
                       'ledger_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            target = vm/'run/startup-noqueue-recovery/boot-A'; target.mkdir(parents=True)
            (target/(prior+'.json')).write_text(json.dumps(receipt))
            startup = SimpleNamespace(validate_receipt=lambda *args:[])
            with patch.object(tool, 'helper', return_value=startup):
                authorization, errors = tool.reuse_authorization(
                    vm, 'boot-A', 'b'*32)
            self.assertEqual(errors, [])

            # Preserve the JSON value but alter its exact byte preimage between
            # admission and reservation.
            path.write_text(json.dumps(json.loads(path.read_text()), indent=2) + '\n')
            before = path.read_bytes()
            with patch.object(tool, 'helper', return_value=startup):
                with self.assertRaisesRegex(ValueError, 'startup_noqueue_receipt'):
                    tool.reserve_boot(used, 'boot-A', 'b'*32, authorization)
            self.assertEqual(path.read_bytes(), before)

    def test_remaining_budget_uses_earlier_launch_cap(self):
        eligible = self.module().probe_fits
        self.assertFalse(eligible(now=100, launch_deadline=150, container_deadline=190))
        self.assertTrue(eligible(now=100, launch_deadline=180, container_deadline=190))
        self.assertFalse(eligible(now=100, launch_deadline=None, container_deadline=190))

    def test_running_guest_must_have_exact_image_and_vfio_device(self):
        check = getattr(self.module(), 'validate_running', None)
        self.assertIsNotNone(check, 'actual QEMU admission check missing')
        manifest = {'image_id': 'sha256:expected', 'vfio_device': '0000:7b:00.0'}
        observed = {'image_id': 'sha256:expected', 'vfio_args':
                    ['vfio-pci,host=0000:7b:00.0,x-pci-device-id=0x73ff']}
        self.assertEqual(check(manifest, observed), [])
        self.assertIn('vfio_device', check(manifest, dict(observed, vfio_args=[])))
        self.assertIn('image_id', check(manifest, dict(observed, image_id='sha256:wrong')))

    def test_headless_vfio_address_matches_opencore_path_without_collision(self):
        tool = self.module()
        topology = {'bus':'pcie.0', 'addr':'0x6',
                    'device_path':'PciRoot(0x0)/Pci(0x6,0x0)'}
        manifest = {'image_id':'sha256:expected', 'gpu':True,
                    'vfio_device':'0000:7b:00.0',
                    'launch_options':{'BOOTDISK_MODE':'custom', 'NVRAM':'stock',
                                      'GENERIC_GRAPHICS':'off'},
                    'vfio_guest_address':topology}
        vfio = ('vfio-pci,host=0000:7b:00.0,bus=pcie.0,addr=0x6,'
                'x-pci-device-id=0x73ff')
        topology_rows = [
            {'model':'qemu-xhci'}, {'model':'ich9-intel-hda'},
            {'model':'ich9-ahci'}, {'model':'vmxnet3'},
            {'model':'vfio-pci', 'bus':'pcie.0', 'slot':6, 'function':0}]
        observed = {'image_id':'sha256:expected', 'vfio_args':[vfio],
                    'pci_topology':topology_rows,
                    'graphics_args':['-vga','none','-display','none']}
        self.assertEqual(tool.validate_running(manifest, observed), [])

        frozen186 = dict(observed,
                         vfio_args=[vfio.replace(',addr=0x6', '')],
                         pci_topology=topology_rows[:-1] + [{'model':'vfio-pci'}])
        self.assertIn('vfio_guest_address',
                      tool.validate_running(manifest, frozen186))
        for replacement in ('bus=pcie.1,addr=0x6',
                            'bus=pcie.0,addr=0x6.1',
                            'bus=pcie.0,addr=0x5'):
            changed = vfio.replace('bus=pcie.0,addr=0x6', replacement)
            bad = dict(observed, vfio_args=[changed],
                       pci_topology=topology_rows[:-1] + [{'model':'vfio-pci'}])
            self.assertIn('vfio_guest_address', tool.validate_running(manifest, bad))

        for conflicting in (
                {'model':'virtio-net-pci', 'bus':'pcie.0', 'slot':6, 'function':0},
                {'model':'virtio-net-pci', 'slot':6, 'function':0}):
            conflict = dict(observed, pci_topology=topology_rows + [conflicting])
            self.assertIn('vfio_guest_address_collision',
                          tool.validate_running(manifest, conflict))
        duplicate = dict(observed, vfio_args=[vfio, vfio],
                         pci_topology=topology_rows + [topology_rows[-1]])
        duplicate_errors = tool.validate_running(manifest, duplicate)
        self.assertIn('vfio_device', duplicate_errors)
        self.assertIn('vfio_guest_address_collision', duplicate_errors)
        wrong_property_path = dict(manifest, vfio_guest_address=dict(
            topology, device_path='PciRoot(0x0)/Pci(0x5,0x0)'))
        self.assertIn('vfio_guest_address',
                      tool.validate_running(wrong_property_path, observed))

    def test_running_identity_sanitizes_device_topology_and_normalizes_addresses(self):
        source = ast.parse((ROOT / 'tools/experiment.py').read_text())
        function = next(node for node in source.body
                        if isinstance(node, ast.FunctionDef) and
                        node.name == 'running_identity')
        script = next(node.value.value for node in function.body
                      if isinstance(node, ast.Assign) and
                      isinstance(node.value, ast.Constant) and
                      isinstance(node.value.value, str))
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary) / 'proc'
            process = proc / '123'; process.mkdir(parents=True)
            args = [
                b'qemu-system-x86_64', b'-device',
                b'isa-applesmc,osk=SECRET-SENTINEL', b'-device',
                b'vfio-pci,host=0000:7b:00.0,bus=pcie.0,addr=6', b'-device',
                b'virtio-net-pci,addr=0x6.0',
            ]
            (process / 'cmdline').write_bytes(b'\0'.join(args) + b'\0')
            isolated = script.replace('/proc', str(proc))
            result = subprocess.run(
                ['python3', '-c', isolated], text=True, capture_output=True,
                check=True, timeout=5)
        self.assertNotIn('SECRET-SENTINEL', result.stdout)
        observed = json.loads(result.stdout)
        self.assertNotIn('device_args', observed)
        self.assertEqual(observed['pci_topology'], [
            {'model':'isa-applesmc'},
            {'model':'vfio-pci', 'bus':'pcie.0', 'slot':6, 'function':0},
            {'model':'virtio-net-pci', 'slot':6, 'function':0},
        ])

    def test_immutable_json_never_overwrites_prepared_identity(self):
        write = self.module().write_once
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'manifest.json'
            write(path, {'candidate': 'first'})
            with self.assertRaises(FileExistsError): write(path, {'candidate': 'second'})
            self.assertEqual(json.loads(path.read_text()), {'candidate': 'first'})

    def test_transactional_esp_staging_preserves_backup_and_reads_back(self):
        stage = getattr(self.module(), 'stage_image', None)
        self.assertIsNotNone(stage, 'transactional image staging missing')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); image = root / 'esp.img'
            subprocess.run(['mformat', '-i', str(image), '-C', '-T', '16384', '::'], check=True)
            for directory in ('::/EFI', '::/EFI/OC', '::/EFI/OC/Kexts'):
                subprocess.run(['mmd', '-i', str(image), directory], check=True)
            before = image.read_bytes()
            bundle = root / 'RaphaelGPU.kext'
            (bundle / 'Contents/MacOS').mkdir(parents=True)
            (bundle / 'Contents/MacOS/RaphaelGPU').write_bytes(b'new-executable')
            (bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleVersion': '1.0.163'}))
            config = plistlib.dumps({'test': 'new-config'})
            result = stage(image, bundle, config, offset=0)
            self.assertEqual(Path(result['backup']).read_bytes(), before)
            self.assertEqual(result['binary_sha256'], hashlib.sha256(b'new-executable').hexdigest())
            got = subprocess.check_output(['mtype', '-i', str(image), '::/EFI/OC/config.plist'])
            self.assertEqual(got, config)
            good = image.read_bytes()
            (bundle / 'Contents/MacOS/RaphaelGPU').unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                stage(image, bundle, config, offset=0)
            self.assertEqual(image.read_bytes(), good)

    def test_one_run_archives_failure_stops_and_never_reuses_boot(self):
        self.exercise_run('hybrid')

    def test_wrong_running_image_aborts_and_stops_exact_container(self):
        self.exercise_run('wrong-image')

    def test_cancelled_observation_stops_exact_container(self):
        self.exercise_run('cancel')

    def test_definitive_capture_loss_stops_without_using_remaining_budget(self):
        self.exercise_run('capture-loss')

    def test_pending_capture_uses_existing_deadline_without_running_probe(self):
        self.exercise_run('capture-pending-timeout')

    def test_runtime_abort_after_validated_launch_attempts_guest_shutdown_first(self):
        self.exercise_run('runtime-abort')

    def test_host_capture_failure_attempts_guest_shutdown_but_forbids_reuse(self):
        self.exercise_run('monitor-capture')

    def test_host_kernel_fault_uses_immediate_exact_stop_and_forbids_reuse(self):
        self.exercise_run('monitor-fault')

    def test_unresolved_startup_stop_is_explicit(self):
        self.exercise_run('unconfirmed')

    def test_gpueless_coordinator_does_not_open_vfio_or_consume_gpu_boot(self):
        self.exercise_run('gpu-less')

    def test_kernel_fault_during_shutdown_invalidates_result(self):
        self.exercise_run('shutdown-fault')

    def test_probe_runs_exactly_once_after_native_readiness(self):
        self.exercise_run('probe-ready')

    def test_probe_is_not_started_without_cleanup_budget(self):
        self.exercise_run('probe-no-budget')

    def test_selected_readiness_refusal_survives_truncated_shutdown_capture(self):
        self.exercise_run('decision-receipt-capture-loss')

    def test_transient_inconclusive_before_ready_does_not_create_refusal_receipt(self):
        self.exercise_run('decision-receipt-ready')

    def test_run_one_quiesces_producer_after_probe_before_shutdown(self):
        self.exercise_run('producer-quiesce-ready')

    def test_run_one_rejects_bytes_after_producer_ack(self):
        self.exercise_run('producer-quiesce-post-ack-tail')

    def test_valid_v2_receipt_authorizes_generic_same_boot_reuse(self):
        tool = self.module()
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm/'run').mkdir()
            manifests = []
            for run_id in ('a'*32, 'b'*32):
                manifest = {key:'fixture' for key in tool.IDENTITY_FIELDS}
                manifest.update(
                    build_id='abc', run_id=run_id, max_seconds=180,
                    boot_id='boot-A', bootdisk_verified=True, gpu=True,
                    recovery_lease_schema=2,
                    recovery_helpers_sha256=self.recovery_helper_hashes(),
                    spec={'run_probe_only_after_native_start':True,
                          'requested_diagnostic':'rgpusdma=1'},
                    launch_options={'BOOTDISK_MODE':'custom', 'NVRAM':'stock'},
                    source_clean=True, vfio_device='0000:7b:00.0',
                    candidate_directory='run/candidate-173',
                    image_id='sha256:expected')
                path = vm/f'prepared-{run_id[0]}.json'
                path.write_text(json.dumps(manifest))
                manifests.append((manifest, path))

            host = dict(self.host(), sleep_inhibited=True)
            now = [100.0]
            calls = []
            lines = [
                'BUILD: identity=abc',
                'HY: HWLibs hybrid trace route=ok entries-match=1',
                'XJ:   waitForHwStamp(1) -> 1',
                'HY: createHybridEngine enter: engine=1 available=1',
                'HY: createHybridEngine exit: engine=1 valid=1 available-before=1 status=4',
                'XJ: AMDHardware::startHWEngines -> 0',
            ]
            lines.extend(self.v2_critical_payloads('a'*32))
            serial = f'RGPU_RECORDS build=abc count={len(lines)} dropped=0 truncated=0\n'+''.join(
                f'RGPU_EVENT build=abc seq={i} {line}\n'
                for i,line in enumerate(lines))

            class StopUnconfirmed(RuntimeError):
                pass

            def start(*args):
                calls.append(('start', args[2]))
                (vm/'run/serial.log').write_text(serial)
                return {'cid':'c'*64, 'deadline_epoch':now[0]+180,
                        'max_seconds':180}

            supervisor = SimpleNamespace(
                start_locked=start, verify=lambda state:None,
                ManagedStopUnconfirmed=StopUnconfirmed,
                stop_exact=lambda cid:calls.append(('unexpected-stop', cid)))

            def shutdown(vm_path, state, expected_build, grace):
                calls.append(('forced-stop-confirmed', state['cid']))
                return {'cid':state['cid'], 'outcome':'forced',
                        'request_sent':True, 'guest_boot_uuid':'1'*36,
                        'request_id':'2'*32, 'request_error':None,
                        'acpi_request_sent':True,
                        'acpi_request_error':'bounded grace expired'}

            lease_evidence = object()
            def parse_v2_lease_records(records, prior):
                calls.append(('parse-v2', prior))
                return lease_evidence

            def recover(vm_path, prior, *, lease_evidence=None,
                        recovery_helpers_sha256=None):
                self.assertIs(lease_evidence, globals_lease_evidence)
                self.assertEqual(recovery_helpers_sha256,
                                 manifests[0][0]['recovery_helpers_sha256'])
                calls.append(('recover', prior))
                recovery_id = 'f'*32
                receipt = self.recovery_receipt(tool, prior, recovery_id)
                target = vm_path/'run/vfio-recovery/boot-A'
                target.mkdir(parents=True, exist_ok=True)
                (target/(prior+'.json')).write_text(json.dumps(receipt))
                return receipt

            globals_lease_evidence = lease_evidence
            recovery = SimpleNamespace(
                recover=recover, parse_v2_lease_records=parse_v2_lease_records)
            guest_shutdown = SimpleNamespace(shutdown=shutdown)
            original_helper = tool.helper

            def helpers(name):
                if name == 'vm-supervision': return supervisor
                if name == 'guest-shutdown': return guest_shutdown
                if name == 'vfio-recover': return recovery
                return original_helper(name)

            class NoopMonitor:
                def __init__(self, cursor, interrupt, interval=1):
                    self.messages = []; self.error = None; self.error_kind = None
                def start(self): pass
                def stop(self): pass

            observed = iter([manifests[0][0], manifests[1][0]])
            def current_identity(vm_path, candidate, requested_diagnostic,
                                 run_id=None, recovery_lease_schema=2,
                                 launch_options_expected=None, probe_spec=None):
                return next(observed)
            with patch.object(tool, 'current_identity', side_effect=current_identity), \
                 patch.object(tool, 'host_snapshot', return_value=host), \
                 patch.object(tool, 'helper', side_effect=helpers), \
                 patch.object(tool, 'running_identity', return_value={
                     'image_id':'sha256:expected',
                     'vfio_args':['vfio-pci,host=0000:7b:00.0']}), \
                 patch.object(tool, 'kernel_updates', return_value=('cursor', [], [])), \
                 patch.object(tool, 'HostMonitor', NoopMonitor), \
                 patch.object(tool.time, 'time', side_effect=lambda:now[0]), \
                 patch.object(tool.time, 'sleep', side_effect=lambda n:now.__setitem__(0, now[0]+n)):
                first = tool.run_one(vm, manifests[0][1], vm/'evidence-a')
                second = tool.run_one(vm, manifests[1][1], vm/'evidence-b')

            # No flag and no status.md allowance: the second run is admitted purely
            # because the first run's teardown left a valid recovery receipt.
            self.assertEqual(first['warm_reuse'], 'recovered')
            self.assertNotEqual(second['verdict'], 'INVALID')
            self.assertNotIn('error', second)
            self.assertEqual(second['warm_reuse'], 'recovered')
            self.assertEqual([call for call in calls if call[0] == 'start'], [
                ('start', ['--gpu','0000:7b:00.0','--gpu-id','0x73ff',
                           '--gpu-rom','run/gpu-patched.rom'])]*2)
            self.assertEqual(len([call for call in calls
                                  if call[0] == 'forced-stop-confirmed']), 2)
            self.assertNotIn(('unexpected-stop', 'c'*64), calls)
            ledger = json.loads((vm/'run/used-gpu-boots/boot-A.json').read_text())
            self.assertEqual([row['run_id'] for row in ledger['launches']],
                             ['a'*32, 'b'*32])
            self.assertEqual(ledger['launches'][1]['recovery_id'], 'f'*32)
            self.assertEqual(ledger['launches'][1]['prior_run_id'], 'a'*32)
            for run_id in ('a'*32, 'b'*32):
                admitted = json.loads(
                    (vm/'run/vfio-recovery/boot-A'/(run_id+'.json')).read_text())
                self.assertEqual(tool.validate_recovery_receipt(
                    admitted, 'boot-A', run_id), [])

    def exercise_run(self, mode):
        tool = self.module()
        self.assertTrue(hasattr(tool, 'run_one'))
        with tempfile.TemporaryDirectory() as temp:
            vm = Path(temp); (vm/'run').mkdir()
            manifest = {key:'fixture' for key in tool.IDENTITY_FIELDS}
            manifest.update(build_id='abc', run_id='a'*32, max_seconds=180, boot_id='boot-A',
                            bootdisk_verified=True, gpu=True,
                            recovery_lease_schema=2,
                            recovery_helpers_sha256=self.recovery_helper_hashes(),
                            spec={'run_probe_only_after_native_start': True,
                                  'requested_diagnostic': 'rgpusdma=1'},
                            launch_options={'BOOTDISK_MODE':'custom', 'NVRAM':'stock'},
                            source_clean=True, vfio_device='0000:7b:00.0',
                            candidate_directory='run/candidate-163', image_id='sha256:expected')
            quiesce_modes = ('producer-quiesce-ready',
                             'producer-quiesce-post-ack-tail')
            decision_modes = ('decision-receipt-capture-loss',
                              'decision-receipt-ready', *quiesce_modes)
            if mode in decision_modes:
                manifest.update(
                    build_id=CR2_BUILD, boot_args='rgpucr2uart=2',
                    critical_replay_schema=2, recovery_lease_schema=3,
                    recovery_critical_replay_tolerance='terminal-prefix-open',
                    recovery_helpers_sha256=self.recovery_helper_hashes(3),
                    critical_replay_transport=TRANSPORT,
                    critical_transport_validator_sha256=hashlib.sha256(
                        (ROOT/'tools/critical-transport.py').read_bytes()).hexdigest())
                manifest['spec']['critical_replay_transport'] = TRANSPORT
                manifest['spec']['critical_replay_schema'] = 2
                manifest['spec']['recovery_critical_replay_tolerance'] = \
                    'terminal-prefix-open'
                if mode in quiesce_modes:
                    manifest['boot_args'] += ' rgpucr2quiesce=1'
                    manifest['critical_replay_quiesce'] = {'version':1}
                    manifest['spec']['critical_replay_quiesce'] = {'version':1}
                if mode == 'decision-receipt-capture-loss':
                    manifest['critical_replay_tolerance'] = 'terminal-prefix'
                    manifest['spec']['critical_replay_tolerance'] = 'terminal-prefix'
            if mode in ('probe-ready', 'probe-no-budget'):
                manifest['spec']['required_observations'] = [
                    'sdma_vm_program', 'vmid2_root_repair']
            path = vm/'prepared.json'; path.write_text(json.dumps(manifest))
            host = dict(self.host(), sleep_inhibited=True)
            if mode == 'gpu-less':
                manifest['gpu'] = False; path.write_text(json.dumps(manifest))
            now = [100.0]; calls = []
            lines = ['BUILD: identity=abc', 'HY: HWLibs hybrid trace route=ok entries-match=1',
                     'XJ:   waitForHwStamp(1) -> 1',
                     'HY: createHybridEngine enter: engine=1 available=1',
                     'HY: createHybridEngine exit: engine=1 valid=1 available-before=1 status=4',
                     'XJ: AMDHardware::startHWEngines -> 0']
            if mode in ('probe-ready', 'probe-no-budget',
                        'decision-receipt-ready', *quiesce_modes):
                lines = [
                    'BUILD: identity=abc',
                    'VM: route AMDGFX10VMM::prepareVMInvalidateRequest -> ok (org=0xffffff8000000000)',
                    'HY: HWLibs hybrid trace route=ok entries-match=1',
                    'XJ:   waitForHwStamp(1) -> 1',
                    'HY: createHybridEngine enter: engine=1 available=1',
                    'HY: createHybridEngine exit: engine=1 valid=1 available-before=1 status=0',
                    'XJ: AMDHardware::startHWEngines -> 1',
                    'XJ: AMDGraphicsAccelerator::powerUpHW -> 1',
                ]
            lines.extend(self.v2_critical_payloads(manifest['run_id']))
            serial = f'RGPU_RECORDS build=abc count={len(lines)} dropped=0 truncated=0\n'+''.join(
                f'RGPU_EVENT build=abc seq={i} {line}\n' for i,line in enumerate(lines))
            decision_prefix = None
            decision_ready_prefix = None
            if mode in decision_modes:
                lines[0] = 'BUILD: identity=' + CR2_BUILD
                lines.append('XH3 LIFETIME state=VALID exact')
                decision_prefix = (
                    f'RGPU_UART_READY v=1 b={CR2_BUILD} port=2\n' +
                    ''.join(snapshot_lines(lines, snapshot=1)))
                serial = ''
                if mode == 'decision-receipt-capture-loss':
                    corrupt = snapshot_lines(
                        ['BUILD: identity=' + CR2_BUILD], snapshot=0)
                    corrupt[0] = re.sub(r'c=[0-9a-f]{8}', 'c=deadbeef', corrupt[0])
                    decision_prefix = (
                        f'RGPU_UART_READY v=1 b={CR2_BUILD} port=2\n' +
                        ''.join(corrupt) + ''.join(snapshot_lines(lines, snapshot=1)))
                if mode in ('decision-receipt-ready', *quiesce_modes):
                    initial = ['BUILD: identity=' + CR2_BUILD]
                    decision_prefix = (
                        f'RGPU_UART_READY v=1 b={CR2_BUILD} port=2\n' +
                        ''.join(snapshot_lines(initial, snapshot=1)))
                    decision_ready_prefix = decision_prefix + ''.join(
                        snapshot_lines(lines, snapshot=2))
            def start(*args):
                calls.append('start'); (vm/'run/serial.log').write_text(serial)
                if mode in decision_modes:
                    (vm/'run/critical.log').write_text(decision_prefix)
                if mode == 'gpu-less': self.assertEqual(args[2], [])
                if mode == 'unconfirmed': raise StopUnconfirmed('pending service stop unknown')
                deadline = 160 if mode == 'probe-no-budget' else 280
                return dict(cid='c'*64, deadline_epoch=deadline, max_seconds=180)
            if mode == 'capture-loss': serial = serial.replace('dropped=0','dropped=1')
            class StopUnconfirmed(RuntimeError): pass
            def verify(state):
                if mode == 'cancel': raise KeyboardInterrupt()
                if mode == 'runtime-abort': raise RuntimeError('runtime observation failed')
            def shutdown(vm_path, state, expected_build, grace):
                if mode == 'shutdown-fault': calls.append('host-fault')
                if mode == 'decision-receipt-capture-loss':
                    tail = snapshot_lines(lines + ['shutdown-tail'], snapshot=2)[0]
                    with (vm/'run/critical.log').open('a') as stream:
                        stream.write(tail[:-17])
                if mode in quiesce_modes:
                    self.assertTrue((vm/'evidence/critical-quiesce.json').exists())
                    self.assertFalse(any((vm/'run').glob(
                        'critical-quiesce-*.request')))
                if mode == 'producer-quiesce-post-ack-tail':
                    with (vm/'run/critical.log').open('a') as stream:
                        stream.write('late producer bytes\r\n')
                calls.append(('guest-shutdown', state['cid'], expected_build))
                return dict(cid=state['cid'], outcome='forced')
            def kernel(cursor=None):
                faults = ['Hardware Error'] if 'host-fault' in calls else []
                return 'cursor', faults, faults
            class ImmediateMonitor:
                def __init__(self, cursor, interrupt, interval=1):
                    self.messages = []
                    self.error_kind = 'fault' if mode == 'monitor-fault' else 'capture'
                    self.error = ('new host kernel fault during exposure' if
                                  self.error_kind == 'fault' else
                                  'host kernel capture failed: journal unavailable')
                def start(self): pass
                def stop(self): pass
            supervisor = SimpleNamespace(start_locked=start, verify=verify,
                ManagedStopUnconfirmed=StopUnconfirmed,
                stop_exact=lambda cid:calls.append(('stop',cid)))
            guest_shutdown = SimpleNamespace(shutdown=shutdown)
            lease_evidence = object()
            def parse_v2_lease_records(records, prior):
                calls.append(('parse-v2', prior, tuple(records)))
                return lease_evidence
            def recover(vm_path, prior, *, lease_evidence=None,
                        recovery_helpers_sha256=None, recovery_lease_schema=None):
                self.assertIs(lease_evidence, globals_lease_evidence)
                self.assertEqual(recovery_helpers_sha256,
                                 manifest['recovery_helpers_sha256'])
                calls.append(('recover', prior))
                receipt = {'schema':2, 'status':'recovered', 'authorizes_launch':True,
                           'boot_id':'boot-A',
                           'prior_run_id':prior, 'recovery_id':'f'*32,
                           'device':'0000:7b:00.0', 'iommu_group':'31', 'driver':'vfio-pci',
                           'pci_command_before':3, 'pci_command_after':3,
                           'reset_methods_before':[], 'reset_methods_after':[],
                           'kernel_messages':[],
                           'gc_quiesce':{'status':'quiesced', 'active_after':0,
                                         'dequeue_timeouts':0, 'forced_inactive':0,
                                         'cp_stat_after':0, 'cp_cpc_busy_after':0,
                                         'cp_me_after':0x15000000,
                                         'cp_mec_after':0x50000000,
                                         'pq_wptr_poll_after':0,
                                         'pq_status_after':0,
                                         'doorbell_range_lower_after':0,
                                         'doorbell_range_upper_after':0,
                                         'sdma0_after':1,
                                         'sdma0_cntl_after':0,
                                         'sdma0_rb_after':0,
                                         'sdma0_ib_after':0,
                                         'gfx_ring_clean':True,
                                         'gfx_retirement_confirmed':True,
                                         'gfx_needs_unmap':False,
                                         'gfx_was_stale':False,
                                         'host_kiq':{'status':'not-needed'},
                                         'gfx_rb_active_after':0,
                                         'gfx_rb_doorbell_after':0,
                                         'gfx_rb_wptr_after':0,
                                         'gfx_rb_wptr_hi_after':0,
                                         'gfx_rb_base_after':0,
                                         'gfx_rb_base_hi_after':0,
                                         'gfx_rb_cntl_after':0},
                           'commands':[{'command':0x00030000, 'response':0x80030000,
                                        'confirmed':True},
                                       {'command':0x000c0000, 'response':0x800c0000,
                                        'confirmed':True}]}
                target = vm_path/'run/vfio-recovery/boot-A'; target.mkdir(parents=True, exist_ok=True)
                (target/(prior+'.json')).write_text(json.dumps(receipt))
                return receipt
            globals_lease_evidence = lease_evidence
            recovery = SimpleNamespace(
                recover=recover, parse_v2_lease_records=parse_v2_lease_records)
            def probe(vm_path, prepared):
                calls.append('probe')
                if mode in quiesce_modes:
                    metal = {
                        'run_id':prepared['run_id'], 'passed':True, 'metal3':True,
                        'device':'AMD Radeon Navi23', 'registry_id':1,
                        'compute_rounds':3, 'compute_values_checked':196608,
                        'render_pixels_checked':4096,
                        'completed_command_buffers':4,
                    }
                    return {'run_id':prepared['run_id'],
                            'output':('RGPU_METAL_RESULT '+json.dumps(metal)+'\n' +
                                      'RGPU_EXIT '+prepared['run_id']+' 0\n')}
                return {'run_id':prepared['run_id'],
                        'output':'RGPU_EXIT '+prepared['run_id']+' 1\n'}
            original_helper = tool.helper
            def helpers(name):
                if name == 'vm-supervision': return supervisor
                if name == 'guest-shutdown': return guest_shutdown
                if name == 'vfio-recover': return recovery
                return original_helper(name)
            actual = dict(image_id='wrong' if mode == 'wrong-image' else 'sha256:expected',
                          vfio_args=['vfio-pci,host=0000:7b:00.0'])
            if mode in decision_modes:
                actual['serial_args'] = [
                    'socket,id=rgpu_console,path=/run/vm/serial.sock,server=on,wait=off',
                    'isa-serial,chardev=rgpu_console,index=0',
                    'socket,id=rgpu_critical,path=/run/vm/critical.sock,server=on,wait=off',
                    'isa-serial,chardev=rgpu_critical,index=1']
            if mode == 'gpu-less': actual['vfio_args'] = []
            monitor_type = ImmediateMonitor if mode in ('monitor-capture', 'monitor-fault') \
                else tool.HostMonitor
            original_parse_manifest_serial = tool.parse_manifest_serial
            def parse_manifest_serial(classifier, prepared, captured):
                if mode == 'capture-pending-timeout':
                    return [{'kind':'capture_loss', 'build':prepared['build_id'],
                             'reason':'CR2: CR2 snapshot has a missing chunk',
                             'definitive':False}]
                return original_parse_manifest_serial(classifier, prepared, captured)
            quiesce_written = [False]
            def advance(seconds):
                request = vm/'run'/('critical-quiesce-'+'c'*64+'.request')
                if mode in quiesce_modes and request.exists():
                    if not quiesce_written[0]:
                        final = ''.join(snapshot_lines(lines, snapshot=3))
                        ack = (f'RGPU_UART_QUIESCED v=1 b={CR2_BUILD} '
                               f's=00000003 count={len(lines):04x}\r\n')
                        with (vm/'run/critical.log').open('a') as stream:
                            stream.write(final+ack)
                        quiesce_written[0] = True
                elif mode in ('decision-receipt-ready', *quiesce_modes) and \
                        decision_ready_prefix is not None:
                    (vm/'run/critical.log').write_text(decision_ready_prefix)
                now[0] += seconds
            with patch.object(tool, 'current_identity', return_value=manifest), \
                 patch.object(tool, 'host_snapshot', return_value=host), \
                 patch.object(tool, 'helper', side_effect=helpers), \
                 patch.object(tool, 'running_identity', return_value=actual), \
                 patch.object(tool, 'kernel_updates', side_effect=kernel), \
                 patch.object(tool, 'HostMonitor', monitor_type), \
                 patch.object(tool, 'run_probe', side_effect=probe), \
                 patch.object(tool, 'parse_manifest_serial',
                              side_effect=parse_manifest_serial), \
                 patch.object(tool.time, 'time', side_effect=lambda:now[0]), \
                 patch.object(tool.time, 'sleep', side_effect=advance):
                out = vm/'evidence'
                result = tool.run_one(vm, path, out)
                self.assertEqual(calls.count('start'), 1)
                if mode != 'gpu-less':
                    self.assertFalse((out/'recovery-reservation.json').exists())
                if mode == 'hybrid':
                    self.assertEqual(result['verdict'], 'HYBRID_QUEUE_SUSPECTED')
                    self.assertIn(('guest-shutdown','c'*64, 'fixture'), calls)
                elif mode == 'gpu-less':
                    self.assertEqual(result['verdict'], 'GPULESS_CAPTURE_CHECK')
                    self.assertFalse((vm/'run/used-gpu-boots/boot-A.json').exists())
                    return
                elif mode == 'unconfirmed':
                    self.assertEqual(result['verdict'], 'STOP_UNCONFIRMED')
                elif mode == 'shutdown-fault':
                    self.assertEqual(result['verdict'], 'INVALID')
                    self.assertIn('host kernel fault', result['error'])
                    self.assertNotIn(('recover', 'a'*32), calls)
                elif mode == 'monitor-capture':
                    self.assertEqual(result['verdict'], 'INVALID')
                    self.assertIn('capture failed', result['error'])
                    self.assertIn(('guest-shutdown','c'*64, 'fixture'), calls)
                    self.assertNotIn(('stop','c'*64), calls)
                    self.assertNotIn(('recover', 'a'*32), calls)
                elif mode == 'monitor-fault':
                    self.assertEqual(result['verdict'], 'INVALID')
                    self.assertIn('host kernel fault', result['error'])
                    self.assertIn(('stop','c'*64), calls)
                    self.assertNotIn(('guest-shutdown','c'*64, 'fixture'), calls)
                    self.assertNotIn(('recover', 'a'*32), calls)
                elif mode == 'wrong-image':
                    self.assertEqual(result['verdict'], 'INVALID')
                    self.assertIn(('stop','c'*64), calls)
                    self.assertNotIn(('guest-shutdown','c'*64, 'fixture'), calls)
                elif mode == 'capture-pending-timeout':
                    self.assertEqual(result['verdict'], 'INVALID')
                    self.assertIn('critical capture remained incomplete',
                                  result['termination_reason'])
                    self.assertEqual(result['termination_reason'], result['error'])
                    self.assertEqual(calls.count('probe'), 0)
                    self.assertGreaterEqual(now[0], 255)
                elif mode in ('probe-ready', 'probe-no-budget'):
                    self.assertEqual(result['verdict'], 'INCONCLUSIVE')
                    self.assertEqual(result['earliest_failure'],
                                     'sdma_vm_program_missing')
                    self.assertEqual(calls.count('probe'),
                                     1 if mode == 'probe-ready' else 0)
                    self.assertEqual((out/'probe.json').exists(),
                                     mode == 'probe-ready')
                elif mode == 'decision-receipt-capture-loss':
                    receipt = json.loads((out/'first-decision.json').read_text())
                    self.assertEqual(receipt['schema'], 1)
                    self.assertEqual(receipt['build_id'], CR2_BUILD)
                    self.assertEqual(receipt['run_id'], 'a'*32)
                    self.assertEqual(receipt['cid'], 'c'*64)
                    self.assertEqual(receipt['decision_time_epoch'], 102.0)
                    self.assertEqual(receipt['readiness'], {
                        'verdict':'HYBRID_QUEUE_SUSPECTED', 'stage':'hybrid'})
                    self.assertEqual(receipt['shutdown'], {
                        'action':'guest_shutdown',
                        'reason':'decisive_readiness_refusal'})
                    self.assertEqual(receipt['capture_acceptance'],
                                     'terminal-prefix')
                    self.assertEqual(receipt['snapshot'], 1)
                    self.assertEqual(receipt['record_count'], len(lines))
                    self.assertEqual(receipt['capture_prefixes']['serial'], {
                        'file':'first-decision-serial.txt', 'byte_length':0,
                        'sha256':hashlib.sha256(b'').hexdigest()})
                    critical_bytes = decision_prefix.encode()
                    self.assertEqual(receipt['capture_prefixes']['critical'], {
                        'file':'first-decision-critical.txt',
                        'byte_length':len(critical_bytes),
                        'sha256':hashlib.sha256(critical_bytes).hexdigest()})
                    self.assertEqual((out/'first-decision-critical.txt').read_bytes(),
                                     critical_bytes)
                    self.assertEqual((out/'first-decision-serial.txt').read_bytes(),
                                     b'')
                    self.assertEqual(result['first_decisive_readiness'], receipt)
                    final_events = [json.loads(row) for row in
                                    (out/'events.jsonl').read_text().splitlines()]
                    self.assertTrue(any(row['kind'] == 'capture_loss'
                                        for row in final_events))
                    self.assertEqual(result['verdict'], 'INCONCLUSIVE')
                    self.assertEqual(result['earliest_failure'],
                                     'identity_or_route_missing')
                    self.assertIn('capture_loss', result['evidence'])
                    self.assertEqual(calls.count('probe'), 0)
                    self.assertNotIn(result['verdict'],
                                     ('CORE_PROBE_PASS', 'FULL_FUNCTION_PASS'))
                elif mode == 'decision-receipt-ready':
                    self.assertFalse((out/'first-decision.json').exists())
                    self.assertNotIn('first_decisive_readiness', result)
                    self.assertEqual(calls.count('probe'), 1, (result, calls))
                elif mode == 'producer-quiesce-ready':
                    self.assertEqual(result['verdict'], 'CORE_PROBE_PASS')
                    self.assertTrue(result['valid'])
                    receipt = result['critical_producer_quiesce']
                    self.assertEqual((receipt['snapshot'], receipt['record_count']),
                                     (3, len(lines)))
                    self.assertEqual(calls.count('probe'), 1)
                    raw = (out/'critical.txt').read_text()
                    self.assertTrue(raw.endswith('count='+f'{len(lines):04x}'+'\n'))
                    self.assertNotIn('capture_loss', result['evidence'])
                elif mode == 'producer-quiesce-post-ack-tail':
                    self.assertEqual(result['verdict'], 'INVALID')
                    self.assertIn('changed after producer quiesce ACK', result['error'])
                    self.assertEqual(calls.count('probe'), 1)
                else:
                    self.assertEqual(result['verdict'], 'INVALID')
                    self.assertIn(('guest-shutdown','c'*64, 'fixture'), calls)
                    self.assertNotIn(('stop','c'*64), calls)
                if mode == 'unconfirmed':
                    self.assertNotIn(('recover', 'a'*32), calls)
                elif mode not in ('shutdown-fault', 'monitor-capture', 'monitor-fault',
                                  'capture-loss', 'decision-receipt-capture-loss'):
                    self.assertIn(('recover', 'a'*32), calls)
                if mode == 'capture-loss': self.assertLess(now[0], 110)
                if mode == 'capture-loss':
                    self.assertEqual(result['termination_reason'], result['error'])
                    self.assertIn('definitive critical capture loss',
                                  result['termination_reason'])
                    self.assertIn('functional_boundary', result)
                self.assertTrue((out/'verdict.json').exists())
                self.assertTrue((vm/'run/used-gpu-boots/boot-A.json').exists())
                second = tool.run_one(vm,path,vm/'second')
                self.assertEqual(second['verdict'], 'INVALID')
                self.assertEqual(calls.count('start'), 1)



class ReserveBootSchemaSixReceiptTest(unittest.TestCase):
    def test_schema6_reservation_validates_with_manifest_helper_hashes(self):
        import tempfile
        path = ROOT / 'tools/experiment.py'
        spec = importlib.util.spec_from_file_location('experiment_reserve_schema6', path)
        experiment = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(experiment)
        seen = []
        original = experiment.validate_recovery_receipt_v6
        def recorder(receipt, boot_id, prior_run_id, helper_hashes=None):
            seen.append((boot_id, prior_run_id, helper_hashes))
            return [] if helper_hashes == {'vfio-recover.py': 'a' * 64} else ['recovery_receipt']
        experiment.validate_recovery_receipt_v6 = recorder
        try:
            with tempfile.TemporaryDirectory() as tmp:
                used = Path(tmp) / 'run' / 'used-gpu-boots'
                used.mkdir(parents=True)
                boot = 'b00700000000'
                prior = 'c' * 32
                (used / (boot + '.json')).write_text(json.dumps(
                    {'schema': 2, 'boot_id': boot, 'max_launches': 3,
                     'launches': [{'run_id': prior, 'reserved_epoch': 1.0}]}))
                receipt = {'schema': 6, 'status': 'recovered', 'authorizes_launch': True,
                           'recovery_id': 'd' * 32, 'prior_run_id': prior, 'boot_id': boot}
                manifest = {'recovery_lease_schema': 3,
                            'recovery_helpers_sha256': {'vfio-recover.py': 'a' * 64}}
                experiment.reserve_boot(used, boot, 'e' * 32, receipt, manifest,
                                        Path(tmp) / 'manifest.json')
                ledger = json.loads((used / (boot + '.json')).read_text())
        finally:
            experiment.validate_recovery_receipt_v6 = original
        self.assertEqual(seen, [(boot, prior, {'vfio-recover.py': 'a' * 64})])
        self.assertEqual(ledger['launches'][-1]['run_id'], 'e' * 32)
        self.assertEqual(ledger['launches'][-1]['recovery_id'], 'd' * 32)

if __name__ == '__main__': unittest.main()
