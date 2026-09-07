#!/usr/bin/env bash
# Rebuild the grafted VBIOS, push config.plist (device properties + Kernel>Patch)
# into the OpenCore ESP, and restart the VM.
#
#   ./redeploy.sh              # plain VM, NO passthrough -- the safe default
#   ./redeploy.sh --gpu        # pass the iGPU through (see the hazard note below)
#
# PASSTHROUGH IS OPT-IN, AND THAT IS DELIBERATE.
#
# The host has hard-hung three times, every time with the iGPU passed through to the guest
# and never otherwise. Passthrough used to be the default here and --no-gpu the opt-out,
# which meant autorun.sh -- which calls this script with no arguments in a loop -- held the
# device open across dozens of launches unattended. That is the shape of the first crash:
# roughly 33 launches over three hours. Nothing else on this machine has ever hung it.
#
# So the default is now the safe one. You have to ask for the risky thing, every time, and
# you should be at the machine when you do.
#
# Read the result on serial (no guest login needed, thanks to debug=0x108):
#   tr -d '\r' < run/serial.log | grep -E 'c00c02|ASSERT|GPUCAP|Accel|panic'
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
export MTOOLS_SKIP_CHECK=1

# sudo has no TTY under this script, so it needs an askpass helper. /tmp is tmpfs here, so
# a helper written by an earlier session is gone after every reboot -- write it if absent
# rather than failing on a stale path. kdialog is the Plasma prompt; fall back to
# systemd-ask-password so this still works outside a KDE session.
#
# Setting this unconditionally also makes "QUIESCE=1 ./redeploy.sh" work on its own; it
# previously needed SUDO_ASKPASS passed in by hand and silently did nothing without it.
export SUDO_ASKPASS="${SUDO_ASKPASS:-${TMPDIR:-/tmp}/rgpu-askpass.sh}"
if [[ ! -x "$SUDO_ASKPASS" ]]; then
    cat > "$SUDO_ASKPASS" <<'ASKPASS'
#!/bin/sh
if command -v kdialog >/dev/null 2>&1; then exec kdialog --password "$1"
else exec systemd-ask-password "$1"; fi
ASKPASS
    chmod 700 "$SUDO_ASKPASS"
fi

ESP_OFF=1048576
DEV=0000:7b:00.0
IMAGE="${IMAGE:-sickcodes/docker-osx:latest}"

WANT_GPU=0
case "${1:-}" in
    --gpu)    WANT_GPU=1; shift ;;
    # Still accepted so iterate.sh / bootonly.sh keep working unchanged; it is now the
    # default, so it does nothing.
    --no-gpu) shift ;;
esac

# Hard cap on how long QEMU may hold the iGPU, in seconds; 0 disables the cap.
#
# Every hang so far happened while the guest had the device open, at 53 s, at ~74 s, and
# somewhere inside a three-hour unattended loop. None of the three is tied to anything
# visible in the guest log -- the third one hung after the guest had reached the same
# quiescent state that 116 of 149 archived runs reach without incident -- so there is no
# milestone to stop at, only elapsed exposure to bound. Five minutes is far longer than any
# experiment needs and far shorter than an unattended loop.
RGPU_MAX_SECONDS="${RGPU_MAX_SECONDS:-300}"

python3 mkrom.py --total 0xB600 -o run/gpu-patched.rom "$@"
python3 ocprop.py config.plist -o run/config-new.plist \
    --drop-vbios --vbios run/gpu-patched.rom --path 'PciRoot(0x0)/Pci(0x6,0x0)'

# qemu-img lives in the docker-osx image, not on this host. Borrow it from the
# running VM if there is one, otherwise from a throwaway container -- do NOT skip
# this step, or the ESP keeps the previous config and the run is not a real test.
qimg() {
    if [[ -n "$(docker ps --format '{{.Names}}' | grep -Fx macos-sequoia || true)" ]]; then
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
    # Refuse, with no override, to pass through an iGPU that amdgpu has never initialised
    # this boot.
    #
    # All three host hangs happened with the iGPU passed through, and all three left the
    # same nothing behind: the journal stops mid-line, no shutdown sequence, no panic, no
    # oops, pstore empty. What separates the two configurations is exposure survived:
    #
    #   amdgpu binds at boot, gpu-bind.sh hands the device over afterwards
    #       ~33 launches over ~3 hours, call it ~100 minutes of guest runtime
    #
    #   vfio-pci claims the device from boot, so it reaches the guest exactly as the system
    #   firmware left it, never POSTed or quiesced by any driver
    #       53 s into the first launch, then ~74 s into the first launch after a reboot
    #
    # About fifty times the runtime for the same number of crashes. That is not a mechanism
    # and is not offered as one -- with every lockup detector disabled on this kernel's
    # command line, the evidence needed to find the mechanism has never been capturable --
    # but the difference is far too large to be luck, and the virgin path buys nothing: the
    # guest reaches the same state either way.
    #
    # This used to be overridable with RGPU_ALLOW_VIRGIN_IGPU=1. That override is gone. It
    # existed for one experiment, the experiment was run twice, and it cost two hangs and
    # told us nothing new. If you want passthrough, run ./disable-early-vfio.sh and reboot
    # so amdgpu owns the device first.
    #
    # grep -c, not grep -q, and the count captured before it is tested. "grep -q" exits the
    # moment it matches, journalctl is still writing megabytes into the pipe, so it takes
    # SIGPIPE and dies 141 -- and under "set -o pipefail" that 141 becomes the pipeline's
    # status even though grep found what it was looking for. The "!" then inverts a success
    # into a failure, so this guard fired exactly when amdgpu HAD initialised the device and
    # passed when it had not: broken in the one direction nobody would notice. grep -c reads
    # its input to the end, so there is no SIGPIPE to misread. This is the same bug that
    # produced the bogus "the discrete GPU is not present" from enable-early-vfio.sh.
    amdgpu_lines="$(journalctl -k -b --no-pager 2>/dev/null | grep -c "amdgpu ${DEV}" || true)"
    if [[ "$drv" == vfio-pci ]] && (( ${amdgpu_lines:-0} == 0 )); then
        cat >&2 <<EOF
REFUSING to pass through ${DEV}: amdgpu has not initialised it this boot.

The device is on vfio-pci but was never POSTed and quiesced by amdgpu. That is the
configuration the host hard-hung in twice, at 53 s and ~74 s into the first launch, versus
~100 minutes of guest runtime in the amdgpu-first configuration.

To get out of it:

    sudo ./disable-early-vfio.sh && sudo reboot
    SUDO_ASKPASS=\$SUDO_ASKPASS sudo -A ./gpu-bind.sh
    ./redeploy.sh --gpu

There is deliberately no override for this.
EOF
        exit 1
    fi
    if [[ "$drv" == vfio-pci ]]; then
        # Make sure the IOMMU group node is ours to open.
        #
        # QEMU opens /dev/vfio/<group>, and a fresh node is root:root 0600. gpu-bind.sh
        # chowns it as its last step -- but with the iGPU claimed by vfio-pci from boot
        # gpu-bind.sh is never run, so nothing does, and the launch dies with
        # "/dev/vfio/31 is not accessible to you" into run/vm-launch.log while the
        # terminal still says "passing through". Do it here instead, where it holds for
        # both paths, and only when it is actually needed so an already-owned node costs
        # no password prompt.
        #
        # -A (askpass) rather than a bare sudo: there is no TTY under this script. Never a
        # "sudo -n" probe first -- a failed non-interactive sudo counts against faillock.
        grp="$(basename "$(readlink -f "/sys/bus/pci/devices/${DEV}/iommu_group")")"
        vfio_node="/dev/vfio/${grp}"
        if [[ ! -r "$vfio_node" || ! -w "$vfio_node" ]]; then
            echo "${vfio_node} is not accessible; taking ownership"
            sudo -A chown "$(id -u):$(id -g)" "$vfio_node" || {
                echo "could not chown ${vfio_node} -- QEMU will not be able to open it" >&2
                exit 1; }
        fi
        echo "iommu group ${grp}: $(ls -l "$vfio_node" | awk '{print $3, $1}')"
        GPU_ARGS=(--gpu "$DEV" --gpu-id 0x73ff --gpu-rom run/gpu-patched.rom)
        echo "passing through ${DEV} (spoofed 0x73ff)"
    else
        echo "NOTE: ${DEV} is bound to '${drv}', not vfio-pci -- starting without passthrough."
        echo "      run 'SUDO_ASKPASS=\"\$SUDO_ASKPASS\" sudo -A ./gpu-bind.sh' first."
    fi
fi

mv -f run/serial.log "run/serial-$(date +%H%M%S).log" 2>/dev/null || true
: > run/serial.log
nohup systemd-inhibit --what=sleep:idle --who="macOS VM" --why="GPU RE run" \
    ./macos-vm.sh run "${GPU_ARGS[@]}" > run/vm-launch.log 2>&1 &
# Bounded, not "until": if QEMU dies on startup -- a bad ROM, an inaccessible /dev/vfio
# node -- an unbounded wait here hangs the script forever on a socket that will never
# appear, and the real error sits unread in run/vm-launch.log.
for _ in $(seq 1 60); do [ -S run/serial.sock ] && break; sleep 1; done
if [ ! -S run/serial.sock ]; then
    echo "QEMU did not come up; run/vm-launch.log says:" >&2
    tail -5 run/vm-launch.log >&2
    exit 1
fi
(nohup ./sercat.py >/dev/null 2>&1 &)

# Bound how long the guest may hold the iGPU.
#
# There is no milestone to stop at: the third hang came after the guest had reached the
# same quiescent end state that 116 of the 149 archived runs reach without incident, so the
# guest log cannot tell us when the danger starts. Elapsed exposure is the only thing left
# to limit, so limit it -- and do it here rather than trusting whoever is driving to
# remember, because the crash that cost three hours was an unattended loop.
if (( WANT_GPU )) && (( RGPU_MAX_SECONDS > 0 )); then
    ( sleep "$RGPU_MAX_SECONDS"
      [[ -n "$(docker ps --format '{{.Names}}' | grep -Fx macos-sequoia || true)" ]] || exit 0
      echo "RGPU_MAX_SECONDS=${RGPU_MAX_SECONDS} reached; stopping the VM to release the iGPU" \
          >> run/vm-launch.log
      docker rm -f macos-sequoia >/dev/null 2>&1
    ) >/dev/null 2>&1 &
    disown
    echo "iGPU exposure capped at ${RGPU_MAX_SECONDS}s (RGPU_MAX_SECONDS=0 to disable)"
fi
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
