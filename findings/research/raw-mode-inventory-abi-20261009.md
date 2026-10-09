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
