#!/usr/bin/env python3
"""Check tracked publication content without printing sensitive values."""
import ipaddress
import plistlib
from pathlib import Path
import re
import subprocess
import sys

GENERIC_USERS = {'user', 'arch', 'runner', 'name', 'Shared', 'guest', 'build', 'example'}
HOME = re.compile(rb'/(?:home|Users)/([A-Za-z0-9_.-]+)')
KEY = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----')
IP = re.compile(rb'(?<![\d.])(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\d.])')
MAC = re.compile(rb'(?<![\da-f])(?:[\da-f]{2}:){5}[\da-f]{2}(?![\da-f])', re.I)


def inspect_content(path, data):
    issues = set()
    if KEY.search(data):
        issues.add('private-key header')
    if any(m.decode() not in GENERIC_USERS for m in HOME.findall(data)):
        issues.add('personal home path')
    for raw in IP.findall(data):
        try:
            ip = ipaddress.ip_address(raw.decode())
        except ValueError:
            continue
        # Conventional user-network/Docker examples are not host identifiers.
        if not any(ip in ipaddress.ip_network(n) for n in
                   ('10.0.2.0/24', '172.17.0.0/16', '172.18.0.0/16')):
            issues.add('local network address')
    for raw in MAC.findall(data):
        value = raw.decode().lower()
        if (value not in ('00:00:00:00:00:00', 'ff:ff:ff:ff:ff:ff') and
                not value.startswith(('52:54:', '02:00:00:')) and
                not int(value[:2], 16) & 1):
            issues.add('device MAC address')
    if path.endswith('.plist') and b'<plist' in data:
        start, end = data.find(b'<plist'), data.rfind(b'</plist>')
        try:
            value = plistlib.loads(data[start:end+8])
        except Exception:
            return issues | {'unreadable property list'}
        def walk(v):
            if isinstance(v, dict):
                for key, item in v.items():
                    if key in ('SystemSerialNumber', 'SystemUUID', 'MLB', 'ROM') and item:
                        text = item.hex() if isinstance(item, bytes) else str(item)
                        if text.strip('0-') and not text.startswith('REDACTED'):
                            issues.add('populated OpenCore identity')
                    walk(item)
            elif isinstance(v, list):
                for item in v:
                    walk(item)
        walk(value)
    return issues


def main():
    root = Path(__file__).resolve().parents[1]
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    failed = False
    for name in filter(None, names):
        path = root/name
        if not path.is_file() or path.is_symlink():
            continue
        issues = inspect_content(name, path.read_bytes())
        if issues:
            failed = True
            print(name + ': ' + ', '.join(sorted(issues)))
    if not failed:
        print('Tracked publication content passed privacy checks.')
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
