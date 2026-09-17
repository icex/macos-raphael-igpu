#!/usr/bin/env python3
"""Bounded vncdotool capture worker; password is accepted only on stdin."""
import argparse
import json
from pathlib import Path
import sys
import time
import tempfile


def _dominant(path, expected):
    from PIL import Image
    image=Image.open(path).convert('RGB')
    if image.size != (1280,720): return False
    roi=image.crop((320,180,960,540))
    # RGB bytes work with both Ubuntu's Pillow and newer Pillow releases.
    channels=iter(roi.tobytes())
    pixels=list(zip(channels,channels,channels))
    return sum(all(abs(pixel[i]-expected[i]) <= 12 for i in range(3))
               for pixel in pixels) >= int(len(pixels)*0.70)


def child(first, second, deadline):
    password = sys.stdin.buffer.read(64)
    if not 1 <= len(password) <= 8 or b'\0' in password:
        raise ValueError('legacy VNC credential must be 1..8 non-NUL bytes')
    from vncdotool import api
    started = time.time()
    if deadline <= started or deadline-started > 40: raise ValueError('invalid capture deadline')
    client = api.connect('127.0.0.1::5900', password.decode('utf-8'), timeout=5)
    try:
        matched=[]
        with tempfile.TemporaryDirectory(prefix='rgpu-vnc-sample-',dir=first.parent) as temp:
            index=0
            while time.time()+1 < deadline and len(matched)<2:
                sample=Path(temp)/f'{index}.png'; index+=1
                client.captureScreen(str(sample)); observed=time.time()
                expected=(255,0,0) if not matched else (0,255,255)
                if _dominant(sample,expected):
                    target=first if not matched else second
                    with target.open('xb') as output: output.write(sample.read_bytes())
                    matched.append(observed)
                else: time.sleep(0.25)
        if len(matched)!=2: raise ValueError('expected red/cyan VNC sequence absent')
        first_epoch,second_epoch=matched
    finally:
        client.disconnect(); api.shutdown()
    print(json.dumps({'first_epoch':first_epoch,'second_epoch':second_epoch,
                      'started_epoch':started}, sort_keys=True))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--first', type=Path, required=True)
    parser.add_argument('--second', type=Path, required=True)
    parser.add_argument('--deadline', type=float, required=True)
    args=parser.parse_args()
    if not args.child:
        parser.error('bounded child invocation required')
    child(args.first,args.second,args.deadline)


if __name__ == '__main__': main()
