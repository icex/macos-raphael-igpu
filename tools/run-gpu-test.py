#!/usr/bin/env python3
"""Run one prepared GPU experiment with a user-level sleep and idle inhibitor."""
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def build_command(vm_dir: Path, manifest: Path, output: Path, worktree: Path = ROOT) -> list[str]:
    return ["systemd-inhibit", "--what=sleep:idle", "--mode=block",
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
    if result.get('postrun_recovery'):
        row += f"- Post-run recovery: `{result['postrun_recovery']['status']}`\n"
    with status.open("a", encoding="utf-8") as stream:
        stream.write(row); stream.flush(); os.fsync(stream.fileno())

def recover_halted_queues(vm: Path, output: Path, worktree: Path) -> dict | None:
    """Complete schema-2 guard cleanup after QEMU has stopped and released VFIO.

    The guard halts GC before guest RAM is unmapped. Ordinary recovery cannot
    retire those halted HQDs afterward; MODE2 plus the complete no-queue scan
    is the existing independent qualification path. Its receipt stays separate.
    """
    try:
        guard = json.loads((output/'dma-guard.json').read_text())
        recovery = json.loads((output/'recovery.json').read_text())
    except (OSError, ValueError):
        return None
    if (guard.get('schema') != 2 or guard.get('status') != 'released' or
            recovery.get('status') not in ('incomplete', 'failed') or
            recovery.get('authorizes_launch') is not False):
        return None
    receipt = output/'postrun-mode2-noqueue.json'
    command = [sys.executable, '-B', str(worktree/'tools/mode2-noqueue-recover.py'),
               '--vm-dir', str(vm), '--run-dir', str(output), '--output', str(receipt),
               '--execute']
    try:
        completed = subprocess.run(command, cwd=worktree, text=True,
                                   capture_output=True, timeout=90, check=False)
        durable_write(output/'postrun-mode2-noqueue.log',
                      completed.stdout + completed.stderr)
        value = json.loads(receipt.read_text())
        status = ('recovered' if completed.returncode == 0 and
                  value.get('status') == 'recovered' and
                  value.get('authorizes_launch') is True else 'failed')
        return {'status': status, 'receipt': str(receipt),
                'returncode': completed.returncode}
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        durable_write(output/'postrun-mode2-noqueue.log',
                      type(error).__name__ + ': ' + str(error) + '\n')
        return {'status': 'failed', 'receipt': str(receipt), 'error': str(error)}

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
    if getattr(args, 'noqueue_reuse', None):
        command += ['--noqueue-reuse', str(Path(args.noqueue_reuse).resolve())]
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
    postrun = recover_halted_queues(vm, output, worktree)
    if postrun is not None:
        result['postrun_recovery'] = postrun
        if postrun['status'] != 'recovered' and returncode == 0:
            returncode = 3
            result['returncode'] = returncode
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
    parser.add_argument("--noqueue-reuse", type=Path,
                        help="prior empty-capture failure; requires fresh stopped-queue proof")
    parser.add_argument("--worktree", default=str(ROOT), help="clean candidate worktree containing tools/experiment.py")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status-path", default=str(default_status_path()))
    return run(parser.parse_args())

if __name__ == "__main__": raise SystemExit(main())
