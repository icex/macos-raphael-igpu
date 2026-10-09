# Console helper source package

This artifact supplies the installer, transaction coordinator and three exact guest helper sources together. It is not a
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
logic; macOS filesystem/signing behavior, clean-user login, second-boot consent,
input/default-audio and update recovery still need native qualification. Sessions remain bounded to6000seconds. This is an experimental
source package, not an unattended daily-use product.
