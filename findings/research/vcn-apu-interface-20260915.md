# Candidate235: VCN firmware SMU interface

Linux v6.12 vcn_v3_0_sw_init sets present_flag_0 bit11 and
smu_interface_info.smu_interface_type=2 specifically for VCN3.1.2.
Source: https://raw.githubusercontent.com/torvalds/linux/v6.12/drivers/gpu/drm/amd/amdgpu/vcn_v3_0.c
Layout: amdgpu_vcn.h at the same revision. Native alignment places the new field
at0x58 and structure end0x5c. Native Apple24G830 engine_hw_init allocates only0x58
bytes and writes the preceding log-size member at0x54; it has no SMU interface.
Do not overwrite0x54: that is firmware-log size, not the new field.

Opt-in rgpuvcnapu=1 extends the shared allocation to0x60 by replacing one51-byte
fully guarded instruction range atHWLibs0x878f5. It covers BOTH ctx+0x368 size
and allocator esi argument, preserving other bytes. Exact native bytes verified
against local24G830 Mach-O with segment translation. Native allocation, zeroing,
NC window size, and release use the recorded size; the enlarged allocation remains
native-owned. Complete replacement readback gates VCN HW initialization. Hook
already installed before patching; if replacement validation fails it returns
failure before native allocation executes. No unsupported success bypass.

After native vcn_hw_init succeeds, verify shared pointer/size, native IP0x30001,
and supplied firmware version04121015; set shared byte0x58=2 then bit11. This is
before first queue calls engine_initialize atHWLibs0x8844c. The old fields remain
intact. The initialized shared firmware interface will thus identify the Raphael
SMU interface to the supplied firmware. No new MMIO or reset path changes.

Hypothesis: firmware uses the wrong SMU protocol because the native older host
interface omits this field. Test exact allocation/field log and first encoder
frame output. Continued stall with verified field setup rejects this as sufficient.
No claim about desktop corruption; additional surface CPU and GPU readbacks pass
but actual menus remain unqualified. No hardware result for235 yet.
