# Candidate273 host crash and diagnostic removal

User reported host crash, followed by reboot to2508eb6d-ddf3-497d-9774-00a7ecebe3ed.
Prior run063833e5a790e948ed941f63fb1fd831,build08823221f09a46cdbbe1b394869048f1,
sourcebf3c544,MODE2 reset132 onbootc782d007-ca85-409b-9cf5-ff12c1a8c6d5.
Raw captures preserved in run/candidate-273-crash-20260916 with SHA256 manifest.

Observed: offscreen1000frames and24readback cases passed before failure. VCN context
creation and capability returned success; startEngine entry, no return. Last serial
line is VCNSR post-submit bytes288 valid-image1. No decoder-submit trace appears.
Final verdict/shutdown/recovery are absent. Pstore and systemd-pstore archive empty;
previous persistent host journal ends without panic/oops. Exact cause unproven.

Source immediately after the final serial line issues protected cache/reset/core
reads before printing VCNC. Diagnostic function inspectVcnSram itself writes LMA
selector addresses after PSP SRAM commit. Later VCNC/VCNMM/VCNSEG/VCNSCAN probes
read guarded only by arithmetic address range, not hardware accessibility. Earlier
comments calling these harmless/read-only were unjustified: MMIO reads can stall
and LMA selection is an actual hardware operation during dynamic power gating.
Working Linux already showed the sentinel values are inconclusive.

Candidate274 branches from272's validated DPM-capability correction, leaving273's
unqualified raw-wptr experiment out of this isolation. Remove LMA readback after
initialization/failed pause, protected cache/reset readbacks after writes, the
extra PGFSM diagnostic delay, and post-init core/segment sweeps. Preserve native
initialization, required waits, DPG/SMU work, queue ownership and ordinary context
metadata logging. Existing required AON status/pause reads remain.

This removes unnecessary diagnostic exposure; it does not prove the diagnostics
caused the crash or that codec execution works. Native Linux control on the new
boot precedes consideration of another macOS experiment. No auto-relaunch of273.
