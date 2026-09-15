# Live status — 2026-09-15

## Encoder unresolved; latest run INVALID
Candidate 262, run 08bd239e28b2248d7cbc547957b45574, build
3f2e6162e3c84d0cacc494c315f56e71, MODE2 #118 on boot
c369c74e-96ff-4c21-ae85-80ccb269f7d2. Before exposure, full host suite passed
(935 tests, three skipped). Correct accelerator 4294968047, codec PID 852.
VCNCYCLE selected=1, active-queues=0, PowerDownVcn5 response=1, PowerUpVcn6
response=1. Static POWER_STATUS=800, PGFSM power-on wait succeeds. H264 frames
0/1 accepted; frame2 stalled. No encoded output. Successful SMU replies do not
prove a physical domain transition. This intervention did not solve encoding.

Desktop probe passed 1000 offscreen frames and all 24 readback cases. During
shutdown critical capture exited with generic `serial capture failed`; harness
marked INVALID/capture_loss and forced the VM off. Recovery recovered;
host-after VM=false, vfio-pci, device pinned awake. No host rebind or reboot.
Results: /home/bogdan/macos-vm/run/candidate-262-results, including service journal.
Allowance consumed. No further launch authorized by this status entry.

## Capture correction awaiting hardware validation
Found request publication race: write_bytes_once creates the final request path
before buffered bytes are flushed, while sercat rejects an empty/partial request.
This is consistent with the failure but not proven causal: the prior collector
lost the exception type. Request now publishes durable complete bytes via an
exclusive hard link; strict request validation and fatal capture stop remain.
Collector now reports exception class/errno. Full regression suite passes after correction: 936 tests, three skipped.

## Independent review
See findings/research/encoder-independent-review-20260915.md. Prior conclusions
about an exhaustive driver audit, successful SRAM replay, and whole-core power
failure exceed available evidence. Static DPG-mode mismatch was corrected and
SMU power cycle tested without encoder success. Software firmware plus committed
SRAM also failed. Hardware decoder API rejected before VCN init, so decoder-first
startup remains unexercised. Requested actual Linux hardware-encode baseline;
no successful local Linux encode artifact located. No merge or push.
