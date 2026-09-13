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

# Raphael GC wrapper offsets used for observation.  These are deliberately ordinary
# software breakpoints: the three hardware slots remain reserved for startKIQ entry,
# its native call, and the dynamic return.  The runtime prologues are authenticated
# before arming them.  The register number is the GC segment-0 CP_MEC_CNTL index.
KIQ_MEC_REGISTER = 0x21B5


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


def decode_invalidate_info(raw):
    if len(raw) != 0x28:
        raise ValueError("invalidate info must be exactly 0x28 bytes")
    hub, vmid = struct.unpack_from("<II", raw)
    root = struct.unpack_from("<Q", raw, 0x18)[0]
    return hub, vmid, root, raw[0x24]


def decode_prepared_root(raw):
    if len(raw) != 0x54:
        raise ValueError("prepared output must be exactly 0x54 bytes")
    return (struct.unpack_from("<I", raw, 12)[0] << 32) | struct.unpack_from("<I", raw, 4)[0]


def matching_native_call(entry_rsp, entry_return, entry_args, native_rbp,
                         saved_return, outgoing_args, stable_indices=(0, 1, 2, 4, 5)):
    if native_rbp + 8 != entry_rsp or saved_return != entry_return:
        return False
    return all(outgoing_args[index] == entry_args[index]
               for index in stable_indices)


def update_covers(destination, count, target):
    limit = (1 << 64) - 1
    if not all(isinstance(value, int) and 0 <= value <= limit
               for value in (destination, count, target)):
        return False
    return (count > 0 and count <= limit // 8 and destination <= target and
            target - destination < count * 8)


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


def native_call_offsets(binary, function_offset, function_end, wrapper_name, native_symbol):
    output = subprocess.check_output([
        "llvm-objdump", "-d", f"--start-address={function_offset:#x}",
        f"--stop-address={function_end:#x}", str(binary)], text=True)
    matches = []
    for line in output.splitlines():
        if "callq" in line and native_symbol in line:
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
             native_offsets=(), original_source_root=None, target_gpu_address=None,
             scenario="entry-update"):
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
    expected_calls = 1 if scenario == "vmid1-root" else 0 if scenario == "post-probe" else 2
    if scenario == "vmid1-root" and not expected_prologue.startswith(bytes.fromhex("554889e5")):
        raise ValueError("vmid1-root requires push-rbp/mov-rsp-rbp frame-pointer prologue")
    if scenario not in ("entry-update", "vmid1-root", "post-probe", "kiq-stamp"):
        raise ValueError("unknown capture scenario")
    if (scenario != "post-probe" and
            (len(native_offsets) != expected_calls or
             any(offset <= function_offset for offset in native_offsets))):
        raise ValueError(f"exactly {expected_calls} native call offsets must follow wrapper entry")
    if target_gpu_address is not None and not 0 <= target_gpu_address < 1 << 64:
        raise ValueError("target GPU address must be uint64")
    # GDB's bundled Python performs all target-memory parsing. Read sizes and list
    # traversal are capped and every identity mismatch raises before symbols load.
    tool_path = Path(__file__).resolve()
    script = f'''set pagination off
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
SCENARIO = '{scenario}'
EXPECTED_PROLOGUE = bytes.fromhex('{expected_prologue.hex()}')
NATIVE_OFFSETS = {list(native_offsets)!r}
TARGET_GPU_ADDRESS = {target_gpu_address!r}
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
{('gdb.execute(\'hbreak *%#x\' % address)\nfor native_offset in NATIVE_OFFSETS: gdb.execute(\'hbreak *%#x\' % (found+native_offset))\ngdb.execute(\'disable 2\')\nprint(\'WRAPPER_BREAKPOINT_ARMED name=%s offset=%#x address=%#x scenario=vmid1-root\' % (WRAPPER_NAME,FUNCTION_OFFSET,address))\n# Invalid/unreadable info pointers are bounded failures for that stop and skipped.\nwhile True:\n    gdb.execute(\'continue\')\n    if int(gdb.parse_and_eval(\'$pc\')) != address: raise gdb.GdbError(\'entry stop PC mismatch\')\n    try:\n        raw=read(int(gdb.parse_and_eval(\'$rdx\')),0x28)\n        hub,vmid,original_root,reprogram=helper.decode_invalidate_info(raw)\n    except Exception as error:\n        print(\'VMID1_ENTRY_INFO_UNAVAILABLE error=%s\' % error); continue\n    if hub == 0 and vmid == 1 and reprogram == 1: break\nprint(\'VMID1_WRAPPER_ENTRY_HIT hub=%u vmid=%u reprogram=%u VMID1_ORIGINAL_ROOT=%#x\' % (hub,vmid,reprogram,original_root))\nend\nset $entry_rdi=$rdi\nset $entry_rsi=$rsi\nset $entry_rdx=$rdx\nset $entry_rcx=$rcx\nset $entry_rsp=$rsp\nset $entry_return=*(unsigned long long*)$rsp\ndisable 1\nenable 2\ncondition 2 $rbp+8==$entry_rsp && *(unsigned long long*)($rbp+8)==$entry_return && $rdi==$entry_rdi && $rsi==$entry_rsi && $rcx==$entry_rcx\npython safe_memory(\'vmid1-original-info\',int(gdb.parse_and_eval(\'$entry_rdx\')),0x28); optional_command(\'info source\'); optional_command(\'info line *$pc\')\ncontinue\npython\nnative_pc=int(gdb.parse_and_eval(\'$pc\'))\nif native_pc not in [found+x for x in NATIVE_OFFSETS]: raise gdb.GdbError(\'native boundary stop PC mismatch\')\nnative_rbp=int(gdb.parse_and_eval(\'$rbp\')); saved=struct.unpack(\'<Q\',read(native_rbp+8,8))[0]\nentry_args=tuple(int(gdb.parse_and_eval(\'$entry_\'+r)) & ((1<<64)-1) for r in (\'rdi\',\'rsi\',\'rdx\',\'rcx\'))\noutgoing=tuple(int(gdb.parse_and_eval(\'$\'+r)) & ((1<<64)-1) for r in (\'rdi\',\'rsi\',\'rdx\',\'rcx\'))\nif not helper.matching_native_call(int(gdb.parse_and_eval(\'$entry_rsp\')),int(gdb.parse_and_eval(\'$entry_return\')),entry_args,native_rbp,saved,outgoing,(0,1,3)): raise gdb.GdbError(\'native call identity mismatch\')\nnative_info=outgoing[2]\ntry: native_raw=read(native_info,0x28); _,_,native_root,_=helper.decode_invalidate_info(native_raw)\nexcept Exception as error: raise gdb.GdbError(\'bounded native info read failed: %s\' % error)\nprint(\'VMID1_NATIVE_CALL_BOUNDARY pc=%#x VMID1_NATIVE_ROOT=%#x CPU_REQUEST_COPY_ONLY ACTUAL_REGISTER_PROGRAMMING_UNESTABLISHED\' % (native_pc,native_root))\nsafe_memory(\'vmid1-native-info\',native_info,0x28)\noptional_command(\'print local.reason\'); optional_command(\'print local.repaired\'); optional_command(\'print local.originalRoot\'); optional_command(\'print local.nativeRoot\')\ngdb.execute(\'disable 1\'); gdb.execute(\'disable 2\')\ngdb.execute(\'hbreak *%#x\' % int(gdb.parse_and_eval(\'$entry_return\')))\ngdb.execute(\'condition 3 $rsp==$entry_rsp+8\')\nend\ncontinue\npython\nif int(gdb.parse_and_eval(\'$pc\')) != int(gdb.parse_and_eval(\'$entry_return\')): raise gdb.GdbError(\'return stop PC mismatch\')\nif int(gdb.parse_and_eval(\'$rsp\')) != int(gdb.parse_and_eval(\'$entry_rsp\'))+8: raise gdb.GdbError(\'return stack mismatch\')\nprepared=int(gdb.parse_and_eval(\'$entry_rsi\'))\ntry: prepared_raw=read(prepared,0x54); prepared_root=helper.decode_prepared_root(prepared_raw)\nexcept Exception as error: raise gdb.GdbError(\'bounded prepared output read failed: %s\' % error)\nprint(\'VMID1_PREPARED_CPU_OUTPUT root=%#x ACTUAL_REGISTER_PROGRAMMING_UNESTABLISHED GPU_COMPLETION_UNESTABLISHED\' % prepared_root)\nsafe_memory(\'vmid1-prepared-output\',prepared,0x54)\nend\nprintf "WRAPPER_CPU_RETURN_HIT GPU_COMPLETION_UNESTABLISHED ACTUAL_REGISTER_PROGRAMMING_UNESTABLISHED DMA_MAY_CHANGE_MEMORY_ASYNCHRONOUSLY\\n"\ndetach\nquit\n' if scenario == 'vmid1-root' else 'gdb.execute(\'hbreak *%#x\' % address)\nfor native_offset in NATIVE_OFFSETS: gdb.execute(\'hbreak *%#x\' % (found+native_offset))\ngdb.execute(\'disable 2\'); gdb.execute(\'disable 3\')\nif TARGET_GPU_ADDRESS is not None:\n    gdb.execute(\'condition 1 (unsigned long long)$rdx>0 && (unsigned long long)$rdx<=0x1fffffffffffffff && (unsigned long long)$rsi<=%#x && %#x-(unsigned long long)$rsi<(unsigned long long)$rdx*8\' % (TARGET_GPU_ADDRESS,TARGET_GPU_ADDRESS))\nprint(\'WRAPPER_BREAKPOINT_ARMED name=%s offset=%#x address=%#x\' % (WRAPPER_NAME,FUNCTION_OFFSET,address))\nend\ncontinue\npython\nif int(gdb.parse_and_eval(\'$pc\')) != address: raise gdb.GdbError(\'entry stop PC mismatch\')\nend\nprintf "WRAPPER_ENTRY_HIT\\\\n"\nset $entry_rdi=$rdi\nset $entry_rsi=$rsi\nset $entry_rdx=$rdx\nset $entry_rcx=$rcx\nset $entry_r8=$r8\nset $entry_r9=$r9\nset $entry_rsp=$rsp\nset $entry_return=*(unsigned long long*)$rsp\ndisable 1\nenable 2\nenable 3\ncondition 2 $rbp+8==$entry_rsp && *(unsigned long long*)($rbp+8)==$entry_return && $rdi==$entry_rdi && $rsi==$entry_rsi && $rdx==$entry_rdx && $r8==$entry_r8 && $r9==$entry_r9\ncondition 3 $rbp+8==$entry_rsp && *(unsigned long long*)($rbp+8)==$entry_return && $rdi==$entry_rdi && $rsi==$entry_rsi && $rdx==$entry_rdx && $r8==$entry_r8 && $r9==$entry_r9\nhbreak *$entry_return\ncondition 4 $rsp==$entry_rsp+8\nprintf "ARGS self=%p destination=%#lx count=%lu source=%#lx template=%#lx increment=%#lx\\\\n", $entry_rdi, $entry_rsi, $entry_rdx, $entry_rcx, $entry_r8, $entry_r9\nprintf "destination/source are GPU addresses; intentionally not dereferenced\\\\n"\npython safe_memory(\'self-before\',int(gdb.parse_and_eval(\'$entry_rdi\')) & ((1<<64)-1),32)\npython optional_command(\'info source\'); optional_command(\'info line *$pc\')\ndisable 1\ncontinue\npython\nnative_pc=int(gdb.parse_and_eval(\'$pc\'))\nif native_pc not in [found+x for x in NATIVE_OFFSETS]: raise gdb.GdbError(\'native boundary stop PC mismatch\')\nnative_rbp=int(gdb.parse_and_eval(\'$rbp\')); saved=struct.unpack(\'<Q\',read(native_rbp+8,8))[0]\nentry_args=tuple(int(gdb.parse_and_eval(\'$entry_\'+r)) & ((1<<64)-1) for r in (\'rdi\',\'rsi\',\'rdx\',\'rcx\',\'r8\',\'r9\'))\noutgoing=tuple(int(gdb.parse_and_eval(\'$\'+r)) & ((1<<64)-1) for r in (\'rdi\',\'rsi\',\'rdx\',\'rcx\',\'r8\',\'r9\'))\nif not helper.matching_native_call(int(gdb.parse_and_eval(\'$entry_rsp\')),int(gdb.parse_and_eval(\'$entry_return\')),entry_args,native_rbp,saved,outgoing): raise gdb.GdbError(\'native call identity mismatch\')\nprint(\'NATIVE_CALL_BOUNDARY pc=%#x CPU_RETURN_PENDING GPU_COMPLETION_UNESTABLISHED VMID_UNESTABLISHED\' % native_pc)\nend\nprintf "NATIVE_ARGS self=%p destination=%#lx count=%lu source=%#lx template=%#lx increment=%#lx\\\\n", $rdi, $rsi, $rdx, $rcx, $r8, $r9\nprintf "INPUT_SOURCE=%#lx DECISION_RESULT_OUTGOING_SOURCE=%#lx callerOffset/source decision via DWARF follows when available\\\\n", $entry_rcx, $rcx\npython optional_command(\'info locals\'); optional_command(\'print decision\'); optional_command(\'print cachedFbBase\'); optional_command(\'print cachedFbTop\'); optional_command(\'print cachedFbOffset\')\ndisable 1\ndisable 2\ndisable 3\ncontinue\npython\nif int(gdb.parse_and_eval(\'$pc\')) != int(gdb.parse_and_eval(\'$entry_return\')): raise gdb.GdbError(\'return stop PC mismatch\')\nif int(gdb.parse_and_eval(\'$rsp\')) != int(gdb.parse_and_eval(\'$entry_rsp\'))+8: raise gdb.GdbError(\'return stack mismatch\')\nend\nprintf "WRAPPER_CPU_RETURN_HIT GPU_COMPLETION_UNESTABLISHED VMID_UNESTABLISHED DMA_MAY_CHANGE_MEMORY_ASYNCHRONOUSLY\\\\n"\npython safe_memory(\'self-after-return\',int(gdb.parse_and_eval(\'$entry_rdi\')) & ((1<<64)-1),32)\npython safe_memory(\'stack-after-return\',int(gdb.parse_and_eval(\'$rsp\')) & ((1<<64)-1),32)\ndetach\nquit\n')}'''

    if scenario == 'post-probe':
        marker = "gdb.execute('hbreak *%#x' % address)"
        prefix = script.split(marker, 1)[0]
        script = prefix + """gdb.execute('interrupt')
print('POST_PROBE_INTERRUPT_HIT')
print('POST_PROBE_VCPU_REGISTERS')
optional_command('info registers')
print('POST_PROBE_VCPU_BACKTRACE')
optional_command('thread apply all bt 8')
print('POST_PROBE_SELECTED_VCPU_BACKTRACE')
optional_command('bt full 8')
print('POST_PROBE_VCPU_STACK')
optional_command('x/32gx $rsp')
gdb.execute('detach')
print('POST_PROBE_DETACHED')
gdb.execute('quit')
end
quit
"""
    return script


def generate_kiq_stamp(runtime_text, expected_uuid, kernel_symbols, raphael_dsym,
                       wait_offset, wait_prologue, submit_offset, submit_prologue,
                       original_source_root=None):
    """Generate an authenticated, bounded KIQ entry/return observation."""
    relocation = kernel_relocation(runtime_text, 0xffffff8000200000)
    uuid = expected_uuid.lower().replace('-', '')
    if len(uuid) != 32 or any(c not in '0123456789abcdef' for c in uuid):
        raise ValueError('expected UUID must be 16-byte hexadecimal')
    if min(wait_offset, submit_offset) <= 0:
        raise ValueError('KIQ wrapper offsets must be positive')
    if not (8 <= len(wait_prologue) <= 32 and 8 <= len(submit_prologue) <= 32):
        raise ValueError('KIQ wrapper prologues must contain 8..32 bytes')
    tool_path = Path(__file__).resolve()
    substitute = ('set substitute-path ' + original_source_root + ' ' +
                  str(Path(raphael_dsym).parent / 'source')) if original_source_root else ''
    return f'''set pagination off
set confirm off
file {kernel_symbols}
directory {Path(raphael_dsym).parent / 'source'}
{substitute}
target remote 127.0.0.1:1234
symbol-file -o 0x{relocation:x} {kernel_symbols}
python
import gdb, struct, importlib.util, time
MAX_HEADER=65536; KERNEL_RUNTIME_TEXT=0x{runtime_text:x}; EXPECTED_UUID='{uuid}'
WAIT_OFFSET=0x{wait_offset:x}; SUBMIT_OFFSET=0x{submit_offset:x}
WAIT_PROLOGUE=bytes.fromhex('{wait_prologue.hex()}'); SUBMIT_PROLOGUE=bytes.fromhex('{submit_prologue.hex()}')
inf=gdb.selected_inferior()
def read(a,n):
    if n < 0 or n > MAX_HEADER: raise gdb.GdbError('bounded read refused')
    return bytes(inf.read_memory(a,n))
def safe(label,a,n=64):
    n=max(0,min(int(n),256))
    try: print('%s address=%#x bytes=%s' % (label,a,read(a,n).hex()))
    except Exception as e: print('%s unavailable=%s' % (label,e))
def canonical(a):
    return a != 0 and (a <= 0x00007fffffffffff or a >= 0xffff800000000000)
def safe_canonical(label,a,n=0x100):
    if not canonical(a): print('%s unavailable=noncanonical address=%#x' % (label,a)); return
    safe(label,a,n)
def channel_state(label,a):
    try:
        requested=struct.unpack('<I',read(a+0x80,4))[0]
        stamp=struct.unpack('<I',read(a+0x84,4))[0]
        ring=struct.unpack('<Q',read(a+0x30,8))[0]
        timestamp=struct.unpack('<Q',read(a+0xc0,8))[0]
        mode=struct.unpack('<I',read(a+0xe0,4))[0]
        timestamp_ok = canonical(timestamp)
        print('%s self=%#x requested_stamp=%u current_stamp=%u ring=%#x timestamp_cpu=%#x mode_raw=%#x timestamp_canonical=%u' %
              (label,a,requested,stamp,ring,timestamp,mode,timestamp_ok))
        if timestamp_ok and mode == 0xffffffff:
            fence=read(timestamp,4)
            print('%s timestamp_memory32=%s' % (label,fence.hex()))
        else:
            print('%s timestamp_memory32=not-read mode_raw=%#x' % (label,mode))
        if canonical(ring): safe_canonical(label+'-ring-descriptor',ring,0x100)
        else: print('%s-ring-descriptor unavailable=noncanonical address=%#x' % (label,ring))
    except Exception as e: print('%s unavailable=%s' % (label,e))
kh=read(KERNEL_RUNTIME_TEXT,32); _,_,_,_,kn,kbytes,_,_=struct.unpack_from('<IiiIIIII',kh)
if kbytes > MAX_HEADER-32: raise gdb.GdbError('kernel commands exceed cap')
kb=read(KERNEL_RUNTIME_TEXT,32+kbytes); off=32; data=None
for _ in range(kn):
    cmd,size=struct.unpack_from('<II',kb,off)
    if size < 8 or off+size > len(kb): raise gdb.GdbError('bad kernel load command')
    if cmd == 0x19 and kb[off+8:off+24].rstrip(b'\\0') == b'__DATA': data=struct.unpack_from('<QQ',kb,off+24)
    off += size
if data is None: raise gdb.GdbError('kernel __DATA mapping absent')
spec=importlib.util.spec_from_file_location('rgpu_gdb_helper','{tool_path}'); h=importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
node=struct.unpack('<Q',read(data[0]+0x214938,8))[0]
try: name,found,got=h.walk_kmods(read,node,EXPECTED_UUID)
except ValueError as e: raise gdb.GdbError(str(e))
print('RAPHAEL_AUTHENTICATED name=%s address=%#x uuid=%s' % (name,found,got))
gdb.execute('add-symbol-file {raphael_dsym}/Contents/Resources/DWARF/RaphaelGPU -o %#x' % found)
wa=found+WAIT_OFFSET; sa=found+SUBMIT_OFFSET
if read(wa,len(WAIT_PROLOGUE)) != WAIT_PROLOGUE: raise gdb.GdbError('wait wrapper bytes mismatch')
if read(sa,len(SUBMIT_PROLOGUE)) != SUBMIT_PROLOGUE: raise gdb.GdbError('submit wrapper bytes mismatch')
class ReturnBP(gdb.Breakpoint):
    def __init__(self, address, wanted_rsp):
        super().__init__('*%#x' % address, gdb.BP_HARDWARE_BREAKPOINT,
                         internal=True)
        self.target_pc=address
        self.wanted_rsp=wanted_rsp
    def stop(self):
        return int(gdb.parse_and_eval('$pc')) == self.target_pc and int(gdb.parse_and_eval('$rsp')) == self.wanted_rsp
wait_bp=gdb.Breakpoint('*%#x' % wa, gdb.BP_HARDWARE_BREAKPOINT, internal=True)
submit_bp=gdb.Breakpoint('*%#x' % sa, gdb.BP_HARDWARE_BREAKPOINT, internal=True)
print('KIQ_BREAKPOINTS_ARMED wait=%#x submit=%#x' % (wa,sa))
entry=None; ret=None; rsp=None; selfp=None; stamp=None; return_bp=None; started=0.0
while True:
    gdb.execute('continue'); pc=int(gdb.parse_and_eval('$pc'))
    if pc == sa:
        print('KIQ_ENTRY kind=submitKIQFrame self=%#x thread=%s' % (int(gdb.parse_and_eval('$rdi')) & ((1<<64)-1),str(gdb.selected_thread().ptid)))
        channel_state('kiq-submit-channel',int(gdb.parse_and_eval('$rdi')) & ((1<<64)-1)); continue
    if pc == wa:
        entry=pc; wait_bp.enabled=False; rsp=int(gdb.parse_and_eval('$rsp')); ret=struct.unpack('<Q',read(rsp,8))[0]
        selfp=int(gdb.parse_and_eval('$rdi')) & ((1<<64)-1); stamp=(int(gdb.parse_and_eval('$rsi')) & 0xffffffff) if pc==wa else None; started=time.monotonic()
        print('KIQ_ENTRY kind=%s self=%#x stamp=%s a=%#x b=%#x spec=%#x out=%#x rsp=%#x return=%#x thread=%s' % ('waitForHwStamp' if pc==wa else 'submitKIQFrame',selfp,stamp if stamp is not None else 'none',int(gdb.parse_and_eval('$rsi')),int(gdb.parse_and_eval('$rdx')),int(gdb.parse_and_eval('$rcx')),int(gdb.parse_and_eval('$r8')),rsp,ret,str(gdb.selected_thread().ptid)))
        channel_state('kiq-channel-entry',selfp); safe('kiq-channel-self',selfp)
        safe('kiq-channel-descriptor',selfp,0x100)
        return_bp=ReturnBP(ret,rsp+8); continue
    if ret is None or pc != ret or int(gdb.parse_and_eval('$rsp')) != rsp+8: raise gdb.GdbError('KIQ return stop identity mismatch')
    result=int(gdb.parse_and_eval('$rax')) & 0xff
    print('KIQ_RETURN kind=%s self=%#x stamp=%s result=%#x elapsed_ms=%.3f thread=%s' % ('waitForHwStamp' if entry==wa else 'submitKIQFrame',selfp,stamp if stamp is not None else 'none',result,(time.monotonic()-started)*1000,str(gdb.selected_thread().ptid)))
    channel_state('kiq-channel-return',selfp); safe('kiq-channel-return',selfp)
    safe('kiq-channel-descriptor-return',selfp,0x100)
    return_bp.delete(); return_bp=None; wait_bp.enabled=True
    if entry==wa and result==0: print('KIQ_WAIT_FAILURE result=0 stamp=%u' % stamp); break
    ret=None
print('KIQ_CAPTURE_COMPLETE'); gdb.execute('detach'); print('KIQ_DETACHED'); gdb.execute('quit')
end
quit
'''


def generate_kiq_start(runtime_text, expected_uuid, kernel_symbols, raphael_dsym,
                       start_offset, start_prologue, native_offset,
                       original_source_root=None, native_prologue=None,
                       mec_write_specs=()):
    """Generate an authenticated, bounded wrapKiqStart ABI observation."""
    relocation = kernel_relocation(runtime_text, 0xffffff8000200000)
    uuid = expected_uuid.lower().replace('-', '')
    if len(uuid) != 32 or any(c not in '0123456789abcdef' for c in uuid):
        raise ValueError('expected UUID must be 16-byte hexadecimal')
    if start_offset <= 0 or native_offset <= start_offset:
        raise ValueError('KIQ start offsets must be positive and ordered')
    if not (8 <= len(start_prologue) <= 32):
        raise ValueError('KIQ start wrapper prologue must contain 8..32 bytes')
    if not start_prologue.startswith(bytes.fromhex('554889e5')):
        raise ValueError('KIQ start requires push-rbp/mov-rsp-rbp frame-pointer prologue')
    if native_prologue is not None and len(native_prologue) != 6:
        raise ValueError('KIQ native call instruction must contain exactly 6 bytes')
    tool_path = Path(__file__).resolve()
    substitute = ('set substitute-path ' + original_source_root + ' ' +
                  str(Path(raphael_dsym).parent / 'source')) if original_source_root else ''
    return f'''set pagination off
set confirm off
file {kernel_symbols}
directory {Path(raphael_dsym).parent / 'source'}
{substitute}
target remote 127.0.0.1:1234
symbol-file -o 0x{relocation:x} {kernel_symbols}
python
import gdb, struct, importlib.util
MAX_HEADER=65536; KERNEL_RUNTIME_TEXT=0x{runtime_text:x}; EXPECTED_UUID='{uuid}'
START_OFFSET=0x{start_offset:x}; NATIVE_OFFSET=0x{native_offset:x}
START_PROLOGUE=bytes.fromhex('{start_prologue.hex()}')
NATIVE_PROLOGUE=bytes.fromhex('{native_prologue.hex() if native_prologue is not None else ""}')
MEC_REGISTER=0x{KIQ_MEC_REGISTER:x}
MEC_WRITE_SPECS={[(offset, prologue.hex(), path) for offset, prologue, path in mec_write_specs]!r}
inf=gdb.selected_inferior()
def read(a,n):
    if n < 0 or n > MAX_HEADER: raise gdb.GdbError('bounded read refused')
    return bytes(inf.read_memory(a,n))
def safe(label,a,n):
    try: print('%s address=%#x bytes=%s' % (label,a,read(a,n).hex()))
    except Exception as e: print('%s unavailable=%s' % (label,e))
kh=read(KERNEL_RUNTIME_TEXT,32); _,_,_,_,kn,kbytes,_,_=struct.unpack_from('<IiiIIIII',kh)
if kbytes > MAX_HEADER-32: raise gdb.GdbError('kernel commands exceed cap')
kb=read(KERNEL_RUNTIME_TEXT,32+kbytes); off=32; data=None
for _ in range(kn):
    cmd,size=struct.unpack_from('<II',kb,off)
    if size < 8 or off+size > len(kb): raise gdb.GdbError('bad kernel load command')
    if cmd == 0x19 and kb[off+8:off+24].rstrip(b'\\0') == b'__DATA': data=struct.unpack_from('<QQ',kb,off+24)
    off += size
if data is None: raise gdb.GdbError('kernel __DATA mapping absent')
spec=importlib.util.spec_from_file_location('rgpu_gdb_helper','{tool_path}'); h=importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
node=struct.unpack('<Q',read(data[0]+0x214938,8))[0]
try: name,found,got=h.walk_kmods(read,node,EXPECTED_UUID)
except ValueError as e: raise gdb.GdbError(str(e))
print('RAPHAEL_AUTHENTICATED name=%s address=%#x uuid=%s' % (name,found,got))
gdb.execute('add-symbol-file {raphael_dsym}/Contents/Resources/DWARF/RaphaelGPU -o %#x' % found)
start=found+START_OFFSET; native=found+NATIVE_OFFSET
if read(start,len(START_PROLOGUE)) != START_PROLOGUE: raise gdb.GdbError('KIQ start wrapper bytes mismatch')
if NATIVE_PROLOGUE and read(native,len(NATIVE_PROLOGUE)) != NATIVE_PROLOGUE: raise gdb.GdbError('KIQ native call bytes mismatch')
class ReturnBP(gdb.Breakpoint):
    def __init__(self, address, wanted_rsp):
        super().__init__('*%#x' % address, gdb.BP_HARDWARE_BREAKPOINT, internal=True)
        self.target_pc=address; self.wanted_rsp=wanted_rsp
    def stop(self):
        return (int(gdb.parse_and_eval('$pc')) == self.target_pc and
                int(gdb.parse_and_eval('$rsp')) == self.wanted_rsp)
class NativeBP(gdb.Breakpoint):
    def stop(self):
        return (entry_seen and int(gdb.parse_and_eval('$pc')) == native and
                int(gdb.parse_and_eval('$rbp')) + 8 == entry_rsp and
                struct.unpack('<Q',read(int(gdb.parse_and_eval('$rbp'))+8,8))[0] == entry_return and
                (int(gdb.parse_and_eval('$rdi')) & ((1<<64)-1)) == entry_rdi)
class MecWriteBP(gdb.Breakpoint):
    def __init__(self, address, path):
        super().__init__('*%#x' % address, internal=True)
        self.path=path
    def stop(self):
        if not native_active:
            return False
        reg=int(gdb.parse_and_eval('$rsi')) & 0xffffffff
        if reg != 0x21b5:
            return False
        value=int(gdb.parse_and_eval('$rdx')) & 0xffffffff
        pc=int(gdb.parse_and_eval('$pc'))
        try: caller=struct.unpack('<Q',read(int(gdb.parse_and_eval('$rsp')),8))[0]
        except Exception: caller=0
        print('KIQ_MEC_CNTL_WRITE path=%s pc=%#x caller=%#x reg=%#x value=%#x native_interval=1' %
              (self.path,pc,caller,reg,value))
        return False
entry_bp=gdb.Breakpoint('*%#x' % start, gdb.BP_HARDWARE_BREAKPOINT, internal=True)
native_bp=NativeBP('*%#x' % native, gdb.BP_HARDWARE_BREAKPOINT, internal=True)
native_bp.enabled=False
writer_addresses=[]
for offset, prologue_hex, path in MEC_WRITE_SPECS:
    writer=found+offset
    if read(writer,len(bytes.fromhex(prologue_hex))) != bytes.fromhex(prologue_hex):
        raise gdb.GdbError('KIQ MEC writer prologue mismatch path=%s offset=%#x' % (path,offset))
    writer_addresses.append((writer,path))
write_bps=[MecWriteBP(writer, path) for writer,path in writer_addresses]
for bp in write_bps:
    bp.enabled=False
print('KIQ_START_BREAKPOINTS_ARMED entry=%#x native=%#x' % (start,native))
native_reached=False; native_active=False; entry_seen=False; return_bp=None
gdb.execute('continue')
if int(gdb.parse_and_eval('$pc')) != start: raise gdb.GdbError('KIQ start entry stop PC mismatch')
entry_rsp=int(gdb.parse_and_eval('$rsp')); entry_return=None
entry_rdi=int(gdb.parse_and_eval('$rdi')) & ((1<<64)-1)
entry_rsi=int(gdb.parse_and_eval('$rsi')) & ((1<<64)-1)
entry_rdx=int(gdb.parse_and_eval('$rdx')) & ((1<<64)-1)
entry_rcx=int(gdb.parse_and_eval('$rcx')) & ((1<<64)-1)
entry_r8=int(gdb.parse_and_eval('$r8')) & ((1<<64)-1)
entry_spec=entry_rcx; entry_out=entry_r8
raw=None
try: raw=read(entry_spec,12)
except Exception as error:
    print('KIQ_START_ENTRY_SPEC_UNAVAILABLE spec=%#x error=%s' % (entry_spec,error))
try: entry_return=struct.unpack('<Q',read(entry_rsp,8))[0]
except Exception as error:
    print('KIQ_START_ENTRY_STACK_UNAVAILABLE rsp=%#x error=%s' % (entry_rsp,error))
print('KIQ_START_ENTRY self=%#x a=%#x b=%#x spec=%#x out=%#x rsp=%#x return=%s spec_raw=%s thread=%s' %
      (entry_rdi,entry_rsi,entry_rdx,entry_spec,entry_out,entry_rsp,
       ('%#x' % entry_return) if entry_return is not None else 'unavailable',
       raw.hex() if raw is not None else 'unavailable',str(gdb.selected_thread().ptid)))
if entry_return is None or raw is None:
    reason='entry-stack-unavailable' if entry_return is None else 'entry-spec-unavailable'
    print('KIQ_START_CAPTURE_INCOMPLETE reason=%s native_boundary=unavailable return=unavailable' % reason)
    gdb.execute('detach'); print('KIQ_START_DETACHED'); gdb.execute('quit')
entry_bp.enabled=False
entry_seen=True
native_bp.enabled=True
return_bp=ReturnBP(entry_return,entry_rsp+8)
gdb.execute('continue')
if int(gdb.parse_and_eval('$pc')) == native:
    native_reached=True
    native_active=True
    for bp in write_bps: bp.enabled=True
    native_insn=read(native,6)
    if native_insn[:2] == bytes.fromhex('ff15'):
        disp=struct.unpack('<i',native_insn[2:])[0]
        slot=native+6+disp
        try: target=struct.unpack('<Q',read(slot,8))[0]
        except Exception: target=0
        print('KIQ_START_NATIVE_ORG_TARGET pc=%#x bytes=%s slot=%#x target=%#x' %
              (native,native_insn.hex(),slot,target))
    else:
        print('KIQ_START_NATIVE_ORG_TARGET unavailable bytes=%s' % native_insn.hex())
    print('KIQ_START_NATIVE_CALL_BOUNDARY pc=%#x self=%#x a=%#x b=%#x' %
          (native, int(gdb.parse_and_eval('$rdi')), int(gdb.parse_and_eval('$rsi')), int(gdb.parse_and_eval('$rdx'))))
    native_bp.enabled=False
else:
    native_reached=False
if int(gdb.parse_and_eval('$pc')) != entry_return:
    gdb.execute('continue')
native_active=False
for bp in write_bps: bp.enabled=False
if int(gdb.parse_and_eval('$pc')) != entry_return or int(gdb.parse_and_eval('$rsp')) != entry_rsp+8:
    raise gdb.GdbError('KIQ start return stop identity mismatch')
result=int(gdb.parse_and_eval('$rax')) & 0xffffffff
raw_out=read(entry_out,4)
if result == 0: outcome='success'
else: outcome='failure'
print('KIQ_START_RETURN result=%#x outcome=%s native_reached=%s out_raw=%s' % (result,outcome,native_reached,raw_out.hex()))
print('KIQ_START_CAPTURE_COMPLETE')
gdb.execute('detach'); print('KIQ_START_DETACHED'); gdb.execute('quit')
end
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
    parser.add_argument("--scenario", choices=("entry-update", "vmid1-root", "post-probe", "kiq-stamp", "kiq-start"), default="entry-update")
    parser.add_argument("--wrapper-name")
    parser.add_argument("--target-gpu-address", type=lambda x: int(x, 0))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    expected_uuid = artifact_uuid(args.raphael_binary) if args.raphael_binary else args.raphael_uuid
    if not expected_uuid:
        parser.error("one of --raphael-binary or --raphael-uuid is required")
    if args.raphael_binary and artifact_uuid(args.raphael_dsym) != expected_uuid:
        parser.error("Raphael binary/dSYM UUID mismatch")
    if args.scenario == "kiq-start":
        if args.wrapper_name:
            parser.error("--wrapper-name is not used for kiq-start")
        start_name, start_end = symbol_bounds(args.raphael_dsym, "wrapKiqStart")
        start_off = symbol_offset(args.raphael_dsym, "wrapKiqStart")
        start_prologue = executable_bytes(args.raphael_binary, start_off)
        native_offsets = native_call_offsets(args.raphael_binary, start_off, start_end,
                                             "wrapKiqStart", "orgKiqStart")
        if len(native_offsets) != 1:
            parser.error("wrapKiqStart must contain exactly one authenticated orgKiqStart call")
        native_prologue = executable_bytes(args.raphael_binary, native_offsets[0], 6)
        writer_specs = []
        for symbol, path in (('__ZL15wrapGcCgsWrite2Pvjjjj', 'ext2'),
                             ('__ZL14wrapGcCgsWritePvjj', 'register'),
                             ('__ZL17wrapGcCgsWriteExtPvjjj', 'ext')):
            writer_offset = symbol_offset(args.raphael_dsym, symbol)
            writer_specs.append((writer_offset, executable_bytes(
                args.raphael_binary, writer_offset, 16), path))
        original_source_root = dwarf_source_root(args.raphael_dsym)
        args.output.write_text(generate_kiq_start(
            args.runtime_kernel_text, expected_uuid, args.kernel_symbols,
            args.raphael_dsym, start_off, start_prologue, native_offsets[0],
            original_source_root, native_prologue, writer_specs))
        return
    if args.scenario == "kiq-stamp":
        if args.wrapper_name:
            parser.error("--wrapper-name is not used for kiq-stamp")
        wait_wrapper = "wrapWaitStamp"
        wait_name, wait_end = symbol_bounds(args.raphael_dsym, wait_wrapper)
        submit_name, submit_end = symbol_bounds(args.raphael_dsym, "wrapKiqSubmit")
        wait_off = symbol_offset(args.raphael_dsym, wait_wrapper)
        submit_off = symbol_offset(args.raphael_dsym, "wrapKiqSubmit")
        wait_prologue = executable_bytes(args.raphael_binary, wait_off)
        submit_prologue = executable_bytes(args.raphael_binary, submit_off)
        original_source_root = dwarf_source_root(args.raphael_dsym)
        generated = generate_kiq_stamp(
            args.runtime_kernel_text, expected_uuid, args.kernel_symbols,
            args.raphael_dsym, wait_off, wait_prologue, submit_off,
            submit_prologue, original_source_root)
        args.output.write_text(generated)
        return
    wrapper_name = args.wrapper_name or ("wrapVmmPrepare" if args.scenario == "vmid1-root" else "wrapVmmUpdateEntries")
    symbol_start, symbol_end = symbol_bounds(args.raphael_dsym, wrapper_name)
    offset = args.function_offset or symbol_start
    if offset != symbol_start:
        parser.error("provided function offset differs from dSYM symbol")
    if not args.raphael_binary:
        parser.error("--raphael-binary is required to authenticate runtime wrapper bytes")
    prologue = executable_bytes(args.raphael_binary, offset)
    native_offsets = [] if args.scenario == "post-probe" else native_call_offsets(
        args.raphael_binary, offset, symbol_end,
        wrapper_name, "orgVmmPrepare" if args.scenario == "vmid1-root" else "orgVmmUpdateEntries")
    original_source_root = dwarf_source_root(args.raphael_dsym)
    args.output.write_text(generate(args.runtime_kernel_text, expected_uuid,
                                    args.kernel_symbols, args.raphael_dsym,
                                    offset, wrapper_name, prologue,
                                    native_offsets, original_source_root,
                                    args.target_gpu_address, args.scenario))


if __name__ == "__main__":
    main()
