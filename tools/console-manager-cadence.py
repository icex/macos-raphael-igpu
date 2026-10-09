#!/usr/bin/env python3
"""Sample the actual virt-manager SpiceDisplay buffer; opens no second connection."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manager-prefix',type=Path,required=True,help='extracted package root/usr')
    parser.add_argument('--nonce',required=True)
    parser.add_argument('--output',type=Path,required=True,help='new JSONL raw-sample file')
    parser.add_argument('--seconds',type=int,default=30)
    parser.add_argument('--interval-ms',type=int,default=16)
    parser.add_argument('--wait-seconds',type=int,default=60)
    parser.add_argument('manager_args',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    if len(args.nonce)!=16 or any(c not in '0123456789abcdefABCDEF' for c in args.nonce):parser.error('nonce needs16 hex digits')
    if not 1<=args.seconds<=120 or not 8<=args.interval_ms<=1000 or not 1<=args.wait_seconds<=120:parser.error('bounded duration/interval required')
    prefix=args.manager_prefix.resolve()
    # Native typelib dependencies require the dynamic loader paths at exec time.
    if os.environ.get('RGPU_CADENCE_PREFIX')!=str(prefix):
        environment=dict(os.environ,RGPU_CADENCE_PREFIX=str(prefix))
        for name,value in [('LD_LIBRARY_PATH',str(prefix/'lib')),('GI_TYPELIB_PATH',str(prefix/'lib/girepository-1.0'))]:
            environment[name]=value+(':'+environment[name] if environment.get(name) else '')
        os.execve(sys.executable,[sys.executable,*sys.argv],environment)
    sys.path[:0]=[str(prefix/'share/virt-manager'),str(prefix/f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')]
    os.environ['GSETTINGS_SCHEMA_DIR']=str(prefix/'share/glib-2.0/schemas')
    os.environ['GSETTINGS_BACKEND']='keyfile'
    for name,leaf in [('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('XDG_DATA_HOME','data')]:
        os.environ[name]=str(args.output.parent/('manager-cadence-'+leaf))
    spec=importlib.util.spec_from_file_location('token',Path(__file__).with_name('console-token.py'))
    token=importlib.util.module_from_spec(spec);spec.loader.exec_module(token)
    import gi
    gi.require_version('Gtk','3.0');gi.require_version('SpiceClientGtk','3.0')
    from gi.repository import Gtk,GLib,SpiceClientGtk
    stream=args.output.open('x');summary_path=Path(str(args.output)+'.summary.json')
    if summary_path.exists():stream.close();raise ValueError('summary already exists')
    tracker=token.SequenceTracker();began=time.monotonic();first=None;last_unique=None
    unique=0;invalid=0;duplicates=0;max_stale=0.;max_sample=0.;finished=False
    def record(data):stream.write(json.dumps(data)+'\n');stream.flush()
    record(dict(event='start',nonce=args.nonce,seconds=args.seconds,interval_ms=args.interval_ms,
                scope='sampled decoded manager buffer only; no host scanout or absolute latency'))
    def finish(reason):
        nonlocal finished
        if finished:return
        finished=True
        elapsed=0 if first is None else time.monotonic()-first
        summary=dict(reason=reason,nonce=args.nonce,unique=unique,duplicates=duplicates,invalid=invalid,
                     elapsed=elapsed,sampled_unique_per_second=unique/elapsed if elapsed else None,
                     max_observed_stale_seconds=max_stale,max_sampling_seconds=max_sample,
                     scope='Sampling lower bound; full pixbuf copying may reduce measured throughput. No GPU FPS, host scanout, or absolute latency claim.')
        record(dict(event='finish',**summary));summary_path.write_text(json.dumps(summary,indent=2)+'\n');stream.close()
    def displays():
        found=[]
        def visit(widget):
            if isinstance(widget,SpiceClientGtk.Display):found.append(widget)
            if isinstance(widget,Gtk.Container):
                for child in widget.get_children():visit(child)
        for window in Gtk.Window.list_toplevels():visit(window)
        return found
    def poll():
        nonlocal first,last_unique,unique,invalid,duplicates,max_stale,max_sample
        now=time.monotonic()
        if first is not None and now-first>=args.seconds:finish('completed');return False
        if first is None and now-began>=args.wait_seconds:finish('no-valid-token');return False
        if last_unique is not None:max_stale=max(max_stale,now-last_unique)
        sample=dict(event='sample',host_monotonic=now)
        try:
            candidates=displays()
            if len(candidates)!=1:raise ValueError('need exactly one manager SpiceDisplay')
            pixels=candidates[0].get_pixbuf()
            if pixels is None:raise ValueError('manager has no decoded pixbuf')
            raw=pixels.get_pixels();errors=[]
            for scale in (1,2):
                try:
                    sequence=token.decode(raw,pixels.get_width(),pixels.get_height(),pixels.get_rowstride(),pixels.get_n_channels(),args.nonce,scale)
                    break
                except ValueError as error:errors.append(str(error))
            else:raise ValueError('; '.join(errors))
            state=tracker.observe(sequence)
            if first is None:first=now
            if state['unique']:
                unique+=1
                if last_unique is not None:max_stale=max(max_stale,now-last_unique)
                last_unique=now
            else:
                duplicates+=1
                if last_unique is not None:max_stale=max(max_stale,now-last_unique)
            sample.update(valid=True,sequence=sequence,scale=scale,width=pixels.get_width(),height=pixels.get_height(),**state)
        except (ValueError,RuntimeError) as error:
            invalid+=1;sample.update(valid=False,error=str(error))
        except Exception as error:
            record(dict(event='sampler-error',error_type=type(error).__name__,error=str(error)))
            finish('sampler-error');return False
        duration=time.monotonic()-now;max_sample=max(max_sample,duration)
        sample['sampling_seconds']=duration;record(sample);return True
    GLib.timeout_add(args.interval_ms,poll)
    extra=args.manager_args[1:] if args.manager_args[:1]==['--'] else args.manager_args
    sys.argv=[str(prefix/'bin/virt-manager'),'--no-fork',*extra]
    try:runpy.run_path(str(prefix/'bin/virt-manager'),run_name='__main__')
    finally:finish('viewer-exited-before-measurement-finished')

if __name__=='__main__':main()
