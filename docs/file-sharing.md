# Private file sharing with the macOS desktop

The local installation shares files while Linux keeps its filesystems mounted.
It does not transfer USB ownership or mount the same raw filesystem twice.

| Finder share | Linux source | macOS mount |
|---|---|---|
| SSD | `/run/media/user/USB-DATA` | `/Volumes/SSD` |
| Nextcloud | `/home/user/Nextcloud` | `/Volumes/Nextcloud` |

Both shares permit read/write access through the separate account `macosshare`.
Its password was selected in a Linux password dialog; the assistant did not
receive it. It is independent of the Linux/macOS account passwords. Connect
from Finder with:

```
smb://macosshare@10.0.2.2/SSD
smb://macosshare@10.0.2.2/Nextcloud
```

Finder can store the password in macOS Keychain. The installed login agent
`~/Library/LaunchAgents/org.raphael.linux-shares.plist` requests these mounts at
GUI login. Saving the credentials avoids another connection prompt. Current
mounts are verified; a subsequent login/reboot has not been exercised.

## Access restrictions

Samba requires SMB3 encryption and signing, with Guest access disabled and
only `macosshare` permitted. The measured session negotiated SMB3.1.1,
AES-128-GCM encryption and AES-128-GMAC signing. The service listens only on
`127.0.0.1:445` inside the current VM container's network namespace. The
guest's QEMU user-network gateway exposes that loopback as `10.0.2.2`.
No SMB ports are published on the Linux host or LAN.

The server container has a read-only root filesystem and bind mounts only
the two selected data paths plus its own configuration/password database.
File access uses Linux uid/gid 1000 and existing permissions. No permissions
were changed on the selected folders. The SSD share avoids extended-attribute
features unsupported by exFAT. No test files were written into either share.

Samba stores its password database in the private state directory, with the
database mode 0600. The password setup helper passes the password through
stdin, without a plaintext password file or password-bearing command line.

## Local configuration and lifecycle

- Service: `~/.config/systemd/user/raphael-macos-shares.service`
- Supervisor: `~/.local/libexec/raphael-macos-shares.py`
- Configuration: `~/.config/raphael-macos/shares/smb.conf`
- Password database: `~/.config/raphael-macos/shares/state/`
- Image recipe and setup evidence: `~/.local/share/raphael-macos-shares/`

The enabled user service starts the SMB container when `macos-sequoia` is
running and stops that container when the VM closes. It holds no sleep
inhibitor and starts no test workloads. If the selected SSD mount is absent,
its share cannot be opened; Nextcloud remains available. It never creates,
mounts, unmounts or claims the SSD device.

Useful commands:

```sh
systemctl --user status raphael-macos-shares
systemctl --user stop raphael-macos-shares
systemctl --user start raphael-macos-shares
python3 -B ~/.local/libexec/raphael-macos-share-password.py
```

Stopping this service stops file sharing only. The Linux SSD mount and VM
are left in place. After changing the separate sharing password, update the
saved credential in Finder/Keychain when prompted.
