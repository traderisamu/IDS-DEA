"""IDS Job Navigator, embedded as a tab inside the DEA Logger.

Originally a standalone app (Project - Job-nav ChatGPT v2); now imported
by client/main_app.py and mounted as the "Job Navigator" notebook tab.
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

APP_NAME = "IDS Navigator"
JOB_ROOT = r"\\EgnyteDrive\idsinc\Shared\Engineering\ENGG PHL\JOBS"

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


def _dir_entries(base, rel):
    """Sorted list of immediate subfolders under a job-relative path."""
    out = []
    try:
        with os.scandir(os.path.join(base, rel)) as it:
            for e in it:
                if e.is_dir():
                    out.append(e.name)
    except OSError:
        pass
    return sorted(out, key=str.lower)


def build_job_sections(job_name):
    """Return [(title, [item, ...]), ...]. An item is either
    {"kind":"button", label, rel, icon} or
    {"kind":"dropdown", label, icon, menu:[(menu_label, rel), ...]}."""
    base = os.path.join(JOB_ROOT, job_name)
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
            root = mathcad + "\\" + sub
            if _exists(base, root):
                submenu = [(sub, root), ("-", None)]
                for name in _dir_entries(base, root):
                    submenu.append((name, root + "\\" + name))
                menu.append((sub, submenu))
        calcs.append({"kind": "dropdown", "label": "CALCS", "icon": "\U0001F9EE", "menu": menu})
    elif _exists(base, sc("CALCS")):
        calcs.append({"kind": "button", "label": "CALCS", "icon": "\U0001F9EE",
                      "rel": sc("CALCS"), "menu": None})
    sent = sc("CALCS", "SENT CALCS")
    if _exists(base, sent):
        menu = [("SENT CALCS", sent), ("-", None)]
        for name in _dir_entries(base, sent):
            menu.append((name, sent + "\\" + name))
        calcs.append({"kind": "dropdown", "label": "SENT CALCS", "icon": "\U0001F4E4", "menu": menu})
    if calcs:
        sections.append(("CALCS", calcs))

    # ---------- Initial proceedings ----------
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
    rfi = sc("RFI")
    if _exists(base, rfi):
        menu = []
        for sub in ("RFI SENT", "RFI RESPONSE"):
            if _exists(base, rfi + "\\" + sub):
                menu.append((sub, rfi + "\\" + sub))
        if menu:
            initial.append({"kind": "dropdown", "label": "RFI", "icon": "\U0001F4E9", "menu": menu})
        else:
            initial.append({"kind": "button", "label": "RFI", "icon": "\U0001F4E9",
                            "rel": rfi, "menu": None})
    sk = sc("SKETCHES")
    if _exists(base, sk):
        menu = []
        try:
            with os.scandir(os.path.join(base, sk)) as it:
                for entry in it:
                    if entry.is_dir():
                        menu.append((entry.name, sk + "\\" + entry.name))
        except OSError:
            pass
        menu = sorted(menu, key=lambda m: m[0].lower())
        if menu:
            initial.append({"kind": "dropdown", "label": "SKETCHES", "icon": "\u270F", "menu": menu})
        else:
            initial.append({"kind": "button", "label": "SKETCHES", "icon": "\u270F",
                            "rel": sk, "menu": None})
    if initial:
        sections.append(("INITIAL", initial))

    # ---------- Submittal stage ----------
    submittal = []
    if _exists(base, sc("SUBMITTAL")):
        submittal.append({"kind": "button", "label": "SUBMITTAL", "icon": "\U0001F4E4",
                          "rel": sc("SUBMITTAL"), "menu": None})
    det_root = sc("DETAILING")
    if _exists(base, det_root):
        menu = []
        for sub in ("SHOP DRAWINGS", "LAYOUT"):
            root = det_root + "\\" + sub
            if _exists(base, root):
                menu.append((sub, root))
        dc = det_root + "\\SHOP DRAWINGS\\DESIGN COMMENTS"
        if _exists(base, dc):
            menu.insert(1, ("DESIGN COMMENTS", dc))
        if menu:
            submittal.append({"kind": "dropdown", "label": "DETAILING",
                              "icon": "\U0001F3D7", "menu": menu})
        else:
            submittal.append({"kind": "button", "label": "DETAILING", "icon": "\U0001F3D7",
                              "rel": det_root, "menu": None})
    if submittal:
        sections.append(("SUBMITTAL", submittal))

    # ---------- Fabrication stage ----------
    fab = []
    if _exists(base, sc("APPROVAL SUMMARY")):
        fab.append({"kind": "button", "label": "APPROVAL SUMMARY", "icon": "\U0001F4CA",
                    "rel": sc("APPROVAL SUMMARY"), "menu": None})
    cd_root = sc("CHANGE DOCUMENTS")
    if _exists(base, cd_root):
        cd_target = cd_root + "\\APPROVAL RETURNS"
        fab.append({"kind": "button", "label": "CD", "icon": "\U0001F4DD",
                    "rel": cd_target if _exists(base, cd_target) else cd_root, "menu": None})
    if fab:
        sections.append(("FABRICATION", fab))

    return sections


DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "IDS", "Navigator")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
SECTION_CACHE_FILE = os.path.join(DATA_DIR, "section_cache.json")


def load_section_cache():
    """Disk cache of built job sections {job_name: sections}. Lets favorites
    and recently opened jobs load instantly instead of re-scanning the network
    share every time. Invalid entries are simply rebuilt by the caller."""
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
SHARED_ADMIN_LINKS = os.path.join(os.path.dirname(DEA_CONFIG), "admin_links.json")


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
    links = _read_links_json(SHARED_ADMIN_LINKS)
    if not links:
        links = _read_links_json(_admin_links_file())
    if not links:
        links = ADMIN_LINKS
    _ADMIN_LINKS_CACHE["links"] = links
    _ADMIN_LINKS_CACHE["at"] = now
    return links


def load_admin_credentials():
    """Username/password that unlock the admin quick-link editor, read live
    from the 'App Settings' sheet of the shared DEA_Config.xlsx."""
    try:
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


def open_target(target):
    t = normalize_path(target)
    if not t:
        return
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
        self.settings = load_settings()
        self.jobs = []
        self.current_job = None
        self.filtered_jobs = []
        self._folder_cache = load_section_cache()
        self._cache_lock = threading.Lock()
        self._collapsed = set()
        self._hover_menus = []
        self._job_token = 0  # guards async renders against rapid re-clicks
        self._select_after_id = None  # debounce for arrow-key scrolling
        self._build_style()
        self._build_ui()
        self.refresh_jobs()
        self.refresh_favorites()
        self._prewarm()

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
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ttk.Frame(self, style="Sidebar.TFrame", padding=(14, 16))
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.configure(width=220)
        sidebar.grid_propagate(False)

        ttk.Label(sidebar, text="IDS NAVIGATOR", style="Sidebar.TLabel",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(0, 18))

        ttk.Label(sidebar, text="FAVORITES", style="Sidebar.TLabel",
                  font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.fav_list = tk.Listbox(sidebar, bg="#20252b", fg="#e8edf2",
                                   selectbackground="#3d79b9", selectforeground="white",
                                   relief="flat", highlightthickness=0,
                                   font=("Segoe UI", 9), activestyle="none",
                                   height=5, exportselection=False)
        self.fav_list.pack(fill="x", pady=(6, 10))
        self.fav_list.bind("<<ListboxSelect>>", self._on_favorite_select)
        self.fav_list.bind("<Double-Button-1>", lambda e: self._favorite_open_folder())
        self.fav_list.bind("<Button-3>", self._favorite_context_menu)

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

        ttk.Button(sidebar, text="\u21bb Refresh Jobs", command=self.refresh_jobs).pack(fill="x", pady=(10, 5))

        ttk.Button(sidebar, text="\u2699 Quick Links", command=self.manage_links).pack(fill="x", pady=5)

        main = ttk.Frame(self, style="App.TFrame", padding=(22, 18))
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)

        top = ttk.Frame(main, style="App.TFrame")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        self.title_var = tk.StringVar(value="Select a job")
        ttk.Label(top, textvariable=self.title_var, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.path_var = tk.StringVar(value=JOB_ROOT)
        ttk.Label(top, textvariable=self.path_var, style="Sub.TLabel").grid(row=1, column=0, sticky="w", pady=(3, 0))

        actions = ttk.Frame(main, style="App.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=(14, 10))
        ttk.Button(actions, text="Open Job", command=self.open_current_job).pack(side="left")
        ttk.Button(actions, text="Add to Favorites", command=self.add_favorite).pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="")
        status = ttk.Label(main, textvariable=self.status_var, style="Sub.TLabel")
        status.grid(row=2, column=0, sticky="w", pady=(0, 8))

        # Scrollable content area: jobs with many sections are taller than
        # the window, and without this the bottom buttons (quick links)
        # could sit below the visible area with no way to reach them.
        # self.content keeps its name/role (the inner frame everything
        # renders into) so no render code changes.
        content_wrap = ttk.Frame(main, style="App.TFrame")
        content_wrap.grid(row=3, column=0, sticky="nsew")
        content_wrap.grid_columnconfigure(0, weight=1)
        content_wrap.grid_rowconfigure(0, weight=1)
        self._content_canvas = tk.Canvas(content_wrap, background="#f5f6f8",
                                         highlightthickness=0)
        content_vsb = ttk.Scrollbar(content_wrap, orient="vertical",
                                    command=self._content_canvas.yview)
        self.content = ttk.Frame(self._content_canvas, style="App.TFrame")
        self._content_canvas.create_window((0, 0), window=self.content, anchor="nw")
        self._content_canvas.configure(yscrollcommand=content_vsb.set)
        self._content_canvas.grid(row=0, column=0, sticky="nsew")
        content_vsb.grid(row=0, column=1, sticky="ns")
        self.content.grid_columnconfigure(0, weight=1, uniform="btn")
        self.content.grid_columnconfigure(1, weight=1, uniform="btn")
        self.content.grid_columnconfigure(2, weight=1, uniform="btn")
        self.content.grid_rowconfigure(99, weight=1)
        self.content.bind("<Configure>",
                          lambda e: self._content_canvas.configure(
                              scrollregion=self._content_canvas.bbox("all")))
        self._content_canvas.bind("<Configure>", self._fit_content_width)
        self._content_canvas.bind_all("<MouseWheel>", self._scroll_content_wheel, add="+")

        self._show_placeholder()

    def _search_focus_in(self, _):
        if self.job_search.get() == "Search jobs...":
            self.job_search.delete(0, "end")
            self.job_search.configure(foreground="#20252b")

    def _search_focus_out(self, _):
        if not self.job_search.get():
            self.job_search.insert(0, "Search jobs...")
            self.job_search.configure(foreground="#7a828a")

    def refresh_jobs(self):
        # NOTE: the section cache is deliberately NOT wiped here. A full
        # wipe made every post-refresh click re-scan the network share
        # (the main click-lag complaint). Stale folders for still-existing
        # jobs are refreshed on click by _show_job_async; only entries for
        # jobs that no longer exist are pruned.
        try:
            names = []
            with os.scandir(JOB_ROOT) as it:
                for entry in it:
                    if entry.is_dir():
                        names.append(entry.name)
            self.jobs = sorted(names, key=str.lower)
        except Exception as e:
            self.jobs = []
            self._show_placeholder("Cannot access JOBS directory.\n\n{}\n\n{}".format(JOB_ROOT, e))
            return
        alive = set(self.jobs)
        with self._cache_lock:
            stale = [k for k in self._folder_cache if k not in alive]
            for k in stale:
                del self._folder_cache[k]
            if stale:
                save_section_cache(self._folder_cache)
        self.filter_jobs()
        self._prewarm(force=True)

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
        self.path_var.set(os.path.join(JOB_ROOT, name))
        self._show_job_async()
        self._add_recent(name)
        self.status_var.set("")
        if name in self.filtered_jobs:
            idx = self.filtered_jobs.index(name)
            self.job_list.selection_clear(0, "end")
            self.job_list.selection_set(idx)
            self.job_list.see(idx)

    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()
        try:
            self._content_canvas.yview_moveto(0.0)
        except (tk.TclError, AttributeError):
            pass

    def _fit_content_width(self, _event=None):
        """Keep the inner content frame as wide as the canvas so the
        3-column button grid always fills the visible width."""
        try:
            width = self._content_canvas.winfo_width()
            for item in self._content_canvas.find_all():
                self._content_canvas.itemconfigure(item, width=width)
        except tk.TclError:
            pass

    def _scroll_content_wheel(self, event):
        """Mouse-wheel scrolling for the content area. Bound app-wide
        (bind_all) but only acts when the pointer is actually over this
        tab's content, so it never hijacks scrolling in DEA's other tabs
        or dialogs."""
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except tk.TclError:
            return
        node = widget
        try:
            while node is not None and node is not self._content_canvas and node is not self.content:
                node = node.master
        except tk.TclError:
            return
        if node is None:
            return
        try:
            self._content_canvas.yview_scroll(-1 * (event.delta // 120), "units")
        except tk.TclError:
            pass

    def _show_placeholder(self, text="Select a job from the left."):
        self._clear_content()
        ttk.Label(self.content, text=text, style="Sub.TLabel",
                  font=("Segoe UI", 11)).grid(row=0, column=0, columnspan=3, pady=(30, 10))
        # No job selected: the job area is empty, so show the quick links here.
        all_links = get_admin_links() + self.settings.get("links", [])
        width = max([len(l["name"]) + 3 for l in all_links] + [1]) + 2
        self._render_quick_links(width, 1)

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
                base = os.path.join(JOB_ROOT, name)
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

    def _toggle_section(self, title, header, frame):
        if frame.winfo_ismapped():
            frame.grid_remove()
            header.configure(text="\u25B8  " + title)
            self._collapsed.add(title)
        else:
            frame.grid()
            header.configure(text="\u25BE  " + title)
            self._collapsed.discard(title)

    def _show_job(self):
        """Synchronous render from cache (or a fast local build). Used by
        the quick-link editors, which only need to repaint the links."""
        self._clear_content()
        if not self.current_job:
            self._show_placeholder()
            return
        self._render_sections(self._get_sections(self.current_job))

    def _show_job_async(self):
        """Click path: paint instantly, never block the UI on the network.

        - Cache hit  -> render immediately (no thread, no flicker).
        - Cache miss -> show a "Loading..." placeholder at once, build the
          sections in a background thread, then paint via after(). A token
          guard drops stale results when the user clicks another job
          before the build finishes."""
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
        self._clear_content()
        ttk.Label(self.content, text="Loading '{}'...".format(name),
                  style="Sub.TLabel", font=("Segoe UI", 11)).grid(
                      row=0, column=0, columnspan=3, pady=(30, 10))

        def work():
            try:
                sections = build_job_sections(name)
            except Exception:
                sections = []
            with self._cache_lock:
                self._folder_cache[name] = sections
                save_section_cache(self._folder_cache)

            def paint():
                if token != self._job_token or self.current_job != name:
                    return  # user moved on; drop this stale result
                try:
                    if not self.content.winfo_exists():
                        return
                except tk.TclError:
                    return
                self._clear_content()
                self._render_sections(sections)
            try:
                self.after(0, paint)
            except tk.TclError:
                pass

        threading.Thread(target=work, daemon=True).start()

    def _render_sections(self, sections):

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
        for title, items in sections:
            if title:
                toggle = ttk.Button(self.content, text="\u25BE  " + title, style="Toggle.TButton",
                                    takefocus=0)
                toggle.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 0))
                row += 1
                frame = ttk.Frame(self.content, style="App.TFrame")
                frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=2)
                self._render_items(frame, items, width)
                toggle.configure(command=lambda t=title, h=toggle, f=frame:
                                 self._toggle_section(t, h, f))
                if title in self._collapsed:
                    frame.grid_remove()
                    toggle.configure(text="\u25B8  " + title)
                row += 1
            else:
                frame = ttk.Frame(self.content, style="App.TFrame")
                frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=2)
                self._render_items(frame, items, width)
                row += 1

        all_links = get_admin_links() + self.settings.get("links", [])
        self._render_quick_links(width, row)

    def _render_quick_links(self, width, row):
        """Quick-links card block with its own collapse toggle. Shown under a
        selected job and on the empty (no-job-selected) screen."""
        all_links = get_admin_links() + self.settings.get("links", [])
        links_toggle = ttk.Button(self.content, text="\u25BE  QUICK LINKS", style="Toggle.TButton",
                                  takefocus=0)
        links_toggle.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(14, 0))
        row += 1
        links_frame = ttk.Frame(self.content, style="App.TFrame")
        links_frame.grid(row=row, column=0, columnspan=3, sticky="ew", padx=2)
        for j, link in enumerate(all_links):
            ttk.Button(links_frame, text="{}  {}".format(
                self._icon_for_type(link["type"]), link["name"]),
                style="Card.TButton", width=width,
                command=lambda x=link["target"]: open_target(x)).grid(
                    row=j // 3, column=j % 3, sticky="ew", padx=5, pady=5)
        links_frame.grid_columnconfigure(0, weight=1, uniform="btn")
        links_frame.grid_columnconfigure(1, weight=1, uniform="btn")
        links_frame.grid_columnconfigure(2, weight=1, uniform="btn")
        links_toggle.configure(command=lambda h=links_toggle, f=links_frame:
                               self._toggle_section("QUICK LINKS", h, f))
        if "QUICK LINKS" in self._collapsed:
            links_frame.grid_remove()
            links_toggle.configure(text="\u25B8  QUICK LINKS")

    def _render_items(self, frame, items, width):
        for i, it in enumerate(items):
            col = i % 3
            r = i // 3
            if it["kind"] == "dropdown":
                mb = ttk.Menubutton(frame, text="\u25BE " + it["label"],
                                    style="Card.TMenubutton", width=width)
                menu = tk.Menu(mb, tearoff=0)
                for entry in it["menu"]:
                    if entry[0] == "-":
                        menu.add_separator()
                    elif isinstance(entry[1], str):
                        menu.add_command(label=entry[0],
                                         command=lambda rr=entry[1]: self.open_job_folder(rr))
                    else:
                        sub = tk.Menu(menu, tearoff=0)
                        for s_entry in entry[1]:
                            if s_entry[0] == "-":
                                sub.add_separator()
                            else:
                                sub.add_command(label=s_entry[0],
                                                command=lambda rr=s_entry[1]: self.open_job_folder(rr))
                        menu.add_cascade(label=entry[0], menu=sub)
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
        for label, rel in items:
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
        return {"web": "\uE774", "file": "\uE8A5", "folder": "\uE8B7"}.get(typ, "\uE71B")

    def open_job_folder(self, rel):
        if not self.current_job:
            return
        path = os.path.join(JOB_ROOT, self.current_job, rel) if rel else os.path.join(JOB_ROOT, self.current_job)
        open_target(path)

    def open_current_job(self):
        if self.current_job:
            open_target(os.path.join(JOB_ROOT, self.current_job))

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
        open_target(os.path.join(JOB_ROOT, favs[sel[0]]))

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
                         command=lambda: open_target(os.path.join(JOB_ROOT, name)))
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

    def manage_links(self):
        win = tk.Toplevel(self)
        win.title("IDS Navigator - Quick Links")
        win.geometry("620x420")
        win.transient(self.winfo_toplevel())
        win.grab_set()

        tree = ttk.Treeview(win, columns=("type", "target"), show="tree headings",
                               style="Nav.Treeview")
        tree.heading("#0", text="Name")
        tree.heading("type", text="Type")
        tree.heading("target", text="Target")
        tree.column("#0", width=180)
        tree.column("type", width=70)
        tree.column("target", width=300)
        tree.pack(fill="both", expand=True, padx=12, pady=(12, 4))
        tree.bind("<Double-Button-1>", lambda e: rename_link())

        hint = tk.StringVar(value="")
        ttk.Label(win, textvariable=hint, foreground="#68727d",
                  font=("Segoe UI", 9)).pack(anchor="w", padx=12)

        def all_links():
            return get_admin_links() + self.settings.get("links", [])

        def reload_tree():
            for x in tree.get_children():
                tree.delete(x)
            for idx, link in enumerate(all_links()):
                admin = idx < len(get_admin_links())
                tree.insert("", "end", iid=str(idx),
                            values=("Admin" if admin else link["type"], link["target"]),
                            text=("{} (Admin)".format(link["name"]) if admin else link["name"]))

        def add_link():
            name = simpledialog.askstring(APP_NAME, "Link name:", parent=win)
            if not name:
                return
            target = simpledialog.askstring(APP_NAME, "URL or path:", parent=win)
            if not target:
                return
            self.settings.setdefault("links", []).append(
                {"name": name, "type": detect_link_type(target), "target": target})
            save_settings(self.settings)
            reload_tree()
            self._show_job()

        def delete_link():
            sel = tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            if idx < len(get_admin_links()):
                messagebox.showwarning(
                    APP_NAME, "Admin links are fixed and cannot be deleted.", parent=win)
                return
            del self.settings["links"][idx - len(get_admin_links())]
            save_settings(self.settings)
            reload_tree()
            self._show_job()

        def rename_link(_=None):
            sel = tree.selection()
            if not sel:
                return
            idx = int(sel[0])
            if idx < len(get_admin_links()):
                messagebox.showwarning(
                    APP_NAME, "Admin links are fixed here \u2014 rename them via Admin Links....", parent=win)
                return
            link = self.settings["links"][idx - len(get_admin_links())]
            name = simpledialog.askstring(APP_NAME, "Link name:",
                                          initialvalue=link["name"], parent=win)
            if not name:
                return
            link["name"] = name.strip()
            save_settings(self.settings)
            reload_tree()
            tree.selection_set(str(idx))
            tree.see(str(idx))
            self._show_job()

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
            reload_tree()
            tree.selection_set(str(idx + step))
            tree.see(str(idx + step))
            self._show_job()

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
                reload_tree()
                self._show_job()
                hint.set("Added {} link(s) \u2014 UNC path generated automatically.".format(added))

        if HAS_DND:
            try:
                win.drop_target_register(DND_FILES)
                win.dnd_bind("<<Drop>>", lambda e: add_dropped_links(e.data))
                hint.set("Drag files or folders here from Explorer \u2014 UNC path is generated for you.")
            except Exception:
                pass

        buttons = ttk.Frame(win)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(buttons, text="+ Add Link", command=add_link).pack(side="left")
        ttk.Button(buttons, text="Rename", command=rename_link).pack(side="left", padx=6)
        ttk.Button(buttons, text="Delete", command=delete_link).pack(side="left")
        ttk.Button(buttons, text="\u25B2 Up", command=lambda: move_link(-1)).pack(side="left")
        ttk.Button(buttons, text="\u25BC Down", command=lambda: move_link(1)).pack(side="left", padx=6)
        ttk.Button(buttons, text="Admin Links...", command=lambda: self._edit_admin_links(win)).pack(side="left", padx=6)
        ttk.Button(buttons, text="Close", command=win.destroy).pack(side="right")
        reload_tree()

    def _edit_admin_links(self, parent=None):
        """The admin edits the shared admin links here (saved to admin_links.json
        next to the shared DEA_Config.xlsx so every install sees them). Unlocked
        only with the credentials stored in the shared DEA_Config.xlsx."""
        top = parent or self.winfo_toplevel()
        creds = load_admin_credentials()
        if not creds:
            messagebox.showerror(
                APP_NAME,
                "Could not read the admin config (DEA_Config.xlsx).\nAdmin links are locked.",
                parent=top)
            return
        user = simpledialog.askstring(APP_NAME, "Admin username:", parent=top)
        if user is None:
            return
        pwd = simpledialog.askstring(APP_NAME, "Admin password:", show="*", parent=top)
        if pwd is None:
            return
        if (user.strip(), pwd) != creds:
            messagebox.showerror(APP_NAME, "Invalid admin credentials.", parent=top)
            return

        path = SHARED_ADMIN_LINKS
        win = tk.Toplevel(self)
        win.title("IDS Navigator - Admin Quick Links")
        win.geometry("640x400")
        win.transient(parent or self.winfo_toplevel())
        win.grab_set()
        links = [dict(l) for l in get_admin_links()]

        tree = ttk.Treeview(win, columns=("type", "target"), show="tree headings",
                               style="Nav.Treeview")
        tree.heading("#0", text="Name")
        tree.heading("type", text="Type")
        tree.heading("target", text="Target")
        tree.column("#0", width=200)
        tree.column("type", width=70)
        tree.column("target", width=320)
        tree.pack(fill="both", expand=True, padx=12, pady=(12, 4))
        tree.bind("<Double-Button-1>", lambda e: rename())

        def reload_tree():
            for x in tree.get_children():
                tree.delete(x)
            for i, l in enumerate(links):
                tree.insert("", "end", iid=str(i), values=(l["type"], l["target"]), text=l["name"])

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

        def rename(_=None):
            sel = tree.selection()
            if not sel:
                return
            i = int(sel[0])
            name = simpledialog.askstring(APP_NAME, "Admin link name:",
                                          initialvalue=links[i]["name"], parent=win)
            if not name:
                return
            links[i]["name"] = name.strip()
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
            self._show_job()

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
        btns.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(btns, text="+ Add", command=add).pack(side="left")
        ttk.Button(btns, text="Rename", command=rename).pack(side="left", padx=6)
        ttk.Button(btns, text="Delete", command=delete).pack(side="left")
        ttk.Button(btns, text="\u25B2 Up", command=lambda: move(-1)).pack(side="left")
        ttk.Button(btns, text="\u25BC Down", command=lambda: move(1)).pack(side="left", padx=6)
        ttk.Button(btns, text="Save", command=save).pack(side="right")
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right", padx=6)
        reload_tree()

def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)