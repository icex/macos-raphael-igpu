#!/usr/bin/env python3
"""Disable two retained SDMA PAGE inputs and clear one halted KIQ WPTR."""
import argparse
import copy
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import sys
import time


def _helper(name):
    path = Path(__file__).with_name(name + '.py')
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SCANNER = _helper('inspect-retained-idle')
RECOVERY = SCANNER.RECOVERY
SCANNER_SOURCE_SHA256 = '0c4f4bc9bd87aa41630349616dbc545d3114018ee93f80ab9c0a82da5f649e79'
LOADED_SCANNER_SOURCE_SHA256 = hashlib.sha256(
    Path(__file__).with_name('inspect-retained-idle.py').read_bytes()).hexdigest()
IDLE_RESULT_SHA256 = '589278713643fc52db7f5a0a8ef7f4f5bab0a8e38aec5a209fa27b8ff9ffe42d'
BOOT_ID, RUN_ID = SCANNER.BOOT_ID, SCANNER.RUN_ID

PAGE_RB_OFFSET = SCANNER.SDMA_AUX_OFFSETS['page_rb_cntl']
PAGE_IB_OFFSET = SCANNER.SDMA_AUX_OFFSETS['page_ib_cntl']
EXPECTED_FIXED_WRITES = (
    (PAGE_IB_OFFSET, 0x00000101, 0x00000100, 0),
    (PAGE_RB_OFFSET, 0x80840021, 0x80840020, 0),
    (RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET, 0x00000100, 0x00000000,
     RECOVERY.HOST_KIQ_SELECTOR),
)


class PageDisableError(RuntimeError):
    def __init__(self, message, evidence=None):
        super().__init__(message)
        self.evidence = evidence or {}


def _sha256(data): return hashlib.sha256(data).hexdigest()


class PageDisableTransport(SCANNER.Bar5SelectorTransport):
    """The selector transport plus one exact, ordered three-DWORD program."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.write_log = []

    def __exit__(self, kind, error, traceback):
        try:
            self.close()
        except BaseException as close_error:
            if error is not None:
                evidence = (error.evidence
                            if isinstance(error, PageDisableError) else None)
                raise PageDisableError(
                    f'{type(error).__name__}: {error}; close failed: '
                    f'{type(close_error).__name__}: {close_error}', evidence) from error
            raise

    def write_fixed(self, offset, before, value):
        step = len(self.write_log)
        candidate = (offset, before, value, getattr(self, '_selected', 0))
        if step >= len(EXPECTED_FIXED_WRITES) or candidate != EXPECTED_FIXED_WRITES[step]:
            raise PageDisableError(f'forbidden PAGE write step {candidate!r}')
        row = {'sequence': step, 'offset': offset, 'before': before,
               'value': value, 'selector': candidate[3], 'attempted': True,
               'store_completed': False, 'completed': False}
        self.write_log.append(row)
        try:
            observed = self._raw32(offset)
            row['observed_before'] = observed
            if observed != before:
                raise PageDisableError(
                    f'fixed write preimage changed at {offset:#x}: {observed:#x}')
            struct.pack_into('<I', self.bar0, offset, value)
            row['store_completed'] = True
            posted = self._raw32(offset)
            row['posted'] = posted
            row['completed'] = posted == value
            return posted
        except BaseException as error:
            row['error'] = type(error).__name__ + ': ' + str(error)
            raise

    def select(self, value):
        super().select(value)
        self._selected = value

    def metadata(self):
        value = super().metadata()
        value['userspace_selector_writes_only'] = False
        value['userspace_fixed_dword_writes'] = [
            {'offset': offset, 'before': before, 'value': after,
             'selector': selector}
            for offset, before, after, selector in EXPECTED_FIXED_WRITES]
        return value


def full_scan_read_trace():
    trace = []
    for _ in (1, 2):
        trace.extend(SCANNER.GLOBAL_OFFSETS.values())
        for selector in SCANNER.COMPUTE_SELECTORS:
            trace.extend((RECOVERY.CP_HQD_ACTIVE_OFFSET,
                          RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET))
            if selector == RECOVERY.HOST_KIQ_SELECTOR:
                trace.extend(SCANNER.HOST_KIQ_DETAIL_OFFSETS.values())
        for descriptor in RECOVERY.GRAPHICS_PIPE_DESCRIPTORS:
            _, _, _, wptr, wptr_hi, base, base_hi, cntl = descriptor
            trace.extend((RECOVERY.CP_RB_DOORBELL_CONTROL_OFFSET,
                          RECOVERY.CP_RB_ACTIVE_OFFSET,
                          RECOVERY.CP_RB1_ACTIVE_OFFSET,
                          wptr, wptr_hi, base, base_hi, cntl))
    return trace


def expected_after_passes(before):
    after = copy.deepcopy(before)
    for scan in after:
        scan['globals']['sdma0_page_ib_cntl'] = 0x100
        scan['globals']['sdma0_page_rb_cntl'] = 0x80840020
        row = next(row for row in scan['compute']
                   if row['selector'] == RECOVERY.HOST_KIQ_SELECTOR)
        row['host_kiq']['wptr_lo'] = 0
    return after


def _capture_scan(transport):
    try:
        return SCANNER.scan_device(transport)
    except SCANNER.IdleInspectionError as error:
        return error.evidence


def _scan_matches(observed, expected_passes, label):
    if (not isinstance(observed, dict) or
            observed.get('passes') != expected_passes or
            observed.get('final_default') != {
                'attempted': True, 'completed': True, 'value': 0} or
            len(observed.get('selector_writes', [])) != 137 or
            any(row.get('completed') is not True
                for row in observed.get('selector_writes', []))):
        raise PageDisableError(f'{label} does not match exact retained state')


def _read_halt_idle(transport, evidence, label):
    row = {}
    evidence[label] = row
    for name, offset in (
            ('f32_cntl', RECOVERY.SDMA0_F32_CNTL_OFFSET),
            ('status', SCANNER.SDMA0_STATUS_REG_OFFSET),
            ('page_ib_cntl', PAGE_IB_OFFSET),
            ('page_rb_cntl', PAGE_RB_OFFSET)):
        row[name] = transport.read32(offset)
    if any(type(value) is not int or value == 0xffffffff for value in row.values()):
        raise PageDisableError(label + ' is inaccessible', evidence)
    if row['f32_cntl'] != RECOVERY.SDMA_HALT_MASK:
        raise PageDisableError(label + ' SDMA halt is absent', evidence)
    if not row['status'] & SCANNER.SDMA_STATUS_IDLE_MASK:
        raise PageDisableError(label + ' SDMA idle is absent', evidence)
    return row


def _append_fixed_write(transport, evidence, offset, before, value):
    prior = len(getattr(transport, 'write_log', []))
    try:
        posted = transport.write_fixed(offset, before, value)
    finally:
        log = getattr(transport, 'write_log', [])
        if evidence['writes'] is not log:
            evidence['writes'][:] = list(log)
    if len(evidence['writes']) != prior + 1:
        raise PageDisableError('fixed write evidence was not retained', evidence)
    return posted


def _select_control(transport, evidence, value, phase):
    row = {'sequence': len(evidence['control_selectors']), 'phase': phase,
           'value': value, 'attempted': True, 'completed': False}
    evidence['control_selectors'].append(row)
    try:
        transport.select(value)
    except BaseException as error:
        row['error'] = type(error).__name__ + ': ' + str(error)
        raise
    row['completed'] = True


def _pre_wptr_snapshot(transport, evidence):
    row = {'globals': {}, 'hqd': {}}
    evidence['pre_wptr'] = row
    globals_to_read = (
        ('cp_stat', RECOVERY.CP_STAT_OFFSET),
        ('cpc_busy', RECOVERY.CP_CPC_BUSY_STAT_OFFSET),
        ('mec_cntl', RECOVERY.CP_MEC_CNTL_OFFSET),
        ('pq_wptr_poll_cntl', RECOVERY.CP_PQ_WPTR_POLL_CNTL_OFFSET),
        ('pq_status', RECOVERY.CP_PQ_STATUS_OFFSET),
        ('doorbell_range_lower', RECOVERY.CP_MEC_DOORBELL_RANGE_LOWER_OFFSET),
        ('doorbell_range_upper', RECOVERY.CP_MEC_DOORBELL_RANGE_UPPER_OFFSET),
        ('sdma_f32_cntl', RECOVERY.SDMA0_F32_CNTL_OFFSET),
        ('sdma_status', SCANNER.SDMA0_STATUS_REG_OFFSET),
        ('page_ib_cntl', PAGE_IB_OFFSET), ('page_rb_cntl', PAGE_RB_OFFSET),
    )
    for name, offset in globals_to_read:
        row['globals'][name] = transport.read32(offset)
    values = row['globals']
    if any(type(value) is not int or value == 0xffffffff for value in values.values()):
        raise PageDisableError('pre-WPTR globals inaccessible', evidence)
    if values['cp_stat'] or values['cpc_busy']:
        raise PageDisableError('pre-WPTR CP idle gate failed', evidence)
    if values['mec_cntl'] != RECOVERY.CP_MEC_HALT_MASK:
        raise PageDisableError('pre-WPTR MEC halt gate failed', evidence)
    if (values['pq_wptr_poll_cntl'] or values['pq_status'] or
            values['doorbell_range_lower'] or values['doorbell_range_upper']):
        raise PageDisableError('pre-WPTR global gate failed', evidence)
    if (values['sdma_f32_cntl'] != RECOVERY.SDMA_HALT_MASK or
            not values['sdma_status'] & SCANNER.SDMA_STATUS_IDLE_MASK or
            values['page_ib_cntl'] != 0x100 or
            values['page_rb_cntl'] != 0x80840020):
        raise PageDisableError('pre-WPTR SDMA gate failed', evidence)
    try:
        _select_control(transport, evidence, RECOVERY.HOST_KIQ_SELECTOR,
                        'pre-wptr-select-kiq')
        for name, offset in (
                ('active', RECOVERY.CP_HQD_ACTIVE_OFFSET),
                ('dequeue', RECOVERY.CP_HQD_DEQUEUE_OFFSET),
                ('rptr', RECOVERY.CP_HQD_PQ_RPTR_OFFSET),
                ('wptr_hi', RECOVERY.CP_HQD_PQ_WPTR_HI_OFFSET),
                ('wptr_lo', RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET),
                ('doorbell_control', RECOVERY.CP_HQD_PQ_DOORBELL_OFFSET)):
            row['hqd'][name] = transport.read32(offset)
        hqd = row['hqd']
        if any(type(value) is not int or value == 0xffffffff
               for value in hqd.values()):
            raise PageDisableError('pre-WPTR HQD inaccessible', evidence)
        expected = {'active': 0, 'dequeue': 0, 'rptr': 0, 'wptr_hi': 0,
                    'wptr_lo': 0x100, 'doorbell_control': 0x80000000}
        for name, value in expected.items():
            if hqd[name] != value:
                label = 'DB_EN' if name == 'doorbell_control' else name.upper()
                raise PageDisableError(f'pre-WPTR {label} gate failed', evidence)
    except BaseException as error:
        try:
            _select_control(transport, evidence, 0, 'pre-wptr-restore-default')
        except BaseException as restore_error:
            raise PageDisableError(
                f'{error}; selector restore failed: {restore_error}', evidence) from error
        raise
    return row


def execute_transaction(transport, expected_device):
    evidence = {
        'status': 'failed', 'authorizes_launch': False,
        'authorizes_recovery': False, 'authorizes_cleanup': False,
        'before': None, 'after': None, 'writes': [],
        'control_selectors': [],
    }
    if hasattr(transport, 'write_log'):
        evidence['writes'] = transport.write_log
    mutation_started = False
    primary = None
    try:
        evidence['before'] = _capture_scan(transport)
        _scan_matches(evidence['before'], expected_device['passes'], 'pre-scan')
        before = _read_halt_idle(transport, evidence, 'immediate_before_page_ib')
        if (before['page_ib_cntl'], before['page_rb_cntl']) != \
                (0x101, 0x80840021):
            raise PageDisableError('immediate PAGE preimages changed', evidence)
        mutation_started = True
        posted = _append_fixed_write(
            transport, evidence, PAGE_IB_OFFSET, 0x101, 0x100)
        if posted != 0x100:
            raise PageDisableError('PAGE IB posting/readback failed', evidence)
        between = _read_halt_idle(transport, evidence, 'immediate_before_page_rb')
        if (between['page_ib_cntl'], between['page_rb_cntl']) != \
                (0x100, 0x80840021):
            raise PageDisableError('PAGE RB preimages changed', evidence)
        posted = _append_fixed_write(
            transport, evidence, PAGE_RB_OFFSET, 0x80840021, 0x80840020)
        if posted != 0x80840020:
            raise PageDisableError('PAGE RB posting/readback failed', evidence)
        _pre_wptr_snapshot(transport, evidence)
        posted = _append_fixed_write(
            transport, evidence, RECOVERY.CP_HQD_PQ_WPTR_LO_OFFSET, 0x100, 0)
        if posted != 0:
            primary = PageDisableError('WPTR posting/readback failed', evidence)
    except BaseException as error:
        primary = error
    finally:
        if evidence['control_selectors'] and \
                evidence['control_selectors'][-1]['value'] != 0:
            try:
                _select_control(transport, evidence, 0, 'final-control-default')
            except BaseException as error:
                if primary is None:
                    primary = error
                else:
                    primary = PageDisableError(
                        f'{primary}; selector restore failed: {error}', evidence)
        if mutation_started:
            try:
                evidence['after'] = _capture_scan(transport)
                if primary is None:
                    _scan_matches(evidence['after'],
                                  expected_after_passes(expected_device['passes']),
                                  'post-scan')
            except BaseException as error:
                if primary is None:
                    primary = error
                else:
                    primary = PageDisableError(
                        f'{primary}; post-scan failed: {error}', evidence)
    evidence['vfio_region'] = transport.metadata()
    if primary is not None:
        evidence['error'] = type(primary).__name__ + ': ' + str(primary)
        if isinstance(primary, PageDisableError) and primary.evidence is evidence:
            raise primary
        raise PageDisableError(type(primary).__name__ + ': ' + str(primary), evidence)
    evidence['status'] = 'page-inputs-disabled-and-kiq-wptr-cleared'
    return evidence


def idle_result_errors(value):
    expected = ('failed', False, False, False, BOOT_ID, RUN_ID)
    observed = (value.get('status'), value.get('authorizes_launch'),
                value.get('authorizes_recovery'), value.get('authorizes_cleanup'),
                value.get('boot_id'), value.get('run_id'))
    device = value.get('device', {})
    if observed != expected:
        return ['retained-idle result identity/status']
    if (device.get('passes') is None or device.get('authorizes_launch') is not False or
            device.get('authorizes_recovery') is not False or
            device.get('authorizes_cleanup') is not False):
        return ['retained-idle device evidence']
    return []


def collect_preflight(vm, evidence_dir, expected_tool_source_sha256,
                      journal_cursor=None):
    vm = Path(vm).resolve()
    scanner_proof = SCANNER.collect_preflight(
        vm, evidence_dir, SCANNER_SOURCE_SHA256, journal_cursor)
    idle_path = vm/'run/retained-idle-inspections'/f'{BOOT_ID}-{RUN_ID}.json'
    idle_raw = idle_path.read_bytes()
    idle_result = json.loads(idle_raw)
    return {
        'scanner_proof': scanner_proof,
        'scanner_errors': SCANNER.preflight_errors(scanner_proof),
        'idle_result_sha256': _sha256(idle_raw),
        'idle_result_errors': idle_result_errors(idle_result),
        'idle_result': idle_result,
        'tool_source_sha256': _sha256(Path(__file__).read_bytes()),
        'expected_tool_source_sha256': expected_tool_source_sha256,
        'loaded_scanner_source_sha256': LOADED_SCANNER_SOURCE_SHA256,
        'scanner_source_sha256': _sha256(
            Path(__file__).with_name('inspect-retained-idle.py').read_bytes()),
    }


def preflight_errors(proof):
    errors = ['scanner: ' + error for error in
              proof.get('scanner_errors', ['scanner proof missing'])]
    if proof.get('idle_result_sha256') != IDLE_RESULT_SHA256 or \
            proof.get('idle_result_errors') != []:
        errors.append('exact retained-idle result')
    if (proof.get('loaded_scanner_source_sha256') != SCANNER_SOURCE_SHA256 or
            proof.get('scanner_source_sha256') != SCANNER_SOURCE_SHA256):
        errors.append('scanner source changed')
    if proof.get('tool_source_sha256') != proof.get('expected_tool_source_sha256'):
        errors.append('tool source changed')
    return errors


def postflight_errors(before, after):
    errors = preflight_errors(after)
    errors.extend('scanner postflight: ' + error for error in
                  SCANNER.postflight_errors(before.get('scanner_proof', {}),
                                            after.get('scanner_proof', {})))
    for key in ('idle_result_sha256', 'idle_result_errors',
                'tool_source_sha256', 'expected_tool_source_sha256',
                'loaded_scanner_source_sha256', 'scanner_source_sha256'):
        if before.get(key) != after.get(key): errors.append(key + ' changed')
    return errors


def run_transaction(preflight_reader, transport_factory, postflight_reader,
                    output, expected_device=None):
    output = Path(output); attempt = output.with_suffix('.attempt.json')
    if output.exists() or attempt.exists():
        raise FileExistsError('retained KIQ preparation path was already consumed')
    base = {'schema': 1, 'kind': 'retained-kiq-preparation', 'status': 'failed',
            'authorizes_launch': False, 'authorizes_recovery': False,
            'authorizes_cleanup': False, 'boot_id': BOOT_ID, 'run_id': RUN_ID}
    try:
        preflight = preflight_reader()
    except BaseException as error:
        result = dict(base, error='preflight collection: ' + str(error),
                      created_epoch=time.time())
        SCANNER.OBSERVER._write_once(output, result)
        raise PageDisableError(result['error'], result) from error
    errors = preflight_errors(preflight)
    if errors:
        result = dict(base, preflight=preflight,
                      error='pre-VFIO ' + ', '.join(errors),
                      created_epoch=time.time())
        SCANNER.OBSERVER._write_once(output, result)
        raise PageDisableError(result['error'], result)
    if expected_device is None:
        expected_device = preflight['idle_result']['device']
    SCANNER.OBSERVER._write_once(
        attempt, dict(base, status='device-open-attempted',
                      created_epoch=time.time()))
    transaction = inner_error = device_error = None
    try:
        with transport_factory() as transport:
            try:
                transaction = execute_transaction(transport, expected_device)
            except BaseException as error:
                inner_error = error
                if isinstance(error, PageDisableError):
                    transaction = error.evidence
                raise
    except BaseException as error:
        if inner_error is not None and error is not inner_error and \
                str(inner_error) not in str(error):
            device_error = PageDisableError(
                f'{inner_error}; close failed: {type(error).__name__}: {error}',
                transaction)
        else:
            device_error = error
    try:
        postflight = postflight_reader(
            preflight['scanner_proof']['base']['journal_cursor'])
        post_errors = postflight_errors(preflight, postflight)
    except BaseException as error:
        postflight = {'collection_error': type(error).__name__ + ': ' + str(error)}
        post_errors = ['postflight collection failed']
    result = dict(base, preflight=preflight, transaction=transaction,
                  postflight=postflight, created_epoch=time.time())
    if device_error is not None: result['device_error'] = str(device_error)
    if post_errors: result['postflight_errors'] = post_errors
    if device_error is not None or post_errors:
        result['error'] = '; '.join(filter(None, (
            'device: ' + str(device_error) if device_error else '',
            'postflight: ' + ', '.join(post_errors) if post_errors else '')))
        SCANNER.OBSERVER._write_once(output, result)
        raise PageDisableError(result['error'], result)
    result['status'] = 'completed-nonauthorizing'
    SCANNER.OBSERVER._write_once(output, result)
    return result


def prepare_once(vm, evidence_dir, output, expected_tool_source_sha256):
    vm, evidence_dir, output = map(lambda value: Path(value).resolve(),
                                   (vm, evidence_dir, output))
    expected_output = vm/'run/retained-kiq-preparations'/f'{BOOT_ID}-{RUN_ID}.json'
    if output != expected_output.resolve():
        raise PageDisableError(f'output must be {expected_output}')
    lock = vm/'run/experiment.lock'; lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_transaction(
            lambda: collect_preflight(vm, evidence_dir,
                                      expected_tool_source_sha256),
            PageDisableTransport,
            lambda cursor: collect_preflight(
                vm, evidence_dir, expected_tool_source_sha256, cursor),
            output)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', required=True, type=Path)
    parser.add_argument('--evidence-dir', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--expected-source-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r'[0-9a-f]{64}', args.expected_source_sha256):
            raise PageDisableError('expected source SHA-256 is invalid')
        result = prepare_once(args.vm_dir, args.evidence_dir, args.output,
                              args.expected_source_sha256)
    except BaseException as error:
        print(json.dumps({'status': 'failed', 'authorizes_launch': False,
                          'authorizes_recovery': False,
                          'authorizes_cleanup': False,
                          'error': type(error).__name__ + ': ' + str(error)},
                         indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True)); return 0


if __name__ == '__main__': sys.exit(main())
