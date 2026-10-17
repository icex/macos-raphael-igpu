#!/usr/bin/env bash
# Host-driven window-drag test for the running macOS guest (iGPU display in QEMU's window).
#
#   tools/rgpu-window-test.sh [SECONDS] [WINDOWS] [LABEL]
#
# Builds tools/rgpu-window-stress.m in the guest (first run), runs it in the logged-in
# desktop session, and reports, for the same interval:
#   - display frames per second actually delivered to QEMU's window (kext SDMACOPY records),
#   - Apple's failed VRAM allocations ("AMD ERROR! Failed to allocate"),
#   - the app's move-timer rate and hitches (main-thread gaps over 50/100 ms),
#   - free VRAM and the orphaned-allocation cache before and after.
set -euo pipefail
SECONDS_RUN="${1:-60}"; WINDOWS="${2:-3}"; LABEL="${3:-run}"
HERE="$(cd "$(dirname "$0")" && pwd)"
KEY="${RGPU_GUEST_KEY:-$HOME/macos-vm/vmkey}"
SERIAL="${RGPU_SERIAL_LOG:-$HOME/macos-vm/run/serial.log}"
G=(ssh -i "${KEY}" -p "${RGPU_GUEST_PORT:-50922}" -o BatchMode=yes -o ConnectTimeout=10 "${RGPU_GUEST_USER:-$USER}@127.0.0.1")
DIR=/var/tmp/rgpu-window-stress
APP="${DIR}/Stress.app"

"${G[@]}" "mkdir -p ${APP}/Contents/MacOS && cat > ${DIR}/stress.m" < "${HERE}/rgpu-window-stress.m"
"${G[@]}" "cd ${DIR} && { cmp -s stress.m stress.built.m && [ -x ${APP}/Contents/MacOS/stress ]; } || {
  xcrun clang -fobjc-arc -O2 -Wall -Werror -framework AppKit -framework QuartzCore -framework Metal stress.m \
    -o ${APP}/Contents/MacOS/stress && cp stress.m stress.built.m &&
  printf '%s' '<?xml version=\"1.0\" encoding=\"UTF-8\"?><plist version=\"1.0\"><dict><key>CFBundleExecutable</key><string>stress</string><key>CFBundleIdentifier</key><string>org.raphaelgpu.window-stress</string><key>CFBundlePackageType</key><string>APPL</string><key>NSHighResolutionCapable</key><true/></dict></plist>' > ${APP}/Contents/Info.plist; }"

stats='ioreg -r -d 1 -c IOAccelerator | grep -o "\"PerformanceStatistics\" = {[^}]*}" | head -1 | grep -oE "\"(vramFreeBytes|orphanedReusableVidMemoryBytes|inUseVidMemoryBytes)\"=[0-9]+" | tr "\n" " "'
before="$("${G[@]}" "${stats}")"
line0=$(wc -l < "${SERIAL}")
"${G[@]}" "rm -f ${DIR}/out.json ${DIR}/ws-cpu.txt
  nohup sh -c 'for i in \$(seq ${SECONDS_RUN}); do ps -Ao %cpu=,comm= | awk \"/WindowServer\\\$/{print \\\$1}\"; sleep 1; done' > ${DIR}/ws-cpu.txt 2>/dev/null &
  open -W -n ${APP} --args ${SECONDS_RUN} ${DIR}/out.json ${WINDOWS}; sleep 1; cat ${DIR}/out.json"> /tmp/rgpu-window-test.$$ || true
sleep 6
after="$("${G[@]}" "${stats}")"
ws="$("${G[@]}" "awk '{s+=\$1; n++} END{if (n) printf \"%.0f\", s/n}' ${DIR}/ws-cpu.txt 2>/dev/null" || true)"
segment="$(tail -n +"$((line0 + 1))" "${SERIAL}")"
fails=$(printf '%s\n' "${segment}" | grep -c 'Failed to allocate' || true)
# SDMACOPY records cover 10-second blocks; the first and last straddle idle time before
# and after the run, so only the blocks fully inside it count.
fps=$(printf '%s\n' "${segment}" | sed -n 's/.*SDMACOPY: \([0-9]*\) frames in \([0-9]*\) s.*/\1 \2/p' |
      awk '{r[NR]=$1/$2} END{for (i=2; i<NR; i++) {s+=r[i]; n++; if (min=="" || r[i]<min) min=r[i]; l=l sprintf("%.0f ", r[i])}
           if (n) printf "%.1f %.1f %s", s/n, min, l; else print "? ? none"}')
restarts=$(printf '%s\n' "${segment}" | grep -c 'restart GPU' || true)
python3 - "${LABEL}" "$(cat /tmp/rgpu-window-test.$$)" "${fps}" "${fails}" "${ws:-?}" "${before}" "${after}" "${restarts}" <<'EOF'
import json, re, sys
label, app, fps, fails, ws, before, after, restarts = sys.argv[1:]
def parse(s):
    return {k: int(v) // 1048576 for k, v in re.findall(r'"(\w+)"=(\d+)', s)}
try: a = json.loads(app)
except Exception: a = {'error': app[-300:]}
mean, low, *blocks = fps.split()
print(json.dumps(dict(label=label, display_fps_mean=mean, display_fps_worst_10s=low, display_fps_blocks=' '.join(blocks),
    alloc_failures=int(fails), gpu_restarts=int(restarts), windowserver_cpu_pct=ws,
    app_ticks_per_s=round(a.get('ticks_per_second', 0), 1), hitches_50ms=a.get('hitches_over_50ms'),
    hitches_100ms=a.get('hitches_over_100ms'), present=a.get('present'), worst_gap_ms=round(a.get('worst_gap_ms', 0)),
    vram_mb_before=parse(before), vram_mb_after=parse(after))))
EOF
rm -f /tmp/rgpu-window-test.$$
