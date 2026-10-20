"""
Normalizes shared-folder path input so both UNC paths
(\\\\server\\share\\folder) and mapped drive letters (Z:\\folder) work
reliably, even if someone pastes it with forward slashes or a trailing
slash (a common copy-paste issue with paths sourced from Explorer's
address bar or a browser).
"""
import os
import re

from . import constants as C


def local_app_dir():
    """The per-Windows-user folder this app keeps its own local state in
    (settings JSON, log file) - %APPDATA%\\IDS_DEA_Logger, or the user's
    home folder as a fallback on a platform without APPDATA."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, C.LOCAL_APP_FOLDER_NAME)
    os.makedirs(folder, exist_ok=True)
    return folder


def normalize_shared_path(path):
    if not path:
        return path
    path = path.strip().strip('"').strip("'")

    is_unc = path.startswith("\\\\") or path.startswith("//")

    # Unify all slashes to backslashes (Windows accepts both, but mixing
    # them can confuse UNC-root detection further down the line).
    path = path.replace("/", "\\")

    # Collapse accidental doubled backslashes, except the leading UNC "\\\\".
    if is_unc:
        rest = path.lstrip("\\")
        rest = re.sub(r"\\{2,}", r"\\", rest)
        path = "\\\\" + rest
    else:
        path = re.sub(r"\\{2,}", r"\\", path)

    # Strip a trailing slash (but keep a bare drive root like "C:\\").
    if len(path) > 3 and path.endswith("\\"):
        path = path.rstrip("\\")

    return path


def is_unc_path(path):
    return bool(path) and path.startswith("\\\\")


_EGNYTE_ROOT = "\\\\egnytedrive"


def shared_path_variants(path, max_alias=5):
    """The folder itself first, then the alias variants Egnyte creates
    when the same share is already mounted under that name on a PC
    ('\\\\EgnyteDrive\\idsinc' -> '...\\idsinc (2)', '(3)', ...).

    Why this exists: whether a PC exposes the share as 'idsinc' or
    'idsinc (2)' depends on what else that user already has mapped, so a
    single hardcoded share name works on most PCs and fails on a few with
    no visible difference on the Egnyte side. Only enabled for the
    \\\\EgnyteDrive root - no guessing on real file servers."""
    p = normalize_shared_path(path)
    if not p or not p.lower().startswith(_EGNYTE_ROOT + "\\"):
        return [p] if p else []

    remainder = p[len(_EGNYTE_ROOT) + 1:]
    parts = remainder.split("\\", 1)
    share = parts[0]
    tail = parts[1] if len(parts) > 1 else ""

    match = re.match(r"^(.*?)\s*\((\d+)\)$", share)
    base = match.group(1) if match else share

    def build(name):
        return _EGNYTE_ROOT.replace("egnytedrive", "EgnyteDrive") + "\\" + name + (
            "\\" + tail if tail else "")

    out = [p]
    bare = build(base)
    if bare not in out:
        out.append(bare)
    for n in range(2, max_alias + 1):
        cand = build(f"{base} ({n})")
        if cand not in out:
            out.append(cand)
    return out


def resolve_existing_dir(path, max_alias=5):
    """The first alias variant of `path` that exists, or `path` unchanged.
    For folder-level network paths (the update source, quick-link seed)
    that have no single file to prove them by."""
    for variant in shared_path_variants(path, max_alias=max_alias):
        try:
            if os.path.isdir(variant):
                return variant
        except OSError:
            continue
    return path


def find_shared_config(candidate_dirs, filename, max_alias=5):
    """First folder among `candidate_dirs` (plus their Egnyte alias
    variants) that actually contains `filename`, or None. Only folders
    with a readable copy of the file are accepted, so an alias pointing at
    some other Egnyte account can never be mistaken for the real share."""
    seen = set()
    for folder in candidate_dirs:
        for variant in shared_path_variants(folder, max_alias=max_alias):
            if not variant or variant.lower() in seen:
                continue
            seen.add(variant.lower())
            try:
                if os.path.isfile(os.path.join(variant, filename)):
                    return variant
            except OSError:
                continue
    return None
