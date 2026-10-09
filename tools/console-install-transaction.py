#!/usr/bin/env python3
"""Stage guest console helpers before publication; recover interrupted replacements.

One per-user advisory lock serializes this installer. Other processes do not honor
that lock: refuse loaded/running helpers and recheck before publishing. Multiple
filesystem paths are rollback-capable, not globally atomic.
"""
import argparse
import ctypes
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import stat
import subprocess
import tempfile


def digest(path):
    """Reject links/special files and include modes and names in tree identity."""
    path = Path(path)
    if not path.exists() and not path.is_symlink():
        return None
    result = hashlib.sha256()
    for item in [path] + (sorted(path.rglob('*')) if path.is_dir() and not path.is_symlink() else []):
        info = item.lstat()
        if info.st_uid != os.getuid() or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise RuntimeError('Unowned or unsupported installation entry: ' + str(item))
        result.update(json.dumps([str(item.relative_to(path)), stat.S_IMODE(info.st_mode),
                                  'dir' if item.is_dir() else 'file']).encode() + b'\0')
        if item.is_file():
            with item.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    result.update(block)
    return result.hexdigest()


def owned_directory(path):
    path = Path(path)
    # Check before mkdir so intermediate links cannot redirect a write.
    for parent in reversed([path] + list(path.parents)):
        if parent.exists() or parent.is_symlink():
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode):
                raise RuntimeError('Not a real directory: ' + str(parent))
            if info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
                raise RuntimeError('Unsafe installation ancestor: ' + str(parent))
        else:
            parent.mkdir(mode=0o700)
    if path.stat().st_uid != os.getuid():
        raise RuntimeError('Destination directory is not owned by current user: ' + str(path))


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_tree(path):
    path = Path(path)
    for item in ([path] + list(path.rglob('*'))) if path.is_dir() else [path]:
        fd = os.open(item, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def rename(source, target):
    # Apple XNU bsd/sys/stdio.h: RENAME_EXCL=0x4. Linux analogue is
    # renameat2(RENAME_NOREPLACE=1), used by host tests. No overwrite fallback.
    libc = ctypes.CDLL(None, use_errno=True)
    if platform.system() == 'Darwin':
        function = libc.renamex_np
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        arguments = (os.fsencode(source), os.fsencode(target), 0x4)
    else:
        function = libc.renameat2
        function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        arguments = (-100, os.fsencode(source), -100, os.fsencode(target), 1)
    function.restype = ctypes.c_int
    if function(*arguments) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))
    sync_directory(Path(source).parent)
    if Path(source).parent != Path(target).parent:
        sync_directory(Path(target).parent)


def move_verified(source, target, expected):
    if digest(source) != expected:
        raise RuntimeError('Concurrent source change before rename: ' + str(source))
    rename(source, target)
    if digest(target) != expected:
        # Keep foreign data intact. Restore its name only if no one occupied it.
        try:
            rename(target, source)
        except OSError:
            pass
        raise RuntimeError('Concurrent source change during rename; retain evidence: ' + str(target))


def write_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


def refuse_active(app):
    result = subprocess.run(['/bin/launchctl', 'print', 'gui/%d/org.raphaelgpu.console' % os.getuid()],
                            capture_output=True, text=True)
    if result.returncode == 0:
        raise RuntimeError('Console LaunchAgent is loaded; boot it out before installing')
    if (result.returncode != 113 or 'Could not find service "org.raphaelgpu.console"' not in result.stderr):
        raise RuntimeError('Cannot establish unloaded console LaunchAgent: ' + result.stderr.strip())
    # Inspect the entire process list successfully; an unavailable observer is not inactivity.
    processes = subprocess.check_output(['/bin/ps', '-axo', 'command='], text=True)
    for name in ('console-presenter', 'virtual-display-server', 'console-display-layout'):
        if any(name in line for line in processes.splitlines()):
            raise RuntimeError('Installed console helper is running: ' + name)


class Transaction:
    def __init__(self, home, active=refuse_active):
        self.home = Path(home)
        self.app = self.home / 'Applications/Raphael Console.app'
        self.support = self.home / 'Library/Application Support/RaphaelGPU/console'
        self.agent = self.home / 'Library/LaunchAgents/org.raphaelgpu.console.plist'
        self.control = self.support.parent
        self.journal = self.control / 'console-install-transaction.json'
        self.active = active
        self.targets = [self.app, self.support / 'start-console.sh',
                        self.support / 'build-provenance.json', self.agent]

    def lock(self):
        for path in (self.app.parent, self.support, self.agent.parent):
            owned_directory(path)
        fd = os.open(self.control / 'console-install.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            os.close(fd)
            raise RuntimeError('Invalid installer lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def read_journal(self):
        info = self.journal.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_nlink != 1 or info.st_mode & 0o077 or info.st_size > 65536):
            raise RuntimeError('Invalid transaction journal file')
        value = json.loads(self.journal.read_text())
        stage = Path(value['stage'])
        if (value.get('schema') != 1 or stage.parent != self.app.parent or
                not stage.name.startswith('.raphael-install-') or stage.is_symlink() or not stage.is_dir()):
            raise RuntimeError('Invalid transaction staging directory')
        if stage.stat().st_uid != os.getuid() or stage.stat().st_mode & 0o077:
            raise RuntimeError('Unowned or exposed transaction staging directory')
        entries = value['entries']
        if len(entries) != len(self.targets):
            raise RuntimeError('Invalid transaction targets')
        for index, (entry, target) in enumerate(zip(entries, self.targets)):
            for field in ('before', 'after'):
                digest_value = entry[field]
                if (digest_value is None and field == 'before'):
                    continue
                if not isinstance(digest_value, str) or len(digest_value) != 64 or any(c not in '0123456789abcdef' for c in digest_value):
                    raise RuntimeError('Invalid journal identity')
            if entry['target'] != str(target) or entry['backup'] != str(stage / ('old-%d' % index)) or entry['new'] != str(stage / ('new-%d' % index)):
                raise RuntimeError('Invalid journal path')
        return value

    def recover(self):
        self.active(self.app)
        value = self.read_journal()
        # Refuse all observed foreign edits BEFORE changing any other target.
        for entry in value['entries']:
            current, backup = digest(entry['target']), digest(entry['backup'])
            if current not in (None, entry['before'], entry['after']) or backup not in (None, entry['before']):
                raise RuntimeError('Concurrent change; retain journal for manual recovery: ' + entry['target'])
            if entry['before'] is not None and current != entry['before'] and backup != entry['before']:
                raise RuntimeError('Original missing; retain journal: ' + entry['target'])
        for index, entry in reversed(list(enumerate(value['entries']))):
            target, backup = Path(entry['target']), Path(entry['backup'])
            current = digest(target)
            if current not in (None, entry['before'], entry['after']) or digest(backup) not in (None, entry['before']):
                raise RuntimeError('Concurrent change during recovery; retain journal: ' + str(target))
            if current == entry['before']:
                continue
            if current is not None:
                discard = Path(value['stage']) / ('discard-%d' % index)
                if discard.exists():
                    raise RuntimeError('Recovery discard already exists')
                move_verified(target, discard, current)
            if entry['before'] is not None:
                move_verified(backup, target, entry['before'])
        self.finish(value, 'rolled-back')

    def finish(self, value, outcome):
        value['outcome'] = outcome
        write_json(Path(value['stage']) / 'result.json', value)
        self.journal.unlink()
        sync_directory(self.journal.parent)

    def install(self, build):
        if self.journal.exists() or self.journal.is_symlink():
            raise RuntimeError('Pending transaction: run installer --recover first')
        self.active(self.app)
        before = [digest(path) for path in self.targets]
        stage = Path(tempfile.mkdtemp(prefix='.raphael-install-', dir=self.app.parent))
        build(stage)
        sources = [stage / 'Raphael Console.app', stage / 'support/start-console.sh',
                   stage / 'support/build-provenance.json', stage / 'agent.plist']
        entries = []
        for index, (source, target, old) in enumerate(zip(sources, self.targets, before)):
            fresh = stage / ('new-%d' % index)
            rename(source, fresh)
            after = digest(fresh)
            if after is None:
                raise RuntimeError('Build output missing: ' + str(source))
            sync_tree(fresh)
            entries.append(dict(target=str(target), backup=str(stage / ('old-%d' % index)),
                                new=str(fresh), before=old, after=after))
        self.active(self.app)
        if [digest(path) for path in self.targets] != before:
            raise RuntimeError('Installation changed during compilation; refusing publication')
        value = dict(schema=1, stage=str(stage), entries=entries)
        write_json(self.journal, value)
        try:
            for entry in entries:
                if digest(entry['target']) != entry['before']:
                    raise RuntimeError('Installation changed during publication')
                if entry['before'] is not None:
                    move_verified(entry['target'], entry['backup'], entry['before'])
                move_verified(entry['new'], entry['target'], entry['after'])
            self.finish(value, 'installed')
        except Exception:
            self.recover()
            raise
        return stage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recover', action='store_true')
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'x86_64' or os.geteuid() == 0:
        raise SystemExit('Run as logged-in non-root x86_64 macOS user')
    transaction = Transaction(Path.home())
    lock = transaction.lock()
    try:
        if args.recover:
            transaction.recover()
            print('Previous installation restored; no agent started.')
        else:
            script = Path(__file__).with_name('install-console-desktop.sh')
            stage = transaction.install(lambda stage: subprocess.run(
                ['/bin/bash', str(script), '--build-stage', str(stage)], check=True))
            print('Installed %s\nTransaction retained: %s' % (transaction.app, stage))
            print('Start: launchctl bootstrap gui/%d "%s"' % (os.getuid(), transaction.agent))
            print('Enable Raphael Console in Screen & System Audio Recording if prompted.')
    finally:
        os.close(lock)


if __name__ == '__main__':
    main()
