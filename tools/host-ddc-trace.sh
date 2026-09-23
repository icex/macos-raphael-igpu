#!/usr/bin/env bash
# Trace the host amdgpu driver's DCN register accesses while it re-detects the
# iGPU HDMI connector and reads its EDID. Root only; the iGPU must be on amdgpu
# (fresh boot, before gpu-bind.sh). Output: a trace file with amdgpu_dc_rreg /
# amdgpu_dc_wreg events, decodable with tools/dcn-trace-decode.py --host-trace.
#   sudo tools/host-ddc-trace.sh [connector=card0-HDMI-A-3] [out=/tmp/host-ddc-trace.txt]
set -euo pipefail
CONN="${1:-card0-HDMI-A-3}"
OUT="${2:-/tmp/host-ddc-trace.txt}"
T=/sys/kernel/tracing
[[ $EUID -eq 0 ]] || { echo "run me with sudo" >&2; exit 1; }
[[ -d "/sys/class/drm/${CONN}" ]] || { echo "no connector ${CONN}" >&2; exit 1; }
[[ -d "${T}/events/amdgpu_dm" ]] || { echo "amdgpu_dm tracepoints missing (is amdgpu loaded?)" >&2; exit 1; }
echo 0 > "${T}/tracing_on"
echo > "${T}/trace"
echo 1 > "${T}/events/amdgpu_dm/amdgpu_dc_rreg/enable"
echo 1 > "${T}/events/amdgpu_dm/amdgpu_dc_wreg/enable"
echo 65536 > "${T}/buffer_size_kb"
echo 1 > "${T}/tracing_on"
# Force a fresh detection and EDID read on that connector.
echo detect > "/sys/class/drm/${CONN}/status"
status="$(cat "/sys/class/drm/${CONN}/status")"
edid_bytes="$(wc -c < "/sys/class/drm/${CONN}/edid")"
sleep 1
echo 0 > "${T}/tracing_on"
cp "${T}/trace" "${OUT}"
echo 0 > "${T}/events/amdgpu_dm/amdgpu_dc_rreg/enable"
echo 0 > "${T}/events/amdgpu_dm/amdgpu_dc_wreg/enable"
[[ -n "${SUDO_UID:-}" ]] && chown "${SUDO_UID}" "${OUT}"
echo "${CONN}: status=${status} edid=${edid_bytes} bytes; $(grep -c 'amdgpu_dc_[rw]reg' "${OUT}") register events -> ${OUT}"
