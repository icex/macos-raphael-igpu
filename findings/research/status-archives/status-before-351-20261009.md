# Live status — 2026-10-09

## Candidate350: copy timing localized; zombie terminal receipt still blocked

Run `1c54d03f095e5c8617423c7ebb17445b`, metal-193, build1.0.350,
MODE2#288, bootba51b3c6. Native Metal/WindowServer/display checks pass.
Normal Settings UI permission renewal succeeds for348's signed timing presenter;
no user keyboard intervention needed, no TCC DB/policy bypass. Real SCK timing
now works: selected steady HiDPI windows average3.446ms lock +16.074ms row copy;
native0.735+4.054ms. ROI moving samples48.482/16.267updates/s, both fixtures finish
and manager desktop returns. These are not GPU fps or a performance improvement.

Synthetic RAM copies pass. First1080p console attempt has54,537 bad pixels;
subsequent4K and1080p repeat pass all cases plus full independent QEMU pixel checks.
First mismatch unexplained; removing the VD with presenter is a topology confound.
Next retain VD independently and compare actual SCK→RAM/RAM→WC/directWC phases.

Capture CORE_PROBE_PASS, earliest_failure=null. Outer shutdown:
exited-after-guest-request. Native terminal absent: both hooks reject original
PID112 stateZ and immediately stop container; failed completion predicate unknown.
Add precise refusal diagnostics before altering wait behavior. GPU recovery:
recovered, authorizes_launch=true. VM/cycle stopped, host sleep:idle blocker active.
No reboot/rebind needed.347/348 reaped-process passes do not qualify zombie race.

1178 tests pass,8 skipped. Kext/manifest match350; candidate remains local.
Dev277ff81 hosted test/build green; main unchanged. Broader desktop, lifecycle,
automatic resize, atomic presentation and VirtualBox qualification remain open.
[Evidence](findings/research/console-source-copy-20261009.md) ·
[Hashes](findings/research/console-source-copy-evidence-20261009.json) ·
[Previous status](findings/research/status-archives/status-before-350-20261009.md).


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-351-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
