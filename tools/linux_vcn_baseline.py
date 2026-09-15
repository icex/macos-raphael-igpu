#!/usr/bin/env python3
"""Bounded native Linux VCN baseline; entered through cycle.py linux-vcn."""
import argparse, hashlib, json, os, re, signal, subprocess, sys, time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
BDF='0000:7b:00.0'
DEV=Path('/sys/bus/pci/devices')/BDF
NODE='/dev/dri/renderD129'

def identity(expected):
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    assert boot==expected, 'boot changed'
    assert (DEV/'vendor').read_text().strip()=='0x1002'
    assert (DEV/'device').read_text().strip()=='0x13c0'
    assert (DEV/'driver').resolve().name=='amdgpu', 'Linux binding required'
    assert (DEV/'power/control').read_text().strip()=='on', 'power not pinned'
    assert Path('/sys/class/drm/renderD129/device').resolve()==DEV.resolve(), 'wrong render node'
    return dict(boot_id=boot,bdf=BDF,driver='amdgpu',render_node=NODE,power_control='on',kernel=os.uname().release)

def pattern():
    y,x=np.indices((720,1280))
    return np.stack([(32+40*(x>=640)+80*(y>=360)+5*n).astype('uint8') for n in range(3)])

def validate(path):
    data=np.fromfile(path,dtype=np.uint8)
    expected=pattern(); framebytes=1280*720*3//2
    if data.size!=3*framebytes: return dict(passed=False,bytes=int(data.size),frames=data.size//framebytes)
    y=data.reshape(3,framebytes)[:,:1280*720].reshape(3,720,1280)
    yy,xx=np.indices((720,1280)); mask=(xx>=4)&(xx<1276)&(yy>=4)&(yy<716)&(abs(xx-640)>=4)&(abs(yy-360)>=4)
    error=np.abs(y.astype('int16')-expected.astype('int16'))[:,mask]
    return dict(passed=bool(error.max()<=8),frames=3,max_luma_error=int(error.max()),values_checked=int(error.size))

TRACE=r'''
set -eu
p=/tracing/instances/$TRACE_NAME
mkdir "$p"
cleanup() {
 if [ -n "${drain:-}" ]; then kill "$drain" 2>/dev/null || true; wait "$drain" 2>/dev/null || true; fi
 echo 0 > "$p/tracing_on"
 echo 0 > "$p/events/enable"
 for f in "$p"/per_cpu/cpu*/stats; do echo "$f"; cat "$f"; done > /out/trace-stats.txt
 rmdir "$p"
}
trap cleanup EXIT
trap 'exit 0' TERM INT
 echo 4096 > "$p/buffer_size_kb"
 for e in amdgpu_device_rreg amdgpu_device_wreg; do
 echo 'did == 0x13c0' > "$p/events/amdgpu/$e/filter"
 echo 1 > "$p/events/amdgpu/$e/enable"
 done
 for e in amdgpu_cs_ioctl amdgpu_sched_run_job amdgpu_vm_flush; do echo 1 > "$p/events/amdgpu/$e/enable"; done
 echo 1 > "$p/tracing_on"
 touch /out/trace-ready
 timeout 5900 cat "$p/trace_pipe" &
 drain=$!
 wait "$drain"
'''

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--boot-id',required=True);ap.add_argument('--output',required=True);ap.add_argument('--worker',action='store_true');a=ap.parse_args()
    out=Path(a.output).resolve()
    if not a.worker:
        identity(a.boot_id)
        assert not out.exists(), 'output already exists'
        assert a.boot_id in (ROOT/'status.md').read_text(), 'status allowance missing'
        subprocess.run([sys.executable,'-B','-m','unittest','discover','-s','tests'],cwd=ROOT,check=True,stdout=open(str(out)+'-tests.log','w'),stderr=subprocess.STDOUT)
        name='rgpu-linux-'+a.boot_id[:8]
        cmd=['systemd-run','--user','--wait','--collect','--unit='+name,'--property=RuntimeMaxSec=6000s','--property=TimeoutStopSec=20s','--property=KillMode=control-group','--property=ExecStopPost=-/usr/bin/docker stop -t 5 '+name,'systemd-inhibit','--what=idle:sleep','--mode=block','--why=Raphael Linux VCN baseline',sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--boot-id',a.boot_id,'--output',str(out)]
        return subprocess.run(cmd).returncode
    out.mkdir()
    facts=identity(a.boot_id); (out/'host-before.json').write_text(json.dumps(facts,indent=2))
    name='rgpu-linux-'+a.boot_id[:8]; started=time.time(); records=[]; capture=None; active=None; kernelmon=None
    def stop(sig,frame): raise SystemExit('termination requested')
    signal.signal(signal.SIGTERM,stop)
    def save(): (out/'commands.json').write_text(json.dumps(records,indent=2))
    def run(label,cmd,limit=90,required=True):
        nonlocal active
        identity(a.boot_id)
        rec=dict(label=label,command=cmd,start=time.time());records.append(rec);save()
        with (out/(label+'.stdout')).open('wb') as stdout,(out/(label+'.stderr')).open('wb') as stderr:
            active=subprocess.Popen(cmd,stdout=stdout,stderr=stderr)
            deadline=time.monotonic()+limit
            try:
                while active.poll() is None:
                    if capture is not None and capture.poll() is not None: raise RuntimeError('trace capture exited')
                    if kernelmon is not None:
                        if kernelmon.poll() is not None: raise RuntimeError('kernel capture exited')
                        tail=(out/'kernel-live.txt').read_text(errors='replace')
                        if re.search(r'BUG:|GPU reset|amdgpu_job_timedout|ring .*timeout|GPU fault',tail,re.I):
                            raise RuntimeError('host fault reported; stopping workloads')
                    if time.monotonic()>deadline or time.time()-started>5800: raise RuntimeError('workload deadline')
                    if (out/'stop-requested').exists(): raise RuntimeError('manual stop')
                    time.sleep(.1)
                rec.update(exit=active.returncode,end=time.time());save()
            finally:
                if active.poll() is None:
                    active.terminate()
                    try: active.wait(5)
                    except subprocess.TimeoutExpired: active.kill();active.wait(5)
                active=None
        if required and rec['exit']: raise RuntimeError(label+' failed')
        return rec['exit']
    summary=dict(functional=[],capture='pending',cleanup='pending')
    try:
        run('boot-kernel',['journalctl','-b','-k','--no-pager','-o','short-monotonic'])
        kernelmon=subprocess.Popen(['journalctl','-b','-k','-f','-n','0','--no-pager','-o','short-monotonic'],stdout=(out/'kernel-live.txt').open('wb'),stderr=(out/'kernel-live.stderr').open('wb'))
        run('versions',['ffmpeg','-version'])
        run('packages',['pacman','-Q','mesa','libva','libva-mesa-driver','linux-firmware-amdgpu'],required=False)
        run('debug-before',['docker','run','--rm','--privileged','-v','/sys/kernel/debug:/debug','alpine:latest','sh','-c','for f in amdgpu_firmware_info amdgpu_pm_info amdgpu_fence_info; do echo "$f"; cat /debug/dri/0000:7b:00.0/$f; done'])
        traceout=(out/'register-trace.txt').open('wb',buffering=0);traceerr=(out/'trace.stderr').open('wb',buffering=0)
        capture=subprocess.Popen(['docker','run','--rm','--name',name,'--privileged','-e','TRACE_NAME='+name,'-v','/sys/kernel/tracing:/tracing','-v',str(out)+':/out','alpine:latest','sh','-c',TRACE],stdout=traceout,stderr=traceerr)
        for _ in range(100):
            if (out/'trace-ready').exists(): break
            if capture.poll() is not None: raise RuntimeError('trace setup failed')
            time.sleep(.1)
        else: raise RuntimeError('trace readiness timeout')
        run('vainfo',['vainfo','--display','drm','--device',NODE])
        with (out/'input.nv12').open('wb') as f:
            for y in pattern(): f.write(y.tobytes());f.write(bytes([128])*(1280*720//2))
        for codec,sw in [('h264','libx264'),('hevc','libx265')]:
            for kind in ['sw','hw','hw-repeat']:
                label=codec+'-'+kind;target=out/(label+'.mkv');hardware=kind!='sw'
                cmd=['ffmpeg','-hide_banner','-loglevel','verbose','-nostdin','-y']
                if hardware: cmd+=['-vaapi_device',NODE]
                cmd+=['-f','rawvideo','-pixel_format','nv12','-video_size','1280x720','-framerate','30','-i',str(out/'input.nv12'),'-frames:v','3','-an']
                cmd+=['-vf','format=nv12,hwupload','-c:v',codec+'_vaapi','-qp','20'] if hardware else ['-c:v',sw,'-crf','18','-threads','2']
                if codec=='hevc' and not hardware: cmd+=['-x265-params','pools=2:frame-threads=1']
                cmd+=['-bf','0',str(target)]
                rc=run(label,cmd,required=False)
                entry=dict(codec=codec,mode=kind,encode_exit=rc);summary['functional'].append(entry)
                if rc: continue
                run(label+'-stream',['ffprobe','-v','error','-count_frames','-show_streams','-of','json',str(target)])
                for decode in (['sw','hw'] if hardware else ['sw']):
                    raw=out/(label+'-'+decode+'.nv12')
                    cmd=['ffmpeg','-hide_banner','-loglevel','verbose','-nostdin','-y']
                    if decode=='hw':cmd+=['-hwaccel','vaapi','-hwaccel_device',NODE,'-hwaccel_output_format','vaapi']
                    cmd+=['-i',str(target)]
                    if decode=='hw': cmd+=['-vf','hwdownload,format=nv12']
                    cmd+=['-pix_fmt','nv12','-f','rawvideo',str(raw)]
                    rc=run(label+'-decode-'+decode,cmd,required=False)
                    entry['decode_'+decode]=validate(raw) if rc==0 else dict(passed=False,exit=rc)
                (out/'result.json').write_text(json.dumps(summary,indent=2))
                time.sleep(2)
        summary['capture']='complete-to-workload-end'
    except BaseException as error:
        summary['error']=str(error);summary['capture']='incomplete'
    finally:
        subprocess.run(['docker','stop','-t','5',name],capture_output=True,timeout=15)
        if kernelmon is not None:
            kernelmon.terminate();kernelmon.wait(timeout=5)
        if capture is not None:
            capture.wait(timeout=10);traceout.close();traceerr.close()
        try:
            summary['host_after']=identity(a.boot_id);summary['cleanup']='workloads stopped; amdgpu retained'
            subprocess.run(['journalctl','-b','-k','--no-pager','-o','short-monotonic'],stdout=(out/'kernel-after.txt').open('w'),timeout=20,check=True)
        except Exception as error: summary['cleanup']=str(error)
        summary['end']=time.time();(out/'result.json').write_text(json.dumps(summary,indent=2))
        hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
        (out/'sha256.json').write_text(json.dumps(hashes,indent=2))
    return 1 if 'error' in summary else 0
if __name__=='__main__':sys.exit(main())
