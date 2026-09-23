"""
Silent auto-update from the shared dist folder.

At startup (background thread, short delay) the app reads version.txt next
to the staged IDS_DEA_Logger.exe on the shared drive and compares it with
its own APP_VERSION. When the staged build is newer it is downloaded to a
.pending file, a tiny updater .bat is written, and the app relaunches
itself through it: the bat waits for the old process to exit (Windows
cannot overwrite a running exe), swaps the new exe in (keeping one .bak),
and starts it again. A manual "Check for Updates" runs the same path on
demand.

Safety rails, all deliberate:
- Never blocks launch, logging, or reminders; every failure (offline
  drive, missing/corrupt version.txt, bad download) silently keeps the
  current build.
- Never interrupts an edit: if any dialog is open, this launch is skipped
  and the update lands on a later launch.
- Only released builds update: source runs (not frozen) never touch this.
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk

from shared import constants as C

PENDING_SUFFIX = ".pending.exe"
BACKUP_SUFFIX = ".bak"
NOTICE_FILENAME = "updated_from.txt"
MIN_EXE_BYTES = 1024 * 1024


def _parse_version(text):
    """'2.1.0' -> (2, 1, 0). Returns None for anything not starting with
    a dotted-number release tag, so garbage can never look 'newer'."""
    if not text:
        return None
    m = re.match(r"\s*v?(\d+(?:\.\d+)*)", str(text))
    if not m:
        return None
    try:
        return tuple(int(p) for p in m.group(1).split("."))
    except ValueError:
        return None


def is_newer(current, staged):
    """True when `staged` is a strictly newer release than `current`.
    Unparseable staged versions are never newer; an unparseable current
    version loses to any parseable staged one."""
    s = _parse_version(staged)
    if s is None:
        return False
    c = _parse_version(current)
    if c is None:
        return True
    width = max(len(s), len(c))
    s = s + (0,) * (width - len(s))
    c = c + (0,) * (width - len(c))
    return s > c


def read_staged_version(dist_folder=None):
    """The staged release tag from the shared folder, or None when there
    is nothing usable to compare against (offline, missing, corrupt)."""
    folder = dist_folder or C.UPDATE_DIST_FOLDER
    try:
        if not folder or not os.path.isdir(folder):
            return None
        with open(os.path.join(folder, C.UPDATE_VERSION_FILENAME),
                  "r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text or len(text) > 32 or _parse_version(text) is None:
            return None
        return text.strip()
    except OSError:
        return None


def install_dir():
    """Folder holding the currently running exe when frozen; the standard
    per-user install folder otherwise (also where updates land)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, C.LOCAL_APP_FOLDER_NAME)


def _busy_with_dialogs(app):
    """True when any modal-ish dialog is open - an update restart now
    would trash unsaved Add/Edit input, so the update waits."""
    try:
        return any(isinstance(w, tk.Toplevel) and bool(w.winfo_viewable())
                   for w in app.winfo_children())
    except tk.TclError:
        return True


def _stage_files(app, dist_folder):
    """Copies the staged exe (+ admin_links.json when present) next to the
    running one. Returns (target, pending) paths, or None on any problem."""
    try:
        target = os.path.join(install_dir(), C.UPDATE_EXE_FILENAME)
        staged_exe = os.path.join(dist_folder, C.UPDATE_EXE_FILENAME)
        if not os.path.isfile(staged_exe):
            return None
        if os.path.getsize(staged_exe) < MIN_EXE_BYTES:
            return None
        pending = target + PENDING_SUFFIX
        shutil.copyfile(staged_exe, pending)
        if os.path.getsize(pending) != os.path.getsize(staged_exe):
            try:
                os.remove(pending)
            except OSError:
                pass
            return None
        staged_links = os.path.join(dist_folder, "admin_links.json")
        if os.path.isfile(staged_links):
            try:
                shutil.copyfile(staged_links,
                                os.path.join(install_dir(), "admin_links.json"))
            except OSError:
                pass
        return target, pending
    except OSError:
        return None


_UPDATER_BAT = """@echo off
setlocal
set "TARGET=%~1"
set "PENDING=%~2"
set "BACKUP=%~3"
set "NOTICE=%~4"
set "OLDVER=%~5"
set "PID=%~6"
:waitloop
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto :waitloop
)
if exist "%TARGET%" copy /Y "%TARGET%" "%BACKUP%" >nul
copy /Y "%PENDING%" "%TARGET%" >nul
del "%PENDING%" >nul 2>&1
echo %OLDVER%>"%NOTICE%"
start "" "%TARGET%"
(goto) 2>nul & del "%~f0"
"""


def _relaunch_through_updater(app, target, pending):
    """Hands off to the updater bat and exits this process. The bat does
    the locked-file swap once we are gone, then starts the new build."""
    try:
        folder = os.path.dirname(target)
        bat_path = os.path.join(folder, "dea_updater.bat")
        notice = os.path.join(folder, NOTICE_FILENAME)
        backup = target + BACKUP_SUFFIX
        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(_UPDATER_BAT)
        subprocess.Popen(
            ["cmd", "/c", bat_path, target, pending, backup, notice,
             C.APP_VERSION, str(os.getpid())],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )
    except Exception:
        return False
    try:
        app.after(0, app._quit_app)
    except tk.TclError:
        pass
    return True


def _try_update(app, dist_folder=None):
    """One update attempt. Returns (applied, message): applied=True means
    this process is on its way out and the new build is coming up."""
    if not getattr(sys, "frozen", False):
        return False, "Auto-update only applies to installed builds."
    try:
        if not app.winfo_exists():
            return False, ""
    except tk.TclError:
        return False, ""
    folder = dist_folder or C.UPDATE_DIST_FOLDER
    staged = read_staged_version(folder)
    if staged is None:
        return False, "Could not reach the shared release folder."
    if not is_newer(C.APP_VERSION, staged):
        return False, f"You are on the latest version (v{C.APP_VERSION})."
    if _busy_with_dialogs(app):
        return False, "Close open dialogs first, then check again."
    staged_paths = _stage_files(app, folder)
    if not staged_paths:
        return False, "Download failed - keeping the current version."
    target, pending = staged_paths
    if _relaunch_through_updater(app, target, pending):
        return True, f"Updating to v{staged} - restarting..."
    return False, "Update failed to launch - keeping the current version."


def auto_check(app, delay_seconds=20, dist_folder=None):
    """Fire-and-forget startup check. Silent unless an update applies
    (the relaunch + arrival notice speak for themselves)."""
    def work():
        try:
            time.sleep(delay_seconds)
            _try_update(app, dist_folder)
        except Exception:
            pass

    threading.Thread(target=work, daemon=True).start()


def manual_check(app, dist_folder=None):
    """On-demand check for the tray item / header button. Returns a short
    status line for the app's status bar (empty when nothing to say)."""
    try:
        applied, message = _try_update(app, dist_folder)
        return "" if applied else message
    except Exception:
        return "Update check failed - keeping the current version."


def consume_update_notice(app):
    """If the updater left a just-updated marker, balloon it once and
    clear it. Call after the tray icon is up."""
    try:
        notice = os.path.join(install_dir(), NOTICE_FILENAME)
        if not os.path.isfile(notice):
            return
        with open(notice, "r", encoding="utf-8") as f:
            old = f.read().strip()
        try:
            os.remove(notice)
        except OSError:
            pass
        if old and getattr(app, "tray", None) is not None:
            app.tray.notify(
                C.APP_TITLE,
                f"Updated to v{C.APP_VERSION}" + (f" (was v{old})." if old else ".")
            )
    except Exception:
        pass
