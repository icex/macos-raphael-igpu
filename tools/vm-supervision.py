#!/usr/bin/env python3
"""Arm and verify user-systemd supervision for one identified VM container.

No background child of redeploy.sh owns the deadline or serial drain. The timer's
absolute deadline is derived from Docker StartedAt, so setup time consumes its cap.
Only selected non-secret Docker identity fields are queried or recorded.
"""
import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import uuid
import subprocess
import sys
import time

CID_PATTERN = re.compile(r"[0-9a-f]{64}")
DOCKER_ENV = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY",
              "DOCKER_CERT_PATH")


def full_cid(value):
    if not CID_PATTERN.fullmatch(value):
        raise ValueError("container identity must be a full 64-digit hexadecimal ID")
    return value


def seconds(value):
    # Zero means GPUless capture; redeploy rejects zero for an actual GPU launch.
    if not re.fullmatch(r"[0-9]+", str(value)) or not 0 <= int(value) <= 2147483647:
        raise ValueError("duration must be a finite nonnegative integer number of seconds")
    return int(value)


def binary(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"required command is unavailable: {name}")
    return path


def run(args, timeout=10):
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=timeout,
                                env=dict(os.environ, LC_ALL="C", TZ="UTC"))
    except subprocess.TimeoutExpired:
        # TimeoutExpired includes full argv, including forwarded endpoint values.
        raise RuntimeError(f"{Path(args[0]).name} {args[1]} timed out") from None
    if result.returncode:
        # Do not echo command environments or complete Docker inspection output.
        raise RuntimeError(f"{Path(args[0]).name} {args[1]} failed ({result.returncode})")
    return result.stdout


def inspect(cid):
    selected = '{"Id":{{json .Id}},"StartedAt":{{json .State.StartedAt}},"Running":{{json .State.Running}}}'
    info = json.loads(run([binary("docker"), "inspect", "--format", selected, cid]))
    if info["Id"] != cid or info["Running"] is not True:
        raise RuntimeError("identified container is not running or inspection identity changed")
    started = datetime.fromisoformat(info["StartedAt"].replace("Z", "+00:00"))
    if started.tzinfo is None or started.timestamp() <= 0 or started.timestamp() > time.time():
        raise RuntimeError("container StartedAt is invalid or in the future")
    return info["StartedAt"], started.timestamp()


def stop_exact(cid, by_name=False):
    launch_name(cid) if by_name else full_cid(cid)
    # Full ID is supplied by the caller and validated before any subprocess is run.
    try:
        run([binary("docker"), "stop", "--time", "0", cid])
    except Exception:
        # A blocked graceful-stop path must not silently leave the test running.
        try:
            run([binary("docker"), "kill", cid])
        except Exception:
            # A successful listing distinguishes an already removed/stopped VM from
            # a daemon we cannot reach. Never treat a connection error as absence.
            active = run([binary("docker"), "ps", "--no-trunc", "--filter",
                          (f"name=^/{cid}$" if by_name else f"id={cid}"), "--format", "{{.ID}}"]).splitlines()
            if cid in active or any(active):
                raise RuntimeError("identified container still runs after stop/kill failure")


def properties(unit):
    output = run([binary("systemctl"), "--user", "show", unit,
                  "--property=LoadState,ActiveState,SubState,MainPID,Unit,NextElapseUSecRealtime,ExecStart"])
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def verify(state, require_ready=True):
    cid = full_cid(state["cid"])
    started_at, started_epoch = inspect(cid)
    maximum = seconds(state["max_seconds"])
    expected_deadline = math.floor(started_epoch + maximum) if maximum else None
    if state["started_at"] != started_at or state["deadline_epoch"] != expected_deadline:
        raise RuntimeError("saved supervision identity/deadline does not match this container start")
    if maximum:
        if expected_deadline <= time.time():
            raise RuntimeError("container exposure deadline has already elapsed")
        timer_name = f"rgpu-deadline-{cid}.timer"
        service_name = f"rgpu-deadline-{cid}.service"
        if state["timer_unit"] != timer_name:
            raise RuntimeError("saved timer does not belong to this container")
        timer = properties(timer_name)
        if (timer.get("LoadState"), timer.get("ActiveState"), timer.get("SubState"),
                timer.get("Unit")) != ("loaded", "active", "waiting", service_name):
            raise RuntimeError("exposure timer is not loaded, active, waiting, and correctly targeted")
        next_at = datetime.strptime(timer.get("NextElapseUSecRealtime", ""),
                                    "%a %Y-%m-%d %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        if next_at.timestamp() != expected_deadline:
            raise RuntimeError("exposure timer is not scheduled for the original deadline")
        target = properties(service_name)
        expected_command = f"{binary('docker')} stop --time 0 {cid}"
        if target.get("LoadState") != "loaded" or expected_command not in target.get("ExecStart", ""):
            raise RuntimeError("exposure service does not stop this exact container")
    elif state["timer_unit"] is not None:
        raise RuntimeError("unexpected timer for GPUless capture")
    serial_name = f"rgpu-serial-{cid}.service"
    if state["serial_unit"] != serial_name:
        raise RuntimeError("saved serial service does not belong to this container")
    serial = properties(serial_name)
    if (serial.get("LoadState"), serial.get("ActiveState"), serial.get("SubState")) != (
            "loaded", "active", "running") or int(serial.get("MainPID", "0")) <= 0:
        raise RuntimeError("serial capture service is not running")
    if require_ready and Path(state["serial_ready"]).read_text() != cid:
        raise RuntimeError("serial capture has not connected and opened its log")
    if maximum and expected_deadline <= time.time():
        raise RuntimeError("exposure deadline elapsed during verification")


def arm(vm, cid, maximum):
    started_at, started_epoch = inspect(cid)
    deadline = math.floor(started_epoch + maximum) if maximum else None
    if deadline is not None and deadline <= time.time():
        raise RuntimeError("container exposure deadline elapsed before supervision was armed")
    vm = vm.resolve()
    if not (vm / "sercat.py").is_file():
        raise RuntimeError("serial capture script is missing")
    runner = binary("systemd-run")
    docker = binary("docker")
    base = [runner, "--user", "--quiet", "--collect"]
    # The service must use the same Docker endpoint as this caller. Values are never logged.
    endpoint = [f"--setenv={key}={os.environ.get(key, '')}" for key in DOCKER_ENV]
    timer_unit = None
    if deadline is not None:
        timer_base = f"rgpu-deadline-{cid}"
        date = datetime.fromtimestamp(deadline, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        run(base + [f"--unit={timer_base}", f"--on-calendar={date}",
                    "--timer-property=AccuracySec=1us", "--timer-property=RandomizedDelaySec=0",
                    "--property=Type=exec", "--property=TimeoutStartSec=15s",
                    "--property=RuntimeMaxSec=15s", "--property=TimeoutStopSec=5s",
                    "--property=Restart=on-failure", "--property=RestartSec=1s"] + endpoint +
            ["--", docker, "stop", "--time", "0", cid])
        timer_unit = timer_base + ".timer"
    serial_base = f"rgpu-serial-{cid}"
    ready = vm / "run" / f"serial-{cid}.ready"
    ready.unlink(missing_ok=True)
    stop_command = shlex.join([docker, "stop", "--time", "0", cid])
    run(base + [f"--unit={serial_base}", "--service-type=exec",
                f"--property=WorkingDirectory={vm}", "--property=TimeoutStopSec=15s",
                f"--property=ExecStopPost={stop_command}", f"--setenv=VM_SERIAL={vm / 'run/serial.sock'}",
                f"--setenv=VM_SERIAL_READY={ready}", f"--setenv=VM_SERIAL_CID={cid}"] +
        endpoint + ["--", binary("systemd-inhibit"), "--what=sleep:idle", "--who=macOS VM serial",
                    "--why=Keep serial capture and the VM awake", sys.executable, "-u", str(vm / "sercat.py")])
    state = {"cid": cid, "started_at": started_at, "max_seconds": maximum,
             "deadline_epoch": deadline, "timer_unit": timer_unit,
             "serial_unit": serial_base + ".service", "serial_ready": str(ready)}
    verify(state, require_ready=False)
    until = time.monotonic() + 60
    while not ready.is_file():
        if time.monotonic() >= until or (deadline is not None and time.time() >= deadline):
            raise RuntimeError("serial capture did not become ready before its deadline")
        time.sleep(0.1)
    verify(state)
    return state



def launch_name(value):
    if not re.fullmatch(r"rgpu-launch-[0-9a-f]{32}", value):
        raise ValueError("cleanup requires a unique launch name")
    return value


def cleanup(vm, name):
    name = launch_name(name)
    identity = vm / "run" / (name + ".cid")
    try:
        cid = full_cid(identity.read_text().strip())
    except (OSError, ValueError):
        cid = None
    if cid:
        stop_exact(cid)
        for unit in (f"rgpu-serial-{cid}.service", f"rgpu-deadline-{cid}.timer"):
            try:
                run([binary("systemctl"), "--user", "stop", unit])
            except Exception:
                pass  # Container stop was positively established above.
    else:
        # This random name belongs exclusively to this launch. Even failed ID
        # lookup must not fall back to the reusable macos-sequoia name.
        stop_exact(name, by_name=True)


def launch(vm, name, maximum, gpu_args):
    """Foreground lifetime of a user service, with cleanup also in ExecStopPost."""
    vm = vm.resolve()
    name = launch_name(name)
    def terminated(signum, frame):
        raise RuntimeError("supervised launch was terminated")
    signal.signal(signal.SIGTERM, terminated)
    child = None
    try:
        # A prior socket must never satisfy this launch's readiness check.
        (vm / "run/serial.sock").unlink(missing_ok=True)
        with (vm / "run/vm-launch.log").open("w") as log:
            child = subprocess.Popen([str(vm / "macos-vm.sh"), "run", *gpu_args], cwd=vm,
                                     env=dict(os.environ, NAME=name, GPU="", GPU_ID="", GPU_ROM="",
                                              GPU_SUB="", EXTRA="", SERIAL="on"),
                                     stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        until = time.monotonic() + 30
        while True:
            if child.poll() is not None:
                raise RuntimeError("VM launcher exited before container identification")
            try:
                raw = run([binary("docker"), "inspect", "--format", "{{.Id}}", name], timeout=2).strip()
            except Exception:
                if time.monotonic() >= until:
                    raise RuntimeError("could not identify this launch within 30 seconds")
                time.sleep(0.1)
                continue
            cid = full_cid(raw)
            identity = vm / "run" / (name + ".cid")
            temporary = identity.with_suffix(".cid.tmp")
            temporary.write_text(cid)
            temporary.replace(identity)
            break
        # Docker publishes the name/ID while State.Status is still "created".
        # Keep the persisted exact identity and wait only through that transition.
        # The launch service's cap and cleanup already protect this interval.
        selected = '{"Id":{{json .Id}},"Running":{{json .State.Running}},"Status":{{json .State.Status}}}'
        while True:
            info = json.loads(run([binary("docker"), "inspect", "--format", selected, cid], timeout=2))
            if info["Id"] != cid:
                raise RuntimeError("container identity changed during startup")
            if info["Running"] is True:
                break
            if info.get("Status") != "created" or time.monotonic() >= until:
                raise RuntimeError("identified container failed to reach running state")
            time.sleep(0.1)
        state = arm(vm, cid, maximum)
        # Existing guest tools address this familiar name; all supervision uses CID.
        run([binary("docker"), "rename", cid, "macos-sequoia"])
        for _ in range(30):
            try:
                run([binary("docker"), "cp", str(vm / "agent-server.py"), f"{cid}:/tmp/"])
                for command in (["python3", "/tmp/agent-server.py"],
                                ["sh", "-c", "cd /run/vm && exec python3 -m http.server 8889"]):
                    try:
                        run([binary("docker"), "exec", "-d", cid, *command])
                    except Exception:
                        pass
                break
            except Exception:
                time.sleep(2)
        verify(state)
        state["launch_unit"] = name + ".service"
        ready = vm / "run" / (name + ".json")
        temporary = ready.with_suffix(".tmp")
        temporary.write_text(json.dumps(state))
        temporary.replace(ready)
        child.wait()
    finally:
        # Prevent an in-flight docker run from creating an uncapped container after
        # cleanup. systemd also kills the complete service cgroup on forced stop.
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        cleanup(vm, name)


def start(vm, maximum, gpu_args):
    vm = vm.resolve()
    name = "rgpu-launch-" + uuid.uuid4().hex
    helper = str(Path(__file__).resolve())
    env_keys = DOCKER_ENV + ("PATH", "DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "IMAGE",
                           "VCPUS", "RAM_GB", "DISK_BUS", "AUDIO", "NVRAM", "BOOTDISK_MODE",
                           "NIC", "GL", "GDB", "SSH_PORT", "SCREEN_PORT")
    endpoint = [f"--setenv={key}={os.environ.get(key, '')}" for key in env_keys]
    # A GPUless request cannot inherit hidden passthrough from the manager or
    # caller. GPU options are supplied solely by the validated launcher flags.
    endpoint += [f"--setenv={key}=" for key in ("GPU", "GPU_ID", "GPU_ROM", "GPU_SUB", "EXTRA")]
    stop_command = shlex.join([sys.executable, helper, "cleanup", "--vm-dir", str(vm), "--name", name])
    command = [binary("systemd-run"), "--user", "--quiet", "--collect", f"--unit={name}",
               "--service-type=exec", f"--property=WorkingDirectory={vm}",
               "--property=TimeoutStartSec=15s", "--property=TimeoutStopSec=30s",
               f"--property=ExecStopPost={stop_command}"]
    if maximum:
        # This first bound begins BEFORE docker run. The exact-CID timer in arm()
        # additionally uses StartedAt; neither phase can extend GPU exposure.
        command += [f"--property=RuntimeMaxSec={maximum}s"]
    command += endpoint + ["--", sys.executable, helper, "launch", "--vm-dir", str(vm),
                           "--name", name, "--max-seconds", str(maximum), "--", *gpu_args]
    try:
        run(command)
        ready = vm / "run" / (name + ".json")
        until = time.monotonic() + 160
        while not ready.is_file():
            service = properties(name + ".service")
            if (service.get("LoadState"), service.get("ActiveState"), service.get("SubState")) != (
                    "loaded", "active", "running"):
                raise RuntimeError("supervised launcher is not running")
            if time.monotonic() >= until:
                raise RuntimeError("supervised launcher did not publish readiness")
            time.sleep(0.2)
        state = json.loads(ready.read_text())
        verify(state)
        service = properties(name + ".service")
        if (service.get("ActiveState"), service.get("SubState")) != ("active", "running"):
            raise RuntimeError("supervised launcher stopped during readiness verification")
        (vm / "run/supervision.json").write_text(json.dumps(state))
        return state
    except Exception:
        try:
            run([binary("systemctl"), "--user", "stop", name + ".service"], timeout=40)
        finally:
            cleanup(vm, name)
        raise

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("arm")
    create.add_argument("--vm-dir", type=Path, required=True)
    create.add_argument("--cid", required=True)
    create.add_argument("--max-seconds", required=True)
    check = commands.add_parser("verify")
    check.add_argument("--state", type=Path, required=True)
    for verb in ("start", "launch", "cleanup"):
        sub = commands.add_parser(verb)
        sub.add_argument("--vm-dir", type=Path, required=True)
        if verb != "start":
            sub.add_argument("--name", required=True)
        if verb != "cleanup":
            sub.add_argument("--max-seconds", required=True)
            sub.add_argument("gpu_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cid = None
    try:
        if args.command in ("start", "launch", "cleanup"):
            if args.command == "cleanup":
                cleanup(args.vm_dir, args.name)
                return 0
            maximum = seconds(args.max_seconds)
            gpu_args = args.gpu_args[1:] if args.gpu_args[:1] == ["--"] else args.gpu_args
            if "--gpu" in gpu_args and maximum == 0:
                raise ValueError("GPU launches require a positive exposure cap")
            if args.command == "launch":
                launch(args.vm_dir, args.name, maximum, gpu_args)
                return 0
            state = start(args.vm_dir, maximum, gpu_args)
        elif args.command == "arm":
            cid = full_cid(args.cid)
            state = arm(args.vm_dir, cid, seconds(args.max_seconds))
        else:
            state = json.loads(args.state.read_text())
            cid = full_cid(state["cid"])
            verify(state)
        print(json.dumps(state))
        return 0
    except Exception as error:
        print(f"VM supervision refused: {error}", file=sys.stderr)
        if cid:
            try:
                stop_exact(cid)
                for unit in (f"rgpu-serial-{cid}.service", f"rgpu-deadline-{cid}.timer"):
                    try:
                        run([binary("systemctl"), "--user", "stop", unit])
                    except Exception:
                        pass
                print(f"Stopped container {cid} after supervision failure", file=sys.stderr)
            except Exception:
                print(f"CRITICAL: could not stop container {cid}; immediate operator action required",
                      file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())
