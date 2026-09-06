#!/usr/bin/env bash
# Log the guest in, open Terminal, and bootstrap the agent command channel.
# After this, ./gx '<cmd>' works. Safe to re-run.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# The agent server lives in the container; the guest reaches it at 10.0.2.2:8888.
docker cp agent-server.py macos-sequoia:/tmp/ >/dev/null
docker exec -d macos-sequoia python3 /tmp/agent-server.py || true

if ! GX_TIMEOUT=3 ./gx 'echo up' >/dev/null 2>&1; then
    ./guest-login.sh || true
    ./drive.py key meta_l-spc wait 1.5 type "Terminal" wait 1.5 enter wait 6
    ./drive.py type 'curl -s http://10.0.2.2:8888/agent | sh &' enter wait 3
fi
GX_TIMEOUT=20 ./gx 'echo guest-agent-ready; sw_vers -productVersion'
