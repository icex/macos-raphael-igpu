# Live status — 2026-09-15

Candidate 255 passed desktop probe but encoding stalled. Its log records the real
VCNM transport response: version=625300, power-response=1, error=0. The claim that
only a dummy function acknowledged PowerUpVcn is contradicted by this path.
Physical power-up and firmware execution remain unproven.

Candidate 256 adds bounded native register-wait diagnostics only. Distinguish
power-status wait from pause acknowledgment using exact caller/register/result.
No change to firmware loading or initialization writes.

## One-run allowance

One launch on boot c369c74e-96ff-4c21-ae85-80ccb269f7d2, candidate 1.0.256 /
metal-102, authorized by current user instruction to continue testing toward a
solution. Fresh MODE2 through tools/cycle.py, --manual-reuse --ack-risk,
max6000 seconds with all host/identity/capture/recovery aborts intact. Stop once
wait and codec result captured. Host checked: vfio-pci, power on, no QEMU.
No merge/push; prior candidate evidence preserved in archive.


## One-command GPU test

- Output: `/home/bogdan/macos-vm/run/candidate-256-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`

## Candidate 256 observed result

Run b0771f0e0ed3919fb4d6693553dc0461, build 6f6b79670013434c8eb74d08b61de7ab.
Desktop probe passed. Hardware H264 selected registry4294968043; two submissions
returned0, third stalled, no callback captured (pre-stop snapshot).
VCNW: PGFSM +93a3b passed; POWER_STATUS +94d68 passed; DPG_PAUSE +94db1
expected8/mask8 returned1 after timeout. This identifies the precise failed wait.
Real VCNM PowerUpVcn response1/version625300 again observed.
Stopped through harness stop-requested: forced shutdown, recovery recovered.
Artifacts /home/bogdan/macos-vm/run/candidate-256-results/. One-run allowance consumed.
Next: test Linux pre-reset-release SRAM register setup missing in Apple builder.
