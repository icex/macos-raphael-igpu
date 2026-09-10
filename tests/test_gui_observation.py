import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import argparse
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("gui_observation", ROOT / "tools/gui-observation.py")
gui = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gui
SPEC.loader.exec_module(gui)


def info(**overrides):
    values = dict(
        window_id="0x42",
        title="QEMU (run-abc) [Paused]",
        wm_state="Normal",
        states=(),
        desktop=2,
        current_desktop=2,
        x=10,
        y=20,
        width=800,
        height=600,
        screen_width=1920,
        screen_height=1080,
    )
    values.update(overrides)
    return gui.WindowInfo(**values)


class GuiObservationTests(unittest.TestCase):
  def test_wrong_title_is_unproven(self):
    result = gui.classify_windows([info(title="QEMU (other) [Paused]")], "run-abc")
    self.assertFalse(result.ok)
    self.assertEqual(result.reason, "wrong-title")

  def test_title_suffix_injection_is_unproven(self):
    result = gui.classify_windows([info(title="QEMU (run-abc) [Paused] attacker")], "run-abc")
    self.assertFalse(result.ok)
    self.assertEqual(result.reason, "wrong-title")

  def test_capture_xid_change_is_unproven(self):
    result = gui.classify_windows([info(window_id="0x43")], "run-abc", "fresh.png", "0x42")
    self.assertFalse(result.ok)
    self.assertEqual(result.reason, "capture-window-changed")


  def test_hidden_window_is_unproven(self):
    result = gui.classify_windows([info(states=("_NET_WM_STATE_HIDDEN",))], "run-abc")
    self.assertFalse(result.ok)
    self.assertEqual(result.reason, "hidden")


  def test_off_desktop_is_unproven(self):
    result = gui.classify_windows([info(desktop=1, current_desktop=2)], "run-abc")
    self.assertFalse(result.ok)
    self.assertEqual(result.reason, "off-desktop")


  def test_zero_geometry_is_unproven(self):
    result = gui.classify_windows([info(width=0)], "run-abc")
    self.assertFalse(result.ok)
    self.assertEqual(result.reason, "zero-geometry")

  def test_offscreen_window_is_unproven(self):
    result = gui.classify_windows([info(x=2000, screen_width=1920)], "run-abc", "window.png")
    self.assertFalse(result.ok)
    self.assertEqual(result.reason, "offscreen")

  def test_missing_desktop_is_unproven(self):
    result = gui.classify_windows([info(desktop=None)], "run-abc", "window.png")
    self.assertFalse(result.ok)
    self.assertEqual(result.reason, "missing-desktop")


  def test_missing_screenshot_is_unproven(self):
    result = gui.classify_windows([info()], "run-abc", screenshot_path=None)
    self.assertFalse(result.ok)
    self.assertEqual(result.reason, "missing-screenshot")


  def test_ambiguous_matching_windows_are_unproven(self):
    result = gui.classify_windows([info(), info(window_id="0x43")], "run-abc")
    self.assertFalse(result.ok)
    self.assertEqual(result.reason, "ambiguous")

  def test_existing_screenshot_path_is_unproven(self):
    with tempfile.TemporaryDirectory() as directory:
      screenshot = pathlib.Path(directory) / "old.png"
      screenshot.write_bytes(b"old evidence")
      args = argparse.Namespace(display=":0", xauthority=None, timeout=1.0,
                                poll=0.1, title="run-abc", screenshot=str(screenshot))
      result = gui.observe(args)
      self.assertFalse(result.ok)
      self.assertEqual(result.reason, "screenshot-exists")

  def test_nonfinite_timeout_is_rejected(self):
    with self.assertRaises(SystemExit):
      gui.main(["--title", "run-abc", "--timeout", "nan", "--screenshot", "/tmp/fresh.png"])

  def test_xprop_fixture_parses_equals_and_multiline_state(self):
    fixture = """WM_NAME(STRING) = \"QEMU (run-abc) [Paused]\"\nWM_STATE(WM_STATE):\n\\t\\twindow state: Normal\n\\t\\ticon window: 0x0\n_NET_WM_DESKTOP(CARDINAL) = 2\n"""
    self.assertEqual(gui._quoted(gui._prop(fixture, "WM_NAME")), "QEMU (run-abc) [Paused]")
    self.assertEqual(gui._int(gui._prop(fixture, "_NET_WM_DESKTOP")), 2)
    self.assertIn("window state: Normal", fixture)


  def test_cli_smoke_requires_live_qemu_window(self):
    if not os.environ.get("GUI_OBSERVATION_SMOKE_COMMAND"):
        self.skipTest("set GUI_OBSERVATION_SMOKE_COMMAND for the live QEMU smoke")
    command = json.loads(os.environ["GUI_OBSERVATION_SMOKE_COMMAND"])
    name = command[command.index("-name") + 1]
    proc = subprocess.Popen(command)
    try:
        with tempfile.TemporaryDirectory(prefix="gui-observation-test-") as directory:
            output = subprocess.run(
                [sys.executable, str(ROOT / "tools/gui-observation.py"),
                 "--title", name, "--timeout", "5", "--poll", "0.1",
                 "--output", str(pathlib.Path(directory) / "result.json"),
                 "--screenshot", str(pathlib.Path(directory) / "window.png")],
                check=False, text=True, capture_output=True,
            )
            self.assertEqual(output.returncode, 0, output.stderr + output.stdout)
            payload = json.loads(output.stdout)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["window"]["title"].endswith(f"({name}) [Paused]"))
            self.assertGreater((pathlib.Path(directory) / "window.png").stat().st_size, 0)
    finally:
        proc.terminate()
        proc.wait(timeout=5)
