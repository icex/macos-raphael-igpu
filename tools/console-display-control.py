#!/usr/bin/env python3
"""Request a bounded mode change from the existing per-user display holder."""
import ctypes
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import struct
import sys
import time

MAGIC=0x52475044
REQUEST=struct.Struct('<5I')
REPLY=struct.Struct('<10I')

def geometry(width,height):
    if type(width) is not int or type(height) is not int or not (640<=width<=3840 and 480<=height<=2160) or width%2 or height%2:
        raise ValueError('even physical dimensions within640..3840 by480..2160 required')

def peer_uid(connection):
    if sys.platform=='darwin':
        libc=ctypes.CDLL(None,use_errno=True)
        function=libc.getpeereid
        function.argtypes=[ctypes.c_int,ctypes.POINTER(ctypes.c_uint),ctypes.POINTER(ctypes.c_uint)]
        function.restype=ctypes.c_int
        uid=ctypes.c_uint();gid=ctypes.c_uint()
        if function(connection.fileno(),ctypes.byref(uid),ctypes.byref(gid)):
            error=ctypes.get_errno();raise OSError(error,os.strerror(error))
        return uid.value
    if sys.platform.startswith('linux'):
        return struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
    raise RuntimeError('peer identity unavailable on this platform')

def identity(path,kind,mode):
    row=path.lstat()
    if not kind(row.st_mode) or row.st_uid!=os.geteuid() or stat.S_IMODE(row.st_mode)!=mode:
        raise ValueError('control endpoint ownership/type/mode refused')
    return row.st_dev,row.st_ino,row.st_uid

def decode(data,sequence,width,height):
    if len(data)!=REPLY.size:raise ValueError('invalid control response length')
    magic,version,reply_sequence,status,display,pw,ph,lw,lh,flags=REPLY.unpack(data)
    if (magic,version,reply_sequence)!=(MAGIC,1,sequence) or status>5 or flags&~3:
        raise ValueError('invalid control response identity/status/flags')
    if status==0 and (display==0 or (pw,ph)!=(width,height) or not 0<lw<=pw or not 0<lh<=ph):
        raise ValueError('successful control response did not verify requested geometry')
    return dict(passed=status==0,status=status,sequence=sequence,display=display,
                pixel_width=pw,pixel_height=ph,width=lw,height=lh,
                changed=bool(flags&1),dynamic_mode_added=bool(flags&2))

def request(directory,width,height,timeout=2):
    geometry(width,height)
    if not 0<timeout<=5:raise ValueError('bounded control timeout required')
    directory=Path(directory)
    if not directory.is_absolute() or directory.resolve()!=directory:
        raise ValueError('absolute control directory without symlink aliases required')
    endpoint=directory/'control.sock'
    before_dir=identity(directory,stat.S_ISDIR,0o700)
    before_socket=identity(endpoint,stat.S_ISSOCK,0o600)
    sequence=secrets.randbelow(0xffffffff)+1
    deadline=time.monotonic()+timeout
    def remaining():
        result=deadline-time.monotonic()
        if result<=0:raise TimeoutError('display control deadline')
        return result
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
        connection.settimeout(remaining());connection.connect(str(endpoint))
        if peer_uid(connection)!=os.geteuid():raise ValueError('control peer UID mismatch')
        if identity(directory,stat.S_ISDIR,0o700)!=before_dir or identity(endpoint,stat.S_ISSOCK,0o600)!=before_socket:
            raise ValueError('control endpoint replaced during connect')
        connection.settimeout(remaining());connection.sendall(REQUEST.pack(MAGIC,1,sequence,width,height))
        data=bytearray()
        while len(data)<REPLY.size:
            connection.settimeout(remaining());part=connection.recv(REPLY.size-len(data))
            if not part:raise EOFError('truncated display control reply')
            data.extend(part)
        connection.settimeout(remaining())
        if connection.recv(1):raise ValueError('extra display control reply bytes')
    return decode(data,sequence,width,height)

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--control-dir',type=Path,required=True)
    parser.add_argument('width',type=int);parser.add_argument('height',type=int)
    args=parser.parse_args()
    result=request(args.control_dir,args.width,args.height)
    print(json.dumps(result));raise SystemExit(0 if result['passed'] else 1)
