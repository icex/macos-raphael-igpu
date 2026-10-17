"""Positive/negative paired-token controls after viewport scaling and letterboxing."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('gl_token', Path(__file__).resolve().parents[1] / 'tools/console-gl-token.py')
gl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gl)
NONCE = '442a0123456789ab'


def frame(width, height, sequence=123, second=None):
    # Independent inverse pixel-center mapping: fill the whole output token
    # cells, rather than just the decoder's sampled positions.
    scale = min(width / 3840, height / 2160)
    w, h = int(3840 * scale + .5), int(2160 * scale + .5)
    left, top = (width - w) // 2, (height - h) // 2
    pixels = bytearray(width * height * 3)
    for sx, seq in ((32, sequence), (352, sequence if second is None else second)):
        packet = gl.token.packet(NONCE, seq)
        for py in range(top, top + h):
            sy = (py - top + .5) * 2160 / h
            row = int((sy - 128) // 16)
            if not 0 <= row < 12:
                continue
            for px in range(left, left + w):
                source_x = (px - left + .5) * 3840 / w
                col = int((source_x - sx) // 16)
                if not 0 <= col < 18:
                    continue
                if row in (0, 11) or col in (0, 17):
                    rgb = b'\xff\x00\xff'
                else:
                    bit = (row - 1) * 16 + col - 1
                    value = 255 if packet[bit // 8] >> (7 - bit % 8) & 1 else 0
                    rgb = bytes((value, value, value))
                off = (py * width + px) * 3
                pixels[off:off + 3] = rgb
    return pixels


class GLTokenTests(unittest.TestCase):
    def test_scaled_and_letterboxed_paired_tokens(self):
        for size in ((1440, 900), (1280, 800), (1920, 1080), (1101, 703)):
            with self.subTest(size=size):
                result = gl.decode_frame(frame(*size), *size, NONCE)
                self.assertEqual(result['sequence'], 123)
                self.assertGreaterEqual(result['minimum_distinct_cell_probes'], 4)

    def test_duplicate_disagreement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'torn duplicate'):
            gl.decode_frame(frame(1440, 900, second=124), 1440, 900, NONCE)

    def test_wrong_nonce_and_missing_border_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'identity'):
            gl.decode_frame(frame(1440, 900), 1440, 900, '0000000000000000')
        with self.assertRaisesRegex(ValueError, 'border'):
            gl.decode_frame(bytes(1440 * 900 * 3), 1440, 900, NONCE)

    def test_malformed_payload_and_small_viewport_are_rejected(self):
        for raw in (b'P6\n1 1\n255\nxx', b'P6\n1 1\n254\nxxx', b'P6\n-1 2\n255\n'):
            with self.assertRaises(ValueError):
                gl.read_ppm(raw)
        with self.assertRaisesRegex(ValueError, 'small'):
            gl.decode_frame(bytes(640 * 480 * 3), 640, 480, NONCE)
        self.assertEqual(gl.read_ppm(b'P6\n1 1\n255\n\x0a\x20\x00'), (b'\x0a\x20\x00', 1, 1))
