#!/usr/bin/env python3
"""Validate a future schema-6 stopped-KIQ WPTR clear and derive its cleanup view."""

import copy
import re


HOST_KIQ_SELECTOR = 9
RING_DWORDS = 0x100
HQD_DOORBELL_OFFSET = 0xc860
PQ_STATUS_OFFSET = 0xc2e0
DOORBELL_ENABLE = 0x40000000
DOORBELL_HIT = 0x80000000
PQ_DOORBELL_ENABLE = 2
MEC_HALT = 0x50000000
ME_HALT = 0x15000000
WPTR_POLL_ENABLE = 0x80000000
UNMAP_GFX = [0xc004a300, 0x30000000, 0x400, 0, 0, 0]
WRITE_FENCE = [0xc0033700, 0x00100500]
SCRATCH_OFFSETS = {
    'ring':0x0f100000, 'mqd':0x0f110000, 'rptr':0x0f111000,
    'wptr':0x0f111008, 'eop':0x0f112000, 'fence':0x0f113000,
}
GLOBAL_KEYS = {
    'cp_stat', 'cpc_busy', 'me_cntl', 'mec_cntl', 'pq_wptr_poll_cntl',
    'pq_status', 'doorbell_range_lower', 'doorbell_range_upper',
    'sdma0_cntl', 'sdma0_f32_cntl', 'sdma0_status',
    'sdma0_gfx_rb_cntl', 'sdma0_gfx_ib_cntl',
    'sdma0_page_rb_cntl', 'sdma0_page_ib_cntl',
    'sdma0_rlc0_rb_cntl', 'sdma0_rlc0_ib_cntl',
    'sdma0_rlc1_rb_cntl', 'sdma0_rlc1_ib_cntl',
}
INPUT_KEYS = {
    'sdma0_gfx_rb_cntl', 'sdma0_gfx_ib_cntl',
    'sdma0_page_rb_cntl', 'sdma0_page_ib_cntl',
    'sdma0_rlc0_rb_cntl', 'sdma0_rlc0_ib_cntl',
    'sdma0_rlc1_rb_cntl', 'sdma0_rlc1_ib_cntl',
}
FINAL_GATE_KEYS = (
    'active_after', 'cp_stat_after', 'cp_cpc_busy_after',
    'pq_wptr_poll_after', 'pq_status_after',
    'doorbell_range_lower_after', 'doorbell_range_upper_after',
    'gfx_ring_clean', 'gfx_retirement_confirmed',
    'graphics_pipe_proof_complete',
)
CONTROL_KEYS = {
    'operation', 'offset', 'observed_before', 'written', 'readback',
    'witness_sequence', 'attempted', 'completed',
}
SELECTOR_KEYS = {'sequence', 'phase', 'value', 'attempted', 'completed'}
ORIGINAL_WPTR_ERROR = (
    'verify host KIQ wptr clear: RecoveryError: host KIQ wptr did not clear')
ORIGINAL_HOST_ERROR = 'host KIQ cleanup failed: ' + ORIGINAL_WPTR_ERROR
UNSUPPORTED_V2_STOPPED_WPTR = 'unsupported_v2_stopped_wptr'


def _dword(value):
    return type(value) is int and 0 <= value < 0xffffffff


def _queue_selector(me, pipe, queue):
    return pipe | (me << 2) | (queue << 8)


def _selector_row(sequence, phase, value):
    return {'sequence':sequence, 'phase':phase, 'value':value,
            'attempted':True, 'completed':True}


def _expected_scan_selectors(phase):
    rows = []
    for number in (1, 2):
        rows.append(_selector_row(
            len(rows), f'{phase}-pass-{number}-default', 0))
        for me in (1, 2):
            for pipe in range(4):
                for queue in range(8):
                    rows.append(_selector_row(
                        len(rows), f'{phase}-pass-{number}-compute',
                        _queue_selector(me, pipe, queue)))
    rows.append(_selector_row(len(rows), f'{phase}-final-default', 0))
    return rows


def _exact_selector_rows(rows, expected):
    return (isinstance(rows, list) and len(rows) == len(expected) and
            all(isinstance(row, dict) and set(row) == SELECTOR_KEYS and
                type(row.get('sequence')) is int and
                type(row.get('value')) is int and
                row.get('attempted') is True and row.get('completed') is True and
                row == wanted for row, wanted in zip(rows, expected)))


def _validate_graphics_snapshot(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != {'pipes', 'final_default'}:
        return False
    if snapshot.get('final_default') != {'value':0, 'completed':True}:
        return False
    pipes = snapshot.get('pipes')
    keys = {'intended_pipe','selector','rb0_active','rb1_active','active',
            'doorbell_control','doorbell_offset','doorbell_status','wptr',
            'wptr_hi','base','base_hi','cntl'}
    if not isinstance(pipes, list) or len(pipes) != 2:
        return False
    for index, row in enumerate(pipes):
        if (not isinstance(row, dict) or set(row) != keys or
                type(row.get('intended_pipe')) is not int or
                row.get('intended_pipe') != index or row.get('selector') != index or
                any(not _dword(row.get(key)) for key in keys - {'intended_pipe'})):
            return False
    return not (pipes[0]['active'] & 1 or pipes[1]['active'] & 1)


def _validate_globals(values):
    if (not isinstance(values, dict) or set(values) != GLOBAL_KEYS or
            any(not _dword(value) for value in values.values())):
        return False
    return (values['cp_stat'] == 0 and values['cpc_busy'] == 0 and
            values['me_cntl'] & ME_HALT == ME_HALT and
            values['mec_cntl'] & MEC_HALT == MEC_HALT and
            not (values['pq_wptr_poll_cntl'] & WPTR_POLL_ENABLE) and
            values['pq_status'] in (0, 1) and
            values['doorbell_range_lower'] == 0 and
            values['doorbell_range_upper'] == 0 and
            not (values['sdma0_cntl'] & 0x00040000) and
            values['sdma0_f32_cntl'] & 1 == 1 and
            values['sdma0_status'] & 1 == 1 and
            all(not (values[key] & 1) for key in INPUT_KEYS))


def _validate_compute(rows):
    keys = {'me','pipe','queue','selector','active','doorbell_control'}
    if not isinstance(rows, list) or len(rows) != 64:
        return False
    expected = [(me, pipe, queue) for me in (1, 2)
                for pipe in range(4) for queue in range(8)]
    for row, identity in zip(rows, expected):
        if (not isinstance(row, dict) or set(row) != keys or
                (row.get('me'), row.get('pipe'), row.get('queue')) != identity or
                row.get('selector') != _queue_selector(*identity) or
                not _dword(row.get('active')) or
                not _dword(row.get('doorbell_control')) or
                row['active'] & 1 or row['doorbell_control'] & DOORBELL_ENABLE):
            return False
        if (row['selector'] == HOST_KIQ_SELECTOR and
                row['doorbell_control'] not in (0, DOORBELL_HIT)):
            return False
    return True


def _validate_scan(scan, phase, before):
    expected_selectors = _expected_scan_selectors(phase)
    if (not isinstance(scan, dict) or
            set(scan) != {'passes','selector_writes','final_default'} or
            not _exact_selector_rows(scan.get('selector_writes'),
                                     expected_selectors)):
        return False
    expected_final = _selector_row(130, f'{phase}-final-default', 0)
    if not _exact_selector_rows([scan.get('final_default')], [expected_final]):
        return False
    passes = scan.get('passes')
    if not isinstance(passes, list) or len(passes) != 2 or passes[0] != passes[1]:
        return False
    sample = passes[0]
    if (not isinstance(sample, dict) or
            set(sample) != {'globals','compute','host_kiq'} or
            not _validate_globals(sample.get('globals')) or
            not _validate_compute(sample.get('compute'))):
        return False
    host = sample.get('host_kiq')
    if (not isinstance(host, dict) or
            set(host) != {'selector','dequeue','rptr','wptr_lo','wptr_hi'} or
            any(not _dword(host.get(key)) for key in host) or
            host['selector'] != HOST_KIQ_SELECTOR or host['dequeue'] != 0 or
            host['rptr'] != 0 or host['wptr_hi'] != 0):
        return False
    return host['wptr_lo'] == (RING_DWORDS if before else 0)


def _validate_stability(before, after):
    first = before['passes'][0]
    last = after['passes'][0]
    for key in GLOBAL_KEYS - {'pq_status'}:
        if first['globals'][key] != last['globals'][key]:
            return False
    if ((first['globals']['pq_status'] ^ last['globals']['pq_status']) & ~1 or
            first['globals']['pq_status'] & 2 or last['globals']['pq_status'] & 2):
        return False
    for old, new in zip(first['compute'], last['compute']):
        for key in ('me','pipe','queue','selector','active'):
            if old[key] != new[key]:
                return False
        if old['selector'] == HOST_KIQ_SELECTOR:
            if (old['doorbell_control'] ^ new['doorbell_control']) & ~DOORBELL_HIT:
                return False
        elif old['doorbell_control'] != new['doorbell_control']:
            return False
    old_host = first['host_kiq']
    new_host = last['host_kiq']
    return (all(old_host[key] == new_host[key]
                for key in ('selector','dequeue','rptr','wptr_hi')) and
            old_host['wptr_lo'] == RING_DWORDS and new_host['wptr_lo'] == 0)


def _control_row(row, operation, offset, observed, written, readback, sequence):
    return (isinstance(row, dict) and set(row) == CONTROL_KEYS and
            all(_dword(row.get(key)) for key in (
                'offset','observed_before','written','readback',
                'witness_sequence')) and
            row.get('operation') == operation and row.get('offset') == offset and
            row.get('observed_before') in observed and row.get('written') == written and
            row.get('readback') in readback and row.get('witness_sequence') == sequence and
            row.get('attempted') is True and row.get('completed') is True)


def _validate_transition(value):
    keys = {'selectors','hqd_enable','global_enable','doorbell','interim_samples',
            'gate_close','final_default','timing'}
    if not isinstance(value, dict) or set(value) != keys:
        return False
    selectors = [
        _selector_row(0, 'transition-select-kiq', HOST_KIQ_SELECTOR),
        _selector_row(1, 'transition-final-default', 0),
    ]
    if (not _exact_selector_rows(value.get('selectors'), selectors) or
            not _exact_selector_rows([value.get('final_default')],
                                     [selectors[-1]])):
        return False
    hqd = value.get('hqd_enable')
    if not _control_row(
            hqd, 'enable-hqd-doorbell', HQD_DOORBELL_OFFSET,
            (0, DOORBELL_HIT), DOORBELL_ENABLE,
            (DOORBELL_ENABLE, DOORBELL_ENABLE | DOORBELL_HIT), 0):
        return False
    global_enable = value.get('global_enable')
    if (not isinstance(global_enable, dict) or set(global_enable) != CONTROL_KEYS or
            global_enable.get('observed_before') not in (0, 1)):
        return False
    global_written = global_enable['observed_before'] | PQ_DOORBELL_ENABLE
    if not _control_row(
            global_enable, 'enable-global-pq-doorbell', PQ_STATUS_OFFSET,
            (global_enable['observed_before'],), global_written,
            (global_written,), 1):
        return False
    doorbell = value.get('doorbell')
    if (not isinstance(doorbell, dict) or
            any(type(doorbell.get(key)) is not int
                for key in ('index','value','width_bits','sequence')) or
            doorbell != {'index':0, 'value':0, 'width_bits':64, 'sequence':2,
                         'attempted':True, 'completed':True}):
        return False
    samples = value.get('interim_samples')
    if not isinstance(samples, list) or not samples:
        return False
    for sample in samples:
        if (not isinstance(sample, dict) or
                set(sample) != {'active','mec_cntl','wptr_lo','wptr_hi'} or
                any(not _dword(item) for item in sample.values()) or
                sample['active'] & 1 or sample['mec_cntl'] & MEC_HALT != MEC_HALT or
                sample['wptr_lo'] not in (0, RING_DWORDS) or
                sample['wptr_hi'] != 0):
            return False
    if samples[-1]['wptr_lo'] != 0 or samples[-1]['wptr_hi'] != 0:
        return False
    close = value.get('gate_close')
    if not isinstance(close, dict) or set(close) != {'global','hqd'}:
        return False
    global_close = close['global']
    if (not isinstance(global_close, dict) or set(global_close) != CONTROL_KEYS or
            global_close.get('observed_before') not in (2, 3)):
        return False
    global_written = global_close['observed_before'] & ~PQ_DOORBELL_ENABLE
    if not _control_row(
            global_close, 'disable-global-pq-doorbell', PQ_STATUS_OFFSET,
            (global_close['observed_before'],), global_written,
            (0, 1), 3):
        return False
    hqd_close = close['hqd']
    if (not isinstance(hqd_close, dict) or set(hqd_close) != CONTROL_KEYS or
            hqd_close.get('observed_before') not in
                (DOORBELL_ENABLE, DOORBELL_ENABLE | DOORBELL_HIT)):
        return False
    hqd_written = hqd_close['observed_before'] & ~DOORBELL_ENABLE
    if not _control_row(
            hqd_close, 'disable-hqd-doorbell', HQD_DOORBELL_OFFSET,
            (hqd_close['observed_before'],), hqd_written,
            (0, DOORBELL_HIT), 4):
        return False
    timing = value.get('timing')
    if (not isinstance(timing, dict) or
            set(timing) != {'observation_budget_ns','started_ns',
                            'through_global_close_ns'} or
            any(type(timing.get(key)) is not int or timing[key] < 0 for key in timing) or
            timing['observation_budget_ns'] != 2000000 or
            timing['through_global_close_ns'] < timing['started_ns'] or
            timing['through_global_close_ns'] - timing['started_ns'] >
                timing['observation_budget_ns']):
        return False
    return True


def _transition_matches_before(value, before):
    sample = before['passes'][0]
    target = next(row for row in sample['compute']
                  if row['selector'] == HOST_KIQ_SELECTOR)
    return (value['hqd_enable']['observed_before'] ==
                target['doorbell_control'] and
            value['global_enable']['observed_before'] ==
                sample['globals']['pq_status'])


def _validate_execution(gc):
    host = gc.get('host_kiq')
    if (not isinstance(host, dict) or set(host) != {'status','error','evidence'} or
            host.get('status') != 'failed' or host.get('error') != ORIGINAL_HOST_ERROR):
        return False
    evidence = host.get('evidence')
    evidence_keys = {'aperture','addresses','packet','fence_sequence',
                     'gfx_doorbell_offset','gart','reservation','hdp_flush',
                     'hdp_read_invalidate','terminal_poll','activation_readback',
                     'dequeue','retired_before_cleanup','cleanup'}
    if not isinstance(evidence, dict) or set(evidence) != evidence_keys:
        return False
    aperture = evidence.get('aperture')
    addresses = evidence.get('addresses')
    if (not isinstance(aperture, dict) or set(aperture) != {'base','size'} or
            type(aperture.get('base')) is not int or aperture['base'] <= 0 or
            type(aperture.get('size')) is not int or aperture['size'] <= 0 or
            not isinstance(addresses, dict) or set(addresses) != set(SCRATCH_OFFSETS) or
            addresses != {key:aperture['base'] + offset
                           for key, offset in SCRATCH_OFFSETS.items()}):
        return False
    packet = evidence.get('packet')
    if (not isinstance(packet, dict) or
            set(packet) != {'unmap','write_fence','ring_used_dwords'} or
            not isinstance(packet.get('unmap'), list) or
            not isinstance(packet.get('write_fence'), list) or
            any(type(value) is not int
                for value in packet.get('unmap') + packet.get('write_fence')) or
            type(packet.get('ring_used_dwords')) is not int or
            packet != {'unmap':UNMAP_GFX, 'write_fence':WRITE_FENCE,
                       'ring_used_dwords':RING_DWORDS}):
        return False
    fence = evidence.get('fence_sequence')
    terminal = evidence.get('terminal_poll')
    if (type(fence) is not int or not 1 <= fence <= 0xffffffff or
            not isinstance(terminal, dict) or
            set(terminal) != {'polls','rptr','report','fence'} or
            any(not _dword(terminal.get(key)) for key in terminal) or
            terminal['polls'] < 1 or terminal['fence'] != fence or
            RING_DWORDS not in (terminal['rptr'], terminal['report'])):
        return False
    invalidate = evidence.get('hdp_read_invalidate')
    if (not isinstance(invalidate, dict) or set(invalidate) != {'count','last'} or
            type(invalidate.get('count')) is not int or invalidate['count'] < 1 or
            invalidate['count'] != terminal['polls'] or
            not isinstance(invalidate.get('last'), dict) or
            type(invalidate['last'].get('register')) is not int or
            type(invalidate['last'].get('trigger')) is not int or
            not _dword(invalidate['last'].get('posted_read')) or
            invalidate['last'].get('register') != 0x3fc4 or
            invalidate['last'].get('trigger') != 1 or
            set(invalidate['last']) != {'register','trigger','posted_read'}):
        return False
    dequeue = evidence.get('dequeue')
    activation = evidence.get('activation_readback')
    if (not _dword(activation) or not (activation & 1) or
            not isinstance(dequeue, dict) or
            set(dequeue) != {'write_value','active_samples','observed_inactive'} or
            type(dequeue.get('write_value')) is not int or
            dequeue.get('write_value') != 1 or
            dequeue.get('observed_inactive') is not True or
            not isinstance(dequeue.get('active_samples'), list) or
            not dequeue['active_samples'] or
            any(not _dword(value) for value in dequeue['active_samples']) or
            dequeue['active_samples'][-1] & 1):
        return False
    retired = evidence.get('retired_before_cleanup')
    retired_keys = {'status','selector','packet_dwords','rptr_after',
                    'fence_sequence','fence_after','gfx_active_after_unmap',
                    'graphics_pipes_after_unmap','gfx_doorbell_offset','addresses',
                    'gart','reservation','hdp_flush'}
    if (not isinstance(retired, dict) or set(retired) != retired_keys or
            retired.get('status') != 'retired' or
            any(type(retired.get(key)) is not int for key in (
                'selector','packet_dwords','rptr_after','fence_sequence',
                'fence_after','gfx_active_after_unmap','gfx_doorbell_offset')) or
            retired.get('selector') != HOST_KIQ_SELECTOR or
            retired.get('packet_dwords') != RING_DWORDS or
            retired.get('rptr_after') != RING_DWORDS or
            retired.get('fence_sequence') != fence or
            retired.get('fence_after') != fence or
            retired.get('gfx_active_after_unmap') != 0 or
            retired.get('gfx_doorbell_offset') != 0x400 or
            retired.get('addresses') != addresses or
            retired.get('gart') != evidence.get('gart') or
            retired.get('reservation') != evidence.get('reservation') or
            retired.get('hdp_flush') != evidence.get('hdp_flush') or
            not _validate_graphics_snapshot(
                retired.get('graphics_pipes_after_unmap'))):
        return False
    cleanup = evidence.get('cleanup')
    cleanup_keys = {'mec_cntl','hqd_active','hqd_doorbell','hqd_rptr',
                    'hqd_wptr_lo','hqd_wptr_hi','pq_status',
                    'doorbell_range_lower','doorbell_range_upper','wptr_poll_cntl'}
    if (not isinstance(cleanup, dict) or set(cleanup) != {'readbacks','errors'} or
            cleanup.get('errors') != [ORIGINAL_WPTR_ERROR] or
            not isinstance(cleanup.get('readbacks'), dict) or
            set(cleanup['readbacks']) != cleanup_keys):
        return False
    readbacks = cleanup['readbacks']
    return (all(_dword(readbacks[key]) for key in cleanup_keys - {'hqd_wptr_hi'}) and
            readbacks['mec_cntl'] & MEC_HALT == MEC_HALT and
            readbacks['hqd_active'] == 0 and
            readbacks['hqd_doorbell'] in (0, DOORBELL_HIT) and
            readbacks['hqd_rptr'] == 0 and
            readbacks['hqd_wptr_lo'] == RING_DWORDS and
            readbacks['hqd_wptr_hi'] is None and
            _dword(readbacks['pq_status']) and
            not (readbacks['pq_status'] & PQ_DOORBELL_ENABLE) and
            readbacks['doorbell_range_lower'] == 0 and
            readbacks['doorbell_range_upper'] == 0 and
            _dword(readbacks['wptr_poll_cntl']) and
            not (readbacks['wptr_poll_cntl'] & WPTR_POLL_ENABLE))


def _validation_errors(receipt):
    errors = []
    if not isinstance(receipt, dict) or receipt.get('schema') != 6:
        return ['schema6_stopped_wptr_proof']
    prior = receipt.get('prior_run_id')
    if not re.fullmatch(r'[0-9a-f]{32}', str(prior or '')):
        errors.append('prior_run_id')
    gc = receipt.get('gc_quiesce')
    if not isinstance(gc, dict):
        return sorted(set(errors + ['gc_quiesce']))
    # Schema 2 relocates every KIQ scratch object into a guest-owned lease.
    # The stopped-WPTR proof below is intentionally frozen to the historical
    # fixed schema-1 layout until its full scan/transition contract is revised.
    if isinstance(gc.get('reservation'), dict) and \
            gc['reservation'].get('schema') == 2:
        return [UNSUPPORTED_V2_STOPPED_WPTR]
    if (type(gc.get('forced_inactive')) is not int or
            gc.get('forced_inactive') != 0 or not _validate_execution(gc)):
        errors.append('host_kiq_execution')
    proof = gc.get('stopped_wptr_doorbell_clear')
    if (not isinstance(proof, dict) or
            set(proof) != {'status','eligibility','before','transition','after'} or
            proof.get('status') != 'cleared' or
            not isinstance(proof.get('eligibility'), dict) or
            set(proof['eligibility']) != {'eligible','errors'}):
        errors.append('stopped_wptr_shape')
        return sorted(set(errors))
    before = proof.get('before')
    after = proof.get('after')
    before_valid = _validate_scan(before, 'before', True)
    after_valid = _validate_scan(after, 'after', False)
    if not before_valid:
        errors.append('stopped_wptr_before')
    transition_valid = _validate_transition(proof.get('transition'))
    if (transition_valid and before_valid and
            not _transition_matches_before(proof['transition'], before)):
        transition_valid = False
    if not transition_valid:
        errors.append('stopped_wptr_transition')
    if not after_valid:
        errors.append('stopped_wptr_after')
    if (before_valid and after_valid and
            not _validate_stability(before, after)):
        errors.append('stopped_wptr_stability')
    raw_host = gc.get('host_kiq')
    evidence = raw_host.get('evidence', {}) if isinstance(raw_host, dict) else {}
    retired = evidence.get('retired_before_cleanup')
    if (not isinstance(retired, dict) or
            retired.get('reservation') != gc.get('reservation') or
            retired.get('graphics_pipes_after_unmap') !=
                gc.get('graphics_pipes_after_retirement')):
        errors.append('parent_retirement_identity')
    if any(type(gc.get(key)) is not int for key in (
            'active_after','cp_stat_after','cp_cpc_busy_after',
            'doorbell_range_lower_after','doorbell_range_upper_after')) or \
            gc.get('active_after') != 0 or gc.get('cp_stat_after') != 0 or \
            gc.get('cp_cpc_busy_after') != 0 or \
            not _dword(gc.get('pq_wptr_poll_after')) or \
            gc['pq_wptr_poll_after'] & WPTR_POLL_ENABLE or \
            not _dword(gc.get('pq_status_after')) or \
            gc['pq_status_after'] & PQ_DOORBELL_ENABLE or \
            gc.get('doorbell_range_lower_after') != 0 or \
            gc.get('doorbell_range_upper_after') != 0 or \
            gc.get('gfx_ring_clean') is not True or \
            gc.get('gfx_retirement_confirmed') is not True or \
            gc.get('graphics_pipe_proof_complete') is not True:
        errors.append('parent_final_gate')
    if isinstance(gc.get('reservation'), dict) and \
            gc['reservation'].get('run_id') != prior:
        errors.append('parent_reservation')
    return sorted(set(errors))


def derive_effective_host_kiq(receipt):
    """Return a derived retired host-KIQ view without changing the raw receipt."""
    try:
        errors = _validation_errors(receipt)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None, ['schema6_stopped_wptr_proof']
    if errors:
        return None, errors
    gc = receipt['gc_quiesce']
    evidence = gc['host_kiq']['evidence']
    retired = copy.deepcopy(evidence['retired_before_cleanup'])
    final = gc['stopped_wptr_doorbell_clear']['after']['passes'][0]
    target = next(row for row in final['compute']
                  if row['selector'] == HOST_KIQ_SELECTOR)
    retired.update({
        'gfx_active_before_scrub':retired['gfx_active_after_unmap'],
        'cleanup_confirmed':True,
        'cleanup':{
            'mec_cntl':final['globals']['mec_cntl'],
            'hqd_active':target['active'],
            'hqd_doorbell':target['doorbell_control'],
            'hqd_rptr':final['host_kiq']['rptr'],
            'hqd_wptr_lo':final['host_kiq']['wptr_lo'],
            'hqd_wptr_hi':final['host_kiq']['wptr_hi'],
            'pq_status':final['globals']['pq_status'],
            'doorbell_range_lower':final['globals']['doorbell_range_lower'],
            'doorbell_range_upper':final['globals']['doorbell_range_upper'],
            'wptr_poll_cntl':final['globals']['pq_wptr_poll_cntl'],
        },
        'final_gate':{key:copy.deepcopy(gc[key]) for key in FINAL_GATE_KEYS},
    })
    return {'source':'stopped_wptr_doorbell_clear',
            'host_kiq':retired}, []
