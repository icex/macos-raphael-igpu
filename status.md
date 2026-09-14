# Status

Updated 2026-09-14 after the reboot-free TigerVNC tests. Historical status is in
`findings/research/status-archives/`; detailed evidence is in
[the TigerVNC audit](findings/research/tigervnc-reset-audit-20260914.md).

## Current result

**The reset path works without a host reboot; the guest desktop is still blocked.**
Candidate 1.0.230 previously passed the managed-texture copy matrix and desktop probes.
The current revalidation did not complete: WindowServer and the Metal probe block, with
pending SDMA/VMPT work. TigerVNC authenticates but receives no usable desktop.
The same failure occurs with no VNC viewers connected, so concurrent viewers are not a
necessary trigger. These runs do not establish the root cause or invalidate the historical
successful readbacks. Configuration equality does not prove current functional success.

## Current candidate and host

| Field | Value |
|---|---|
| Driver | 1.0.230, build `c115e782494e43f6850aedfb67010375` |
| Executable SHA-256 | `c9e5a856a34ebbe4f3b1bf59de2c613d15edff37c7b2e677a8d476b324bfcf94` |
| Driver source | unchanged from proven candidate230 |
| Coordinator worktree | `/home/bogdan/macos-vm/run/worktrees/candidate-230` |
| Host boot | `c369c74e-96ff-4c21-ae85-80ccb269f7d2` |
| GPU | `0000:7b:00.0`, vfio-pci, power/control=on |
| Ledger launches | 44; launches 41–43 were the TigerVNC tests |
| Last reset | `run/mode2-reset-69.json` (before launch44): CP_STAT=0, RLC_CNTL=0 |
| VM | stopped |
| Guest shutdown | forced; harness recovery incomplete, followed by successful MODE2 reset |

MODE2 resets 65–68 all met the documented CP_STAT/RLC_CNTL checks. No host reboot or
vfio-pci → amdgpu cycle occurred. No universal all-engine recovery claim follows from these
register checks. Normal host checks and capture/shutdown abort paths remain enabled.

## Changes made

- The coordinator accepts a reviewed, hash-pinned prior initialization snapshot only for the
  same live boot, kernel, device, IOMMU group and vfio-pci driver. Explicit initialization
  failures in the current journal override it. Other live admission checks remain separate.
  Pin: `experiments/amdgpu-initialization-evidence.json`. This fixes loss of historical
  initialization evidence after journal rotation; it grants no launch authority.
- Both WindowServer preference plists were restored from `/var/root/wsprefs-aside/` to the
  global preferences and bogdan's ByHost preferences, with hashes and ownership verified.
  Original backups remain. A WindowServer TERM did not release the blocked process; a fresh
  guest boot with restored preferences also failed to complete the probe.
- Screen Sharing authentication works with the current guest account. The earlier kickstart
  settings have no verified pre-change backup and were not guessed at or reset arbitrarily.
- The pre-existing uncommitted supervision edit remains preserved in the named git stash
  `Preserve pre-existing supervision edit before TigerVNC test`; it was not used for these runs.

## Blocking issue and next discriminating observation

The first failed run's sampled WindowServer main thread waits in
`IOAccelSharedCreateDeviceShmem`. Channel dumps contain pending SDMA/VMPT work while the
hardware graphics-ring read/write pointers are equal. VTEncoderXPCService also blocks,
including in the run with no VNC connections. It is not yet established which command or
client initiates the failure. Identify that encoder's requester and the first stalled
SDMA/VMPT operation, comparing guest state and startup against the successful candidate230
repeat before selecting another GPU intervention. Restoring preferences alone was insufficient.

Physical HDMI/DP scanout, remote-artifact diagnosis, games/performance, and full lifecycle
qualification remain open. The current failure must not be described as proven transport
corruption or an inherent absence of macOS virtual displays.

## Running and authority

Use [the experiment cycle](docs/running-an-experiment.md) and
[host safety rules](docs/host-safety.md). Each authorized launch needs a fresh clean MODE2
receipt, a note naming the host boot, and bounded supervision (up to 6000 seconds).
The three TigerVNC allowances are consumed; a failed pre-QEMU launch does not consume one.
No merge or push to main. User instruction: **no further host reboots**.

Validation of the coordinator used for these runs: 925 host tests, 3 skipped, no failures;
`/home/bogdan/macos-vm/run/tigervnc-host-tests-final.log`.

## Diagnostic result and controlled retry

Launch44 (`encoder-trace`) identified RustDesk --check-hwcodec-config as the encoder
requester in both current and prior boot logs. RustDesk was in the ByHost loginwindow
reopen list; backed up the original plist and removed only its entry. The guest still
stalled in this already-exposed run. Forced shutdown, incomplete recovery; VM stopped.
See audit for process, XPC, timestamp and backup evidence.

One additional authorized fix-validation launch on boot
`c369c74e-96ff-4c21-ae85-80ccb269f7d2`, attempt `without-rustdesk`, after fresh
MODE2, unchanged candidate230, initially no viewers. Verify RustDesk and its encoder
request are absent; require probe completion and a watchable TigerVNC desktop to
support the workaround. Persistence of the stall falsifies removal as a sufficient fix.
Bounded to6000s; normal abort/cleanup, no host reboot or binding cycle.
