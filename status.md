# Live status — 2026-10-09

## Candidate382: pre-guest topology abort; same-boot recovery completed

Run a41f7d1abac0b52f450eb624a55b307d, metal210,1.0.382,MODE2#306,
bootba51b3c6. VFIO exposure occurred; ledger entry is retained.
The manifest requested CONSOLE_VDAGENT=on, but observed QEMU agent_args was empty.
Identity validation aborted before guest output. Serial/critical captures are
empty, so no driver attachment, desktop, sound or port-open result exists.
Outer shutdown forced-after-abort; private terminal absent. This was not a clean
guest shutdown. Normal lease recovery failed because no producer was ready.

Cause: tools/vm-supervision.py start_locked forwards launch options through an
explicit systemd --setenv list; CONSOLE_VDAGENT was omitted. Launcher/container/
profile checks alone did not cover this boundary. The supervisor test double
inherited the parent environment and masked the missing explicit forwarding.
Next candidate must test the actual start_locked systemd command before exposure.

Stopped-device inspection found stable inactive queues. Supported MODE2/no-queue
recovery then completed: schema9,recovered,authorizes_launch=true, no kernel
faults, post-teardown queue errors empty. Original failed lease receipt retained.
Evidence: run/candidate-382-results, candidate-382-noqueue-inspection.json and
candidate-382-noqueue-recovery.json. No reboot or amdgpu rebind required; host
awake, vfio-pci, power/control=on. Commit this result before the next cycle.

1332 host tests pass,8skip; build/identity/dry-run and isolated TCG topology pass.
These checks did not qualify real systemd propagation. Guest probe remains unrun.
Last verified milestone remains381: pixel-matched1440p about57.5 observed IDs/s;
same4K source34.5–34.9 instead of14.4, audio retry/fallback/natural recovery pass.
Dev447131e has hosted37963569176 test/build green; main unchanged.
