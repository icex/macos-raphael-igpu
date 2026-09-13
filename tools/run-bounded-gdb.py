#!/usr/bin/env python3
"""Run one identity-bound GDB capture inside an existing experiment deadline."""
import argparse
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

KERNEL_TEXT = re.compile(r"Kernel text (0x[0-9a-f]+)-(0x[0-9a-f]+) to be write-protected")


def readiness(text, build_id):
    match = KERNEL_TEXT.search(text)
    loaded = re.search(r"BUILD: identity=([0-9a-f]{32})", text)
    if not match or not loaded or loaded.group(1) != build_id:
        return None
    start, end = (int(value, 16) for value in match.groups())
    if end - start != 0xa00000:
        raise ValueError("unexpected fresh kernel text mapping")
    return start


def verify_port(cid, docker="docker"):
    value = subprocess.check_output(
        [docker, "inspect", "--format",
         '{{.State.Running}} {{json .NetworkSettings.Ports}}', cid],
        text=True, timeout=5)
    running, encoded_ports = value.strip().split(' ', 1)
    if running != "true":
        raise ValueError("exact supervised CID is not running")
    ports = json.loads(encoded_ports)
    rows = ports.get("1234/tcp") or []
    if not any(row.get("HostIp") == "127.0.0.1" and row.get("HostPort") == "1234"
               for row in rows):
        raise ValueError("exact supervised CID lacks loopback GDB mapping")


def live_serial_path(state):
    cid = state.get("cid")
    ready = state.get("serial_ready")
    if (not isinstance(cid, str) or not re.fullmatch(r"[0-9a-f]{64}", cid) or
            not isinstance(ready, str)):
        raise ValueError("supervision lacks live serial identity")
    ready_path = Path(ready)
    if not ready_path.is_absolute() or ready_path.name != f"serial-{cid}.ready":
        raise ValueError("supervision serial readiness identity mismatch")
    if ready_path.is_symlink():
        raise ValueError("supervision serial readiness path must not be a symlink")
    expected = cid + (" console" if state.get("critical_enabled") is True else "")
    try:
        content = ready_path.read_text()
    except OSError as error:
        raise ValueError("supervision serial readiness content unavailable") from error
    if content != expected:
        raise ValueError("supervision serial readiness content mismatch")
    serial = ready_path.parent / "serial.log"
    if serial.is_symlink():
        raise ValueError("live serial path must not be a symlink")
    return serial


def detach(gdb):
    result = subprocess.run([gdb, "-batch", "-ex", "set confirm off", "-ex",
                    "target remote 127.0.0.1:1234", "-ex", "detach", "-ex", "quit"],
                   capture_output=True, text=True, timeout=3,
                   check=False)
    return {"returncode":result.returncode, "detached":result.returncode == 0,
            "output":(result.stdout+result.stderr)[-2000:]}


def post_probe_script():
    """Read-only stop snapshot; the GDB stub exposes vCPUs, not Darwin threads."""
    return '''set pagination off
set confirm off
target remote 127.0.0.1:1234
interrupt
printf "POST_PROBE_INTERRUPT_HIT\\n"
printf "POST_PROBE_VCPU_REGISTERS\\n"
info registers
printf "POST_PROBE_VCPU_BACKTRACE\\n"
thread apply all bt 8
printf "POST_PROBE_SELECTED_VCPU_BACKTRACE\\n"
bt full 8
printf "POST_PROBE_VCPU_STACK\\n"
x/32gx $rsp
detach
printf "POST_PROBE_DETACHED\\n"
quit
'''


def validate_failure_record(path, state, build_id, run_id, manifest_path):
    try:
        record = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("probe failure record unavailable") from error
    if not isinstance(record, dict):
        raise ValueError("probe failure record must be an object")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("probe manifest unavailable") from error
    if (record.get("run_id") != run_id or record.get("build_id") != build_id or
            manifest.get("run_id") != run_id or manifest.get("build_id") != build_id):
        raise ValueError("probe failure record identity mismatch")
    if record.get("cid") != state.get("cid"):
        raise ValueError("probe failure record CID mismatch")
    if record.get("boot_id") != manifest.get("boot_id"):
        raise ValueError("probe failure record boot identity mismatch")
    probe = record.get("probe")
    if not isinstance(probe, dict) or not (
            probe.get("failed") is True or probe.get("timed_out") is True or
            probe.get("transport_exit") not in (None, 0) or
            (isinstance(probe.get("output"), str) and
             re.search(r'"passed"\s*:\s*false|RGPU_EXIT\s+' + re.escape(run_id) + r'\s+[1-9]\b', probe["output"]))):
        raise ValueError("probe failure record does not prove failed probe")
    if (not isinstance(record.get("manifest_sha256"), str) or
            not re.fullmatch(r"[0-9a-f]{64}", record["manifest_sha256"])):
        raise ValueError("probe failure record manifest hash missing")
    if (not isinstance(record.get("deadline_epoch"), (int, float)) or
            not math.isfinite(record["deadline_epoch"]) or
            record["deadline_epoch"] > float(state["deadline_epoch"]) + 1):
        raise ValueError("probe failure record deadline mismatch")
    try:
        manifest_hash = __import__('hashlib').sha256(manifest_path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError("probe manifest unavailable") from error
    if record["manifest_sha256"] != manifest_hash:
        raise ValueError("probe failure record manifest hash mismatch")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supervision", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--gdb", required=True)
    parser.add_argument("--generator", required=True, type=Path)
    parser.add_argument("--kernel-symbols", required=True, type=Path)
    parser.add_argument("--raphael-binary", required=True, type=Path)
    parser.add_argument("--raphael-dsym", required=True, type=Path)
    parser.add_argument("--scenario", choices=("entry-update", "vmid1-root", "post-probe", "kiq-stamp"), default="entry-update")
    parser.add_argument("--target-gpu-address")
    parser.add_argument("--run-id")
    parser.add_argument("--failure-record", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{32}", args.build_id):
        parser.error("invalid build identity")
    if args.scenario == "entry-update" and args.target_gpu_address is None:
        parser.error("--target-gpu-address is required for entry-update")
    if args.scenario == "vmid1-root" and args.target_gpu_address is not None:
        parser.error("--target-gpu-address is not used for vmid1-root")
    if args.scenario == "kiq-stamp" and args.target_gpu_address is not None:
        parser.error("--target-gpu-address is not used for kiq-stamp")
    if args.scenario == "post-probe":
        if args.target_gpu_address is not None:
            parser.error("--target-gpu-address is not used for post-probe")
        if (not isinstance(args.run_id, str) or
                not re.fullmatch(r"[0-9a-f]{32}", args.run_id)):
            parser.error("post-probe requires a valid --run-id")
        if args.failure_record is None:
            parser.error("post-probe requires --failure-record")
        if args.manifest is None:
            parser.error("post-probe requires --manifest")
    state = json.loads(args.supervision.read_text())
    cid = state.get("cid")
    if not isinstance(cid, str) or not re.fullmatch(r"[0-9a-f]{64}", cid):
        raise ValueError("supervision lacks exact CID")
    serial = live_serial_path(state)
    deadline = min(float(state["deadline_epoch"]),
                   float(state.get("launch_deadline_epoch", state["deadline_epoch"]))) - 25
    if args.scenario == "kiq-stamp":
        deadline = min(deadline, time.time() + 150)
    if deadline - time.time() < 10:
        raise ValueError("insufficient experiment time for bounded debugger capture")
    record = None
    if args.scenario == "post-probe":
        record = validate_failure_record(args.failure_record, state, args.build_id,
                                         args.run_id, args.manifest)
        deadline = min(deadline, float(record["deadline_epoch"]))
        if deadline - time.time() < 10:
            raise ValueError("insufficient experiment time for bounded debugger capture")
    runtime_text = None
    while time.time() < deadline - 8:
        verify_port(cid, args.docker)
        try:
            serial_text = serial.read_text(errors="replace")
        except FileNotFoundError:
            serial_text = ""
        runtime_text = readiness(serial_text, args.build_id)
        if runtime_text is not None:
            break
        time.sleep(.2)
    if runtime_text is None:
        raise TimeoutError("fresh kernel mapping and authenticated kmod were not observed")
    if args.scenario == "post-probe":
        args.output.mkdir(parents=False, exist_ok=False)
        verify_port(cid, args.docker)
        script = args.output / "capture.gdb"
        subprocess.run([sys.executable, str(args.generator),
                        "--runtime-kernel-text", hex(runtime_text),
                        "--raphael-binary", str(args.raphael_binary),
                        "--kernel-symbols", str(args.kernel_symbols),
                        "--raphael-dsym", str(args.raphael_dsym),
                        "--scenario", "post-probe", "--output", str(script)],
                       check=True, timeout=5)
        transcript = args.output / "gdb-transcript.log"
        normal_detach = False
        cleanup = None
        capture_error = None
        try:
            with transcript.open("x") as stream:
                process = subprocess.Popen([args.gdb, "-batch", "-x", str(script)],
                                           stdout=stream, stderr=subprocess.STDOUT, text=True)
                try:
                    process.wait(timeout=max(1, deadline-time.time()-4))
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try: process.wait(timeout=2)
                    except subprocess.TimeoutExpired: process.kill(); process.wait()
                    raise TimeoutError("bounded post-probe GDB capture timed out")
                if process.returncode:
                    raise RuntimeError(f"GDB capture failed with status {process.returncode}")
            transcript_text = transcript.read_text(errors="replace")
            required = ("RAPHAEL_AUTHENTICATED", "POST_PROBE_INTERRUPT_HIT", "POST_PROBE_VCPU_REGISTERS",
                        "POST_PROBE_VCPU_BACKTRACE", "POST_PROBE_DETACHED")
            if not all(marker in transcript_text for marker in required):
                raise RuntimeError("post-probe transcript lacks complete bounded capture")
            normal_detach = True
        except Exception as error:
            capture_error = error
        finally:
            if not normal_detach:
                verify_port(cid, args.docker)
                cleanup = detach(args.gdb)
                (args.output / "detach-result.json").write_text(json.dumps(cleanup, indent=2)+"\n")
        if capture_error is not None:
            if cleanup is not None and not cleanup["detached"]:
                raise RuntimeError(f"capture failed ({capture_error}); detach/resume failed: {cleanup['output']}")
            raise capture_error
        (args.output / "result.json").write_text(json.dumps({
            "cid": cid, "run_id": args.run_id, "build_id": args.build_id,
            "scenario": "post-probe", "complete": True,
            "partial": bool(re.search(
                r"(?:Cannot access memory|No stack|unavailable|error:)",
                transcript_text, re.I)),
            "gpu_completion_established": False,
            "atomic_hardware_snapshot": False,
            "darwin_all_threads": False,
            "meaning": "read-only stopped-vCPU registers, backtrace, and stack",
        }, indent=2) + "\n")
        return
    args.output.mkdir(parents=False, exist_ok=False)
    verify_port(cid, args.docker)
    script = args.output / "capture.gdb"
    subprocess.run([sys.executable, str(args.generator), "--runtime-kernel-text", hex(runtime_text),
                    "--raphael-binary", str(args.raphael_binary),
                    "--kernel-symbols", str(args.kernel_symbols),
                    "--raphael-dsym", str(args.raphael_dsym),
                    "--scenario", args.scenario,
                    *(["--target-gpu-address", args.target_gpu_address] if args.target_gpu_address else []),
                    "--output", str(script)],
                   check=True, timeout=5)
    transcript = args.output / "gdb-transcript.log"
    normal_detach = False
    cleanup = None
    capture_error = None
    try:
        with transcript.open("x") as stream:
            process = subprocess.Popen([args.gdb, "-batch", "-x", str(script)],
                                       stdout=stream, stderr=subprocess.STDOUT, text=True)
            try:
                process.wait(timeout=max(1, deadline-time.time()-4))
            except subprocess.TimeoutExpired:
                process.terminate()
                try: process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
                raise TimeoutError("bounded GDB capture timed out")
            if process.returncode:
                raise RuntimeError(f"GDB capture failed with status {process.returncode}")
        transcript_text = transcript.read_text(errors="replace")
        normal_detach = ("KIQ_DETACHED" in transcript_text
                         if args.scenario == "kiq-stamp"
                         else "WRAPPER_CPU_RETURN_HIT" in transcript_text)
    except Exception as error:
        capture_error = error
    finally:
        if not normal_detach:
            verify_port(cid, args.docker)
            cleanup = detach(args.gdb)
            (args.output / "detach-result.json").write_text(json.dumps(cleanup, indent=2)+"\n")
    if capture_error is not None:
        if cleanup is not None and not cleanup["detached"]:
            raise RuntimeError(f"capture failed ({capture_error}); detach/resume failed: {cleanup['output']}")
        raise capture_error
    transcript_text = transcript.read_text(errors="replace")
    required = (("VMID1_WRAPPER_ENTRY_HIT", "VMID1_NATIVE_CALL_BOUNDARY", "VMID1_PREPARED_CPU_OUTPUT", "WRAPPER_CPU_RETURN_HIT")
                if args.scenario == "vmid1-root" else
                ("KIQ_WAIT_FAILURE", "KIQ_CAPTURE_COMPLETE", "KIQ_DETACHED")
                if args.scenario == "kiq-stamp" else
                ("WRAPPER_ENTRY_HIT", "NATIVE_CALL_BOUNDARY", "WRAPPER_CPU_RETURN_HIT"))
    if not all(marker in transcript_text for marker in required):
        raise RuntimeError("GDB transcript lacks complete bounded capture")
    (args.output / "result.json").write_text(json.dumps({
        "cid": cid, "runtime_kernel_text": hex(runtime_text), "build_id": args.build_id,
        "scenario": args.scenario, "target_gpu_address": args.target_gpu_address,
        "complete": True, "gpu_completion_established": False,
        "atomic_hardware_snapshot": False}, indent=2) + "\n")


if __name__ == "__main__":
    main()
