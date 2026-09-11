"""
A lightweight month-grid calendar built from plain tk widgets (no
external calendar library needed - keeps the PyInstaller build small
and dependency-free).
"""
import calendar
import datetime as dt
import tkinter as tk
from tkinter import ttk

COLOR_MAP = {
    "green": "#2E7D32",
    "orange": "#F9A825",
    "blue": "#1565C0",
    "red": "#C62828",
    "weekend": "#BDBDBD",
    "future": "#ECEFF1",
    "none": "#ECEFF1",
}
TEXT_ON_DARK = "#FFFFFF"
TEXT_ON_LIGHT = "#333333"


class MonthCalendar(ttk.Frame):
    """
    day_status_provider(year, month) -> {date_iso: color_key}
    on_day_click(date_obj) -> called when a day cell is clicked
    """

    def __init__(self, master, day_status_provider, on_day_click=None, **kwargs):
        super().__init__(master, **kwargs)
        self.day_status_provider = day_status_provider
        self.on_day_click = on_day_click
        today = dt.date.today()
        self.year = today.year
        self.month = today.month

        nav = ttk.Frame(self)
        nav.pack(fill="x", pady=(0, 6))
        ttk.Button(nav, text="< Prev", command=self._prev_month).pack(side="left")
        self.month_label = ttk.Label(nav, text="", font=("Arial", 12, "bold"))
        self.month_label.pack(side="left", expand=True)
        ttk.Button(nav, text="Next >", command=self._next_month).pack(side="right")

        self.grid_frame = ttk.Frame(self)
        self.grid_frame.pack(fill="both", expand=True)

        self.refresh()

    def _prev_month(self):
        self.month -= 1
        if self.month < 1:
            self.month = 12
            self.year -= 1
        self.refresh()

    def _next_month(self):
        self.month += 1
        if self.month > 12:
            self.month = 1
            self.year += 1
        self.refresh()

    def refresh(self):
        for w in self.grid_frame.winfo_children():
            w.destroy()

        self.month_label.config(
            text=f"{calendar.month_name[self.month]} {self.year}"
        )

        headers = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, h in enumerate(headers):
            ttk.Label(self.grid_frame, text=h, font=("Arial", 9, "bold"),
                      anchor="center").grid(row=0, column=i, sticky="nsew", padx=1, pady=1)

        status_map = self.day_status_provider(self.year, self.month) or {}

        cal = calendar.Calendar(firstweekday=0)
        row = 1
        for week in cal.monthdayscalendar(self.year, self.month):
            for col, day_num in enumerate(week):
                if day_num == 0:
                    ttk.Label(self.grid_frame, text="").grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
                    continue
                the_date = dt.date(self.year, self.month, day_num)
                color_key = status_map.get(the_date.isoformat(), "none")
                bg = COLOR_MAP.get(color_key, COLOR_MAP["none"])
                fg = TEXT_ON_DARK if color_key in ("green", "orange", "blue", "red") else TEXT_ON_LIGHT

                cell = tk.Label(
                    self.grid_frame, text=str(day_num), bg=bg, fg=fg,
                    font=("Arial", 10, "bold"), width=4, height=2, relief="flat",
                    cursor="hand2" if self.on_day_click else "arrow",
                )
                cell.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
                if self.on_day_click:
                    cell.bind("<Button-1>", lambda e, d=the_date: self.on_day_click(d))
            row += 1

        for c in range(7):
            self.grid_frame.columnconfigure(c, weight=1)


def legend_frame(master):
    frame = ttk.Frame(master)
    items = [
        ("green", "Complete (>= min hrs)"),
        ("orange", "Logged, but under min hrs"),
        ("blue", "Holiday / Leave"),
        ("red", "Missing"),
        ("weekend", "Weekend"),
        ("future", "Future / no data"),
    ]
    for key, label in items:
        sw = tk.Label(frame, text="  ", bg=COLOR_MAP[key], width=2)
        sw.pack(side="left", padx=(8, 2))
        ttk.Label(frame, text=label, font=("Arial", 8)).pack(side="left")
    return frame
