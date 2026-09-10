#!/usr/bin/env python3
"""Prove that one uniquely named QEMU GTK window is visible on X11."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


_X_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
_IGNORE_X_ERROR = _X_ERROR_HANDLER(lambda _display, _error: 0)


@dataclass(frozen=True)
class WindowInfo:
    window_id: str
    title: str
    wm_state: str
    states: tuple[str, ...]
    desktop: int | None
    current_desktop: int | None
    x: int
    y: int
    width: int
    height: int
    screen_width: int | None = None
    screen_height: int | None = None


@dataclass(frozen=True)
class Observation:
    ok: bool
    reason: str
    window: WindowInfo | None = None
    screenshot: str | None = None


def _run(argv: Sequence[str], env: dict[str, str], timeout: float = 2.0) -> str:
    result = subprocess.run(argv, env=env, check=False, capture_output=True,
                            text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"command failed: {argv[0]}")
    return result.stdout


def _xenv(display: str | None, authority: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if display:
        env["DISPLAY"] = display
    if authority:
        env["XAUTHORITY"] = authority
    return env


def _prop(output: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}(?:\([^)]*\))?\s*[:=]\s*(.*)$", output, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _quoted(value: str) -> str:
    match = re.search(r'"(.*)"', value)
    return match.group(1) if match else ""


def _int(value: str) -> int | None:
    match = re.search(r"-?\d+", value)
    return int(match.group()) if match else None


def client_ids(env: dict[str, str]) -> list[str]:
    output = _run(["xprop", "-root", "_NET_CLIENT_LIST"], env)
    return re.findall(r"0x[0-9a-fA-F]+", output)


def geometry(window_id: str, env: dict[str, str]) -> tuple[int, int, int, int, int, int]:
    display_name = env.get("DISPLAY", "")
    lib = ctypes.CDLL("libX11.so.6")
    lib.XOpenDisplay.restype = ctypes.c_void_p
    display = lib.XOpenDisplay(display_name.encode())
    if not display:
        raise RuntimeError("cannot open X display")
    try:
        lib.XSetErrorHandler.argtypes = [_X_ERROR_HANDLER]
        lib.XSetErrorHandler(_IGNORE_X_ERROR)
        root = ctypes.c_ulong()
        x = ctypes.c_int()
        y = ctypes.c_int()
        width = ctypes.c_uint()
        height = ctypes.c_uint()
        border = ctypes.c_uint()
        depth = ctypes.c_uint()
        lib.XGetGeometry.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                     ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                                     ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint),
                                     ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
                                     ctypes.POINTER(ctypes.c_uint)]
        if not lib.XGetGeometry(display, int(window_id, 16), ctypes.byref(root), ctypes.byref(x),
                                ctypes.byref(y), ctypes.byref(width), ctypes.byref(height),
                                ctypes.byref(border), ctypes.byref(depth)):
            raise RuntimeError("cannot query window geometry")
        root_x = ctypes.c_int()
        root_y = ctypes.c_int()
        child = ctypes.c_ulong()
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        root_window = lib.XDefaultRootWindow(display)
        lib.XDefaultScreen.argtypes = [ctypes.c_void_p]
        lib.XDefaultScreen.restype = ctypes.c_int
        lib.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XDisplayWidth.restype = ctypes.c_int
        lib.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XDisplayHeight.restype = ctypes.c_int
        screen = lib.XDefaultScreen(display)
        lib.XTranslateCoordinates.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                               ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                               ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                               ctypes.POINTER(ctypes.c_ulong)]
        if not lib.XTranslateCoordinates(display, int(window_id, 16), int(root_window),
                                          0, 0, ctypes.byref(root_x), ctypes.byref(root_y),
                                          ctypes.byref(child)):
            root_x.value, root_y.value = x.value, y.value
        return (root_x.value, root_y.value, width.value, height.value,
                lib.XDisplayWidth(display, screen), lib.XDisplayHeight(display, screen))
    finally:
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        lib.XCloseDisplay(display)


def read_window(window_id: str, env: dict[str, str]) -> WindowInfo:
    output = _run(["xprop", "-id", window_id, "WM_NAME", "_NET_WM_NAME",
                   "WM_STATE", "_NET_WM_STATE", "_NET_WM_DESKTOP"], env)
    title = _quoted(_prop(output, "_NET_WM_NAME")) or _quoted(_prop(output, "WM_NAME"))
    wm_state = "Iconic" if re.search(r"(?:IconicState|window state:\s*Iconic)", output) \
        else "Normal" if re.search(r"(?:NormalState|window state:\s*Normal)", output) else "Unknown"
    states_raw = _prop(output, "_NET_WM_STATE")
    states = tuple(re.findall(r"_NET_WM_STATE_[A-Z_]+", states_raw))
    desktop = _int(_prop(output, "_NET_WM_DESKTOP"))
    current = _int(_run(["xprop", "-root", "_NET_CURRENT_DESKTOP"], env))
    x, y, width, height, screen_width, screen_height = geometry(window_id, env)
    return WindowInfo(window_id, title, wm_state, states, desktop, current,
                      x, y, width, height, screen_width, screen_height)


def capture_window(window_id: str, destination: Path, env: dict[str, str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".gui-observation-", suffix=".png",
                                     dir=str(destination.parent))
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        _run(["import", "-window", window_id, str(temporary_path)], env, timeout=5.0)
        identify = _run(["identify", "-format", "%w %h", str(temporary_path)], env, timeout=5.0)
        dimensions = identify.split()
        if len(dimensions) != 2 or int(dimensions[0]) <= 0 or int(dimensions[1]) <= 0:
            raise RuntimeError("screenshot has zero geometry")
        os.replace(temporary_path, destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def allowed_titles(unique_title: str) -> frozenset[str]:
    # QEMU appends one of these exact status suffixes. No prefix matching is
    # allowed: a second launch or a title containing an injected suffix must not
    # satisfy the observation.
    return frozenset({f"QEMU ({unique_title})",
                      f"QEMU ({unique_title}) [Paused]",
                      f"QEMU ({unique_title}) [Running]"})


def classify_windows(windows: Sequence[WindowInfo], unique_title: str,
                     screenshot_path: str | None = None,
                     screenshot_window_id: str | None = None) -> Observation:
    matches = [w for w in windows if w.title in allowed_titles(unique_title)]
    if not matches:
        return Observation(False, "wrong-title")
    if len(matches) != 1:
        return Observation(False, "ambiguous")
    window = matches[0]
    if screenshot_window_id is not None and window.window_id != screenshot_window_id:
        return Observation(False, "capture-window-changed", window)
    if window.wm_state != "Normal" or "_NET_WM_STATE_HIDDEN" in window.states:
        return Observation(False, "hidden", window)
    if window.desktop is None or window.current_desktop is None:
        return Observation(False, "missing-desktop", window)
    if window.desktop not in (0xFFFFFFFF,) and window.desktop != window.current_desktop:
        return Observation(False, "off-desktop", window)
    if window.width <= 0 or window.height <= 0:
        return Observation(False, "zero-geometry", window)
    if window.screen_width is None or window.screen_height is None:
        return Observation(False, "missing-screen-geometry", window)
    if (window.x + window.width <= 0 or window.y + window.height <= 0 or
            window.x >= window.screen_width or window.y >= window.screen_height):
        return Observation(False, "offscreen", window)
    if not screenshot_path or not Path(screenshot_path).is_file():
        return Observation(False, "missing-screenshot", window)
    return Observation(True, "visible", window, screenshot_path)


def observe(args: argparse.Namespace) -> Observation:
    env = _xenv(args.display, args.xauthority)
    destination = Path(args.screenshot)
    if destination.exists():
        return Observation(False, "screenshot-exists")
    deadline = time.monotonic() + args.timeout
    last = Observation(False, "no-window")
    while time.monotonic() < deadline:
        try:
            ids = client_ids(env)
            windows = []
            for window_id in ids:
                try:
                    windows.append(read_window(window_id, env))
                except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                    continue
            matches = [w for w in windows if w.title in allowed_titles(args.title)]
            captured_window_id = None
            if len(matches) == 1:
                try:
                    captured_window_id = matches[0].window_id
                    capture_window(captured_window_id, destination, env)
                    # Re-enumerate all clients after capture. A destroyed/reused
                    # XID or second exact-title window must never certify a crop.
                    after = []
                    for window_id in client_ids(env):
                        try:
                            after.append(read_window(window_id, env))
                        except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                            continue
                    windows = after
                except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                    windows = []
            last = classify_windows(windows, args.title, args.screenshot, captured_window_id)
            if last.ok or last.reason in {"hidden", "off-desktop", "zero-geometry", "ambiguous"}:
                return last
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        time.sleep(args.poll)
    return last


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", required=True, help="unique QEMU name passed to -name")
    parser.add_argument("--display", default=None)
    parser.add_argument("--xauthority", default=None)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--poll", type=float, default=0.2)
    parser.add_argument("--screenshot", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0 or not math.isfinite(args.poll) or args.poll <= 0:
        parser.error("--timeout and --poll must be finite and positive")
    result = observe(args)
    payload = {"ok": result.ok, "reason": result.reason,
               "window": asdict(result.window) if result.window else None,
               "screenshot": result.screenshot}
    if result.ok and result.screenshot:
        screenshot = Path(result.screenshot)
        payload["screenshot_size"] = screenshot.stat().st_size
        payload["screenshot_mtime_ns"] = screenshot.stat().st_mtime_ns
        payload["screenshot_sha256"] = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    encoded = json.dumps(payload, sort_keys=True)
    print(encoded)
    if args.output:
        Path(args.output).write_text(encoded + "\n")
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
