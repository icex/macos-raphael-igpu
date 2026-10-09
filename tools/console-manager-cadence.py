#!/usr/bin/env python3
"""Sample the actual virt-manager SpiceDisplay buffer; opens no second connection."""
import argparse
import importlib.util
import importlib.machinery
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import time


def load_roi_extension(path):
    """Load one explicit local extension and retain its actual binary identity."""
    path=Path(path).resolve(strict=True)
    if not path.is_file() or not any(str(path).endswith(suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES):
        raise ValueError('ROI extension must be a local native extension file')
    def digest():
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    before=digest()
    spec=importlib.util.spec_from_file_location('console_token_roi',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if Path(module.__file__).resolve()!=path or digest()!=before:
        raise ValueError('ROI extension changed while loading')
    if not callable(getattr(module,'snapshot',None)):raise ValueError('ROI extension lacks snapshot API')
    return module,dict(path=str(path),sha256=before,python_cache_tag=sys.implementation.cache_tag)


def sample_display(display,token,nonce,roi=None):
    """Reacquire each callback; ROI never falls back to a full screenshot."""
    errors=[]
    if roi is None:
        pixels=display.get_pixbuf()
        if pixels is None:raise ValueError('manager has no decoded pixbuf')
        raw=pixels.get_pixels()
    for scale in (1,2):
        try:
            if roi is None:
                width,height=pixels.get_width(),pixels.get_height()
                sequence=token.decode(raw,width,height,pixels.get_rowstride(),pixels.get_n_channels(),nonce,scale)
            else:
                sample=roi.snapshot(display,scale)
                sequence=token.decode(sample['pixels'],sample['width'],sample['height'],sample['stride'],sample['channels'],nonce,scale)
                width,height=sample['surface_width'],sample['surface_height']
            return dict(sequence=sequence,scale=scale,width=width,height=height)
        except (ValueError,RuntimeError) as error:errors.append(str(error))
    raise ValueError('; '.join(errors))


def stale_bound(previous_maximum,last_unique,now):
    """Include trailing silence even when no invalidation callback arrives."""
    return previous_maximum if last_unique is None else max(previous_maximum,now-last_unique)


class EventObserver:
    """Synchronous existing-channel observer; never dispatches nested GLib work.

    Invalidation is a completed region application, not a frame or scanout.
    All handlers and ROI copying run inside the same default main context.
    """
    def __init__(self, display, channel, connect_after, disconnect, sample, record,
                 fail, clock=time.monotonic):
        self.display=display;self.channel=channel;self.disconnect=disconnect
        self.sample=sample;self.record=record;self.fail=fail;self.clock=clock
        self.invalidations=0;self.completed_callbacks=0;self.draws=0;self.callback_seconds=0.;self.max_callback=0.
        self.closed=False;self.active=False;self.handlers=[]
        try:
            self.handlers.append((channel,connect_after(channel,'display-invalidate',self.invalidate)))
            self.handlers.append((display,connect_after(display,'draw',self.draw)))
        except BaseException:
            self.close();raise

    def invalidate(self, channel, x, y, width, height):
        if self.closed:return
        started=self.clock();entered=False
        try:
            if channel is not self.channel or self.active:
                raise RuntimeError('changed channel or reentrant invalidate callback')
            if any(type(v) is not int for v in (x,y,width,height)) or min(x,y)<0 or min(width,height)<=0:
                raise ValueError('malformed invalidate rectangle')
            self.active=True;entered=True;self.invalidations+=1
            self.record(dict(event='display-invalidate',host_monotonic=started,
                             index=self.invalidations,x=x,y=y,width=width,height=height))
            if self.sample is not None:self.sample(self.display,'display-invalidate')
        except Exception as error:self.fail(error)
        finally:
            elapsed=self.clock()-started
            if entered:
                self.active=False
                self.completed_callbacks+=1
                self.callback_seconds+=elapsed;self.max_callback=max(self.max_callback,elapsed)
                if not self.closed:
                    self.record(dict(event='invalidate-complete',index=self.invalidations,
                                     host_monotonic=self.clock(),callback_seconds=elapsed))

    def draw(self, display, context):
        if not self.closed:self.draws+=1
        return False  # Never consume/replace the widget's normal drawing.

    def summary(self):
        return dict(invalidate_callbacks=self.invalidations,completed_invalidate_callbacks=self.completed_callbacks,
                    final_callback_in_progress=self.active,widget_draw_callbacks=self.draws,
                    event_callback_total_seconds=self.callback_seconds,
                    event_callback_max_seconds=self.max_callback,
                    event_scope='region callbacks/redraws, not frames/scanout; synchronous observer delays decoding. Cost includes begin/sample writes, excludes completion-record write. If final_callback_in_progress, terminating callback cost is excluded.')

    def close(self):
        if self.closed:return
        self.closed=True
        for obj,handler in self.handlers:self.disconnect(obj,handler)
        self.handlers=[]


def matching_display_channel(display, display_channel_type):
    session=display.get_property('session')
    if session is None:raise ValueError('display has no existing session')
    channel_id=display.get_property('channel-id')
    matches=[c for c in session.get_channels()
             if isinstance(c,display_channel_type) and c.get_property('channel-id')==channel_id]
    if len(matches)!=1:raise ValueError('need exactly one matching existing display channel')
    return matches[0]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event-observer',choices=['roi','count-only'],help='optional existing-channel invalidation observer; count-only never decodes and starts its window at attachment')
    parser.add_argument('--roi-extension',type=Path,help='optional explicit console_token_roi native extension file; default remains full pixbuf')
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
    if args.event_observer=='roi' and args.roi_extension is None:parser.error('event ROI observer requires explicit ROI extension')
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
    roi,extension_identity=load_roi_extension(args.roi_extension) if args.roi_extension else (None,None)
    observer='roi' if roi is not None else 'full-pixbuf'
    import gi
    gi.require_version('Gtk','3.0');gi.require_version('SpiceClientGtk','3.0')
    gi.require_version('SpiceClientGLib','2.0')
    from gi.repository import Gtk,GLib,GObject,SpiceClientGtk,SpiceClientGLib
    stream=args.output.open('x');summary_path=Path(str(args.output)+'.summary.json')
    if summary_path.exists():stream.close();raise ValueError('summary already exists')
    tracker=token.SequenceTracker();began=time.monotonic();first=None;last_unique=None
    unique=0;invalid=0;duplicates=0;max_stale=0.;max_sample=0.;finished=False
    event_observer=None;last_heartbeat=None;max_heartbeat_gap=0.
    def record(data):stream.write(json.dumps(data)+'\n');stream.flush()
    record(dict(event='start',nonce=args.nonce,seconds=args.seconds,interval_ms=args.interval_ms,
                observer=observer,event_observer=args.event_observer,roi_extension=extension_identity,
                window_start='attachment' if args.event_observer=='count-only' else 'first-valid-token',
                scope='sampled decoded manager buffer only; no host scanout or absolute latency'))
    def finish(reason):
        nonlocal finished
        if finished:return
        finished=True
        elapsed=0 if first is None else time.monotonic()-first
        summary=dict(reason=reason,nonce=args.nonce,observer=observer,roi_extension=extension_identity,unique=unique,duplicates=duplicates,invalid=invalid,
                     elapsed=elapsed,sampled_unique_per_second=unique/elapsed if elapsed else None,
                     max_observed_stale_seconds=stale_bound(max_stale,last_unique,time.monotonic()),max_sampling_seconds=max_sample,
                     scope='Sampling lower bound; observer work may reduce measured throughput. No GPU FPS, host scanout, or absolute latency claim.')
        if args.event_observer:
            summary.update(event_observer=args.event_observer,max_heartbeat_gap_seconds=max_heartbeat_gap,
                           **(event_observer.summary() if event_observer else {}))
            if event_observer:event_observer.close()
        record(dict(event='finish',**summary));summary_path.write_text(json.dumps(summary,indent=2)+'\n');stream.close()
    def displays():
        found=[]
        def visit(widget):
            if isinstance(widget,SpiceClientGtk.Display):found.append(widget)
            if isinstance(widget,Gtk.Container):
                for child in widget.get_children():visit(child)
        for window in Gtk.Window.list_toplevels():visit(window)
        return found
    def poll(display=None,trigger='timer'):
        nonlocal first,last_unique,unique,invalid,duplicates,max_stale,max_sample
        now=time.monotonic()
        if first is not None and now-first>=args.seconds:finish('completed');return False
        if first is None and now-began>=args.wait_seconds:finish('no-valid-token');return False
        if last_unique is not None:max_stale=max(max_stale,now-last_unique)
        sample=dict(event='sample',host_monotonic=now)
        if args.event_observer:sample['trigger']=trigger
        try:
            if display is None:
                candidates=displays()
                if len(candidates)!=1:raise ValueError('need exactly one manager SpiceDisplay')
                display=candidates[0]
            decoded=sample_display(display,token,args.nonce,roi)
            sequence=decoded['sequence']
            state=tracker.observe(sequence)
            if first is None:first=now
            if state['unique']:
                unique+=1
                if last_unique is not None:max_stale=max(max_stale,now-last_unique)
                last_unique=now
            else:
                duplicates+=1
                if last_unique is not None:max_stale=max(max_stale,now-last_unique)
            sample.update(valid=True,**decoded,**state)
        except (ValueError,RuntimeError) as error:
            invalid+=1;sample.update(valid=False,error=str(error))
        except Exception as error:
            record(dict(event='sampler-error',error_type=type(error).__name__,error=str(error)))
            finish('sampler-error');return False
        duration=time.monotonic()-now;max_sample=max(max_sample,duration)
        sample['sampling_seconds']=duration;record(sample);return True
    def event_failure(error):
        if finished:return
        record(dict(event='sampler-error',error_type=type(error).__name__,error=str(error)))
        finish('sampler-error')
    def heartbeat():
        nonlocal event_observer,first,last_heartbeat,max_heartbeat_gap
        now=time.monotonic()
        if last_heartbeat is not None:max_heartbeat_gap=max(max_heartbeat_gap,now-last_heartbeat)
        last_heartbeat=now
        if finished:return False
        if first is not None and now-first>=args.seconds:finish('completed');return False
        if first is None and now-began>=args.wait_seconds:finish('no-valid-token');return False
        try:
            found=displays()
            if event_observer:
                if len(found)!=1 or found[0] is not event_observer.display:
                    raise RuntimeError('observed manager display replaced/disappeared')
                if matching_display_channel(found[0],SpiceClientGLib.DisplayChannel) is not event_observer.channel:
                    raise RuntimeError('observed channel replaced/disappeared')
            elif len(found)==1:
                try:channel=matching_display_channel(found[0],SpiceClientGLib.DisplayChannel)
                except ValueError:return True  # Channel may not exist during initial connection.
                event_observer=EventObserver(found[0],channel,GObject.Object.connect_after,
                    GObject.Object.disconnect,None if args.event_observer=='count-only' else poll,
                    record,event_failure)
                if args.event_observer=='count-only':first=now
                record(dict(event='observer-attached',host_monotonic=now,
                            channel_id=channel.get_property('channel-id'),mode=args.event_observer))
            elif len(found)>1:raise RuntimeError('ambiguous manager displays')
        except Exception as error:event_failure(error);return False
        return True
    GLib.timeout_add(args.interval_ms,heartbeat if args.event_observer else poll)
    extra=args.manager_args[1:] if args.manager_args[:1]==['--'] else args.manager_args
    sys.argv=[str(prefix/'bin/virt-manager'),'--no-fork',*extra]
    try:runpy.run_path(str(prefix/'bin/virt-manager'),run_name='__main__')
    finally:finish('viewer-exited-before-measurement-finished')

if __name__=='__main__':main()
