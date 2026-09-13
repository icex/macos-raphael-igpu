#!/usr/bin/env python3
"""Reset the Raphael graphics core with the SMU MODE2 message over user-owned VFIO.

This reproduces what amdgpu does for this APU at unbind (nv_asic_mode2_reset ->
smu_v13_0_5_mode2_reset): clear bus mastering, cache the PCI config space, send
PPSMC_MSG_GfxDeviceDriverReset with SMU_RESET_MODE_2 through the MP1 13.0.5
mailbox, restore the config space, and wait for NBIO to report a memory size.
The mailbox lives in SMN space and is reached through the NBIO 7.2 PCIE_INDEX2 /
PCIE_DATA2 pair in BAR5, the way amdgpu_device_indirect_rreg/wreg do.

`--probe` only reads state and sends GetSmuVersion, which changes nothing.
`--execute` performs the reset. Both write a JSON receipt.
"""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import struct
import time
from pathlib import Path


def _load_recover():
    path = Path(__file__).with_name('vfio-recover.py')
    spec = importlib.util.spec_from_file_location('vfio_recover_host', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = _load_recover()

# NBIO 7.2 (nbio_7_2_0_offset.h, BASE_IDX 0 -> NBIO segment 0 at 0x0)
PCIE_INDEX2_OFFSET = 0x000e * 4
PCIE_DATA2_OFFSET = 0x000f * 4
# MP1 13.0.5 mailbox (smu_v13_0_5_ppt.c local defines + MP1_BASE segment 0 0x16000);
# dword index * 4 is the SMN byte address.
SMN_MP1_C2PMSG_2 = ((0xbee142 + 0xb00000 // 4) + 0x16000) * 4    # message   0x03B10508
SMN_MP1_C2PMSG_33 = ((0xbee261 + 0xb00000 // 4) + 0x16000) * 4   # response  0x03B10984
SMN_MP1_C2PMSG_34 = ((0xbee262 + 0xb00000 // 4) + 0x16000) * 4   # argument  0x03B10988
SMN_MP1_FIRMWARE_FLAGS = 0x03b00000 | 0x3010024
PPSMC_MSG_GetSmuVersion = 2
PPSMC_MSG_GfxDeviceDriverReset = 10
SMU_RESET_MODE_2 = 2
SMU_RESP = {0: 'none', 1: 'ok', 0xff: 'cmd-fail', 0xfe: 'cmd-unknown',
            0xfd: 'bad-prereq', 0xfc: 'busy-other', 0xfb: 'debug-end'}
VFIO_PCI_CONFIG_REGION_INDEX = 7
PCI_COMMAND = 0x04
PCI_COMMAND_MASTER = 0x4
# GC 10.3 registers (dword index; segment 0 at 0x1260, segment 1 at 0xa000)
GC_SEG0, GC_SEG1 = 0x1260, 0xa000
GC_REGS = {
    'GRBM_STATUS': GC_SEG0 + 0x0da4, 'GRBM_STATUS2': GC_SEG0 + 0x0da2,
    'CP_STAT': GC_SEG0 + 0x0f40, 'CP_ME_CNTL': GC_SEG0 + 0x0f56,
    'CP_MEC_CNTL': GC_SEG0 + 0x0f55, 'CP_CPC_STATUS': GC_SEG0 + 0x0e24,
    'CP_CPF_STATUS': GC_SEG0 + 0x0e27, 'RLC_CNTL': GC_SEG1 + 0x4c00,
    'RLC_STAT': GC_SEG1 + 0x4c04, 'RLC_BOOTLOAD_STATUS': GC_SEG1 + 0x4e8d,
    'RLC_GPM_STAT': GC_SEG1 + 0x4e6e, 'RLC_CP_SCHEDULERS': GC_SEG1 + 0x4ca1,
    'CH_PIPE_STEER': GC_SEG1 + 0x2d90, 'GL1_PIPE_STEER': GC_SEG1 + 0x2d10,
    'GB_ADDR_CONFIG': GC_SEG0 + 0x13de,
}


class Smn:
    def __init__(self, mmio):
        self.mmio = mmio

    def rreg(self, address):
        R._store_mmio_u32(self.mmio.bar, PCIE_INDEX2_OFFSET, address)
        R._load_mmio_u32(self.mmio.bar, PCIE_INDEX2_OFFSET)
        return R._load_mmio_u32(self.mmio.bar, PCIE_DATA2_OFFSET)

    def wreg(self, address, value):
        R._store_mmio_u32(self.mmio.bar, PCIE_INDEX2_OFFSET, address)
        R._load_mmio_u32(self.mmio.bar, PCIE_INDEX2_OFFSET)
        R._store_mmio_u32(self.mmio.bar, PCIE_DATA2_OFFSET, value)
        R._load_mmio_u32(self.mmio.bar, PCIE_DATA2_OFFSET)


class ConfigSpace:
    def __init__(self, mmio):
        region = R.VfioRegionInfo(ctypes.sizeof(R.VfioRegionInfo), 0,
                                  VFIO_PCI_CONFIG_REGION_INDEX, 0, 0, 0)
        R.ioctl(mmio.device_fd, R.VFIO_DEVICE_GET_REGION_INFO, ctypes.byref(region))
        if region.size < 256:
            raise R.RecoveryError('PCI config region is too small')
        self.fd = mmio.device_fd
        self.base = region.offset

    def read(self, offset, size):
        data = os.pread(self.fd, size, self.base + offset)
        if len(data) != size:
            raise R.RecoveryError('short PCI config read')
        return data

    def write(self, offset, data):
        if os.pwrite(self.fd, data, self.base + offset) != len(data):
            raise R.RecoveryError('short PCI config write')

    def command(self):
        return struct.unpack('<H', self.read(PCI_COMMAND, 2))[0]

    def set_command(self, value):
        self.write(PCI_COMMAND, struct.pack('<H', value))
        return self.command()


def poll_response(smn, timeout_s):
    deadline = time.monotonic() + timeout_s
    while True:
        resp = smn.rreg(SMN_MP1_C2PMSG_33)
        if resp != 0 or time.monotonic() >= deadline:
            return resp
        time.sleep(0.0002)


def send_message(smn, index, argument, timeout_s=3.0):
    """smu_msg_v1_send_msg without the RAS filter: pre-poll, send, post-poll."""
    pre = smn.rreg(SMN_MP1_C2PMSG_33)
    if pre == 0:
        pre = poll_response(smn, timeout_s)
    smn.wreg(SMN_MP1_C2PMSG_33, 0)
    smn.wreg(SMN_MP1_C2PMSG_34, argument)
    smn.wreg(SMN_MP1_C2PMSG_2, index)
    resp = poll_response(smn, timeout_s)
    out = smn.rreg(SMN_MP1_C2PMSG_34)
    return {'message': index, 'argument': argument, 'pre_response': pre,
            'response': resp, 'response_name': SMU_RESP.get(resp, 'unexpected'),
            'out_argument': out, 'ok': resp == 1}


def gc_snapshot(mmio):
    return {name: mmio.read32(index * 4) for name, index in GC_REGS.items()}


def run(args):
    receipt = {'schema': 1, 'mode': 'execute' if args.execute else 'probe',
               'started': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
               'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
               'device': R.DEVICE}
    with R.LegacyVfio() as mmio:
        smn = Smn(mmio)
        cfg = ConfigSpace(mmio)
        receipt['memsize_before'] = mmio.read32(R.NBIO_CONFIG_MEMSIZE_OFFSET)
        receipt['mp1_firmware_flags'] = smn.rreg(SMN_MP1_FIRMWARE_FLAGS)
        receipt['pci_command_before'] = cfg.command()
        receipt['gc_before'] = gc_snapshot(mmio)
        receipt['mailbox_before'] = {
            'msg': smn.rreg(SMN_MP1_C2PMSG_2), 'resp': smn.rreg(SMN_MP1_C2PMSG_33),
            'arg': smn.rreg(SMN_MP1_C2PMSG_34)}
        if receipt['mp1_firmware_flags'] in (0, 0xffffffff):
            receipt['error'] = 'MP1 firmware flags unreadable; refusing to touch the mailbox'
            return receipt
        receipt['version_probe'] = send_message(smn, PPSMC_MSG_GetSmuVersion, 0)
        if not receipt['version_probe']['ok']:
            receipt['error'] = 'GetSmuVersion did not return OK; mailbox not trusted'
            return receipt
        receipt['smu_version'] = receipt['version_probe']['out_argument']
        if not args.execute:
            return receipt
        config_before = cfg.read(0, 256)
        receipt['pci_config_before_sha256'] = hashlib.sha256(config_before).hexdigest()
        receipt['pci_command_master_cleared'] = cfg.set_command(
            receipt['pci_command_before'] & ~PCI_COMMAND_MASTER)
        receipt['reset'] = send_message(smn, PPSMC_MSG_GfxDeviceDriverReset,
                                        SMU_RESET_MODE_2, timeout_s=5.0)
        deadline = time.monotonic() + 2.0
        memsize = mmio.read32(R.NBIO_CONFIG_MEMSIZE_OFFSET)
        while memsize == 0xffffffff and time.monotonic() < deadline:
            time.sleep(0.001)
            memsize = mmio.read32(R.NBIO_CONFIG_MEMSIZE_OFFSET)
        receipt['memsize_after'] = memsize
        config_after = cfg.read(0, 256)
        changed = [i * 4 for i in range(64)
                   if config_before[i*4:i*4+4] != config_after[i*4:i*4+4]]
        receipt['pci_config_changed_dwords'] = changed
        # Restore only what the reset disturbed, then the original command word.
        for offset in changed:
            if offset == 4:
                continue
            cfg.write(offset, config_before[offset:offset+4])
        receipt['pci_command_after'] = cfg.set_command(receipt['pci_command_before'])
        receipt['gc_after'] = gc_snapshot(mmio)
        receipt['mp1_firmware_flags_after'] = smn.rreg(SMN_MP1_FIRMWARE_FLAGS)
    receipt['finished'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--probe', action='store_true',
                       help='read state and send GetSmuVersion only')
    group.add_argument('--execute', action='store_true', help='send the MODE2 reset')
    parser.add_argument('--output', type=Path, required=True,
                        help='JSON receipt path (must not exist)')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f'output already exists: {args.output}')
    receipt = run(args)
    args.output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))
    return 0 if 'error' not in receipt else 1


if __name__ == '__main__':
    raise SystemExit(main())
