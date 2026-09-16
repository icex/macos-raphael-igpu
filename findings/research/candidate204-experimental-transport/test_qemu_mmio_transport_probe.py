import importlib.util
import socket
import unittest
import time
from pathlib import Path

PATH = Path(__file__).parents[1] / "tools" / "qemu-mmio-transport-probe.py"
spec = importlib.util.spec_from_file_location("probe", PATH)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class TransportProbeTests(unittest.TestCase):
    def test_edu_bar_is_one_megabyte(self):
        self.assertEqual(probe.BAR_SIZE, 0x100000)
    def test_rsp_frame_checksum(self):
        self.assertEqual(probe.frame("m10000004,4"), b"$m10000004,4#52")

    def test_rsp_bad_checksum_rejected(self):
        with self.assertRaises(ValueError): probe.parse_frame(b"$OK#00")

    def test_rsp_error_payload_is_preserved(self):
        payload = b"E14"
        self.assertEqual(probe.parse_frame(b"$E14#" + probe.checksum(payload).encode()), "E14")

    def test_rsp_fragmented_reply_and_ack(self):
        class Fake:
            def __init__(self): self.parts=[b"+", b"$OK#", probe.checksum(b"OK").encode()]; self.sent=[]
            def settimeout(self, value): pass
            def sendall(self, value): self.sent.append(value)
            def recv(self, size): return self.parts.pop(0) if self.parts else b""
        fake=Fake(); result=probe.RSP(fake, time.monotonic()+1).command("c")
        self.assertEqual(result,"OK"); self.assertEqual(fake.sent[-1],b"+")

    def test_mmio_bounds_are_fixed_to_edu_bar(self):
        probe.check_range(probe.BAR_GPA + 4, 4)
        with self.assertRaises(ValueError): probe.check_range(probe.BAR_GPA - 1, 4)
        with self.assertRaises(ValueError): probe.check_range(probe.BAR_GPA + probe.BAR_SIZE - 1, 4)

    def test_qemu_command_is_fixed_tcg_edu_and_no_passthrough(self):
        source = PATH.read_text()
        self.assertIn('"-accel","tcg"', source)
        self.assertIn('"-device","edu,id=edu0,bus=pcie.0,addr=4.0"', source)
        self.assertNotIn("vfio-pci", source)
        self.assertNotIn("--device", source)

    def test_qtest_uses_cf8_cfc_configuration(self):
        source = PATH.read_text()
        self.assertIn("outl 0xcf8 0x80002010", source)
        self.assertIn("outw 0xcfc 0x0002", source)

if __name__ == "__main__": unittest.main()
