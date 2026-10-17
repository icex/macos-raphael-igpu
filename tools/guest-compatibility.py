#!/usr/bin/env python3
"""Validate a GPU-less guest's compatibility proof before any GPU launch.

A saved OS label is insufficient. The proof binds the guest's observed collections
and userspace text, the production discovery contracts, and the stopped system
disk's identity. Any subsequent disk write requires a new GPU-less inspection.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def disk_identity(path):
    stat = Path(path).stat()
    return dict(device=stat.st_dev, inode=stat.st_ino, size=stat.st_size,
                mtime_ns=stat.st_mtime_ns, ctime_ns=stat.st_ctime_ns)


def validate(vm, guest, require_sealed=True):
    proof = guest.get('compatibility')
    if not isinstance(proof, dict) or proof.get('policy') != 'dynamic-sites-v1':
        raise ValueError('fresh GPU-less compatibility proof required; saved guest build is insufficient')
    build = guest.get('guest_build', '')
    version = proof.get('guest_version', '')
    if not ((version.startswith('15.') and re.fullmatch(r'24[A-Z][0-9]+[a-z]?', build)) or
            (version.startswith('26.') and re.fullmatch(r'25[A-Z][0-9]+[a-z]?', build))):
        raise ValueError('guest version/build is outside macOS 15/26 compatibility policy')
    if require_sealed and proof.get('sealed') is not True:
        raise ValueError('GPU-less observation has not been sealed after guest shutdown')
    if require_sealed and proof.get('plain_shutdown', {}).get('exit_code') != 0:
        raise ValueError('successful native plain-guest shutdown proof missing')
    if require_sealed and proof.get('disk_identity') != disk_identity(vm/'mac_hdd_ng.img'):
        raise ValueError('system disk changed after GPU-less compatibility inspection')
    if require_sealed:
        shutdown = proof.get('plain_shutdown', {})
        expected_ack = proof.get('observation_nonce', '')+' '+guest.get('guest_boot_uuid', '')
        if shutdown.get('method') != 'native-request' or shutdown.get('acknowledgement') != expected_ack:
            raise ValueError('native shutdown acknowledgement identity differs')
    if not re.fullmatch(r'[0-9a-f]{32}', proof.get('observation_nonce', '')):
        raise ValueError('missing guest compatibility observation identity')
    catalog = ROOT/'findings/research/update-portability-20261013/kernel-sites.json'
    userspace = ROOT/'findings/research/update-portability-20261013/userspace-sites.json'
    if proof.get('kernel_catalog_sha256') != sha(catalog) or proof.get('userspace_catalog_sha256') != sha(userspace):
        raise ValueError('compatibility contracts changed after inspection')
    spec = importlib.util.spec_from_file_location('kernel_sites', ROOT/'tools/kernel-sites.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    system = proof.get('system_collection', {})
    boot = proof.get('boot_collection', {})
    for artifact in (system, boot):
        path = Path(artifact.get('path', ''))
        if not path.is_file() or sha(path) != artifact.get('sha256'):
            raise ValueError('guest kernel collection identity changed')
    report = module.verify_collection(system['path'])
    if not report['supported']:
        raise ValueError('guest kernel collection has unsupported or ambiguous driver sites')
    images = proof.get('userspace_images')
    if not isinstance(images, dict) or set(images) != {'AMDRadeonX6000MTLDriver', 'AMDRadeonVADriver2'}:
        raise ValueError('missing active userspace driver images')
    with tempfile.TemporaryDirectory(prefix='rgpu-user-compat-') as directory:
        binary = Path(directory)/'discovery'
        subprocess.run(['c++','-std=c++14','-O2','-I',str(ROOT/'src'),
                        str(ROOT/'tests/userspace_site_locator.cpp'),'-o',str(binary)],check=True)
        for image in images.values():
            path = Path(image.get('path',''))
            if not path.is_file() or sha(path) != image.get('sha256'):
                raise ValueError('userspace image identity changed after inspection')
            subprocess.run([str(binary),str(path)],check=True)
    return {'policy': proof['policy'], 'guest_build': build,
            'kernel_catalog_sha256': proof['kernel_catalog_sha256'],
            'userspace_catalog_sha256': proof['userspace_catalog_sha256'],
            'observation_nonce': proof['observation_nonce'],
            'kernel_sites': report['sites']}
