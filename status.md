# Live status — 2026-10-09

## Candidate353: full-refresh HiDPI improvement confirmed by same-image OFF baseline

Run `8b32ccd1e303a4b3fa845aaeded1d885`, metal-196, build1.0.353,
MODE2#292, bootba51b3c6. Native Metal/WindowServer/display pass; normal desktop
visible in actual virt-manager and viewer closure leaves VM alive. Same image,
SPICE60 and O2 presenter as352, but full-refresh property absent/OFF.

OFF native/HiDPI row copies4.04/16.38ms versus ON0.37/1.48ms. HiDPI manager
delivery OFF23.53/22.36 versus ON31.76/34.88 updates/s (full/ROI observers).
Native delivery has no uniform gain. QEMU CPU is lower ON in all four measured
cases; total host CPU is unmeasured. Producer draws vary and are below60/s,
so no GPU FPS,60Hz ceiling, atomicity or full desktop qualification claim.

Capture CORE_PROBE_PASS, earliest_failure=null. Outer shutdown:
exited-after-guest-request. Terminal absent: both EOF hooks (~0.316s) see PID113
stateZ with two tasks, completion_reason=not-sole-task. GPU recovery recovered,
authorizes_launch=true. VM/cycle stopped, host awake; no reboot/rebind needed.
Next354 adds early shutdown-event and bounded task-state diagnostics; no new grace.

Initial353 metadata failure occurred before QEMU/VFIO (MODE2#291, no ledger
launch); expanded identity was repaired and deep-validated before retry.
1189 host tests pass,8skip; kext/manifest match353. Milestone delivery to dev
pending; main unchanged. General desktop, lifecycle, window resize/input,
console audio/install durability and VirtualBox qualification remain open.
[Evidence](findings/research/bochs-full-refresh-paired-20261009.md) ·
[Paired data/receipts](findings/research/bochs-full-refresh-paired-evidence-20261009.json) ·
[Previous status](findings/research/status-archives/status-before-353-20261009.md).
