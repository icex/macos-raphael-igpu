#!/usr/bin/env python3
"""Classify sequenced critical records; never infer execution from enumeration."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import struct

ENTRY_MC_BASE = 0xf400000000
ENTRY_PHYSICAL_BASE = 0x840000000
ENTRY_APERTURE_SIZE = 0x20000000
ENTRY_CHILD_CALLER = 0x55a72
ENTRY_UPDATE_COUNT_KEYS = (
    'converted', 'physical', 'outside', 'system', 'invalid_template',
    'invalid_aperture', 'empty', 'overflow', 'span', 'zero')
ENTRY_UPDATE_OMISSION_KEYS = ('child', 'eligible', 'control')


def _recovery_lease_v2():
    path = Path(__file__).with_name('recovery_lease_v2.py')
    spec = importlib.util.spec_from_file_location('recovery_lease_v2_classifier', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _critical_replay():
    path = Path(__file__).with_name('critical-replay.py')
    spec = importlib.util.spec_from_file_location('critical_replay_classifier', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _decode_payload(build, seq, payload):
    row = dict(build=build, seq=seq, kind='other', raw=payload)
    if payload == 'BUILD: identity='+str(build):
        row['kind'] = 'build'
    elif 'HY: HWLibs hybrid trace' in payload:
        row.update(kind='route', ok='route=ok entries-match=1' in payload)
    elif 'HY: SDMA selector trace' in payload:
        row.update(kind='sdma_route', ok='route=ok entries-match=1' in payload)
    elif payload.startswith('VM: route AMDGFX10VMM::prepareVMInvalidateRequest ->'):
        row.update(kind='vm_program_route', ok='-> ok ' in payload)
    elif payload.startswith('SD: topology routes='):
        m = re.fullmatch(r'SD: topology routes=(ok|FAILED) count=(\d+) entries-match=([01])',
                         payload)
        row.update(kind='sdma_topology_route', count=int(m[2]) if m else 0,
                   ok=bool(m and m[1] == 'ok' and m[3] == '1'))
    elif m := re.fullmatch(
            r'SUB: routes=(ok|FAILED) count=(\d+) entries-match=([01]) '
            r'capture=(armed|disabled)', payload):
        row.update(kind='submission_trace_route', count=int(m[2]),
                   entries_match=bool(int(m[3])), capture=m[4],
                   ok=(m[1] == 'ok' and m[2] in ('5', '6', '7') and m[3] == '1' and
                       m[4] == 'armed'))
    elif payload.startswith('SUB: routes='):
        row.update(kind='submission_trace_route', ok=False, malformed=True)
    elif m := re.fullmatch(
            r'SUB: summary process=(\d+)/(\d+)/(\d+) '
            r'mappings=(\d+)/(\d+)/(\d+) prepare=(\d+)/(\d+)/(\d+) '
            r'map=(\d+)/(\d+)/(\d+) submit=(\d+)/(\d+)/(\d+) '
            r'dropped=(\d+)/(\d+)', payload):
        values = [int(m[index]) for index in range(1, 18)]
        row.update(kind='submission_trace_summary', ok=True,
                   counts=[values[index:index + 3] for index in range(0, 15, 3)],
                   dropped=values[15:17])
    elif payload.startswith('SUB: summary'):
        row.update(kind='submission_trace_summary', ok=False, malformed=True)
    elif m := re.fullmatch(
            r'SUB: map-phase seq=(\d+) '
            r'class=(capacity|va-allocation-reclaim|backing-pte|unknown) '
            r'accel=(0x[0-9a-fA-F]+|0) map=(0x[0-9a-fA-F]+|0) '
            r'thread=(0x[0-9a-fA-F]+|0) '
            r'pre=(\d+)/(\d+)/(0x[0-9a-fA-F]+|0)/(0x[0-9a-fA-F]+|0) '
            r'post=(\d+)/(\d+)/(0x[0-9a-fA-F]+|0)/(0x[0-9a-fA-F]+|0)',
            payload):
        row.update(kind='submission_map_phase', observation_sequence=int(m[1]),
                   classification=m[2], accelerator=int(m[3], 16),
                   memory_map=int(m[4], 16), thread=int(m[5], 16),
                   before=[int(m[6]), int(m[7]), int(m[8], 16), int(m[9], 16)],
                   after=[int(m[10]), int(m[11]), int(m[12], 16), int(m[13], 16)])
    elif payload.startswith('SUB: map-phase seq='):
        row.update(kind='submission_map_phase', ok=False, malformed=True)
    elif m := re.fullmatch(
            r'SUB: map-phase-summary total=(\d+) capacity=(\d+) va=(\d+) '
            r'backing-pte=(\d+) unknown=(\d+) dropped=(\d+)/(\d+)/(\d+)/(\d+)',
            payload):
        values = [int(m[index]) for index in range(1, 10)]
        consistent = values[0] == sum(values[1:5])
        row.update(kind='submission_map_phase_summary', ok=consistent,
                   malformed=not consistent, total=values[0],
                   counts=values[1:5], dropped=values[5:9])
    elif payload.startswith('SUB: map-phase-summary'):
        row.update(kind='submission_map_phase_summary', ok=False, malformed=True)
    elif m := re.fullmatch(
            r'SUB: backing seq=(\d+) object=(0x[0-9a-fA-F]+|0) '
            r'thread=(0x[0-9a-fA-F]+|0) (?:pool=\d+ )?result=([01]) '
            r'pre=([01])/(0x[0-9a-fA-F]+|0)/(0x[0-9a-fA-F]+|0)/'
            r'(0x[0-9a-fA-F]+|0)/(0x[0-9a-fA-F]+|0)/(0x[0-9a-fA-F]+|0) '
            r'post=([01])/(0x[0-9a-fA-F]+|0)/(0x[0-9a-fA-F]+|0)/'
            r'(0x[0-9a-fA-F]+|0)/(0x[0-9a-fA-F]+|0)/(0x[0-9a-fA-F]+|0) '
            r'(?:counters=\d+/\d+->\d+/\d+ )?state=live', payload):
        def snapshot(start):
            return dict(available=bool(int(m[start])), length=int(m[start + 1], 16),
                        owner=int(m[start + 2], 16), element=int(m[start + 3], 16),
                        raw120=int(m[start + 4], 16), flags=int(m[start + 5], 16))
        failure_sample = m[4] == '0'
        row.update(kind='submission_backing_allocation', ok=failure_sample,
                   malformed=not failure_sample,
                   observation_sequence=int(m[1]), backing=int(m[2], 16),
                   thread=int(m[3], 16), result=bool(int(m[4])),
                   before=snapshot(5), after=snapshot(11), state='live')
        pool = re.search(r'\bpool=(\d+)\b', payload)
        counters = re.search(r'\bcounters=(\d+)/(\d+)->(\d+)/(\d+)\b', payload)
        if pool:
            row['pool'] = int(pool[1])
        if counters:
            row['counters'] = {
                'successful_before': int(counters[1]),
                'failed_before': int(counters[2]),
                'successful_after': int(counters[3]),
                'failed_after': int(counters[4]),
            }
    elif payload.startswith('SUB: backing seq='):
        row.update(kind='submission_backing_allocation', ok=False, malformed=True)
    elif m := re.fullmatch(
            r'SUB: backing-summary completed=(\d+) true=(\d+) false=(\d+) '
            r'dropped=(\d+) state=live', payload):
        completed, successful, failed, dropped = map(int, m.groups())
        consistent = completed == successful + failed
        row.update(kind='submission_backing_allocation_summary', ok=consistent,
                   malformed=not consistent, completed=completed,
                   successful=successful, failed=failed, dropped=dropped,
                   state='live')
    elif payload.startswith('SUB: backing-summary'):
        row.update(kind='submission_backing_allocation_summary', ok=False,
                   malformed=True)
    elif payload.startswith('XH2 OWNED'):
        row.update(kind='recovery_lease_owned')
    elif payload.startswith('XH2 POOL'):
        row.update(kind='recovery_lease_pool')
    elif payload.startswith('XH2 '):
        row.update(kind='recovery_lease_wire', ok=False, malformed=True)
    elif m := re.fullmatch(
            r'XV2 VMM phase=(early|native) enable=(\d+) '
            r'base=(0|0x[1-9a-f][0-9a-f]*) '
            r'arena=(0|0x[0-9a-f]+) '
            r'pool0=(0|0x[0-9a-f]+) '
            r'pool1=(0|0x[0-9a-f]+)', payload):
        row.update(kind='vmm_readiness', phase=m[1], enable=int(m[2]),
                   base=int(m[3], 16), arena=int(m[4], 16),
                   pool0=int(m[5], 16), pool1=int(m[6], 16), ok=True)
    elif payload.startswith('XV2 VMM'):
        row.update(kind='vmm_readiness', ok=False, malformed=True)
    elif payload == 'SD: topology applied: discovered=1 kept=SDMA0 removed=SDMA1 before initialize':
        row.update(kind='sdma_topology', applied=True)
    elif payload.startswith('SD: topology NOT applied:'):
        row.update(kind='sdma_topology', applied=False)
    elif m := re.fullmatch(r'SD: AMDHardware::initializeHWEngines -> (\d+) \(topology-applied=([01])\)', payload):
        row.update(kind='sdma_initialize', result=int(m[1]), applied=bool(int(m[2])))
    elif m := re.match(r'SD: one-instance start -> (\d+) \(SDMA0=\S+ SDMA1=\S+\)$', payload):
        row.update(kind='sdma_one_start', result=int(m[1]))
    elif m := re.search(r'HY: SDMA select index=(\d+) queue-type=(\d+) found=([01]) counts=(\d+),(\d+),(\d+),(\d+)', payload):
        row.update(kind='sdma_select', index=int(m[1]), queue_type=int(m[2]),
                   found=bool(int(m[3])), counts=[int(m[i]) for i in range(4,8)])
    elif m := re.search(r'submitKIQFrame -> (\d+)(?: caller=x6\+(0x[0-9a-fA-F]+))?',
                        payload):
        row.update(kind='kiq_submit', result=int(m[1]))
        if m[2] is not None: row['caller'] = int(m[2], 16)
    elif m := re.search(r'waitForHwStamp\((\d+)\) -> (\d+)'
                        r'(?: caller=x6\+(0x[0-9a-fA-F]+))?', payload):
        row.update(kind='kiq', stamp=int(m[1]), result=int(m[2]))
        if m[3] is not None: row['caller'] = int(m[3], 16)
    elif m := re.search(r'HY: createHybridEngine enter: engine=(\d+) available=(\d+)', payload):
        row.update(kind='hybrid_enter', engine=int(m[1]), available=int(m[2]))
    elif m := re.search(r'HY: createHybridEngine exit: engine=(\d+) valid=(\d+) available-before=(\d+) status=(\d+)', payload):
        row.update(kind='hybrid_exit', engine=int(m[1]), arguments_valid=int(m[2]),
                   available=int(m[3]), result=int(m[4]))
    elif m := re.search(r'AMDHardware::startHWEngines -> (\d+)', payload):
        row.update(kind='engine_start', result=int(m[1]))
    elif m := re.search(r'AMDGraphicsAccelerator::powerUpHW -> (\d+)', payload):
        row.update(kind='accelerator_start', result=int(m[1]))
    elif m := re.search(r'SD: channel engine remap (\d+) -> (\d+)', payload):
        row.update(kind='sdma_engine_remap', requested=int(m[1]), selected=int(m[2]))
    elif m := re.fullmatch(r'SD: submit IB\[(\d+)\] (0x[0-9a-fA-F]+) -> (0x[0-9a-fA-F]+) recognized=([01]) entries=(\d+) changed-total=(\d+)', payload):
        row.update(kind='sdma_ib_repair', index=int(m[1]), before=int(m[2], 16),
                   after=int(m[3], 16), valid=bool(int(m[4])), entries=int(m[5]),
                   changed_total=int(m[6]), changed=int(m[6]) > 0)
    elif m := re.fullmatch(r'SD: submit vmid=(\d+) flags=(0x[0-9a-fA-F]+|0) entries=(\d+) valid=([01]) IB0=(0x[0-9a-fA-F]+|0) IB1=(0x[0-9a-fA-F]+|0)(?: seq=(\d+))?', payload):
        row.update(kind='sdma_submit', vmid=int(m[1]), flags=int(m[2], 16),
                   entries=int(m[3]), valid=bool(int(m[4])), ib0=int(m[5], 16),
                   ib1=int(m[6], 16))
        if m[7] is not None: row['vm_sequence'] = int(m[7])
    elif m := re.fullmatch(r'VM: invalidate hub=(\d+) vmid=(\d+) start=(0x[0-9a-fA-F]+|0) end=(0x[0-9a-fA-F]+|0) root=(0x[0-9a-fA-F]+|0) flags=(0x[0-9a-fA-F]+|0) reprogram=([01])', payload):
        row.update(kind='vm_invalidate', hub=int(m[1]), vmid=int(m[2]),
                   start=int(m[3], 16), end=int(m[4], 16), root=int(m[5], 16),
                   flags=int(m[6], 16), reprogram=bool(int(m[7])))
    elif m := re.fullmatch(r'VM: prepared hub=(\d+) vmid=(\d+) start=(0x[0-9a-fA-F]+|0) end=(0x[0-9a-fA-F]+|0) root=(0x[0-9a-fA-F]+|0) flags=(0x[0-9a-fA-F]+|0) reprogram=([01]) alternate=([01]) info=((?:[0-9a-fA-F]{8},){9}[0-9a-fA-F]{8}) words=((?:[0-9a-fA-F]{8},){20}[0-9a-fA-F]{8})', payload):
        row.update(kind='vm_program', hub=int(m[1]), vmid=int(m[2]),
                   start=int(m[3], 16), end=int(m[4], 16), root=int(m[5], 16),
                   flags=int(m[6], 16), reprogram=bool(int(m[7])),
                   alternate=bool(int(m[8])),
                   info_words=[int(value, 16) for value in m[9].split(',')],
                   words=[int(value, 16) for value in m[10].split(',')])
    elif m := re.fullmatch(r'VM: entry-gate init marked=([01]) aperture=([01]) mode=(\d+)', payload):
        row.update(kind='vm_entry_gate', marked=bool(int(m[1])),
                   aperture=bool(int(m[2])), mode=int(m[3]))
    elif m := re.fullmatch(r'VM: entry-conv mode=(\d+) routes=([01])/([01]) pde=(\d+)/(\d+)/(\d+)/(\d+)/(\d+) pte=(\d+)/(\d+)/(\d+)/(\d+)/(\d+)(?: inactive=(\d+)/(\d+))? dropped=(\d+)/(\d+)', payload):
        row.update(kind='vm_entry_conversion', mode=int(m[1]),
                   pde_route=bool(int(m[2])), pte_route=bool(int(m[3])),
                   pde={'converted':int(m[4]), 'physical':int(m[5]), 'outside':int(m[6]),
                        'system':int(m[7]), 'invalid':int(m[8])},
                   pte={'converted':int(m[9]), 'physical':int(m[10]), 'outside':int(m[11]),
                        'system':int(m[12]), 'invalid':int(m[13])},
                   inactive=(int(m[14] or 0), int(m[15] or 0)),
                   dropped_samples=(int(m[16]), int(m[17])))
    elif m := re.fullmatch(r'VM: entry-sample kind=(pde|pte) level=(\d+) flags=(0x[0-9a-fA-F]+|0) original=(0x[0-9a-fA-F]+|0) result=(0x[0-9a-fA-F]+|0)(?: domain=([a-z-]+))?', payload):
        row.update(kind='vm_entry_sample', entry=m[1], level=int(m[2]),
                   flags=int(m[3], 16), original=int(m[4], 16), result=int(m[5], 16),
                   domain=m[6])
    elif m := re.fullmatch(
            r'VM: fault-walk vmid=(\d+) status=(0x[0-9a-fA-F]+|0) '
            r'fault-va=(0x[0-9a-fA-F]+|0) cid=(\d+) walker=(\d+) '
            r'permission=(0x[0-9a-fA-F]+|0) mapping=([01]) rw=([01]) atomic=([01]) '
            r'ctl=(0x[0-9a-fA-F]+|0) root=(0x[0-9a-fA-F]+|0) '
            r'start=(0x[0-9a-fA-F]+|0) end=(0x[0-9a-fA-F]+|0) aperture=([01]) '
            r'context-stable=([01]) address-in-context=([01]) '
            r'timing=worker-after-latch tables-non-atomic=1', payload):
        values = [int(m[index], 16) for index in (2, 3, 6, 10, 11, 12, 13)]
        status, fault_va, permission, control, root, start, end = values
        address_in_context = bool(int(m[16]))
        decoded = {
            'walker': (status >> 1) & 7, 'permission': (status >> 4) & 0xf,
            'mapping': (status >> 8) & 1, 'cid': (status >> 9) & 0x1ff,
            'write': (status >> 18) & 1, 'atomic': (status >> 19) & 1,
            'vmid': (status >> 20) & 0xf,
        }
        valid = (int(m[1]) == decoded['vmid'] and 1 <= decoded['vmid'] < 16 and int(m[4]) == decoded['cid'] and
                 int(m[5]) == decoded['walker'] and permission == decoded['permission'] and
                 int(m[7]) == decoded['mapping'] and int(m[8]) == decoded['write'] and
                 int(m[9]) == decoded['atomic'] and
                 status <= 0xffffffff and control <= 0xffffffff and
                 all(value <= 0xffffffffffffffff
                     for value in (fault_va, root, start, end)) and
                 address_in_context == (start <= fault_va <= end))
        if valid:
            row.update(kind=('vmid1_fault_walk' if decoded['vmid'] == 1 else 'client_fault_walk'), vmid=decoded['vmid'], status=status,
                       fault_va=fault_va, cid=int(m[4]), walker_error=int(m[5]),
                       permission_faults=permission, mapping_error=bool(int(m[7])),
                       write=bool(int(m[8])), atomic=bool(int(m[9])), control=control,
                       root=root, context={'start':start, 'end':end},
                       aperture=bool(int(m[14])), context_stable=bool(int(m[15])),
                       context_bounds_valid=start <= end,
                       address_in_context=address_in_context)
        else:
            row.update(kind='capture_loss', reason='malformed client fault-walk record',
                       definitive=True)
    elif payload.startswith('VM: fault-walk vmid='):
        row.update(kind='capture_loss', reason='malformed client fault-walk record',
                   definitive=True)
    elif m := re.fullmatch(
            r'VM: fault-walk-view status=(0x[0-9a-fA-F]+|0) '
            r'fault-va=(0x[0-9a-fA-F]+|0) view=(relative|absolute) '
            r'valid=([01]) complete=([01]) count=(\d+)', payload):
        status, fault_va, count = int(m[1], 16), int(m[2], 16), int(m[6])
        vmid = (status >> 20) & 0xf
        if (status <= 0xffffffff and fault_va <= 0xffffffffffffffff and count <= 4 and
                1 <= vmid < 16):
            row.update(kind=('vmid1_fault_walk_view' if vmid == 1 else
                             'client_fault_walk_view'), vmid=vmid, status=status,
                       fault_va=fault_va, view=m[3], valid=bool(int(m[4])),
                       complete=bool(int(m[5])), count=count)
        else:
            row.update(kind='capture_loss',
                       reason='malformed client fault-walk view record', definitive=True)
    elif payload.startswith('VM: fault-walk-view status='):
        row.update(kind='capture_loss', reason='malformed client fault-walk view record',
                   definitive=True)
    elif m := re.fullmatch(
            r'VM: fault-walk-entry status=(0x[0-9a-fA-F]+|0) '
            r'fault-va=(0x[0-9a-fA-F]+|0) view=(relative|absolute) n=(\d+) '
            r'level=(\d+) index=(\d+) table=(0x[0-9a-fA-F]+|0) '
            r'raw=(0x[0-9a-fA-F]+|0) entry-addr=(0x[0-9a-fA-F]+|0) '
            r'V=([01]) S=([01]) X=([01]) R=([01]) W=([01]) P=([01]) TF=([01]) '
            r'mc2pa-eligible=([01]) child-mc2pa=([01])', payload):
        status, fault_va = int(m[1], 16), int(m[2], 16)
        number, level, index = int(m[4]), int(m[5]), int(m[6])
        table, raw, address = int(m[7], 16), int(m[8], 16), int(m[9], 16)
        emitted = tuple(int(m[position]) for position in range(10, 18))
        pde_as_pte = bool(raw & (1 << 54))
        leaf = level == 0 or pde_as_pte
        decoded = (
            bool(raw & (1 << 0)), bool(raw & (1 << 1)),
            bool(raw & (1 << 4)), bool(raw & (1 << 5)),
            bool(raw & (1 << 6)), pde_as_pte,
            bool(raw & (1 << 56)), not bool(raw & (1 << 1)) and not pde_as_pte,
        )
        decoded_address = raw & (0x0000fffffffff000 if leaf else
                                 0x0000ffffffffffc0)
        vmid = (status >> 20) & 0xf
        valid = (status <= 0xffffffff and 1 <= vmid < 16 and number < 4 and level < 4 and
                 all(value <= 0xffffffffffffffff
                     for value in (fault_va, index, table, raw, address)) and
                 emitted == tuple(int(value) for value in decoded) and
                 address == decoded_address)
        if valid:
            names = ('valid', 'system', 'executable', 'readable', 'writeable',
                     'pde_as_pte', 'translate_further', 'mc2pa_eligible',
                     'child_converted')
            row.update(kind=('vmid1_fault_walk_entry' if vmid == 1 else
                             'client_fault_walk_entry'), vmid=vmid, status=status,
                       fault_va=fault_va, view=m[3], number=number, level=level,
                       index=index, table=table, raw_entry=raw, address=address,
                       attributes={name:bool(int(m[position]))
                                   for name, position in zip(names, range(10, 19))})
        else:
            row.update(kind='capture_loss',
                       reason='malformed client fault-walk entry record', definitive=True)
    elif payload.startswith('VM: fault-walk-entry status='):
        row.update(kind='capture_loss', reason='malformed client fault-walk entry record',
                   definitive=True)
    elif m := re.fullmatch(
            r'VM: map-process-summary retained=(\d+) dropped=(\d+)', payload):
        retained, dropped = int(m[1]), int(m[2])
        if retained <= 8 and dropped <= 0xffffffffffffffff:
            row.update(kind='vm_map_process_summary', retained=retained,
                       dropped=dropped, ok=True)
        else:
            row.update(kind='capture_loss', reason='malformed map-process-summary record',
                       definitive=True)
    elif payload.startswith('VM: map-process-summary'):
        row.update(kind='capture_loss', reason='malformed map-process-summary record',
                   definitive=True)
    elif m := re.fullmatch(
            r'VM: map-process-root input=(0x[0-9a-fA-F]+|0) '
            r'native=(0x[0-9a-fA-F]+|0) final=(0x[0-9a-fA-F]+|0) '
            r'pasid=(\d+) header=(0x[0-9a-fA-F]+|0) return-valid=([01]) '
            r'repaired=([01]) reason=(\d+)', payload):
        input_root, native_root, final_root = (int(m[index], 16) for index in (1, 2, 3))
        pasid, header, reason = int(m[4]), int(m[5], 16), int(m[8])
        return_valid, repaired = bool(int(m[6])), bool(int(m[7]))
        valid = (all(value <= 0xffffffffffffffff for value in
                     (input_root, native_root, final_root)) and
                 pasid <= 0xffffffff and header <= 0xffffffff and reason <= 13 and
                 ((repaired and return_valid and header == 0xc00ea100 and
                   reason == 12 and native_root != final_root) or
                  (not repaired and
                  ((return_valid and native_root == final_root) or
                    (not return_valid and native_root == 0 and final_root == 0 and
                     header == 0 and reason == 0)))))
        if valid:
            row.update(kind='vm_map_process_root', input_root=input_root,
                       native_root=native_root, final_root=final_root, pasid=pasid,
                       header=header, return_valid=return_valid,
                       repaired=repaired, reason=reason, ok=True,
                       guard_valid=return_valid and header == 0xc00ea100)
        else:
            row.update(kind='capture_loss', reason='malformed map-process-root record',
                       definitive=True)
    elif payload.startswith('VM: map-process-root'):
        row.update(kind='capture_loss', reason='malformed map-process-root record',
                   definitive=True)
    elif m := re.fullmatch(
            r'VM: route AMDGFX10HIQHWChannel::fillMapProcessPacket -> '
            r'(ok|FAILED) \(entry=([01]) org=(0x[0-9a-fA-F]+)\)', payload):
        original = int(m[3], 16)
        if original <= 0xffffffffffffffff:
            row.update(kind='vm_map_process_route', ok=m[1] == 'ok',
                       entry=bool(int(m[2])), original=original)
        else:
            row.update(kind='vm_map_process_route', ok=False, malformed=True)
    elif payload.startswith(
            'VM: route AMDGFX10HIQHWChannel::fillMapProcessPacket'):
        row.update(kind='vm_map_process_route', ok=False, malformed=True)
    elif m := re.fullmatch(
            r'VM: route AMDHWVMContext::updateContiguousPTEsWithDMAUsingAddr '
            r'-> (ok|FAILED) \(entry=([01]) org=(0x[0-9a-fA-F]+)\)', payload):
        row.update(kind='vm_entry_update_route', ok=m[1] == 'ok',
                   entry=bool(int(m[2])), original=int(m[3], 16))
    elif payload.startswith(
            'VM: route AMDHWVMContext::updateContiguousPTEsWithDMAUsingAddr'):
        row.update(kind='vm_entry_update_route', ok=False, malformed=True)
    elif m := re.fullmatch(
            r'VM: entry-update mode=(\d+) route=([01]) inactive=(\d+) '
            r'converted=(\d+) physical=(\d+) outside=(\d+) system=(\d+) '
            r'invalid-template=(\d+) invalid-aperture=(\d+) empty=(\d+) '
            r'overflow=(\d+) span=(\d+) zero=(\d+) '
            r'omitted-child=(\d+) omitted-eligible=(\d+) omitted-control=(\d+)',
            payload):
        names = ('converted', 'physical', 'outside', 'system', 'invalid_template',
                 'invalid_aperture', 'empty', 'overflow', 'span', 'zero')
        row.update(kind='vm_entry_update', mode=int(m[1]), route=bool(int(m[2])),
                   inactive=int(m[3]),
                   counts={name:int(m[index]) for index, name in enumerate(names, 4)},
                   omitted={'child':int(m[14]), 'eligible':int(m[15]),
                            'control':int(m[16])}, ok=True)
    elif payload.startswith('VM: entry-update mode='):
        row.update(kind='vm_entry_update', ok=False, malformed=True)
    elif m := re.fullmatch(
            r'VM: entry-update-sample bucket=(child|eligible|control) '
            r'caller=x6\+(0x[0-9a-fA-F]+) producer=(child|leaf|unmap|other) '
            r'domain=(converted|physical|outside|system|invalid-template|'
            r'invalid-aperture|empty|overflow|span|zero) '
            r'destination=(0x[0-9a-fA-F]+) count=(\d+) '
            r'source=(0x[0-9a-fA-F]+) result=(0x[0-9a-fA-F]+) '
            r'template=(0x[0-9a-fA-F]+) increment=(0x[0-9a-fA-F]+) '
            r'constructed=(0x[0-9a-fA-F]+) state=returned', payload):
        row.update(kind='vm_entry_update_sample', bucket=m[1], caller=int(m[2], 16),
                   producer=m[3], domain=m[4], destination=int(m[5], 16),
                   count=int(m[6]), source=int(m[7], 16), result=int(m[8], 16),
                   template=int(m[9], 16), increment=int(m[10], 16),
                   constructed=int(m[11], 16), state='returned', ok=True)
    elif payload.startswith('VM: entry-update-sample'):
        row.update(kind='vm_entry_update_sample', ok=False, malformed=True)
    elif m := re.fullmatch(
            r'VM: correlate-submit order=(\d+) thread=(0x[0-9a-fA-F]+) '
            r'hint=(\d+) result=(\d+) reason=(matched|invalid-submit|no-program|'
            r'no-same-thread|no-earlier|no-in-range) retained=(\d+) '
            r'same-thread=(\d+) earlier=(\d+) in-range=(\d+)', payload):
        result = int(m[4])
        reason = m[5]
        retained = int(m[6])
        predicate_counts = tuple(int(m[index]) for index in range(7, 10))
        same_thread_count, earlier_count, in_range_count = predicate_counts
        same_thread, earlier, in_range = (
            value > 0 for value in predicate_counts)
        hierarchy = (retained >= same_thread_count >= earlier_count >=
                     in_range_count)
        expected = {
            'matched': (result > 0 and retained > 0 and same_thread and earlier and
                        in_range),
            'invalid-submit': (result == 0 and not same_thread and not earlier and
                               not in_range),
            'no-program': (result == 0 and retained == 0 and not same_thread and
                           not earlier and not in_range),
            'no-same-thread': (result == 0 and retained > 0 and not same_thread and
                               not earlier and not in_range),
            'no-earlier': (result == 0 and same_thread and not earlier and
                           not in_range),
            'no-in-range': (result == 0 and same_thread and earlier and not in_range),
        }
        consistent = hierarchy and expected[reason]
        row.update(kind='vm_submit_correlation', order=int(m[1]),
                   thread=int(m[2], 16), hint=int(m[3]), result=result,
                   reason=reason, retained=retained,
                   same_thread=predicate_counts[0], earlier=predicate_counts[1],
                   in_range=predicate_counts[2], ok=consistent,
                   malformed=not consistent)
    elif payload.startswith('VM: correlate-submit'):
        row.update(kind='vm_submit_correlation', ok=False, malformed=True)
    elif m := re.fullmatch(r'VM: route AMDGFX10VMM::(getPDEValue|getPTEValue) -> (ok|FAILED) \(entry=([01]) org=(0x[0-9a-fA-F]+)\)', payload):
        row.update(kind='vm_entry_route', method=m[1], ok=m[2] == 'ok',
                   entry=bool(int(m[3])))
    elif m := re.fullmatch(r'VM: root-repair seq=(\d+) vmid=(\d+) original=(0x[0-9a-fA-F]+|0) native=(0x[0-9a-fA-F]+|0) repaired=([01]) reason=([a-z-]+) prepared-match=([01])', payload):
        row.update(kind='vm_root_repair', vm_sequence=int(m[1]), vmid=int(m[2]),
                   original_root=int(m[3], 16), native_root=int(m[4], 16),
                   repaired=bool(int(m[5])), reason=m[6],
                   prepared_match=bool(int(m[7])))
    elif m := re.fullmatch(r'VM: state seq=(\d+) phase=([^ ]+) vmid=(\d+) ctl=(0x[0-9a-fA-F]+|0) root=(0x[0-9a-fA-F]+|0) start=(0x[0-9a-fA-F]+|0) end=(0x[0-9a-fA-F]+|0) requested=(0x[0-9a-fA-F]+|0) native=(0x[0-9a-fA-F]+|0) prepared=(0x[0-9a-fA-F]+|0) repaired=([01]) reason=([a-z-]+) prepared-match=([01]) live-match=([01])', payload):
        row.update(kind='vm_state', vm_sequence=int(m[1]), phase=m[2], vmid=int(m[3]),
                   control=int(m[4], 16), root=int(m[5], 16), start=int(m[6], 16),
                   end=int(m[7], 16), requested_root=int(m[8], 16),
                   native_root=int(m[9], 16), prepared_root=int(m[10], 16),
                   repaired=bool(int(m[11])), reason=m[12],
                   prepared_match=bool(int(m[13])), live_match=bool(int(m[14])))
    elif m := re.fullmatch(r'VM: walk seq=(\d+) va=(0x[0-9a-fA-F]+|0) root=(0x[0-9a-fA-F]+|0) valid=([01]) complete=([01]) count=(\d+)', payload):
        row.update(kind='vm_walk', vm_sequence=int(m[1]), va=int(m[2], 16),
                   root=int(m[3], 16), valid=bool(int(m[4])),
                   complete=bool(int(m[5])), count=int(m[6]))
    elif m := re.fullmatch(
            r'VM: walk-entry seq=(\d+) va=(0x[0-9a-fA-F]+|0) n=(\d+) '
            r'level=(\d+) index=(\d+) table=(0x[0-9a-fA-F]+|0) '
            r'raw=(0x[0-9a-fA-F]+|0) addr=(0x[0-9a-fA-F]+|0) '
            r'V=([01]) S=([01]) C=([01]) X=([01]) R=([01]) W=([01]) '
            r'P=([01]) TF=([01]) child-mc2pa=([01])', payload):
        row.update(kind='vm_walk_entry', vm_sequence=int(m[1]), va=int(m[2], 16),
                   ordinal=int(m[3]), level=int(m[4]), index=int(m[5]),
                   table=int(m[6], 16), raw_entry=int(m[7], 16),
                   address=int(m[8], 16), valid=bool(int(m[9])),
                   system=bool(int(m[10])), snooped=bool(int(m[11])),
                   executable=bool(int(m[12])), readable=bool(int(m[13])),
                   writeable=bool(int(m[14])), pde_as_pte=bool(int(m[15])),
                   translate_further=bool(int(m[16])),
                   child_converted=bool(int(m[17])))
    elif m := re.fullmatch(
            r'VM: invalidate-live seq=(\d+) phase=([^ ]+) reg=(0x[0-9a-fA-F]+|0) '
            r'kind=sem engine=(\d+) value=unread', payload):
        row.update(kind='vm_invalidate_live', vm_sequence=int(m[1]), phase=m[2],
                   register=int(m[3], 16), register_kind='sem', engine=int(m[4]),
                   value=None, vmid2_bit=None)
    elif m := re.fullmatch(
            r'VM: invalidate-live seq=(\d+) phase=([^ ]+) reg=(0x[0-9a-fA-F]+|0) '
            r'kind=(sem|req|ack) engine=(\d+) value=(0x[0-9a-fA-F]+|0) bit2=([01])',
            payload):
        row.update(kind='vm_invalidate_live', vm_sequence=int(m[1]), phase=m[2],
                   register=int(m[3], 16), register_kind=m[4], engine=int(m[5]),
                   value=int(m[6], 16), vmid2_bit=bool(int(m[7])))
    elif m := re.fullmatch(
            r'VM: pre-clear-fault seq=(\d+) cntl=(0x[0-9a-fA-F]+|0) '
            r'status=(0x[0-9a-fA-F]+|0) addr=(0x[0-9a-fA-F]+|0)', payload):
        row.update(kind='vm_pre_clear_fault', vm_sequence=int(m[1]),
                   fault_control=int(m[2], 16), fault_status=int(m[3], 16),
                   fault_address=int(m[4], 16))
    elif m := re.fullmatch(
            r'VM: fault seq=(\d+) phase=([^ ]+) cntl=(0x[0-9a-fA-F]+|0) '
            r'status=(0x[0-9a-fA-F]+|0) addr=(0x[0-9a-fA-F]+|0) \| '
            r'invalidate-order=(0x[0-9a-fA-F]+|0) eng0-sem=(0x[0-9a-fA-F]+|0|unread) '
            r'req=(0x[0-9a-fA-F]+|0) ack=(0x[0-9a-fA-F]+|0) bit2=([01])/([01]) '
            r'prepared-mask=(0x[0-9a-fA-F]+|0)/(0x[0-9a-fA-F]+|0)', payload):
        row.update(kind='vm_fault', vm_sequence=int(m[1]), phase=m[2],
                   fault_control=int(m[3], 16), fault_status=int(m[4], 16),
                   fault_address=int(m[5], 16), invalidate_order=int(m[6], 16),
                   semaphore0=None if m[7] == 'unread' else int(m[7], 16),
                   request0=int(m[8], 16),
                   acknowledge0=int(m[9], 16), request_vmid2_bit=int(m[10]),
                   acknowledge_vmid2_bit=int(m[11]),
                   prepared_request_mask=int(m[12], 16),
                   prepared_ack_mask=int(m[13], 16))
    elif m := re.fullmatch(
            r'SD: runtime seq=(\d+) phase=([^ ]+) cntl=(0x[0-9a-fA-F]+|0) '
            r'ucode=(0x[0-9a-fA-F]+|0) f32=(0x[0-9a-fA-F]+|0) '
            r'status=(0x[0-9a-fA-F]+|0)/(0x[0-9a-fA-F]+|0)/'
            r'(0x[0-9a-fA-F]+|0)/(0x[0-9a-fA-F]+|0) '
            r'utcl-cntl=(0x[0-9a-fA-F]+|0) page=(0x[0-9a-fA-F]+|0) '
            r'rd=(0x[0-9a-fA-F]+|0) wr=(0x[0-9a-fA-F]+|0)', payload):
        row.update(kind='sdma_runtime', vm_sequence=int(m[1]), phase=m[2],
                   control=int(m[3], 16), ucode_checksum=int(m[4], 16),
                   f32_control=int(m[5], 16),
                   status=[int(m[n], 16) for n in range(6, 10)],
                   utcl_control=int(m[10], 16), utcl_page=int(m[11], 16),
                   read_status=int(m[12], 16), write_status=int(m[13], 16))
    elif m := re.fullmatch(
            r'SD: xnack seq=(\d+) phase=([^ ]+) rd=(0x[0-9a-fA-F]+|0)/'
            r'(0x[0-9a-fA-F]+|0) wr=(0x[0-9a-fA-F]+|0)/'
            r'(0x[0-9a-fA-F]+|0)', payload):
        row.update(kind='sdma_xnack', vm_sequence=int(m[1]), phase=m[2],
                   read_xnack0=int(m[3], 16), read_xnack1=int(m[4], 16),
                   write_xnack0=int(m[5], 16), write_xnack1=int(m[6], 16))
    elif m := re.fullmatch(
            r'SD: page seq=(\d+) phase=([^ ]+) status=(0x[0-9a-fA-F]+|0) '
            r'context=(0x[0-9a-fA-F]+|0) ib-cntl=(0x[0-9a-fA-F]+|0) '
            r'rptr=(0x[0-9a-fA-F]+|0) offset=(0x[0-9a-fA-F]+|0) '
            r'base=(0x[0-9a-fA-F]+|0)_([0-9a-fA-F]{8}) size=(0x[0-9a-fA-F]+|0)',
            payload):
        row.update(kind='sdma_page_state', vm_sequence=int(m[1]), phase=m[2],
                   status=int(m[3], 16), context=int(m[4], 16),
                   ib_control=int(m[5], 16), rptr=int(m[6], 16),
                   offset=int(m[7], 16),
                   ib_base=(int(m[8], 16) << 32) | int(m[9], 16),
                   size=int(m[10], 16))
    elif m := re.fullmatch(r'VM: context-snapshot vmid=(\d+) root=(0x[0-9a-fA-F]+|0) ctl=(0x[0-9a-fA-F]+|0) start=(0x[0-9a-fA-F]+|0) end=(0x[0-9a-fA-F]+|0)', payload):
        row.update(kind='vm_context', vmid=int(m[1]), root=int(m[2], 16),
                   control=int(m[3], 16), start=int(m[4], 16), end=int(m[5], 16))
    elif m := re.fullmatch(r'SD: IB template (0x[0-9a-fA-F]+) -> (0x[0-9a-fA-F]+) valid=([01]) changed=([01])', payload):
        row.update(kind='sdma_ib_repair', before=int(m[1], 16), after=int(m[2], 16),
                   valid=bool(int(m[3])), changed=bool(int(m[4])))
    elif m := re.fullmatch(
            r'XQ2: dequeue INACTIVE-RETAINED after (\d+) us; descriptor unchanged; '
            r'native-restore=(\d+) lease=(\d+) owners=(\d+) active=(0x[0-9a-fA-F]+|\d+) '
            r'dequeue=(0x[0-9a-fA-F]+|\d+) poll=(0x[0-9a-fA-F]+|\d+) '
            r'doorbell=(0x[0-9a-fA-F]+|\d+) image-exact=(\d+)', payload):
        active, dequeue, poll, doorbell = (int(m[index], 0) for index in (5, 6, 7, 8))
        row.update(kind='kiq', result=0, source='inactive-retained',
                   elapsed_us=int(m[1]), restore_admitted=(m[2] == '1' and
                   m[3] == '1' and m[4] == '1' and m[9] == '1' and
                   active == 0 and dequeue == 0 and
                   not (poll & (1 << 31)) and not (doorbell & (1 << 30))))
    elif m := re.fullmatch(
            r'XQ2: dequeue TIMEOUT after (\d+) us; descriptor unchanged; '
            r'native-restore=(\d+) lease=(\d+) owners=(\d+) active=(0x[0-9a-fA-F]+|0) '
            r'dequeue=(0x[0-9a-fA-F]+|0) poll=(0x[0-9a-fA-F]+|0) '
            r'doorbell=(0x[0-9a-fA-F]+|0) image-exact=(\d+)', payload):
        row.update(kind='kiq', result=0, source='dequeue-timeout',
                   elapsed_us=int(m[1]), restore_admitted=(m[2] == '1' and
                   m[3] == '1' and m[4] == '1' and m[9] == '1' and
                   int(m[5], 0) & 1 and int(m[6], 0) == 1 and
                   not (int(m[7], 0) & (1 << 31)) and
                   not (int(m[8], 0) & (1 << 30))))
    elif payload.startswith('XQ2: dequeue') and ('refused' in payload or 'timeout' in payload.lower()):
        row.update(kind='kiq', result=0, source='dequeue-timeout', restore_admitted=False)
    return row


def _parse_legacy_serial(serial):
    records, losses, counts, raw_records, panics, hardware_timeouts = {}, [], {}, [], [], []
    raw_builds = set()
    serial = serial.replace('\r', '')
    # sercat fsyncs every append, so a concurrent reader can legitimately observe
    # the bytes in the middle of one line.  A line has no evidentiary value until
    # its newline is durable; parsing that tail can turn a replay into a conflict.
    if serial and not serial.endswith('\n'):
        serial = serial.rsplit('\n', 1)[0] + ('\n' if '\n' in serial else '')
    for line_number, line in enumerate(serial.splitlines()):
        summary = re.search(r'RGPU_RECORDS build=(\S+) count=(\d+) dropped=(\d+) truncated=(\d+)', line)
        if summary:
            counts[summary[1]] = max(counts.get(summary[1], 0), int(summary[2]))
        if summary and any(int(summary[i]) for i in (3, 4)):
            losses.append(dict(kind='capture_loss', build=summary[1], reason='overflow'))
        match = re.search(r'RGPU_EVENT build=(\S+) seq=(\d+) (.+)$', line)
        if match:
            build, seq, payload = match[1], int(match[2]), match[3]
            key = (build, seq)
            if key in records:
                if records[key]['raw'] != payload:
                    losses.append(dict(kind='capture_loss', build=build, reason='conflicting replay'))
                continue
            records[key] = _decode_payload(build, seq, payload)
            continue
        raw = re.search(r'RaphaelGPU\s+rgpu:\s*@\s+(.*)$', line)
        if raw:
            payload = raw[1]
            if m := re.fullmatch(r'BUILD: identity=(\S+)', payload):
                raw_builds.add(m[1])
            raw_records.append((line_number, payload))
            terminal = _decode_payload(None, line_number, payload)
            if (terminal['kind'] in ('kiq', 'kiq_submit') and
                    terminal.get('result') == 0):
                terminal['kind'] = 'kiq'
                terminal['source'] = 'raw-terminal'
                terminal['raw'] = line.strip()
                hardware_timeouts.append(terminal)
        if m := re.search(r'Unexpected kernel trap number:\s*(\S+), RIP:\s*(0x[0-9a-fA-F]+), CR2:\s*(0x[0-9a-fA-F]+)', line):
            panics.append(dict(kind='guest_panic', build=None, seq=line_number, raw=line.strip(),
                               trap=m[1], rip=int(m[2], 16), cr2=int(m[3], 16)))
        if (panics and 'symbol' not in panics[-1] and
                (m := re.search(r'com\.apple\.kext\.AMDRadeonX6000\s*:\s*(\S+)\s*\+\s*(0x[0-9a-fA-F]+)', line))):
            panics[-1].update(symbol=m[1], offset=int(m[2], 16))
        if (re.search(r'HW Channel \d+ SDMA0_PAGE is occupied by channel \d+ stamp \d+', line) or
                re.search(r'Restart Channel:\s*\d+\s+SDMA0_PAGE', line)):
            hardware_timeouts.append(dict(kind='sdma_page_timeout', build=None,
                                          seq=line_number, source='raw-terminal',
                                          raw=line.strip()))
    raw_build = next(iter(raw_builds)) if len(raw_builds) == 1 else None
    if raw_build is None and len(counts) == 1:
        raw_build = next(iter(counts))
    structured_payloads = {(r['build'], r['raw']) for r in records.values()}
    seen_raw = set()
    decoded_raw = []
    for line_number, payload in raw_records:
        build_match = re.fullmatch(r'BUILD: identity=(\S+)', payload)
        build = build_match[1] if build_match else raw_build
        row = _decode_payload(build, line_number, payload)
        key = (build, payload)
        if row['kind'] == 'other' or key in seen_raw or key in structured_payloads:
            continue
        seen_raw.add(key)
        decoded_raw.append(row)
    for panic in panics:
        panic['build'] = raw_build
    for timeout in hardware_timeouts:
        timeout['build'] = raw_build
    for build, count in counts.items():
        if any((build, seq) not in records for seq in range(count)):
            losses.append(dict(kind='capture_loss', build=build, reason='snapshot incomplete'))
    for build, _ in records:
        if build not in counts:
            losses.append(dict(kind='capture_loss', build=build, reason='overflow summary missing'))
            counts[build] = 0
    for build, seq in records:
        if seq >= counts[build]:
            losses.append(dict(kind='capture_loss', build=build, reason='summary precedes newer records'))
    # A complete structured snapshot is an immutable, sequenced prefix. Later direct
    # log lines have no record sequence and may race the next snapshot; do not splice
    # their serial line numbers into that prefix. Preserve only a terminal KIQ failure
    # which precedes a panic: it is causal ordering evidence that cannot be replayed in
    # the next snapshot once the kernel has trapped. It remains outside the structured
    # sequence and therefore cannot create synthetic capture gaps.
    terminal_live = []
    for row in decoded_raw:
        if row.get('build') not in counts:
            row['source'] = 'raw-fallback'
            terminal_live.append(row)
        elif row['kind'] in ('submission_trace_route', 'recovery_lease_owned',
                             'recovery_lease_pool', 'recovery_lease_wire',
                             'vmm_readiness'):
            # Route readiness is emitted once from the kext-load callback and is
            # safe to consume before the next immutable replay snapshot.
            row['source'] = 'live-readiness'
            terminal_live.append(row)
        elif row['kind'] in ('vm_invalidate', 'vm_context', 'vm_program', 'vm_root_repair',
                            'vm_state', 'vm_walk', 'vm_walk_entry',
                            'vm_invalidate_live', 'vm_pre_clear_fault', 'vm_fault',
                            'sdma_runtime', 'sdma_xnack', 'sdma_page_state', 'sdma_submit',
                            'submission_trace_summary', 'submission_map_phase',
                            'submission_map_phase_summary',
                            'submission_backing_allocation',
                            'submission_backing_allocation_summary',
                            'vmid1_fault_walk', 'vmid1_fault_walk_view',
                            'vmid1_fault_walk_entry', 'client_fault_walk',
                            'client_fault_walk_view', 'client_fault_walk_entry'):
            # These records are formatted by the dedicated observation thread,
            # outside the driver callbacks. Preserve the exact live line until
            # the next immutable structured snapshot includes it.
            row['source'] = 'live-observation'
            terminal_live.append(row)
        elif (row['kind'] == 'kiq' and row.get('result') == 0 and
              any(panic['seq'] > row['seq'] for panic in panics)):
            row['source'] = 'live-terminal'
            terminal_live.append(row)
    decoded_raw = terminal_live
    if decoded_raw and raw_build not in counts:
        losses.append(dict(kind='capture_loss', build=raw_build, reason='live records only'))
    rows = sorted(list(records.values()) + decoded_raw + panics + hardware_timeouts,
                  key=lambda r: r['seq'])
    return rows + losses


CRITICAL_REPLAY_TOLERANCES = (None, 'terminal-prefix', 'terminal-prefix-open')


def parse_serial(serial, *, critical_replay_schema=None, expected_build=None,
                 critical_replay_tolerance=None):
    if critical_replay_schema is None:
        return _parse_legacy_serial(serial)
    if critical_replay_schema != 2 or not isinstance(expected_build, str):
        return [dict(kind='capture_loss', build=expected_build,
                     reason='CR2 selection is invalid', definitive=True)]
    if critical_replay_tolerance not in CRITICAL_REPLAY_TOLERANCES:
        return [dict(kind='capture_loss', build=expected_build,
                     reason='CR2 tolerance selection is invalid', definitive=True)]
    replay = _critical_replay()
    try:
        snapshot = replay.parse(
            serial, expected_build,
            tolerate_corruption=critical_replay_tolerance is not None,
            open_attempt=critical_replay_tolerance == 'terminal-prefix-open')
    except replay.CriticalReplayError as error:
        message = str(error)
        recoverable_missing_chunk = (
            critical_replay_tolerance == replay.TOLERANCE_TERMINAL_PREFIX and
            message == 'CR2 snapshot has a missing chunk')
        pending = any(fragment in message for fragment in (
            'missing CR2 transport', 'missing END', 'incomplete transport line',
            'latest attempt is incomplete', 'after the terminal manifest')) or \
            recoverable_missing_chunk
        return [dict(kind='capture_loss', build=expected_build,
                     reason='CR2: ' + message, definitive=not pending)]
    synthetic = (
        f'RGPU_RECORDS build={expected_build} count={snapshot["count"]} '
        'dropped=0 truncated=0\n' + ''.join(
            f'RGPU_EVENT build={expected_build} seq={seq} {payload}\n'
            for seq, payload in enumerate(snapshot['records'])))
    rows = _parse_legacy_serial(synthetic)
    generic_kinds = ('client_fault_walk', 'client_fault_walk_view',
                     'client_fault_walk_entry')
    generic_keys = {(row.get('status'), row.get('fault_va')) for row in rows
                    if row.get('kind') in generic_kinds}
    invalid_generic_keys = {}
    for key in generic_keys:
        grouped = [row for row in rows
                   if row.get('kind') in generic_kinds and
                   (row.get('status'), row.get('fault_va')) == key]
        position = 0
        complete = False
        prefix_ended = False
        contradictory = not grouped or grouped[0]['kind'] != 'client_fault_walk'
        position += not contradictory
        for view in ('relative', 'absolute'):
            if contradictory or position == len(grouped):
                break
            current = grouped[position]
            if (current['kind'] != 'client_fault_walk_view' or
                    current['view'] != view):
                contradictory = True
                break
            position += 1
            for number in range(current['count']):
                if position == len(grouped):
                    prefix_ended = True
                    break
                entry = grouped[position]
                if (entry['kind'] != 'client_fault_walk_entry' or
                        entry['view'] != view or entry['number'] != number):
                    contradictory = True
                    break
                position += 1
            if contradictory or prefix_ended:
                break
        else:
            complete = position == len(grouped)
            contradictory = not complete
        if not complete:
            invalid_generic_keys[key] = contradictory
    if invalid_generic_keys:
        rows = [row for row in rows
                if not (row.get('kind') in generic_kinds and
                        (row.get('status'), row.get('fault_va')) in
                        invalid_generic_keys)]
        for status, fault_va in sorted(invalid_generic_keys):
            definitive = invalid_generic_keys[(status, fault_va)]
            rows.append(dict(
                kind='capture_loss', build=expected_build,
                status=status, fault_va=fault_va,
                reason=('contradictory' if definitive else 'incomplete') +
                       ' generic client fault-walk group',
                definitive=definitive))
    fault_pairs = {(row.get('status'), row.get('fault_va')) for row in rows
                   if row.get('kind') in ('vmid1_fault_walk', 'client_fault_walk')}
    if len(fault_pairs) > 2:
        rows.append(dict(kind='capture_loss', build=expected_build,
                         reason='client fault-walk contains more than two distinct pairs',
                         definitive=True))
    if snapshot.get('tolerance'):
        # Tolerated corruption is evidence, never a loss: the terminal snapshot's
        # digests and every valid earlier chunk were checked against the prefix.
        rows.append(dict(kind='capture_tolerance', build=expected_build,
                         seq=snapshot['count'], tolerance=snapshot['tolerance'],
                         corrupt_lines=snapshot['corrupt_lines'],
                         corrupt_reasons=snapshot['corrupt_reasons'],
                         incomplete_snapshots=snapshot['incomplete_snapshots'],
                         terminal_snapshot=snapshot['snapshot'],
                         open_attempt=snapshot.get('open_attempt')))
    terminal = []
    for row in _parse_legacy_serial(serial):
        if (row['kind'] == 'guest_panic' or
                row.get('source') == 'raw-terminal'):
            row = dict(row, build=expected_build)
            terminal.append(row)
    seen = {(row['kind'], row.get('raw'), row.get('seq')) for row in rows}
    rows.extend(row for row in terminal
                if (row['kind'], row.get('raw'), row.get('seq')) not in seen)
    return rows


def parse_console_lifecycle(serial, expected_build):
    """Read only console identity and panic evidence for dedicated CR2 runs."""
    identities = set(re.findall(
        r'RaphaelGPU\s+rgpu:\s*@\s+BUILD: identity=(\S+)',
        serial.replace('\r', '')))
    if identities - {expected_build}:
        raise ValueError('console has a conflicting build identity')
    return [dict(row, build=expected_build)
            for row in _parse_legacy_serial(serial)
            if row.get('kind') == 'guest_panic']


def parse_manifest_files(manifest, run):
    contract_path = Path(__file__).with_name('critical-transport.py')
    spec = importlib.util.spec_from_file_location('critical_transport_contract', contract_path)
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    transport = contract.validate(manifest)
    tolerance = manifest.get('critical_replay_tolerance')
    if transport is None:
        return parse_serial(
            (run / 'serial.txt').read_text(errors='replace'),
            critical_replay_schema=manifest.get('critical_replay_schema'),
            expected_build=(manifest.get('build_id')
                            if 'critical_replay_schema' in manifest else None),
            critical_replay_tolerance=tolerance)
    critical = (run / 'critical.txt').read_text(errors='replace')
    events = parse_serial(critical, critical_replay_schema=2,
                          expected_build=manifest.get('build_id'),
                          critical_replay_tolerance=tolerance)
    ready_state = contract.producer_ready_state(critical, manifest.get('build_id'))
    if ready_state != 'valid':
        events.append(dict(
            kind='capture_loss', build=manifest.get('build_id'),
            reason='dedicated critical producer readiness is absent or conflicting',
            definitive=ready_state == 'conflicting'))
    events += parse_console_lifecycle(
        (run / 'serial.txt').read_text(errors='replace'), manifest.get('build_id'))
    return events


def _probe_status(manifest, probe):
    """Extract only nonce-bound, structurally complete probe diagnostics.

    A failed probe is useful evidence even though the strict validator rejects
    it as a benchmark pass.  Never attach that evidence unless its result and
    exit marker are both bound to the prepared run nonce and identify the
    expected Metal device.
    """
    if (not isinstance(probe, dict) or not isinstance(probe.get('output'), str) or
            not manifest.get('run_id') or probe.get('run_id') != manifest['run_id']):
        return None
    output = probe['output']
    rows = [line.removeprefix('RGPU_SMALL_METAL_RESULT ')
            for line in output.splitlines()
            if line.startswith('RGPU_SMALL_METAL_RESULT ')]
    exits = re.findall(r'^RGPU_EXIT ' + re.escape(manifest['run_id']) + r' (\d+)$',
                       output, re.M)
    if len(rows) != 1 or len(exits) != 1:
        return None
    try:
        result = json.loads(rows[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if (not isinstance(result, dict) or result.get('run_id') != manifest['run_id'] or
            result.get('device') != 'AMD Radeon Navi23' or
            result.get('metal3') is not True or
            type(result.get('completed_command_buffers')) is not int or
            result['completed_command_buffers'] < 0 or
            type(result.get('values_checked')) is not int or
            result['values_checked'] < 0 or type(result.get('registry_id')) is not int or
            result['registry_id'] < 1):
        return None
    if (result.get('passed') is not False or not isinstance(result.get('error'), str) or
            not result['error'] or exits != ['1'] or probe.get('transport_exit') != 0):
        return None
    return dict(verdict='EXECUTION_FAILED',
                completed_command_buffers=result['completed_command_buffers'],
                  values_checked=result['values_checked'],
                  registry_id=result['registry_id'], error=result.get('error'))


def _probe_summary(manifest, probe):
    """Nonce-bound raw probe result (pass or fail) for verdicts that cannot promote it."""
    if not isinstance(probe, dict) or not isinstance(probe.get('output'), str):
        return None
    run_id = manifest.get('run_id')
    if not run_id or probe.get('run_id') != run_id:
        return None
    rows = []
    for line in probe['output'].splitlines():
        for prefix in ('RGPU_SMALL_METAL_RESULT ', 'RGPU_METAL_RESULT '):
            if line.startswith(prefix):
                rows.append(line[len(prefix):])
    exits = re.findall(r'^RGPU_EXIT ' + re.escape(run_id) + r' (\d+)$',
                       probe['output'], re.M)
    if len(rows) != 1:
        return None
    try:
        result = json.loads(rows[0])
    except (TypeError, ValueError):
        return None
    if not isinstance(result, dict) or result.get('run_id') != run_id:
        return None
    summary = dict(passed=result.get('passed') is True,
                   completed_command_buffers=result.get('completed_command_buffers'),
                   values_checked=result.get('values_checked'),
                   exits=exits, transport_exit=probe.get('transport_exit'))
    for key in ('render_pixels_checked', 'error'):
        if key in result:
            summary[key] = result[key]
    return summary


def _classify(manifest, events, probe, defer_absent_workload=False):
    probe_status = None
    # Candidate 211 completed its compute probe while a later graphics-ring
    # stall produced the KIQ stage; the raw nonce-bound result must survive on
    # every verdict, not only under capture loss.
    probe_summary = _probe_summary(manifest, probe)

    def verdict(name, valid=False, stage=None, next_action='repair observation before another experiment'):
        result = dict(valid=valid, verdict=name, earliest_failure=stage,
                      evidence=[r.get('raw', r['kind']) for r in events], next_action=next_action)
        if probe_status is not None:
            result['probe_status'] = probe_status
        if probe_summary is not None:
            result['probe_summary'] = probe_summary
        return result
    expected = manifest.get('build_id')
    if not expected or any(r.get('build') not in (None, expected) for r in events):
        return verdict('INVALID', stage='loaded_build')
    kinds = {kind: [r for r in events if r['kind'] == kind]
             for kind in ('build', 'route', 'kiq', 'kiq_submit', 'hybrid_enter',
                          'hybrid_exit', 'engine_start')}
    if any(not r.get('ok') for r in kinds['route']):
        return verdict('INVALID', stage='route_guards')
    if not kinds['build'] or not kinds['route']:
        return verdict('INCONCLUSIVE', stage='identity_or_route_missing')
    probe_status = _probe_status(manifest, probe)
    required = manifest.get('spec', {}).get('required_observations', [])
    if manifest.get('recovery_lease_schema') in (2, 3):
        lease = _recovery_lease_v2()
        wire = [r.get('raw', '') for r in events
                if r['kind'] in ('recovery_lease_owned', 'recovery_lease_pool',
                                 'recovery_lease_wire')]
        try:
            expected_nonce = struct.unpack('<QQ', bytes.fromhex(manifest['run_id']))
            evidence = lease.parse_critical_records(wire, expected_nonce=expected_nonce)
        except (KeyError, TypeError, ValueError, lease.LeaseValidationError):
            return verdict('INCONCLUSIVE', stage='recovery_lease_pool_missing')
        if evidence.pool_status is None or evidence.pool_status.state != lease.POOL_ACTIVE:
            return verdict('INCONCLUSIVE', stage='recovery_lease_pool_missing')
        vmm = [r for r in events if r['kind'] == 'vmm_readiness']
        if any(not r.get('ok') for r in vmm):
            return verdict('INVALID', stage='vmm_readiness_malformed')
        native = [r for r in vmm if r.get('phase') == 'native']
        if not native:
            return verdict('INCONCLUSIVE', stage='vmm_native_readiness_missing')
        final = native[-1]
        if (final.get('enable') != 1 or not final.get('base') or
                not final.get('arena') or not final.get('pool0') or
                not final.get('pool1')):
            return verdict('STARTUP_FAILED_LATER', True, 'vmm_native_arena',
                           'inspect the final native VMM arena and allocator fields')
        arena_offset = final['base'] & (lease.VRAM_BAR_SIZE - 1)
        arena_end = arena_offset + 0x04400000
        descriptor = evidence.descriptor
        if (arena_end > lease.VRAM_BAR_SIZE or
                (arena_offset < descriptor.lease_end and
                 descriptor.lease_offset < arena_end)):
            return verdict('INVALID', stage='vmm_native_arena_overlap')
    if 'submission_trace' in required:
        trace_routes = [r for r in events if r['kind'] == 'submission_trace_route']
        if not trace_routes:
            return verdict('INCONCLUSIVE', stage='submission_trace_route_missing')
        if len(trace_routes) != 1 or not trace_routes[0].get('ok'):
            return verdict('INVALID', stage='submission_trace_route_guard')
        trace_summaries = [r for r in events if r['kind'] == 'submission_trace_summary']
        if any(not r.get('ok') for r in trace_summaries):
            return verdict('INVALID', stage='submission_trace_worker_malformed')
        if not any(r.get('seq', -1) > trace_routes[0].get('seq', -1)
                   for r in trace_summaries):
            return verdict('INCONCLUSIVE', stage='submission_trace_worker_missing')
    if 'submission_map_phase' in required:
        phase_observations = [r for r in events
                              if r['kind'] == 'submission_map_phase']
        if any(r.get('malformed') or r.get('ok') is False
               for r in phase_observations):
            return verdict('INVALID',
                           stage='submission_map_phase_observation_malformed')
        phase_summaries = [r for r in events
                           if r['kind'] == 'submission_map_phase_summary']
        if any(not r.get('ok') for r in phase_summaries):
            return verdict('INVALID', stage='submission_map_phase_worker_malformed')
        trace_routes = [r for r in events if r['kind'] == 'submission_trace_route']
        route_sequence = trace_routes[0].get('seq', -1) if len(trace_routes) == 1 else -1
        if not any(r.get('seq', -1) > route_sequence for r in phase_summaries):
            return verdict('INCONCLUSIVE', stage='submission_map_phase_worker_missing')
    if 'submission_backing_allocation' in required:
        backing_observations = [
            r for r in events if r['kind'] == 'submission_backing_allocation']
        if any(r.get('malformed') or r.get('ok') is False
               for r in backing_observations):
            return verdict('INVALID',
                           stage='submission_backing_allocation_observation_malformed')
        trace_routes = [r for r in events if r['kind'] == 'submission_trace_route']
        if not trace_routes:
            return verdict('INCONCLUSIVE',
                           stage='submission_backing_allocation_route_missing')
        if (len(trace_routes) != 1 or not trace_routes[0].get('ok') or
                trace_routes[0].get('count') not in (6, 7)):
            return verdict('INVALID',
                           stage='submission_backing_allocation_route_guard')
        backing_summaries = [
            r for r in events
            if r['kind'] == 'submission_backing_allocation_summary']
        if any(not r.get('ok') for r in backing_summaries):
            return verdict('INVALID',
                           stage='submission_backing_allocation_worker_malformed')
        route_sequence = trace_routes[0].get('seq', -1)
        if not any(r.get('seq', -1) > route_sequence for r in backing_summaries):
            return verdict('INCONCLUSIVE',
                           stage='submission_backing_allocation_worker_missing')
    post_workload_kinds = {
        'sdma_submit', 'sdma_ib_repair', 'vm_program', 'vm_root_repair',
        'vm_state', 'vm_walk', 'vm_walk_entry', 'vm_context',
        'vm_invalidate', 'vm_invalidate_live',
        'vm_pre_clear_fault', 'vm_fault', 'sdma_runtime', 'sdma_xnack',
        'sdma_page_state',
    }
    require_workload_outcomes = (not defer_absent_workload or
                                 any(r['kind'] in post_workload_kinds for r in events))
    if 'vmid2_entry_gate' in required:
        gates = [r for r in events if r['kind'] == 'vm_entry_gate']
        expected_mode = (5 if 'map_process_root' in required else
                         4 if 'vmid2_entry_update' in required else 3)
        if not gates:
            return verdict('INCONCLUSIVE', stage='vmid2_entry_gate_missing')
        if (len(gates) != 1 or not gates[0].get('marked') or
                not gates[0].get('aperture') or
                gates[0].get('mode') != expected_mode):
            return verdict('INVALID', stage='vmid2_entry_gate_state')
    correlations = [r for r in events if r['kind'] == 'vm_submit_correlation']
    if any(not r.get('ok') for r in correlations):
        return verdict('INVALID', stage='vmid2_submit_correlation_malformed')
    if 'vmid2_entry_update' in required:
        routes = [r for r in events if r['kind'] == 'vm_entry_update_route']
        if (len(routes) != 1 or not routes[0].get('ok') or
                not routes[0].get('entry')):
            return verdict('INVALID', stage='vmid2_entry_update_route_guard')
        summaries = [r for r in events if r['kind'] == 'vm_entry_update']
        if not summaries:
            return verdict('INCONCLUSIVE', stage='vmid2_entry_update_missing')
        if any(not row.get('ok') for row in summaries):
            return verdict('INVALID', stage='vmid2_entry_update_state')
        previous = None
        for row in summaries:
            row_counts = row.get('counts')
            row_omitted = row.get('omitted')
            if (not isinstance(row_counts, dict) or
                    set(row_counts) != set(ENTRY_UPDATE_COUNT_KEYS) or
                    any(type(value) is not int or value < 0
                        for value in row_counts.values()) or
                    not isinstance(row_omitted, dict) or
                    set(row_omitted) != set(ENTRY_UPDATE_OMISSION_KEYS) or
                    any(type(value) is not int or value < 0
                        for value in row_omitted.values()) or
                    type(row.get('inactive')) is not int or
                    row.get('inactive') < 0):
                return verdict('INVALID', stage='vmid2_entry_update_state')
            current = ((row['inactive'],) +
                       tuple(row_counts[key] for key in ENTRY_UPDATE_COUNT_KEYS) +
                       tuple(row_omitted[key] for key in ENTRY_UPDATE_OMISSION_KEYS))
            if (previous is not None and
                    any(value < old for value, old in zip(current, previous))):
                return verdict('INVALID', stage='vmid2_entry_update_state')
            previous = current
        expected_update_mode = 5 if 'map_process_root' in required else 4
        if any(row.get('mode') != expected_update_mode or row.get('route') is not True
               for row in summaries):
            return verdict('INVALID', stage='vmid2_entry_update_state')
        summary = summaries[-1]
        counts = summary.get('counts')
        omitted = summary.get('omitted')
        if (summary.get('mode') != expected_update_mode or summary.get('route') is not True or
                summary.get('inactive') != 0 or
                any(counts.get(key) for key in ('invalid_aperture', 'overflow', 'span'))):
            return verdict('INVALID', stage='vmid2_entry_update_state')
        samples = [r for r in events if r['kind'] == 'vm_entry_update_sample']
        if any(not r.get('ok') for r in samples):
            return verdict('INVALID', stage='vmid2_entry_update_sample_malformed')

        domain_keys = {
            'converted':'converted', 'physical':'physical', 'outside':'outside',
            'system':'system', 'invalid-template':'invalid_template',
            'invalid-aperture':'invalid_aperture', 'empty':'empty',
            'overflow':'overflow', 'span':'span', 'zero':'zero'}
        for row in samples:
            key = domain_keys.get(row.get('domain'))
            if key is None:
                return verdict('INVALID', stage='vmid2_entry_update_sample_malformed')
            caller = row.get('caller')
            expected_producer = ('leaf' if caller == 0x559dc else
                                 'child' if caller == ENTRY_CHILD_CALLER else
                                 'unmap' if caller == 0x561f6 else 'other')
            if row.get('producer') != expected_producer:
                return verdict('INVALID', stage='vmid2_entry_update_sample_malformed')
        if any(row.get('domain') == 'converted' and
               row.get('bucket') not in ('child', 'eligible')
               for row in samples):
            return verdict('INVALID', stage='vmid2_entry_update_control')
        if any(row.get('domain') in ('invalid-aperture', 'overflow', 'span')
               for row in samples):
            return verdict('INVALID', stage='vmid2_entry_update_state')
        controls = [row for row in samples if row.get('domain') != 'converted']
        if any(row.get('bucket') != 'control' or
               type(row.get('source')) is not int or
               type(row.get('result')) is not int or
               row.get('source') != row.get('result') or
               type(row.get('template')) is not int or
               type(row.get('constructed')) is not int or
               row.get('constructed') != row.get('template') | row.get('result') or
               row.get('state') != 'returned' for row in controls):
            return verdict('INVALID', stage='vmid2_entry_update_control')

        def valid_converted(row):
            source = row.get('source')
            result = row.get('result')
            template = row.get('template')
            constructed = row.get('constructed')
            count = row.get('count')
            increment = row.get('increment')
            if (type(source) is not int or type(result) is not int or
                    type(template) is not int or type(constructed) is not int or
                    type(count) is not int or count <= 0 or
                    type(increment) is not int or increment < 0):
                return False
            steps = count - 1
            if increment and steps > ((1 << 64) - 1) // increment:
                return False
            span = steps * increment
            if source > (1 << 64) - 1 - span:
                return False
            return (template & 1 == 1 and template & 2 == 0 and
                    ENTRY_MC_BASE <= source < ENTRY_MC_BASE + ENTRY_APERTURE_SIZE and
                    source + span < ENTRY_MC_BASE + ENTRY_APERTURE_SIZE and
                    ENTRY_PHYSICAL_BASE <= result <
                        ENTRY_PHYSICAL_BASE + ENTRY_APERTURE_SIZE and
                    result + span < ENTRY_PHYSICAL_BASE + ENTRY_APERTURE_SIZE and
                    result == source - ENTRY_MC_BASE + ENTRY_PHYSICAL_BASE and
                    constructed == template | result and
                    row.get('bucket') in ('child', 'eligible') and
                    row.get('state') == 'returned')

        converted = [r for r in samples if r.get('domain') == 'converted']
        if any(not valid_converted(row) for row in converted):
            return verdict('INVALID', stage='vmid2_entry_update_child_invalid')
        children = [r for r in converted if r.get('bucket') == 'child' and
                    r.get('producer') == 'child' and
                    r.get('caller') == ENTRY_CHILD_CALLER and r.get('count') == 1]
        if not children:
            return verdict('INCONCLUSIVE', stage='vmid2_entry_update_child_missing')
        if any(r['kind'] == 'vm_fault' and r.get('fault_status')
               for r in events):
            return verdict('EXECUTION_FAILED', True, 'vmid2_mapping_fault',
                           'the VMID2 mapping still faults; do not retry unchanged')
    if 'map_process_root' in required:
        routes = [r for r in events if r['kind'] == 'vm_map_process_route']
        if (len(routes) != 1 or not routes[0].get('ok') or
                not routes[0].get('entry') or not routes[0].get('original')):
            return verdict('INVALID', stage='map_process_root_route_guard')
        route_seq = routes[0].get('seq', -1)
        roots = [r for r in events if r['kind'] == 'vm_map_process_root']
        if len(roots) > 8:
            return verdict('INVALID', stage='map_process_root_capacity')
        if any(r.get('seq', -1) <= route_seq or not r.get('ok') or
               not r.get('guard_valid') for r in roots):
            return verdict('INVALID', stage='map_process_root_state')
        summaries = [r for r in events if r['kind'] == 'vm_map_process_summary']
        if any(not r.get('ok') for r in summaries):
            return verdict('INVALID', stage='map_process_root_summary')
        for row in roots:
            if row.get('repaired'):
                attributes = row['native_root'] & ~0x0000ffffffffffc0
                source = row['native_root'] & 0x0000ffffffffffc0
                expected = source - ENTRY_MC_BASE + ENTRY_PHYSICAL_BASE
                if (attributes not in (0, 1, 5) or
                        not ENTRY_MC_BASE <= source < ENTRY_MC_BASE + ENTRY_APERTURE_SIZE or
                        row['final_root'] != (expected | attributes)):
                    return verdict('INVALID', stage='map_process_root_conversion')
    if 'sdma_vm_program' in required:
        program_routes = [r for r in events if r['kind'] == 'vm_program_route']
        if len(program_routes) != 1 or not program_routes[0].get('ok'):
            return verdict('INVALID', stage='sdma_vm_program_route_guard')
    if 'sdma_vm_program' in required and require_workload_outcomes:
        submits = [r for r in events if r['kind'] == 'sdma_submit' and
                   r.get('valid') and r.get('vmid') == 2]
        programs = [r for r in events if r['kind'] == 'vm_program' and
                    r.get('hub') == 0 and r.get('vmid') == 2 and
                    len(r.get('info_words', [])) == 10 and
                    len(r.get('words', [])) == 21]
        if not submits or not programs:
            return verdict('INCONCLUSIVE', stage='sdma_vm_program_missing')
        coherent = any(
            program.get('reprogram') and program.get('root') and
            program.get('start') <= address <= program.get('end')
            for submit in submits
            for address in (submit.get('ib0', 0), submit.get('ib1', 0)) if address
            for program in programs)
        if not coherent:
            return verdict('INCONCLUSIVE', stage='sdma_vm_program_mismatch')
    if 'vmid2_entry_conversion' in required:
        entry_routes = {r.get('method'): r for r in events if r['kind'] == 'vm_entry_route'}
        if (len(entry_routes) != 2 or
                any(not r.get('ok') or not r.get('entry') for r in entry_routes.values())):
            return verdict('INVALID', stage='vmid2_entry_conversion_route_guard')
    if 'vmid2_entry_conversion' in required:
        conversions = [r for r in events if r['kind'] == 'vm_entry_conversion']
        if not conversions and require_workload_outcomes:
            return verdict('INCONCLUSIVE', stage='vmid2_entry_conversion_missing')
        final = conversions[-1] if conversions else None
        if final is not None:
            if (final.get('mode') != 3 or not final.get('pde_route') or
                    not final.get('pte_route')):
                return verdict('INVALID', stage='vmid2_entry_conversion_mode')
            if any(final.get('inactive', (0, 0))):
                return verdict('INVALID', stage='vmid2_entry_conversion_inactive',
                               next_action='page-table producers ran before the conversion gate opened; fix the gate before retry')
            if final['pde']['invalid'] or final['pte']['invalid']:
                return verdict('INVALID', stage='vmid2_entry_conversion_aperture')
        if (require_workload_outcomes and final is not None and
                final['pde']['converted'] == 0):
            return verdict('INCONCLUSIVE', stage='vmid2_entry_conversion_no_pde',
                           next_action='no child PDE crossed the aperture; inspect samples before retry')
    if 'vmid2_root_repair' in required and require_workload_outcomes:
        repairs = [r for r in events if r['kind'] == 'vm_root_repair' and
                   r.get('vmid') == 2]
        if not repairs:
            return verdict('INCONCLUSIVE', stage='vmid2_root_repair_missing')
        repaired = [r for r in repairs if r.get('repaired') and
                    r.get('reason') == 'repaired']
        if not repaired:
            reason = repairs[-1].get('reason', 'unknown')
            return verdict('INCONCLUSIVE', stage=f'vmid2_root_repair_refused:{reason}',
                           next_action='inspect the refusal reason; do not retry unchanged')
        if any(not r.get('prepared_match') for r in repaired):
            return verdict('INVALID', stage='vmid2_root_prepared_mismatch')
        if 'vmid2_entry_update' not in required:
            sequence_ids = {r.get('vm_sequence') for r in repaired}
            submits = [r for r in events if r['kind'] == 'sdma_submit' and
                       r.get('valid') and r.get('vmid') == 2 and
                       r.get('vm_sequence') in sequence_ids]
            if not submits:
                return verdict('INCONCLUSIVE', stage='vmid2_root_submit_mismatch')
            correlated = {r.get('vm_sequence') for r in submits}
            states = [r for r in events if r['kind'] == 'vm_state' and
                      r.get('vmid') == 2 and r.get('phase') == 'dispatch+0ms' and
                      r.get('vm_sequence') in correlated]
            if not states:
                return verdict('INCONCLUSIVE', stage='vmid2_root_state_missing')
            if 'vmid2_walk_hardware' not in required:
                targets = {0x400100000, 0x4000c0000, 0x400200000}
                if not any(targets <= {r.get('va') for r in events
                                      if r['kind'] == 'vm_walk' and
                                      r.get('vm_sequence') == sequence}
                           for sequence in correlated):
                    return verdict('INCONCLUSIVE', stage='vmid2_root_walk_missing')
    if 'vmid2_walk_hardware' in required and require_workload_outcomes:
        submits = sorted((r for r in events if r['kind'] == 'sdma_submit' and
                          r.get('valid') and r.get('vmid') == 2 and
                          r.get('vm_sequence')),
                         key=lambda r: r.get('seq', -1))
        first = submits[0] if submits else None
        addresses = ([value for value in
                      (first.get('ib0', 0), first.get('ib1', 0)) if value]
                     if first else [])
        if not addresses:
            return verdict('INCONCLUSIVE', stage='vmid2_walk_hardware_missing')
        sequence = first['vm_sequence']
        if any(r['kind'] == 'vm_fault' and r.get('vm_sequence') == sequence and
               r.get('fault_status') and r.get('fault_address') in addresses
               for r in events):
            return verdict('EXECUTION_FAILED', True, 'vmid2_mapping_fault',
                           'the submitted VMID2 address still faults; do not retry unchanged')
        for address in addresses:
            walks = [r for r in events if r['kind'] == 'vm_walk' and
                     r.get('vm_sequence') == sequence and r.get('va') == address]
            if not walks:
                return verdict('INCONCLUSIVE', stage='vmid2_walk_hardware_missing')
            complete = [r for r in walks if r.get('valid') and r.get('complete')]
            if not complete:
                return verdict('INCONCLUSIVE', stage='vmid2_walk_hardware_incomplete')
            walk = complete[-1]
            entries = sorted((r for r in events if r['kind'] == 'vm_walk_entry' and
                              r.get('vm_sequence') == sequence and
                              r.get('va') == address and
                              r.get('seq', -1) > walk.get('seq', -1)),
                             key=lambda r: r.get('ordinal', -1))
            entries = entries[:walk.get('count', 0)]
            if (len(entries) != walk.get('count') or
                    [r.get('ordinal') for r in entries] != list(range(len(entries)))):
                return verdict('INCONCLUSIVE', stage='vmid2_walk_hardware_incomplete')
            children = [r for r in entries if r.get('level', 0) > 0 and
                        not r.get('pde_as_pte')]
            if not children:
                return verdict('INCONCLUSIVE', stage='vmid2_walk_hardware_incomplete')
            if any(r.get('child_converted') for r in children):
                return verdict('INVALID', stage='vmid2_walk_hardware_child_translation')
    panics = [r for r in events if r['kind'] == 'guest_panic']
    raw_sdma = [r for r in events if r['kind'] == 'sdma_page_timeout' and
                r.get('source') == 'raw-terminal']
    raw_kiq = [r for r in events if r['kind'] == 'kiq' and
               r.get('source') == 'raw-terminal']
    sdma_precedes_terminal_kiq = bool(
        raw_sdma and raw_kiq and
        min(r['seq'] for r in raw_sdma) < min(r['seq'] for r in raw_kiq))
    explicit_submit = [r for r in kinds['kiq_submit']
                       if not panics or r['seq'] < panics[0]['seq']]
    live_terminal_kiq = [r for r in kinds['kiq']
                         if r.get('source') == 'live-terminal' and
                         (not panics or r['seq'] < panics[0]['seq'])]
    restore_mode = manifest.get('spec', {}).get('functional_boot_arguments', {}).get('rgpumqdrestore')
    restore_enabled = restore_mode in ('1', '2', '3')
    diagnostic_dequeue = (lambda r: restore_enabled and
                          r.get('source') == 'dequeue-timeout' and
                          r.get('restore_admitted') is True)
    diagnostic_inactive = (lambda r: restore_mode == '3' and
                           r.get('source') == 'inactive-retained' and
                           r.get('restore_admitted') is True)
    kiq_before_terminal = explicit_submit + live_terminal_kiq
    if not kiq_before_terminal:
        kiq_before_terminal = [
            r for r in kinds['kiq'] if not diagnostic_dequeue(r) and
            not diagnostic_inactive(r) and
            (not panics or r['seq'] < panics[0]['seq'])]
    terminal_kiq = (max(kiq_before_terminal, key=lambda r:r['seq'])
                    if kiq_before_terminal else None)
    if (terminal_kiq and terminal_kiq.get('result') == 0 and
            not sdma_precedes_terminal_kiq):
        return verdict('BASELINE_BLOCKED', True, 'kiq',
                       'repair stale KIQ/HQD state and remove lock-held diagnostics before another launch')
    if panics:
        panic = panics[0]
        if 'sdma_topology' in manifest.get('spec', {}).get('required_observations', []):
            routes = [r for r in events if r['kind'] == 'sdma_topology_route']
            applied = [r for r in events if r['kind'] == 'sdma_topology']
            initialized = [r for r in events if r['kind'] == 'sdma_initialize']
            if any(not r.get('ok') for r in routes):
                return verdict('INVALID', stage='sdma_topology_route_guard')
            if not (len(routes) == len(applied) == len(initialized) == 1 and
                    applied[0].get('applied') and initialized[0].get('applied') and
                    initialized[0].get('result') == 1 and routes[0]['seq'] < applied[0]['seq'] <
                    initialized[0]['seq'] < panic['seq']):
                return verdict('INCONCLUSIVE', stage='guest_panic_context_missing')
        symbol = panic.get('symbol', 'unknown')
        short = 'createAccelChannels' if 'createAccelChannels' in symbol else symbol
        offset = panic.get('offset')
        stage = f'guest_panic:{short}' + (f'+{offset:#x}' if offset is not None else '')
        return verdict('GUEST_PANIC', True, stage,
                       'decode the symbolicated fault and repair it offline; no retry')
    seqs = sorted(r['seq'] for r in events if 'seq' in r and
                  r.get('source') not in ('raw-terminal', 'live-observation',
                                          'live-readiness'))
    if (any(r['kind'] == 'capture_loss' for r in events) or
            seqs != list(range(len(seqs)))):
        return verdict('INCONCLUSIVE', stage='capture_loss')
    if 'sdma_topology' in manifest.get('spec', {}).get('required_observations', []):
        routes = [r for r in events if r['kind'] == 'sdma_topology_route']
        applied = [r for r in events if r['kind'] == 'sdma_topology']
        initialized = [r for r in events if r['kind'] == 'sdma_initialize']
        one_starts = [r for r in events if r['kind'] == 'sdma_one_start']
        selections = [r for r in events if r['kind'] == 'sdma_select']
        if any(not r.get('ok') for r in routes):
            return verdict('INVALID', stage='sdma_topology_route_guard')
        if (len(routes) != 1 or len(applied) != 1 or len(initialized) != 1 or
                len(one_starts) != 1 or
                any(not r.get('applied') for r in applied + initialized)):
            return verdict('INCONCLUSIVE', stage='sdma_topology_missing')
        if any(r.get('result') == 0 for r in initialized + one_starts):
            return verdict('STARTUP_FAILED_LATER', True, 'sdma_engine_start',
                           'inspect the preserved native SDMA initialization/start failure')
        if any(r.get('index') != 0 for r in selections):
            return verdict('STARTUP_FAILED_LATER', True, 'sdma_topology_effect',
                           'the removed SDMA instance is still reaching native selection')
        sdma_events = sorted(
            (r for r in events if r['kind'] == 'sdma_select' or
             (r['kind'] in ('hybrid_enter', 'hybrid_exit') and
              r.get('engine') in (10, 11))),
            key=lambda r: r['seq'])
        expected = (
            ('hybrid_enter', 10, None),
            ('sdma_select', None, 0),
            ('hybrid_exit', 10, None),
            ('hybrid_enter', 11, None),
            ('sdma_select', None, 1),
            ('hybrid_exit', 11, None),
        )
        if len(sdma_events) != len(expected):
            return verdict('INCONCLUSIVE', stage='sdma_topology_effect_missing')
        for row, (kind, engine, queue_type) in zip(sdma_events, expected):
            if row['kind'] != kind:
                return verdict('INCONCLUSIVE', stage='sdma_topology_order')
            if engine is not None and row.get('engine') != engine:
                return verdict('INCONCLUSIVE', stage='sdma_topology_effect_missing')
            if kind == 'hybrid_enter' and row.get('available') != 1:
                return verdict('INCONCLUSIVE', stage='sdma_topology_effect_missing')
            if kind == 'hybrid_exit' and row.get('result') != 0:
                return verdict('INCONCLUSIVE', stage='sdma_topology_effect_missing')
            if kind == 'sdma_select' and not (
                    row.get('index') == 0 and row.get('queue_type') == queue_type and
                    row.get('found') and row.get('counts') == [1, 0, 0, 0]):
                return verdict('INCONCLUSIVE', stage='sdma_topology_effect_missing')
        starts = [r for r in events if r['kind'] == 'engine_start']
        if (len(starts) != 1 or not routes[0]['seq'] < applied[0]['seq'] <
                initialized[0]['seq'] < sdma_events[0]['seq'] <
                sdma_events[-1]['seq'] < one_starts[0]['seq'] < starts[0]['seq']):
            return verdict('INCONCLUSIVE', stage='sdma_topology_order')
        if 'sdma_channel_remap' in manifest.get('spec', {}).get('required_observations', []):
            expected_route_count = (7 if any(name in
                                    manifest.get('spec', {}).get('required_observations', [])
                                    for name in ('sdma_ib_address_repair', 'sdma_vm_context',
                                                 'sdma_vm_program')) else 6)
            if routes[0].get('count') != expected_route_count:
                return verdict('INVALID', stage='sdma_channel_route_guard')
            remaps = [r for r in events if r['kind'] == 'sdma_engine_remap']
            if not remaps:
                return verdict('INCONCLUSIVE', stage='sdma_channel_remap_missing')
            if any(r.get('requested') != 2 or r.get('selected') != 1 for r in remaps):
                return verdict('STARTUP_FAILED_LATER', True, 'sdma_channel_remap',
                               'inspect the unexpected SDMA channel mapping')
            if not initialized[0]['seq'] < remaps[0]['seq'] < one_starts[0]['seq']:
                return verdict('INCONCLUSIVE', stage='sdma_channel_remap_order')
        if 'sdma_vm_context' in manifest.get('spec', {}).get('required_observations', []):
            submits = [r for r in events if r['kind'] == 'sdma_submit' and
                       r.get('valid') and r.get('vmid') == 2]
            invalidates = [r for r in events if r['kind'] == 'vm_invalidate' and
                           r.get('hub') == 0 and r.get('vmid') == 2]
            contexts = [r for r in events if r['kind'] == 'vm_context' and
                        r.get('vmid') == 2]
            if not submits or not invalidates or not contexts:
                return verdict('INCONCLUSIVE', stage='sdma_vm_context_missing')
            # The hardware context is read later by a dedicated worker so the
            # driver callback never performs MMIO or serial formatting while a
            # caller lock may be held. Treat it as an asynchronous snapshot:
            # require a coherent request/snapshot chain that actually contains
            # one of the submitted GPU virtual addresses. Mere coexistence of
            # three unrelated records cannot validate this observation.
            coherent = False
            for submit in submits:
                addresses = [submit.get('ib0', 0), submit.get('ib1', 0)]
                for address in (value for value in addresses if value):
                    for request in invalidates:
                        if (not request.get('reprogram') or not request.get('root') or
                                not request.get('start') <= address <= request.get('end')):
                            continue
                        if any(context.get('root') == request.get('root') and
                               context.get('start') <= address <= context.get('end')
                               for context in contexts):
                            coherent = True
                            break
                    if coherent:
                        break
                if coherent:
                    break
            if not coherent:
                return verdict('INCONCLUSIVE', stage='sdma_vm_context_mismatch')
        if any(r['kind'] == 'sdma_page_timeout' for r in events):
            return verdict('SDMA_PAGE_TIMEOUT', True, 'sdma0_page',
                           'inspect the indirect packet and SDMA VM state; do not retry unchanged')
        if 'sdma_ib_address_repair' in manifest.get('spec', {}).get('required_observations', []):
            repairs = [r for r in events if r['kind'] == 'sdma_ib_repair' and
                       r.get('valid') and r.get('changed')]
            if not repairs:
                return verdict('INCONCLUSIVE', stage='sdma_ib_address_repair_missing')
            if any(r['seq'] <= starts[0]['seq'] for r in repairs):
                return verdict('INCONCLUSIVE', stage='sdma_ib_address_repair_order')
    if 'sdma_selection' in manifest.get('spec', {}).get('required_observations', []):
        routes = [r for r in events if r['kind'] == 'sdma_route']
        if any(not r.get('ok') for r in routes):
            return verdict('INVALID', stage='sdma_route_guard')
        target = manifest['spec'].get('sdma_selection_target', {})
        selections = [r for r in events if r['kind'] == 'sdma_select' and
                      r.get('index') == target.get('index') and
                      r.get('queue_type') == target.get('queue_type')]
        if not routes or not selections:
            return verdict('INCONCLUSIVE', stage='sdma_selection_missing')
    if not kinds['kiq'] or not kinds['hybrid_enter'] or not kinds['hybrid_exit']:
        return verdict('INCONCLUSIVE', stage='required_native_record_missing')
    for row in kinds['hybrid_exit']:
        if row['result'] == 4:
            name = 'HYBRID_QUEUE_SUSPECTED' if row['available'] else 'HYBRID_UNAVAILABLE_SUSPECTED'
            return verdict(name, True, 'hybrid', 'locate native rejecting branch; snapshot is not causal proof')
        if row['result'] != 0:
            return verdict('HYBRID_FAILED', True, 'hybrid', 'decode native result and arguments offline')
    if not kinds['engine_start']:
        return verdict('INCONCLUSIVE', stage='engine_start_missing')
    if any(r['result'] == 0 for r in kinds['engine_start']):
        return verdict('STARTUP_FAILED_LATER', True, 'engine_start', 'trace the next native startup failure')
    if any(r['kind'] == 'sdma_page_timeout' for r in events):
        return verdict('SDMA_PAGE_TIMEOUT', True, 'sdma0_page',
                       'inspect the repaired indirect packet and SDMA VM state; do not retry unchanged')
    if probe is None:
        return verdict('PROBE_NOT_RUN', True, next_action='run the prepared probe only if remaining budget permits')
    if not isinstance(probe, dict) or 'run_id' not in probe or 'output' not in probe:
        return verdict('INCONCLUSIVE', stage='probe_evidence_missing')
    if not manifest.get('run_id') or probe['run_id'] != manifest['run_id']:
        return verdict('INVALID', stage='probe_identity')
    if probe:
        profile = manifest.get('probe_profile', {})
        profile_name = profile.get('name') if isinstance(profile, dict) else profile
        path = Path(__file__).with_name(
            'small-metal-test.py' if profile_name == 'small-metal' else 'metal-test.py')
        spec = importlib.util.spec_from_file_location('metal_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        try:
            if not manifest.get('run_id') or probe['run_id'] != manifest['run_id']:
                raise ValueError('probe nonce differs from the prepared experiment')
            module.validate_output(probe['output'], manifest['run_id'])
        except (KeyError, ValueError, TypeError):
            exits = re.findall(r'^RGPU_EXIT '+re.escape(manifest['run_id'])+r' (\d+)$', probe['output'], re.M)
            if len(exits) != 1:
                return verdict('INCONCLUSIVE', stage='probe_completion_missing')
        else:
            return verdict('CORE_PROBE_PASS', True, next_action='qualify memory, lifecycle and desktop; core probe alone is insufficient')
    return verdict('EXECUTION_FAILED', True, 'first_submission', 'inspect command completion and checked output')


def classify(manifest, events, probe):
    return _classify(manifest, events, probe)


def classify_probe_readiness(manifest, events):
    """Classify native startup while the workload-dependent records are still absent."""
    result = _classify(manifest, events, None, defer_absent_workload=True)
    if result['verdict'] != 'PROBE_NOT_RUN':
        return result
    starts = [r for r in events if r['kind'] == 'accelerator_start']
    if len(starts) != 1:
        result.update(valid=False, verdict='INCONCLUSIVE',
                      earliest_failure='accelerator_start_missing',
                      next_action='wait for the outer accelerator power-up result')
    elif starts[0].get('result') != 1:
        result.update(valid=True, verdict='STARTUP_FAILED_LATER',
                      earliest_failure='accelerator_start',
                      next_action='trace the outer accelerator power-up failure')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory', type=Path)
    args = parser.parse_args()
    run = args.run_directory
    manifest = json.loads((run / 'manifest.json').read_text())
    events = parse_manifest_files(manifest, run)
    probe_path = run / 'probe.json'
    probe = json.loads(probe_path.read_text()) if probe_path.exists() else None
    print(json.dumps(classify(manifest, events, probe), indent=2))
