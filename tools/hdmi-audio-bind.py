#!/usr/bin/env python3
"""One-way, audio-only host handoff; no resets and no application termination.

Run through the announced privileged container with host /sys, /dev and /proc.
Only control handles may be open: ALSA disconnect replaces their operations and
notifies pollers before freeing the device. Any PCM handle or non-closed PCM
status refuses handoff. Never binds the audio function back to its host driver.
"""
import argparse
import json
import os
from pathlib import Path
import time

BDF = '0000:7b:00.1'

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    sys = Path('/sys'); dev = sys/'bus/pci/devices'/BDF
    gpu = sys/'bus/pci/devices/0000:7b:00.0'
    require((dev/'vendor').read_text().strip() == '0x1002' and
            (dev/'device').read_text().strip() == '0x1640', 'wrong audio PCI identity')
    require((dev/'iommu_group').resolve().name == '32' and
            sorted(p.name for p in (dev/'iommu_group/devices').iterdir()) == [BDF],
            'unexpected audio IOMMU group')
    require((gpu/'driver').resolve().name == 'vfio-pci' and
            (gpu/'power/control').read_text().strip() == 'on' and
            (gpu/'power/runtime_status').read_text().strip() == 'active',
            'GPU must remain awake on VFIO')
    require(not (gpu/'reset_method').read_text().strip(), 'GPU reset method enabled')
    driver = (dev/'driver').resolve().name
    require(driver in ('snd_hda_intel', 'vfio-pci'), 'unexpected audio driver')
    cards = [p.name for p in (dev/'sound').glob('card*')]
    if driver == 'snd_hda_intel':
        require(len(cards) == 1, 'audio card identity missing')
    statuses = {}
    for card in cards:
        for status in Path('/proc/asound', card).glob('pcm*/sub*/status'):
            statuses[str(status)] = status.read_text().strip()
    if driver == 'snd_hda_intel':
        require(bool(statuses) and all(v == 'closed' for v in statuses.values()),
                'audio PCM is active or status is missing')
    controls = []
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            name = (process/'comm').read_text().strip()
            require(not name.startswith('qemu-system'), 'QEMU is still running')
            for fd in (process/'fd').iterdir():
                try:
                    target = os.readlink(fd)
                except FileNotFoundError:
                    continue
                require(target not in ('/dev/vfio/31', '/dev/vfio/32'), 'VFIO group still open')
                for card in cards:
                    number = card.removeprefix('card')
                    require(not target.startswith('/dev/snd/pcmC'+number+'D'),
                            'audio PCM descriptor is open')
                    if target == '/dev/snd/controlC'+number:
                        controls.append(dict(pid=int(process.name), name=name, target=target))
        except (FileNotFoundError, ProcessLookupError):
            continue
    before = dict(boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                  device=BDF, driver=driver, pcm_status=statuses, control_clients=controls)
    print(json.dumps(dict(phase='inspection', **before)), flush=True)
    if not args.execute:
        return
    require(os.geteuid() == 0, 'root required for this one-time handoff')
    (dev/'power/control').write_text('on\n')
    until = time.monotonic()+5
    while (dev/'power/runtime_status').read_text().strip() != 'active':
        require(time.monotonic() < until, 'audio runtime wake failed')
        time.sleep(.05)
    # Disable all PCI reset methods before VFIO can open this function.
    (dev/'reset_method').write_text('\n')
    require(not (dev/'reset_method').read_text().strip(), 'audio reset disable failed')
    if driver == 'snd_hda_intel':
        (dev/'driver_override').write_text('vfio-pci\n')
        (dev/'driver/unbind').write_text(BDF+'\n')
        (sys/'bus/pci/drivers_probe').write_text(BDF+'\n')
    require((dev/'driver').resolve().name == 'vfio-pci', 'audio VFIO bind failed')
    (dev/'power/control').write_text('on\n')
    (dev/'reset_method').write_text('\n')
    require((dev/'power/runtime_status').read_text().strip() == 'active' and
            not (dev/'reset_method').read_text().strip(), 'post-bind power/reset mismatch')
    os.chown('/dev/vfio/32', 1000, 1000)
    os.chmod('/dev/vfio/32', 0o660)
    with (dev/'config').open('rb') as stream:
        config = stream.read(8)
    command = int.from_bytes(config[4:6], 'little')
    require(len(config) == 8 and command != 0xffff and command & 4 == 0,
            'audio DMA remains enabled after host driver removal')
    print(json.dumps(dict(phase='bound', device=BDF, driver='vfio-pci',
                          pci_command=command, power='on', reset_methods=[])), flush=True)

if __name__ == '__main__':
    main()
