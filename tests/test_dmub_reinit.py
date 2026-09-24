import pathlib
import subprocess
import tempfile
import unittest
import hashlib
import re
import json


class DmubReinitTests(unittest.TestCase):
    def test_bounds_protocol_and_failure_holds(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            binary = pathlib.Path(directory) / 'dmub-test'
            subprocess.run(['g++', '-std=c++14', '-Wall', '-Wextra', '-Werror',
                            str(root / 'tests/test_dmub_reinit.cpp'), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_embedded_payloads_match_review_hashes(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        text = (root / 'src/DmubReinitPayload.hpp').read_text()
        blocks = re.findall(r'// SHA256 ([0-9a-f]{64})\nstatic const uint32_t (\w+)\[\] = \{(.*?)\};', text, re.S)
        self.assertEqual([name for _, name, _ in blocks], ['Code', 'Bios'])
        manifest = json.loads((root / 'findings/research/dmcub-reinit-review-20260924.json').read_text())
        pinned = {'Code': manifest['firmware']['payload_sha256'], 'Bios': manifest['vbios']['sha256']}
        for expected, name, body in blocks:
            self.assertEqual(expected, pinned[name])
            data = b''.join(int(word, 16).to_bytes(4, 'little')
                            for word in re.findall(r'0x([0-9a-f]{8})u', body))
            self.assertEqual(hashlib.sha256(data).hexdigest(), expected)
            self.assertEqual(len(data), {'Code': 238880, 'Bios': 44544}[name])

    def test_signed_payload_matches_linux_file_slice(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        text = (root / 'src/DmubPspPayload.hpp').read_text()
        expected = re.search(r'SHA256 ([0-9a-f]{64})', text).group(1)
        data = b''.join(int(x,16).to_bytes(4,'little') for x in re.findall(r'0x([0-9a-f]{8})u',text))
        self.assertEqual(len(data),239392)
        self.assertEqual(hashlib.sha256(data).hexdigest(),expected)
        code = (root/'src/DmubReinitPayload.hpp').read_text().split('static const uint32_t Code[] = {')[1].split('};')[0]
        payload = b''.join(int(x,16).to_bytes(4,'little') for x in re.findall(r'0x([0-9a-f]{8})u',code))
        self.assertEqual(data[256:-256],payload)
