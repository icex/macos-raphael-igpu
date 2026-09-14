# Reboot-free reset and TigerVNC audit — 2026-09-14

The initial reboot recommendation was premature and is retracted. The host remains on boot
`c369c74e-96ff-4c21-ae85-80ccb269f7d2`. The retained candidate230 repeat host snapshot
(`run/candidate-230-attempt-repeat-results/host-before.json`, SHA-256
`65a797408ef6c06a2edcdb45d8422876009e5883437138c3ec2e4c50d9603af6`) recorded successful
amdgpu initialization before journal rotation. The coordinator now validates this exact
snapshot against live host identity; a fresh MODE2 reset is still required separately.

All run paths below are relative to `/home/bogdan/macos-vm/`.

| Launch | Run id | Reset | Results |
|---|---|---|---|
| 41 | `4aff2d26b7fe53a1a91428c00e5d54c3` | 65 | `run/candidate-230-attempt-tigervnc-results/` |
| 42 | `7557ae12fd712a5043d7c249b2503628` | 66 | `run/candidate-230-attempt-tigervnc-restored-results/` |
| 43 | `28acce9ab6009fc2d1afeee9219cec6f` | 67 | `run/candidate-230-attempt-tigervnc-only-results/` |

The kext executable/build stayed identical to candidate230's successful repeat. Run 41's
`running-identity.json` equals that repeat's record in every field, including QEMU argv hash.
Functional boot arguments match; only run nonces change. The `XTCOW p=0 w=0 r=0 v=0`
records indicate KERN_SUCCESS for all four operations, not failed verification.

## Independent outcomes

**Function:** none of the three desktop probes completed; `probe.json` records transport exit
1 and no guest-agent response. Run 41 authenticated over TigerVNC after correcting the stale
helper-script account, but Screen Sharing reported no active display dimensions. Run 42's
`display-log.txt` explicitly records `good authentication`; no usable desktop followed.
Run 43 failed before any viewer connection. Its `pre-viewer-observation.txt` and
`vnc-sockets-at-failure.txt` establish that control condition.

**Observation/identity:** exact build and running topology were captured. In run 41,
`windowserver.sample.txt` shows the main thread in Metal command-buffer shared-memory creation
through IOConnectCallMethod. Serial channel dumps show pending SDMA/VMPT work, including
video-encoder clients; graphics ring RPTR/WPTR are equal in the captured snapshots. This is
not sufficient to identify the first causative packet. Run 43's `guest-state.txt` still shows
VTEncoderXPCService blocked without a Screen Sharing process or connected viewer. The
concurrent-viewer hypothesis is therefore insufficient and is not retained as a diagnosis.

**Guest state restoration:** run 41's `display-restore.txt` proves the original global and
user ByHost WindowServer files were restored, with SHA-256 values `361f982d…` and `4ad8e580…`
respectively and preserved ownership. The backup directory was retained. Run 42 confirms
both destinations exist. No unverified Screen Sharing preference preimage was invented.

**Cleanup:** all three guests stopped via the existing harness path and reported `forced`.
Each harness recovery receipt reports `incomplete`. The host remained reachable and on
vfio-pci with power pinned on. Final MODE2 receipt `run/mode2-reset-68.json` confirms
CP_STAT=0 and RLC_CNTL=0 after run 43; this is a successful documented reset, not a clean
macOS shutdown or proof that every engine's future workload is qualified.

**Qualification:** INCONCLUSIVE / probe_completion_missing for all three. Historical passing
copy matrices remain valid historical evidence, but the present desktop is not qualified.

## Next observation

Identify the initiator of VTEncoderXPCService in the no-viewer guest and reconstruct the
first SDMA/VMPT stall against the successful repeat, including guest persistent configuration
and workload. Do not make another nearby GPU patch or infer that reboot is required from a
missing journal record. The user explicitly prohibits host reboots.
