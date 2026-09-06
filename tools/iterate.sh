#!/usr/bin/env bash
# One iteration of the plugin loop, unattended:
#   1. boot WITHOUT the GPU (guest survives, agent reachable)
#   2. rebuild + install the plugin, relink the Aux KC
#   3. boot WITH the GPU and capture the verdict
# Two boots are needed because a TTL failure still panics the guest until m1's
# doGPUPanic patch actually lands, and a panicked guest has no agent.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

# The container is recreated on every boot (--rm), so agent-server.py has to be
# re-copied each time. Errors here used to be suppressed, so a race with container
# startup left both servers absent and the only evidence was `curl exit 7` inside
# the guest. Verify they answer before going any further.
boot() {  # $1 = --no-gpu | (empty)
    ./redeploy.sh ${1:-} >/dev/null 2>&1
    for i in $(seq 1 20); do
        docker cp agent-server.py macos-sequoia:/tmp/ >/dev/null 2>&1 || { sleep 2; continue; }
        docker exec -d macos-sequoia python3 /tmp/agent-server.py 2>/dev/null
        docker exec -d macos-sequoia sh -c 'cd /run/vm && exec python3 -m http.server 8889' 2>/dev/null
        sleep 2
        a=$(docker exec macos-sequoia sh -c 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8888/agent' 2>/dev/null)
        f=$(docker exec macos-sequoia sh -c 'curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8889/' 2>/dev/null)
        [ "$a" = 200 ] && [ "$f" = 200 ] && { echo "  container servers up (agent=$a files=$f)"; return 0; }
        sleep 3
    done
    echo "  container servers NOT up" >&2; return 1
}
# The screenshot helper now fails (non-zero) rather than returning a stale frame,
# so honour its exit status. Trusting a stale bright frame previously made this
# return instantly while the guest was still on the OpenCore picker -- and the
# keystrokes that followed cancelled the picker's auto-boot timeout for good.
STATE=""
wait_login() {
    for i in $(seq 1 60); do
        if ./macos-vm.sh screenshot >/dev/null 2>&1; then
            m=$(magick screenshot.png -format '%[mean]' info: 2>/dev/null || echo 0)
            mi=${m%.*}
            if [ "$mi" -gt 30000 ] 2>/dev/null; then STATE=desktop; echo "  desktop (mean=$m)"; return 0; fi
            if [ "$mi" -gt 8000 ]  2>/dev/null; then STATE=login;   echo "  login window (mean=$m)"; return 0; fi
        fi
        sleep 10
    done
    echo "  never reached login" >&2; return 1
}

echo "### 1/3 boot without GPU"
boot --no-gpu
wait_login || exit 1
[ "$STATE" = login ] && ./guest-login.sh >/dev/null 2>&1
./drive.py key meta_l-spc wait 2 type 'Terminal' wait 2 enter wait 8 >/dev/null 2>&1
./drive.py type 'curl -s http://10.0.2.2:8888/agent | sh &' wait 1 enter wait 5 >/dev/null 2>&1
GX_TIMEOUT=30 ./gx 'echo agent-up' || { echo "  no agent" >&2; exit 1; }

echo "### 2/3 deploy plugin + relink Aux KC"
./deploy-plugin.sh 2>&1 | tail -6

echo "### 3/3 boot with GPU"
boot
sleep 150
echo "--- rgpu / verdict ---"
tr -d '\r' < run/serial.log | grep -E 'rgpu|APPLIED|FAILED|c00c02|GPUCAP\] refresh|panic\(' | head -30
