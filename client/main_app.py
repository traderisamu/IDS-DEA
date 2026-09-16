import os
import sys
import datetime as dt
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared import constants as C
from shared import config_manager
from shared import data_store as ds
from shared.applog import get_logger
from client import local_settings as LS
from client.calendar_widget import MonthCalendar, legend_frame
from client.admin_dashboard import open_admin_login, require_admin_approval
from client.cutoff_summary_dialog import open_cutoff_summary
from client.autocomplete import enable_typeahead
from client.autostart import ensure_autostart
from client.shortcuts import ensure_desktop_shortcut
from client import tray as trayicon
from client.hotkey import GlobalHotkey, DEFAULT_LABEL as HOTKEY_LABEL

log = get_logger(__name__)


def resource_path(relative_path):
    """Resolves a bundled asset path both when running from source and
    when running as a PyInstaller-frozen .exe (which unpacks data files
    to a temp folder referenced by sys._MEIPASS)."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)


ICON_PATH = resource_path(os.path.join("assets", "icon.ico"))


def _hint_wants_numeric(tip):
    """True when the configured Details hint signals a plain count/number
    (e.g. '# of joints', '# sheets') rather than free text (e.g. 'RFI
    number and title'). Convention: the hint contains a '#' character."""
    return bool(tip) and "#" in tip


class DEAApp(tk.Tk):
    def __init__(self):
        super().__init__()
        ensure_autostart()
        # Native drag-and-drop for this interpreter (Quick Links / Admin
        # Links / file link generator drop zones). Optional: without the
        # package everything still runs, just without DnD.
        try:
            from tkinterdnd2 import TkinterDnD
            TkinterDnD._require(self)
        except Exception:
            pass
        self.title(f"{C.APP_TITLE}  (v{C.APP_VERSION})")
        self.geometry("920x760")
        self.minsize(860, 700)
        self._apply_icon()
        # Start hidden - the app runs quietly in the system tray and only
        # shows itself when asked to (tray icon) or when a reminder needs
        # attention. Shown again below if this turns out to be a first
        # run (needs the name-picker) or the tray icon can't start.
        self.withdraw()

        self.tray = None
        self.hotkey = None
        self._resolve_config(candidate_delay_seconds=0.5)

        self.employee_name = LS.get_employee_name()
        first_run = not self.employee_name
        if first_run:
            self.deiconify()
            self._first_run_pick_name()
            self.employee_name = LS.get_employee_name()  # may still be blank if they closed it

        # PIN is checked once here, at this startup/identity-confirmation
        # moment - not repeatedly every time the window is later opened
        # from the tray/hotkey during the day. Once unlocked, the rest of
        # this running session is trusted, the same way the employee name
        # itself is only ever confirmed once per session.
        self._locked = False
        if self.employee_name:
            expected_pin = self.cfg.pin_for(self.employee_name)
            if expected_pin:
                self.deiconify()
                self._locked = not self._prompt_unlock_pin(expected_pin)
            # No "else": if the Employees sheet has no Employee ID (or no
            # trailing number) for this person, there's simply no PIN to
            # check - nothing locks for them until the admin adds one.

        self._build_ui()
        if self.employee_name and not self._locked:
            self._refresh_today_tab()
        self._schedule_reminder_check()

        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)
        tray_started = self._start_tray()
        ensure_desktop_shortcut()
        self._start_hotkey()

        # Always open the main window on launch - manual or auto-started
        # at login. The tray icon keeps running underneath for reminders
        # and quick re-open; closing the window (X) still hides to tray.
        self.deiconify()
        self.lift()
        self.focus_force()
        if tray_started:
            if self.employee_name:
                self.tray.notify(
                    C.APP_TITLE,
                    f"Click the tray icon, or press "
                    f"{HOTKEY_LABEL}, anytime to pop this window open."
                )
            else:
                self.tray.notify(
                    C.APP_TITLE,
                    f"No name selected yet. Click the "
                    f"tray icon, or press {HOTKEY_LABEL}, to pick one."
                )

    # ------------------------------------------------------------------
    # Config resolution
    # ------------------------------------------------------------------
    def _candidate_config_dirs(self):
        """Ordered, de-duplicated list of folders to look for
        DEA_Config.xlsx in: the shared path remembered from last time (or
        the hardcoded network default if none is remembered yet), then
        the folder the app itself is running from (covers a simpler
        local/portable deployment where the config sits right next to
        the exe)."""
        candidates = [LS.get_shared_path(), C.DEFAULT_SHARED_PATH]
        if getattr(sys, "frozen", False):
            candidates.append(os.path.dirname(sys.executable))
        else:
            candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return candidates

    def _resolve_config(self, candidate_delay_seconds=0.5):
        try:
            cfg, resolved_folder = config_manager.load_config_with_fallback(
                self._candidate_config_dirs(), C.CONFIG_FILENAME, delay_seconds=candidate_delay_seconds)
            self.shared_path = resolved_folder
            LS.set_shared_path(resolved_folder)  # self-heal: fastest candidate next launch
            self.cfg_mgr = config_manager.ConfigManager(os.path.join(resolved_folder, C.CONFIG_FILENAME))
            self.cfg = cfg
        except config_manager.ConfigError as e:
            log.warning("config resolution failed at startup: %s", e)
            self.shared_path = LS.get_shared_path()
            self.cfg_mgr = config_manager.ConfigManager(os.path.join(self.shared_path, C.CONFIG_FILENAME))
            self.deiconify()
            messagebox.showerror("Config Error", str(e))
            self._prompt_shared_path_and_retry()

    def _apply_icon(self):
        try:
            if os.path.isfile(ICON_PATH):
                # default=True applies this icon to the root window AND
                # every Toplevel/dialog spawned afterward (Admin Dashboard,
                # popups, etc.) so the taskbar icon stays consistent.
                self.iconbitmap(default=ICON_PATH)
        except tk.TclError:
            pass  # non-Windows dev environment, or missing icon - not fatal

    # ------------------------------------------------------------------
    # First run / setup
    # ------------------------------------------------------------------
    def _prompt_shared_path_and_retry(self):
        path = simpledialog.askstring(
            "Shared Folder Location",
            "Could not find the config file at the default location.\n"
            "Enter the shared network folder path (the one containing "
            f"'{C.CONFIG_FILENAME}'):",
            initialvalue=self.shared_path,
        )
        if not path:
            messagebox.showerror("Setup incomplete", "A valid shared folder is required. Closing.")
            self.destroy()
            sys.exit(1)
        LS.set_shared_path(path)
        self.shared_path = path
        self.cfg_mgr = config_manager.ConfigManager(os.path.join(path, C.CONFIG_FILENAME))
        try:
            self.cfg = self.cfg_mgr.get(force_refresh=True)
        except config_manager.ConfigError as e:
            messagebox.showerror("Config Error", str(e))
            self.destroy()
            sys.exit(1)

    def _first_run_pick_name(self):
        win = tk.Toplevel(self)
        win.title("Welcome - Select Your Name")
        win.geometry("420x220")
        win.grab_set()
        win.transient(self)

        ttk.Label(win, text=f"{self.cfg.company_name()} - DEA Logger", font=("Arial", 13, "bold")).pack(pady=(16, 4))
        ttk.Label(win, text="Select your name. This will be remembered on this PC\n"
                             "and cannot be changed to someone else's name without a reset.",
                  justify="center").pack(pady=(0, 10))

        names = sorted(n for n, _t in self.cfg.employees)
        var = tk.StringVar()
        combo = ttk.Combobox(win, textvariable=var, values=names, state="readonly", width=40)
        combo.pack(pady=6)

        def confirm():
            if not var.get():
                messagebox.showwarning("Required", "Please select your name.", parent=win)
                return
            LS.set_employee_name(var.get())
            self.employee_name = var.get()
            win.destroy()

        ttk.Button(win, text="Confirm", command=confirm).pack(pady=14)
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self.wait_window(win)

    def _prompt_pick_name(self):
        """Reopens the name picker (used by the 'Select Your Name' button
        in the no-name placeholder UI, and by the daily 9 AM reminder).
        The rest of the app depends on employee_name in enough places
        that the simplest safe thing to do once a name IS picked is ask
        for a quick restart, rather than trying to hot-swap the whole UI
        mid-session."""
        self._first_run_pick_name()
        self.employee_name = LS.get_employee_name()
        if self.employee_name:
            messagebox.showinfo(
                "Name Saved",
                f"Thanks, {self.employee_name}! Restarting so everything loads correctly..."
            )
            self.after(100, self._quit_app)

    def _prompt_unlock_pin(self, expected_pin):
        """Modal PIN entry, checked directly against the PIN read from
        DEA_Config.xlsx (see ConfigManager.pin_for). Returns True if
        unlocked, False if cancelled - the caller decides what 'not
        unlocked' means (either don't build the real UI yet during
        startup, or stay on the locked placeholder if this was a retry
        from there)."""
        result = {"unlocked": False}
        fail_count = [0]

        win = tk.Toplevel(self)
        win.title("Enter PIN")
        win.geometry("320x230")
        win.grab_set()
        win.transient(self)
        win.protocol("WM_DELETE_WINDOW", win.destroy)

        ttk.Label(win, text="\U0001F512 Enter PIN", font=("Arial", 13, "bold")).pack(pady=(16, 4))
        ttk.Label(win, text=f"for \"{self.employee_name}\"", font=("Arial", 9)).pack()

        pin_var = tk.StringVar()
        digits_only = (win.register(lambda p: p == "" or p.isdigit()), "%P")
        entry = ttk.Entry(win, textvariable=pin_var, show="*", width=16, justify="center",
                           validate="key", validatecommand=digits_only)
        entry.pack(pady=14)
        entry.focus_set()

        status_label = ttk.Label(win, text="", font=("Arial", 8), foreground="#C62828")
        status_label.pack()

        def attempt():
            ok = bool(expected_pin) and pin_var.get() == expected_pin
            if ok:
                result["unlocked"] = True
                win.destroy()
                return
            fail_count[0] += 1
            pin_var.set("")
            if fail_count[0] >= 3:
                status_label.config(text="Too many attempts - wait a moment...")
                entry.configure(state="disabled")
                unlock_btn.configure(state="disabled")

                def re_enable():
                    fail_count[0] = 0
                    status_label.config(text="")
                    entry.configure(state="normal")
                    unlock_btn.configure(state="normal")
                    entry.focus_set()
                win.after(5000, re_enable)
            else:
                status_label.config(text="Incorrect PIN, try again.")

        btn_row = ttk.Frame(win)
        btn_row.pack(pady=6)
        unlock_btn = ttk.Button(btn_row, text="Unlock", command=attempt)
        unlock_btn.pack(side="left", padx=4)
        ttk.Button(btn_row, text="Cancel", command=win.destroy).pack(side="left", padx=4)

        # Lets another employee take over this PC without uninstalling the app.
        # The existing admin approval flow still protects the reset.
        ttk.Button(
            win,
            text="Reset / Switch User",
            command=lambda: self._reset_user_from_pin_dialog(win),
        ).pack(pady=(2, 4))

        ttk.Label(win, text="Forgot your PIN? It's your employee number.",
                  font=("Arial", 8), foreground="#888").pack(pady=(0, 8))
        win.bind("<Return>", lambda e: attempt())

        self.wait_window(win)
        return result["unlocked"]

    # ------------------------------------------------------------------
    # System tray
    # ------------------------------------------------------------------
    def _start_tray(self):
        if not trayicon.TRAY_AVAILABLE:
            return False
        self.tray = trayicon.TrayIcon(
            ICON_PATH, C.APP_TITLE,
            on_open=lambda: self.after(0, self._show_window),
            on_admin=lambda: self.after(0, self._open_admin_from_tray),
            on_exit=lambda: self.after(0, self._quit_app),
        )
        return self.tray.start()

    def _start_hotkey(self):
        self.hotkey = GlobalHotkey(callback=lambda: self.after(0, self._toggle_window))
        self.hotkey.start()

    def _show_window(self):
        self.deiconify()
        self.attributes("-topmost", True)
        self.lift()
        self.focus_force()
        self.after(300, lambda: self.attributes("-topmost", False))

    def _toggle_window(self):
        """Alt+Escape's actual behavior: show the window if it's
        currently hidden/minimized, or send it back to the tray if it's
        already open - so the same shortcut both opens AND closes it,
        rather than only ever being able to open it."""
        try:
            state = self.state()
        except tk.TclError:
            state = "withdrawn"
        if state in ("withdrawn", "iconic"):
            self._show_window()
        else:
            self._hide_to_tray()

    def _open_admin_from_tray(self):
        self._show_window()
        self._open_admin()

    def _hide_to_tray(self):
        if self.tray is not None:
            self.withdraw()
        else:
            # No tray running (dependency missing) - closing the window
            # is the only way out, so behave like a normal app close.
            self._quit_app()

    def _quit_app(self):
        if self.hotkey is not None:
            self.hotkey.stop()
        if self.tray is not None:
            self.tray.stop()
        self.destroy()
        sys.exit(0)

    def _reset_user_from_pin_dialog(self, pin_window):
        """Reset the saved employee identity directly from the PIN prompt."""
        try:
            pin_window.grab_release()
        except tk.TclError:
            pass
        pin_window.destroy()
        self._reset_user()

    def _reset_user(self):
        """Clears only the saved-name pointer on this PC, so the next
        person who opens the app here gets asked to pick their own name.
        Doesn't touch any PIN - there's nothing to clear: PINs come
        straight from DEA_Config.xlsx (the Employee ID column), so this
        never needs to, and can't, change one."""
        def do_reset():
            LS.clear_employee_name()
            messagebox.showinfo("Done", "Saved name cleared on this PC. Please restart the app.")
            if self.hotkey is not None:
                self.hotkey.stop()
            if self.tray is not None:
                self.tray.stop()
            self.destroy()
            sys.exit(0)

        require_admin_approval(
            self, self.cfg_mgr, on_approved=do_reset,
            message=(
                f"\"{self.employee_name}\" wants to clear the saved name on this PC, so "
                f"the next person who opens the app here gets asked to pick their own "
                f"name.\n\n"
                f"An admin needs to approve this first."
            )
        )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_no_name_ui(self):
        """Shown instead of the full logger whenever no name has been
        picked yet. Almost everything else in the app (reading/writing
        logs, the calendar, reminders about incomplete days) needs an
        employee_name to operate on, so rather than half-build a UI that
        would just error out, this is a simple placeholder with a way to
        pick a name - reachable from here, from the tray icon's "Open"
        action, and from the daily 9 AM reminder."""
        wrap = ttk.Frame(self, padding=30)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text=self.cfg.company_name(), font=("Arial", 16, "bold")).pack(pady=(20, 4))
        ttk.Label(wrap, text="Daily Employee Accomplishment Logger", font=("Arial", 9)).pack()
        ttk.Label(
            wrap, text="\nNo name has been selected on this PC yet, so nothing can be logged.\n"
                       "You'll get a reminder at 9 AM each day until this is done.",
            font=("Arial", 10), foreground="#C62828", justify="center"
        ).pack(pady=20)
        ttk.Button(wrap, text="Select Your Name", command=self._prompt_pick_name).pack()

        status = ttk.Frame(self, padding=(10, 4))
        status.pack(fill="x", side="bottom")
        self.status_label = ttk.Label(status, text="", font=("Arial", 8), foreground="#666")
        self.status_label.pack(side="left")

    def _build_locked_ui(self):
        """Shown instead of the full logger whenever a PIN is set but
        hasn't been unlocked yet this session - reachable via the
        'Unlock' button here, or by reopening the app fresh (tray/hotkey)
        to get another crack at the PIN prompt."""
        wrap = ttk.Frame(self, padding=30)
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text=self.cfg.company_name(), font=("Arial", 16, "bold")).pack(pady=(20, 4))
        ttk.Label(wrap, text="Daily Employee Accomplishment Logger", font=("Arial", 9)).pack()
        ttk.Label(
            wrap, text=f"\n\U0001F512 Locked - enter the PIN for \"{self.employee_name}\" to continue.",
            font=("Arial", 10), foreground="#C62828", justify="center"
        ).pack(pady=20)
        ttk.Button(wrap, text="Unlock", command=self._prompt_unlock_and_restart).pack()

        status = ttk.Frame(self, padding=(10, 4))
        status.pack(fill="x", side="bottom")
        self.status_label = ttk.Label(status, text="", font=("Arial", 8), foreground="#666")
        self.status_label.pack(side="left")

    def _prompt_unlock_and_restart(self):
        """Used from the locked placeholder (after the UI has already
        been built in locked mode) - unlike the very first unlock attempt
        during __init__, we can't just carry on building the real UI
        mid-session, so this asks for a quick restart instead, the same
        pattern _prompt_pick_name uses for a newly-picked name."""
        if self._prompt_unlock_pin(self.cfg.pin_for(self.employee_name)):
            self._locked = False
            messagebox.showinfo("Unlocked", "Restarting so everything loads correctly...")
            self.after(100, self._quit_app)

    def _build_ui(self):
        if not self.employee_name:
            self._build_no_name_ui()
            return
        if self._locked:
            self._build_locked_ui()
            return

        header = ttk.Frame(self, padding=10)
        header.pack(fill="x")

        left = ttk.Frame(header)
        left.pack(side="left")
        ttk.Label(left, text=self.cfg.company_name(), font=("Arial", 16, "bold")).pack(anchor="w")
        ttk.Label(left, text="Daily Employee Accomplishment Logger", font=("Arial", 9)).pack(anchor="w")
        ttk.Label(left, text=f"Tip: press {HOTKEY_LABEL} anytime to pop this window open",
                  font=("Arial", 8), foreground="#888").pack(anchor="w")

        right = ttk.Frame(header)
        right.pack(side="right")
        name_row = ttk.Frame(right)
        name_row.pack(anchor="e")
        ttk.Label(name_row, text="Logged in as:", font=("Arial", 9)).pack(side="left")
        tk.Label(name_row, text=f"  {self.employee_name}  ", fg="#C62828",
                 font=("Arial", 11, "bold")).pack(side="left")
        btn_row = ttk.Frame(right)
        btn_row.pack(anchor="e", pady=(4, 0))
        ttk.Button(btn_row, text="Cutoff Summary...", command=self._open_cutoff_summary).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Not you? Reset", command=self._reset_user).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Admin Login", command=self._open_admin).pack(side="left", padx=4)

        ttk.Separator(self).pack(fill="x")

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        self.tab_today = ttk.Frame(self.notebook)
        self.tab_overview = ttk.Frame(self.notebook)
        self.tab_navigator = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_today, text="Log Today's Work")
        # ttk cannot paint one tab's background, so the Job Navigator tab
        # carries a crisp green-dot image (always visible, theme-proof)
        # plus green title text while selected (see _paint_navigator_tab).
        self._nav_tab_dot = tk.PhotoImage(width=12, height=12)
        for _px in range(12):
            for _py in range(12):
                if (_px - 5.5) ** 2 + (_py - 5.5) ** 2 <= 25.0:
                    self._nav_tab_dot.put("#2e7d32", (_px, _py))
        self.notebook.add(self.tab_navigator, text="Job Navigator",
                          image=self._nav_tab_dot, compound="left")
        self.notebook.add(self.tab_overview, text="My Calendar & Dashboard")
        self._dashboard_tab_obj = None
        self._navigator_tab_obj = None
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)
        # Ctrl+Tab / Ctrl+Shift+Tab cycle the tabs (Log Today's Work /
        # Job Navigator / My Calendar & Dashboard) from anywhere in the
        # main window - one binding sniffs Shift for direction. Returning
        # "break" stops the keypress dead so focus never jumps elsewhere.
        self.bind("<Control-Tab>", self._cycle_notebook_tab)

        self._build_today_tab()
        self._build_overview_tab()

        status = ttk.Frame(self, padding=(10, 4))
        status.pack(fill="x", side="bottom")
        self.status_label = ttk.Label(status, text="", font=("Arial", 8), foreground="#666")
        self.status_label.pack(side="left")

    # ------------------------------------------------------------------
    # "Log Today's Work" tab
    # ------------------------------------------------------------------
    def _build_today_tab(self):
        frame = self.tab_today

        top = ttk.Frame(frame)
        top.pack(fill="x", pady=(4, 2))

        date_block = ttk.Frame(top)
        date_block.pack(side="left", padx=(0, 12))
        date_row = ttk.Frame(date_block)
        date_row.pack(anchor="w")
        ttk.Label(date_row, text="Date:", font=("Arial", 10, "bold")).pack(side="left")
        self.date_var = tk.StringVar(value=dt.date.today().isoformat())
        date_entry = ttk.Entry(date_row, textvariable=self.date_var, width=12)
        date_entry.pack(side="left", padx=(4, 0))
        self.day_of_week_label = ttk.Label(date_block, text="", font=("Arial", 8, "italic"), foreground="#555")
        self.day_of_week_label.pack(anchor="w")

        nav = ttk.Frame(top)
        nav.pack(side="left", padx=(0, 12))
        ttk.Button(nav, text="\u00ab Week", width=7,
                   command=lambda: self._shift_date(-7)).pack(side="left")
        ttk.Button(nav, text="\u2039 Day", width=6,
                   command=lambda: self._shift_date(-1)).pack(side="left", padx=(2, 0))
        ttk.Button(nav, text="Today", width=6,
                   command=self._jump_to_today).pack(side="left", padx=(2, 0))
        ttk.Button(nav, text="Day \u203a", width=6,
                   command=lambda: self._shift_date(1)).pack(side="left", padx=(2, 0))
        ttk.Button(nav, text="Week \u00bb", width=7,
                   command=lambda: self._shift_date(7)).pack(side="left", padx=(2, 0))

        ttk.Label(top, text="(YYYY-MM-DD, defaults to today)", font=("Arial", 8), foreground="#888").pack(side="left")

        ttk.Button(top, text="Mark this date as Holiday / Leave",
                   command=self._mark_holiday_leave).pack(side="right")

        top2 = ttk.Frame(frame)
        top2.pack(fill="x", pady=(0, 8))
        ttk.Button(top2, text="Clear Holiday/Leave mark",
                   command=self._clear_holiday_leave).pack(side="right")

        self.day_status_note = ttk.Label(frame, text="", font=("Arial", 9, "italic"), foreground="#1565C0")
        self.day_status_note.pack(fill="x")

        form = ttk.LabelFrame(frame, text="New Entry", padding=10)
        form.pack(fill="x", pady=8)

        ttk.Label(form, text="JOB Code:").grid(row=0, column=0, sticky="w", pady=4)
        self.job_var = tk.StringVar()
        self.job_combo = ttk.Combobox(form, textvariable=self.job_var, values=[],
                                       width=16)  # editable (not readonly) - suggestions, not a restriction
        self.job_combo.grid(row=0, column=1, sticky="w", padx=(4, 20))
        # Details suggestions AND which Work Descriptions even show up are
        # both scoped to the current JOB Code (see _refresh_details_suggestions
        # and _refresh_workdesc_options), so they need to stay in sync with
        # whatever's typed/selected here too - a trace catches every way
        # this can change (typing, clicking a suggestion, an Undo/Edit
        # dialog setting it programmatically).
        self.job_var.trace_add("write", lambda *_args: self._on_job_changed())

        ttk.Label(form, text="Hours Used:").grid(row=0, column=2, sticky="w", pady=4)
        self.hours_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.hours_var, width=10).grid(row=0, column=3, sticky="w", padx=4)

        ttk.Label(form, text="Work Description:").grid(row=1, column=0, sticky="w", pady=4)
        self.workdesc_var = tk.StringVar()
        self.workdesc_combo = ttk.Combobox(form, textvariable=self.workdesc_var, values=[],
                                            state="readonly", width=35)
        self.workdesc_combo.grid(row=1, column=1, columnspan=3, sticky="w", padx=4)
        self.workdesc_combo.bind("<<ComboboxSelected>>", self._update_tooltip)

        ttk.Label(form, text="Details:").grid(row=2, column=0, sticky="w", pady=4)
        self.details_var = tk.StringVar()
        self.details_combo = ttk.Combobox(form, textvariable=self.details_var, values=[],
                                           width=45)  # editable - suggests this employee's own past phrasing
        self.details_combo.grid(row=2, column=1, columnspan=3, sticky="w", padx=4)
        self._details_numeric_vcmd = (self.register(self._validate_numeric_details), "%P")
        self.tooltip_label = ttk.Label(form, text="", font=("Arial", 8, "italic"), foreground="#F57F17")
        self.tooltip_label.grid(row=3, column=1, columnspan=3, sticky="w", padx=4)

        ttk.Label(form, text="Remarks:").grid(row=4, column=0, sticky="w", pady=4)
        self.remarks_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.remarks_var, width=45).grid(row=4, column=1, columnspan=3, sticky="w", padx=4)

        ttk.Button(form, text="Add Entry", command=self._add_entry).grid(row=5, column=1, sticky="w", pady=(10, 0))
        ttk.Button(form, text="Delete Selected Entry", command=self._delete_selected_entry).grid(
            row=5, column=2, sticky="w", pady=(10, 0), padx=(8, 0))

        self._refresh_suggestions()
        self._refresh_workdesc_options()
        enable_typeahead(self.job_combo, lambda: self._job_suggestions)
        enable_typeahead(self.details_combo, lambda: self._details_suggestions)

        list_frame = ttk.LabelFrame(frame, text="Entries for selected date (double-click a row to edit)", padding=8)
        list_frame.pack(fill="both", expand=True)

        cols = ("job", "workdesc", "hours", "details", "remarks")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=8)
        for c, label, w in [
            ("job", "JOB", 70), ("workdesc", "Work Description", 220),
            ("hours", "Hours", 55), ("details", "Details", 200), ("remarks", "Remarks", 160),
        ]:
            self.tree.heading(c, text=label)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, side="left")
        self.tree.bind("<Double-1>", self._edit_selected_entry)
        self.tree.bind("<Delete>", self._delete_selected_entry)
        self.tree.bind("<BackSpace>", self._delete_selected_entry)
        self.tree.bind("<Button-3>", self._tree_context_menu)
        scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=scroll.set)

        bottom = ttk.Frame(frame)
        bottom.pack(fill="x", pady=(4, 0))
        summary = ttk.Frame(bottom)
        summary.pack(side="right")
        self.total_label = ttk.Label(summary, text="Total: 0h", font=("Arial", 10, "bold"))
        self.total_label.pack(anchor="e")
        time_out_row = ttk.Frame(summary)
        time_out_row.pack(anchor="e")
        self.time_out_label = ttk.Label(time_out_row, text="", font=("Arial", 8), foreground="#666")
        self.time_out_label.pack(side="left")
        customize_link = ttk.Label(time_out_row, text=" (customize)", font=("Arial", 8),
                                    foreground="#999999", cursor="hand2")
        customize_link.pack(side="left")
        customize_link.bind("<Button-1>", lambda e: self._open_customize_times())
        self.logout_need_label = ttk.Label(summary, text="", font=("Arial", 8), foreground="#666")
        self.logout_need_label.pack(anchor="e")
        self.range_totals_label = ttk.Label(summary, text="", font=("Arial", 8), foreground="#666")
        self.range_totals_label.pack(anchor="e")

        self.undo_bar = ttk.Frame(frame)
        self.undo_label = ttk.Label(self.undo_bar, text="", font=("Arial", 9))
        self.undo_label.pack(side="left", padx=(0, 8))
        ttk.Button(self.undo_bar, text="Undo", command=self._undo_delete).pack(side="left")
        self._undo_after_id = None
        self._undo_data = None
        # not packed here on purpose - shown/hidden on demand by _show_undo_bar/_hide_undo_bar

        date_entry.bind("<FocusOut>", lambda e: self._refresh_today_tab())
        date_entry.bind("<Return>", lambda e: self._refresh_today_tab())

    def _on_job_changed(self):
        """Fired on every JOB Code keystroke/selection - keeps both the
        Work Description dropdown's available options and the Details
        typeahead suggestions in sync with whatever JOB Code is
        currently typed (see AppConfig.work_items_for_job)."""
        self._refresh_workdesc_options()
        self._refresh_details_suggestions()

    def _refresh_workdesc_options(self):
        """Filters the New Entry form's Work Description list down to
        what's available for the currently-typed JOB Code. If the
        currently-selected Work Description is no longer in that list
        (JOB Code changed to something that no longer allows it), the
        selection is cleared rather than silently left pointing at a
        now-hidden option."""
        values = self.cfg.work_items_for_job(self.job_var.get())
        self.workdesc_combo["values"] = values
        if self.workdesc_var.get() and self.workdesc_var.get() not in values:
            self.workdesc_var.set("")
            self._update_tooltip()

    def _update_tooltip(self, _event=None):
        tip = self.cfg.tooltip_for(self.workdesc_var.get())
        self.tooltip_label.config(text=f"Details required - Hint: {tip}" if tip else "")
        if _hint_wants_numeric(tip):
            self.details_combo.configure(validate="key", validatecommand=self._details_numeric_vcmd)
        else:
            self.details_combo.configure(validate="none")
        self._refresh_details_suggestions()

    def _validate_numeric_details(self, proposed_value):
        """Key-level validator: only lets digits through while the
        selected Work Description's hint contains '#' (e.g. '# of
        joints'), since that's a numeric count. Empty string is always
        allowed so backspacing/clearing the field still works."""
        return proposed_value == "" or proposed_value.isdigit()

    def _refresh_suggestions(self):
        """Pulls this employee's own JOB code + Details history so their
        entries stay consistent with themselves over time (not a
        company-wide restriction - always still free-typeable). Cached
        on self so the typeahead filter doesn't hit disk every keystroke."""
        self._job_suggestions = ds.get_employee_job_code_history(self.shared_path, self.employee_name)
        self.job_combo["values"] = self._job_suggestions
        self._refresh_details_suggestions()

    def _refresh_details_suggestions(self):
        job = self.job_var.get().strip()
        wd = self.workdesc_var.get().strip()
        self._details_suggestions = ds.get_employee_details_history(
            self.shared_path, self.employee_name, job or None, wd or None)
        self.details_combo["values"] = self._details_suggestions

    def _selected_date(self):
        try:
            return dt.date.fromisoformat(self.date_var.get().strip())
        except ValueError:
            messagebox.showerror("Invalid date", "Please enter the date as YYYY-MM-DD.")
            return None

    def _mark_holiday_leave(self):
        the_date = self._selected_date()
        if not the_date:
            return
        win = tk.Toplevel(self)
        win.title("Mark Holiday / Leave")
        win.geometry("320x180")
        win.grab_set()
        ttk.Label(win, text=f"Date: {the_date.isoformat()}", font=("Arial", 10, "bold")).pack(pady=(12, 6))
        choice = tk.StringVar(value=ds.STATUS_HOLIDAY)
        ttk.Radiobutton(win, text="Holiday", variable=choice, value=ds.STATUS_HOLIDAY).pack(anchor="w", padx=20)
        ttk.Radiobutton(win, text="Leave", variable=choice, value=ds.STATUS_LEAVE).pack(anchor="w", padx=20)
        ttk.Label(win, text="Note (optional):").pack(anchor="w", padx=20, pady=(8, 0))
        note_var = tk.StringVar()
        ttk.Entry(win, textvariable=note_var, width=30).pack(padx=20)

        def confirm():
            try:
                ds.set_day_status(self.shared_path, self.employee_name, the_date, choice.get(), note_var.get())
            except ds.FileLockedError as e:
                messagebox.showerror("File Locked", str(e), parent=win)
                return
            win.destroy()
            self._refresh_today_tab()

        ttk.Button(win, text="Save", command=confirm).pack(pady=14)

    def _clear_holiday_leave(self):
        the_date = self._selected_date()
        if not the_date:
            return
        try:
            ds.set_day_status(self.shared_path, self.employee_name, the_date, None)
        except ds.FileLockedError as e:
            messagebox.showerror("File Locked", str(e))
            return
        self._refresh_today_tab()

    def _add_entry(self):
        the_date = self._selected_date()
        if not the_date:
            return
        status = ds.get_day_status(self.shared_path, self.employee_name, the_date)
        if status and status[0] in (ds.STATUS_HOLIDAY, ds.STATUS_LEAVE):
            if not messagebox.askyesno(
                "Marked as " + status[0],
                f"This date is marked as {status[0]}. Add a work entry anyway?"
            ):
                return

        job = self.job_var.get().strip()
        workdesc = self.workdesc_var.get().strip()
        details = self.details_var.get().strip()
        remarks = self.remarks_var.get().strip()
        hours_raw = self.hours_var.get().strip()

        if not job:
            messagebox.showwarning("Missing JOB Code", "Please enter a JOB code.")
            return
        if not workdesc:
            messagebox.showwarning("Missing Work Description", "Please select a Work Description.")
            return
        tip = self.cfg.tooltip_for(workdesc)
        if tip and not details:
            messagebox.showwarning(
                "Details Required",
                f"'{workdesc}' requires Details.\n\nHint: {tip}"
            )
            return
        if _hint_wants_numeric(tip) and not details.isdigit():
            messagebox.showwarning(
                "Numbers Only",
                f"'{workdesc}' expects a number for Details.\n\nHint: {tip}"
            )
            return
        try:
            hours = float(hours_raw)
            if hours <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Invalid Hours", "Please enter a positive number of hours (e.g. 1.5).")
            return

        if hours > C.MAX_SINGLE_ENTRY_HOURS:
            messagebox.showwarning(
                "Hours Look Off",
                f"{hours:g}h for a single entry looks like a typo - a day only has 24 hours. "
                f"Please double-check the value."
            )
            return
        if hours > C.SINGLE_ENTRY_HOURS_CONFIRM_THRESHOLD:
            if not messagebox.askyesno(
                "Confirm Hours",
                f"You entered {hours:g}h for this one entry - that's unusually high. Continue anyway?"
            ):
                return

        try:
            new_total = ds.add_log_entry(self.shared_path, self.employee_name, the_date,
                                          job, workdesc, hours, details, remarks)
        except ds.FileLockedError as e:
            messagebox.showerror("File Locked", str(e))
            return

        max_warn = self.cfg.max_hours_warning()
        if new_total > max_warn:
            messagebox.showwarning(
                "Hours Exceed Threshold",
                f"Total hours logged for {the_date.isoformat()} is now {new_total:g}h, "
                f"which exceeds the {max_warn:g}h/day threshold. Please double-check your entries."
            )

        self.job_var.set("")
        self.workdesc_var.set("")
        self.details_var.set("")
        self.remarks_var.set("")
        self.hours_var.set("")
        self.tooltip_label.config(text="")
        self._refresh_suggestions()

        self._refresh_today_tab()

    def _edit_selected_entry(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        excel_row = int(self.tree.item(sel[0], "tags")[0])
        values = self.tree.item(sel[0], "values")
        job_val, workdesc_val, hours_val, details_val, remarks_val = values

        win = tk.Toplevel(self)
        win.title("Edit Entry")
        win.geometry("480x300")
        win.grab_set()
        win.transient(self)

        form = ttk.Frame(win, padding=12)
        form.pack(fill="both", expand=True)

        ttk.Label(form, text="JOB Code:").grid(row=0, column=0, sticky="w", pady=4)
        job_var = tk.StringVar(value=job_val)
        job_entry = ttk.Combobox(form, textvariable=job_var, values=self._job_suggestions, width=18)
        job_entry.grid(row=0, column=1, sticky="w", pady=4)

        ttk.Label(form, text="Hours Used:").grid(row=1, column=0, sticky="w", pady=4)
        hours_var = tk.StringVar(value=str(hours_val))
        ttk.Entry(form, textvariable=hours_var, width=10).grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(form, text="Work Description:").grid(row=2, column=0, sticky="w", pady=4)
        wd_var = tk.StringVar(value=workdesc_val)
        wd_combo = ttk.Combobox(form, textvariable=wd_var, values=[], state="readonly", width=30)
        wd_combo.grid(row=2, column=1, sticky="w", pady=4)

        def refresh_edit_wd_options(*_args):
            # Keeps the entry's current Work Description selectable even
            # if it wouldn't otherwise qualify for the JOB Code now typed
            # (e.g. it was logged before this restriction existed, or the
            # JOB Code is mid-edit and doesn't match yet) - only actually
            # clears the selection if the person picks something else.
            wd_combo["values"] = self.cfg.work_items_for_job(job_var.get(), always_include=wd_var.get())

        job_var.trace_add("write", refresh_edit_wd_options)
        refresh_edit_wd_options()

        ttk.Label(form, text="Details:").grid(row=3, column=0, sticky="w", pady=4)
        details_var = tk.StringVar(value=details_val)
        details_entry = ttk.Combobox(form, textvariable=details_var, values=[], width=32)
        details_entry.grid(row=3, column=1, sticky="w", pady=4)
        details_numeric_vcmd = (win.register(self._validate_numeric_details), "%P")
        # Same memory as the main window: this employee's own past Details
        # phrasing, scoped to the JOB Code + Work Description currently in
        # this dialog (not a restriction - still free-typeable, with the
        # same typeahead popup as the main tab).
        edit_details_history = {"items": []}

        def refresh_edit_details(*_args):
            edit_details_history["items"] = ds.get_employee_details_history(
                self.shared_path, self.employee_name,
                job_var.get().strip() or None, wd_var.get().strip() or None)
            details_entry["values"] = edit_details_history["items"]

        job_var.trace_add("write", refresh_edit_details)
        wd_var.trace_add("write", refresh_edit_details)
        refresh_edit_details()
        enable_typeahead(details_entry, lambda: edit_details_history["items"])
        edit_tooltip_label = ttk.Label(form, text="", font=("Arial", 8, "italic"), foreground="#F57F17")
        edit_tooltip_label.grid(row=3, column=2, columnspan=2, sticky="w", padx=(6, 0))

        def update_edit_tooltip(_event=None):
            tip = self.cfg.tooltip_for(wd_var.get())
            edit_tooltip_label.config(text=f"Details required - Hint: {tip}" if tip else "")
            if _hint_wants_numeric(tip):
                details_entry.configure(validate="key", validatecommand=details_numeric_vcmd)
            else:
                details_entry.configure(validate="none")

        wd_combo.bind("<<ComboboxSelected>>", update_edit_tooltip)
        update_edit_tooltip()

        ttk.Label(form, text="Remarks:").grid(row=4, column=0, sticky="w", pady=4)
        remarks_var = tk.StringVar(value=remarks_val)
        ttk.Entry(form, textvariable=remarks_var, width=32).grid(row=4, column=1, sticky="w", pady=4)

        def save():
            try:
                hours = float(hours_var.get().strip())
                if hours <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Invalid Hours", "Please enter a positive number of hours.", parent=win)
                return
            if hours > C.MAX_SINGLE_ENTRY_HOURS:
                messagebox.showwarning(
                    "Hours Look Off",
                    f"{hours:g}h for a single entry looks like a typo - a day only has 24 hours. "
                    f"Please double-check the value.",
                    parent=win
                )
                return
            if hours > C.SINGLE_ENTRY_HOURS_CONFIRM_THRESHOLD:
                if not messagebox.askyesno(
                    "Confirm Hours",
                    f"You entered {hours:g}h for this one entry - that's unusually high. Continue anyway?",
                    parent=win
                ):
                    return
            if not job_var.get().strip() or not wd_var.get().strip():
                messagebox.showwarning("Missing Fields", "JOB Code and Work Description are required.", parent=win)
                return
            tip = self.cfg.tooltip_for(wd_var.get().strip())
            if tip and not details_var.get().strip():
                messagebox.showwarning(
                    "Details Required",
                    f"'{wd_var.get().strip()}' requires Details.\n\nHint: {tip}",
                    parent=win
                )
                return
            if _hint_wants_numeric(tip) and not details_var.get().strip().isdigit():
                messagebox.showwarning(
                    "Numbers Only",
                    f"'{wd_var.get().strip()}' expects a number for Details.\n\nHint: {tip}",
                    parent=win
                )
                return
            try:
                ds.update_log_entry(self.shared_path, self.employee_name, excel_row,
                                     job_var.get().strip(), wd_var.get().strip(), hours,
                                     details_var.get().strip(), remarks_var.get().strip())
            except ds.FileLockedError as e:
                messagebox.showerror("File Locked", str(e), parent=win)
                return
            win.destroy()
            self._refresh_suggestions()
            self._refresh_today_tab()

        btn_row = ttk.Frame(form)
        btn_row.grid(row=5, column=0, columnspan=2, pady=(14, 0))
        ttk.Button(btn_row, text="Save Changes", command=save).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Cancel", command=win.destroy).pack(side="left", padx=4)

    def _tree_context_menu(self, event):
        """Right-click menu on an entry row: Edit / Duplicate / Copy as
        Text / Delete. Right-click selects the row under the pointer
        first; a click on empty space shows nothing."""
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        self.tree.selection_set(row_id)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Edit Entry", command=self._edit_selected_entry)
        menu.add_command(label="Duplicate Entry", command=self._duplicate_selected_entry)
        menu.add_command(label="Copy as Text", command=self._copy_selected_entry_text)
        menu.add_separator()
        menu.add_command(label="Delete Entry", command=self._delete_selected_entry)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _selected_entry_values(self):
        """(excel_row, job, workdesc, hours, details, remarks) for the
        currently selected tree row, or None when nothing is selected."""
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            excel_row = int(self.tree.item(sel[0], "tags")[0])
        except (IndexError, ValueError, TypeError):
            return None
        values = self.tree.item(sel[0], "values")
        if len(values) != 5:
            return None
        return (excel_row,) + tuple(values)

    def _duplicate_selected_entry(self, _event=None):
        """Adds an exact copy of the selected entry to the same date -
        handy for repeating a similar line without retyping it. The copy
        lands as a brand-new row, so editing or deleting one never
        touches the other."""
        the_date = self._selected_date()
        if not the_date:
            return
        got = self._selected_entry_values()
        if not got:
            return
        _excel_row, job, workdesc, hours, details, remarks = got
        try:
            hours_val = float(hours)
            if hours_val <= 0:
                raise ValueError
        except (TypeError, ValueError):
            messagebox.showwarning("Invalid Hours", "The selected entry has no usable hours value.")
            return
        try:
            ds.add_log_entry(self.shared_path, self.employee_name, the_date,
                              job, workdesc, hours_val, details, remarks)
        except ds.FileLockedError as e:
            messagebox.showerror("File Locked", str(e))
            return
        self._refresh_suggestions()
        self._refresh_today_tab()

    def _copy_selected_entry_text(self, _event=None):
        """Copies the selected entry to the clipboard as one tab-separated
        line (JOB / Work Description / Hours / Details / Remarks) - ready
        to paste straight into Excel or the timesheet portal."""
        got = self._selected_entry_values()
        if not got:
            return
        _excel_row, job, workdesc, hours, details, remarks = got
        text = "\t".join(str(v) for v in (job, workdesc, hours, details, remarks))
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_label.config(text="Entry copied to clipboard.")

    def _delete_selected_entry(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        row_num = self.tree.item(sel[0], "tags")[0]
        values = self.tree.item(sel[0], "values")
        if not messagebox.askyesno("Delete Entry", "Delete this entry?"):
            return
        the_date = self._selected_date()
        try:
            ds.delete_log_entry(self.shared_path, self.employee_name, int(row_num))
        except ds.FileLockedError as e:
            messagebox.showerror("File Locked", str(e))
            return
        self._refresh_today_tab()
        if the_date and len(values) == 5:
            self._show_undo_bar(the_date, *values)

    def _show_undo_bar(self, the_date, job, workdesc, hours, details, remarks):
        if self._undo_after_id:
            self.after_cancel(self._undo_after_id)
        self._undo_data = (the_date, job, workdesc, hours, details, remarks)
        self.undo_label.config(text=f"Entry deleted ({workdesc}, {hours}h).")
        self.undo_bar.pack(fill="x", pady=(4, 0))
        self._undo_after_id = self.after(6000, self._hide_undo_bar)

    def _hide_undo_bar(self):
        self._undo_after_id = None
        self._undo_data = None
        self.undo_bar.pack_forget()

    def _undo_delete(self):
        if not self._undo_data:
            return
        the_date, job, workdesc, hours, details, remarks = self._undo_data
        try:
            hours_val = float(hours)
        except (TypeError, ValueError):
            hours_val = 0.0
        try:
            ds.add_log_entry(self.shared_path, self.employee_name, the_date,
                              job, workdesc, hours_val, details, remarks)
        except ds.FileLockedError as e:
            messagebox.showerror("File Locked", str(e))
            return
        self._hide_undo_bar()
        self.date_var.set(the_date.isoformat())
        self._refresh_suggestions()
        self._refresh_today_tab()

    def _shift_date(self, days):
        try:
            base = dt.date.fromisoformat(self.date_var.get().strip())
        except ValueError:
            base = dt.date.today()
        self.date_var.set((base + dt.timedelta(days=days)).isoformat())
        self._refresh_today_tab()

    def _jump_to_today(self):
        self.date_var.set(dt.date.today().isoformat())
        self._refresh_today_tab()

    DEFAULT_TIME_IN = dt.time(7, 30)
    DEFAULT_LUNCH_OUT = dt.time(12, 0)
    DEFAULT_LUNCH_IN = dt.time(13, 0)
    DEFAULT_LOG_OUT = dt.time(16, 30)  # keep in sync with C.DEFAULT_LOG_OUT

    @staticmethod
    def _parse_time_str(text):
        """Parses "HH:MM" (24h) - the only format this app ever writes
        via the customize-times dialog - back into a datetime.time.
        Returns None for anything unparseable rather than raising, so a
        corrupted/hand-edited local settings file just falls back to
        defaults instead of crashing the app."""
        try:
            h, m = text.split(":")
            return dt.time(int(h), int(m))
        except (ValueError, AttributeError):
            return None

    def _standard_times(self):
        """This employee's (this PC's) current standard-schedule times
        for the 'X start + lunch -> out at Y' indicator and the 'need N
        hours to hit log-out Z' helper - the built-in defaults, with any
        of the four individually overridden via _open_customize_times.
        Always returns all four as real datetime.time values (never
        None), falling back per-field."""
        overrides = LS.get_standard_times()
        time_in = self._parse_time_str(overrides.get("time_in")) or self.DEFAULT_TIME_IN
        lunch_out = self._parse_time_str(overrides.get("lunch_out")) or self.DEFAULT_LUNCH_OUT
        lunch_in = self._parse_time_str(overrides.get("lunch_in")) or self.DEFAULT_LUNCH_IN
        log_out = self._parse_time_str(overrides.get("log_out")) or self.DEFAULT_LOG_OUT
        return time_in, lunch_out, lunch_in, log_out

    def _simulate_time_out(self, total_hours):
        """Illustrative only - not tied to any actual login/logout
        tracking. Just answers: 'if the workday started at the standard
        time and included the standard lunch break, what time would
        logging this many hours put the clock-out at?' Handy as a quick
        gut-check that the hours entered look reasonable. The standard
        start/lunch times default to 7:30 AM / 12:00-1:00 PM but can be
        quietly customized per PC (see _open_customize_times) - most
        people will never touch this, so it isn't surfaced as a real
        Settings feature, just a small "customize" link by the
        indicator itself."""
        if not total_hours or total_hours <= 0:
            return None
        time_in, lunch_start_t, lunch_end_t, _log_out = self._standard_times()
        anchor = dt.date.today()
        login = dt.datetime.combine(anchor, time_in)
        lunch_start = dt.datetime.combine(anchor, lunch_start_t)
        lunch_end = dt.datetime.combine(anchor, lunch_end_t)
        remaining = dt.timedelta(hours=total_hours)

        if login < lunch_start:
            before_lunch = lunch_start - login
            if remaining <= before_lunch:
                return login + remaining
            return lunch_end + (remaining - before_lunch)
        return login + remaining

    def _hours_for_logout(self, logout_t=None):
        """Inverse of _simulate_time_out: how many total logged hours does
        it take to be out at `logout_t` (default: this PC's standard
        log-out), given the standard start/lunch times? Lunch-aware: a
        log-out after lunch starts costs the lunch break on top of the
        raw start->log-out span. Returns a float (may be <= 0 if the
        log-out is at/before the start - the caller formats that)."""
        time_in, lunch_out_t, lunch_in_t, std_log_out = self._standard_times()
        logout_t = logout_t or std_log_out
        anchor = dt.date.today()
        login = dt.datetime.combine(anchor, time_in)
        lunch_start = dt.datetime.combine(anchor, lunch_out_t)
        lunch_end = dt.datetime.combine(anchor, lunch_in_t)
        logout = dt.datetime.combine(anchor, logout_t)
        span = logout - login
        if logout > lunch_start:
            # Workday crosses the lunch break: the break itself isn't
            # loggable time, so it adds on top of the raw span (clamped
            # at zero for a log-out inside the lunch hour, which costs
            # exactly the pre-lunch stretch).
            lunch_len = lunch_end - lunch_start
            if logout <= lunch_end:
                span = lunch_start - login
            else:
                span = span - lunch_len
        return span.total_seconds() / 3600.0

    @staticmethod
    def _parse_user_time_input(text):
        """Flexible parser for what someone types into the customize-
        times dialog - accepts '7:30 AM', '7:30am', '07:30', '19:30',
        etc. Returns None (rather than raising) for anything that
        doesn't match, so the caller can show a friendly warning
        instead of a traceback."""
        text = (text or "").strip().upper()
        if not text:
            return None
        for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M", "%I %p", "%I%p"):
            try:
                return dt.datetime.strptime(text, fmt).time()
            except ValueError:
                continue
        return None

    def _open_customize_times(self):
        """Small, deliberately low-key dialog (reached via the tiny
        'customize' link next to the start+lunch note) for adjusting
        the illustrative standard-schedule times used by
        _simulate_time_out and _hours_for_logout. This is a personal
        display preference, not a real feature to advertise - it doesn't
        change how hours are logged, totaled, or reported anywhere else,
        and it only affects this one PC. Defaults (7:30 AM start,
        12:00-1:00 PM lunch, 4:30 PM log-out) are untouched unless
        someone deliberately opens this and changes them."""
        time_in, lunch_out, lunch_in, log_out = self._standard_times()
        today = dt.date.today()

        win = tk.Toplevel(self)
        win.title("Customize Standard Times")
        win.geometry("400x430")
        win.grab_set()
        win.transient(self)

        ttk.Label(win, text="Customize Standard Times", font=("Arial", 12, "bold")).pack(pady=(14, 4))
        ttk.Label(
            win, text="Only changes the illustrative \"start + lunch \u2192 out at\" and "
                      "\"need N hours to hit log-out\" notes on this tab - they don't "
                      "change how hours are logged, totaled, or reported anywhere "
                      "else, and they're local to this PC. Default is 7:30 AM start, "
                      "12:00-1:00 PM lunch, 4:30 PM log-out.",
            font=("Arial", 9), wraplength=340, justify="left"
        ).pack(padx=16, pady=(0, 10))

        form = ttk.Frame(win)
        form.pack()
        time_in_var = tk.StringVar(value=self._format_12h(dt.datetime.combine(today, time_in)))
        lunch_out_var = tk.StringVar(value=self._format_12h(dt.datetime.combine(today, lunch_out)))
        lunch_in_var = tk.StringVar(value=self._format_12h(dt.datetime.combine(today, lunch_in)))
        log_out_var = tk.StringVar(value=self._format_12h(dt.datetime.combine(today, log_out)))

        ttk.Label(form, text="Time In:").grid(row=0, column=0, sticky="e", pady=4)
        ttk.Entry(form, textvariable=time_in_var, width=12).grid(row=0, column=1, pady=4, padx=(4, 0))
        ttk.Label(form, text="Lunch Out:").grid(row=1, column=0, sticky="e", pady=4)
        ttk.Entry(form, textvariable=lunch_out_var, width=12).grid(row=1, column=1, pady=4, padx=(4, 0))
        ttk.Label(form, text="Lunch In:").grid(row=2, column=0, sticky="e", pady=4)
        ttk.Entry(form, textvariable=lunch_in_var, width=12).grid(row=2, column=1, pady=4, padx=(4, 0))
        ttk.Label(form, text="Log Out:").grid(row=3, column=0, sticky="e", pady=4)
        ttk.Entry(form, textvariable=log_out_var, width=12).grid(row=3, column=1, pady=4, padx=(4, 0))
        ttk.Label(form, text="e.g. 7:30 AM", font=("Arial", 8), foreground="#888").grid(
            row=4, column=1, sticky="w", pady=(2, 0))

        def do_save():
            t_in = self._parse_user_time_input(time_in_var.get())
            l_out = self._parse_user_time_input(lunch_out_var.get())
            l_in = self._parse_user_time_input(lunch_in_var.get())
            g_out = self._parse_user_time_input(log_out_var.get())
            if not (t_in and l_out and l_in and g_out):
                messagebox.showwarning("Invalid Time", "Please enter valid times, e.g. 7:30 AM.", parent=win)
                return
            LS.set_standard_times(t_in.strftime("%H:%M"), l_out.strftime("%H:%M"),
                                   l_in.strftime("%H:%M"), g_out.strftime("%H:%M"))
            win.destroy()
            self._refresh_today_tab()

        def do_reset():
            LS.clear_standard_times()
            win.destroy()
            self._refresh_today_tab()

        btn_row = ttk.Frame(win)
        btn_row.pack(pady=16)
        ttk.Button(btn_row, text="Save", command=do_save).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Reset to Default", command=do_reset).pack(side="left", padx=4)
        ttk.Button(btn_row, text="Cancel", command=win.destroy).pack(side="left", padx=4)
        win.bind("<Return>", lambda e: do_save())

    @staticmethod
    def _fmt_h(hours):
        """Hours capped at 2 decimals with trailing zeros stripped, so the
        customize readout shows "8h" / "9.5h" / "7.97h" - never a long
        float tail like 7.9666667h from an odd start time."""
        text = f"{hours:.2f}"
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return f"{text}h"

    @staticmethod
    def _format_12h(moment):
        # %-I / %#I (no leading zero) isn't portable across platforms,
        # so format zero-padded and strip a leading "0" by hand instead.
        text = moment.strftime("%I:%M %p")
        return text[1:] if text.startswith("0") else text

    def _range_totals_text(self, the_date):
        """This-week (Mon-Sun containing the_date) running total, so
        someone can sanity-check their week's pace without leaving the
        tab."""
        try:
            week_start = the_date - dt.timedelta(days=the_date.weekday())
            week_end = week_start + dt.timedelta(days=6)
            week_entries = ds.read_log_entries(self.shared_path, self.employee_name, week_start, week_end)
            week_total = sum(float(e["hours"] or 0) for e in week_entries)
        except ds.DriveUnreachableError:
            return self.range_totals_label.cget("text")  # keep whatever was last shown successfully

        return f"This week: {week_total:g}h"

    def _refresh_today_tab(self):
        the_date = self._selected_date()
        if not the_date:
            return
        self.day_of_week_label.config(text=the_date.strftime("%A"))
        try:
            entries = ds.read_log_entries(self.shared_path, self.employee_name, the_date, the_date)
            status = ds.get_day_status(self.shared_path, self.employee_name, the_date)
        except ds.DriveUnreachableError as e:
            log.warning("shared drive unreachable during Today tab refresh: %s", e)
            self.day_status_note.config(
                text="\u26a0 Can't reach the shared drive right now (network/VPN hiccup) - "
                     "still showing the last data that loaded successfully. Your entries are safe.",
                foreground="#C62828"
            )
            return  # leave the tree/totals exactly as they were - don't overwrite with a false "empty" state

        for item in self.tree.get_children():
            self.tree.delete(item)
        total = 0.0
        for e in entries:
            self.tree.insert("", "end", values=(e["job"], e["work_description"], e["hours"],
                                                  e["details"], e["remarks"]), tags=(str(e["excel_row"]),))
            total += float(e["hours"] or 0)
        self.total_label.config(text=f"Total: {total:g}h")
        time_out = self._simulate_time_out(total)
        if time_out:
            time_in, lunch_out, lunch_in, _log_out = self._standard_times()
            self.time_out_label.config(
                text=f"{self._format_12h(dt.datetime.combine(the_date, time_in))} start + lunch "
                     f"({self._format_12h(dt.datetime.combine(the_date, lunch_out))}-"
                     f"{self._format_12h(dt.datetime.combine(the_date, lunch_in))}) "
                     f"\u2192 out at {self._format_12h(time_out)}"
            )
        else:
            self.time_out_label.config(text="")
        # Reverse helper: exactly how many hours must this day total to hit
        # the standard log-out - and how far off the current total is. This
        # is the line that answers "how much do I still need to add/edit".
        _ti, _lo, _li, log_out = self._standard_times()
        need = self._hours_for_logout(log_out)
        delta = need - total
        hit_at = self._format_12h(dt.datetime.combine(the_date, log_out))
        if abs(delta) < 0.005:
            need_text = (f"To hit {hit_at}: need {self._fmt_h(need)} total - exactly there.")
        elif delta > 0:
            need_text = (f"To hit {hit_at}: need {self._fmt_h(need)} total "
                         f"(+{self._fmt_h(delta)} more).")
        else:
            need_text = (f"To hit {hit_at}: need {self._fmt_h(need)} total "
                         f"({self._fmt_h(-delta)} over).")
        self.logout_need_label.config(text=need_text)
        self.range_totals_label.config(text=self._range_totals_text(the_date))

        if status and status[0] in (ds.STATUS_HOLIDAY, ds.STATUS_LEAVE):
            note = f" - {status[1]}" if status[1] else ""
            self.day_status_note.config(text=f"This date is marked as {status[0]}{note}. No activity log is required.",
                                         foreground="#1565C0")
        else:
            self.day_status_note.config(text="", foreground="#1565C0")

        # Keep the calendar tab in sync with whatever just changed here
        # (add/edit/delete/holiday-mark all funnel through this method).
        if hasattr(self, "my_calendar"):
            self.my_calendar.refresh()

    # ------------------------------------------------------------------
    # "My Calendar" tab
    # ------------------------------------------------------------------
    def _build_overview_tab(self):
        """Combined My Calendar + My Dashboard tab: one scrolling page with
        the month calendar on top and the efficiency dashboard below it.
        The calendar (lightweight) builds immediately; the dashboard
        (matplotlib - slow import) is built lazily on first view."""
        frame = self.tab_overview
        canvas = tk.Canvas(frame, highlightthickness=0)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        self._overview_win = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(self._overview_win, width=e.width))
        canvas.bind_all("<MouseWheel>", self._overview_wheel, add="+")
        self._overview_canvas = canvas
        self.tab_overview_inner = inner

        cal_wrap = ttk.Frame(inner, padding=(4, 4, 4, 0))
        cal_wrap.pack(fill="x")
        ttk.Label(cal_wrap, text="Your logging history. Click a day to view/edit that date.",
                  font=("Arial", 9)).pack(anchor="w", pady=(4, 4))

        def provider(year, month):
            cfg = self.cfg_mgr.get()
            return ds.admin_month_grid(self.shared_path, [(self.employee_name, "")],
                                        year, month, cfg.min_hours_green())[self.employee_name]

        def on_click(the_date):
            self.notebook.select(self.tab_today)
            self.date_var.set(the_date.isoformat())
            self._refresh_today_tab()

        self.my_calendar = MonthCalendar(cal_wrap, provider, on_click)
        self.my_calendar.pack(fill="x")
        legend_frame(cal_wrap).pack(anchor="w", pady=(6, 0))

        self.overview_dash_wrap = ttk.Frame(inner, padding=(4, 0, 4, 4))
        self.overview_dash_wrap.pack(fill="x")

    def _overview_wheel(self, event):
        """Mouse-wheel scrolling for the overview page. App-wide binding
        that only acts when the pointer is over the overview tab, so it
        never hijacks scrolling elsewhere."""
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except tk.TclError:
            return
        node = widget
        try:
            while node is not None and node is not self.tab_overview:
                node = node.master
        except (tk.TclError, AttributeError):
            return
        if node is None:
            return
        try:
            self._overview_canvas.yview_scroll(-1 * (event.delta // 120), "units")
        except tk.TclError:
            pass

    def _cycle_notebook_tab(self, event=None):
        """Ctrl+Tab handler: select the next tab (previous with Shift held).
        Works from any widget in the main window; safe to call when the
        notebook doesn't exist yet (locked / no-name screens)."""
        try:
            tabs = list(self.notebook.tabs())
        except (tk.TclError, AttributeError):
            return "break"
        if not tabs:
            return "break"
        try:
            cur = tabs.index(self.notebook.select())
        except (tk.TclError, ValueError):
            cur = 0
        step = -1 if (event is not None and getattr(event, "state", 0) & 0x1) else 1
        try:
            self.notebook.select(tabs[(cur + step) % len(tabs)])
        except tk.TclError:
            pass
        return "break"

    def _paint_navigator_tab(self, active):
        """Green title text for the Job Navigator tab while it is the
        selected tab. ttk offers no per-tab colors, and the native Windows
        theme ignores tab background mapping entirely - but the selected
        state's foreground mapping does apply, so the title text itself
        goes green only while this tab is current. Cleared the moment you
        leave, so no other tab is ever affected."""
        try:
            ttk.Style(self).map("TNotebook.Tab",
                                foreground=[("selected", "#1B5E20")] if active else [])
        except tk.TclError:
            pass

    def _on_tab_changed(self, _event=None):
        # Dashboard built lazily, on first view of the combined tab, rather
        # than at startup - matplotlib's import is noticeably slow, so this
        # defers that cost to only the people who actually open this tab,
        # instead of everyone on every launch.
        if self.notebook.select() == str(self.tab_overview) and self._dashboard_tab_obj is None:
            from client.personal_dashboard import PersonalDashboardTab
            self._dashboard_tab_obj = PersonalDashboardTab(self.overview_dash_wrap, self)
            self._dashboard_tab_obj.pack(fill="x")
            self._dashboard_tab_obj.refresh()
        # Same lazy pattern for the embedded Job Navigator: its first
        # paint scans the JOBS share, so don't pay that (or touch the
        # network at all) until someone actually opens the tab.
        if self.notebook.select() == str(self.tab_navigator) and self._navigator_tab_obj is None:
            from client.navigator_tab import Navigator
            self._navigator_tab_obj = Navigator(self.tab_navigator)
            self._navigator_tab_obj.pack(fill="both", expand=True)
        # Green title text while the Job Navigator tab is current (see
        # _paint_navigator_tab) - cleared on every other tab.
        self._paint_navigator_tab(self.notebook.select() == str(self.tab_navigator))

    # ------------------------------------------------------------------
    # Admin
    # ------------------------------------------------------------------
    def _open_admin(self):
        open_admin_login(self, self.cfg_mgr, self.shared_path)

    def _open_cutoff_summary(self):
        open_cutoff_summary(self, self.cfg, self.shared_path, self.employee_name)

    def refresh_config_and_ui(self):
        """Re-applies the latest config to every widget that was
        populated from it at startup (right now: the Work Description
        dropdown and its tooltip/tally). Called after the Admin
        Dashboard's 'Refresh Config' succeeds, so an admin's edits (a
        new Work Description, a changed hint, an updated threshold) show
        up here immediately - previously this required closing and
        reopening the whole app, since self.cfg was only ever read once
        at startup."""
        try:
            self.cfg = self.cfg_mgr.get(force_refresh=True)
        except config_manager.ConfigError:
            return  # Admin Dashboard already surfaced this error - nothing more to do here
        if hasattr(self, "workdesc_combo"):
            self._refresh_workdesc_options()
            self._update_tooltip()
        if hasattr(self, "date_var"):
            self._refresh_today_tab()

    # ------------------------------------------------------------------
    # End-of-day reminder
    # ------------------------------------------------------------------
    def _schedule_reminder_check(self):
        # Tracks which of today's configured "today" reminder slots (e.g.
        # "15:00" and any later ones) have already fired, the last "still
        # missing" nag time for the hourly repeat that follows the final
        # slot, whether the once-a-day "previous work day" check (the
        # earliest configured slot, e.g. "09:00") has already run, the
        # last "you still haven't picked a name" nag time for anyone
        # running without a name selected (repeats hourly, see below),
        # and whether the previous work day was flagged as "not really
        # complete" despite clearing the green threshold (see below) -
        # if so, that gets folded into today's 3 PM+ reminders too.
        self._reminder_day = None
        self._fired_slots = set()
        self._last_nag_time = None
        self._morning_checked = False
        self._last_name_nag_time = None
        self._pending_incomplete_prev_day = None
        self._reminder_popup_open = False  # re-entrancy guard - see _check_reminder
        self._check_reminder()

    def _previous_work_day(self, cfg, from_date):
        """Walks backwards from the day before `from_date` to find the
        most recent day that was actually expected to be worked (skips
        weekends unless the config counts them). Personal Holiday/Leave
        marks on that day are NOT skipped here - get_day_completion
        already treats those as complete, so the popup simply won't fire
        for them."""
        weekends_count = cfg.weekends_count_as_workday()
        d = from_date - dt.timedelta(days=1)
        for _ in range(14):  # generous safety bound, never actually needed
            is_weekend = d.weekday() >= 5
            if weekends_count or not is_weekend:
                return d
            d -= dt.timedelta(days=1)
        return None

    def _check_reminder(self):
        # If a reminder popup is still on screen (the user hasn't
        # dismissed it yet), skip this cycle entirely rather than risking
        # an overlapping/duplicate check - messagebox is modal but Tk's
        # nested event loop while it's open still services `after()`
        # timers, so without this guard a slow-to-dismiss popup could
        # let a second check slip in underneath it.
        if self._reminder_popup_open:
            self.after(60_000, self._check_reminder)
            return
        if getattr(self, "_locked", False):
            # Nothing should nag someone who hasn't unlocked yet - not
            # even the "you haven't picked a name" reminder, since that
            # doesn't even apply here (a locked session already has a
            # name, just not an unlocked one).
            self.after(60_000, self._check_reminder)
            return
        try:
            cfg = self.cfg_mgr.get()
            now = dt.datetime.now()
            today = dt.date.today()

            if self._reminder_day != today:
                self._reminder_day = today
                self._fired_slots = set()
                self._last_nag_time = None
                self._morning_checked = False
                self._last_name_nag_time = None
                self._pending_incomplete_prev_day = None

            slots = cfg.reminder_times()  # sorted "HH:MM" strings, e.g. ["09:00", "15:00"]
            slot_times = []
            for s in slots:
                hh, mm = (int(x) for x in s.split(":"))
                slot_times.append((s, now.replace(hour=hh, minute=mm, second=0, microsecond=0)))

            if not self.employee_name:
                # Nothing else below makes sense without an identity - nag
                # every hour, starting at the same morning slot as the
                # other reminders, until 4:30 PM, then stop for the day
                # (same "don't nag forever" philosophy as the today_repeat
                # cutoff further down, just on a fixed schedule since
                # there's no per-day "is this done yet" threshold to check
                # here - either a name is picked, or it isn't).
                if slot_times and now >= slot_times[0][1] and now.time() <= C.NAME_REMINDER_CUTOFF_TIME:
                    due = (self._last_name_nag_time is None or
                           (now - self._last_name_nag_time).total_seconds()
                           >= C.NAME_REMINDER_REPEAT_MINUTES * 60)
                    if due:
                        self._last_name_nag_time = now
                        self._show_reminder_popup(kind="select_name", for_date=today)
                return

            is_weekend = today.weekday() >= 5
            should_check_today = cfg.weekends_count_as_workday() or not is_weekend

            if should_check_today:
                min_hours = cfg.min_hours_green()

                # --- Earliest slot (e.g. 9 AM): checks the PREVIOUS work
                # day, fires at most once, never repeats. ---
                if slot_times and not self._morning_checked and now >= slot_times[0][1]:
                    self._morning_checked = True
                    prev_day = self._previous_work_day(cfg, today)
                    if prev_day is not None:
                        complete, total_hours, _reason = ds.get_day_completion(
                            self.shared_path, self.employee_name, prev_day, min_hours)
                        if not complete:
                            self._show_reminder_popup(kind="previous_day", for_date=prev_day,
                                                       total_hours=total_hours, min_hours=min_hours)
                            return  # one popup per check cycle is plenty
                        elif min_hours <= total_hours < cfg.max_hours_warning():
                            # Technically clears the green threshold, but
                            # well under a full day - a partial log left
                            # as-is looks identical to a genuinely short
                            # (but complete) day, so ask rather than
                            # silently assuming it's done.
                            self._show_reminder_popup(kind="confirm_previous_day", for_date=prev_day,
                                                       total_hours=total_hours, min_hours=min_hours)
                            return

                # --- Remaining slot(s) (e.g. 3 PM onward): check TODAY,
                # then keep nagging hourly once the last of them has passed.
                # Also where a previous day flagged "not really complete"
                # (see above) gets surfaced, even if today itself is fine -
                # otherwise that concern would never resurface at all. ---
                today_slots = slot_times[1:] if len(slot_times) > 1 else slot_times
                if today_slots:
                    complete, total_hours, _reason = ds.get_day_completion(
                        self.shared_path, self.employee_name, today, min_hours)
                    pending = self._pending_incomplete_prev_day
                    if not complete or pending:
                        for label, slot_dt in today_slots:
                            if label not in self._fired_slots and now >= slot_dt:
                                self._fired_slots.add(label)
                                self._last_nag_time = now
                                self._show_reminder_popup(kind="today", for_date=today,
                                                           total_hours=total_hours, min_hours=min_hours)
                                return  # one popup per check cycle is plenty

                        if now >= today_slots[-1][1]:
                            # No new slot fired this cycle, but the last one
                            # has already passed - keep nagging every
                            # ReminderRepeatMinutes (default/floor: 30 min)
                            # until the cutoff window closes (default: 90
                            # min after that last slot, e.g. 3:00pm -> stops
                            # after 4:30pm), then stop for the day entirely -
                            # nothing beyond that, even if still incomplete.
                            cutoff_dt = today_slots[-1][1] + dt.timedelta(
                                minutes=cfg.reminder_repeat_cutoff_minutes())
                            if now <= cutoff_dt:
                                repeat_min = cfg.reminder_repeat_minutes()
                                due = (self._last_nag_time is None or
                                       (now - self._last_nag_time).total_seconds() >= repeat_min * 60)
                                if due:
                                    self._last_nag_time = now
                                    self._show_reminder_popup(kind="today_repeat", for_date=today,
                                                               total_hours=total_hours, min_hours=min_hours)
        except ds.DriveUnreachableError:
            # Don't nag falsely just because the drive is temporarily
            # unreachable, and don't spam a full traceback every single
            # 60-second cycle for the duration of an outage - one quiet
            # line is plenty.
            log.info("skipping reminder check - shared drive unreachable")
        except Exception:
            log.exception("reminder check cycle failed")
        finally:
            self.after(60_000, self._check_reminder)

    def _show_reminder_popup(self, kind, for_date, total_hours=0.0, min_hours=4.0):
        self._reminder_popup_open = True
        try:
            self._fire_reminder_popup(kind=kind, for_date=for_date, total_hours=total_hours, min_hours=min_hours)
        finally:
            self._reminder_popup_open = False

    def _fire_reminder_popup(self, kind, for_date, total_hours=0.0, min_hours=4.0):
        self.deiconify()
        self.attributes("-topmost", True)
        self.lift()
        self.after(400, lambda: self.attributes("-topmost", False))

        if kind == "select_name":
            messagebox.showwarning(
                "Reminder - Select Your Name",
                "You haven't selected your name on this PC yet, so nothing has been logged.\n\n"
                "Please pick your name now."
            )
            self._prompt_pick_name()
            return

        if kind == "confirm_previous_day":
            self.notebook.select(self.tab_today)
            self.date_var.set(for_date.isoformat())
            self._refresh_today_tab()
            is_complete = messagebox.askyesno(
                "Is Yesterday's Log Complete?",
                f"Hi {self.employee_name}, you logged {total_hours:g}h for the previous work "
                f"day ({for_date.isoformat()}) - that clears the {min_hours:g}h threshold, but "
                f"it's well under a full day.\n\nIs that log actually complete?"
            )
            if not is_complete:
                # Not nagged about separately - folded into today's
                # 3 PM+ reminder instead (see below), so it's one
                # notification carrying both concerns, not two.
                self._pending_incomplete_prev_day = (for_date, total_hours)
            return

        self.notebook.select(self.tab_today)
        self.date_var.set(for_date.isoformat())
        self._refresh_today_tab()
        today_complete = total_hours >= min_hours
        hours_note = (f"You've logged {total_hours:g}h so far for {for_date.isoformat()} (need {min_hours:g}h)."
                      if total_hours > 0 else f"You haven't logged anything for {for_date.isoformat()} yet.")

        pending_note = ""
        pending = self._pending_incomplete_prev_day
        if pending and kind in ("today", "today_repeat"):
            pd_date, pd_hours = pending
            pending_note = (f"\n\nAlso: you flagged {pd_date.isoformat()} ({pd_hours:g}h logged) as "
                            f"not actually complete earlier - please make sure that's finished too.")
            # Shown once, as part of this notification, then cleared -
            # not turned into its own separate repeating nag.
            self._pending_incomplete_prev_day = None

        if kind == "previous_day":
            msg = (f"Hi {self.employee_name}, your work log for the previous work day "
                   f"({for_date.isoformat()}) isn't complete.\n\n{hours_note}\n\nPlease fill it "
                   f"in, or mark that date as Holiday/Leave if it doesn't apply.")
        elif kind in ("today", "today_repeat") and today_complete:
            # Today itself is fine - the only reason this fired is the
            # pending previous-day flag, so say that plainly instead of
            # falsely claiming today isn't complete.
            msg = (f"Hi {self.employee_name}, your log for today ({for_date.isoformat()}) looks "
                   f"complete ({total_hours:g}h logged).{pending_note}")
        elif kind == "today_repeat":
            msg = (f"Hi {self.employee_name}, your work log for today ({for_date.isoformat()}) "
                   f"still isn't complete.\n\n{hours_note}\n\nPlease fill in your JOB code, Work "
                   f"Description, Hours and Details - or mark today as Holiday/Leave if it "
                   f"doesn't apply.{pending_note}")
        else:  # "today"
            msg = (f"Hi {self.employee_name}, it looks like your work log for "
                   f"{for_date.isoformat()} isn't complete yet.\n\n{hours_note}\n\nPlease "
                   f"fill in your JOB code, Work Description, Hours and Details - or mark today "
                   f"as Holiday/Leave if it doesn't apply.{pending_note}")
        messagebox.showwarning("Reminder - Log Your Accomplishments", msg)


def main():
    app = DEAApp()
    app.mainloop()


if __name__ == "__main__":
    main()
