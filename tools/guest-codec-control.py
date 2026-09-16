#!/usr/bin/env python3
"""Issue the bounded VideoToolbox decode control workload during an interactive hold.

Runs only against a supervised experiment that has written interactive-ready.json.
Compiles tests/video_decode_control_probe.m inside the guest through the gx relay
with the same permit protocol metal-test.py uses, runs it once, and records the
command and output next to the run's results. Never launches a VM.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


def load_metal_test():
    import importlib.util
    spec = importlib.util.spec_from_file_location("metal_test", ROOT / "tools/metal-test.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def registry_id_from_probe(results):
    text = (results / "probe.json").read_text()
    # probe.json embeds the guest result as an escaped JSON string.
    ids = sorted({int(x) for x in re.findall(r'registry_id\\?"\s*:\s*(\d+)', text)})
    if len(ids) != 1:
        raise SystemExit(f"expected exactly one registry_id in probe.json, found {ids}")
    return ids[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vm-dir", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True, help="run results directory")
    parser.add_argument("--codec", choices=("h264", "hevc"), default="h264")
    parser.add_argument("--mode", choices=("hw", "sw"), default="hw")
    parser.add_argument("--registry-id", type=int, help="override the accelerator registry id")
    parser.add_argument("--source", default="tests/video_decode_control_probe.m",
                        help="probe source relative to the repository (same CLI: codec hw|sw registryID)")
    parser.add_argument("--args", default="{codec} {mode} {registry}",
                        help="probe argument template; {codec} {mode} {registry} {dir} are substituted")
    parser.add_argument("--post-log", metavar="PREDICATE",
                        help="after the probe, append the guest unified log of the last 3 minutes "
                             "matching this predicate (bounded, read-only)")
    parser.add_argument("--tag", help="results file prefix (default: source stem, mode, codec)")
    args = parser.parse_args()
    vm = args.vm_dir.resolve()
    results = args.results.resolve()
    ready = json.loads((results / "interactive-ready.json").read_text())
    if time.time() > ready["deadline_epoch"] - 150:
        raise SystemExit("interactive hold deadline too close; not issuing the workload")
    if (results / "stop-requested").exists():
        raise SystemExit("stop already requested for this run")
    registry = args.registry_id or registry_id_from_probe(results)
    source = (ROOT / args.source).read_bytes()
    nonce = uuid.uuid4().hex
    guest_dir = f"/var/tmp/rgpu-codec-{nonce}"
    payload = base64.b64encode(source).decode("ascii")
    action = (f"permit=$(/usr/bin/curl -fsS --max-time 3 "
              f"{shlex.quote(f'http://10.0.2.2:8889/metal-permit-{nonce}')}) && "
              f"test \"$permit\" = {nonce} && mkdir -p {guest_dir} && "
              f"printf %s {payload} | /usr/bin/base64 -D > {guest_dir}/probe.m && "
              f"/usr/bin/xcrun clang -fobjc-arc -O2 {guest_dir}/probe.m -framework Foundation "
              f"-framework VideoToolbox -framework CoreMedia -framework CoreVideo -framework IOKit -framework Metal "
              f"-o {guest_dir}/probe && {guest_dir}/probe "
              + shlex.join(args.args.format(codec=args.codec, mode=args.mode, registry=registry,
                                            dir=guest_dir).split()))
    if args.post_log:
        action = (f"{action}; probe_result=$?; /usr/bin/log show --last 3m --style compact "
                  f"--predicate {shlex.quote(args.post_log)} | /usr/bin/head -n 400; "
                  f"( exit $probe_result )")
    command = f"( {action}; result=$?; printf \"\\nRGPU_EXIT {nonce} %s\\n\" \"$result\" )"
    tag = args.tag or f"{Path(args.source).stem.replace('_', '-')}-{args.mode}-{args.codec}"
    (results / f"{tag}-command.json").write_text(json.dumps(
        {"nonce": nonce, "command": command, "registry_id": registry,
         "experiment_run_id": ready["run_id"], "codec": args.codec,
         "source": args.source}, indent=2) + "\n")
    metal = load_metal_test()
    env = dict(os.environ, GX_TIMEOUT="200")
    proc = metal.run_guest_command(vm, command, nonce, env, timeout=220, execution_grace=0)
    output = proc.stdout
    (results / f"{tag}-output.txt").write_text(output)
    print(output, end="" if output.endswith("\n") else "\n")
    exits = re.findall(r"^RGPU_EXIT " + nonce + r" (\d+)$", output, re.M)
    print(f"guest exit: {exits}", file=sys.stderr)
    return 0 if exits == ["0"] else 1


if __name__ == "__main__":
    sys.exit(main())
