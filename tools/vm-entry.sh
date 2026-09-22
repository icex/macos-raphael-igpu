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

./enable-ssh.sh >/dev/null 2>&1 || true
echo "QEMU graphics policy: GENERIC_GRAPHICS=${GENERIC_GRAPHICS:-on}"
exec bash "${LAUNCH}"
