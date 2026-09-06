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
if [[ -n "${SUDO_ASKPASS:-}" ]]; then
    sudo -A ./gpu-quiesce.sh || echo "NOTE: PSP quiesce failed; x7 should still recover"
else
    echo "NOTE: SUDO_ASKPASS unset, skipping PSP quiesce (x7 should still recover)"
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
