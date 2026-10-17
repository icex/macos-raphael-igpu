#!/usr/bin/env bash
# Install the "macOS (Raphael iGPU)" desktop launcher.
#
#   tools/install-desktop.sh --release N --card metal-NNN --pins experiments/pins-....json
#       (as the desktop user) release config, ~/.local/bin/raphael-macos, application-menu
#       and desktop shortcuts. The release worktree is the one this script runs from.
#   sudo tools/install-desktop.sh --system
#       (once) root-owned /usr/local/libexec/rgpu-gpu-bind and a polkit rule letting the
#       invoking user, in an active local session, run exactly that helper without a
#       password. Nothing else gains privilege.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == --system ]]; then
    [[ $EUID -eq 0 ]] || { echo "use: sudo $0 --system" >&2; exit 1; }
    user="${SUDO_USER:?run through sudo so the desktop user is known}"
    [[ "${user}" =~ ^[a-z_][a-z0-9_-]*$ ]] || { echo "unexpected user name" >&2; exit 1; }
    install -d -o root -g root -m 0755 /usr/local/libexec
    install -o root -g root -m 0755 "${HERE}/tools/rgpu-gpu-bind-root.sh" /usr/local/libexec/rgpu-gpu-bind
    install -d -o root -g root -m 0755 /etc/polkit-1/rules.d
    cat > /etc/polkit-1/rules.d/49-raphael-macos.rules <<EOF
// Raphael iGPU desktop launcher: the desktop user may hand the iGPU to vfio-pci.
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.policykit.exec" &&
        action.lookup("program") == "/usr/local/libexec/rgpu-gpu-bind" &&
        subject.user == "${user}" && subject.local && subject.active) {
        return polkit.Result.YES;
    }
});
EOF
    chmod 0644 /etc/polkit-1/rules.d/49-raphael-macos.rules
    echo "installed /usr/local/libexec/rgpu-gpu-bind and the polkit rule for ${user}"
    exit 0
fi

release="" card="" pins=""
while (( $# )); do
    case "$1" in
        --release) release="$2"; shift 2 ;;
        --card) card="$2"; shift 2 ;;
        --pins) pins="$2"; shift 2 ;;
        *) echo "unknown option $1" >&2; exit 2 ;;
    esac
done
[[ "${pins}" = /* ]] || pins="${HERE}/${pins}"
[[ "${release}" =~ ^[0-9]{3}$ && "${card}" =~ ^metal-[0-9]{3}$ && -r "${pins}" ]] || {
    echo "usage: $0 --release N --card metal-NNN --pins experiments/pins-....json" >&2; exit 2; }
[[ $EUID -ne 0 ]] || { echo "run the user part as the desktop user, not root" >&2; exit 1; }

conf="$HOME/.config/raphael-macos"
vm_dir="${VM_DIR:-$HOME/macos-vm}"
if (( 10#${release} >= 515 )); then
    python3 -B "${HERE}/tools/install-ih-dma-guard.py" --vm-dir "${vm_dir}"
fi
mkdir -p "${conf}" "$HOME/.local/bin" "$HOME/.local/libexec" "$HOME/.local/share/applications"
cat > "${conf}/release.conf" <<EOF
RELEASE_WORKTREE=${HERE}
CANDIDATE=${release}
CARD=${card}
PINS=${pins}
EOF
install -m 0755 "${HERE}/tools/raphael-macos.sh" "$HOME/.local/bin/raphael-macos"
install -m 0755 "${HERE}/tools/desktop-inhibitor.py" "$HOME/.local/libexec/raphael-macos-inhibitor.py"
# The guest container mounts ~/macos-vm/vm-entry.sh; keep it in step with the release (QEMU
# audio and window options). Other harness files there may carry local changes: left alone.
vm_dir="${VM_DIR:-$HOME/macos-vm}"
if [[ -f "${vm_dir}/vm-entry.sh" ]] && ! cmp -s "${HERE}/tools/vm-entry.sh" "${vm_dir}/vm-entry.sh"; then
    cp -p "${vm_dir}/vm-entry.sh" "${vm_dir}/vm-entry.sh.before-${release}"
fi
install -m 0755 "${HERE}/tools/vm-entry.sh" "${vm_dir}/vm-entry.sh"

desktop="[Desktop Entry]
Type=Application
Name=macOS (Raphael iGPU)
Comment=Start macOS with the Raphael iGPU in a QEMU window
Exec=$HOME/.local/bin/raphael-macos
Icon=computer
Terminal=false
Categories=System;Emulator;
Actions=usb;stop;status;

[Desktop Action usb]
Name=USB devices…
Exec=$HOME/.local/bin/raphael-macos usb

[Desktop Action stop]
Name=Shut down macOS
Exec=$HOME/.local/bin/raphael-macos stop

[Desktop Action status]
Name=Status
Exec=sh -c 'notify-send \"macOS (Raphael iGPU)\" \"\$($HOME/.local/bin/raphael-macos status)\"'
"
printf '%s' "${desktop}" > "$HOME/.local/share/applications/raphael-macos.desktop"
desk="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [[ -d "${desk}" ]]; then
    printf '%s' "${desktop}" > "${desk}/raphael-macos.desktop"
    chmod +x "${desk}/raphael-macos.desktop"
fi
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

[[ -x /usr/local/libexec/rgpu-gpu-bind ]] ||
    echo "next, once: sudo $0 --system   (lets the shortcut bind the iGPU)"
echo "installed: application menu and desktop shortcut 'macOS (Raphael iGPU)' -> release ${release} (${card})"
