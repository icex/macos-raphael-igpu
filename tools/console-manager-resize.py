#!/usr/bin/env python3
"""Bounded viewport diagnostic in the actual virt-manager connection."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys
import time

def surface_metadata(display,cadence,spice):
    """Read only scalar fields on this widget's existing display channel.

    The installed DisplayPrimary GI layout is invalid; never call it.
    Monitor records have fixed scalar fields and do not contain that enum.
    """
    channel=cadence.matching_display_channel(display,spice.DisplayChannel)
    monitors=channel.get_property('monitors')
    maps=[]
    if monitors is not None:
        for monitor in monitors:
            maps.append({name:int(getattr(monitor,name)) for name in
                         ('id','surface_id','x','y','width','height')})
    # Installed0.42 GIR incorrectly models enum format as gpointer, shifting
    # DisplayPrimary fields on x86_64. Do not call this unsafe marshaling path.
    return dict(channel_id=int(channel.get_property('channel-id')),
                widget_monitor_id=int(display.get_property('monitor-id')),
                monitors=maps,primary_surface_id=0,primary_available=False,
                primary_unavailable='GI-ABI-mismatch: enum format declared as pointer',
                primary=None,
                scope='existing-channel monitor metadata only; primary unavailable; no pixel or pointer access')

def parse_args(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manager-prefix',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--viewport',type=int,nargs=2,action='append',metavar=('WIDTH','HEIGHT'))
    p.add_argument('manager_args',nargs=argparse.REMAINDER)
    a=p.parse_args(argv)
    if a.viewport is None:a.viewport=[(1280,720),(1920,1080)]
    if not 1<=len(a.viewport)<=12:p.error('need 1..12 viewports')
    if any(not (320<=w<=1920 and 200<=h<=1080) for w,h in a.viewport):
        p.error('viewport must be 320..1920 by 200..1080 logical pixels')
    a.viewport=[tuple(size) for size in a.viewport]
    a.deadline_seconds=min(180,25+10*len(a.viewport))
    return a

def main():
    a=parse_args();prefix=a.manager_prefix.resolve()
    if os.environ.get('RGPU_RESIZE_PREFIX')!=str(prefix):
        env=dict(os.environ,RGPU_RESIZE_PREFIX=str(prefix))
        for key,leaf in [('LD_LIBRARY_PATH','lib'),('GI_TYPELIB_PATH','lib/girepository-1.0')]:
            env[key]=str(prefix/leaf)+(':'+env[key] if env.get(key) else '')
        os.execve(sys.executable,[sys.executable,*sys.argv],env)
    sys.path[:0]=[str(prefix/'share/virt-manager'),str(prefix/f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')]
    os.environ['GSETTINGS_SCHEMA_DIR']=str(prefix/'share/glib-2.0/schemas')
    os.environ['GSETTINGS_BACKEND']='keyfile'
    for key,leaf in [('XDG_CONFIG_HOME','config'),('XDG_CACHE_HOME','cache'),('XDG_DATA_HOME','data')]:
        os.environ[key]=str(Path(str(a.output)+'-'+leaf))
    spec=importlib.util.spec_from_file_location('cadence',Path(__file__).with_name('console-manager-cadence.py'))
    cadence=importlib.util.module_from_spec(spec);spec.loader.exec_module(cadence)
    import gi
    gi.require_version('Gtk','3.0');gi.require_version('SpiceClientGtk','3.0')
    gi.require_version('SpiceClientGLib','2.0')
    from gi.repository import Gtk,GLib,Gio,SpiceClientGtk,SpiceClientGLib
    # The manager synchronizes this preference after connecting its channels.
    # Store it only in this diagnostic's isolated keyfile settings directory.
    settings=Gio.Settings.new('org.virt-manager.virt-manager.console')
    if not settings.set_int('resize-guest',1):raise RuntimeError('resize preference refused')
    Gio.Settings.sync()
    stream=a.output.open('x');began=time.monotonic();control=None;ready_at=None;phase=0;done=False
    sizes=a.viewport
    def record(**row):
        stream.write(json.dumps(dict(monotonic=time.monotonic(),**row))+'\n');stream.flush()
    record(event='configuration',requested_viewports=sizes,phase_seconds=10,deadline_seconds=a.deadline_seconds)
    def poll():
        nonlocal control,ready_at,phase,done
        if done:return False
        try:
            if time.monotonic()-began>a.deadline_seconds:raise RuntimeError('diagnostic deadline')
            found=[]
            def visit(widget):
                if isinstance(widget,SpiceClientGtk.Display):found.append(widget)
                if isinstance(widget,Gtk.Container):
                    for child in widget.get_children():visit(child)
            for window in Gtk.Window.list_toplevels():visit(window)
            if not found and control is None:return True
            if len(found)!=1:raise RuntimeError('need exactly one owned display')
            display=found[0]
            if control is None:
                display.set_property('scaling',True)
                display.set_property('resize-guest',True)
                control=cadence.ViewportControl(display,sizes[phase])
                record(event='request',phase=phase,viewport=sizes[phase])
            if control.display is not display:raise RuntimeError('display replaced')
            if not control.check():return True
            if control.metadata['resize_guest'] is not True:raise RuntimeError('manager disabled resize-guest')
            if ready_at is None:
                ready_at=time.monotonic();record(event='viewport-ready',phase=phase,surface_metadata=surface_metadata(display,cadence,SpiceClientGLib),**control.metadata)
            if time.monotonic()-ready_at>=10:
                pix=display.get_pixbuf()
                record(event='surface',phase=phase,surface_metadata=surface_metadata(display,cadence,SpiceClientGLib),width=pix.get_width() if pix else None,height=pix.get_height() if pix else None)
                phase+=1
                if phase==len(sizes):
                    done=True;record(event='finished');return False
                control=None;ready_at=None
        except Exception as error:
            done=True;record(event='error',error=str(error));return False
        return True
    GLib.timeout_add(100,poll)
    extra=a.manager_args[1:] if a.manager_args[:1]==['--'] else a.manager_args
    sys.argv=[str(prefix/'bin/virt-manager'),'--no-fork',*extra]
    try:runpy.run_path(str(prefix/'bin/virt-manager'),run_name='__main__')
    finally:record(event='viewer-exited');stream.close()

if __name__=='__main__':main()
