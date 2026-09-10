#!/usr/bin/env python3
"""Generate a bounded GDB script for a source breakpoint in RaphaelGPU."""

import argparse
import re
import struct
import subprocess
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


def artifact_uuid(path):
    output = subprocess.check_output(["llvm-dwarfdump", "--uuid", str(path)], text=True)
    match = re.search(r"UUID:\s*([0-9A-Fa-f-]{36})\s", output)
    if not match:
        raise ValueError("artifact UUID absent")
    return match.group(1).lower().replace("-", "")


def symbol_bounds(dsym, wrapper_name):
    dwarf = Path(dsym) / "Contents/Resources/DWARF/RaphaelGPU"
    output = subprocess.check_output(["llvm-nm", "-nm", str(dwarf)], text=True)
    symbols = []
    for line in output.splitlines():
        match = re.match(r"^([0-9a-fA-F]+) .* ([^ ]+)$", line)
        if match:
            symbols.append((int(match.group(1), 16), match.group(2)))
    matches = [address for address, name in symbols if wrapper_name in name]
    if len(matches) != 1 or matches[0] <= 0:
        raise ValueError("wrapper symbol must resolve exactly once")
    following = [address for address, _ in symbols if address > matches[0]]
    if not following:
        raise ValueError("wrapper symbol end absent")
    return matches[0], min(following)


def symbol_offset(dsym, wrapper_name):
    return symbol_bounds(dsym, wrapper_name)[0]


def executable_bytes(binary, offset, size=16):
    data = Path(binary).read_bytes()
    if len(data) < 32:
        raise ValueError("truncated executable")
    _,_,_,_,ncmds,sizeofcmds,_,_=struct.unpack_from('<IiiIIIII',data)
    cursor=32; file_offset=None
    for _ in range(ncmds):
        cmd,cmdsize=struct.unpack_from('<II',data,cursor)
        if cmdsize < 8 or cursor+cmdsize > 32+sizeofcmds:
            raise ValueError("invalid executable load command")
        if cmd == 0x19:
            vmaddr,vmsize,fileoff,filesize=struct.unpack_from('<QQQQ',data,cursor+24)
            if vmaddr <= offset < vmaddr+vmsize and offset-vmaddr+size <= filesize:
                file_offset=fileoff+offset-vmaddr; break
        cursor += cmdsize
    if file_offset is None or offset <= 0 or size <= 0 or file_offset + size > len(data):
        raise ValueError("wrapper bytes outside executable")
    return data[file_offset:file_offset + size]


def native_call_offsets(binary, function_offset, function_end, wrapper_name):
    output = subprocess.check_output([
        "llvm-objdump", "-d", f"--start-address={function_offset:#x}",
        f"--stop-address={function_end:#x}", str(binary)], text=True)
    matches = []
    for line in output.splitlines():
        if "callq" in line and "orgVmmUpdateEntries" in line:
            match = re.match(r"\s*([0-9a-fA-F]+):", line)
            if match:
                address=int(match.group(1),16)
                if function_offset <= address < function_end:
                    matches.append(address)
    if not matches or len(matches) > 4:
        raise ValueError(f"native call boundary count invalid for {wrapper_name}")
    return sorted(set(matches))


def dwarf_source_root(dsym):
    dwarf = Path(dsym) / "Contents/Resources/DWARF/RaphaelGPU"
    output = subprocess.check_output(["llvm-dwarfdump", "--debug-info", str(dwarf)],
                                     text=True)
    matches = re.findall(r'DW_AT_(?:name|decl_file)\s*\("([^"]*/RaphaelGPU\.cpp)"\)', output)
    roots = {str(Path(path).parent) for path in matches}
    if len(roots) != 1:
        raise ValueError("DWARF RaphaelGPU source root must resolve exactly once")
    return roots.pop()


def generate(runtime_text, expected_uuid, kernel_symbols, raphael_dsym,
             function_offset, wrapper_name, expected_prologue=None,
             native_offsets=(), original_source_root=None):
    relocation = kernel_relocation(runtime_text, 0xffffff8000200000)
    expected_uuid = expected_uuid.lower().replace("-", "")
    if len(expected_uuid) != 32 or any(c not in "0123456789abcdef" for c in expected_uuid):
        raise ValueError("expected UUID must be 16-byte hexadecimal")
    if function_offset <= 0:
        raise ValueError("function offset must be positive")
    if not wrapper_name or not all(c.isalnum() or c == '_' for c in wrapper_name):
        raise ValueError("invalid wrapper name")
    if not expected_prologue or len(expected_prologue) < 8 or len(expected_prologue) > 32:
        raise ValueError("expected wrapper prologue must contain 8..32 bytes")
    if not native_offsets or len(native_offsets) > 2 or any(offset <= function_offset for offset in native_offsets):
        raise ValueError("native call offsets must follow wrapper entry")
    # GDB's bundled Python performs all target-memory parsing. Read sizes and list
    # traversal are capped and every identity mismatch raises before symbols load.
    tool_path = Path(__file__).resolve()
    return f'''set pagination off
set confirm off
file {kernel_symbols}
directory {Path(raphael_dsym).parent / 'source'}
{('set substitute-path '+original_source_root+' '+str(Path(raphael_dsym).parent / 'source')) if original_source_root else ''}
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
FUNCTION_OFFSET = 0x{function_offset:x}
WRAPPER_NAME = '{wrapper_name}'
EXPECTED_PROLOGUE = bytes.fromhex('{expected_prologue.hex()}')
NATIVE_OFFSETS = {list(native_offsets)!r}
inf = gdb.selected_inferior()
def read(addr, size):
    if size < 0 or size > MAX_HEADER: raise gdb.GdbError('bounded read refused')
    return bytes(inf.read_memory(addr, size))
def safe_memory(label, addr, size=32):
    size=max(0,min(int(size),64))
    try: print('%s address=%#x bytes=%s' % (label,addr,read(addr,size).hex()))
    except Exception as error: print('%s unavailable=%s' % (label,error))
def optional_command(command):
    try: print(gdb.execute(command,to_string=True))
    except Exception as error: print('%s unavailable=%s' % (command,error))
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
gdb.execute('add-symbol-file {raphael_dsym}/Contents/Resources/DWARF/RaphaelGPU -o %#x' % found)
address=found+FUNCTION_OFFSET
if read(address,len(EXPECTED_PROLOGUE)) != EXPECTED_PROLOGUE: raise gdb.GdbError('runtime wrapper bytes mismatch')
gdb.execute('hbreak *%#x' % address)
for native_offset in NATIVE_OFFSETS: gdb.execute('hbreak *%#x' % (found+native_offset))
print('WRAPPER_BREAKPOINT_ARMED name=%s offset=%#x address=%#x' % (WRAPPER_NAME,FUNCTION_OFFSET,address))
end
continue
python
if int(gdb.parse_and_eval('$pc')) != address: raise gdb.GdbError('entry stop PC mismatch')
end
printf "WRAPPER_ENTRY_HIT\\n"
set $entry_rdi=$rdi
set $entry_rsi=$rsi
set $entry_rdx=$rdx
set $entry_rcx=$rcx
set $entry_r8=$r8
set $entry_r9=$r9
set $entry_thread=$_thread
set $entry_return=*(unsigned long long*)$rsp
printf "ARGS self=%p destination=%#lx count=%lu source=%#lx template=%#lx increment=%#lx\\n", $entry_rdi, $entry_rsi, $entry_rdx, $entry_rcx, $entry_r8, $entry_r9
printf "destination/source are GPU addresses; intentionally not dereferenced\\n"
python safe_memory('self-before',int(gdb.parse_and_eval('$entry_rdi')),32)
python optional_command('info source'); optional_command('info line *$pc'); optional_command('info locals')
disable 1
continue
python
native_pc=int(gdb.parse_and_eval('$pc'))
if native_pc not in [found+x for x in NATIVE_OFFSETS]: raise gdb.GdbError('native boundary stop PC mismatch')
if int(gdb.parse_and_eval('$_thread')) != int(gdb.parse_and_eval('$entry_thread')): raise gdb.GdbError('native boundary thread mismatch')
print('NATIVE_CALL_BOUNDARY pc=%#x CPU_RETURN_PENDING GPU_COMPLETION_UNESTABLISHED VMID_UNESTABLISHED' % native_pc)
end
printf "NATIVE_ARGS self=%p destination=%#lx count=%lu source=%#lx template=%#lx increment=%#lx\\n", $rdi, $rsi, $rdx, $rcx, $r8, $r9
printf "INPUT_SOURCE=%#lx DECISION_RESULT_OUTGOING_SOURCE=%#lx callerOffset/source decision via DWARF follows when available\\n", $entry_rcx, $rcx
python optional_command('info locals'); optional_command('print decision'); optional_command('print cachedFbBase'); optional_command('print cachedFbTop'); optional_command('print cachedFbOffset')
disable 2
python
if len(NATIVE_OFFSETS) > 1: gdb.execute('disable 3')
end
finish
python
if int(gdb.parse_and_eval('$_thread')) != int(gdb.parse_and_eval('$entry_thread')): raise gdb.GdbError('return thread mismatch')
if int(gdb.parse_and_eval('$pc')) != int(gdb.parse_and_eval('$entry_return')): raise gdb.GdbError('return stop PC mismatch')
end
printf "WRAPPER_CPU_RETURN_HIT GPU_COMPLETION_UNESTABLISHED VMID_UNESTABLISHED DMA_MAY_CHANGE_MEMORY_ASYNCHRONOUSLY\\n"
python safe_memory('self-after-return',int(gdb.parse_and_eval('$entry_rdi')),32)
python safe_memory('stack-after-return',int(gdb.parse_and_eval('$rsp')),32)
detach
quit
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-kernel-text", required=True, type=lambda x: int(x, 0))
    parser.add_argument("--raphael-uuid")
    parser.add_argument("--raphael-binary", type=Path)
    parser.add_argument("--kernel-symbols", required=True)
    parser.add_argument("--raphael-dsym", required=True)
    parser.add_argument("--function-offset", type=lambda x: int(x, 0))
    parser.add_argument("--wrapper-name", default="wrapVmmUpdateEntries")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    expected_uuid = artifact_uuid(args.raphael_binary) if args.raphael_binary else args.raphael_uuid
    if not expected_uuid:
        parser.error("one of --raphael-binary or --raphael-uuid is required")
    if args.raphael_binary and artifact_uuid(args.raphael_dsym) != expected_uuid:
        parser.error("Raphael binary/dSYM UUID mismatch")
    symbol_start, symbol_end = symbol_bounds(args.raphael_dsym, args.wrapper_name)
    offset = args.function_offset or symbol_start
    if offset != symbol_start:
        parser.error("provided function offset differs from dSYM symbol")
    if not args.raphael_binary:
        parser.error("--raphael-binary is required to authenticate runtime wrapper bytes")
    prologue = executable_bytes(args.raphael_binary, offset)
    native_offsets = native_call_offsets(args.raphael_binary, offset, symbol_end,
                                         args.wrapper_name)
    original_source_root = dwarf_source_root(args.raphael_dsym)
    args.output.write_text(generate(args.runtime_kernel_text, expected_uuid,
                                    args.kernel_symbols, args.raphael_dsym,
                                    offset, args.wrapper_name, prologue,
                                    native_offsets, original_source_root))


if __name__ == "__main__":
    main()
