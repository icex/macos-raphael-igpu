#!/bin/bash
# Run INSIDE the macOS guest before a physical-display observation.
# Bounded launchd job survives the command relay shell. Never sleep in the relay.
set -euo pipefail
label=org.raphael.physical-display-awake
if /bin/launchctl list "$label" >/dev/null 2>&1; then
    /bin/launchctl remove "$label"
fi
/bin/launchctl submit -l "$label" -o /var/tmp/rgpu-awake.log \
    -e /var/tmp/rgpu-awake.err -- /usr/bin/caffeinate -d -i -u -t 6000
sleep 1
assertions=$(/usr/bin/pmset -g assertions)
printf '%s\n' "$assertions"
if ! printf '%s\n' "$assertions" | /usr/bin/grep -Eq 'PreventUserIdleDisplaySleep[[:space:]]+1' ||
   ! printf '%s\n' "$assertions" | /usr/bin/grep -Eq 'UserIsActive[[:space:]]+1'; then
    echo 'Missing display-awake assertion' >&2
    exit 1
fi
