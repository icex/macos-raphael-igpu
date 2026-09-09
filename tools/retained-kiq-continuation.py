#!/usr/bin/env python3
"""Seal one exact candidate-176 continuation after the retained KIQ cleanup."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]


def _helper(name):
    path = Path(__file__).with_name(name + '.py')
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


OBSERVER = _helper('inspect-retained-kiq')
RECOVERY = OBSERVER.RECOVERY

BOOT_ID = '5d6f45d0-4384-4340-b819-7751bc26ebb3'
FIRST_RUN_ID = 'e583a1b2d97a4ad3b607c1d20a29a812'
PRIOR_RUN_ID = '1a065e4f5f674cc0a26d4e9dbdf59649'
HISTORICAL_RECOVERY_ID = 'e503b2ca63db4e11a21494d1841dca24'
STARTUP_RECOVERY_ID = '70463a1f1b3e4dc4899a175e64103df8'
STARTUP_ATTEMPT_ID = 'f11105d537dd4ff097476de97a7620a4'
LEDGER_SHA256 = '69b8e1464a6866d3da2518e5db7222b0d557e0eb7f3ac3c27ebffbec139b9d15'
SPEC_SHA256 = '2a30ec87b0d6bfeed52088401d666c2fee3e3a11b8f44905493d5ed3981f33cf'
EVIDENCE = {
    'recovery': {
        'path':'run/metal-008-175-bar0/recovery.json',
        'sha256':'117d2d4cea6b007c49fc797af7c64ef78bfeb4da8acebaa245abd945372e3e4d'},
    'receipt': {
        'path':f'run/vfio-recovery/{BOOT_ID}/{PRIOR_RUN_ID}.json',
        'sha256':'9cf80653e198faa09c6f4da456e8495e07a045015c6ac0b64a7561ffbfc85fc7'},
    'observation': {
        'path':f'run/retained-kiq-inspections/{BOOT_ID}-{PRIOR_RUN_ID}.json',
        'sha256':'f0282d7b51ad2a6f962c03c0bb467c9e5058784a0055a427697bbb4e31eee4f8'},
    'idle': {
        'path':f'run/retained-idle-inspections/{BOOT_ID}-{PRIOR_RUN_ID}.json',
        'sha256':'589278713643fc52db7f5a0a8ef7f4f5bab0a8e38aec5a209fa27b8ff9ffe42d'},
    'preparation': {
        'path':f'run/retained-kiq-preparations/{BOOT_ID}-{PRIOR_RUN_ID}.json',
        'sha256':'99bb203ee46b24c1adf55c38366dadbaa238776508cf9d1d46842e125ebbd8ea'},
    'doorbell_zero': {
        'path':f'run/retained-kiq-doorbell-zero/{BOOT_ID}-{PRIOR_RUN_ID}.json',
        'sha256':'3ac3511b9b302c873b2b205be45b9b4135703844506f971a766923f4fb096b2e'},
    'global_close': {
        'path':f'run/retained-kiq-global-doorbell-closures/{BOOT_ID}-{PRIOR_RUN_ID}.json',
        'sha256':'173c020e378c74dbb647adcca15e4ebe26e146a694351ac8bbb3d28c8f684756'},
}
FIXED_CONTRACT = {
    'boot_id':BOOT_ID, 'first_run_id':FIRST_RUN_ID,
    'prior_run_id':PRIOR_RUN_ID,
    'historical_recovery_id':HISTORICAL_RECOVERY_ID,
    'startup_recovery_id':STARTUP_RECOVERY_ID,
    'startup_attempt_id':STARTUP_ATTEMPT_ID,
    'ledger_sha256':LEDGER_SHA256, 'spec_sha256':SPEC_SHA256,
    'evidence':EVIDENCE,
}
SOURCE_PATHS = (
    'tools/retained-kiq-continuation.py',
    'tools/experiment.py',
    'tools/vfio-recover.py',
    'tools/kiq-recovery-proof.py',
    'tools/inspect-retained-kiq.py',
    'tools/inspect-retained-idle.py',
    'tools/prepare-retained-kiq.py',
    'tools/retained-kiq-doorbell-zero.py',
    'tools/close-retained-kiq-global-doorbell.py',
    'src/RaphaelGPU.cpp',
    'src/KiqQueuePreparation.hpp',
    'experiments/metal-009.json',
)
COMPUTE_SELECTORS = tuple(
    RECOVERY.queue_selector(me, pipe, queue)
    for me in (1, 2) for pipe in range(4) for queue in range(8))
MQD_STATUS_WRITEBACK = (
    (86, 318496812), (87, 262), (90, 318496800),
    (91, 262), (93, 256), (94, 256),
)


class ContinuationError(RuntimeError):
    pass


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def source_hashes(root=ROOT):
    root = Path(root)
    return {relative:_sha256((root/relative).read_bytes())
            for relative in SOURCE_PATHS}


def _read_json(path):
    raw = Path(path).read_bytes()
    return raw, json.loads(raw)


def _false_authority(value):
    return (isinstance(value, dict) and
            value.get('authorizes_launch') is False and
            value.get('authorizes_recovery') is False and
            value.get('authorizes_cleanup') is False)


def _scan_errors(scan, expected_pq):
    errors = []
    def dword(value):
        return type(value) is int and 0 <= value < 0xffffffff
    if (not isinstance(scan, dict) or len(scan.get('passes', [])) != 2 or
            scan['passes'][0] != scan['passes'][1] or
            scan.get('final_default') != {
                'attempted':True, 'completed':True, 'value':0} or
            len(scan.get('selector_writes', [])) != 137 or
            any(row.get('completed') is not True
                for row in scan.get('selector_writes', []))):
        return ['final stopped scan shape']
    for observed in scan['passes']:
        globals_ = observed.get('globals', {})
        exact_global_dwords = ('cp_stat', 'cpc_busy', 'pq_wptr_poll_cntl',
                               'pq_status', 'doorbell_range_lower',
                               'doorbell_range_upper')
        if (any(not dword(globals_.get(key)) for key in exact_global_dwords) or
                globals_.get('cp_stat') != 0 or globals_.get('cpc_busy') != 0 or
                not dword(globals_.get('me_cntl')) or
                globals_['me_cntl'] & RECOVERY.CP_ME_HALT_MASK !=
                RECOVERY.CP_ME_HALT_MASK or
                not dword(globals_.get('mec_cntl')) or
                globals_['mec_cntl'] & RECOVERY.CP_MEC_HALT_MASK !=
                RECOVERY.CP_MEC_HALT_MASK or
                globals_.get('pq_wptr_poll_cntl') != 0 or
                globals_.get('pq_status') != expected_pq or
                globals_.get('doorbell_range_lower') != 0 or
                globals_.get('doorbell_range_upper') != 0):
            errors.append('final CP/ingress state')
        sdma_keys = ('sdma0_gfx_rb_cntl', 'sdma0_gfx_ib_cntl',
                     'sdma0_page_rb_cntl', 'sdma0_page_ib_cntl',
                     'sdma0_rlc0_rb_cntl', 'sdma0_rlc0_ib_cntl',
                     'sdma0_rlc1_rb_cntl', 'sdma0_rlc1_ib_cntl')
        if (not dword(globals_.get('sdma0_f32_cntl')) or
                globals_['sdma0_f32_cntl'] & RECOVERY.SDMA_HALT_MASK !=
                RECOVERY.SDMA_HALT_MASK or
                not dword(globals_.get('sdma0_status')) or
                not globals_['sdma0_status'] & 1 or
                not dword(globals_.get('sdma0_cntl')) or
                globals_['sdma0_cntl'] & RECOVERY.SDMA_AUTO_CTXSW_ENABLE_MASK or
                any(not dword(globals_.get(key)) or globals_[key] & 1
                    for key in sdma_keys)):
            errors.append('final SDMA state')
        compute = observed.get('compute')
        if (not isinstance(compute, list) or len(compute) != 64 or
                [row.get('selector') for row in compute] != list(COMPUTE_SELECTORS) or
                any(not dword(row.get('active')) or
                    not dword(row.get('pq_doorbell_control')) or
                    row.get('active') != 0 or
                    row.get('pq_doorbell_control') not in (0, 0x80000000)
                    for row in compute)):
            errors.append('final compute state')
        else:
            target = compute[COMPUTE_SELECTORS.index(RECOVERY.HOST_KIQ_SELECTOR)]
            if target.get('host_kiq') != {
                    'dequeue':0, 'rptr':0, 'wptr_lo':0, 'wptr_hi':0}:
                errors.append('final selector 9 state')
        graphics = observed.get('graphics', {})
        pipes = graphics.get('pipes') if isinstance(graphics, dict) else None
        if (not isinstance(pipes, list) or len(pipes) != 2 or
                [row.get('selector') for row in pipes] != [0, 1] or
                any(any(not dword(row.get(key)) for key in
                        ('active','doorbell_status','wptr','wptr_hi')) or
                    row.get('active') != 0 or row.get('doorbell_status') != 0 or
                    row.get('wptr') != 0 or row.get('wptr_hi') != 0
                    for row in pipes) or
                graphics.get('final_default') != {
                    'completed':True, 'value':0}):
            errors.append('final graphics state')
    return sorted(set(errors))


def _mqd_writeback_errors(observation):
    try:
        device = observation['device']; analysis = device['analysis']
        sequence = analysis['sequence']
        if (analysis.get('ring_exact') is not True or
                analysis.get('mqd_exact') is not False or
                analysis.get('stored_wptr') != 0x100 or
                analysis.get('stored_wptr_expected') != 0x100 or
                analysis.get('current_report') != 0x100 or
                analysis.get('current_fence') != sequence or
                analysis.get('fence_matches_sequence') is not True):
            return ['retained completion analysis']
        _, expected = OBSERVER.expected_images(sequence)
        row = next(row for row in device['ranges'] if row.get('name') == 'mqd')
        if len(row.get('passes', [])) != 2:
            return ['retained MQD passes']
        images = [bytes.fromhex(value['data_hex']) for value in row['passes']]
        if images[0] != images[1] or len(images[0]) != len(expected):
            return ['retained MQD stability']
        differences = []
        for offset in range(0, len(expected), 4):
            before = int.from_bytes(expected[offset:offset+4], 'little')
            after = int.from_bytes(images[0][offset:offset+4], 'little')
            if before != after:
                differences.append((offset//4, after))
        if tuple(differences) != MQD_STATUS_WRITEBACK:
            return ['retained MQD writeback']
    except (KeyError, TypeError, ValueError, StopIteration):
        return ['retained MQD evidence']
    return []


def evidence_errors(values, contract=FIXED_CONTRACT):
    errors = []
    boot, prior = contract['boot_id'], contract['prior_run_id']
    recovery = values.get('recovery', {})
    receipt = values.get('receipt', {})
    identity = (5, 'incomplete', False, boot, prior,
                contract['historical_recovery_id'])
    for name, value in (('recovery', recovery), ('receipt', receipt)):
        got = (value.get('schema'), value.get('status'),
               value.get('authorizes_launch'), value.get('boot_id'),
               value.get('prior_run_id'), value.get('recovery_id'))
        if got != identity:
            errors.append('historical ' + name)
    if recovery != receipt:
        errors.append('historical receipt equality')
    try:
        commands = recovery['commands']
        if ([row.get('command') for row in commands] != [0x30000, 0xc0000] or
                any(row.get('confirmed') is not True or
                    type(row.get('response')) is not int or
                    row['response'] & 0x8000ffff != 0x80000000 or
                    (row['response'] >> 16) & 0x7fff != row['command'] >> 16
                    for row in commands)):
            errors.append('historical PSP acknowledgements')
        gc = recovery['gc_quiesce']
        pipes = gc['graphics_pipes_after_retirement']['pipes']
        if (gc.get('status') != 'quiesced' or gc.get('gfx_needs_unmap') is not True or
                gc.get('gfx_retirement_confirmed') is not False or
                len(pipes) != 2 or pipes[0].get('active') != 0 or
                pipes[0].get('doorbell_status') != 0):
            errors.append('historical pre-scrub graphics state')
    except (KeyError, TypeError):
        errors.append('historical recovery proof')
    observation = values.get('observation', {})
    if (not _false_authority(observation) or
            (observation.get('schema'), observation.get('kind'),
             observation.get('status'), observation.get('boot_id'),
             observation.get('run_id')) !=
            (1, 'retained-host-kiq-observation', 'observed', boot, prior)):
        errors.append('retained observation identity')
    errors.extend(_mqd_writeback_errors(observation))
    for name, status in (('idle', 'failed'), ('preparation', 'failed'),
                         ('doorbell_zero', 'failed')):
        value = values.get(name, {})
        if (not _false_authority(value) or value.get('schema') != 1 or
                value.get('status') != status or value.get('boot_id') != boot or
                value.get('run_id') != prior):
            errors.append(name + ' identity')
    try:
        writes = values['preparation']['transaction']['writes']
        if ([(row.get('offset'), row.get('before'), row.get('value'),
              row.get('posted'), row.get('completed')) for row in writes] != [
                (0x4d08, 0x101, 0x100, 0x100, True),
                (0x4ce0, 0x80840021, 0x80840020, 0x80840020, True),
                (0xc8fc, 0x100, 0, 0x100, False)]):
            errors.append('PAGE/ignored-WPTR transaction')
        doorbell = values['doorbell_zero']['transaction']
        if (doorbell['doorbell_writes'] != [{
                'attempted':True, 'barrier':0x200, 'completed':True,
                'index':0, 'offset':0, 'sequence':0, 'store_completed':True,
                'value':0, 'width_bits':64}] or
                not doorbell.get('interim_samples') or
                doorbell['interim_samples'][-1] != {
                    'active':0, 'mec_cntl':RECOVERY.CP_MEC_HALT_MASK,
                    'wptr_hi':0, 'wptr_lo':0}):
            errors.append('stopped doorbell WPTR transaction')
    except (KeyError, TypeError):
        errors.append('retained preparation transaction')
    close = values.get('global_close', {})
    if (not _false_authority(close) or
            (close.get('schema'), close.get('kind'), close.get('status'),
             close.get('boot_id'), close.get('run_id')) !=
            (1, 'retained-kiq-global-doorbell-close',
             'completed-nonauthorizing', boot, prior)):
        errors.append('global close identity')
    try:
        transaction = close['transaction']
        if (not _false_authority(transaction) or
                transaction.get('status') !=
                'global-doorbell-gate-closed-nonauthorizing' or
                transaction.get('writes') != [{
                    'attempted':True, 'before':3, 'completed':True,
                    'observed_before':3, 'offset':RECOVERY.CP_PQ_STATUS_OFFSET,
                    'posted':1, 'sequence':0, 'store_completed':True, 'value':1}]):
            errors.append('global close transaction')
        errors.extend(_scan_errors(transaction.get('after'), 1))
    except (KeyError, TypeError):
        errors.append('global close proof')
    return sorted(set(errors))


def _ledger_errors(ledger, contract):
    expected = {
        'schema':2, 'boot_id':contract['boot_id'], 'max_launches':3,
        'launches':[
            {'run_id':contract['first_run_id']},
            {'run_id':contract['prior_run_id'],
             'prior_run_id':contract['first_run_id'],
             'recovery_id':contract['startup_recovery_id'],
             'attempt_id':contract['startup_attempt_id']}],
    }
    # Timestamps are evidence but not authorization semantics.
    if not isinstance(ledger, dict):
        return ['exact two-entry ledger']
    comparable = json.loads(json.dumps(ledger))
    for row in comparable.get('launches', []):
        row.pop('reserved_epoch', None)
    return [] if comparable == expected else ['exact two-entry ledger']


def _manifest_errors(manifest, raw, seal, contract):
    errors = []
    if not isinstance(manifest, dict):
        return ['candidate176 manifest policy']
    identity = ('build_id', 'source_commit', 'source_sha256', 'binary_sha256',
                'info_sha256', 'bootdisk_sha256')
    if (seal.get('manifest_sha256') != _sha256(raw) or
            seal.get('next_run_id') != manifest.get('run_id') or
            any(seal.get(key) != manifest.get(key) for key in identity)):
        errors.append('sealed manifest identity')
    if (manifest.get('boot_id') != contract['boot_id'] or
            manifest.get('candidate_directory') != 'run/candidate-176' or
            manifest.get('max_seconds') != 180 or manifest.get('gpu') is not True or
            manifest.get('source_clean') is not True or
            manifest.get('built_from_commit') != manifest.get('source_commit') or
            not re.fullmatch(r'[0-9a-f]{32}', str(manifest.get('run_id', ''))) or
            not re.fullmatch(r'[0-9a-f]{32}', str(manifest.get('build_id', ''))) or
            not re.fullmatch(r'[0-9a-f]{40}', str(manifest.get('source_commit', '')))):
        errors.append('candidate176 manifest policy')
    spec = manifest.get('spec')
    if (not isinstance(spec, dict) or spec.get('id') != 'metal-009' or
            spec.get('candidate_version') != '1.0.176' or
            spec.get('requested_diagnostic') != 'rgpuvmroot=1' or
            spec.get('max_seconds') != 180 or
            spec.get('run_probe_only_after_native_start') is not True or
            'same_boot_candidate176_one_use_authorization' not in
                spec.get('prerequisites', [])):
        errors.append('candidate176 experiment policy')
    return errors


def contract_errors(contract, seal):
    if not isinstance(seal, dict):
        return ['candidate seal is not configured']
    exact_keys = {
        'schema','kind','approved_for_one_launch','boot_id','prior_run_id',
        'next_run_id','target_version','manifest_path','manifest_sha256',
        'build_id','source_commit','source_sha256','binary_sha256','info_sha256',
        'bootdisk_sha256','ledger_sha256','evidence_sha256','source_hashes'}
    errors = []
    if (set(seal) != exact_keys or seal.get('schema') != 1 or
            seal.get('kind') != 'reviewed-candidate176-retained-kiq-seal' or
            seal.get('approved_for_one_launch') is not True or
            seal.get('boot_id') != contract['boot_id'] or
            seal.get('prior_run_id') != contract['prior_run_id'] or
            seal.get('target_version') != '1.0.176' or
            seal.get('manifest_path') != 'run/metal-009-176-manifest.json' or
            seal.get('ledger_sha256') != contract['ledger_sha256'] or
            seal.get('evidence_sha256') != {
                name:row['sha256'] for name,row in contract['evidence'].items()} or
            not isinstance(seal.get('source_hashes'), dict) or
            set(seal['source_hashes']) != set(SOURCE_PATHS)):
        errors.append('candidate seal contract')
    return errors


def collect_fresh_host(journal_cursor=None):
    host = OBSERVER.collect_host()
    cursor, messages, faults = RECOVERY.kernel_updates(journal_cursor)
    host.update(journal_cursor=cursor, journal_messages=messages,
                journal_faults=faults)
    return host


def test_host_fixture(boot_id=BOOT_ID):
    return {
        'boot_id':boot_id, 'active_vm':False, 'driver':'vfio-pci',
        'device':RECOVERY.DEVICE_ID, 'iommu_group':RECOVERY.GROUP,
        'pci_command':3, 'reset_methods':[],
        'canonical_device':OBSERVER.CANONICAL_DEVICE,
        'power_control':'on', 'power_state':'D0', 'runtime_status':'active',
        'enable_count':'0', 'sleep_inhibited':True,
        'watchdogs':{'watchdog':'1', 'nmi_watchdog':'1', 'hardlockup_panic':'1'},
        'residual_units':[], 'siblings':OBSERVER.EXPECTED_SIBLINGS,
        'reset_domain':OBSERVER.EXPECTED_RESET_DOMAIN,
        'kernel_release':OBSERVER.KERNEL_RELEASE,
        'vfio_module_sha256':OBSERVER.VFIO_MODULE_SHA256,
        'vfio_module_build_id':OBSERVER.VFIO_MODULE_BUILD_ID,
        'journal_cursor':'cursor', 'journal_messages':[], 'journal_faults':[],
    }


def host_errors(host, boot_id, prefix='fresh host '):
    if not isinstance(host, dict):
        return [prefix + 'proof']
    errors = [prefix + error for error in RECOVERY.validate_host_state(host, boot_id)]
    if host.get('pci_command') != 3: errors.append(prefix + 'PCI command')
    if host.get('canonical_device') != OBSERVER.CANONICAL_DEVICE:
        errors.append(prefix + 'canonical device')
    if ((host.get('power_control'), host.get('power_state'),
         host.get('runtime_status'), host.get('enable_count')) !=
            ('on', 'D0', 'active', '0')):
        errors.append(prefix + 'power state')
    if host.get('sleep_inhibited') is not True:
        errors.append(prefix + 'sleep inhibitor')
    if host.get('watchdogs') != {
            'watchdog':'1', 'nmi_watchdog':'1', 'hardlockup_panic':'1'}:
        errors.append(prefix + 'watchdogs')
    if host.get('residual_units') != []:
        errors.append(prefix + 'residual launch units')
    if host.get('siblings') != OBSERVER.EXPECTED_SIBLINGS:
        errors.append(prefix + 'reset-domain siblings')
    if host.get('reset_domain') != OBSERVER.EXPECTED_RESET_DOMAIN:
        errors.append(prefix + 'reset-domain identity')
    if (host.get('kernel_release') != OBSERVER.KERNEL_RELEASE or
            host.get('vfio_module_sha256') != OBSERVER.VFIO_MODULE_SHA256 or
            host.get('vfio_module_build_id') != OBSERVER.VFIO_MODULE_BUILD_ID):
        errors.append(prefix + 'VFIO module identity')
    if host.get('journal_faults') != []:
        errors.append(prefix + 'journal faults')
    messages = host.get('journal_messages')
    if not isinstance(messages, list) or any(re.search(
            rf'(?:{re.escape(RECOVERY.DEVICE)}[^\n]*\breset|\breset[^\n]*'
            rf'{re.escape(RECOVERY.DEVICE)}|vfio[^\n]*\breset)',
            str(message), re.I) for message in messages):
        errors.append(prefix + 'implicit reset messages')
    if not isinstance(host.get('journal_cursor'), str) or not host['journal_cursor']:
        errors.append(prefix + 'journal cursor')
    return sorted(set(errors))


def _context(vm, manifest_path, seal_path, expected_tool_source_sha256,
             contract=FIXED_CONTRACT, source_root=ROOT,
             loaded_source_sha256=None, host_reader=collect_fresh_host):
    vm, manifest_path, seal_path = map(Path, (vm, manifest_path, seal_path))
    errors = []
    expected_manifest = vm/'run/metal-009-176-manifest.json'
    expected_seal = vm/'run/retained-kiq-continuation-seal.json'
    if manifest_path.resolve() != expected_manifest.resolve():
        errors.append('canonical candidate176 manifest path')
    if seal_path.resolve() != expected_seal.resolve():
        errors.append('canonical candidate176 seal path')
    try:
        seal_raw, seal = _read_json(seal_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        seal_raw, seal = b'', None
        errors.append('candidate seal read')
    errors.extend(contract_errors(contract, seal))
    try:
        manifest_raw, manifest = _read_json(manifest_path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        manifest_raw, manifest = b'', {}
        errors.append('candidate manifest read')
    if isinstance(seal, dict):
        errors.extend(_manifest_errors(manifest, manifest_raw, seal, contract))
    try:
        spec_raw = (Path(source_root)/'experiments/metal-009.json').read_bytes()
        if (_sha256(spec_raw) != contract['spec_sha256'] or
                json.loads(spec_raw) != manifest.get('spec')):
            errors.append('exact candidate176 spec')
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        errors.append('candidate176 spec read')
    ledger_path = vm/'run/used-gpu-boots'/(contract['boot_id']+'.json')
    try:
        ledger_raw, ledger = _read_json(ledger_path)
        if _sha256(ledger_raw) != contract['ledger_sha256']:
            errors.append('exact ledger bytes')
        errors.extend(_ledger_errors(ledger, contract))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        ledger_raw, ledger = b'', {}
        errors.append('ledger read')
    values = {}
    for name, row in contract['evidence'].items():
        try:
            raw, value = _read_json(vm/row['path'])
            if _sha256(raw) != row['sha256']:
                errors.append('evidence hash ' + name)
            values[name] = value
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            errors.append('evidence read ' + name)
    if set(values) == set(contract['evidence']):
        errors.extend(evidence_errors(values, contract))
    try:
        current_sources = source_hashes(source_root)
        if not isinstance(seal, dict) or seal.get('source_hashes') != current_sources:
            errors.append('sealed source hashes')
    except OSError:
        current_sources = {}
        errors.append('source hash read')
    if loaded_source_sha256 is None:
        loaded_source_sha256 = _sha256(Path(__file__).read_bytes())
    current_tool = current_sources.get('tools/retained-kiq-continuation.py')
    if (expected_tool_source_sha256 != loaded_source_sha256 or
            current_tool != loaded_source_sha256):
        errors.append('authorizer source identity')
    try:
        closure_cursor = (values['global_close']['postflight']['doorbell_proof']
                          ['preparation_proof']['scanner_proof']['base']
                          ['journal_cursor'])
        if not isinstance(closure_cursor, str) or not closure_cursor:
            raise KeyError('closure journal cursor')
    except (KeyError, TypeError):
        closure_cursor = None
        errors.append('closure journal cursor')
    try:
        host = host_reader(closure_cursor) if closure_cursor is not None else None
        if host is not None:
            errors.extend(host_errors(host, contract['boot_id']))
    except BaseException:
        host = None
        errors.append('fresh host collection')
    return {
        'errors':sorted(set(errors)), 'seal':seal,
        'seal_sha256':_sha256(seal_raw), 'manifest':manifest,
        'manifest_sha256':_sha256(manifest_raw), 'ledger':ledger,
        'ledger_sha256':_sha256(ledger_raw),
        'evidence_sha256':{name:row['sha256']
                           for name,row in contract['evidence'].items()},
        'source_hashes':current_sources, 'host':host,
    }


def _write_once(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    directory = os.open(path.parent, os.O_DIRECTORY)
    try: os.fsync(directory)
    finally: os.close(directory)


def authorize_once(vm, manifest_path, seal_path, output,
                   expected_tool_source_sha256, expected_seal_sha256, *,
                   contract=FIXED_CONTRACT,
                   source_root=ROOT, loaded_source_sha256=None,
                   host_reader=collect_fresh_host, id_factory=lambda:uuid.uuid4().hex,
                   now=time.time):
    vm, output = Path(vm).resolve(), Path(output).resolve()
    expected_output = (vm/'run/retained-kiq-continuations'/
                       contract['boot_id']/(contract['prior_run_id']+'.json')).resolve()
    if output != expected_output:
        raise ContinuationError(f'output must be {expected_output}')
    if output.exists():
        raise FileExistsError(output)
    context = _context(vm, manifest_path, seal_path,
                       expected_tool_source_sha256, contract, source_root,
                       loaded_source_sha256, host_reader)
    if (not re.fullmatch(r'[0-9a-f]{64}', str(expected_seal_sha256)) or
            context['seal_sha256'] != expected_seal_sha256):
        context['errors'].append('reviewed seal hash')
    if context['errors']:
        raise ContinuationError('authorization refused: '+','.join(context['errors']))
    seal = context['seal']; manifest = context['manifest']
    authorization_id, recovery_id = id_factory(), id_factory()
    if (not re.fullmatch(r'[0-9a-f]{32}', str(authorization_id)) or
            not re.fullmatch(r'[0-9a-f]{32}', str(recovery_id)) or
            authorization_id == recovery_id):
        raise ContinuationError('authorization identifiers are invalid')
    receipt = {
        'schema':7, 'kind':'same-boot-retained-kiq-continuation',
        'status':'authorized', 'authorizes_launch':True,
        'authorizes_recovery':False, 'authorizes_cleanup':False,
        'boot_id':contract['boot_id'], 'prior_run_id':contract['prior_run_id'],
        'next_run_id':manifest['run_id'], 'authorization_id':authorization_id,
        'recovery_id':recovery_id, 'target_version':'1.0.176',
        'ledger_sha256':context['ledger_sha256'],
        'manifest_path':seal['manifest_path'],
        'manifest_sha256':context['manifest_sha256'],
        'seal_sha256':context['seal_sha256'],
        'evidence_sha256':context['evidence_sha256'],
        'source_hashes':context['source_hashes'],
        'host_proof':context['host'], 'created_epoch':now(),
    }
    _write_once(output, receipt)
    return receipt


def validate_receipt(receipt, vm, boot_id, prior_run_id, next_run_id,
                     manifest, manifest_path, *, contract=FIXED_CONTRACT,
                     source_root=ROOT, host_reader=collect_fresh_host):
    if not isinstance(receipt, dict):
        return ['retained_kiq_continuation_receipt']
    errors = []
    exact_keys = {
        'schema','kind','status','authorizes_launch','authorizes_recovery',
        'authorizes_cleanup','boot_id','prior_run_id','next_run_id',
        'authorization_id','recovery_id','target_version','ledger_sha256',
        'manifest_path','manifest_sha256','seal_sha256','evidence_sha256',
        'source_hashes','host_proof','created_epoch'}
    if (set(receipt) != exact_keys or receipt.get('schema') != 7 or
            receipt.get('kind') != 'same-boot-retained-kiq-continuation' or
            receipt.get('status') != 'authorized' or
            receipt.get('authorizes_launch') is not True or
            receipt.get('authorizes_recovery') is not False or
            receipt.get('authorizes_cleanup') is not False or
            receipt.get('boot_id') != boot_id or boot_id != contract['boot_id'] or
            receipt.get('prior_run_id') != prior_run_id or
            prior_run_id != contract['prior_run_id'] or
            receipt.get('next_run_id') != next_run_id or
            receipt.get('target_version') != '1.0.176' or
            not re.fullmatch(r'[0-9a-f]{32}', str(receipt.get('authorization_id', ''))) or
            not re.fullmatch(r'[0-9a-f]{32}', str(receipt.get('recovery_id', ''))) or
            receipt.get('authorization_id') == receipt.get('recovery_id') or
            type(receipt.get('created_epoch')) not in (int, float)):
        errors.append('retained_kiq_continuation_receipt')
    seal_path = Path(vm)/'run/retained-kiq-continuation-seal.json'
    try:
        seal_raw, seal = _read_json(seal_path)
        errors.extend(contract_errors(contract, seal))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        seal_raw, seal = b'', None
        errors.append('retained_kiq_continuation_seal')
    manifest_path = Path(manifest_path)
    try:
        manifest_raw = manifest_path.read_bytes()
        disk_manifest = json.loads(manifest_raw)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        manifest_raw, disk_manifest = b'', {}
        errors.append('retained_kiq_continuation_manifest')
    if disk_manifest != manifest:
        errors.append('retained_kiq_continuation_manifest')
    if isinstance(seal, dict):
        errors.extend(_manifest_errors(disk_manifest, manifest_raw, seal, contract))
    if (receipt.get('manifest_path') != 'run/metal-009-176-manifest.json' or
            manifest_path.resolve() !=
                (Path(vm)/receipt.get('manifest_path', '')).resolve() or
            receipt.get('manifest_sha256') != _sha256(manifest_raw) or
            receipt.get('seal_sha256') != _sha256(seal_raw)):
        errors.append('retained_kiq_continuation_manifest')
    ledger_path = Path(vm)/'run/used-gpu-boots'/(boot_id+'.json')
    try:
        ledger_raw, ledger = _read_json(ledger_path)
        if (receipt.get('ledger_sha256') != _sha256(ledger_raw) or
                _sha256(ledger_raw) != contract['ledger_sha256']):
            errors.append('retained_kiq_continuation_ledger')
        errors.extend('retained_kiq_continuation_' + error
                      for error in _ledger_errors(ledger, contract))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        errors.append('retained_kiq_continuation_ledger')
    for name, row in contract['evidence'].items():
        try:
            if _sha256((Path(vm)/row['path']).read_bytes()) != row['sha256']:
                errors.append('retained_kiq_continuation_evidence')
        except OSError:
            errors.append('retained_kiq_continuation_evidence')
    if receipt.get('evidence_sha256') != {
            name:row['sha256'] for name,row in contract['evidence'].items()}:
        errors.append('retained_kiq_continuation_evidence')
    try:
        current_sources = source_hashes(source_root)
        if (receipt.get('source_hashes') != current_sources or
                not isinstance(seal, dict) or
                seal.get('source_hashes') != current_sources):
            errors.append('retained_kiq_continuation_source')
    except OSError:
        errors.append('retained_kiq_continuation_source')
    errors.extend(host_errors(receipt.get('host_proof'), boot_id,
                              'sealed host '))
    try:
        fresh = host_reader(receipt.get('host_proof', {}).get('journal_cursor'))
        errors.extend(host_errors(fresh, boot_id))
    except BaseException:
        errors.append('fresh host collection')
    return sorted(set(errors))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', required=True, type=Path)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--seal', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--expected-source-sha256', required=True)
    parser.add_argument('--expected-seal-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        if (not re.fullmatch(r'[0-9a-f]{64}', args.expected_source_sha256) or
                not re.fullmatch(r'[0-9a-f]{64}', args.expected_seal_sha256)):
            raise ContinuationError('expected SHA-256 is invalid')
        vm = args.vm_dir.resolve()
        lock = vm/'run/experiment.lock'; lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open('a') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = authorize_once(vm, args.manifest, args.seal, args.output,
                                    args.expected_source_sha256,
                                    args.expected_seal_sha256)
    except BaseException as error:
        print(json.dumps({'status':'failed', 'authorizes_launch':False,
                          'authorizes_recovery':False,
                          'authorizes_cleanup':False,
                          'error':type(error).__name__+': '+str(error)}, indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
