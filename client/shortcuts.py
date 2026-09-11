"""
Creates the Desktop shortcut, and self-heals it on every launch the same
way client/autostart.py self-heals the Run-key registration - so the
shortcut reappears even if:
  - install.bat was never run (someone just copied the exe and ran it), or
  - install.bat's own shortcut step silently failed on that PC, or
  - the shortcut got deleted by a cleanup tool / accidental delete.

Resolving the Desktop folder from %USERPROFILE%\\Desktop (what install.bat
used previously) is wrong on any PC where the Desktop has been redirected
- most commonly by OneDrive Known Folder Move, which many IT departments
turn on by default. On those PCs the real Desktop lives somewhere like
"%USERPROFILE%\\OneDrive - Company\\Desktop", so a shortcut written to the
old plain path is silently invisible: no error, no warning, it just isn't
where the user is looking. We resolve the *actual* Desktop location from
the registry (which is redirection-aware) instead.

No admin rights and no extra pip dependency (pywin32) needed - the .lnk
itself is created by shelling out to PowerShell's WScript.Shell COM
object, which ships with every supported version of Windows. If that's
blocked (some locked-down environments disable PowerShell), we fall back
to a plain .bat launcher, which needs nothing but a text file write.
"""
import os
import sys
import subprocess


def _real_desktop_dir():
    """Redirection-aware Desktop path. Falls back to the plain
    %USERPROFILE%\\Desktop only if the registry lookup fails outright."""
    fallback = os.path.join(os.path.expanduser("~"), "Desktop")
    if not sys.platform.startswith("win"):
        return fallback
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
        value, _kind = winreg.QueryValueEx(key, "Desktop")
        winreg.CloseKey(key)
        # Value may contain unexpanded env vars like %USERPROFILE%.
        value = os.path.expandvars(value)
        return value if value else fallback
    except Exception:
        return fallback


def _create_lnk_via_powershell(lnk_path, target_exe, icon_path, description):
    ps_script = (
        "$s = New-Object -ComObject WScript.Shell;"
        f"$l = $s.CreateShortcut('{lnk_path}');"
        f"$l.TargetPath = '{target_exe}';"
        f"$l.WorkingDirectory = '{os.path.dirname(target_exe)}';"
        f"$l.IconLocation = '{icon_path}, 0';"
        f"$l.Description = '{description}';"
        "$l.Save()"
    )
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps_script],
            capture_output=True, timeout=15, creationflags=creationflags,
        )
        return result.returncode == 0 and os.path.isfile(lnk_path)
    except Exception:
        return False


def _create_bat_launcher(bat_path, target_exe):
    try:
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write("@echo off\r\n")
            f.write(f'start "" "{target_exe}"\r\n')
        return os.path.isfile(bat_path)
    except Exception:
        return False


def ensure_desktop_shortcut(app_title="IDS PH DEA Logger"):
    """Best-effort - never raises, never blocks the app from opening."""
    if not sys.platform.startswith("win"):
        return
    if not getattr(sys, "frozen", False):
        return  # running from source - nothing sensible to shortcut to

    try:
        target_exe = sys.executable
        desktop = _real_desktop_dir()
        if not desktop or not os.path.isdir(desktop):
            return

        lnk_path = os.path.join(desktop, f"{app_title}.lnk")
        bat_path = os.path.join(desktop, f"{app_title}.bat")

        if os.path.isfile(lnk_path) or os.path.isfile(bat_path):
            return  # already present - nothing to do

        icon_path = target_exe  # the .exe has the icon baked in
        ok = _create_lnk_via_powershell(lnk_path, target_exe, icon_path,
                                         "IDS PH - Daily Employee Accomplishment Logger")
        if not ok:
            _create_bat_launcher(bat_path, target_exe)
    except Exception:
        pass  # never let a shortcut hiccup block the app from opening
