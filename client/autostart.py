"""
Registers the app to auto-start at Windows login, using the current
user's registry Run key. Called on every app launch (not just install),
so autostart self-heals even if install.bat's own registration step
failed on a particular PC (e.g. blocked script host, AV interference) -
as long as someone opens the app manually once, it fixes itself for
every login after that.

No admin rights needed - HKEY_CURRENT_USER is always writable by the
current user.
"""
import sys

APP_NAME = "IDS_DEA_Logger"


def ensure_autostart():
    if not sys.platform.startswith("win"):
        return  # no-op outside Windows (e.g. dev/test environment)

    if not getattr(sys, "frozen", False):
        return  # running from source (python.exe) - nothing sensible to register

    try:
        import winreg
        target = f'"{sys.executable}"'
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE,
        )
        try:
            current_value, _ = winreg.QueryValueEx(key, APP_NAME)
        except FileNotFoundError:
            current_value = None

        if current_value != target:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, target)
        winreg.CloseKey(key)
    except Exception:
        pass  # never let a registry hiccup block the app from opening
