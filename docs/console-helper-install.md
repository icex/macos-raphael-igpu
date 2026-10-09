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
