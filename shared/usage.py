"""
Per-person feature-usage telemetry.

What and why: the Admin Dashboard answers "how much did people log", but
not "which parts of the app do people actually use, and where does their
logged time go". This module records the former in a cheap, local-first
way: each application calls `record("tab:navitool")` / `record("action:add_entry")`
and, once configured, those counters are periodically merged into one
small JSON file per PC per employee under
    <SharedPath>\\Logs\\.usage\\usage_<PC>_<employee>.json

Design rules (deliberate, they matter):
  - `record()` only bumps an integer in memory. It must never do I/O,
    never raise, and never take more than a few microseconds - it is
    called from UI event handlers.
  - The delta merge happens on a background daemon thread every
    FLUSH_SECONDS (and once on shutdown), so a slow or unreachable
    shared drive can never stall the UI. Failures keep the deltas
    pending and try again on the next flush.
  - Only counters are stored, never anything typed by a user (no job
    codes, no details text). Activity Mix reads the existing log
    workbooks instead.
  - Counts are merged (added), so two app instances / repeated flushes
    can't overwrite each other's numbers.
  - Files older than RETENTION_MONTHS are pruned on flush, and
    data_store.prune_usage() can do the same sweep from the UI.
"""
import datetime as dt
import json
import os
import socket
import threading
import time

from shared.applog import get_logger

log = get_logger(__name__)

FLUSH_SECONDS = 300
RETENTION_MONTHS = 12
MAX_KEYS = 5000          # hard stop on unbounded growth if record() is spammed
LOCK_TIMEOUT_S = 2.0

# Feature keys -> human labels. Anything recorded but not listed here is
# still stored and shown, just with its raw key, so adding a new hook
# never requires touching this table (but do add it for a nicer label).
FEATURE_LABELS = {
    "tab:log": "Screen: Log Today's Work",
    "tab:navitool": "Screen: NaviTool 2.0",
    "tab:dashboard": "Screen: My Dashboard",
    "action:add_entry": "Action: Add a log entry",
    "action:edit_entry": "Action: Edit a log entry",
    "action:delete_entry": "Action: Delete a log entry",
    "action:undo_delete": "Action: Undo a delete",
    "action:day_status": "Action: Mark holiday/leave",
    "action:cutoff_summary": "Action: Open Cutoff Summary",
    "action:admin_open": "Action: Open Admin Dashboard",
    "action:update_check": "Action: Check for updates",
    "action:open_link": "Action: Open a folder/file link",
    "action:nav_open_job": "Action: NaviTool - open a job",
    "action:nav_favorite": "Action: NaviTool - add a favorite",
    "action:nav_refresh": "Action: NaviTool - refresh jobs",
    "action:latest_scan": "Action: Latest Details - scan a job",
    "action:latest_open_folder": "Action: Latest Details - open a folder",
    "action:linkgen_open": "Action: Open the Link Generator",
}

TAB_ORDER = ["tab:log", "tab:navitool", "tab:dashboard"]

_lock = threading.Lock()
_counts = {}                  # (day_iso, key) -> int, pending
_enabled = False
_shared_path = None
_employee = None
_pc = ""
_thread = None
_stop = threading.Event()


def label_for(key):
    return FEATURE_LABELS.get(key, key)


def configure(shared_path, employee_name, enabled=True):
    """Point the recorder at a share/employee and start the flusher.
    Safe to call repeatedly; never raises."""
    global _enabled, _shared_path, _employee, _pc, _thread
    try:
        _shared_path = shared_path or None
        _employee = (employee_name or "").strip() or None
        _enabled = bool(enabled and _shared_path and _employee)
        if not _pc:
            try:
                _pc = socket.gethostname()
            except OSError:
                _pc = ""
        if not _enabled:
            return
        if _thread is None or not _thread.is_alive():
            _stop.clear()
            _thread = threading.Thread(target=_flusher_loop, name="usage-flush",
                                       daemon=True)
            _thread.start()
    except Exception:
        log.exception("usage.configure failed")


def shutdown():
    """Flush what's pending and stop the daemon (called on app quit)."""
    try:
        _stop.set()
    except Exception:
        pass
    flush()


def record(key):
    """Count one use of `key`. In-memory only - never raises, never blocks."""
    if not _enabled or not key:
        return
    try:
        today = dt.date.today().isoformat()
        k = (today, str(key))
        with _lock:
            if len(_counts) >= MAX_KEYS and k not in _counts:
                return
            _counts[k] = _counts.get(k, 0) + 1
    except Exception:
        pass


def pending_count():
    """Number of counted events not yet written (for tests/diagnostics)."""
    with _lock:
        return sum(_counts.values())


def flush():
    """Write all pending counters to the share. Returns True on success
    (including 'nothing to do'). Never raises."""
    if not _enabled or not _shared_path or not _employee:
        return False
    with _lock:
        batch = dict(_counts)
        _counts.clear()
    if not batch:
        return True
    try:
        path = _usage_file_path()
        merged = _read_file(path)
        days = merged.setdefault("days", {})
        for (day, key), n in batch.items():
            day_counts = days.setdefault(day, {})
            day_counts[key] = int(day_counts.get(key, 0)) + int(n)
        _prune_days(days)
        merged["employee"] = _employee
        merged["pc"] = _pc
        merged["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        _atomic_json(path, merged)
        return True
    except Exception as e:
        log.warning("usage flush failed (%s); keeping %d events for retry",
                    e, sum(batch.values()))
        with _lock:
            for k, n in batch.items():
                _counts[k] = _counts.get(k, 0) + n
        return False


def _usage_folder():
    return os.path.join(_shared_path, "Logs", ".usage")


def _usage_file_path():
    from shared.data_store import safe_filename
    return os.path.join(
        _usage_folder(),
        f"usage_{safe_filename(_pc or 'pc')}_{safe_filename(_employee or 'unknown')}.json")


def _read_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("days"), dict):
            return data
    except (OSError, ValueError):
        pass
    return {"pc": _pc, "employee": _employee, "days": {}}


def _prune_days(days):
    cutoff = _months_ago(dt.date.today(), RETENTION_MONTHS).isoformat()
    for day in list(days.keys()):
        if str(day) < cutoff:
            del days[day]


def _months_ago(day, months):
    month_index = day.year * 12 + (day.month - 1) - months
    year, month = divmod(month_index, 12)
    month += 1
    try:
        return dt.date(year, month, day.day)
    except ValueError:
        return dt.date(year, month, 28)


def _atomic_json(path, payload):
    """tmp-file + os.replace, with a short-lived lock file so two app
    instances on the same PC don't lose each other's deltas."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    lock_path = path + ".lock"
    deadline = time.time() + LOCK_TIMEOUT_S
    locked = False
    while time.time() < deadline:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            locked = True
            break
        except FileExistsError:
            time.sleep(0.05)
        except OSError:
            break
    try:
        tmp_path = os.path.join(folder, f".~{os.path.basename(path)}.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, sort_keys=True)
        os.replace(tmp_path, path)
    finally:
        if locked:
            try:
                os.remove(lock_path)
            except OSError:
                pass


def _flusher_loop():
    while not _stop.wait(FLUSH_SECONDS):
        try:
            flush()
        except Exception:
            log.exception("usage flush loop error")
