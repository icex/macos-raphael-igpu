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
import stat
import uuid
import subprocess
import sys
import time
import fcntl
import hashlib
import importlib.util

CID_PATTERN = re.compile(r"[0-9a-f]{64}")
DOCKER_ENV = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_TLS_VERIFY",
              "DOCKER_CERT_PATH")


class CommandTimeout(RuntimeError):
    pass


class CommandFailure(RuntimeError):
    def __init__(self,message,returncode):
        self.returncode=returncode
        super().__init__(message)


class ManagedStopUnconfirmed(RuntimeError):
    pass


class PreExposureFailure(RuntimeError):
    """A failure proven to precede persistent reservation and systemd."""
    def __init__(self, message, evidence):
        super().__init__(message)
        self.evidence = evidence


def logind_block_inhibited():
    try:
        result = subprocess.run(
            [binary("busctl"), "--system", "--json=short", "call",
             "org.freedesktop.login1", "/org/freedesktop/login1",
             "org.freedesktop.login1.Manager", "ListInhibitors"],
            text=True, capture_output=True, timeout=15, check=False)
        if result.returncode:
            return False
        payload = json.loads(result.stdout)
        if (payload.get("type") != "a(ssssuu)" or type(payload.get("data")) is not list or
                len(payload["data"]) != 1 or type(payload["data"][0]) is not list):
            return False
        matching = False
        for fields in payload["data"][0]:
            if (type(fields) is not list or len(fields) != 6 or
                    not all(isinstance(fields[index], str) for index in range(4)) or
                    not all(type(fields[index]) is int and 0 <= fields[index] < 1 << 32
                            for index in (4, 5))):
                return False
            scopes = fields[0].split(":")
            if (fields[3] == "block" and len(scopes) == 2 and
                    set(scopes) == {"sleep", "idle"}):
                matching = True
        return matching
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, AttributeError):
        return False


def full_cid(value):
    if not CID_PATTERN.fullmatch(value):
        raise ValueError("container identity must be a full 64-digit hexadecimal ID")
    return value


def record_preexposure_failure(vm, name, context, phase, error):
    evidence = {
        'schema': 1, 'kind': 'supervised-pre-exposure-failure',
        'launch': name, 'phase': phase, 'exposure_started': False,
        'systemd_invoked': False, 'docker_create_observed': False,
        'boot_id': context.get('boot_id'), 'run_id': context.get('run_id'),
        'source_commit': context.get('source_commit'),
        'manifest_sha256': context.get('manifest_sha256'),
        'error_type': type(error).__name__, 'error': str(error)[:512],
    }
    directory = vm / 'run/pre-exposure-failures'
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name + '.json')
    evidence['path'] = str(path.resolve())
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(evidence, sort_keys=True) + '\n')
    with temporary.open('rb') as stream:
        os.fsync(stream.fileno())
    temporary.replace(path)
    fd = os.open(directory, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return evidence


def canonical_mounts(value):
    """Return an order-independent representation of Docker mount metadata.

    Docker's inspect response may reorder the Mounts list between equivalent
    reads. Preserve and compare every field while removing only that ordering
    artifact; malformed metadata remains non-comparable and is rejected.
    """
    if type(value) is not list or not all(type(mount) is dict for mount in value):
        return None
    try:
        return tuple(sorted(json.dumps(mount, sort_keys=True, separators=(",", ":"))
                           for mount in value))
    except (TypeError, ValueError):
        return None


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
        raise CommandTimeout(f"{Path(args[0]).name} {args[1]} timed out") from None
    if result.returncode:
        # Do not echo command environments or complete Docker inspection output.
        raise CommandFailure(f"{Path(args[0]).name} {args[1]} failed ({result.returncode})",result.returncode)
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


def capture_exit(vm,cid,started_at,deadline,run_id,admission_digest,channel=None):
    """Allow an exited QEMU or a narrowly qualified guest-shutdown overlap.

    Unknown, ordinarily live or unobserved paths retain immediate exact-CID stop.
    No signal is sent during the at-most-two-second natural-container-exit window.
    """
    full_cid(cid)
    began=time.monotonic();until=began+2
    stage='container-inspect'
    result=dict(cid=cid,started_at=started_at,run_id=run_id,deferred=False,
                budget_origin='legacy-hook-completion-only')
    def running():
        remaining=min(.5,until-time.monotonic(),deadline-time.time())
        if remaining<=0:raise RuntimeError('capture exit budget expired')
        selected='{"Id":{{json .Id}},"StartedAt":{{json .State.StartedAt}},"Running":{{json .State.Running}}}'
        info=json.loads(run([binary('docker'),'inspect','--format',selected,cid],timeout=remaining))
        if info['Id']!=cid or info['StartedAt']!=started_at or type(info['Running']) is not bool:
            raise RuntimeError('capture exit container identity changed')
        return info['Running']
    eof=None
    try:
        try:
            if channel is not None:
                stage='clean-eof'
                if channel not in ('console','critical'):raise ValueError('invalid EOF channel')
                path=Path(vm)/'run'/f'capture-eof-{cid}-{channel}.json'
                reset_path=Path(vm)/'run'/f'capture-reset-{cid}-{channel}.json'
                if os.path.lexists(path) and os.path.lexists(reset_path):raise ValueError('conflicting transport observations')
                is_reset=not os.path.lexists(path) and os.path.lexists(reset_path)
                if is_reset:path=reset_path
                fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW)
                try:
                    metadata=os.fstat(fd)
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size>4096:raise ValueError('invalid EOF file')
                    payload=os.read(fd,4097)
                    if len(payload)>4096:raise ValueError('oversized EOF file')
                    eof=json.loads(payload)
                finally:os.close(fd)
                if is_reset:
                    if (eof.get('kind')!='recv-reset' or eof.get('operation')!='recv' or
                        type(eof.get('errno')) is not int or eof['errno']!=104):raise ValueError('invalid reset observation')
                    eof['eof_monotonic']=eof.get('reset_monotonic');eof['eof_epoch']=eof.get('reset_epoch')
                elif eof.get('kind','clean-eof')!='clean-eof':raise ValueError('invalid clean EOF kind')
                expected=dict(schema=1,cid=cid,started_at=started_at,run_id=run_id,
                              admission_sha256=admission_digest,channel=channel)
                if type(eof.get('schema')) is not int or any(eof.get(k)!=v for k,v in expected.items()):raise ValueError('EOF identity mismatch')
                for field in ('eof_monotonic','eof_epoch','published_monotonic'):
                    if type(eof.get(field)) not in (int,float) or not math.isfinite(eof[field]):
                        raise ValueError('invalid EOF timestamp')
                if not (0<eof['eof_monotonic']<=eof['published_monotonic']<=began<eof['eof_monotonic']+2):
                    raise ValueError('stale or future EOF')
                if not 0<=time.time()-eof['eof_epoch']<2:raise ValueError('invalid EOF epoch')
                until=eof['eof_monotonic']+2
                result['transport_end_monotonic']=eof['eof_monotonic'];result['channel']=channel
                result['transport_end_kind']='recv-reset' if is_reset else 'clean-eof'
                result['budget_origin']='transport-observation'
        except Exception as marker_error:
            eof=None;until=began+2
            result['observation_error']=type(marker_error).__name__
            result['budget_origin']='legacy-hook-completion-only'
        if not running():result['outcome']='already-stopped';return result
        budget=min(1,until-time.monotonic(),deadline-time.time())
        if budget<=0:raise RuntimeError('capture exit budget expired')
        stage='docker-exec'
        observed=json.loads(run([binary('docker'),'exec',cid,'python3','-B',
                                '/run/rgpu-tools/libvirt-console-entry.py','inspect-exited']+
                                ([str(eof['eof_monotonic'])] if eof else []),timeout=budget))
        stage='exit-proof'
        if observed.get('exited') is False and observed.get('shutdown_wait') is not True:
            report=observed.get('refusal',{})
            stages={'admission','receipt-read','permit-binding','plan-binding','running-binding',
                    'namespace','original-process','proc-list','proc-scan','shutdown-event'}
            codes={'missing-file','permission-denied','malformed-json','missing-field',
                   'validation-refused','inspection-error','original-pid-present','other-qemu'}
            if report.get('stage') in stages and report.get('code') in codes:
                safe={k:report[k] for k in ('stage','code')}
                for key in ('pid','process_uid','process_euid','errno'):
                    if type(report.get(key)) is int and report[key]>=0:safe[key]=report[key]
                if report.get('state') in tuple('RSDTtZXIPKW')+('unknown',):safe['state']=report['state']
                if report.get('operation') in ('comm','exe'):safe['operation']=report['operation']
                if report.get('completion_reason') in ('initial-state-changed','not-sole-task',
                        'descriptors-present','final-state-changed','incomplete-proc-view'):
                    safe['completion_reason']=report['completion_reason']
                if type(report.get('completion_task_count')) is int and report['completion_task_count']>=0:
                    safe['completion_task_count']=report['completion_task_count']
                task_samples=report.get('completion_tasks')
                if isinstance(task_samples,list) and len(task_samples)<=8:
                    clean=[]
                    for item in task_samples:
                        if not isinstance(item,dict):continue
                        if type(item.get('tid')) is not int or item['tid']<0:continue
                        if item.get('state') not in tuple('RSDTtZXIPKW')+('unknown',):continue
                        sample={'tid':item['tid'],'state':item['state']}
                        if type(item.get('start_ticks')) is int and item['start_ticks']>=0:
                            sample['start_ticks']=item['start_ticks']
                        clean.append(sample)
                    safe['completion_tasks']=clean
                    safe['completion_tasks_truncated']=report.get('completion_tasks_truncated') is True
                # Diagnostics cannot authorize a wait or completion. Retain only
                # bounded typed fields, never arbitrary exception text or paths.
                for key in ('diag_flags','diag_task_count'):
                    v=report.get(key)
                    if type(v) is int and 0<=v<(2**64 if key=='diag_flags' else 65):safe[key]=v
                for key in ('diag_tasks_truncated','diag_budget_exhausted'):
                    if type(report.get(key)) is bool:safe[key]=report[key]
                wchan=report.get('diag_wchan')
                if type(wchan) is str and re.fullmatch(r'(?:0|[A-Za-z_][A-Za-z0-9_.]{0,126})',wchan):safe['diag_wchan']=wchan
                diagnostics=report.get('diag_errors')
                if isinstance(diagnostics,list):
                    safe['diag_errors']=[v for v in diagnostics[:12] if type(v) is str and
                        re.fullmatch(r'(stat|wchan|task|tasks):(permission|missing|budget|oversized|malformed|io|identity-changed)',v)]
                tasks=report.get('diag_tasks')
                if isinstance(tasks,list):
                    safe['diag_tasks']=[]
                    for item in tasks[:8]:
                        if (isinstance(item,dict) and type(item.get('tid')) is int and item['tid']>0 and
                            item.get('state') in tuple('RSDTtZXIPKW') and
                            type(item.get('flags')) is int and 0<=item['flags']<2**64 and
                            type(item.get('start_ticks')) is int and item['start_ticks']>0):
                            safe['diag_tasks'].append({k:item[k] for k in ('tid','state','flags','start_ticks')})
                result['proof_refusal']=safe
            raise RuntimeError('capture exit proof refused')
        waiting=(eof is not None and observed.get('shutdown_wait') is True and
                 observed.get('exited') is False and observed.get('transport_end_monotonic')==eof['eof_monotonic'] and
                 type(observed.get('shutdown_observed_monotonic')) in (int,float) and
                 math.isfinite(observed['shutdown_observed_monotonic']) and
                 0<=eof['eof_monotonic']-observed['shutdown_observed_monotonic']<=2)
        if not ((observed['exited'] is True or waiting) and observed['cid']==cid and
                observed['started_at']==started_at and observed['run_id']==run_id and
                observed['admission_sha256']==admission_digest and
                type(observed['deadline_epoch']) is int and
                time.time()<observed['deadline_epoch']<=deadline):
            raise RuntimeError('capture exit proof mismatch')
        until=min(until,time.monotonic()+observed['deadline_epoch']-time.time())
        result['deferred']=True
        result['completed_original_zombie']=observed.get('completed_zombie') is True
        stage='exit-wait'
        result['shutdown_event_wait']=waiting
        while waiting and time.monotonic()<until and time.time()<deadline:
            time.sleep(min(.05,max(0,until-time.monotonic()),max(0,deadline-time.time())))
            budget=min(.5,until-time.monotonic(),deadline-time.time())
            if budget<=0:break
            try:
                next_observed=json.loads(run([binary('docker'),'exec',cid,'python3','-B',
                    '/run/rgpu-tools/libvirt-console-entry.py','inspect-exited',str(eof['eof_monotonic'])],timeout=budget))
            except CommandFailure as witness_error:
                if witness_error.returncode == 137:
                    result['witness_exit_code']=137
                if not running():
                    # Container lifetime is proven over, but this is deliberately
                    # not a process-completion proof or synthesized terminal.
                    result['outcome']='container-stopped-during-shutdown-wait';return result
                if witness_error.returncode == 137:
                    # PID-namespace teardown can kill docker-exec witnesses before
                    # Docker publishes Running=false. Only this already-bound
                    # shutdown wait admits polling; never renew the EOF/deadline
                    # budget or infer QEMU completion from the killed witness.
                    while time.monotonic()<until and time.time()<deadline:
                        time.sleep(min(.05,max(0,until-time.monotonic()),
                                       max(0,deadline-time.time())))
                        if time.monotonic()>=until or time.time()>=deadline:break
                        if not running():
                            result['outcome']='container-stopped-during-shutdown-wait';return result
                raise
            if next_observed.get('exited') is False and isinstance(next_observed.get('refusal'),dict):
                refusal=next_observed['refusal']
                # Same fixed vocabulary as the initial probe; never exception text.
                result['wait_refusal']={k:refusal[k] for k,allowed in {
                    'stage':('admission','receipt-read','permit-binding','plan-binding','running-binding','namespace','original-process','proc-list','proc-scan','shutdown-event'),
                    'code':('missing-file','permission-denied','malformed-json','missing-field','validation-refused','inspection-error','original-pid-present','other-qemu'),
                    'completion_reason':('initial-state-changed','not-sole-task','descriptors-present','final-state-changed','incomplete-proc-view'),
                    'state':tuple('RSDTtZXIPKW')+('unknown',)}.items() if refusal.get(k) in allowed}
            for key in ('cid','started_at','run_id','admission_sha256','identity','scope','plan_sha256','deadline_epoch'):
                if next_observed.get(key)!=observed.get(key):raise RuntimeError('shutdown wait binding changed')
            if next_observed.get('exited') is True:
                waiting=False
                result['completed_original_zombie']=next_observed.get('completed_zombie') is True
            elif not (next_observed.get('shutdown_wait') is True and
                      next_observed.get('transport_end_monotonic')==eof['eof_monotonic'] and
                      next_observed.get('shutdown_observed_monotonic')==observed['shutdown_observed_monotonic']):
                raise RuntimeError('shutdown wait no longer eligible')
        if waiting:
            result['outcome']='shutdown-wait-expired';return result
        while time.monotonic()<until and time.time()<deadline:
            if not running():result['outcome']='natural-container-exit';return result
            time.sleep(min(.05,max(0,until-time.monotonic())))
        result['outcome']='receipt-grace-expired'
    except Exception as error:
        result['outcome']='immediate-stop';result['error_type']=type(error).__name__
        result['refusal_stage']=stage
        result['refusal_code']=('command-timeout' if isinstance(error,CommandTimeout) else
                                'command-failed' if isinstance(error,CommandFailure) else
                                'malformed-json' if isinstance(error,json.JSONDecodeError) else
                                'refused')
        if isinstance(error,CommandFailure):result['command_exit_code']=error.returncode
    finally:
        try:
            if result.get('outcome') not in ('already-stopped','natural-container-exit','container-stopped-during-shutdown-wait'):
                stop_exact(cid) # Never let evidence IO delay the capture-fatal stop.
        finally:
            # Best-effort separate host observation; never synthesize terminal.json.
            result['elapsed_seconds']=time.monotonic()-began
            try:
                _durable_json(Path(vm)/'run'/f'capture-exit-{cid}-{os.getpid()}.json',result)
            except Exception:pass
    return result


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
    external_inhibitor = state.get("external_inhibitor", False)
    if type(external_inhibitor) is not bool:
        raise RuntimeError("saved inhibitor mode is invalid")
    if external_inhibitor and not logind_block_inhibited():
        raise RuntimeError("existing sleep:idle block inhibitor was lost")
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
    critical_enabled = state.get("critical_enabled", False)
    if type(critical_enabled) is not bool:
        raise RuntimeError("saved critical transport mode is invalid")
    serial_name = f"rgpu-serial-{cid}.service"
    if state["serial_unit"] != serial_name:
        raise RuntimeError("saved serial service does not belong to this container")
    serial = properties(serial_name)
    if (serial.get("LoadState"), serial.get("ActiveState"), serial.get("SubState")) != (
            "loaded", "active", "running") or int(serial.get("MainPID", "0")) <= 0:
        raise RuntimeError("serial capture service is not running")
    expected_serial_ready = cid + " console" if critical_enabled else cid
    if require_ready and Path(state["serial_ready"]).read_text() != expected_serial_ready:
        raise RuntimeError("serial capture has not connected and opened its log")
    if critical_enabled:
        critical_name = f"rgpu-critical-{cid}.service"
        if state.get("critical_unit") != critical_name:
            raise RuntimeError("saved critical service does not belong to this container")
        critical = properties(critical_name)
        if (critical.get("LoadState"), critical.get("ActiveState"),
                critical.get("SubState")) != ("loaded", "active", "running") or int(
                    critical.get("MainPID", "0")) <= 0:
            raise RuntimeError("critical capture service is not running")
        if require_ready and Path(state["critical_ready"]).read_text() != cid + " critical":
            raise RuntimeError("critical capture has not connected and opened its log")
    if maximum and expected_deadline <= time.time():
        raise RuntimeError("exposure deadline elapsed during verification")


# Execute inside the identified container's PID namespace. The socket lives in a
# shared bind mount, so verify its peer is a QEMU process visible in THIS namespace
# before writing. A socket replaced by another container has no visible peer PID.
POWERDOWN = r"""
import os, socket, struct, time
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
    sock.settimeout(2)
    sock.connect('/run/vm/monitor.sock')
    pid, uid, gid = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if pid <= 0 or not os.path.basename(os.readlink('/proc/%d/exe' % pid)).startswith('qemu-system-'):
        raise RuntimeError('monitor peer is not QEMU in this container')
    data = b''
    until = time.monotonic() + 2
    while b'(qemu)' not in data:
        if time.monotonic() >= until or len(data) > 65536:
            raise RuntimeError('monitor prompt unavailable')
        chunk = sock.recv(4096)
        if not chunk:
            raise RuntimeError('monitor disconnected')
        data += chunk
    sock.sendall(b'system_powerdown\n')
"""

# This is deliberately HMP ``quit``, rather than Docker stop/kill or ACPI
# powerdown.  The caller records authorization before docker exec, while this
# script authenticates the monitor peer inside the container's PID namespace.
QUIT = POWERDOWN.replace("system_powerdown", "quit")


def same_start_running(state):
    cid = full_cid(state["cid"])
    selected = '{"Id":{{json .Id}},"StartedAt":{{json .State.StartedAt}},"Running":{{json .State.Running}}}'
    try:
        info = json.loads(run([binary("docker"), "inspect", "--format", selected, cid], timeout=2))
    except RuntimeError:
        active = run([binary("docker"), "ps", "--no-trunc", "--filter", f"id={cid}",
                      "--format", "{{.ID}}"], timeout=2).strip()
        if not active:
            return False
        raise
    if info["Id"] != cid or info["StartedAt"] != state["started_at"]:
        raise RuntimeError("shutdown target identity/start changed; refusing to affect the new session")
    return info["Running"] is True


def shutdown(state, grace=20):
    """Request ACPI powerdown; observe exit or force-stop within the existing cap.

    Exiting after the request does NOT prove that GPU queues were quiesced.
    Never cancel/rearm the deadline or serial service while waiting. The launcher
    owns the entire container lifetime; restarting that CID does not escape its cap.
    The initial StartedAt check rejects stale standalone requests, but Docker has no
    conditional stop API: do not restart a supervised container concurrently.
    """
    cid = full_cid(state["cid"])
    grace = seconds(grace)
    if not 1 <= grace <= 30:
        raise ValueError("shutdown grace must be 1..30 seconds")
    if not same_start_running(state):
        return {"cid": cid, "outcome": "already-stopped"}
    # Shutdown is an authenticated cleanup path, not a readiness assertion.
    # The exact CID plus its persisted StartedAt is the authorization boundary;
    # collector readiness, inhibitor state, and the exposure deadline may all
    # be absent or expired by the time cleanup runs. Never re-arm or extend the
    # existing deadline here.
    budget = min(grace, max(0, state["deadline_epoch"] - time.time() - 2)) if state["deadline_epoch"] else grace
    until = time.monotonic() + budget
    requested = False
    error = None
    if budget >= 1:
        try:
            run([binary("docker"), "exec", cid, "python3", "-c", POWERDOWN], timeout=min(4, budget))
            requested = True
        except Exception as failure:
            error = str(failure)
    if requested:
        while time.monotonic() < until:
            if not same_start_running(state):
                return {"cid": cid, "outcome": "exited-after-request"}
            time.sleep(min(0.2, max(0, until - time.monotonic())))
    if same_start_running(state):
        stop_exact(cid)
        return {"cid": cid, "outcome": "forced", "request_sent": requested, "request_error": error}
    return {"cid": cid, "outcome": "exited-after-request" if requested else "already-stopped"}


def _durable_json(path, value, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "w") as stream:
            fd = None
            stream.write(json.dumps(value, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if fd is not None:
            os.close(fd)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _validate_close_artifacts(results, run_id, manifest_sha256):
    results = Path(results)
    paths = {name: results / name for name in
             ("manifest.json", "interactive-ready.json", "probe.json")}
    if not all(path.is_file() for path in paths.values()):
        raise RuntimeError("closure requires manifest, interactive-ready, and probe artifacts")
    manifest_raw = paths["manifest.json"].read_bytes()
    if hashlib.sha256(manifest_raw).hexdigest() != manifest_sha256:
        raise RuntimeError("closure manifest hash does not match the expected card hash")
    try:
        manifest = json.loads(manifest_raw)
        ready = json.loads(paths["interactive-ready.json"].read_text())
        probe = json.loads(paths["probe.json"].read_text())
    except (OSError, ValueError, TypeError) as error:
        raise RuntimeError("closure artifacts are not valid JSON") from error
    if (manifest.get("run_id") != run_id or ready.get("run_id") != run_id or
            probe.get("run_id") != run_id):
        raise RuntimeError("closure artifacts have mismatched run identity or probe did not pass")
    output = probe.get("output", "")
    rows = [line[len("RGPU_DESKTOP_METAL_RESULT "):]
            for line in output.splitlines()
            if line.startswith("RGPU_DESKTOP_METAL_RESULT ")]
    exits = re.findall(r"^RGPU_EXIT " + re.escape(run_id) + r" (\d+)$", output, re.M)
    try:
        result = json.loads(rows[0]) if len(rows) == 1 else None
    except (ValueError, TypeError):
        result = None
    if (probe.get("transport_exit") != 0 or exits != ["0"] or
            not isinstance(result, dict) or result.get("run_id") != run_id or
            result.get("passed") is not True or result.get("device") != "AMD Radeon Navi23"):
        raise RuntimeError("closure requires one successful nonce-bound desktop probe and exit")
    if manifest.get("spec", {}).get("lifecycle_test") != "supervised-qemu-quit":
        raise RuntimeError("closure requires the predeclared supervised-qemu-quit lifecycle test")


def intentional_close(state, run_id, manifest_sha256, results, action_seconds=10):
    """Ask the exact supervised QEMU to exit through its authenticated HMP socket.

    The request is write-ahead and single-use.  This operation never falls back
    to Docker stop/kill and makes no claim about guest shutdown or recovery.
    """
    cid = full_cid(state["cid"])
    if not isinstance(run_id, str) or not run_id or len(run_id) > 256:
        raise ValueError("closure run_id is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(manifest_sha256)):
        raise ValueError("closure manifest hash must be a SHA-256 hex digest")
    action_seconds = seconds(action_seconds)
    if action_seconds < 1 or action_seconds > 30:
        raise ValueError("closure action seconds must be 1..30")
    results = Path(results).resolve()
    request_path = results / "intentional-closure-request.json"
    receipt_path = results / "intentional-closure-receipt.json"
    if request_path.exists() or receipt_path.exists():
        raise RuntimeError("closure request or receipt already exists; refusing replay")
    state_path = results / "supervision.json"
    if not state_path.is_file() or json.loads(state_path.read_text()) != state:
        raise RuntimeError("supplied supervision state is not the canonical results state")
    if (type(state.get("max_seconds")) is not int or state["max_seconds"] <= 0 or
            type(state.get("deadline_epoch")) not in (int, float) or
            not math.isfinite(state["deadline_epoch"]) or state["deadline_epoch"] <= 0):
        raise RuntimeError("closure requires a finite positive supervision deadline")
    _validate_close_artifacts(results, run_id, manifest_sha256)
    verify(state)
    if not same_start_running(state):
        raise RuntimeError("closure target is stopped or its identity/start changed")
    remaining = state["deadline_epoch"] - time.time() - 2
    if remaining < 1:
        raise RuntimeError("supervision deadline leaves no time for intentional closure")
    action_until = time.monotonic() + min(action_seconds, remaining)
    request = {"schema": 1, "kind": "intentional-qemu-closure-request",
               "nonce": uuid.uuid4().hex, "cid": cid,
               "started_at": state["started_at"], "run_id": run_id,
               "manifest_sha256": manifest_sha256, "requested_at": time.time(),
               "action_deadline": time.time() + max(0, action_until - time.monotonic())}
    try:
        _durable_json(request_path, request, exclusive=True)
    except FileExistsError:
        raise RuntimeError("closure request already exists; refusing replay") from None
    receipt = dict(request, kind="intentional-qemu-closure-receipt")
    try:
        # Re-run every supervision gate after the write-ahead record and bind
        # the action to the same live CID/start immediately before docker exec.
        verify(state)
        if not same_start_running(state):
            raise RuntimeError("closure target changed before HMP action")
        remaining = min(action_until - time.monotonic(), state["deadline_epoch"] - time.time() - 2)
        if remaining < 1:
            raise RuntimeError("closure action deadline elapsed before HMP action")
        run([binary("docker"), "exec", cid, "python3", "-c", QUIT],
            timeout=min(4, remaining))
        receipt["action"] = "hmp-quit"
        stopped = False
        while time.monotonic() < action_until:
            if not same_start_running(state):
                stopped = True
                break
            time.sleep(min(0.2, max(0, action_until - time.monotonic())))
        receipt["outcome"] = "stopped" if stopped else "deadline-expired"
        receipt["stopped_confirmed"] = stopped
    except Exception as error:
        receipt["outcome"] = "action-failed"
        receipt["stopped_confirmed"] = False
        try:
            receipt["stopped_after_action"] = not same_start_running(state)
        except Exception:
            receipt["stopped_after_action"] = False
        receipt["error_type"] = type(error).__name__
        receipt["error"] = str(error)[:512]
    try:
        _durable_json(receipt_path, receipt, exclusive=True)
    except FileExistsError:
        raise RuntimeError("closure receipt appeared during action; refusing overwrite") from None
    return receipt


def arm(vm, cid, maximum, critical_enabled=False):
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
    stop_command = shlex.join([docker, "stop", "--time", "0", cid])
    if os.environ.get('VM_MANAGER')=='libvirt':
        if deadline is None:raise RuntimeError('libvirt capture requires an exposure deadline')
        run_id=os.environ['RGPU_LIBVIRT_RUN_ID'];admission_digest=os.environ['RGPU_LIBVIRT_ADMISSION_SHA256']
        if not re.fullmatch('[0-9a-f]{32}',run_id) or not re.fullmatch('[0-9a-f]{64}',admission_digest):
            raise RuntimeError('invalid libvirt capture identity')
        stop_command=shlex.join([sys.executable,str(Path(__file__).resolve()),'capture-exit',
                                '--vm-dir',str(vm),'--cid',cid,'--started-at',started_at,
                                '--deadline',str(deadline),'--run-id',run_id,
                                '--admission-sha256',admission_digest])
    headless = os.environ.get("GENERIC_GRAPHICS") == "off"
    if headless and not logind_block_inhibited():
        raise RuntimeError("headless capture requires an existing sleep:idle block inhibitor")
    channels = [("serial", "console")]
    if critical_enabled:
        channels.append(("critical", "critical"))
    ready_paths = {}
    units = {}
    for stem, channel in channels:
        unit_base = f"rgpu-{stem}-{cid}"
        ready = vm / "run" / f"{stem}-{cid}.ready"
        ready.unlink(missing_ok=True)
        ready_paths[stem] = ready
        units[stem] = unit_base + ".service"
        explicit = ([f"--setenv=VM_SERIAL_CHANNEL={channel}"] if critical_enabled else [])
        channel_stop=stop_command
        if os.environ.get('VM_MANAGER')=='libvirt':
            eof_path=vm/'run'/f'capture-eof-{cid}-{channel}.json'
            eof_path.unlink(missing_ok=True)
            reset_path=vm/'run'/f'capture-reset-{cid}-{channel}.json'
            reset_path.unlink(missing_ok=True)
            channel_stop=stop_command+' --channel '+channel
            if not critical_enabled:explicit.append(f'--setenv=VM_SERIAL_CHANNEL={channel}')
            explicit += [f'--setenv=VM_SERIAL_EOF={eof_path}',f'--setenv=VM_SERIAL_RESET={reset_path}',
                         f'--setenv=VM_SERIAL_STARTED_AT={started_at}',
                         f'--setenv=VM_SERIAL_RUN_ID={run_id}',
                         f'--setenv=VM_SERIAL_ADMISSION_SHA256={admission_digest}']
        collector = [sys.executable, "-u", str(vm / "sercat.py")]
        if not headless:
            collector = [binary("systemd-inhibit"), "--what=sleep:idle",
                         f"--who=macOS VM {channel}",
                         "--why=Keep capture and the VM awake", *collector]
        run(base + [f"--unit={unit_base}", "--service-type=exec",
                    f"--property=WorkingDirectory={vm}", "--property=TimeoutStopSec=15s",
                    f"--property=ExecStopPost={channel_stop}",
                    f"--setenv=VM_SERIAL_SOCKET={vm / ('run/' + stem + '.sock')}",
                    f"--setenv=VM_SERIAL_OUTPUT={vm / ('run/' + stem + '.log')}",
                    f"--setenv=VM_SERIAL_READY={ready}", f"--setenv=VM_SERIAL_CID={cid}"] +
            explicit + endpoint + ["--", *collector])
    state = {"cid": cid, "started_at": started_at, "max_seconds": maximum,
             "deadline_epoch": deadline, "timer_unit": timer_unit,
             "serial_unit": units["serial"], "serial_ready": str(ready_paths["serial"]),
             "critical_enabled": bool(critical_enabled),
             "external_inhibitor": headless}
    if critical_enabled:
        state.update(critical_unit=units["critical"],
                     critical_ready=str(ready_paths["critical"]))
    verify(state, require_ready=False)
    until = time.monotonic() + 60  # One shared absolute readiness deadline.
    while not all(path.is_file() for path in ready_paths.values()):
        if time.monotonic() >= until or (deadline is not None and time.time() >= deadline):
            raise RuntimeError("capture channels did not become ready before their shared deadline")
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
        for unit in (f"rgpu-serial-{cid}.service", f"rgpu-critical-{cid}.service",
                     f"rgpu-deadline-{cid}.timer"):
            try:
                run([binary("systemctl"), "--user", "stop", unit])
            except Exception:
                pass  # Container stop was positively established above.
    else:
        # This random name belongs exclusively to this launch. Even failed ID
        # lookup must not fall back to the reusable macos-sequoia name.
        stop_exact(name, by_name=True)
    # Exact unique reservation: an old cleanup cannot unlink a newer launch.
    # Reached only after container stop was confirmed. Unknown stop leaves it.
    (vm / 'run/launch-pending' / name).unlink(missing_ok=True)



def release_libvirt(vm,state):
    """Publish one resume permit after exact-CID capture/timer verification."""
    path=Path(__file__).with_name('libvirt-console-handoff.py')
    spec=importlib.util.spec_from_file_location('libvirt_handoff',path)
    bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
    directory=bridge.run_directory(vm/'run',os.environ['RGPU_LIBVIRT_RUN_ID'])
    admission=json.loads((directory/'admission.json').read_text())
    expected=os.environ['RGPU_LIBVIRT_ADMISSION_SHA256']
    bridge.validate_admission(admission,admission['run_id'],expected,vm,
                              Path('/proc/sys/kernel/random/boot_id').read_text().strip())
    until=min(time.time()+30,admission['deadline_epoch'],state['deadline_epoch'])
    while not (directory/'paused.json').is_file():
        verify(state)
        if time.time()>=until:raise RuntimeError('paused libvirt identity not published before deadline')
        time.sleep(.1)
    paused=json.loads((directory/'paused.json').read_text())
    verify(state)
    if run([binary('docker'),'inspect','--format','{{.Image}}',state['cid']]).strip()!=admission['image_id']:
        raise RuntimeError('libvirt container image differs from admission')
    observed=json.loads(run([binary('docker'),'exec',state['cid'],'python3','-B',
                             '/run/rgpu-tools/libvirt-console-entry.py','inspect-paused'],
                            timeout=max(.1,min(20,until-time.time()))))
    # Recheck live host topology immediately before authorizing guest execution.
    spec=importlib.util.spec_from_file_location('libvirt_network',path.with_name('libvirt-console-network.py'))
    network=importlib.util.module_from_spec(spec);spec.loader.exec_module(network)
    if network.capture_host(admission['network']['name'],admission['network']['mac'])!=admission['network']:
        raise RuntimeError('host macvtap changed during launch')
    verify(state)
    if time.time()>=until:
        raise RuntimeError('libvirt handoff deadline elapsed before resume permit')
    permit=bridge.permit(admission,expected,paused,observed,state)
    bridge.write_once(directory/'resume.json',permit)
    while not (directory/'running.json').is_file():
        verify(state)
        if time.time()>=until:raise RuntimeError('libvirt controller did not observe resume')
        time.sleep(.1)
    running=json.loads((directory/'running.json').read_text())
    if (running['cid']!=state['cid'] or running['started_at']!=state['started_at'] or
            running['run_id']!=admission['run_id'] or running['identity']!=paused['identity'] or
            running['scope']!=paused['scope'] or running['plan_sha256']!=paused['plan_sha256']):
        raise RuntimeError('resumed domain identity mismatch')
    state['libvirt_run_id']=admission['run_id']
    state['libvirt_plan_sha256']=paused['plan_sha256']


def launch(vm, name, maximum, gpu_args, critical_enabled=False):
    """Foreground lifetime of a user service, with cleanup also in ExecStopPost."""
    vm = vm.resolve()
    name = launch_name(name)
    def terminated(signum, frame):
        # Retry loops catch Exception; termination must always reach finally.
        raise SystemExit("supervised launch was terminated")
    signal.signal(signal.SIGTERM, terminated)
    child = None
    try:
        # A prior socket must never satisfy this launch's readiness check.
        (vm / "run/serial.sock").unlink(missing_ok=True)
        (vm / "run/critical.sock").unlink(missing_ok=True)
        with (vm / "run/vm-launch.log").open("w") as log:
            child = subprocess.Popen([str(vm / "macos-vm.sh"), "run", *gpu_args], cwd=vm,
                                     env=dict(os.environ, NAME=name, GPU="", GPU_ID="", GPU_ROM="",
                                              GPU_SUB="", EXTRA="", SERIAL="on",
                                              HDMI_AUDIO=os.environ.get("HDMI_AUDIO", "off") if "--gpu" in gpu_args else "off",
                                              CRITICAL_SERIAL="on" if critical_enabled else "off"),
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
        state = arm(vm, cid, maximum, critical_enabled)
        # Existing guest tools address this familiar name; all supervision uses CID.
        run([binary("docker"), "rename", cid, "macos-sequoia"])
        agent_source = Path(__file__).with_name('agent-server.py')
        if not agent_source.is_file():
            raise RuntimeError('versioned agent server is missing')
        for attempt in range(30):
            try:
                run([binary("docker"), "cp", str(agent_source), f"{cid}:/tmp/"])
                for command in (["python3", "/tmp/agent-server.py"],
                                ["sh", "-c", "cd /run/vm && exec python3 -m http.server 8889"]):
                    run([binary("docker"), "exec", "-d", cid, *command])
                run([binary("docker"), "exec", cid, "sh", "-c",
                     "curl -fsS --max-time 2 http://127.0.0.1:8888/health >/dev/null && "
                     "curl -fsS --max-time 2 http://127.0.0.1:8889/ >/dev/null"])
                break
            except Exception:
                if attempt == 29:
                    raise RuntimeError('container command and permit servers did not become ready')
                time.sleep(2)
        verify(state)
        if os.environ.get("VM_MANAGER") == "libvirt":
            release_libvirt(vm,state)
        state["launch_unit"] = name + ".service"
        ready = vm / "run" / (name + ".json")
        temporary = ready.with_suffix(".tmp")
        temporary.write_text(json.dumps(state))
        temporary.replace(ready)
        if maximum:
            # Leave the original service cap and exact-CID deadline armed. Start
            # ACPI shutdown early enough to allow a bounded grace interval.
            while child.poll() is None:
                if time.time() >= state["deadline_epoch"] - 30:
                    result = shutdown(state)
                    (vm / "run" / f"shutdown-{cid}.json").write_text(json.dumps(result))
                    break
                time.sleep(0.2)
        child.wait()
    except BaseException as error:
        # Preserve the underlying launcher failure before cleanup.  This record
        # contains no command arguments or environment and is best-effort so a
        # full run directory can never prevent the safety cleanup below.
        try:
            record = vm / "run" / (name + ".failure.json")
            record.write_text(json.dumps({"launch": name,
                                          "error_type": type(error).__name__,
                                          "error": str(error)[:512]}) + "\n")
            record.chmod(0o600)
        except OSError:
            pass
        raise
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


def start(vm, maximum, gpu_args, critical_enabled=False):
    with (vm / 'run/redeploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pending = vm / 'run/launch-pending'
        pending.mkdir(exist_ok=True)
        if any(pending.iterdir()):
            raise RuntimeError('a supervised launch is still pending')
        active = run([binary('docker'), 'ps', '-a', '--filter', 'status=running',
                      '--filter', 'status=created', '--filter', 'status=restarting',
                      '--filter', 'status=paused', '--format', '{{.Names}}'])
        if any(name == 'macos-sequoia' or name.startswith('rgpu-launch-')
               for name in active.splitlines()):
            raise RuntimeError('active or pending VM already owns the media')
        return start_locked(vm, maximum, gpu_args, critical_enabled)


def start_locked(vm, maximum, gpu_args, critical_enabled=False, context=None):
    vm = vm.resolve()
    name = "rgpu-launch-" + uuid.uuid4().hex
    context = context or {}
    if os.environ.get("GENERIC_GRAPHICS") == "off" and not logind_block_inhibited():
        raise RuntimeError("headless capture requires an existing sleep:idle block inhibitor")
    try:
        familiar_name = run([binary("docker"), "ps", "-a", "--filter",
                             "name=^/macos-sequoia$", "--format", "{{.Names}}"]).strip()
        if familiar_name == "macos-sequoia":
            cid = full_cid(run([binary("docker"), "inspect", "--format", "{{.Id}}",
                                 "macos-sequoia"]).strip())
            selected = '{"Id":{{json .Id}},"Name":{{json .Name}},"Running":{{json .State.Running}},"Status":{{json .State.Status}},"Mounts":{{json .Mounts}}}'
            info = json.loads(run([binary("docker"), "inspect", "--format", selected, cid]))
            if (info["Id"] != cid or info["Name"] != "/macos-sequoia" or info["Running"] or
                    info["Status"] not in ("exited", "dead")):
                raise RuntimeError("familiar macos-sequoia container is not stopped")
            expected_disk = str((vm / "mac_hdd_ng.img").resolve())
            if not any(m.get("Type") == "bind" and m.get("Source") == expected_disk
                       for m in info.get("Mounts", [])):
                raise RuntimeError("familiar macos-sequoia container is not associated with this VM")
            archive_name = "macos-sequoia-archive-" + uuid.uuid4().hex
            run([binary("docker"), "rename", cid, archive_name])
            check = json.loads(run([binary("docker"), "inspect", "--format", selected, cid]))
            if (check["Id"] != cid or check["Name"] != "/" + archive_name or
                    canonical_mounts(check.get("Mounts")) is None or
                    canonical_mounts(check.get("Mounts")) != canonical_mounts(info.get("Mounts")) or
                    check["Running"] or check["Status"] not in ("exited", "dead")):
                raise RuntimeError("familiar container identity changed while archiving")
            archive_record = vm / "run" / (archive_name + ".json")
            archive_record.write_text(json.dumps({"old_name": "macos-sequoia",
                                                  "new_name": archive_name, "cid": cid,
                                                  "status": check["Status"]}) + "\n")
            archive_record.chmod(0o600)
    except BaseException as error:
        evidence = record_preexposure_failure(vm, name, context, 'archive', error)
        raise PreExposureFailure(str(error), evidence) from error
    # Durable admission survives the short-lived caller dying before Docker has
    # created a visible container. Managed cleanup removes only this launch's file.
    reservation = vm / 'run/launch-pending' / name
    try:
        with reservation.open('x') as stream:
            stream.write(name+'\n')
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException as error:
        evidence = record_preexposure_failure(vm, name, context, 'reservation', error)
        raise PreExposureFailure(str(error), evidence) from error
    helper = str(Path(__file__).resolve())
    env_keys = DOCKER_ENV + ("PATH", "DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "IMAGE",
                           "VCPUS", "RAM_GB", "DISK_BUS", "AUDIO", "NVRAM", "BOOTDISK_MODE",
                           "NIC", "GL", "GDB", "SSH_PORT", "SCREEN_PORT")
    env_keys += ("GENERIC_GRAPHICS", "VM_CONSOLE", "VM_MANAGER", "CONSOLE_REFRESH", "CONSOLE_FULL_REFRESH", "CONSOLE_SNAPSHOT", "CONSOLE_VDAGENT",
                 "RGPU_LIBVIRT_RUN_ID", "RGPU_LIBVIRT_ADMISSION_SHA256")
    endpoint = [f"--setenv={key}={os.environ.get(key, '')}" for key in env_keys]
    # A GPUless request cannot inherit hidden passthrough from the manager or
    # caller. GPU options are supplied solely by the validated launcher flags.
    endpoint += [f"--setenv={key}=" for key in ("GPU", "GPU_ID", "GPU_ROM", "GPU_SUB", "EXTRA")]
    audio_option = os.environ.get("HDMI_AUDIO", "off") if "--gpu" in gpu_args else "off"
    if audio_option not in ("off", "on"):
        raise ValueError("invalid HDMI_AUDIO option")
    endpoint.append(f"--setenv=HDMI_AUDIO={audio_option}")
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
                           "--name", name, "--max-seconds", str(maximum)]
    if critical_enabled:
        command.append("--critical-serial")
    command += ["--", *gpu_args]
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
        reservation.unlink()
        return state
    except BaseException:
        launch_error = sys.exc_info()
        failure_record = vm / "run" / (name + ".failure.json")
        failure_summary = f'{type(launch_error[1]).__name__}: {str(launch_error[1])[:160]}'
        try:
            if failure_record.is_file():
                prior = json.loads(failure_record.read_text())
                if (prior.get("launch") == name and isinstance(prior.get("error"), str)):
                    failure_summary = f'{prior.get("error_type", "Error")}: {prior["error"][:160]}'
        except (OSError, ValueError, TypeError):
            pass
        try:
            run([binary("systemctl"), "--user", "stop", name + ".service"], timeout=40)
        except Exception as stop_error:
            # A vanished transient unit must not replace the launch exception
            # with a second systemctl/show failure.  Only an explicit bounded
            # not-found result permits cleanup; unknown service state remains a
            # failed stop and retains the reservation.
            try:
                service = properties(name + ".service")
            except Exception:
                raise ManagedStopUnconfirmed(
                    f'managed service stop unconfirmed ({failure_summary}); launch reservation retained'
                ) from stop_error
            if service.get("LoadState") == "not-found":
                cleanup(vm, name)
                raise launch_error[1].with_traceback(launch_error[2])
            # Absence of a container does not cancel an accepted but delayed
            # service launch. Its own cap/cleanup remain responsible; keep the
            # reservation until that lifetime is known to have ended.
            raise ManagedStopUnconfirmed(
                f'managed service stop unconfirmed ({failure_summary}); launch reservation retained') from stop_error
        cleanup(vm, name)
        raise launch_error[1].with_traceback(launch_error[2])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("arm")
    create.add_argument("--vm-dir", type=Path, required=True)
    create.add_argument("--cid", required=True)
    create.add_argument("--max-seconds", required=True)
    create.add_argument("--critical-serial", action="store_true")
    capture=commands.add_parser('capture-exit')
    capture.add_argument('--vm-dir',type=Path,required=True)
    capture.add_argument('--cid',required=True)
    capture.add_argument('--started-at',required=True)
    capture.add_argument('--deadline',type=int,required=True)
    capture.add_argument('--run-id',required=True)
    capture.add_argument('--admission-sha256',required=True)
    capture.add_argument('--channel',choices=('console','critical'))
    halt = commands.add_parser("shutdown")
    halt.add_argument("--state", type=Path, required=True)
    halt.add_argument("--grace-seconds", default="20")
    close = commands.add_parser("intentional-close")
    close.add_argument("--state", type=Path, required=True)
    close.add_argument("--run-id", required=True)
    close.add_argument("--manifest-sha256", required=True)
    close.add_argument("--results-dir", type=Path, required=True)
    close.add_argument("--action-seconds", default="10")
    check = commands.add_parser("verify")
    check.add_argument("--state", type=Path, required=True)
    for verb in ("start", "launch", "cleanup"):
        sub = commands.add_parser(verb)
        sub.add_argument("--vm-dir", type=Path, required=True)
        if verb != "start":
            sub.add_argument("--name", required=True)
        if verb != "cleanup":
            sub.add_argument("--max-seconds", required=True)
            sub.add_argument("--critical-serial", action="store_true")
            sub.add_argument("gpu_args", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    cid = None
    try:
        if args.command == 'capture-exit':
            result=capture_exit(args.vm_dir,args.cid,args.started_at,args.deadline,
                                args.run_id,args.admission_sha256,args.channel)
            print(json.dumps(result));return 0
        if args.command == "shutdown":
            # shutdown checks the saved StartedAt before any request or force-stop.
            # Do not use generic failure cleanup, which may target a restarted CID.
            result = shutdown(json.loads(args.state.read_text()), args.grace_seconds)
            print(json.dumps(result))
            return 0
        if args.command == "intentional-close":
            state_path = args.state.resolve()
            results = args.results_dir.resolve()
            if state_path != results / "supervision.json":
                raise ValueError("--state must be results-dir/supervision.json")
            result = intentional_close(json.loads(state_path.read_text()), args.run_id,
                                       args.manifest_sha256, results, args.action_seconds)
            print(json.dumps(result))
            return 0 if result.get("stopped_confirmed") is True else 1
        if args.command in ("start", "launch", "cleanup"):
            if args.command == "cleanup":
                cleanup(args.vm_dir, args.name)
                return 0
            maximum = seconds(args.max_seconds)
            gpu_args = args.gpu_args[1:] if args.gpu_args[:1] == ["--"] else args.gpu_args
            if "--gpu" in gpu_args and maximum == 0:
                raise ValueError("GPU launches require a positive exposure cap")
            if args.command == "launch":
                launch(args.vm_dir, args.name, maximum, gpu_args, args.critical_serial)
                return 0
            state = start(args.vm_dir, maximum, gpu_args, args.critical_serial)
        elif args.command == "arm":
            cid = full_cid(args.cid)
            state = arm(args.vm_dir, cid, seconds(args.max_seconds), args.critical_serial)
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
                for unit in (f"rgpu-serial-{cid}.service", f"rgpu-critical-{cid}.service",
                             f"rgpu-deadline-{cid}.timer"):
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
