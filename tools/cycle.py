#!/usr/bin/env python3
"""One candidate iteration: preflight -> reset -> stage -> prepare -> run -> record.

This is the single entry point for the change/test/run loop. Everything that can be
derived from the repository and the host is derived here; only the values that genuinely
cannot be (the staged boot image, the verified Lilu bundle, the device identity) come
from experiments/pins.json.

    tools/cycle.py --candidate 231 --card metal-079
    tools/cycle.py --candidate 231 --card metal-079 --dry-run
    tools/cycle.py --candidate 231 --card metal-079 --attempt retry1

A GPU launch is only reached when every preflight gate passes. --dry-run stops before the
MODE2 reset and prints the exact commands, so the plan can be reviewed without touching
the device.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CycleError(RuntimeError):
    """A gate failed; no GPU exposure has happened."""


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_pins(path: Path) -> dict:
    try:
        pins = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise CycleError(f"cannot read pins {path}: {error}") from error
    for key in ("vm_dir", "gpu_bdf", "image_id", "inhibitor_container", "lilu"):
        if key not in pins:
            raise CycleError(f"pins missing required key: {key}")
    return pins


def boot_id() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()


def gpu_driver(bdf: str) -> str:
    link = Path(f"/sys/bus/pci/devices/{bdf}/driver")
    if not link.exists():
        return "(unbound)"
    return os.path.basename(os.path.realpath(link))


def container_running(name: str) -> bool:
    try:
        out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                             capture_output=True, text=True, timeout=20, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return name in out.split()


def git(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode:
        raise CycleError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def next_reset_index(vm: Path) -> int:
    """MODE2 receipts are numbered; continue the sequence rather than overwrite one."""
    highest = 0
    for path in (vm / "run").glob("mode2-reset-*.json"):
        match = re.fullmatch(r"mode2-reset-(\d+)\.json", path.name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def run_step(name: str, command: list[str], cwd: Path, log: Path | None = None,
             allow_failure: bool = False) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(command)}", flush=True)
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w", encoding="utf-8") as stream:
            stream.write(result.stdout)
            stream.write(result.stderr)
            stream.flush()
            os.fsync(stream.fileno())
    if result.returncode and not allow_failure:
        tail = (result.stderr or result.stdout).strip().splitlines()[-15:]
        raise CycleError(f"{name} failed (exit {result.returncode}):\n" + "\n".join(tail))
    return result


def preflight(args, pins: dict, worktree: Path, vm: Path) -> dict:
    """Every gate that must hold before the device is touched."""
    print("[1/5] preflight")
    facts: dict[str, object] = {}

    driver = gpu_driver(pins["gpu_bdf"])
    if driver != "vfio-pci":
        raise CycleError(f"GPU {pins['gpu_bdf']} is bound to {driver!r}, expected vfio-pci. "
                         "Never rebind to amdgpu within a boot.")
    facts["gpu_driver"] = driver
    print(f"      GPU {pins['gpu_bdf']} on vfio-pci")

    if not container_running(pins["inhibitor_container"]):
        raise CycleError(f"idle inhibitor container {pins['inhibitor_container']!r} is not running")
    print(f"      inhibitor {pins['inhibitor_container']} up")

    if not worktree.is_dir():
        raise CycleError(f"candidate worktree missing: {worktree}")
    dirty = git(["status", "--porcelain"], worktree)
    if dirty and not args.allow_dirty:
        raise CycleError(f"worktree {worktree} is dirty; commit or pass --allow-dirty:\n{dirty}")
    commit = git(["rev-parse", "HEAD"], worktree)
    facts["commit"] = commit
    print(f"      worktree {worktree.name} @ {commit[:12]}{' (dirty)' if dirty else ''}")

    card = worktree / "experiments" / f"{args.card}.json"
    if not card.is_file():
        raise CycleError(f"card not found: {card}")
    facts["card_sha256"] = sha_file(card)
    print(f"      card {args.card} sha {facts['card_sha256'][:12]}")

    suffix = f"-attempt-{args.attempt}" if args.attempt else ""
    identities = vm / "run" / f"candidate-{args.candidate}{suffix}-build-identities.json"
    if not identities.is_file():
        identities = vm / "run" / f"candidate-{args.candidate}-build-identities.json"
    if not identities.is_file():
        raise CycleError(f"build identities not found: {identities}")
    facts["identities"] = str(identities)
    facts["identities_sha256"] = sha_file(identities)
    print(f"      identities {identities.name} sha {facts['identities_sha256'][:12]}")

    if not args.skip_tests:
        print("      running host regression suite")
        result = run_step("unit tests",
                          [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"],
                          cwd=worktree, allow_failure=True)
        summary = re.search(r"Ran (\d+) tests?", result.stderr or "")
        if result.returncode:
            tail = (result.stderr or "").strip().splitlines()[-15:]
            raise CycleError("host regression suite failed:\n" + "\n".join(tail))
        facts["tests"] = int(summary.group(1)) if summary else None
        print(f"      tests OK ({facts.get('tests')} passed)")
    else:
        print("      tests SKIPPED (--skip-tests)")

    facts["boot_id"] = boot_id()
    return facts


def mode2_reset(worktree: Path, vm: Path, index: int) -> dict:
    print(f"[2/5] MODE2 reset #{index}")
    tool = worktree / "tools" / "smu-mode2-reset.py"
    run_step("mode2 probe", [sys.executable, "-B", str(tool), "--probe",
                             "--output", str(vm / "run" / f"mode2-probe-{index}.json")], cwd=vm)
    receipt = vm / "run" / f"mode2-reset-{index}.json"
    run_step("mode2 execute", [sys.executable, "-B", str(tool), "--execute",
                               "--output", str(receipt)], cwd=vm)
    data = json.loads(receipt.read_text(encoding="utf-8"))
    after = data.get("gc_after", {})
    ok = bool(data.get("reset", {}).get("ok")) and after.get("CP_STAT") == 0 and after.get("RLC_CNTL") == 0
    if not ok:
        raise CycleError(f"MODE2 reset did not quiesce the GPU: {json.dumps(after)}")
    print(f"      reset OK  CP_STAT=0 RLC_CNTL=0  ({receipt.name})")
    return {"receipt": str(receipt), "index": index}


def stage(args, pins: dict, facts: dict, worktree: Path, vm: Path) -> str:
    print("[3/5] stage candidate")
    suffix = f"-attempt-{args.attempt}" if args.attempt else ""
    lilu = pins["lilu"]
    command = [sys.executable, "-B", "tools/stage-candidate.py", "--execute",
               "--candidate-version", f"1.0.{args.candidate}", "--card-id", args.card,
               "--expected-commit", facts["commit"],
               "--expected-boot-id", facts["boot_id"],
               "--expected-card-sha256", facts["card_sha256"],
               "--expected-identities-sha256", facts["identities_sha256"],
               "--image-id", pins["image_id"],
               "--lilu-bundle", str(vm / lilu["bundle"]),
               "--expected-lilu-executable-sha256", lilu["executable_sha256"],
               "--expected-lilu-info-sha256", lilu["info_sha256"],
               "--expected-lilu-build-manifest-sha256", lilu["build_manifest_sha256"]]
    if args.attempt:
        command[6:6] = ["--attempt", args.attempt]
    run_step("stage-candidate", command, cwd=worktree,
             log=vm / "run" / f"candidate-{args.candidate}{suffix}-stage.log")
    run_id_file = vm / "run" / f"candidate{args.candidate}{suffix}-qualification-run-id.txt"
    if not run_id_file.is_file():
        raise CycleError(f"staging produced no run id at {run_id_file}")
    run_id = run_id_file.read_text(encoding="utf-8").strip()
    print(f"      staged, run id {run_id}")
    return run_id


def prepare_and_run(args, facts: dict, worktree: Path, vm: Path, run_id: str) -> dict:
    suffix = f"-attempt-{args.attempt}" if args.attempt else ""
    manifest = vm / "run" / f"candidate-{args.candidate}{suffix}-manifest.json"
    results = vm / "run" / f"candidate-{args.candidate}{suffix}-results"
    print("[4/5] prepare")
    command = [sys.executable, "-B", "tools/experiment.py", "prepare", "--vm-dir", str(vm),
               "--spec", f"experiments/{args.card}.json", "--run-id", run_id,
               "--output", str(manifest)]
    if args.attempt:
        command += ["--attempt", args.attempt]
    run_step("experiment prepare", command, cwd=worktree,
             log=vm / "run" / f"candidate-{args.candidate}{suffix}-prepare.log")
    print(f"      manifest {manifest.name}")

    print("[5/5] run  (this exposes the GPU)")
    runner = [sys.executable, "-B", "tools/run-gpu-test.py", "--vm-dir", str(vm),
              "--manifest", str(manifest), "--output", str(results),
              "--worktree", str(worktree), "--status-path", str(worktree / "status.md")]
    result = run_step("gpu run", runner, cwd=worktree, allow_failure=True,
                      log=vm / "run" / f"candidate-{args.candidate}{suffix}-run.log")
    try:
        verdict = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        verdict = {"verdict": "UNKNOWN", "returncode": result.returncode}
    return {"manifest": str(manifest), "results": str(results), "verdict": verdict}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate", required=True, help="candidate number, e.g. 231")
    parser.add_argument("--card", required=True, help="experiment card id, e.g. metal-079")
    parser.add_argument("--attempt", help="isolated retry namespace")
    parser.add_argument("--pins", default=str(ROOT / "experiments" / "pins.json"))
    parser.add_argument("--worktree", help="candidate worktree (default: VM run/worktrees/candidate-N)")
    parser.add_argument("--skip-tests", action="store_true", help="skip the host regression suite")
    parser.add_argument("--allow-dirty", action="store_true", help="permit an uncommitted worktree")
    parser.add_argument("--dry-run", action="store_true", help="preflight only; do not touch the GPU")
    args = parser.parse_args()

    try:
        pins = load_pins(Path(args.pins))
        vm = Path(pins["vm_dir"]).resolve()
        worktree = Path(args.worktree).resolve() if args.worktree else \
            vm / "run" / "worktrees" / f"candidate-{args.candidate}"
        facts = preflight(args, pins, worktree, vm)

        if args.dry_run:
            print("\n-- dry run: stopping before the MODE2 reset; the GPU was not touched --")
            print(json.dumps({"preflight": facts, "next_reset": next_reset_index(vm)}, indent=2))
            return 0

        reset = mode2_reset(worktree, vm, next_reset_index(vm))
        run_id = stage(args, pins, facts, worktree, vm)
        outcome = prepare_and_run(args, facts, worktree, vm, run_id)
    except CycleError as error:
        print(f"\nCYCLE ABORTED: {error}", file=sys.stderr)
        return 2

    summary = {"candidate": f"1.0.{args.candidate}", "card": args.card,
               "attempt": args.attempt, "commit": facts["commit"],
               "boot_id": facts["boot_id"], "reset": reset, **outcome}
    print("\n" + json.dumps(summary, indent=2))
    print("\nNext: review the verdict above, then record the run in status.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
