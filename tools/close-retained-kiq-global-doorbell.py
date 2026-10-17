#!/usr/bin/env python3
"""Close the retained KIQ global doorbell gate without authorizing reuse."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time


def _helper(name):
    path = Path(__file__).with_name(name + '.py')
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DOORBELL = _helper('retained-kiq-doorbell-zero')
SCANNER, RECOVERY, OBSERVER = DOORBELL.SCANNER, DOORBELL.RECOVERY, DOORBELL.OBSERVER
DOORBELL_SOURCE_SHA256 = (
    'eb9257a9ed0d9453e171a4be86466d690f40b525444ce99d5ae248aaa30f4d30')
LOADED_DOORBELL_SOURCE_SHA256 = hashlib.sha256(
    Path(__file__).with_name('retained-kiq-doorbell-zero.py').read_bytes()).hexdigest()
DOORBELL_RESULT_SHA256 = (
    '3ac3511b9b302c873b2b205be45b9b4135703844506f971a766923f4fb096b2e')
BOOT_ID, RUN_ID = DOORBELL.BOOT_ID, DOORBELL.RUN_ID
PQ_UPDATED = 1
PQ_ENABLE = RECOVERY.CP_PQ_DOORBELL_ENABLE_MASK


class GlobalCloseError(RuntimeError):
    def __init__(self, message, evidence=None):
        super().__init__(message)
        self.evidence = evidence or {}


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


class GlobalCloseTransport(SCANNER.Bar5SelectorTransport):
    """The frozen selector transport plus one exact CP_PQ_STATUS DWORD store."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.close_writes = []

    def __exit__(self, kind, error, traceback):
        try:
            self.close()
        except BaseException as close_error:
            if error is not None:
                evidence = (error.evidence
                            if isinstance(error, GlobalCloseError) else None)
                raise GlobalCloseError(
                    f'{type(error).__name__}: {error}; close failed: '
                    f'{type(close_error).__name__}: {close_error}', evidence) from error
            raise

    def write_global_close(self, offset, before, value):
        if self.close_writes:
            raise GlobalCloseError('global close store was already attempted')
        if (type(offset) is not int or type(before) is not int or
                type(value) is not int or
                offset != RECOVERY.CP_PQ_STATUS_OFFSET or before != 3 or value != 1):
            raise GlobalCloseError('forbidden global close store')
        row = {'sequence': 0, 'offset': offset, 'before': before, 'value': value,
               'attempted': True, 'store_completed': False, 'completed': False}
        self.close_writes.append(row)
        try:
            observed = RECOVERY._load_mmio_u32(self.bar0, offset)
            row['observed_before'] = observed
            if observed != before:
                raise GlobalCloseError(
                    f'global close preimage is {observed:#x}, expected {before:#x}')
            RECOVERY._store_mmio_u32(self.bar0, offset, value)
            row['store_completed'] = True
            posted = RECOVERY._load_mmio_u32(self.bar0, offset)
            row['posted'] = posted
            if posted not in (0, PQ_UPDATED):
                raise GlobalCloseError(
                    f'global doorbell gate did not close: {posted:#x}')
            row['completed'] = True
            return posted
        except BaseException as error:
            row['error'] = type(error).__name__ + ': ' + str(error)
            raise

    def metadata(self):
        value = super().metadata()
        value.update({
            'userspace_mapping': 'BAR5-only',
            'userspace_selector_writes_only': False,
            'userspace_fixed_dword_writes': [{
                'offset': RECOVERY.CP_PQ_STATUS_OFFSET,
                'before': 3, 'value': 1}],
            'native_store_width_bits': 32,
        })
        return value


def _capture_scan(transport):
    try:
        return SCANNER.scan_device(transport)
    except SCANNER.IdleInspectionError as error:
        return error.evidence


def _scan_shape(scan, label):
    if (not isinstance(scan, dict) or len(scan.get('passes', [])) != 2 or
            scan['passes'][0] != scan['passes'][1] or
            scan.get('final_default') != {
                'attempted': True, 'completed': True, 'value': 0} or
            len(scan.get('selector_writes', [])) != 137 or
            any(row.get('completed') is not True
                for row in scan.get('selector_writes', []))):
        raise GlobalCloseError(label + ' is incomplete or unstable')


def _exact_pre_scan(scan, expected):
    _scan_shape(scan, 'pre-scan')
    if scan['passes'] != expected['passes']:
        raise GlobalCloseError('pre-scan does not match exact retained state')
    for observed in scan['passes']:
        values = observed['globals']
        if (values['cp_stat'] != 0 or values['cpc_busy'] != 0 or
                values['me_cntl'] & RECOVERY.CP_ME_HALT_MASK !=
                RECOVERY.CP_ME_HALT_MASK or
                values['mec_cntl'] & RECOVERY.CP_MEC_HALT_MASK !=
                RECOVERY.CP_MEC_HALT_MASK or
                values['pq_wptr_poll_cntl'] != 0 or values['pq_status'] != 3 or
                values['doorbell_range_lower'] != 0 or
                values['doorbell_range_upper'] != 0):
            raise GlobalCloseError('pre-scan CP/global doorbell gate changed')
        if (values['sdma0_f32_cntl'] != RECOVERY.SDMA_HALT_MASK or
                not values['sdma0_status'] & SCANNER.SDMA_STATUS_IDLE_MASK or
                values['sdma0_page_ib_cntl'] != 0x100 or
                values['sdma0_page_rb_cntl'] != 0x80840020):
            raise GlobalCloseError('pre-scan SDMA/PAGE gates changed')
        for row in observed['compute']:
            if (row['active'] != 0 or
                    row['pq_doorbell_control'] & ~DOORBELL.DOORBELL_HIT or
                    row['pq_doorbell_control'] & DOORBELL.DOORBELL_ENABLE):
                raise GlobalCloseError('pre-scan compute ingress/ACTIVE changed')
        target = next(row for row in observed['compute']
                      if row['selector'] == RECOVERY.HOST_KIQ_SELECTOR)
        if target['host_kiq'] != {
                'dequeue': 0, 'rptr': 0, 'wptr_lo': 0, 'wptr_hi': 0}:
            raise GlobalCloseError('pre-scan selector 9 state changed')


def _exact_post_scan(scan, expected):
    _scan_shape(scan, 'post-scan')
    for observed, reference in zip(scan['passes'], expected['passes']):
        changed = json.loads(json.dumps(reference))
        actual_status = observed['globals']['pq_status']
        if actual_status not in (0, PQ_UPDATED):
            raise GlobalCloseError(
                f'post-scan global doorbell gate is open: {actual_status:#x}')
        changed['globals']['pq_status'] = actual_status
        if observed != changed:
            raise GlobalCloseError('post-scan state changed outside CP_PQ_STATUS')
        target = next(row for row in observed['compute']
                      if row['selector'] == RECOVERY.HOST_KIQ_SELECTOR)
        if target['host_kiq']['wptr_lo'] or target['host_kiq']['wptr_hi']:
            raise GlobalCloseError('post-scan selector 9 WPTR changed')


def execute_transaction(transport, expected_device):
    evidence = {
        'status': 'failed', 'authorizes_launch': False,
        'authorizes_recovery': False, 'authorizes_cleanup': False,
        'before': None, 'after': None, 'writes': [],
    }
    if hasattr(transport, 'close_writes'):
        evidence['writes'] = transport.close_writes
    mutation_started = False
    primary = None
    try:
        evidence['before'] = _capture_scan(transport)
        _exact_pre_scan(evidence['before'], expected_device)
        mutation_started = True
        try:
            posted = transport.write_global_close(
                RECOVERY.CP_PQ_STATUS_OFFSET, 3, PQ_UPDATED)
        finally:
            log = getattr(transport, 'close_writes', [])
            if evidence['writes'] is not log:
                evidence['writes'][:] = list(log)
        if posted not in (0, PQ_UPDATED):
            raise GlobalCloseError('global doorbell gate did not close', evidence)
    except BaseException as error:
        primary = error
    finally:
        if mutation_started:
            try:
                evidence['after'] = _capture_scan(transport)
                if primary is None:
                    _exact_post_scan(evidence['after'], expected_device)
            except BaseException as error:
                if primary is None:
                    primary = error
                else:
                    primary = GlobalCloseError(
                        f'{primary}; post-scan failed: {error}', evidence)
    try:
        evidence['vfio_region'] = transport.metadata()
    except BaseException as error:
        if primary is None:
            primary = error
        else:
            primary = GlobalCloseError(
                f'{primary}; metadata failed: {type(error).__name__}: {error}', evidence)
    if primary is not None:
        evidence['error'] = type(primary).__name__ + ': ' + str(primary)
        if isinstance(primary, GlobalCloseError) and primary.evidence is evidence:
            raise primary
        raise GlobalCloseError(type(primary).__name__ + ': ' + str(primary), evidence)
    evidence['status'] = 'global-doorbell-gate-closed-nonauthorizing'
    return evidence


def doorbell_result_errors(value):
    errors = []
    if (value.get('status') != 'failed' or value.get('boot_id') != BOOT_ID or
            value.get('run_id') != RUN_ID or
            value.get('authorizes_launch') is not False or
            value.get('authorizes_recovery') is not False or
            value.get('authorizes_cleanup') is not False or
            value.get('device_error') !=
            'global gate close: global PQ doorbell close preimage changed'):
        errors.append('doorbell result identity/status')
    transaction = value.get('transaction', {})
    try:
        if (transaction['doorbell_writes'] != [{
                'attempted': True, 'barrier': 0x200, 'completed': True,
                'index': 0, 'offset': 0, 'sequence': 0,
                'store_completed': True, 'value': 0, 'width_bits': 64}] or
                transaction['interim_samples'] != [{
                    'active': 0, 'mec_cntl': RECOVERY.CP_MEC_HALT_MASK,
                    'wptr_hi': 0, 'wptr_lo': 0}] or
                transaction['gate_close']['global']['completed'] is not False or
                transaction['gate_close']['hqd']['completed'] is not True or
                transaction['final_default'] != {
                    'attempted': True, 'completed': True, 'value': 0} or
                transaction['after']['passes'][0] !=
                transaction['after']['passes'][1]):
            errors.append('doorbell exact transaction')
    except (KeyError, TypeError):
        errors.append('doorbell transaction missing')
    return errors


def collect_preflight(vm, evidence_dir, expected_tool_source_sha256,
                      journal_cursor=None):
    vm = Path(vm).resolve()
    doorbell_proof = DOORBELL.collect_preflight(
        vm, evidence_dir, DOORBELL_SOURCE_SHA256, journal_cursor)
    path = vm/'run/retained-kiq-doorbell-zero'/f'{BOOT_ID}-{RUN_ID}.json'
    raw = path.read_bytes(); value = json.loads(raw)
    return {
        'doorbell_proof': doorbell_proof,
        'doorbell_errors': DOORBELL.preflight_errors(doorbell_proof),
        'doorbell_result_sha256': _sha256(raw),
        'doorbell_result_errors': doorbell_result_errors(value),
        'doorbell_result': value,
        'tool_source_sha256': _sha256(Path(__file__).read_bytes()),
        'expected_tool_source_sha256': expected_tool_source_sha256,
        'loaded_doorbell_source_sha256': LOADED_DOORBELL_SOURCE_SHA256,
        'current_doorbell_source_sha256': _sha256(
            Path(__file__).with_name('retained-kiq-doorbell-zero.py').read_bytes()),
    }


def preflight_errors(proof):
    errors = ['doorbell: ' + error for error in
              proof.get('doorbell_errors', ['doorbell proof missing'])]
    if (proof.get('doorbell_result_sha256') != DOORBELL_RESULT_SHA256 or
            proof.get('doorbell_result_errors') != []):
        errors.append('exact doorbell-zero result')
    if (proof.get('loaded_doorbell_source_sha256') != DOORBELL_SOURCE_SHA256 or
            proof.get('current_doorbell_source_sha256') != DOORBELL_SOURCE_SHA256):
        errors.append('doorbell source changed')
    if proof.get('tool_source_sha256') != proof.get('expected_tool_source_sha256'):
        errors.append('tool source changed')
    return errors


def postflight_errors(before, after):
    errors = preflight_errors(after)
    errors.extend('doorbell postflight: ' + error for error in
                  DOORBELL.postflight_errors(
                      before.get('doorbell_proof', {}),
                      after.get('doorbell_proof', {})))
    for key in ('doorbell_result_sha256', 'doorbell_result_errors',
                'tool_source_sha256', 'expected_tool_source_sha256',
                'loaded_doorbell_source_sha256',
                'current_doorbell_source_sha256'):
        if before.get(key) != after.get(key): errors.append(key + ' changed')
    return errors


def run_transaction(preflight_reader, transport_factory, postflight_reader,
                    output, expected_device=None):
    output = Path(output); attempt = output.with_suffix('.attempt.json')
    if output.exists() or attempt.exists():
        raise FileExistsError('retained KIQ global-close path was already consumed')
    base = {'schema': 1, 'kind': 'retained-kiq-global-doorbell-close',
            'status': 'failed', 'authorizes_launch': False,
            'authorizes_recovery': False, 'authorizes_cleanup': False,
            'boot_id': BOOT_ID, 'run_id': RUN_ID}
    try:
        preflight = preflight_reader()
    except BaseException as error:
        result = dict(base, error='preflight collection: ' + str(error),
                      created_epoch=time.time())
        OBSERVER._write_once(output, result)
        raise GlobalCloseError(result['error'], result) from error
    errors = preflight_errors(preflight)
    if errors:
        result = dict(base, preflight=preflight,
                      error='pre-VFIO ' + ', '.join(errors),
                      created_epoch=time.time())
        OBSERVER._write_once(output, result)
        raise GlobalCloseError(result['error'], result)
    if expected_device is None:
        expected_device = preflight['doorbell_result']['transaction']['after']
    OBSERVER._write_once(
        attempt, dict(base, status='device-open-attempted',
                      created_epoch=time.time()))
    transaction = inner_error = device_error = None
    try:
        with transport_factory() as transport:
            try:
                transaction = execute_transaction(transport, expected_device)
            except BaseException as error:
                inner_error = error
                if isinstance(error, GlobalCloseError):
                    transaction = error.evidence
                raise
    except BaseException as error:
        if (inner_error is not None and error is not inner_error and
                str(inner_error) not in str(error)):
            device_error = GlobalCloseError(
                f'{inner_error}; close failed: {type(error).__name__}: {error}',
                transaction)
        else:
            device_error = error
    try:
        postflight = postflight_reader(
            preflight['doorbell_proof']['preparation_proof']
            ['scanner_proof']['base']['journal_cursor'])
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
        OBSERVER._write_once(output, result)
        raise GlobalCloseError(result['error'], result)
    result['status'] = 'completed-nonauthorizing'
    OBSERVER._write_once(output, result)
    return result


def close_once(vm, evidence_dir, output, expected_tool_source_sha256):
    vm, evidence_dir, output = map(lambda value: Path(value).resolve(),
                                   (vm, evidence_dir, output))
    expected = vm/'run/retained-kiq-global-doorbell-closures'/f'{BOOT_ID}-{RUN_ID}.json'
    if output != expected.resolve():
        raise GlobalCloseError(f'output must be {expected}')
    lock = vm/'run/experiment.lock'; lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return run_transaction(
            lambda: collect_preflight(vm, evidence_dir,
                                      expected_tool_source_sha256),
            GlobalCloseTransport,
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
            raise GlobalCloseError('expected source SHA-256 is invalid')
        result = close_once(args.vm_dir, args.evidence_dir, args.output,
                            args.expected_source_sha256)
    except BaseException as error:
        print(json.dumps({'status': 'failed', 'authorizes_launch': False,
                          'authorizes_recovery': False,
                          'authorizes_cleanup': False,
                          'error': type(error).__name__ + ': ' + str(error)},
                         indent=2))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True)); return 0


if __name__ == '__main__':
    sys.exit(main())
