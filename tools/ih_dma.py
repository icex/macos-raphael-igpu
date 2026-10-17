"""OSSSYS 5 interrupt-handler DMA shutdown and independently checked evidence.

Offsets/masks: Linux navi10_ih.c and osssys_5_0_0_{offset,sh_mask}.h,
revision 238650ef6c7c7cca08e032527329424c9fbd70e5. Raphael OSSSYS base
is 0x10a0 dwords. Never change a ring base, pointer, address space or size.
"""
import math
import time

BASE = 0x10a0
RINGS = ((0x80, 0x84, 0x00020101),
         (0x8c, 0x90, 0x00000001),
         (0x98, 0x9c, 0x00000001))
CNTL2 = (BASE + 0xc1) * 4
WPTR_FORCE_ENABLE = 0x100
SAMPLES = 5
INTERVAL = 0.025


def snapshot(mmio):
    rings = []
    for control, pointer, mask in RINGS:
        value = mmio.read32((BASE + control) * 4)
        wptr = mmio.read32((BASE + pointer) * 4)
        if value == 0xffffffff or wptr == 0xffffffff:
            raise ValueError('inaccessible IH ring registers')
        rings.append({'control': value, 'wptr': wptr})
    cntl2 = mmio.read32(CNTL2)
    if cntl2 == 0xffffffff:
        raise ValueError('inaccessible IH_CNTL2')
    return {'rings': rings, 'cntl2': cntl2}


def validate(proof):
    """Validate serialized evidence without trusting a producer's status flag."""
    errors = []
    try:
        samples = proof['samples']
        if type(samples) is not list or len(samples) != SAMPLES:
            return ['ih_sample_coverage']
        times = [s['monotonic'] for s in samples]
        if (any(type(t) not in (float, int) or not math.isfinite(t) for t in times) or
                any(b - a < INTERVAL * 0.9 for a, b in zip(times, times[1:]))):
            errors.append('ih_sample_interval')
        for sample in samples:
            if type(sample['rings']) is not list or len(sample['rings']) != 3:
                return ['ih_ring_coverage']
            cntl2 = sample['cntl2']
            if type(cntl2) is not int or not 0 <= cntl2 < 0xffffffff:
                errors.append('ih_cntl2_inaccessible')
            elif cntl2 & WPTR_FORCE_ENABLE:
                errors.append('ih_force_enabled')
            for ring, (_, _, mask) in zip(sample['rings'], RINGS):
                for key in ('control', 'wptr'):
                    if type(ring[key]) is not int or not 0 <= ring[key] < 0xffffffff:
                        errors.append('ih_inaccessible')
                if ring['control'] & mask:
                    errors.append('ih_enabled')
        for index in range(3):
            if len({s['rings'][index]['wptr'] for s in samples}) != 1:
                errors.append('ih_pointer_moving')
            if len({s['rings'][index]['control'] for s in samples}) != 1:
                errors.append('ih_control_unstable')
    except (KeyError, TypeError, ValueError, OverflowError):
        errors.append('ih_malformed')
    return sorted(set(errors))


def inspect(mmio, *, sleep=time.sleep, monotonic=time.monotonic):
    samples = []
    for index in range(SAMPLES):
        if index:
            sleep(INTERVAL)
        sample = snapshot(mmio)
        sample['monotonic'] = monotonic()
        samples.append(sample)
    return {'samples': samples}


def quiesce(mmio):
    before = snapshot(mmio)
    writes = []
    # Stop self-interrupt forcing before disabling the three hardware rings.
    registers = [(CNTL2, WPTR_FORCE_ENABLE, before['cntl2'])]
    registers += [((BASE + reg) * 4, mask, ring['control'])
                  for (reg, _, mask), ring in zip(RINGS, before['rings'])]
    for offset, mask, old in registers:
        new = old & ~mask
        if new != old:
            mmio.write32(offset, new)
        observed = mmio.read32(offset)  # Flush posted writes; preserve every other bit.
        writes.append({'offset': offset, 'before': old, 'after': observed, 'mask': mask})
        if observed != new:
            raise ValueError('IH disable readback mismatch')
    proof = {'before': before, 'writes': writes, **inspect(mmio)}
    errors = validate(proof)
    if errors:
        raise ValueError('IH did not quiesce: ' + ','.join(errors))
    return proof
