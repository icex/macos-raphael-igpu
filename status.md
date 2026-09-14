# Live status — 2026-09-15

Desktop corruption and hardware encoding remain unresolved. Worktree241 branch
vcn-platform-power at /home/bogdan/macos-vm/run/worktrees/candidate-241.
Launch55/cardmetal-087 rund0555e6ac091ce72f6c72546f6456edc, sourcece21694,
build16b9b1054a4449c4b90024a1a2dd28e3. Hostbootc369c74e-96ff-4c21-ae85-80ccb269f7d2,
prelaunchMODE2reset90. Guestboot479DFF77-82E5-447C-ACD5-AEF9E871C362,
registry4294968037. Results /home/bogdan/macos-vm/run/candidate-241-results/.

## Latest result

Native MMHUB2.3 table fix still delivered. Desktop Metal probe passes. Actual
native CGS indirect transport reports SMU pre1, GetSmuVersion625300,
PowerUpVcn6/arg0 response1,error0. This verifies transport/request, not readiness.
VCN static initializer still hits firmware-ready timeout, returns0. Query/context
firmware addressf41f400000 correct; code cache readsffffffff/ffffffff. H264 hardware
selected; frame0/1 accepted, third blocks/no output. No further encoder on stalled
state. PowerUpVcn alone is insufficient. No new MMHUB fault in capture.
Artifacts serial.txt, h264-hardware.jsonl, mmhub-vcn-after-h264.jsonl, probe.json.

## Verified repairs and visual limit

Native HWLibs MMHUB GART corrected in240, separate from X6000 paging table fix233:
CTX0 enabled1555481, physicalroot84fdfc001, rangeffbfa00..ffffe00. Original native
2.1 table addressed wrong registers; native2.3 selected after runtime identity.
Latest raw TigerVNC screenshot240 still shows diagonal green/purple Safari/menu
corruption before encoding. Format/CPU/quad/sampling/derivative probes pass small
12-case workloads; no actual desktop qualification/common cause proven.
Software H264/HEVC small roundtrips pass; hardware HEVC unverified after fixes.

## Cleanup

Stopped via interactive stop-requested. Shutdown forced, harness recovered. VM
stopped, finalMODE2reset91 CP_STAT0/RLC_CNTL0; no host reboot. vfio-pci retained,
power/control on, inhibitor active. SSH closed. Host928 tests/3skipped pass; build
succeeds. No new launch allowance; no merge/push to main.

## Next discriminating observation

VCN VCPU_CNTL already0ff00200 (reset bit28 clear) before recent static startup.
Native static initializer only ORs clock bit200 at931a1, programs caches, then
clears reset bit28 at9350b. Thus it assumes reset was asserted, although MODE2
receipts only prove graphics/RLC reset. Linux boot-failure retry explicitly asserts
VCPU reset before release. Audit/reset that boot precondition in native sequence;
do not assume a cold VCN or bypass firmware-ready failure. Source code and live
state justify this narrower test, not a host reboot. Superseded status archived.

## Candidate242 launch56 allowance

One launch56 on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2, fresh MODE2 via
tools/cycle.py, max6000s, all abort/recovery guards. Test VCPU reset assertion at
exact native static clock-enable before caches; actual bit28 readback required,
then firmware-ready and H264 frames. Further encoders only if healthy; stop on
first stall. Host928 tests/3skipped pass, build succeeds. Worktree242.
