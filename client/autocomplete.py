"""
Lightweight type-ahead suggestions for editable ttk.Combobox widgets.

Previous version used ttk's own `combo.event_generate("<Down>")` to pop
the built-in dropdown open on every keystroke. That also triggers ttk's
internal "post" behaviour, which highlights/selects the nearest-matching
text inside the entry itself - so the next keystroke could silently wipe
out what you'd just typed, and focus/cursor handling felt like it was
fighting you. That's the "too forceful" behaviour being fixed here.

This version renders its own small borderless popup window with a
Listbox of matches instead of using ttk's built-in dropdown machinery.
It never calls focus_set() on the popup and never touches the entry's
selection or insertion cursor - the entry keeps focus and keeps the
cursor exactly where you left it while you type. Nothing gets chosen
until the user actively clicks a suggestion or presses Enter with one
highlighted; Up/Down just move a visual highlight within the popup.
"""
import tkinter as tk

_IGNORED_KEYS = {
    "Return", "KP_Enter", "Escape", "Tab", "ISO_Left_Tab",
    "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
    "Caps_Lock", "Left", "Right", "Home", "End",
}

_MAX_VISIBLE_ROWS = 8
_ROW_HEIGHT_PX = 20


class _SuggestPopup:
    def __init__(self, combo):
        self.combo = combo
        self.top = None
        self.listbox = None
        self.items = []
        self.highlight = -1

    def _ensure_built(self):
        if self.top is not None:
            return
        self.top = tk.Toplevel(self.combo)
        self.top.withdraw()
        self.top.wm_overrideredirect(True)
        try:
            self.top.wm_attributes("-topmost", True)
        except tk.TclError:
            pass
        # takefocus=0 is what keeps the cursor in the entry: clicking a
        # suggestion never steals keyboard focus away from where you're typing.
        self.listbox = tk.Listbox(
            self.top, activestyle="none", exportselection=False,
            highlightthickness=1, highlightbackground="#999",
            relief="solid", bd=1, takefocus=0,
        )
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<Button-1>", self._on_click)
        self.listbox.bind("<Motion>", self._on_motion)

    def show(self, items):
        if not items:
            self.hide()
            return
        self._ensure_built()
        self.items = items
        self.listbox.delete(0, "end")
        for it in items:
            self.listbox.insert("end", it)
        rows = min(len(items), _MAX_VISIBLE_ROWS)
        self.listbox.configure(height=rows)

        self.combo.update_idletasks()
        x = self.combo.winfo_rootx()
        y = self.combo.winfo_rooty() + self.combo.winfo_height()
        w = max(self.combo.winfo_width(), 120)
        self.top.wm_geometry(f"{w}x{rows * _ROW_HEIGHT_PX}+{x}+{y}")
        self.top.deiconify()
        self.top.lift()
        self.highlight = -1
        self.listbox.selection_clear(0, "end")

    def hide(self):
        if self.top is not None:
            self.top.withdraw()
        self.items = []
        self.highlight = -1

    def is_visible(self):
        return self.top is not None and bool(self.top.winfo_ismapped())

    def move_highlight(self, delta):
        if not self.items:
            return
        if self.highlight < 0:
            self.highlight = 0 if delta > 0 else len(self.items) - 1
        else:
            self.highlight = max(0, min(len(self.items) - 1, self.highlight + delta))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(self.highlight)
        self.listbox.see(self.highlight)

    def highlighted_value(self):
        if 0 <= self.highlight < len(self.items):
            return self.items[self.highlight]
        return None

    def _on_motion(self, event):
        idx = self.listbox.nearest(event.y)
        if 0 <= idx < len(self.items):
            self.highlight = idx
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(idx)

    def _on_click(self, event):
        idx = self.listbox.nearest(event.y)
        if 0 <= idx < len(self.items):
            self._choose(self.items[idx])

    def _choose(self, value):
        self.combo.set(value)
        self.combo.icursor("end")
        self.hide()
        # Keep focus in the entry so the user can keep typing/tabbing
        # normally right after picking a suggestion.
        self.combo.focus_set()


def enable_typeahead(combo, get_all_values):
    """
    combo: an editable (not readonly) ttk.Combobox.
    get_all_values: zero-arg callable returning the current full list of
                     candidate strings. Called fresh on every keystroke,
                     so keep it cheap (return a cached list, not a fresh
                     disk read - callers should refresh that cache
                     separately, e.g. after saving a new entry).
    """
    popup = _SuggestPopup(combo)
    combo._suggest_popup = popup  # keep a reference alive on the widget

    def refresh(_event=None):
        typed = combo.get()
        all_values = get_all_values() or []
        if typed:
            filtered = [v for v in all_values if typed.lower() in v.lower() and v != typed]
        else:
            filtered = list(all_values)
        popup.show(filtered)

    def on_keyrelease(event):
        if event.keysym in _IGNORED_KEYS:
            return
        refresh()

    def on_down(event):
        if popup.is_visible():
            popup.move_highlight(1)
            return "break"
        # Nothing showing yet (e.g. empty box) - show the full list.
        refresh()
        return "break"

    def on_up(event):
        if popup.is_visible():
            popup.move_highlight(-1)
            return "break"
        return None

    def on_return(event):
        if popup.is_visible():
            value = popup.highlighted_value()
            if value is not None:
                popup._choose(value)
                return "break"
            popup.hide()
        return None

    def on_escape(event):
        if popup.is_visible():
            popup.hide()
            return "break"
        return None

    def on_focus_out(event):
        # Small delay so a click on the popup registers before we hide it
        # (the popup never takes focus itself, so this mainly covers the
        # user clicking away to a different widget entirely).
        combo.after(150, popup.hide)

    combo.bind("<KeyRelease>", on_keyrelease)
    combo.bind("<Down>", on_down)
    combo.bind("<Up>", on_up)
    combo.bind("<Return>", on_return)
    combo.bind("<KP_Enter>", on_return)
    combo.bind("<Escape>", on_escape)
    combo.bind("<FocusOut>", on_focus_out)
