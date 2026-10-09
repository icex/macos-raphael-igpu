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

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manager-prefix',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('manager_args',nargs=argparse.REMAINDER)
    a=p.parse_args();prefix=a.manager_prefix.resolve()
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
    from gi.repository import Gtk,GLib,SpiceClientGtk
    stream=a.output.open('x');began=time.monotonic();control=None;ready_at=None;phase=0;done=False
    sizes=[(1280,720),(1920,1080)]
    def record(**row):
        stream.write(json.dumps(dict(monotonic=time.monotonic(),**row))+'\n');stream.flush()
    def poll():
        nonlocal control,ready_at,phase,done
        if done:return False
        try:
            if time.monotonic()-began>45:raise RuntimeError('diagnostic deadline')
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
            if ready_at is None:
                ready_at=time.monotonic();record(event='viewport-ready',phase=phase,**control.metadata)
            if time.monotonic()-ready_at>=10:
                pix=display.get_pixbuf()
                record(event='surface',phase=phase,width=pix.get_width() if pix else None,height=pix.get_height() if pix else None)
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
