"""
Global (system-wide) hotkey to pop the DEA Logger's window open (or, if
it's already open, send it back to the tray - a toggle, not just an
"open" button) from anywhere - even while it's sitting quietly in the
tray with no window in focus, since a normal Tkinter key binding only
fires when the app already has focus.

Implemented directly against the official Win32 RegisterHotKey API via
ctypes (stdlib only - no extra pip dependency, and deliberately NOT a
background keyboard-hook/"keyboard" library, since a global key hook is
exactly the kind of thing antivirus tools flag as keylogger-like
behavior). RegisterHotKey is the same mechanism Windows itself uses for
built-in shortcuts like Win+L - it only ever sees the one exact key
combination it registered, nothing else.

Default combo is Alt+Escape - just two keys held together, deliberately
avoiding the Windows (Win) key entirely (reserved for OS shortcuts).
Note this one IS a longstanding Windows system shortcut on its own
(cycles to the next window, similar to Alt+Tab) - RegisterHotKey still
lets an app claim it (first app to register wins), but it means this
app's popup takes over that combo system-wide while it's running,
instead of Windows' own window-cycling behavior. Worth knowing before
wider rollout in case that trade-off matters to anyone.
"""
import sys
import ctypes
import threading

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

VK_ESCAPE = 0x1B

DEFAULT_MODIFIERS = MOD_ALT | MOD_NOREPEAT
DEFAULT_VK = VK_ESCAPE
DEFAULT_LABEL = "Alt+Escape"

_HOTKEY_ID = 1
_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012


class GlobalHotkey:
    """Best-effort - if the combo is already taken by something else, or
    this isn't Windows, start() just returns False and the app carries
    on exactly as before (tray icon / manual open still work)."""

    def __init__(self, callback, modifiers=DEFAULT_MODIFIERS, vk=DEFAULT_VK):
        self._callback = callback
        self._modifiers = modifiers
        self._vk = vk
        self._thread = None
        self._thread_id = None
        self._registered = threading.Event()
        self._registration_ok = False

    def start(self, timeout=2.0):
        if not sys.platform.startswith("win"):
            return False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._registered.wait(timeout)
        return self._registration_ok

    def _run(self):
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            self._thread_id = kernel32.GetCurrentThreadId()
            self._registration_ok = bool(
                user32.RegisterHotKey(None, _HOTKEY_ID, self._modifiers, self._vk)
            )
        except Exception:
            self._registration_ok = False
        finally:
            self._registered.set()

        if not self._registration_ok:
            return

        try:
            from ctypes import wintypes
            msg = wintypes.MSG()
            user32 = ctypes.windll.user32
            while user32.GetMessageA(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == _WM_HOTKEY and self._callback:
                    self._callback()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageA(ctypes.byref(msg))
        except Exception:
            pass
        finally:
            try:
                ctypes.windll.user32.UnregisterHotKey(None, _HOTKEY_ID)
            except Exception:
                pass

    def stop(self):
        if self._registration_ok and self._thread_id:
            try:
                ctypes.windll.user32.PostThreadMessageA(self._thread_id, _WM_QUIT, 0, 0)
            except Exception:
                pass
