#!/usr/bin/env python3
"""Prepare and run one bounded Aqua virtual-display stimulus.

Preparation is a separate GPU-less operation.  The runtime command verifies the
prepared source and binary identities, then bootstraps the process in the
current console user's ``gui/<uid>`` launchd domain.
"""

import base64
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shlex
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests" / "desktop_display.m"
HEX32 = re.compile(r"[0-9a-f]{32}")
SHA256 = re.compile(r"[0-9a-f]{64}")
SAFE_GUEST_PATH = re.compile(
    r"/var/tmp/rgpu-desktop-display-v2-[0-9a-f]{16}/desktop-display")


def _valid_nonce(value):
    return isinstance(value, str) and HEX32.fullmatch(value) is not None


def _valid_epoch(value):
    return type(value) is int and value > 0


def _valid_sha(value):
    return isinstance(value, str) and SHA256.fullmatch(value) is not None


def _prepared_paths(source_sha256):
    directory = f"/var/tmp/rgpu-desktop-display-v2-{source_sha256[:16]}"
    return directory, f"{directory}/desktop_display.m", f"{directory}/desktop-display"


def prepare_guest_command(nonce, source, expiry):
    """Build the helper in a GPU-less guest and report its exact identity."""
    if not _valid_nonce(nonce) or type(source) is not bytes or not _valid_epoch(expiry):
        raise ValueError("invalid desktop preparation input")
    source_sha = hashlib.sha256(source).hexdigest()
    directory, guest_source, guest_binary = _prepared_paths(source_sha)
    encoded = base64.b64encode(source).decode("ascii")
    permit = f"http://10.0.2.2:8889/metal-permit-{nonce}"
    qdir = shlex.quote(directory)
    qsource = shlex.quote(guest_source)
    qbinary = shlex.quote(guest_binary)
    qtemporary = shlex.quote(guest_binary + "." + nonce + ".tmp")
    action = (
        f"dir={qdir}; permit=$(/usr/bin/curl -fsS --max-time 3 {shlex.quote(permit)}) && "
        f"test \"$permit\" = {shlex.quote(nonce)} && "
        f"test $(/bin/date +%s) -le {expiry} && "
        "test ! -e \"$dir\" && test ! -L \"$dir\" && "
        "/bin/mkdir -m 755 \"$dir\" && "
        "test \"$(/usr/bin/stat -f %u \"$dir\")\" = 0 && "
        f"test ! -e {qsource} && test ! -L {qsource} && "
        f"test ! -e {qbinary} && test ! -L {qbinary} && "
        f"test ! -e {qtemporary} && test ! -L {qtemporary} && "
        f"/usr/bin/printf %s {shlex.quote(encoded)} | /usr/bin/base64 -D > {qsource} && "
        f"test \"$(/usr/bin/shasum -a 256 {qsource} | /usr/bin/awk '{{print $1}}')\" = "
        f"{shlex.quote(source_sha)} && "
        "/usr/bin/xcrun clang -fobjc-arc -fblocks -O2 -Wall -Wextra -Werror "
        "-framework Foundation -framework CoreGraphics -framework SystemConfiguration "
        f"-framework AppKit -framework QuartzCore -framework Metal {qsource} -o {qtemporary} && "
        f"/bin/chmod 755 {qtemporary} && "
        f"/usr/bin/codesign --force --sign - --timestamp=none {qtemporary} && "
        f"/usr/bin/codesign --verify --strict {qtemporary} && "
        f"/bin/mv {qtemporary} {qbinary} && "
        f"binary_sha=$(/usr/bin/shasum -a 256 {qbinary} | /usr/bin/awk '{{print $1}}') && "
        f"/usr/bin/printf 'RGPU_DESKTOP_PREPARE "
        f"{{\"schema\":1,\"nonce\":\"%s\",\"source_sha256\":\"%s\","
        f"\"binary_sha256\":\"%s\",\"guest_binary\":\"%s\","
        f"\"compiled\":true}}\\n' {shlex.quote(nonce)} {shlex.quote(source_sha)} "
        f"\"$binary_sha\" {qbinary}"
    )
    return (f"( {action}; result=$?; /usr/bin/printf '\\nRGPU_EXIT {nonce} %s\\n' "
            '"$result" )')


def _launch_agent_plist(label, guest_binary, execution_mode, nonce, expiry, hold_seconds,
                        registry_id, output_path, launch_domain, source_sha256,
                        binary_sha256):
    arguments = (guest_binary, execution_mode, nonce, str(expiry), str(hold_seconds),
                 str(registry_id), output_path, source_sha256, binary_sha256)
    escaped_arguments = "".join(
        f"<string>{value}</string>" for value in arguments)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>'
        f'<key>Label</key><string>{label}</string>'
        f'<key>ProgramArguments</key><array>{escaped_arguments}</array>'
        '<key>RunAtLoad</key><true/>'
        '<key>ProcessType</key><string>Interactive</string>'
        '<key>EnvironmentVariables</key><dict>'
        f'<key>RGPU_LAUNCH_DOMAIN</key><string>{launch_domain}</string>'
        '</dict></dict></plist>\n')


def _guest_command(nonce, expiry, hold_seconds, *, guest_binary,
                   source_sha256, binary_sha256, registry_id, execution_mode):
    if (not _valid_nonce(nonce) or not _valid_epoch(expiry) or
            type(hold_seconds) is not int or not 1 <= hold_seconds <= 30 or
            not _valid_sha(source_sha256) or not _valid_sha(binary_sha256) or
            not isinstance(guest_binary, str) or
            SAFE_GUEST_PATH.fullmatch(guest_binary) is None or
            execution_mode not in ("production", "gpuless-qualification") or
            type(registry_id) is not int or
            (execution_mode == "production" and registry_id <= 0) or
            (execution_mode == "gpuless-qualification" and registry_id != 0)):
        raise ValueError("invalid desktop runtime input")
    prepared_directory = str(Path(guest_binary).parent)
    prepared_source = str(Path(prepared_directory) / "desktop_display.m")
    runtime_directory = f"/var/tmp/rgpu-desktop-run-{nonce}"
    label = f"com.raphael.desktop.{nonce}"
    plist_path = f"{runtime_directory}/{label}.plist"
    output_path = f"{runtime_directory}/result.txt"
    launch_domain = "gui/__RGPU_UID__"
    plist = _launch_agent_plist(label, guest_binary, execution_mode, nonce, expiry, hold_seconds,
                                registry_id, output_path, launch_domain,
                                source_sha256, binary_sha256)
    encoded_plist = base64.b64encode(plist.encode("utf-8")).decode("ascii")
    permit = f"http://10.0.2.2:8889/metal-permit-{nonce}"
    qruntime = shlex.quote(runtime_directory)
    qsource = shlex.quote(prepared_source)
    qbinary = shlex.quote(guest_binary)
    qplist = shlex.quote(plist_path)
    qoutput = shlex.quote(output_path)
    qlabel = shlex.quote(label)
    # bootstrap is the authority transition.  asuser is deliberately absent: it
    # does not establish execution in the Aqua bootstrap namespace by itself.
    action = (
        f"dir={qruntime}; bootstrapped=0; "
        "cleanup() { if test \"$bootstrapped\" = 1; then "
        f"/bin/launchctl kill TERM \"gui/$uid/{label}\" >/dev/null 2>&1; "
        f"/bin/launchctl bootout \"gui/$uid\" {qplist} >/dev/null 2>&1; fi; "
        '/bin/rm -rf "$dir"; }; trap cleanup EXIT HUP INT TERM; '
        f"/bin/mkdir -m 700 {qruntime} && "
        f"permit=$(/usr/bin/curl -fsS --max-time 3 {shlex.quote(permit)}) && "
        f"test \"$permit\" = {shlex.quote(nonce)} && "
        "console_user=$(/usr/bin/stat -f %Su /dev/console) && "
        "test -n \"$console_user\" && test \"$console_user\" != root && "
        "test \"$console_user\" != loginwindow && "
        "uid=$(/usr/bin/id -u \"$console_user\") && test \"$uid\" -ge 500 && "
        "/bin/launchctl print \"gui/$uid\" >/dev/null && "
        f"test -x {qbinary} && "
        f"test \"$(/usr/bin/shasum -a 256 {qsource} | /usr/bin/awk '{{print $1}}')\" = "
        f"{shlex.quote(source_sha256)} && "
        f"test \"$(/usr/bin/shasum -a 256 {qbinary} | /usr/bin/awk '{{print $1}}')\" = "
        f"{shlex.quote(binary_sha256)} && "
        f"/usr/bin/codesign --verify --strict {qbinary} && "
        "now=$(/bin/date +%s) && "
        f"test \"$now\" -le {expiry} && "
        f"test $((now + {hold_seconds} + 8)) -le {expiry} && "
        f"/usr/bin/printf %s {shlex.quote(encoded_plist)} | /usr/bin/base64 -D > {qplist} && "
        f"/usr/bin/sed -i '' \"s/__RGPU_UID__/$uid/g\" {qplist} && "
        f"/usr/sbin/chown -R \"$uid\" {qruntime} && "
        f"/bin/launchctl bootstrap \"gui/$uid\" {qplist} && bootstrapped=1 && "
        f"/bin/launchctl print \"gui/$uid/{label}\" >/dev/null && "
        f"while test ! -f {qoutput} && test $(/bin/date +%s) -le {expiry}; do "
        "/bin/sleep 1; done && "
        f"test -s {qoutput} && /bin/cat {qoutput} && "
        f"/bin/launchctl bootout \"gui/$uid\" {qplist} && bootstrapped=0"
    )
    return (f"( {action}; result=$?; /usr/bin/printf '\\nRGPU_EXIT {nonce} %s\\n' "
            '"$result" )')


def guest_command(nonce, expiry, hold_seconds, *, guest_binary,
                  source_sha256, binary_sha256, registry_id):
    """Build the production command; no software or missing-device fallback exists."""
    return _guest_command(
        nonce, expiry, hold_seconds, guest_binary=guest_binary,
        source_sha256=source_sha256, binary_sha256=binary_sha256,
        registry_id=registry_id, execution_mode="production")


def qualification_guest_command(nonce, expiry, hold_seconds, *, guest_binary,
                                source_sha256, binary_sha256):
    """Build an explicitly non-GPU lifecycle/session qualification command."""
    return _guest_command(
        nonce, expiry, hold_seconds, guest_binary=guest_binary,
        source_sha256=source_sha256, binary_sha256=binary_sha256,
        registry_id=0, execution_mode="gpuless-qualification")


def _one_json_row(output, prefix, error_message):
    rows = [line.removeprefix(prefix) for line in output.splitlines()
            if line.startswith(prefix)]
    if len(rows) != 1:
        raise ValueError(error_message)
    try:
        value = json.loads(rows[0])
    except json.JSONDecodeError as error:
        raise ValueError(error_message) from error
    if not isinstance(value, dict):
        raise ValueError(error_message)
    return value


def _require_exit(output, nonce, label):
    exits = re.findall(r"^RGPU_EXIT " + re.escape(nonce) + r" (\d+)$", output, re.M)
    if exits != ["0"]:
        raise ValueError(f"{label} did not exit successfully")


def validate_prepare_output(output, nonce, expected_source_sha256=None):
    if (not isinstance(output, str) or not _valid_nonce(nonce) or
            expected_source_sha256 is not None and
            not _valid_sha(expected_source_sha256)):
        raise ValueError("invalid preparation output arguments")
    result = _one_json_row(output, "RGPU_DESKTOP_PREPARE ",
                           "expected exactly one desktop preparation receipt")
    _require_exit(output, nonce, "desktop preparation")
    keys = {"schema", "nonce", "source_sha256", "binary_sha256",
            "guest_binary", "compiled"}
    if (set(result) != keys or result.get("schema") != 1 or
            result.get("nonce") != nonce or result.get("compiled") is not True or
            not _valid_sha(result.get("source_sha256")) or
            not _valid_sha(result.get("binary_sha256")) or
            not isinstance(result.get("guest_binary"), str) or
            SAFE_GUEST_PATH.fullmatch(result["guest_binary"]) is None or
            expected_source_sha256 is not None and
            result["source_sha256"] != expected_source_sha256):
        raise ValueError("invalid desktop preparation receipt")
    expected_path = _prepared_paths(result["source_sha256"])[2]
    if result["guest_binary"] != expected_path:
        raise ValueError("desktop preparation path does not match source identity")
    return result


def finalize_card(template, prepare_receipt):
    """Fill a desktop card template from one exact current-source build receipt."""
    if not isinstance(template, dict) or not isinstance(prepare_receipt, dict):
        raise ValueError("invalid desktop card finalization input")
    phase = template.get("desktop_phase")
    phase_keys = {"schema", "hold_seconds", "cleanup_reserve_seconds",
                  "source_sha256", "binary_sha256", "guest_binary",
                  "require_remote_frame_change"}
    receipt_keys = {"schema", "nonce", "source_sha256", "binary_sha256",
                    "guest_binary", "compiled"}
    identity_keys = ("source_sha256", "binary_sha256", "guest_binary")
    if (not isinstance(phase, dict) or set(phase) != phase_keys or
            phase.get("schema") != 1 or
            type(phase.get("hold_seconds")) is not int or
            not 1 <= phase["hold_seconds"] <= 30 or
            type(phase.get("cleanup_reserve_seconds")) is not int or
            phase["cleanup_reserve_seconds"] < 25 or
            phase.get("require_remote_frame_change") is not True or
            any(phase.get(key) is not None for key in identity_keys) or
            set(prepare_receipt) != receipt_keys or
            prepare_receipt.get("schema") != 1 or
            not _valid_nonce(prepare_receipt.get("nonce")) or
            prepare_receipt.get("compiled") is not True or
            not _valid_sha(prepare_receipt.get("source_sha256")) or
            not _valid_sha(prepare_receipt.get("binary_sha256")) or
            not isinstance(prepare_receipt.get("guest_binary"), str)):
        raise ValueError("desktop card template or preparation receipt is invalid")
    current_source_sha = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if (prepare_receipt["source_sha256"] != current_source_sha or
            prepare_receipt["guest_binary"] !=
            _prepared_paths(current_source_sha)[2]):
        raise ValueError("desktop preparation does not match the current helper source")
    finalized = copy.deepcopy(template)
    for key in identity_keys:
        finalized["desktop_phase"][key] = prepare_receipt[key]
    return finalized


def _require_keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"invalid {label} schema")


def _validate_output(output, nonce, expected, execution_mode):
    if not isinstance(output, str) or not _valid_nonce(nonce):
        raise ValueError("invalid desktop output arguments")
    if expected is not None and not isinstance(expected, dict):
        raise ValueError("invalid expected desktop identity")
    result = _one_json_row(output, "RGPU_DESKTOP_RESULT ",
                           "expected exactly one desktop result")
    _require_exit(output, nonce, "desktop probe")
    _require_keys(result, (
        "schema", "nonce", "execution_mode", "source_sha256", "binary_sha256", "guest_binary",
        "expiry_epoch", "started_epoch", "finished_epoch", "hold_seconds",
        "aqua", "display", "stimulus", "remote_observation"), "desktop result")
    if (result.get("schema") != 1 or result.get("nonce") != nonce or
            result.get("execution_mode") != execution_mode or
            not _valid_sha(result.get("source_sha256")) or
            not _valid_sha(result.get("binary_sha256")) or
            not isinstance(result.get("guest_binary"), str) or
            SAFE_GUEST_PATH.fullmatch(result["guest_binary"]) is None or
            not _valid_epoch(result.get("expiry_epoch")) or
            not _valid_epoch(result.get("started_epoch")) or
            not _valid_epoch(result.get("finished_epoch")) or
            type(result.get("hold_seconds")) is not int or
            not 1 <= result["hold_seconds"] <= 30 or
            result["started_epoch"] > result["finished_epoch"] or
            result["finished_epoch"] > result["expiry_epoch"]):
        raise ValueError("invalid desktop result identity or deadline")
    if expected is not None:
        bindings = ("source_sha256", "binary_sha256", "guest_binary",
                    "expiry_epoch", "hold_seconds")
        if any(result.get(key) != expected.get(key) for key in bindings):
            raise ValueError("desktop result does not match expected identity")

    aqua = result["aqua"]
    _require_keys(aqua, (
        "ready", "console_user", "console_uid", "session_user", "session_uid",
        "login_done", "on_console", "launch_domain",
        "launch_domain_environment", "launchd_job_pid"), "Aqua")
    uid = aqua.get("console_uid")
    if (aqua.get("ready") is not True or type(uid) is not int or uid < 500 or
            type(aqua.get("session_uid")) is not int or aqua["session_uid"] != uid or
            not isinstance(aqua.get("console_user"), str) or
            not aqua["console_user"] or aqua["console_user"] in ("root", "loginwindow") or
            aqua.get("session_user") != aqua["console_user"] or
            aqua.get("login_done") is not True or aqua.get("on_console") is not True or
            aqua.get("launch_domain") != f"gui/{uid}" or
            aqua.get("launch_domain_environment") is not True or
            type(aqua.get("launchd_job_pid")) is not int or
            aqua["launchd_job_pid"] <= 0):
        raise ValueError("Aqua session proof did not complete")

    display = result["display"]
    _require_keys(display, (
        "baseline_ids", "created", "display_id", "new_ids", "settings_applied",
        "added", "active", "width", "height", "refresh", "removed",
        "final_ids", "cleanup_complete", "termination_signal"), "display lifecycle")
    baseline, final_ids, new_ids = (display.get("baseline_ids"),
                                    display.get("final_ids"), display.get("new_ids"))
    lists = (baseline, final_ids, new_ids)
    if (any(not isinstance(values, list) or
            any(type(value) is not int or value <= 0 for value in values)
            for values in lists) or
            any(len(values) != len(set(values)) for values in lists) or
            type(display.get("display_id")) is not int or display["display_id"] <= 0 or
            new_ids != [display["display_id"]] or display["display_id"] in baseline or
            final_ids != baseline or
            any(display.get(key) is not True for key in
                ("created", "settings_applied", "added", "active", "removed",
                 "cleanup_complete")) or
            display.get("width") != 1280 or display.get("height") != 720 or
            type(display.get("refresh")) not in (int, float) or
            abs(display["refresh"] - 60.0) > 0.01 or
            type(display.get("termination_signal")) is not int or
            display["termination_signal"] not in (0, 1, 2, 15)):
        raise ValueError("display lifecycle did not complete")

    stimulus = result["stimulus"]
    _require_keys(stimulus, (
        "registry_id", "device_name", "window_visible", "window_display_id",
        "drawables_acquired", "command_buffers_submitted",
        "command_buffers_completed", "presented_frames", "first_frame",
        "last_frame", "distinct_color_tokens", "first_color_token",
        "last_color_token", "classification"), "stimulus")
    expected_registry = expected.get("registry_id") if expected is not None else None
    if execution_mode == "production" and (
            type(stimulus.get("registry_id")) is not int or
            stimulus["registry_id"] <= 0 or
            expected_registry is not None and stimulus["registry_id"] != expected_registry or
            stimulus.get("device_name") != "AMD Radeon Navi23" or
            stimulus.get("window_visible") is not True or
            stimulus.get("window_display_id") != display["display_id"] or
            any(type(stimulus.get(key)) is not int for key in
                ("drawables_acquired", "command_buffers_submitted",
                 "command_buffers_completed", "presented_frames", "first_frame",
                 "last_frame", "distinct_color_tokens")) or
            stimulus["drawables_acquired"] < 2 or
            stimulus["command_buffers_submitted"] < stimulus["command_buffers_completed"] or
            stimulus["command_buffers_completed"] < stimulus["presented_frames"] or
            stimulus["presented_frames"] < 2 or
            stimulus["last_frame"] <= stimulus["first_frame"] or
            stimulus["distinct_color_tokens"] < 2 or
            stimulus.get("first_color_token") != "#ff0000" or
            stimulus.get("last_color_token") != "#00ffff" or
            stimulus.get("classification") != "selected_metal_device"):
        raise ValueError("visible Metal stimulus did not complete")
    if execution_mode == "gpuless-qualification" and (
            stimulus.get("registry_id") != 0 or stimulus.get("device_name") != "" or
            stimulus.get("window_visible") is not True or
            stimulus.get("window_display_id") != display["display_id"] or
            any(stimulus.get(key) != 0 for key in
                ("drawables_acquired", "command_buffers_submitted",
                 "command_buffers_completed", "presented_frames", "first_frame",
                 "last_frame", "distinct_color_tokens")) or
            stimulus.get("first_color_token") != "" or
            stimulus.get("last_color_token") != "" or
            stimulus.get("classification") != "non_gpu_qualification"):
        raise ValueError("invalid non-GPU qualification classification")

    remote = result["remote_observation"]
    _require_keys(remote, ("required", "observed", "frame_change_observed", "evidence"),
                  "remote observation")
    expected_remote = ((True, "external_capture_required") if execution_mode == "production"
                       else (False, "not_requested_gpuless_qualification"))
    if (remote.get("required") is not expected_remote[0] or
            remote.get("observed") is not False or
            remote.get("frame_change_observed") is not False or
            remote.get("evidence") != expected_remote[1]):
        raise ValueError("remote frame evidence must remain external")
    return result


def validate_output(output, nonce, expected=None):
    """Validate production proof without promoting local counters to VNC proof."""
    return _validate_output(output, nonce, expected, "production")


def validate_qualification_output(output, nonce, expected=None):
    """Validate only Aqua/display lifecycle in explicit non-GPU mode."""
    return _validate_output(output, nonce, expected, "gpuless-qualification")


def prepare_existing_display_guest_command(nonce, source, expiry):
    if not _valid_nonce(nonce) or type(source) is not bytes or not _valid_epoch(expiry):
        raise ValueError("invalid existing-display preparation input")
    sha = hashlib.sha256(source).hexdigest()
    directory = f"/var/tmp/rgpu-desktop-existing-v1-{sha[:16]}"
    src, tmp, binary = f"{directory}/desktop_existing_display.m", f"{directory}/desktop-display.{nonce}.tmp", f"{directory}/desktop-display"
    encoded = base64.b64encode(source).decode()
    q = shlex.quote
    permit = q(f"http://10.0.2.2:8889/metal-permit-{nonce}")
    return (f"( permit=$(/usr/bin/curl -fsS --max-time 3 {permit}) && test \"$permit\" = {q(nonce)} && "
            f"test $(/bin/date +%s) -le {expiry} && test ! -e {q(directory)} && /bin/mkdir -m 755 {q(directory)} && "
            f"/usr/bin/printf %s {q(encoded)} | /usr/bin/base64 -D > {q(src)} && "
            f"/usr/bin/xcrun clang -fobjc-arc -fblocks -O2 -Wall -Wextra -Werror -framework Foundation -framework CoreGraphics -framework SystemConfiguration -framework AppKit -framework QuartzCore -framework Metal {q(src)} -o {q(tmp)} && "
            f"/bin/chmod 755 {q(tmp)} && /usr/bin/codesign --force --sign - --timestamp=none {q(tmp)} && /usr/bin/codesign --verify --strict {q(tmp)} && /bin/mv {q(tmp)} {q(binary)} && "
            f"sha=$(/usr/bin/shasum -a 256 {q(binary)} | /usr/bin/awk '{{print $1}}') && /usr/bin/printf 'RGPU_DESKTOP_EXISTING_PREPARE {{\"schema\":1,\"nonce\":\"{nonce}\",\"source_sha256\":\"{sha}\",\"binary_sha256\":\"%s\",\"guest_binary\":\"{binary}\",\"compiled\":true}}\\n' \"$sha\"; rc=$?; /usr/bin/printf '\\nRGPU_EXIT {nonce} %s\\n' \"$rc\" )")


def existing_display_guest_command(nonce, expiry, hold_seconds, *, guest_binary,
                                    source_sha256, binary_sha256, registry_id,
                                    expected_width, expected_height, expected_refresh):
    if (not _valid_nonce(nonce) or not _valid_epoch(expiry) or type(hold_seconds) is not int or
            not 1 <= hold_seconds <= 30 or not _valid_sha(source_sha256) or not _valid_sha(binary_sha256) or
            not isinstance(guest_binary, str) or type(registry_id) is not int or registry_id <= 0 or
            type(expected_width) is not int or type(expected_height) is not int or
            not isinstance(expected_refresh, (int, float)) or expected_width <= 0 or expected_height <= 0):
        raise ValueError("invalid existing-display runtime input")
    label = f"com.raphael.desktop.existing.{nonce}"; d = f"/var/tmp/rgpu-desktop-existing-run-{nonce}"
    out = f"{d}/result.txt"; plist = f"{d}/{label}.plist"; q = shlex.quote
    args = [guest_binary, "existing-display-production", nonce, str(expiry), str(hold_seconds), str(registry_id), str(expected_width), str(expected_height), str(expected_refresh), out, source_sha256, binary_sha256]
    escaped = "".join(f"<string>{x}</string>" for x in args)
    xml = (f'<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
           f'<key>Label</key><string>{label}</string><key>ProgramArguments</key><array>{escaped}</array>'
           '<key>RunAtLoad</key><true/><key>ProcessType</key><string>Interactive</string>'
           '<key>EnvironmentVariables</key><dict><key>RGPU_LAUNCH_DOMAIN</key><string>gui/__UID__</string></dict></dict></plist>')
    encoded = base64.b64encode(xml.replace("__UID__", "$uid").encode()).decode()
    return (f"( dir={q(d)}; mkdir -m 700 \"$dir\" && uid=$(id -u $(stat -f %Su /dev/console)) && "
            f"permit=$(/usr/bin/curl -fsS --max-time 3 {q(f'http://10.0.2.2:8889/metal-permit-{nonce}')}) && test \"$permit\" = {q(nonce)} && "
            f"test -x {q(guest_binary)} && /usr/bin/codesign --verify --strict {q(guest_binary)} && /usr/bin/printf %s {q(encoded)} | /usr/bin/base64 -D > {q(plist)} && "
            f"launchctl bootstrap \"gui/$uid\" {q(plist)} && while test ! -s {q(out)} && test $(date +%s) -le {expiry}; do sleep 1; done; test -s {q(out)} && cat {q(out)}; launchctl bootout \"gui/$uid\" {q(plist)}; rc=$?; printf '\\nRGPU_EXIT {nonce} %s\\n' \"$rc\" )")


def validate_existing_display_output(output, nonce, expected):
    result = _one_json_row(output, "RGPU_DESKTOP_EXISTING_RESULT ", "expected exactly one existing-display result")
    _require_exit(output, nonce, "existing-display probe")
    if result.get("schema") != 1 or result.get("nonce") != nonce or result.get("execution_mode") != "existing-display-production":
        raise ValueError("invalid existing-display identity")
    for key in ("source_sha256", "binary_sha256", "guest_binary", "expiry_epoch", "started_epoch", "finished_epoch", "hold_seconds", "aqua", "display", "render", "provenance", "remote_observation"):
        if key not in result: raise ValueError("invalid existing-display schema")
    if any(result.get(k) != expected.get(k) for k in ("source_sha256", "binary_sha256", "guest_binary", "expiry_epoch", "hold_seconds")):
        raise ValueError("existing-display identity mismatch")
    aqua, display, render, prov, remote = result["aqua"], result["display"], result["render"], result["provenance"], result["remote_observation"]
    if not aqua.get("ready") or aqua.get("console_uid", 0) < 500 or aqua.get("launch_domain") != f"gui/{aqua.get('console_uid')}": raise ValueError("Aqua session proof did not complete")
    if (display.get("online_ids") != [display.get("display_id")] or display.get("nsscreen_ids") != [display.get("display_id")] or display.get("screen_count") != 1 or display.get("main_display_id") != display.get("display_id") or not display.get("main") or not display.get("active") or not display.get("online") or display.get("ownership") != "preexisting" or display.get("width") != expected["expected_width"] or display.get("height") != expected["expected_height"] or display.get("expected_width") != expected["expected_width"] or display.get("expected_height") != expected["expected_height"] or abs(display.get("refresh", 0) - expected["expected_refresh"]) > .01 or abs(display.get("expected_refresh", 0) - expected["expected_refresh"]) > .01): raise ValueError("existing-display geometry/lifecycle invalid")
    counts = ("drawables_acquired", "command_buffers_submitted", "completion_callbacks_observed", "command_buffers_completed", "presentation_callbacks_observed", "presented_frames")
    if (render.get("registry_id") != expected["registry_id"] or render.get("device_name") != "AMD Radeon Navi23" or render.get("window_display_id") != display.get("display_id") or not render.get("window_visible") or any(type(render.get(k)) is not int or render[k] < 2 for k in counts) or len({render[k] for k in counts}) != 1 or render.get("last_frame", 0) <= render.get("first_frame", 0) or render.get("distinct_color_tokens") < 2 or render.get("first_color_token") != "#ff0000" or render.get("last_color_token") != "#00ffff"): raise ValueError("visible Metal render proof failed")
    if prov.get("existing_display_origin_basis") != "pinned_launch_profile" or prov.get("compositor_gpu_provenance") != "unproven" or prov.get("scanout_gpu_provenance") != "unproven" or remote.get("observed") or remote.get("frame_change_observed"): raise ValueError("provenance must remain unproven")
    return result


def _metal_test():
    path = ROOT / "tools" / "metal-test.py"
    spec = importlib.util.spec_from_file_location("metal_test_for_desktop", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_prepared(vm, manifest, deadline_epoch, registry_id, *, now=time.time,
                 runner=None, nonce_factory=None):
    """Run a card-pinned helper while leaving the card's cleanup reserve unused."""
    phase = manifest.get("desktop_phase") if isinstance(manifest, dict) else None
    required = {"schema", "hold_seconds", "cleanup_reserve_seconds",
                "source_sha256", "binary_sha256", "guest_binary",
                "require_remote_frame_change"}
    if (not isinstance(phase, dict) or set(phase) != required or
            phase.get("schema") != 1 or
            type(phase.get("hold_seconds")) is not int or
            not 1 <= phase["hold_seconds"] <= 30 or
            type(phase.get("cleanup_reserve_seconds")) is not int or
            phase["cleanup_reserve_seconds"] < 25 or
            phase.get("require_remote_frame_change") is not True or
            not _valid_sha(phase.get("source_sha256")) or
            not _valid_sha(phase.get("binary_sha256")) or
            not isinstance(phase.get("guest_binary"), str) or
            SAFE_GUEST_PATH.fullmatch(phase["guest_binary"]) is None or
            type(deadline_epoch) not in (int, float) or
            not math.isfinite(deadline_epoch) or deadline_epoch <= 0 or
            type(registry_id) is not int or
            registry_id <= 0):
        raise ValueError("invalid desktop phase manifest")
    current = now()
    if type(current) not in (int, float) or not math.isfinite(current):
        raise ValueError("invalid desktop phase clock")
    hold = phase["hold_seconds"]
    reserve = phase["cleanup_reserve_seconds"]
    if current + hold + reserve + 8 >= deadline_epoch:
        raise ValueError("insufficient time before cleanup reserve")
    expiry = int(deadline_epoch - reserve)
    factory = nonce_factory or (lambda: uuid.uuid4().hex)
    nonce = factory()
    command = guest_command(
        nonce, expiry, hold, guest_binary=phase["guest_binary"],
        source_sha256=phase["source_sha256"], binary_sha256=phase["binary_sha256"],
        registry_id=registry_id)
    runner = runner or _metal_test().run_guest_command
    phase_seconds = max(1, int(expiry - current - 1))
    timeout = min(hold + 23, phase_seconds)
    proc = runner(Path(vm), command, nonce,
                  dict(os.environ, GX_TIMEOUT=str(timeout)),
                  timeout=timeout, execution_grace=0)
    if proc.returncode:
        raise ValueError(f"desktop guest transport failed with exit {proc.returncode}")
    expected = dict(phase, expiry_epoch=expiry, registry_id=registry_id)
    return validate_output(proc.stdout, nonce, expected)
