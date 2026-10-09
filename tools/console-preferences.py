#!/usr/bin/env python3
"""Persistent console UI scale and opt-in text clipboard.

Both settings take effect at the next owned restart.

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
    if type(value) is not dict or type(value.get('schema')) is not int:
        raise ValueError('unsupported console preferences')
    keys={'schema','guest_scale'} if value['schema']==1 else {'schema','guest_scale','clipboard_text'}
    if (value['schema'] not in (1,2) or set(value)!=keys or
            type(value['guest_scale']) is not int or value['guest_scale'] not in (1,2) or
            (value['schema']==2 and type(value['clipboard_text']) is not bool)):
        raise ValueError('unsupported console preferences')
    return dict(value, source='user-preference')

def write(path, scale=None, *, clipboard_text=None):
    if scale is not None and (type(scale) is not int or scale not in (1, 2)):
        raise ValueError('guest scale must be 1 or 2')
    path = directory(path)
    old=read(path)  # Refuse replacing a foreign, malformed or aliased preference.
    if clipboard_text is not None and type(clipboard_text) is not bool:
        raise ValueError('clipboard preference must be boolean')
    value = dict(schema=old['schema'], guest_scale=old['guest_scale'] if scale is None else scale)
    if old['schema']==2 or clipboard_text is not None:
        value.update(schema=2,clipboard_text=old.get('clipboard_text',False) if clipboard_text is None else clipboard_text)
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
    parser.add_argument('--set-clipboard',choices=('on','off'))
    parser.add_argument('--read-clipboard',action='store_true')
    args = parser.parse_args()
    if (args.read_scale or args.read_clipboard) and (args.set_scale is not None or args.set_clipboard is not None) or args.read_scale and args.read_clipboard:
        parser.error('read and write are separate operations')
    value = read(args.support_dir) if args.set_scale is None and args.set_clipboard is None else write(args.support_dir, args.set_scale, clipboard_text=None if args.set_clipboard is None else args.set_clipboard=='on')
    print(value['guest_scale'] if args.read_scale else ('on' if value.get('clipboard_text',False) else 'off') if args.read_clipboard else json.dumps(value))

if __name__ == '__main__':
    main()
