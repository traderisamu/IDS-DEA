import os
import sys
import calendar
import datetime as dt
import subprocess
from collections import Counter
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from shared import data_store as ds
from shared import config_manager
from shared import constants as C
from client.calendar_widget import COLOR_MAP, legend_frame
from client.cutoff_summary_dialog import open_cutoff_summary
from client.admin_efficiency_dialog import open_admin_efficiency


def require_admin_approval(parent, cfg_mgr, on_approved, message=None):
    """Shows a login prompt checked against the SAME admin credentials as
    the Admin Dashboard, without opening the dashboard itself - for
    sensitive one-off actions (like resetting a saved employee name)
    that need admin sign-off but aren't really 'open the dashboard'
    tasks. Calls on_approved() only once the credentials check out;
    does nothing if the prompt is cancelled or the credentials are wrong."""
    win = tk.Toplevel(parent)
    win.title("Admin Approval Required")
    win.geometry("340x230")
    win.grab_set()
    win.transient(parent)

    ttk.Label(win, text="Admin Approval Required", font=("Arial", 13, "bold")).pack(pady=(14, 4))
    if message:
        ttk.Label(win, text=message, wraplength=300, justify="left").pack(padx=16, pady=(0, 8))

    form = ttk.Frame(win)
    form.pack()
    ttk.Label(form, text="Admin Username:").grid(row=0, column=0, sticky="e", pady=4)
    user_var = tk.StringVar()
    ttk.Entry(form, textvariable=user_var).grid(row=0, column=1, pady=4)
    ttk.Label(form, text="Admin Password:").grid(row=1, column=0, sticky="e", pady=4)
    pass_var = tk.StringVar()
    ttk.Entry(form, textvariable=pass_var, show="*").grid(row=1, column=1, pady=4)

    def attempt():
        cfg = cfg_mgr.get(force_refresh=True)
        if user_var.get() == cfg.admin_user() and pass_var.get() == cfg.admin_pass():
            win.destroy()
            on_approved()
        else:
            messagebox.showerror("Approval Denied", "Incorrect admin username or password.", parent=win)

    btn_row = ttk.Frame(win)
    btn_row.pack(pady=14)
    ttk.Button(btn_row, text="Approve", command=attempt).pack(side="left", padx=4)
    ttk.Button(btn_row, text="Cancel", command=win.destroy).pack(side="left", padx=4)
    win.bind("<Return>", lambda e: attempt())


def open_admin_login(parent, cfg_mgr, shared_path):
    win = tk.Toplevel(parent)
    win.title("Admin Login")
    win.geometry("300x180")
    win.grab_set()
    win.transient(parent)

    ttk.Label(win, text="Admin Login", font=("Arial", 13, "bold")).pack(pady=(14, 8))

    form = ttk.Frame(win)
    form.pack()
    ttk.Label(form, text="Username:").grid(row=0, column=0, sticky="e", pady=4)
    user_var = tk.StringVar()
    ttk.Entry(form, textvariable=user_var).grid(row=0, column=1, pady=4)
    ttk.Label(form, text="Password:").grid(row=1, column=0, sticky="e", pady=4)
    pass_var = tk.StringVar()
    ttk.Entry(form, textvariable=pass_var, show="*").grid(row=1, column=1, pady=4)

    def attempt_login():
        cfg = cfg_mgr.get(force_refresh=True)
        if user_var.get() == cfg.admin_user() and pass_var.get() == cfg.admin_pass():
            win.destroy()
            AdminDashboard(parent, cfg_mgr, shared_path)
        else:
            messagebox.showerror("Login Failed", "Incorrect username or password.", parent=win)

    ttk.Button(win, text="Login", command=attempt_login).pack(pady=14)
    win.bind("<Return>", lambda e: attempt_login())


class AdminDashboard(tk.Toplevel):
    def __init__(self, parent, cfg_mgr, shared_path):
        super().__init__(parent)
        self.parent = parent
        self.cfg_mgr = cfg_mgr
        self.shared_path = shared_path
        self.cfg = cfg_mgr.get()
        self.year = dt.date.today().year
        self.month = dt.date.today().month
        self._team_ranking = []
        self._individual_ranking = []

        self.title(f"Admin Dashboard - IDS PH DEA Logger (v{C.APP_VERSION})")
        self.geometry("1050x680")
        self.minsize(900, 560)

        self._build_ui()
        self._refresh_grid()

    def _build_ui(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Admin Dashboard", font=("Arial", 15, "bold")).pack(side="left")
        ttk.Label(top, text=f"v{C.APP_VERSION}", font=("Arial", 8), foreground="#888").pack(side="left", padx=(6, 0))
        ttk.Button(top, text="Open Database Folder (Logs)", command=self._open_db_folder).pack(side="right")
        ttk.Button(top, text="Open Config File", command=self._open_config_file).pack(side="right", padx=6)
        ttk.Button(top, text="Refresh Config", command=self._refresh_config).pack(side="right", padx=6)
        ttk.Button(top, text="Export Month...", command=self._export_month).pack(side="right", padx=6)
        ttk.Button(top, text="Rankings...", command=self._show_rankings).pack(side="right", padx=6)
        ttk.Button(top, text="Efficiency Dashboard...", command=self._open_efficiency_dashboard).pack(side="right", padx=6)
        ttk.Button(top, text="Cutoff Summary...", command=self._open_cutoff_summary).pack(side="right", padx=6)
        ttk.Button(top, text="View Employee PINs...", command=self._view_employee_pins).pack(side="right", padx=6)

        nb = ttk.Frame(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_grid = nb
        ttk.Label(self.tab_grid, text="All-Employee Calendar", font=("Arial", 11, "bold")).pack(
            anchor="w", pady=(0, 4))

        self._build_grid_tab()

    # -------------------- All-employee visual calendar --------------------
    def _build_grid_tab(self):
        frame = self.tab_grid
        nav = ttk.Frame(frame, padding=(0, 8))
        nav.pack(fill="x")
        ttk.Button(nav, text="< Prev", command=self._prev_month).pack(side="left")
        self.grid_month_label = ttk.Label(nav, text="", font=("Arial", 11, "bold"))
        self.grid_month_label.pack(side="left", padx=10)
        ttk.Button(nav, text="Next >", command=self._next_month).pack(side="left")
        legend_frame(nav).pack(side="right")

        self.team_avg_label = ttk.Label(frame, text="", font=("Arial", 8), foreground="#555")
        self.team_avg_label.pack(fill="x", padx=2, pady=(0, 2))
        self.overworked_label = ttk.Label(frame, text="", font=("Arial", 8, "bold"), foreground="#C62828")
        self.overworked_label.pack(fill="x", padx=2, pady=(0, 4))

        canvas_frame = ttk.Frame(frame)
        canvas_frame.pack(fill="both", expand=True, padx=8, pady=8)

        self.canvas = tk.Canvas(canvas_frame, background="white")
        vscroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        hscroll = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vscroll.set, xscrollcommand=hscroll.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.inner = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))

    def _prev_month(self):
        self.month -= 1
        if self.month < 1:
            self.month = 12
            self.year -= 1
        self._refresh_grid()

    def _next_month(self):
        self.month += 1
        if self.month > 12:
            self.month = 1
            self.year += 1
        self._refresh_grid()

    def _refresh_grid(self):
        self.cfg = self.cfg_mgr.get()
        self.grid_month_label.config(text=f"{calendar.month_name[self.month]} {self.year}")

        for w in self.inner.winfo_children():
            w.destroy()

        employees = self.cfg.employees  # list[(name, team)]
        days_in_month = calendar.monthrange(self.year, self.month)[1]

        NAME_COL_W = 26
        CELL_W = 2

        # header row: day numbers
        tk.Label(self.inner, text="Employee (Team)", width=NAME_COL_W, anchor="w",
                 font=("Arial", 9, "bold")).grid(row=0, column=0, sticky="w", padx=2)
        for d in range(1, days_in_month + 1):
            tk.Label(self.inner, text=str(d), width=CELL_W, font=("Arial", 7)).grid(row=0, column=d, padx=0)

        try:
            grid_data = ds.admin_month_grid(self.shared_path, employees, self.year, self.month,
                                             self.cfg.min_hours_green())
            heartbeats = ds.read_version_heartbeats(self.shared_path)
            hb_norm = {ds._normalize_name(k): v for k, v in heartbeats.items()}
            self._team_ranking = ds.rank_teams_by_avg_hours(self.shared_path, employees, self.year, self.month)
            self._individual_ranking = ds.rank_individuals_by_hours(
                self.shared_path, employees, self.year, self.month)
        except ds.DriveUnreachableError as e:
            tk.Label(self.inner, text=f"\u26a0 Can't reach the shared drive right now:\n{e}",
                     fg="#C62828", font=("Arial", 9), justify="left", anchor="w").grid(
                row=1, column=0, columnspan=days_in_month + 1, sticky="w", padx=4, pady=8)
            self.team_avg_label.config(text="")
            self.overworked_label.config(text="")
            self._team_ranking, self._individual_ranking = [], []
            return

        if self._team_ranking:
            parts = [f"{i}. {team}: {avg:.1f}h/employee ({count})"
                     for i, (team, avg, count) in enumerate(self._team_ranking, start=1)]
            self.team_avg_label.config(
                text="Teams ranked by avg hours logged this month: " + "   \u2022   ".join(parts))
        else:
            self.team_avg_label.config(text="")

        if self._individual_ranking and self._individual_ranking[0][2] > 0:
            top_name, top_team_of, top_hours = self._individual_ranking[0]
            top_team, top_team_avg = (
                (self._team_ranking[0][0], self._team_ranking[0][1]) if self._team_ranking else (None, 0.0))
            team_bit = f" ({top_team_of})" if top_team_of else ""
            team_part = f"   \u2022   Busiest team: {top_team} ({top_team_avg:.1f}h/employee avg)" if top_team else ""
            self.overworked_label.config(
                text=f"\u26a0 Most hours logged this month: {top_name}{team_bit} - {top_hours:g}h{team_part}"
                     f"   \u2022   Click \"Rankings\" for the full list")
        else:
            self.overworked_label.config(text="")

        current_team = None
        row_idx = 1
        for name, team in sorted(employees, key=lambda x: (x[1] or "", x[0])):
            if team != current_team:
                current_team = team
                tk.Label(self.inner, text=f"-- Team {team} --", font=("Arial", 8, "bold"),
                         anchor="w", foreground="#555").grid(row=row_idx, column=0, columnspan=days_in_month + 1,
                                                              sticky="w", pady=(6, 0))
                row_idx += 1

            head = tk.Frame(self.inner)
            head.grid(row=row_idx, column=0, sticky="w", padx=2)
            name_label = tk.Label(head, text=name, width=NAME_COL_W, anchor="w",
                                  font=("Arial", 8), cursor="hand2")
            name_label.pack(side="left")
            name_label.bind("<Button-1>", lambda _e, n=name: self._open_employee_workbook(n))
            info = heartbeats.get(name) or hb_norm.get(ds._normalize_name(name))
            if info is None:
                chip_text, chip_fg = "--", "#9E9E9E"
            else:
                try:
                    stale = (info["updated_at"] is not None
                             and (dt.datetime.now() - info["updated_at"]).days > 7)
                except TypeError:
                    stale = False
                if stale:
                    chip_text, chip_fg = "v" + info["app_version"], "#9E9E9E"
                elif info["app_version"] == C.APP_VERSION:
                    chip_text, chip_fg = "v" + info["app_version"], "#2E7D32"
                else:
                    chip_text, chip_fg = "v" + info["app_version"], "#EF6C00"
            tk.Label(head, text=chip_text, font=("Arial", 7),
                     foreground=chip_fg).pack(side="left", padx=(4, 0))
            day_map = grid_data.get(name, {})
            for d in range(1, days_in_month + 1):
                iso = dt.date(self.year, self.month, d).isoformat()
                color_key = day_map.get(iso, "none")
                bg = COLOR_MAP.get(color_key, COLOR_MAP["none"])
                cell = tk.Label(self.inner, text="", bg=bg, width=CELL_W, height=1, relief="flat")
                cell.grid(row=row_idx, column=d, padx=0, pady=1)
                cell.bind("<Button-1>", lambda e, n=name, dte=iso: self._show_day_popup(n, dte))
            row_idx += 1

    def _show_day_popup(self, name, date_iso):
        the_date = dt.date.fromisoformat(date_iso)
        entries = ds.read_log_entries(self.shared_path, name, the_date, the_date)
        status = ds.get_day_status(self.shared_path, name, the_date)
        lines = [f"{name} - {date_iso}", ""]
        if status:
            lines.append(f"Marked: {status[0]} ({status[1] or 'no note'})")
        if entries:
            total = sum(float(e['hours'] or 0) for e in entries)
            lines.append(f"Total hours: {total:g}")
            lines.append("")
            for e in entries:
                lines.append(f"- [{e['job']}] {e['work_description']} ({e['hours']}h) - {e['details'] or ''}")
        elif not status:
            lines.append("No entry logged.")
        messagebox.showinfo("Day Detail", "\n".join(lines))

    def _refresh_config(self):
        try:
            self.cfg = self.cfg_mgr.get(force_refresh=True)
        except config_manager.ConfigError as e:
            messagebox.showerror(
                "Config Error",
                f"Could not reload the config file:\n\n{e}\n\n"
                "The dashboard is still showing the last config that loaded "
                "successfully."
            )
            return
        self._refresh_grid()
        if self.parent is not None and hasattr(self.parent, "refresh_config_and_ui"):
            self.parent.refresh_config_and_ui()

        warnings = []
        if not self.cfg.employees:
            warnings.append("- No employees found in the 'Employees' sheet.")
        if not self.cfg.work_items:
            warnings.append("- No rows found in the 'Work Items' sheet.")
        dupe_names = {name for name, count in Counter(
            n for n, _team in self.cfg.employees).items() if count > 1}
        if dupe_names:
            warnings.append(f"- Duplicate employee name(s) in the roster: {', '.join(sorted(dupe_names))}")
        no_team = [name for name, team in self.cfg.employees if not team]
        if no_team:
            warnings.append(f"- {len(no_team)} employee(s) with no Team assigned "
                             f"(they'll group under a blank team on the calendar).")

        summary = (
            f"Loaded {len(self.cfg.employees)} employee(s), {len(self.cfg.work_items)} work item(s)."
        )
        if warnings:
            messagebox.showwarning(
                "Refreshed - with warnings",
                summary + "\n\nThings worth double-checking:\n" + "\n".join(warnings)
            )
        else:
            messagebox.showinfo("Refreshed", summary)

    def _view_employee_pins(self):
        """Read-only lookup of what each employee's current PIN actually
        is. There's nothing to 'set' or 'clear' here anymore - a PIN is
        just the trailing number of that person's Employee ID in the
        Employees sheet of DEA_Config.xlsx (config_manager.pin_for), so
        the only way to change, add, or remove someone's PIN is to edit
        that column directly in Excel. This window is just a convenience
        so an admin doesn't have to go hunt through the spreadsheet to
        answer "what's so-and-so's PIN" or "why isn't the app locking
        for them"."""
        win = tk.Toplevel(self)
        win.title("Employee PINs")
        win.geometry("380x460")
        win.transient(self)

        ttk.Label(win, text="Employee PINs", font=("Arial", 13, "bold")).pack(pady=(14, 4))
        ttk.Label(
            win, text="A PIN is just the trailing number of the employee's ID in the "
                      "Employees sheet - there's no separate PIN storage. To set, change, "
                      "or remove someone's PIN, edit their Employee ID in DEA_Config.xlsx "
                      "and Refresh Config. Blank means the app won't lock for them.",
            font=("Arial", 9), wraplength=340, justify="left"
        ).pack(padx=16, pady=(0, 8))

        list_frame = ttk.Frame(win)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 10))
        cols = ("name", "pin")
        tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=14)
        tree.heading("name", text="Employee")
        tree.heading("pin", text="PIN")
        tree.column("name", width=230, anchor="w")
        tree.column("pin", width=80, anchor="center")
        tree.pack(side="left", fill="both", expand=True)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=tree.yview)
        scroll.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scroll.set)

        for name, _team in sorted(self.cfg.employees):
            tree.insert("", "end", values=(name, self.cfg.pin_for(name) or "(none)"))

        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 12))

    def _open_cutoff_summary(self):
        """Same Cutoff Summary dialog employees can open on themselves,
        but with an employee picker added (self.cfg.employees) so an
        admin can pull anyone's payroll-period summary without needing
        to be signed in as them."""
        open_cutoff_summary(self, self.cfg, self.shared_path, None, employee_list=self.cfg.employees)

    def _open_efficiency_dashboard(self):
        """Same efficiency view as each employee's own My Dashboard tab,
        but with an employee picker and a free-form date range instead
        of a fixed period list - for an admin checking an arbitrary
        custom stretch of time."""
        open_admin_efficiency(self, self.cfg, self.shared_path)

    def _open_employee_workbook(self, name):
        """Opens one individual's Logs workbook (<SharedPath>\\Logs\\<name>.xlsx)
        in Excel - from the Rankings rows or the calendar name labels. Uses
        the same rename-tolerant resolver as the readers, so a roster typo
        fix doesn't break the lookup; a person with no saved file yet gets
        a plain note instead of an error."""
        if not name:
            return
        path = ds._resolve_existing_file_path(self.shared_path, name)
        if not os.path.isfile(path):
            messagebox.showinfo(
                "No Log File Yet",
                f"{name} has no saved log workbook yet - nothing to open.\n\n"
                f"Looked for:\n{path}",
                parent=self,
            )
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Could Not Open Workbook", f"{path}\n\n{e}", parent=self)

    def _show_rankings(self):
        win = tk.Toplevel(self)
        win.title(f"Rankings - {calendar.month_name[self.month]} {self.year}")
        win.geometry("560x520")
        win.transient(self)

        ttk.Label(win, text=f"Busiest teams and individuals for {calendar.month_name[self.month]} {self.year} "
                            "(double-click a person, or click a name on the calendar, to open their Excel log)",
                  font=("Arial", 10, "bold")).pack(anchor="w", padx=10, pady=(10, 4))

        body = ttk.Frame(win)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        team_frame = ttk.LabelFrame(body, text="Teams - ranked by avg hours/employee")
        team_frame.pack(fill="both", expand=True, pady=(0, 8))
        team_tree = ttk.Treeview(team_frame, columns=("rank", "team", "avg", "count"),
                                  show="headings", height=6)
        for c, label, w in [("rank", "#", 40), ("team", "Team", 220),
                             ("avg", "Avg h/employee", 140), ("count", "Employees", 100)]:
            team_tree.heading(c, text=label)
            team_tree.column(c, width=w, anchor="w")
        team_tree.pack(fill="both", expand=True, padx=6, pady=6)
        for i, (team, avg, count) in enumerate(self._team_ranking, start=1):
            team_tree.insert("", "end", values=(i, team, f"{avg:.1f}", count))
        if not self._team_ranking:
            team_tree.insert("", "end", values=("", "No data for this month yet.", "", ""))

        ind_frame = ttk.LabelFrame(body, text="Individuals - ranked by total hours logged")
        ind_frame.pack(fill="both", expand=True)
        ind_tree = ttk.Treeview(ind_frame, columns=("rank", "name", "team", "hours"),
                                 show="headings", height=12)
        for c, label, w in [("rank", "#", 40), ("name", "Employee", 220),
                             ("team", "Team", 140), ("hours", "Total Hours", 100)]:
            ind_tree.heading(c, text=label)
            ind_tree.column(c, width=w, anchor="w")
        ind_scroll = ttk.Scrollbar(ind_frame, orient="vertical", command=ind_tree.yview)
        ind_tree.configure(yscrollcommand=ind_scroll.set)
        ind_tree.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        ind_scroll.pack(side="right", fill="y", pady=6)

        def _open_selected_workbook(_event=None):
            sel = ind_tree.selection()
            if not sel:
                return
            values = ind_tree.item(sel[0], "values")
            if not values or not values[0]:
                return  # placeholder "No data" row - nothing to open
            self._open_employee_workbook(values[1])

        ind_tree.bind("<Double-Button-1>", _open_selected_workbook)
        for i, (name, team, total) in enumerate(self._individual_ranking, start=1):
            ind_tree.insert("", "end", values=(i, name, team, f"{total:g}"))
        if not self._individual_ranking:
            ind_tree.insert("", "end", values=("", "No data for this month yet.", "", ""))

        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 10))

    def _export_month(self):
        default_name = f"DEA_Export_{self.year:04d}-{self.month:02d}.xlsx"
        out_path = filedialog.asksaveasfilename(
            parent=self,
            title=f"Export {calendar.month_name[self.month]} {self.year}",
            initialfile=default_name,
            defaultextension=".xlsx",
            filetypes=[("Excel Workbook", "*.xlsx"), ("CSV", "*.csv")],
        )
        if not out_path:
            return
        try:
            row_count = ds.export_month(self.shared_path, self.cfg.employees, self.year, self.month, out_path)
        except ds.FileLockedError as e:
            messagebox.showerror("File Locked", str(e), parent=self)
            return
        except ds.DriveUnreachableError as e:
            messagebox.showerror("Shared Drive Unreachable", str(e), parent=self)
            return
        except OSError as e:
            messagebox.showerror("Export Failed", str(e), parent=self)
            return

        if row_count == 0:
            messagebox.showinfo(
                "Export Complete",
                f"Saved to:\n{out_path}\n\nNo entries were found for "
                f"{calendar.month_name[self.month]} {self.year} - the file just has headers.",
                parent=self
            )
            return

        if messagebox.askyesno(
            "Export Complete",
            f"Saved {row_count} row(s) to:\n{out_path}\n\nOpen the containing folder now?",
            parent=self
        ):
            folder = os.path.dirname(out_path)
            try:
                if sys.platform.startswith("win"):
                    os.startfile(folder)  # noqa
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", folder])
                else:
                    subprocess.Popen(["xdg-open", folder])
            except Exception as e:
                messagebox.showerror("Could not open folder", f"{folder}\n\n{e}", parent=self)

    def _open_config_file(self):
        path = self.cfg_mgr.path
        if not os.path.isfile(path):
            messagebox.showerror(
                "Config File Not Found",
                f"Could not find the config file at:\n{path}\n\n"
                "It may have been moved - use 'Refresh Config' after fixing "
                "its location, or check the shared folder."
            )
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showerror("Could not open config file", f"{path}\n\n{e}")

    def _open_db_folder(self):
        folder = ds.logs_folder(self.shared_path)
        os.makedirs(folder, exist_ok=True)
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)  # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception as e:
            messagebox.showerror("Could not open folder", f"{folder}\n\n{e}")
