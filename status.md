# Publication cleanup — 2026-10-17

The publication tree is privacy-sanitized: private OpenCore configuration dumps
and browser captures are excluded from all published history; personal paths,
usernames and host/network identifiers are examples. Recorded capture hashes
refer to privately retained originals. Historical helper pins have been updated
to their exact sanitized fixtures; design contracts, verification and abort
paths remain enforced. The installed VM and its original recovery receipts
are unchanged. No guest restart or hardware run is part of this cleanup.

Local host suite: 1670 tests passed, 12 skipped. Current tracked content and
rewritten history pass publication privacy and secret scans. Hosted validation
must pass for the final main commit before delivery is called complete.

# Live status — 2026-10-17 — desktop shortcut session expiry removed; VM stopped

The installed ordinary desktop card now explicitly requests no session expiry
(`max_seconds=0`, `interactive_hold_seconds=0`). It creates no exposure timer
and no systemd runtime cap; it waits for user shutdown/close while preserving
identity, host-fault, serial/critical capture and GPU cleanup. Startup continues
to skip host tests and guest probe workloads. Experiment cards retain deadlines.
Host suite passed 1666 tests (8 skipped). The installed runtime/card match
the checked dev change and are clean. Fresh current-source stopped-device
recovery recovered/authorizes_launch=true; there is no Raphael expiry timer
or sleep/idle block while the VM is stopped. No new VM launch was performed.
Validation and deployment evidence are recorded in
[desktop session expiry](findings/research/desktop-no-timeout-20261017.md).

Prior ordinary desktop run `f5446ac413460078fe9d7cdc81942c13` completed with
`DESKTOP_SESSION_COMPLETE`, no probe, native guest shutdown, guard release and
separate stopped-device recovery authorizing reuse. It stopped at 16:10 local
because the desktop card incorrectly retained the old 5800/6000-second limits;
the host suspended at 16:25:33 and resumed at 16:25:45, after the VM had stopped.
It was guest shutdown, not guest suspend with the host.

The user's next launch `501c3f3853567b0b2ad630e57d197fa6`, attempt
`d20261017162609`, started on the same boot. I stopped its deadline timer while
trying to preserve the session; supervisor verification rejected the missing
timer and force-stopped QEMU after guest-shutdown verification also refused.
This was an interrupted session, not a clean guest shutdown. Guard cleanup
completed and separate recovery authorized reuse. The user requested that
macOS be left running and that the desktop shortcut never time out. No further
VM launch is performed by this change; the user will start it from the desktop.

Last verified file access: the SSD is mounted on Linux as exFAT at
`/run/media/user/USB-DATA`; the user's Linux copy was left undisturbed.
The SSD and `/home/user/Nextcloud` were mounted read/write in the prior macOS
session as `/Volumes/SSD` and `/Volumes/Nextcloud`, using authenticated SMB3.1.1.
Those guest mounts ended with shutdown; the login reconnect agent remains configured.
The live session reports full AES-128-GCM encryption and AES-128-GMAC signing.
Guest access and SMB2 negotiation were rejected; only loopback inside the VM
network namespace listens on port 445, with no host/LAN port published.
The separate `macosshare` password was entered through a local password
dialog; no plaintext password was saved. Samba's password database is mode
0600 under the private user configuration directory. Both mounts passed
console-user read/write permission checks without test-file writes.
The user service follows the VM lifecycle and holds no sleep inhibitor;
a macOS login agent is configured to reconnect using Keychain credentials
when saved. Next-login behavior has not been reboot-tested. No GPU launch,
VM restart, SSD unmount or device handoff was needed for this setup.
See [file sharing](docs/file-sharing.md) and
[evidence](findings/research/private-smb-shares-20261017.md).

The installed shortcut now requests `startup_workload=none` and skips the
host regression suite. Earlier run `f5446ac413460078fe9d7cdc81942c13`,
attempt `d20261017143231`, reached interactive desktop without a probe
artifact or automatic Metal workload. It uses the unchanged release-519
build and QEMU pins v20. Its final shutdown and recovery are recorded above; the VM is now stopped.
No standalone development blocker is active.

Earlier USB validation: the then-attached Intel 1.9 TB SSD was redirected through its ASMedia `174c:1153`
enclosure. A serial-specific uaccess rule grants access to the desktop user.
Its existing encrypted APFS volume was initially locked. The user entered
the drive password in macOS; `diskutil info` now confirms mounted/unlocked
and `df` confirms the mounted filesystem. No format or content changes were
requested by that validation. The user subsequently exchanged/formatted the
drive and returned it to Linux; current access uses the SMB shares above.
Host suite: 1664 tests, 8 skipped. Original build-worktree identity checks
are preserved. Coordinator source changes required a fresh schema-9
no-queue requalification of the prior actual run; it authorized launch
without modifying original recovery evidence. See the
[lifecycle evidence](findings/research/desktop-inhibitor-lifecycle-20261017.md).

The shortcut previously aborted before exposure because `rgpu-inhibit` was
stopped. The installed launcher now starts that container and holds logind
sleep/idle inhibition through preflight, the VM and recovery, then stops it.
The container has `restart=no`; no Raphael block inhibitor remains while
closed. Systemd termination and failed-start checks also released inhibition.

Earlier completed hardware run: installed release 519 / metal-324 / QEMU pins v20,
attempt `d20261017141818`, run `7cb21dad101d30e43f60aeaba3e532ac`, build
`dc14fd8203a747e1a92c8d10efdbbf94`, on host boot
`aee5672f-423f-46c0-95d5-e917928b979b`. Functional: CORE_PROBE_PASS, no
sampled readback mismatches, guest selected 5120x2880/120. Capture: valid
identity and serial/critical proof. Shutdown: exited-after-guest-request;
schema-2 DMA guard released. Ordinary recovery remained incomplete; separate
schema-9 stopped-device recovery recovered/authorizes_launch=true. That cycle
left no VM or Raphael inhibitor; power/control remains on. Full host
suite: 1661 tests, 8 skipped. This verifies the launcher lifecycle on this
boot; actual host suspend/resume and broader desktop qualification were not
rerun. [Evidence](findings/research/desktop-inhibitor-lifecycle-20261017.md).

Priority: continue higher-impact desktop and integrity qualification after
the 2048x1152 scaled-mode copy fix. The verified
QEMU window fit/cursor improvement is installed and delivered on `dev`
`2190c98` with exact-commit hosted test/build success. Safari
fast-scroll stutter and slow QEMU-window resize audio are known low-priority
issues at the user's direction. Remote `dev`
`ce5bfe8` passed exact-commit hosted test and macOS build; the release job was
skipped on the branch push. Candidate 515
has two diagnostic native schema-2 runs, two guarded QEMU-death runs and one
installed desktop-launcher run. Recovery and repeated post-crash guest integrity
passed on this boot; longer-term qualification remains.
See the
[independent investigation](findings/research/guest-memory-corruption-20261015.md)
and [remaining-issues handoff](docs/handoff-remaining-issues-20261015.md).

Earlier diagnostic run: candidate 517 / metal-322 / `dd7922903fe898f0dd0013b40b9fb212`.
Functional: viewport trace shows source 4096x2304 while output timing remains
5120x2880; copy refusal and guest reachability reproduced, then session mode
restored. Capture: serial viewport evidence retained, but my direct macOS UI
shutdown during interactive hold ended capture before the supervisor handled
the stop request, making wrapper `INVALID`. Shutdown/recovery: guard released,
ordinary recovery incomplete, separate stopped-device schema-9 recovery
`recovered/authorizes_launch=true`; no QEMU remains. Next: use validated
viewport bounds for the source copy, then repeat with intact capture and
shutdown. See [scaled-mode research](findings/research/scaled-mode-copy-20261015.md).

Candidate 518 / metal-323 / `dbcd1eead4a5bd7c37d1293be61c682c`:
functional CORE_PROBE_PASS; 4096x2304 scaled mode copied 100+ frames per
10-second window, QEMU presented its geometry, and 5120x2880 copying resumed
after restore. Capture remained valid. Supervisor guest shutdown exited after
request; schema-2 guard released; ordinary recovery incomplete, separate
schema-9 stopped-device recovery recovered/authorizes_launch=true. Remove
overly verbose success logging and rerun before delivery.

Candidate 519 / metal-324 / `c416a847497fc62c3fe1a6ec6a6e7858`:
bounded diagnostic build passed Metal, continuous 4096x2304/120 copying,
return to 5120x2880/120, QEMU host-window fit, valid capture and supervised
guest-requested stop. Guard released; original recovery incomplete; separate
schema-9 stopped-device recovery recovered/authorizes_launch=true. Installed
launcher attempt `d20261015161621`, run `635a7bb73b41a07bf2409156bc613f64`,
passed its Metal/desktop fit and normal start/stop path with the same guard and
recovery outcomes. No QEMU remains; `power/control=on`. This qualifies the
scaled-mode copy and installed default on this boot; fresh-boot and long-term
memory integrity qualification remain open.
After the installed launch, GPU-less Tahoe refresh nonce
`8df0d7de731644e99584ab2582cd5e7f` sealed all four image identities and
native guest shutdown exit 0. Remote `dev` `9a7802f` matches local; exact-commit
hosted test/build CI passed in run 38741944813 (release skipped on `dev`).

## Current configuration and safety

Host boot `aee5672f-423f-46c0-95d5-e917928b979b`, kernel 7.2.10-1-cachyos-bore,
Ryzen 7 9800X3D, microcode 0x0b404035, BIOS UMA 4 GB. Host configuration unchanged;
iGPU 0000:7b:00.0 remains vfio-pci with power/control=on. GPU bindings and host
KVM settings are unchanged. Initial IH containment at 07:22:51 UTC is recorded
in `memory-diag-20261015/continuation-01/ih-quiesce-01.jsonl`.

Candidate 519 is staged on the installed Tahoe guest with QEMU pins v20.
The desktop selection is release 519 / metal-324 / pins v20. The repaired live
launcher requires the new guard capability, so old images refuse startup.
Harness installation preserved local CPUID settings and saved
backups in `run/ih-harness-install-*`. The current desktop and its scoped inhibitor are running. The owned post-crash GPU-less guest was
paused, its complete RAM core preserved, then stopped through its bounded user unit;
this was a forced diagnostic stop, not native shutdown.
Stopped Tahoe disk backup:
`~/macos-vm/backups/mac_hdd_ng-before-memory-diag-20261015.qcow2`.
The separate macOS 15 clone preserves its rollback source.

## Candidate 515 validation

- Full host suite: **1656 run, 8 skipped**. Build from `bd1be16`, source
  SHA `7d540f2dbed000f5d3c8728674a97fe92a07f5c95012eca32eafa6a21aab96a9`.
- Installed Tahoe GPU-less refresh passed four guest/upload image hashes and
  native exit 0 (`continuation-01/tahoe-after-ih-stop-guest-identity.json`).
- Original 514 recovery was independently requalified with fresh MODE2,
  complete queue scans and stationary disabled IH; original receipts unchanged.
  Evidence: `continuation-01/ih-requalification-before515-02.json`.
- **First native run:** `083451d7ee2a8bc3b39b508dc8dc4d12`, build
  `90c57452e22f449ca010e6d08cf51f83`, results `run/candidate-515-results/`.
  Functional: CORE_PROBE_PASS / sampled render readbacks correct. Capture:
  serial/critical proof retained, readable GTK desktop PNG kept locally;
  HMP screendump unsupported (`no surface`). Shutdown: native requested,
  direct natural exit 0. Guard: IH0 `0x1033011f` -> `0x1031001e`, stationary
  WPTR 0 before unmap. Full schema-10 recovery recovered / authorizes_launch=true.
- **Abrupt QEMU death:** run `9fc73c08a7081e1b9d72193f612610a3` passed Metal
  before an identity-checked pidfd SIGKILL. QEMU was container PID1, so this also
  ended its container. Guard stayed alive, cleared active IH0 and SDMA RLC0
  inputs, and released only after stationary IH proof. Full schema-10 recovery
  recovered / authorizes_launch=true. Wrapper INVALID and shutdown already-stopped
  are expected crash outcomes, not native shutdown. A paused/flushed disk reflink
  was saved immediately before injection. Results: `run/candidate-515-attempt-procdeath01-results/`.
- **Post-crash plain refresh blocked:** nonce `5e88f1b2865a4253839f8969dde20adb`
  matched all four images but panicked at 71.997 s uptime during shutdown, in
  `phys_attribute_test` called by `heap` / `mach_vm_page_range_query`. A reverse
  mapping points to a zeroed pmap object; `pmap_pte` returned NULL, then XNU
  dereferenced it. Exact BootKC bytes establish slide `0x19600000`; this is
  observed guest failure, with cause unresolved. The tool correctly refused to
  seal native shutdown. Evidence: `continuation-01/aftercrash-panic-buffer.txt`,
  `aftercrash-pmap-context01.json`, `aftercrash-plain-guest.core` (12 GiB, local).
  Owned plain CID `01929eaf7c1d` stopped via `rgpu-compat-plain-5d33904a94c6`
  after capture. No new GPU exposure or ledger entry for `aftercrash01`.
- **Fresh independent control after SIGKILL:** macOS 15 build 24H32, original
  rollback reflink, eight CPUs / 8 GiB / NVMe / only `/dev/kvm`, Lilu/plugin off.
  Canary, four image hashes and native exit 0 passed in 103.9 s. Evidence:
  `continuation-01/control-03-after-procdeath/run/memory-diag-20261015/`.
- Read-only MMIO at 08:41 UTC confirms IH0 disabled / WPTR 0 stationary.
  Two IH clusters in Tahoe RAM exactly match bytes at qcow2 offsets
  `0x17aa04000` / `0x17aa06000`, including O_DIRECT reads and both pre-test
  backups. The earlier 2026-10-14 21:35 backup also contains both sequences.
  This proves persisted historical IH corruption in the production disk;
  it does not establish that the new panic has the same cause. Identifying
  that file was subsequently identified and quarantined as documented below.
- The unmodified Tahoe clone `tahoe-pmap-01` passed 120 s of the new bounded
  page-query/fork stress (105,251 queries / 154,842 child lifecycles), the remap
  canary, all image hashes and native shutdown. This does not explain or erase
  the earlier panic. A complete raw-disk signature scan attributed both live IH
  extents to the symbolication cache; a third duplicate has no current-tree owner.
- Teardown audit: schema-1 guard stopped IH/display but GC/SDMA cleanup ran later.
  The crash recovery initially saw CP ME unhalted, five active HQDs, enabled
  SDMA GFX/PAGE inputs. This is an unclosed pre-unmap boundary, not proof of
  another DMA write. Schema-2 guard now adds source-backed GC/SDMA halt/idle
  checks before release. Full software suite: 1656 run, 8 skipped.
  The installed live helper is now schema 2, with an installer backup under
  `run/ih-harness-install-20261015T094555.135714Z`.
- **Schema-2 native run:** `0e6dd8a6bb200cc3a4d84e0c6498305f` reached
  CORE_PROBE_PASS with zero sampled render mismatches and native requested exit.
  The independent guard stopped IH/display and proved GC/SDMA halted and idle
  in five samples before releasing its VFIO descriptor. Capture was retained.
  **Ordinary recovery was incomplete / authorizes_launch=false:** all 16 active HQDs
  timed out during post-unmap dequeue, the host KIQ was blocked by active HQDs,
  and CPC_BUSY remained nonzero. This run is not a reuse or stability pass.
  Evidence: `run/candidate-515-attempt-enginehalt01-results/`, guard receipt
  `run/dma-guards/rgpu-launch-51c8089847ab4a15a5d3d46b40e0dc50.json`.
  A read-only no-queue inspection refused on those active HQDs. A subsequent
  stopped-device MODE2 reset and complete no-queue scan passed, yielding a
  separate schema-9 recovered/authorizes_launch=true receipt:
  `continuation-01/enginehalt01-noqueue-recovery.json`. The ordinary receipt
  remains incomplete. The supervised wrapper now invokes this strict fallback
  when a released schema-2 guard leaves ordinary recovery incomplete; hardware
  validation of the automatic path passed on the next native run.
- **Second schema-2 native run:** `d53a27bbd753a6becaae13c6e40a81e8`
  passed the Metal probe, retained serial/critical capture and exited after
  the guest shutdown request. Its guard released after IH and GC/SDMA proofs;
  ordinary recovery was incomplete with active HQDs, and the supervised
  wrapper automatically completed MODE2/no-queue recovery. Separate schema-9
  receipt is recovered/authorizes_launch=true; wrapper return code 0.
  Evidence: `run/candidate-515-attempt-enginehalt02-results/`.
  Abrupt-stop validation and repeated guest integrity are recorded below.
- **Schema-2 abrupt QEMU death:** `c60f611464eade014bfa16d65097c0e0`
  passed the Metal probe before exact pidfd SIGKILL of QEMU/container PID1.
  A paused/flushed disk reflink was preserved. Guard survived outside the
  container, recorded `qemu-death`, and released only after five stationary IH
  and stopped/idle GC/SDMA samples. Ordinary recovery again was incomplete;
  automatic MODE2/no-queue recovery returned a separate schema-9
  recovered/authorizes_launch=true receipt. Wrapper INVALID due Docker inspect
  after process death and shutdown already-stopped are expected crash outcomes,
  not native shutdown or a failed Metal probe. Evidence:
  `run/candidate-515-attempt-procdeath02-results/`,
  `continuation-01/c515-procdeath-02-injection.json`.
  Post-crash plain Tahoe refresh nonce `2f2c09e5228241d0b269789eab3cd039`
  matched all four guest/upload image hashes and sealed native exit 0.
  A focused installed-guest follow-up nonce `0bb1db7e8c10458693fec4ad8f58453c`
  passed 44,291 remaps/90,707,968 page checks, 104,919 page queries/150,415
  child lifecycles, four hashes and native exit 0.
- **Repeat schema-2 abrupt death on repaired disk:**
  `911cda8adc60b63a8c031be608f1cba9` passed Metal before an exact
  identity-checked QEMU/container PID1 SIGKILL. A paused/flushed disk reflink
  was preserved. The guard again released after `qemu-death` with five IH and
  GC/SDMA stopped samples; the automatic MODE2/no-queue fallback produced
  schema-9 recovered/authorizes_launch=true. Wrapper INVALID / shutdown
  already-stopped are the injected crash outcomes. Evidence:
  `run/candidate-515-attempt-procdeath03-results/` and
  `continuation-01/c515-procdeath-03-injection.json`. The installed Tahoe
  follow-up nonce `1745e1076ed34218bb0b55c84f910c3f` passed 44,701
  remaps/91,547,648 page checks, 108,618 page queries/152,410 children,
  all four image hashes and native exit 0. This is a second bounded
  crash/recovery/integrity sequence.
- **Desktop selection:** release 515 / `metal-321` / pins v19 is installed;
  its card caps the supervised session at 6000 s. The first shortcut attempt
  `d20261015133701` failed in shell argument parsing before cycle/QEMU/VFIO;
  no GPU ledger entry was consumed. The nested launcher receipt-check quoting
  was corrected. The installed launcher attempt `d20261015133753`, run
  `92e438ba58725f977267dbd21b381319`, passed Metal readbacks and showed a
  readable macOS GTK desktop. Serial and critical capture were retained.
  `raphael-macos stop` produced guest-requested native exit, guard schema-2
  release, and separate automatic MODE2/no-queue schema-9
  recovered/authorizes_launch=true. Wrapper CORE_PROBE_PASS and return code 0;
  the launcher reports stopped. Private desktop PNG remains local in
  `continuation-01/product515-window-local.png`. A subsequent GPU-less plain
  Tahoe refresh sealed nonce `7390f2a8808c407d8b0886cc7fcafc6f`: all four
  image hashes matched and native shutdown exited 0.
- **Historical disk repair:** two live IH extents were traced to the Data
  volume's `/System/Library/Caches/com.apple.coresymbolicationd/data`.
  A stopped-disk reflink backup was saved as
  `backups/mac_hdd_ng-before-cache-quarantine-20261015.qcow2` (89,834,717,184
  bytes). The installed guest file had grown to 1,704,050,688 bytes, but both
  IH signatures remained at the mapped offsets. Its cache was renamed inside
  the guest to `data.rgpu-corrupt-20261015`; no user document was removed.
  An isolated Tahoe clone passed reboot, 107,612 page queries/152,192 children,
  four hashes and native exit 0 after the same quarantine. The installed disk
  then passed 42,771 remaps/87,595,008 page checks, 102,387 queries/147,028
  children, four hashes and native exit 0 after reboot (nonce
  `b3a48bb4e0224d1aa273de12f92f3a84`). Evidence:
  `continuation-01/tahoe-corrupt-symbolication-cache.json`,
  `tahoe-cache-clone-postquarantine-stress.log`,
  `prod-cache-postquarantine-stress.log` and matching `run/compat-*-output.txt`.
  The earlier `heap` pmap panic's precise cause is still unproved. No new APFS
  error, image mismatch or panic appeared in these bounded repeats; long-term
  stability and every possible DMA engine remain outside this evidence.
- **Audio baseline after delivery:** installed 515 attempt `d20261015135005`,
  run `fe2177bdcc148de6ec1f2070a5e30b84`, passed CORE_PROBE_PASS; host
  recording and 4K/120 window stress are in
  `run/audio-diag-20261015/baseline-515/`. The original 5K/120 run and a clean
  single-tone 4K/120 repeat reached 105–120 QEMU frames/s and 107–120 macOS
  presents/s without a sustained silent interval. The clean 4K/120 70-second
  sink recording had zero 1 ms windows below 30% of steady tone RMS after its
  first eight seconds; 30 seconds of three-window stress ran inside it. The
  historical 22/30-second dropout did not reproduce. A QuickTime foreground
  attempt stalled at its open dialog and supplies no playback result. The
  launcher stop was native; guard schema-2 released and automatic MODE2/no-queue
  schema-9 recovered/authorizes_launch=true. Only `rgpu-inhibit` remains active.
  Audio's earlier cause and wider app coverage are unresolved; longer
  single-source stress and sample-path instrumentation are next discriminators.
  The earlier pmap panic's exact mechanism and unmeasured autonomous DMA
  sources also remain open.
- **Five-minute single-source audio repeat:** installed 515 attempt
  `d20261015140130`, run `fd53b1d6499a36bcb8a416f302bc3b03`, passed
  CORE_PROBE_PASS. An owned GPU-less compatibility refresh preceded exposure
  and completed normally. A 300-second 48 kHz stereo 440 Hz WAV played alone
  in Tahoe at 3840×2160 backing / 120 Hz; the host sink capture ran for
  289.98 seconds. After the first eight seconds, every 1 ms window remained
  above 30% of steady tone RMS, and 440 Hz dominated every one-second spectrum
  window. During 240 seconds of three-window stress, QEMU delivered mean
  119.7 fps, macOS presented 119.7 fps, with no GPU restart or allocation
  failure. Evidence: `run/audio-diag-20261015/soak-515/analysis.json`,
  `4k120-monitor.wav` and `window-stress.json` (large WAV kept local).
  Launcher stop produced native guest exit, schema-2 guard release and
  automatic schema-9 MODE2/no-queue recovered/authorizes_launch=true;
  only the idle inhibitor remains. The old dropout remains unexplained and
  was not reproduced under this longer controlled load.
- **Foreground-app and host-window resize repeat:** installed 515 attempt
  `d20261015141057`, run `d96edb412a6611c8d57ecc8c4f6875a4`, passed
  CORE_PROBE_PASS. A local Cocoa/AVAudioPlayer window played the 300-second
  tone at 3840×2160 backing / 120 Hz while a 100-second host sink capture
  recorded zero 1 ms windows below 30% of steady RMS after startup. The guest
  three-window stress ran 60 seconds at mean 120 QEMU fps / 120 macOS presents;
  20 alternating X11 QEMU host-window resize requests took effect during that
  interval. The guest remained at 4K/120. Evidence:
  `run/audio-diag-20261015/foreground-515/analysis.json` and
  `window-stress.json` (WAV and player source kept local). Native guest stop,
  guard release and schema-9 recovered/authorizes_launch=true followed.
  These bounded synthetic actions did not represent a gradual manual edge
  drag; they do not clear the user-reported audio failure.
- **Manual resize reproduction:** installed 515 attempt `d20261015142454`, run
  `129ff961614528f8cfa27142f85c8991`, passed CORE_PROBE_PASS. The user
  reproduced choppy Safari audio while scrolling and dragging a QEMU window
  edge over several seconds. Host sink recording and timestamped X11 geometry
  are in `run/audio-diag-20261015/manual-slow-515/`. A separate single-source
  440 Hz `afplay` capture in `manual-tone-515/` has exact digital-zero spans,
  including two of 1.99 s. The first starts about 0.08 s after the first
  manual size change; the guest `afplay` process stayed alive. Fast Safari
  scrolling did not interrupt the tone in this pass, but slow resizing did,
  and the user heard it stop. The earlier instant-resize tests missed this
  workload. The layer dropping samples is not yet established; QEMU USB
  packet/empty-buffer counters do not measure sample amplitudes. The launcher
  requested guest shutdown, the container exited naturally, the schema-2
  guard released, and separate schema-9 MODE2/no-queue recovery is
  `recovered/authorizes_launch=true`; wrapper CORE_PROBE_PASS/returncode 0.
  Receipts: `run/candidate-515-attempt-d20261015142454-results/`. The launcher
  reports stopped; only the idle inhibitor remains. Next discriminator:
  timestamp QEMU guest USB packet content and callback/display stalls under a
  new supervised manual-drag run.
- **Instrumented slow-drag run:** release-515 attempt `d20261015144021`,
  run `5ea82c478ac1c3ca33cf6b1b4966e651`, used a local QEMU diagnostic
  image with the unchanged VFIO guard and timestamped USB/GTK EGL logs. It
  passed CORE_PROBE_PASS. At 5K backing / 120 Hz, the user's gradual side
  drag again halted the 440 Hz tone. Host sink samples were exact zeros for
  2.477 s beginning ~11:45:31.655 UTC. QEMU received nonzero tone packets
  before the drag, then logged a 2012 ms gap in guest USB packets; the audio
  callback still ran intermittently and reported an empty queue. The guest
  `coreaudiod` log at 11:45:31 UTC records deadline/safety overloads,
  `AppleUSBXHCIIsochronousTransferRing` enqueue failure and audio-engine
  stop/restart. QEMU EGL swap had 0.8–1.0 s stalls earlier during startup,
  but no comparably long logged swap in the 11:45:31–34 dropout interval.
  The first abnormal step during the drag and its host scheduling cause are
  not yet proved. The user corrected an apparent desktop freeze: the desktop
  remained responsive, but the guest cursor disappeared after manual resize.
  Capture, geometry, diagnostic patch/build and guest audio log are in
  `run/audio-diag-20261015/instrumented-515/` and its parent. Guest-requested
  native exit, schema-2 guard release, and separate schema-9
  recovered/authorizes_launch=true followed. Wrapper CORE_PROBE_PASS/returncode
  0; launcher stopped, only idle inhibitor remains. Receipts:
  `run/candidate-515-attempt-d20261015144021-results/`. Next: test paced
  display presentation during drag; then address cursor restoration and
  one-time guest-size window fit capped by usable host display area.
- **Failed presentation-hold trial:** release-515 attempt `d20261015145005`,
  run `7727f8484651e0720f582146273d5af6`, used local diagnostic image
  `rgpu-qemu:c516-resize-hold`. It deferred display presentation for 200 ms
  after UI size changes and forced cursor reimport on resume. Under the user's
  slow side drag, the tone again contained 0.880 s and 2.004 s exact-zero
  intervals; QEMU logged a 2009 ms USB packet gap. Its first resize hold was
  at 11:53:50.180 UTC, after critical silence began, so this is not a fix.
  The cursor again became invisible without a resize script. Read-only
  inspection of the live shared display memfd found cursor `enabled=1`,
  256×256, with nonzero alpha data and plausible position; GTK/GL cursor
  presentation remains suspect. Evidence: `run/audio-diag-20261015/resize-hold-515/`.
  Launcher stop requested guest shutdown; wrapper CORE_PROBE_PASS/returncode 0,
  guard released, postrun schema-9 recovery `recovered/authorizes_launch=true`.
  Receipts: `run/candidate-515-attempt-d20261015145005-results/`. Launcher
  stopped, `power/control=on`. Next: trace the earliest scheduling stall and
  add a persistent host cursor fallback.
- **Fitted-window and priority discriminator:** release-515 attempt
  `d20261015145931`, run `1ad02a49f2b6070bb696231b184a6b46`, used local
  diagnostic image `rgpu-qemu:c516-fit-cursor-enabled`. At desktop 5120×2880,
  QEMU chose a 3608×2064 window inside the 7584×2112 work area; the user
  confirmed fit. The host-cursor fallback stayed visible after slow resizing.
  Audio still stopped during the resize: the host sink WAV has several exact
  zero spans near 2 s, QEMU logged 1997–2027 ms guest USB packet gaps, and
  guest `coreaudiod` reported missed deadlines, USB isochronous enqueue
  failure, and engine restart. Host Ananicy assigns QEMU `nice=9` and I/O
  priority 7. A bounded process-only `nice=0` override kept this run's QEMU
  threads at 0 during the drag, but the dropout persisted. Per-thread
  schedstat showed little runnable wait during those gaps, so host nice level
  is not a sufficient cause. Evidence: `run/audio-diag-20261015/fit-cursor-515/`,
  `nice0-fit-cursor-515/`, and its `priority-maintenance.log`. The override
  ended with the run; no host policy file or KVM setting changed. Launcher
  requested guest shutdown; wrapper CORE_PROBE_PASS/returncode 0, schema-2
  guard released, separate schema-9 recovery `recovered/authorizes_launch=true`.
  Receipts: `run/candidate-515-attempt-d20261015145931-results/`. Launcher
  stopped and `power/control=on`. User reprioritized: investigate Safari
  scrolling and other guest app activity first; slow-resize audio is lower
  priority.
- **Post-audio plain integrity:** direct Tahoe refresh nonce
  `944596ffbed34e9b9c86f8e0d1328060` matched all four guest/upload image
  hashes and sealed native exit 0 after the third audio GPU session. Evidence:
  `run/audio-diag-20261015/after-audio-plain-refresh.log` and
  `run/guest-identity.json`. No VM remains running; power/control is `on`.
- **Safari viewport discriminator:** installed-515 attempt
  `d20261015151631`, run `3710f00dc07dc31dca8135387cad44ff`, used local
  diagnostic fit/cursor image at 5K/120. The user reproduced YouTube music
  stutter while fast-scrolling the normal Safari page, then reported no
  stutter on the same page with the video in Picture in Picture. The quiet
  997 Hz guest `afplay` pilot stayed present in the host recording across the
  normal-page stutter, and QEMU USB packets remained near 1000/s without a
  comparable long gap. Guest WebKit logs during normal scrolling repeatedly
  changed the video's viewport visibility, flushed/replaced its renderer,
  stalled it and paused its AudioQueue. After the same video entered PiP at
  15:26:08 guest time, those events did not recur through the captured
  15:26:35 interval. This implicates Safari's video visibility/renderer path
  for this symptom; it does not establish that all guest applications are
  unaffected or that WebKit itself is the root cause. Evidence:
  `run/audio-diag-20261015/safari-scroll-515/` and `safari-pip-515/`.
  Launcher requested shutdown; wrapper CORE_PROBE_PASS/returncode 0, schema-2
  guard released, original recovery incomplete, separate schema-9 MODE2/no-queue
  receipt `recovered/authorizes_launch=true`. Receipts:
  `run/candidate-515-attempt-d20261015151631-results/`. Launcher stopped,
  no QEMU remains, `power/control=on`. The Brave comparison follows below.
- **Clean QEMU fit/cursor and browser comparison:** installed-515 attempt
  `d20261015153150`, run `59a36d6e692836031ad7e7fce3c72016`, used QEMU
  image `sha256:7785dc54e21d619219008e361d8393b1d7baa16f6e2ea9a92318e1940db94a3c`.
  It contains v19 guard/audio code plus only the GTK auto-fit/host-cursor patch;
  temporary USB/EGL tracing was removed. Image binary SHA-256
  `a3d8d946571aa0a41b8768f55be1961abb7add121edd5d445e2cc09a8a3aca09`
  matched the built binary. QEMU logged the 3840x2160 boot picture and the
  5120x2880 desktop each fitted to a 3608x2064 host window inside the
  7584x2112 work area. The user confirmed the final window fit and pointer
  visibility. On the same YouTube page, fast scrolling in Brave had no audio
  stutter; the user marked Safari's app-specific symptom low priority. An
  extra Brave copy was placed in the guest user's Applications folder from the
  downloaded DMG, with code signature verified after removing copied Finder
  metadata. The existing system Brave was already running, so the extra user
  copy was removed in the next run. QEMU exited after
  guest-requested shutdown with CORE_PROBE_PASS/returncode 0, schema-2 guard
  released, original recovery incomplete and separate schema-9 MODE2/no-queue
  receipt `recovered/authorizes_launch=true`. Receipts:
  `run/candidate-515-attempt-d20261015153150-results/`. No QEMU remains,
  `power/control=on`.
- **Installed v20 shortcut:** the unchanged release-515 worktree/card now use
  local installed pins `run/release515-pins-v20.json` through
  `~/.config/raphael-macos/release.conf`; the prior config is backed up as
  `release.conf.before-v20`. The installed command itself launched attempt
  `d20261015154053`, run `28a4788b5fec67399bc3d26c535c2f49`, with the
  same immutable image ID. At the 5120x2880 desktop QEMU logged the expected
  3608x2064 fit in the 7584x2112 work area. The existing system Brave was
  present, and the redundant copy from the user Applications folder was
  removed. Guest-requested stop produced CORE_PROBE_PASS/returncode 0,
  schema-2 guard release, original recovery incomplete and separate schema-9
  MODE2/no-queue `recovered/authorizes_launch=true`. Receipts:
  `run/candidate-515-attempt-d20261015154053-results/`. No QEMU remains,
  `power/control=on`. Local installed path is verified; `dev` `2190c98`
  points to this milestone, remote ref matched, and exact-commit hosted test
  and build passed (release job skipped on `dev`).
- **Scaled-mode failure on current release:** attempt `d20261015154833`, run
  `6bf1f855012317e8a887781506f4f41b`, started in 5120x2880/120 with
  the installed v20 image. A session-scoped CoreGraphics switch to logical
  2048x1152 / physical 4096x2304/120 succeeded. The SDMA poller rejected
  four `pitch=4096 for 5120x2880` surfaces and reported zero copied frames in
  two consecutive 10-second windows. SSH and guest mode query stayed live.
  Restoring logical 2560x1440 / physical 5120x2880/120 republished valid
  `geometry 5120x2880 fmt 8 pitch 5120`. The copy path is using output timing
  as source geometry despite macOS scaling. Evidence and next register-level
  discriminator: `findings/research/scaled-mode-copy-20261015.md` and local
  `run/scaled-mode-diag-20261015/`. Guest-requested stop produced
  CORE_PROBE_PASS/returncode 0, schema-2 guard release, original recovery
  incomplete, and separate schema-9 MODE2/no-queue
  `recovered/authorizes_launch=true`. Receipts:
  `run/candidate-515-attempt-d20261015154833-results/`. No QEMU remains,
  `power/control=on`.


At 06:48 UTC no macOS container or QEMU process remained. The independently
launched desktop attempt 514 `d20261015092721` (started 06:27 UTC) had already
ended at 06:35 UTC: INVALID verdict, shutdown **already-stopped**, separate
recovery recovered / authorizes_launch=true. This continuation did not signal or
alter that run. Earlier 514 `d20261015000754` reached desktop, poller about 17 µs/tick;
its already-stopped shutdown also does not prove native guest shutdown.

## Memory findings and limits

- **New leading mechanism: orphan display IH DMA.** After every QEMU process
  exited, one host artifact's buffered/mmap hashes changed with stable metadata;
  O_DIRECT and its reflink snapshot matched the original received SHA. The bad
  bytes decode as AMD 32-byte display interrupt records (client 4, source 0x57).
  The earlier TCG core has the same records around its corrupted tree pointer.
- Read-only BAR inspection found iGPU IH0 enabled and advancing ~120 entries/s
  with an identity default IOMMU domain, ring base 0x11f6e000 and writeback 0x11cf0000.
  Source-backed IH cleanup stopped the pointer. Existing recovery checks omit
  IH; their recovered receipts do not prove this DMA path was stopped. The
  exact physical-page/translation mapping and coverage of every panic remain open.
- Earlier Tahoe/macOS 15 GPU-less trials had APFS failures, panics and sparse
  image overwrites. Plugin/Lilu off, one vCPU, THP off and NVMe did not fix them.
  Canary/image/shutdown passes sometimes coexisted with earlier APFS errors.
  Full verified/retracted controls and first-panic timelines are in the audit.
- The original-binary one-vCPU TCG trial ended at its 6000 s deadline at
  00:40:23 UTC (SIGTERM), without a guest-command response or integrity/shutdown
  proof. Both TCG controls remain inconclusive for KVM; the eight-vCPU crash's
  corrupted host tree allocation now has matching IH overwrite evidence.
- Direct upstream KVM memory-slot and MMU invalidation controls passed under
  bounded user services. These short synthetic checks do not clear KVM/hardware.
- Fresh macOS 15 control `pcid-control-01`: only /dev/kvm, no TAP/DRI/VFIO;
  eight vCPUs, 8 GB, NVMe, THP off, Lilu/plugin off. All eight live CR4 values
  have PCIDE clear, yet SystemKC guest/upload hashes differ. Canary passed;
  failed identity gate, preserved capture and force-stop, no native shutdown.
  Active PCID tagging and the second NIC are not required for this disagreement.
  Full evidence: `memory-diag-20261015/continuation-01/`.
- `transfer-02` caught a correct C buffer before/after sending but a bad host
  artifact, followed by changing host cached contents after guest exit. Since
  IH containment, that cached SHA stayed fixed for 120 s. Fresh trials
  `transfer-03-after-ih-stop` and `control-02-after-ih-stop` passed canary/image
  checks with no recorded APFS integrity error/panic; both acknowledged native
  shutdown and exited 0. This is bounded containment evidence, not permanent
  crash/relaunch or whole-host memory qualification.

Earlier mislabeled one-CPU and THP controls had unapplied environment overrides;
the research note retracts those conclusions and gives verified replacements.
No KVM/host-kernel defect is established. Host AVIC/NPT or kernel changes require
explicit user instruction under the existing no-host-changes constraint.
IH shutdown, a separate VFIO descriptor owner and stopped-device MODE2/no-queue
recovery are implemented. The separate owner retains DMA mappings after
QEMU/container death until measured IH/display/GC/SDMA paths stop. Native and
abrupt-death runs plus post-crash integrity checks passed on this boot.
The sysfs group type is the default domain, not a live VFIO attachment query.

## Other remaining issues and delivery

Release 515 retains the delivered VRAM-pressure release (512), aspect-locked QEMU
window (510) and 120 Hz window-copy path (509). Audio gaps under ~120 fps window
compositing remain open; USB packet counters did not measure sample amplitudes.
The logical 2048×1152 QEMU-copy freeze is fixed in release 519. Safari fast-scroll audio
and slow manual QEMU-window resize audio are known lower-priority issues.

Added a scoped guest remap canary and image/hash details to compatibility mismatch
errors; rejection and identity gates are unchanged. The guarded release has
passed bounded local qualification and exact-commit hosted test/build CI on `dev`.

[Superseded diary](findings/research/status-archives/status-before-memory-audit-20261015.md).


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-517-results`
- Verdict: `INVALID`
- Boundary: `None`
- Post-run recovery: `recovered`


## One-command GPU test

- Output: `/home/user/macos-vm/run/candidate-518-results`
- Verdict: `CORE_PROBE_PASS`
- Boundary: `None`
- Post-run recovery: `recovered`
