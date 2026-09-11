# Temporary automatic login for the desktop experiment

Apple documents automatic login as a macOS setting and states that it is
unavailable when FileVault is enabled or when an organization manages the Mac.
Those are treated as hard prerequisites by the temporary transaction.  The
transaction also refuses an enrolled DEP/MDM guest and verifies the selected
local account and UID before changing loginwindow state.

Apple does not publish a supported command-line interface or source for creating
`/etc/kcpassword`.  Searches of Apple's open-source distributions found the
Security/keychain implementation, but no loginwindow `kcpassword` encoder.  The
repeating-XOR format used here is therefore a private, undocumented interface.
Its presence is not proof that login succeeded.  The only useful validation is
a subsequent guest observation showing UID 501 at the console, an on-console
CGSession, a `gui/501` launchd domain, and then a successful virtual-display
lifecycle in that Aqua session.

The password is read from the existing host `.guestpw` file only after checking
that it is a regular, non-symlink 0600 file.  It crosses into the exact supervised
QEMU container over `docker exec -i`, then is served once from memory on a
nonce-specific URL.  Request logging is disabled.  It is piped directly into a
small guest C encoder and never appears in argv, an environment variable, the gx
command file, evidence, or this repository.  Python cannot promise complete
memory zeroization; the host buffer is overwritten on a best-effort basis and
the container-side process exits after its single bounded request.

Before changing the login preference or credential file, the guest saves exact
content and filesystem metadata (or records absence), installs a root-owned
LaunchDaemon and restore script, and verifies that launchd accepted it.  The
absolute deadline survives a guest reboot through `RunAtLoad` and a 30-second
interval.  Explicit restoration uses the same path.  Backups are removed only
after content, owner, group, and mode restoration verifies successfully; failed
restoration leaves root-private evidence and backups in place.

Primary product documentation: [Apple, Change Users & Groups settings on Mac](https://support.apple.com/guide/mac-help/change-users-groups-settings-mtusr001/mac), and [Apple Platform Deployment, Automated Device Enrollment](https://support.apple.com/guide/deployment/automated-device-enrollment-dep73069dd57/web). The format classification above is based on the absence of a corresponding API or implementation in [Apple's open-source distributions](https://github.com/apple-oss-distributions).
