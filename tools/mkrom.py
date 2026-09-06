#!/usr/bin/env python3
"""
Graft a PSP directory table and a vram_info table onto the Raphael APU ATOMBIOS so
Apple's AMDRadeonX6000Framebuffer Navi 2x path gets past
  AmdAtomPspDirectory::createPspDirectory  ASSERT(0 != tableOffset)
  AmdAtomVramInfo::createVramInfo          (vram_info master-data entry is 0)
  AmdAsicInfo::populateMemoryConfig        Invalid Memory Type from VBIOS: 0

Layout requirements were read out of the KDK 24G830 binary, not guessed:
  createPspDirectory : format_rev must be 2; content_rev 1 -> V2_1, table size 0x414,
                       entry count is a u32 at body+0x08, entries are 16 bytes from body+0x10.
  createVramInfo     : format_rev 2; content_rev 6 -> V2_6, table size 0x358,
                       module count u8 at +0x14 (<=0xf), modules at +0x18 stride 0x34,
                       memory_type at module+0x17, width = module[0x18] << module[0x19].
  populateMemoryConfig accepts any NON-ZERO type and width -- there is no enum check.
"""
import struct, sys, argparse

MDT_VRAM_INFO_INDEX = 28          # atom_master_list_of_data_tables_v2_1
MDT_PSP_DIR_INDEX   = 9           # 'sw_datatable9' -- Apple reads the PSP directory from HERE,
                                  # not from ATOM_ROM_HEADER.pspdirtableoffset, which it never loads.
ROM_HDR_PTR         = 0x48
CKSUM_OFF           = 0x21

ap = argparse.ArgumentParser()
ap.add_argument('-i', '--input',  default='igpu-vbios.rom')
ap.add_argument('-o', '--output', default='run/gpu-patched.rom')
ap.add_argument('--psp-entries', type=int, default=0, help='PSP directory entry count')
ap.add_argument('--mem-type',  type=lambda s:int(s,0), default=0x70, help='ATOM_DGPU_VRAM_TYPE (0x70=GDDR6)')
ap.add_argument('--chan-num',  type=int, default=8)
ap.add_argument('--chan-width',type=int, default=4, help='width = chan_num << chan_width')
ap.add_argument('--mem-size',  type=int, default=8192, help='per-module memory size')
ap.add_argument('--modules',   type=int, default=1)
ap.add_argument('--total',     type=lambda s:int(s,0), default=0xC000, help='final rom size (multiple of 512)')
a = ap.parse_args()

d = bytearray(open(a.input,'rb').read())
assert d[0]==0x55 and d[1]==0xAA, 'not a PCI option ROM'
old = d[2]*512
hdr = struct.unpack_from('<H', d, ROM_HDR_PTR)[0]
assert d[hdr+4:hdr+8] == b'ATOM'
mdt = struct.unpack_from('<H', d, hdr+0x20)[0]

# ---- build vram_info v2.6 (0x358) -------------------------------------------
VI_LEN = 0x358
vi = bytearray(VI_LEN)
struct.pack_into('<HBB', vi, 0, VI_LEN, 2, 6)      # structuresize, format_rev=2, content_rev=6
vi[0x14] = a.modules                                # vram_module_num
vi[0x15] = 0                                        # umcip_min_ver
vi[0x16] = 0                                        # umcip_max_ver
vi[0x17] = 1                                        # mc_phy_tile_num
for i in range(a.modules):
    m = 0x18 + i*0x34
    struct.pack_into('<I', vi, m+0x00, a.mem_size)  # memory_size
    struct.pack_into('<I', vi, m+0x04, 0xffffffff)  # channel_enable
    struct.pack_into('<I', vi, m+0x08, 1750*100)    # max_mem_clk
    vi[m+0x16] = i                                  # ext_memory_id
    vi[m+0x17] = a.mem_type                         # memory_type      <- read by Apple
    vi[m+0x18] = a.chan_num                         # channel_num      <- read by Apple
    vi[m+0x19] = a.chan_width                       # channel_width    <- read by Apple
    vi[m+0x1c] = 0                                  # vender_rev_id

# ---- build psp directory v2.1 (0x414) ---------------------------------------
PD_LEN = 0x414
pd = bytearray(PD_LEN)
struct.pack_into('<HBB', pd, 0, PD_LEN, 2, 1)      # structuresize, format_rev=2, content_rev=1
body = 4
pd[body+0:body+4] = b'$PSP'                         # magic (cosmetic for Apple, real for AMD)
struct.pack_into('<I', pd, body+0x08, a.psp_entries)   # num_entries  <- read by Apple
struct.pack_into('<I', pd, body+0x0c, 0)            # additional_info

# ---- append -----------------------------------------------------------------
def align(x, n=0x20): return (x + n - 1) & ~(n - 1)
vi_off = align(len(d))
d += b'\x00' * (vi_off - len(d)); d += vi
pd_off = align(len(d))
d += b'\x00' * (pd_off - len(d)); d += pd
assert len(d) <= a.total, f'grew past {a.total:#x}'
d += b'\x00' * (a.total - len(d))
assert vi_off < 0x10000 and pd_off < 0x10000, 'table offsets must fit u16 master-data-table entries'
assert a.total <= 0x10000, 'Apple caps the ATOM image at 64 KiB (validateAtomBiosImage: img[2] <= 128)'
assert pd_off + PD_LEN <= a.total and vi_off + VI_LEN <= a.total, 'table runs past the declared image size'

# ---- rewire -----------------------------------------------------------------
struct.pack_into('<H', d, mdt + 4 + MDT_VRAM_INFO_INDEX*2, vi_off)
struct.pack_into('<H', d, mdt + 4 + MDT_PSP_DIR_INDEX*2,   pd_off)
struct.pack_into('<I', d, hdr + 0x24, pd_off)        # cosmetic: real ROMs set it, Apple ignores it
d[2] = a.total // 512
d[CKSUM_OFF] = 0
d[CKSUM_OFF] = (256 - sum(d[:a.total]) % 256) % 256

open(a.output,'wb').write(bytes(d))
print(f"in  {a.input}: {old} bytes, rom hdr @{hdr:#x}, master data table @{mdt:#x}")
print(f"vram_info   -> {vi_off:#06x}  v2.6  modules={a.modules} type={a.mem_type:#04x} "
      f"width={a.chan_num<<a.chan_width} size={a.mem_size}")
print(f"psp dir     -> {pd_off:#06x}  v2.1  entries={a.psp_entries}")
print(f"out {a.output}: {len(d)} bytes, size byte={d[2]}, checksum byte={d[CKSUM_OFF]:#04x}, "
      f"sum%256={sum(d[:a.total])%256}")
