# Independent encoder review — 2026-09-15

The hardware encoder remains unresolved. The evidence does not establish that
all driver paths are correct, that every useful intervention was tested, or that
a whole-core power failure is the definitive cause.

## Corrections to the prior conclusion

- The platform hook already sends real Raphael SMU PowerUpVcn6 through native
  CGS/BGM register transport. Candidate256/259/261 logs show version625300,
  response1. A successful response is not proof of physical completion, but
  this is not merely the dummy backend acknowledging without sending a command.
- DPG PGFSM wait expects2a2aaaaa (off state); its success is not a power-on proof.
  Candidate256 identifies the later failing wait precisely: DPG_PAUSE1:14,
  expected8/mask8, native caller94db1, result1. The preceding power-status wait
  succeeds. Native pause updates software state despite this failure; Linux's
  corresponding path also ignores that ACK wait return, so this alone is not a
  demonstrated Apple-specific cause.
- Candidate250 software loading used native direct-LMA initialization. It did
  not test software firmware plus a committed SRAM image. Candidate259 now did:
  native-owned512byte SRAM, correct early identity guard, software firmware at
  f40fa98000 rather than PSP firmware atf41f400000, secure committing initializer.
  Same pause failure. This rules out PSP firmware placement as the sole cause
  in that tested configuration; SRAM submission still uses PSP.
- Candidate257 adds Linux's pre-reset-release XX masks, unstall memory and
  register access settings. They execute but are insufficient.
- Decoder-first H264/HEVC sessions are rejected by VideoToolbox before VCN init:
  pinned-12906, automatic-12913. Software control completes3frames/maxlumaerror1.
  No decoder execution or startup-order falsification was established. Native
  queue type1 is decode and returns require_dpg_pause=0; type2 is JPEG. Do not
  mislabel the type2 exclusion in pause_dpg as the decoder mechanism.
- Candidate260 read selections returnedffffffff for all final SRAM entries
  after submit and after pause failure. The port may be inaccessible. Neither
  SRAM contents nor replay correctness was established by those sentinel reads.
- Earlier static runs retained hardware DPG_MODE although software selected the
  static initializer. Native static preservesbit2; Linux stop_dpg clears it.
  Candidate261 clears it:905->901, native static finishespower800. Encoder still
  stalls. Correction is insufficient, but the path was previously confounded.
- Candidate261 PGFSM power-on wait returns0 (success). Status00800000 masked
  by3f3fffff is0; the excluded field is JPEG. Other VCN registers are accessible.
  Selectiveffffffff cache/reset reads do not prove the entire VCN core is off.

## Evidence and independent outcomes

Artifacts below are under `/home/bogdan/macos-vm/run/`.

| Candidate | Main observation | Function | Cleanup |
|---|---|---|---|
|256|Exact native pause ACK timeout|Desktop passes; encoder stalls|Forced/recovered|
|257|Pre-release register image additions executed|Desktop passes; encoder stalls|Forced/recovered|
|258|Early identity guard rejected before VCPU init|No encoder hypothesis exercised|Forced; recovery INVALID missing XH2 ownership|
|259|Software firmware plus committed native-owned SRAM|Desktop passes; encoder stalls|Forced/recovered; next fresh MODE2 clears reset markers|
|259 attempt decodefirst|VT decoder API rejected before VCN initialization|Software decoder control passes|Guest-request exit/recovered|
|260 initial|Incorrect launch after failed host test; stopped before codec|Desktop passes; unqualified run|Guest-request exit/recovered|
|260 attempt readback|All selected LMA readsffffffff|Desktop passes; encoder stalls|Forced/recovered|
|261|DPG_MODE cleared; static PGFSM wait succeeds|Desktop passes; encoder stalls|Forced/recovered|
|262|PowerDownVcn5 and PowerUpVcn6 both reply1 with zero active queues|Desktop probe passes; encoder stalls|Capture loss, INVALID; forced/recovered|

Use each results directory's manifest/running-identity, serial.txt, probe.json,
codec-transcript.jsonl, shutdown.json, recovery.json and host-after.json. The
latest261 run isdff020605f965e42a43c9f4eba6fef0e, build7bd20b251b6a44d5b76b15a0f52fcbcc,
MODE2 #117 on bootc369c74e-96ff-4c21-ae85-80ccb269f7d2.
CORE_PROBE_PASS is the desktop workload result, not encoder qualification.

## Additional concrete supervision fix

The260 full suite exposed a temporary-directory cleanup race. Waiting for the
orphan fixture showed that SIGTERM raised RuntimeError inside startup loops
that catch Exception and retry. Change to SystemExit so the existing outer
BaseException handler records the failure and finally cleans up. The fixture
waits via pidfd for the orphan to finish before deleting files. Full cycle suite
passes after this correction (935 tests at261, three skipped).

## Remaining discriminating work

262 tests real SMU PowerDownVcn5 thenPowerUpVcn6 only for an unstarted engine
with zero active queues. Earlier hooks only sentPowerUp; graphics MODE2 receipts
do not independently prove that VCN underwent a complete domain cycle.

No local successful Linux hardware-encode artifact has been located. Requested
that baseline from the user; firmware presence or initialization is insufficient.
A paired Linux execution/MMIO trace would distinguish inaccessible registers
normal to this platform from an actual initialization mismatch. Host vfio->amdgpu
cycling is prohibited within the boot; this does not authorize rebinding/reboot.

Primary source comparisons: local exact24G830 HWLibs decompilation plus assembly;
Linuxvcn_v3_0.c,amdgpu_vcn.h,smu_v13_0_5_ppt.c and its PPSMC header. No merge/push.

## Capture publication correction after 262

Run `08bd239e28b2248d7cbc547957b45574`, build
`3f2e6162e3c84d0cacc494c315f56e71`, MODE2 #118: VCN cycle selected,
PowerDown reply 1, PowerUp reply 1, engine active queue count 0. Static mode
and power-on wait succeed; encoder accepts two frames and stalls on the third.
Offscreen/readback probe passes. Critical capture later fails; overall INVALID.
Recovery receipt says recovered and host-after shows no VM, vfio-pci, pinned.

`write_bytes_once` exposes the request filename before flushing its bytes, but
`sercat` treats empty/partial control records as fatal. Changed only control
request publication to write/fsync a temporary file, then exclusive hard-link
publication and directory fsync. Existing request cannot be overwritten. A
fixture verifies complete bytes at publication and collision refusal. Capture
errors now retain class and errno. This fixes a demonstrated source race;
causality for run262 is unconfirmed because its generic error discarded details.
Hardware validation of this publication correction remains outstanding.
