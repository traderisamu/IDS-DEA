"""
Each employee gets their own Excel workbook on the shared drive:
    <SharedPath>\\Logs\\<Employee Name>.xlsx

Sheet "Log":        Date | JOB | Work Description | Hours Used | Details | Remarks | Entered At
Sheet "DayStatus":  Date | Status (Holiday/Leave/Workday) | Note

Kept as plain per-employee Excel files (per user's preference) rather
than one shared database - each file is small and only ever written
by its own owner, so lock/contention risk stays low.
"""
import os
import re
import csv
import json
import socket
import datetime as dt
import openpyxl
from openpyxl.styles import Font, PatternFill

from .applog import get_logger

log = get_logger(__name__)

LOG_HEADERS = ["Date", "JOB", "Work Description", "Hours Used", "Details", "Remarks", "Entered At"]
STATUS_HEADERS = ["Date", "Status", "Note"]

HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF")
HEADER_FILL = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
BODY_FONT = Font(name="Arial", size=10)

STATUS_HOLIDAY = "Holiday"
STATUS_LEAVE = "Leave"


class FileLockedError(Exception):
    """Raised when an employee's Excel file couldn't be saved because
    it's currently open (locked) in another program - almost always
    Excel itself, opened by an admin poking around or the employee
    double-clicking their own file out of curiosity. Callers should show
    a friendly 'please close it and try again' message rather than a
    raw traceback."""
    pass


class DriveUnreachableError(Exception):
    """Raised when the shared root folder itself can't be reached (a
    disconnected VPN, an unmounted network drive, a mid-session
    connection drop) - as opposed to one specific employee simply not
    having a log file yet, which is completely normal and NOT an error.
    Callers should tell the user their data is safe and this is just a
    connectivity hiccup, rather than showing what looks like an empty/
    all-missing day that never happened."""
    pass


def check_shared_reachable(shared_path):
    """Raises DriveUnreachableError if the shared root itself isn't
    reachable right now. Doesn't touch any specific employee's file -
    that's a separate, much more common and completely normal case
    (new employee, first day) handled by the individual read functions."""
    if not shared_path or not os.path.isdir(shared_path):
        raise DriveUnreachableError(
            f"Can't reach the shared folder right now:\n{shared_path}\n\n"
            "This usually means a network drive or VPN connection dropped. "
            "Your data is safe - this is just a connectivity issue, try again "
            "in a moment."
        )


def _cleanup_tmp(tmp_path):
    try:
        if os.path.isfile(tmp_path):
            os.remove(tmp_path)
    except OSError:
        pass


def _atomic_write(save_fn, path):
    """General version: `save_fn(tmp_path)` does the actual writing to a
    temp file in the same folder as `path`, which is then swapped into
    place with a single rename. See the module-level notes above for why
    (corruption safety + a friendly message instead of a raw traceback
    when `path` is locked open in another program)."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    tmp_path = os.path.join(folder, f".~{os.path.basename(path)}.tmp")
    try:
        save_fn(tmp_path)
    except PermissionError as e:
        log.warning("save blocked (file locked?) while writing temp file for %s: %s", path, e)
        _cleanup_tmp(tmp_path)
        raise FileLockedError(
            f"Could not write to:\n{path}\n\n"
            "This usually means the file is currently open in Excel (or "
            "another program). Please close it and try again."
        ) from e
    try:
        os.replace(tmp_path, path)
    except PermissionError as e:
        log.warning("save blocked (file locked?) while replacing %s: %s", path, e)
        _cleanup_tmp(tmp_path)
        raise FileLockedError(
            f"Could not save changes to:\n{path}\n\n"
            "This usually means the file is currently open in Excel (or "
            "another program). Please close it and try again."
        ) from e
    except OSError as e:
        log.warning("save failed while replacing %s: %s", path, e)
        _cleanup_tmp(tmp_path)
        raise FileLockedError(f"Could not save changes to:\n{path}\n\n{e}") from e


def _atomic_save(wb, path):
    """Convenience wrapper for the common case of saving an openpyxl
    workbook - see _atomic_write for the safety properties this gives."""
    _atomic_write(lambda tmp_path: wb.save(tmp_path), path)


def _normalize_name(name):
    return re.sub(r"\s+", " ", (name or "").strip()).casefold()


def _resolve_existing_file_path(shared_path, employee_name):
    """Exact match first (the normal case - and always what's used when
    saving/writing, see add_log_entry). Falls back to a whitespace/case
    -insensitive match against files already sitting in the Logs folder.

    Why this matters: each employee's local PC remembers the exact name
    they first picked from the Employees roster dropdown, and never asks
    again. If the roster is edited afterwards - a typo fix, a spacing
    change, a capitalization tweak - that person's app keeps saving
    under their original (now slightly different) file name forever,
    while anything reading the CURRENT roster (like the Admin Dashboard's
    Missing Logs list) looks for the NEW name and finds nothing, wrongly
    reporting someone who has actually been logging every day as
    missing. This reconciles the two without silently merging two
    genuinely different people: it only falls back when there's exactly
    one on-disk file that normalizes to the same name."""
    exact = employee_file_path(shared_path, employee_name)
    if os.path.isfile(exact):
        return exact
    folder = logs_folder(shared_path)
    if not os.path.isdir(folder):
        return exact
    target = _normalize_name(employee_name)
    matches = []
    try:
        for fname in os.listdir(folder):
            if not fname.lower().endswith(".xlsx"):
                continue
            stem = os.path.splitext(fname)[0]
            if _normalize_name(stem) == target:
                matches.append(fname)
    except OSError:
        return exact
    if len(matches) == 1:
        return os.path.join(folder, matches[0])
    return exact  # none, or more than one ambiguous match - behave as before


def safe_filename(name):
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", name).strip()
    return cleaned


def logs_folder(shared_path):
    return os.path.join(shared_path, "Logs")


def employee_file_path(shared_path, employee_name):
    return os.path.join(logs_folder(shared_path), f"{safe_filename(employee_name)}.xlsx")


VERSIONS_SUBFOLDER = ".versions"


def versions_folder(shared_path):
    return os.path.join(logs_folder(shared_path), VERSIONS_SUBFOLDER)


def heartbeat_file_path(shared_path, employee_name):
    return os.path.join(versions_folder(shared_path), f"{safe_filename(employee_name)}.json")


def write_heartbeat(shared_path, employee_name, app_version):
    """Best-effort 'I am running version X' stamp for the Admin Dashboard's
    per-person version chips. Called at app startup and whenever the main
    window is opened - never allowed to block or break a launch, so every
    failure mode (unreachable drive, locked file, anything else) just
    means 'no fresh heartbeat' and returns False."""
    try:
        if not shared_path or not os.path.isdir(shared_path):
            return False
        os.makedirs(versions_folder(shared_path), exist_ok=True)
        try:
            pc = socket.gethostname()
        except OSError:
            pc = ""
        payload = {
            "app_version": str(app_version),
            "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "pc": pc,
        }

        def save_fn(tmp_path):
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f)

        _atomic_write(save_fn, heartbeat_file_path(shared_path, employee_name))
        return True
    except (OSError, FileLockedError):
        return False


def read_version_heartbeats(shared_path):
    """{employee_name: {"app_version", "updated_at" (datetime|None),
    "pc"}} for every heartbeat file found. Skips missing/corrupt files;
    raises DriveUnreachableError when the share itself is down."""
    check_shared_reachable(shared_path)
    folder = versions_folder(shared_path)
    out = {}
    if not os.path.isdir(folder):
        return out
    try:
        fnames = os.listdir(folder)
    except OSError:
        return out
    for fname in fnames:
        if not fname.lower().endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, fname), "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict) or not data.get("app_version"):
                continue
            try:
                updated = dt.datetime.fromisoformat(str(data.get("updated_at", "")))
            except ValueError:
                updated = None
            out[os.path.splitext(fname)[0]] = {
                "app_version": str(data["app_version"]),
                "updated_at": updated,
                "pc": str(data.get("pc") or ""),
            }
        except (OSError, ValueError):
            continue
    return out


def ensure_logs_folder(shared_path):
    folder = logs_folder(shared_path)
    os.makedirs(folder, exist_ok=True)
    return folder


def _new_workbook():
    wb = openpyxl.Workbook()
    ws_log = wb.active
    ws_log.title = "Log"
    for i, h in enumerate(LOG_HEADERS, start=1):
        c = ws_log.cell(row=1, column=i, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
    ws_log.freeze_panes = "A2"

    ws_status = wb.create_sheet("DayStatus")
    for i, h in enumerate(STATUS_HEADERS, start=1):
        c = ws_status.cell(row=1, column=i, value=h)
        c.font = HEADER_FONT
        c.fill = HEADER_FILL
    ws_status.freeze_panes = "A2"
    return wb


def ensure_employee_file(shared_path, employee_name):
    ensure_logs_folder(shared_path)
    path = employee_file_path(shared_path, employee_name)
    if not os.path.isfile(path):
        wb = _new_workbook()
        _atomic_save(wb, path)
    return path


def _date_str(d):
    if isinstance(d, dt.datetime):
        d = d.date()
    if isinstance(d, dt.date):
        return d.isoformat()
    return str(d)


def _entered_at_str(v):
    """Normalizes the 'Entered At' cell (column G of the Log sheet) to a
    plain, consistently-formatted string, regardless of what type
    openpyxl handed back for it. This app always WRITES that column as
    plain text (see add_log_entry/update_log_entry), but a cell that's
    ever been manually retyped, reformatted, or pasted into in Excel can
    come back from openpyxl as a real datetime.datetime/date instead of
    text, if Excel decided the cell looks like a date. Mixing str and
    datetime values in the same column then crashes any naive sort by
    this field ('<' isn't defined between datetime and str in Python 3)
    - so every value gets coerced to one consistent, still-chronologically-
    sortable string form right here, before it goes anywhere else."""
    if v is None:
        return ""
    if isinstance(v, dt.datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S.%f")
    if isinstance(v, dt.date):
        return v.isoformat() + " 00:00:00.000000"
    return str(v)


def add_log_entry(shared_path, employee_name, entry_date, job, work_desc, hours, details, remarks):
    """entry_date: datetime.date. Returns the new total hours for that date."""
    path = ensure_employee_file(shared_path, employee_name)
    wb = openpyxl.load_workbook(path)
    ws = wb["Log"]
    next_row = ws.max_row + 1
    ws.cell(row=next_row, column=1, value=_date_str(entry_date)).font = BODY_FONT
    ws.cell(row=next_row, column=2, value=job or "").font = BODY_FONT
    ws.cell(row=next_row, column=3, value=work_desc or "").font = BODY_FONT
    ws.cell(row=next_row, column=4, value=float(hours)).font = BODY_FONT
    ws.cell(row=next_row, column=5, value=details or "").font = BODY_FONT
    ws.cell(row=next_row, column=6, value=remarks or "").font = BODY_FONT
    ws.cell(row=next_row, column=7, value=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")).font = BODY_FONT
    _atomic_save(wb, path)
    wb.close()
    return get_day_total_hours(shared_path, employee_name, entry_date)


def update_log_entry(shared_path, employee_name, excel_row, job, work_desc, hours, details, remarks):
    """Edits an existing entry in place (identified by its Excel row
    number, as returned by read_log_entries) rather than delete+re-add,
    so the entry keeps its original position and entered_at stays intact
    except we bump entered_at to reflect the edit time."""
    path = ensure_employee_file(shared_path, employee_name)
    wb = openpyxl.load_workbook(path)
    ws = wb["Log"]
    ws.cell(row=excel_row, column=2, value=job or "").font = BODY_FONT
    ws.cell(row=excel_row, column=3, value=work_desc or "").font = BODY_FONT
    ws.cell(row=excel_row, column=4, value=float(hours)).font = BODY_FONT
    ws.cell(row=excel_row, column=5, value=details or "").font = BODY_FONT
    ws.cell(row=excel_row, column=6, value=remarks or "").font = BODY_FONT
    ws.cell(row=excel_row, column=7, value=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")).font = BODY_FONT
    _atomic_save(wb, path)
    wb.close()


def delete_log_entry(shared_path, employee_name, row_index_in_sheet):
    """row_index_in_sheet is the actual Excel row number (as returned in read_log_entries)."""
    path = ensure_employee_file(shared_path, employee_name)
    wb = openpyxl.load_workbook(path)
    ws = wb["Log"]
    ws.delete_rows(row_index_in_sheet, 1)
    _atomic_save(wb, path)
    wb.close()


def read_log_entries(shared_path, employee_name, start_date=None, end_date=None):
    """Returns list of dicts, each with an 'excel_row' key for later editing/deleting."""
    path = _resolve_existing_file_path(shared_path, employee_name)
    if not os.path.isfile(path):
        check_shared_reachable(shared_path)  # tell "drive is down" apart from "no file yet"
        return []
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb["Log"]
    results = []
    for row in ws.iter_rows(min_row=2):
        if row[0].value is None:
            continue
        date_val = _date_str(row[0].value)
        if start_date and date_val < start_date.isoformat():
            continue
        if end_date and date_val > end_date.isoformat():
            continue
        results.append({
            "excel_row": row[0].row,
            "date": date_val,
            "job": row[1].value,
            "work_description": row[2].value,
            "hours": row[3].value or 0,
            "details": row[4].value,
            "remarks": row[5].value,
            "entered_at": _entered_at_str(row[6].value),
        })
    wb.close()
    return results


def _distinct_most_recent(values_with_time, limit):
    """values_with_time: list of (value, entered_at_str). Returns distinct
    values ordered most-recently-used first (based on entered_at, not the
    logged date, so back-dated entries don't distort recency)."""
    ordered = sorted(values_with_time, key=lambda x: x[1] or "", reverse=True)
    out = []
    seen = set()
    for value, _ts in ordered:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
        if len(out) >= limit:
            break
    return out


def get_employee_job_code_history(shared_path, employee_name, limit=25):
    """Distinct JOB codes this employee has personally used before, most
    recently used first - keeps each individual's own codes consistent
    without restricting them to a fixed company-wide list."""
    entries = read_log_entries(shared_path, employee_name)
    pairs = [(e["job"], e["entered_at"]) for e in entries if e.get("job")]
    return _distinct_most_recent(pairs, limit)


def get_employee_details_history(shared_path, employee_name, job=None, work_description=None, limit=15):
    """Distinct Details strings this employee has personally used before,
    most recently used first, scoped to whichever of JOB Code / Work
    Description are given. Details phrasing is often specific to BOTH -
    a reference like 'SC01' logged under one JOB Code has no business
    being suggested for a completely different JOB Code, even under the
    same Work Description, since that's how a copy-paste mistake happens
    (the wrong reference ending up on the wrong job)."""
    entries = read_log_entries(shared_path, employee_name)
    if job:
        entries = [e for e in entries if e.get("job") == job]
    if work_description:
        entries = [e for e in entries if e.get("work_description") == work_description]
    pairs = [(e["details"], e["entered_at"]) for e in entries if e.get("details")]
    return _distinct_most_recent(pairs, limit)


def get_day_total_hours(shared_path, employee_name, the_date):
    entries = read_log_entries(shared_path, employee_name, the_date, the_date)
    return sum(float(e["hours"] or 0) for e in entries)


def get_month_totals(shared_path, employee_name, year, month):
    """Returns {date_iso: total_hours} for every logged day in that month."""
    start = dt.date(year, month, 1)
    end = dt.date(year, month, 28) + dt.timedelta(days=4)
    end = end.replace(day=1) - dt.timedelta(days=1)
    entries = read_log_entries(shared_path, employee_name, start, end)
    totals = {}
    for e in entries:
        totals[e["date"]] = totals.get(e["date"], 0) + float(e["hours"] or 0)
    return totals


# ---------------------- Day status (Holiday / Leave) ----------------------

def set_day_status(shared_path, employee_name, the_date, status, note=""):
    path = ensure_employee_file(shared_path, employee_name)
    wb = openpyxl.load_workbook(path)
    ws = wb["DayStatus"]
    date_iso = _date_str(the_date)
    target_row = None
    for row in ws.iter_rows(min_row=2):
        if row[0].value and _date_str(row[0].value) == date_iso:
            target_row = row[0].row
            break
    if status is None:
        # clear it
        if target_row:
            ws.delete_rows(target_row, 1)
    else:
        if target_row is None:
            target_row = ws.max_row + 1
        ws.cell(row=target_row, column=1, value=date_iso).font = BODY_FONT
        ws.cell(row=target_row, column=2, value=status).font = BODY_FONT
        ws.cell(row=target_row, column=3, value=note or "").font = BODY_FONT
    _atomic_save(wb, path)
    wb.close()


def get_month_day_statuses(shared_path, employee_name, year, month):
    """Returns {date_iso: (status, note)}."""
    path = _resolve_existing_file_path(shared_path, employee_name)
    if not os.path.isfile(path):
        check_shared_reachable(shared_path)  # tell "drive is down" apart from "no file yet"
        return {}
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb["DayStatus"]
    prefix = f"{year:04d}-{month:02d}"
    out = {}
    for row in ws.iter_rows(min_row=2):
        if row[0].value is None:
            continue
        date_iso = _date_str(row[0].value)
        if date_iso.startswith(prefix):
            out[date_iso] = (row[1].value, row[2].value)
    wb.close()
    return out


def get_day_status(shared_path, employee_name, the_date):
    year, month = the_date.year, the_date.month
    statuses = get_month_day_statuses(shared_path, employee_name, year, month)
    return statuses.get(_date_str(the_date))


# ---------------------------- Admin aggregation ----------------------------


def get_day_completion(shared_path, employee_name, the_date, min_hours):
    """'Is today's log actually DONE' - complete only once total hours
    reach min_hours (the same threshold that turns the calendar day
    green), or the day is a personal Holiday/Leave mark. Used to decide
    whether the individual's own reminder popup should keep nagging (so
    a lone 1-hour entry no longer silences the 3:00 PM reminder)."""
    status = get_day_status(shared_path, employee_name, the_date)
    if status and status[0] in (STATUS_HOLIDAY, STATUS_LEAVE):
        return True, 0.0, "on " + status[0]
    total = get_day_total_hours(shared_path, employee_name, the_date)
    complete = total >= min_hours
    reason = f"{total:g}h logged (need {min_hours:g}h)" if total else "no entry"
    return complete, total, reason


def admin_month_grid(shared_path, employee_list, year, month, min_hours_green):
    """
    Returns {employee_name: {date_iso: 'green'|'orange'|'blue'|'red'|'none'}}
    for the whole month, for every employee in employee_list.
    """
    today = dt.date.today()
    first = dt.date(year, month, 1)
    last = (dt.date(year, month, 28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)

    grid = {}
    for name, _team in employee_list:
        totals = get_month_totals(shared_path, name, year, month)
        statuses = get_month_day_statuses(shared_path, name, year, month)
        day_map = {}
        d = first
        while d <= last:
            iso = d.isoformat()
            if iso in statuses and statuses[iso][0] in (STATUS_HOLIDAY, STATUS_LEAVE):
                day_map[iso] = "blue"
            elif totals.get(iso, 0) >= min_hours_green:
                day_map[iso] = "green"
            elif totals.get(iso, 0) > 0:
                day_map[iso] = "orange"
            elif d.weekday() >= 5:
                day_map[iso] = "weekend"
            elif d > today:
                day_map[iso] = "future"
            else:
                day_map[iso] = "red"
            d += dt.timedelta(days=1)
        grid[name] = day_map
    return grid


def team_average_hours(shared_path, employee_list, year, month):
    """employee_list: list[(name, team)]. For the given month, returns
    {team: (avg_hours_per_employee, employee_count)} - each employee's
    total logged hours for the month, averaged across everyone on that
    team. A quick comparative view of which teams are logging more or
    less, without needing the full day-by-day grid."""
    team_totals = {}
    team_counts = {}
    for name, team in employee_list:
        team = team or "(no team)"
        totals = get_month_totals(shared_path, name, year, month)
        team_totals[team] = team_totals.get(team, 0.0) + sum(totals.values())
        team_counts[team] = team_counts.get(team, 0) + 1
    return {team: (team_totals[team] / count, count) for team, count in team_counts.items()}


def rank_individuals_by_hours(shared_path, employee_list, year, month):
    """employee_list: list[(name, team)]. Returns [(name, team,
    total_hours), ...] for the given month, sorted busiest-first (total
    hours descending) - the full ranking, not just the top one. Ties
    keep roster order."""
    rows = []
    for name, team in employee_list:
        total = sum(get_month_totals(shared_path, name, year, month).values())
        rows.append((name, team or "(no team)", total))
    rows.sort(key=lambda r: -r[2])
    return rows


def rank_teams_by_avg_hours(shared_path, employee_list, year, month):
    """Returns [(team, avg_hours_per_employee, employee_count), ...] for
    the given month, sorted busiest-first (average hours descending)."""
    avgs = team_average_hours(shared_path, employee_list, year, month)
    rows = [(team, avg, count) for team, (avg, count) in avgs.items()]
    rows.sort(key=lambda r: -r[1])
    return rows


def most_overworked(shared_path, employee_list, year, month):
    """employee_list: list[(name, team)]. Thin convenience wrapper: just
    the #1 entries from rank_individuals_by_hours / rank_teams_by_avg_hours,
    for a quick one-line dashboard summary. See those two functions for
    the full ranking of everyone, not just the top one. Comes back as
    (None, None, 0.0, None, 0.0) if employee_list is empty."""
    individuals = rank_individuals_by_hours(shared_path, employee_list, year, month)
    if not individuals:
        return None, None, 0.0, None, 0.0
    top_name, top_team_of, top_hours = individuals[0]

    teams = rank_teams_by_avg_hours(shared_path, employee_list, year, month)
    top_team_name, top_team_avg = (teams[0][0], teams[0][1]) if teams else (None, 0.0)

    return top_name, top_team_of, top_hours, top_team_name, top_team_avg


# ------------------------- Personal dashboard stats -------------------------
#
# Everything below powers the "My Dashboard" tab - an individual's own
# efficiency view. All date-range based (rather than fixed-month) so the
# dashboard's period selector (this week / this month / last 3 months...)
# can drive all of these the same way.

def hours_by_work_description(shared_path, employee_name, start_date, end_date):
    """Returns {work_description: total_hours} for entries in
    [start_date, end_date] - "where does my time actually go"."""
    entries = read_log_entries(shared_path, employee_name, start_date, end_date)
    totals = {}
    for e in entries:
        wd = e["work_description"] or "(unspecified)"
        totals[wd] = totals.get(wd, 0.0) + float(e["hours"] or 0)
    return totals


def hours_by_job(shared_path, employee_name, start_date, end_date):
    """Returns {job_code: total_hours} for entries in [start_date, end_date]."""
    entries = read_log_entries(shared_path, employee_name, start_date, end_date)
    totals = {}
    for e in entries:
        job = e["job"] or "(unspecified)"
        totals[job] = totals.get(job, 0.0) + float(e["hours"] or 0)
    return totals


def employee_total_hours(shared_path, employee_name, start_date, end_date):
    """Total hours logged in [start_date, end_date]."""
    entries = read_log_entries(shared_path, employee_name, start_date, end_date)
    return sum(float(e["hours"] or 0) for e in entries)


WORK_DESC_CALC_CREATION = "Create Calculation Template"
WORK_DESC_CALC_RUN = "Run Calculation Joints"
WORK_DESC_SHOP_REVIEW = "Review Shop & Erection Dwgs"
# These three must match the "Work Description" text exactly as it
# appears in the 'Work Items' sheet of DEA_Config.xlsx - if an admin
# renames one of these three rows there, update the matching constant
# above too, or that efficiency metric will just show "No data" (it
# won't error, it'll just stop finding matching entries).


def _leading_number(text):
    """First number (int or decimal) found in a free-text Details
    string, e.g. '12 joints' or '8 sheets, north elevation' -> 12.0 /
    8.0. Returns None if there's no number in there at all, so the
    caller can skip that entry rather than silently treating it as 0."""
    if not text:
        return None
    match = re.search(r"\d+(?:\.\d+)?", str(text))
    return float(match.group()) if match else None


def efficiency_metrics(shared_path, employee_name, start_date, end_date):
    """Three per-unit efficiency numbers for [start_date, end_date],
    each hours spent per unit of output for one specific Work
    Description (see the WORK_DESC_* constants above):
      - 'calc'  : hours per DISTINCT calc name logged under Create
        Calculation Template - the Details column holds the calc name,
        not a count, so the "unit" here is how many different calcs
        were touched, not a number typed into Details.
      - 'joint' : hours per joint logged under Run Calculation Joints -
        the Details column is expected to hold a joint count; the
        leading number in it is used.
      - 'sheet' : hours per sheet logged under Review Shop & Erection
        Dwgs - same idea, leading number in Details is the sheet count.
    An entry that doesn't have a usable Details value for its metric
    (blank, or no leading number where a count is expected) is simply
    excluded from that metric's hours AND unit count - it shouldn't
    silently count as a free 0-unit hour and skew the average down.
    Returns {'calc': {...}, 'joint': {...}, 'sheet': {...}}, each a
    dict with 'hours', 'units', 'per_unit' (None if there's no usable
    data at all for that metric in this period - shown as "No data"
    rather than a misleading 0.0)."""
    entries = read_log_entries(shared_path, employee_name, start_date, end_date)

    def calc_metric():
        hours, calc_names = 0.0, set()
        for e in entries:
            if e.get("work_description") != WORK_DESC_CALC_CREATION:
                continue
            name = e.get("details")
            if not name or not str(name).strip():
                continue
            hours += float(e["hours"] or 0)
            calc_names.add(str(name).strip().lower())
        return hours, float(len(calc_names))

    def counted_metric(work_desc):
        hours, units = 0.0, 0.0
        for e in entries:
            if e.get("work_description") != work_desc:
                continue
            n = _leading_number(e.get("details"))
            if n is None:
                continue
            hours += float(e["hours"] or 0)
            units += n
        return hours, units

    def pack(hours, units):
        return {"hours": hours, "units": units, "per_unit": (hours / units) if units else None}

    calc_hours, calc_units = calc_metric()
    joint_hours, joint_units = counted_metric(WORK_DESC_CALC_RUN)
    sheet_hours, sheet_units = counted_metric(WORK_DESC_SHOP_REVIEW)
    return {
        "calc": pack(calc_hours, calc_units),
        "joint": pack(joint_hours, joint_units),
        "sheet": pack(sheet_hours, sheet_units),
    }


# ------------------------------- Cutoff Summary -----------------------------
#
# The company's semi-monthly payroll cutoffs: the 23rd of one month
# through the 7th of the next, and the 8th through the 22nd of the same
# month. Both always fall on real calendar days (23, 22, 8, 7 exist in
# every month), so none of this needs Feb-29-style edge-case handling.


def _add_months(date_val, delta):
    """date_val.replace() with an arbitrary month delta, wrapping the
    year - only ever called with day=1, so there's no day-doesn't-exist
    risk (e.g. landing on Feb 30)."""
    total = date_val.month - 1 + delta
    year = date_val.year + total // 12
    month = total % 12 + 1
    return date_val.replace(year=year, month=month)


def cutoff_bounds(reference_date):
    """Returns (start_date, end_date, label) for whichever of the two
    cutoff periods contains reference_date."""
    d = reference_date
    if 8 <= d.day <= 22:
        start, end = d.replace(day=8), d.replace(day=22)
    elif d.day >= 23:
        start = d.replace(day=23)
        end = _add_months(d.replace(day=1), 1).replace(day=7)
    else:  # day 1-7
        start = _add_months(d.replace(day=1), -1).replace(day=23)
        end = d.replace(day=7)
    label = f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"
    return start, end, label


def list_recent_cutoffs(reference_date=None, count_before=2, count_after=1):
    """A handful of cutoff periods around reference_date (default
    today), oldest first - for populating a period-picker dropdown.
    Always includes whichever cutoff contains reference_date itself."""
    reference_date = reference_date or dt.date.today()
    cur_start, cur_end, cur_label = cutoff_bounds(reference_date)
    cutoffs = [(cur_start, cur_end, cur_label)]

    probe = cur_start
    for _ in range(count_before):
        probe = probe - dt.timedelta(days=1)  # last day of the previous cutoff
        s, e, l = cutoff_bounds(probe)
        cutoffs.append((s, e, l))
        probe = s

    probe = cur_end
    for _ in range(count_after):
        probe = probe + dt.timedelta(days=1)  # first day of the next cutoff
        s, e, l = cutoff_bounds(probe)
        cutoffs.append((s, e, l))
        probe = e

    cutoffs.sort(key=lambda t: t[0])
    return cutoffs


def simulate_time_out(total_hours, anchor_date=None,
                       start_time=dt.time(7, 30), lunch_start=dt.time(12, 0),
                       lunch_end=dt.time(13, 0)):
    """Illustrative only - not tied to any actual login/logout tracking.
    Just answers: 'if the workday started at start_time and included the
    standard lunch break, what time would logging this many hours put
    the clock-out at?' Returns a datetime, or None if total_hours is 0
    (there's nothing to simulate a clock-out from)."""
    if not total_hours or total_hours <= 0:
        return None
    anchor = anchor_date or dt.date.today()
    login = dt.datetime.combine(anchor, start_time)
    l_start = dt.datetime.combine(anchor, lunch_start)
    l_end = dt.datetime.combine(anchor, lunch_end)
    remaining = dt.timedelta(hours=total_hours)

    if login < l_start:
        before_lunch = l_start - login
        if remaining <= before_lunch:
            return login + remaining
        return l_end + (remaining - before_lunch)
    return login + remaining


def cutoff_summary(shared_path, employee_name, start_date, end_date):
    """Builds the per-day / per-JOB-code table behind the Cutoff Summary
    view/export - one row per calendar day in [start_date, end_date],
    meant to make manual entry into the company's Online Timesheet
    Portal faster (see the portal's own per-JOB-code columns - this
    mirrors that part of the layout; it does NOT try to reproduce the
    portal's actual clock-in/out times, which this app has no way of
    knowing).

    Only JOB codes with at least one hour logged SOMEWHERE in this
    period get a column - a code nobody touched this period just isn't
    shown, rather than cluttering the table with an all-blank column.
    Columns are sorted alphabetically, left to right. Matching against
    logged entries is case-insensitive/whitespace-trimmed, so
    'engg-cub' and 'ENGG-CUB' typed on different days still count as
    the same column (using whichever spelling was typed first).

    Each day gets:
      - total_hours: sum of everything logged that day.
      - per_job: {job_code: hours}, keyed by the exact column labels
        returned in 'job_codes' below.
    Returns {'job_codes': [...], 'days': [...]}."""
    entries = read_log_entries(shared_path, employee_name, start_date, end_date)
    by_date = {}
    hours_norm = {}  # normalized JOB code -> [first-seen original spelling, total hours]
    for e in entries:
        by_date.setdefault(e["date"], []).append(e)
        job = str(e.get("job") or "").strip()
        if not job:
            continue
        norm = job.upper()
        hrs = float(e["hours"] or 0)
        if norm in hours_norm:
            hours_norm[norm][1] += hrs
        else:
            hours_norm[norm] = [job, hrs]

    job_codes = sorted((orig for orig, total in hours_norm.values() if total > 0), key=str.upper)
    job_codes_norm = [c.upper() for c in job_codes]

    days = []
    d = start_date
    while d <= end_date:
        day_entries = by_date.get(d.isoformat(), [])
        total = sum(float(e["hours"] or 0) for e in day_entries)
        status = get_day_status(shared_path, employee_name, d)
        per_job = {}
        for code, code_norm in zip(job_codes, job_codes_norm):
            per_job[code] = sum(
                float(e["hours"] or 0) for e in day_entries
                if str(e.get("job") or "").strip().upper() == code_norm
            )
        days.append({
            "date": d, "weekday": d.strftime("%a"), "total_hours": total,
            "status": status[0] if status else None,
            "per_job": per_job,
        })
        d += dt.timedelta(days=1)

    return {"job_codes": job_codes, "days": days}


def export_cutoff_summary(shared_path, employee_name, start_date, end_date, out_path):
    """Writes cutoff_summary() to out_path (.xlsx or .csv, by
    extension) - Day, Date, Total, then one column per JOB code - so a
    day's row can be read straight off and typed into the portal.
    Returns the summary dict that was written, so the caller can show a
    "totalled N hours across M days" summary without re-reading the
    file."""
    summary = cutoff_summary(shared_path, employee_name, start_date, end_date)
    job_codes = summary["job_codes"]
    headers = ["", "Date", "Total"] + job_codes
    weekend_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
    total_font = Font(name="Arial", size=10, bold=True)

    def write_xlsx(tmp_path):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Cutoff Summary"
        for i, h in enumerate(headers, start=1):
            c = ws.cell(row=1, column=i, value=h)
            c.font, c.fill = HEADER_FONT, HEADER_FILL
        ws.freeze_panes = "A2"

        for r, day in enumerate(summary["days"], start=2):
            is_weekend = day["date"].weekday() >= 5
            ws.cell(row=r, column=1, value=day["weekday"]).font = BODY_FONT
            ws.cell(row=r, column=2, value=day["date"].strftime("%m/%d")).font = BODY_FONT
            ws.cell(row=r, column=3, value=round(day["total_hours"], 2)).font = total_font
            for j, code in enumerate(job_codes, start=4):
                hrs = day["per_job"].get(code, 0.0)
                cell = ws.cell(row=r, column=j)
                if hrs:
                    cell.value = round(hrs, 2)
                cell.font = BODY_FONT
            if is_weekend:
                for c in range(1, len(headers) + 1):
                    ws.cell(row=r, column=c).fill = weekend_fill

        widths = [7, 9, 8] + [11] * len(job_codes)
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
        wb.save(tmp_path)

    def write_csv(tmp_path):
        with open(tmp_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for day in summary["days"]:
                row = [day["weekday"], day["date"].strftime("%m/%d"), round(day["total_hours"], 2)]
                row += [round(day["per_job"].get(code, 0.0), 2) or "" for code in job_codes]
                writer.writerow(row)

    ext = os.path.splitext(out_path)[1].lower()
    _atomic_write(write_csv if ext == ".csv" else write_xlsx, out_path)
    return summary


# ------------------------------- Export ------------------------------------

EXPORT_HEADERS = ["Employee", "Team", "Date", "JOB", "Work Description", "Hours", "Details", "Remarks"]


def gather_month_export_rows(shared_path, employee_list, year, month):
    """employee_list: list[(name, team)]. Returns a list of row tuples
    matching EXPORT_HEADERS, across every employee for the given month,
    sorted by employee then date. Holiday/Leave-marked days show up too
    (Work Description holds the mark, Hours left blank), so a combined
    export tells the whole story without needing every employee's file
    open side by side."""
    start = dt.date(year, month, 1)
    end = (dt.date(year, month, 28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1)
    rows = []
    for name, team in employee_list:
        for e in read_log_entries(shared_path, name, start, end):
            rows.append((name, team, e["date"], e["job"] or "", e["work_description"] or "",
                         float(e["hours"] or 0), e["details"] or "", e["remarks"] or ""))
        for date_iso, (status, note) in get_month_day_statuses(shared_path, name, year, month).items():
            if status in (STATUS_HOLIDAY, STATUS_LEAVE):
                rows.append((name, team, date_iso, "", f"({status})", "", note or "", ""))
    rows.sort(key=lambda r: (r[0], r[2]))
    return rows


def export_month(shared_path, employee_list, year, month, out_path):
    """Writes gather_month_export_rows() to out_path - .xlsx or .csv,
    picked by the file extension (anything else defaults to .xlsx).
    Returns the number of rows written. Uses the same atomic-write
    safety as the per-employee saves, so exporting over a file that's
    currently open elsewhere gives a friendly FileLockedError instead of
    a raw traceback, and a save that gets interrupted can't leave a
    half-written export behind."""
    rows = gather_month_export_rows(shared_path, employee_list, year, month)

    def write_xlsx(tmp_path):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = f"{year:04d}-{month:02d}"
        for i, h in enumerate(EXPORT_HEADERS, start=1):
            c = ws.cell(row=1, column=i, value=h)
            c.font = HEADER_FONT
            c.fill = HEADER_FILL
        ws.freeze_panes = "A2"
        for r, row in enumerate(rows, start=2):
            for i, val in enumerate(row, start=1):
                ws.cell(row=r, column=i, value=val).font = BODY_FONT
        widths = [22, 14, 12, 10, 32, 8, 30, 24]
        for i, w in enumerate(widths, start=1):
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
        wb.save(tmp_path)

    def write_csv(tmp_path):
        with open(tmp_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(EXPORT_HEADERS)
            writer.writerows(rows)

    ext = os.path.splitext(out_path)[1].lower()
    _atomic_write(write_csv if ext == ".csv" else write_xlsx, out_path)
    return len(rows)
