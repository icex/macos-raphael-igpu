#!/usr/bin/env python3
"""Owned virt-manager process with manual-only SPICE USB redirection.

Does not attach devices or modify installed virt-manager/user preferences.
Pass the existing isolated virt-manager Python package path via PYTHONPATH.
"""
import os
import sys


def manual_only(viewer, gtk_session):
    """Run after session construction, before any session connection."""
    gtk_session.set_property('auto-usbredir', False)
    manager = viewer._usbdev_manager
    if manager is None:
        raise RuntimeError('SPICE USB redirection support unavailable')
    manager.set_property('auto-connect', False)
    manager.set_property('redirect-on-connect', None)
    if gtk_session.get_property('auto-usbredir') or manager.get_property('auto-connect') or manager.get_property('redirect-on-connect'):
        raise RuntimeError('automatic USB redirection was not disabled')


def run_manager(on_session=None):
    """Run inside an already-owned private D-Bus session.

    Optional diagnostic callback receives (viewer, session, gtk_session) after
    manual-only policy is established, before connection. It must not attach USB.
    This function does not create a second SPICE client.
    """
    # Process-local settings; never alter an existing manager's preferences.
    os.environ['GSETTINGS_BACKEND'] = 'memory'
    import gi
    gi.require_version('SpiceClientGtk', '3.0')
    from gi.repository import Gio, SpiceClientGtk
    settings = Gio.Settings.new('org.virt-manager.virt-manager.console')
    if not settings.set_boolean('auto-redirect', False) or settings.get_boolean('auto-redirect'):
        raise RuntimeError('cannot disable automatic USB redirection')
    from virtManager.details import viewers
    original = viewers.SpiceViewer._create_spice_session

    def create(self):
        original(self)
        gtk_session=SpiceClientGtk.GtkSession.get(self._spice_session)
        manual_only(self, gtk_session)
        if on_session is not None:
            on_session(self, self._spice_session, gtk_session)
    viewers.SpiceViewer._create_spice_session = create
    from virtManager import virtmanager
    virtmanager.runcli()


def main():
    # A private bus prevents delegation to an already-running, unguarded manager.
    # Internal re-exec marker is removed before loading any manager code.
    if os.environ.pop('RGPU_USBREDIR_PRIVATE_BUS', None) != '1':
        environment=dict(os.environ, RGPU_USBREDIR_PRIVATE_BUS='1')
        os.execvpe('dbus-run-session', ['dbus-run-session', '--', sys.executable,
                    os.path.abspath(__file__), *sys.argv[1:]], environment)
        raise RuntimeError('private session launch returned unexpectedly')
    run_manager()


if __name__ == '__main__':
    main()
