#!/usr/bin/env python3
"""OFFLINE ONLY: emit a fail-before-VFIO-open configuration; never run VBoxManage."""
import json
import os
import stat
from pathlib import Path

ADDRESS = 'ffff:ff:1f.7'
PIN = '14841851fa211c7faf615978ba385d59947236c6'

def plan():
    # Existing non-directory ancestor makes both access methods fail ENOTDIR,
    # even if a nonexistent PCI address alone would not prevent /dev/vfio opens.
    null = Path('/dev/null')
    st = null.lstat()
    if not stat.S_ISCHR(st.st_mode) or st.st_uid != 0 or st.st_rdev != os.makedev(1, 3):
        raise RuntimeError('Unexpected /dev/null identity; refuse plan')
    pci = Path('/sys/bus/pci/devices') / ADDRESS
    if os.path.lexists(pci):
        raise RuntimeError('Reserved impossible-device probe address exists; refuse')
    node = 'VBoxInternal/Devices/pci-vfio/0/'
    values = {
        node+'Trusted': 'integer:1',
        node+'PCIBusNo': 'integer:0',
        node+'PCIDeviceNo': 'integer:6',
        node+'PCIFunctionNo': 'integer:0',
        node+'Config/IommuPath': 'string:/dev/null/raphael-discriminator-iommu',
        node+'Config/VfioPath': 'string:/dev/null/raphael-discriminator-vfio',
        node+'Config/Fun0/HostAddress': 'string:'+ADDRESS,
    }
    return dict(schema=1, scope='offline proposed CFGM overlay; no VM registered or started',
        source_commit=PIN, source_tag='v7.2.18', host_address_observed_absent=ADDRESS,
        values=values,
        expected_failure='Opening VFIO container path "/dev/null/raphael-discriminator-vfio" failed',
        errno_expected=20,
        acceptance='Root-owned throwaway diskless VM reaches this exact backend error; independently trace open attempts and no actual /dev/vfio or /dev/iommu opens. Recheck guards immediately before eventual execution.',
        limits='Only backend/configuration dispatch. No PCI enumeration, DMA, IRQ, reset, ROM, macOS boot or acceleration qualification.')

if __name__ == '__main__':
    print(json.dumps(plan(), indent=2))
