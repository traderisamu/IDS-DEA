"""
Shared rendering helpers for the "efficiency" (hours-of-work-by-type,
and per-unit-of-output) view used on both the employee-facing My
Dashboard tab (client/personal_dashboard.py) and the Admin Dashboard's
Efficiency Dashboard (client/admin_efficiency_dialog.py), so the two
stay visually and numerically consistent instead of drifting apart.

matplotlib is imported here, not at either caller's module top, so its
(noticeably slow) import cost is only ever paid once someone actually
opens a tab/dialog that uses it.
"""
import tkinter as tk
from tkinter import ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

BAR_COLOR = "#1F4E78"

# (key into ds.efficiency_metrics()'s result, card title, unit label, show_in_minutes)
# Run and Review are shown in MINUTES per unit, not hours - a single
# joint or sheet is usually a small fraction of an hour (e.g. 0.07 hrs),
# which is much harder to read at a glance than the equivalent 4.2 min.
# Calc Creation stays in hours since a full calc more plausibly takes an
# hour or more.
EFFICIENCY_METRICS = [
    ("calc", "Calc Creation", "hrs / calc", False),
    ("joint", "Run", "min / joint", True),
    ("sheet", "Review Shop Drawing", "min / sheet", True),
]


def clear(frame):
    for w in frame.winfo_children():
        w.destroy()


def embed_figure(frame, fig):
    canvas = FigureCanvasTkAgg(fig, master=frame)
    canvas.draw()
    canvas.get_tk_widget().pack(fill="both", expand=True)


def empty(frame, text):
    clear(frame)
    ttk.Label(frame, text=text, foreground="#888").pack(pady=30)


def draw_bar(frame, totals, xlabel="Hours"):
    """totals: {label: hours}. Draws the top 8 by hours, largest first,
    as a horizontal bar chart."""
    clear(frame)
    if not totals:
        empty(frame, "No entries for this period.")
        return
    items = sorted(totals.items(), key=lambda kv: -kv[1])[:8]
    labels = [k if len(k) <= 18 else k[:16] + "\u2026" for k, _ in items]
    values = [v for _, v in items]

    fig = Figure(figsize=(4.2, 3.0), dpi=90)
    ax = fig.add_subplot(111)
    ax.barh(labels[::-1], values[::-1], color=BAR_COLOR)
    ax.set_xlabel(xlabel)
    fig.tight_layout()
    embed_figure(frame, fig)


def draw_efficiency_cards(frame, metrics):
    """metrics: shared.data_store.efficiency_metrics()'s return value -
    {'calc': {...}, 'joint': {...}, 'sheet': {...}}. Draws one card per
    entry in EFFICIENCY_METRICS above."""
    clear(frame)
    cards = ttk.Frame(frame)
    cards.pack(fill="both", expand=True, padx=6, pady=10)
    for i in range(len(EFFICIENCY_METRICS)):
        cards.columnconfigure(i, weight=1)

    for col, (key, title, unit_label, in_minutes) in enumerate(EFFICIENCY_METRICS):
        m = metrics.get(key, {})
        per_unit = m.get("per_unit")
        card = ttk.Frame(cards)
        card.grid(row=0, column=col, sticky="nsew", padx=10)

        ttk.Label(card, text=title, font=("Arial", 10, "bold")).pack()
        if per_unit is None:
            ttk.Label(card, text="No data", font=("Arial", 20, "bold"),
                      foreground="#AAAAAA").pack(pady=(4, 0))
            ttk.Label(card, text=f"for this period ({unit_label})",
                      font=("Arial", 8), foreground="#888").pack()
        else:
            display_value = per_unit * 60 if in_minutes else per_unit
            value_text = f"{display_value:.1f}" if in_minutes else f"{display_value:.2f}"
            ttk.Label(card, text=value_text, font=("Arial", 22, "bold"),
                      foreground=BAR_COLOR).pack(pady=(4, 0))
            ttk.Label(card, text=unit_label, font=("Arial", 9), foreground="#666").pack()
            units = m.get("units", 0.0)
            units_str = f"{units:.0f}" if units == int(units) else f"{units:.1f}"
            noun = "calc" if key == "calc" else key
            ttk.Label(
                card, text=f"({m.get('hours', 0.0):.1f} hrs over {units_str} "
                           f"{noun}{'s' if units != 1 else ''})",
                font=("Arial", 8), foreground="#888"
            ).pack(pady=(2, 0))
