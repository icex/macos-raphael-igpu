"""Check the exact AMD DMCUB payload carried through the source-header conversion."""
import hashlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DmcubFirmwareTests(unittest.TestCase):
    def test_payload_identity_and_psp_header(self):
        manifest = json.loads((ROOT / 'build-support/dmcub-firmware.json').read_text())
        source = (ROOT / 'src/DmcubFirmware.hpp').read_text()
        version = int(re.search(r'raphaelDmcubFirmwareVersion = (0x[0-9a-f]+)', source).group(1), 16)
        payload = bytes(int(x, 16) for x in re.findall(r'0x([0-9a-f]{2})', source.split('{', 1)[1]))
        self.assertEqual(len(payload), manifest['payload_size'])
        self.assertEqual(hashlib.sha256(payload).hexdigest(), manifest['payload_sha256'])
        self.assertEqual(payload[0x10:0x14], b'$PS1')
        self.assertEqual(version, int(manifest['version'], 16))
        # The DMCU service's staging buffer (_dmcub_sw_init) is 1 MiB.
        self.assertLessEqual(len(payload), 0x100000)


if __name__ == '__main__':
    unittest.main()
