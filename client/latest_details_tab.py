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
import json
import os
import re
import threading
import tkinter as tk
from tkinter import ttk

from client.navigator_tab import (
    DATA_DIR,
    JOB_ROOT,
    open_target,
    parse_job_code,
    load_settings as _nav_load_settings,
    save_settings as _nav_save_settings,
)

SIDES = ("STRUCTURAL", "MISC")
SIDE_LABELS = {"STRUCTURAL": "Structural", "MISC": "Miscellaneous"}

# Sheet tags sit on either side of the REV depending on who issued the
# file ("BS MAP01 (S-141A)_REV0A_..." vs "MC MAP01_REV0B (S-104)_..."),
# misc stair files say DETAILS (plural), and the date may be a not-sent
# placeholder (XXXX / 000000) - captured loosely, validated strictly.
_DETAIL_RE = re.compile(
    r"^(?P<prefix>[A-Za-z]+)_(?P<body>.+?)_REV(?P<rev>[0-9A-Z]+)\s*"
    r"(?:\([^)]*\)\s*)?_DETAILS?_(?P<date>[0-9A-Za-z]*)\.pdf$",
    re.IGNORECASE,
)
# Maps without the DETAIL keyword ("FBD_MC_MAP05 (S2.91)_REV0Q_081326"):
# same shape, date directly after the REV. Layout/reference suffixed
# copies ("..._REV0E_042826_ABY_LAYOUT.pdf") and dateless ones
# ("..._REV03.pdf") deliberately do NOT match - they can't be ranked.
_MAP_FILE_RE = re.compile(
    r"^(?P<prefix>[A-Za-z]+)_(?P<body>.+?)_REV(?P<rev>[0-9A-Z]+)_"
    r"(?P<date>[0-9A-Za-z]*)\.pdf$",
    re.IGNORECASE,
)
# "BS01_(15th)" must still match (trailing underscore is not a \b word
# boundary), and hyphenated codes like S2E-A2 need their own pattern.
_CONN_RE = re.compile(r"(?<![A-Z0-9])([A-Z]{2,}\d{1,3}[A-Z]?)(?![0-9])")
_CONN_HYPHEN_RE = re.compile(
    r"(?<![A-Z0-9])([A-Z]+\d+[A-Z0-9]*(?:-[A-Z0-9]+)+)(?![0-9A-Z])")
_MAP_RE = re.compile(r"(?<![A-Z0-9])MAP\s*0*(\d{1,3})\b", re.IGNORECASE)


def _rev_key(rev):
    """Orders issued revisions as they actually progress: pure-numeric
    working REVs (00, 01, ...) first, then the lettered issued series
    (0A < 0B < ... < 0Q < ...). So REV00 < REV10 < REV0A < REV0B - a
    dated REV03 never outranks a dated REV0R from the live series."""
    m = re.match(r"(\d*)([A-Za-z]*)$", (rev or "").strip())
    num = int(m.group(1)) if m and m.group(1) else 0
    letters = (m.group(2) if m else "").upper()
    return (1 if letters else 0, num, letters)


def _date_key(date):
    """'MMDDYY' -> (YY, MM, DD) so cross-year dates compare correctly."""
    try:
        return (int(date[4:6]), int(date[0:2]), int(date[2:4]))
    except (ValueError, IndexError):
        return (-1, -1, -1)


def _valid_detail_date(date):
    """6 digits and a plausible calendar date. Placeholder stamps
    (XXXX, 000000, month 13, day 00...) mean 'not sent to the detailer
    yet' and must never surface as anyone's latest."""
    if not re.fullmatch(r"\d{6}", date or ""):
        return False
    month, day = int(date[0:2]), int(date[2:4])
    return 1 <= month <= 12 and 1 <= day <= 31


def parse_detail_name(filename):
    """SPS_BS02_(15th) (A)_REV0C_DETAIL_100126.pdf (or an FBD-style map
    like FBD_MC_MAP05 (S2.91)_REV0Q_081326.pdf, no DETAIL keyword) ->
    {'prefix', 'rev', 'date', 'key'}. None when the name isn't a
    rankable issued file (wrong shape, or a not-sent placeholder date
    like XXXX / 04XX26 / 000000)."""
    m = _DETAIL_RE.match(filename or "")
    body, rev, date = None, None, None
    if m:
        body, rev, date = m.group("body"), m.group("rev").upper(), m.group("date")
    else:
        m = _MAP_FILE_RE.match(filename or "")
        if m and _MAP_RE.search(m.group("body") or ""):
            body, rev, date = m.group("body"), m.group("rev").upper(), m.group("date")
    if body is None:
        return None
    if not _valid_detail_date(date):
        return None
    return {
        "prefix": m.group("prefix").upper(),
        "body": body,
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


def _stem(word):
    """Lowercase, de-space, drop ONE trailing 's' ('Stairs' -> 'stair')
    - but never touch short codes ('BS' must not become 'b')."""
    s = re.sub(r"\s+", "", (word or "").lower())
    if len(s) > 3 and s.endswith("s"):
        s = s[:-1]
    return s


def _pkg_mentions(pkg_name, conn):
    """Singular/plural/case-tolerant package attribution: STAIRS matches
    'West Stair 2', RAILINGS matches 'Rail', BS matches 'BS Calc Details'."""
    target = _stem(conn)
    if len(target) < 2:
        return False
    for word in re.findall(r"[A-Za-z]+", pkg_name or ""):
        w = _stem(word)
        if len(w) < 2:
            continue
        if w == target or target.startswith(w) or w.startswith(target):
            return True
    return False


def _token_alpha(token):
    m = re.match(r"[A-Z]+", token or "")
    return m.group(0) if m else ""


def _misc_family(name):
    """Bucket a misc folder/token name into its family."""
    n = _stem(name or "")
    if "stair" in n:
        return "STAIRS"
    if "ladder" in n:
        return "LADDERS"
    if "rail" in n:
        return "RAILINGS"
    if "gate" in n:
        return "GATES"
    if "ec" in n:
        return "EC"
    return None


# Working-folder children that never hold issued details at top level.
_SKIP_DIRS = {"CALCS", "MAPS", "REF", "BACKUP", "MODEL", "CAD+SKETCH",
              "RISA INPUT", "RISA OUTPUT"}


def scan_job_folders(job_base, code, side, progress=None, cancel=None):
    """Walk a job's detail sources; returns
    {family: {group: {'calc': [paths], 'map': [paths], 'folder': rel}}}.
    job_base/code are split out (instead of a job name) so tests can
    point this at a temp tree instead of the live JOBS share.

    Two-phase (enumerate, then parse) so progress(phase, done, total)
    can drive a determinate bar; cancel() returning True aborts with
    None (the caller keeps whatever it was showing before)."""
    code = (code or "").upper()
    conns = _list_conns(job_base, code, side)
    other_side = "MISC" if side == "STRUCTURAL" else "STRUCTURAL"
    other_conns = _list_conns(job_base, code, other_side)
    seen_maps = {}  # MAPnn -> conn, from working MAPS folders (disambiguates packages)

    def _report(phase, done, total):
        if progress:
            try:
                progress(phase, done, total)
            except Exception:
                pass

    def _aborted():
        try:
            return bool(cancel and cancel())
        except Exception:
            return False

    def _owning_conn(alpha):
        """(side, conn-name) for token 'BS' (from BS01): exact match,
        then prefix (ST -> STAIRS). (None, None) when neither side
        has the connection yet."""
        a = (alpha or "").upper()
        for c in conns:
            if c.upper() == a:
                return ("mine", c)
        for c in other_conns:
            if c.upper() == a:
                return ("theirs", c)
        if len(a) >= 2:
            for c in conns:
                if c.upper().startswith(a):
                    return ("mine", c)
            for c in other_conns:
                if c.upper().startswith(a):
                    return ("theirs", c)
        return (None, None)

    def _kind(info):
        return "map" if _MAP_RE.search(info["body"]) else "calc"

    def _work_family(info, conn):
        if side == "MISC" and _token_alpha(_conn_group(info["body"]) or "") == "EC":
            return "EC"
        return conn

    plans = []  # (folder, top_only, is_pkg, folder_rel, resolve)

    def _add(folder, top_only, is_pkg, folder_rel, resolve):
        plans.append((folder, top_only, is_pkg, folder_rel, resolve))

    side_root = os.path.join(job_base, "{}_CALCS".format(code), "MATHCAD CALCS", side)
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
            _add(calcs_dir, True, False, os.path.join(tail, "CALCS"),
                 lambda i, _p, c=conn: (_work_family(i, c), c, "calc"))
            try:
                subs = sorted(
                    (e.name for e in os.scandir(calcs_dir) if e.is_dir()),
                    key=str.lower,
                )
            except OSError:
                subs = []
            for sub in subs:
                _add(os.path.join(calcs_dir, sub), True, False,
                     os.path.join(tail, "CALCS", sub),
                     lambda i, _p, c=conn, s=sub: (_work_family(i, c), s, "calc"))
        # MAPS\\*.pdf (top level only - ref\\ is reference material).
        def _maps_resolve(info, _path, c=conn):
            mg = _map_group(info["body"]) or c
            if mg != c:
                seen_maps.setdefault(mg, c)
            return (_work_family(info, c), mg, "map")

        _add(os.path.join(conn_abs, "MAPS"), True, False,
             os.path.join(tail, "MAPS"), _maps_resolve)
        # Anything else issued sitting directly under the connection
        # folder, plus one level of misc-style subfolders (East Stair 1)
        # and the _SENT TO DETAILER drops.
        _add(conn_abs, True, False, tail,
             lambda i, _p, c=conn: (_work_family(i, c), _conn_group(i["body"]) or c,
                                   _kind(i)))
        try:
            kids = sorted(
                (e.name for e in os.scandir(conn_abs) if e.is_dir()),
                key=str.lower,
            )
        except OSError:
            kids = []
        for kid in kids:
            if kid.upper() in _SKIP_DIRS or kid == "_SENT TO DETAILER":
                continue
            _add(os.path.join(conn_abs, kid), True, False,
                 os.path.join(tail, kid),
                 lambda i, _p, c=conn, k=kid: (_work_family(i, c),
                                               _conn_group(i["body"]) or k, _kind(i)))
        sent = os.path.join(conn_abs, "_SENT TO DETAILER")
        if os.path.isdir(sent):
            _add(sent, False, False, os.path.join(tail, "_SENT TO DETAILER"),
                 lambda i, _p, c=conn: (_work_family(i, c),
                                        _conn_group(i["body"]) or c, _kind(i)))

    # Dated submittal packages - these can hold newer revisions than the
    # working folders, so they merge into the same groups. A package file
    # is only claimed by this side when it belongs here: calc files carry
    # their connection token (BS01 -> BS), map files ride on a working
    # MAPS copy or the package name mentioning one of this side's
    # connections ("... - BS Calc Details"). Anything neither side can
    # place lands in OTHER rather than hidden.
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
        mentioned = [c for c in conns if _pkg_mentions(pkg, c)]
        mentioned_other = [c for c in other_conns if _pkg_mentions(pkg, c)]

        def _pkg_resolve(info, path, _abs=pkg_abs,
                         _men=list(mentioned), _meno=list(mentioned_other)):
            body = info["body"]
            kind = "map" if _MAP_RE.search(body) else "calc"
            if _MAP_RE.search(body):
                grp = _map_group(body)
                if grp in seen_maps:
                    return (seen_maps[grp], grp, kind)
                if _men and not _meno:
                    return (_men[0] if len(_men) == 1 else "OTHER", grp, kind)
                if _meno and not _men:
                    return None
                return ("OTHER", grp, kind)
            tok = _conn_group(body)
            if tok is None:
                if _meno and not _men:
                    return None  # the other side's package - not ours
                parent = os.path.basename(os.path.dirname(path))
                if side == "MISC" and parent:
                    return (_misc_family(parent) or "OTHER", parent, kind)
                return ("OTHER", "(submittal)", kind)
            alpha = _token_alpha(tok)
            if alpha == "EC":
                return (("EC", tok, kind) if side == "MISC" else None)
            where, who = _owning_conn(alpha)
            if where == "mine":
                return (who, tok, kind)
            if where == "theirs":
                return None
            if _men and not _meno:
                return (_men[0] if len(_men) == 1 else "OTHER", tok, kind)
            if _meno and not _men:
                return None
            return ("OTHER", tok, kind)

        _add(pkg_abs, False, True, pkg_tail, _pkg_resolve)

    # ---- phase 1: enumerate (fast scandir walk, no parsing) ----
    files = []  # (path, folder_rel, is_pkg, resolve)
    for idx, (folder, top_only, is_pkg, folder_rel, resolve) in enumerate(plans):
        if _aborted():
            return None
        if os.path.isdir(folder):
            for path in _iter_files(folder, top_only=top_only):
                if path.lower().endswith(".pdf"):
                    files.append((path, folder_rel, is_pkg, resolve))
        _report("Listing files…", idx + 1, len(plans))

    # ---- phase 2: parse & classify (working first, then packages,
    # so package maps inherit their working MAPS family) ----
    groups = {}
    seen_names = set()  # same basename in two places = same issued file

    def _process(chunk, phase):
        total = len(chunk)
        for i, (path, folder_rel, _pkg, resolve) in enumerate(chunk):
            if _aborted():
                return False
            if i % 10 == 0 or i + 1 == total:
                _report(phase, i + 1, total)
            info = parse_detail_name(os.path.basename(path))
            if info is None or info["prefix"] != code:
                continue
            base = os.path.basename(path).lower()
            if base in seen_names:
                continue
            got = resolve(info, path)
            if got is None:
                continue
            family, group, kind = got
            seen_names.add(base)
            fam = groups.setdefault(family, {})
            g = fam.setdefault(group, {"calc": [], "map": [], "folder": folder_rel})
            if not g["folder"]:
                g["folder"] = folder_rel
            g[kind].append((info["key"], path))
        return True

    working = [f for f in files if not f[2]]
    pkgs = [f for f in files if f[2]]
    if not _process(working, "Reading working folders…"):
        return None
    if not _process(pkgs, "Reading submittal packages…"):
        return None

    # Misc packages spell the same stair several ways ("Stair 2" vs
    # "West Stair2"): merge parent-folder groups when one's de-spaced
    # name contains the other's. Structural/token groups are exact codes
    # (EC1 vs EC10 must NOT merge) and are left alone.
    for family in list(groups):
        if family not in ("STAIRS", "LADDERS", "RAILINGS", "GATES"):
            continue
        fdata = groups[family]
        merged = {}
        for gname in sorted(fdata, key=str.lower):
            norm = re.sub(r"\s+", "", gname.lower())
            dest = None
            for mk in merged:
                mkn = re.sub(r"\s+", "", mk.lower())
                if len(norm) >= 5 and len(mkn) >= 5 and (norm in mkn or mkn in norm):
                    dest = mk
                    break
            if dest is None:
                merged[gname] = fdata[gname]
                continue
            d = merged.pop(dest)
            s = fdata[gname]
            d["calc"].extend(s["calc"])
            d["map"].extend(s["map"])
            if "SUBMITTAL" in d["folder"] and "SUBMITTAL" not in s["folder"]:
                d["folder"] = s["folder"]
            merged[gname if len(gname) > len(dest) else dest] = d
        groups[family] = merged

    winners = {}
    for family, fdata in groups.items():
        grows = {}
        for group, data in fdata.items():
            row = {"folder": data["folder"]}
            for kind in ("calc", "map"):
                hits = data[kind]
                if not hits:
                    row[kind] = []
                    continue
                best = max(k for k, _p in hits)
                row[kind] = sorted(p for k, p in hits if k == best)
            if row["calc"] or row["map"]:
                grows[group] = row
        if grows:
            winners[family] = grows
    return winners


def _cache_key(job_name, side):
    return "{}\x00{}".format(job_name, side)


def get_cached_latest(job_name, side):
    """Last full scan's rows for instant paint while a background
    refresh revalidates. None when never scanned."""
    try:
        ent = _latest_cache_load().get(_cache_key(job_name, side))
    except Exception:
        return None
    rows = ent.get("rows") if isinstance(ent, dict) else None
    return rows if isinstance(rows, dict) else None


def scan_latest_details(job_name, side, progress=None, cancel=None,
                        use_cache=True):
    """Full scan for a real job on the JOBS share. {} when the job has
    no code, the share is unreachable, or nothing is found; None when a
    cancellation was requested mid-scan. Successful scans refresh the
    disk cache (see get_cached_latest)."""
    code = parse_job_code(job_name or "")
    if not code:
        return {}
    base = os.path.join(JOB_ROOT, job_name)
    if not os.path.isdir(base):
        return {}
    try:
        rows = scan_job_folders(base, code, side, progress, cancel)
    except Exception:
        return {}
    if rows is None:
        return None
    try:
        cache = _latest_cache_load()
        cache[_cache_key(job_name, side)] = {"rows": rows}
        _latest_cache_save(cache)
    except Exception:
        pass
    return rows


LATEST_CACHE_FILE = os.path.join(DATA_DIR, "latest_cache.json")


def _latest_cache_load():
    try:
        with open(LATEST_CACHE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _latest_cache_save(cache):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = LATEST_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, LATEST_CACHE_FILE)
    except Exception:
        pass


class LatestDetailsTab(ttk.Frame):
    """Newest calc detail + map per connection, grouped under MC / VB /
    BS / ... family headers. Follows NaviTool's selected job via
    get_job. Paints the cached rows instantly, then re-scans in the
    background with a progress bar (cancellable) and repaints only when
    something actually changed."""

    def __init__(self, master, get_job, embedded=False, **kwargs):
        super().__init__(master, **kwargs)
        self._get_job = get_job
        self._embedded = embedded
        # Embedded inside NaviTool's pale content area: static text uses
        # explicit-background tk labels so rows blend in (ttk labels
        # would render default gray). Standalone keeps native ttk.
        self._ebg = "#f5f6f8" if embedded else None
        self._token = 0
        self._last_job = None
        self._last_side = None
        self._cancel = None
        self._shown = None  # (job, side, rows) currently painted
        self._prog_last = 0.0
        try:
            self._side = tk.StringVar(
                value=_nav_load_settings().get("latest_side", SIDES[0]))
        except Exception:
            self._side = tk.StringVar(value=SIDES[0])
        if self._side.get() not in SIDES:
            self._side.set(SIDES[0])
        self._build_ui()

    def _tlabel(self, parent, **kw):
        """Theme-matching label: explicit-bg tk in embedded mode,
        native ttk standalone."""
        if self._ebg is None:
            return ttk.Label(parent, **kw)
        kw.pop("padding", None)  # ttk-only option - embedded packs without it
        kw.setdefault("background", self._ebg)
        return tk.Label(parent, **kw)

    # ---------------------------- UI ----------------------------
    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Latest Details and Maps",
                  font=("Segoe UI", 13, "bold")).pack(side="left")
        self.job_label = self._tlabel(top, text="", font=("Segoe UI", 9),
                                          foreground="#68727d")
        self.job_label.pack(side="left", padx=(12, 0))
        ttk.Button(top, text="Refresh",
                   command=lambda: self.refresh(force=True)).pack(side="right")
        for side in SIDES:
            ttk.Radiobutton(top, text=SIDE_LABELS[side], value=side,
                            variable=self._side,
                            command=self._on_side_changed).pack(side="right", padx=4)
        ttk.Label(top, text="Show:", font=("Segoe UI", 9)).pack(side="right", padx=(10, 0))

        hint = self._tlabel(self, padding=(10, 2, 10, 0), font=("Segoe UI", 8),
                                foreground="#68727d", wraplength=900, justify="left",
                         text="Newest issued detail + map per connection for the job "
                              "selected in NaviTool 2.0 - one tab per family, maps "
                              "in their own rows. Click a file name to open the PDF.")
        hint.pack(fill="x")

        prog = ttk.Frame(self, padding=(10, 2, 10, 0))
        prog.pack(fill="x")
        self.prog_label = self._tlabel(prog, text="", font=("Segoe UI", 8),
                                          foreground="#68727d")
        self.prog_label.pack(side="left")
        self.cancel_btn = ttk.Button(prog, text="Cancel", command=self._cancel_scan)
        self.prog_bar = ttk.Progressbar(prog, mode="determinate", length=220)
        self.prog_bar.pack(side="right", padx=(6, 0))
        self._set_progress_visible(False)

        wrap = ttk.Frame(self, padding=(10, 6, 10, 10))
        wrap.pack(fill="both", expand=True)
        if self._embedded:
            # No inner scroll region when embedded - NaviTool's own
            # content canvas scrolls the whole page (nested canvases
            # fight over the mouse wheel).
            self.body = ttk.Frame(wrap, style="App.TFrame")
            self.body.pack(fill="x")
            self._body_win = None
            return
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
    def refresh(self, force=False):
        """Paint the cached rows instantly (when the job/side didn't
        change and a cache exists), then re-scan in the background and
        repaint only on change. force=True always re-scans from blank."""
        job = self._get_job() if self._get_job else None
        side = self._side.get()
        self._token += 1
        token = self._token
        if self._cancel is not None:
            try:
                self._cancel.set()
            except Exception:
                pass
        self._cancel = threading.Event()
        if not job:
            self._set_progress_visible(False)
            self._clear()
            self._shown = None
            self._message("Pick a job in NaviTool 2.0 first - this panel follows "
                          "whatever job is selected there.")
            return
        self._last_job, self._last_side = job, side
        self.job_label.config(text="{}  \u2022  {}".format(job, SIDE_LABELS[side]))
        cached = None if force else get_cached_latest(job, side)
        if cached is not None and (self._shown is None
                                   or self._shown[:2] != (job, side)):
            self._paint(token, job, side, cached)
        elif cached is None or force:
            self._clear()
            self._shown = None
            self._tlabel(self.body, text="Loading '{}'...".format(job),
                         font=("Segoe UI", 10)).grid(row=0, column=0, pady=24)
        self._set_progress_visible(True)
        cancel = self._cancel

        def on_progress(phase, done, total):
            try:
                self.after(0, lambda: self._update_progress(
                    token, phase, done, total))
            except Exception:
                pass

        def work():
            try:
                rows = scan_latest_details(job, side,
                                           progress=on_progress,
                                           cancel=cancel.is_set)
            except Exception:
                rows = {}
            try:
                self.after(0, lambda: self._finish(token, job, side, rows))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _cancel_scan(self):
        if self._cancel is not None:
            try:
                self._cancel.set()
            except Exception:
                pass

    def _set_progress_visible(self, visible):
        try:
            if visible:
                self.prog_bar.pack(side="right", padx=(6, 0))
                self.cancel_btn.pack(side="right")
                self.prog_bar["value"] = 0
                self.prog_label.config(text="Starting…")
            else:
                self.prog_bar.pack_forget()
                self.cancel_btn.pack_forget()
                self.prog_label.config(text="")
        except tk.TclError:
            pass

    def _update_progress(self, token, phase, done, total):
        if token != self._token:
            return
        try:
            import time as _time
            now = _time.monotonic()
            if done < total and now - self._prog_last < 0.1:
                return
            self._prog_last = now
            self.prog_bar["maximum"] = max(total, 1)
            self.prog_bar["value"] = done
            self.prog_label.config(text="{}  {}/{}".format(phase, done, total))
        except tk.TclError:
            pass

    def _finish(self, token, job, side, rows):
        if token != self._token:
            return
        try:
            if not self.body.winfo_exists():
                return
        except tk.TclError:
            return
        self._set_progress_visible(False)
        if rows is None:
            # Cancelled - keep whatever was on screen.
            self.prog_label.config(text="Cancelled - showing previous results.")
            return
        if self._shown is not None and self._shown[:2] == (job, side) \
                and self._shown[2] == rows:
            return  # background refresh found nothing new - no flicker
        self._paint(token, job, side, rows)

    def _clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def _message(self, text):
        self.job_label.config(text="")
        self._tlabel(self.body, text=text, font=("Segoe UI", 10),
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
        self._shown = (job, side, rows)
        self.job_label.config(text="{}  \u2022  {}".format(job, SIDE_LABELS[side]))
        if not rows:
            self._message("No issued detail files found yet for '{}' "
                          "({}). They appear here once DETAIL pdfs land in the "
                          "job's CALCS/MAPS folders or a dated submittal "
                          "package.".format(job, SIDE_LABELS[side]))
            return
        show_maps = side != "MISC"  # misc (stairs/rails/ladders/gates/EC) has no maps
        nb = ttk.Notebook(self.body)
        nb.pack(fill="x", padx=4, pady=(2, 6))
        fams = sorted(rows, key=str.lower)
        # OTHER collects the unplaceable leftovers - always the last tab.
        fams = [f for f in fams if f != "OTHER"]
        if "OTHER" in rows:
            fams.append("OTHER")
        for family in fams:
            page = ttk.Frame(nb)
            if self._ebg is not None:
                page.configure(style="App.TFrame")
            nb.add(page, text=family)
            self._paint_family(page, job, rows[family], show_maps)
        self._fam_nb = nb

    def _paint_family(self, page, job, fdata, show_maps):
        """One family tab: connection calc rows, then a MAPS block with
        one row per map (structural only). No map column anywhere."""
        headers = ("Connection", "Latest calc detail", "")
        for col, text in enumerate(headers):
            self._tlabel(page, text=text,
                         font=("Segoe UI", 9, "bold")).grid(
                             row=0, column=col, sticky="w", padx=8, pady=(2, 6))
        row_idx = 1
        calc_groups = sorted(
            (g for g, d in fdata.items() if d["calc"]), key=str.lower)
        for group in calc_groups:
            row_idx = self._paint_row(page, job, row_idx, group, fdata[group]["calc"],
                                      fdata[group]["folder"])
        if show_maps:
            map_groups = sorted(
                (g for g, d in fdata.items() if d["map"]), key=str.lower)
            if map_groups:
                self._tlabel(page, text="\u2014 MAPS \u2014",
                             font=("Segoe UI", 9, "bold"),
                             foreground="#20252b").grid(row=row_idx, column=0,
                                                        columnspan=3, sticky="w",
                                                        padx=8, pady=(10, 2))
                row_idx += 1
                for group in map_groups:
                    row_idx = self._paint_row(page, job, row_idx, group,
                                              fdata[group]["map"],
                                              fdata[group]["folder"])
        page.grid_columnconfigure(1, weight=1)

    def _paint_row(self, page, job, row_idx, group, paths, folder_rel):
        self._tlabel(page, text=group,
                     font=("Segoe UI", 10, "bold")).grid(
                         row=row_idx, column=0, sticky="nw", padx=8, pady=6)
        self._link_cell(page, row_idx, 1, paths, job)
        if folder_rel:
            ttk.Button(page, text="Open folder",
                       command=lambda r=folder_rel: open_target(
                           os.path.join(JOB_ROOT, job, r))).grid(
                               row=row_idx, column=2, sticky="nw",
                               padx=8, pady=4)
        else:
            self._tlabel(page, text="\u2014",
                         foreground="#9aa0a6").grid(row=row_idx, column=2,
                                                    sticky="w", padx=8)
        return row_idx + 1

    def _link_cell(self, parent, row, col, paths, job):
        if self._ebg is None:
            cell = ttk.Frame(parent)
        else:
            cell = ttk.Frame(parent, style="App.TFrame")
        cell.grid(row=row, column=col, sticky="nw", padx=8, pady=4)
        if not paths:
            self._tlabel(cell, text="\u2014", foreground="#9aa0a6").pack(anchor="w")
            return
        for path in paths:
            name = os.path.basename(path)
            link = tk.Label(cell, text=name, font=("Segoe UI", 9, "underline"),
                            foreground="#1565C0", cursor="hand2", anchor="w",
                            justify="left", wraplength=420)
            if self._ebg is not None:
                link.configure(background=self._ebg)
            link.pack(anchor="w", pady=1)
            link.bind("<Button-1>", lambda _e, p=path: open_target(p))
