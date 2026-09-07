#!/usr/bin/env bash
# Rebuild the grafted VBIOS, push config.plist (device properties + Kernel>Patch)
# into the OpenCore ESP, and restart the VM.
#
#   ./redeploy.sh              # with the iGPU passed through, if it is bound to vfio-pci
#   ./redeploy.sh --no-gpu     # plain VM, no passthrough
#
# Read the result on serial (no guest login needed, thanks to debug=0x108):
#   tr -d '\r' < run/serial.log | grep -E 'c00c02|ASSERT|GPUCAP|Accel|panic'
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
export MTOOLS_SKIP_CHECK=1
ESP_OFF=1048576
DEV=0000:7b:00.0
IMAGE="${IMAGE:-sickcodes/docker-osx:latest}"

WANT_GPU=1
[[ "${1:-}" == --no-gpu ]] && { WANT_GPU=0; shift; }

python3 mkrom.py --total 0xB600 -o run/gpu-patched.rom "$@"
python3 ocprop.py config.plist -o run/config-new.plist \
    --drop-vbios --vbios run/gpu-patched.rom --path 'PciRoot(0x0)/Pci(0x6,0x0)'

# qemu-img lives in the docker-osx image, not on this host. Borrow it from the
# running VM if there is one, otherwise from a throwaway container -- do NOT skip
# this step, or the ESP keeps the previous config and the run is not a real test.
qimg() {
    if docker ps --format '{{.Names}}' | grep -qx macos-sequoia; then
        docker exec macos-sequoia qemu-img "$@"
    else
        docker run --rm -v "$PWD/run:/run/vm" --entrypoint qemu-img "$IMAGE" "$@"
    fi
}

docker rm -f macos-sequoia >/dev/null 2>&1 || true
sleep 1

# The guest never tears down its PSP GPCOM ring (QEMU is just killed), and Apple's
# psp_ring_create only calls ring_stop on its TEE path -- so without this every boot
# after the first fails at "psp_ring_create: KM ring creation failed". Best effort: the
# in-guest x7 milestone destroys a stale ring too, so a skipped quiesce is not fatal.
# Opt-in only: milestone x7 destroys a stale GPCOM ring from inside the guest with no root
# at all, so the host-side quiesce is redundant during normal iteration and only earns a
# password prompt. Use it when the guest cannot get far enough to run x7:
#     QUIESCE=1 SUDO_ASKPASS=/path/to/askpass ./redeploy.sh
# gpu-restore.sh still quiesces unconditionally, because handing a dirty PSP back to amdgpu
# is a different matter.
if [[ "${QUIESCE:-0}" == 1 && -n "${SUDO_ASKPASS:-}" ]]; then
    sudo -A ./gpu-quiesce.sh || echo "NOTE: PSP quiesce failed; x7 should still recover"
fi
[[ -f run/oc-raw.img ]] || qimg convert -O raw /run/vm/OpenCore.qcow2 /run/vm/oc-raw.img
mcopy -o -i "run/oc-raw.img@@${ESP_OFF}" run/config-new.plist ::/EFI/OC/config.plist
# No -c: compressing a 384 MB image on every deploy costs seconds for no benefit here.
qimg convert -O qcow2 /run/vm/oc-raw.img /run/vm/OpenCore-rebuilt.qcow2

# Never overwrite a qcow2 that a running QEMU has open -- the container is already
# stopped above, which is the only safe moment to do this.
cp -f run/config-new.plist config.plist
cp -f run/OpenCore-rebuilt.qcow2 OpenCore.qcow2

GPU_ARGS=()
if (( WANT_GPU )); then
    drv="$(basename "$(readlink -f "/sys/bus/pci/devices/${DEV}/driver")" 2>/dev/null || echo none)"
    # Refuse to pass through an iGPU that amdgpu has never initialised this boot.
    #
    # The host has hard-hung twice, both times with the VM running and the iGPU passed
    # through, and both times leaving nothing behind: the journal stops mid-line with no
    # shutdown sequence, no panic, no oops, and /sys/fs/pstore empty. The two differ only in
    # how long they took. In the configuration where amdgpu binds the iGPU at boot and
    # gpu-bind.sh hands it over afterwards, it survived roughly 33 VM launches over three
    # hours before dying. With the iGPU claimed by vfio-pci straight from boot -- so the
    # device reached the guest exactly as the system firmware left it, never initialised or
    # quiesced by a driver -- it died 53 seconds into the FIRST launch.
    #
    # That is not proof of a mechanism, and it is not claimed as one: the evidence needed to
    # find the mechanism was never captured. It is enough to say the virgin path is far more
    # dangerous, and there is no reason to take it, so do not start on it by accident. The
    # check is simply whether amdgpu ever logged anything about this device this boot.
    if [[ "$drv" == vfio-pci ]] && ! journalctl -k -b --no-pager 2>/dev/null |
            grep -q "amdgpu ${DEV}"; then
        cat >&2 <<EOF
REFUSING to pass through ${DEV}: amdgpu has not initialised it this boot.

The device is on vfio-pci but was never POSTed and quiesced by amdgpu, which is the
configuration in which the host hard-hung 53 seconds into the first VM launch. Undo the
early binding (./disable-early-vfio.sh, then reboot) so amdgpu owns the iGPU at boot and
gpu-bind.sh hands it over afterwards.

Set RGPU_ALLOW_VIRGIN_IGPU=1 to override, and be at the machine when you do.
EOF
        [[ "${RGPU_ALLOW_VIRGIN_IGPU:-0}" == 1 ]] || exit 1
        echo "RGPU_ALLOW_VIRGIN_IGPU=1 -- proceeding against a virgin iGPU anyway" >&2
    fi
    if [[ "$drv" == vfio-pci ]]; then
        GPU_ARGS=(--gpu "$DEV" --gpu-id 0x73ff --gpu-rom run/gpu-patched.rom)
        echo "passing through ${DEV} (spoofed 0x73ff)"
    else
        echo "NOTE: ${DEV} is bound to '${drv}', not vfio-pci -- starting without passthrough."
        echo "      run 'SUDO_ASKPASS=/tmp/askpass.sh sudo -A ./gpu-bind.sh' first."
    fi
fi

mv -f run/serial.log "run/serial-$(date +%H%M%S).log" 2>/dev/null || true
: > run/serial.log
nohup systemd-inhibit --what=sleep:idle --who="macOS VM" --why="GPU RE run" \
    ./macos-vm.sh run "${GPU_ARGS[@]}" > run/vm-launch.log 2>&1 &
until [ -S run/serial.sock ]; do sleep 1; done
(nohup ./sercat.py >/dev/null 2>&1 &)
# The container is recreated on every boot, so the agent command channel and the file
# server die with it. Without this, ./gx reports "no response from guest agent" and the
# guest looks unreachable when it is merely unserved.
for i in $(seq 1 30); do
    docker cp agent-server.py macos-sequoia:/tmp/ >/dev/null 2>&1 || { sleep 2; continue; }
    docker exec -d macos-sequoia python3 /tmp/agent-server.py 2>/dev/null || true
    docker exec -d macos-sequoia sh -c 'cd /run/vm && exec python3 -m http.server 8889' 2>/dev/null || true
    break
done
echo "VM relaunched; serial draining to run/serial.log"
./milestones.py list | tail -5
