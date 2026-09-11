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
