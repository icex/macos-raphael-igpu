#!/usr/bin/env python3
"""Decode paired source tokens from actual raw-primary GtkGLArea P6 readbacks.

Sparse diagnostic readback only: not a display FPS or whole-frame integrity test.
The source must be full 3840x2160 Retina backing, uncropped and scaled to fit.
"""
import argparse
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('console_token', Path(__file__).with_name('console-token.py'))
token = importlib.util.module_from_spec(spec)
spec.loader.exec_module(token)


def read_ppm(raw):
    parts = raw.split(b'\n', 3)
    if len(parts) != 4 or parts[0] != b'P6' or parts[2] != b'255':
        raise ValueError('requires raw GL P6 header')
    try:
        w, h = map(int, parts[1].split())
    except (ValueError, TypeError):
        raise ValueError('invalid dimensions') from None
    if not (1 <= w <= 16384 and 1 <= h <= 16384) or len(parts[3]) != w * h * 3:
        raise ValueError('invalid pixel payload')
    return parts[3], w, h


def decode_frame(pixels, width, height, nonce):
    if type(width) is not int or type(height) is not int or not (1 <= width <= 16384 and 1 <= height <= 16384):
        raise ValueError('invalid viewport')
    if len(pixels) != width * height * 3:
        raise ValueError('invalid RGB payload')
    sw, sh = 3840, 2160
    scale = min(width / sw, height / sh)
    w, h = int(sw * scale + .5), int(sh * scale + .5)
    if w < 960 or h < 540:
        raise ValueError('viewport too small for conservative token sampling')
    left, top = (width - w) // 2, (height - h) // 2

    def map_point(x, y):
        px = int(left + (x + .5) * w / sw)
        py = int(top + (y + .5) * h / sh)
        if not (left <= px < left + w and top <= py < top + h):
            raise ValueError('mapped point outside content')
        return px, py

    minimum_distinct = 5
    for origin in (32, 352):
        for bit in range(160):
            x = origin + (1 + bit % 16) * 16
            y = 128 + (1 + bit // 16) * 16
            probes = {map_point(x + dx * 2, y + dy * 2)
                      for dx, dy in ((2, 2), (5, 2), (2, 5), (5, 5), (4, 4))}
            minimum_distinct = min(minimum_distinct, len(probes))
    if minimum_distinct < 4:
        raise ValueError('mapped probes lose corner redundancy')

    class MappedRGB:
        def __getitem__(self, key):
            if not isinstance(key, slice) or key.step is not None or key.start < 0 or key.stop != key.start + 3 or key.start % 3:
                raise ValueError('unsupported RGB access')
            y, x = divmod(key.start // 3, sw)
            if not (0 <= x < sw and 0 <= y < sh):
                raise ValueError('sample outside source')
            # Floor of the physical center coordinate selects the containing
            # output pixel; this is NOT a claim of reconstructing source RGB.
            px, py = map_point(x, y)
            off = (py * width + px) * 3
            return pixels[off:off + 3]

    sequence = token.decode(MappedRGB(), sw, sh, sw * 3, 3, nonce, 2)
    return dict(sequence=sequence, source_backing=[sw, sh], viewport=[width, height],
                content=[left, top, w, h], minimum_distinct_cell_probes=minimum_distinct, scope='paired token CRC at mapped GL-output samples; not whole-frame integrity or FPS')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frame', type=Path, required=True)
    p.add_argument('--nonce', required=True)
    a = p.parse_args()
    if a.frame.stat().st_size > 128 * 1024 * 1024:
        p.error('readback exceeds diagnostic bound')
    pixels, w, h = read_ppm(a.frame.read_bytes())
    print(json.dumps(decode_frame(pixels, w, h, a.nonce)))


if __name__ == '__main__':
    main()
