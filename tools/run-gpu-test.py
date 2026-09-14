#!/usr/bin/env python3
"""Run one prepared GPU experiment with a user-level idle inhibitor."""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def build_command(vm_dir: Path, manifest: Path, output: Path, worktree: Path = ROOT) -> list[str]:
    return ["systemd-inhibit", "--what=idle", "--mode=block",
            "--who=RaphaelGPU", "--why=GPU test", sys.executable, "-B",
            str(worktree / "tools" / "experiment.py"), "run", "--vm-dir",
            str(vm_dir), "--manifest", str(manifest), "--output", str(output)]

def default_status_path() -> Path:
    return ROOT / "status.md"

def manifest_identity(manifest: Path) -> dict:
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {"candidate_version": "unknown", "run_id": "unknown"}
    spec = data.get("spec", data) if isinstance(data, dict) else {}
    return {"candidate_version": spec.get("candidate_version", "unknown"),
            "run_id": data.get("run_id", spec.get("run_id", "unknown"))}

def durable_write(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8") as stream:
        stream.write(content); stream.flush(); os.fsync(stream.fileno())

def append_status(status: Path, result: dict, output: Path) -> None:
    status.parent.mkdir(parents=True, exist_ok=True)
    row = ("\n\n## One-command GPU test\n\n"
           f"- Output: `{output}`\n"
           f"- Verdict: `{result.get('verdict', 'unknown')}`\n"
           f"- Boundary: `{result.get('earliest_failure', 'unknown')}`\n")
    with status.open("a", encoding="utf-8") as stream:
        stream.write(row); stream.flush(); os.fsync(stream.fileno())

def run(args: argparse.Namespace) -> int:
    vm = Path(args.vm_dir).resolve(); manifest = Path(args.manifest).resolve()
    output = Path(args.output).resolve()
    status = Path(getattr(args, "status_path", default_status_path())).resolve()
    worktree = Path(getattr(args, "worktree", ROOT)).resolve()
    if not vm.is_dir(): raise SystemExit(f"missing vm directory: {vm}")
    if not manifest.is_file(): raise SystemExit(f"missing manifest: {manifest}")
    if not (worktree / "tools" / "experiment.py").is_file(): raise SystemExit(f"missing experiment runner: {worktree}")
    if output.exists(): raise SystemExit(f"output already exists: {output}")
    command = build_command(vm, manifest, output, worktree)
    manual_reuse = getattr(args, "manual_reuse", False)
    ack_risk = getattr(args, "ack_risk", False)
    if manual_reuse != ack_risk:
        raise SystemExit("--manual-reuse and --ack-risk must be supplied together")
    if manual_reuse:
        command += ["--manual-reuse", "--ack-risk"]
    if args.dry_run:
        print(json.dumps({"dry_run": True, "command": command}, indent=2)); return 0
    identity = manifest_identity(manifest)
    try:
        completed = subprocess.run(command, cwd=worktree, text=True,
                                   capture_output=True, check=False)
        stdout, stderr, returncode = completed.stdout, completed.stderr, completed.returncode
    except OSError as error:
        stdout, stderr, returncode = "", str(error), 127
    output.mkdir(parents=True, exist_ok=True)
    durable_write(output / "wrapper-stdout.txt", stdout)
    durable_write(output / "wrapper-stderr.txt", stderr)
    try:
        parsed = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if isinstance(parsed, dict):
        result = dict(parsed, returncode=returncode,
                      stdout_bytes=len(stdout.encode()), stderr_bytes=len(stderr.encode()), **identity)
    else:
        result = {'returncode': returncode, 'stdout_bytes': len(stdout.encode()),
                  'stderr_bytes': len(stderr.encode()), 'verdict': 'WRAPPER_FAILURE',
                  'earliest_failure': 'launcher', **identity}
    durable_write(output / "wrapper-result.json", json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result.get(key) for key in
                     ('verdict', 'earliest_failure', 'candidate_version', 'run_id', 'returncode')}))
    append_status(status, result, output)
    return returncode

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-dir", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--worktree", default=str(ROOT), help="clean candidate worktree containing tools/experiment.py")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status-path", default=str(default_status_path()))
    parser.add_argument("--manual-reuse", action="store_true",
                        help="explicit same-boot reuse under a recorded status.md allowance")
    parser.add_argument("--ack-risk", action="store_true")
    return run(parser.parse_args())

if __name__ == "__main__": raise SystemExit(main())
