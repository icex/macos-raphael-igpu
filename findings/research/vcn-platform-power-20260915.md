# VCN platform power request

After native MMHUB GART correction in240, VCN still fails firmware-ready wait.
Linux vcn_v3_0_start calls amdgpu_dpm_enable_uvd(true) before static init; Raphael
smu_v13_0_5_dpm_set_vcn_enable sends PowerUpVcn6 with argument0. Current Apple
compatibility uses dummy SMU power backend, so this request is missing.

Candidate241 opt-in rgpuvcnsmu1 uses native VCN CGS interface callbacks to access
byte-addressed SMN registers. Exact24G830 callbacks: read9e5f1, write9e619. They
call IpiRead/WriteIndirectRegister a13fe/a13dc, BGM a3450/a3403. No Navi SMU IDs.
SMN transport addresses match existing tested MODE2 helper. Require original
Raphael target barrier, native interface function identities, VCN30001, signed
firmwareversion04121015. Query GetSmuVersion2 and require00625300 (host reset89)
before PowerUpVcn6/argument0. Pre-response must be1; bounded1s polling; error
refuses native VCN initialization. Serial records actual replies. Our mailbox
transactions are serialized; native dummy SMU backend sends no power messages.
Native VCN initialization still owns PGFSM/registers/PSP loading. No host power
command, power-down command, clock setting, firmware load bypass or forced success.
Tests cover exact writes/IDs, unreadable/busy pre-state, wrong version and command
failure. They establish protocol behavior only; native transport and effect require
hardware evidence. Falsifier: successful6 but VCN still fails firmware-ready/output.
Visible corruption remains independently unqualified.

Launch55: actual pre1/version625300/PowerUpVcn response1,error0. Native CGS
transport works; VCN firmware-ready timeout and third H264 submit stall persist.
This rejects the missing power request as sufficient. Forced shutdown/recovered,
finalMODE2reset91. No host reboot or additional host SMU power action.
