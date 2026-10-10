#!/bin/bash
# Rendered with an exact, owned external payload path by console-support-install.
set -euo pipefail
# An owned native framebuffer supplies its own mode/VBL path. Starting the
# holder or SCK publisher here would create a second authority over Bochs mode.
native=$(ioreg -r -c RaphaelFramebuffer -d 1)
if printf '%s\n' "$native" | grep -Eq '"NativeConsoleReady" = (Yes|true)[[:space:]]*$'; then
 printf '{"event":"native-framebuffer","capture_helpers":"suppressed","reason":"exclusive native mode ownership"}\n'
 exit 0
fi
bridge=$(ioreg -r -c RaphaelConsole -d 1)
printf '%s\n' "$bridge" | grep -q 'RaphaelConsole' || exit 0
# The sealed presenter already supports ABI1 snapshots. Select them only when
# the new driver reports restart-safe private staging; never inherit this policy
# or a conflicting RAM cache alias from the launching shell.
snapshot=0
if printf '%s\n' "$bridge" | grep -Eq '"SnapshotRestartable" = 1[[:space:]]*$' &&
   printf '%s\n' "$bridge" | grep -Eq '"SnapshotProtocol" = 1[[:space:]]*$'; then
 snapshot=1
fi
printf '{"event":"capture-transport","snapshot":%s,"policy":"restartable-capability","cache":"default"}\n' "$snapshot"
app="$HOME/Applications/Raphael Console.app"
support="$HOME/Library/Application Support/RaphaelGPU/console"
payload=@@PAYLOAD@@
vd=''; awake=''; resize=''; presenter=''
cleanup() {
 for child in "$resize" "$presenter" "$vd" "$awake"; do
  [[ -n "$child" ]] || continue
  # Only this shell's unreaped children; never discover/kill helpers by name.
  if jobs -p | grep -qx "$child"; then kill "$child" 2>/dev/null || true; fi
 done
 for ((i=0;i<20;i++)); do
  [[ -n "$(jobs -pr)" ]] || break
  sleep .1
 done
 for child in "$resize" "$presenter" "$vd" "$awake"; do
  [[ -n "$child" ]] || continue
  if jobs -pr | grep -qx "$child"; then kill -KILL "$child" 2>/dev/null || true; fi
  wait "$child" 2>/dev/null || true
 done
}
trap cleanup EXIT
trap 'exit 143' TERM INT
guest_scale=$(/usr/bin/python3 -B "$payload/console-preferences.py" --support-dir "$support" --read-scale)
case "$guest_scale" in 1|2) ;; *) exit 3 ;; esac
printf '{"event":"scale-policy","guest_scale":%s,"scope":"fixed for this holder lifetime"}\n' "$guest_scale"
clipboard=$(/usr/bin/python3 -B "$payload/console-preferences.py" --support-dir "$support" --read-clipboard)
clipboard_args=()
case "$clipboard" in on) clipboard_args=(--clipboard-text) ;; off) ;; *) exit 3 ;; esac
printf '{"event":"clipboard-policy","text":"%s","scope":"explicit persistent preference"}\n' "$clipboard"
refresh_rate=$(/usr/bin/python3 -B "$payload/console-preferences.py" --support-dir "$support" --read-refresh)
case "$refresh_rate" in 60|120) ;; *) exit 3 ;; esac
printf '{"event":"refresh-policy","refresh_rate":%s,"scope":"fixed for this holder lifetime"}\n' "$refresh_rate"
start=$SECONDS
caffeinate -dimsu -t 6000 & awake=$!
: >"$support/display.log"
"$payload/virtual-display-server" --serve --control-dir "$support/control" --guest-scale "$guest_scale" --refresh-rate "$refresh_rate" >"$support/display.log" 2>&1 & vd=$!
for ((i=0;i<200;i++)); do
 if grep -q '"phase":"serving"' "$support/display.log" && [[ -S "$support/control/control.sock" ]]; then break; fi
 kill -0 "$vd" 2>/dev/null || exit 3
 sleep .1
done
grep -q '"phase":"serving"' "$support/display.log" && [[ -S "$support/control/control.sock" ]] || exit 3
"$app/Contents/Helpers/console-display-layout" >"$support/layout.log" 2>&1
remaining=$((6000-SECONDS+start))
((remaining>0)) || exit 3
# Absence of the optional channel is supported. The agent validates identity and
# exclusive ownership; this launcher never takes over another port holder.
if [[ -c /dev/tty.com.redhat.spice.0 && ! -L /dev/tty.com.redhat.spice.0 ]]; then
 /usr/bin/python3 -B "$payload/console-vdagent-agent.py" --control-dir "$support/control" --seconds "$remaining" --guest-scale "$guest_scale" "${clipboard_args[@]}" >"$support/vdagent.log" 2>&1 & resize=$!
fi
remaining=$((6000-SECONDS+start))
((remaining>0)) || exit 3
RGPU_CONSOLE_SNAPSHOT="$snapshot" RGPU_CONSOLE_CACHE=default "$app/Contents/MacOS/console-presenter" auto "$refresh_rate" "$remaining" >"$support/presenter.log" 2>&1 & presenter=$!
wait "$presenter"
