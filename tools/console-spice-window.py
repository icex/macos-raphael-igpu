#!/usr/bin/env python3
"""View the supervised Bochs/SPICE console; closing this window leaves VM ownership intact."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time

spec = importlib.util.spec_from_file_location('console_window', Path(__file__).with_name('console-window.py'))
identity = importlib.util.module_from_spec(spec)
spec.loader.exec_module(identity)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-dir', type=Path, default=Path.home()/'macos-vm')
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--capture', type=Path, help='save one full console frame after 15 seconds')
    args = parser.parse_args()
    state = json.loads(args.state.read_text())

    def endpoint():
        live = json.loads(subprocess.check_output(['docker', 'inspect', state['cid']],
                                                 text=True, timeout=5))[0]
        return identity.console_endpoint(args.vm_dir.resolve(), state, live, 'bochs-spice')

    sock = endpoint()
    if args.check:
        print(json.dumps({'ready': True, 'socket': str(sock)}))
        return
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('SpiceClientGLib', '2.0')
    gi.require_version('SpiceClientGtk', '3.0')
    from gi.repository import Gtk, GLib, SpiceClientGLib, SpiceClientGtk
    session = SpiceClientGLib.Session()
    session.set_property('unix-path', str(sock))
    session.set_property('enable-audio', False)  # Existing USB/Pulse audio remains separate.
    session.set_property('enable-usbredir', False)
    session.set_property('enable-smartcard', False)
    gtk_session = SpiceClientGtk.GtkSession.get(session)
    gtk_session.set_property('auto-clipboard', False)
    gtk_session.set_property('auto-usbredir', False)
    display = None
    window = Gtk.Window(title='Raphael macOS — SPICE console')
    window.set_default_size(1280, 720)

    def channel_new(session, channel):
        nonlocal display
        if isinstance(channel, SpiceClientGLib.DisplayChannel) and channel.get_property('channel-id') == 0:
            display = SpiceClientGtk.Display.new(session, 0)
            display.set_property('resize-guest', False)
            display.set_property('scaling', True)
            window.add(display)
            display.show()
            display.grab_focus()

    # GObject signal connection is distinct from SpiceSession.connect().
    from gi.repository import GObject
    GObject.Object.connect(session, 'channel-new', channel_new)
    window.connect('destroy', lambda *_: Gtk.main_quit())
    started = time.monotonic()
    captured = False

    def poll():
        nonlocal captured
        try:
            if endpoint() != sock:
                raise ValueError('console endpoint changed')
            if args.capture and display is not None and not captured and time.monotonic()-started >= 15:
                pixels = display.get_pixbuf()
                if pixels is not None:
                    pixels.savev(str(args.capture), 'png', [], [])
                    print(json.dumps({'capture': str(args.capture), 'width': pixels.get_width(),
                                      'height': pixels.get_height()}), flush=True)
                    captured = True
        except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
            print(f'console disconnected: {error}', flush=True)
            Gtk.main_quit()
            return False
        return True

    window.show_all()
    if not session.connect():
        raise RuntimeError('SPICE connection could not start')
    GLib.timeout_add_seconds(2, poll)
    try:
        Gtk.main()
    finally:
        session.disconnect()


if __name__ == '__main__':
    main()
