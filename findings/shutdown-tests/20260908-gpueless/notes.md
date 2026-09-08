# GPU-less ACPI shutdown test

The guest was launched with `redeploy.sh --no-gpu`, reached its root LaunchDaemon,
and received `system_powerdown` through the verified QEMU monitor peer in the exact
container's PID namespace. It did not exit within the 20-second grace interval.
The supervisor recorded `forced`, with `request_sent: true`, and stopped that CID.
Docker's subsequent running-container listing was empty. No GPU was passed through.

This validates the live request transport and bounded fallback, not graceful macOS
shutdown, GPU queue teardown, or recovery of the previously stuck KIQ.
