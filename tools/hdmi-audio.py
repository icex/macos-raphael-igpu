#!/usr/bin/env python3
"""Read-only, exact Raphael HDMI audio VFIO admission and teardown checks."""
import json
import os
from pathlib import Path

BDF = '0000:7b:00.1'

def snapshot(sysfs=Path('/sys'), dev=Path('/dev')):
    device = sysfs / 'bus/pci/devices' / BDF
    def read(name):
        try:
            return (device / name).read_text().strip()
        except OSError:
            return None
    try:
        with (device / 'config').open('rb') as stream:
            config = stream.read(8)
        command = int.from_bytes(config[4:6], 'little') if len(config) == 8 else None
    except OSError:
        command = None
    try:
        members = sorted(p.name for p in (device / 'iommu_group/devices').iterdir())
    except OSError:
        members = None
    reset = read('reset_method')
    return dict(bdf=BDF, vendor=read('vendor'), device=read('device'),
                driver=(device/'driver').resolve().name,
                group=(device/'iommu_group').resolve().name, members=members,
                power=read('power/control'), runtime=read('power/runtime_status'),
                reset_methods=None if reset is None else reset.split(),
                accessible=os.access(dev/'vfio/32', os.R_OK | os.W_OK),
                pci_command=command)


def errors(state):
    expected = dict(bdf=BDF, vendor='0x1002', device='0x1640',
                    driver='vfio-pci', group='32', members=[BDF], power='on',
                    runtime='active', reset_methods=[], accessible=True)
    result = ['hdmi_audio_'+key for key, value in expected.items()
              if state.get(key) != value]
    command = state.get('pci_command')
    if type(command) is not int or command == 0xffff or command & 4:
        result.append('hdmi_audio_bus_master')
    return result

if __name__ == '__main__':
    state = snapshot()
    failures = errors(state)
    print(json.dumps(dict(state=state, errors=failures)))
    raise SystemExit(bool(failures))
