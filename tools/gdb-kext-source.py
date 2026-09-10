#!/usr/bin/env python3
"""Generate a bounded GDB script for a source breakpoint in RaphaelGPU."""

import argparse
import struct
from pathlib import Path


MH_MAGIC_64 = 0xFEEDFACF
LC_UUID = 0x1B
MAX_HEADER = 65536
MAX_KMODS = 256
KMOD_NAME = 0x10
KMOD_ADDRESS = 0x9C


def kernel_relocation(runtime_text, link_text):
    if runtime_text < link_text:
        raise ValueError("runtime __TEXT precedes link __TEXT")
    return runtime_text - link_text


def macho_uuid(data):
    if len(data) < 32:
        raise ValueError("load commands exceed available header")
    magic, _, _, _, ncmds, sizeofcmds, _, _ = struct.unpack_from("<IiiIIIII", data)
    if magic != MH_MAGIC_64:
        raise ValueError("invalid Mach-O 64 magic")
    if sizeofcmds > MAX_HEADER - 32:
        raise ValueError("Mach-O load commands too large")
    end = 32 + sizeofcmds
    if end > len(data):
        raise ValueError("load commands exceed available header")
    offset = 32
    for _ in range(ncmds):
        if offset + 8 > end:
            raise ValueError("truncated load command")
        cmd, size = struct.unpack_from("<II", data, offset)
        if size < 8 or offset + size > end:
            raise ValueError("invalid load command size")
        if cmd == LC_UUID:
            if size != 24:
                raise ValueError("invalid LC_UUID size")
            return data[offset + 8:offset + 24].hex()
        offset += size
    raise ValueError("LC_UUID absent")


def macho_uuid_from_reader(reader, address):
    header = reader(address, 32)
    if len(header) != 32:
        raise ValueError("short Mach-O header")
    sizeofcmds = struct.unpack_from("<I", header, 20)[0]
    if sizeofcmds > MAX_HEADER - 32:
        raise ValueError("Mach-O load commands too large")
    return macho_uuid(header + reader(address + 32, sizeofcmds))


def walk_kmods(reader, head, expected_uuid=None):
    seen = set()
    node = head
    for _ in range(MAX_KMODS):
        if not node:
            raise ValueError("Raphael kmod absent")
        if node in seen:
            raise ValueError("kmod list cycle")
        seen.add(node)
        raw = reader(node, 0xAC)
        if len(raw) != 0xAC:
            raise ValueError("short kmod_info")
        name = raw[KMOD_NAME:KMOD_NAME + 64].split(b"\0", 1)[0].decode("ascii", "strict")
        address = struct.unpack_from("<Q", raw, KMOD_ADDRESS)[0]
        if name == "RaphaelGPU" or name.endswith(".RaphaelGPU"):
            uuid = macho_uuid_from_reader(reader, address)
            if expected_uuid and uuid != expected_uuid.lower().replace("-", ""):
                raise ValueError("Raphael UUID mismatch")
            return name, address, uuid
        node = struct.unpack_from("<Q", raw)[0]
    raise ValueError("kmod traversal cap reached")


def generate(runtime_text, expected_uuid, kernel_symbols, raphael_dsym):
    relocation = kernel_relocation(runtime_text, 0xffffff8000200000)
    expected_uuid = expected_uuid.lower().replace("-", "")
    if len(expected_uuid) != 32 or any(c not in "0123456789abcdef" for c in expected_uuid):
        raise ValueError("expected UUID must be 16-byte hexadecimal")
    # GDB's bundled Python performs all target-memory parsing. Read sizes and list
    # traversal are capped and every identity mismatch raises before symbols load.
    tool_path = Path(__file__).resolve()
    return f'''set pagination off
set confirm off
file {kernel_symbols}
target remote 127.0.0.1:1234
symbol-file -o 0x{relocation:x} {kernel_symbols}
python
import gdb, struct, importlib.util
MAX_HEADER = 65536
MAX_KMODS = 256
KMOD_NAME = 0x10
KMOD_ADDRESS = 0x9c
EXPECTED_UUID = '{expected_uuid}'
KERNEL_LINK_TEXT = 0xffffff8000200000
KERNEL_RUNTIME_TEXT = 0x{runtime_text:x}
RELOCATION = KERNEL_RUNTIME_TEXT - KERNEL_LINK_TEXT
inf = gdb.selected_inferior()
def read(addr, size):
    if size < 0 or size > MAX_HEADER: raise gdb.GdbError('bounded read refused')
    return bytes(inf.read_memory(addr, size))
# Runtime kernel load-command vmaddrs are already relocated. Validate __TEXT and
# derive _kmod from the independently observed runtime __DATA segment.
kh = read(KERNEL_RUNTIME_TEXT, 32)
_,_,_,_,kn,kbytes,_,_ = struct.unpack_from('<IiiIIIII', kh)
if kbytes > MAX_HEADER-32: raise gdb.GdbError('kernel commands exceed cap')
kb = read(KERNEL_RUNTIME_TEXT, 32+kbytes); off=32; runtime_text=None; runtime_data=None
for _ in range(kn):
    cmd,size=struct.unpack_from('<II',kb,off)
    if size < 8 or off+size > len(kb): raise gdb.GdbError('bad kernel load command')
    if cmd == 0x19:
        seg=kb[off+8:off+24].rstrip(b'\\0'); vmaddr,vmsize=struct.unpack_from('<QQ',kb,off+24)
        if seg == b'__TEXT': runtime_text=(vmaddr,vmsize)
        if seg == b'__DATA': runtime_data=(vmaddr,vmsize)
    off += size
if runtime_text != (KERNEL_RUNTIME_TEXT,0xa00000): raise gdb.GdbError('kernel __TEXT mapping mismatch')
if runtime_data is None or not (runtime_data[0] <= runtime_data[0]+0x214938 < runtime_data[0]+runtime_data[1]): raise gdb.GdbError('kernel __DATA mapping mismatch')
kmod_head_ptr = runtime_data[0] + 0x214938
spec=importlib.util.spec_from_file_location('rgpu_gdb_helper','{tool_path}')
helper=importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
node = struct.unpack('<Q', read(kmod_head_ptr,8))[0]
try: name,found,uuid=helper.walk_kmods(read,node,EXPECTED_UUID)
except ValueError as error: raise gdb.GdbError(str(error))
print('RAPHAEL_AUTHENTICATED name=%s address=%#x uuid=%s' % (name,found,uuid))
expected=bytes.fromhex('554889e54157415641554154534881ec')
if read(found+0x3cf0,len(expected)) != expected: raise gdb.GdbError('Raphael criticalDumpThread bytes mismatch')
gdb.execute('add-symbol-file {raphael_dsym}/Contents/Resources/DWARF/RaphaelGPU -o %#x' % found)
_,sals=gdb.decode_line('RaphaelGPU.cpp:532')
if not sals: raise gdb.GdbError('source line 532 unresolved')
addresses=sorted(set(int(sal.pc) for sal in sals))
if len(addresses) != 1: raise gdb.GdbError('source line 532 is ambiguous')
gdb.execute('hbreak *%#x' % addresses[0])
print('SOURCE_BREAKPOINT_ARMED RaphaelGPU.cpp:532 address=%#x' % addresses[0])
end
continue
printf "SOURCE_BREAKPOINT_HIT RaphaelGPU.cpp:532\\n"
info locals
info registers rip rsp rdi rsi rdx rcx rax rbp cr3
x/8gx $rsp
disable 1
set $before_pc=$pc
si
printf "AFTER_SOURCE_STEP before=%p after=%p\\n", $before_pc, $pc
info registers rip rsp rax
detach
quit
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-kernel-text", required=True, type=lambda x: int(x, 0))
    parser.add_argument("--raphael-uuid", required=True)
    parser.add_argument("--kernel-symbols", required=True)
    parser.add_argument("--raphael-dsym", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(generate(args.runtime_kernel_text, args.raphael_uuid,
                                    args.kernel_symbols, args.raphael_dsym))


if __name__ == "__main__":
    main()
