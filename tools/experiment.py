#!/usr/bin/env python3
"""Identity and admission primitives for one bounded GPU experiment. No device resets."""
import json
import os
from pathlib import Path
import re
import hashlib
import shutil
import subprocess
import tempfile
import uuid


def sha(data):
    return hashlib.sha256(data).hexdigest()


def image_files(image, offset=1048576):
    address = str(image) + (f'@@{offset}' if offset else '')
    def read(name):
        return subprocess.check_output(['mtype', '-i', address, '::/EFI/OC/'+name],
                                       env=dict(os.environ, MTOOLS_SKIP_CHECK='1'), timeout=15)
    return {'binary_sha256': sha(read('Kexts/RaphaelGPU.kext/Contents/MacOS/RaphaelGPU')),
            'info_sha256': sha(read('Kexts/RaphaelGPU.kext/Contents/Info.plist')),
            'config_sha256': sha(read('config.plist'))}


def stage_image(image, bundle, config, offset=1048576):
    """Caller must hold VM lock and establish no active VM. Never edit in place."""
    binary = (bundle / 'Contents/MacOS/RaphaelGPU').read_bytes()
    info = (bundle / 'Contents/Info.plist').read_bytes()
    if not binary or not info or not config: raise ValueError('incomplete staging input')
    expected = dict(binary_sha256=sha(binary), info_sha256=sha(info), config_sha256=sha(config))
    with tempfile.TemporaryDirectory(prefix='rgpu-stage-', dir=image.parent) as temp:
        stage = Path(temp) / image.name
        shutil.copyfile(image, stage)
        configuration = Path(temp) / 'config.plist'
        configuration.write_bytes(config)
        address = str(stage) + (f'@@{offset}' if offset else '')
        env = dict(os.environ, MTOOLS_SKIP_CHECK='1')
        subprocess.run(['mdeltree', '-i', address, '::/EFI/OC/Kexts/RaphaelGPU.kext'],
                       env=env, capture_output=True, timeout=15)
        subprocess.run(['mcopy', '-s', '-o', '-i', address, str(bundle), '::/EFI/OC/Kexts/'],
                       env=env, check=True, capture_output=True, timeout=30)
        subprocess.run(['mcopy', '-o', '-i', address, str(configuration), '::/EFI/OC/config.plist'],
                       env=env, check=True, capture_output=True, timeout=15)
        errors = validate_identity(expected, image_files(stage, offset))
        if errors: raise ValueError('ESP readback mismatch: '+','.join(errors))
        backup = image.with_name(image.name+'.backup-'+uuid.uuid4().hex)
        # Hard link retains the old inode; replace publishes the verified new one.
        os.link(image, backup)
        with stage.open('rb') as stream: os.fsync(stream.fileno())
        stage.replace(image)
        directory = os.open(image.parent, os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    return dict(expected, backup=str(backup))


def validate_identity(expected, observed):
    return [key for key, value in expected.items()
            if value is None or observed.get(key) != value]


def admit(manifest, host, used_boots):
    errors = []
    for key in ('amdgpu_initialized', 'capture_ready', 'watchdogs_verified',
                'device_pinned_awake', 'device_accessible'):
        if host.get(key) is not True:
            errors.append(key)
    if host.get('active_vm') is not False: errors.append('active_vm')
    if not host.get('boot_id') or host['boot_id'] != manifest.get('boot_id'):
        errors.append('boot_id')
    if host.get('boot_id') in used_boots: errors.append('boot_already_used')
    if host.get('driver') != 'vfio-pci': errors.append('driver')
    if host.get('device') != '1002:13c0': errors.append('device')
    if host.get('iommu_group') != '31': errors.append('iommu_group')
    if manifest.get('source_clean') is not True: errors.append('source_clean')
    if manifest.get('vfio_device') != '0000:7b:00.0': errors.append('vfio_device')
    if type(manifest.get('max_seconds')) is not int or manifest['max_seconds'] != 180:
        errors.append('max_seconds')
    return errors


def write_once(path, value):
    """O_EXCL is the reservation. A crash leaves a consumed path, never a retry."""
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    fd = os.open(Path(path).parent, os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def reserve_boot(directory, boot_id, experiment):
    if not re.fullmatch(r'[A-Za-z0-9-]+', boot_id):
        raise ValueError('invalid host boot ID')
    directory.mkdir(parents=True, exist_ok=True)
    write_once(directory / (boot_id+'.json'), {'boot_id': boot_id, 'experiment': experiment})


def probe_fits(now, launch_deadline, container_deadline, probe_seconds=45, cleanup_seconds=25):
    if launch_deadline is None or container_deadline is None: return False
    return now + probe_seconds + cleanup_seconds < min(launch_deadline, container_deadline)
