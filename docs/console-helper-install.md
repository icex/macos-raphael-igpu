# Console helper source package

This artifact supplies the four exact guest helper files together. It is not a
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

The current installer writes the final app directly. Do not install over a
running presentation session. Atomic replacement/rollback and clean-user login,
second-boot consent persistence, input/default-audio checks are still pending
qualification. Sessions remain bounded to6000seconds. This is an experimental
source package, not an unattended daily-use product.
