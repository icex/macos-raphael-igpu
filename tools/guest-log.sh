#!/usr/bin/env bash
# Pull plugin / AMD-driver os_log output from the guest.
#
#   ./guest-log.sh rgpu|amd [minutes]
#
# TWO traps this exists to avoid, both of which produced confident false zeros:
#  1. Lilu plugin SYSLOG and the AMD kexts' driver messages go to os_log, NOT to
#     serial. Only Lilu's early "config:"/"api:" lines and kprintf reach the 16550.
#     Grepping run/serial.log for them reports nothing and looks like failure.
#  2. `log show --last Nm` silently returns nothing when N is smaller than the
#     guest's uptime, because the interesting lines are emitted at boot. Default
#     the window from guest uptime, never a guess.
#  3. Since the plugin moved into the BOOT kernel collection (OpenCore Kernel>Add), its
#     start-up and kext-callback messages are emitted long before logd exists, so they
#     NEVER appear here -- `log show` legitimately returns nothing for them. Serial is
#     the only channel for anything logged before userspace. Use this for late messages.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
WHAT="${1:-rgpu}"
case "$WHAT" in
  rgpu) PRED='eventMessage CONTAINS "rgpu: @"' ;;
  amd)  PRED='senderImagePath CONTAINS "AMD"' ;;
  *)    echo "usage: $0 rgpu|amd [minutes]" >&2; exit 1 ;;
esac
if [[ -n "${2:-}" ]]; then MIN="$2"; else
    # uptime in minutes, +10 slack, so boot-time lines are always inside the window
    MIN=$(GX_TIMEOUT=30 ./gx 'echo $(( ($(date +%s) - $(sysctl -n kern.boottime | sed -E "s/.*sec = ([0-9]+).*/\1/")) / 60 + 10 ))' 2>/dev/null | tr -dc 0-9)
    [[ -n "$MIN" ]] || MIN=180
fi
echo "# window: last ${MIN}m  predicate: ${PRED}"
GX_TIMEOUT=280 ./gx "log show --last ${MIN}m --predicate '${PRED}' > /tmp/gl.log 2>&1; grep -c . /tmp/gl.log" >/dev/null 2>&1
GX_TIMEOUT=120 ./gx "grep -oE 'rgpu: @ .*' /tmp/gl.log 2>/dev/null | cut -c1-160 || true"
