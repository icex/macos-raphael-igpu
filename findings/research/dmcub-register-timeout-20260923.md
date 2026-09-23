# Retained DMCUB register timeout, 2026-09-23

After 307 retry, host capture in `~/macos-vm/run/c307-retained-dmcub-state/`
read CW4/5/6 twice through MM_INDEX with selectors restored. All bytes matched
between snapshots. Trace contains 367 entries; last entry code34/param2. Its
private enum is not decoded, so do not assign it a power-state meaning.

FW-state at CW6+0x580 includes repeated tuples 14/60039b07/5ecf. These initially
looked like an exception record, but installed firmware disassembly instead
connects them to register-interface timeout reporting. **Do not report Xtensa
exception 14 from this tuple.** Generic exception enum14 is not evidence for
this private structure's meaning.

Installed `dcn_3_1_5_dmcub.bin.zst`, uncompressed SHA in the existing code-reference
JSON, version05003500: code starts file512, linked at60000000. Capstone6 Xtensa
provides partial disassembly; unsupported instructions are not silently decoded.

- 60034208 reads the RBBMIF_INT_STATUS fields via generic register-get helper
  60039b04. Constant60008354 points to60006bd0; its field20c contains5ffcd908,
  register3642. 60034255..60034271 writes `(saved_mask <<31)|40000000`, then
  `(saved_mask <<31)`, i.e. timeout ACK pulse preserving mask.
- 60034278 writes its two arguments via the register table600045d0 fieldsb0/b8,
  which resolve to SCRATCH13/SCRATCH15. Caller60020c10 passes the record's
  PC and 16-bit register index. Register5ecf resolves to
  DCIO_UNIPHY1_UNIPHY_MACRO_CNTL_RESERVED15; 60039b07 is in generic register-get.
- Captured scratch12=80000000, scratch13=60039b07, scratch14=80, scratch15=5ecf.
  Scratch12 bit31 is also set by firmware6002f94c..6002f955; it is not enough
  to identify an exception, instruction fault, or safe firmware restart.

Live RBBMIF_INT_STATUS=b000e808, CLIENTS_DEC=8: timeout address3a02
(DCHUBBUB_TEST_DEBUG_DATA), OP=1, RDWR_STATUS=1, MASK=1. This current timeout
is distinct from the retained UNIPHY report. Some diagnostic reads can themselves
set register-interface error flags; capture is not proof of the original cause.

308 tests exactly one source-backed timeout acknowledgement before its first
GPINT query, only for version05003500 and one of the two recorded addresses.
It preserves MASK and does not touch DMCUB enable/reset, firmware bytes, IRQ
controls, scratch registers or ring pointers. Hypothesis: an unacknowledged
register-interface timeout prevents mailbox progress. GPINT still timing out
after a successful ACK rejects the ACK as a sufficient remedy.

308 result: ACK readback c0000000 then80000000, clients cleared from8 to0.
GPINT still times out. This rejects acknowledgement alone as sufficient, without
establishing what originally caused the retained PHY timeout. CORE_PROBE_PASS,
clean shutdown, ordinary recovery authorizes reuse.
