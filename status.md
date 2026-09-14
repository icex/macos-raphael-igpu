# Live status — 2026-09-15

Desktop corruption and hardware encoding remain broken; no full desktop qualification.
Worktree /home/bogdan/macos-vm/run/worktrees/candidate-239 (mmhub-native-initializer).
Latest launch53/cardmetal-085 run7d1e7f059d7e66444ba73bff0c975059,
build1796407bff064026af65b8df4080aa08, source4251420. Hostboot
c369c74e-96ff-4c21-ae85-80ccb269f7d2; prelaunch MODE2reset86.
Results /home/bogdan/macos-vm/run/candidate-239-results/.

## Latest run is not functional evidence

No desktop probe or encoder test. Native MMHUB2.3 call patch was skipped:
raphaelTargetConfirmed is not established at HWLibs load-time. No MHG log; source
condition accounts for skip, while actual build identity matches. Correct delivery
must validate target at native runtime without weakening existing identity checks.
Do not describe this run as testing MMHUB2.3 initialization.

Startup also produced repeated1000ms callback waits before firmware submission,
later PSP LOAD_ASD wire4 status7. TMR unload wire7, TOC32, SETUP_TMR5 and VCNwire13
succeeded. Earliest callback needs symbol identity before diagnosing reset cause.
No unsupported conclusion that MODE2 resets VCN or that host reboot is required.

Stopped using experiment.py verified SIGTERM handler (probe never reached hold).
Guest shutdown exited-after-guest-request, recovery recovered, overall INVALID.
VM stopped. Final MODE2reset87 confirms CP_STAT0/RLC_CNTL0, not VCN readiness.
Inhibitor active; vfio-pci retained; power/control on; no host reboot/new allowance.
Host927 tests/3skipped passed, build succeeds.

## Last functional evidence and next fix

Launch52 candidate238: Metal probe pass, H264 third submission hangs/no output;
VCN query and context both retain correct TMRf41f400000. All-ones code cache reads
therefore do not prove bad firmware placement. Native static FW-ready wait times out.
GFXHUB GARTCTX0 enabled/rangeffbfa00..ffffe00; MMHUB CTX0disabled/range0..3ffff.
VCN shared bufferffbfe52000 requires GART. HWLibs VM10.3 selects2.1 table builder
3675b, separate from X6000 paging table corrected in233. Native2.3 builder36223
has matching Raphael offsets and same void(vm*) ABI; guarded call correction
prepared but not delivered in239. See findings/research/mmhub-native-gart-20260915.md.

Visible corruption latest screenshot is launch50 before encoder use:
/home/bogdan/macos-vm/run/candidate-236-results/tigervnc-corruption.jpg.
Small12-case format/CPU/quad/sampling probes pass; no common cause established.
Software H264/HEVC small roundtrips pass; hardware HEVC remains unverified after fixes.
No merge/push to main. Prior detailed state archived under findings/research/status-archives/.
