"""
Small local (per-Windows-user) settings file stored under %APPDATA%.
Remembers which employee this PC/profile belongs to, so the name is
only ever picked once, and remembers the resolved shared network path.
"""
import os
import json

from shared import constants as C
from shared.pathutils import normalize_shared_path, local_app_dir


def _settings_dir():
    return local_app_dir()


def _settings_path():
    return os.path.join(_settings_dir(), C.LOCAL_SETTINGS_FILENAME)


def load():
    path = _settings_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save(data):
    path = _settings_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_employee_name():
    return load().get("employee_name")


def set_employee_name(name):
    data = load()
    data["employee_name"] = name
    save(data)


def clear_employee_name():
    data = load()
    data.pop("employee_name", None)
    save(data)


def get_shared_path():
    raw = load().get("shared_path") or C.DEFAULT_SHARED_PATH
    return normalize_shared_path(raw)


def set_shared_path(path):
    data = load()
    data["shared_path"] = normalize_shared_path(path)
    save(data)


def config_file_path():
    return os.path.join(get_shared_path(), C.CONFIG_FILENAME)


def get_standard_times():
    """Per-PC override for the Log Today's Work tab's illustrative
    'X start + lunch -> out at Y' schedule (see
    client/main_app.py's _simulate_time_out) plus the 'need N hours to
    hit log-out Z' helper (see _hours_for_logout). Each value is an
    "HH:MM" 24-hour string, or None if that particular time hasn't been
    customized - the caller falls back to the built-in default (7:30 AM
    start, 12:00-1:00 PM lunch, 4:30 PM log-out) for any value that's
    None. This is a personal display preference only, so it's local to
    this PC/profile rather than synced via the shared drive - on a
    different PC it just shows the default again, which is fine for
    what this is."""
    d = load()
    return {
        "time_in": d.get("standard_time_in"),
        "lunch_out": d.get("standard_lunch_out"),
        "lunch_in": d.get("standard_lunch_in"),
        "log_out": d.get("standard_log_out"),
    }


def set_standard_times(time_in, lunch_out, lunch_in, log_out=None):
    """Each argument is an "HH:MM" 24-hour string, or None to leave that
    particular time at the built-in default."""
    data = load()
    data["standard_time_in"] = time_in
    data["standard_lunch_out"] = lunch_out
    data["standard_lunch_in"] = lunch_in
    data["standard_log_out"] = log_out
    save(data)


def clear_standard_times():
    data = load()
    for key in ("standard_time_in", "standard_lunch_out", "standard_lunch_in",
                "standard_log_out"):
        data.pop(key, None)
    save(data)
