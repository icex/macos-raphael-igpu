#!/usr/bin/env python3
"""Run one identity-bound GDB capture inside an existing experiment deadline."""
import argparse
import json
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


def detach(gdb):
    result = subprocess.run([gdb, "-batch", "-ex", "set confirm off", "-ex",
                    "target remote 127.0.0.1:1234", "-ex", "detach", "-ex", "quit"],
                   capture_output=True, text=True, timeout=3,
                   check=False)
    return {"returncode":result.returncode, "detached":result.returncode == 0,
            "output":(result.stdout+result.stderr)[-2000:]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--supervision", required=True, type=Path)
    parser.add_argument("--serial", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--gdb", required=True)
    parser.add_argument("--generator", required=True, type=Path)
    parser.add_argument("--kernel-symbols", required=True, type=Path)
    parser.add_argument("--raphael-binary", required=True, type=Path)
    parser.add_argument("--raphael-dsym", required=True, type=Path)
    parser.add_argument("--scenario", choices=("entry-update", "vmid1-root"), default="entry-update")
    parser.add_argument("--target-gpu-address")
    parser.add_argument("--docker", default="docker")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{32}", args.build_id):
        parser.error("invalid build identity")
    if args.scenario == "entry-update" and args.target_gpu_address is None:
        parser.error("--target-gpu-address is required for entry-update")
    if args.scenario == "vmid1-root" and args.target_gpu_address is not None:
        parser.error("--target-gpu-address is not used for vmid1-root")
    state = json.loads(args.supervision.read_text())
    cid = state.get("cid")
    if not isinstance(cid, str) or not re.fullmatch(r"[0-9a-f]{64}", cid):
        raise ValueError("supervision lacks exact CID")
    deadline = min(float(state["deadline_epoch"]),
                   float(state.get("launch_deadline_epoch", state["deadline_epoch"]))) - 25
    if deadline - time.time() < 10:
        raise ValueError("insufficient experiment time for bounded debugger capture")
    args.output.mkdir(parents=False, exist_ok=False)
    verify_port(cid, args.docker)
    runtime_text = None
    while time.time() < deadline - 8:
        verify_port(cid, args.docker)
        runtime_text = readiness(args.serial.read_text(errors="replace"), args.build_id)
        if runtime_text is not None:
            break
        time.sleep(.2)
    if runtime_text is None:
        raise TimeoutError("fresh kernel mapping and authenticated kmod were not observed")
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
        normal_detach = "WRAPPER_CPU_RETURN_HIT" in transcript.read_text(errors="replace")
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
