# macOS 26 code-family admission — candidate487, 2026-10-13

Inputs: signed Apple 26.6/25G72 and 26.7.1/25G241 installer assets. CPU-only
installation/inspection uses an independent copy of the tested 15.8 clone; the
original 15.8.1 user disk is retained for restoration. No macOS 26 GPU verdict yet.

The original catalog correctly refuses 19 of 163 sites on 25G241:

- Four short functions have unchanged bodies; their old 80-byte guards included
  unrelated following functions. Keep the entire target function instead:
  internal_cgs_write_register (37 bytes), internal_cgs_read_register (35),
  WriteIndirectRegister (43), AMDHardware::getHWChannel (38).
- Two interior sites retain the exact contract but move inside their owner:
  AMDGraphicsAccelerator::start cleanup branch and AMDHWVMContext::unmapVMPTE
  producer return. Scan uniquely within the named owner/end symbols. CPU proof
  verifies the end is the actual next function, refusing newly inserted functions
  that would silently widen the range. No root-relative address/delta is selected
  from an OS build label. A missing named boundary refuses admission.
- Thirteen typed function entries have audited alternate compiler code: boolean
  loads use bit-zero tests, counted loops simplify, registers/stack temporaries
  change. Object offsets and virtual-call slots remain exact. Boolean writes and
  requests remain canonical 0/1; these are not permission to mask native fields.
  The affected entries are commitLinkStatus, validateDetailedTiming, BatchPrepare,
  commitIntoGPUPageTable, setMemoryAllocationsEnabled, prepareVMInvalidateRequest,
  initializeHWEngines, powerUpHWEngines, powerOffHWEngines, startHWEngines,
  stopHWEngines, powerOff, and AMDNavi23Hardware::powerUp.

Legacy short entry guards accept a changed prologue only when the whole audited
alternate contract still matches at the discovered entry. Unknown fields/call
slots/operands remain rejected. Distinct target addresses across alternatives
are ambiguous and refused; all sites resolve before any patch in that image.

25G241 Metal's texture constructor already passes metadata-derived discovery.
Feedback's patch instruction is unchanged (TEST ESI; SETZ DL; OR DL,DIL); only
following compiler register/stack code differs. Its alternate long guard keeps
object offsets 0x45f0, 0x3618 and 0x3938 exact. The patch still clears only the
barrier-requested skip. All four VA guards pass unchanged. Streaming uses the
longest family overlap and deduplicates the same target address across patterns;
multiple distinct targets refuse.

Read-only checks pass all 163 kernel sites on 15.7.7/24G720, live 15.7.9/24G830,
15.8/24H23, live 15.8.1/24H32, 26.6/25G72, and 26.7.1/25G241: 978 checks. Real
26.7.1 MTL/VA images pass all six production userspace contracts, including
already-patched and native-layout mutation checks. Synthetic tests cover moved
owner-bound code, inserted/foreign functions, cross-family ambiguity and longer
streaming-boundary matches. Full host suite 1623 tests / 8 skips passes.

Regenerate reviewed catalogs with tools/kernel-sites.py and tools/user-sites.py.
No design digest, host identity, recovery, regression or pre-VFIO gate is relaxed.
These are compatible instruction families, not a promise about arbitrary future
private ABI rewrites. Hardware qualification and an update between two macOS 26
versions remain required before delivery is called complete.

Candidate488 adds the scoped common failed-start cleanup/false-return block
(reference key 0x1fd2) and computes near-JE displacement from the discovered
branch/cleanup addresses. The old six-byte displacement cannot be reused after
intra-function compiler shifts. Complete cleanup call, canary and return epilogue
are guarded; JE condition and signed range remain checked. All six real kernel
input sets pass 164 sites (984 checks); host suite 1624 / 8 skips passes.


Candidate489: remaining relocation guards
----------------------------------------
The candidate488 retry reached all164 sites and the corrected failed-start
cleanup branch, but hybrid entry admission still compared a baseline CALL
operand. `_ttlIsHwAvailable` calls `_ttlGetDev` at0x97bb4 in the baseline
and0x91010 in Tahoe; the catalog already verifies its complete code family
with only relocation operands masked. Candidate489 rechecks that complete
contract at the discovered target before routing, rather than comparing the
baseline displacement. The VCN shared allocation extension similarly builds
its replacement from current bytes and overlays only the audited size/domain
changes after full catalog verification; it preserves the native allocation
call displacement and requires exact replacement readback. Synthetic tests
cover relocation retention, native-field rejection and failure without writes.
No candidate489 hardware result is claimed by this source change.
