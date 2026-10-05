#!/usr/bin/env python3
"""Exercise stock QEMU's Bochs console without a guest OS, KVM or physical GPU.

Uses qtest to model the guest PCI/MMIO writes; QMP screendump is the pixel oracle.
This qualifies the console transport only, never macOS rendering or acceleration.
"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time


class Channel:
    def __init__(self, path, process):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(10)
        deadline = time.monotonic() + 10
        while True:
            try:
                self.socket.connect(str(path))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('QEMU channel unavailable')
                time.sleep(.02)
        self.file = self.socket.makefile('rwb', buffering=0)

    def line(self, text):
        self.file.write(text.encode() + b'\n')
        reply = self.file.readline().decode().strip()
        if not reply:
            raise RuntimeError('QEMU channel closed')
        return reply

    def close(self):
        self.file.close()
        self.socket.close()


def run(qemu):
    with tempfile.TemporaryDirectory(prefix='rgpu-console-') as temp:
        root = Path(temp)
        with (root/'qemu.log').open('w+') as log:
            command = [qemu, '-machine', 'q35,accel=tcg', '-nodefaults', '-S',
                       '-m', '128M', '-vga', 'none', '-display', 'none',
                       '-device', 'bochs-display,id=console,addr=02.0,vgamem=64M',
                       '-qtest', f'unix:{root}/qtest,server=on,wait=off',
                       '-qmp', f'unix:{root}/qmp,server=on,wait=off']
            process = subprocess.Popen(command, stdout=log, stderr=log)
            channels = []
            try:
                qt = Channel(root/'qtest', process); channels.append(qt)
                qm = Channel(root/'qmp', process); channels.append(qm)
                assert 'QMP' in json.loads(qm.file.readline())

                def qmp(name, args=None):
                    qm.file.write(json.dumps({'execute': name, 'arguments': args or {}}).encode()+b'\n')
                    while True:
                        result = json.loads(qm.file.readline())
                        if 'error' in result:
                            raise RuntimeError(result['error'])
                        if 'return' in result:
                            return result['return']

                def test(line):
                    result = qt.line(line)
                    if not result.startswith('OK'):
                        raise RuntimeError(result)
                    return result

                def pci(offset, value=None):
                    test(f'outl 0xcf8 {0x80001000 + offset:#x}')
                    if value is None:
                        return int(test('inl 0xcfc').split()[1], 0)
                    test(f'outl 0xcfc {value:#x}')

                qmp('qmp_capabilities')
                identity = pci(0)
                if identity != 0x11111234:
                    raise RuntimeError(f'unexpected Bochs PCI identity {identity:#x}')
                pci(0x10, 0xe0000000); pci(0x18, 0xf0000000); pci(4, 2)
                def vbe(index, value):
                    test(f'writew {0xf0000500 + index * 2:#x} {value:#x}')
                assert int(test('readw 0xf0000500').split()[1], 0) == 0xb0c5
                frames = []
                for width, height, phase in [(640,480,0), (640,480,1), (800,600,2)]:
                    vbe(4, 0)
                    for index, value in [(1,width),(2,height),(3,32),(6,width),(8,0),(9,0)]:
                        vbe(index, value)
                    # Three color bars with phase/row-dependent changes catch BGR,
                    # stride, stale-frame and resize errors independently.
                    raw = bytearray(); rgb = bytearray()
                    for y in range(height):
                        for x in range(width):
                            color = [0,0,0]
                            color[(x * 3 // width + phase) % 3] = 255 if y % 16 < 8 else 127
                            r,g,b = color
                            raw.extend((b,g,r,0)); rgb.extend(color)
                    for offset in range(0,len(raw),32768):
                        chunk = raw[offset:offset+32768]
                        test(f'write {0xe0000000+offset:#x} {len(chunk):#x} 0x{chunk.hex()}')
                    vbe(4, 0x41)
                    path = root/f'frame-{phase}.ppm'
                    qmp('screendump', {'filename':str(path)})
                    data = path.read_bytes()
                    header = f'P6\n{width} {height}\n255\n'.encode()
                    if data != header + rgb:
                        raise RuntimeError(f'console pixels mismatch at phase {phase}')
                    frames.append({'width':width,'height':height,'phase':phase,
                                   'pixels_checked':width*height,
                                   'sha256':hashlib.sha256(data).hexdigest()})
                qmp('quit'); process.wait(timeout=10)
                return {'schema':1, 'passed':True, 'scope':'software console transport only',
                        'qemu':subprocess.check_output([qemu,'--version'],text=True).splitlines()[0],
                        'pci_identity':hex(identity), 'frames':frames,
                        'physical_gpu_opened':False}
            finally:
                for channel in channels:
                    channel.close()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
                if process.returncode:
                    log.seek(0)
                    print(log.read()[-3000:])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.qemu)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))
