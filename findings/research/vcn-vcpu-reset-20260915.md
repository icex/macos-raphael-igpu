# VCPU reset precondition

Launch55 proves correct GART and accepted PowerUpVcn6, yet firmware-ready wait
fails. Captured VCPU_CNTL0ff00200 has BLK_RST28 clear. Native static start930f8
only sets clock bit9 at931a1 and clears reset bit28 at9350b; it never asserts it.
MODE2 graphics/RLC receipts do not prove reset of this already-used VCPU.
Linux vcn_v3_0_start boot-failure retry asserts bit28, holds10ms, releases reset.

Candidate242 opt-in rgpuvcnreset1 intercepts native internal_cgs_write_register
8680f only for exact caller931ba/segment1/register156, native VCN30001/mode0,
static option and published target identity. Adds reset bit28 when native enables
clock, preserving all other value bits. Holds10ms and logs immediate/delayed
readback. Native code then programs caches and releases reset as before. Other
register writes/callers unchanged. Entire17-byte native prologue guard checked
against mapped MachO bytes; missing route refuses native initialization.
No reset after submissions or external host power/rebind/reboot action is added.
Falsifier: reset readback takes but firmware still not ready/no H264 output.
Do not infer firmware address wrong from protected cache register readback.
