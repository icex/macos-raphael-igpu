# Live status — 2026-09-15

Candidate257 executed Linux pre-release SRAM setup but still timed out at pause
acknowledgment +94db1; PGFSM/power waits passed. Desktop probe passed. Artifacts:
/home/bogdan/macos-vm/run/candidate-257-results/. Cleanup receipt checked before launch.

Candidate259 tests software firmware placement + committing SRAM, a combination
not covered by250 (direct LMA). Native mode1 supplies firmware; allocate missing
512-byte SRAM via audited native allocator, keep its ownership/cleanup fields,
and select secure committing initializer. PSP still commits SRAM; it no longer
places the firmware. Preserve257 pre-release setup and256 wait observer.

## One-run allowance
One launch candidate1.0.259 / metal-105 on boot
c369c74e-96ff-4c21-ae85-80ccb269f7d2 under current user instruction to continue
working/testing toward a solution. Fresh MODE2 through cycle.py, manual-reuse /
ack-risk, max6000seconds, existing host/identity/capture/recovery aborts intact.
Stop on encoded output or first stall. Host must remain vfio-pci/pinned awake.
No merge/push. Record outcomes after this run.

Candidate258 failed before testing software placement: its guard used the later
VMM target-publication flag at early HW init. Candidate259 uses the audited early
GC-discovery/unique-PCI-marker check. Fixture keeps the late flag false and checks
missing-marker refusal. Candidate258 is not evidence of firmware execution failure.

258 cleanup: forced via supervision; harness recovery failed because early VCN
HW-init refusal prevented XH2 lease publication. VM stopped, vfio-pci/pinned.
259 requires fresh MODE2 CP_STAT=0/RLC_CNTL=0 before staging; normal cycle gates
remain intact. Prior invalid run is not a firmware-path result.
