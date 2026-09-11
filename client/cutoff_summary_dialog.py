"""
"Cutoff Summary" dialog - shows a Day/Date/Total/per-JOB-code table
(see shared/data_store.py's cutoff_summary) for one employee over one
payroll cutoff period (23rd-7th or 8th-22nd), with an "Export to
Excel/CSV..." button. Built to make manual entry into the company's
Online Timesheet Portal faster - a row can be read straight off and
typed in. Only JOB codes with at least one hour logged somewhere in
the period get a column, sorted alphabetically left to right.

Used from two places:
  - client/main_app.py: self-service, always the signed-in employee,
    no employee picker.
  - client/admin_dashboard.py: an employee picker is shown too, so an
    admin can pull anyone's summary without needing to be them.
"""
import os
import sys
import subprocess
import datetime as dt
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from shared import data_store as ds


def open_cutoff_summary(parent, cfg, shared_path, employee_name, employee_list=None):
    """employee_list: list[(name, team)] - pass this (e.g. cfg.employees)
    to show an employee picker (admin use); leave it None for the
    self-service case, where employee_name is fixed. cfg: the current
    AppConfig (kept for signature consistency with the other admin
    dialogs; not currently used by this one)."""
    win = tk.Toplevel(parent)
    win.title("Cutoff Summary")
    win.geometry("760x560")
    win.transient(parent)

    state = {"employee": employee_name, "start": None, "end": None, "job_codes": []}

    top = ttk.Frame(win, padding=10)
    top.pack(fill="x")

    if employee_list:
        ttk.Label(top, text="Employee:").pack(side="left")
        names = sorted(name for name, _team in employee_list)
        emp_var = tk.StringVar(value=employee_name if employee_name in names else (names[0] if names else ""))
        emp_combo = ttk.Combobox(top, textvariable=emp_var, values=names, state="readonly", width=28)
        emp_combo.pack(side="left", padx=(4, 16))
    else:
        emp_var = tk.StringVar(value=employee_name)
        ttk.Label(top, text=f"Employee: {employee_name}", font=("Arial", 10, "bold")).pack(side="left", padx=(0, 16))

    ttk.Label(top, text="Cutoff Period:").pack(side="left")
    cutoffs = ds.list_recent_cutoffs(dt.date.today(), count_before=3, count_after=2)
    period_labels = [label for _s, _e, label in cutoffs]
    today_cutoff = ds.cutoff_bounds(dt.date.today())
    default_label = today_cutoff[2]
    period_var = tk.StringVar(value=default_label)
    period_combo = ttk.Combobox(top, textvariable=period_var, values=period_labels,
                                 state="readonly", width=26)
    period_combo.pack(side="left", padx=(4, 16))

    status_label = ttk.Label(win, text="", font=("Arial", 8), foreground="#888")
    status_label.pack(anchor="w", padx=12)

    table_frame = ttk.Frame(win)
    table_frame.pack(fill="both", expand=True, padx=10, pady=(4, 4))

    bottom = ttk.Frame(win, padding=(10, 0, 10, 10))
    bottom.pack(fill="x")
    total_label = ttk.Label(bottom, text="", font=("Arial", 9, "bold"))
    total_label.pack(side="left")

    def selected_bounds():
        label = period_var.get()
        for s, e, l in cutoffs:
            if l == label:
                return s, e
        return today_cutoff[0], today_cutoff[1]

    def build_tree(job_codes):
        for child in table_frame.winfo_children():
            child.destroy()
        cols = ["day", "date", "total"] + [f"job_{i}" for i in range(len(job_codes))]
        tree = ttk.Treeview(table_frame, columns=cols, show="headings", height=18)
        headers = [("day", "", 44), ("date", "Date", 70), ("total", "Total", 60)]
        for code, col in zip(job_codes, cols[3:]):
            headers.append((col, code, 90))
        for c, label, w in headers:
            tree.heading(c, text=label)
            tree.column(c, width=w, anchor="center" if c != "date" else "w")
        tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        scroll.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scroll.set)
        return tree

    def refresh():
        emp = emp_var.get().strip()
        start, end = selected_bounds()
        state["employee"], state["start"], state["end"] = emp, start, end
        if not emp:
            return
        try:
            summary = ds.cutoff_summary(shared_path, emp, start, end)
        except ds.DriveUnreachableError as e:
            status_label.config(text=f"\u26a0 Can't reach the shared drive right now: {e}")
            return
        job_codes = summary["job_codes"]
        state["job_codes"] = job_codes
        tree = build_tree(job_codes)
        grand_total = 0.0
        for day in summary["days"]:
            is_weekend = day["date"].weekday() >= 5
            grand_total += day["total_hours"]
            values = [day["weekday"], day["date"].strftime("%m/%d"), f"{day['total_hours']:g}"]
            for code in job_codes:
                hrs = day["per_job"].get(code, 0.0)
                values.append(f"{hrs:g}" if hrs else "")
            tags = ("weekend",) if is_weekend else ()
            tree.insert("", "end", values=values, tags=tags)
        tree.tag_configure("weekend", background="#F2F2F2")
        status_label.config(text=f"Showing {start.isoformat()} to {end.isoformat()} for {emp}")
        total_label.config(text=f"Total for this cutoff: {grand_total:g}h")

    def do_export():
        if not state["employee"]:
            return
        default_name = f"{state['employee']}_Cutoff_{state['start']}_{state['end']}.xlsx"
        out_path = filedialog.asksaveasfilename(
            parent=win, title="Export Cutoff Summary", initialfile=default_name,
            defaultextension=".xlsx", filetypes=[("Excel Workbook", "*.xlsx"), ("CSV", "*.csv")],
        )
        if not out_path:
            return
        try:
            ds.export_cutoff_summary(shared_path, state["employee"], state["start"], state["end"],
                                      out_path)
        except ds.FileLockedError as e:
            messagebox.showerror("File Locked", str(e), parent=win)
            return
        except ds.DriveUnreachableError as e:
            messagebox.showerror("Shared Drive Unreachable", str(e), parent=win)
            return
        except OSError as e:
            messagebox.showerror("Export Failed", str(e), parent=win)
            return
        if messagebox.askyesno("Export Complete", f"Saved to:\n{out_path}\n\nOpen the containing folder now?", parent=win):
            folder = os.path.dirname(out_path)
            try:
                if sys.platform.startswith("win"):
                    os.startfile(folder)  # noqa
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", folder])
                else:
                    subprocess.Popen(["xdg-open", folder])
            except Exception as e:
                messagebox.showerror("Could Not Open Folder", f"{folder}\n\n{e}", parent=win)

    ttk.Button(bottom, text="Export to Excel/CSV...", command=do_export).pack(side="right")
    ttk.Button(bottom, text="Refresh", command=refresh).pack(side="right", padx=(0, 8))

    if employee_list:
        emp_combo.bind("<<ComboboxSelected>>", lambda _e: refresh())
    period_combo.bind("<<ComboboxSelected>>", lambda _e: refresh())
    refresh()
