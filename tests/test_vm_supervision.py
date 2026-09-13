"""Exercise supervision commands in subprocesses without Docker or systemd access."""
from datetime import datetime, timedelta, timezone
import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import signal
import shutil
import time
import unittest
import fcntl
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1] / "tools/vm-supervision.py"
CID = "a" * 64

FIXTURE_COMMAND = r'''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
root = pathlib.Path(os.environ["SUPERVISION_FIXTURE"])
command, args = pathlib.Path(sys.argv[0]).name, sys.argv[1:]
with (root / "calls.jsonl").open("a") as output:
    output.write(json.dumps([command, args]) + "\n")
state = json.loads((root / "fixture.json").read_text())
failure = state.get("failure", "")
if command == "docker":
    if args[0] == "ps":
        if '{{.Names}}' in args:
            print(state.get('active_name', ''))
        else:
            print(state["cid"] if state.get("running", True) else "")
    elif args[0] == "inspect":
        if state.get('no_identity'):
            sys.exit(1)
        if args[args.index("--format") + 1] == "{{.Id}}":
            print(state["cid"])
            sys.exit(0)
        obj = {"Id": state["cid"], "Running": state.get("running", True),
               "StartedAt": state["started"]}
        obj["Status"] = "running" if obj["Running"] else "exited"
        if state.get("created_reads", 0):
            obj.update(Running=False, Status="created")
            state["created_reads"] -= 1
            (root / "fixture.json").write_text(json.dumps(state))
        print(json.dumps(obj))
    elif args[0] == "exec":
        if state.get("shutdown_error"):
            sys.exit(1)
        if state.get("shutdown_stops"):
            state["running"] = False
            (root / "fixture.json").write_text(json.dumps(state))
    elif args[0] in ("rename", "cp"):
        pass
    elif args[0] in ("stop", "kill"):
        if failure == "stop" or (failure == "absent" and not state.get("running", True)):
            sys.exit(1)
        state["running"] = False
        (root / "fixture.json").write_text(json.dumps(state))
    else:
        sys.exit(90)
elif command == "systemd-run":
    if failure == "arm" and any(a.startswith("--on-calendar=") for a in args):
        sys.exit(1)
    unit = next(a.split("=", 1)[1] for a in args if a.startswith("--unit="))
    state.setdefault("units", {})[unit] = args
    ready = next((a.split("=", 2)[2] for a in args if a.startswith("--setenv=VM_SERIAL_READY=")), None)
    channel = next((a.split("=", 2)[2] for a in args
                    if a.startswith("--setenv=VM_SERIAL_CHANNEL=")), None)
    if ready and failure not in ("not-ready", "not-ready-" + str(channel)):
        pathlib.Path(ready).write_text(
            state["cid"] if channel is None else state["cid"] + " " + channel)
    (root / "fixture.json").write_text(json.dumps(state))
    if unit.startswith("rgpu-launch-"):
        out = (root / "managed-launch.log").open("w")
        child = subprocess.Popen(args[args.index("--") + 1:], stdout=out, stderr=out,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
        (root / "managed.pid").write_text(str(child.pid))
elif command == "systemctl":
    unit = next(a for a in args if a.endswith((".timer", ".service")))
    if args[1] == "stop":
        sys.exit(0)
    base = unit.rsplit(".", 1)[0]
    saved = state.get("units", {}).get(base)
    if not saved:
        print("LoadState=not-found\nActiveState=inactive")
    elif unit.endswith(".timer"):
        print("LoadState=loaded\nActiveState=active\nSubState=waiting")
        print("Unit=" + ("unrelated.service" if failure == "target" else base + ".service"))
        print("NextElapseUSecRealtime=" + ("0" if failure == "deadline" else state["next"]))
    elif "serial" in base or "critical" in base or "launch" in base:
        active = "failed" if failure in ("serial", "critical") and failure in base else "active"
        print("LoadState=loaded\nActiveState=" + active + "\nSubState=running\nMainPID=123")
    else:
        print("LoadState=loaded\nActiveState=inactive")
        executable = saved[saved.index("--") + 1:]
        print("ExecStart={ argv[]=" + " ".join(executable) + " ; }")
elif command == "busctl":
    rows = [[state.get("inhibitor_what", "sleep:idle"), "fixture", "reason",
             state.get("inhibitor_mode", "block"), 1000, 123]] if state.get(
        "logind_inhibited") else []
    if state.get("malformed_inhibitor"):
        rows.append(["broken"])
    print(json.dumps({"type":"a(ssssuu)", "data":[rows]}))
else:
    sys.exit(91)
'''


class SupervisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vm = Path(self.temp.name)
        (self.vm / "run").mkdir()
        (self.vm / "sercat.py").write_text("raise SystemExit(0)\n")
        binaries = self.vm / "bin"
        binaries.mkdir()
        for command in ("docker", "systemd-run", "systemctl", "systemd-inhibit", "busctl"):
            path = binaries / command
            path.write_text(FIXTURE_COMMAND)
            path.chmod(0o700)
        self.env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"],
                        SUPERVISION_FIXTURE=str(self.vm), PYTHONDONTWRITEBYTECODE="1")
        self.started = datetime.now(timezone.utc) - timedelta(seconds=60)
        self.fixture = {"cid": CID, "started": self.started.isoformat(),
                        "next": (self.started + timedelta(seconds=180)).strftime(
                            "%a %Y-%m-%d %H:%M:%S UTC")}
        self.save()

    def save(self):
        (self.vm / "fixture.json").write_text(json.dumps(self.fixture))

    def run_tool(self, *args):
        return subprocess.run([sys.executable, "-B", str(TOOL), *args], env=self.env,
                              text=True, capture_output=True, timeout=10)

    def arm(self, seconds="180", cid=CID, critical=False):
        args = ["arm", "--vm-dir", str(self.vm), "--cid", cid,
                "--max-seconds", seconds]
        if critical:
            args.append("--critical-serial")
        return self.run_tool(*args)

    def calls(self):
        path = self.vm / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def stopped(self):
        return [args[-1] for cmd, args in self.calls() if cmd == "docker" and args[0] == "stop"]

    def test_staging_lock_refuses_direct_supervisor_start(self):
        with (self.vm / 'run/redeploy.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_tool('start', '--vm-dir', str(self.vm), '--max-seconds', '180')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(command == 'systemd-run' for command, _ in self.calls()))

    def test_pending_container_refuses_second_direct_start(self):
        self.fixture['active_name'] = 'rgpu-launch-pending'
        self.save()
        result = self.run_tool('start', '--vm-dir', str(self.vm), '--max-seconds', '180')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(command == 'systemd-run' for command, _ in self.calls()))

    def test_unconfirmed_service_stop_does_not_release_pending_launch(self):
        spec = importlib.util.spec_from_file_location('supervisor', TOOL)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        pending = self.vm / 'run/launch-pending'; pending.mkdir()
        def unavailable(args, **kwargs):
            if args[:2] == ['docker', 'ps']: return ''
            raise RuntimeError('service may have accepted launch; transport unavailable')
        with patch.object(module, 'binary', side_effect=lambda name: name), \
             patch.object(module, 'run', side_effect=unavailable):
            with self.assertRaises(RuntimeError): module.start_locked(self.vm, 180, [])
        self.assertEqual(len(list(pending.iterdir())), 1)

    def test_caller_death_before_container_identity_keeps_launch_reserved(self):
        self.fixture['no_identity'] = True
        self.save()
        script = self.vm / 'macos-vm.sh'
        script.write_text('#!/bin/sh\nexec sleep 30\n'); script.chmod(0o700)
        parent = subprocess.Popen([sys.executable, '-B', str(TOOL), 'start',
                                   '--vm-dir', str(self.vm), '--max-seconds', '180'],
                                  env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def cleanup_parent():
            if parent.poll() is None: parent.kill()
            parent.wait()
            pid_path = self.vm / 'managed.pid'
            if pid_path.exists():
                try: os.kill(int(pid_path.read_text()), signal.SIGTERM)
                except ProcessLookupError: pass
        self.addCleanup(cleanup_parent)
        until = time.monotonic()+3
        while not (self.vm / 'managed.pid').exists() and time.monotonic() < until:
            time.sleep(0.02)
        self.assertTrue((self.vm / 'managed.pid').exists())
        parent.kill(); parent.wait()
        before = len([c for c in self.calls() if c[0] == 'systemd-run'])
        second = self.run_tool('start', '--vm-dir', str(self.vm), '--max-seconds', '180')
        self.assertNotEqual(second.returncode, 0)
        self.assertIn('pending', second.stderr)
        self.assertEqual(len([c for c in self.calls() if c[0] == 'systemd-run']), before)

    def test_arms_absolute_deadline_and_preserves_exact_container_target(self):
        result = self.arm()
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state["deadline_epoch"], int(self.started.timestamp() + 180))
        timers = [args for cmd, args in self.calls() if cmd == "systemd-run"
                  and any(a.startswith("--on-calendar=") for a in args)]
        self.assertEqual(len(timers), 1)
        command = timers[0][timers[0].index("--") + 1:]
        self.assertEqual(command[-4:], ["stop", "--time", "0", CID])
        self.assertIn("--user", timers[0])
        self.assertIn("--property=RuntimeMaxSec=15s", timers[0])
        self.assertIn("--property=TimeoutStopSec=5s", timers[0])
        self.assertIn("--setenv=DOCKER_HOST=", timers[0])
        serial = [args for cmd, args in self.calls() if cmd == "systemd-run"
                  and any(a.startswith("--unit=rgpu-serial-") for a in args)][0]
        self.assertTrue(any("systemd-inhibit" in a for a in serial))
        self.assertTrue(any(a.startswith("--property=ExecStopPost=") and a.endswith(CID)
                            for a in serial))
        self.assertEqual(Path(state["serial_ready"]).read_text(), CID)
        self.assertFalse(self.stopped())
        self.assertTrue(any(cmd == "systemctl" and state["timer_unit"] in args
                            for cmd, args in self.calls()))
        self.assertTrue(any(cmd == "systemctl" and state["serial_unit"] in args
                            for cmd, args in self.calls()))

    def test_headless_collector_reuses_verified_logind_block_inhibitor(self):
        self.env["GENERIC_GRAPHICS"] = "off"
        self.fixture["logind_inhibited"] = True; self.save()
        result = self.arm()
        self.assertEqual(result.returncode, 0, result.stderr)
        serial = [args for cmd,args in self.calls() if cmd == 'systemd-run'
                  and any(a.startswith('--unit=rgpu-serial-') for a in args)][0]
        self.assertNotIn(str(self.vm/'bin/systemd-inhibit'), serial)
        self.assertIn(str(self.vm/'sercat.py'), serial)

    def test_headless_collector_accepts_idle_only_block_inhibitor(self):
        self.env["GENERIC_GRAPHICS"] = "off"
        self.fixture.update(logind_inhibited=True, inhibitor_what="idle"); self.save()
        result = self.arm()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_headless_collector_rejects_sleep_only_or_delay_inhibitor(self):
        self.env["GENERIC_GRAPHICS"] = "off"
        for what, mode in (("sleep", "block"), ("idle", "delay")):
            with self.subTest(what=what, mode=mode):
                self.fixture.update(logind_inhibited=True, inhibitor_what=what,
                                    inhibitor_mode=mode); self.save()
                result = self.arm()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('block inhibitor', result.stderr)

    def test_headless_collector_refuses_without_logind_block_inhibitor(self):
        self.env["GENERIC_GRAPHICS"] = "off"
        self.fixture["logind_inhibited"] = False; self.save()
        result = self.arm()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('block inhibitor', result.stderr)

    def test_headless_collector_rejects_malformed_trailing_inhibitor(self):
        self.env["GENERIC_GRAPHICS"] = "off"
        self.fixture.update(logind_inhibited=True, malformed_inhibitor=True); self.save()
        result = self.arm()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('block inhibitor', result.stderr)

    def test_verify_refuses_lost_external_inhibitor(self):
        self.env["GENERIC_GRAPHICS"] = "off"
        self.fixture["logind_inhibited"] = True; self.save()
        result = self.arm(); self.assertEqual(result.returncode, 0, result.stderr)
        (self.vm/'run/supervision.json').write_text(result.stdout)
        state = self.fixture; state["logind_inhibited"] = False; self.save()
        checked = self.run_tool('verify', '--state', str(self.vm/'run/supervision.json'))
        self.assertNotEqual(checked.returncode, 0)
        self.assertIn('inhibitor was lost', checked.stderr)

    def test_dedicated_transport_arms_two_channel_bound_collectors(self):
        result = self.arm(critical=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(Path(state["serial_ready"]).read_text(), CID + " console")
        self.assertEqual(Path(state["critical_ready"]).read_text(), CID + " critical")
        collectors = [args for cmd, args in self.calls() if cmd == "systemd-run"
                      and any(a.startswith(("--unit=rgpu-serial-", "--unit=rgpu-critical-"))
                              for a in args)]
        self.assertEqual(len(collectors), 2)
        self.assertTrue(any("VM_SERIAL_SOCKET=" + str(self.vm / "run/critical.sock") in a
                            for a in collectors[1]))
        self.assertTrue(any("VM_SERIAL_OUTPUT=" + str(self.vm / "run/critical.log") in a
                            for a in collectors[1]))

    def test_dedicated_transport_failure_stops_exact_cid(self):
        self.fixture["failure"] = "critical"
        self.save()
        result = self.arm(critical=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.stopped(), [CID])

    def shutdown(self, grace="1"):
        armed = self.arm()
        self.assertEqual(armed.returncode, 0, armed.stderr)
        state_file = self.vm / "run/supervision.json"
        state_file.write_text(armed.stdout)
        return self.run_tool("shutdown", "--state", str(state_file), "--grace-seconds", grace)

    def test_shutdown_observes_guest_exit_without_changing_deadline(self):
        self.fixture["shutdown_stops"] = True
        self.save()
        result = self.shutdown()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["outcome"], "exited-after-request")
        self.assertFalse(self.stopped())
        requests = [args for cmd, args in self.calls() if cmd == "docker" and args[0] == "exec"]
        self.assertEqual(requests[0][1], CID)
        self.assertFalse(any(cmd == "systemctl" and "stop" in args for cmd, args in self.calls()))
        timers = [args for cmd, args in self.calls() if cmd == "systemd-run"
                  and any(a.startswith("--on-calendar=") for a in args)]
        self.assertEqual(len(timers), 1)

    def test_shutdown_forces_exact_target_if_guest_ignores_request(self):
        result = self.shutdown()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["outcome"], "forced")
        self.assertEqual(self.stopped(), [CID])

    def test_shutdown_transport_failure_forces_exact_target(self):
        self.fixture["shutdown_error"] = True
        self.save()
        result = self.shutdown()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["outcome"], "forced")
        self.assertEqual(self.stopped(), [CID])

    def test_shutdown_stops_exact_cid_when_inhibitor_and_collector_are_missing(self):
        self.env["GENERIC_GRAPHICS"] = "off"
        self.fixture["logind_inhibited"] = True; self.save()
        armed = self.arm()
        self.assertEqual(armed.returncode, 0, armed.stderr)
        state = json.loads(armed.stdout)
        state["external_inhibitor"] = True
        (self.vm / "run" / "supervision.json").write_text(json.dumps(state))
        self.fixture["logind_inhibited"] = False; self.save()
        Path(state["serial_ready"]).unlink()
        result = self.run_tool("shutdown", "--state", str(self.vm / "run" / "supervision.json"),
                               "--grace-seconds", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["outcome"], "forced")
        self.assertEqual(self.stopped(), [CID])

    def test_shutdown_stops_after_deadline_without_rearming_or_extending_cap(self):
        armed = self.arm()
        self.assertEqual(armed.returncode, 0, armed.stderr)
        state = json.loads(armed.stdout)
        state["deadline_epoch"] = int(time.time()) - 1
        (self.vm / "run" / "supervision.json").write_text(json.dumps(state))
        result = self.run_tool("shutdown", "--state", str(self.vm / "run" / "supervision.json"),
                               "--grace-seconds", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["outcome"], "forced")
        self.assertEqual(self.stopped(), [CID])
        timers = [args for cmd, args in self.calls() if cmd == "systemd-run"
                  and any(a.startswith("--on-calendar=") for a in args)]
        self.assertEqual(len(timers), 1)
        self.assertEqual(json.loads((self.vm / "run" / "supervision.json").read_text())[
            "deadline_epoch"], state["deadline_epoch"])

    def test_shutdown_refuses_restarted_container_without_request_or_stop(self):
        armed = self.arm()
        state_file = self.vm / "run/supervision.json"
        state_file.write_text(armed.stdout)
        self.fixture = json.loads((self.vm / "fixture.json").read_text())
        self.fixture["started"] = (self.started + timedelta(seconds=1)).isoformat()
        self.save()
        result = self.run_tool("shutdown", "--state", str(state_file))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.stopped())
        self.assertFalse(any(cmd == "docker" and args[0] == "exec" for cmd, args in self.calls()))

    def test_elapsed_cap_stops_without_starting_a_fresh_timer(self):
        self.fixture["started"] = (self.started - timedelta(seconds=300)).isoformat()
        self.save()
        result = self.arm()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.stopped(), [CID])
        self.assertFalse(any(cmd == "systemd-run" for cmd, _ in self.calls()))

    def test_failed_arm_and_failed_positive_verification_stop_only_our_cid(self):
        for failure in ("arm", "target", "deadline", "serial"):
            with self.subTest(failure=failure):
                self.fixture["failure"] = failure
                self.save()
                (self.vm / "calls.jsonl").write_text("")
                result = self.arm()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.stopped(), [CID])

    def test_bad_started_at_stops_identified_container(self):
        self.fixture["started"] = "not a timestamp"
        self.save()
        result = self.arm()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.stopped(), [CID])

    def test_mismatched_inspect_identity_never_targets_returned_other_container(self):
        self.fixture["cid"] = "b" * 64
        self.save()
        self.assertNotEqual(self.arm().returncode, 0)
        self.assertEqual(self.stopped(), [CID])

    def test_rejects_short_or_injected_ids_before_running_commands(self):
        for cid in ("abc123", "macos-sequoia", CID + ";true"):
            self.assertNotEqual(self.arm(cid=cid).returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_verify_detects_serial_death_after_arm_and_stops_own_container(self):
        result = self.arm()
        self.assertEqual(result.returncode, 0, result.stderr)
        state_file = self.vm / "run/supervision.json"
        state_file.write_text(result.stdout)
        self.fixture = json.loads((self.vm / "fixture.json").read_text())
        self.fixture["failure"] = "serial"
        self.save()
        checked = self.run_tool("verify", "--state", str(state_file))
        self.assertNotEqual(checked.returncode, 0)
        self.assertEqual(self.stopped(), [CID])

    def test_cleanup_of_already_absent_container_is_success(self):
        self.fixture.update(running=False, failure="absent")
        self.save()
        result = self.arm()
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("CRITICAL", result.stderr)
        self.assertTrue(any(cmd == "docker" and args[0] == "ps" for cmd, args in self.calls()))

    def test_failed_stop_with_still_running_container_is_critical(self):
        self.fixture.update(failure="stop", started="invalid")
        self.save()
        result = self.arm()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CRITICAL", result.stderr)

    def test_launch_waits_for_running_then_arms_before_bootstrap_and_cleans_up(self):
        self.fixture["created_reads"] = 2
        self.save()
        script = self.vm / "macos-vm.sh"
        script.write_text("#!/bin/sh\nexec sleep 30\n")
        script.chmod(0o700)
        name = "rgpu-launch-" + "b" * 32
        ready = self.vm / "run" / (name + ".json")
        process = subprocess.Popen([sys.executable, "-B", str(TOOL), "launch",
                                    "--vm-dir", str(self.vm), "--name", name,
                                    "--max-seconds", "180"], env=self.env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        until = time.monotonic() + 5
        while not ready.is_file() and process.poll() is None and time.monotonic() < until:
            time.sleep(0.02)
        if process.poll() is not None:
            output, error = process.communicate()
            self.fail("supervised launch did not become ready: " + error)
        self.assertTrue(ready.is_file(), "supervised launch never published readiness")
        calls = self.calls()
        timer = next(i for i, (cmd, args) in enumerate(calls) if cmd == "systemd-run"
                     and any(a.startswith("--on-calendar=") for a in args))
        bootstrap = next(i for i, (cmd, args) in enumerate(calls)
                         if cmd == "docker" and args[0] == "cp")
        self.assertLess(timer, bootstrap)
        self.assertEqual(json.loads(ready.read_text())["cid"], CID)
        process.send_signal(signal.SIGTERM)
        process.communicate(timeout=5)
        self.assertIn(CID, self.stopped())

    def test_start_returns_with_separately_owned_launcher_and_preinstalled_cap(self):
        script = self.vm / "macos-vm.sh"
        script.write_text("#!/bin/sh\n[ -z \"$GPU\" ] || exit 22\nexec sleep 30\n")
        script.chmod(0o700)
        self.env["GPU"] = "must-not-be-inherited"
        result = self.run_tool("start", "--vm-dir", str(self.vm), "--max-seconds", "180")
        pid_file = self.vm / "managed.pid"
        if pid_file.exists():
            pid = int(pid_file.read_text())
            self.addCleanup(lambda: os.kill(pid, signal.SIGTERM))
        self.assertEqual(result.returncode, 0, result.stderr +
                         (self.vm / "managed-launch.log").read_text())
        os.kill(pid, 0)  # Managed lifetime survives the start command exiting.
        state = json.loads(result.stdout)
        self.assertTrue(state["launch_unit"].startswith("rgpu-launch-"))
        commands = [args for cmd, args in self.calls() if cmd == "systemd-run"]
        self.assertIn("--property=RuntimeMaxSec=180s", commands[0])
        self.assertTrue(any(a.startswith("--property=ExecStopPost=") and " cleanup " in a
                            for a in commands[0]))
        self.assertEqual(json.loads((self.vm / "run/supervision.json").read_text())["cid"], CID)

    def test_graphics_policy_is_explicitly_forwarded_without_extra(self):
        self.env["GENERIC_GRAPHICS"] = "off"
        self.fixture["logind_inhibited"] = True
        self.save()
        script = self.vm / "macos-vm.sh"
        script.write_text("#!/bin/sh\nexec sleep 30\n"); script.chmod(0o700)
        result = self.run_tool("start", "--vm-dir", str(self.vm), "--max-seconds", "180")
        self.assertEqual(result.returncode, 0, result.stderr)
        launch = next(args for cmd, args in self.calls() if cmd == "systemd-run"
                      and any(a.startswith("--unit=rgpu-launch-") for a in args))
        self.assertIn("--setenv=GENERIC_GRAPHICS=off", launch)
        self.assertIn("--setenv=EXTRA=", launch)

    def test_cleanup_without_identity_targets_only_unique_launch_name(self):
        name = "rgpu-launch-" + "b" * 32
        result = self.run_tool("cleanup", "--vm-dir", str(self.vm), "--name", name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stopped(), [name])
        self.assertNotEqual(self.run_tool("cleanup", "--vm-dir", str(self.vm),
                                         "--name", "macos-sequoia").returncode, 0)
        self.assertEqual(self.stopped(), [name])

    def test_partial_identity_file_falls_back_only_to_owned_unique_name(self):
        name = "rgpu-launch-" + "b" * 32
        (self.vm / "run" / (name + ".cid")).write_text(CID[:7])
        result = self.run_tool("cleanup", "--vm-dir", str(self.vm), "--name", name)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.stopped(), [name])

    def test_serial_marker_requires_connection_and_log_open(self):
        shutil.copy(TOOL.with_name("sercat.py"), self.vm / "sercat.py")
        path = self.vm / "run/serial.sock"
        ready = self.vm / "run/real-serial.ready"
        connect_allowed = self.vm / "connect-allowed"
        wrapper = self.vm / "serial-fixture.py"
        wrapper.write_text(
            "import pathlib, runpy, socket, sys\n"
            "class SocketFixture:\n"
            "    sent = False\n"
            "    def connect(self, address):\n"
            "        if not pathlib.Path(sys.argv[1]).exists(): raise ConnectionRefusedError()\n"
            "    def settimeout(self, seconds): pass\n"
            "    def recv(self, size):\n"
            "        if self.sent: return b''\n"
            "        self.sent = True\n"
            "        return b'serial survives caller exit\\n'\n"
            "socket.socket = lambda *args: SocketFixture()\n"
            "runpy.run_path(sys.argv[2], run_name='__main__')\n")
        serial_env = dict(self.env, VM_SERIAL=str(path), VM_SERIAL_READY=str(ready), VM_SERIAL_CID=CID)
        capture = subprocess.Popen([sys.executable, "-B", str(wrapper),
                                    str(connect_allowed), str(self.vm / "sercat.py")],
                                   env=serial_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def terminate_capture():
            if capture.poll() is None:
                capture.kill()
            capture.communicate()
        self.addCleanup(terminate_capture)
        time.sleep(0.1)
        self.assertFalse(ready.exists())
        connect_allowed.touch()
        output, error = capture.communicate(timeout=3)
        self.assertEqual(capture.returncode, 0, error)
        self.assertEqual(ready.read_text(), CID)
        self.assertEqual((self.vm / "run/serial.log").read_bytes(), b"serial survives caller exit\n")

    def test_timeout_error_does_not_expose_forwarded_environment(self):
        spec = importlib.util.spec_from_file_location("vm_supervision_under_test", TOOL)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaises(Exception) as raised:
            module.run([sys.executable, "-c", "import time; time.sleep(1)",
                        "--setenv=DOCKER_HOST=private-endpoint"], timeout=0.02)
        self.assertNotIn("private-endpoint", str(raised.exception))
        self.assertIn("timed out", str(raised.exception))

    def test_gpueless_capture_has_supervised_serial_without_exposure_timer(self):
        result = self.arm(seconds="0")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertIsNone(state["timer_unit"])
        self.assertIsNone(state["deadline_epoch"])
        self.assertFalse(any(any(a.startswith("--on-calendar=") for a in args)
                             for cmd, args in self.calls() if cmd == "systemd-run"))


if __name__ == "__main__":
    unittest.main()
