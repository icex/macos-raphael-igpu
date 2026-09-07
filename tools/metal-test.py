#!/usr/bin/env python3
"""Compile/run a bounded Metal compute + render probe through an existing guest's gx.

Does not launch a VM or change device ownership. Prepare with a GPU-less guest first.
The guest exit status and a fresh run ID are required: gx itself discards exit status.
"""
import argparse
import base64
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]


def run_guest_command(vm, command, run_id, env, timeout=80, execution_grace=45):
    """Revoke delayed delivery as well as timing out the waiting gx process."""
    permit = vm / "run" / f"metal-permit-{run_id}"
    pending = vm / "run/cmd.txt"
    with (vm / "run/metal-test.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        permit.write_text(run_id)
        exited = False
        try:
            proc = subprocess.run([str(vm / "gx"), command], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, timeout=timeout)
            exited = bool(re.search(r"^RGPU_EXIT " + re.escape(run_id) + r" \d+$",
                                    proc.stdout, re.M))
            return proc
        finally:
            permit.unlink(missing_ok=True)
            try:
                if pending.read_text() == command:
                    pending.unlink(missing_ok=True)
            except FileNotFoundError:
                pass  # The guest has already consumed this command.
            # Revocation prevents delayed starts. A probe already admitted may still be
            # running, so retain the lock for its maximum process lifetime on lost output.
            if not exited and execution_grace > 0:
                time.sleep(execution_grace)


def validate_output(output, run_id):
    rows = [line.removeprefix("RGPU_METAL_RESULT ") for line in output.splitlines()
            if line.startswith("RGPU_METAL_RESULT ")]
    if len(rows) != 1:
        raise ValueError("expected exactly one complete Metal result")
    result = json.loads(rows[0])
    if not isinstance(result, dict) or result.get("run_id") != run_id:
        raise ValueError("missing or stale run ID")
    exits = re.findall(r"^RGPU_EXIT " + re.escape(run_id) + r" (\d+)$", output, re.M)
    if exits != ["0"]:
        raise ValueError("probe did not exit successfully (gx exit status is insufficient)")
    if result.get("passed") is not True or result.get("metal3") is not True:
        raise ValueError("Metal probe failed or Metal 3 is unavailable")
    if result.get("device") != "AMD Radeon Navi23":
        raise ValueError("the expected passed-through Navi23 device was not tested")
    for key, minimum in (("registry_id", 1), ("compute_rounds", 3),
                         ("compute_values_checked", 196608),
                         ("render_pixels_checked", 4096), ("completed_command_buffers", 4)):
        if type(result.get(key)) is not int or result[key] < minimum:
            raise ValueError(f"insufficient execution evidence: {key}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-dir", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true",
                        help="compile in a GPU-less guest without running Metal")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "findings/metal-tests")
    args = parser.parse_args()
    vm = args.vm_dir.resolve()
    if not (vm / "gx").is_file() or not (vm / "run").is_dir():
        parser.error("--vm-dir must contain gx and run/")
    source = (ROOT / "tests/metal_probe.m").read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    run_id = uuid.uuid4().hex
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.output_dir / f"{stamp}-{run_id[:8]}"
    out.mkdir(parents=True, exist_ok=False)
    guest_dir = f"/var/tmp/rgpu-metal-{digest[:16]}"
    qdir = shlex.quote(guest_dir)
    payload = base64.b64encode(source).decode("ascii")
    # Separate final marker captures failure of decoding, compilation, and execution alike.
    prepare = (f"mkdir -p {qdir} && printf %s {shlex.quote(payload)} | /usr/bin/base64 -D "
               f"> {qdir}/probe.m && /usr/bin/xcrun clang -fobjc-arc -fblocks -O2 "
               f"-Wall -Wextra -Werror -framework Foundation -framework Metal "
               f"{qdir}/probe.m -o {qdir}/probe")
    if args.prepare_only:
        action = prepare
    else:
        # Require an already prepared binary so GPU exposure never includes compiler setup.
        # The permit disappears when gx finishes or times out. A late guest must fetch it
        # immediately before running; a timestamp alone would depend on guest clock skew.
        expiry = int(time.time()) + 65
        permit_url = f"http://10.0.2.2:8889/metal-permit-{run_id}"
        action = (f"permit=$(/usr/bin/curl -fsS --max-time 3 {shlex.quote(permit_url)}) && "
                  f"test \"$permit\" = {shlex.quote(run_id)} && "
                  f"test -x {qdir}/probe && {qdir}/probe {shlex.quote(run_id)} {expiry}")
    command = f"( {action}; result=$?; printf '\\nRGPU_EXIT {run_id} %s\\n' \"$result\" )"
    env = dict(os.environ, GX_TIMEOUT="100" if args.prepare_only else "70")
    metadata = {"run_id": run_id, "source_sha256": digest, "prepare_only": args.prepare_only,
                "passed": False, "guest_binary": guest_dir + "/probe"}
    output = ""
    try:
        proc = run_guest_command(vm, command, run_id, env,
                                 timeout=110 if args.prepare_only else 80,
                                 execution_grace=0 if args.prepare_only else 45)
        output = proc.stdout
        if proc.returncode:
            raise ValueError(f"guest transport failed with exit {proc.returncode}")
        if args.prepare_only:
            if re.findall(r"^RGPU_EXIT " + run_id + r" (\d+)$", output, re.M) != ["0"]:
                raise ValueError("guest compiler failed; see guest-output.txt")
            metadata["prepared"] = True
        else:
            metadata["probe"] = validate_output(output, run_id)
            metadata["passed"] = True
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        if isinstance(error, subprocess.TimeoutExpired):
            partial = error.stdout or b""
            output = partial.decode(errors="replace") if isinstance(partial, bytes) else partial
        metadata["error"] = str(error)
    (out / "guest-output.txt").write_text(output)
    (out / "result.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(output, end="" if output.endswith("\n") else "\n")
    print(f"Evidence: {out}")
    if "error" in metadata:
        print(f"FAIL: {metadata['error']}", file=sys.stderr)
        return 1
    print("PREPARED (GPU execution not tested)" if args.prepare_only else
          "PASS: repeated Metal compute and offscreen rendering returned correct results")
    return 0


if __name__ == "__main__":
    sys.exit(main())
