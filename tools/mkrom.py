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
MDT_DISPLAY_OBJECT_INDEX = 22     # displayobjectinfo. NOT 16 -- getting this index wrong once
                                  # produced the entirely false conclusion that this VBIOS has
                                  # no display object info table at all.
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
ap.add_argument('--keep-dead-display-paths', action='store_true',
                help='do NOT drop display paths whose device_tag is 0 (see fix below)')
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

# ---- drop display paths with device_tag == 0 --------------------------------
#
# Apple's framebuffer kext refuses a path with no device tag:
#
#   ATOM: AmdAtomObjectInfo_V1_4::populateConnectorEntry(atom_display_object_path_v2 *,
#         AtomConnectorEntry &) const: ASSERT(0 != object->device_tag)
#
# and then every AmdRadeonFramebuffer reports "Driver is offline", so nothing reaches a
# screen -- not the emulated display, not a monitor physically attached to the iGPU.
#
# This VBIOS declares six paths, and they match amdgpu's connector list exactly:
#
#   path[0] objid 0x340c HDMI_TYPE_A enum 4  device_tag 0x0400 DFP3  -> amdgpu HDMI-A-3
#   path[1] objid 0x0000 (empty)             device_tag 0x0000       -> nothing
#   path[2] objid 0x3113 DISPLAYPORT enum 1  device_tag 0x0008 DFP1  -> amdgpu DP-3
#   path[3] objid 0x3213 DISPLAYPORT enum 2  device_tag 0x0080 DFP6  -> amdgpu DP-4
#   path[4] objid 0x3313 DISPLAYPORT enum 3  device_tag 0x0200 CV2   -> amdgpu DP-5
#   path[5] objid 0x7103 type 7              device_tag 0x0000       -> amdgpu Writeback-2
#
# supporteddevices is 0x0688 = 0x008|0x080|0x200|0x400, i.e. exactly the four real tags, so
# the firmware itself does not count the two tagless entries as devices. amdgpu tolerates
# them; Apple asserts on them. Dropping them leaves the four real connectors.
#
# The path array is compacted in place and number_of_path reduced. Everything after the
# array -- the display and encoder records -- is left exactly where it is, because the
# offsets inside each path entry point at those records absolutely; moving whole 16-byte
# entries keeps those references valid, and the few bytes freed at the end of the array
# simply go unused.
if not a.keep_dead_display_paths:
    do = struct.unpack_from('<H', d, mdt + 4 + MDT_DISPLAY_OBJECT_INDEX*2)[0]
    assert do, 'displayobjectinfo master-data entry is 0 -- wrong index, or a different VBIOS'
    _, dfmt, dcont = struct.unpack_from('<HBB', d, do)
    assert (dfmt, dcont) == (1, 4), f'expected display_object_info v1.4, got v{dfmt}.{dcont}'
    supported, npath = struct.unpack_from('<HB', d, do + 4)
    PATH_LEN = 16                 # sizeof(atom_display_object_path_v2): 7 u16 + 2 u8
    kept, dropped, tags = [], [], 0
    for i in range(npath):
        e = do + 8 + i*PATH_LEN
        entry = bytes(d[e:e+PATH_LEN])
        objid, devtag = struct.unpack_from('<H', entry, 0)[0], struct.unpack_from('<H', entry, 12)[0]
        (kept if devtag else dropped).append((i, objid, devtag, entry))
        if devtag: tags |= devtag
    assert kept, 'every display path has device_tag 0 -- refusing to leave an empty table, ' \
                 'Apple also asserts ASSERT(0 != connectorCount)'
    for n, (_, _, _, entry) in enumerate(kept):
        d[do + 8 + n*PATH_LEN : do + 8 + (n+1)*PATH_LEN] = entry
    d[do + 6] = len(kept)                                  # number_of_path
    struct.pack_into('<H', d, do + 4, tags)                # supporteddevices
    disp_note = (f"display paths -> {do:#06x}  kept {len(kept)}/{npath} "
                 f"(dropped {', '.join(f'path[{i}] objid={o:#06x}' for i,o,_,_ in dropped) or 'none'}), "
                 f"supporteddevices {supported:#06x} -> {tags:#06x}")
else:
    disp_note = 'display paths -> left alone (--keep-dead-display-paths)'

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
print(disp_note)
print(f"out {a.output}: {len(d)} bytes, size byte={d[2]}, checksum byte={d[CKSUM_OFF]:#04x}, "
      f"sum%256={sum(d[:a.total])%256}")
