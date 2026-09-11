"""
"My Dashboard" tab - an individual's own efficiency view: where their
time goes (by Work Description and JOB Code), and three per-unit
efficiency numbers (see client/efficiency_view.py for exactly how each
is drawn, and shared/data_store.py's efficiency_metrics for how each is
computed from the Details column). Run and Review are shown in minutes
per unit, not hours - see efficiency_view.EFFICIENCY_METRICS.

Deliberately never shows any OTHER individual's name or numbers - only
this employee's own entries - so this can't be used to snoop on a
specific coworker even though it lives inside each person's own copy of
the app.

The Admin Dashboard has an equivalent view (client/admin_efficiency_dialog.py)
with an employee picker and a free-form date range, for admin use.
"""
import datetime as dt
import tkinter as tk
from tkinter import ttk

from shared import data_store as ds
from client import efficiency_view as ev


def _last_month_range(today):
    first_of_this_month = today.replace(day=1)
    last_of_prev_month = first_of_this_month - dt.timedelta(days=1)
    return last_of_prev_month.replace(day=1), last_of_prev_month


PERIODS = {
    "This Week": lambda today: (today - dt.timedelta(days=today.weekday()), today),
    "This Month": lambda today: (today.replace(day=1), today),
    "Last Month": _last_month_range,
    "Last 3 Months": lambda today: (today - dt.timedelta(days=90), today),
}


class PersonalDashboardTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app  # the DEAApp instance - gives us shared_path / employee_name / cfg
        self._build_ui()

    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="My Dashboard", font=("Arial", 14, "bold")).pack(side="left")
        ttk.Label(top, text="Period:").pack(side="left", padx=(20, 4))
        self.period_var = tk.StringVar(value="This Month")
        period_combo = ttk.Combobox(top, textvariable=self.period_var, values=list(PERIODS.keys()),
                                     state="readonly", width=16)
        period_combo.pack(side="left")
        period_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="left", padx=(10, 0))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=0)

        self.wd_frame = ttk.LabelFrame(body, text="Where My Time Goes \u2013 by Work Description")
        self.wd_frame.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.job_frame = ttk.LabelFrame(body, text="Where My Time Goes \u2013 by JOB Code")
        self.job_frame.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        self.efficiency_frame = ttk.LabelFrame(body, text="Efficiency \u2013 per unit of output")
        self.efficiency_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=4, pady=4)

        self.status_label = ttk.Label(self, text="", font=("Arial", 8), foreground="#888")
        self.status_label.pack(anchor="w", padx=12, pady=(0, 6))

    def refresh(self):
        today = dt.date.today()
        start, end = PERIODS[self.period_var.get()](today)
        shared_path = self.app.shared_path
        employee_name = self.app.employee_name

        try:
            wd_totals = ds.hours_by_work_description(shared_path, employee_name, start, end)
            job_totals = ds.hours_by_job(shared_path, employee_name, start, end)
            metrics = ds.efficiency_metrics(shared_path, employee_name, start, end)
        except ds.DriveUnreachableError as e:
            self.status_label.config(text=f"\u26a0 Can't reach the shared drive right now: {e}")
            return

        self.status_label.config(text=f"Showing {start.isoformat()} to {end.isoformat()}")
        ev.draw_bar(self.wd_frame, wd_totals)
        ev.draw_bar(self.job_frame, job_totals)
        ev.draw_efficiency_cards(self.efficiency_frame, metrics)
