Raphael userspace patch update-resilience audit (offline, 2026-09-14)

Scope
-----
Read-only review of the locally archived Sequoia 24G830 x86_64h Metal driver
segment. No guest, VM, project, or hardware changes were made. The main local
artifact is `/tmp/claude-1000/-home-bogdan-src-macos-raphael-igpu/015b73f8-2b58-4b71-acd8-e47ac36b2820/scratchpad/re/mtl__TEXT.bin`
(5,253,550 bytes, SHA-256 `edea49f14138e3d017dd4e910db94ef19fcb708b3f31e178c208706a7b5da88d`).

Findings
--------

1. The current bit identity has an independent semantic anchor. The driver’s
   `__objc_methtype` encoding at segment offset `0x4d7ea1` contains
   `AMD_DeviceSettings`, with contiguous one-bit fields. Counting from
   `allowVRAM` at bit 0, `enableTexturePipeBankXor` is bit 27. This independently
   confirms the patched immediate’s bit 27 and does not depend on the current
   UUID or instruction offset. The name string also occurs at `0x3b236e`.

2. The settings-name constructor/reader is locatable by a name cluster. In the
   current segment, a long run of RIP-relative `lea` + common helper calls starts
   near `0x10d6c0`; the unique references are:
   `enableTexturePipeBankXor` at `0x10d7d9`, adjacent
   `enableBlitDMA` at `0x10d7eb`, and `enableLinearMSAABlit` at `0x10d863`.
   An update locator can search for the strings, require the repeated helper-call
   shape and nearby neighboring setting names, and reject isolated string hits.
   This identifies the settings-processing region without hard-coding its address.

3. The routine beginning at `0x13a700` is a useful structural anchor, but its
   arguments must not be misidentified. `rdi` is the settings/output object;
   `rsi` is a hardware-info input. The `[rsi+0xa0]` read is a hardware
   capability word, not the settings object. The routine stores the constructed
   settings value through `[rdi]`; it later emits the immediate `0x1ff700000`
   at `0x13a7e1`. This is a consumer/constructor relationship useful for
   cross-checking the patch site, but `rsi+0xa0` must not be used as a settings
   field offset.

4. The metadata encoding gives the bit number, but not the runtime byte offset
   of the C++/C settings object. It is not sufficient by itself to compute a
   live address after an update. The settings-object field location must be
   recovered from constructor stores or true settings consumers, then checked
   against the metadata bit index. Do not infer it from the unrelated hardware
   capability word at `rsi+0xa0`.

Recommended update locator
--------------------------
Use a staged, fail-closed locator:

* Identify `AMD_DeviceSettings` in `__objc_methtype`; parse the ordered `b1`
  fields to obtain the target bit index from the field name.
* Find `enableTexturePipeBankXor`, `enableBlitDMA`, and
  `enableLinearMSAABlit`; require their RIP-relative references to occur in a
  bounded cluster of repeated setting-helper calls. This identifies the
  settings code semantically.
* Independently scan executable sections for a bounded constructor or consumer
  window that accesses the settings/output object, extracts the
  metadata-derived bit, and stores or consumes it. Use that to recover the
  field byte offset and validate the current value/role; do not treat the
  hardware-info `rsi+0xa0` access as such evidence.
* Within the same consumer, locate the `movabs`/immediate or equivalent
  constant that contains the target descriptor bit. Patch only when the
  consumer has the expected read/merge/store dataflow, the target bit is set,
  and there is exactly one candidate. Otherwise leave the process untouched.
* Keep UUID/path checks as provenance and compatibility checks, but treat them
  as rejection guards rather than the locator itself. Verify the live bytes
  immediately before patching and make a per-process no-op on any ambiguity.

Limits
------
No second OS-version driver/cache is present locally, so cross-version
stability cannot be demonstrated. The current artifact is a raw/reconstructed
segment rather than a complete loadable Mach-O; the offsets above are evidence
for this exact 24G830 image. Future compiler changes may alter instruction
forms, field packing, or the settings consumer. The semantic locator must be
tested against each new cache and should never fall back to the old offset.

Prototype locator audit
-----------------------
`/home/bogdan/macos-vm/run/update-resilience-20260914/locate_texture_setting.py`
and its 11 checks pass: one real image plus synthetic UUID, immediate, metadata,
movement, ambiguity, dataflow, section, and truncation mutations. This is useful
fail-closed structural validation, not cross-version proof. In particular, the
prototype derives the bit number from metadata and finds a unique constructor-like
`movabs`/`or`/store window, but it does not establish full semantic dataflow from
the named setting through the settings constructor to that immediate. The
`metadata-bit-layout-shift` synthetic check proves it follows metadata bit order;
it does not prove a future binary preserves the same field-to-consumer relation.
The real-image check is therefore a locator result for 24G830 only, with no
deployment recommendation by itself.
