# Current status — candidate 194 passed Metal compute/render; capture incomplete (2026-09-11)

## Admission control session 009 (2026-09-11)

This GPU-less session ran the same signed-v2 desktop helper under three
execution contexts (root, direct `gui/501` LaunchAgent, and a shell wrapper).
All three reached the helper's main path and then aborted while writing their
receipt: Foundation rejects `NSDataWritingAtomic | NSDataWritingWithoutOverwriting`
as an invalid option combination (signal `Abort trap: 6`). This is an
application bug, not evidence of AMFI or GPU failure. The exact captured
commands, launchd state, per-control serial offsets, and metadata are frozen
under `/home/bogdan/macos-vm/run/desktop-session-009/admission`; no GPU
attempt was consumed and the ledger remains **2/3**. The fix is staged in the
desktop-195 worktree: use `NSDataWritingAtomic` alone, then rerun the same
three controls with the rebuilt binary before any hybrid GPU launch.

## Hybrid preparation session 010 (2026-09-11)

A fresh GPU-less guest compiled the corrected existing-display helper
successfully. Source SHA-256 is
`ff150b488e7c978e9c7a6a729318913fe25cba2203d1baacd41a14bb73b1e652` and
binary SHA-256 is
`f4966b86f857558a4bf1a69af55b20f59a4ee7d4380d48f3f69247c2c07643f9`.
Preparation exited 0; no GPU launch was consumed. The guest was stopped under
the exact supervisor after preparation. The remaining launch needs a fresh
authority binding this pair to the Raphael registry, QEMU scanout, and cleanup.

The hybrid coordinator integration is now staged in development commit
`eea37e5` with helper/source coverage in `9fe2fcf`. It accepts a separate
`existing-display-production` profile, pins QEMU generic graphics only for that
profile, launches QEMU monitor frame capture under the same deadline, and keeps
compositor and physical-scanout provenance explicitly unproven. The combined
offline coordinator/helper suite passes **139 tests**. No hardware launch has
been performed with this profile yet; a fresh one-run card still needs to bind
the candidate-194 recovery receipt and the new hybrid identities.

## Desktop access sessions 006–008 (2026-09-11)

Session 006 used the clean candidate-194 supervisor, pinned image
`sha256:3a3c82c79bc4e73531f819ccdfa4053b3084efd7c1f645678dbf8b4b3a24369c`,
generic VMware graphics, and no VFIO/GPU argument. The user logged into a real
`bogdan:501` Aqua session. Through supported System Settings UI, automatic login
was changed from Off to Bogdan Popa and Screen Sharing was changed from Off to
On while Remote Management remained Off. The separate private autologin helper
was never run. Read-only verification reported `autoLoginUser=bogdan`, enabled
`com.apple.screensharing`, and a guest TCP 5900 listener. Exact-CID shutdown was
forced after a successful guest request. UI and shutdown receipts are under
`/home/bogdan/macos-vm/run/desktop-session-006-ui`.

Session 007 used the same pinned, GPU-less generic-display topology. Persisted
automatic login reached `bogdan:501` and `gui/501 session = Aqua` without input.
Supported Screen Sharing UI enabled legacy VNC password authentication using a
new, separate eight-character secret held in a user-owned mode-0600 file outside
the repository; no secret value entered command arguments or evidence. Access
remains `Only these users: Administrators`, which includes Bogdan but is broader
than the intended single-user scope. Remote Management remained Off. Guest TCP
5900 listened, but no host viewer/frame qualification was completed. Exact-CID
shutdown exited normally after the request. Evidence is under
`/home/bogdan/macos-vm/run/desktop-session-007`.

Session 008 used the same supervisor and pinned image with the actual headless
QEMU topology `-vga none -display none`, no generic graphics device, and no
VFIO/GPU argument. Persisted automatic login again reached `bogdan:501` and an
Aqua `gui/501` domain while the display count remained zero. Screen Sharing
listened on guest TCP 5900, and the host loopback path returned the exact RFB
banner `RFB 003.889\\n`; this proves the transport endpoint, not a desktop
surface or Raphael composition.

The pinned desktop helper source SHA-256 was
`b43ad3df9435c1094649b875f6ee0e815a2cdfa1a74b974f8cf90aac3998146c`.
The first guest compile succeeded, but the execution produced no desktop result.
Its `region 0, not code signed` log line does not establish rejection because a
known passing probe emitted the same warning. A reviewed v2 prepare then ad-hoc
signed and strictly verified a new binary with SHA-256
`78f2f596e86521137e21d80d78e030dec798b87da312053e235aa7ed60c5ca64`;
execution still failed before emitting a desktop result. The frozen raw serial
records `AMFI: ... is adhoc signed.` followed by
`AMFI: code signature validation failed.` No virtual display was created or
removed, so GPU-less display qualification remains incomplete. Exact-CID
shutdown was forced after a successful request. Evidence is under
`/home/bogdan/macos-vm/run/desktop-session-008`; the post-shutdown serial,
agent events, QEMU launch log, final supervision snapshot, and SHA-256 manifest
were frozen before any later launch. Sessions 006–008 were GPU-less and did not
change the **2/3** GPU launch ledger or the actual-GPU review count.

## Current authoritative state — first real Metal compute/render pass (2026-09-11)

The launch ledger is **2/3** on fresh boot
`f828eb26-9cb7-4fac-bff2-bc87515fa2ba`: candidate 193 and candidate 194 used
one launch each. Candidate 194's authenticated native Metal probe
is the first demonstrated real GPU compute and offscreen render/readback pass:
three randomized compute command buffers checked **196,608 values**, and one
render/blit/readback command buffer used a private 64x64 render target and
checked all **4,096 pixels**, for four completed buffers total. The passed-through
device was reported as `AMD Radeon Navi23`, Metal 3, registry ID `0x1000002ed`. The exact
supervised CID was
`71bdfae412a34c7b2dee7303ffa71e8ef210089d6a6829ecc8415d932077304d`;
its recorded QEMU topology contains only VFIO `0000:7b:00.0` at PCI slot 6,
`-vga none`, and `-display none`, with no generic graphics device. Serial binds
the Navi23 driver to `[0:6:0]` / `S30@6`.

The frozen overall verdict remains `INCONCLUSIVE` at
`identity_or_route_missing` with `capture_loss`. Snapshot 6 ends mid-transport
line and is not accepted as a complete functional capture. Read-only replay of
the immutable prefix through checksum-complete snapshot 5 (`count=293`, 251,788
bytes, SHA-256
`7007c42cc05df47ed588a1e7b1790dce055b8b88aa9ad7f786dbf24b1bfbc880`)
produces valid `PROBE_NOT_RUN`; pairing those strict-prefix events with the
authenticated probe produces valid `CORE_PROBE_PASS`. This is forensic support
for the independent functional result, not a rewrite of the frozen verdict or
acceptance of the truncated tail. Snapshot 5 records the mode-5 gate, route,
and consistent mode-5 bulk-update summaries, but contains no A1
`map-process-root` sample. Do not claim that the A1 correction caused the pass.

Recovery completed once as schema 6 `recovered`, `authorizes_launch=true`: two
active MEC HQDs were dequeued with no timeout or forced-inactive fallback, final
active state was zero, the persistent reservation remained unchanged, and no
new host-kernel messages were recorded. This establishes cleanup after this
successful workload once; it does not establish repeatable cleanup, guest-crash
cleanup, or QEMU-close cleanup.

Candidate 194 demonstrably crossed the first-command-completion issue. The
historical **14-cycle unresolved execution streak is closed**; the interim
15-cycle statement was superseded because it counted the successful attempt as
another unresolved failure. The mandatory-review batch is **1 attempt** (`194`).
The new desktop-presentation and lifecycle issue has GPU-less discriminator
runs (inventory 003 and desktop sessions 004–005); they do not consume the GPU
launch ledger. The launch
ledger is **2/3**. No GPU retry is authorized; the remaining work is visible
desktop presentation followed by repeatable normal, guest-crash, and QEMU-close
cleanup qualification.

The mandatory Astra review is complete. Astra report SHA-256 is
`ecfb42b240ae15be0ddc68626191462919c86b1ea6732ad04ae58e089a42481b`.
P0 is validated: the production formatter emits the active mode, with positive
`PROBE_NOT_RUN` and negative unchanged-193 classifier coverage. P1 decision
receipt preservation is also validated. The final full Python suite ran **735
tests with 3 skipped**; the focused classifier/integration coverage is **86
tests**, the affected C++ sanitizer fixture passed, and exact-KDK preflight
passed. Candidate 194 is metadata-prepared with source digest
`c798dfd66c14c5d14160141586062ea5624f5314d14604f9d12abb40945e202d`. The
candidate-194 debug-symbol build completed once from clean commit `52c7517`;
archive SHA-256 is `98ce668b16af1cfc7d2f4374bd037749c243572633169ca90b1018e03d74db80`,
executable SHA-256 is `7623059a5ea035f929f9e10d6aad35cda698d643bbe2a2801a649eeed19fd24e`,
and the canonical identity record SHA-256 is
`0cd4a829e37cee90c29b82a85f36e24fa2b60ea94c0ea10488bff3d83926ed93`.
Candidate 194 was staged and its one-run policy was sealed, but the first
invocation was refused before ledger reservation because the coordinator
checkout was dirty (`source_clean`). The frozen output is
`/home/bogdan/macos-vm/run/metal-028-194`; its verdict is
`INVALID` at `identity_or_route_missing` with two `capture_loss` records and
`warm_reuse=not-attempted`. At that refusal the ledger remained **1/3
launches**, and it did not count as a GPU attempt. Any reviewed retry must invoke
the repository
`tools/experiment.py` from the clean candidate-194 worktree, with a fresh
manifest/output/policy binding; the failed output and existing authority are
immutable evidence.

The resealed candidate-194 run is frozen under
`/home/bogdan/macos-vm/run/metal-028-194-resealed` with run ID
`1f0649a6a31fbf73162696891cf5b9bc`. Verdict SHA-256 is
`01987196b14c47057672b690715ca7e01cf9dc9a5ffd00d5aaa32ad4b5bdaacc`, probe
SHA-256 is `339c0e652308d9af57ba948045b86196b11d0da74fc7cc5e27d11eae25b4a8c9`,
recovery SHA-256 is
`389631b0041fa92e38e7f458bfeb813851540a798cd4a74934e2ab0dd6924f8a`, and
serial SHA-256 is
`4b7f3514a8bffa2848ca325794decc4bc6b250de0b43e71314dd92b1fc67502c`.
Critical SHA-256 is
`43a7dd59487fad6264c28d8f5b349d66709d08b08066ae3fb266122f8be50cb5`,
manifest SHA-256 is
`99e56a676c588fa44d6b5210ca899c9334e73a154f8c568fb96d92c8ef3b477b`,
and the probe source SHA-256 is
`f0fc0ced81fe70732c3491cff1557a83d85c9ccb8c18a6303f9070ae1f969d77`.
The coordinator verified guest build `24G830` and probe binary SHA-256
`1637e4b31bca0a1bdc400f96e34b344a823de1b408a8d1677d6bcca475c8c787`
immediately before nonce-bound execution. The result contains exactly one
matching `passed=true` record and `RGPU_EXIT 1f0649a6a31fbf73162696891cf5b9bc 0`.

The authorized GPU-less virtual-display inventory is frozen under
`/home/bogdan/macos-vm/run/desktop-inventory-001`. It used a clean candidate
194 supervisor with `GENERIC_GRAPHICS=off`, `GDB=off`, custom boot disk, stock
NVRAM, `-vga none`, `-display none`, and no VFIO/GPU arguments. The guest agent
was ready and the inventory binary exited 0, but validation failed closed:
WindowServer was running, all four `CGVirtualDisplay` classes and required
selectors were present, while the online display list was empty and
ScreenCaptureKit preflight was false. Exact-CID shutdown sent the guest request
and then forced the container within the 20-second grace bound. Inventory
runner SHA-256 is
`be7c7da7589544e761bd58252757d71bbb364530fc2f5b64b17cfb4833e37d25`; source
SHA-256 is
`1cffd80d3ab1fa5a1011a868bcae9df7663a9c8a8a4f48ba9ff6237438d9f833`.
This GPU-less run did not change the GPU ledger and does not establish guest
desktop presentation.

The inventory archive includes the supervisor state, launch CID, raw QEMU
launch log, serial log, agent-server events, and inventory identity/output/error.
No standalone shutdown-result JSON, running-identity snapshot, or host-after
snapshot was emitted by this direct supervisor/inventory procedure; the
shutdown outcome is preserved only in the exact-CID shutdown console result and
the guest serial log. Post-cleanup inspection found no active VM/container.
The GPU ledger remains 2/3; its existing JSON was not modified by this
GPU-less run.

### GPU-less virtual-display inventory 002 (2026-09-11)

A second authorized GPU-less inventory used CID
`324f9255da5f87c61d6f8fa3f00309608bfeede3985063dbc462536361d48114` with the
same no-GPU topology (`-vga none -display none`, `GENERIC_GRAPHICS=off`,
`GDB=off`, custom boot disk, stock NVRAM). The guest agent became ready and
the corrected inventory binary completed its ABI inventory, but its one bounded
create/remove lifecycle failed closed: `created=false`, `added=false`,
`settings_applied=false`, and `removed=false`, despite `cleanup_complete=true`.
The runtime inventory again reported no online displays, with capture blockers
`console_session_unavailable` and `screen_capture_permission_absent`.

Evidence is frozen under
`/home/bogdan/macos-vm/run/desktop-inventory-002`, including the live running
identity, exact QEMU argv, both raw command outputs, supervisor state, raw
serial/launcher/agent logs, exact shutdown return, host-after snapshot, and
ledger-after copy. Shutdown returned `forced` after a successful request with
no error, and no container remains. The GPU ledger remains 2/3 and its
SHA-256 is `4300754fb8ed2ad909b733381a28c09f15532b3067cbef75bfbe9d392bfcf7f4`.
This GPU-less result does not establish virtual-display creation or desktop
presentation.

### GPU-less virtual-display inventory 003 (2026-09-11)

The third authorized GPU-less inventory used CID
`f7ec297176883e19a91d2d77a968efe1fe15f13ffa05227c2a5091c116a46fed` with the
same reviewed no-GPU topology and clean candidate-194 supervisor. The ABI
inventory passed (`display_list_error=0`, all reviewed classes/selectors
present, WindowServer running), but the single bounded Chromium-compatible
create/remove attempt failed closed. The raw result had `abi_valid=true` and
`cleanup_complete=true`, while `created=false`, `settings_applied=false`,
`added=false`, `active=false`, `removed=false`, and no display ID. The guest
also reported no console user/session and no online displays; the runner
rejected the lifecycle record as incomplete. The runner source SHA-256 is
`8acdd6e93069aa3ba9221b22da80be1285c647dafef10998a09635068dc7357a`, and its
Objective-C source SHA-256 is
`48b406afff819bf2c4b2db454fa670ebbbc5b8f194cc7f134e7ddfe3dd187ff7`.

Evidence is frozen under
`/home/bogdan/macos-vm/run/desktop-inventory-003`, including the fresh
identity, inventory/create outputs, raw serial and agent logs, running
supervision state, exact shutdown receipt (`forced` after a successful request),
host-after snapshot, and unchanged ledger-after copy. The ledger remains 2/3;
this GPU-less run is not an actual GPU experiment and establishes neither
virtual-display creation nor desktop presentation.

### GPU-less desktop session inventory 004 (2026-09-11)

An authorized software-only session used the clean candidate-194 supervisor
with a 600-second bound, `GENERIC_GRAPHICS=off`, `GDB=off`, custom boot disk,
stock NVRAM, and no GPU/VFIO arguments. CID
`19880f6f12f9733a03a082e8b2fbe596f13dd5a5c7f01ccf57116dcdbf7f118a` was
shut down once by the exact-CID procedure (`forced` after a successful request,
no error). Frozen evidence is under
`/home/bogdan/macos-vm/run/desktop-session-004`, including supervisor state,
running state, QEMU launch log, serial logs, agent events, nonce-bound query
outputs, parity inventory, shutdown receipt, host-after snapshot, and ledger
copy.

Read-only account discovery identified `bogdan` UID 501. The attempted
`launchctl print gui/501` command returned exit 127; because the command's
availability/path was not captured, this result is indeterminate and does not
prove that the GUI domain is absent. `loginwindow` and `WindowServer` were
observed. The parity inventory passed ABI discovery but reported
`console_uid=0`, an empty console user, no online displays, and
`screen_capture_preflight=false`. No login, credential, TCC, display
configuration, or GPU operation was performed. The GPU ledger remains 2/3 and
this run does not count as an actual GPU experiment.

### GPU-less desktop session inventory 005 (2026-09-11)

An authorized software-only prelogin session used the clean candidate-194
supervisor with the same reviewed no-GPU topology and a 600-second bound. CID
`9d45de0accd2dd7fc80a7dba250557926e248bc9545f22b2d1c57241230ca1b6` was shut
down by the exact-CID procedure: the guest request was sent, then the
container was forced after the request returned no error. No VM/container is
currently active. Frozen evidence is under
`/home/bogdan/macos-vm/run/desktop-session-005`, including the launch and
supervision state, serial and agent logs, session/context queries, login
prerequisites, virtual-display inventory/create outputs, shutdown receipt,
and host-after snapshot. The live ledger remained unchanged at **2/3**; no
ledger-after copy was emitted in this archive.

The query captured the actual `/bin/launchctl` path (`which` exit 0). Account
discovery identified `bogdan` UID 501; `user/501` exists in `session = Background`
with exit 0, while `launchctl print gui/501` returned exit 125 (`Domain does
not support specified action`). The context query observed the WindowServer
daemon as a system launchd service (its actual process user is
`_windowserver`, user ID 88), while the console remained UID 0 (`root`). The
virtual-display inventory reported `window_server_running=true`,
`console_user=""`, `console_uid=0`, and no online displays; the create result
was ABI-valid but failed closed with `created=false`, `settings_applied=false`,
`added=false`, `active=false`, `removed=false`, `display_id=0`, and
`display_init=nil`/`serverDisplay=0`. The raw WindowServer log contains explicit
prelogin access errors: “This user is not allowed access to the window system
right now.” The corrected log completed with `status=0`, `truncated=0`, and
`bytes=25672`.

Prerequisite checks reported FileVault Off, no DEP or MDM enrollment, no
`autoLoginUser`, and no `kcpassword` metadata. This run is GPU-less, does not
consume the GPU launch ledger (still **2/3**), and provides no desktop proof.
The next planned discriminator is a reversible guest login validation followed
by the same session/display checks; it has not been implemented or run.

### Offline CR2 producer-quiesce implementation (not deployed)

The frozen candidate-194 result above is unchanged. Its 335,062-byte critical
capture has six checksum-clean `RGPU_END2` lines through snapshot 5
(`count=293`), followed by snapshot 6, which ends mid physical line at
`r=00a3 p=03/06 `. Recovery-only replay records 502 checksum-valid chunks in
that open attempt. The agent log places successful probe completion at
05:49:43.682660Z, the native shutdown request afterward, and guest exit near
05:49:53Z. The truncated bytes are observed evidence; expiry of the worker's
10-second inter-snapshot sleep during shutdown is an inference from those times
and the producer code, not a guest-timestamped causal observation.

An offline, opt-in producer lifecycle handshake is now implemented and reviewed.
It requires both the exact manifest/card selector
`"critical_replay_quiesce":{"version":1}` and boot argument
`rgpucr2quiesce=1`; historical manifests retain the prior path. After a probe,
the coordinator writes a CID/build/run-bound request for the existing full-duplex
COM2 collector. The collector sends a seven-byte RX token. The worker polls at
snapshot boundaries and during its existing sleep, emits a fresh snapshot, and
acknowledges only when formatter/UART completion succeeds and record count,
drop count, and truncation count remain unchanged. A token received during an
ordinary snapshot requires a newer sample. The single ACK binds build,
snapshot, and count, then the replay worker terminates. The coordinator waits
only to the existing deadline-minus-25 cleanup boundary, applies the unchanged
functional parser, preserves the full raw stream, and later requires its exact
length and SHA-256 to remain equal to the acknowledged capture. Missing,
conflicting, nonconverging, or post-ACK output fails closed; host-fault,
shutdown, recovery, and exposure limits are unchanged.

Focused validation passed 123 Python experiment/transport/collector tests, the
UART C++ fixture, and a final 23-test targeted rerun including request-unlink
races and bytes after ACK. A scratch-only cross-build linked an x86_64 Mach-O
kext bundle with SHA-256
`e5264d3042d56e80670454597020a7d4bc7cb0d64ed1b300a04adb39e1ed222f`;
only the existing warning classes appeared. No release build, staging, VM/GPU
run, ledger use, or hardware validation was performed.

The previously missing end-to-end transport lifecycle coverage now passes in a
software-only QEMU guest with no VFIO, host device, or network. The source-built
guest uses the production `CriticalUart.hpp` RX parser and ACK writer; the host
uses production `sercat.py` and `quiesce_critical_producer`. A request delivered
mid ordinary snapshot produced a newer checksum-complete snapshot
`0x01020305` with 512 records, one matching ACK, and no later bytes. An
independent ignore mode proved actual token receipt on COM1, withheld the ACK,
hit the existing helper boundary, removed the request, and stopped the exact
software QEMU instance. The source/maximum-payload and two lifecycle cases pass
4/4 in 6.457 seconds; the affected Python set passes 23/23 and the UART
ASAN/UBSAN fixture passes. All three freestanding guest modes compile with
warnings as errors, and `_start` disassembly begins directly with `cli`, stack
assignment, and `call guest_main`, with no compiler prologue. CI installs QEMU
and multilib explicitly, requires both lifecycle tests instead of permitting a
skip, and now runs the UART fixture explicitly. Candidate/card metadata and a
coordinator final audit remain required before deployment. The current ledger
stays **2/3**, the mandatory-review batch stays **1 attempt**, the closed
historical execution streak stays closed, and desktop-presentation/lifecycle
testing remains **0 failed attempts / not yet tried**.

### Candidate 194 debugger limitation and result decision tree

`GDB=on` keeps the authenticated loopback debugger endpoint available; it does
not mean candidate 194 includes breakpoint capture. The existing coordinator
blocks in the Metal probe and begins shutdown immediately afterward, while
`probe.json` is written only after shutdown and capture collection. The bounded
GDB runner also reserves 25 seconds for cleanup, requires at least 10 seconds
for capture, offers only `entry-update` and VMID1-specific root scenarios, and
has no A1 or arbitrary-client scenario. There is therefore no qualified, safe
post-probe debugger window in this run. Do not attach manually after a probe
failure or describe candidate 194 as breakpoint-debugged; a future post-probe
lifecycle requires separate implementation and GPU-less qualification.

After a frozen run, use `python3 tools/classify-run.py <run-194-output>` and
interpret only checksum-valid complete CR2 evidence. The bounded driver records
provide the current discriminator:

- A complete probe pass is the functional result; preserve its completion,
  compute, render, readback, and cleanup evidence independently of A1 samples.
- A failed probe with a valid `map-process-root` record showing native MC root,
  physical final root, header `0xc00ea100`, `return-valid=1`, `repaired=1`, and
  reason 13 demonstrates that the A1 conversion ran. If a coherent fault-walk
  group also selects a physical-root client, investigate table, invalidate, and
  completion ordering next.
- If A1 was repaired but the fault-selected client still reports an MC root,
  investigate another writer or a later overwrite. The selected client comes
  from the coherent `fault-walk` status/VA group and may be any VMID 1 through
  15; the worker-time walk is not fault-time causality.
- An already-physical A1 root is a valid no-op and does not require repair. An
  absent sample or a bounded drop summary does not prove that A1 did not run.
- Identity, route, mode, malformed guard, or capture refusal leaves the A1 GPU
  hypothesis untested. Preserve that observation failure without inferring a
  Metal or root result.

## Historical candidate 193 / metal-027 offline preparation (2026-09-11)

The host is on fresh boot `f828eb26-9cb7-4fac-bff2-bc87515fa2ba`; the launch
ledger has **0 launches consumed**. Candidate 193 / metal-027 is being prepared
offline with mode 5, preserving the reviewed mode-4 conversion behavior and
the candidate-192 headless, dynamic-GDB, `GENERIC_GRAPHICS=off`, 180-second,
and unchanged 45-second probe settings. Handoff verification is pending; no
launch is authorized.

Offline source for the next candidate adds explicit `rgpuvmroot=5`: it retains
all mode-4 contiguous-entry conversion and repairs the independent MES A1
MAP_PROCESS page-table-base field from the published MC aperture to the physical
aperture after native packet construction. Candidate 192's frozen VRAM fields
and exact KDK code support the hypothesis that native can leave an MC-valued
root unchanged, while Linux GFX10 supplies the matching hardware-PDE conversion
rule. The actual A1 output remains unobserved; this is a source-qualified
hypothesis, not demonstrated GPU progress. The full Python suite passed 728
tests with 3 skipped; focused classifier tests pass (82), all 17 VM diagnostic
sanitizer fixtures pass under ASan/UBSan, exact-KDK
preflight passes including the A1 constant/prologue/route/callback-order guard,
and a scratch-only cross-build produced an x86_64 Mach-O kext bundle (SHA-256
`ea722df7aa486ecc63a2526e26010c8a7e352c7a7d7c01bdde74f3bce740163f`).
The reviewed staging transaction completed with run ID
`a02f2b4e09e1a0319615d410c6965afb`, nonce words
`3576105534214582176` / `18111954628853896598`, and staging SHA-256
`d4e840c1a2ab0287d4eef5582fd5dd286c1cbee47eac61c65e2c4036816efd89`.
The prepared manifest is
`/home/bogdan/macos-vm/run/metal-027-193-manifest.json`, SHA-256
`8b006e227052915c6c92f0202f963fe683363547cccfde3293e1384f9f32d882`.
Its source, archive, KDK, harness, boot, headless-Lilu, and mode-5 pins match
the reviewed candidate. No VM launch or GPU cycle has occurred; no launch is
authorized pending handoff verification.

## Candidate 193 / metal-027 hardware run (2026-09-11)

The single authorized first launch on boot
`f828eb26-9cb7-4fac-bff2-bc87515fa2ba` completed the bounded procedure. The
classifier verdict is `INCONCLUSIVE` at `identity_or_route_missing`, with
`capture_loss` evidence; no Metal probe result is valid. The run consumed
**1/3 launches** and advances the unresolved GPU-execution streak to **14
actual cycles** and the post-Astra batch to **3 attempts** (`191`, `192`,
`193`). No retry or debugger attachment is authorized; mandatory Astra review
is now due before another GPU attempt.

Run output is frozen under `/home/bogdan/macos-vm/run/metal-027-193`:

- verdict SHA-256: `01987196b14c47057672b690715ca7e01cf9dc9a5ffd00d5aaa32ad4b5bdaacc`
- serial SHA-256: `27514348eb803178ab0b4c7c282de7d59ab643e24e794443686a1f64b4e304d8`
- critical capture SHA-256: `d8b7f2eb5ca1d1a0d1a5b9130aad440200068f6629169854b2d5526d4aa49130`
- recovery SHA-256: `b4d05ccc18f9305dcf42b5b3f9819821333e84851d9b80b4dd4c83c37cda06ba`
- host-after SHA-256: `ed791c4c9324466410aabec95f320beaadedf049b2951450873f01682cee34ef`

Recovery completed as `recovered` with `authorizes_launch=true`, no active VM,
VFIO retained, and no reset methods. The observed entry gate reported mode 5,
while the emitted entry-update summaries remained mode 4; the resulting
identity/route classification is an integration failure requiring offline
repair before any further run.

## Historical candidate 192 offline preparation handoff (2026-09-11)

The host has rebooted into boot `ac38a04c-de54-43b3-8141-414d5ea8a459`.
At preparation time the same-boot launch ledger had **zero rows consumed**; no
GPU experiment had run on this boot, and host handoff authentication was
pending. Historical
candidate 191 boot `3bca3e47-1f28-4f78-af00-5dbf76b00620` remains exhausted at
3/3 launches. The unresolved GPU-execution streak remains **12 actual cycles**;
the review batch remains **1 attempt since Astra**.

Candidate 192 / metal-026 is prepared offline with the known candidate 191
custom-boot settings: headless Lilu, dynamic `GDB=on`, `GENERIC_GRAPHICS=off`,
180-second exposure, and the unchanged native 45-second Metal probe. Its scope
is worker-time observation of the actual faulting client VMID 1..15 using the
existing mapping behavior. Generic-client fault-walk records are conditional;
the card makes no claim that root, child, or prepared-request correlation is
complete. The current source-tree digest pinned by the card is
`e2eb4769e41af10dcbb48f315446030fdd8af0632fa5f6de8ec8f9abba630526`.

| Offline preparation | Result |
|---|---|
| Candidate/card | `1.0.192` / `metal-026` |
| Card SHA-256 | `6452f113812901ae1265f9c31f52e6dcabe727aa21c248e9a675124a691941da` |
| Metadata/stage tests | 48 passed |
| C++ VM diagnostics sanitizer fixture | passed (ASan/UBSan) |
| Exact-KDK preflight | passed (24G830; existing `kOffVmmInit` name skip) |
| Full Python suite | 722 tests run, OK (3 skipped) |
| Generic-client parser audit | passed (77 focused tests plus exhaustive-prefix coverage) |
| GPU cycles on current boot | 0 |
| Blocking issue | host handoff authentication pending |

## Candidate 192 / metal-026 hardware run (2026-09-11)

The single authorized first launch used run ID
`575d67d557b07f98b186c0cfb024fcbd`, supervised CID
`91a0836c3827fc755f040c1f1deacc8462f4951d6670e6292fe70ea2f323908e`, and
completed bounded shutdown; recovery remained incomplete. The checked verdict is
`EXECUTION_FAILED` at `first_submission`; verdict SHA-256 is
`307a429cd7fc6719b6284f5197b52e27542aea212409ac57dde01335c3bb7cd9`.
The unchanged native probe enumerated `AMD Radeon Navi23` / Metal 3, compiled
and committed, then timed out after five seconds with zero completed command
buffers, zero compute rounds, and zero readback pixels. Probe SHA-256 is
`d3c686614989146fee69029a0a6e2901da0f0a79e9b05debdfe2c1bc6bc146ef`.

CR2 capture completed as a valid terminal snapshot with 306 records and no
corruption. The frozen diagnostic group observed the actual client VMID 11:
status `0xb0093b`, fault VA `0x400300000`, worker-time root `0xf40b709000`,
stable context, relative two-entry walk, and absolute one-entry walk. This is
worker-time current-state evidence and does not prove fault-time root or child
causality. Critical capture SHA-256 is
`6cf7082b8f64ecdc0147eb9237f256dbade07843ebb72037a4098696c001cc66`;
recovery replay SHA-256 is
`175cac21a8c3a8f65d0bf81ab265ab99bf7b33d55123011f011c1d44355a918b`.

Recovery is `incomplete` with `authorizes_launch=false`; recovery SHA-256 is
`045f6daa72ca21d9c27161f6d908eb3a0d621f5122c961317e1748a5bfb0a4f6`. Host
after-state reports no active VM, `vfio-pci`, accessible pinned-awake device,
empty reset methods, verified watchdogs/capture/sleep inhibition; host-after
SHA-256 is `2be691de8bcc95bf658d8e2997f4b839c567e33f68f7bea21d5fc6e06749a203`.
The unresolved GPU-execution streak is now **13 actual cycles** and the
current post-Astra batch is **2 attempts** (`191`, `192`). No retry, debugger,
reset, rebind, or additional launch is authorized.

Candidate 192 offline build and preparation are complete. The clean detached
worktree is commit `4eaab5748f935fce785b286a0b9ab07194e59a86`; build ID is
`29a8fe9f66034d26bef5adf9f8b9c643`; source digest is
`e2eb4769e41af10dcbb48f315446030fdd8af0632fa5f6de8ec8f9abba630526`; archive
digest is `c79cc2e1705c33ef18bfc901ea7c629c21d178ad81b5dd2428d58c8b581ccb89`;
executable digest is `27fc7102fc57702d8966cc3d06fcf1f23c0e7c28f04dd3eaeab2e3518ca6f676`;
and executable/dSYM UUID is `aea42840cf6a3e81b5a6ba3fd4c762a5`. The canonical
build-identity record digest is
`930b4997535a9c63b4d312797b34ef22deee4a65ce78b1ff1be08ec5e22da9cc`.

The metadata-only staging record is
`/home/bogdan/macos-vm/run/candidate-192/staging.json`, digest
`4bcfd7d176b1fd5c445b40511faccfba86ddee5090c0722639c2c2d974f27671`, with
fresh run ID `575d67d557b07f98b186c0cfb024fcbd` and fresh numeric recovery
nonce words `10988695507096264023` / `13689857309117810353`. Preparation
produced `/home/bogdan/macos-vm/run/metal-026-192-manifest.json`, digest
`c9c2869b39f5982216c4ffa9e05a5db57f3c69ee59a3b429fccbef9579323c7c`, binding
the staged source, build, KDK, harness, ROM, boot disk, current boot ID,
`sercat.py` digest `3dd229f4ea4df1c0d3a9f3c5f50becd69b2664bf85ebe8c515893488ceaa4ad8`,
and the `GENERIC_GRAPHICS=off`, headless-Lilu, dynamic-GDB configuration. The
build manifest retains `physical_tested=false` as an artifact claim; candidate
192 has since run once on this boot, as recorded above.

The `MAP_PROCESS` address investigation has now identified the frozen serial
values: actual memory plus-`0x60` is `0xebc0000000`, plus-`0x50` is
`0xf400000000`, and plus-`0x58` is `0x840000000`. The native A1 packet root
remains unobserved. A conditional mode-5 A1 post-fill root-repair
implementation is under offline review only; it has not been staged, launched,
or tested on hardware, and no conversion fix or Metal success claim is
authorized.


**Desktop Metal remains unproven. No further GPU launch is admitted.** Candidate
191 demonstrated complete CR2 capture under real QEMU load, but the unchanged
native Metal probe timed out at its first command-buffer completion. Cleanup
left graphics retirement incomplete, and the prior candidate 191 boot ledger is exhausted.

## Historical review accounting through candidate191

The latest user instruction requires reasoning/source review after every three
actual GPU attempts, followed by a revised test batch. The Astra xhigh review
is complete in `report-astra.md` (SHA-256
`ded9fb9162731d48d90bbc3b3872d495e85b253a240f67b23da338681b1f27f1`).
The coordinator accepts its conclusions after checking the exact VMID1 mapping
arithmetic, probe implementation, capture/recovery evidence, and old boot logs.
Implementation-agent assessment and final independent integration audit passed;
see `findings/research/2026-09-10-astra-post190-assessment.md` and
`findings/research/2026-09-10-candidate191-integration-audit.md`.

- Unresolved GPU-execution streak: **12 actual cycles overall**.
- Last reviewed batch: **187, 188, 190**; 189 never exposed the GPU.
- Current batch: **1 attempt since this review: 191**. Its complete capture is
  meaningful transport progress, but its failed Metal completion does not reset
  the execution streak. A review does not erase the
  unresolved issue, count recovery as an experiment, or increase a boot budget.
- Current boot `3bca3e47-1f28-4f78-af00-5dbf76b00620`: **3 of 3 launches used**.

Candidate 191 / metal-025 kept the exact candidate-190 GPU source
SHA-256 `7515f121230fbd26e32b198bd622e106155708e4108d9def96dcc7daa9d173f3`,
the known-booting dynamic-slide configuration, headless Lilu, and `GDB=on`.
Its primary test was complete CR2 capture followed promptly by the unchanged
45-second Metal probe: three randomized compute rounds (196,608 values), four
command-buffer completions, and all 4,096 rendered/readback pixels. Identity,
native-start, capture, time-fit, 180-second exposure, and cleanup gates remain.
The probe did not pass, so it proved neither compute/render execution nor
desktop presentation.

No new GPU behavior is bundled. The host collector now drains independently of
its generation-tracked fsync worker; short writes, socket/disk failures and
final-sync timeout remain failures. The debugger derives its live serial input
from the exact supervised CID. These fixes have offline regression coverage and
candidate 191 demonstrated complete real Btrfs/QEMU capture. Synchronous file
writes can still contend with fsync.

The proposed early-GDB `slide=0` implementation was rejected before build or
hardware use and archived under `findings/research/blocked-early-gdb-2026-09-10/`.
The old failure's Darwin lines were copied from a prior launch; the actual
appended attempt failed boot-loader kernel allocation. Independently, the draft
omitted the demonstrated `0xe8000` kernel-collection placement. Qualify a
corrected nonzero-slide early rendezvous separately without GPU exposure; do
not make that unfinished tool the next functional test's prerequisite.

Candidate 191 was built exactly once with debug symbols from clean detached
commit `acbb6a8dc00775abccd2deb76c189f0a6c6f88bc`. The archive at
`/home/bogdan/macos-vm/run/candidate-191-dist/RaphaelGPU-1.0.191-experimental.zip`
has SHA-256
`a39419bac951e7e67538eb528347a136f5c988ed1f9dc46be6f7916f79bdad01`.
Its executable SHA-256 is
`54a72a855c9096a5bd7e158aca4c5501a5ac661e93f40631bf62ae76141ff235`,
build ID is `fb72743f19c6425f8a850da877d28df4`, and executable/dSYM UUID is
`3208f400ebfd32e599bdfd665ebbc1fc`. The extracted build manifest SHA-256 is
`1ccfc0a151a3db0009d440f344fb5a6fc6bfd3bf91c362aa422e56d28b543b28`;
the build log SHA-256 is
`14c652af4fcdfeaafe8a7d0d1b8d4a6e8598f53ea93faa1cb08938a4e52d6fd4`.
The identity record at
`/home/bogdan/macos-vm/run/candidate-191-build-identities.json` has SHA-256
`58c8793c1af850a94299f3919ed39d5dc72f9ea5abda75007548163d7ca46dba`.
It pins the exact SDK, Lilu, firmware, headless-Lilu, source, private debug-script,
archive, manifest, executable, dSYM, and log identities. Canonical inputs matched
before and after the private debug build, and the source hash remained the exact
candidate-190 value above. Archive checksum, Mach-O, plist/manifest, and matching
dSYM UUID validation passed. Exact-KDK preflight passed all route, constant,
recovery, callback, ABI, and byte-pattern gates; the focused release and current
normal-GDB suite passed 32 tests. The rejected early-rendezvous generator was not
used and remains only in its archived patch.

The first staging request refused before writes because the initially generated
identity record used noncanonical field names (`candidate`, `archive_path`, and
`manifest_path`) instead of the staging schema's `version`, `archive`,
`build_manifest_sha256`, `worktree`, and `extracted_candidate` fields. That exact
rejected record is preserved as
`/home/bogdan/macos-vm/run/candidate-191-build-identities.rejected-schema-91cf3399fb8a8e946fa14849dcb0242f07f13e2f16ac480670c8463770ea86d1.json`,
whose SHA-256 is the embedded `91cf3399fb8a8e946fa14849dcb0242f07f13e2f16ac480670c8463770ea86d1`.
The corrected canonical record was derived from the unchanged existing build;
the actual `verify_build_inputs` staging validator accepts every required field,
artifact hash, manifest/source binding, debug-symbol identity, archive checksum,
and pinned Docker image identity. No rebuild, staging write, launch, or GPU cycle
occurred during this metadata correction.

After the final generic-fault diagnostic patch, Python discovery ran 719 tests:
`OK (skipped=3)`. Independent integration review found no blocker. The
current-source exact-KDK preflight passed route ownership, constants, prologues,
recovery-v2/v3 ordering, VM callback/entry/correlation, pointer-width ABI, and
all eight exact byte-pattern checks; it retained only the existing explicit
`kOffVmmInit` symbol-name skip. All 17 C++ sanitizer fixtures passed on the
prior candidate source. The subsequently changed VM diagnostic source and its
fixture were rerun alone under the sanitizers and passed; the other 16 fixtures
were not rerun on this current tree. This final validation performed no build,
staging, hardware operation, or GPU cycle. The earlier
726-test Python qualification included the subsequently archived early-debugger
draft and is historical; the candidate 191 hardware run is counted above.

## Candidate 191 execution and recovery evidence

Frozen experiment: `/home/bogdan/macos-vm/run/metal-025-191`, run ID
`20187457d3e5ad837617f89efa477219`, supervised CID
`7b21158bcb22841ad70f017dbba7ccbbff0c2f5b3533326787f4f78a39f31b38`.
The authoritative manifest SHA-256 is
`8271c546213e449d73c0ef4ae2e6b8fb5b6ebb22fdbe6d6f4a5f88e25127c1d9`;
the one-run policy and activation SHA-256 values are
`06e5e008f59a93b5d26b8f6fe19fc8104985b2ad938a638ad6532ea466d3e3b6`
and `d85618767dbb9927d799f67318e372406853ce843fe8f688e72a621b9721966d`.
The ledger consumed its third and final row. No debugger, retry, extension,
reset, or driver rebind occurred.

The strict native probe enumerated `AMD Radeon Navi23` with Metal 3, compiled
the shaders, entered compute and committed the command buffer. It then reported
`GPU completion timeout after 5 seconds`, with zero completed command buffers,
zero compute rounds and no render readback. The checked verdict is valid
`EXECUTION_FAILED` at `first_submission`; its SHA-256 is
`b8c3f6ba481f07104f523eab74f68c9c707d72e578f0551ab55772a252a66d63`.

Offline analysis decoded the retained `0xb0093a` fault at `0x400300000` as a
VMID11, CID4/CPF read mapping fault. The existing two-slot recorder discarded
it because it accepted only VMID1 and the worker always read context 1. The
approved observation-only fix now accepts client VMIDs 1 through 15 within the
same combined two-slot bound and selects the decoded context's existing
control/PTB/start/end bank in the worker. The callback still copies only status
and address; it adds no MMIO, GPU write, route, or deadline change. VMID1 parser
kinds remain compatible, generic clients receive bounded typed records, and
the worker still labels its context and table observations as after-latch and
non-atomic. Sanitized C++ diagnostics and 77 parser tests passed, and replaying
the frozen 191 evidence retained `EXECUTION_FAILED` at `first_submission`.
Per-client prepared-request correlation remains pending because the current
sequence and storage are VMID2-owned; no root or entry conversion defect has
been established. This offline change has not been built, staged, or used on
hardware. See `findings/research/2026-09-10-candidate191-fault-analysis.md`.
The probe record SHA-256 is
`c69369703d7b26f1495ff1e3ffafa7d16d507d6c4413288d6b4aa31438e3a665`.

Unlike candidate 190, CR2 capture completed under the real workload. The
560,666-byte `critical.txt` has SHA-256
`d3ac2d3ba32dc9308943846b58d73ef3f36935bbc4d37c891cc7d8093670bd71`;
the 423,512-byte `serial.txt` has SHA-256
`5c791de22e64dbe0d8e013a9baa2dd247ba45d64c87dc9614bd2b0b2e26e562d`.
Recovery replay accepted snapshot 7 with 300 records, zero corrupt lines, no
incomplete snapshot and no open attempt. It preserves the native VMID2 repair
to root `0x84b6f3000`, complete mapping walks, submissions and the later fault at
`0x400300000`. The replay SHA-256 is
`063fa53cdabd29dbaee58bf535048076900b294bead79d93b57e951ac093d004`.

Recovery did not complete. Schema-6 `recovery.json` reports `incomplete` and
`authorizes_launch=false`: host KIQ did not consume graphics `UNMAP_QUEUES`, its
write pointer did not clear, and `gfx_retirement_confirmed=false` and
`gfx_ring_clean=false`. Active queues reached zero without a dequeue timeout or
forced-inactive fallback, and the graphics-pipe proof completed, but those facts
do not weaken the failed final gate. Recovery SHA-256 is
`0d5420be9c85a5bc22ef43f166ec14203ddb70448c4e059866227add594b864e`.
Shutdown was forced after the bounded guest request because no ACPI grace
remained. Host-after reports no active VM, `vfio-pci`, an accessible pinned-awake
device, active sleep inhibitor and verified watchdogs; its SHA-256 is
`baaaa152974422b2a42d3efbe839ef154778ca2456ae9e043edd0ee0210366b0`.
Incomplete retirement and the exhausted ledger block all launches and cleanup
retries.

Two prelaunch corrections remain in the audit trail. The first staging attempt
rejected a noncanonical identity schema before writes. The corrected identity
record SHA-256 is
`58c8793c1af850a94299f3919ed39d5dc72f9ea5abda75007548163d7ca46dba`.
The first prepared manifest then exposed the old live collector SHA-256
`9d386cd3081e3b08dfb1354cb2645609b73840b488d485a4ce2df3a6d7bb759e`.
That manifest is preserved as superseded with SHA-256
`ffdbcf8304937a6d56c21462e75b0a5c0e0f4fef5c8dc2a6aafb59dfaab60547`.
Only `sercat.py` was atomically deployed, with reviewed SHA-256
`3dd229f4ea4df1c0d3a9f3c5f50becd69b2664bf85ebe8c515893488ceaa4ad8`,
before sealing the authoritative manifest.

Although candidate 191 retained `GDB=on`, attaching after the real probe failure
was unsafe within the bounded shutdown and cleanup sequence. The forced shutdown
had no remaining ACPI grace, so there was no authenticated post-probe debugger
window. The rejected early-rendezvous design remains research only. Any future
debugger experiment needs a separately qualified rendezvous and cannot bypass
the current recovery and ledger blocks.

Concise notes: `findings/experiments/metal-025-191/notes.md`.

## Candidate 190 execution and recovery evidence

Frozen experiment: `/home/bogdan/macos-vm/run/metal-024-190`, run ID
`3ffc5f3dbec53665214863ed91fee0e7`. Build commit
`c2e22b813eb76cd0d84b75564f0294514adf96ec`; build ID
`f504d465bddf4a0aa0edcc9b57d2b4ef`; executable/dSYM UUID
`8a78c544be033f7a96de3de39639f423`; executable SHA-256
`52d9984e59e9ad098e1f03028f651425493ac6f1775b2463ecf7b40f450e048f`.

CR2 completed only snapshots 0–3, then transmission failed on later attempts.
The original verdict and recovery.json remain INVALID/failed, respectively.
GDB authenticated the kext but attached late and obtained no selected wrapper
hit; bounded fallback detach succeeded. Serial reached `submit=660/660/0`
versus 188's `249/249/0`, with mapping/prepare errors 6/2. These are CPU calls,
not GPU completions; no retained VMID1 fault is not proof that no fault occurred.
The native Metal probe did not run.

A separately reviewed extractor recovered nine identical checksum-valid
OWNED/ACTIVE/VALID record sets from incomplete snapshots. Those records seeded
unchanged live BAR authentication, including exact ownership/pool/lifetime
readbacks before scratch writes. One authorized recovery then dequeued two
active queues with no timeout or forced-inactive fallback, retired graphics via
host KIQ, passed final CP/graphics/SDMA gates and confirmed PSP ring destruction.
No new kernel messages or implicit reset were reported. No VM remains; the
same-boot VFIO, watchdog, capture, device-awake and sleep-inhibition checks pass.

Canonical receipt:
`/home/bogdan/macos-vm/run/vfio-recovery/3bca3e47-1f28-4f78-af00-5dbf76b00620/3ffc5f3dbec53665214863ed91fee0e7.json`
SHA-256 `82560e48da2e6fb4300f5b0095e821d3da404d170108fd891ca7824aad49967a`.
It reports `recovered`, `authorizes_launch=true`; both schema-6 and reuse
validation with manifest context return no errors. The wrapper's immutable
failed result retained that receipt: its second validator omitted the manifest.
That call-wiring bug is fixed offline with a regression against the actual
receipt. No cleanup retry occurred. Reviewed proof v2, original wrapper result,
canonical attempt marker, and all frozen captures remain unchanged.

References: `findings/research/2026-09-10-candidate190-capture-audit.md`,
`findings/research/2026-09-10-candidate190-recovery-admission-audit.md`, and
`findings/research/2026-09-10-candidate190-recovery-independent-review.md`.

# Historical — pre190 offline mapping audit (superseded deployment/count text)

The working source now repairs eligible hub-0 client roots for VMIDs **1–15**,
instead of only VMID2. VMID0 remains on the separate legacy GART path. Existing
target, aperture, SYSTEM, known-attribute and address-range checks remain; no
new register writes or ordering changes were added. The decoder now matches
X6000's exact `info[0x24] == 1` reprogram predicate.

The failing regression uses the captured VMID1 root `0xf40b6ff000`, framebuffer
base/top/offset `0xf400/0xf41f/0x840`, and independently derived expected root
`0x84b6ff000`. It failed before the correction and passes afterward. This proves
the helper correction, **not GPU completion**. The exact X6000 prepare method
(`0x6249c`, root copies at `0x624ed–0x624f8`) preserves the supplied root in
prepared words at `+4/+0xc`; a live VMID1 call and subsequent execution still
need authenticated GDB capture.

Independent review passed. Verification: **689 Python tests, 3 skipped**;
the focused C++ fixture passed ASan/UBSan, and the nine-fixture C++ UBSan loop
passed. Full Python log: `/tmp/linux-vm-exact-unittest-20260910.log`, SHA-256
`06c0c54c15c40aae9a27de28845cca506d5920592179d98cabff258cc6474558`.
The private compile also passed, with route ownership verified. Output directory:
`/home/bogdan/macos-vm/run/offline-client-root-fix-20260910T184927Z`;
executable SHA-256
`1bc7979cd1980e789c350631f896c1babd8a3670d570e0e10f3bed84ceaaf90c`.
Its manifest correctly says `source_clean=false` and
`metal_execution_verified=false`. This is a compile qualification using the
existing version field, not a replacement candidate 188 or an admitted release.
Only explanatory comments changed after this compile; a future deployable build
needs a distinct reviewed candidate identity and its own source/build manifest.
No GPU cycle or staging was performed for this source correction. This historical
audit predates candidate 190; its old deployment and cycle-count statements are
superseded by the current candidate 190 runtime state above.

Research and limitations:

- [Apple documentation, open source and native binary comparison](findings/research/2026-09-10-apple-vm-source-comparison.md)
  separates public Metal resource semantics, generic XNU DMA mapping, community
  APU fixes and exact X6000 instructions. No reviewed public Apple source supplies
  the private GFX10 page-table implementation. NootedRed's framebuffer-offset fix
  is relevant precedent, not a compatible formula to copy blindly.
- [Exact Linux and native geometry comparison](findings/research/2026-09-10-linux-vm-exact.md)
  pins upstream source and distinguishes root/PDE conversion from the generic
  VRAM PTE update path. Apple emits BFS4 in the captured hierarchy; Linux's BFS9
  layout is not a drop-in replacement. TF remains an unsupported incomplete
  diagnostic boundary, not proof of an absent leaf.
- [Independent mapping/ABI audit](findings/research/2026-09-10-mapping-independent-audit.md)
  verifies native argument layouts and identifies tests that enforced the old
  VMID2 restriction. CPU reconstruction of MC pointers does not establish what
  the GPU successfully fetched.
- [Ordering and lifetime audit](findings/research/2026-09-10-vm-ordering-audit.md)
  finds no missing direct contiguous-update caller. Repeated aperture publication
  is a design hazard if values change concurrently; no torn tuple or stale-pointer
  use has been demonstrated. SDMA completion/fence/invalidate ordering is still
  unverified. VMID2 diagnostic correlation remains intentionally VMID2-only;
  it must not be reused as evidence for VMID1.

# Candidate 188 runtime state — continuation capture loss (2026-09-10)

Candidate 188 build, staging, and preparation completed on boot
`3bca3e47-1f28-4f78-af00-5dbf76b00620`. Build commit is
`5623d076a1855d7e33747c0c20de52a56f495993`, archive SHA-256 is
`3502ea8e0271e04733af236f6d980fdf61a7a3ea449da46ec9c3a0a50ae3f9f9`, and the
debug executable/dSYM UUID is `991549896385377caa3ade02134636af`. Prepared
manifest SHA-256 is `5f6dcff73c1b7df66ffe9b78459aed88178a3a33f213310d20c23c25d3f89673`;
staging record SHA-256 is `4df591ae25454e937fa15d6f266c23fed85796c4f1fdedcbf890fd82b86f1553`;
the single ledger reservation is run ID `cb1d0aadd8186205d867a23fe175c336`.

The first GPU-attached launch request stopped before Docker/QEMU because
`/tmp/.X11-unix/X0` was absent. No container was created, so no guest shutdown,
VFIO open, guest boot, GDB hit, or exposure occurred. Frozen evidence is in
`findings/research/2026-09-10-candidate188-prelaunch-evidence/`. A reviewed
bounded continuation then reached the guest but ended `INCONCLUSIVE` with
`capture_loss` because the CR2 transport line was incomplete. GDB reached the
target on QEMU CPU thread 8; CPU thread 1 reached the native-call breakpoint
next. The CPU-number check rejected the pair before capturing outgoing
arguments, so an argument mismatch was not established. The
uninitialized entry decision is invalid evidence and ignored. The same VMID1
fault was `0x101b3a` at VA `0x400580000`, PDE `0x200000084b700001`, leaf index
1408, raw entry `0`.

Continuation output is frozen at
`/home/bogdan/macos-vm/run/metal-021-188-continuation-output`; `recovery.json`
schema 6 reports `recovered` and `authorizes_launch=true`. This is a valid
cleanup receipt, not Metal execution success.

For the candidate 188 source, `src/GpuVmDiagnostics.hpp:266` excluded every
VMID other than 2 from root repair, and its prepare wrapper retained
observations only for VMID2. The current audited source is fixed separately;
the live
VMID1 root was `0xf40b6ff000` and remained unconverted. The CPU walker silently
translated its physical table address to `0x84b6ff000`; therefore raw zero at
leaf index 1408 is a reconstructed CPU view, not proof of the first GPU
failure, and the GPU may fail before the leaf. The next GDB target is
`wrapVmmPrepare`, guarded to hub 0 / VMID1 / reprogram 1, capturing original and
native info plus prepared root, then correlating the later PTB. Existing valid
recovery and cycle counts remain unchanged.

A separate private GPU-less qualification at
`/home/bogdan/macos-vm/run/headless-no-x11-qualification-20260910` first
booted Darwin 24.6.0 with `-vga none -display none`, without X11 or VFIO.
Kernel text was `0xffffff8009ee8000-0xffffff800a8e8000`. Its supervisor requested
shutdown and then forcibly stopped the exact container; the container and
capture units are absent. This verifies headless kernel boot and capture,
not Metal or graceful guest shutdown. No actual GPU cycle was added.

The launcher and external-inhibitor fixes passed offline and runtime checks;
the combined regression suite passed 679 tests with 3 skipped. This records
actual GPU cycle **10 overall, 2 since post-186 review**; the pre-Docker failure
and GPU-less runs are not cycles. The ledger remains unchanged; the one-shot
prelaunch marker was consumed by the continuation. Root
is auditing a finite reuse admission and frame-pair fix before any further
launch; no desktop Metal claim is made.

Historical preparation/build attempts remain in dated research records.

# Raphael iGPU: current technical status

## GDB is qualified for source-level Raphael debugging

The subsequent GPU-less source cycle authenticated live
`as.rgpu.RaphaelGPU` at `0xffffff800e47c000` by UUID
`474EF697-FC28-3BA2-83A4-763D76C8E200` and instruction bytes. A hardware
breakpoint requested at source line532 resolved to optimized executable line542
in `criticalDumpThread` and hit at `0xffffff800e481411`. Locals, CPU registers
and stack were inspected. `si` advanced RIP to `0xffffff800e481413`; detach
resumed execution. ACPI shutdown was requested, then the exact CID was stopped
after the bounded grace period. No VM remains. Several scalars were optimized
out; the captured UART structure was initialized and not failed at the stop.
Debugger timing prevents interpreting this as a natural UART-failure test.

Reusable tool: `tools/gdb-kext-source.py`; five focused tests passed in
`tests/test_gdb_kext_source.py`. The tool is scoped to the pinned 24G830 kernel
and this exact private debug artifact; its hard-coded offsets are not a generic
KDK locator. Research and evidence paths:
`findings/research/2026-09-10-gdb-kext-source-preparation.md`.
Production187, canonical media and GPU state were not changed by qualification.

Next GPU investigation uses breakpoints and target memory: catch the VM entry
update boundary (`wrapVmmUpdateEntries`) and inspect source/destination/count,
template, conversion decision and native output; correlate the actual VMID1
root and child/leaf table addresses with the faulting submission. Separately,
catch the UART failure branch after its predicate is satisfied to distinguish
byte-ready timeout from snapshot deadline without attributing debugger-induced
delays to normal operation. Do not relax recovery or capture acceptance.

The GPU fault itself is NOT fixed. Host remains on boot
`888a196d-562a-4e7f-ba4e-8f2243b9633a`, with no candidate187 recovery receipt.
A GPU-attached test requires a clean, admitted device state; debugger access does
not reset hardware or authorize reuse. GPU cycle count remains9.

## GDB cycle — kernel breakpoint and single-step verified

One fresh GPU-less run at `run/gdb-runtime-fix-20260910T203000Z` resolved the
missing kernel text relocation: reported KASLR `0x1b400000` plus collection
placement `0xe8000`, total `0x1b4e8000`. Isolating the KDK executable from its
adjacent incompatible DWARF5 dSYM also fixed GDB symbol loading. A named hardware
breakpoint in `mach_absolute_time` hit at `0xffffff801b9389e4`. CPU registers
and stack memory were read, then `si` advanced RIP seven bytes to
`0xffffff801b9389eb`, matching the decoded instruction. Detach resumed the
guest; exact-CID ACPI shutdown completed and no VM remains.

Runtime code bytes and segment mapping matched the KDK. Runtime LC_UUID was
not decoded in this cycle; this limits the identity claim. No GPU was attached,
so the GPU cycle count remains9 and candidate187 recovery remains unverified.
Next work is a bounded, UUID-checked kext locator and source breakpoint generator,
with the existing private DWARF4 kext qualified only in a GPU-less private guest.
No claim of hardware fault repair or desktop Metal success is made.

## Historical — initial debugger setup, before corrected mapping

Normal GPU iterations are paused at the user's request. Two isolated GPU-less
qualifications were performed; neither exposed VFIO/DRI nor counted as a GPU
cycle. The first failed before kernel boot. The second booted successfully and
GDB interrupted mapped kernel code at `0xffffff801853c429`, reading CPU
registers, memory and disassembly. A named hardware breakpoint was accepted but
never hit: the bytes at KDK `_mach_absolute_time` plus reported KASLR slide
`0x18000000` did not match the pinned symbol. Named breakpoints, instruction
stepping and source-level stepping are therefore NOT yet qualified. The second
VM exited under its 180-second supervisor and no VM remains.

Next prerequisite: authenticate the actual guest kernel collection/fileset UUID
and segment-to-runtime mapping. KC relocation is a hypothesis; mismatched guest
binary or runtime patching must also be excluded. No further GPU run or recovery
is authorized by debugger access. Report and raw evidence paths:
`findings/research/2026-09-10-gpueless-gdb-qualification.md`.

A separate private Raphael debug artifact was built once with `-O2 -g
-gdwarf-4`, preserving tracked source and production toolchain files. Matching
executable/dSYM UUID: `474EF697-FC28-3BA2-83A4-763D76C8E200`. GDB loading the
dSYM resolves `pluginStart` and `wrapGfx10PowerUp` to source lines and optimized
variable-location ranges. Artifact and proof:
`/home/bogdan/macos-vm/run/debug-symbols-187-20260910T154947Z-08911110`.
It is not deployed and is not the production187 binary.

The completed capture audit is
`findings/research/2026-09-10-candidate187-capture.md`: repeated incomplete UART
emission from snapshot3 onward, not an oversized CR2 record. Existing capture
remains invalid and cannot authorize recovery. COM1 long-line truncation is
separate. No attempt was made to relax the capture/recovery gates.

## Candidate 187 run — PCI path restored, capture failed

Run `a89f6fadf08d2f6bf55a53e6c7b4196c` completed once on boot
`888a196d-562a-4e7f-ba4e-8f2243b9633a`. The explicit VFIO placement was
observed at guest `pcie.0` slot 6 function 0, matching the OpenCore property
path, and `marked=1` was observed. Native startup progressed past the earlier
lease boundary: SDMA topology applied, XH2 `OWNED`, active pool, KIQ success,
and PM4/SDMA0/VCN0 engine power-up all passed. Route installation and engine
startup are distinct; both passed.

The run reached a VMID1 fault with status `0x101b3a` at VA `0x400580000`.
The walk recorded root `0xf40b6ff000`, relative PDE physical
`0x84b700000`, then a missing leaf at index 1408. No Metal probe ran. At the
180-second deadline critical capture remained incomplete, so the authoritative
classifier returned `INVALID` with `capture_loss`; recovery was refused because
the CR2 attempt exceeded the terminal prefix, and no recovery receipt exists.
Shutdown completed after the guest request. Host-after matches host-before:
same boot, VFIO active, reset methods empty, and no active VM.

| Boundary | Verified result |
|---|---|
| Guest PCI identity | `pcie.0` slot 6 function 0; OpenCore marker `marked=1` |
| Native readiness | SDMA topology, OWNED lease, active pool, KIQ, and engines passed |
| VMID1 / Metal | VMID1 fault `0x101b3a`; no probe result |
| Capture / recovery | 180-second capture loss; recovery refused; no receipt |
| Host / shutdown | Same boot; bounded guest-request exit; recovery unverified |

This is actual GPU cycle **9 overall**, **5 since the post-182 Astra review**, and
**1 since the post-186 Astra review**. The broader unresolved execution streak is
not reset. Frozen text
and metadata evidence is archived under
`findings/experiments/metal-020-187/raw`; no GPU retry is authorized.

## Astra assessment accepted; PCI-path correction verified offline

The mandatory Astra review is complete and accepted. Frozen evidence
demonstrates a guest slot-5 GPU while OpenCore properties remain bound to
property slot 6; the absent specific marker is inferred from target rejection,
not directly dumped from IORegistry. The revised hypothesis is that an explicit
VFIO guest PCI placement `bus=pcie.0,addr=0x6` will restore target identity,
lease acquisition, and native startup while leaving VMID1 behavior unchanged.

The offline correction is implemented in `tools/macos-vm.sh`,
`tools/experiment.py`, `tests/test_experiment.py`, and
`tests/test_vm_entry.py`; `src/` is unchanged. The launcher fixes VFIO at
`bus=pcie.0,addr=0x6`, matching the existing OpenCore property path. Runtime
admission records and validates the guest bus/slot/function and collision-free
topology. Its extractor retains only sanitized PCI model/location summaries; a
fake `/proc` test containing `isa-applesmc,osk=SECRET-SENTINEL` proved the secret
is absent from output. Marker admission now also matches the driver's minimum
512-byte `ATY,bin_image` requirement. Tests reject frozen 186's missing address,
wrong bus/slot/function/path, duplicate or implicit-root slot conflicts, and
missing/short properties, while exercising generic and headless layouts. All
103 tests in the two changed modules pass.

The composition test uses the locally cached Docker-OSX launcher device order.
It is offline argv evidence, not emulator topology or guest IORegistry proof.
The live `/home/bogdan/macos-vm/macos-vm.sh` remains unchanged at SHA-256
`6819d3b9b4d3857e56da66f3cefe9fd7e3a1a61b4d34951a59495fd3b9f791b5`.
During this offline correction, no commit, build, staging, VM, device operation,
or sudo occurred. Candidate 186 has no recovery receipt, so another GPU cycle
remains blocked; spare ledger capacity is not authorization. Deployment is
deferred until the next candidate is prepared; the receipt restriction applies
to hardware reuse, not offline preparation.

The next discriminating sequence, after coordinator review and a fresh safe-host
deployment plan, is: verify explicit topology and properties, observe `marked=1`,
confirm topology applied, OWNED with nonzero VMM base, paging channel, KIQ
success, engine startup, ACTIVE pool and VALID lifetime, then run the existing
Metal probe and cleanup. The 180-second exposure, 45-second probe, marker, lease,
and recovery gates remain unchanged.
The unresolved count remains 8 actual GPU cycles, including 4 since the
post-182 Astra boundary. The historical handoff and failed-run sections below
are retained for evidence.

## Historical — Candidate 186 failed; Astra review completed

Run `8ec4b0197975c1df32f408f188de64ce` completed once on boot
`81e1e41f-f11b-40d0-b202-20850c245ead`. The headless Lilu correction works with
the actual iGPU: patcher dispatch, all three loadKinfo calls, and driver route
installation are observed. COM2 captures complete snapshots. **Native engines
DID NOT successfully power up**; route installation is not engine success.

```text
XH: initVRAMInfo -> 1 ... fbPhysical=0x840000000 ... poolA/poolB nonnull
XV: setMemoryAllocationsEnabled(0) exit: m_0x20=0 m_0x28=0 m_0x30=0
XH: startKIQ refused before native call: no valid OWNED lease
XJ: engine 0 PM4 ... powerUp -> 0
LC: partial engine power-up cleaned before DMA teardown -> 1
XJ: AMDHardware::powerUpHWEngines -> 0
panic ... AMDHWVMM::endVMPTUpdate+0x13, CR2=0, RDI=0
Panicked task: WindowServer
```

This is earlier than183's VMID1 execution faults. The NULL VMM dereference is
observed, but its upstream cause requires investigation; do not bypass the missing
ownership guard. The lack of a lease may be an initialization or delivery ordering
problem rather than just a missing capture. The earlier operator summary saying
engine initialization passed was incorrect and is superseded by these log lines.

| Boundary | Verified result |
|---|---|
| No-generic headless startup | Patcher/loadKinfo/routes restored |
| Critical capture | Complete COM2 snapshots; authenticated BUILD observed |
| Recovery ownership / pool | Required XH2 ownership record absent |
| Native engine startup | Refused before native KIQ; PM4 and HW power-up return 0 |
| Desktop / Metal | WindowServer NULL panic; no valid probe result |
| Shutdown | Exact CID exited after ACPI request |
| Recovery / reuse | Refused; no authorizing receipt, no further launch |
| Host | Same boot; no active VM; VFIO active, resets disabled, watchdogs/inhibitor on |

Verdict is `INCONCLUSIVE`, earliest classification boundary
`recovery_lease_pool_missing`; recovery says
`invalid native recovery lease records: missing XH2 ownership record`.
Classification precedence does not erase the separately observed guest panic.
The current ledger contains one run of ceiling3; remaining capacity does not
permit reuse without the latest-run receipt. No manual reset/rebind/cleanup or
retry was attempted. Host capture configuration passed; pstore listing remains
unavailable (`null`), not proven empty.

Frozen output: `/home/bogdan/macos-vm/run/metal-019-186`.
Serial SHA-256 `1bb600905f78139a8868a06c08838ea3f8964cb09503ab0bc19aa925bfccd2b7`;
critical SHA-256 `210e1c2b573da997a541a0ca892b202251e668a5a02378585c3033dd9e084c`.
Repository archive is preserved at `findings/experiments/metal-019-186/raw`.

Conservative unresolved actual-GPU streak is now **8**:179,180,181,182,183,
GUI-183,185,186. The four cycles since the post182 mandatory review are183,
GUI-183,185,186. Headless startup/capture progress does not reset the broader
unresolved execution streak. Routine hardware retries are paused while the
required Astra xhigh review evaluates current evidence, methods and regressions.
Baseline183 had the NULL-state diagnostic warning but proceeded past startup;
186 explicitly refuses KIQ for missing OWNED lease and later panics. Compare
lease setup/callback ordering and precise record production against183 before
changing functional VMID1 behavior. No source or safety-gate changes are approved
by this failure alone.

## Historical — Candidate 186 handoff and single run authorization

The user completed the handoff at 17:59:12 on 2026-09-10. Live checks confirm
vfio-pci/group31 access, active/on runtime state, no reset methods, and enabled
watchdogs/capture/sleep inhibition. The single normal first-boot run below has
completed; no retry or extra exposure is authorized. The earlier authentication
failure paragraph below is historical.

User requested resuming after reboot and reducing token usage. Headless Lilu
initialization was verified in an isolated no-GPU guest; the corrected source and
staging work passed 40 focused tests. Local dev commit:
`ab2ba0c83ae07af6171960b4ec73d4df1d262c98`. Nothing was merged/pushed to main;
the unrelated `.gitignore` edit remains untouched. No new GPU cycle occurred;
unresolved actual-GPU count remains7 (three since the post182 Astra review).

Candidate186 is built, staged, and prepared for the normal first-launch path:

- Clean worktree: `/home/bogdan/macos-vm/run/worktrees/candidate-186`.
- Run: `8ec4b0197975c1df32f408f188de64ce`; build:
  `5c0abfad59e04aae8c8a97528c7bda53`; card `metal-019`.
- Manifest: `/home/bogdan/macos-vm/run/metal-019-186-manifest.json`, SHA-256
  `f74dd63c7187ad06190df4d1dda9efe74980aeba454eccedaf92d7e845a20966`.
- Staging record: `run/candidate-186/staging.json`, SHA-256
  `971e3eb7d2edf29f0c39f31ae0c127eca8909510942306be6875371a47f44c21`.
- Final bootdisk SHA-256:
  `75b64824cd8ec78a9e973e2f4927e4ad6443358ed84fbd8456eb439a8a7af719`.
- Raphael executable SHA-256:
  `d511c8970c38d282824fc3453acea883f78be0f00ecce4b41356bd588942ebdb`.
- Audited Lilu executable SHA-256:
  `53b5a19812e66eeea3d3b874fe642f441cbfeccd171fb5ba05dc2e0ced3b8887`.
- Durable Lilu bundle/manifest: `run/headless-lilu-verified-53b5a19812e6/`.

The final private and published-image readbacks verified both Raphael files,
both Lilu files and the config. Driver src hash is unchanged from185:
`db511634c6d292ef3a65285e56bd5cf5f9e03cf4c20680a27b96c46a18f2e9b0`.
The change is patched Lilu selected by `-liluheadless`, plus `rgpudump=5000`.
A complete early BUILD-only snapshot was checked against the actual classifier:
`INCONCLUSIVE`, so readiness polling continues. No generic GPU or ramfb;
180-second exposure and 45-second probe remain unchanged. All recovery helpers
are unchanged. The next test must first verify patcher callbacks/routes before
interpreting VMID1 faults or Metal execution.

Current host boot `81e1e41f-f11b-40d0-b202-20850c245ead` remains on initialized
amdgpu, no active VM, watchdogs/capture and sleep inhibitor active. The authorized
one-way handoff command was invoked once via `SUDO_ASKPASS=/tmp/askpass.sh sudo -A
./gpu-bind.sh`; sudo authentication failed after its password retries. The script
never ran. No bind, reset, rebind, cleanup, or additional privilege probe followed.
Root verified `driver=amdgpu`, `device_accessible=false`, `active_vm=false`.
The user must authenticate that existing handoff before GPU launch admission can
pass. Do not retry sudo automatically or use `sudo -n`.

After successful handoff, verify driver vfio-pci/group31 access, runtime active/on,
empty reset_methods, same boot, no VM, and unused current-boot ledger. Recheck
manifest/staging/source identities, then use the clean worktree's normal
`experiment.py run` with this manifest and fresh output `run/metal-019-186`.
No old-boot receipt or one-run policy is needed/valid for this fresh first launch.
Do not reuse failed185 authorization. No GPU launch is authorized if host gates
fail. Preserve the mandatory Astra review trigger if186 is another stalled cycle.

Evidence limitations: candidate186 build.log is an operator summary, not a saved
compiler transcript; artifact/preflight identities passed. The operator's first
stage command used a truncated image digest and was refused before mutation;
the corrected exact digest passed normal staging. Neither stage attempt was a
GPU cycle. Full desktop Metal remains unverified.

## Latest CPU-only qualification — headless Lilu dispatch verified

The audited Lilu 1.6.8 artifact was injected into isolated private media and
read back byte-exact. One bounded no-GPU qualification then observed the exact
candidate-185 build, `-liluheadless rgpudump=5000`, `patcher ready`, and
`loadKinfo` indices 1/2/3 with `err=0`. The run used zero VFIO/DRI,
`-vga none -display none`, and both serial channels; it ended with the reviewed
ACPI request and exact-CID forced stop. This verifies Lilu initialization, plugin patcher callback dispatch, and
kext lookup registration only; no GPU or Metal execution was performed and no recovery
proof was required. Evidence is archived under
`findings/experiments/headless-lilu-qualification/qualified/` and the private
run metadata. The fresh boot remains
`81e1e41f-f11b-40d0-b202-20850c245ead`, iGPU on amdgpu, unresolved GPU count 7.

The prior invalid qualification is preserved below for the preparation failure
and corrected media workflow.

## Latest CPU-only qualification — invalid preparation, GPU untouched

The headless Lilu build passed 5 focused builder tests, exact24G830 kernel import
checks and all12 Lilu exports imported by candidate185. Executable SHA-256:
`53b5a19812e66eeea3d3b874fe642f441cbfeccd171fb5ba05dc2e0ced3b8887`.

One isolated GPU-less qualification ran in
`/home/bogdan/macos-vm/run/headless-lilu-qualification-20260910T140718Z`.
Zero VFIO/DRI and no generic adapter were verified; the185 BUILD marker appeared.
However, the operator failed to embed its modified private plist in the ESP;
observed args still had `rgpudump=40000` and no `-liluheadless`. This run does
not test the proposed initialization fix. Serial also reports a rejected duplicate
Lilu UUID, which alone does not establish which copy was rejected. No patcher
readiness was observed. Exact-CID forced stop followed an ACPI request.

Correction followed in a fresh private media set; both exact config and Lilu
were read back from the final qcow2 image before the qualification above. No new
GPU cycle, handoff, sudo, or ledger use occurred; unresolved GPU count remains7.
The fresh host GPU remains on amdgpu.

## Current work — headless Lilu correction, no GPU exposure

The opt-in `-liluheadless` source patch now applies to both pinned Lilu 1.6.8
preimages. It bypasses the console trigger on Big Sur+ only when requested;
default/older-kernel behavior and existing policy initialization guards remain.
Two focused integration tests passed, including compiled actual `registerPolicy`
branches and independent refusal of modified source/header inputs. Coordinator
review rejected and corrected an earlier malformed draft and unnecessary slow-mode
change before any build or deployment. These tests do not prove macOS execution.

A separate offline Lilu build recipe is in progress; the patched Lilu has not been
deployed. Next planned validation is GPU-less macOS patcher dispatch, then normal
GPU admission only if the new artifact and guest evidence pass. The fresh boot
remains `81e1e41f-f11b-40d0-b202-20850c245ead`, iGPU on amdgpu; no sudo/handoff,
new GPU cycle, candidate bump, merge, or push has occurred.

Cost controls: one owner per code surface, concise evidence reports, targeted
regression tests, coordinator audit, and no repeated full suites/releases without
new changes. Two independent current surfaces are source preparation and Lilu
build tooling. Preserve the user's `.gitignore` change.

## Reboot resumed; candidate 185 earliest-boundary diagnosis (2026-09-10)

Live read-only verification by the coordinator reports boot
`81e1e41f-f11b-40d0-b202-20850c245ead`, amdgpu initialized, no active VM, active
watchdogs/capture checks, and restored sleep inhibition. No device handoff or GPU
cycle has occurred on this boot. Work is using one implementation agent plus
coordinator audit to limit token use.

Offline comparison found candidate 185 never observed Lilu dispatch its patcher callback:
there is no `patcher ready`, `loadKinfo`, or AMD kext callback, so no framebuffer,
HWLibs, or X6000 patch/route was installed. The ensuing zero-width GPUCAP, BGM
`0xc00c0203`, and PPLIB panic therefore precede the intended candidate-183 path.
The new COM2 worker also cannot announce readiness before its configured 40-second
initial sleep, later than this panic. Pinned Lilu proves both Force registrations
returned successfully under its API lock; worker ordering is not the cause. The
source-backed hypothesis is that removing generic display removed Lilu's required
early `kPEEnableScreen` initialization trigger. `-liluslow` does not bypass the
Big Sur console path. Smallest proposed correction is an opt-in, pinned Lilu
headless mode that selects its existing TrustedBSD policy initialization while
retaining the no-generic/no-ramfb topology, then gate hardware on patcher dispatch,
callbacks/routes, and corrected-first-GPUCAP evidence. No
implementation or hardware retry has started. Detailed evidence:
`findings/research/2026-09-10-candidate185-investigation.md`.

## Resumed at user request — offline diagnosis first (2026-09-10)

The user has authorized resuming testing and development. Live verification still
shows boot `73ad3355-80a7-48f1-a8dd-e6f770b41de8`, no active VM, awake VFIO
iGPU and active sleep inhibitor/watchdogs. Candidate 185's missing recovery
receipt still blocks GPU reuse; the resume instruction does not override that
gate. No new GPU cycle has occurred (unresolved count 7).

Two Sol agents are independently tracing the candidate185 BGM panic and missing
COM2 producer readiness against the frozen evidence and actual source. The
coordinator is checking live safety and recovery state. Implementation and offline
regression tests will follow verified findings; no hardware retry is authorized
by an old receipt. Preserve the unrelated existing `.gitignore` change.

The stopped-state handoff below remains the authoritative last-run evidence;
only its user-pause instruction has been superseded by the new resume request.

## STOPPED at user request — candidate 185 failed (2026-09-10)

The user requested stopping after this attempt and updating this file for another
model. **Do not start another iteration or hardware test without a new user
instruction.** Candidate 185 ran once and failed. No functional desktop Metal
acceleration has been demonstrated. The VM is stopped; the host remained up.
Only evidence archival and this handoff followed the user's stop request.

| Boundary | Candidate 185 result |
|---|---|
| Launch admission | Passed; exact run-scoped authority; ledger now 2/3 |
| Running topology | Raphael VFIO, COM1 index 0, COM2 index 1, `-vga none -display none` |
| Guest boot | Candidate 185 loaded; WindowServer reached framebuffer power-up |
| Guest failure | `AmdPowerPlayHelper::powerUp` / BGM event `0xc00c0203` panic |
| Critical capture | No `RGPU_UART_READY` or CR2; only early firmware/OpenCore output |
| VMID1 diagnostic / Metal probe | Not reached; neither fault hypothesis nor acceleration tested |
| Shutdown | Exited after ACPI request; identity-bound guest shutdown unavailable |
| Recovery | Refused before recovery: required dedicated critical readiness absent |
| Host | Same boot, no active VM, watchdogs/inhibitor active; no reported host fault |

### Exact current identities and frozen evidence

- Source: `c499829dd134402dc9f7227363740720c1a89a15` on local `dev`;
  detached worktree `/home/bogdan/macos-vm/run/worktrees/candidate-185` is frozen.
- Run: `2ef50dc9d8b466c5f2521208b5ba87ea`; card `metal-018`; version `1.0.185`.
- Build: `68b28f81b7d5404cb69a7baf2f6117c5`.
- Manifest: `/home/bogdan/macos-vm/run/metal-018-185-manifest.json`, SHA-256
  `e23b8013bbc8ecdc4374dedc0e89afd6b63287ba1c35450515b59c828e8cafd1`.
- Frozen output: `/home/bogdan/macos-vm/run/metal-018-185`;
  repository archive: `findings/experiments/metal-018-185/raw`.
- Serial SHA-256: `514abea543f1ccd0d8cb65842ca10e4b18cd34c4e624c5af9496d122b4980be8`.
- Critical SHA-256: `ab710717ef19c8a691c8885ac055f4660bdfd3df37a1976202f9b375211324d6`.
- Operator log SHA-256: `983799c1985c68460cbc253ef596a8241ef5b1f96e23b998596785f3134d8019`.

The classifier correctly refuses incomplete critical evidence. Its
`identity_or_route_missing` label is a capture/validation boundary, **not the
functional cause of the guest panic**. COM1 directly records this earlier event:

```text
panic(cpu 1 ...): "[0:5:0][PPLIB] Failed to send PPLIB IRI to Accelerator.
TTL Error Message: {... Error SW_IP_CLIENT_ID__BGM:
event_id=0xc00c0203 event_info:type=3 hw_id=0 ...}"
Panicked task ... pid 160: WindowServer
AMDRadeonX6000_AmdRadeonController::doGPUPanic
AMDRadeonX6000_AmdPowerPlayHelper::powerUp
AMDRadeonX6000_AmdRadeonController::powerUp
AMDRadeonX6000_AmdRadeonFramebuffer::enableController
IOFramebuffer::open
```

Final machine-readable results:

```text
verdict=INVALID
early validation boundary=identity_or_route_missing
termination=critical capture remained incomplete at exposure deadline
shutdown=exited-after-acpi-request; acpi_request_sent=true
request_sent=false; request_error=guest identity transport failed
recovery=failed: dedicated critical producer readiness is absent or conflicting
```

### Reuse is NOT authorized on this boot

Current boot is `73ad3355-80a7-48f1-a8dd-e6f770b41de8`. The used-boot ledger
has two launches of ceiling three, SHA-256
`5ca6d116d551dc29a958d4849d5b22b6ce9495ff2acf106ad6550b8f79dd42c8`.
Numerical capacity is **not** permission to reuse: candidate 185 produced no
recovery receipt. The old GUI-183 receipt remains byte-identical at
`d2e2fad9244033002bdd3643e72049e9b4f4b858080aa8fa0cadd91d095ad367`,
but is no longer the latest-run recovery and must not authorize another launch.
No manual cleanup, reset, rebind, retry, sudo, or budget extension was attempted.
ACPI exit is not proof of a clean GPU. Preserve existing gates.

Post-run snapshot: `driver=vfio-pci`, group 31 accessible and pinned awake,
`amdgpu_initialized=true`, all three watchdog sysctls `1`, capture configuration
verified, `active_vm=false`, `sleep_inhibited=true`; `pstore_files=null` means
its listing was unavailable, not a verified empty pstore. Sleep inhibitor remains
active as previously requested; it was not changed by this handoff.

### Regression comparison and next-model questions (offline only while paused)

Source/host fixes before this run passed 624 Python tests with one explicit skip;
exact 24G830 preflight and candidate build passed. Dedicated COM2 had passed
10/10 CPU-only real-QEMU qualification cases. These checks did not establish
that the delayed macOS critical producer can emit before an early guest panic.
Candidate 184 never launched; its final identity propagation bug was fixed in
185 and actual admission now passed. It contributes zero GPU test cycles.

Candidate 185 preserved candidate 183's functional driver path, but removed the
generic adapter per user instruction and added COM2 plus observation-only VMID1
diagnostics. The earlier framebuffer panic and missing critical readiness are
observed; attribution to the no-generic topology, warm-device state, or worker
scheduling has **not** been established. Do not call VMID1 conversion fixed or
regressed: its diagnostic and the unchanged Metal probe were not reached.

When the user resumes, the next model should first inspect the frozen serial
leading up to the BGM event, compare the actual prior 183 boundary, and audit
critical-worker scheduling versus panic time. Keep the user prohibition on a
generic GPU. Repairing capture alone cannot authorize a device recovery without
the required authenticated lifetime/lease evidence. No new implementation or
hardware procedure has been approved by this failed run.

Conservative unresolved actual-GPU streak: **7** (179, 180, 181, 182, 183,
GUI-183, 185). No demonstrated functional progress resets it. Mandatory Astra
xhigh review completed after 182; three actual GPU cycles have followed that
review. Preserve the AGENTS.md fourth-stalled-cycle trigger and reconstruct
from evidence if the next model uses a more precise boundary accounting.
Relevant interpretation aid: `findings/research/2026-09-10-candidate185-evidence-checklist.md`.
Build and admission reviews: `findings/research/2026-09-10-candidate185-*.md`.
No merge or push to main occurred. Documentation below is historical and is
superseded by this stopped-state section wherever it describes pending launch
or recovered-device eligibility.

---

## Current milestone — candidate 185 built and staged; admission review pending

Candidate 184 was refused before reservation and QEMU because the final identity
check omitted the manifest's no-generic-graphics launch options. No GPU exposure
or recovery occurred; the unresolved GPU-cycle count remains 6. Its output,
policy, activation and artifacts are frozen. The host ledger is unchanged at one
launch of three on boot `73ad3355-80a7-48f1-a8dd-e6f770b41de8`.

Agents repaired exact option propagation at both final reservation paths and
added run-scoped policy filenames, retaining legacy compatibility and refusing
fallback around invalid scoped policies. Existing caps, receipts, identity checks
and reservation rules remain enforced. Candidate 185 / `metal-018` preserves the
reviewed driver and COM2/VMID1 diagnostic; it does not add a functional GPU fix.
Independent review and coordinator audit cleared the source changes.

| Boundary | Verified result |
|---|---|
| Final admission | Exact launch options propagated; mismatch prevents ledger write |
| Authority namespace | Exclusive run-scoped creation; old 184 authority unchanged |
| Regression checks | 624 Python tests successful, one explicit skip; syntax checks passed |
| Capture lifecycle | Earlier 10/10 real CPU-only COM2 qualification remains applicable |
| Candidate 185 | Clean-worktree build and staging passed; final admission review pending |
| Metal execution/desktop | Still unverified; no new GPU run |

Four reviewed runtime harness files were deployed before candidate 184's refusal;
all five recovery helpers remain unchanged. The next test is bounded to 180
seconds with the unchanged 45-second probe, no generic graphics adapter and no
automatic retry. Headless diagnostic capture does not provide a visible desktop.
Details: `findings/plans/2026-09-10-candidate184-prelaunch-refusal-followup.md`.

Candidate 185 source commit is `c499829dd134402dc9f7227363740720c1a89a15`.
Run `2ef50dc9d8b466c5f2521208b5ba87ea`, build
`68b28f81b7d5404cb69a7baf2f6117c5`, manifest SHA-256
`e23b8013bbc8ecdc4374dedc0e89afd6b63287ba1c35450515b59c828e8cafd1`.
Fresh run-scoped policy SHA-256
`4b092ebd67911ccbe79c67807f97e3991ddaa865e9d2ace5ff5fc5b341ff1fca`
and activation SHA-256
`7076d8328552683824abef35fe8f34e23908086afcdaf0134d7b08d0287bd181`
bind the unchanged GUI-183 recovery and ledger preimage. No reservation has
occurred. The archive was built with the recorded pinned inputs; its build report
records physical testing as false. The staged
bootdisk SHA-256 is
`1dc61cf61dc0a98d4370fcb36608421d4077283f1ca46260aaa9f562d1a27843`.

The final tiny-guest fixture is 1,144,917 bytes (complete baseline plus maximum
snapshot), SHA-256 `83be7814817571a62e58879602b051615940d4bf6b840ae38cdecfa88eedafa5`.
It arrived byte-exact over COM2 while COM1 carried malformed marker noise. Tests
covered swapped channels, stale readiness, three interrupted offsets, loss of
either collector, missing-channel deadlines, exact-CID stop and cleanup. QEMU
used TCG, no devices, `-nodefaults -vga none -display none`, and no macOS disk.
This qualifies the repository supervisor/collectors with explicit tiny-guest
topology; live macOS deployment remains pending.

The production-shaped temporary build verified pinned SDK/Lilu trees, the firmware
header hash, and embedded firmware (177,104 bytes; 3/3 probes). The 725,552-byte
kext has SHA-256 `03293912e45393f53bbe89cf50bd589d669d41fdbb243fcdc7b5cf86d9cf6d89`.
It is a build verification artifact with a temporary identity, not a staged
candidate. Evidence and commands are in `findings/research/2026-09-10-com2-*`.
All five recovery/parser helpers remain byte-identical. The historical GUI-183
one-use runner still rejects changed source; tests use its exact archived fixture.

Current host verification: same boot `73ad3355-80a7-48f1-a8dd-e6f770b41de8`,
no VM running and sleep inhibition active. The recovered receipt below remains
the latest cleanup evidence. No new GPU cycle has occurred; unresolved count 6.

The next discriminating hardware observation remains the actual faulting VMID1
context and page-table chain; candidate 183's corrected VMID2 child address does
not explain VMID1's later faults. Before that run, prepare a new immutable
candidate and schema-3 warm-launch authority, verify remaining budget/receipt,
and implement and verify a launcher contract honoring the user's no-generic-GPU
requirement. No capture test extends a GPU budget or proves desktop acceleration.

COM2/VMID1 milestone committed locally on `dev` as `d421120`; no main update.
Candidate 184 / `metal-017` source preparation is independently reviewed: explicit no-generic/headless
launch options, a pinned repository entrypoint, exact running graphics identity,
and additive structured VMID1 diagnostic parsing. Final Python discovery ran
615 tests successfully with one explicit skip; syntax/diff checks passed.
Driver source is unchanged from `d421120`; both bundle versions are `1.0.184`.
The new parser was checked with production C++ formatting and decoding for
both known fault statuses, zero entries, `0x61` read/write entries and nonzero
SYSTEM/PDE/TF fields. It retains invalid context state as diagnostic data and
does not gate probe readiness on fault presence. Inert inspection of the pinned
Docker image found exactly one `-vga vmware` and no `-display` in `Launch.sh`
(SHA-256 `ae6050750f4ba26fbe85785da909b8f7d34fab064b6539d9a3f1903abf3fe302`).
The inspected container was never started and was removed by exact ID. This
corrected a fixture assumption before launch; display options currently originate
in the host launcher. Plan: `findings/plans/2026-09-10-post-com2-candidate.md`.

### Candidate 184 artifacts and admission preparation

Candidate source is committed on `dev` as
`ec02aacea85fe5d652b5da0cee2e8eda344ef278`; detached worktree
`~/macos-vm/run/worktrees/candidate-184` is clean. Build, four-file runtime
deployment and boot-artifact staging completed. No guest launch has occurred.

```text
build_id       3b398d6d46e14fc89c40d62c4868f407
run_id         f32c2266a96dd7e3c91a46b85ac7878d
kext_sha256    e66062ce0934881c4f777520d2cd3fa1c742ecfe7bc250f5d9749dc3b8a40d5e
archive_sha256 78f5b478093ffd60b298b685640ddf01f6bf5cf63eabf8411af8bb40e2bdc761
staging_sha256 591f23047e3995316b16cc5e9aa96e09588fcd1eab098d90120195c469b43a24
manifest_sha256 35b2d1ac983a3b5730c51693460ace4a52d69e58e166641091cf5e275a4f8df3
bootdisk_sha256 7e37a084299b147b1228def489e957da0976a8d90cff2078bc534566917a1801
```

Manifest: `~/macos-vm/run/metal-017-184-manifest.json`. It selects
`GENERIC_GRAPHICS=off`, COM2, `rgpuvmdiag=1`, `rgpuvmroot=4`, `rgpusubmit=1`,
`rgpudump=40000`, and the exact numeric run nonce. Runtime deployment record:
`~/macos-vm/run/harness-deployment-20260910T115451Z-four-runtime-ec02aace-r2.json`,
SHA-256 `1e1d480a3377917f8249de060818e3493524780c82c231482174360821eda227`.
Original files are archived under `run/harness-preimages/`.

The latest read-only host snapshot confirms amdgpu initialization this boot,
vfio-pci ownership, group 31 accessibility, device pinned awake, no reset methods,
all watchdogs enabled, capture ready, sleep inhibited and no active VM. The
ledger remains 1/3 and the canonical recovery receipt remains byte-identical.
### Candidate 184 invocation refused before reservation

The single invocation reached the final locked admission check and refused:

```text
ValueError: one-run qualification refused: harness_sha256,launch_options
```

No reservation, QEMU process, GPU exposure, probe or recovery occurred. Output
`~/macos-vm/run/metal-017-184` is frozen with `verdict=INVALID`; this is an
admission failure, not a driver regression. `shutdown.json` is null and both
captures are empty. Operator log SHA-256:
`1028ebaea272e83ce983f2641dc53f880a676a8c14ac37b8c71a0bd99179bc35`.
The unresolved GPU-cycle count remains six.

The cause is localized: the final reservation path's `current_identity` call
omits `launch_options_expected`, so it reconstructs historical options and omits
the new `vm-entry.sh` harness pin. Preparation and the outer live-identity path
already pass the selected options. The independent authorization review checked
`authorize`, which does not execute this later reservation gate. The fix must
propagate the exact manifest options and add a regression at that actual gate;
identity equality must remain enforced. Candidate-184 worktree, output, policy
and activation are preserved. A fresh attempted run requires reviewed source
and authority handling, with no cap extension or silent reuse of this output.

## Current viewing requirement — no generic QEMU GPU

The user requested another desktop launch with **no generic QEMU graphics
adapter**. No launch was made. The earlier GTK window used VMware VGA; removing
that adapter does not automatically expose Raphael scanout to GTK. QEMU 10.1.2
`hw/vfio/display.c::vfio_display_probe` requires a VFIO display-plane interface
(DMA-BUF or display region). No live capability ioctl was issued in this review,
and this project has no implemented, verified Raphael-to-QEMU presentation path.
Desktop Metal is also still unverified. Future viewing work must respect the
no-generic-adapter requirement rather than silently restoring VMware VGA.
The successful cleanup below remains valid on the current boot; no reboot is
currently requested. See `findings/research/2026-09-10-vfio-display-capability.md`.

## Resume: GUI visibility and capture investigation — 2026-09-10

**Same-boot cleanup succeeded.** The independently reviewed one-use runner
`tools/gui183-recovery-once.py` (SHA-256
`23a25da9972f6a29ae15a6421369c1653af8d7ddc038a0f222db030251bc9ecc`)
executed exactly once after 576 Python tests passed (one explicit live skip).
Canonical receipt SHA-256
`d2e2fad9244033002bdd3643e72049e9b4f4b858080aa8fa0cadd91d095ad367`
reports `status=recovered`, `authorizes_launch=true`:

```text
active_before=2 dequeued=2 dequeue_timeouts=0 forced_inactive=0
gfx_retirement_confirmed=true gfx_ring_clean=true
PSP destroy-all-rings=confirmed destroy-GPCOM-ring=confirmed
kernel_messages=[]
```

The coordinator inspected the durable result; the operator verified the same
boot, accessible vfio-pci device, blank reset methods, no VM and active sleep
inhibitor afterward. Evidence is separately archived in
`findings/experiments/metal-016-183-gui-73ad3355/recovery-migration/`.
This demonstrates recovery for this run after requested guest shutdown. It does
not establish recovery from every crash or forced close. The frozen functional
verdict remains INCONCLUSIVE; no relaunch has occurred. The next diagnostic and
launch still require their normal staging/identity and remaining-budget checks.

The user reported that no QEMU window appeared during the preceding run.
The earlier GTK/process observation did not establish visibility. A subsequent
diskless, no-VFIO smoke test on the same desktop produced a focused QEMU X11
window, with both GL on and off. This proves the display route can work; it does
not reconstruct the historical window's placement or contents. A standalone
window-state and screenshot observer is implemented, with review in progress.
The coordinator inspected its diskless QEMU screenshot (expected uninitialized
guest display). Evidence is archived under
`findings/research/2026-09-10-gui-visibility/`; screenshot SHA-256
`e008c3c5c85e18793f80e4b34afc086a22e9e9196eda418fee2b23483b831841`.
This is host-window validation, not macOS rendering. Investigation:
`findings/research/2026-09-10-gui-visibility.md`.

All 13 archived GUI-run hashes were verified. Offline capture investigation
found an intact snapshot 0 (186 records, 662 chunks) and a damaged terminal
snapshot 1 (265 records, 915 manifested chunks, 508 valid chunks). The 407
missing chunks belong to the earlier immutable prefix. Donor reconstruction
matches the original terminal CRC/FNV. The proof-only tool is implemented and
under independent review; proof SHA-256
`59809d556b050cd8f1b1629601efdffedec34b37ab8cfbabdb3204429abaf3fb`,
derived capture SHA-256
`d33deff7cd420013a290d195967c0e43689c3810422b9647b8336a83180f0675`.
It explicitly sets `authorizes_gpu_action=false`. A separate one-use cleanup
runner was reviewed and executed as recorded above. The original transcript
remains inadmissible; the reviewed derived transcript enabled cleanup only. Concurrent
Apple console output visibly interleaves with the replay before host collection;
`sercat.py` fsync cannot repair that corruption. A durable independent capture
transport remains a design task, not an implemented fix.

Offline driver review decoded both recurring post-183 faults as **VMID1**:
`0x101b3a @ 0x400900000` (SDMA0) and `0x1009ba @ 0x401180000` (CPF).
The coordinator verified the raw words and local register masks. The successful
VMID2 walks do not inspect these faulting mappings. Proposed next driver test:
bounded, observation-only capture of the fault-selected VMID1 context and exact
address, comparing relative and absolute walk indices without modifying page
tables. See `findings/research/2026-09-10-post183-fault-boundary.md`.

The opt-in `rgpuvmdiag=1` diagnostic is now implemented in the working tree and
independently reviewed. It preserves flag-off MMIO behavior, captures at most two
distinct VMID1 fault pairs, reads/walks on the worker, and emits at most 30 added
critical records. It reports `fault-va` separately from `entry-addr`, context
range/stability, and non-atomic table timing. Focused VM and unchanged mode-4
C++ fixtures passed with warnings treated as errors. **No KDK cross-build,
staging or hardware validation of this diagnostic has occurred.** The dedicated
COM2 capture design is in
`findings/plans/2026-09-10-dedicated-critical-transport.md`; it is not implemented.
Cleanup and GUI-observation work is committed locally on `dev` at `d109910`;
the new driver diagnostic remains uncommitted. Nothing was pushed to main.

Host boot remains `73ad3355-80a7-48f1-a8dd-e6f770b41de8`, iGPU on vfio-pci,
reset methods empty, no macOS VM active, sleep inhibitor active. No additional
GPU experiment cycle was consumed; the unresolved count remains 6. Cleanup did
not consume a VM launch, reset the fault streak, or extend the run budget.

## User-requested GUI observation after reboot — 2026-09-10

**No desktop Metal success was verified.** The user explicitly requested a direct
visible launch of the existing candidate after reboot. This was a manual viewing
run, not a new driver fix. New boot `73ad3355-80a7-48f1-a8dd-e6f770b41de8` passed
host checks; normal amdgpu-first handoff succeeded and sleep inhibition was
recreated. Candidate 183 was reused without rebuilding. Fresh staging outputs
under `run/candidate-183-gui-73ad3355` preserved the original candidate artifacts
and supplied a new nonce/run ID through the unchanged staging transaction.

Run `4661e574bbd5695d00176d85bfa87325`, build
`1d5f98d2e5b641eeab1869987f569e73`, manifest SHA-256
`b78905e67974809e085849001514a6c934d314bc43de2e0ae71a26ddc5470c11`.
QEMU was launched with the current GUI environment at `09:51:53.304Z` and a
180-second bound. Independent visual confirmation of the desktop is absent.
The guest exited after the shutdown request (`exited-after-guest-request`).
No active VM remains. This was the first GPU launch on the new boot (ledger 1/3).

Raw diagnostics again recorded `converted=206`, then `converted=347`, with no
inactive/invalid-aperture/overflow/span counts. A pending WindowServer command
was reported on VMID2, followed by a KIQ stamp timeout. No `RGPU_METAL_STAGE`
marker or valid probe result was captured; no panic marker was seen in this log.
The final verdict remains `INCONCLUSIVE`, `identity_or_route_missing`,
`capture_loss`. Recovery failed before receipt creation with
`CriticalReplayError: CR2 snapshot has a missing chunk`.

Serial SHA-256 `a8c7aeda24244094d2a153df066d3857f3adfa823bb4ff62bbe72a79180c765b`.
Original run evidence is under `~/macos-vm/run/metal-016-183-gui-73ad3355`.
**No reuse is authorized by the remaining numerical budget.** No alternate
cleanup or second launch has been attempted. The prior run-specific recovery
wrapper pins another run and boot and cannot be used here. Further hardware
testing is paused pending admissible capture and successful cleanup.
Conservative unresolved-cycle accounting is now 6 (179–183 plus this explicitly
requested GUI observation); the prior Astra review was completed after cycle 182.

## Candidate 183 result: source correction observed; hardware retirement blocks reuse

### Latest outcome: reconstruction passed; hardware retirement incomplete

The reviewed one-use recovery wrapper executed once after **548 Python tests**
passed and independent source/proof review. It successfully reconstructed the
terminal snapshot through the unchanged parser and admitted normal schema-3
cleanup. **The remaining failure is hardware retirement, not capture validation.**
Receipt `3b9e76e85ad349d2a480b4f154d2609c` is `incomplete`,
`authorizes_launch=false`, SHA-256
`914c2ea652ea076e8168f362543200f69af0e7037f4011aba745018e71513c17`.

```text
gc_quiesce: active_before=9 dequeued=1 dequeue_timeouts=8 forced_inactive=8
host_kiq: status=blocked-active-hqd
gfx_retirement_confirmed=false gfx_ring_clean=false
active_after=0 gfx_rb_active_after=0
PSP destroy-all-rings: confirmed
PSP destroy-GPCOM-ring: confirmed
kernel_messages=[]
```

Zero final active bits after forced disable are not proof of clean retirement.
The recovery helper correctly refuses reuse. The host stayed on the same boot;
no additional device action or launch is authorized by the remaining 2/3 ledger.
A fresh host boot is required before another GPU experiment under the current
safety gates. No reset or second cleanup attempt will bypass this result.
Original serial, failed automatic-recovery result, and `INCONCLUSIVE` functional
verdict remain unchanged. The proof, durable attempt and new result are separate.
Result SHA-256 `9c712d4c536a065e343f97f3b7f27f28dc4ee58056d682c5cb90a689a1624e75`;
attempt SHA-256 `1b21d97a6496d9c00750a0b7a77cda0d62faf2776ab0f85d1aedc8e6d5c86eee`.
Regression log `~/macos-vm/run/candidate183-recovery-final-regression.log`, SHA-256
`f7b9e433afb6ff1e30a4e0003c524f401d77fb95fc70f8d385818b6ca9981815`.

Next work must separate capture reliability from the later lifecycle fault:
preserve mode-4 source conversion, investigate `doStop`'s KIQ frame and queue
progress using frozen evidence, and make the next probe's admission observable.
Do not assume the unobserved VMID9 path is the current cause or repeat candidate
183 unchanged. The 5-second guest picker setting remains staged and verified.

### Original run result and recovery investigation history

The following records the original failure and investigation before the latest
recovery outcome above. **Desktop Metal is not yet functional.** Run
`f1728b74e128c5acd35661334bff12be` used the sealed candidate below on the same boot
at `2026-09-10T09:06:25.104Z`, with the verified 5-second picker setting. It reached
the 180-second bound, requested shutdown and forced the exact QEMU container
closed. No valid Metal probe verdict was produced. The host remains on boot
`d67da91d-94e6-42f0-8dd1-78b42f5496e1`; watchdogs and sleep inhibition remain active.

**Preliminary functional evidence (raw serial, not an accepted final CR2
snapshot):** the mode-4 route and gate installed; conversion counters reached
206 then 347. A returned child sample reported
`source=0xf40b6f4000 result=0x84b6f4000 template=0x2000000000000001`.
VMID2 dispatch fault samples at 0/1/10/100 ms reported status zero. Later raw
fault diagnostics showed `0x101b3a @ 0x400900000` and
`0x1009ba @ 0x401180000`, followed by stamp timeouts. Native submission counts
reached `113/113/0`; this is not a completed-work count. Agents are comparing
the later fault boundary with the prior VMID2 failure and Astra's VMID9 hypothesis.

**Capture and cleanup:** raw verdict is `INCONCLUSIVE`, earliest failure
`identity_or_route_missing`, evidence `capture_loss`, termination reason null.
Automatic recovery returned `failed` with
`CriticalReplayError: CR2 snapshot has a missing chunk`; no authorizing receipt
was issued. Ledger is now **2/3 used**, but remaining numerical budget does not
authorize another launch without successful cleanup. No alternate hardware
cleanup, reset, or retry has been attempted. An offline capture audit is checking
whether the unchanged validator has any admissible final evidence; guards are
not being relaxed.

**Offline capture audit:** the latest manifested snapshot 3 is missing all four
chunks of record 134, destroyed by concurrent AMD console output. Earlier
snapshot 2 is complete (267 records). Using its exact record 134 bytes for an
offline diagnostic reconstruction makes snapshot 3's existing CRC/FNV match
all 285 records. The unchanged parser and `recover-frozen-run.build_proof`
nevertheless reject this transcript. No reconstructed stream has authorized
hardware access. Agents are designing and independently auditing an explicit
proof with original-input provenance, complete terminal integrity checks and
unchanged live lifetime/ownership gates before considering recovery.
The design is recorded in `findings/research/2026-09-10-post183-capture.md`.
Independent review approved an insertion-only, run-specific recovery wrapper;
implementation and tests are in progress. It preserves every original byte and
adds only the four donor-derived chunks immediately before the original terminal
END. The unchanged parser must accept that full derived transcript. The proof
will be recovery-only, with explicit provenance and one-use execution; it will
not change the functional verdict or authorize another launch. No recovery
execution has occurred. CRC/FNV provide accidental-corruption integrity checks,
not cryptographic authentication.
The frozen wrapper is `tools/candidate183-recovery-repair.py`, SHA-256
`5421088fd8302116d5ea413937572aa2687ac84acf46bbd6d437740b5999c956`.
Its 13 focused tests passed. Proof-only output in the original run directory,
`candidate183-recovery-repair-proof.json`, has SHA-256
`5e2c287356cd3721d481aad6dd9a0422a218d7674c8b9e23624bda3f5db0ad14`.
It records insertion offset 1511806, donor snapshot 2, terminal snapshot 3,
285 records, 971 chunks, CRC32 `f18488f3`, FNV `72e0f4557e90ee72`, and derived
transcript SHA-256 `73aac21e747be5e14178b2bf2e38424dee03214d0a9beb89eff023ce1d47a364`.
Root reviewed these identities. Full Python regression and independent final
source/proof review remain before a single cleanup attempt.

**Functional review:** raw dispatch evidence includes two completed walks through
physical child `0x84b6f4000` and clear fault samples through 100 ms. The later KIQ
timeout caller `x6+0x68707` maps to `AMDGFX10PM4Engine::doStop(bool)`, which is a
lifecycle stop path; it does not identify a failed workload packet. No VMID9/probe
process record was observed, so the VMID9 hypothesis remains untested. The earlier
paging boundary appears improved, but final evidence validation is still pending.

The first timestamped guest `launchd` message was about 18.2 seconds after
supervision start (versus roughly 70 seconds for 182); this is an approximate
whole-startup comparison, not isolated picker timing.

Frozen serial: `~/macos-vm/run/metal-016-183/serial.txt`, SHA-256
`af132e635729bee36634c4bd4f5280bf63735183f88b465e8a3d34c1c0df0ce1`.
Verdict SHA-256 `4d896e153fafbc59072eb82014e591dff8536c31d449f63f9a3e032b5052fc49`;
recovery SHA-256 `ddb66b00adb660c710cd8bc4db03fd37ab569908563630f4f1c5b99d3370055b`.
The streak is conservatively **5 cycles (179–183)** until meaningful progress
past the fault is established from reviewed evidence. The mandatory review after
cycle 182 was completed and directly informed 183; no routine retry is underway.

## Candidate 182 result: fourth stalled cycle; mandatory review — 2026-09-10

**Full desktop Metal is still not working.** The mandatory review is completed
and audited; candidate 183 is being implemented offline under the plan below.
Run `113c5b949683bf38fd5a807447088a69` used source
`70b7f127ca0ddc6c8404eff48897001368d0acca`, build
`9f8584cf8a0246308772d6958443e503`, binary SHA-256
`e26f707160a540123fc4bdf5bc2fd295c5e7fab737509258f9953ada8b3a26a0`,
on boot `d67da91d-94e6-42f0-8dd1-78b42f5496e1`. Evidence is frozen under
`~/macos-vm/run/metal-015-182/` and mirrored unchanged under
`findings/experiments/metal-015-182/raw/` with a SHA-256 inventory. The sealed manifest SHA-256 is
`9efb977fa6046e8fe837e59d3c744c68915b2d96ccfcd72f4e23061cdc975f55`.

**Functional boundary.** Native accelerator startup, lease ownership, ACTIVE
pool exclusion, VALID lifetime, native VMM arena, KIQ stamps and the VMID2 root
repair repeated. The early gate explicitly reported `marked=1 aperture=1 mode=3`.
The repaired root again matched live `0x84b6f3000`. Nevertheless:

```text
VM: fault seq=1 phase=prepared ... status=0x2009bb addr=0x400200000
VM: entry-conv mode=3 routes=1/1 pde=0/0/183/0/0 pte=0/0/23/2410/0 inactive=0/0 dropped=175/2425
VM: entry-sample kind=pde ... original=0 result=0 domain=outside
SD: submit vmid=2 ... IB0=0x400100000 IB1=0 seq=0
VM: submit-correlation refused: ... no in-range program
```

All first-eight PDE samples and all first-eight PTE samples have address zero;
the full counters show **zero converted PDEs/PTEs and no pre-gate calls**. Opening
the identity gate earlier did not expose the child addresses. This refutes the
gate-timing explanation as sufficient. Investigate where the nonzero child
addresses are actually inserted: these functions may be used to make attribute
templates with address zero, with another caller adding addresses later. That is
a hypothesis from the run, now **confirmed independently in KDK disassembly by
Astra and the coordinator**: `AMDHWVMContext::mapVMPTE` clears EDX at `0x559ab`
before the PTE virtual call (`+0x1e0`) and at `0x55a4d` before the PDE virtual call
(`+0x1d8`). The real address goes separately in RCX, while the returned template
goes in R8, to `updateContiguousPTEsWithDMAUsingAddr` at `0x559d7`/`0x55a6d`.
The completed review selected the narrow updater boundary described below;
hardware execution still requires offline validation and finite admission. The submitted-IB
walk was unobserved because correlation failed; do not call it a walk regression.
No identity-bound Metal probe result was produced. Candidate181 reached probe
commit; 182 has not demonstrated that outcome. Its final retained native/background
submission summary is `submit=43/43/0` (event 173), so it must not be described as
having fewer total submissions than 181's reported 18. These counts are not
completed GPU work; the capture abort prevents a clean probe regression comparison.

**Capture and cleanup.** The live coordinator aborted on definitive capture loss,
then requested guest shutdown and ultimately forced the exact container closed.
Raw verdict remains `INVALID`, earliest stage `vmid2_entry_conversion_no_pde`,
error `RuntimeError: definitive critical capture loss; aborting exposure`.
The recovery-only parser recovered checksum-clean snapshot 3 (205 records,
CRC32 3562850089, FNV1a64 7163687658012943284) despite 69 corrupted lines in
earlier transport; there was no open final attempt. Raw serial SHA-256:
`7366a5c22e027f4235c3ba3799b28f4e9d7309ff074dc2b69174984e6577a705`.
Automatic schema-3 cleanup **succeeded**, receipt
`13c92dcc904742ce8fd4de28a3fb1988`, `authorizes_launch=true`. Graphics retirement
and final inactive state were confirmed, both PSP destroys acknowledged, and
the recovery-interval kernel message list is empty. The whole-run capture contains
32 Docker/UFW networking messages; no captured GPU/IOMMU fault was identified.
The host remains on the same
boot and QEMU is stopped. This demonstrates successful cleanup after this forced
closure, not universal recovery or permission to bypass one-run admission gates.

**Streak: 4 actual GPU cycles (179, 180, 181, 182)** with unresolved SDMA/VM memory
faults. Routine retries remain paused until the reviewed next candidate passes
offline checks and separate finite admission. The required Astra xhigh review
completed as `astra_post182`; current `report-astra.md` SHA-256 is
`98a247bacc8f2d2e0db4d8e7bc3164a57f19df3dc0a6901488d54548df0f3037`.
The coordinator read it, independently checked the zero-template/separate-address
call chain, and accepted the narrow source-operand correction and bounded pending
capture design. Both implementation agents have assessed it and are implementing
the reviewed correction and regression checks.
The previous report is archived unchanged at
`findings/research/2026-09-10-post182-astra/report-astra-before182.md` (SHA-256
`5314d914023ea152ee54313f8bd3ec4bb80ba33ff8d1b6b87f70ef13b5500d3a`).
The current boot ledger remains **1/3 consumed**. The receipt is not a generic
reuse override: the next run needs the reviewed one-run policy with no budget
extension. Nothing was pushed to main.

### Candidate 183 implementation and discriminating test

**Built and staged, not yet launched.** Source `94ca24a403135e42af808b83028be48b3709b3b8`,
build `1d5f98d2e5b641eeab1869987f569e73`, binary SHA-256
`d238309a4073395e4f8fe6e85980b9479e8b988a1fff5ce7e4a05b920b91cd5a`.
Run ID `f1728b74e128c5acd35661334bff12be`; sealed manifest
`~/macos-vm/run/candidate-183-manifest.json`, SHA-256
`e809cee6b8dc3cb8749d56dcedeb4dcdb55ab98caf21ee3a5bdd7de59f660775`.
Actual bundle/KDK/firmware preflight passed. Staged picker timeout is verified
at 5 seconds with `ShowPicker=true`. Independent read-only host review found
the same boot, no running VM, ledger 1/3, valid matching recovery receipts and
unchanged helper pins, active sleep inhibition and watchdog capture. Finite
one-run policy creation/review remains before hardware; no budget extension.

1. Route exactly one real-address boundary, `updateContiguousPTEsWithDMAUsingAddr`
   (`0x55cda`), after exact ABI/prologue review. In explicit mode 4, convert only
   the real entry source for valid non-SYSTEM templates. Preserve destination,
   template, count and increment; validate the entire batch span and arithmetic.
   Preserve root repair and existing lease/engine settings. No speculative VMID9
   or global `adjustVRAMAddress` change in this candidate.
2. Add production-path tests for native zero-address templates plus separate MC
   sources, encoded packet fields, SYSTEM/unmap/physical/outside controls and
   batch overflow/aperture boundaries. Capture bounded actual-source samples and
   counters; distinguish packet construction from hardware execution.
3. Keep the recovery parser and five receipt-bound helpers unchanged. Treat only
   the established recoverable missing-chunk case as pending during the existing
   live deadline. Pending exposes no admissible events and cannot launch a probe.
   Test the frozen 182 streaming prefixes; integrity conflicts remain fatal and
   unresolved final capture remains invalid. Report termination cause separately
   from the final scientific boundary.
4. Replace the ineffective template-counter acceptance with real-source evidence.
   Make correlation failures explain their actual predicate; do not manufacture
   cross-thread association. Check readiness against native activity preceding
   the probe. Missing descriptive walks are not completed GPU work or regressions.
5. Coordinator audits, combined regression suite, one build, exact staging and
   finite same-boot admission. One unchanged 180-second run and 45-second probe.
   Success for this boundary requires real source conversion plus downstream
   paging progress; full acceleration still requires checked results and desktop
   presentation. If a later VMID9 root fault appears, record it as the next
   measured boundary. No automatic retry after inconclusive evidence.

**Pre-build audit corrections.** The new updater forwards the native call before
publishing returned-call observations. Counters are cumulative lower bounds;
bounded sample omissions are intentional, not CR2 transport loss. Publication
uses exponential thresholds plus first conversion/refusal signals, so continuous
activity cannot prevent readiness by keeping a quiescence timer reset. Mode 4
retains root repair and its prepared-match check without requiring a fabricated
cross-thread association or an unobserved walk to admit the probe. Legacy mode-3
acceptance remains separate. Combined verification passed **535 Python tests and
16 C++ sanitizer fixtures**, route ownership and diff checks. Log:
`~/macos-vm/run/candidate-183-final-offline-verification.log`, SHA-256
`fad37311f1d1b399c546d8df2e24b1829c18af9a9cefdb8b1c64af11d0408903`.
The log's final hash-printing command had an awk quoting error; the test steps
and their recorded exits all passed. Hashes were read separately. A subsequent
test-only correction strengthens the sample parser fixture to assert successful
decoding for every expected record, including the exact `template=0x1` spelling;
its focused rerun passed **65/65**. Log:
`~/macos-vm/run/candidate-183-classifier-final.log`, SHA-256
`12acb79e8fa5877f19abbef78e23327903b71608565f999f5dddf89264cfb017`.
No candidate 183 hardware cycle has occurred.

**User-requested boot speed change.** Read-only inspection found the guest
OpenCore picker timeout set to 45 seconds, with `ShowPicker=true` and
`TakeoffDelay=0`. The next staged image will use a card-pinned 5-second timeout,
preserving recovery selection. This can remove up to 40 seconds of picker wait;
the actual improvement has not yet been measured. The transform belongs inside
normal staging and sealing; candidate 182 evidence and the host bootloader are
unchanged.

## Historical pre-run record: candidate 182 resumed after reboot — 2026-09-10

Current boot is `d67da91d-94e6-42f0-8dd1-78b42f5496e1`. The user confirmed the
reboot. The ordinary amdgpu-first handoff completed once; Raphael is now on
vfio-pci, with reset methods disabled and runtime power held on. Watchdog and
capture readiness were checked before handoff. The user sleep/idle inhibitor is
active. No GPU experiment has run on this boot yet.

Clean candidate-182 worktree at `e9e541175a028bd43a7df66870409a87a706902c`
passed a fresh 513 Python tests and 14 C++ sanitizer fixtures. Evidence:
`~/macos-vm/run/candidate-182-offline-verification.log`, SHA-256
`298c3d9655ebcd9fcbb35ac1c1a1371966c9f92ff947315946b74186711ec416`.
Independent driver audit matched exact KDK prologues and confirmed the early
identity gate and cached address-conversion callbacks; no driver blocker found.

Before hardware, two agents implemented review corrections. Automatic recovery
now has its own card-pinned interrupted-replay tolerance, separate from functional
classification. Its focused 96-test suite includes the actual archived 181 capture
(snapshot 2: 164 records; open snapshot 3: 37 valid chunks), conflict/ABORT refusal,
and bidirectional card/manifest binding. Log: `~/macos-vm/run/candidate-182-recovery-selector-tests.log`,
SHA-256 `756beac220c29ba1e9040612ba6a755b5f55df197fcde8ed6efe53529f94e0c6`.

Candidate-182 acceptance requires the early gate and a valid complete walk of the
first correlated submitted IB, with raw child addresses already in the physical
domain. The diagnostic walk can translate an incorrect MC child itself, so a
readable diagnostic walk alone is insufficient. The walker also incorrectly
rejected the observed zero-attribute native root; that diagnostic defect is fixed.
Its context-relative indexing reconstructs the frozen directory layout (entry 0
populated, context start `0x400000000`); it is an inference, not independently
proved hardware semantics. Checked workload progress remains decisive. Actual
walks occur at the first correlated dispatch, not the prepared phase previously
claimed: that earlier call supplied no submission and never walked.

The classifier safety correction is complete: early conversion observations do
not trigger a circular wait for a probe that has not launched, while any observed
bad mode/routes, inactive gate, or invalid aperture blocks admission. Focused
classifier/metadata tests passed 65/65 and the VM diagnostic sanitizer fixture
passed; an independent cross-audit also passed 65/65. Scientific verification log:
`~/macos-vm/run/candidate-182-scientific-acceptance.log`, SHA-256
`1fa1ae659233c5781aafb6fb0a906456674d32b0901777f48ccc83781b0f09ef`.
Both implementation agents froze their changes and the coordinator audited them.
Final combined verification passed **522 Python tests and all 14 C++ sanitizer
fixtures**, route ownership, and diff checks. Log:
`~/macos-vm/run/candidate-182-final-offline-verification.log`, SHA-256
`682f1a3cb8fc93637ac73dabb80b4faf46f8df1b7f65c12ee2200217b8c303ef`.
The next step is the single candidate-182 artifact build from this reviewed source.
No candidate-182 artifact has been built or staged yet. Full desktop Metal
remains unverified; the unresolved SDMA/VM fault streak remains **3 (179–181)**.
An unchanged failure in 182 triggers the mandatory Astra review before another
hardware cycle. Nothing has been pushed to main.

## Candidate 181 run and candidate 182 preparation — 2026-09-10 08:20 UTC

Coordinator note by Claude Code (session `015gka3zkh6eBg2CtqZx8MSQ`), acting on the user's
"fix it and run it again" instruction. Full desktop Metal is **still not working**.

**Hardware result (run `8a6beaeb1b5f5800a7e01c1e1954c4b5`, evidence
`findings/experiments/metal-014-181/`).** Candidate 181 (`rgpuvmroot=3`: convert child
PDE and non-SYSTEM PTE addresses through the same aperture arithmetic as the proven VMID2
root repair) installed both routes, repeated the native startup, lease, VMM arena and root
repair, and for the first time in a warm launch the probe reached `commit`: it ended with
`GPU completion timeout after 5 seconds` after 18 channel submissions instead of the old
`e00002bd`. The first GPU fault is unchanged from 179/181: SDMA0 read under VMID 2 with
`MAPPING_ERROR` at `0x400180000` (`VM_FAULT_STATUS=0x201b3b`), then the page queue stall.
The conversion counters classified every counted producer call as outside the MC
aperture (`pde=0/0/43/0/0 pte=0/0/5/301/0`), while a read-only BAR0 dump of the stopped
device shows VMID2's root page directory entry 0 = `0x200000f40b6f4001`: `getPDEValue`'s
exact encoding around an **unconverted** MC child address. The rule is right; the earliest
entries (the first arena block is the VMID2 root) were produced before the wrapper
counted anything. Candidate 182 confirms the Raphael marker at `AMDHWVMM::init`, samples
every `getPDEValue`/`getPTEValue` call with its address domain, counts calls that arrive
before the gate, and walks the VMID2 tables through BAR0 at the prepared phase.

**Cleanup.** Candidate 180's frozen state was retired first (schema-6 receipt
`74d7749f63c04cdaa0034df35c58d308`, recovered and authorizing) using the reviewed
terminal-prefix CR2 tolerance: the clean snapshot 3 (181 records, CRC `0x0d541f1e`)
with 27 garbled physical lines counted as corruption and every valid chunk of the
incomplete attempt matching the prefix (`candidate180-recovery-replay-proof.json`).
Candidate 181's own capture was cut off by the forced stop during replay; the new
`terminal-prefix-open` rule decodes it (terminal snapshot 2, 164 records, no abort,
lifetime VALID), but its schema-3 recovery ended **incomplete**: three MEC HQDs dequeued
cleanly, CP idle, both PSP acknowledgements, no kernel message, yet the temporary host
KIQ did not consume graphics `UNMAP_QUEUES` (the faulted CP left the graphics ring
active). `authorizes_launch=false`; the ledger is 2/3 and **no further launch is
admitted on this boot**. The next experiment needs a fresh host boot, the amdgpu-first
handoff (`SUDO_ASKPASS=... sudo -A ./gpu-bind.sh` in `~/macos-vm`), then the ordinary
first-launch path for candidate 182 (card `experiments/metal-015.json`).

**Same-boot reuse.** The coordinator refuses generic same-boot reuse for lease-schema
launches; `tools/one-run-qualification.py` now provides the finite authority as a
policy-pinned generalization of the candidate-179 helper (`--one-run-policy-sha256` /
`--one-run-activation-sha256`). Two admission refusals preceded the 181 launch, both
before device access (missing authority; identity gate computed helper hashes for lease
schema 2). Their outputs are kept under `run/candidate-181-refused-admission/`.

**Streak accounting.** The unresolved SDMA/VM memory-fault issue now spans three cycles
(179, 180, 181); the fourth-cycle adversarial review rule in AGENTS.md applies before a
fifth. Meaningful progress in 181: probe committed, a channel submission count of 18, and
a directly observed page-table content defect with its producer identified.

**Offline state.** dev `HEAD` carries candidates 181/182; 513 Python tests, the C++
sanitizer fixtures, route ownership, exact-KDK preflight (both new prologues) and the
cross-build pass. Nothing was pushed to main.


## PAUSED at user request — 2026-09-10 06:27 UTC

The user requested: stop after updating this file; do not start new iterations.
Active investigation/implementation agents were interrupted. **No new GPU run,
cleanup attempt, reset, or recovery-proof migration was started.** The proposed
`candidate180-recovery-repair.py` and its tests do not exist yet. Repository code
remains the reviewed dev milestone `9030f1140ec308ed75aba03e7acedace8416312d`;
only coordinator documentation and model-selection instructions changed afterward.
Nothing was pushed to main. Sleep inhibition remains active in the last observed
host state.

### Final known result

Full desktop Metal is **not working**. Candidate180 did prove the zero-attribute
VMID2 repair: independently checksum-validated snapshot0 records 73/74 show
original root `0xf40b6f3000`, repaired/native/prepared/live root `0x84b6f3000`,
`repaired=1`, `reason=repaired`, and both match checks true. The earliest validated
new fault (record76) is `VM_FAULT_STATUS=0x2009bb` at `0x400200000`; paging SDMA
still does not demonstrate successful execution. No identity-bound Metal probe
result exists. Keep the broader unresolved SDMA memory-fault streak conservatively
at **two cycles (179,180)**; do not reset it solely because the address repair
worked. The mandatory fourth-cycle adversarial-review rule still applies.

### Capture and cleanup evidence

Raw verdict/recovery stay INVALID/failed and must not be rewritten. Both agents
independently validated complete snapshots 0,1,3 with the existing per-chunk CRC,
aggregate CRC/FNV, count, and prefix checks. Snapshot2 contains character-level
console interleaving: 27 malformed transport-bearing lines, first at serial line
8464, only 218 intact chunks, no valid END. The final snapshot3 is a contiguous
clean block at lines 12715–13253: 181 records, 18847 bytes, 538 chunks,
CRC `0x0d541f1e`, FNV `0x3b0a2fab724073a0`, zero drop/truncation. It extends the
validated earlier prefixes, and no transport marker follows its END.

Snapshot3 contains nonce-bound OWNED, ACTIVE POOL, and XH3 VALID. The expected
lifetime checksum reconstructed from ownership and pool records is
`0x0f4523b0ec420869`, matching the guest record. **This is guest evidence, not
current BAR authentication.** No valid recovery receipt exists. QEMU stopped;
host responsiveness, vfio accessibility, and an awake device do not prove cleanup.

Frozen raw serial SHA-256:
`af976400493d4b4e5299caee89a9363966029cad0834aa3bace76ec45219c6c8`.
All 12 raw output files are hashed in
`~/macos-vm/run/candidate-180-evidence-sha256.txt` (inventory SHA-256
`b73f72e170c46627865ba414ec3b4e99d8ff949250301c444ae6ffd52aef9934`).
Final host snapshot `candidate-180-final-host.json` is byte-identical to the run's
`host-after.json` (SHA-256 `4565fc54fb00ae0364546bb72fc1de7d63eae0a8ce1022066122f39a1fb87dc7`).
Current boot ledger has one row, SHA-256
`fe4c707f0d0c2f2b163cd5e16e841f33b956c4f5dff87137408465d85979f95d`.

### Pending proposal, not implemented or authorized by execution

On a future resume, assess a narrowly pinned recovery-proof migration for this
run: validate the terminal contiguous CR2 block, require consistency with every
prior complete snapshot **and every earlier valid-CRC chunk** (including incomplete
snapshots), reject later transport/conflicting records/ABORT, pin raw serial,
manifest, original failure, and migration-helper hashes in a separate exclusive
proof. Only after independent code/tests review could it call the unchanged
pinned schema3 VFIO validator, requiring exact current OWNED/ACTIVE POOL/VALID
BAR reads and another full read immediately before scratch writes. Preserve the
original failed receipt and write any repair receipt separately. Do not manually
filter the serial capture, bypass helper hashes, or infer current marker state.
No reboot is requested at this pause; the no-reboot cleanup proposal is untested.

## Candidate 180 hardware result — 2026-09-10 06:17 UTC launch

Run `7966fb1045ddeae71535030cd94deab1`, evidence `~/macos-vm/run/metal-013-180/`,
boot `5aa7641a-6dd5-4cb6-a482-5bd1b15fa946`. Source milestone `9030f11` was
built exactly once and staged/verified. Build ID `51f32e118fba4ec396ced9af51875499`;
manifest SHA `dc32a52e8b12d8a3c91295423771971f3731d2d4435cea0b9be949dcdaea19b7`.
QEMU argv confirms GTK/VMware virtual display plus VFIO Raphael attachment.
No independent window-content proof or accelerated desktop result was obtained.

Raw verdict is **INVALID**, `identity_or_route_missing`, evidence `capture_loss`.
Recovery refused with `CriticalReplayError: CR2 physical line bound exceeded`.
The guest was forced closed after its shutdown request; QEMU is stopped and the
host is responsive. **GPU cleanup is unvalidated**; device accessibility and a
healthy host snapshot are not a valid cleanup receipt. No retry is being attempted.

Direct serial confirms OWNED, ACTIVE POOL, and `XH3 LIFETIME state=VALID` at lines
2551, 2734, 2735, followed by non-null native VMM allocators. CR2 END records are
present, but GPU restart diagnostics interleave with physical replay lines and
strict reconstruction rejects the capture. Agents are examining checksummed
records offline to separate the functional fault from transport corruption.
Root repair / meaningful progress past 179 is not yet claimed. This is the second
actual cycle since 179 crossed the old VMM failure boundary; do not reset that
count until a new boundary is demonstrated.

Routine operations now use Luna, with Sol for driver/recovery investigation and
coordinator audit. The mandatory fourth-stalled-cycle Astra escalation remains.

## Candidate 180 preparation after reboot — 2026-09-10

New host boot verified: `5aa7641a-6dd5-4cb6-a482-5bd1b15fa946`.
amdgpu initialized Raphael and currently owns group31; watchdog/NMI/panic and
crash capture pass, no VM/pending launch or fresh-boot ledger exists. The user
sleep inhibitor was restored without sudo and is active. Pre-bind reset method
`bus` is baseline state, not permission to reset; normal preparation must still
disable reset methods and bind through the reviewed path.

Candidate 180 selects CR2 transport 2 and recovery schema3 via `metal-013`.
Its functional hypothesis is the zero-attribute VMID2 root repair described below.
Readiness review found the classifier's native ownership/VMM gate omitted schema3;
that is fixed with missing/malformed schema3 fixtures (56 classifier tests pass).
The nonce-bound staging transaction was adapted from the audited 179 transaction
with pinned inputs, backups, atomic publication and rollback; independent review
and final source freeze precede build/staging. No GPU run has occurred this boot.

User requested a visible GUI. Existing QEMU argv already uses VMware VGA and
`-display gtk,gl=on` alongside the passed-through Raphael device. Host X11 access
was verified. The next bounded launch will expose that window without topology
changes; it displays the virtual VMware framebuffer, not direct iGPU scanout.

## Capture/cleanup repair verified offline — 2026-09-10 05:47 UTC

**Completed:** three implementation/review agents delivered CR2 capture framing,
strict host reconstruction, and schema3 persistent lifecycle authentication.
Coordinator audited the diffs and test evidence. Final verification: **484/484
Python tests, 14/14 C++ fixtures, whole-driver syntax and exact-24G830 KDK
preflight passed**. Lease activation/invalidation race tests also passed TSan.
Independent guest and VFIO reviews returned GO after the reported races were fixed.
No new hardware cycle, deployment, artifact build, or main push occurred.

Evidence: `~/macos-vm/run/capture-cleanup-verification/`, including
`python-discovery.log` SHA-256
`0107707218d89990f5fe575810367955be21f25a8e267d21cdd926aab0c1234c`,
`cpp-fixtures.log` SHA-256
`6a5bee171ab4370c7c6291205ebfbf9c8a185b8f6018928ec1f8de5ccff52b24`,
`guest-verification-summary.txt`, and exact source hashes. The following chronology
records the implementation and review decisions; final results above supersede
its intermediate pending statements.

**Hardware handoff:** candidate179 remains non-authorizing. Its schema2 ACTIVE
record can survive late invalidation, its replay is malformed, and it has no
schema3 lifecycle marker or valid recovery receipt. Neither selective log parsing
nor new code establishes safe cleanup of that frozen run. A clean host reboot is
required before the next GPU experiment under the project's gates. Same-boot
ledger is exhausted at seven launches; no allowance was bypassed or renewed here.
After reboot: verify amdgpu-initialized baseline and existing safety gates, build
one new candidate from reviewed source, explicitly select CR2/schema3 in its
manifest, and run a bounded functional/cleanup qualification. Pre-VALID crashes
and stopped-WPTR exceptional recovery remain unsupported; do not claim universal
crash recovery or desktop Metal from these offline results.

User requested multiple implementation agents, coordinator audit, then testing.
Three agents are assigned guest capture framing, host reconstruction/regressions,
and independent cleanup-state review. No additional GPU cycle has run.
CR2 replay uses <=40-byte hex chunks with build/snapshot/record identity and CRC32;
an END record verifies a complete immutable-prefix snapshot and its aggregate
digests. All physical lines are designed below 240 bytes including SYSLOG overhead.
The legacy candidate179 capture stays invalid and frozen.

The cleanup audit found that BAR OWNED and ACTIVE can survive a later ABORT;
those bytes cannot replace missing terminal log evidence. A complete replay
snapshot also cannot prove no later invalidation before a crash. A persistent
monotonic invalidation marker is being designed for future candidates. The prior
dev-only relaxation of unrelated replay conflicts is being removed from legacy
recovery admission; arbitrary corruption could otherwise conceal an ABORT.
Host boot remains unchanged and sleep inhibition active. Current179 has no valid
recovery receipt; new software cannot retroactively add its missing marker.

Implementation work is split into three bounded components:

- Guest CR2 framing and lifecycle integration: short hex chunks with checked
  snapshot manifests, prechecked ready slots, immutable record prefixes.
- Host CR2 reconstruction/classification and schema3 recovery integration:
  explicit transport selection, no downgrade on malformed new-format evidence,
  preservation of legacy refusal and frozen179 evidence.
- Independent lifecycle core and tests: 88-byte record at lease+0x200, bound to
  OWNED/POOL checksums and nonce; state publication last, monotonic abort poisoning,
  crash-prefix and activation/abort race tests. Exact VALID readbacks required
  before admission and before recovery writes.

The lifecycle marker cannot authorize early initialization failures before ACTIVE
POOL publication. That limitation must remain explicit. All current work is offline;
source changes alone do not clear the GPU or create another run allowance.

Verification so far: CR2 guest and host agree on the shared 184/511-byte vector
(18 chunks, CRC `c8001837`, FNV `2231439245f39550`). Producer and lifecycle C++
fixtures pass ASan/UBSan; initial host CR2/consumer integration passes 17 focused
tests. Independent review accepted the framing bounds (197-byte chunk lines,
231-byte END lines including the measured prefix/newline). Guest whole-source
syntax passed with existing Lilu deprecation warnings. These are component results;
final integrated verification is pending.

Review corrections made before deployment: short build-ID rejection was reproduced
under ASan and fixed; VALID publication refuses any nonzero existing marker state
and verifies zero before writing; client admission stays blocked during both pool
and lifetime publication. A newly identified race in the older LeaseState phase
is being corrected with atomic transitions before acceptance. Host receipts retain
exact marker reads, with a second full validation immediately before scratch writes.

## Latest run: candidate 179 — 2026-09-10 03:31 UTC

The user approved the prepared one-run policy. Run
`bbbe52426889a90fec1680d5c808dd97` launched at 03:29:00 UTC and ended at
03:31:39 UTC. Evidence: `~/macos-vm/run/metal-012-179/`. This section supersedes
the pre-run status below; no second launch is authorized or attempted.

**Meaningful progress past 178-B:** frozen serial line 15519, event 65:
```text
XV2 VMM phase=native enable=1 base=0xf40b6f3000 arena=0xffffff9b1637c280 pool0=0xffffffa4b0190180 pool1=0xffffffa4b0190200
```
Both software pools exclude the native lease `[0xfaf3000,0xfb08000)` with exact
`0x10000000 -> 0xffeb000` free-byte changes. Paging submissions now reach SDMA
(events 81 and 180); the old pre-submission/VMM-arena boundary is crossed.
The previous at-least-four-cycle streak is retired on this evidence, not on a
successful Metal result. New downstream issue count: **one actual cycle**.

**Current functional failure:** SDMA paging fetch faults at `0x400180000`,
`VM_FAULT_STATUS=0x201b3a`. Captured VMID2 root is `0xf40b6f3000`, with root repair
declined as `unsupported-flags`. BAR-to-MC root translation is under offline
investigation; this is a hypothesis, not yet a proven fault mechanism. No completed
Metal probe or functional desktop is demonstrated.

**Capture/cleanup regression:** raw verdict is `INVALID`, earliest failure
`recovery_lease_pool_missing`, with `definitive critical capture loss; aborting exposure`.
The capture includes a complete later ACTIVE record but corrupted/interleaved
structured replay. Recovery refused with
`ValueError: canonical critical capture has a conflicting replay`; no valid recovery
receipt exists. Preserve the raw verdict; later records do not erase capture ambiguity.
Shutdown was forced after the guest shutdown request. No further device access or
GPU retries are being attempted; agents are auditing the capture offline.

Final host snapshot: same boot, vfio-pci, no active VM, watchdogs/capture/sleep
inhibition active. Operator confirmed no QEMU process remains and no host GPU fault
in the captured kernel messages. Device release is not proof of cleaned GPU state.

| Boundary | 179 result |
|---|---|
| Native VMM arena and allocator construction | Passed |
| Paging SDMA dispatch | Reached; GPU memory fault |
| Correct Metal compute/render | Not demonstrated; no probe result |
| Validated cleanup/reuse | Failed closed on capture conflict |

### Post-run offline findings and changes

The native-root refusal is now reproduced by a regression fixture. The captured
root has zero low attributes; request `flags=0xff` is a separate field. Exact KDK
code at `0x624ed..0x624f8` copies the root into prepared PTB words. The old helper
allowed only root attributes 1 or 5. The agent added observed form 0 within the
existing Raphael/hub0/VMID2/reprogram/aperture gates; SYSTEM and unknown forms
remain refused. The fixture failed before the predicate change and passed under
ASan/UBSan and release-style UBSan afterward. Coordinator reviewed the two-file
diff. It is **dev source only**, not rebuilt or deployed. Hardware causality is
still untested; a later qualified experiment must show repaired/prepared/live
root `0x84b6f3000` and actual PAGE progress.

Capture root cause is more precise than random serial corruption: the structured
POOL replay reaches exactly **255 visible characters** (81-byte envelope plus
174 payload bytes), truncating the checksum after `0x3410` and losing the newline.
Its direct 210-character line is complete. Local Lilu formats into 1024 bytes,
so the demonstrated limit is downstream of that formatter. Other replay records
also truncate at this boundary. An unrelated seq84 replay additionally suffers
transient serial corruption. Internal `truncated=0` tracks the 512-byte storage
slot and does not detect transport truncation. All agents agree malformed POOL
replay must continue to block frozen179 recovery. A future compact/chunked replay
format with bounded physical lines and end-to-end integrity is needed; parser-only
tolerance cannot make this capture valid.

A separate dev-only recovery extractor now limits unrelated replay conflicts to
experiment classification while retaining all XH2 ambiguity/identity/bounds
refusals. Its focused 13-test run passed, including unchanged classifier failure
cases. The real frozen179 capture still fails strict parsing with
`malformed XH2 POOL record`; no recovery was attempted through this code. Test log:
`/tmp/candidate179-recovery-extractor-tests.log`, SHA-256
`763b7e7bfa13fc451258b27e5433af0f3c47903fb3f2a2168b7e8cf8a56be3be`.
These post-run changes are uncommitted/unbuilt and cannot replace the pinned
candidate179 helper identity. Next prerequisite is reliable critical replay
transport and a reviewed recovery path; no new GPU allowance is active.

## Pre-run preparation and historical context

**Standing escalation rule (2026-09-10):** after a fourth consecutive GPU test
cycle with the same unresolved issue, pause routine retries and obtain a
`gpt-6-astra` / `xhigh` adversarial review using the user's exact prompt. Archive
the previous report, review the new findings with implementation agents, and
record the revised experiment before resuming. The durable instructions and
counting rules are in [AGENTS.md](AGENTS.md). Builds and offline unit tests do
not count. Last hardware run remains **178-B**; no new hardware cycles have run
during the current report review. The inherited streak is **at least four cycles: 176, 177, 178-A, 178-B**, all
with no completed Metal command and `e00002bd`. The exact pre-submission boundary
is directly observed in 177 and 178-A/B; 176 has no downstream SDMA callback but
lacks the later submission observer. This conservative symptom-based trigger
is sufficient to request a fresh Astra review before any more hardware testing.
The original report is preserved in `findings/research/astra-reviews/2026-09-09-2138-original/`.
Current offline work corrects native recovery ownership and adds backing allocation
observations; it has not demonstrated functional progress or reset the streak.

Last updated: **2026-09-09 23:24 UTC**. Maintained by the coordinator after each hardware run,
material finding, implementation change, or review correction. This is the current review entry
point; older handoffs and chronological findings can contain superseded conclusions.

**Latest offline verification:** the frozen integration passes **449/449 Python
tests** and **12/12 C++ fixtures**, compiled with g++, warnings as errors,
ASan and UBSan. The coordinator read the combined results, checked the final diff,
and verified that the archived 178-B ledger and both receipt hashes match.
Whole-driver Apple-kext syntax and exact-KDK symbol/prologue preflight also passed
for the final guest code. Logs are preserved under
`findings/research/2026-09-metal-integration/candidate-179-offline-verification/`.
These are offline results, not evidence of Metal execution. The coordinator accepted the guest
implementation after checking exact owner guards before native pool mutation and
the native both-pool reserve ABI. See
`findings/research/2026-09-metal-integration/lease-v2-verification.md`.
Candidate metadata is now 1.0.179, and the new experiment card is `metal-012`.
The independent one-run policy is only offline code: no live authority or activation
has been created, and it does not itself approve a seventh launch. The candidate
has now been built exactly once from clean detached commit
`29df146165dec1bbab4829a845aca5e7621c87b9` and staged with verified readbacks;
no GPU cycle or ledger admission has occurred. Last hardware evidence remains 178-B and the streak remains
at least four. Build ID is `aae8954f05dd497ba9019529e6fec39e`; executable SHA-256
is `5642d859aa53b6de849af04c26de0f2682299bfb6d38f4ffb1cc4f40b839c4c7` and ZIP
SHA-256 is `747893ea69c2e0021f35bb84109c6f59fa2346e0792c22b4ee5529468ab63255`.
Full identities and logs are in `~/macos-vm/run/candidate-179-build-identities.json`
and `candidate-179-verification.log`. Archive integrity, clean source, version,
embedded build ID, and x86_64 kext metadata verified. Production build warnings
are Lilu route deprecations and cross-toolchain option/path warnings.
Actual-artifact exact-KDK preflight passed; its sole symbol-name lookup skip,
`kOffVmmInit=0x56d3a`, was independently verified against the exact symbol and
17-byte prologue with no RIP-relative operand. Evidence:
`~/macos-vm/run/candidate-179-preflight.log` (SHA-256
`9cc35583dd43e3ba526d24cc205c84bc1569f384e87429ef31c510318811e222`).
The staging-only transaction passed independent review and completed successfully.
An interrupt window between file replacement and rollback bookkeeping was corrected
and tested offline before execution. Raw/config/qcow readbacks and all backups match.
Run identity is `bbbe52426889a90fec1680d5c808dd97`; staging record
`~/macos-vm/run/candidate-179/staging.json` SHA-256 is
`d35150d0b83fcbfc5b66a32988e555783da2e3a31d14a1d458f903c230e03912`.
Reviewed script and log are preserved as `run/candidate179-stage-e887303d.py`
and `.log`. No hardware launch occurred and the live ledger remains 6/6 with
unchanged SHA-256 `8105707580a4d89b2e883be90730e1e84ad32f42e69a0310264f3e5431f0260f`.
Manifest sealing and draft-only one-run packet generation passed. Manifest
`run/candidate179-qualification-manifests/179.json` SHA-256:
`f6c86824ef8e140ece9476f3d11f388f7336b9e7afe359f69b98db42e37bf05d`.
Draft packet is `~/macos-vm/run/candidate179-review/`; policy SHA-256
`3398648a794835b2cb2344e69ddda57dae1ae25b2fc3b1a0ab7e7917c608e3ed`,
activation SHA-256 `c988cc79a72d3ddc1361ba8c415de6954555e062649ca86182a480e84f87bd97`.
The real authorization validator accepted these drafts in a disposable VM tree.
No live authority exists. Coordinator reviewed the packet: exactly one additional
launch, 180-second VM limit, 45-second probe limit, no automatic retry/extension,
preserved six-row ledger and exact 178-B receipts. Await explicit user renewal of
this exhausted run budget before live activation; general resume was not interpreted
as permission to bypass AGENTS.md's exhausted-budget prohibition. No reboot requested.
The existing
`redeploy.sh` is not a staging-only command and must not be used for this preparation.

**Work resumed:** the user supplied `report-astra.md` and `report.md` and requested
verification, fixes, and automated desktop Metal testing. Three agents are independently
checking native backing/commit dispatch, the allocator regression, and recovery ownership.
The last hardware action remains 178-B's validated cleanup. Fresh read-only checks confirm
the same host boot, vfio-pci binding, enabled watchdog/NMI/panic settings, and active sleep
inhibitor; no QEMU or experiment process was found. No sudo is needed for this investigation.

**Review priorities:** compare 171's reached paging submission with 178's pre-submit rejection;
verify the 240 MiB pool cap and duplicate initialization against actual allocator domains;
resolve the exact native backing/commit rejection. The reports' cap correlation is a strong
lead, not yet a controlled causal result. The proposed test that puts recovery scratch inside
Apple's allocatable heap is rejected: descriptor validation does not establish exclusive memory
ownership. Any functional experiment must preserve that ownership. Candidate179's earlier
commit-correlation design has been replaced by the bounded physical-backing observer.

**New static correction under independent review:** IOAcceleratorFamily2 24G830
`init_pool(unsigned long long, unsigned long long, unsigned long long)` at `0x1facc`
initializes the pool using its first numeric argument, then calls
`reserve(nullptr, second, third)`. It is not a start/end range initializer.
X6000's unequal branch at `0x52a71` therefore does not establish the claimed inverted
range. Both our existing equalization rationale and Claude's suggested field swap depend on
that incorrect interpretation. Agent verification is tracing zero-length reservations,
actual total/visible fields, and native allocation ownership before selecting a correction.
Evidence: local `/tmp/ioaccel.dis` lines 35537 onward and exact X6000 `0x52a1e` routine.
This is a static finding, not evidence that restoring capacity makes Metal work.

**Recovery ownership regression found offline:** independent review resolves the VMM
68 MiB request to `AMDHardware::appendToReservedVRAMOffset` (`0x72afe`), a top-down
reservation operation. The logged low address `191922176` is `0x0b708000` (Claude's
hex conversion was off by 8 KiB), yielding the inferred BAR-relative reservation
`[0x0b708000, 0x0fb08000)`. Existing descriptor and scratch at `0x0f000000` and
`0x0f100000` lie within that interval. The software pool cap cannot exclude an earlier
hardware reservation. Successful stopped-device cleanup does not establish non-overlap while
macOS runs. No further GPU transaction is being attempted until the ownership correction is
reviewed. Relocation above the VMM end is also unproven: top-down allocation means older
reservations may occupy that area. The report's “183 MiB consumed below MQD” inference is
unsupported for the same reason. Full address/owner publication remains part of the audit.

**Current result: Metal enumerates and shaders compile, but no Metal command buffer has completed.
Full desktop acceleration is not working.** Two runs of candidate 178 consistently locate the
observed rejection after GPU virtual-address assignment, in backing-memory preparation or
page-table insertion, before channel submission. The next task is to separate those two paths.

## Objective and live work

**Standing regression requirement (user, 2026-09-09):** every change must check for
regressions. Tests must cover the affected behavioral contract and failure cases, not only
source shape. Compare each hardware run with both its immediate baseline and the furthest
previously reached relevant stage (currently 171's client paging submission). Report a lost
stage explicitly; lifecycle success never substitutes for functional progress. Memory changes
must test allocator capacity, visible/total semantics, protected-range ownership, and repeated
initialization. Preserve historical raw verdicts and report functional interpretation separately.


The objective is correct Metal compute and rendering, then a usable accelerated macOS desktop
through the VM display, with repeatable GPU cleanup and reuse that protects the Linux host.
Gaming is outside the current focus. Do not infer an overall completion percentage from the
number of patches or the advertised Metal version.

- **Hardware:** stopped after 178-B; its normal recovery validates. No further hardware run is
  admitted by the completed two-run plan. Its terminal boot ledger is **6/6**; a new finite
  experiment must preserve that history and review fresh hardware prerequisites.
- **Implementation:** candidate 178 is an observation change, not a functional memory fix.
  Candidate 179 now contains the native lease, full-pool correction, VMM diagnostics,
  and bounded `AMDAccelVidMemory::allocPhysical` observer. The earlier commit-correlation
  design is superseded. Offline integration passed and the candidate is built; deployment
  and functional validation remain outstanding.
- **Research:** Metal and Raphael/Navi/Linux reports are written. The combined list of exactly
  20 potential issues is written and cross-reviewed. Further research and the native
  commit-target analysis have resumed against both external reports.
- **Documentation:** candidate 178 archives and roadmap updates are written on `dev` and
  reviewed. Archive checksum and identity checks passed; small wording corrections are underway.
- **Integration:** no merge or push to `main` until full acceleration is demonstrated.
  One local dev milestone and one isolated experimental build were completed. No push
  or published release was performed.

| Owner | Active responsibility |
|---|---|
| Coordinator | Reviews both reports, verifies host state, coordinates implementation; maintains this status |
| `lease_review` | Sol agent auditing/fixing guest lease, native ordering, and VMM arena diagnostics |
| `host_review` | Sol agent auditing host lease validation, regression comparisons, and host integration plan |
| `harness_v2` | Sol agent integrating prestaged nonce identity, canonical recovery records and VMM readiness |

`astra_stall_review` completed the required review; its report and accepted next
test are linked below. Guest and host integration passed the combined offline suite;
the agents are now verifying the built artifact and preparing staging without launch.

Implementation and testing are delegated to agents; the coordinator reviews their changes.
Other reviewers should provide sourced suggestions rather than start another VM or touch the GPU.

## Current implementation decision

**Fourth-cycle review complete:** the fresh [report-astra.md](report-astra.md)
has SHA-256 `5314d914023ea152ee54313f8bd3ec4bb80ba33ff8d1b6b87f70ef13b5500d3a`.
The coordinator read it in full and independently checked the VMM retry, arena
factory/reserve and null-allocator instruction intervals. Its H1 and minimum
functional experiment are accepted, with runtime attribution still conditional.
Guest/host agents are addressing the reported integration defects and will assess
the final report before hardware testing. The implementation sequence is recorded
in [the revised plan](docs/superpowers/plans/2026-09-10-native-vmm-arena.md).
No functional progress is yet measured, so the inherited streak remains at least
four; completion of this review does not reset it.

**Fresh adversarial finding (21:44 UTC, verification continuing):** native
`AMDHWVMM::setMemoryAllocationsEnabled` does not return when `VMM+0x20` is
non-null. Its `0x5793d` branch skips channel creation but reaches `0x57ba8`.
At `0x57bdc` it requests the full `0x4400000` arena at `VMM+0x50`, stores the
returned object at `+0x58`, and exits at `0x57d18` if null. The two page-table
allocators at `+0x78` and `+0x80` are created only after that succeeds. The
historically inferred arena ends at `0x0fb08000`, beyond our `0x0f000000`
software-pool cap. Astra resolved the service target through `AMDHWHandler`
`createVidMemoryWithPhysicalAddress` (`0x4ab86`) to
`AMDAccelVidMemory::withPhysicalAddress` (`0x3a830`), whose reserve-enabled
branch calls `AMDHWMemory::reserve` and returns null on failure. Separately,
`allocVMBlock` (`0x57ed2`) returns false immediately if `VMM+0x78` is null.
This is a concrete candidate explanation for absent mapping resources, stronger
than generic exhaustion; runtime allocator pointers still need verification.
Existing VMM route diagnostics will
record these fields in the corrected candidate. No new GPU result is claimed.

**Discriminating prediction:** if the top-down cursor is unchanged from 178-B,
the new 0x15000-byte lease is `[0x0faf3000,0x0fb08000)` and the following
68 MiB VMM arena becomes `[0x0b6f3000,0x0faf3000)`. These are source-derived
predictions, not measured addresses or mandatory hardcoded locations. Acceptance
uses the actual native allocation and full memory base. A final `XV2 VMM
phase=native enable=1` record must show non-null `arena`, `pool0`, and `pool1`
(`VMM+0x58/+0x78/+0x80`). If it never returns, the critical native-entry log
separates that stall from a returned null arena. Even all three non-null pointers
are only prerequisites: the unchanged probe must still complete correct GPU work.

Root and Astra independently also found the pending guest OWNED/POOL log nonce
order reversed relative to the host parser. Agents are correcting the producer
and adding a log-format contract test; matching binary fixtures alone missed it.
Root subsequently verified an allocator-enable ABI defect: its native tail target
`isDeviceValid` returns through `mov al`/`and al,1` (`0x7091b..0x7092d`), so
upper EAX bits are not a Boolean result. The lease wrapper must use the Boolean ABI
before treating enablement as successful. This is being corrected offline.

The first functional candidate will correct recovery ownership and remove the 240 MiB cap,
while retaining the 256/256 MiB equalization and `rgpuvmm=3` to avoid combining independent
hypotheses. The obsolete forced `AMDHWMemory::enableAllocations` call/route will be removed
as part of making native pool initialization authoritative. A dynamic, native-owned type-0
reservation is being designed before VMM/queue initialization; the exact same range must then
be excluded from both software pools before ordinary clients can allocate. Its launch-bound
nonce/locator must reach the host without occupying somebody else's VRAM. Host cleanup must
also handle a guest crash before final software-pool activation; missing ownership proof must
never authorize scratch writes. No fixed free gap has been assumed.

The independent observer uses exact 24G830 `AMDAccelVidMemory::allocPhysical` at `0x3aa76`,
not the compiler-generated base prepare helper. It preserves native behavior and records a
bounded set of allocation failures with independent live true/false completion counts. No
cross-call slot reuse, map/probe association, extra virtual invocation, or MMIO is introduced.
The root reviewed the helper/test and route/parser diffs. The agent reports 53 focused Python
tests, concurrent ASan/UBSan C++ fixtures, whole-driver syntax, route ownership, and exact
symbol/prologue checks passing. Review follow-ups added live replay preservation and sixth-route
readiness without requiring workload callbacks; periodic publication is being budgeted for the
full exposure. These are offline results, not native GPU acceptance. Restoring native 512/256 capacity is a subsequent separate functional experiment.

The v2 wire contract is now fixed for implementation: an immutable 80-byte OWNED record at
lease+0, and a separate 104-byte pool result at lease+0x100. The compact lease occupies
0x15000 bytes; scratch starts at +0x1000 and ends at +0x14004. Host and guest tests must agree
on every byte. Byte-identical log replay is not a new lease; conflicting identity/status is
rejected. The old v1 format remains readable only for historical receipts, never a fallback
for a new GPU launch. No ledger revision or device transaction has been performed.

## Reproducible target

| Item | Current value |
|---|---|
| Guest | macOS Sequoia **15.7.9**, build **24G830**, x86_64 |
| GPU | AMD Raphael, GC 10.3.6, physical PCI `1002:13c0` at `0000:7b:00.0` |
| Guest identity | Navi23 spoof `1002:73ff`; Metal name `AMD Radeon Navi23` |
| Host | CachyOS kernel `7.2.3-1-cachyos-bore` |
| Host boot ID | `5d6f45d0-4384-4340-b819-7751bc26ebb3` |
| GPU ownership | `vfio-pci`, IOMMU group 31; host display remains on the discrete GPU |
| QEMU | 10.1.2 |
| Branch | `dev`; documentation work is currently uncommitted |
| Candidate source commit | `ef326108b868a00efb292e481ea2efb866205efa` |
| Candidate version | RaphaelGPU **1.0.178** |
| Loaded build ID, both runs | `5908f278b80548d6b9c88e2e9a300ae5` |
| Driver executable SHA-256 | `0456ad80a694d0ccd1a9fa9297f77ba629af8a620e29c877baa710c8be1006a5` |
| Source digest | `cc44faa70f6ad2db0f202e8a831897f1f655784edbf7b8faba1d04ce490940ca` |
| Experiment card | [experiments/metal-011.json](experiments/metal-011.json) |

Both runs used identical driver, configuration, boot disk, boot arguments, and prepared probe.
Their predeclared manifests differ only by run ID. The VM exposure limit was 180 seconds and
the unchanged probe had a 45-second process budget.

```text
-v keepsyms=1 tlbto_us=0 vti=9 serial=3 debug=0x108 -lilubetaall
rgpudump=40000 rgpu=0xfffa5981 rgpuvmm=3 rgpumem=2 rgpuptb=2
rgpumqd=2 rgpuhybrid=1 rgpusdma=1 rgpuvmroot=1 rgpusubmit=1
```

These are evidence of the tested configuration, not instructions to launch it outside the
experiment coordinator.

## Progress and latest results

| Checkpoint | Evidence | Limit |
|---|---|---|
| OpenCore/Lilu injection and Navi23 matching | Exact loaded build verified | Does not prove execution |
| Native KIQ and engine startup | KIQ stamps 1, 2, 3; native engine/accelerator startup succeeds | KIQ completion is not a shader test |
| SDMA topology | One physical SDMA instance retained; residual channel mapping applied | Workload paging remains untested in these runs |
| Metal API and shader compilation | Expected device, Metal 3, library/pipeline/queue/buffer creation | API objects can exist before residency succeeds |
| Resource preparation | **Fails**, consistently in backing/PTE phase | Exact underlying rejecting callback still unknown |
| Channel submission | **Zero** observed `submitBuffer` entries | Work has not crossed this boundary |
| Compute correctness | **Zero** completed rounds or checked values | No passing compute result |
| Render correctness | **Zero** checked pixels | No passing offscreen render result |
| Desktop presentation | Not qualified | Separate surface/display integration remains |
| Normal cleanup and warm startup | Three measured cleanup-to-restart transitions on this boot | Not crash/force-close recovery or unrestricted reuse proof |

| Latest run | 178-A | 178-B |
|---|---|---|
| Run ID | `f103e47500ed4a06ae346df23250d95d` | `4a45f4a4c1dd49c69fab2dc37e2e4898` |
| Start, UTC | 2026-09-09 19:44:52 | 2026-09-09 19:52:41 |
| Startup and capture gates | Passed | Passed |
| Failed map preparations | 483 | 531 |
| Phase counts: capacity / VA / backing-PTE / unknown | 0 / 0 / 483 / 0 | 0 / 0 / 531 / 0 |
| Completed Metal command buffers | 0 | 0 |
| Probe status | 5 / `e00002bd` | 5 / `e00002bd` |
| Shutdown | `exited-after-guest-request` | `exited-after-guest-request` |
| Normal schema-6 recovery | Valid, errors `[]` | Valid, errors `[]` |
| Recorded host/IOMMU/reset fault | None | None |

The raw classifier result in **both** runs remains:

```json
{"verdict":"INCONCLUSIVE","earliest_failure":"sdma_vm_program_missing","warm_reuse":"recovered"}
```

That verdict is preserved. Its required downstream VM-program record is absent because the
observed work never reaches submission. The new phase diagnosis is a separate conclusion from
the trace; it does not turn the original run verdict into a Metal pass.

## Relevant captured evidence

Candidate 178-A retained these native callback snapshots:

```text
SUB: map-phase seq=6 class=backing-pte accel=0xffffff95185b1000 map=0xffffff904c593600 thread=0xffffff86b3670598 pre=0/0/0xb13/0x4000c0000 post=0/0/0xb13/0x4000c0000
SUB: map-phase-summary total=483 capacity=0 va=0 backing-pte=483 unknown=0 dropped=0/0/481/0
SUB: summary process=162/162/162 mappings=483/483/483 prepare=486/486/486 map=483/483/483 submit=0/0/0 dropped=3164/1582
```

Candidate 178-B repeated the same scalar map state on its own guest objects:

```text
SUB: map-phase seq=6 class=backing-pte accel=0xffffff9dcc264000 map=0xffffff98fdc98180 thread=0xffffff99009c70c8 pre=0/0/0xb13/0x4000c0000 post=0/0/0xb13/0x4000c0000
SUB: map-phase-summary total=531 capacity=0 va=0 backing-pte=531 unknown=0 dropped=0/0/529/0
SUB: summary process=178/178/178 mappings=531/531/531 prepare=534/534/534 map=531/531/531 submit=0/0/0 dropped=3484/1742
```

Here `pre` and `post` contain: batch prepared-map count / map prepare count / full map flags /
raw GPU virtual address. Flags bit 0 records an assigned GPU address. Both samples therefore
have an address before and after the failed native call; neither batch is at its capacity limit.

The unchanged probe reached:

```text
RGPU_METAL_STAGE enumerate
RGPU_METAL_STAGE compile_shaders
RGPU_METAL_STAGE compute
RGPU_METAL_STAGE commit
command failed: status=5 error=Error Domain=MTLCommandBufferErrorDomain Code=1
"Internal Error (e00002bd:Internal Error)"
```

Each run's complete nonce-bound JSON reports `passed=false`, `metal3=true`, and zero
`completed_command_buffers`, `compute_rounds`, `compute_values_checked`, and
`render_pixels_checked`. Guest exit is 1; transport exit is 0. `e00002bd` is the IOKit
`kIOReturnNoMemory` value; the Metal wrapper alone does not identify the particular allocator.

The first probe command uses two **256 KiB managed buffers**, `didModifyRange`, compute dispatch,
and a managed-resource synchronization blit. It is not an isolated shader-only workload.
See [tests/metal_probe.m](tests/metal_probe.m). A passing complete probe must check 196,608
compute values and 4,096 rendered pixels, with at least four completed command buffers.

Candidate 178-B also confirms that the global DMA paging channel exists before the failed work:

```text
XV: after forced enable: m_0x20=0xffffff9dcbef2000 m_0x28=0xffffff9dcbd3bc00 m_0x30=0xffffff98fecd6000 -> DMA PAGING CHANNEL PRESENT
XV: setMemoryAllocationsEnabled(1) exit:  m_0x20=0xffffff9dcbef2000 m_0x28=0xffffff9dcbd3bc00 m_0x30=0xffffff98fecd6000 -> DMA PAGING CHANNEL PRESENT
```

This contradicts a simple missing-global-paging-channel explanation. It does not establish that
every per-client page-table object is initialized correctly. Earlier log lines with null pointers
before enablement are not the final enabled state.

### Observation limits

- These are **final blocking phases after native retries**, not necessarily the first failure.
- Detailed samples are bounded and can overflow; atomic lifetime counters continue. The
  independent critical replay and worker validation passed in both runs.
- Object and kernel-thread tokens do not identify the issuing guest PID or probe nonce.
  Do not claim a retained background map is the probe's input or output buffer.
- Capacity and final VA acquisition are excluded as the blocking branch for the **observed
  failures**. Earlier recovered VA misses or unrelated allocation defects are not globally excluded.
- No downstream VM callback is evidence of an earlier stop, not proof that the VMID-2 root,
  PTE flags, SDMA, fences, shader ISA, or display path is correct.

## Exact implementation boundary and next diagnostic

Private offsets below are specific to the extracted **24G830** binaries, not stable APIs:

| Binary | SHA-256 |
|---|---|
| AMDRadeonX6000 | `2e364270c3243c532a9428c670313d5afd20406e42d64edb4fa8f3572504104e` |
| IOAcceleratorFamily2 | `1700f3badafbb9014d55b7f6ecde5cdff0d585bd1f0e143c9f8465e4466e5d35` |

The observed chain is:

```text
batchMemoryMapPrepare (X6000 +0x6550) -> false
  BatchPrepareMappings (+0x18256) -> zero mappings prepared
  BatchPrepare (+0x184d8) -> false
  enclosing command processing -> e00002bd
  submitBuffer -> never entered
```

Candidate 178 observes accelerator `+0x1fb0`, map `+0xc`, map flags `+0x10`, and raw GPUVA
`+0x98` through the existing safe wrapper. It preserves the native result and performs no MMIO,
allocation, waits, or formatted logging in that callback.
See [the phase design](findings/experiments/metal-010-177/memory-map-phase-design.md),
[src/SubmissionTrace.hpp](src/SubmissionTrace.hpp), and [src/RaphaelGPU.cpp](src/RaphaelGPU.cpp).

The current implementation observes `AMDAccelVidMemory::allocPhysical` at **`+0x3aa76`**,
ABI `bool(this)`, exact guarded entry `554889e5415741564155415453504883ec18`.
The callback captures the native result and proven scalar fields without altering allocation.
Four immutable failure samples are retained; live true/false completion counters continue
beyond sample saturation. The sixth route is required before this observer is armed.

Exact 24G830 backing dispatch verified by independent review:

```text
map+0x18 = retained IOAccelMemory* (IOAF init 0x5267e, store at 0x526ea)
IOAccelVidMemory::prepare -> IOAccelMemory::prepare (+0x28d6)
  backing vslot +0x1b0 -> IOAccelVidMemory::wire (+0x561c0)
  backing vslot +0x1e8 -> AMDAccelVidMemory::allocPhysical (X6000 +0x3aa76)
```

A false observed here proves this backing allocation operation rejected. A true result does
not prove that its enclosing map committed, and no sample is identified as a probe resource.
The existing outer backing/PTE phase counts remain separate. The observer records length at
backing+0x40, owner+0x110, allocation element+0x118, raw field+0x120, and flags+0x128.
Unproven placement/alignment semantics remain explicitly raw.

The [earlier candidate179 commit-correlation design](findings/research/2026-09-metal-integration/candidate179-design.md)
is **superseded and not implemented**. Review found that the last commit need not belong to
the final prepare retry, slot reuse was not protected for scanners, and equal counter snapshots
could still be partially accounted. The direct native backing observer avoids those mechanisms.
If backing succeeds but map preparation still fails, the next candidate boundary remains
`AMDAccelMemoryMap::commitIntoGPUPageTable` (+0x3b4d2): task mode selects task+0x260 vslot+0x120
or map+0x118 vslot+0x130. That route has not been added. The first branch can reach native VM
range checks before PTE work; no page-table correction is justified without a measured defect.

Do **not** route `AMDAccelMemoryMap::prepare` at `+0x3b3fe` with the existing trampoline:
its initial displaced span contains a relative branch outside that span. Do not replace native
false results with true, raise the `0x3ff` batch bound, or rewrite PTEs without a measured defect.

## Cleanup, repeatability, and host constraints

Measured cleanup-to-startup transitions are:

```text
candidate176 normal cleanup -> candidate177 successful startup
candidate177 normal cleanup -> candidate178-A successful startup
candidate178-A normal cleanup -> candidate178-B successful startup
candidate178-B -> normal validated cleanup, then stopped
```

Both 178 receipts record two genuine MEC queue dequeues, zero timeouts and forced inactive
clears, a completed temporary host-KIQ graphics retirement fence, final disabled/clean queue and
doorbell state, ordered SDMA shutdown, and both exact PSP ring-destruction acknowledgements.
PCI command remains 3 (bus mastering off), reset methods remain empty, and the recovery kernel
message interval is empty. Both raw/canonical receipt pairs validate under the current consumer
with `[]`; they are semantically equal JSON, **not identical serialized bytes**.

| Receipt | 178-A | 178-B |
|---|---|---|
| Recovery ID | `0975a837f47b47389c032cdb9a3e9a14` | `8fb71c4acf944fa3b6ee545dfb58a448` |
| Raw SHA-256 | `e696db64544372dd986df8319c9bd931bf7e2e81a0c89db4ea0eaebeb34a4fd5` | `ea9f41341b5d0f5ff08f7ef72ee44bd052c2a823ebeaae267c57798b5dd789d5` |
| Canonical SHA-256 | `528a400f4c059bb150ed98f480434599e27fbe3648fc9b6b4f635d6f47b24f4e` | `fc1c08c831cd0b95862ae397f0ac60f09e312bba6316bac67c9cceae609e956c` |

The terminal six-row ledger SHA-256 is
`8105707580a4d89b2e883be90730e1e84ad32f42e69a0310264f3e5431f0260f`.
B's receipt is cleanup evidence; it does **not** override the exhausted experiment policy.

This sequence does not prove recovery from every macOS panic, forced QEMU termination, or host
boot state. Historical host hangs remain unexplained. No finite test guarantees no future hang.

Standing constraints for every reviewer/operator:

- No extra VM launch, live VFIO inspection, MMIO experiment, reset, or manual recovery outside
  a separately reviewed experiment. Do not erase ledgers, receipts, or consumption history.
- Never cycle `vfio-pci -> amdgpu -> vfio-pci`; never use virgin-iGPU passthrough.
- Never use PCI/bus reset, PSP MODE1, GRBM soft reset, or retarget Apple's SMU messages to the
  host CPU's SMU. Preserve the host discrete GPU and sibling devices.
- Current tests and cleanup operate without sudo. Never use `sudo -n` authentication probes.
- No host kernel, Secure Boot, bootloader, `/etc`, or initramfs changes are part of this work.
- `rgpu-work-inhibit.service` is active; watchdog, NMI watchdog, and hardlockup panic read 1.
  Persistent one-second journaling and EFI pstore configuration pass the current capture gate.
  `pstore_files=null` means its contents were not established, not that pstore was empty.

## Evidence and review entry points

- [178-A archive](findings/experiments/metal-011-178-a/manifest.json),
  [events](findings/experiments/metal-011-178-a/events.jsonl),
  [probe](findings/experiments/metal-011-178-a/probe.json),
  [recovery](findings/experiments/metal-011-178-a/recovery.json).
- [178-B archive](findings/experiments/metal-011-178-b/manifest.json),
  [events](findings/experiments/metal-011-178-b/events.jsonl),
  [probe](findings/experiments/metal-011-178-b/probe.json),
  [recovery](findings/experiments/metal-011-178-b/recovery.json).
- [Roadmap](docs/ROADMAP.md) and [historical findings](findings/GPU-RE.md) now include both runs
  and the completed three-transition sample. [A notes](findings/experiments/metal-011-178-a/notes.md)
  and [B notes](findings/experiments/metal-011-178-b/notes.md) explain the retained raw verdicts.
- [Existing Linux comparison](findings/raphael-vs-navi-linux.md) and
  [candidate176 submission forensics](findings/experiments/metal-009-176/submission-failure-forensics.md).
- The [new hardware/Linux research](findings/research/2026-09-metal-integration/raphael-navi-linux.md)
  and [ten hardware hypotheses](findings/research/2026-09-metal-integration/hypotheses-hardware.md)
  are now in the repository. Review corrected the version label, distinguished tagged source
  from verified signatures, and removed a causal exclusion unsupported by the host logs.
  The combined research review is still open.
- The [Metal internals report](findings/research/2026-09-metal-integration/metal-internals.md),
  [Metal hypothesis analysis](findings/research/2026-09-metal-integration/hypotheses-metal.md),
  and [combined top-20 matrix](findings/research/2026-09-metal-integration/top-20-issues.md)
  are now available. The matrix is the intended canonical elimination order; its final review
  is checking virtual-call observation and guest-wiring versus host-IOMMU boundaries.
  Ranks 1 and 2 are the active sibling branches; downstream execution/display rows stay untested.
- Original research drafts and source caches remain under
  `$HOME/macos-vm/run/research/metal-integration-20260909/`.
- Original run directories remain `$HOME/macos-vm/run/metal-011-178-a` and
  `$HOME/macos-vm/run/metal-011-178-b`. Archived evidence is not to be rewritten.

Candidate178 passed 377 Python tests, the focused 72-test experiment/qualification/adversarial
set, C++ UBSan fixtures, whole-driver syntax checking, and exact-KDK preflight before the build.
Those checks establish the tested software properties, not GPU execution. New driver and test changes are present but have not been built or run on the GPU.

Useful external suggestions should name the exact source/build/function, explain how the
observed state can follow, identify contrary evidence, and specify the smallest observation
that would refute the hypothesis. Prioritize backing preparation versus PTE insertion. Keep
later VM/SDMA/ISA/display concerns in the roadmap until work can reach those boundaries.
Do not revive the superseded claims that a stale PSP ring is the entire problem, that KIQ cannot
execute, or that Metal enumeration already demonstrates acceleration.
