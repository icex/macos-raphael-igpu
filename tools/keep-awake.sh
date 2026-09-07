#!/usr/bin/env bash
# Hold a systemd idle+sleep inhibitor for as long as the macOS VM container exists.
# Releases by itself when the VM stops, so it never outlives the work.
set -euo pipefail
NAME="${1:-macos-sequoia}"

# grep -c, not grep -q: see the comment in redeploy.sh's passthrough guard.
running() { [[ -n "$(docker ps --filter "name=^${NAME}$" --format '{{.Names}}')" ]]; }

# Give a VM that is still starting a chance to appear.
for _ in $(seq 1 60); do running && break; sleep 2; done
running || { echo "no container named ${NAME}; not inhibiting"; exit 0; }

exec systemd-inhibit \
    --what=idle:sleep \
    --who="macOS VM" \
    --why="macOS VM ${NAME} is running" \
    --mode=block \
    bash -c "while [ -n \"\$(docker ps --filter 'name=^${NAME}\$' --format '{{.Names}}')\" ]; do sleep 20; done"
