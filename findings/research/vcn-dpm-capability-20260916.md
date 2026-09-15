# VCN decode DPM capability mismatch

## Observation

Candidate271, run39c0d61758f19ada2d7db6ee73c7570e, exact24G830:
pre-context AMDGraphicsAccelerator::sendPMCommand caller+28d1d forwards header
16/00c00053, input128bytes, accel flags2, non-null display machine. Native result
e00002c7. Hardware decoder creation returns-12913, with no CreateVcnContext entry.
Software control validates3frames; offscreen desktop probe passes.

## Source

Our wrapPpPowerUp intentionally clears helper+28f8 to prevent unsupported native
PowerPlay initialization from aborting graphics startup. Native isSupported
requires this flag and PPlib pointer+68; isReady additionally requires28fa, set by
completeInit after successful powerUp sets28f9. Re-enabling flags is not a backend.
Framebuffer pppt handling checks readiness before dispatching lower-level PM.

Exact AMDVA UUID81DF7215-43E2-3BA1-BE2D-EFB1C508B81A:
- TEXT7ffb08606000,sizeb9000.
- VCNPowerManagement::isDpmSupported at7ffb086435f6 returns true unconditionally.
- VAVcnDecoder::setupPowerState at7ffb08649464 checks this virtual first. False
  destroys the PM object, nulls decoder+138, returns0. True sends setClocks then
  activates the PM client. Failure blocks createVcnContext.
- Init at7ffb08649110 zeros context scheduler/client fields before setupPowerState.
  Creation-failure PM deactivation checks the object pointer before calling.

## Candidate272 hypothesis

Align AMDVA's capability with intentionally unavailable Apple PowerPlay. Select
its native no-DPM path by changing only the AL immediate1→0 at TEXT+3d5fb.
The experiment is enabled only with XI bypass plus Raphael SMU and DPG options,
and delivered only after actual bypass execution. Do not fabricate PM response
success, set PPlib readiness, or change the SMU message protocol. Native kernel
VCN power-up remains responsible for the real Raphael SMU request.

Delivery uses current-task image inspection during native video getHWInfo (selector100),
requiring the exact terminated image path, UUID, text bounds, complete original
8-byte function, and executable read-only mapping. Copy-on-write changes one byte
on a private page, restores original protection even after failure, and verifies
all8bytes. The existing Metal target retains its own exact guards. Wrong identity
or bytes refuse the patch. Critical logs distinguish inspection and delivery.

Falsifier: confirmed delivery followed by the same pre-context clock request means
the proposed timing/call-path model is incomplete. Confirmed delivery and native
context/start entries establish passage of the earlier boundary, not working
hardware decode. Hardware decode requires callbacks, correct pixels and hardware
selection. Subsequent stalls must be analyzed separately, with normal cleanup.

No runtime result for272 yet. Host fixture/parser tests do not prove COW delivery,
VCN execution, display output or lifecycle reliability.

## Dispatch correction verified from exact Mach-O

Video contextStart assigns table1607a0 to+10e8. Table entries are48bytes;
selector100 contains virtual member ba1,104 bc1,106 bd1 (lowbit denotesvirtual).
Navi10VideoContext constructor installs vtable16c618: slotsba0→2892c getHWInfo,
bc0→49292 newContext,bd0→49632 startEngine. Thus prior shared CreateVcnContext
hook21ba0 does not cover the AMDVA decoder's selector104. Candidate272 additionally
traces49292 with native ABI self/input/output/input-size/output-size-pointer.
Its native requestCapability path remains covered by the existing engine hook.
The safe video HWInfo route is28935 after TEST RSI/JZ null guard at2892c; the
16-byte displaced prologue contains no branch/call/PC-relative instruction.
