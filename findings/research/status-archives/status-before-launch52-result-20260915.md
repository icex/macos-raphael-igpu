# Live status — 2026-09-15

Full desktop acceleration is not qualified. Visible TigerVNC corruption persists
before encoder use; hardware H264 stalls without output. HEVC hardware is not yet
retested after these changes. Small software H264/HEVC round trips pass.

Worktree: /home/bogdan/macos-vm/run/worktrees/candidate-237 (vcn-static-init).
Source build commit0409db2; build e217de9d579b48668b6c3a9c70eea623.
Launch51/cardmetal-083 run aaffa25897eb5cf086b488a8b64e399a on host boot
c369c74e-96ff-4c21-ae85-80ccb269f7d2, prelaunch MODE2 reset82.
Results: /home/bogdan/macos-vm/run/candidate-237-results/.

## Function and identity

Native static VCN initializer930f8 actually executes with flags144 and mode0
(PSP firmware authentication retained). Shared allocation96/SMU-interface2.
Desktop Metal probe passes. H264 third submission stalls, no output callbacks;
other graphics, SDMA and VMPT timestamps complete. No further codec tested on
stalled engine. Native initializer returns0 despite an internal50ms wait timeout.
First-submit and +2s MMIO show VCN awake (POWER_STATUS804), ring WPTR20/RPTR0,
firmware cache BAR823c/d bothffffffff. PSP transcript previously records successful
wireType13 load to TMRf41f400000. Native static code writes engine context+2c0 to
those registers; actual context/query values have not yet been captured. Therefore
an invalid firmware placement is a hypothesis, not yet a proven query bug.
Artifacts: serial.txt, h264-hardware.jsonl, mmhub-vcn-at-first-submit.jsonl,
mmhub-vcn-two-seconds.jsonl, running-identity.json, probe.json.

## Visible corruption

Launch50 raw Linux TigerVNC screenshot still shows diagonal green/purple Safari
and menu corruption BEFORE encoder use:
/run/candidate-236-results/tigervnc-corruption.jpg under /home/bogdan/macos-vm.
Format/IOSurface CPU comparisons, two-triangle and interpolated sampling probes
pass their12 small cases each; these do not qualify WindowServer/Safari rendering.
A common cause with VCN is not established.

## Cleanup and host

Launch51 stopped through interactive stop-requested. Shutdown forced (not clean
guest shutdown); harness recovery recovered. VM container is stopped. Final MODE2
reset83 receipt confirms CP_STAT0/RLC_CNTL0. Host boot unchanged, vfio-pci retained,
power/control on; no host kernel fault in run capture. Inhibitor remains active.
No new launch allowance. No host reboot; no vfio-to-amdgpu cycling.

## Next discriminating work

Trace native PSP firmware-status response through CGS into context+2c0 and cache
register writes. Do not substitute a cached diagnostic address or assume that an
all-ones register read proves the context itself is all ones. Then validate actual
encoded frames before testing further codecs. Separately reproduce desktop
corruption with a workload matching the visible Safari/WindowServer artifact.
Host suite927 tests/3 skipped passed before launch51. No merge/push to main.

Superseded state is archived in findings/research/status-archives/
status-before-launch51-result-20260915.md.

## Candidate238 launch52 allowance

One launch52 on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2, fresh MODE2 via
tools/cycle.py, max6000s with all abort/cleanup guards. Same workload as51, native
VCN query and post-init context read-only trace. A valid context address falsifies
bad firmware query as cause of all-ones cache readback. Stop on first H264 stall.
Work continues in /home/bogdan/macos-vm/run/worktrees/candidate-238.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-238-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
