"""
"Usage Stats" dialog for the Admin Dashboard.

Two complementary views over one date range, both loaded on a background
thread (the share can be slow, and Work Mix reads every employee's
workbook):

  - Screens & Actions: which parts of the app are actually being used,
    from the counters written by shared/usage.py. Totals or a per-employee
    matrix, plus the number of PCs reporting.
  - Work Mix: where the logged hours went - hours by work description and
    by JOB code, with configured work items that never got used flagged.

Only counters are shown for the first tab; no content typed by a user is
ever stored. Export writes the active tab to CSV or XLSX.
"""
import datetime as dt
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import openpyxl
from openpyxl.utils import get_column_letter

from shared import data_store as ds
from shared import usage as usage_mod

PRESETS = ["This month", "Last 30 days", "Last 3 months", "Custom..."]


def _bounds_for(preset, custom_start="", custom_end=""):
    today = dt.date.today()
    if preset == "This month":
        return today.replace(day=1), today
    if preset == "Last 30 days":
        return today - dt.timedelta(days=29), today
    if preset == "Last 3 months":
        return today - dt.timedelta(days=89), today
    start = dt.date.fromisoformat(custom_start.strip())
    end = dt.date.fromisoformat(custom_end.strip())
    if start > end:
        start, end = end, start
    return start, end


def write_table(out_path, headers, rows, sheet="Usage Stats"):
    """Writes one table to .csv or .xlsx based on the extension."""
    if os.path.splitext(out_path)[1].lower() == ".csv":
        import csv
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        return
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i, value=h)
        c.font = ds.HEADER_FONT
        c.fill = ds.HEADER_FILL
    for r, row in enumerate(rows, start=2):
        for c, value in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=value).font = ds.BODY_FONT
    ws.freeze_panes = "A2"
    for i in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 24
    wb.save(out_path)


def open_usage_stats(parent, cfg, shared_path):
    win = tk.Toplevel(parent)
    win.title("Usage Stats")
    win.geometry("960x640")
    win.minsize(780, 500)
    win.transient(parent)

    state = {"start": None, "end": None, "usage": None, "mix": None,
             "queue": queue.Queue(), "loading": False}

    top = ttk.Frame(win, padding=10)
    top.pack(fill="x")
    ttk.Label(top, text="Usage Stats", font=("Arial", 14, "bold")).pack(side="left")

    preset_var = tk.StringVar(value="This month")
    start_var = tk.StringVar(value=dt.date.today().replace(day=1).isoformat())
    end_var = tk.StringVar(value=dt.date.today().isoformat())

    ttk.Label(top, text="Range:").pack(side="left", padx=(18, 4))
    preset_combo = ttk.Combobox(top, textvariable=preset_var, values=PRESETS,
                                state="readonly", width=16)
    preset_combo.pack(side="left")
    start_entry = ttk.Entry(top, textvariable=start_var, width=11)
    end_entry = ttk.Entry(top, textvariable=end_var, width=11)
    dash = ttk.Label(top, text="to")
    start_entry.pack(side="left", padx=(6, 2))
    dash.pack(side="left")
    end_entry.pack(side="left", padx=(2, 6))

    def _sync_custom(_e=None):
        custom = preset_var.get() == "Custom..."
        for w in (start_entry, end_entry, dash):
            if custom:
                w.pack(side="left", padx=2)
            else:
                w.pack_forget()
        if not custom:
            try:
                s, e = _bounds_for(preset_var.get())
                start_var.set(s.isoformat())
                end_var.set(e.isoformat())
            except ValueError:
                pass

    status = ttk.Label(win, text="", font=("Arial", 8), foreground="#777")
    status.pack(anchor="w", padx=12)

    nb = ttk.Notebook(win)
    nb.pack(fill="both", expand=True, padx=10, pady=(4, 6))

    # ---------------- Screens & Actions ----------------
    tab_use = ttk.Frame(nb, padding=6)
    nb.add(tab_use, text="Screens & Actions")

    use_bar = ttk.Frame(tab_use)
    use_bar.pack(fill="x", pady=(0, 4))
    mode_var = tk.StringVar(value="Totals")
    ttk.Label(use_bar, text="View:").pack(side="left")
    mode_combo = ttk.Combobox(use_bar, textvariable=mode_var, state="readonly",
                              values=["Totals", "By employee"], width=14)
    mode_combo.pack(side="left", padx=(4, 12))
    use_label = ttk.Label(use_bar, text="", font=("Arial", 8), foreground="#555")
    use_label.pack(side="left")

    use_frame = ttk.Frame(tab_use)
    use_frame.pack(fill="both", expand=True)
    use_tree = ttk.Treeview(use_frame, show="headings", height=16)
    use_vsb = ttk.Scrollbar(use_frame, orient="vertical", command=use_tree.yview)
    use_hsb = ttk.Scrollbar(use_frame, orient="horizontal", command=use_tree.xview)
    use_tree.configure(yscrollcommand=use_vsb.set, xscrollcommand=use_hsb.set)
    use_tree.grid(row=0, column=0, sticky="nsew")
    use_vsb.grid(row=0, column=1, sticky="ns")
    use_hsb.grid(row=1, column=0, sticky="ew")
    use_frame.grid_rowconfigure(0, weight=1)
    use_frame.grid_columnconfigure(0, weight=1)

    # ---------------- Work Mix ----------------
    tab_mix = ttk.Frame(nb, padding=6)
    nb.add(tab_mix, text="Work Mix")

    mix_bar = ttk.Frame(tab_mix)
    mix_bar.pack(fill="x", pady=(0, 4))
    mix_label = ttk.Label(mix_bar, text="", font=("Arial", 8), foreground="#555")
    mix_label.pack(side="left")

    mix_panes = ttk.Panedwindow(tab_mix, orient="vertical")
    mix_panes.pack(fill="both", expand=True)

    work_frame = ttk.Frame(mix_panes)
    work_frame.grid_rowconfigure(1, weight=1)
    work_frame.grid_columnconfigure(0, weight=1)
    ttk.Label(work_frame, text="Hours by Work Description",
              font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 3))
    work_tree = ttk.Treeview(work_frame, show="headings",
                             columns=("work", "hours", "share", "used"),
                             height=9)
    for col, label, width, anchor in (
            ("work", "Work Description", 380, "w"),
            ("hours", "Hours", 80, "e"),
            ("share", "Share", 70, "e"),
            ("used", "Used", 80, "center")):
        work_tree.heading(col, text=label)
        work_tree.column(col, width=width, anchor=anchor, stretch=(col == "work"))
    work_vsb = ttk.Scrollbar(work_frame, orient="vertical", command=work_tree.yview)
    work_tree.configure(yscrollcommand=work_vsb.set)
    work_tree.grid(row=1, column=0, sticky="nsew")
    work_vsb.grid(row=1, column=1, sticky="ns")
    work_tree.tag_configure("unused", foreground="#9aa0a6")
    mix_panes.add(work_frame, weight=1)

    job_frame = ttk.Frame(mix_panes)
    job_frame.grid_rowconfigure(1, weight=1)
    job_frame.grid_columnconfigure(0, weight=1)
    ttk.Label(job_frame, text="Hours by JOB Code",
              font=("Arial", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(4, 3))
    job_tree = ttk.Treeview(job_frame, show="headings",
                            columns=("job", "hours", "share"), height=7)
    for col, label, width, anchor in (
            ("job", "JOB Code", 380, "w"),
            ("hours", "Hours", 80, "e"),
            ("share", "Share", 70, "e")):
        job_tree.heading(col, text=label)
        job_tree.column(col, width=width, anchor=anchor, stretch=(col == "job"))
    job_vsb = ttk.Scrollbar(job_frame, orient="vertical", command=job_tree.yview)
    job_tree.configure(yscrollcommand=job_vsb.set)
    job_tree.grid(row=1, column=0, sticky="nsew")
    job_vsb.grid(row=1, column=1, sticky="ns")
    mix_panes.add(job_frame, weight=1)

    # ---------------- Actions ----------------
    bottom = ttk.Frame(win, padding=(10, 0, 10, 10))
    bottom.pack(fill="x")

    def load():
        if state["loading"]:
            return
        try:
            start, end = _bounds_for(preset_var.get(), start_var.get(), end_var.get())
        except ValueError:
            messagebox.showwarning(
                "Bad Date", "Enter both dates as YYYY-MM-DD (e.g. 2026-10-01).",
                parent=win)
            return
        state["start"], state["end"] = start, end
        state["loading"] = True
        status.config(text=f"Loading {start.isoformat()} to {end.isoformat()}...")
        employees = list(getattr(cfg, "employees", []) or [])
        work_items = [d for d, _tip in (getattr(cfg, "work_items", []) or [])]
        q = state["queue"]

        def worker():
            out = {"start": start, "end": end, "usage": None, "mix": None,
                   "error": None}
            try:
                out["usage"] = ds.read_usage(shared_path, start, end)
            except Exception as e:
                out["error"] = str(e)
            try:
                out["mix"] = ds.activity_mix(shared_path, employees, start, end,
                                             work_items=work_items)
            except Exception as e:
                out["error"] = out["error"] or str(e)
            q.put(out)

        threading.Thread(target=worker, daemon=True).start()

    def poll():
        try:
            while True:
                out = state["queue"].get_nowait()
                state["loading"] = False
                if out.get("error"):
                    status.config(text="\u26a0 " + out["error"])
                else:
                    status.config(text=f"Showing {out['start'].isoformat()} to "
                                       f"{out['end'].isoformat()}")
                state["usage"] = out.get("usage")
                state["mix"] = out.get("mix")
                paint_usage()
                paint_mix()
        except queue.Empty:
            pass
        win.after(150, poll)

    def paint_usage():
        for item in use_tree.get_children():
            use_tree.delete(item)
        data = state["usage"]
        if not data:
            use_label.config(text="")
            return
        features = data["features"]
        total = sum(features.values())
        use_label.config(
            text=f"{total:,} uses  \u2022  {len(features)} features  \u2022  "
                 f"{data['pc_count']} PC(s)  \u2022  {len(data['days'])} day(s)"
                 + (f"  \u2022  {data['skipped']} unreadable file(s)"
                    if data["skipped"] else ""))
        order = {k: i for i, k in enumerate(usage_mod.TAB_ORDER)}
        keys = sorted(features, key=lambda k: (order.get(k, 99),
                                               -features[k], k.lower()))
        if mode_var.get() == "By employee":
            employees = sorted(data["by_employee"])
            columns = ["feature"] + employees
            use_tree.configure(columns=columns)
            use_tree.heading("feature", text="Feature")
            use_tree.column("feature", width=260, anchor="w", stretch=False)
            for emp in employees:
                use_tree.heading(emp, text=emp)
                use_tree.column(emp, width=max(80, min(160, len(emp) * 8)),
                                anchor="e", stretch=False)
            for key in keys:
                row = [usage_mod.label_for(key)]
                for emp in employees:
                    n = data["by_employee"][emp].get(key, 0)
                    row.append(f"{n:,}" if n else "")
                use_tree.insert("", "end", values=row)
        else:
            use_tree.configure(columns=("feature", "uses", "share"))
            for col, label, width, anchor in (
                    ("feature", "Feature", 420, "w"),
                    ("uses", "Uses", 90, "e"),
                    ("share", "Share", 80, "e")):
                use_tree.heading(col, text=label)
                use_tree.column(col, width=width, anchor=anchor,
                                stretch=(col == "feature"))
            for key in keys:
                n = features[key]
                share = (n / total * 100.0) if total else 0.0
                use_tree.insert("", "end", values=(
                    usage_mod.label_for(key), f"{n:,}", f"{share:.1f}%"))
        if not keys:
            use_tree.insert("", "end", values=("No usage recorded in this range.",))

    def paint_mix():
        for item in work_tree.get_children():
            work_tree.delete(item)
        for item in job_tree.get_children():
            job_tree.delete(item)
        data = state["mix"]
        if not data:
            mix_label.config(text="")
            return
        total = data["total_hours"]
        mix_label.config(
            text=f"{total:,.2f} hours  \u2022  {data['entries']:,} entries  \u2022  "
                 f"{len(data['employees'])} employee(s)")
        by_work = data["by_work"]
        names = sorted(set(by_work) | set(data.get("work_items") or []),
                       key=lambda w: (-by_work.get(w, 0.0), w.lower()))
        for wd in names:
            hours = by_work.get(wd, 0.0)
            share = (hours / total * 100.0) if total else 0.0
            tags = ("unused",) if hours <= 0 else ()
            work_tree.insert("", "end", tags=tags, values=(
                wd, f"{hours:,.2f}" if hours else "0.00",
                f"{share:.1f}%" if hours else "", "never" if hours <= 0 else "yes"))
        if not names:
            work_tree.insert("", "end", values=("No log entries in this range.",))
        for job in sorted(by_work, key=lambda j: -by_work[j]):
            hours = by_work[job]
            share = (hours / total * 100.0) if total else 0.0
            job_tree.insert("", "end", values=(job, f"{hours:,.2f}", f"{share:.1f}%"))
        if not by_work:
            job_tree.insert("", "end", values=("No log entries in this range.",))

    def do_export():
        tab = nb.index(nb.select())
        if tab == 0:
            data = state["usage"]
            if not data or not data["features"]:
                messagebox.showinfo("Nothing to Export", "No usage data in this range.",
                                    parent=win)
                return
            if mode_var.get() == "By employee":
                employees = sorted(data["by_employee"])
                headers = ["Feature"] + employees
                rows = []
                for key in sorted(data["features"], key=lambda k: -data["features"][k]):
                    rows.append([usage_mod.label_for(key)] +
                                [data["by_employee"][e].get(key, 0) for e in employees])
            else:
                headers = ["Feature", "Uses", "Share %"]
                total = sum(data["features"].values()) or 1
                rows = [[usage_mod.label_for(k), n, round(n / total * 100.0, 1)]
                        for k, n in sorted(data["features"].items(),
                                           key=lambda kv: -kv[1])]
            default = "Usage_Stats_Screens_%s_%s" % (state["start"], state["end"])
        else:
            data = state["mix"]
            if not data:
                messagebox.showinfo("Nothing to Export", "No log data in this range.",
                                    parent=win)
                return
            headers = ["Section", "Name", "Hours", "Share %"]
            total = data["total_hours"] or 1
            rows = [["Work Description", w, round(h, 2), round(h / total * 100.0, 1)]
                    for w, h in sorted(data["by_work"].items(), key=lambda kv: -kv[1])]
            rows += [["JOB", j, round(h, 2), round(h / total * 100.0, 1)]
                     for j, h in sorted(data["by_job"].items(), key=lambda kv: -kv[1])]
            default = "Usage_Stats_WorkMix_%s_%s" % (state["start"], state["end"])

        out_path = filedialog.asksaveasfilename(
            parent=win, title="Export Usage Stats", initialfile=default,
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx"), ("CSV", "*.csv")])
        if not out_path:
            return
        try:
            write_table(out_path, headers, rows)
        except OSError as e:
            messagebox.showerror("Export Failed", str(e), parent=win)
            return
        if messagebox.askyesno("Export Complete", f"Saved to:\n{out_path}\n\nOpen the folder?",
                               parent=win):
            try:
                os.startfile(os.path.dirname(out_path))
            except Exception:
                pass

    ttk.Button(bottom, text="Close", command=win.destroy).pack(side="right")
    ttk.Button(bottom, text="Export...", command=do_export).pack(side="right", padx=6)
    ttk.Button(bottom, text="Refresh", command=load).pack(side="right")

    preset_combo.bind("<<ComboboxSelected>>", lambda _e: (_sync_custom(), load()))
    mode_combo.bind("<<ComboboxSelected>>", lambda _e: paint_usage())
    _sync_custom()
    win.after(150, poll)
    load()
    return win
