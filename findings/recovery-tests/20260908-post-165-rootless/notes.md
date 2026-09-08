# Rootless recovery after candidate 165

Host boot `851d35df-7e63-4154-b70b-5cfa044913d6`; prior experiment
`bbe3258b2ec94444948702a99c1b4f8a` (`hybrid-003`, candidate 1.0.165).
The guest panicked in `createAccelChannels+0x278`; the supervised cleanup confirmed the exact
QEMU container was force-stopped.

`tools/vfio-recover.py` then ran as the desktop user. It opened `/dev/vfio/31`, mapped BAR5,
destroyed the UM/RBI and GPCOM rings, and retained PCI command `0x0003`. Both command-specific
responses completed and the bounded journal interval contained no host fault. No sudo, sysfs
resource mapping, driver rebind, PCI reset, or reboot was used.

This receipt authorizes only the next run on this boot. It proves the cleanup transaction, while
the next experiment must separately prove that the Apple stack reinitializes successfully.
