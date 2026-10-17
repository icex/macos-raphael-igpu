#!/usr/bin/python3
"""Guest helper for the Raphael iGPU display in QEMU's window (runs as root via launchd).

The kext publishes RGPUDisplayOverride {seq, vendor, product, panel-*, logical-*, refresh}
on the AMD framebuffer before it emulates a hotplug for a new window size. The new display
offers a 3840-wide HiDPI panel shaped like the window and the window's exact pixel size as
a 1x mode. This selects HiDPI "looks like panel/2" (default) or the exact 1x mode at the
best refresh when /Library/Preferences/org.raphaelgpu.display has dpi = "low".
(macOS 15.7 ignores /Library/Displays overrides, so none are written.)
"""
import os, plistlib, subprocess, sys, time

PREFS = '/Library/Preferences/org.raphaelgpu.display.plist'
MODE_TOOL = '/usr/local/libexec/rgpu-display-mode'


def request():
    try:
        out = subprocess.run(['/usr/sbin/ioreg', '-a', '-r', '-k', 'RGPUDisplayOverride', '-d', '1'],
                             capture_output=True, timeout=5).stdout
        entries = plistlib.loads(out) if out.strip() else []
    except Exception:
        return None
    for entry in entries:
        r = entry.get('RGPUDisplayOverride')
        if isinstance(r, dict) and r.get('vendor') == 0x48f0:
            return r
    return None


def dpi_preference():
    try:
        with open(PREFS, 'rb') as f:
            return plistlib.load(f).get('dpi', 'high')
    except Exception:
        return 'high'


def console_uid():
    try:
        return os.stat('/dev/console').st_uid
    except OSError:
        return 0


NOT_READY = 'no mode tool or no console user'


def select_mode(r):
    if not os.path.exists(MODE_TOOL) or not console_uid():
        return NOT_READY
    if dpi_preference() == 'low':
        w, h, scale, hz = r['logical-width'], r['logical-height'], 1, r['refresh']
    else:
        w, h, scale, hz = r['panel-width'] // 2, r['panel-height'] // 2, 2, r.get('panel-refresh', 60)
    for _ in range(20):                       # the display needs a moment to come back
        time.sleep(0.5)
        res = subprocess.run(['/bin/launchctl', 'asuser', str(console_uid()), MODE_TOOL,
                              str(r['vendor']), str(r['product']), str(w), str(h), str(scale),
                              str(hz)], capture_output=True, text=True, timeout=10)
        if res.returncode == 0:
            return res.stdout.strip()
    return 'display with product %#x did not offer %dx%d@%dx' % (r['product'], w, h, scale)


def main():
    last = None
    while True:
        r = request()
        if r and r.get('seq') != last:
            result = select_mode(r)
            # Before login there is no session to configure: keep the request and retry,
            # so the window's size and refresh still apply once a user logs in.
            if result == NOT_READY:
                time.sleep(2)
                continue
            last = r.get('seq')
            print('request', r, flush=True)
            print('mode', result, flush=True)
        time.sleep(0.25)


if __name__ == '__main__':
    sys.exit(main())
