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
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk

from client.navigator_tab import (
    DATA_DIR,
    JOB_ROOT,
    open_target,
    parse_job_code,
    load_settings as _nav_load_settings,
    save_settings as _nav_save_settings,
)
from shared.applog import get_logger

_log = get_logger(__name__)

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


def _pruned_dir(name):
    """Subtrees that can never hold a rankable issued detail: sent-calc
    bundles (dateless REV00-03), review areas, models/backups, reference
    and void drops. NOTE: OLD archive packages are deliberately NOT
    pruned - spot-verified files (FBD Stair 1 REV1A, the ladders) exist
    ONLY there; the attribution rules place them correctly, so nothing
    leaks. Verified against Trinity/JPI/FBD/SAB - the winners test
    guards this list (any miss shows up as a diff)."""
    u = (name or "").upper()
    if u in ("SENT CALCS", "TO EQA", "MODEL", "BACKUP", "CAD", "SK", "VOID",
             "REF", "RISA INPUT", "RISA OUTPUT", "CAD+SKETCH", "OTHER RUNS",
             "CBFEM"):
        return True
    if re.match(r"^(VOID|REF)\b", u):
        return True
    if u.startswith(("BACKUP", "RISA", "CHECKING", "FULL CALC",
                     "MUSTAFA")):
        return True
    return False


def _walk_pdfs(folder, max_depth):
    """Yield pdf paths under folder up to max_depth below it (0 = top
    files only), never descending into _pruned_dir() subtrees."""
    try:
        with os.scandir(folder) as it:
            entries = sorted(it, key=lambda e: e.name.lower())
    except OSError:
        return
    subdirs = []
    for e in entries:
        try:
            if e.is_file():
                if e.name.lower().endswith(".pdf"):
                    yield e.path
            elif e.is_dir() and max_depth > 0 and not _pruned_dir(e.name):
                subdirs.append(e.path)
        except OSError:
            continue
    if max_depth > 0:
        for sub in subdirs:
            yield from _walk_pdfs(sub, max_depth - 1)


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


# "STAIR 02" / "Stair 2" / "WEST STAIR 2" -> canonical "STAIR 2".
_STAIR_RE = re.compile(r"STAIR\s*0*(\d+)", re.IGNORECASE)
# S-shorthand in folder/package names only ("S1", "S2", "EC10 S1") - never
# bare sheet tags like "(S2.91)", guarded by the lookahead.
_S_SHORT_RE = re.compile(r"\bS\s*-?\s*0*(\d+)\b(?!\s*\.\d)")


def _stair_token(name):
    """Canonical stair designator in a file/folder/package name, or None."""
    m = _STAIR_RE.search(name or "")
    if m:
        return "STAIR %d" % int(m.group(1))
    return None


def _stair_context(*names):
    """First stair designator across names (full token, else S-shorthand)."""
    for nm in names:
        if not nm:
            continue
        m = _STAIR_RE.search(nm)
        if m:
            return "STAIR %d" % int(m.group(1))
        m = _S_SHORT_RE.search(nm)
        if m:
            return "STAIR %d" % int(m.group(1))
    return None


def _stair_name(name):
    """Stair designator in a folder/package name (full or S-shorthand)."""
    return _stair_context(name)


def _loose_group(side, conn, sub, body):
    """Group for issued files sitting loose in a conn folder (sub=None),
    a kid folder, or a _SENT TO DETAILER subtree (sub = kid name)."""
    if _MAP_RE.search(body or ""):
        return _map_group(body) or sub or conn
    st = _stair_token(body or "")
    if st is not None:
        return st
    tok = _conn_group(body or "")
    if tok is not None:
        if side == "MISC" and _token_alpha(tok) == "EC":
            ctx = _stair_token(body or "") or (_stair_name(sub) if sub else None)
            return "{} {}".format(ctx, tok) if ctx else tok
        return tok
    if side == "MISC" and sub:
        return _strip_pkg_date(sub)
    return sub or conn


def _subpath(task_folder, path):
    """First path part of path's directory relative to task_folder
    (None when the file sits directly in it)."""
    try:
        rel = os.path.relpath(os.path.dirname(path), task_folder)
    except ValueError:
        return None
    if rel in (".", ""):
        return None
    return rel.split(os.sep)[0]


def _strip_pkg_date(name):
    """'100126 - Stair 2' -> 'Stair 2' (dated package/folder prefixes)."""
    return re.sub(r"^\d{6}\s*-\s*", "", name or "").strip() or name


def _desc_from_body(body):
    """Connection description straight from a filename body: drop (tags)
    and floor tags, underscores to spaces. 'EC3 RAIL TYPE A_(15th)' ->
    'EC3 RAIL TYPE A'; 'STAIR 01_(15th)' -> 'STAIR 01'."""
    s = re.sub(r"\s*\([^)]*\)", "", body or "")
    s = s.replace("_", " ")
    s = re.sub(r"\b\d+(ST|ND|RD|TH)\b", "", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()


def _norm_desc(desc):
    """Grouping key: upper-cased, zero-pads stripped ('STAIR 01' and
    'STAIR 1' are the same stair)."""
    return re.sub(r"\b0+(\d)", r"\1", (desc or "").upper())


def _folder_short(folder_rel):
    base = os.path.basename(folder_rel or "") or folder_rel or ""
    return _strip_pkg_date(base)


def _pkg_mentions(pkg_name, conn):
    """Singular/plural/case-tolerant package attribution: STAIRS matches
    'West Stair 2' (and S1/S2/S3 shorthand), RAILINGS matches 'Rail',
    BS matches 'BS Calc Details'."""
    target = _stem(conn)
    if len(target) < 2:
        return False
    if target == "stair" and _S_SHORT_RE.search(pkg_name or ""):
        return True
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
    if "pipesupport" in n:
        return "PIPE SUPPORTS"
    if "ec" in n:
        return "EC"
    return None


_MISC_WORDS_RE = re.compile(
    r"\b(STAIRS?|LADDERS?|(?:GUARD|HAND)?RAIL(ING)?S?|GATES?|PIPE\s*SUPPORTS?)\b",
    re.IGNORECASE)
_EC_TOKEN_RE = re.compile(r"\bEC\d", re.IGNORECASE)


def _blob(*texts):
    """Join names for keyword matching with underscores flattened - file
    bodies join words with '_' ("EC3_RAIL TYPE A"), which defeats \b
    boundaries unless normalized first."""
    return " ".join(t for t in texts if t).replace("_", " ")


def _looks_like_misc(*texts):
    """Rail/stair/ladder/gate words or an EC-digit token anywhere across
    the given names. Word-boundaried so SPEC3 / S2.91 can't match."""
    blob = _blob(*texts)
    return bool(_MISC_WORDS_RE.search(blob) or _EC_TOKEN_RE.search(blob))


def _misc_kw_family(*texts):
    """Misc family from rail/stair/ladder/gate keywords, or None."""
    m = _MISC_WORDS_RE.search(_blob(*texts))
    if not m:
        return None
    return _misc_family(m.group(1))


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
    _all_conns = _list_conns(job_base, code, side)
    other_side = "MISC" if side == "STRUCTURAL" else "STRUCTURAL"
    other_conns = _list_conns(job_base, code, other_side)
    if side == "MISC":
        # Misc calcs are only Rails / Stairs / Ladders / Gates - anything
        # else parked under MISC (2M2W, MC, M2F, ...) is not misc work.
        conns = [c for c in _all_conns if _misc_family(c) is not None]
    else:
        # No stair calcs under Structural - those live on the misc side.
        conns = [c for c in _all_conns if "stair" not in c.lower()]
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
        # Body keywords win over the folder: a guardrail DETAIL sitting
        # under a LADDERS connection is still a railing (and stair rails
        # under RAILINGS are still stairs) - the folder is only the
        # fallback when the filename says nothing.
        if side != "MISC":
            return conn
        kw = _misc_kw_family(info["body"], conn)
        if kw is not None:
            return kw
        if _token_alpha(_conn_group(info["body"]) or "") == "EC":
            return "EC"
        return conn

    plans = []  # (folder, depth, is_pkg, resolve)

    def _add(folder, depth, is_pkg, resolve):
        plans.append((folder, depth, is_pkg, resolve))

    side_root = os.path.join(job_base, "{}_CALCS".format(code), "MATHCAD CALCS", side)
    for conn in conns:
        conn_abs = os.path.join(side_root, conn)
        # tail is the job-relative rel ("CODE_CALCS\\...") used by the
        # Open-folder buttons - rebuilt from parts so temp-tree scans in
        # tests produce sane rels too.
        tail = os.path.join("{}_CALCS".format(code), "MATHCAD CALCS", side, conn)

        def _work_resolve(info, path, _conn=conn, _tail=tail):
            """Classify one working-folder file by its path relative to
            the connection folder (one walk per conn, not six)."""
            try:
                rel = os.path.relpath(path, os.path.join(side_root, _conn))
            except ValueError:
                return None
            parts = rel.split(os.sep)
            body = info["body"]
            fam = _work_family(info, _conn)
            if len(parts) == 1:
                return (fam, _loose_group(side, _conn, None, body),
                        _kind(info), _tail)
            head = parts[0]
            if head == "CALCS":
                # CALCS\\<NN>\\file groups by NN; loose CALCS files by conn.
                if len(parts) == 2:
                    return (fam, _conn, "calc", os.path.join(_tail, "CALCS"))
                if len(parts) == 3:
                    return (fam, parts[1], "calc",
                            os.path.join(_tail, "CALCS", parts[1]))
                return None
            if head == "MAPS":
                # Top level only - ref/ is reference material (also pruned).
                if len(parts) == 2:
                    mg = _map_group(body) or _conn
                    if mg != _conn:
                        seen_maps.setdefault(mg, _conn)
                    return (fam, mg, "map", os.path.join(_tail, "MAPS"))
                return None
            if head == "_SENT TO DETAILER":
                sub = parts[1] if len(parts) > 2 else None
                return (fam, _loose_group(side, _conn, sub, body),
                        _kind(info), os.path.join(_tail, "_SENT TO DETAILER"))
            if head.upper() in _SKIP_DIRS:
                return None
            # Misc-style kid folders (East Stair 1) and one level below.
            if len(parts) in (2, 3):
                return (fam, _loose_group(side, _conn, head, body),
                        _kind(info), os.path.join(_tail, head))
            return None

        _add(conn_abs, 3, False, _work_resolve)

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

    def _make_pkg_resolve(pkg_name, pkg_tail):
        mentioned = [c for c in conns if _pkg_mentions(pkg_name, c)]
        mentioned_other = [c for c in other_conns if _pkg_mentions(pkg_name, c)]

        def _pkg_resolve(info, path, _pkg=pkg_name, _tail=pkg_tail,
                         _men=list(mentioned), _meno=list(mentioned_other)):
            body = info["body"]
            kind = "map" if _MAP_RE.search(body) else "calc"
            parent = os.path.basename(os.path.dirname(path))
            stair = _stair_context(body, parent, _pkg)
            if side == "STRUCTURAL" and _looks_like_misc(body, parent, _pkg):
                return None  # rails/stairs/ladders/gates/EC live on misc
            if _MAP_RE.search(body):
                grp = _map_group(body)
                if grp in seen_maps:
                    return (seen_maps[grp], grp, kind, _tail)
                if stair is not None and side == "MISC" \
                        and not (_meno and not _men):
                    return ("STAIRS", grp, kind, _tail)
                if _men and not _meno:
                    return (_men[0] if len(_men) == 1 else "OTHER", grp, kind,
                            _tail)
                if _meno and not _men:
                    return None
                return ("OTHER", grp, kind, _tail)
            stok = _stair_token(body)
            if stok is not None:
                # "STAIR 02" belongs to whoever owns STAIRS (misc) -
                # nowhere on the structural side.
                where, who = _owning_conn("STAIR")
                if where != "mine":
                    return None
                return (who, stok, kind, _tail)
            tok = _conn_group(body)
            if tok is None:
                if side == "MISC":
                    # Keyworded files stay findable even inside a package
                    # claimed by the other side (no black holes).
                    kwf = _misc_kw_family(body, parent, _pkg)
                    if kwf is not None and parent:
                        return (kwf, _strip_pkg_date(parent), kind, _tail)
                    if _meno and not _men:
                        return None  # the other side's package - not ours
                    if parent:
                        return (_misc_family(parent) or "OTHER",
                                _strip_pkg_date(parent), kind, _tail)
                    return ("OTHER", "(submittal)", kind, _tail)
                if _meno and not _men:
                    return None  # the other side's package - not ours
                if _men and not _meno:
                    # Sole-claimed package: file belongs to that connection
                    # (an MC-named folder's untokened calc is an MC row).
                    return (_men[0],
                            _strip_pkg_date(parent) if parent else "(submittal)",
                            kind, _tail)
                return ("OTHER",
                        _strip_pkg_date(parent) if parent else "(submittal)",
                        kind, _tail)
            alpha = _token_alpha(tok)
            if alpha == "EC":
                if side != "MISC":
                    return None
                # The context picks the family: rail context files under
                # RAILINGS, stair context under STAIRS (stair-qualified so
                # Stair 1 EC1 and Stair 2 EC1 stay apart); EC only with
                # zero context anywhere.
                fam = _misc_kw_family(body, parent, _pkg) or "EC"
                if fam == "STAIRS" and stair:
                    tok = "{} {}".format(stair, tok)
                return (fam, tok, kind, _tail)
            where, who = _owning_conn(alpha)
            if where == "mine":
                return (who, tok, kind, _tail)
            if where == "theirs":
                return None
            if side == "MISC":
                kwf = _misc_kw_family(body, parent, _pkg)
                if kwf is not None:
                    return (kwf, tok, kind, _tail)
            if _men and not _meno:
                return (_men[0] if len(_men) == 1 else "OTHER", tok, kind,
                        _tail)
            if _meno and not _men:
                return None
            return ("OTHER", tok, kind, _tail)

        return _pkg_resolve

    for pkg in packages:
        pkg_abs = os.path.join(subm_root, pkg)
        pkg_tail = os.path.join("{}_SUBMITTAL".format(code), pkg)
        # The package's own top files keep its name, but each child
        # folder is its own package: files under OLD/050226B - MC/...
        # must attribute by the dated name, not the container, or every
        # mention-match misses and they all sink into OTHER.
        _add(pkg_abs, 0, True, _make_pkg_resolve(pkg, pkg_tail))
        try:
            _subpkgs = sorted(
                (e.name for e in os.scandir(pkg_abs) if e.is_dir()),
                key=str.lower,
            )
        except OSError:
            _subpkgs = []
        for _sp in _subpkgs:
            if _pruned_dir(_sp):
                continue
            _add(os.path.join(pkg_abs, _sp), 3, True,
                 _make_pkg_resolve(_sp, os.path.join(pkg_tail, _sp)))

    # ---- phase 1: enumerate in breadth-first rounds (one task per
    # directory, balanced across workers - a single deep tree like OLD/
    # can no longer serialize the phase on one worker) ----
    files = []  # (path, is_pkg, resolve)
    found = [0]
    _found_lock = threading.Lock()
    _walk_index = []  # (dir-rel under side_root or SUBMITTAL, [child names])

    def _run_dir(task):
        folder, depth, is_pkg, resolve = task
        local = []
        children = []
        if _aborted() or not os.path.isdir(folder):
            return local, children
        for path in _walk_pdfs(folder, 0):
            local.append((path, is_pkg, resolve))
            with _found_lock:
                found[0] += 1
                n = found[0]
            if n % 50 == 0:
                _report("Listing files… (%d found)" % n, 0, None)
        if depth > 0 and not _aborted():
            try:
                with os.scandir(folder) as it:
                    kids = sorted((e.name for e in it if e.is_dir()),
                                  key=str.lower)
            except OSError:
                kids = []
            try:
                _rel = os.path.relpath(folder, side_root)
            except ValueError:
                _rel = ""
            with _found_lock:
                _walk_index.append((_rel, kids))
            for k in kids:
                if not _pruned_dir(k):
                    children.append((os.path.join(folder, k), depth - 1,
                                     is_pkg, resolve))
        return local, children

    _report("Listing files…", 0, None)
    pending = list(plans)
    with ThreadPoolExecutor(max_workers=min(8, 64)) as _ex:
        while pending:
            if _aborted():
                return None
            results = list(_ex.map(_run_dir, pending))
            pending = []
            for _local, _kids in results:
                for _f in _local:
                    files.append(_f)
                pending.extend(_kids)
    if _aborted():
        return None
    _report("Listing files… (%d found)" % len(files), 1, 1)

    # ---- phase 2: parse & classify (working first, then packages,
    # so package maps inherit their working MAPS family) ----
    groups = {}
    seen_names = set()  # same basename in two places = same issued file

    def _process(chunk, phase):
        total = len(chunk)
        for i, (path, _pkg, resolve) in enumerate(chunk):
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
            family, group, kind, folder_rel = got
            seen_names.add(base)
            display = group
            if side == "MISC":
                # Filename-first: the connection name comes from the file
                # itself; the folder only disambiguates genuine duplicates
                # at winners time (structural keeps folder/token groups).
                desc = _desc_from_body(info["body"])
                if desc:
                    display = desc
                    group = _norm_desc(desc)
            fam = groups.setdefault(family, {})
            g = fam.setdefault(group, {"calc": [], "map": [], "folder": folder_rel,
                                       "display": display})
            if not g["folder"]:
                g["folder"] = folder_rel
            if len(display) > len(g.get("display") or ""):
                g["display"] = display
            ident = _stair_context(info["body"]) or _stair_context(folder_rel)
            g[kind].append((info["key"], path, folder_rel, ident))
        return True

    working = [f for f in files if not f[1]]
    pkgs = [f for f in files if f[1]]
    if not _process(working, "Reading working folders…"):
        return None
    if not _process(pkgs, "Reading submittal packages…"):
        return None

    # Misc filename-first housekeeping is done per-row below (folder
    # identities unify spelling variants); structural groups are
    # folder/token names and need no merging.

    # Folder descriptions for bare token groups (JPI's "MC01" package
    # rows borrow "MC01 - WBm to ..." from the working tree). Built from
    # the enumeration's directory listings - zero extra network calls.
    # Structural only; misc rows are already filename descriptions.
    _conn_kids = {}
    for _rel, _kids in _walk_index:
        _top = _rel.split(os.sep)[0] if _rel not in (".", "") else ""
        if not _top or _top == "..":
            continue
        _conn_kids.setdefault(_top, set()).update(_kids)

    def _folder_desc(family, token):
        kids = _conn_kids.get(family)
        if not kids:
            return None
        t = (token or "").upper()
        if not re.fullmatch(r"[A-Z]{2,}\d+[A-Z]?", t):
            return None
        hits = sorted(nm for nm in kids
                      if nm.upper() == t or nm.upper().startswith(t + " ")
                      or nm.upper().startswith(t + "-"))
        return hits[0] if hits else None

    def _best(hits):
        if not hits:
            return []
        top = max(k for k, _p, _f, _i in hits)
        return sorted(p for k, p, _f, _i in hits if k == top)

    def _best_pairs(pairs):
        if not pairs:
            return []
        top = max(k for k, _p in pairs)
        return sorted(p for k, p in pairs if k == top)

    winners = {}
    for family, fdata in groups.items():
        if side == "MISC" and family not in ("STAIRS", "LADDERS", "RAILINGS",
                                             "GATES", "PIPE SUPPORTS", "EC"):
            continue  # misc is rails/stairs/ladders/gates/pipes/EC only
        grows = {}
        for group, data in fdata.items():
            display = data.get("display") or group
            if side != "MISC":
                desc = _folder_desc(family, group)
                row = {"calc": _best(data["calc"]), "map": _best(data["map"]),
                       "folder": data["folder"],
                       "label": desc or group}
                if row["calc"] or row["map"]:
                    grows[group] = row
                continue
            # Partition one description's hits by stair identity (the file's
            # own stair context first, else its folder's): "West Stair2" ==
            # "Stair 2" == "061926 - West Stair" for the same WEST STAIR 2
            # file, while bare EC1s under different stairs stay apart - and
            # only then does the folder name appear in the label.
            parts = {}
            for kind in ("calc", "map"):
                for k, p, f, ident in data[kind]:
                    d = parts.setdefault(ident, {"calc": [], "map": [],
                                                 "folder": f})
                    d[kind].append((k, p))
                    if "SUBMITTAL" in d["folder"] and "SUBMITTAL" not in f:
                        d["folder"] = f
            if len(parts) == 1:
                d = next(iter(parts.values()))
                row = {"calc": _best_pairs(d["calc"]),
                       "map": _best_pairs(d["map"]),
                       "folder": d["folder"], "label": display}
                if row["calc"] or row["map"]:
                    grows[group] = row
                continue
            for ident, d in sorted(parts.items(), key=lambda kv: str(kv[0]).lower()):
                norm_ident = _norm_desc(str(ident or ""))
                if norm_ident and norm_ident in _norm_desc(display):
                    label = display  # identity already named (other rows carry suffixes)
                else:
                    short = ident if re.fullmatch(r"STAIR \d+", str(ident or "")) \
                        else _folder_short(d["folder"])
                    label = "{} ({})".format(display, short)
                row = {"calc": _best_pairs(d["calc"]),
                       "map": _best_pairs(d["map"]),
                       "folder": d["folder"], "label": label}
                if row["calc"] or row["map"]:
                    grows["{}||{}".format(group, ident)] = row
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
        _log.exception("Latest Details scan failed for %s (%s)", job_name, side)
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


def _stairs_block(label):
    """STAIRS-tab sub-block for a group label: 1 = stair EC calcs, 2 =
    stair rails, 0 = whole-stair rows. EC wins ties (an 'EC1 STAIR RAIL'
    is first an EC calc)."""
    text = label or ""
    if _EC_TOKEN_RE.search(text):
        return 1
    if _MISC_WORDS_RE.search(text) and "rail" in _stem(text):
        return 2
    return 0


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
        self._fam_names = []
        self._fam_rows = {}
        self._fam_job = None
        self._fam_show_maps = True
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
        # Controls on their own row so long job names can't squeeze them
        # into an unreadable stub (was one crowded row before).
        ctl = ttk.Frame(self, padding=(10, 0, 10, 0))
        ctl.pack(fill="x")
        ttk.Label(ctl, text="Show:", font=("Segoe UI", 9)).pack(side="left")
        for side in SIDES:
            ttk.Radiobutton(ctl, text=SIDE_LABELS[side], value=side,
                            variable=self._side,
                            command=self._on_side_changed).pack(side="left", padx=4)

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

        # Fixed family tabs + scrolling rows: neither scrolls away.
        # (Embedded pages don't scroll themselves - this rows canvas is
        # the Latest page's only scroll region, so the wheel never
        # fights nested scrollers.)
        self._fam_slot = ttk.Frame(self, padding=(10, 2, 10, 0))
        self._fam_slot.pack(fill="x")
        self._fam_nb = None
        rows_wrap = ttk.Frame(self, padding=(10, 2, 10, 10))
        rows_wrap.pack(fill="both", expand=True)
        rows_wrap.grid_columnconfigure(0, weight=1)
        rows_wrap.grid_rowconfigure(0, weight=1)
        self._rows_canvas = tk.Canvas(rows_wrap, background="#f5f6f8",
                                      highlightthickness=0)
        rows_vsb = ttk.Scrollbar(rows_wrap, orient="vertical",
                                 command=self._rows_canvas.yview)
        self.body = ttk.Frame(self._rows_canvas,
                              style="App.TFrame" if self._embedded else "TFrame")
        self._body_win = self._rows_canvas.create_window((0, 0), window=self.body,
                                                         anchor="nw")
        self._rows_canvas.configure(yscrollcommand=rows_vsb.set)
        self._rows_canvas.grid(row=0, column=0, sticky="nsew")
        rows_vsb.grid(row=0, column=1, sticky="ns")
        self.body.bind("<Configure>",
                       lambda _e: self._rows_canvas.configure(
                           scrollregion=self._rows_canvas.bbox("all")))
        self._rows_canvas.bind("<Configure>",
                               lambda e: self._rows_canvas.itemconfig(
                                   self._body_win, width=e.width))

    def scroll_top(self):
        """Reset the rows scroll (used by NaviTool's Latest Details... button)."""
        try:
            self._rows_canvas.yview_moveto(0.0)
        except (tk.TclError, AttributeError):
            pass

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
                self.prog_bar.configure(mode="determinate")
                self.prog_bar["value"] = 0
                self.prog_label.config(text="Starting…")
            else:
                try:
                    self.prog_bar.stop()
                except tk.TclError:
                    pass
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
            if total is None:
                # Listing phase: total unknown - pulse until phase 2.
                self.prog_bar.configure(mode="indeterminate")
                try:
                    self.prog_bar.start(50)
                except tk.TclError:
                    pass
                self.prog_label.config(text=phase)
                return
            try:
                self.prog_bar.stop()
            except tk.TclError:
                pass
            self.prog_bar.configure(mode="determinate")
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
        for w in self._fam_slot.winfo_children():
            w.destroy()
        self._fam_nb = None
        try:
            self._rows_canvas.yview_moveto(0.0)
        except (tk.TclError, AttributeError):
            pass

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
        self.body.grid_columnconfigure(1, weight=1)
        if not rows:
            self._message("No issued detail files found yet for '{}' "
                          "({}). They appear here once DETAIL pdfs land in the "
                          "job's CALCS/MAPS folders or a dated submittal "
                          "package.".format(job, SIDE_LABELS[side]))
            return
        show_maps = side != "MISC"  # misc (stairs/rails/ladders/gates/EC) has no maps
        # Family tabs are a fixed selector above the rows canvas; only
        # the selected family's rows live in the scrolling body, so long
        # lists (FBD MC) actually scroll.
        self._fam_names = [f for f in sorted(rows, key=str.lower) if f != "OTHER"]
        # OTHER collects the unplaceable leftovers - always the last tab.
        if "OTHER" in rows:
            self._fam_names.append("OTHER")
        self._fam_rows = rows
        self._fam_job = job
        self._fam_show_maps = show_maps
        nb = ttk.Notebook(self._fam_slot)
        nb.pack(fill="x")
        for family in self._fam_names:
            pg = ttk.Frame(nb)
            if self._ebg is not None:
                pg.configure(style="App.TFrame")
            nb.add(pg, text=family)
        self._fam_nb = nb
        nb.bind("<<NotebookTabChanged>>", lambda _e: self._paint_selected_family())
        self._paint_selected_family()

    def _paint_selected_family(self):
        nb = self._fam_nb
        if nb is None:
            return
        try:
            family = self._fam_names[nb.index(nb.select())]
        except (tk.TclError, IndexError, AttributeError, TypeError):
            return
        self._paint_rows(family)

    def _paint_rows(self, family):
        try:
            if not self.body.winfo_exists():
                return
        except tk.TclError:
            return
        for w in self.body.winfo_children():
            w.destroy()
        self.body.grid_columnconfigure(1, weight=1)
        self._paint_family(self.body, self._fam_job, family,
                           self._fam_rows[family], self._fam_show_maps)
        try:
            self._rows_canvas.yview_moveto(0.0)
        except (tk.TclError, AttributeError):
            pass

    def _paint_family(self, page, job, family, fdata, show_maps):
        """One family tab: connection calc rows, then a MAPS block with
        one row per map (structural only). STAIRS splits further into
        whole-stair rows plus EC and RAILS blocks; RAILINGS splits off an
        EC block the same way. No map column anywhere."""
        headers = ("Connection", "Latest calc detail", "")
        for col, text in enumerate(headers):
            self._tlabel(page, text=text,
                         font=("Segoe UI", 9, "bold")).grid(
                             row=0, column=col, sticky="w", padx=8, pady=(2, 6))
        row_idx = 1
        calc_groups = sorted(
            (g for g, d in fdata.items() if d["calc"]),
            key=lambda g: fdata[g].get("label") or g)
        blocks = [("main", calc_groups)]
        if family in ("STAIRS", "RAILINGS"):
            ec = [g for g in calc_groups
                  if _EC_TOKEN_RE.search(fdata[g].get("label") or g)]
            rest = [g for g in calc_groups if g not in set(ec)]
            if family == "STAIRS":
                rail = [g for g in rest
                        if _stairs_block(fdata[g].get("label") or g) == 2]
                main = [g for g in rest if g not in set(rail)]
                blocks = [("main", main),
                          ("\u2014 EC \u2014", ec),
                          ("\u2014 RAILS \u2014", rail)]
            else:
                blocks = [("main", rest),
                          ("\u2014 EC \u2014", ec)]
        for title, members in blocks:
            if title != "main" and members:
                self._tlabel(page, text=title,
                             font=("Segoe UI", 9, "bold"),
                             foreground="#20252b").grid(row=row_idx, column=0,
                                                        columnspan=3, sticky="w",
                                                        padx=8, pady=(10, 2))
                row_idx += 1
            for group in members:
                row_idx = self._paint_row(page, job, row_idx,
                                          fdata[group].get("label") or group,
                                          fdata[group]["calc"],
                                          fdata[group]["folder"])
        if show_maps:
            map_groups = sorted(
                (g for g, d in fdata.items() if d["map"]),
                key=lambda g: fdata[g].get("label") or g)
            if map_groups:
                self._tlabel(page, text="\u2014 MAPS \u2014",
                             font=("Segoe UI", 9, "bold"),
                             foreground="#20252b").grid(row=row_idx, column=0,
                                                        columnspan=3, sticky="w",
                                                        padx=8, pady=(10, 2))
                row_idx += 1
                for group in map_groups:
                    row_idx = self._paint_row(page, job, row_idx,
                                              fdata[group].get("label") or group,
                                              fdata[group]["map"],
                                              fdata[group]["folder"])
        page.grid_columnconfigure(1, weight=1)

    def _paint_row(self, page, job, row_idx, label, paths, folder_rel):
        self._tlabel(page, text=label,
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
