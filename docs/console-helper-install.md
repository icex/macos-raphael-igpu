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
1× 4K at the next guest boot with unchanged capture identity. Current stock
spice-gtk stationary-pointer clicks after resize remain defective. Candidate392
qualifies an isolated client-library correction against a matched unpatched build;
it does not update the host system libraries or the guest package. Fresh-user
setup remains unqualified.


## Optional text clipboard (candidate 423)

Clipboard sharing is off by default. The updated external support package adds
`console-clipboard` and the SPICE text handler outside the signed capture app.
Install with the existing support transaction while its owned helpers are stopped;
this does not replace the presenter or change Screen Recording consent. From the
updated package’s source directory, as the logged-in guest user:

```sh
/usr/bin/python3 -B console-preferences.py \
  --support-dir "$HOME/Library/Application Support/RaphaelGPU/console" --set-clipboard on
```

Use `--set-clipboard off` to disable or `--read-clipboard` to inspect the choice.
The setting takes effect at the next normal owned console-agent restart or login,
not immediately in a running agent. Scale and clipboard settings are preserved
independently. Missing or legacy preferences leave clipboard sharing off.

With the admitted SPICE agent channel and a compatible client, copy new plain text
in either desktop and paste in the other. The agent does not export preexisting
guest clipboard contents when it connects. Only UTF-8 text up to 64 KiB is shared;
images, files, primary/secondary selections and embedded NUL bytes are unsupported.
Text is not recorded in agent logs or temporary files. Incoming text above the
limit is discarded while preserving subsequent resize messages, up to the bounded
16 MiB message ceiling; malformed frames or excessive traffic terminate the agent.
Ambiguous timed-out clipboard requests disable sharing until reconnection, and a
disconnect with queued clipboard bytes refuses continuation to avoid replaying
old-client data. Clipboard release never clears the guest’s current contents.

The helper checks AppKit’s change counter before writing, but AppKit provides no
atomic compare-and-clear operation; a concurrent local copy can still race the
final ownership change. Offline parser, socketpair and installer tests pass.
Candidate428 compiles the helper and verifies fresh ASCII and Unicode/multiline
text in both directions through native virt-manager with `GDK_BACKEND=x11` on
KDE. Use this tested backend for now. The Wayland background automation had delayed
clipboard delivery; it is not qualified as equivalent. The check uses actual
GtkClipboard and macOS pbcopy/pbpaste, not an independent transport client.

## Manual USB redirection in virt-manager (428 native qualification)

The reviewed `CONSOLE_USBREDIR=on` profile supplies two empty SPICE redirection
slots on the existing xHCI bus with eight direct USB2/USB3 ports; default off adds none. It does not attach a host
device or give the VM direct access to host USB device nodes. Use the project’s
`console-manager-usbredir.py` entrypoint with the prepared isolated virt-manager
client environment and the existing connection/domain arguments. It starts an
owned private D-Bus session and disables automatic USB redirection before the
SPICE connection. Launching an ordinary unguarded manager does not provide that
manual-only policy. The isolated client must include USB redirection support;
the older candidate 393 client prefix did not.

For the tested KDE setup, launch with `GDK_BACKEND=x11`. In that manager’s
console, open **Virtual Machine → Redirect USB device**, select the intended spare
device, and use the same chooser to disconnect it when finished. The client machine
supplies the device; the device must be supported by macOS and available to the
client. An ordinary desktop authorization prompt may be required. Neither a visible
chooser nor an empty slot alone proves successful USB transfer. Candidate428
verifies Kingston USB3 storage enumeration and repeated read-only I/O, and Arctis
USB audio enumeration/output callbacks. The normal Arctis chooser disconnect
restores Linux audio/HID drivers. Eject storage inside macOS before unchecking it.
The Kingston probe made no writes, but macOS mounted its volumes writable and
eject attempts failed while they were busy; clean Kingston eject is not qualified.
The physical USB device must be attached to the computer running the SPICE viewer;
remote desktop access to a Linux-hosted viewer does not forward USB from the
remote computer automatically.

Do not terminate the viewer process while a device is attached: a forced test
viewer stop left Arctis interfaces detached. The normal chooser disconnect did
restore them. This is a known lifecycle limit, not general crash recovery.
Existing guest keyboard, tablet and QEMU USB audio remain separate devices.
[Topology and client-policy details](../findings/research/console-usb-redirection-plan-20261010.md).

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

Candidate 410 uses a separate, bounded FAT exchange disk to return fresh PCI and
framebuffer inventory from stock VMSVGA. Its nine returned file hashes pass; old 409
temporary files were absent. Existing IONDRVFramebuffer/user-client attachment
means the aperture cannot be assumed unowned. This helper package does not supply
a VirtualBox presentation adapter or acceleration.

Root verified input/awake state and removal of the owned awake job. Natural guest
shutdown and medium closure are independently proven, while the controller's
transient state-query error remains recorded. 406's earlier eight-vCPU functional
qualification and PerfPowerServices CPU limitation remain separate.
[410 result](../findings/research/virtualbox-fat-exchange-native-20261010.md).

A future early-loader suppression experiment changes the AAPL,iokit-ignore-ndrv
property before boot, then performs read-only inventory; it is not installed by this helper and
must not be applied as a live framebuffer takeover.
[Source-backed plan](../findings/research/virtualbox-boot-framebuffer-ownership-20261010.md).
