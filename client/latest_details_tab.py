"""Latest Details and Maps tab, embedded in the DEA Logger after NaviTool 2.0.

For the job currently selected in NaviTool, this shows one row per
connection with a direct link to its newest issued calc detail and its
newest map - no more digging through CALCS/MAPS folders or dated
submittal packages by hand.

Sources scanned (both - the dated SPS_SUBMITTAL packages can hold newer
revisions than the working folders):
  Structural .... <JOB>\\<CODE>_CALCS\\MATHCAD CALCS\\STRUCTURAL\\<CONN>\\
                  CALCS\\<NN>\\*.pdf and ...\\MAPS\\*.pdf
  Miscellaneous . <JOB>\\<CODE>_CALCS\\MATHCAD CALCS\\MISC\\<CONN>\\
                  (incl. _SENT TO DETAILER) plus matching dated packages
  Packages ...... <JOB>\\<CODE>_SUBMITTAL\\<dated *>\\*.pdf

A detail file looks like SPS_BS02_(15th) (A)_REV0C_DETAIL_100126.pdf -
latest means highest REV first (numeric part, then letter, so
REV00 < REV0A < REV0B < ... < REV0D), newest MMDDYY date second.
Files tied on both are all shown.

Must stay import-safe: no Tk root creation at import.
"""
import os
import re
import threading
import tkinter as tk
from tkinter import ttk

from client.navigator_tab import (
    JOB_ROOT,
    open_target,
    parse_job_code,
    load_settings as _nav_load_settings,
    save_settings as _nav_save_settings,
)

SIDES = ("STRUCTURAL", "MISC")
SIDE_LABELS = {"STRUCTURAL": "Structural", "MISC": "Miscellaneous"}

_DETAIL_RE = re.compile(
    r"^(?P<prefix>[A-Za-z]+)_(?P<body>.+?)_REV(?P<rev>[0-9A-Z]+)_DETAIL_(?P<date>\d{6})\.pdf$",
    re.IGNORECASE,
)
# "BS01_(15th)" must still match (trailing underscore is not a \b word
# boundary), and hyphenated codes like S2E-A2 need their own pattern.
_CONN_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{2,}\d{1,3})(?![0-9])")
_CONN_HYPHEN_RE = re.compile(
    r"(?<![A-Z0-9])([A-Z]+\d+[A-Z0-9]*(?:-[A-Z0-9]+)+)(?![0-9A-Z])")
_MAP_RE = re.compile(r"\bMAP\s*0*(\d{1,3})\b", re.IGNORECASE)


def _rev_key(rev):
    """'00' -> (0, ''), '0A' -> (0, 'A'), '10' -> (10, '') - orders
    REV00 < REV0A < REV0B < ... < REV10 as issued revisions grow."""
    m = re.match(r"(\d*)([A-Za-z]*)$", (rev or "").strip())
    num = int(m.group(1)) if m and m.group(1) else 0
    return (num, (m.group(2) if m else "").upper())


def _date_key(date):
    """'MMDDYY' -> (YY, MM, DD) so cross-year dates compare correctly."""
    try:
        return (int(date[4:6]), int(date[0:2]), int(date[2:4]))
    except (ValueError, IndexError):
        return (-1, -1, -1)


def parse_detail_name(filename):
    """SPS_BS02_(15th) (A)_REV0C_DETAIL_100126.pdf ->
    {'prefix': 'SPS', 'rev': '0C', 'date': '100126',
     'key': ((0, 'C'), (26, 10, 1))}. None when the name isn't an
    issued detail file."""
    m = _DETAIL_RE.match(filename or "")
    if not m:
        return None
    rev = m.group("rev").upper()
    date = m.group("date")
    return {
        "prefix": m.group("prefix").upper(),
        "body": m.group("body"),
        "rev": rev,
        "date": date,
        "key": (_rev_key(rev), _date_key(date)),
    }


def _iter_files(folder, top_only=True):
    try:
        with os.scandir(folder) as it:
            entries = sorted(it, key=lambda e: e.name.lower())
    except OSError:
        return
    for e in entries:
        try:
            if e.is_file():
                yield e.path
            elif not top_only and e.is_dir():
                yield from _iter_files(e.path, top_only=False)
        except OSError:
            continue


def _map_group(body):
    m = _MAP_RE.search(body or "")
    if not m:
        return None
    return "MAP{:02d}".format(int(m.group(1)))


def _conn_group(body):
    m = _CONN_RE.search(body or "")
    if m:
        return m.group(1).upper()
    m = _CONN_HYPHEN_RE.search(body or "")
    return m.group(1).upper() if m else None


def _list_conns(job_base, code, side):
    side_root = os.path.join(job_base, "{}_CALCS".format(code), "MATHCAD CALCS", side)
    try:
        return sorted(
            (e.name for e in os.scandir(side_root) if e.is_dir()),
            key=str.lower,
        )
    except OSError:
        return []


def scan_job_folders(job_base, code, side):
    """Walk a job's detail sources; returns
    {group: {'calc': [(sortkey, path)], 'map': [...], 'folder': rel}}.
    job_base/code are split out (instead of a job name) so tests can
    point this at a temp tree instead of the live JOBS share."""
    code = (code or "").upper()
    groups = {}
    seen_names = set()  # same basename in two places = same issued file

    def _hit(group, kind, info, path, folder_rel):
        g = groups.setdefault(group, {"calc": [], "map": [], "folder": folder_rel})
        if not g["folder"]:
            g["folder"] = folder_rel
        base = os.path.basename(path)
        if base.lower() in seen_names:
            return
        seen_names.add(base.lower())
        g[kind].append((info["key"], path))

    def _collect(folder, group_for, kind_for, folder_rel, top_only=True):
        if not os.path.isdir(folder):
            return
        for path in _iter_files(folder, top_only=top_only):
            if not path.lower().endswith(".pdf"):
                continue
            info = parse_detail_name(os.path.basename(path))
            if info is None or info["prefix"] != code:
                continue
            group = group_for(info)
            if group is None:
                continue
            _hit(group, kind_for(info), info, path, folder_rel)

    side_root = os.path.join(job_base, "{}_CALCS".format(code), "MATHCAD CALCS", side)
    conns = _list_conns(job_base, code, side)
    other_side = "MISC" if side == "STRUCTURAL" else "STRUCTURAL"
    other_conns = _list_conns(job_base, code, other_side)

    def _owner(alpha):
        """Which side owns connection token 'BS' (from BS01): exact name
        match first, then prefix match (ST -> STAIRS). 'mine' / 'theirs'
        / None when neither side has the connection yet."""
        a = (alpha or "").upper()
        if any(c.upper() == a for c in conns):
            return "mine"
        if any(c.upper() == a for c in other_conns):
            return "theirs"
        if len(a) < 2:
            return None  # single letters prefix-match everything - abstain
        if any(c.upper().startswith(a) for c in conns):
            return "mine"
        if any(c.upper().startswith(a) for c in other_conns):
            return "theirs"
        return None
    for conn in conns:
        conn_abs = os.path.join(side_root, conn)
        # tail is the job-relative rel ("CODE_CALCS\\...") used by the
        # Open-folder buttons - rebuilt from parts so temp-tree scans in
        # tests produce sane rels too.
        tail = os.path.join("{}_CALCS".format(code), "MATHCAD CALCS", side, conn)
        # CALCS\\<NN>\\*.pdf groups by the NN folder; loose files group
        # under the connection itself.
        calcs_dir = os.path.join(conn_abs, "CALCS")
        if os.path.isdir(calcs_dir):
            _collect(calcs_dir, lambda i: conn, lambda i: "calc",
                     os.path.join(tail, "CALCS"))
            try:
                subs = sorted(
                    (e.name for e in os.scandir(calcs_dir) if e.is_dir()),
                    key=str.lower,
                )
            except OSError:
                subs = []
            for sub in subs:
                _collect(os.path.join(calcs_dir, sub), lambda i: sub,
                         lambda i: "calc", os.path.join(tail, "CALCS", sub))
        # MAPS\\*.pdf (top level only - ref\\ is reference material).
        _collect(os.path.join(conn_abs, "MAPS"),
                 lambda i, c=conn: _map_group(i["body"]) or c,
                 lambda i: "map", os.path.join(tail, "MAPS"))
        # _SENT TO DETAILER drops (misc flow) and anything else issued
        # sitting directly under the connection folder.
        _collect(conn_abs, lambda i, c=conn: _conn_group(i["body"]) or c,
                 lambda i: "map" if _MAP_RE.search(i["body"]) else "calc",
                 tail)
        sent = os.path.join(conn_abs, "_SENT TO DETAILER")
        if os.path.isdir(sent):
            _collect(sent, lambda i, c=conn: _conn_group(i["body"]) or c,
                     lambda i: "map" if _MAP_RE.search(i["body"]) else "calc",
                     os.path.join(tail, "_SENT TO DETAILER"), top_only=False)

    # Dated submittal packages - these can hold newer revisions than the
    # working folders, so they merge into the same groups. A package file
    # is only claimed by this side when it belongs here: calc files carry
    # their connection token (BS01 -> BS), map files ride on the package
    # name mentioning one of this side's connections ("... - BS Calc
    # Details"). Anything neither side can place is shown on both rather
    # than hidden.
    subm_root = os.path.join(job_base, "{}_SUBMITTAL".format(code))
    try:
        packages = sorted(
            (e.name for e in os.scandir(subm_root) if e.is_dir()),
            key=str.lower,
        )
    except OSError:
        packages = []
    for pkg in packages:
        pkg_abs = os.path.join(subm_root, pkg)
        pkg_tail = os.path.join("{}_SUBMITTAL".format(code), pkg)
        mentioned = [c for c in conns
                     if re.search(r"\b{}\b".format(re.escape(c)), pkg, re.IGNORECASE)]
        mentioned_other = [c for c in other_conns
                           if re.search(r"\b{}\b".format(re.escape(c)), pkg, re.IGNORECASE)]

        def _pkg_group(info):
            body = info["body"]
            if _MAP_RE.search(body):
                if mentioned and not mentioned_other:
                    return _map_group(body)
                if mentioned_other and not mentioned:
                    return None
                return _map_group(body)  # generic package - both sides show it
            token = _conn_group(body)
            if token is None:
                return "(submittal)"
            alpha = re.match(r"[A-Z]+", token).group(0)
            own = _owner(alpha)
            if own == "theirs":
                return None
            if own == "mine":
                return token
            # Unclaimed token - the package name decides ("072826 - SC
            # Details" belongs to SC's side); generic packages show both.
            if mentioned_other and not mentioned:
                return None
            return token

        _collect(pkg_abs, _pkg_group,
                 lambda i: "map" if _MAP_RE.search(i["body"]) else "calc",
                 pkg_tail, top_only=False)

    winners = {}
    for group, data in groups.items():
        row = {"folder": data["folder"]}
        for kind in ("calc", "map"):
            hits = data[kind]
            if not hits:
                row[kind] = []
                continue
            best = max(k for k, _p in hits)
            row[kind] = sorted(p for k, p in hits if k == best)
        if row["calc"] or row["map"]:
            winners[group] = row
    return winners


def scan_latest_details(job_name, side):
    """scan_job_folders() for a real job on the JOBS share. {} when the
    job has no code, the share is unreachable, or nothing is found."""
    code = parse_job_code(job_name or "")
    if not code:
        return {}
    base = os.path.join(JOB_ROOT, job_name)
    if not os.path.isdir(base):
        return {}
    try:
        return scan_job_folders(base, code, side)
    except Exception:
        return {}


class LatestDetailsTab(ttk.Frame):
    """One row per connection: newest calc detail + newest map as
    clickable links. Follows NaviTool's selected job via get_job."""

    def __init__(self, master, get_job, **kwargs):
        super().__init__(master, **kwargs)
        self._get_job = get_job
        self._token = 0
        self._last_job = None
        self._last_side = None
        try:
            self._side = tk.StringVar(
                value=_nav_load_settings().get("latest_side", SIDES[0]))
        except Exception:
            self._side = tk.StringVar(value=SIDES[0])
        if self._side.get() not in SIDES:
            self._side.set(SIDES[0])
        self._build_ui()

    # ---------------------------- UI ----------------------------
    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Latest Details and Maps",
                  font=("Segoe UI", 13, "bold")).pack(side="left")
        self.job_label = ttk.Label(top, text="", font=("Segoe UI", 9),
                                   foreground="#68727d")
        self.job_label.pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Refresh", command=self.refresh).pack(side="right")
        for side in SIDES:
            ttk.Radiobutton(top, text=SIDE_LABELS[side], value=side,
                            variable=self._side,
                            command=self._on_side_changed).pack(side="right", padx=4)
        ttk.Label(top, text="Show:", font=("Segoe UI", 9)).pack(side="right", padx=(10, 0))

        hint = ttk.Label(self, padding=(10, 2, 10, 0), font=("Segoe UI", 8),
                         foreground="#68727d", wraplength=900, justify="left",
                         text="Newest issued detail + map per connection for the job "
                              "selected in NaviTool 2.0. Click a file name to open the PDF.")
        hint.pack(fill="x")

        wrap = ttk.Frame(self, padding=(10, 6, 10, 10))
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, background="#f5f6f8", highlightthickness=0)
        vscroll = ttk.Scrollbar(wrap, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vscroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")
        self.body = ttk.Frame(self.canvas)
        self._body_win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>",
                       lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfig(self._body_win, width=e.width))

    def _on_side_changed(self):
        try:
            data = _nav_load_settings()
            data["latest_side"] = self._side.get()
            _nav_save_settings(data)
        except Exception:
            pass
        self.refresh()

    # ---------------------------- data ----------------------------
    def refresh(self):
        job = self._get_job() if self._get_job else None
        side = self._side.get()
        self._token += 1
        token = self._token
        self._clear()
        if not job:
            self._message("Pick a job in NaviTool 2.0 first - this tab follows "
                          "whatever job is selected there.")
            return
        self._last_job, self._last_side = job, side
        self.job_label.config(text="{}  \u2022  {}".format(job, SIDE_LABELS[side]))
        ttk.Label(self.body, text="Loading '{}'...".format(job),
                  font=("Segoe UI", 10)).grid(row=0, column=0, pady=24)

        def work():
            try:
                rows = scan_latest_details(job, side)
            except Exception:
                rows = {}
            try:
                self.after(0, lambda: self._paint(token, job, side, rows))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _message(self, text):
        self.job_label.config(text="")
        ttk.Label(self.body, text=text, font=("Segoe UI", 10),
                  wraplength=700, justify="left").grid(row=0, column=0,
                                                       padx=6, pady=24, sticky="w")

    # ---------------------------- paint ----------------------------
    def _paint(self, token, job, side, rows):
        if token != self._token:
            return
        try:
            if not self.body.winfo_exists():
                return
        except tk.TclError:
            return
        self._clear()
        self.job_label.config(text="{}  \u2022  {}".format(job, SIDE_LABELS[side]))
        if not rows:
            self._message("No issued detail files found yet for '{}' "
                          "({}). They appear here once DETAIL pdfs land in the "
                          "job's CALCS/MAPS folders or a dated submittal "
                          "package.".format(job, SIDE_LABELS[side]))
            return
        headers = ("Connection", "Latest calc detail", "Latest map", "")
        for col, text in enumerate(headers):
            ttk.Label(self.body, text=text, font=("Segoe UI", 9, "bold")).grid(
                row=0, column=col, sticky="w", padx=8, pady=(2, 6))
        ttk.Separator(self.body, orient="horizontal").grid(
            row=1, column=0, columnspan=4, sticky="ew", padx=4)
        row_idx = 2
        for group in sorted(rows, key=str.lower):
            data = rows[group]
            ttk.Label(self.body, text=group,
                      font=("Segoe UI", 10, "bold")).grid(
                          row=row_idx, column=0, sticky="nw", padx=8, pady=6)
            self._link_cell(row_idx, 1, data["calc"], job)
            self._link_cell(row_idx, 2, data["map"], job)
            rel = data["folder"]
            if rel:
                ttk.Button(self.body, text="Open folder",
                           command=lambda r=rel: open_target(
                               os.path.join(JOB_ROOT, job, r))).grid(
                                   row=row_idx, column=3, sticky="nw",
                                   padx=8, pady=4)
            else:
                ttk.Label(self.body, text="\u2014",
                          foreground="#9aa0a6").grid(row=row_idx, column=3,
                                                     sticky="w", padx=8)
            row_idx += 1
        self.body.grid_columnconfigure(1, weight=1)
        self.body.grid_columnconfigure(2, weight=1)

    def _link_cell(self, row, col, paths, job):
        cell = ttk.Frame(self.body)
        cell.grid(row=row, column=col, sticky="nw", padx=8, pady=4)
        if not paths:
            ttk.Label(cell, text="\u2014", foreground="#9aa0a6").pack(anchor="w")
            return
        for path in paths:
            name = os.path.basename(path)
            link = tk.Label(cell, text=name, font=("Segoe UI", 9, "underline"),
                            foreground="#1565C0", cursor="hand2", anchor="w",
                            justify="left", wraplength=420)
            link.pack(anchor="w", pady=1)
            link.bind("<Button-1>", lambda _e, p=path: open_target(p))
