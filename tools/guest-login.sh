#!/usr/bin/env bash
# Wait for the macOS login window, then log in. Password read from .guestpw (0600),
# so it never sits in a command line or process list.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
[[ -r .guestpw ]] || { echo "no .guestpw" >&2; exit 1; }

# The login window is a bright full-screen wallpaper; the verbose boot console is dark.
for i in $(seq 1 60); do
    ./macos-vm.sh screenshot >/dev/null 2>&1 || true
    m=$(magick screenshot.png -format '%[mean]' info: 2>/dev/null || echo 0)
    if (( ${m%.*} > 8000 )); then echo "login window up after ${i}0s (mean=$m)"; break; fi
    sleep 10
done

./drive.py click 960 900 >/dev/null 2>&1 || true   # focus the password field
./drive.py type "$(cat .guestpw)" >/dev/null
./drive.py enter >/dev/null
echo "password sent"
for i in $(seq 1 30); do
    sleep 5
    ./macos-vm.sh screenshot >/dev/null 2>&1 || true
    m=$(magick screenshot.png -format '%[mean]' info: 2>/dev/null || echo 0)
    echo "  t+$((i*5))s mean=$m"
    # 40000 was too strict: this wallpaper with windows open sits at ~38200, so a
    # perfectly good desktop was reported as "did not reach desktop".
    (( ${m%.*} > 30000 )) && { echo "desktop up"; exit 0; }
done
echo "did not reach desktop" >&2; exit 1
