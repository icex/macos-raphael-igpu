#!/usr/bin/env python3
"""Persistent console UI scale; changes take effect at the next owned restart.

Concurrent valid setters use atomic last-writer-wins publication.
"""
import argparse
import json
import os
from pathlib import Path
import stat
import tempfile

NAME = 'console-preferences.json'

def directory(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise ValueError('absolute support directory without symlinks required')
    row = path.lstat()
    if not stat.S_ISDIR(row.st_mode) or row.st_uid != os.geteuid() or row.st_mode & 0o022:
        raise ValueError('support directory ownership or permissions refused')
    return path

def read(path):
    path = directory(path) / NAME
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return dict(schema=1, guest_scale=2, source='legacy-default')
    try:
        row = os.fstat(fd)
        if (not stat.S_ISREG(row.st_mode) or row.st_uid != os.geteuid() or
                stat.S_IMODE(row.st_mode) != 0o600 or row.st_nlink != 1 or row.st_size > 4096):
            raise ValueError('preference file ownership/type/size/permissions refused')
        data = os.read(fd, 4097)
        after = os.fstat(fd)
        current = path.lstat()
        if (len(data) != row.st_size or
                (after.st_size, after.st_mtime_ns, after.st_ctime_ns) !=
                (row.st_size, row.st_mtime_ns, row.st_ctime_ns) or
                (current.st_dev, current.st_ino) != (row.st_dev, row.st_ino)):
            raise ValueError('preferences changed during read')
    finally:
        os.close(fd)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate preference key')
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=unique)
    if (type(value) is not dict or set(value) != {'schema', 'guest_scale'} or
            type(value['schema']) is not int or value['schema'] != 1 or
            type(value['guest_scale']) is not int or value['guest_scale'] not in (1, 2)):
        raise ValueError('unsupported console preferences')
    return dict(value, source='user-preference')

def write(path, scale):
    if type(scale) is not int or scale not in (1, 2):
        raise ValueError('guest scale must be 1 or 2')
    path = directory(path)
    read(path)  # Refuse replacing a foreign, malformed or aliased preference.
    value = dict(schema=1, guest_scale=scale)
    fd, temporary = tempfile.mkstemp(prefix='.console-preferences-', dir=path)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path / NAME)
        parent = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return read(path)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--support-dir', type=Path, required=True)
    parser.add_argument('--set-scale', type=int, choices=(1, 2))
    parser.add_argument('--read-scale', action='store_true')
    args = parser.parse_args()
    if args.read_scale and args.set_scale is not None:
        parser.error('read and write are separate operations')
    value = read(args.support_dir) if args.set_scale is None else write(args.support_dir, args.set_scale)
    print(value['guest_scale'] if args.read_scale else json.dumps(value))

if __name__ == '__main__':
    main()
