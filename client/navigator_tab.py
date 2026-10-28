"""NaviTool 2.0, embedded as a tab inside the DEA Logger.

Originally a standalone app (Project - Job-nav ChatGPT v2); now imported
by client/main_app.py and mounted as the "NaviTool 2.0" notebook tab.
Must stay import-safe: no Tk root creation and no demo runner at import.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except Exception:
    HAS_DND = False

try:
    from shared import pathutils
except Exception:  # standalone copy of this module, outside DEA
    pathutils = None

try:
    from shared import usage
except Exception:  # standalone copy of this module, outside DEA
    usage = None


def _record(key):
    try:
        if usage is not None:
            usage.record(key)
    except Exception:
        pass

APP_NAME = "NaviTool 2.0"
JOB_ROOT = r"\\EgnyteDrive\idsinc\Shared\Engineering\ENGG PHL\JOBS"

_JOB_ROOT_CACHE = {"path": None, "at": 0.0}
_JOB_ROOT_TTL_SECONDS = 60.0


def job_root():
    """JOB_ROOT pointed at whichever Egnyte share name actually exists on
    this PC ('idsinc' or 'idsinc (2)' - see shared/pathutils). Cached
    briefly: this is read on every job-row render, and probing the aliases
    of a share that is genuinely missing costs real network timeouts."""
    now = time.time()
    cached = _JOB_ROOT_CACHE["path"]
    if cached and now - _JOB_ROOT_CACHE["at"] < _JOB_ROOT_TTL_SECONDS:
        return cached
    path = pathutils.resolve_existing_dir(JOB_ROOT) if pathutils else JOB_ROOT
    _JOB_ROOT_CACHE["path"] = path
    _JOB_ROOT_CACHE["at"] = now
    return path


def _scan_job_dirs():
    """Folder names under job_root(), sorted case-insensitively.

    Module-level (and Tk-free) so it can run in a daemon thread and be
    stubbed in tests: the walk costs ~0.3 s for 182 folders on a warm
    share and much more on a slow day, which is exactly why the Navigator
    paints its shell first and fills the job list in afterwards
    (v2.6.39). Raises OSError when the JOBS root itself can't be read."""
    names = []
    with os.scandir(job_root()) as it:
        for entry in it:
            try:
                if entry.is_dir():
                    names.append(entry.name)
            except OSError:
                continue  # one unreadable entry must not kill the list
    return sorted(names, key=str.lower)


# Work-stage groups. Each section header is a click-to-collapse toggle.
# Items are either plain buttons or dropdown (Menubutton) buttons; "{code}"
# in a relative path is replaced with the job's 3-letter code. Only items
# whose folder actually exists for the selected job are shown.
STAGE_TITLES = ["CALCS", "INITIAL", "SUBMITTAL", "FABRICATION"]

_CODE_RE = re.compile(r"\b([A-Za-z]{3})-")


def parse_job_code(folder_name):
    """'26 SPS-ASD15 Trinity' -> 'SPS'. None if the name has no CODE- pattern."""
    m = _CODE_RE.search(folder_name)
    return m.group(1).upper() if m else None


def _exists(base, rel):
    return bool(rel) and os.path.isdir(os.path.join(base, rel))


def _folder_menu(base, rel, depth=0, max_depth=3, label=None):
    """Nested menu entries for one folder: [(label, rel-or-children), ...].

    Every level starts with the folder's own name as an open-folder
    command (tk cascade headers can't run commands themselves, so this
    keeps each folder clickable: BS, BS > CALCS, BS > CALCS > BS01...),
    followed by one cascade per subfolder, down to max_depth. A folder
    with no subfolders of its own collapses to a plain open-folder
    command (a bare rel string)."""
    own = label if label is not None else (os.path.basename(rel.rstrip("\\")) or rel)
    entries = [(own, rel)]
    if depth >= max_depth:
        return entries
    kids = _dir_entries(base, rel)
    if kids:
        entries.append(("-", None))
        for name in kids:
            child = rel + "\\" + name if rel else name
            sub = _folder_menu(base, child, depth + 1, max_depth)
            entries.append((name, sub if len(sub) > 1 else child))
    return entries


def _dir_entries(base, rel):
    """Sorted list of immediate subfolders under a job-relative path.
    Folders named exactly VOID, OLD, or REF (any case) are left out -
    void drops, archive dumps, and reference piles never belonged in
    working menus. Anything merely *containing* those words
    ("... to VOID", "Threshold") still lists: only exact names match."""
    out = []
    try:
        with os.scandir(os.path.join(base, rel)) as it:
            for e in it:
                if e.is_dir():
                    if e.name.strip().upper() in ("VOID", "OLD", "REF"):
                        continue
                    out.append(e.name)
    except OSError:
        pass
    return sorted(out, key=str.lower)


def _short_menu_label(name):
    """Display-only short code for a menu entry: an already-ranged "X
    to Y" header is kept verbatim, so a chunk range is never truncated
    to its first endpoint (leaf folders essentially never take that
    exact single-token shape, and keeping input unchanged is harmless
    when they do); else the embedded #-code ("262601 FBD CD#001
    (Sequence Map...)" -> "CD#001"), else a from/to range when both
    ends hold a digit ("032626 - S2 to 050926E - giza" -> "032626 to
    050926E"), else a leading date ("061826 - Seq.18M Stair..." ->
    "061826" - sketch folders are date-filed), else the first
    whitespace-delimited token when it looks like a code (letters AND
    digits: "MC36 - ..." -> "MC36", "2M2W-C3B1 - ..." -> "2M2W-C3B1").
    Pure sequence numbers ("01) To LPM", "031226", "1007 FF") and plain
    words ("For Approval", "RFI SENT", "Seq 01", "Wbm to Wcol Web") are
    NOT codes - the full name stays, since there the description is the
    meaning. Open targets never change - only what's printed."""
    text = str(name or "")
    if re.match(r"^(\S+) to (\S+)$", text.strip()):
        return text
    m = re.search(r"([A-Z]{2,}#\d+[A-Z0-9-]*)", text)
    if m:
        return m.group(1)
    m = re.match(r"^(\S*\d\S*)\s+.*?\bto\b\s+(\S*\d\S*)",
                 text.strip(), re.IGNORECASE)
    if m:
        return "{} to {}".format(m.group(1), m.group(2))
    m = re.match(r"^(\d{4,8})\s+-\s+", text.strip())
    if m:
        return m.group(1)
    m = re.match(r"^(?=\S*\d)(?=\S*[A-Za-z])(\S+)", text.strip())
    if m:
        return m.group(1)
    return text


def _shorten_menu_level(entries):
    """One menu level with display labels compressed via
    _short_menu_label. Entries colliding on the same short code keep
    their full names so no two rows ever read identically."""
    shorts = {}
    for entry in entries or []:
        if not entry or entry[0] == "-":
            continue
        shorts.setdefault(_short_menu_label(entry[0]), []).append(entry[0])
    dupes = {s for s, owners in shorts.items() if len(owners) > 1}
    out = []
    for entry in entries or []:
        if not entry or entry[0] == "-":
            out.append(entry)
            continue
        short = _short_menu_label(entry[0])
        if short in dupes:
            out.append(entry)
        else:
            out.append((short,) + tuple(entry[1:]))
    return out


def _cascade_or_open(base, rel, label=None):
    """_folder_menu() when the folder has children, else a bare rel that
    renders as a plain open-folder command."""
    if _dir_entries(base, rel):
        return _folder_menu(base, rel, label=label)
    return rel


# A cascade level holding more than this many entries gets split into
# balanced "first to last" sub-cascades, so no native menu grows taller
# than the screen. Short levels render exactly as before.
MENU_CHUNK_SIZE = 25


def _chunk_range_label(first, last):
    """Compact "CD#001 to CD#025" / "MC01 to MC35" / "031226 to 033126"
    chunk label from the chunk's real first/last entry names. In order:
    (1) same leading text plus a trailing number on both sides collapses
    to first-full-name + last-number (number strings kept verbatim, so
    zero-padding and "#" styles survive); (2) same embedded PREFIX#/-
    digits code with different numbers (the CD number buried in
    "262601 FBD CD#001 (Sequence Map...)") collapses to "CD#001 to
    CD#025". Single-letter codes (W21) and digit-free names can never
    match. Anything else composes from the entries' own short display
    forms ("050926E - per CD132" .. "SQ_004 Material Grade" becomes
    "050926E to SQ_004" instead of a full-text range); only a degenerate
    equal-short pair falls back to truncated full names, so a chunk
    header is always short and always bounds its contents."""
    first, last = str(first or "").strip(), str(last or "").strip()
    m1 = re.match(r"^(.*?)(\d+)$", first)
    m2 = re.match(r"^(.*?)(\d+)$", last)
    if m1 and m2 and m1.group(1) == m2.group(1) and m1.group(2) != m2.group(2):
        return "{} to {}{}".format(first[:28], m1.group(1), m2.group(2))[:60]
    c1 = re.search(r"([A-Z]{2,}[#-]?)(\d{1,4})", first)
    c2 = re.search(r"([A-Z]{2,}[#-]?)(\d{1,4})", last)
    if c1 and c2 and c1.group(1) == c2.group(1) and c1.group(2) != c2.group(2):
        return "{} to {}{}".format(c1.group(0), c1.group(1), c2.group(2))
    r1 = re.match(r"^(\S+) to (\S+)$", first)
    r2 = re.match(r"^(\S+) to (\S+)$", last)
    if r1 and r2:
        return "{} to {}".format(r1.group(1), r2.group(2))
    s1, s2 = _short_menu_label(first), _short_menu_label(last)
    if s1 and s2 and s1 != s2:
        return "{} to {}".format(s1, s2)
    label = "{} to {}".format(first, last)
    return label if len(label) <= 60 else label[:57] + "..."


def _chunk_menu_entries(entries):
    """Split long runs of non-separator entries into balanced sub-cascades
    ("CD#1 to CD#60", ...). Leaves and sub-cascades chunk together (CD
    folders and CALCS connections mix both); separators, head pins, and
    short levels pass through untouched, in original order. Applied per
    level by _fill_menu, so every depth chunks independently."""
    out = []
    run = []

    def _flush():
        if len(run) > MENU_CHUNK_SIZE:
            n = -(-len(run) // MENU_CHUNK_SIZE)  # ceil: balanced, no tiny tail
            size, extra = divmod(len(run), n)
            idx = 0
            for c in range(n):
                take = size + (1 if c < extra else 0)
                part = run[idx:idx + take]
                idx += take
                out.append((_chunk_range_label(part[0][0], part[-1][0]),
                            list(part)))
        else:
            out.extend(run)
        del run[:]

    for entry in entries or []:
        if not entry or entry[0] == "-":
            _flush()
            if entry:
                out.append(entry)
        else:
            run.append(entry)
    _flush()
    return out


def _group_calc_packages(sent, names):
    """SENT CALCS menu tail for the package folders. CALC#-pattern
    packages nest under a CALC cascade once they outnumber
    MENU_CHUNK_SIZE (an AMG-scale run chunks within it); anything else
    stays a top-level leaf, and small sets stay flat exactly as before.
    Children are plain open-folder leaves - packages can be enormous,
    so their contents are never enumerated at build time."""
    pkgs = [n for n in names if re.search(r"CALC#\d+", n)]
    if len(pkgs) <= MENU_CHUNK_SIZE:
        return [(n, sent + "\\" + n) for n in names]
    rest = [n for n in names if not re.search(r"CALC#\d+", n)]
    kids = [(n, sent + "\\" + n) for n in pkgs]
    return [("CALC", kids)] + [(n, sent + "\\" + n) for n in rest]


def build_job_sections(job_name, progress=None, cancel=None):
    """Return [(title, [item, ...]), ...]. An item is either
    {"kind":"button", label, rel, icon} or
    {"kind":"dropdown", label, icon, menu:[(menu_label, rel-or-children), ...]}
    where a nested list value is a further cascade (see _folder_menu).

    progress(phase_text) reports where the background build is (same
    contract as the Latest Details scan); cancel() returning True aborts
    with None (the caller keeps its placeholder and caches nothing)."""
    def _report(text):
        if progress:
            try:
                progress(text)
            except Exception:
                pass

    def _aborted():
        try:
            return bool(cancel and cancel())
        except Exception:
            return False

    base = os.path.join(job_root(), job_name)
    code = parse_job_code(job_name)
    if not code:
        return [("", [{"kind": "button", "label": "Job folder", "icon": "\U0001F4C1",
                       "rel": "", "menu": None}])]

    def sc(name, *parts):
        return "\\".join([code + "_" + name] + list(parts))

    sections = []

    # ---------- CALCS (main work) ----------
    calcs = []
    mathcad = sc("CALCS", "MATHCAD CALCS")
    if _exists(base, mathcad):
        menu = [("CALCS", sc("CALCS")), ("-", None)]
        for sub in ("MISC", "STRUCTURAL"):
            if _aborted():
                return None
            root = mathcad + "\\" + sub
            if _exists(base, root):
                submenu = [(sub, root), ("-", None)]
                names = _dir_entries(base, root)
                for i, name in enumerate(names):
                    if _aborted():
                        return None
                    conn = root + "\\" + name
                    submenu.append((name, _folder_menu(base, conn)))
                    _report("Reading CALCS… {}/{}".format(i + 1, len(names)))
                menu.append((sub, submenu))
        calcs.append({"kind": "dropdown", "label": "CALCS", "icon": "\U0001F9EE", "menu": menu})
    elif _exists(base, sc("CALCS")):
        calcs.append({"kind": "button", "label": "CALCS", "icon": "\U0001F9EE",
                      "rel": sc("CALCS"), "menu": None})
    if _aborted():
        return None
    sent = sc("CALCS", "SENT CALCS")
    if _exists(base, sent):
        menu = [("SENT CALCS", sent), ("-", None)]
        names = _dir_entries(base, sent)
        if _aborted():
            return None
        menu.extend(_group_calc_packages(sent, names))
        _report("Reading SENT CALCS… {}/{}".format(len(names), len(names)))
        calcs.append({"kind": "dropdown", "label": "SENT CALCS", "icon": "\U0001F4E4", "menu": menu})
    if calcs:
        sections.append(("CALCS", calcs))

    # ---------- Initial proceedings ----------
    if _aborted():
        return None
    _report("Reading INITIAL…")
    initial = []
    dd_root = sc("DESIGN DRAWINGS")
    if _exists(base, dd_root):
        menu = [("DESIGN DRAWINGS", dd_root), ("-", None)]
        for name in ("ARCHITECTURAL", "STRUCTURAL"):
            if _exists(base, dd_root + "\\" + name):
                menu.append((name, dd_root + "\\" + name))
        initial.append({"kind": "dropdown", "label": "DESIGN DRAWINGS",
                        "icon": "\U0001F4D0", "menu": menu})
    ier_root = sc("INITIAL ENGINEERING REVIEW")
    if _exists(base, ier_root):
        menu = []
        for sub in ("MISC", "STRUCTURAL"):
            if _exists(base, ier_root + "\\" + sub):
                menu.append((sub, ier_root + "\\" + sub))
        if menu:
            initial.append({"kind": "dropdown", "label": "IER", "icon": "\U0001F50E", "menu": menu})
        else:
            initial.append({"kind": "button", "label": "IER", "icon": "\U0001F50E",
                            "rel": ier_root, "menu": None})
    schemes = sc("SCHEMES")
    if _exists(base, schemes):
        initial.append({"kind": "button", "label": "SCHEMES", "icon": "\U0001F4D0",
                        "rel": schemes, "menu": None})
    rfi = sc("RFI")
    if _exists(base, rfi):
        menu = [("RFI", rfi), ("-", None)]
        subs = [s for s in ("RFI SENT", "RFI RESPONSE")
                if _exists(base, rfi + "\\" + s)]
        for i, sub in enumerate(subs):
            if _aborted():
                return None
            root = rfi + "\\" + sub
            menu.append((sub, _cascade_or_open(base, root, sub)))
            _report("Reading RFI… {}/{}".format(i + 1, len(subs)))
        initial.append({"kind": "dropdown", "label": "RFI", "icon": "\U0001F4E9", "menu": menu})
    sk = sc("SKETCHES")
    if _exists(base, sk):
        if _aborted():
            return None
        _report("Reading SKETCHES…")
        if _dir_entries(base, sk):
            initial.append({"kind": "dropdown", "label": "SKETCHES", "icon": "\u270F",
                            "menu": _folder_menu(base, sk, label="SKETCHES")})
        else:
            initial.append({"kind": "button", "label": "SKETCHES", "icon": "\u270F",
                            "rel": sk, "menu": None})
    if initial:
        sections.append(("INITIAL", initial))

    # ---------- Submittal stage ----------
    if _aborted():
        return None
    _report("Reading SUBMITTAL…")
    submittal = []
    if _exists(base, sc("SUBMITTAL")):
        submittal.append({"kind": "button", "label": "SUBMITTAL", "icon": "\U0001F4E4",
                          "rel": sc("SUBMITTAL"), "menu": None})
    det_root = sc("DETAILING")
    if _exists(base, det_root):
        menu = [("DETAILING", det_root), ("-", None)]
        subs = [s for s in ("SHOP DRAWINGS", "LAYOUT")
                if _exists(base, det_root + "\\" + s)]
        for i, sub in enumerate(subs):
            if _aborted():
                return None
            root = det_root + "\\" + sub
            # DESIGN COMMENTS (and For Approval / Seq XX levels) live
            # under SHOP DRAWINGS and surface through the recursion.
            menu.append((sub, _cascade_or_open(base, root, sub)))
            _report("Reading DETAILING… {}/{}".format(i + 1, len(subs)))
        submittal.append({"kind": "dropdown", "label": "DETAILING",
                          "icon": "\U0001F3D7", "menu": menu})
    if submittal:
        sections.append(("SUBMITTAL", submittal))

    # ---------- Fabrication stage ----------
    if _aborted():
        return None
    _report("Reading FABRICATION…")
    fab = []
    if _exists(base, sc("APPROVAL SUMMARY")):
        fab.append({"kind": "button", "label": "APPROVAL SUMMARY", "icon": "\U0001F4CA",
                    "rel": sc("APPROVAL SUMMARY"), "menu": None})
    cd_root = sc("CHANGE DOCUMENTS")
    if _exists(base, cd_root):
        cd_target = cd_root + "\\APPROVAL RETURNS"
        if _exists(base, cd_target) and _dir_entries(base, cd_target):
            menu = [("CD", cd_target), ("-", None)]
            names = _dir_entries(base, cd_target)
            for i, name in enumerate(names):
                if _aborted():
                    return None
                rel = cd_target + "\\" + name
                menu.append((name, _cascade_or_open(base, rel, name)))
                _report("Reading CD… {}/{}".format(i + 1, len(names)))
            fab.append({"kind": "dropdown", "label": "CD", "icon": "\U0001F4DD",
                        "menu": menu})
        else:
            fab.append({"kind": "button", "label": "CD", "icon": "\U0001F4DD",
                        "rel": cd_target if _exists(base, cd_target) else cd_root,
                        "menu": None})
    if fab:
        sections.append(("FABRICATION", fab))

    if _aborted():
        return None
    return sections


DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "IDS", "Navigator")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")

# Splitter limits. The sidebar may grow well past its old 520 px ceiling
# (long job names at high display scaling) but never so far that the
# 3-column job-folder grid gets squeezed below _MAIN_MIN_W. Drag motion
# is coalesced to one layout pass per frame: re-laying out hundreds of
# folder/row widgets on every pixel was what made dragging feel laggy.
SIDEBAR_MIN_W = 200
SIDEBAR_MAX_W = 720
MAIN_MIN_W = 420
DRAG_INTERVAL_MS = 16
FAV_DEFAULT_ROWS = 10
FAV_MIN_ROWS = 3
FAV_MAX_ROWS = 30
GRIP_BG = "#20252b"
GRIP_HOVER = "#3d79b9"

# Bumped whenever menu-tree content rules change (2.6.17 excluded
# VOID/OLD/REF folders at build time) so stale cached jobs rebuild
# once instead of showing pre-change entries forever. The orphaned
# previous file is deleted on load.
SECTION_CACHE_FILE = os.path.join(DATA_DIR, "section_cache_v4.json")
SECTION_CACHE_PREVIOUS = (os.path.join(DATA_DIR, "section_cache_v3.json"),)


def load_section_cache():
    """Disk cache of built job sections {job_name: sections}. Lets favorites
    and recently opened jobs load instantly instead of re-scanning the network
    share every time. Invalid entries are simply rebuilt by the caller."""
    for old in SECTION_CACHE_PREVIOUS:
        try:
            if os.path.isfile(old) and old != SECTION_CACHE_FILE:
                os.remove(old)
        except OSError:
            pass
    try:
        with open(SECTION_CACHE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_section_cache(cache):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = SECTION_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
        os.replace(tmp, SECTION_CACHE_FILE)
    except Exception:
        pass

ADMIN_LINKS = [
    {"name": "Connection Ebook", "type": "web",
     "target": "http://192.168.0.118/ids-connection-ebook/dashboard"},
    {"name": "AISC Steel Manual", "type": "file",
     "target": r"\\EgnyteDrive\idsinc\Shared\Engineering\ENGG PHL\REFERENCES\AISC 15th Ed Manual & Specs\AISC Steel Construction Manual, 15th Edition, First Printing Edition, 2017 (HIGH QUALITY VERSION).pdf"},
]

def _admin_links_file():
    # Offline fallback shipped with the app. When embedded in DEA this
    # module lives in client/, so check the app root (parent of client/)
    # first, then the module's own folder (standalone layout).
    here = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, "frozen", False):
        # Installed exe: next to the exe first, then the PyInstaller bundle
        # (covers running straight from dist\ before install.bat copies the
        # fallback file alongside the exe).
        for base in (os.path.dirname(sys.executable),
                     getattr(sys, "_MEIPASS", None)):
            if base and os.path.isfile(os.path.join(base, "admin_links.json")):
                return os.path.join(base, "admin_links.json")
        return os.path.join(os.path.dirname(sys.executable), "admin_links.json")
    for candidate in (os.path.join(os.path.dirname(here), "admin_links.json"),
                      os.path.join(here, "admin_links.json")):
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(os.path.dirname(here), "admin_links.json")


def _read_links_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            clean = [d for d in data
                     if isinstance(d, dict) and d.get("name") and d.get("target")]
            if clean:
                return clean
    except Exception:
        pass
    return None


def _write_links_json(path, links):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(links, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


DEA_CONFIG = r"\\EgnyteDrive\idsinc\Shared\Engineering\ENGG PHL\REPORTS\16 Manhour Report LEADERBOARD\DEA App\DEA_Config.xlsx"


def _shared_admin_links_file():
    """admin_links.json next to the shared DEA_Config.xlsx, on whichever
    Egnyte share name this PC actually has (see job_root()). Without this,
    PCs where the share is 'idsinc (2)' silently fall back to the local
    copy and the admin's edits never reach the team."""
    folder = os.path.dirname(DEA_CONFIG)
    if pathutils:
        folder = pathutils.resolve_existing_dir(folder)
    return os.path.join(folder, "admin_links.json")


# Built-in icon set for quick-link buttons (Segoe MDL2 Assets glyphs,
# theme-proof unlike color emoji). A link may override its type default
# with any of these via the "Icon..." button in either link manager;
# stored as link["icon"] in settings.json / admin_links.json.
LINK_ICON_CHOICES = [
    ("Globe", "\uE774"),
    ("Document", "\uE8A5"),
    ("Folder", "\uE8B7"),
    ("Calculator", "\uE8EF"),
    ("Mail", "\uE715"),
    ("Link", "\uE71B"),
    ("Star", "\uE734"),
    ("Wrench", "\uE924"),
    ("People", "\uE716"),
    ("Phone", "\uE723"),
    ("Share", "\uE72D"),
    ("Calendar", "\uE787"),
    ("MapPin", "\uE81C"),
    ("Database", "\uE80A"),
    ("Upload", "\uE7E8"),
    ("Download", "\uE896"),
    ("Home", "\uE80F"),
    ("Chart", "\uE825"),
]

# Optional per-link accent color, painted onto the glyph (launch buttons
# get a Pillow-rendered colored image, manager lists get a colored row).
# None = default monochrome look. Stored as link["color"] in
# settings.json / admin_links.json; old links without it are unaffected.
LINK_COLOR_CHOICES = [
    ("Default", None),
    ("Orange", "#F57F17"),
    ("Blue", "#1E88E5"),
    ("Green", "#43A047"),
    ("Red", "#E53935"),
    ("Purple", "#8E24AA"),
    ("Teal", "#00897B"),
]


_LINK_IMAGE_CACHE = {}

def colored_glyph_image(glyph, color, px=18):
    """Render an MDL2 glyph in `color` to a PhotoImage (Pillow, system
    font - exe-safe, no asset file). Cached; Tk images die with their
    last Python reference, hence the module-level cache. Returns None
    if Pillow/the font is unavailable - callers fall back to the plain
    monochrome text glyph."""
    key = (glyph, color, px)
    img = _LINK_IMAGE_CACHE.get(key)
    if img is None:
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageTk
            big = px * 4
            font = ImageFont.truetype("segmdl2.ttf", big)
            im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
            d = ImageDraw.Draw(im)
            bbox = d.textbbox((0, 0), glyph, font=font)
            w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            d.text(((big - w) / 2 - bbox[0], (big - h) / 2 - bbox[1]),
                   glyph, font=font, fill=color)
            im = im.resize((px, px), Image.LANCZOS)
            img = ImageTk.PhotoImage(im)
            _LINK_IMAGE_CACHE[key] = img
        except Exception:
            return None
    return img


def default_icon_for_type(typ):
    return {"web": "\uE774", "file": "\uE8A5", "folder": "\uE8B7"}.get(typ, "\uE71B")


_ORANGE_DOT_CACHE = {}

def orange_dot_image(size=14, color="#F57F17"):
    """Small orange-circle PhotoImage for buttons. Drawn at runtime (no
    asset file, so exe-safe) and cached - Tk images die with their last
    Python reference, hence the module-level cache."""
    key = (size, color)
    img = _ORANGE_DOT_CACHE.get(key)
    if img is None:
        try:
            img = tk.PhotoImage(width=size, height=size)
            r = size / 2 - 1
            for y in range(size):
                for x in range(size):
                    dx, dy = x + 0.5 - size / 2, y + 0.5 - size / 2
                    if dx * dx + dy * dy <= r * r:
                        img.put(color, (x, y))
                    else:
                        img.transparency_set(x, y, True)
            _ORANGE_DOT_CACHE[key] = img
        except Exception:
            return None
    return img


def resolve_link_icon(link):
    """Explicit per-link icon if one was picked, else the type default."""
    return link.get("icon") or default_icon_for_type(link.get("type"))


def pick_link_icon(parent, current_glyph=None, current_color=None):
    """Modal glyph + color picker. Returns (glyph, color) on Save (color
    None = default monochrome), or None if cancelled. Opens preselected
    on the link's current choices, so saving untouched keeps them."""
    result = {"glyph": current_glyph, "color": current_color, "saved": False}
    win = tk.Toplevel(parent)
    win.title("Choose Icon")
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()
    summary = tk.StringVar()
    dots = []

    def refresh_summary():
        gname = next((n for n, g in LINK_ICON_CHOICES if g == result["glyph"]),
                     "Type default" if not result["glyph"] else "Custom")
        cname = next((n for n, c in LINK_COLOR_CHOICES if c == result["color"]),
                     "Custom" if result["color"] else "Default")
        summary.set("Icon: {}    Color: {}".format(gname, cname))

    ttk.Label(win, text="Choose an icon:", font=("Segoe UI", 10, "bold")).pack(
        padx=14, pady=(12, 6))
    grid = ttk.Frame(win)
    grid.pack(padx=14, pady=(0, 6))
    for i, (name, glyph) in enumerate(LINK_ICON_CHOICES):
        ttk.Button(grid, text="{}  {}".format(glyph, name), width=16,
                   command=lambda g=glyph: (result.update(glyph=g), refresh_summary())
                   ).grid(row=i // 3, column=i % 3, padx=4, pady=4)
    ttk.Label(win, text="Color:", font=("Segoe UI", 10, "bold")).pack(padx=14, pady=(6, 2))
    crow = ttk.Frame(win)
    crow.pack(padx=14, pady=(0, 6))
    for cname, chex in LINK_COLOR_CHOICES:
        if chex is None:
            ttk.Button(crow, text=cname,
                       command=lambda: (result.update(color=None), refresh_summary())
                       ).pack(side="left", padx=4)
        else:
            dot = orange_dot_image(12, chex)
            dots.append(dot)
            ttk.Button(crow, text=cname, image=dot, compound="left",
                       command=lambda c=chex: (result.update(color=c), refresh_summary())
                       ).pack(side="left", padx=4)
    ttk.Label(win, textvariable=summary, font=("Segoe UI", 9),
              foreground="#68727d").pack(padx=14, pady=(0, 6))
    brow = ttk.Frame(win)
    brow.pack(pady=(0, 12))
    ttk.Button(brow, text="Save",
               command=lambda: (result.update(saved=True), win.destroy())).pack(side="left")
    ttk.Button(brow, text="Cancel", command=win.destroy).pack(side="left", padx=(6, 0))
    refresh_summary()
    win.bind("<Escape>", lambda e: win.destroy())
    parent.wait_window(win)
    if result["saved"]:
        return result["glyph"], result["color"]
    return None


_ADMIN_LINKS_CACHE = {"links": None, "at": 0.0}
_ADMIN_LINKS_TTL_SECONDS = 60.0


def invalidate_admin_links_cache():
    """Forget the memoized admin links so the next read hits disk."""
    _ADMIN_LINKS_CACHE["links"] = None
    _ADMIN_LINKS_CACHE["at"] = 0.0


def get_admin_links():
    """Admin-defined quick links, shared centrally so every install sees the
    same set. Priority:
      1. admin_links.json sitting next to the shared DEA_Config.xlsx
      2. a local admin_links.json shipped with the app (offline fallback)
      3. the embedded defaults above.

    Memoized briefly: the click path calls this several times per render,
    and each uncached call hits the network share."""
    now = time.monotonic()
    if (_ADMIN_LINKS_CACHE["links"] is not None
            and now - _ADMIN_LINKS_CACHE["at"] < _ADMIN_LINKS_TTL_SECONDS):
        return _ADMIN_LINKS_CACHE["links"]
    links = _read_links_json(_shared_admin_links_file())
    if not links:
        links = _read_links_json(_admin_links_file())
    if not links:
        links = ADMIN_LINKS
    _ADMIN_LINKS_CACHE["links"] = links
    _ADMIN_LINKS_CACHE["at"] = now
    return links


def load_admin_credentials():
    """Username/password that unlock the admin quick-link editor, read live
    from the 'App Settings' sheet of the shared DEA_Config.xlsx. Goes
    through the shared config opener so a file-open-encrypted config still
    works (falls back to a plain openpyxl read when run standalone)."""
    try:
        try:
            from shared.config_manager import open_config_workbook
            wb = open_config_workbook(DEA_CONFIG)
        except ImportError:
            import openpyxl
            wb = openpyxl.load_workbook(DEA_CONFIG, data_only=True, read_only=True)
        try:
            if "App Settings" not in wb.sheetnames:
                return None
            creds = {}
            for row in wb["App Settings"].iter_rows(values_only=True):
                if row and row[0] in ("AdminUsername", "AdminPassword") and row[1] not in (None, ""):
                    creds[row[0]] = str(row[1]).strip()
            if creds.get("AdminUsername") and creds.get("AdminPassword"):
                return creds["AdminUsername"], creds["AdminPassword"]
        finally:
            wb.close()
    except Exception:
        pass
    return None


def _user_links(links):
    """Per-user quick links, with any admin-defined links removed so they
    never appear twice (admin links are always shown separately)."""
    admin_targets = {l.get("target") for l in get_admin_links()}
    return [l for l in (links or []) if l.get("target") not in admin_targets]


def _local_admin_links():
    """Admin quick links that need NO network: the admin_links.json shipped
    next to the exe, else the embedded defaults. Used to seed the memo so
    the Navigator's first paint never waits on the share; the shared copy
    is read in a background thread right after (see
    Navigator._start_admin_links_refresh)."""
    return _read_links_json(_admin_links_file()) or ADMIN_LINKS


def _link_signature(links):
    """Comparable fingerprint of a link set - lets the background shared
    read tell "same links, different list object" from a real change, so
    an unchanged set never repaints the footer."""
    return [(l.get("name"), l.get("type"), l.get("target"),
             l.get("icon"), l.get("color")) for l in (links or [])]


def ensure_data():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(SETTINGS_FILE):
        save_settings({"favorites": [], "recent": [], "links": []})

def load_settings():
    ensure_data()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["links"] = _user_links(data.get("links"))
        return data
    except Exception:
        return {"favorites": [], "recent": [], "links": []}

def save_settings(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, SETTINGS_FILE)

def normalize_path(path):
    """Tidy a path before handing it to the OS: strip stray quotes/whitespace
    (including newlines from pasted Explorer address bars), unify slashes,
    and collapse doubled backslashes -- keeps UNC quick links working."""
    if not path:
        return path
    path = path.strip().strip('"').strip("'")
    is_unc = path.startswith("\\\\") or path.startswith("//")
    path = path.replace("/", "\\")
    if is_unc:
        rest = path.lstrip("\\")
        rest = re.sub(r"\\{2,}", r"\\", rest)
        path = "\\\\" + rest
    else:
        path = re.sub(r"\\{2,}", r"\\", path)
    if len(path) > 3 and path.endswith("\\"):
        path = path.rstrip("\\")
    return path


def open_target(target, record=True):
    t = normalize_path(target)
    if not t:
        return
    # Links are stored with an absolute share path ('\\EgnyteDrive\idsinc\...')
    # in the bundled defaults, the shared admin_links.json and local settings.
    # A PC that mounts the share as 'idsinc (2)' cannot open those verbatim,
    # so swap in whichever alias is actually present here.
    t = pathutils.remap_share_path(t) if pathutils else t
    if record:  # callers that log a more specific action pass False
        _record("action:open_link")
    try:
        os.startfile(t)
    except Exception as e:
        messagebox.showerror(APP_NAME, "Could not open:\n{}\n\n{}".format(t, e))


FILE_EXTS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
             ".txt", ".dwg", ".zip", ".exe", ".msg", ".eml")

def detect_link_type(target):
    """Figure out the link type from its target instead of asking the user."""
    raw = (target or "").strip()
    if raw.lower().startswith(("http://", "https://")):
        return "web"
    t = normalize_path(target)
    if os.path.splitext(t)[1].lower() in FILE_EXTS:
        return "file"
    try:
        if os.path.isfile(t):
            return "file"
    except OSError:
        pass
    return "folder"


def parse_drop_paths(data):
    """Split Explorer's drag-drop payload into raw paths. Explorer wraps paths
    containing spaces in {braces}; a drop may carry several items."""
    paths = []
    i, n = 0, len(data)
    while i < n:
        if data[i] == "{":
            j = data.find("}", i)
            if j == -1:
                break
            paths.append(data[i + 1:j])
            i = j + 1
        elif data[i] in " \t":
            i += 1
        else:
            j = i
            while j < n and data[j] not in " \t":
                j += 1
            paths.append(data[i:j])
            i = j
    return [p for p in paths if p]


def to_unc(path):
    """Resolve a dropped path to its UNC form: drive letters (mapped drives)
    become \\\\server\\share via PowerShell, UNC paths pass through."""
    p = (path or "").strip().strip("{}").strip().replace("/", "\\")
    if not p:
        return ""
    if p.startswith("\\\\"):
        return normalize_path(p)
    m = re.match(r"^([A-Za-z]):(.*)$", p)
    if not m:
        return p
    drive, rest = m.group(1).upper(), m.group(2)
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "(Get-PSDrive {}).DisplayRoot".format(drive)],
            stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        out = ""
    if out:
        return out.rstrip("\\") + rest
    return p

class Navigator(tk.Frame):
    def __init__(self, master=None, **kwargs):
        super().__init__(master, **kwargs)
        # v2.6.39: paint from local data only. Seeding the admin-links memo
        # with the admin_links.json shipped next to the exe (or the embedded
        # defaults) keeps the whole first paint - load_settings(),
        # get_admin_links(), the Latest panel - off the network share. The
        # shared copy is read in a daemon thread below and adopted only if
        # it differs (see _start_admin_links_refresh).
        if _ADMIN_LINKS_CACHE["links"] is None:
            _ADMIN_LINKS_CACHE["links"] = _local_admin_links()
            _ADMIN_LINKS_CACHE["at"] = time.monotonic()
        self.settings = load_settings()
        self.jobs = []
        self.current_job = None
        self.filtered_jobs = []
        self._folder_cache = load_section_cache()
        self._cache_lock = threading.Lock()
        self._collapsed = {"MANAGE LINKS"}
        self._hover_menus = []
        self._job_token = 0  # guards async renders against rapid re-clicks
        self._select_after_id = None  # debounce for arrow-key scrolling
        # Job-list loading state. The JOBS walk is a network read (~0.3 s
        # for 182 folders here), so it runs in a daemon thread and lands
        # via after() - the shell, sidebar and Quick Links are visible and
        # clickable the moment this constructor returns.
        self._jobs_token = 0
        self._jobs_ready = False
        self._jobs_scanning = False
        self._jobs_notice = False
        self._build_style()
        self._build_ui()
        self._start_jobs_scan()
        self.refresh_favorites()
        self._prewarm()
        self._start_admin_links_refresh()

    def _build_style(self):
        # NOTE: ttk styles (and especially theme_use) are application-global.
        # This tab must NEVER call theme_use() or restyle stock selectors
        # ("Treeview", "TButton", ...) - doing so repainted the whole DEA
        # window in clam's gray/brown. Every selector below is Nav-prefixed
        # so only widgets inside this tab are affected; DEA keeps its
        # initial native look.
        style = ttk.Style(self)
        style.configure("App.TFrame", background="#f5f6f8")
        style.configure("Sidebar.TFrame", background="#20252b")
        style.configure("Sidebar.TLabel", background="#20252b", foreground="#e8edf2")
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"), background="#f5f6f8", foreground="#20252b")
        style.configure("Sub.TLabel", font=("Segoe UI", 9), background="#f5f6f8", foreground="#68727d")

        border = dict(borderwidth=1, relief="solid", bordercolor="#c2c8cf",
                      lightcolor="#c2c8cf", darkcolor="#c2c8cf")
        style.configure("Card.TButton", font=("Segoe UI", 10), padding=(12, 9),
                        background="#ffffff", foreground="#20252b", **border)
        style.map("Card.TButton",
                  background=[("active", "#eef2f6"), ("pressed", "#dfe5ea")],
                  bordercolor=[("active", "#b0b8c2")])
        style.configure("Card.TMenubutton", font=("Segoe UI", 10), padding=(12, 9),
                        background="#ffffff", foreground="#20252b", **border)
        style.map("Card.TMenubutton",
                  background=[("active", "#eef2f6"), ("pressed", "#dfe5ea")],
                  bordercolor=[("active", "#b0b8c2")])
        style.configure("Link.TButton", font=("Segoe UI", 10), padding=(12, 9))
        style.configure("Toggle.TButton", font=("Segoe UI", 9), padding=(4, 2),
                        borderwidth=0, relief="flat", background="#f5f6f8")
        style.map("Toggle.TButton", background=[("active", "#e6e8ec")])
        style.configure("Nav.Treeview", rowheight=28, font=("Segoe UI", 9),
                        background="#ffffff", fieldbackground="#ffffff")
        style.configure("Nav.Treeview.Heading", font=("Segoe UI", 9, "bold"))

    def _build_ui(self):
        self.configure(bg="#f5f6f8")
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self, style="Sidebar.TFrame", padding=(14, 16))
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.configure(width=265)
        # The children are packed, so pack propagation (not grid) is what
        # dictates the frame's requested width - without this the sidebar
        # always draws at its content width (~162 px) and every configure
        # (width=...) call is silently ignored.
        sidebar.pack_propagate(False)
        sidebar.grid_propagate(False)
        self._sidebar = sidebar
        self._sidebar_manual = False
        self._grip_start_x = 0
        self._grip_start_w = 265
        self._drag_width = 265
        self._drag_guide = None
        self._grip_active = False
        self._fav_grip_active = False
        self._fav_start_rows = FAV_DEFAULT_ROWS
        self._fav_rows_target = FAV_DEFAULT_ROWS
        self._fav_row_px = 19.0
        self._fav_guide_y0 = 300
        try:
            _saved = int((self.settings or {}).get("sidebar_width") or 0)
        except (TypeError, ValueError):
            _saved = 0
        if SIDEBAR_MIN_W <= _saved <= SIDEBAR_MAX_W:
            sidebar.configure(width=_saved)
            self._sidebar_manual = True
            self._sidebar_pref = _saved
        else:
            self._sidebar_pref = None
        grip = tk.Frame(self, bg=GRIP_BG, cursor="sb_h_double_arrow", width=8)
        grip.grid(row=0, column=1, sticky="ns")
        grip.grid_propagate(False)
        grip.bind("<Button-1>", self._sidebar_grip_press)
        grip.bind("<B1-Motion>", self._sidebar_grip_drag)
        grip.bind("<ButtonRelease-1>", self._sidebar_grip_release)
        grip.bind("<Double-Button-1>", self._sidebar_grip_reset)
        grip.bind("<Enter>", lambda _e: grip.configure(bg=GRIP_HOVER))
        grip.bind("<Leave>", lambda _e: grip.configure(bg=GRIP_BG))
        self._sidebar_grip = grip
        # Safety net: the grip takes a local grab, so a release anywhere
        # inside the app still ends the drag; Escape cancels it. Both are
        # no-ops unless a drag is actually in progress.
        top = self.winfo_toplevel()
        top.bind("<ButtonRelease-1>", self._sidebar_grip_release, add="+")
        top.bind("<ButtonRelease-1>", self._fav_grip_release, add="+")
        top.bind("<Escape>", self._cancel_grip_drags, add="+")
        top.bind("<Configure>", self._clamp_sidebar_to_window, add="+")

        ttk.Label(sidebar, text="NAVITOOL 2.0", style="Sidebar.TLabel",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 18))

        ttk.Label(sidebar, text="FAVORITES", style="Sidebar.TLabel",
                  font=("Segoe UI", 8, "bold")).pack(anchor="w")
        fav_frame = tk.Frame(sidebar, bg="#20252b")
        fav_frame.pack(fill="x", pady=(6, 10))
        self.fav_list = tk.Listbox(fav_frame, bg="#20252b", fg="#e8edf2",
                                   selectbackground="#3d79b9", selectforeground="white",
                                   relief="flat", highlightthickness=0,
                                   font=("Segoe UI", 9), activestyle="none",
                                   height=10, exportselection=False)
        fav_scroll = tk.Scrollbar(fav_frame, orient="vertical", command=self.fav_list.yview,
                                  bg="#2b3138", troughcolor="#20252b",
                                  activebackground="#3d79b9", relief="flat",
                                  borderwidth=0, width=12, highlightthickness=0)
        self.fav_list.configure(yscrollcommand=fav_scroll.set)
        self.fav_list.pack(side="left", fill="x", expand=True)
        fav_scroll.pack(side="right", fill="y")
        self.fav_list.bind("<<ListboxSelect>>", self._on_favorite_select)
        self.fav_list.bind("<Double-Button-1>", lambda e: self._favorite_open_folder())
        self.fav_list.bind("<Button-3>", self._favorite_context_menu)
        try:
            _fav_rows = int((self.settings or {}).get("favorites_height") or 0)
        except (TypeError, ValueError):
            _fav_rows = 0
        if FAV_MIN_ROWS <= _fav_rows <= FAV_MAX_ROWS:
            self.fav_list.configure(height=_fav_rows)

        fav_grip = tk.Frame(sidebar, bg="#2b3138", cursor="sb_v_double_arrow", height=7)
        fav_grip.pack(fill="x", pady=(0, 8))
        fav_grip.pack_propagate(False)
        fav_grip.bind("<Button-1>", self._fav_grip_press)
        fav_grip.bind("<B1-Motion>", self._fav_grip_drag)
        fav_grip.bind("<ButtonRelease-1>", self._fav_grip_release)
        fav_grip.bind("<Double-Button-1>", self._fav_grip_reset)
        fav_grip.bind("<Enter>", lambda _e: fav_grip.configure(bg=GRIP_HOVER))
        fav_grip.bind("<Leave>", lambda _e: fav_grip.configure(bg="#2b3138"))
        self._fav_grip = fav_grip

        ttk.Label(sidebar, text="JOBS", style="Sidebar.TLabel",
                  font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.job_search = ttk.Entry(sidebar)
        self.job_search.pack(fill="x", pady=(6, 10))
        self.job_search.insert(0, "Search jobs...")
        self.job_search.configure(foreground="#7a828a")
        self.job_search.bind("<FocusIn>", self._search_focus_in)
        self.job_search.bind("<FocusOut>", self._search_focus_out)
        self.job_search.bind("<KeyRelease>", lambda e: self.filter_jobs())

        self.job_list = tk.Listbox(sidebar, bg="#20252b", fg="#e8edf2",
                                   selectbackground="#3d79b9", selectforeground="white",
                                   relief="flat", highlightthickness=0,
                                   font=("Segoe UI", 9), activestyle="none",
                                   exportselection=False)
        self.job_list.pack(fill="both", expand=True)
        self.job_list.bind("<<ListboxSelect>>", self.select_job)
        self.job_list.bind("<Double-Button-1>", lambda e: self.open_current_job())
        self.job_list.bind("<Button-3>", self._job_context_menu)

        ttk.Button(sidebar, text="\u21bb Refresh Jobs", command=lambda: self.refresh_jobs(record=True)).pack(fill="x", pady=(10, 5))

        main = ttk.Frame(self, style="App.TFrame", padding=(22, 18))
        main.grid(row=0, column=2, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(4, weight=1)

        top = ttk.Frame(main, style="App.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        self.title_var = tk.StringVar(value="Select a job")
        ttk.Label(top, textvariable=self.title_var, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.path_var = tk.StringVar(value=job_root())
        self._path_full = job_root()
        self.path_label = ttk.Label(top, textvariable=self.path_var, style="Sub.TLabel")
        self.path_label.grid(row=1, column=0, sticky="w", pady=(3, 0))
        # A full job path is far wider than the content column; letting the
        # label ask for its natural width inflates the whole right side and
        # pushes the window's requested size past the screen. Elide it to
        # the column instead.
        top.bind("<Configure>", self._fit_path_label, add="+")

        actions = ttk.Frame(main, style="App.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 4))
        ttk.Button(actions, text="Open Job", command=self.open_current_job).pack(side="left")
        ttk.Button(actions, text="Add to Favorites", command=self.add_favorite).pack(side="left", padx=6)
        # Per-user item filter (v2.6.39): tick the folder items you actually
        # use and the rest disappear from the job pages. Empty = show all,
        # so nothing changes for anyone who never opens it.
        ttk.Button(actions, text="Show Items\u2026",
                   command=self._open_item_filter).pack(side="left")

        self.status_var = tk.StringVar(value="")
        status = ttk.Label(main, textvariable=self.status_var, style="Sub.TLabel")
        status.grid(row=3, column=0, sticky="w", pady=(0, 4))

        def _sync_status_row(*_args):
            # The status line only takes up space while it has something to
            # say - an empty message collapses the row entirely.
            if self.status_var.get().strip():
                status.grid()
            else:
                status.grid_remove()

        self.status_var.trace_add("write", _sync_status_row)
        _sync_status_row()

        # Job-folders loading row: shown only while a background section
        # build runs (cache misses) - phase text, indeterminate bar (a
        # determinate total would cost a full pre-walk just for counting),
        # and a Cancel button. Mirrors the Latest Details progress row.
        prog = ttk.Frame(main, style="App.TFrame")
        prog.grid(row=2, column=0, sticky="ew", pady=(0, 4))
        self._folders_prog_label = ttk.Label(prog, text="", style="Sub.TLabel",
                                             font=("Segoe UI", 8))
        self._folders_prog_label.pack(side="left")
        self._folders_cancel_btn = ttk.Button(prog, text="Cancel",
                                              command=self._cancel_folders_build)
        self._folders_prog_bar = ttk.Progressbar(prog, mode="indeterminate",
                                                 length=180)
        self._folders_prog_bar.pack(side="right", padx=(6, 0))
        self._folders_prog = prog
        self._folders_cancel = None
        self._set_folders_progress_visible(False)

        # Fixed tab strip + one scroll region per page: the Job Folders /
        # Latest Details tabs never scroll away; each page scrolls its own
        # content (exactly one canvas per scrolling page, so the mouse
        # wheel never fights nested scrollers). The Latest page holds only
        # the panel, which freezes its own header and family tabs above
        # its rows canvas (see _mount_latest_panel). Below the tabs sits
        # the fixed Quick Links footer (launch buttons + MANAGE LINKS
        # editor) - outside every scroll region, so always visible.
        content_wrap = ttk.Frame(main, style="App.TFrame")
        content_wrap.grid(row=4, column=0, sticky="nsew")
        content_wrap.grid_columnconfigure(0, weight=1)
        content_wrap.grid_rowconfigure(0, weight=1)
        self._sub_nb = ttk.Notebook(content_wrap)
        self._sub_nb.grid(row=0, column=0, sticky="nsew")
        self._page_frames = {}
        self._page_canvas = {}
        self._page_inner = {}
        self._scroll_map = {}
        for _pname, _plabel in (("folders", "Job Folders"),
                                ("latest", "Latest Details")):
            _pg = ttk.Frame(self._sub_nb, style="App.TFrame")
            self._sub_nb.add(_pg, text=_plabel)
            self._page_frames[_pname] = _pg
            if _pname == "latest":
                self._page_latest = _pg
                continue
            _pg.grid_columnconfigure(0, weight=1)
            _pg.grid_rowconfigure(0, weight=1)
            _cv = tk.Canvas(_pg, background="#f5f6f8", highlightthickness=0)
            _vsb = ttk.Scrollbar(_pg, orient="vertical", command=_cv.yview)
            _inner = ttk.Frame(_cv, style="App.TFrame")
            _cv.create_window((0, 0), window=_inner, anchor="nw")
            _cv.configure(yscrollcommand=_vsb.set)
            _cv.grid(row=0, column=0, sticky="nsew")
            _vsb.grid(row=0, column=1, sticky="ns")
            for _col in range(3):
                _inner.grid_columnconfigure(_col, weight=1, uniform="btn")
            _inner.bind("<Configure>",
                        lambda e, c=_cv: c.configure(scrollregion=c.bbox("all")))
            _cv.bind("<Configure>", lambda e, c=_cv: self._fit_canvas_width(c))
            self._page_canvas[_pname] = _cv
            self._page_inner[_pname] = _inner
            self._scroll_map[_inner] = _cv
        self._quick_footer = ttk.Frame(main, style="App.TFrame")
        self._quick_footer.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        for _col in range(3):
            self._quick_footer.grid_columnconfigure(_col, weight=1, uniform="btn")
        self._quick_footer_built = False
        self._latest_panel = None
        self._links_tree = None
        self._links_notice = ""
        self._link_images = []
        self.bind_all("<MouseWheel>", self._scroll_content_wheel, add="+")

        # The job list arrives from a background scan, so the first thing
        # painted is the shell plus this notice - never a blank page.
        self._show_placeholder("Loading job folders\u2026")
        self._fit_sidebar_width()

    def _fit_path_label(self, event=None):
        """Elide the job path from the middle so it never asks for more
        width than the content column has (keeps the drive/share head and
        the job folder tail, which is the part people read)."""
        full = getattr(self, "_path_full", "") or ""
        if not full:
            self.path_var.set("")
            return
        try:
            avail = int(event.width if event is not None
                        else self.path_label.master.winfo_width()) - 4
        except (tk.TclError, TypeError, ValueError, AttributeError):
            return
        if avail < 80:
            avail = 80
        import tkinter.font as tkfont
        try:
            spec = ttk.Style(self).lookup("Sub.TLabel", "font") or "TkDefaultFont"
            font = tkfont.Font(root=self, font=spec)
        except tk.TclError:
            font = tkfont.nametofont("TkDefaultFont")
        text = full
        if font.measure(full) > avail:
            tail_len = max(12, min(len(full) // 3, 60))
            tail = full[-tail_len:]
            head = full[:-tail_len]
            while head and font.measure(head + "\u2026" + tail) > avail:
                head = head[:-3] if len(head) > 3 else ""
            text = (head.rstrip("\\/") + "\u2026" + tail) if head else "\u2026" + tail
            # Last resort: drop leading characters (keeping the ellipsis)
            # until it fits. Every pass removes one REAL character, so this
            # always terminates - the old version re-prefixed the ellipsis
            # it had just stripped and spun forever at a tiny available
            # width (e.g. a withdrawn window, or a squeezed column).
            while len(text) > 1 and font.measure(text) > avail:
                text = "\u2026" + text.lstrip("\u2026").lstrip("\\/")[1:]
        if self.path_var.get() != text:
            self.path_var.set(text)

    def _fit_sidebar_width(self):
        """Size the sidebar to its content, in real pixels on this machine
        (a fixed width clips names under display scaling). Widest favorite
        / job text plus padding, clamped so one long name can't eat the
        window. Re-run when the job list changes, not on every keystroke
        of the search box (stability over twitchiness). Yields entirely
        once the user has dragged the grip (double-click the grip to go
        back to auto-fit)."""
        if getattr(self, "_sidebar_manual", False):
            return
        try:
            import tkinter.font as tkfont
            font = tkfont.Font(root=self, family="Segoe UI", size=9)
            texts = list(self.job_list.get(0, "end")) + \
                list(self.fav_list.get(0, "end"))
            widest = max([font.measure(t) for t in texts if t] + [0])
            width = min(max(widest + 28 + 14, 220),
                        SIDEBAR_MAX_W, self._sidebar_max_width())
            if not getattr(self, "_jobs_ready", True):
                # The background job scan hasn't landed yet: fitting to an
                # empty list would shrink the sidebar and then snap it back
                # when the names arrive. Keep the width it was built at.
                try:
                    width = max(width, int(self._sidebar.cget("width")))
                except (tk.TclError, TypeError, ValueError):
                    pass
            self._sidebar.configure(width=width)
        except Exception:
            pass

    # ------------------------- splitter plumbing -------------------------
    def _window_width(self):
        """The real window width. Deliberately NOT this frame's width: when
        the sidebar is dragged past the space available, Tk's pack/grid can
        hand this frame its inflated *requested* width (the sidebar visibly
        runs off the edge and the content gets squeezed to nothing). The
        toplevel always knows the true window size."""
        try:
            return int(self.winfo_toplevel().winfo_width())
        except tk.TclError:
            return 1000

    def _sidebar_max_width(self):
        """Widest the sidebar can get without starving the main content:
        the absolute cap, the window minus a usable content column, or 45%
        of the window - whichever is smallest. The percentage matters at
        laptop widths, where "window - 420" alone would still let the
        sidebar take over half the screen."""
        win = self._window_width()
        return max(SIDEBAR_MIN_W,
                   min(SIDEBAR_MAX_W, win - MAIN_MIN_W, int(win * 0.45)))

    # While a grip is dragged only a thin guide line moves - no widget
    # resizes, so nothing re-lays out and there is nothing to lag. The new
    # size is applied once, on release, clamped to the real window width.
    def _guide(self):
        if self._drag_guide is None:
            self._drag_guide = tk.Frame(self, bg=GRIP_HOVER, bd=0,
                                        highlightthickness=0)
        return self._drag_guide

    def _show_vguide(self, x):
        g = self._guide()
        try:
            g.configure(width=2, height=2)
            g.place(x=max(0, int(x)), y=0, relheight=1.0)
            g.lift()
        except tk.TclError:
            pass

    def _show_hguide(self, y):
        g = self._guide()
        try:
            g.configure(width=2, height=2)
            g.place(x=0, y=max(0, int(y)), relwidth=1.0)
            g.lift()
        except tk.TclError:
            pass

    def _hide_guide(self):
        if self._drag_guide is not None:
            try:
                self._drag_guide.place_forget()
            except tk.TclError:
                pass

    def _sidebar_grip_press(self, event):
        self._grip_start_x = event.x_root
        try:
            self._grip_start_w = int(self._sidebar.cget("width")) or 265
        except (tk.TclError, TypeError, ValueError):
            self._grip_start_w = 265
        self._drag_width = self._grip_start_w
        self._grip_active = True
        self._sidebar_manual = True
        try:
            self._sidebar_grip.grab_set()
        except tk.TclError:
            pass
        self._show_vguide(self._grip_start_w)
        return "break"

    def _sidebar_grip_drag(self, event):
        if not self._grip_active:
            return "break"
        if not (getattr(event, "state", 0x0100) & 0x0100):
            # Release landed outside the app (no event reached us): the
            # button is no longer down, so finish instead of staying stuck.
            return self._sidebar_grip_release()
        w = self._grip_start_w + (event.x_root - self._grip_start_x)
        self._drag_width = int(min(max(w, SIDEBAR_MIN_W),
                                   self._sidebar_max_width()))
        self._show_vguide(self._drag_width)
        return "break"

    def _sidebar_grip_release(self, _event=None):
        if not self._grip_active:
            return
        self._grip_active = False
        self._hide_guide()
        try:
            self._sidebar_grip.grab_release()
        except tk.TclError:
            pass
        try:
            self._sidebar.configure(width=self._drag_width)
        except tk.TclError:
            pass
        self._sidebar_pref = self._drag_width
        try:
            self.settings["sidebar_width"] = self._drag_width
            save_settings(self.settings)
        except Exception:
            pass
        return "break"

    def _sidebar_grip_reset(self, _event=None):
        """Double-click the grip: forget the manual width and go back to
        content-fitting."""
        self._cancel_grip_drags()
        try:
            self.settings.pop("sidebar_width", None)
            save_settings(self.settings)
        except Exception:
            pass
        self._sidebar_manual = False
        self._sidebar_pref = None
        self._fit_sidebar_width()
        return "break"

    def _clamp_sidebar_to_window(self, event=None):
        """Fit the sidebar to the window: shrinking clamps it so the main
        content never disappears, and growing gives a manual width back.
        The saved preference is left untouched either way."""
        try:
            top = self.winfo_toplevel()
        except tk.TclError:
            return  # already being torn down
        if event is not None and getattr(event, "widget", None) is not top:
            return
        if getattr(self, "_grip_active", False):
            return
        try:
            cur = int(self._sidebar.cget("width"))
        except (tk.TclError, TypeError, ValueError):
            return
        limit = self._sidebar_max_width()
        pref = getattr(self, "_sidebar_pref", None)
        target = limit if pref is None else min(pref, limit)
        if cur == target:
            return
        if cur < target and pref is None:
            return  # auto-fit mode: only ever clamped, never widened
        try:
            self._sidebar.configure(width=target)
        except tk.TclError:
            pass

    # ---------------------- favorites height grip ----------------------
    def _fav_rows(self):
        try:
            return int(self.fav_list.cget("height")) or FAV_DEFAULT_ROWS
        except (tk.TclError, TypeError, ValueError):
            return FAV_DEFAULT_ROWS

    def _fav_max_rows(self):
        """Never let the favorites box squeeze the JOBS list out of the
        sidebar at small window heights."""
        try:
            h = int(self._sidebar.winfo_height())
        except tk.TclError:
            h = 780
        chrome = 260  # title, labels, search box, refresh button, padding
        row_px = max(1.0, self._fav_row_px)
        room = (h - chrome - 6 * row_px) / row_px
        return max(FAV_MIN_ROWS, min(FAV_MAX_ROWS, int(room)))

    def _fav_grip_press(self, event):
        self._fav_grip_start_y = event.y_root
        self._fav_start_rows = self._fav_rows()
        self._fav_rows_target = self._fav_start_rows
        self._fav_grip_active = True
        rows = max(1, self._fav_start_rows)
        try:
            self._fav_row_px = max(1.0, self.fav_list.winfo_height() / rows)
            self._fav_guide_y0 = (self.fav_list.winfo_rooty() - self.winfo_rooty()
                                  + self.fav_list.winfo_height())
        except tk.TclError:
            self._fav_row_px = 19.0
            self._fav_guide_y0 = 300
        try:
            self._fav_grip.grab_set()
        except tk.TclError:
            pass
        self._show_hguide(self._fav_guide_y0)
        return "break"

    def _fav_grip_drag(self, event):
        if not self._fav_grip_active:
            return "break"
        if not (getattr(event, "state", 0x0100) & 0x0100):
            return self._fav_grip_release()
        dy = event.y_root - self._fav_grip_start_y
        rows = self._fav_start_rows + int(round(dy / max(1.0, self._fav_row_px)))
        rows = max(FAV_MIN_ROWS, min(rows, self._fav_max_rows()))
        self._fav_rows_target = rows
        y = self._fav_guide_y0 + (rows - self._fav_start_rows) * self._fav_row_px
        self._show_hguide(y)
        return "break"

    def _fav_grip_release(self, _event=None):
        if not self._fav_grip_active:
            return
        self._fav_grip_active = False
        self._hide_guide()
        try:
            self._fav_grip.grab_release()
        except tk.TclError:
            pass
        try:
            self.fav_list.configure(height=self._fav_rows_target)
        except tk.TclError:
            pass
        try:
            self.settings["favorites_height"] = self._fav_rows_target
            save_settings(self.settings)
        except Exception:
            pass
        return "break"

    def _fav_grip_reset(self, _event=None):
        self._cancel_grip_drags()
        try:
            self.settings.pop("favorites_height", None)
            save_settings(self.settings)
        except Exception:
            pass
        try:
            self.fav_list.configure(height=FAV_DEFAULT_ROWS)
        except tk.TclError:
            pass
        return "break"

    def _cancel_grip_drags(self, _event=None):
        """Escape during a drag: put everything back the way it was."""
        was_dragging = self._grip_active or self._fav_grip_active
        if not was_dragging:
            return
        if self._grip_active:
            self._grip_active = False
            try:
                self._sidebar_grip.grab_release()
            except tk.TclError:
                pass
        if self._fav_grip_active:
            self._fav_grip_active = False
            try:
                self._fav_grip.grab_release()
            except tk.TclError:
                pass
        self._hide_guide()
        return "break"
    def _fit_canvas_width(self, canvas):
        """Keep a page canvas's inner frame as wide as the canvas so the
        3-column button grid always fills the visible width."""
        try:
            width = canvas.winfo_width()
            for item in canvas.find_all():
                canvas.itemconfigure(item, width=width)
        except tk.TclError:
            pass

    def _search_focus_in(self, _):
        if self.job_search.get() == "Search jobs...":
            self.job_search.delete(0, "end")
            self.job_search.configure(foreground="#20252b")

    def _search_focus_out(self, _):
        if not self.job_search.get():
            self.job_search.insert(0, "Search jobs...")
            self.job_search.configure(foreground="#7a828a")

    def refresh_jobs(self, record=False):
        if record:  # the Refresh Jobs button, not the first-visit scan
            _record("action:nav_refresh")
        # v2.6.39: fire-and-forget. The JOBS walk is a network read, so it
        # runs in a daemon thread and _apply_jobs paints the result; this
        # call returns immediately (the old synchronous version froze the
        # whole window for ~0.3 s on a warm share, longer on a slow day).
        #
        # NOTE: the section cache is deliberately NOT wiped here. A full
        # wipe made every post-refresh click re-scan the network share
        # (the main click-lag complaint). Only entries for jobs that no
        # longer exist are pruned; favorites/recents rebuild in the
        # background via _prewarm(force=True); and the currently open job
        # (if any) is rebuilt as soon as the scan lands - so a rename or a
        # new folder shows up right after pressing this button.
        self._start_jobs_scan(notice=bool(record))

    def _start_jobs_scan(self, notice=False):
        """Scan the JOBS root off the UI thread. `notice` asks for the
        "Refreshed HH:MM." status once it lands (manual Refresh Jobs); the
        first-visit scan stays quiet. A newer scan bumps the token, so a
        slow result can never overwrite a fresher list."""
        self._jobs_token += 1
        token = self._jobs_token
        self._jobs_scanning = True
        self._jobs_notice = bool(notice)
        if notice:
            self.status_var.set("Scanning job folders\u2026")
        elif not self._jobs_ready:
            self.status_var.set("Loading job folders\u2026")

        def work():
            try:
                names = _scan_job_dirs()
                err = None
            except Exception as e:  # OSError, or a share that vanished
                names = []
                err = e
            try:
                self.after(0, lambda: self._apply_jobs(token, names, err))
            except Exception:
                pass  # tab torn down while the scan was running

        threading.Thread(target=work, daemon=True).start()

    def _apply_jobs(self, token, names, err=None):
        """Paint a finished job scan (UI thread). Stale tokens are dropped
        so only the newest scan wins."""
        if token != self._jobs_token:
            return
        self._jobs_scanning = False
        self._jobs_ready = True
        notice = self._jobs_notice
        self._jobs_notice = False
        if err is not None:
            self.jobs = []
            self.filter_jobs()
            self._show_placeholder("Cannot access JOBS directory.\n\n{}\n\n{}"
                                   .format(job_root(), err))
            self.status_var.set("")
            return
        self.jobs = list(names)
        alive = set(self.jobs)
        with self._cache_lock:
            stale = [k for k in self._folder_cache if k not in alive]
            for k in stale:
                del self._folder_cache[k]
            if stale:
                save_section_cache(self._folder_cache)
        self.filter_jobs()
        self._fit_sidebar_width()
        self._prewarm(force=True)
        if not self.current_job:
            self._show_placeholder()
        elif self.current_job in self.jobs:
            # Rebuild the open job so a rename/new folder shows up at once.
            with self._cache_lock:
                self._folder_cache.pop(self.current_job, None)
            self._show_job_async()
        else:
            self.current_job = None
            self.title_var.set("Select a job")
            self._path_full = job_root()
            self._fit_path_label()
            self._show_placeholder("That job folder no longer exists.\n\n"
                                   "Select another job from the left.")
        if notice:
            try:
                import datetime as _dt
                self.status_var.set("Refreshed %s." % _dt.datetime.now().strftime("%H:%M"))
            except Exception:
                pass
        else:
            self.status_var.set("")

    # ---------- shared admin links (background) ----------

    def _start_admin_links_refresh(self):
        """Read the shared admin_links.json off the network in a background
        thread, then adopt it if it differs from the local set already on
        screen. The first paint uses the local/embedded set, so a normal
        launch never waits for this."""
        def work():
            try:
                links = _read_links_json(_shared_admin_links_file())
            except Exception:
                links = None
            if not links:
                return  # keep what is already shown
            try:
                self.after(0, lambda: self._apply_admin_links(links))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _apply_admin_links(self, links):
        """Adopt the shared admin link set (UI thread). No-op when it
        matches what is already shown - the common case, so a normal
        launch paints the footer exactly once."""
        if not links:
            return
        same = _link_signature(links) == _link_signature(_ADMIN_LINKS_CACHE["links"])
        _ADMIN_LINKS_CACHE["links"] = links
        _ADMIN_LINKS_CACHE["at"] = time.monotonic()
        if same:
            return
        # Admin links always render separately from per-user links; re-run
        # the de-dupe now that the real shared set is known, so a personal
        # link pointing at the same target can't appear twice.
        try:
            self.settings["links"] = _user_links(self.settings.get("links"))
        except Exception:
            pass
        try:
            self._refresh_quick_links()
        except tk.TclError:
            pass

    def filter_jobs(self):
        q = self.job_search.get().strip().lower()
        if q == "search jobs...":
            q = ""
        self.filtered_jobs = [j for j in self.jobs if q in j.lower()]
        self.job_list.delete(0, "end")
        for job in self.filtered_jobs:
            self.job_list.insert("end", job)

    def select_job(self, _=None):
        # Debounced: arrow-key scrolling fires <<ListboxSelect>> on every
        # step, and each step used to trigger a full synchronous network
        # scan. Wait briefly so only the settled-on job actually renders.
        if self._select_after_id is not None:
            try:
                self.after_cancel(self._select_after_id)
            except tk.TclError:
                pass
            self._select_after_id = None

        def fire():
            self._select_after_id = None
            sel = self.job_list.curselection()
            if not sel:
                return
            self._open_job(self.filtered_jobs[sel[0]])

        self._select_after_id = self.after(80, fire)

    def _open_job(self, name):
        self.current_job = name
        self.title_var.set(name)
        self._path_full = os.path.join(job_root(), name)
        self._fit_path_label()
        self._show_job_async()
        self._add_recent(name)
        self.status_var.set("")
        if name in self.filtered_jobs:
            idx = self.filtered_jobs.index(name)
            self.job_list.selection_clear(0, "end")
            self.job_list.selection_set(idx)
            self.job_list.see(idx)

    def _clear_content(self):
        for inner in self._page_inner.values():
            for w in inner.winfo_children():
                w.destroy()
        for w in self._page_frames["latest"].winfo_children():
            w.destroy()
        self._latest_panel = None
        for canvas in list(self._page_canvas.values()):
            try:
                canvas.yview_moveto(0.0)
            except (tk.TclError, AttributeError):
                pass

    def _scroll_content_wheel(self, event):
        """Mouse-wheel scrolling for the page canvases. Bound app-wide
        (bind_all) but only acts when the pointer is actually over one of
        this tab's scroll regions (a page inner or the Latest panel's
        rows), so it never hijacks scrolling in DEA's other tabs
        or dialogs."""
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except tk.TclError:
            return
        node = widget
        try:
            target = None
            while node is not None:
                if node in self._scroll_map:
                    target = self._scroll_map[node]
                    break
                node = node.master
        except tk.TclError:
            return
        if target is None:
            return
        try:
            target.yview_scroll(-1 * (event.delta // 120), "units")
        except tk.TclError:
            pass

    def _show_placeholder(self, text="Select a job from the left."):
        self._clear_content()
        page_folders = self._page_inner["folders"]
        page_latest = self._page_frames["latest"]
        ttk.Label(page_folders, text=text, style="Sub.TLabel",
                  font=("Segoe UI", 11)).grid(row=0, column=0, columnspan=3, pady=(30, 10))
        # No job selected: the folders page is just the placeholder, the
        # Quick Links footer is global (ensured once), and the Latest page
        # explains itself (the panel guides job selection).
        self._ensure_quick_footer()
        self._mount_latest_panel(page_latest)

    # ---------- main content ----------

    def _get_sections(self, name):
        """Return built job sections, using the in-memory/disk cache when
        available and persisting newly built ones to disk."""
        with self._cache_lock:
            if name in self._folder_cache:
                return self._folder_cache[name]
        try:
            sections = build_job_sections(name)
        except Exception:
            return []
        with self._cache_lock:
            self._folder_cache[name] = sections
            save_section_cache(self._folder_cache)
        return sections

    def _prewarm(self, force=False):
        """Pre-build sections for favorites AND recently opened jobs in a
        background thread so they are already cached when the user clicks
        them. With force=True (Refresh Jobs) existing cache is rebuilt so
        data stays current."""
        targets = []
        seen = set()
        for n in list(self.settings.get("favorites", [])) + list(self.settings.get("recent", [])):
            if n and n not in seen:
                seen.add(n)
                with self._cache_lock:
                    if force or n not in self._folder_cache:
                        targets.append(n)
        if not targets:
            return

        def work():
            for name in targets:
                base = os.path.join(job_root(), name)
                if not os.path.isdir(base):
                    continue
                try:
                    sections = build_job_sections(name)
                except Exception:
                    continue
                with self._cache_lock:
                    self._folder_cache[name] = sections
                    save_section_cache(self._folder_cache)

        threading.Thread(target=work, daemon=True).start()

    def _toggle_section(self, key, header, frame, label):
        """Collapse/expand a section. `key` tracks the state in _collapsed;
        `label` is the text shown next to the arrow ("" for the untitled
        stage groups, "QUICK LINKS" for the links block)."""
        suffix = "  " + label if label else ""
        if frame.winfo_ismapped():
            frame.grid_remove()
            header.configure(text="\u25B8" + suffix)
            self._collapsed.add(key)
        else:
            frame.grid()
            header.configure(text="\u25BE" + suffix)
            self._collapsed.discard(key)

    def _show_job(self):
        """Synchronous render from cache (or a fast local build). Used by
        the quick-link editors, which only need to repaint the links."""
        self._clear_content()
        if not self.current_job:
            self._show_placeholder()
            return
        self._render_sections(self._get_sections(self.current_job))

    def _set_folders_progress_visible(self, visible):
        try:
            if visible:
                self._folders_prog.grid()
                self._folders_cancel_btn.pack(side="right")
                self._folders_prog_bar.pack(side="right", padx=(6, 0))
                try:
                    self._folders_prog_bar.start(50)
                except tk.TclError:
                    pass
                self._folders_prog_label.config(text="Starting…")
            else:
                try:
                    self._folders_prog_bar.stop()
                except tk.TclError:
                    pass
                self._folders_prog.grid_remove()
        except tk.TclError:
            pass

    def _update_folders_progress(self, token, text):
        if token != self._job_token:
            return
        try:
            self._folders_prog_label.config(text=text)
        except tk.TclError:
            pass

    def _cancel_folders_build(self):
        if self._folders_cancel is not None:
            try:
                self._folders_cancel.set()
            except Exception:
                pass

    def _show_job_async(self):
        """Click path: paint instantly, never block the UI on the network.

        - Cache hit  -> render immediately (no thread, no flicker).
        - Cache miss -> show a "Loading..." placeholder at once, build the
          sections in a background thread with a progress row (cancellable),
          then paint via after(). A token guard drops stale results when
          the user clicks another job before the build finishes."""
        self._clear_content()
        if not self.current_job:
            self._show_placeholder()
            return
        with self._cache_lock:
            cached = self._folder_cache.get(self.current_job)
        if cached is not None:
            self._render_sections(cached)
            return
        self._job_token += 1
        token = self._job_token
        name = self.current_job
        if self._folders_cancel is not None:
            try:
                self._folders_cancel.set()
            except Exception:
                pass
        cancel = threading.Event()
        self._folders_cancel = cancel
        self._clear_content()
        ttk.Label(self._page_inner["folders"], text="Loading '{}'...".format(name),
                  style="Sub.TLabel", font=("Segoe UI", 11)).grid(
                      row=0, column=0, columnspan=3, pady=(30, 10))
        self._set_folders_progress_visible(True)

        def on_progress(text):
            try:
                self.after(0, lambda: self._update_folders_progress(token, text))
            except Exception:
                pass

        def work():
            try:
                sections = build_job_sections(name, progress=on_progress,
                                              cancel=cancel.is_set)
            except Exception:
                sections = []
            try:
                self.after(0, lambda: self._finish_folders(token, name, sections))
            except Exception:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _finish_folders(self, token, name, sections):
        if token != self._job_token or self.current_job != name:
            return  # user moved on; drop this stale result
        self._set_folders_progress_visible(False)
        if sections is None:
            # Cancelled - keep the placeholder, note how to retry.
            self.status_var.set("Loading cancelled - click the job again to retry.")
            return
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        with self._cache_lock:
            self._folder_cache[name] = sections
            save_section_cache(self._folder_cache)
        self._clear_content()
        self._render_sections(sections)

    def _mount_latest_panel(self, page):
        """Latest Details panel filling the Latest page (fixed header +
        family tabs above its own rows canvas - the page itself does not
        scroll). Lazy import avoids a circular import (that module imports
        JOB_ROOT etc. from here). Recreated per render; instant cache
        paint keeps it free, and its token guard drops stale background
        results."""
        from client.latest_details_tab import LatestDetailsTab
        self._latest_panel = LatestDetailsTab(page, lambda: self.current_job,
                                              embedded=True)
        self._latest_panel.pack(fill="both", expand=True)
        rows_canvas = getattr(self._latest_panel, "_rows_canvas", None)
        self._scroll_map = {k: v for k, v in self._scroll_map.items()
                            if k in self._page_inner.values()}
        if rows_canvas is not None:
            try:
                rows_inner = self._latest_panel.body
                self._scroll_map[rows_inner] = rows_canvas
            except AttributeError:
                pass
        self._latest_panel.refresh()

    def _visible_item_labels(self):
        """The per-user item filter: the labels ticked in "Show Items...".
        Empty/missing means show everything, so a fresh install - and
        everyone who never opens the dialog - is completely unaffected."""
        items = self.settings.get("visible_items") or []
        if isinstance(items, str):
            items = [items]
        return {str(i).strip() for i in items if str(i).strip()}

    def _filtered_sections(self, sections):
        """Drop unticked items (v2.6.39) and any section left with nothing.
        An untitled group is the fallback "Job folder" entry for a job with
        no recognised stage folders - it is never filtered, because it is
        the only way into such a job."""
        visible = self._visible_item_labels()
        if not visible:
            return list(sections)
        out = []
        for title, items in sections:
            if title:
                items = [it for it in items if it.get("label") in visible]
                if not items:
                    continue
            out.append((title, items))
        return out

    def _item_filter_labels(self):
        """Labels the "Show Items..." dialog offers: whatever the open
        job's built sections contain (that is what the user is looking at),
        plus anything already ticked so a job that lacks one of their items
        can never silently drop that choice."""
        labels = []
        with self._cache_lock:
            sections = self._folder_cache.get(self.current_job) if self.current_job else None
        for _title, items in (sections or []):
            for it in items:
                if it.get("label") and it["label"] not in labels:
                    labels.append(it["label"])
        for lab in sorted(self._visible_item_labels()):
            if lab not in labels:
                labels.append(lab)
        return labels

    def _open_item_filter(self):
        """Checklist of the items the current job offers. Ticking a subset
        hides the rest from the job pages for THIS Windows user only
        (settings.json); "Show all items" is the one-click way back."""
        labels = self._item_filter_labels()
        if not labels:
            messagebox.showinfo(
                "Show Items",
                "Open a job first - this list shows the items that job offers.")
            return
        current = self._visible_item_labels()
        win = tk.Toplevel(self)
        win.title("Show Items")
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)
        body = ttk.Frame(win, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Tick the items you use. Unticked items are hidden "
                             "from the job folders page; nothing is deleted.",
                  style="Sub.TLabel", wraplength=340, justify="left").pack(
                      anchor="w", pady=(0, 10))
        vars_ = {}
        for lab in labels:
            var = tk.BooleanVar(value=(not current) or lab in current)
            vars_[lab] = var
            ttk.Checkbutton(body, text=lab, variable=var).pack(anchor="w")

        def save():
            chosen = [lab for lab in labels if vars_[lab].get()]
            if len(chosen) == len(labels):
                self.settings.pop("visible_items", None)  # all = no filter
            else:
                self.settings["visible_items"] = chosen
            try:
                save_settings(self.settings)
            except Exception:
                pass
            win.destroy()
            self._rerender_current()

        def show_all():
            self.settings.pop("visible_items", None)
            try:
                save_settings(self.settings)
            except Exception:
                pass
            win.destroy()
            self._rerender_current()

        btns = ttk.Frame(body)
        btns.pack(fill="x", pady=(12, 0))
        ttk.Button(btns, text="Show all items", command=show_all).pack(side="left")
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Save", command=save).pack(side="right", padx=(0, 6))
        try:
            win.grab_set()
        except tk.TclError:
            pass

    def _rerender_current(self):
        """Repaint after the item filter changed - cached sections only, so
        this never touches the network."""
        if not self.current_job:
            self._show_placeholder()
            return
        with self._cache_lock:
            cached = self._folder_cache.get(self.current_job)
        if cached is None:
            self._show_job_async()
            return
        self._clear_content()
        self._render_sections(cached)

    def _render_sections(self, sections):
        sections = self._filtered_sections(sections)
        width = 1
        for title, items in sections:
            for it in items:
                w = len(it["label"]) + (2 if it["kind"] == "dropdown" else 3)
                width = max(width, w)
        all_links = get_admin_links() + self.settings.get("links", [])
        for link in all_links:
            width = max(width, len(link["name"]) + 3)
        width += 2

        row = 0
        page_folders = self._page_inner["folders"]
        page_latest = self._page_frames["latest"]
        # Stage groups keep their collapsible arrow-toggle, but the toggle
        # shows ONLY the arrow - no title text. Only QUICK LINKS keeps a
        # titled header (see _render_quick_links). Each group still gets
        # its own row-block so its buttons start on a fresh row.
        for title, items in sections:
            # Plain label, not a button: a button outline can never appear,
            # and the hand cursor still says "click me". Still collapses.
            toggle = tk.Label(page_folders, text="\u25BE", font=("Segoe UI", 9),
                              bg="#f5f6f8", fg="#555555", cursor="hand2")
            toggle.grid(row=row, column=0, columnspan=3, sticky="w", padx=8,
                        pady=(2 if row == 0 else 10, 0))
            row += 1
            frame = ttk.Frame(page_folders, style="App.TFrame")
            frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=2)
            self._render_items(frame, items, width)
            toggle.bind("<Button-1>", lambda e, t=title, h=toggle, f=frame:
                        self._toggle_section(t, h, f, ""))
            if title in self._collapsed:
                frame.grid_remove()
                toggle.configure(text="\u25B8")
            row += 1

        if not sections:
            ttk.Label(page_folders,
                      text="No items are shown for this job.\n"
                           "Use \u201cShow Items\u2026\u201d above to tick the ones you use.",
                      style="Sub.TLabel", font=("Segoe UI", 10),
                      justify="center").grid(row=0, column=0, columnspan=3,
                                             pady=(30, 10))

        self._ensure_quick_footer()
        self._mount_latest_panel(page_latest)

    def _ensure_quick_footer(self):
        """Build the fixed Quick Links footer once (launch buttons +
        MANAGE LINKS editor, below the tabs and outside every scroll
        region). The footer is global, not per-job, so job switches and
        the placeholder screen only ensure it exists - repaints happen
        solely through _refresh_quick_links after a manager edit."""
        if self._quick_footer_built:
            return
        all_links = get_admin_links() + self.settings.get("links", [])
        width = max([len(l["name"]) + 3 for l in all_links] + [1]) + 2
        self._render_quick_page(width)

    def _render_quick_page(self, width):
        """Whole Quick Links block in the fixed footer: launch buttons
        plus the embedded link manager underneath."""
        self._links_tree = None
        self._link_images = []
        self._render_quick_links(self._quick_footer, width, 0)
        self._render_links_manager(self._quick_footer, 2)
        self._quick_footer_built = True

    def _refresh_quick_links(self, select=None):
        """Repaint only the fixed Quick Links footer after a manager edit
        - the Job Folders and Latest pages keep their state, and `select`
        (a tree iid) restores the edited row's selection in the rebuilt list."""
        for w in self._quick_footer.winfo_children():
            w.destroy()
        all_links = get_admin_links() + self.settings.get("links", [])
        width = max([len(l["name"]) + 3 for l in all_links] + [1]) + 2
        self._render_quick_page(width)
        if select is not None and self._links_tree is not None:
            try:
                iid = str(select)
                if iid in self._links_tree.get_children():
                    self._links_tree.selection_set(iid)
                    self._links_tree.see(iid)
            except tk.TclError:
                pass

    def _render_quick_links(self, host, width, row):
        """Quick-links card block with its own collapse toggle. Shown under a
        selected job and on the empty (no-job-selected) screen."""
        all_links = get_admin_links() + self.settings.get("links", [])
        links_toggle = tk.Label(host, text="\u25BE  QUICK LINKS",
                                font=("Segoe UI", 9, "bold"),
                                bg="#f5f6f8", fg="#20252b", cursor="hand2")
        links_toggle.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(14, 0))
        row += 1
        links_frame = ttk.Frame(host, style="App.TFrame")
        links_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=2)
        for j, link in enumerate(all_links):
            color = link.get("color")
            glyph_img = colored_glyph_image(resolve_link_icon(link), color) if color else None
            if glyph_img is not None:
                self._link_images.append(glyph_img)
                ttk.Button(links_frame, text=link["name"], image=glyph_img,
                           compound="left", style="Card.TButton", width=width,
                           command=lambda x=link["target"]: open_target(x)).grid(
                               row=j // 3, column=j % 3, sticky="ew", padx=5, pady=5)
            else:
                ttk.Button(links_frame, text="{}  {}".format(
                    resolve_link_icon(link), link["name"]),
                    style="Card.TButton", width=width,
                    command=lambda x=link["target"]: open_target(x)).grid(
                        row=j // 3, column=j % 3, sticky="ew", padx=5, pady=5)
        links_frame.grid_columnconfigure(0, weight=1, uniform="btn")
        links_frame.grid_columnconfigure(1, weight=1, uniform="btn")
        links_frame.grid_columnconfigure(2, weight=1, uniform="btn")
        links_toggle.bind("<Button-1>", lambda e, h=links_toggle, f=links_frame:
                            self._toggle_section("QUICK LINKS", h, f, "QUICK LINKS"))
        if "QUICK LINKS" in self._collapsed:
            links_frame.grid_remove()
            links_toggle.configure(text="\u25B8  QUICK LINKS")
        return row + 1

    def _fill_menu(self, menu, entries):
        """Populate a tk.Menu from nested [(label, rel-or-children), ...]
        entries to any depth: "-" is a separator, a bare rel string is an
        open-folder command, a list is a further cascade. Chunking runs
        first on full labels (split points are order-based, so shortening
        can't move them); display labels compress after, per actual menu -
        so the collision guard only ever fires on rows that truly render
        together, never on a pre-chunk level no one sees."""
        for entry in _shorten_menu_level(_chunk_menu_entries(entries)):
            if entry[0] == "-":
                menu.add_separator()
            elif isinstance(entry[1], str):
                menu.add_command(label=entry[0],
                                 command=lambda rr=entry[1]: self.open_job_folder(rr))
            else:
                sub = tk.Menu(menu, tearoff=0)
                self._fill_menu(sub, entry[1])
                menu.add_cascade(label=entry[0], menu=sub)

    def _render_items(self, frame, items, width):
        for i, it in enumerate(items):
            col = i % 3
            r = i // 3
            if it["kind"] == "dropdown":
                mb = ttk.Menubutton(frame, text="\u25BE " + it["label"],
                                    style="Card.TMenubutton", width=width)
                menu = tk.Menu(mb, tearoff=0)
                self._fill_menu(menu, it["menu"])
                mb["menu"] = menu
                mb.grid(row=r, column=col, sticky="ew", padx=5, pady=5)
            elif it["kind"] == "hover":
                self._hover_button(frame, it, width, r, col)
            else:
                btn = ttk.Button(
                    frame, text="{}  {}".format(it["icon"], it["label"]),
                    style="Card.TButton", width=width,
                    command=lambda rr=it["rel"]: self.open_job_folder(rr),
                )
                btn.grid(row=r, column=col, sticky="ew", padx=5, pady=5)
        frame.grid_columnconfigure(0, weight=1, uniform="btn")
        frame.grid_columnconfigure(1, weight=1, uniform="btn")
        frame.grid_columnconfigure(2, weight=1, uniform="btn")

    def _hover_button(self, frame, it, width, r, col):
        """Menubutton whose dropdown appears on hover; a click on the button
        itself opens its folder."""
        items = it.get("menu") or []
        if not items:
            ttk.Button(
                frame, text="{}  {}".format(it.get("icon", ""), it["label"]),
                style="Card.TButton", width=width,
                command=lambda rr=it["rel"]: self.open_job_folder(rr),
            ).grid(row=r, column=col, sticky="ew", padx=5, pady=5)
            return

        mb = ttk.Menubutton(frame, text="\u25BE " + it["label"],
                            style="Card.TMenubutton", width=width)
        menu = tk.Menu(mb, tearoff=0)
        for label, rel in _shorten_menu_level(items):
            menu.add_command(label=label,
                             command=lambda rr=rel: self.open_job_folder(rr))
        mb["menu"] = menu
        self._hover_menus.append(menu)

        def _post(_e):
            for m in self._hover_menus:
                try:
                    m.unpost()
                except tk.TclError:
                    pass
            if menu.index("end") is not None:
                menu.post(mb.winfo_rootx(), mb.winfo_rooty() + mb.winfo_height())

        def _leave(_e):
            x, y = mb.winfo_pointerxy()
            w = mb.winfo_containing(x, y)
            if w is None or not str(w).startswith(str(menu)):
                try:
                    menu.unpost()
                except tk.TclError:
                    pass

        def _click(_e):
            for m in self._hover_menus:
                try:
                    m.unpost()
                except tk.TclError:
                    pass
            self.open_job_folder(it["rel"])
            return "break"

        mb.bind("<Enter>", _post)
        mb.bind("<Leave>", _leave)
        mb.bind("<Button-1>", _click)
        mb.grid(row=r, column=col, sticky="ew", padx=5, pady=5)

    def _icon_for_type(self, typ):
        # Modern Windows (Segoe MDL2 Assets) glyphs instead of emoji.
        return default_icon_for_type(typ)

    def open_job_folder(self, rel):
        if not self.current_job:
            return
        path = os.path.join(job_root(), self.current_job, rel) if rel else os.path.join(job_root(), self.current_job)
        open_target(path)

    def open_current_job(self):
        if self.current_job:
            _record("action:nav_open_job")
            open_target(os.path.join(job_root(), self.current_job), record=False)

    def _add_recent(self, job):
        recent = self.settings.setdefault("recent", [])
        if job in recent:
            recent.remove(job)
        recent.insert(0, job)
        self.settings["recent"] = recent[:10]
        save_settings(self.settings)

    # ---------- favorites (shown directly in the sidebar) ----------

    def refresh_favorites(self):
        self.fav_list.delete(0, "end")
        favs = self.settings.get("favorites", [])
        for f in favs:
            self.fav_list.insert("end", "\u2605  {}".format(f))
        if not favs:
            self.fav_list.insert("end", "  (no favorites yet)")
        self._fit_sidebar_width()

    def _on_favorite_select(self, _=None):
        sel = self.fav_list.curselection()
        favs = self.settings.get("favorites", [])
        if not sel or sel[0] >= len(favs):
            return
        self._open_job(favs[sel[0]])

    def _favorite_open_folder(self):
        sel = self.fav_list.curselection()
        favs = self.settings.get("favorites", [])
        if not sel or sel[0] >= len(favs):
            return
        open_target(os.path.join(job_root(), favs[sel[0]]))

    def _job_context_menu(self, event):
        idx = self.job_list.nearest(event.y)
        jobs = self.filtered_jobs
        if idx < 0 or idx >= len(jobs):
            return
        name = jobs[idx]
        self.job_list.selection_clear(0, "end")
        self.job_list.selection_set(idx)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Open in Explorer",
                         command=lambda: open_target(os.path.join(job_root(), name)))
        menu.add_command(label="Open in Navigator", command=lambda: self._open_job(name))
        menu.add_separator()
        menu.add_command(label="Add to Favorites",
                         command=lambda: self._add_favorite(name))
        menu.tk_popup(event.x_root, event.y_root)

    def _favorite_context_menu(self, event):
        idx = self.fav_list.nearest(event.y)
        favs = self.settings.get("favorites", [])
        if idx < 0 or idx >= len(favs):
            return
        name = favs[idx]
        self.fav_list.selection_clear(0, "end")
        self.fav_list.selection_set(idx)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Open", command=lambda: self._open_job(name))
        menu.add_separator()
        menu.add_command(label="Remove from favorites",
                         command=lambda: self._remove_favorite(name))
        menu.tk_popup(event.x_root, event.y_root)

    def _remove_favorite(self, name):
        favs = self.settings.get("favorites", [])
        if name in favs:
            favs.remove(name)
            self.settings["favorites"] = favs
            save_settings(self.settings)
        self.refresh_favorites()
        self.status_var.set("Removed '{}' from favorites.".format(name))

    def _add_favorite(self, name):
        favs = self.settings.setdefault("favorites", [])
        if name in favs:
            return False
        favs.append(name)
        save_settings(self.settings)
        self.refresh_favorites()
        self.status_var.set("Added '{}' to favorites.".format(name))
        return True

    def add_favorite(self):
        if not self.current_job:
            messagebox.showinfo(
                APP_NAME,
                "Select a job from the list first, then click Add to Favorites.",
                parent=self.winfo_toplevel())
            return
        if not self._add_favorite(self.current_job):
            messagebox.showinfo(
                APP_NAME,
                "'{}' is already a favorite.".format(self.current_job),
                parent=self.winfo_toplevel())
            return
        messagebox.showinfo(
            APP_NAME,
            "Added '{}' to Favorites (shown in the sidebar).".format(self.current_job),
            parent=self.winfo_toplevel())
        _record("action:nav_favorite")

    def _check_admin(self, parent):
        """Admin username/password gate. Returns True on success - used
        before any write to the shared admin links."""
        creds = load_admin_credentials()
        if not creds:
            messagebox.showerror(
                APP_NAME,
                "Could not read the admin config (DEA_Config.xlsx).\nAdmin links are locked.",
                parent=parent)
            return False
        user = simpledialog.askstring(APP_NAME, "Admin username:", parent=parent)
        if user is None:
            return False
        pwd = simpledialog.askstring(APP_NAME, "Admin password:", show="*", parent=parent)
        if pwd is None:
            return False
        if (user.strip(), pwd) != creds:
            messagebox.showerror(APP_NAME, "Invalid admin credentials.", parent=parent)
            return False
        return True

    def _edit_link_dialog(self, link, parent):
        """Modal name + target editor. Returns (name, target), or None if
        cancelled / left incomplete."""
        result = {}

        def save():
            name = name_var.get().strip()
            target = target_var.get().strip()
            if not name or not target:
                messagebox.showwarning(APP_NAME, "Both a name and a URL or path are needed.",
                                       parent=win)
                return
            result.update(name=name, target=target)
            win.destroy()

        win = tk.Toplevel(parent)
        win.title("Edit Link")
        win.resizable(False, False)
        win.transient(parent)
        win.grab_set()
        ttk.Label(win, text="Name:").grid(row=0, column=0, sticky="w", padx=14, pady=(12, 2))
        name_var = tk.StringVar(value=link.get("name", ""))
        ttk.Entry(win, textvariable=name_var, width=48).grid(row=1, column=0, padx=14, sticky="ew")
        ttk.Label(win, text="URL or path:").grid(row=2, column=0, sticky="w", padx=14, pady=(8, 2))
        target_var = tk.StringVar(value=link.get("target", ""))
        ttk.Entry(win, textvariable=target_var, width=48).grid(row=3, column=0, padx=14, sticky="ew")
        btns = ttk.Frame(win)
        btns.grid(row=4, column=0, sticky="e", padx=14, pady=12)
        ttk.Button(btns, text="Save", command=save).pack(side="left")
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="left", padx=(6, 0))
        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<Return>", lambda e: save())
        parent.wait_window(win)
        if result:
            return result["name"], result["target"]
        return None

    def _render_links_manager(self, host, row):
        """The link manager embedded under the launch buttons in the fixed
        Quick Links footer (add/rename/delete/reorder/icons/admin links) -
        no popup. Every edit repaints only the footer (see
        _refresh_quick_links) so the edited row stays selected."""
        top = self.winfo_toplevel()
        toggle = tk.Label(host, text="\u25BE  MANAGE LINKS",
                          font=("Segoe UI", 9, "bold"),
                          bg="#f5f6f8", fg="#20252b", cursor="hand2")
        toggle.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(14, 0))
        body = ttk.Frame(host, style="App.TFrame")
        body.grid(row=row + 1, column=0, columnspan=3, sticky="ew", padx=2)
        body.grid_columnconfigure(0, weight=1)

        tree_frame = ttk.Frame(body)
        tree_frame.grid(row=0, column=0, sticky="ew", pady=(4, 0))
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        tree = ttk.Treeview(tree_frame, columns=("type", "target"), show="tree headings",
                            style="Nav.Treeview", height=8)
        tree.heading("#0", text="Name")
        tree.heading("type", text="Type")
        tree.heading("target", text="Target")
        for _col, _w in (("#0", 180), ("type", 70), ("target", 340)):
            tree.column(_col, width=_w, stretch=False)
        tree_vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree_hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=tree_vsb.set, xscrollcommand=tree_hsb.set)
        tree.grid(row=0, column=0, sticky="ew")
        tree_vsb.grid(row=0, column=1, sticky="ns")
        tree_hsb.grid(row=1, column=0, sticky="ew")
        tree.bind("<Double-Button-1>", lambda e: edit_link())
        self._links_tree = tree

        hint = tk.StringVar(value=self._links_notice)
        self._links_notice = ""
        ttk.Label(body, textvariable=hint, foreground="#68727d",
                  font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w")

        def all_links():
            return get_admin_links() + self.settings.get("links", [])

        def reload_tree():
            for x in tree.get_children():
                tree.delete(x)
            used_colors = set()
            for idx, link in enumerate(all_links()):
                admin = idx < len(get_admin_links())
                shown = "{} {}".format(resolve_link_icon(link), link["name"])
                color = link.get("color")
                tags = ()
                if color:
                    tags = ("linkcolor_" + str(color),)
                    used_colors.add(str(color))
                tree.insert("", "end", iid=str(idx),
                            values=("Admin" if admin else link["type"], link["target"]),
                            text=("{} (Admin)".format(shown) if admin else shown),
                            tags=tags)
            for color in used_colors:
                tree.tag_configure("linkcolor_" + color, foreground=color)

        def add_link():
            name = simpledialog.askstring(APP_NAME, "Link name:", parent=top)
            if not name:
                return
            target = simpledialog.askstring(APP_NAME, "URL or path:", parent=top)
            if not target:
                return
            self.settings.setdefault("links", []).append(
                {"name": name, "type": detect_link_type(target), "target": target})
            save_settings(self.settings)
            self._refresh_quick_links(select=len(all_links()) - 1)

        def delete_link():
            sel = tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            if idx < len(get_admin_links()):
                messagebox.showwarning(
                    APP_NAME, "Admin links are fixed and cannot be deleted.", parent=top)
                return
            del self.settings["links"][idx - len(get_admin_links())]
            save_settings(self.settings)
            self._refresh_quick_links(select=min(idx, len(all_links()) - 1))

        def edit_link(_=None):
            sel = tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            if idx < len(get_admin_links()):
                if not self._check_admin(top):
                    return
                admin_list = get_admin_links()
                result = self._edit_link_dialog(admin_list[idx], top)
                if not result:
                    return
                admin_list[idx]["name"], admin_list[idx]["target"] = result
                admin_list[idx]["type"] = detect_link_type(result[1])
                try:
                    _write_links_json(_shared_admin_links_file(), admin_list)
                except Exception as e:
                    messagebox.showerror(APP_NAME, "Could not save admin links:\n{}".format(e),
                                         parent=top)
                    return
                invalidate_admin_links_cache()
                self._refresh_quick_links(select=idx)
                return
            link = self.settings["links"][idx - len(get_admin_links())]
            result = self._edit_link_dialog(link, top)
            if not result:
                return
            link["name"], link["target"] = result
            link["type"] = detect_link_type(result[1])
            save_settings(self.settings)
            self._refresh_quick_links(select=idx)

        def set_link_icon(_=None):
            sel = tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            if idx < len(get_admin_links()):
                messagebox.showwarning(
                    APP_NAME, "Admin links are fixed here \u2014 change icons via Admin Links....", parent=top)
                return
            link = self.settings["links"][idx - len(get_admin_links())]
            picked = pick_link_icon(top, link.get("icon"), link.get("color"))
            if not picked:
                return
            glyph, color = picked
            if glyph:
                link["icon"] = glyph
            link["color"] = color
            save_settings(self.settings)
            self._refresh_quick_links(select=idx)

        def move_link(step):
            sel = tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            admin_count = len(get_admin_links())
            if idx < admin_count:
                hint.set("Admin links are fixed here \u2014 reorder them via Admin Links....")
                return
            user_links = self.settings.setdefault("links", [])
            pos, new_pos = idx - admin_count, idx - admin_count + step
            if new_pos < 0 or new_pos >= len(user_links):
                return
            user_links[pos], user_links[new_pos] = user_links[new_pos], user_links[pos]
            save_settings(self.settings)
            self._refresh_quick_links(select=idx + step)

        def add_dropped_links(data):
            added = 0
            for raw in parse_drop_paths(data):
                unc = to_unc(raw)
                if not unc:
                    continue
                name = os.path.basename(unc.rstrip("\\")) or unc
                self.settings.setdefault("links", []).append(
                    {"name": name, "type": detect_link_type(unc), "target": unc})
                added += 1
            if added:
                save_settings(self.settings)
                self._links_notice = "Added {} link(s) \u2014 UNC path generated automatically.".format(added)
                self._refresh_quick_links(select=len(all_links()) - 1)

        if HAS_DND:
            try:
                tree.drop_target_register(DND_FILES)
                tree.dnd_bind("<<Drop>>", lambda e: add_dropped_links(e.data))
                if not hint.get():
                    hint.set("Drag files or folders onto the list \u2014 UNC path is generated for you.")
            except Exception:
                pass

        buttons = ttk.Frame(body)
        buttons.grid(row=2, column=0, sticky="w", pady=(4, 0))
        ttk.Button(buttons, text="+ Add Link", command=add_link).pack(side="left")
        ttk.Button(buttons, text="Delete", command=delete_link).pack(side="left", padx=6)
        ttk.Button(buttons, text="\u25B2 Up", command=lambda: move_link(-1)).pack(side="left")
        ttk.Button(buttons, text="\u25BC Down", command=lambda: move_link(1)).pack(side="left", padx=6)
        ttk.Button(buttons, text="Icon...", command=set_link_icon).pack(side="left")
        ttk.Button(buttons, text="Admin Links...",
                   command=lambda: self._edit_admin_links(top)).pack(side="left", padx=6)
        toggle.bind("<Button-1>", lambda e, h=toggle, f=body:
                    self._toggle_section("MANAGE LINKS", h, f, "MANAGE LINKS"))
        if "MANAGE LINKS" in self._collapsed:
            body.grid_remove()
            toggle.configure(text="\u25B8  MANAGE LINKS")
        reload_tree()

    def _edit_admin_links(self, parent=None):
        """The admin edits the shared admin links here (saved to admin_links.json
        next to the shared DEA_Config.xlsx so every install sees them). Unlocked
        only with the credentials stored in the shared DEA_Config.xlsx."""
        top = parent or self.winfo_toplevel()
        if not self._check_admin(top):
            return

        path = _shared_admin_links_file()
        win = tk.Toplevel(self)
        win.title("NaviTool 2.0 - Admin Quick Links")
        win.geometry("700x450")
        win.minsize(620, 400)
        win.transient(parent or self.winfo_toplevel())
        win.grab_set()
        links = [dict(l) for l in get_admin_links()]

        tree_frame = ttk.Frame(win)
        tree_frame.pack(fill="both", expand=True, padx=12, pady=(12, 4))
        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)
        tree = ttk.Treeview(tree_frame, columns=("type", "target"), show="tree headings",
                               style="Nav.Treeview")
        tree.heading("#0", text="Name")
        tree.heading("type", text="Type")
        tree.heading("target", text="Target")
        for _col, _w in (("#0", 200), ("type", 70), ("target", 340)):
            tree.column(_col, width=_w, stretch=False)
        tree_vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        tree_hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=tree_vsb.set, xscrollcommand=tree_hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        tree_vsb.grid(row=0, column=1, sticky="ns")
        tree_hsb.grid(row=1, column=0, sticky="ew")
        tree.bind("<Double-Button-1>", lambda e: edit())

        def reload_tree():
            for x in tree.get_children():
                tree.delete(x)
            used_colors = set()
            for i, l in enumerate(links):
                shown = "{} {}".format(resolve_link_icon(l), l["name"])
                color = l.get("color")
                tags = ()
                if color:
                    tags = ("linkcolor_" + str(color),)
                    used_colors.add(str(color))
                tree.insert("", "end", iid=str(i), values=(l["type"], l["target"]),
                            text=shown, tags=tags)
            for color in used_colors:
                tree.tag_configure("linkcolor_" + color, foreground=color)

        def add():
            name = simpledialog.askstring(APP_NAME, "Admin link name:", parent=win)
            if not name:
                return
            target = simpledialog.askstring(APP_NAME, "URL or path:", parent=win)
            if not target:
                return
            links.append({"name": name, "type": detect_link_type(target), "target": target})
            reload_tree()

        def delete():
            sel = tree.selection()
            if not sel:
                return
            del links[int(sel[0])]
            reload_tree()

        def edit(_=None):
            sel = tree.selection()
            if not sel:
                return
            i = int(sel[0])
            result = self._edit_link_dialog(links[i], win)
            if not result:
                return
            links[i]["name"], links[i]["target"] = result
            links[i]["type"] = detect_link_type(result[1])
            reload_tree()
            tree.selection_set(str(i))
            tree.see(str(i))

        def set_icon(_=None):
            sel = tree.selection()
            if not sel:
                return
            i = int(sel[0])
            picked = pick_link_icon(win, links[i].get("icon"), links[i].get("color"))
            if not picked:
                return
            glyph, color = picked
            if glyph:
                links[i]["icon"] = glyph
            links[i]["color"] = color
            reload_tree()
            tree.selection_set(str(i))
            tree.see(str(i))

        def move(step):
            sel = tree.selection()
            if not sel:
                return
            pos, new_pos = int(sel[0]), int(sel[0]) + step
            if new_pos < 0 or new_pos >= len(links):
                return
            links[pos], links[new_pos] = links[new_pos], links[pos]
            reload_tree()
            tree.selection_set(str(new_pos))
            tree.see(str(new_pos))

        def save():
            try:
                _write_links_json(path, links)
            except Exception as e:
                messagebox.showerror(APP_NAME, "Could not save admin links:\n{}".format(e), parent=win)
                return
            invalidate_admin_links_cache()
            messagebox.showinfo(
                APP_NAME,
                "Admin links saved to the shared config:\n{}\n\nAll installs share this file.".format(path),
                parent=win)
            win.destroy()
            self._refresh_quick_links()

        hint = tk.StringVar(value="")

        def add_dropped_links(data):
            added = 0
            for raw in parse_drop_paths(data):
                unc = to_unc(raw)
                if not unc:
                    continue
                name = os.path.basename(unc.rstrip("\\")) or unc
                links.append({"name": name, "type": detect_link_type(unc), "target": unc})
                added += 1
            if added:
                reload_tree()
                hint.set("Added {} link(s) \u2014 UNC path generated automatically.".format(added))

        if HAS_DND:
            try:
                win.drop_target_register(DND_FILES)
                win.dnd_bind("<<Drop>>", lambda e: add_dropped_links(e.data))
                hint.set("Drag files or folders here from Explorer \u2014 UNC path is generated for you.")
            except Exception:
                pass

        ttk.Label(win, text="Shared by all installs. Saved to (next to DEA_Config.xlsx):\n" + path,
                  foreground="#68727d", font=("Segoe UI", 9)).pack(anchor="w", padx=12)
        ttk.Label(win, textvariable=hint, foreground="#68727d",
                  font=("Segoe UI", 9)).pack(anchor="w", padx=12)
        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=12, pady=(0, 2))
        ttk.Button(btns, text="+ Add", command=add).pack(side="left")
        ttk.Button(btns, text="Delete", command=delete).pack(side="left", padx=6)
        ttk.Button(btns, text="\u25B2 Up", command=lambda: move(-1)).pack(side="left")
        ttk.Button(btns, text="\u25BC Down", command=lambda: move(1)).pack(side="left", padx=6)
        ttk.Button(btns, text="Icon...", command=set_icon).pack(side="left")
        btns2 = ttk.Frame(win)
        btns2.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns2, text="Save", command=save).pack(side="right")
        ttk.Button(btns2, text="Cancel", command=win.destroy).pack(side="right", padx=6)
        reload_tree()

def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)