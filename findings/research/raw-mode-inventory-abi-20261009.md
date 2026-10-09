# Read-only raw mode inventory ABI

The diagnostic tests/console_raw_modes_probe.m is restricted to the unique online
Raphael vendor0x5250/model0x3453 display with expected ID4128836. It has a10-second
alarm and256-record/54,272-byte caller buffer; no selection, configuration or cache
mutation. Native compilation/execution remains root-owned and pending.

Local decoded24G830 source under
`/home/bogdan/macos-vm/re/roadmap-24G830/SkyLight-full/functions/`:

- `7ff807e03c6b__SLSGetNumberOfDisplayModes.c`: signature display uint32/count
  uint32 pointer; returns status and writes current system-state mode count.
- `7ff807e03ff1__SLSGetDisplayModeDescriptionsOfLength.asm:16–19`: saves ECX
  record length, RDX count pointer, RSI buffer, EDI displayID. The C export
  lines9–10 corroborates that four-argument signature. It bounds copied records
  by supplied count, resets/writes count, uses native stride0xd4 and copies
  min(caller-record-length,0xd4). It may internally allocate the server's mode
  count; the caller's cap is not a proof of bounded private-library allocation.
- `7ff807b46d3f__initDisplayModeList.c`: its own caller allocates count×0xd4 and
  passes0xd4; it filters IOFlags0x1080 and additional validity/duplicate conditions
  before building the public cached array.
- `7ff807b47295__CGSCreateModeDictFromDescription.c:80–118`: logical width/height
  words2/3, mode number word0, IOFlags word0x30(offset0xc0), IODisplayModeID word0x31,
  pixels words0x32/0x33, resolution float word0x34. Probe retains every raw byte
  and both IDs, avoiding guessed flag names beyond these observed filter masks.
- `7ff807e67b14__SLDisplayCopyAllDisplayModes.c`: the duplicate-mode option returns
  the full cached array, already filtered by initDisplayModeList. The existing
  public duplicate option therefore does not necessarily expose every raw mode.

Compare raw absent-public modes13/18/20 with visible21 to discriminate creation
failure from public-list filtering. Availability of3840×2304 already contradicts
a simple monotonic maximum-size explanation. Serial reuse/cache persistence is
not established by this source; no serial or cache changes are proposed here.

## Native raw evidence and preferred configuration correction

`run/c390-raw-modes.txt` contains raw valid1x IDs13/18/20, flags3, at
2880×1800/3360×2100/3840×2160. Matching2x descriptors36/37/40 have flags0x200002
without the validity bit. Native-flag4 belongs to first advertised2048×1536 mode1.
The decoded initDisplayModeList comparison scans all raw matching2x entries,
not just valid entries; it suppresses those larger-than-native1x modes. Public
duplicate-mode options act after this filter.3840×2304 survives without a matching
2x descriptor, arguing against a simple size limit.

CoreGraphics applySettings and CoreDisplay VirtualDisplayProxy applyProxySettings
serialize/iterate supplied modes in order. The first/native correspondence is
native evidence, not a proven general private-SPI ordering guarantee. The minimal
public-path experiment moves the existing3840×2304 default to the front ONLY at
scale1, retaining all entries and descriptor bounds. Scale2 and custom tables are
unchanged. Root must verify raw native flags, public4K visibility, and ordinary
public mode selection after native installation.

A separately prepared raw configuration diagnostic is **not the preferred path**
and must not be run while this mode-table correction is being qualified. Its ABI
is source-proven: SLConfigureDisplayWithDisplayMode checks public membership then
passes a mode number to SLSConfigureDisplayMode; callee assembly7ff807e04f30 saves
RDI(config),ESI(display),EDX(mode), returns status EAX. Constructing a synthetic
CGDisplayMode would still hit public membership validation. No private mutating
probe, binary patch, cache purge, or serial change has been executed here.
