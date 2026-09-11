#!/usr/bin/env python3
"""Exact manifest contract for the opt-in dedicated CR2 UART transport."""

import re

TRANSPORT = {
    "kind": "isa-serial",
    "version": 1,
    "index": 1,
    "io_base": 760,
    "baud": 115200,
    "socket": "run/critical.sock",
    "capture": "critical.txt",
}
QUIESCE = {"version": 1}


def validate(data):
    if "critical_replay_transport" not in data:
        return None
    value = data["critical_replay_transport"]
    if (type(value) is not dict or set(value) != set(TRANSPORT) or
            any(type(value[key]) is not type(expected) or value[key] != expected
                for key, expected in TRANSPORT.items())):
        raise ValueError("critical replay transport must match the dedicated COM2 contract")
    if type(data.get("critical_replay_schema")) is not int or data.get(
            "critical_replay_schema") != 2:
        raise ValueError("critical replay transport requires schema 2")
    return dict(TRANSPORT)


def selected(data):
    return validate(data) is not None


def quiesce(data):
    if "critical_replay_quiesce" not in data:
        return None
    value = data["critical_replay_quiesce"]
    if (type(value) is not dict or set(value) != {"version"} or
            type(value.get("version")) is not int or value["version"] != 1):
        raise ValueError("critical replay quiesce must match the version-1 contract")
    if not selected(data):
        raise ValueError("critical replay quiesce requires dedicated COM2 transport")
    return dict(QUIESCE)


def validate_boot_args(boot_args, data):
    values = [word for word in boot_args.split()
              if word == "rgpucr2uart" or word.startswith("rgpucr2uart=")]
    if selected(data):
        if values != ["rgpucr2uart=2"]:
            raise ValueError("rgpucr2uart=2 must appear exactly once for dedicated transport")
    elif values:
        raise ValueError("rgpucr2uart=2 requires dedicated critical replay transport")
    quiesce_values = [word for word in boot_args.split()
                      if word == "rgpucr2quiesce" or
                      word.startswith("rgpucr2quiesce=")]
    if quiesce(data) is not None:
        if quiesce_values != ["rgpucr2quiesce=1"]:
            raise ValueError(
                "rgpucr2quiesce=1 must appear exactly once for producer quiesce")
    elif quiesce_values:
        raise ValueError(
            "rgpucr2quiesce=1 requires the critical replay quiesce contract")


def producer_ready_state(capture, expected_build):
    if not isinstance(capture, str) or not re.fullmatch(r"[0-9a-f]{32}", expected_build):
        return "conflicting"
    expected = f"RGPU_UART_READY v=1 b={expected_build} port=2"
    complete = []
    pending = False
    for line in capture.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if body.startswith("RGPU_UART_READY "):
            if line.endswith("\n"):
                complete.append(body)
            else:
                pending = True
    if complete and complete != [expected]:
        return "conflicting"
    if pending:
        return "pending"
    if complete == [expected]:
        return "valid"
    return "absent"


def quiesced_state(capture, expected_build):
    if not isinstance(capture, str) or not re.fullmatch(r"[0-9a-f]{32}", expected_build):
        return {"state": "conflicting"}
    prefix = "RGPU_UART_QUIESCED "
    pattern = re.compile(
        r"RGPU_UART_QUIESCED v=1 b=([0-9a-f]{32}) "
        r"s=([0-9a-f]{8}) count=([0-9a-f]{4})")
    complete = []
    nonempty = []
    pending = False
    for line in capture.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if body:
            nonempty.append(body)
        if body.startswith(prefix):
            if line.endswith("\n"):
                complete.append(body)
            else:
                pending = True
    if pending and not complete:
        return {"state": "pending"}
    if pending or len(complete) != 1 or not nonempty or nonempty[-1] != complete[0]:
        return {"state": "conflicting" if complete else "absent"}
    match = pattern.fullmatch(complete[0])
    if match is None or match[1] != expected_build:
        return {"state": "conflicting"}
    snapshot, count = int(match[2], 16), int(match[3], 16)
    if count > 512:
        return {"state": "conflicting"}
    return {"state": "valid", "snapshot": snapshot, "count": count}
