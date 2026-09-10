import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = {
    "kind": "isa-serial", "version": 1, "index": 1,
    "io_base": 760, "baud": 115200,
    "socket": "run/critical.sock", "capture": "critical.txt"}


def module():
    path = ROOT / "tools/critical-transport.py"
    spec = importlib.util.spec_from_file_location("critical_transport_test", path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class CriticalTransportTests(unittest.TestCase):
    def test_exact_types_and_key_set_are_required(self):
        tool = module()
        card = {"critical_replay_schema": 2,
                "critical_replay_transport": TRANSPORT}
        self.assertEqual(tool.validate(card), TRANSPORT)
        for key, value in (("critical_replay_schema", 2.0),
                           ("critical_replay_schema", True)):
            bad = dict(card, **{key: value})
            with self.assertRaises(ValueError):
                tool.validate(bad)

    def test_boot_argument_presence_is_bidirectional_and_conflict_free(self):
        tool = module()
        selected = {"critical_replay_schema": 2,
                    "critical_replay_transport": TRANSPORT}
        tool.validate_boot_args("debug=1 rgpucr2uart=2", selected)
        for args in ("", "rgpucr2uart=1", "rgpucr2uart=02",
                     "rgpucr2uart", "rgpucr2uart=2 rgpucr2uart=1",
                     "rgpucr2uart=2 rgpucr2uart=2"):
            with self.assertRaises(ValueError, msg=args):
                tool.validate_boot_args(args, selected)
        for args in ("rgpucr2uart=2", "rgpucr2uart=1", "rgpucr2uart"):
            with self.assertRaises(ValueError, msg=args):
                tool.validate_boot_args(args, {"critical_replay_schema": 2})

    def test_every_incomplete_ready_prefix_remains_pending(self):
        tool = module()
        build = "a" * 32
        marker = f"RGPU_UART_READY v=1 b={build} port=2"
        for ending in ("\n", "\r\n"):
            wire = marker + ending
            for cut in range(len("RGPU_UART_READY "), len(wire)):
                self.assertEqual(tool.producer_ready_state(wire[:cut], build),
                                 "pending", (ending, cut))
        self.assertEqual(tool.producer_ready_state(marker + "\n", build), "valid")
        self.assertEqual(tool.producer_ready_state(marker + "\r\n", build), "valid")
        self.assertEqual(tool.producer_ready_state(
            marker.replace("port=2", "port=1") + "\n", build), "conflicting")


if __name__ == "__main__":
    unittest.main()
