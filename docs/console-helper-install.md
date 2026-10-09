# Console helper source package

This artifact supplies the installer, transaction coordinator and three exact guest helper sources and the shared source-token header together. It is not a
kext installer or a prequalified clean-guest deployment. The manifest identifies
source commit, whether the packaging tree was clean, and each input's byte count
and SHA256. Keep the package and its manifest with the installed build receipt.

Requirements: logged-in non-root x86_64 macOS user, Command Line Tools (`xcrun
clang`), `/usr/bin/python3`, available AppKit/CoreGraphics/ScreenCaptureKit/IOKit
frameworks, matching Raphael kext and admitted Bochs console VM profile. The
host experiment harness retains all VM/GPU lifecycle ownership.

Extract into a new directory. Run `bash install-console-desktop.sh`, then follow
its printed bootstrap instruction. Use ordinary Privacy & Security settings to
approve Raphael Console for Screen & System Audio Recording. The app identifier
remains `org.raphaelgpu.console`; an ad-hoc rebuild can need renewed permission.
There is no permission bypass. The installer does not start the agent itself.
The presenter and two helpers compile with explicit `-O2`. After signing and
verification, `build-provenance.json` under the console support directory records
actual compiler/SDK, binary hashes, CDHash and designated requirement. It does not
establish consent or runtime success.

The installer refuses a loaded console LaunchAgent or running helpers. Boot out
that agent through the normal guest lifecycle before an update; installation never
stops it. It holds a per-user installer lock, builds and verifies all outputs in a
private staging directory, then publishes the app, launcher, receipt and LaunchAgent
using exclusive renames. Existing unrelated logs are retained. Failed publication
attempts restoration; an interrupted process retains a journal and refuses another
installation until `bash install-console-desktop.sh --recover` restores the previous
files. Observed concurrent edits prevent restoration and retain evidence for manual
review. Old files and transaction results remain in the printed staging directory.

These multiple paths are not a globally atomic update. Other programs do not honor
the installer lock; external launch/edit races remain a limit. No TCC settings are
written and the agent is not started. Host fault-injection tests cover transaction
logic. Candidate364 additionally passes16 tests in disposable macOS directories,
actual existing-user build/sign/publication, active refusal and identical reinstall.
The first changed ad-hoc binary needs ordinary consent renewal; identical reinstall
retains consent. Desktop/default audio pass; input is not rerun. This does not
qualify power-loss recovery of the installed app or clean-user login. Candidate366
subsequently verifies automatic startup and unchanged consent on the next guest
boot for that same installed app; it does not qualify independent host boot or
console-only first setup. [Persistence evidence](../findings/research/console-cadence-native-20261009.md). See [native evidence](../findings/research/console-install-native-20261009.md).
Sessions remain bounded to6000seconds. This is an experimental
source package, not an unattended daily-use product.

Candidate368 also compiles the shared source-token header into the native presenter.
Its opt-in diagnostic passes bounded source-validity windows at native and HiDPI
resolutions; normal copying remains the default. Changing the signed app required
ordinary consent renewal again. Both diagnostic cases restore the original agent
and ordinary capture. This is not fresh-user or unattended deployment qualification.


Candidate370's changed presenter also required normal consent renewal; ordinary
capture succeeded before its one-shot snapshot mode was enabled. Snapshot mode
must not be left in the ordinary login agent: an armed lease cannot be reacquired
in the same QEMU device lifetime. The native test restored the exact original
agent and verified ordinary fallback startup. See
[the snapshot setup and limits](virtual-console.md#immutable-snapshots-and-single-rectangle-native-experiment-370).

Candidate374 reuses the exact installed370 presenter executable and retains
startup/consent on the next guest boot without reinstalling. This remains an
existing-user result, not fresh-user or console-only first setup qualification.

Candidate376 again retains the installed370 binary/consent. After orderly snapshot
exit, native positive/negative controls verify ordinary BAR0 mapping and deny
snapshot regrant. The original login agent is restored byte-for-byte and ordinary
awake3840x2160 capture restarts. This does not qualify client-crash cleanup or
rearming snapshot mode within the same VM lifetime.

Candidate379 again retains the installed370 presenter binary and consent. After
snapshot-owner retirement, legacy BAR0 mapping succeeds while ARM and staging
regrant are denied; the original agent resumes fresh, awake3840×2160 capture.
Default stereo delivery and independent audio-route restoration pass. This does
not qualify fresh-user consent setup or snapshot-owner restart in the same VM.
[Evidence](../findings/research/console-event-native-20261009.md).

Candidate381 retains the installed presenter and normal consent while selecting
existing guest modes and explicitly matching the manager viewport's physical
pixels. No presenter reinstall or permission bypass is needed for this
configuration result. Retirement still denies snapshot regrant, then the original
agent restores ordinary awake3840×2160 capture. At that historical381 milestone, automatic window-to-guest resizing was not
installed. Subsequent383 transport and385–392 external support qualify the bounded
installed path described below; personality inventory alone was insufficient.
[Viewport qualification](../findings/research/console-viewport-native-20261009.md).


## Persistent guest scale

The optional external resize-support package installs a preference tool outside
the sealed capture app. From that package's source directory, as the logged-in
guest user:

```sh
/usr/bin/python3 -B console-preferences.py \
  --support-dir "$HOME/Library/Application Support/RaphaelGPU/console" --set-scale 1
```

Use `--set-scale 2` for HiDPI2 or `--read-scale` to inspect the choice. This writes
`console-preferences.json` in the owned support directory. Missing preferences
retain2× compatibility; malformed preferences refuse startup. Support-payload
updates preserve the preference. Apply a changed policy at the next normal owned
console-agent restart or guest login; it does not change a running holder in place.
No capture app rebuild, re-signing or consent change is involved.

Scale1 allows odd physical dimensions within640..3840 ×480..2160 and equal logical
sizes, useful for a GDK1 manager window. Scale2 requires even dimensions and maps
to half-sized logical dimensions. This is a user choice, not automatic host-DPI
detection. Candidate390 validates both policies and candidate392 restores selected
1×4K at the next guest boot with unchanged capture identity. Current stock
spice-gtk stationary-pointer clicks after resize remain defective. Candidate392
qualifies an isolated client-library correction against a matched unpatched build;
it does not update the host system libraries or the guest package. Fresh-user
setup remains unqualified.


## Restartable immutable presentation (394/395/402)

The updated external launcher selects the sealed presenter's existing snapshot
mode only when the bridge reports both SnapshotProtocol1 and SnapshotRestartable1.
It explicitly selects default RAM cache policy and overrides inherited snapshot/
cache variables; legacy or unavailable capability selects ordinary presentation.
Presenter failure propagates and owned children stop, with no hidden fallback or
restart loop. This requires the matching experimental QEMU image and driver;
ordinary stock QEMU does not acquire the restartable capability through packaging.

394 verifies installed capture and two owned session restarts without app changes.
395 additionally passes explicit retained-map cleanup and capacity recovery, plus
two mixed-motion observations. The old one-shot snapshot image remains one-shot;
its restart limitation is not waived.395 retains private guest-shutdown/Docker
exit0 evidence despite an original unverified reporting classification.394
capture-abort teardown is not a clean shutdown. See
[qualification evidence](../findings/research/console-private-staging-cleanup-native-20261009.md).

Candidate 402 retains the same sealed presenter and external-helper interfaces.
Its optional host-private pool requires the exact experimental QEMU image and
`CONSOLE_SNAPSHOT=restart-timing-pool`; no capture-app replacement or fresh consent
was needed for this test. Owned restart, odd resize, input and audio regressions
pass. Natural shutdown/recovery pass with two corrupt serial lines and two incomplete
snapshots retained separately. Pooling is not enabled by this installer on stock QEMU.
[402 evidence](../findings/research/console-snapshot-private-pool-native-20261010.md).

## Actual VirtualBox software-boot scope

Candidate 403 reaches a software desktop with eight vCPUs and RealTSCOffset;
clock mode and frequency changed together. Candidate 401's earlier one-vCPU
keyboard and awake checks remain separately scoped. Neither qualifies this
accelerated helper package or a GPU transport on VirtualBox. New eight-vCPU input,
orderly shutdown and long-term clock stability remain open. Before controlled
shutdown, stop only the test's owned awake job and verify that it no longer blocks
Terminal closure.
[403 result](../findings/research/virtualbox-eight-cpu-real-tsc-native-20261010.md).
