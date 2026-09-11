"""
Admin Dashboard's "Efficiency Dashboard" - the same breakdown-by-Work-
Description / breakdown-by-JOB-code / per-unit-efficiency view as each
employee's own My Dashboard tab (client/personal_dashboard.py), but
with an employee picker and a free-form date range instead of a fixed
list of periods - built for an admin who needs to check an arbitrary
custom stretch of time, not just "this month" / "last month".

Shares its actual drawing code with My Dashboard via
client/efficiency_view.py, so the two never numerically or visually
drift apart.
"""
import datetime as dt
import tkinter as tk
from tkinter import ttk, messagebox

from shared import data_store as ds
from client import efficiency_view as ev


def _last_month_range(today):
    first_of_this_month = today.replace(day=1)
    last_of_prev_month = first_of_this_month - dt.timedelta(days=1)
    return last_of_prev_month.replace(day=1), last_of_prev_month


QUICK_RANGES = [
    ("This Month", lambda today: (today.replace(day=1), today)),
    ("Last Month", _last_month_range),
    ("This Cutoff", lambda today: ds.cutoff_bounds(today)[:2]),
    ("Last 30 Days", lambda today: (today - dt.timedelta(days=30), today)),
    ("This Year", lambda today: (today.replace(month=1, day=1), today)),
]


def open_admin_efficiency(parent, cfg, shared_path):
    win = tk.Toplevel(parent)
    win.title("Efficiency Dashboard")
    win.geometry("920x640")
    win.transient(parent)

    names = sorted(name for name, _team in cfg.employees)
    today = dt.date.today()

    top = ttk.Frame(win, padding=10)
    top.pack(fill="x")

    ttk.Label(top, text="Employee:").grid(row=0, column=0, sticky="e", padx=(0, 4))
    emp_var = tk.StringVar(value=names[0] if names else "")
    emp_combo = ttk.Combobox(top, textvariable=emp_var, values=names, state="readonly", width=26)
    emp_combo.grid(row=0, column=1, padx=(0, 16))

    ttk.Label(top, text="From:").grid(row=0, column=2, sticky="e", padx=(0, 4))
    start_var = tk.StringVar(value=today.replace(day=1).isoformat())
    ttk.Entry(top, textvariable=start_var, width=12).grid(row=0, column=3)
    ttk.Label(top, text="To:").grid(row=0, column=4, sticky="e", padx=(8, 4))
    end_var = tk.StringVar(value=today.isoformat())
    ttk.Entry(top, textvariable=end_var, width=12).grid(row=0, column=5)
    ttk.Label(top, text="(YYYY-MM-DD)", font=("Arial", 8), foreground="#888").grid(
        row=0, column=6, sticky="w", padx=(4, 0))

    quick = ttk.Frame(win, padding=(10, 0, 10, 4))
    quick.pack(fill="x")
    ttk.Label(quick, text="Quick range:", font=("Arial", 8), foreground="#888").pack(side="left", padx=(0, 6))

    def apply_quick_range(fn):
        s, e = fn(today)
        start_var.set(s.isoformat())
        end_var.set(e.isoformat())
        refresh()

    for label, fn in QUICK_RANGES:
        ttk.Button(quick, text=label, width=12,
                   command=lambda fn=fn: apply_quick_range(fn)).pack(side="left", padx=2)

    status_label = ttk.Label(win, text="", font=("Arial", 8), foreground="#888")
    status_label.pack(anchor="w", padx=12)

    body = ttk.Frame(win)
    body.pack(fill="both", expand=True, padx=10, pady=(0, 4))
    body.columnconfigure(0, weight=1)
    body.columnconfigure(1, weight=1)
    body.rowconfigure(0, weight=1)
    body.rowconfigure(1, weight=0)

    wd_frame = ttk.LabelFrame(body, text="Where Time Goes \u2013 by Work Description")
    wd_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
    job_frame = ttk.LabelFrame(body, text="Where Time Goes \u2013 by JOB Code")
    job_frame.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
    efficiency_frame = ttk.LabelFrame(body, text="Efficiency \u2013 per unit of output")
    efficiency_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=4, pady=4)

    def parse_dates():
        try:
            start = dt.date.fromisoformat(start_var.get().strip())
            end = dt.date.fromisoformat(end_var.get().strip())
        except ValueError:
            messagebox.showwarning(
                "Invalid Date", "Please use YYYY-MM-DD for both dates (e.g. 2026-08-01).", parent=win)
            return None
        if end < start:
            messagebox.showwarning("Invalid Range", "'To' date is before 'From' date.", parent=win)
            return None
        return start, end

    def refresh():
        emp = emp_var.get().strip()
        if not emp:
            status_label.config(text="No employees in the roster.")
            return
        parsed = parse_dates()
        if not parsed:
            return
        start, end = parsed
        try:
            wd_totals = ds.hours_by_work_description(shared_path, emp, start, end)
            job_totals = ds.hours_by_job(shared_path, emp, start, end)
            metrics = ds.efficiency_metrics(shared_path, emp, start, end)
        except ds.DriveUnreachableError as e:
            status_label.config(text=f"\u26a0 Can't reach the shared drive right now: {e}")
            return
        status_label.config(text=f"Showing {start.isoformat()} to {end.isoformat()} for {emp}")
        ev.draw_bar(wd_frame, wd_totals)
        ev.draw_bar(job_frame, job_totals)
        ev.draw_efficiency_cards(efficiency_frame, metrics)

    emp_combo.bind("<<ComboboxSelected>>", lambda _e: refresh())
    ttk.Button(top, text="Refresh", command=refresh).grid(row=0, column=7, padx=(16, 0))

    refresh()
