#!/usr/bin/env bash
# Container-side entrypoint for the macOS VM. The default source is the reviewed
# live preimage 13912a2b...; GENERIC_GRAPHICS=off adds a fail-closed transformation.
set -euo pipefail

cd "${VM_ENTRY_ROOT:-/home/arch/OSX-KVM}"

if [[ -r /env ]]; then
    set +u; source /env; set -u
    export DEVICE_MODEL SERIAL BOARD_SERIAL UUID MAC_ADDRESS
fi

sudo chown "$(id -u):$(id -g)" /dev/kvm 2>/dev/null || true
sudo chown -R "$(id -u):$(id -g)" /dev/snd 2>/dev/null || true
mkdir -p /tmp/xdg 2>/dev/null || true
chmod 700 /tmp/xdg 2>/dev/null || true

LAUNCH=/tmp/Launch.sh
[[ -z "${VM_ENTRY_ROOT:-}" ]] || LAUNCH="${VM_ENTRY_ROOT}/Launch.generated.sh"
cp Launch.sh "${LAUNCH}"

if [[ -w /home/arch/OSX-KVM/OVMF_VARS.fd ]]; then
    sed -i 's|OVMF_VARS-1024x768.fd|OVMF_VARS.fd|' "${LAUNCH}"
fi
if [[ "${NOPICKER:-false}" == true ]]; then
    sed -i '/InstallMedia/d' "${LAUNCH}"
fi

case "${DISK_BUS:-ahci}" in
    ahci) : ;;
    nvme) sed -i 's|-device ide-hd,bus=sata.4,drive=MacHDD|-device nvme,drive=MacHDD,serial=OSX0000000001|' "${LAUNCH}" ;;
    virtio) sed -i 's|-device ide-hd,bus=sata.4,drive=MacHDD|-device virtio-blk-pci,drive=MacHDD|' "${LAUNCH}" ;;
    *) echo "unknown DISK_BUS=${DISK_BUS}" >&2; exit 1 ;;
esac

if [[ "${AUDIO_DRIVER:-}" == none ]]; then
    sed -i '/-audiodev/d; /intel-hda/d; /hda-duplex/d' "${LAUNCH}"
fi

if [[ "${AUDIO_DRIVER:-}" == usb ]]; then
    # Swap the image's HDA codec (no macOS driver) for a USB audio class device
    # on the pulse backend; macOS's own AppleUSBAudio drives it, no guest kext.
    grep -Eq -- '-device qemu-xhci,id=xhci([[:space:],\\]|$)' "${LAUNCH}" || {
        echo 'usb audio needs the image xhci controller' >&2; exit 1; }
    sed -i -E 's/-audiodev [^[:space:],]+,id=hda([[:space:],\\]|$)/-audiodev pa,id=hda\1/;
               s/-device ich9-intel-hda -device hda-duplex,audiodev=hda([[:space:],\\]|$)/-device usb-audio,audiodev=hda,bus=xhci.0\1/' "${LAUNCH}"
    launch_body="$(grep -v '^[[:space:]]*#' "${LAUNCH}")"
    [[ $(grep -c -- '-audiodev pa,id=hda' <<<"${launch_body}") -eq 1 &&
       $(grep -c -- '-device usb-audio,audiodev=hda,bus=xhci.0' <<<"${launch_body}") -eq 1 ]] &&
        ! grep -Eq -- 'intel-hda|hda-duplex|hda-micro|hda-output' <<<"${launch_body}" || {
        echo 'failed to produce exactly one usb-audio device on the pa backend' >&2; exit 1; }
fi

case "${GENERIC_GRAPHICS:-on}" in
    on) ;;
    off)
        [[ "${EXTRA:-}" != *-vga* ]] || {
            echo 'VGA option forbidden in EXTRA' >&2; exit 1; }
        [[ $(grep -Eo -- '(^|[[:space:]])-display[[:space:]]+[^[:space:]]+' <<<"${EXTRA:-}" | wc -l) -eq 1 &&
           " ${EXTRA:-} " == *" -display none "* ]] || {
            echo 'EXTRA must contain exactly one -display none' >&2; exit 1; }
        [[ ! "${EXTRA:-}" =~ (^|[[:space:],=])(VGA|vmware-svga|qxl(-vga)?|virtio-(vga|gpu)(-gl)?(-pci)?|bochs-display|ramfb|secondary-vga|ati-vga|cirrus-vga)([[:space:],=]|$) ]] || {
            echo 'generic graphics device forbidden in EXTRA' >&2; exit 1; }
        launch_body="$(grep -v '^[[:space:]]*#' "${LAUNCH}")"
        vga_token="$(grep -Eo -- '-vga[[:space:]]+[^[:space:]\\]+' <<<"${launch_body}" || true)"
        [[ "${vga_token}" == '-vga vmware' ]] || {
            echo 'expected exactly one default -vga vmware token' >&2; exit 1; }
        [[ $(grep -Eo -- '-display[[:space:]]+[^[:space:]\\]+' <<<"${launch_body}" | wc -l) -eq 0 ]] || {
            echo 'image launcher must not contain a display token' >&2; exit 1; }
        if grep -Eq -- '-device[[:space:]]+(VGA|vmware-svga|qxl(-vga)?|virtio-(vga|gpu)(-gl)?(-pci)?|bochs-display|ramfb|secondary-vga|ati-vga|cirrus-vga)([,[:space:]\\]|$)' <<<"${launch_body}"; then
            echo 'generic graphics device present in image launcher' >&2; exit 1
        fi
        sed -i 's|-vga vmware|-vga none|' "${LAUNCH}"
        [[ $(grep -Eo -- '-vga[[:space:]]+[^[:space:]\\]+' "${LAUNCH}" || true) == '-vga none' ]] || {
            echo 'failed to produce exact -vga none' >&2; exit 1; }
        ;;
    *) echo "unknown GENERIC_GRAPHICS=${GENERIC_GRAPHICS}" >&2; exit 1 ;;
esac

# Explicit presentation-only console: keep the historical no-adapter contract
# unchanged unless the manifest selects this exact device and local endpoint.
case "${CONSOLE_VDAGENT:-off}" in
    off) ;;
    on) [[ "${VM_MANAGER:-direct}" == libvirt && "${VM_CONSOLE:-off}" == bochs-spice && "${GENERIC_GRAPHICS:-on}" == off ]] || { echo "vdagent requires native libvirt SPICE" >&2; exit 1; } ;;
    *) echo "unknown CONSOLE_VDAGENT" >&2; exit 1 ;;
esac
case "${CONSOLE_SNAPSHOT:-off}" in
    off) ;;
    on|restart|restart-timing) [[ "${VM_MANAGER:-direct}" == libvirt && "${VM_CONSOLE:-off}" == bochs-spice && "${CONSOLE_REFRESH:-default}" == 60 && "${CONSOLE_FULL_REFRESH:-off}" == on && "${GENERIC_GRAPHICS:-on}" == off ]] || { echo "snapshot requires native libvirt SPICE60 full refresh" >&2; exit 1; } ;;
    *) echo "unknown CONSOLE_SNAPSHOT" >&2; exit 1 ;;
esac
case "${CONSOLE_FULL_REFRESH:-off}" in
    off) ;;
    on) [[ "${VM_MANAGER:-direct}" == libvirt && "${VM_CONSOLE:-off}" == bochs-spice && "${CONSOLE_REFRESH:-default}" == 60 ]] || { echo "full refresh requires libvirt SPICE60" >&2; exit 1; } ;;
    *) echo "unknown CONSOLE_FULL_REFRESH" >&2; exit 1 ;;
esac
case "${CONSOLE_REFRESH:-default}" in
    default) ;;
    60) [[ "${VM_MANAGER:-direct}" == libvirt && "${VM_CONSOLE:-off}" == bochs-spice ]] || { echo "explicit refresh requires libvirt SPICE" >&2; exit 1; } ;;
    *) echo "unknown CONSOLE_REFRESH" >&2; exit 1 ;;
esac
case "${VM_CONSOLE:-off}" in
    off|"") ;;
    bochs|bochs-spice)
        [[ "${GENERIC_GRAPHICS:-on}" == off && "${EXTRA:-}" != *-vnc* && "${EXTRA:-}" != *-spice* ]] || {
            echo 'Bochs console requires no generic graphics or injected viewer' >&2; exit 1; }
        export EXTRA="${EXTRA:-} -device bochs-display,id=rgpu_present,bus=pcie.0,addr=0x7,vgamem=64M"
        if [[ "${CONSOLE_FULL_REFRESH:-off}" == on ]]; then export EXTRA="${EXTRA},x-debug-full-refresh=on"; fi
        if [[ "${CONSOLE_SNAPSHOT:-off}" == on || "${CONSOLE_SNAPSHOT:-off}" == restart || "${CONSOLE_SNAPSHOT:-off}" == restart-timing ]]; then export EXTRA="${EXTRA},x-debug-snapshot=on"; fi
        if [[ "${CONSOLE_SNAPSHOT:-off}" == restart || "${CONSOLE_SNAPSHOT:-off}" == restart-timing ]]; then export EXTRA="${EXTRA},x-debug-snapshot-restart=on"; fi
        if [[ "${CONSOLE_SNAPSHOT:-off}" == restart-timing ]]; then export EXTRA="${EXTRA},x-debug-snapshot-timing=on"; fi
        if [[ "${VM_CONSOLE}" == bochs-spice ]]; then
            export EXTRA="${EXTRA} -spice unix=on,addr=/run/vm/console-spice.sock,disable-ticketing=on,image-compression=off,gl=off"
            if [[ "${CONSOLE_REFRESH:-default}" == 60 ]]; then export EXTRA="${EXTRA},max-refresh-rate=60"; fi
            # SPICE routes mouse to any attached agent regardless of capabilities.
            # Our resize-only agent leaves input on the existing USB tablet.
            if [[ "${CONSOLE_VDAGENT:-off}" == on ]]; then export EXTRA="${EXTRA},agent-mouse=off"; fi
        else
            export EXTRA="${EXTRA} -vnc unix:/run/vm/console-vnc.sock"
        fi
        ;;
    *) echo 'unknown VM_CONSOLE' >&2; exit 1 ;;
esac

if [[ -n "${LAN_TAP_NODE:-}" ]]; then
    # Bridged LAN NIC: open the macvtap node here and hand it to QEMU by
    # descriptor; the guest gets its own LAN address next to the NAT NIC.
    [[ -c "${LAN_TAP_NODE}" ]] || { echo "LAN tap node ${LAN_TAP_NODE} missing" >&2; exit 1; }
    [[ "${LAN_MAC:-}" =~ ^([0-9a-f]{2}:){5}[0-9a-f]{2}$ ]] || { echo "LAN_MAC must be a lowercase MAC" >&2; exit 1; }
    exec 3<>"${LAN_TAP_NODE}"
    export EXTRA="${EXTRA:-} -netdev tap,id=lan0,fd=3 -device vmxnet3,netdev=lan0,id=lan0,mac=${LAN_MAC}"
fi

# Keep the new explicit PCI slot after all existing devices (including LAN).
if [[ "${CONSOLE_VDAGENT:-off}" == on ]]; then
    export EXTRA="${EXTRA:-} -device virtio-serial-pci,id=rgpu_agent_serial,bus=pcie.0,addr=0x10,max_ports=2 -chardev spicevmc,id=rgpu_vdagent,name=vdagent -device virtserialport,id=rgpu_agent_port,bus=rgpu_agent_serial.0,nr=1,chardev=rgpu_vdagent,name=com.redhat.spice.0"
fi

case "${VM_MANAGER:-direct}" in
    direct|"") ;;
    libvirt)
        [[ "${VM_CONSOLE:-}" == bochs-spice && "${GENERIC_GRAPHICS:-}" == off &&
           "${AUDIO_DRIVER:-}" == usb && -n "${LAN_TAP_NODE:-}" ]] || {
            echo 'libvirt requires exact admitted native console profile' >&2; exit 1; }
        [[ $(grep -Ec '^exec qemu-system-x86_64 ' "${LAUNCH}") -eq 1 ]] || {
            echo 'unreviewed native launcher invocation' >&2; exit 1; }
        python3 -B /run/rgpu-tools/libvirt-console-entry.py preflight
        mkdir -m700 /tmp/rgpu-qemu-shim
        cat > /tmp/rgpu-qemu-shim/qemu-system-x86_64 <<'SHIM'
#!/bin/sh
exec python3 -B /run/rgpu-tools/libvirt-console-entry.py launch "$@"
SHIM
        chmod 700 /tmp/rgpu-qemu-shim/qemu-system-x86_64
        export PATH="/tmp/rgpu-qemu-shim:${PATH}"
        ;;
    *) echo 'unknown VM_MANAGER' >&2; exit 1 ;;
esac

# Libvirt uses Docker exec and its private Unix socket. Guest SSH is QEMU's
# separate port10022 forwarding; unused container sshd adds privileged processes.
if [[ "${VM_MANAGER:-direct}" != libvirt ]]; then
    ./enable-ssh.sh >/dev/null 2>&1 || true
fi
echo "QEMU graphics policy: GENERIC_GRAPHICS=${GENERIC_GRAPHICS:-on}"
exec bash "${LAUNCH}"
