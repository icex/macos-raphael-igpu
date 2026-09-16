#!/usr/bin/env python3
"""Capture bounded QEMU HMP screendumps for a visible color transition."""
import argparse, hashlib, json, math, os, socket, struct, time
from pathlib import Path

def dominant(path, color, geometry, tolerance=12, fraction=.70):
    # QEMU HMP screendump emits binary PPM (P6); parse it without guest packages.
    data=Path(path).read_bytes(); offset=0; tokens=[]
    for _ in range(4):
        while offset<len(data) and data[offset] in b' \t\r\n': offset+=1
        start=offset
        while offset<len(data) and data[offset] not in b' \t\r\n': offset+=1
        tokens.append(data[start:offset])
    if tokens[0]!=b'P6' or tokens[3]!=b'255' or offset>=len(data) or data[offset] not in b' \t\r\n': return False
    offset+=1
    try: width,height=int(tokens[1]),int(tokens[2])
    except ValueError: return False
    pixels=data[offset:]
    if (width,height)!=geometry or len(pixels)!=width*height*3: return False
    x0,y0,x1,y1=width//4,height//4,3*width//4,3*height//4; count=0
    for y in range(y0,y1):
        for x in range(x0,x1):
            p=pixels[(y*width+x)*3:(y*width+x+1)*3]
            count += all(abs(p[i]-color[i]) <= tolerance for i in range(3))
    return count >= int((x1-x0)*(y1-y0)*fraction)

def receive_until(channel, marker, deadline):
    data=b''
    while marker not in data:
        remaining=deadline-time.time()
        if remaining <= 0: raise TimeoutError('absolute screendump deadline elapsed')
        channel.settimeout(min(2,remaining)); chunk=channel.recv(4096)
        if not chunk: raise RuntimeError('monitor disconnected')
        data += chunk
        if len(data)>65536: raise RuntimeError('monitor response overflow')
    return data

def screendump(socket_path, container_path, deadline):
    with socket.socket(socket.AF_UNIX) as channel:
        remaining=deadline-time.time()
        if remaining <= 0: raise TimeoutError('absolute screendump deadline elapsed')
        channel.settimeout(min(2,remaining)); channel.connect(socket_path)
        pid,_,_=struct.unpack('3i',channel.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
        if pid <= 0 or not os.path.basename(os.readlink(f'/proc/{pid}/exe')).startswith('qemu-system-'):
            raise RuntimeError('monitor peer is not QEMU in this container')
        receive_until(channel,b'(qemu)',deadline)
        channel.sendall(f'screendump {container_path}\n'.encode())
        reply=receive_until(channel,b'(qemu)',deadline)
        if b'Error' in reply or b'error' in reply: raise RuntimeError('QEMU screendump failed')

def main():
    p=argparse.ArgumentParser(); p.add_argument('--host-dir',type=Path,required=True)
    p.add_argument('--nonce',required=True); p.add_argument('--deadline',type=float,required=True)
    p.add_argument('--width',type=int,required=True); p.add_argument('--height',type=int,required=True)
    a=p.parse_args(); geometry=(a.width,a.height); found=[]; index=0
    if not (len(a.nonce)==32 and all(c in '0123456789abcdef' for c in a.nonce)): p.error('invalid nonce')
    if a.host_dir.resolve()!=Path('/run/vm') or not (320<=a.width<=4096 and 200<=a.height<=2160) or not math.isfinite(a.deadline): p.error('invalid capture boundary')
    while time.time() < a.deadline and len(found)<2:
        index += 1; name=f'desktop-qemu-{a.nonce}-{index:03d}.ppm'; host=a.host_dir/name
        if os.path.lexists(host): raise RuntimeError('frozen screendump path exists')
        screendump('/run/vm/monitor.sock',f'/run/vm/{name}',a.deadline)
        if not host.is_file(): raise RuntimeError('QEMU did not create requested screendump')
        color=(255,0,0) if not found else (0,255,255)
        if dominant(host,color,geometry): found.append({'path':name,'epoch':time.time(),'sha256':hashlib.sha256(host.read_bytes()).hexdigest()})
        remaining=a.deadline-time.time()
        if remaining>0: time.sleep(min(.2,remaining))
    if len(found)!=2: raise RuntimeError('expected red-to-cyan QEMU frames absent')
    print(json.dumps({'schema':1,'nonce':a.nonce,'source':'exact-container-qemu-hmp-screendump',
                      'geometry':[a.width,a.height],'frames':found},sort_keys=True))
if __name__=='__main__': main()
