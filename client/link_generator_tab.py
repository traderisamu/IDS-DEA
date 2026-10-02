"""Link Generator tab - drop files/folders onto the table (or Add them
via the buttons) and get share-ready UNC links, with per-row
double-click copy, Copy All, and Clear.

Split out of client/navigator_tab.py (where it used to live as a
section under each job); self-contained state, mounted as its own
notebook tab by client/main_app.py. Must stay import-safe: no Tk root
creation at import.
"""
import os
import tkinter as tk
from tkinter import ttk, filedialog

from client.navigator_tab import parse_drop_paths, to_unc

try:
    from tkinterdnd2 import DND_FILES
    HAS_DND = True
except Exception:
    HAS_DND = False
    DND_FILES = None


class LinkGeneratorFrame(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self._gen_files = []  # [(name, unc)]
        self._build_ui()
        self._refresh_gen_tree()

    def _build_ui(self):
        top = ttk.Frame(self, padding=(10, 10, 10, 0))
        top.pack(fill="x")
        ttk.Label(top, text="Link Generator",
                  font=("Segoe UI", 13, "bold")).pack(side="left")
        ttk.Label(top, text="Drop files / folders onto the table (multi-select OK), "
                            "or add them with the buttons.",
                  font=("Segoe UI", 9), foreground="#68727d").pack(side="left", padx=(12, 0))

        btn_row = ttk.Frame(self, padding=(10, 8, 10, 0))
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="Add Files...", command=self._gen_pick_files).pack(side="left")
        ttk.Button(btn_row, text="Add Folder...", command=self._gen_pick_folder).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Copy All", command=self._gen_copy_all).pack(side="left")
        ttk.Button(btn_row, text="Clear", command=self._gen_clear).pack(side="right")

        body = ttk.Frame(self, padding=(10, 6, 10, 0))
        body.pack(fill="both", expand=True)
        tree = ttk.Treeview(body, columns=("unc",), show="tree headings", height=12)
        tree.heading("#0", text="Name")
        tree.heading("unc", text="UNC Path")
        tree.column("#0", width=220, stretch=False)
        tree.column("unc", width=560, stretch=True)
        tree_vsb = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        tree_hsb = ttk.Scrollbar(body, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=tree_vsb.set, xscrollcommand=tree_hsb.set)
        tree_vsb.pack(side="right", fill="y")
        tree_hsb.pack(side="bottom", fill="x")
        tree.pack(fill="both", expand=True)
        tree.bind("<Double-Button-1>", lambda e: self._gen_copy_selected())
        self._gen_tree = tree

        hint_text = ("Drag-and-drop is unavailable here - use Add Files / Add Folder."
                     if not HAS_DND else "Tip: double-click a row to copy its link.")
        self._gen_hint = tk.StringVar(value=hint_text)
        ttk.Label(self, textvariable=self._gen_hint,
                  font=("Segoe UI", 8), foreground="#68727d").pack(
                      anchor="w", padx=12, pady=(2, 10))

        if HAS_DND:
            try:
                tree.drop_target_register(DND_FILES)
                tree.dnd_bind("<<Drop>>", lambda e: self._gen_add_dropped(e.data))
            except Exception:
                pass

    def _gen_pick_files(self):
        paths = filedialog.askopenfilenames(parent=self.winfo_toplevel(), title="Add files")
        if paths:
            self._gen_add_paths(list(paths))

    def _gen_pick_folder(self):
        path = filedialog.askdirectory(parent=self.winfo_toplevel(), title="Add folder")
        if path:
            self._gen_add_paths([path])

    def _gen_add_dropped(self, data):
        # A fresh drop always replaces the list - never accumulates.
        self._gen_files = []
        self._gen_add_paths(parse_drop_paths(data))

    def _gen_add_paths(self, raw_paths):
        added = 0
        for raw in raw_paths:
            unc = to_unc(raw)
            if not unc:
                continue
            if any(u == unc for _, u in self._gen_files):
                continue
            name = os.path.basename(unc.rstrip("\\")) or unc
            self._gen_files.append((name, unc))
            added += 1
        self._refresh_gen_tree()
        total = len(self._gen_files)
        if added:
            self._gen_hint.set(
                f"{total} file(s) ready - double-click a row or Copy All to grab links.")
        elif raw_paths:
            self._gen_hint.set("Those are already in the list.")

    def _refresh_gen_tree(self):
        tree = getattr(self, "_gen_tree", None)
        if tree is None:
            return
        try:
            for x in tree.get_children():
                tree.delete(x)
            for name, unc in self._gen_files:
                tree.insert("", "end", text=name, values=(unc,))
        except tk.TclError:
            pass

    def _gen_selected_unc(self):
        tree = getattr(self, "_gen_tree", None)
        if tree is None:
            return None
        sel = tree.selection()
        if not sel:
            return None
        vals = tree.item(sel[0], "values")
        return vals[0] if vals else None

    def _gen_copy_selected(self):
        unc = self._gen_selected_unc()
        if not unc:
            return
        self.clipboard_clear()
        self.clipboard_append(unc)
        self._gen_hint.set(f"Copied: {unc}")

    def _gen_copy_all(self):
        if not self._gen_files:
            self._gen_hint.set("Nothing to copy yet - drop or add files first.")
            return
        self.clipboard_clear()
        self.clipboard_append("\n".join(u for _, u in self._gen_files))
        self._gen_hint.set(f"Copied {len(self._gen_files)} link(s).")

    def _gen_clear(self):
        self._gen_files = []
        self._refresh_gen_tree()
        self._gen_hint.set("Cleared.")
