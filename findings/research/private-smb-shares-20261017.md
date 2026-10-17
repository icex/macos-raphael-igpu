# Private SMB sharing — 2026-10-17

User request: share the Linux-mounted exFAT SSD at
`/run/media/user/USB-DATA` and `/home/user/Nextcloud`, preserving the
ongoing Linux copy and requiring a secured connection. Guest access was
explicitly replaced with a separate authenticated sharing account before
the login was enabled.

The setup uses a local image built from the existing digest-pinned official
Alpine base with distribution Samba packages, version 4.23.8. The server's
network is `container:<current macos-sequoia CID>`, without published ports.
It listens only on loopback. Only the two requested data directories and
its own configuration/private state are bind mounted. The root filesystem
is read-only; runtime/cache/log directories use tmpfs. The supervisor starts
and stops the share container with the VM and never manages the GPU or USB.

The user entered a separate password through KDialog's new-password UI.
The helper required at least 12 characters, passed it to `smbpasswd` and
authenticated verification clients through stdin, then exited. No plaintext
password file, chat credential or password-bearing process argument was used.
The stored Samba database is mode 0600, under a mode-0700 configuration tree.
Mac Finder authentication used that separate `macosshare` account.

Observed checks:

- `testparm` accepted the configuration. Both shares resolve `smb encrypt`
  to `required`, Guest to No, and map-to-guest to Never.
- Anonymous share listing was rejected. An SMB2-only connection was rejected.
- The namespace TCP table showed only `127.0.0.1:445`; connecting to the VM's
  bridge IP on 445 returned connection refused. Host port 445 had no listener.
- Authenticated encrypted SMB clients could read the directory metadata of
  both shares. Their file-name output was discarded.
- macOS mounted both shares as the console user at `/Volumes/SSD` and
  `/Volumes/Nextcloud`; console-user read/write permission checks passed.
- `smbstatus --json` reports SMB3_11, full AES-128-GCM encryption and full
  AES-128-GMAC signing, with both SSD and Nextcloud tree connections.
- `findmnt` still reports `/dev/sda2` mounted as exFAT on Linux at the
  requested source path. No USB redirection, unmount, format, host file
  permission change, benchmark or test-file write was performed for sharing.
- A GUI-login LaunchAgent was installed and passed `plutil -lint`. It uses
  Finder/Keychain authentication for reconnection; no reboot/login test was
  performed while the user was using the VM and copying files.

Evidence is local under `~/.local/share/raphael-macos-shares/`:
`effective-config.txt`, `anonymous-check.log`, `smb2-check.log`,
`session-status.json`, and `mac-verified-mounts.log`. The configuration,
service, supervisor, password helper and image recipe are user-local files,
listed in [the operating guide](../../docs/file-sharing.md).

This is verified current-session file sharing and security negotiation.
Future login/reconnection and server recovery remain configured but not
independently exercised. The GPU run remains the existing desktop session;
this setup did not launch or restart the VM or alter its safety harness.
