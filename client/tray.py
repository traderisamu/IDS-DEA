"""
System tray icon integration.

The app is meant to run quietly in the background (it auto-starts at
Windows login so reminders fire even if nobody opens it). Previously it
popped its full window open every time it launched, which is disruptive
- especially at login. This module puts a small icon in the system tray
instead; the main window only appears when the user asks for it (via the
tray icon) or when a reminder needs their attention.

Requires `pystray` + `Pillow`. Both are optional at import time - if
they're missing (e.g. a stray dev environment without them installed),
TRAY_AVAILABLE is False and callers should fall back to just showing the
window normally, so a missing dependency never makes the app unreachable.
"""
import threading

try:
    import pystray
    from PIL import Image
    TRAY_AVAILABLE = True
except Exception:
    # pystray selects its backend eagerly at import time, so a missing
    # native dependency (e.g. no AppIndicator/GTK on some Linux setups)
    # can raise things other than ImportError - catch broadly so a tray
    # backend problem never takes the whole app down with it.
    TRAY_AVAILABLE = False


class TrayIcon:
    """Thin wrapper around pystray.Icon that runs it on a background
    thread. Menu callbacks fire on that background thread (pystray's
    doing, not ours) - callers should hop back onto the Tk thread
    themselves (e.g. via `root.after(0, fn)`) before touching any
    widget."""

    def __init__(self, icon_path, title, on_open=None, on_admin=None, on_check=None, on_exit=None):
        self._icon_path = icon_path
        self._title = title
        self._on_open = on_open
        self._on_admin = on_admin
        self._on_check = on_check
        self._on_exit = on_exit
        self._icon = None
        self._thread = None

    def start(self):
        if not TRAY_AVAILABLE:
            return False
        try:
            image = Image.open(self._icon_path)
        except Exception:
            return False

        menu = pystray.Menu(
            pystray.MenuItem("Open DEA Logger", self._handle_open, default=True),
            pystray.MenuItem("Admin Dashboard", self._handle_admin),
            pystray.MenuItem("Check for Updates", self._handle_check),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", self._handle_exit),
        )
        try:
            self._icon = pystray.Icon("IDS_DEA_Logger", image, self._title, menu)
            self._thread = threading.Thread(target=self._icon.run, daemon=True)
            self._thread.start()
            return True
        except Exception:
            self._icon = None
            return False

    def _handle_open(self, icon, item):
        if self._on_open:
            self._on_open()

    def _handle_admin(self, icon, item):
        if self._on_admin:
            self._on_admin()

    def _handle_check(self, icon, item):
        if self._on_check:
            self._on_check()

    def _handle_exit(self, icon, item):
        if self._on_exit:
            self._on_exit()

    def notify(self, title, message):
        """Best-effort balloon/toast notification. Silently does nothing
        if the tray icon isn't running or the platform doesn't support it."""
        if self._icon is None:
            return
        try:
            self._icon.notify(message, title)
        except Exception:
            pass

    def stop(self):
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
