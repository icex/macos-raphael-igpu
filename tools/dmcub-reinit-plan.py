#!/usr/bin/env python3
"""Offline review manifest only. No device access, MMIO, reset, or launch support."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess

FIRMWARE_SHA = 'c198f520748ed8ac0b8bec04c7d85d2962865c6bbe6c9a6791e661c23750b8d5'
VBIOS_SHA = 'b77d1d7f5d8a402936b60f1e84e89ccfcb0f320c2490ec9f8df11bcbb8742123'
LINUX_COMMIT = '238650ef6c7c7cca08e032527329424c9fbd70e5'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def align(n, boundary):
    return (n + boundary - 1) & ~(boundary - 1)


def plan(firmware, vbios, capture, linux):
    blob = subprocess.check_output(['zstd', '-dc', str(firmware)])
    bios = vbios.read_bytes()
    if sha(blob) != FIRMWARE_SHA or sha(bios) != VBIOS_SHA:
        raise ValueError('unreviewed firmware or VBIOS')
    header = struct.unpack_from('<10I', blob)
    if header[0] != len(blob) or header[4] != 0x05003500 or header[9] != 0:
        raise ValueError('unexpected firmware header/version/BSS')
    start = header[6] + 256
    # Linux dmub_srv_get_fw_meta_info_from_raw_fw: remove PSP footer too.
    count = header[8] - 256 - 256
    metadata = []
    for pad in range(16):
        at = start + count - 64 - pad
        if struct.unpack_from('<I', blob, at)[0] == 0x444d5542:
            metadata.append((at, struct.unpack_from('<8I', blob, at)))
    if len(metadata) != 1:
        raise ValueError('ambiguous/missing firmware metadata')
    at, meta = metadata[0]
    if meta[3] != header[4] or meta[4:] != (1, 0, 0, 0):
        raise ValueError('unreviewed firmware features')
    if (count, meta[1], meta[2]) != (0x3a520, 0xc880, 0x10010):
        raise ValueError('unreviewed firmware sizes')
    captured = json.loads(capture.read_text())
    if captured['status'] != 'captured' or captured['total'] != 0x80000000:
        raise ValueError('unexpected retained-state capture')
    if captured['host_after']['active_vm'] or captured['host_after']['driver'] != 'vfio-pci':
        raise ValueError('capture was not stopped VFIO state')
    for snap in captured['snapshots']:
        for filename, digest in snap['files'].items():
            if sha((capture.parent / filename).read_bytes()) != digest:
                raise ValueError('capture artifact hash mismatch')
    commit = subprocess.check_output(['git', '-C', str(linux), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != LINUX_COMMIT:
        raise ValueError('unreviewed Linux reference')
    sources = {}
    for name in ['display/dmub/src/dmub_srv.c', 'display/dmub/src/dmub_dcn31.c',
                 'display/dmub/inc/dmub_cmd.h', 'display/amdgpu_dm/amdgpu_dm_dmub.c',
                 'include/asic_reg/dcn/dcn_3_1_5_offset.h',
                 'include/asic_reg/dcn/dcn_3_1_5_sh_mask.h']:
        source = (linux/'drivers/gpu/drm/amd'/name).read_bytes()
        committed = subprocess.check_output(['git', '-C', str(linux), 'show',
                                            commit+':drivers/gpu/drm/amd/'+name])
        if source != committed:
            raise ValueError('Linux reference source has uncommitted changes')
        sources[name] = sha(source)
    rows = []
    end = 0x7f000000
    for cw, name, size in [(0, 'instructions', count), (1, 'stack_context', 640*1024),
                           (3, 'vbios', len(bios)), (4, 'mailboxes', 16384),
                           (5, 'trace', meta[2]), (6, 'firmware_state', meta[1])]:
        offset = align(end, 256)
        length = align(size, 64)
        end = offset + length
        # CW0/1 use physical FB translation; CW3..6 use MC addresses.
        domain = 'physical_fb' if cw < 2 else 'mc'
        address = captured['physical' if cw < 2 else 'mc'] + offset
        base = 0x60000000 + (cw << 24)
        # Linux uses size-1 for CW0/1; size for CW3..6. Allocate the extra byte.
        top = base + length - (1 if cw < 2 else 0)
        rows.append(dict(cw=cw, name=name, payload_bytes=size, allocation_bytes=length,
                         framebuffer_offset=hex(offset), address_domain=domain,
                         register_offset_address=hex(address), virtual_base=hex(base),
                         top_inclusive_register=hex(0x80000000 | (top & 0x1fffffff))))
        if cw >= 3:
            end += 1
    allocation_end = align(end, 4096)
    if allocation_end > 0x7f200000:
        raise ValueError('layout exceeds proposed 2 MiB reservation')
    registers = captured['snapshots'][0]['registers']
    retained = []
    for cw in (0, 1, 3, 4, 5, 6):
        address = registers[hex(0x3675+2*cw)] | registers[hex(0x3676+2*cw)] << 32
        base = registers[hex(0x3665+cw)] & 0x1fffffff
        top = registers[hex(0x366d+cw)]
        size = (top & 0x1fffffff) - base + 1
        offsets = {address-domain for domain in (captured['physical'], captured['mc'])
                   if 0 <= address-domain <= captured['total']-size}
        if not top & 0x80000000 or len(offsets) != 1 or size <= 0:
            raise ValueError('invalid retained window')
        offset = offsets.pop()
        if max(offset, 0x7f000000) < min(offset+size, allocation_end):
            raise ValueError('new layout overlaps retained windows')
        retained.append(dict(cw=cw, start=hex(offset), end=hex(offset+size)))
    return dict(schema=1, review_only=True, executable=False,
                authorization='Preparation only; hardware reinitialization not approved',
                firmware=dict(path=str(firmware), uncompressed_sha256=sha(blob),
                              version=hex(header[4]), payload_offset=start,
                              payload_bytes=count, payload_sha256=sha(blob[start:start+count]),
                              metadata_file_offset=at, psp_header_bytes=256, psp_footer_bytes=256),
                vbios=dict(path=str(vbios), bytes=len(bios), sha256=sha(bios)),
                reference=dict(linux_commit=commit, source_sha256=sources,
                               capture=str(capture), capture_sha256=sha(capture.read_bytes()),
                               observed_boot=captured['boot_id']),
                reservation=dict(start='0x7f000000', end=hex(allocation_end),
                                 allowed_end='0x7f200000', requires_live_revalidation=True),
                retained_windows=retained, windows=rows, boot_options_scratch14='0x80',
                validation='Offline layout and pinned input checks only; no hardware-safety claim')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['firmware', 'vbios', 'capture', 'linux', 'output']:
        p.add_argument('--'+name, type=Path, required=True)
    a = p.parse_args()
    result = plan(a.firmware, a.vbios, a.capture, a.linux)
    with a.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps({'review_only': True, 'reservation': result['reservation'],
                      'payload_bytes': result['firmware']['payload_bytes']}, indent=2))
