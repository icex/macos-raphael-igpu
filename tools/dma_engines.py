"""Stop the measured Raphael GC/SDMA input paths before VFIO unmaps RAM.

GC/SDMA offsets and masks match the sealed vfio-recover.py and Linux gfx_v10_0
and sdma_v5_2 halt/idle paths. Queue retirement/PSP recovery remains separate.
No ring pointers, target addresses, reset or binding changes are made here.
"""
import math
import time

GC = 0x1260
# (name, byte offset, clear mask, set mask). Preserve every other control bit.
CONTROLS = (
    ('pq_poll', (GC + 0x1e23) * 4, 0x80000000, 0),
    ('pq_doorbell', (GC + 0x1e58) * 4, 2, 0),
    ('me', (GC + 0x0f56) * 4, 0, 0x15000000),
    ('mec', (GC + 0x0f55) * 4, 0, 0x50000000),
    ('sdma_context', (GC + 0x001c) * 4, 0x40000, 0),
    ('sdma_gfx_ib', (GC + 0x008a) * 4, 1, 0),
    ('sdma_gfx_rb', (GC + 0x0080) * 4, 1, 0),
    ('sdma_page_ib', (GC + 0x00e2) * 4, 1, 0),
    ('sdma_page_rb', (GC + 0x00d8) * 4, 1, 0),
    ('sdma_rlc0_ib', (GC + 0x013a) * 4, 1, 0),
    ('sdma_rlc0_rb', (GC + 0x0130) * 4, 1, 0),
    ('sdma_rlc1_ib', (GC + 0x0192) * 4, 1, 0),
    ('sdma_rlc1_rb', (GC + 0x0188) * 4, 1, 0),
    ('sdma_f32', (GC + 0x002a) * 4, 0, 1),
)
STATUS = (
    ('cp', (GC + 0x0f40) * 4),
    ('cpc', (GC + 0x0e25) * 4),
    ('grbm', (GC + 0x0da4) * 4),
    ('sdma', (GC + 0x0025) * 4),
)


def read(mmio, offset):
    value = mmio.read32(offset)
    if type(value) is not int or not 0 <= value < 0xffffffff:
        raise ValueError('inaccessible DMA engine register')
    return value


def snapshot(mmio):
    return {**{name: read(mmio, offset) for name, offset, _, _ in CONTROLS},
            **{name: read(mmio, offset) for name, offset in STATUS}}


def stopped(values):
    return (all(values[name] & clear == 0 and values[name] & set_mask == set_mask
                for name, _, clear, set_mask in CONTROLS) and
            values['cp'] == 0 and values['cpc'] == 0 and
            values['grbm'] & 0x80000000 == 0 and values['sdma'] & 1 == 1)


def validate(proof):
    try:
        writes, samples = proof['writes'], proof['samples']
        if len(writes) != len(CONTROLS) or len(samples) != 5:
            return ['dma_engines_incomplete']
        for row, (name, offset, clear, set_mask) in zip(writes, CONTROLS):
            old = row['before']
            if (row['name'] != name or row['offset'] != offset or
                    type(old) is not int or not 0 <= old < 0xffffffff or
                    row['after'] != ((old & ~clear) | set_mask)):
                return ['dma_engines_writes']
        expected_keys = {name for name, *_ in CONTROLS} | {name for name, _ in STATUS}
        previous = None
        for sample in samples:
            values, timestamp = sample['values'], sample['monotonic']
            if (set(values) != expected_keys or
                    any(type(v) is not int or not 0 <= v < 0xffffffff for v in values.values()) or
                    not stopped(values) or type(timestamp) not in (int, float) or
                    not math.isfinite(timestamp) or
                    (previous is not None and timestamp - previous < 0.02)):
                return ['dma_engines_not_stopped']
            previous = timestamp
        return []
    except (KeyError, TypeError, ValueError):
        return ['dma_engines_malformed']


def quiesce(mmio, sleep=time.sleep, monotonic=time.monotonic):
    writes = []
    for name, offset, clear, set_mask in CONTROLS:
        old = read(mmio, offset)
        new = (old & ~clear) | set_mask
        if old != new:
            mmio.write32(offset, new)
        after = read(mmio, offset)
        writes.append({'name': name, 'offset': offset, 'before': old, 'after': after})
        if after != new:
            raise ValueError('DMA engine halt readback mismatch: ' + name)
    deadline = monotonic() + 5
    while not stopped(snapshot(mmio)):
        if monotonic() >= deadline:
            raise ValueError('GC/SDMA did not become idle; retain DMA mappings')
        sleep(0.01)
    samples = []
    for index in range(5):
        if index:
            sleep(0.025)
        samples.append({'values': snapshot(mmio), 'monotonic': monotonic()})
    proof = {'writes': writes, 'samples': samples}
    errors = validate(proof)
    if errors:
        raise ValueError('GC/SDMA stop proof failed: ' + ','.join(errors))
    return proof
