#!/bin/bash
# Rendered with an exact, owned external payload path by console-support-install.
set -euo pipefail
ioreg -r -c RaphaelConsole -d 1 | grep -q 'RaphaelConsole' || exit 0
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
start=$SECONDS
caffeinate -dimsu -t 6000 & awake=$!
: >"$support/display.log"
"$payload/virtual-display-server" --serve --control-dir "$support/control" >"$support/display.log" 2>&1 & vd=$!
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
 /usr/bin/python3 -B "$payload/console-vdagent-agent.py" --control-dir "$support/control" --seconds "$remaining" >"$support/vdagent.log" 2>&1 & resize=$!
fi
remaining=$((6000-SECONDS+start))
((remaining>0)) || exit 3
"$app/Contents/MacOS/console-presenter" auto 60 "$remaining" >"$support/presenter.log" 2>&1 & presenter=$!
wait "$presenter"
