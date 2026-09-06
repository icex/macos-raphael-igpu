#!/usr/bin/env python3
"""List kexts and symbols inside a macOS Mach-O fileset kernel collection.

The AMD drivers ship no standalone binaries any more: their bundles are stubs and
the code is prelinked into SystemKernelExtensions.kc. This walks the fileset so we
can get link-time addresses for gdb (boot the guest with slide=0 and they are the
runtime addresses).

  ./kcsym.py <kc> --list
  ./kcsym.py <kc> --kext com.apple.kext.AMDRadeonX6000Framebuffer [--grep Navi23]
"""
import argparse, struct, sys

LC_SYMTAB, LC_SEGMENT_64, LC_FILESET_ENTRY = 0x2, 0x19, 0x80000035


def u(fmt, b, off):
    return struct.unpack_from(fmt, b, off)


class MachO:
    def __init__(self, buf, base=0):
        self.buf, self.base = buf, base
        magic = u("<I", buf, base)[0]
        if magic != 0xFEEDFACF:
            raise ValueError(f"not a 64-bit Mach-O at 0x{base:x} (magic {magic:#x})")
        self.ncmds = u("<I", buf, base + 16)[0]
        self.cmds = []
        off = base + 32
        for _ in range(self.ncmds):
            cmd, size = u("<II", buf, off)
            self.cmds.append((cmd, off, size))
            off += size

    def filesets(self):
        for cmd, off, _ in self.cmds:
            if cmd == LC_FILESET_ENTRY:
                vmaddr, fileoff, entry_id = u("<QQI", self.buf, off + 8)
                name = self.buf[off + entry_id:off + 256].split(b"\0")[0].decode()
                yield name, vmaddr, fileoff

    def segments(self):
        for cmd, off, _ in self.cmds:
            if cmd == LC_SEGMENT_64:
                name = self.buf[off + 8:off + 24].split(b"\0")[0].decode()
                vmaddr, vmsize, fileoff = u("<QQQ", self.buf, off + 24)
                yield name, vmaddr, vmsize, fileoff

    def symbols(self):
        for cmd, off, _ in self.cmds:
            if cmd != LC_SYMTAB:
                continue
            symoff, nsyms, stroff, _ = u("<IIII", self.buf, off + 8)
            for i in range(nsyms):
                n_strx, n_type, _, _, n_value = u("<IBBHQ", self.buf, symoff + i * 16)
                if not n_value:
                    continue
                name = self.buf[stroff + n_strx:self.buf.index(b"\0", stroff + n_strx)]
                yield name.decode(errors="replace"), n_value, n_type


ap = argparse.ArgumentParser()
ap.add_argument("kc")
ap.add_argument("--list", action="store_true")
ap.add_argument("--kext")
ap.add_argument("--grep")
a = ap.parse_args()

buf = open(a.kc, "rb").read()
top = MachO(buf)

if a.list:
    for name, vmaddr, fileoff in top.filesets():
        print(f"{vmaddr:#018x}  file+{fileoff:#010x}  {name}")
    sys.exit(0)

target = None
for name, vmaddr, fileoff in top.filesets():
    if a.kext in name:
        target = (name, vmaddr, fileoff)
        break
if not target:
    sys.exit(f"kext matching {a.kext!r} not found; try --list")

name, vmaddr, fileoff = target
print(f"# {name}  vmaddr={vmaddr:#x} fileoff={fileoff:#x}", file=sys.stderr)
mh = MachO(buf, fileoff)
for segname, sva, svs, _ in mh.segments():
    print(f"# seg {segname:<16} {sva:#018x} + {svs:#x}", file=sys.stderr)
n = 0
for sym, val, _ in mh.symbols():
    if a.grep and a.grep not in sym:
        continue
    print(f"{val:#018x}  {sym}")
    n += 1
print(f"# {n} symbols", file=sys.stderr)
