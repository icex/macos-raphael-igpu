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


def validate_boot_args(boot_args, data):
    values = [word for word in boot_args.split()
              if word == "rgpucr2uart" or word.startswith("rgpucr2uart=")]
    if selected(data):
        if values != ["rgpucr2uart=2"]:
            raise ValueError("rgpucr2uart=2 must appear exactly once for dedicated transport")
    elif values:
        raise ValueError("rgpucr2uart=2 requires dedicated critical replay transport")


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
