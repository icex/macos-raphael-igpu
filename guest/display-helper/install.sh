#!/bin/sh
# Install the Raphael display helper in the guest (run as root from this directory).
set -eu
mkdir -p /usr/local/libexec
install -m 0755 rgpu-display-helper.py /usr/local/libexec/rgpu-display-helper.py
clang -fobjc-arc -framework Foundation -framework CoreGraphics rgpu-display-mode.m -o /usr/local/libexec/rgpu-display-mode
install -m 0644 org.raphaelgpu.display-helper.plist /Library/LaunchDaemons/org.raphaelgpu.display-helper.plist
launchctl bootout system/org.raphaelgpu.display-helper 2>/dev/null || true
launchctl bootstrap system /Library/LaunchDaemons/org.raphaelgpu.display-helper.plist
echo "display helper installed; HiDPI by default. For 1x: defaults write /Library/Preferences/org.raphaelgpu.display dpi low"
