#!/usr/bin/env bash
#
# macOS Sequoia VM launcher -- QEMU/KVM, via the Docker-OSX image.
#
#   ./macos-vm.sh install     first run: boot the recovery installer
#   ./macos-vm.sh run         normal run: boot the installed system
#   ./macos-vm.sh ssh         ssh into the guest (user/alpine by default)
#   ./macos-vm.sh screenshot  capture the guest framebuffer to screenshot.png
#   ./macos-vm.sh info        show config that would be used, then exit
#
# Everything the VM owns lives next to this script:
#   mac_hdd_ng.img   the macOS system disk (256G sparse qcow2)
#   BaseSystem.img   Apple's recovery installer
#   OpenCore.qcow2   bootloader with this VM's fixed serials
#   env              the machine identity that OpenCore.qcow2 was built with
#
set -euo pipefail

VM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-sickcodes/docker-osx:latest}"
NAME="${NAME:-macos-sequoia}"

# --- tunables (env or flags) -------------------------------------------------
VCPUS="${VCPUS:-8}"            # vCPUs; host has 8 cores / 16 threads
RAM_GB="${RAM_GB:-auto}"       # auto = leave 8G for the host, clamp to 8..20
DISK_BUS="${DISK_BUS:-ahci}"   # ahci (safe) | nvme (faster) | virtio
AUDIO="${AUDIO:-pa}"           # pa (PipeWire's pulse server) | alsa | none
NVRAM="${NVRAM:-stock}"        # stock (image default) | persist (EFI vars survive reboots)
BOOTDISK_MODE="${BOOTDISK_MODE:-custom}"  # custom (per-VM serials, working) | stock (image default)
NIC="${NIC:-vmxnet3}"          # Sequoia ships a vmxnet3 driver; it has no e1000 driver at all
GL="${GL:-on}"                 # on = upload the guest framebuffer to the host GPU
GPU="${GPU:-}"                 # PCI address to pass through, e.g. 0000:7b:00.0
GPU_ID="${GPU_ID:-}"           # spoof this PCI device id to the guest, e.g. 0x73ff
GPU_ROM="${GPU_ROM:-}"         # video BIOS image for the passed-through GPU
GPU_SUB="${GPU_SUB:-}"         # spoof subsystem ids too, as "vendor:device"
SERIAL="${SERIAL:-on}"         # on = expose a serial port at run/serial.sock
CRITICAL_SERIAL="${CRITICAL_SERIAL:-off}" # on = dedicated CR2 UART at COM2
GDB="${GDB:-off}"              # on = gdbstub on 127.0.0.1:1234 | wait = also start halted
SSH_PORT="${SSH_PORT:-50922}"
SCREEN_PORT="${SCREEN_PORT:-5900}"

usage() { sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

MODE=""
EXTRA_QEMU="${EXTRA:-}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        install|run|ssh|info|screenshot) MODE="$1"; shift ;;
        --cpus)     VCPUS="$2"; shift 2 ;;
        --ram)      RAM_GB="$2"; shift 2 ;;
        --disk-bus) DISK_BUS="$2"; shift 2 ;;
        --audio)    AUDIO="$2"; shift 2 ;;
        --nvram)    NVRAM="$2"; shift 2 ;;
        --bootdisk) BOOTDISK_MODE="$2"; shift 2 ;;
        --nic)      NIC="$2"; shift 2 ;;
        --gl)       GL="$2"; shift 2 ;;
        --gpu)      GPU="$2"; shift 2 ;;
        --gpu-id)   GPU_ID="$2"; shift 2 ;;
        --gpu-rom)  GPU_ROM="$2"; shift 2 ;;
        --gpu-sub)  GPU_SUB="$2"; shift 2 ;;
        --serial)   SERIAL="$2"; shift 2 ;;
        --gdb)      GDB="$2"; shift 2 ;;
        --extra)    EXTRA_QEMU="$2"; shift 2 ;;
        -h|--help)  usage 0 ;;
        *) echo "unknown argument: $1" >&2; usage 1 ;;
    esac
done
[[ -n "${MODE}" ]] || usage 1

# --- ssh shortcut ------------------------------------------------------------
if [[ "${MODE}" == ssh ]]; then
    exec ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
             -p "${SSH_PORT}" user@localhost
fi

# --- screenshot via the QEMU monitor ------------------------------------------
if [[ "${MODE}" == screenshot ]]; then
    out="${VM_DIR}/screenshot.png"
    # Delete the old dump FIRST. If screendump fails (monitor not up yet, or QEMU
    # dead) magick would otherwise silently re-convert the previous frame and the
    # caller would act on a stale image -- which has already caused keystrokes to
    # be sent into the OpenCore picker, cancelling its auto-boot timeout.
    rm -f "${VM_DIR}/run/screen.ppm"
    python3 - "${VM_DIR}/run/monitor.sock" <<'EOF' || true
import socket, sys, time
try:
    s = socket.socket(socket.AF_UNIX); s.settimeout(5); s.connect(sys.argv[1])
    s.sendall(b"screendump /run/vm/screen.ppm\n"); time.sleep(1.5)
    try:
        while s.recv(4096):
            pass
    except socket.timeout:
        pass
except Exception as e:
    print(f"monitor unreachable: {e}", file=sys.stderr)
EOF
    if [[ ! -s "${VM_DIR}/run/screen.ppm" ]]; then
        echo "screenshot failed: no fresh frame from the QEMU monitor" >&2
        exit 1
    fi
    magick "${VM_DIR}/run/screen.ppm" "${out}"
    echo "${out}"
    exit 0
fi

# --- preflight ---------------------------------------------------------------
die() { echo "error: $*" >&2; exit 1; }

[[ -w /dev/kvm ]] || die "/dev/kvm is not writable -- is the kvm module loaded?"
docker info >/dev/null 2>&1 || die "cannot talk to the docker daemon (are you in the 'docker' group in THIS session? try: newgrp docker)"

for f in mac_hdd_ng.img OpenCore.qcow2 env; do
    [[ -e "${VM_DIR}/${f}" ]] || die "missing ${VM_DIR}/${f} -- run the setup steps in README.md"
done
[[ "${MODE}" == run ]] || [[ -e "${VM_DIR}/BaseSystem.img" ]] || die "missing BaseSystem.img"

# X11: the QEMU window is an X client, so it needs the Xwayland socket plus a cookie.
[[ -S /tmp/.X11-unix/X0 ]] || die "no X11 socket at /tmp/.X11-unix/X0"
XAUTH="${XAUTHORITY:-}"
if [[ -z "${XAUTH}" || ! -r "${XAUTH}" ]]; then
    XAUTH="$(ls -1t /run/user/"$(id -u)"/xauth_* 2>/dev/null | head -1 || true)"
fi
[[ -n "${XAUTH}" && -r "${XAUTH}" ]] || die "no readable X authority file; set XAUTHORITY"

# RAM: macOS + Xcode wants a lot, the host still needs room to breathe.
if [[ "${RAM_GB}" == auto ]]; then
    avail_gb=$(( $(awk '/MemAvailable/{print $2}' /proc/meminfo) / 1024 / 1024 ))
    RAM_GB=$(( avail_gb - 8 ))
    (( RAM_GB > 20 )) && RAM_GB=20
    (( RAM_GB < 8 ))  && RAM_GB=8
fi

# --- audio backend -----------------------------------------------------------
AUDIO_ARGS=()
case "${AUDIO}" in
    pa)
        # libpulse insists XDG_RUNTIME_DIR be a 0700 dir owned by the calling uid,
        # so hand it one from this directory rather than a root-owned docker mount.
        pulse_dir="/run/user/$(id -u)/pulse"
        [[ -S "${pulse_dir}/native" ]] || die "no PulseAudio/PipeWire socket at ${pulse_dir}/native; try --audio alsa"
        mkdir -p "${VM_DIR}/xdg"; chmod 700 "${VM_DIR}/xdg"
        AUDIO_ARGS=(-v "${VM_DIR}/xdg:/xdgrt" -v "${pulse_dir}:/xdgrt/pulse"
                    -e XDG_RUNTIME_DIR=/xdgrt -e AUDIO_DRIVER=pa)
        ;;
    alsa)  AUDIO_ARGS=(--device /dev/snd -e AUDIO_DRIVER=alsa) ;;
    none)  AUDIO_ARGS=(-e AUDIO_DRIVER=none) ;;
    *)     die "unknown --audio ${AUDIO}" ;;
esac

# A second QEMU monitor on a unix socket, so the VM can be inspected and
# screenshotted from outside without stealing the stdio monitor.
mkdir -p "${VM_DIR}/run"
EXTRA_QEMU="-chardev socket,id=mon1,path=/run/vm/monitor.sock,server=on,wait=off -mon chardev=mon1,mode=readline ${EXTRA_QEMU}"

# Without gl=on, every guest frame is copied by the CPU and pushed over X11.
[[ "${GL}" == on ]] && EXTRA_QEMU="-display gtk,gl=on ${EXTRA_QEMU}"

# A 16550 serial port on a unix socket. macOS does not run a login shell on it,
# but the kernel can be told to log there, which is the only way to capture an
# early-boot panic that never reaches the framebuffer.
case "${SERIAL}" in on|off) ;; *) die "unknown serial setting ${SERIAL}" ;; esac
case "${CRITICAL_SERIAL}" in on|off) ;; *) die "unknown critical serial setting ${CRITICAL_SERIAL}" ;; esac
if [[ "${SERIAL}" == on ]]; then
    rm -f "${VM_DIR}/run/serial.sock"
    EXTRA_QEMU="-chardev socket,id=rgpu_console,path=/run/vm/serial.sock,server=on,wait=off -device isa-serial,chardev=rgpu_console,index=0 ${EXTRA_QEMU}"
fi
if [[ "${CRITICAL_SERIAL}" == on ]]; then
    [[ "${SERIAL}" == on ]] || die "critical serial requires the console serial channel"
    rm -f "${VM_DIR}/run/critical.sock"
    EXTRA_QEMU="-chardev socket,id=rgpu_critical,path=/run/vm/critical.sock,server=on,wait=off -device isa-serial,chardev=rgpu_critical,index=1 ${EXTRA_QEMU}"
fi

# QEMU's gdbstub. Debugs the guest kernel from outside, with no guest cooperation
# and nothing to install in the guest. Pair it with slide=0 in boot-args so kernel
# and kext addresses match what kcsym.py reads out of the kernel collection.
GDB_ARGS=()
if [[ "${GDB}" != off ]]; then
    EXTRA_QEMU="-gdb tcp:0.0.0.0:1234 ${EXTRA_QEMU}"
    [[ "${GDB}" == wait ]] && EXTRA_QEMU="-S ${EXTRA_QEMU}"
    GDB_ARGS=(-p 127.0.0.1:1234:1234)
fi

# VFIO passthrough of a host GPU.
GPU_ARGS=()
if [[ -n "${GPU}" ]]; then
    [[ -e "/sys/bus/pci/devices/${GPU}" ]] || die "no such PCI device: ${GPU}"
    drv="$(basename "$(readlink -f "/sys/bus/pci/devices/${GPU}/driver")" 2>/dev/null || echo none)"
    [[ "${drv}" == vfio-pci ]] || die "${GPU} is bound to '${drv}', not vfio-pci -- run ./gpu-bind.sh first"
    reset_path="/sys/bus/pci/devices/${GPU}/reset_method"
    [[ -r "${reset_path}" ]] || die "${GPU} reset_method is unreadable -- refusing VFIO open"
    reset_methods="$(tr -d '[:space:]' < "${reset_path}")"
    [[ -z "${reset_methods}" ]] || die "PCI reset methods are still enabled for ${GPU}: ${reset_methods} -- run ./gpu-bind.sh before QEMU"
    grp="$(basename "$(readlink -f "/sys/bus/pci/devices/${GPU}/iommu_group")")"
    [[ -r "/dev/vfio/${grp}" && -w "/dev/vfio/${grp}" ]] || die "/dev/vfio/${grp} is not accessible to you"
    GPU_ARGS=(--device /dev/vfio/vfio --device "/dev/vfio/${grp}" --ulimit memlock=-1)
    # The GPU sits directly on pcie.0, which makes it a Root Complex Integrated
    # Endpoint. That costs us the PCIe link registers -- Apple's HWLibs then finds no
    # device-info-table entry with a capability offset (see findings/GPU-RE.md) -- but
    # the alternative does not work: behind a pcie-root-port, OVMF allocates the bridge
    # window correctly (pref64 [0x800000000, 0x8101fffff], every BAR mapped) and then
    # macOS's PCI configurator tears it straight back down the moment the kernel takes
    # over, leaving every BAR unmapped so the AMD driver never even matches. Measured
    # with and without resource-reservation hints, with hotplug=off, and with
    # npci=0x2000. Do not reintroduce the root port without solving that first.
    vf="-device vfio-pci,host=${GPU},bus=pcie.0"
    [[ -n "${GPU_ID}" ]] && vf+=",x-pci-vendor-id=0x1002,x-pci-device-id=${GPU_ID}"
    if [[ -n "${GPU_SUB}" ]]; then
        vf+=",x-pci-sub-vendor-id=0x${GPU_SUB%%:*},x-pci-sub-device-id=0x${GPU_SUB##*:}"
    fi
    if [[ -n "${GPU_ROM}" ]]; then
        [[ -f "${GPU_ROM}" ]] || die "no such rom file: ${GPU_ROM}"
        cp -f "${GPU_ROM}" "${VM_DIR}/run/gpu.rom"
        vf+=",romfile=/run/vm/gpu.rom"
    fi
    EXTRA_QEMU="${vf} ${EXTRA_QEMU}"
fi

NOPICKER=true
[[ "${MODE}" == install ]] && NOPICKER=false

DOCKER_ARGS=(
    --rm --name "${NAME}"
    --device /dev/kvm
    # X11 clients use MIT-SHM; without the host IPC namespace the X server
    # rejects the shared segments and the QEMU window dies on startup.
    --ipc=host
    # QEMU's SLIRP stack only ever uses the FIRST nameserver in the container's
    # resolv.conf, and this network's router refuses DNS from docker containers.
    # Without this the guest resolves nothing and macOS reports "recovery server
    # could not be contacted".
    --dns 1.1.1.1
    --dns 9.9.9.9
    -p "127.0.0.1:${SSH_PORT}:10022"
    -p "127.0.0.1:${SCREEN_PORT}:5900"
    -v /tmp/.X11-unix:/tmp/.X11-unix
    -v "${XAUTH}:/home/arch/.Xauthority:ro"
    -e DISPLAY="${DISPLAY:-:0}"
    -e XAUTHORITY=/home/arch/.Xauthority
    -v "${VM_DIR}/mac_hdd_ng.img:/home/arch/OSX-KVM/mac_hdd_ng.img"
    -v "${VM_DIR}/run:/run/vm"
    -v "${VM_DIR}/vm-entry.sh:/entry.sh:ro"
    -e IMAGE_PATH=/home/arch/OSX-KVM/mac_hdd_ng.img
    -e BOOTDISK=/home/arch/OSX-KVM/OpenCore/OpenCore.qcow2
    -e GENERATE_UNIQUE=false
    -e GENERATE_SPECIFIC=false
    -e "NOPICKER=${NOPICKER}"
    -e "DISK_BUS=${DISK_BUS}"
    -e "NETWORKING=${NIC}"
    -e "RAM=${RAM_GB}"
    # macOS refuses to boot on an AMD-looking CPU, so QEMU presents an Intel one.
    -e CPU=Haswell-noTSX
    -e CPUID_FLAGS='kvm=on,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on'
    -e "CPU_STRING=${VCPUS},sockets=1,cores=${VCPUS},threads=1"
    -e "EXTRA=${EXTRA_QEMU}"
    "${AUDIO_ARGS[@]}"
    "${GPU_ARGS[@]}"
    "${GDB_ARGS[@]}"
)

# Host GPU node: accelerates the QEMU window itself on the host side.
# It does NOT give the guest graphics acceleration -- macOS has no driver for
# RDNA 4 (RX 9070 XT) or for AMD integrated graphics, so passthrough is pointless here.
[[ -e /dev/dri ]] && DOCKER_ARGS+=(--device /dev/dri)

if [[ "${BOOTDISK_MODE}" == custom ]]; then
    DOCKER_ARGS+=(-v "${VM_DIR}/OpenCore.qcow2:/home/arch/OSX-KVM/OpenCore/OpenCore.qcow2"
                  -v "${VM_DIR}/env:/env:ro")
fi

if [[ "${NVRAM}" == persist ]]; then
    [[ -e "${VM_DIR}/OVMF_VARS.fd" ]] || die "missing ${VM_DIR}/OVMF_VARS.fd"
    DOCKER_ARGS+=(-v "${VM_DIR}/OVMF_VARS.fd:/home/arch/OSX-KVM/OVMF_VARS.fd")
fi

# QEMU's monitor is on stdio; give it a terminal when we have one.
if [[ -t 0 && -t 1 ]]; then DOCKER_ARGS+=(-it); else DOCKER_ARGS+=(-i); fi

[[ "${MODE}" == install ]] && DOCKER_ARGS+=(-v "${VM_DIR}/BaseSystem.img:/home/arch/OSX-KVM/BaseSystem.img")

cat <<EOF
macOS VM
  mode        ${MODE}
  vCPUs       ${VCPUS}
  RAM         ${RAM_GB}G
  disk bus    ${DISK_BUS}
  audio       ${AUDIO}
  nvram       ${NVRAM}
  bootdisk    ${BOOTDISK_MODE}
  nic         ${NIC}
  gl          ${GL}
  serial      ${SERIAL}
  critical    ${CRITICAL_SERIAL}
  gdb         ${GDB}
  gpu         ${GPU:-none}${GPU_ID:+ (spoofed as ${GPU_ID})}
  disk        ${VM_DIR}/mac_hdd_ng.img (256G max, $(du -h "${VM_DIR}/mac_hdd_ng.img" | cut -f1) used on host)
  ssh         ssh -p ${SSH_PORT} user@localhost
EOF

[[ "${MODE}" == info ]] && exit 0

docker rm -f "${NAME}" >/dev/null 2>&1 || true

# Stop the desktop suspending or locking mid-install; releases when the VM exits.
if command -v systemd-inhibit >/dev/null; then
    setsid "${VM_DIR}/keep-awake.sh" "${NAME}" >/dev/null 2>&1 < /dev/null &
fi

exec docker run "${DOCKER_ARGS[@]}" --entrypoint /entry.sh "${IMAGE}"
