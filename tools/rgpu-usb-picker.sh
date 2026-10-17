#!/usr/bin/env bash
# Desktop USB picker for the macOS guest: one checklist of host USB devices; checked ones are
# redirected to macOS (up to two, tools/rgpu-usb.sh slots), unchecked ones are given back.
# Root hubs and USB hubs are not offered. Messages go to a desktop notification.
set -uo pipefail
USB="$(dirname "$(readlink -f "$0")")/rgpu-usb.sh"
TITLE="macOS (Raphael iGPU)"
notify() { notify-send -a "${TITLE}" -i drive-removable-media "${TITLE}" "$1" 2>/dev/null || echo "$1"; }

declare -A attached=()      # VID:PID -> slot
while read -r slot id; do
    [[ "${id}" =~ ^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$ ]] && attached["${id,,}"]="${slot}"
done < <("${USB}" status | sed -n 's/^slot \([12]\): \(.*\)$/\1 \2/p')

items=()
while read -r _ _ _ _ _ id name; do
    id="${id,,}"
    [[ "${id}" == 1d6b:* || "${name}" =~ [Hh]ub$ ]] && continue
    state=off; [[ -n "${attached[${id}]:-}" ]] && state=on
    items+=("${id}" "${name:-${id}} (${id})" "${state}")
done < <(lsusb)
(( ${#items[@]} )) || { notify "No USB devices to pass to macOS."; exit 0; }

if command -v kdialog >/dev/null; then
    chosen=$(kdialog --title "${TITLE}" --separate-output \
        --checklist "USB devices used by macOS (at most two):" "${items[@]}") || exit 0
else
    args=(); for ((i=0; i<${#items[@]}; i+=3)); do
        args+=("$([[ ${items[i+2]} == on ]] && echo TRUE || echo FALSE)" "${items[i]}" "${items[i+1]}")
    done
    chosen=$(zenity --list --checklist --title "${TITLE}" --text "USB devices used by macOS (at most two):" \
        --column Use --column ID --column Device --separator=$'\n' "${args[@]}") || exit 0
fi
mapfile -t want < <(printf '%s\n' "${chosen}" | sed '/^$/d' | tr 'A-F' 'a-f')
(( ${#want[@]} <= 2 )) || { notify "macOS can use at most two USB devices at a time."; exit 1; }

messages=()
for id in "${!attached[@]}"; do
    printf '%s\n' "${want[@]}" | grep -qx "${id}" && continue
    "${USB}" detach "${attached[${id}]}" >/dev/null && messages+=("Returned ${id} to Linux.")
done
for id in "${want[@]}"; do
    [[ -n "${attached[${id}]:-}" ]] && continue
    if out=$("${USB}" attach "${id}" 2>&1); then messages+=("Connected ${id} to macOS.")
    else messages+=("Could not connect ${id}: ${out##*$'\n'}"); fi
done
(( ${#messages[@]} )) && notify "$(printf '%s\n' "${messages[@]}")"
exit 0
