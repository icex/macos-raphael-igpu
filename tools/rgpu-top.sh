#!/usr/bin/env bash
# Live GPU/CPU view of the running macOS guest, printed once per second on the host.
#
#   tools/rgpu-top.sh [seconds]        (default: until Ctrl+C)
#
# Columns: GPU busy % (Apple's "Device Utilization"), free VRAM, time the driver spent
# waiting for VRAM evictions during the last interval (stalls show up here), GART use,
# guest CPU busy %, the busiest guest process, and the host CPU used by QEMU.
# Guest values come over the project SSH key (port 50922); the host column needs no root.
set -euo pipefail

KEY="${RGPU_GUEST_KEY:-$HOME/macos-vm/vmkey}"
PORT="${RGPU_GUEST_PORT:-50922}"
USER_NAME="${RGPU_GUEST_USER:-$USER}"
limit="${1:-0}"

qemu_pid="$(pgrep -f qemu-system-x86_64 | head -1 || true)"
[[ -n "${qemu_pid}" ]] || { echo "macOS is not running" >&2; exit 1; }
hz="$(getconf CLK_TCK)"
qemu_ticks() { awk '{print $14 + $15}' "/proc/${qemu_pid}/stat" 2>/dev/null || echo 0; }

# One SSH session streams one line per second; the host side adds QEMU's CPU use.
guest_loop='
prev=""
while :; do
  stats=$(ioreg -r -d 1 -c IOAccelerator | grep -o "\"PerformanceStatistics\" = {[^}]*}" | head -1)
  val() { printf "%s" "$stats" | grep -oE "\"$1\"=[0-9]+" | head -1 | cut -d= -f2; }
  util=$(val "Device Utilization %"); free=$(val vramFreeBytes); wait=$(val vramEvictionWaitTime)
  gart=$(val gartUsedBytes)
  cpu=$(top -l 2 -n 1 -s 0 -stats command,cpu -o cpu | awk "/^CPU usage/{u=\$3+\$5} END{print u}")
  topp=$(ps -Ao %cpu=,comm= -r | head -1 | awk "{n=\$2; sub(/.*\\//,\"\",n); printf \"%s %s%%\", n, \$1}")
  dwait=0; [ -n "$prev" ] && dwait=$(( (${wait:-0} - prev) / 1000000 )); prev=${wait:-0}
  echo "${util:-?} $(( ${free:-0} / 1048576 )) $dwait $(( ${gart:-0} / 1048576 )) ${cpu:-?} $topp"
  sleep 1
done'

printf '%-8s %-6s %-9s %-11s %-7s %-9s %s\n' TIME GPU% VRAMfree EVICTwait GART CPU% "QEMU%  busiest guest process"
last="$(qemu_ticks)"; last_t="$(date +%s.%N)"; count=0
ssh -i "${KEY}" -p "${PORT}" -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5 \
    "${USER_NAME}@127.0.0.1" "${guest_loop}" | while read -r util free dwait gart cpu name pct; do
    now="$(qemu_ticks)"; now_t="$(date +%s.%N)"
    qemu="$(awk -v a="${last}" -v b="${now}" -v t0="${last_t}" -v t1="${now_t}" -v hz="${hz}" \
        'BEGIN{d=t1-t0; if (d<=0) d=1; printf "%.0f", (b-a)/hz/d*100}')"
    last="${now}"; last_t="${now_t}"
    printf '%-8s %-6s %-9s %-11s %-7s %-9s %-6s %s %s\n' "$(date +%T)" "${util}" "${free}MB" \
        "${dwait}ms" "${gart}MB" "${cpu}" "${qemu}" "${name}" "${pct}"
    count=$((count + 1))
    (( limit == 0 || count < limit )) || break
done || true
