# Native MMHUB GART setup

Launch52 proves valid PSP firmware address in VCN context but no firmware-ready
status/output. GFXHUB CTX0 is enabled with GARTffbfa00..ffffe00; MMHUB CTX0 remains
reset-like, disabled with pages0..3ffff. VCN shared bufferffbfe52000 uses GART.

Exact HWLibs24G830 disassembly: VM10.3 hw_init33d8a calls MMHUB2.1 initializer3675b
at33ec5. That builder ignores the remapped discovery version and builds MMHUB2.0
segment0 offsets6c0/72b/etc. Existing X6000 VMM table repair does not affect this
HWLibs table allocated at vm+510. Native MMHUB2.3 builder36223 instead uses segment1
740/940..945, 8-dword context stride, a00-family invalidation and700/8ec families.
The mapping agrees with locally retained Linux mmhub2.3 headers used for Raphael.
Both builders take void(vm*) and populate only MMHUB slots in the same table; they
do not allocate, free, submit work, or change firmware authentication.

Candidate239 changes only the call at33ec5 to36223 under rgpummhub1 and target
identity. Guard includes preceding mov rdi,r14 plus complete target prologue.
Old call delta2891; new2359. Complete8-byte block readback, exclusive-end N+1 bound.
Native GART programming, read/write domains, defaults, teardown and errors retained.
This is not yet hardware validation. Falsifier: delivered call correction but
MMHUB CTX0 remains disabled/wrong range or VCN remains unready despite correct GART.
Inspect MMHUB state before starting codec; stop on first stall, preserve recovery.
Visible corruption remains unresolved independently.
