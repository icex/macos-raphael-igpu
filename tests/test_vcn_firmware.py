"""Check the exact AMD payload carried through the source-header conversion."""
import hashlib
import json
from pathlib import Path
import re
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]

class VcnFirmwareTests(unittest.TestCase):
    def test_payload_identity_and_native_header(self):
        manifest = json.loads((ROOT / 'build-support/vcn-firmware.json').read_text())
        source = (ROOT / 'src/VcnFirmware.hpp').read_text().split('{', 1)[1]
        payload = bytes(int(x, 16) for x in re.findall(r'0x([0-9a-f]{2})', source))
        self.assertEqual(len(payload), manifest['payload_size'])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest['payload_sha256'])
        self.assertEqual(payload[0xa0:0xa4], b'AMD@')
        self.assertEqual(struct.unpack_from('<I', payload, 0x60)[0], int(manifest['version'], 16))
        self.assertLessEqual(len(payload), 0x100000)
