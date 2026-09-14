# Candidate237: native VCN static initialization

Launch50 delivered firmware/shared-SMU field correctly but first-submit captures
already showed POWER_STATUS905 and gated registersdeadbeef before codec request.
H264 first queue stalls. This is a power/wake-path observation, not proof of the
exact missing SMU message. Apple uses dummy SMU backend in this project; Linux
smu_v13_0_5_dpm_set_vcn_enable sends PowerUpVcn/PowerDownVcn param0.

Native registry mapping at24G830 HWLibs0x50fae0 stride0x108 identifies indices:
0 EnableVCNDPG default1;1 PP_EnableVCNPG default1;3 EnableSwVCNFWLoading default0;
7 EnableVCNSecureLoad default1. engine_sw_init packs flags: index0->bit1,
index1->bit3,index7->bit9. Mode3=0 retains PSP image loading. Under mode0,
engine_init_pfn_ptr chooses secure-DPG on bit9, otherwise static initialization.

rgpuvcnstatic=1 returns0 for only indices0/1/7 on engine internal IP0x30001.
All other native settings and results retained. This chooses native
_engine_3_0_static_initialize0x930f8, not a success stub. Its disable_power_gating
uses PGFSM_CONFIG15155555, waits PGFSM_STATUS0, clears POWER_STATUS103 when PG
is disabled; Linux v6.12 vcn_v3_0_disable_static_power_gating has the same optional
no-PG path. Actual startup and firmware command acceptance are untested.

Hook _engine_initialize logs selected native function and actual return without
changing it. Both route entry preimages verified from exact local Mach-O, complete
prologue instructions. No new raw MMIO or host power transition. Native firmware
mode remains0 and native PSP verification/loading remains in place.

Hypothesis: native automatic power gating prevents the VCN queue from starting.
Test actual selected static initializer/result, powered registers before encode,
and completed frame callbacks. Continued stall with live registers rejects static
initialization as sufficient. Corruption remains a separate unresolved requirement.
