#!/usr/bin/env python3
"""Bind a hardened VBox process to its owned VM log; no executable-proof claim on EACCES."""
import errno
import os
from pathlib import Path
import re
import stat


def process_identity(home, name, ident, proc_root=Path('/proc'),
                     binary_root=Path('/usr/lib/virtualbox'), binary_uid=0):
    log = home / 'vms' / name / 'Logs' / 'VBox.log'
    ls = log.lstat()
    if not stat.S_ISREG(ls.st_mode) or ls.st_uid != os.getuid():
        raise ValueError('unowned VM log')
    fd = os.open(log, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        opened = os.fstat(stream.fileno())
        if ((opened.st_dev, opened.st_ino) != (ls.st_dev, ls.st_ino) or
                not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.getuid()):
            raise ValueError('VM log changed before open')
        header = stream.read(65536)
    pids = re.findall(rb'^\d\d:\d\d:\d\d\.\d+ Process ID: ([1-9][0-9]*)\r?$', header, re.M)
    if len(pids) != 1:
        raise ValueError('ambiguous VM log PID')
    pid = int(pids[0]); proc = proc_root / str(pid)
    if proc.stat().st_uid != os.getuid():
        raise ValueError('foreign process owner')
    status = proc.joinpath('status').read_text()
    uids = re.findall(r'^Uid:\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$', status, re.M)
    if len(uids) != 1 or any(int(v) != os.getuid() for v in uids[0]):
        raise ValueError('process credentials differ')
    before = proc.joinpath('stat').read_text()
    fields = before.rsplit(')', 1)[1].split()
    if fields[0] in ('Z', 'X') or not fields[19].isdigit():
        raise ValueError('process not live')
    start = fields[19]
    argv_bytes = proc.joinpath('cmdline').read_bytes()
    argv = argv_bytes.rstrip(b'\0').split(b'\0')
    if argv.count(b'--startvm') != 1 or argv[argv.index(b'--startvm') + 1] != ident.encode():
        raise ValueError('process VM identity differs')
    program = Path(os.fsdecode(argv[0]))
    if program.name not in ('VirtualBoxVM', 'VBoxHeadless') or program != binary_root / program.name:
        raise ValueError('unexpected process command path')
    bs = program.stat()
    if not stat.S_ISREG(bs.st_mode) or bs.st_uid != binary_uid or bs.st_mode & 0o022:
        raise ValueError('untrusted installed executable')
    evidence = 'kernel-executable-link'
    try:
        actual = Path(os.readlink(proc / 'exe'))
        if actual != program:
            raise ValueError('executable link differs')
    except PermissionError as exc:
        if exc.errno != errno.EACCES:
            raise
        # Hardened VBox sets non-dumpable. Require its owned log PID and all
        # session/process checks; do not pretend argv proves the executable.
        evidence = 'owned-session-log-and-process'
    after = proc.joinpath('stat').read_text().rsplit(')', 1)[1].split()
    if after[0] in ('Z', 'X') or after[19] != start or proc.joinpath('cmdline').read_bytes() != argv_bytes:
        raise ValueError('process changed during observation')
    return dict(pid=pid, starttime=start, log_device=ls.st_dev, log_inode=ls.st_ino,
                binary_device=bs.st_dev, binary_inode=bs.st_ino, evidence=evidence)
