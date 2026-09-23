#!/usr/bin/env python3
"""Read retained DMCUB windows through MM_INDEX while QEMU is stopped.

Only MM_INDEX and MM_INDEX_HI are written and restored. No MM_DATA, firmware,
DMCUB controls, queue pointers, or reset writes are issued.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import time


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), Path(__file__).with_name(name+'.py'))
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


R = load('vfio-recover')
H = load('mode2-noqueue-recover')


def window_offset(address, physical, mc, total, length):
    if not 0 < length <= 0x20000:
        raise ValueError('window length')
    offsets = {address - base for base in (physical, mc)
               if address >= base and address - base <= total - length}
    if len(offsets) != 1:
        raise ValueError('ambiguous or invalid window address')
    offset = offsets.pop()
    if offset < total - 0x2000000 or offset & 3:
        raise ValueError('outside reserved tail')
    return offset


def capture(vm, output):
    output.mkdir(parents=True, exist_ok=False)
    evidence = {'status': 'failed', 'writes': 'MM_INDEX and MM_INDEX_HI only', 'snapshots': []}
    with (vm/'run/experiment.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        evidence['host_before'] = H.host_gate(boot)
        cursor, _, faults = R.kernel_updates()
        if faults: raise ValueError('host faults')
        with R.LegacyVfio() as m:
            def rd(index): return R._load_mmio_u32(m.bar, 4*index)
            def selector(index, value):
                if index not in (0, 6): raise ValueError('forbidden write')
                m.write32(index*4, value)
            total = rd(R.NBIO_CONFIG_MEMSIZE_OFFSET//4) << 20
            physical = (rd(0x2947) & 0xffffff) << 24
            mc = (rd(0x295c) & 0xffffff) << 24
            saved = (rd(0), rd(6))
            evidence.update(boot_id=boot, total=total, physical=physical, mc=mc,
                            saved_selectors=list(saved), windows={})
            try:
                for window in (4, 5, 6):
                    address = rd(0x3675+2*window) | rd(0x3676+2*window) << 32
                    base = rd(0x3665+window) & 0x1fffffff
                    top = rd(0x366d+window)
                    if not top & 0x80000000: raise ValueError('window disabled')
                    # Linux setup_windows uses an inclusive extra top byte for these windows.
                    length = ((top & 0x1fffffff) - base) & ~3
                    offset = window_offset(address, physical, mc, total, length)
                    evidence['windows'][str(window)] = dict(offset=offset, length=length, address=address)
                for sample in range(2):
                    row = {'registers': {hex(i): rd(i) for i in range(0x364e, 0x36c1)}, 'files': {}}
                    for window, info in evidence['windows'].items():
                        data = bytearray()
                        for at in range(info['offset'], info['offset']+info['length'], 4):
                            selector(0, (at & 0xffffffff) | 0x80000000)
                            selector(6, at >> 31)
                            data.extend(struct.pack('<I', rd(1)))
                        name = f'cw{window}-{sample}.bin'
                        (output/name).write_bytes(data)
                        row['files'][name] = hashlib.sha256(data).hexdigest()
                    evidence['snapshots'].append(row)
                    if sample == 0: time.sleep(0.1)
            finally:
                selector(0, saved[0]); selector(6, saved[1])
                evidence['restored_selectors'] = [rd(0), rd(6)]
                if evidence['restored_selectors'] != list(saved):
                    raise ValueError('MM_INDEX restore mismatch')
        evidence['host_after'] = H.host_gate(boot)
        evidence['kernel_cursor'], evidence['kernel_messages'], faults = R.kernel_updates(cursor)
        if faults: raise ValueError('new host faults')
        evidence['status'] = 'captured'
        (output/'capture.json').write_text(json.dumps(evidence, indent=2)+'\n')
    return evidence


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vm-dir', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    a = p.parse_args()
    result = capture(a.vm_dir.resolve(), a.output.resolve())
    print(json.dumps({k: result[k] for k in ('status','boot_id','windows','restored_selectors')}, indent=2))
