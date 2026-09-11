"""
Generates assets/icon.ico - used for the .exe file icon, the window
icon, and the taskbar icon. A clipboard-with-checkmark + clock motif
in IDS PH's navy/gold palette. Re-run this if you want a different
design; no external image files required.
"""
from PIL import Image, ImageDraw

NAVY = (31, 78, 120, 255)      # #1F4E78
NAVY_DARK = (17, 51, 82, 255)  # clipboard clip
WHITE = (255, 255, 255, 255)
GOLD = (245, 166, 35, 255)     # clock accent
GREEN = (46, 125, 50, 255)     # checkmark


def draw_master(size=512):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded square background
    pad = int(size * 0.04)
    d.rounded_rectangle([pad, pad, size - pad, size - pad],
                         radius=int(size * 0.16), fill=NAVY)

    # Clipboard body (white rounded rect, slightly inset)
    cb_l, cb_t = int(size * 0.20), int(size * 0.16)
    cb_r, cb_b = int(size * 0.80), int(size * 0.86)
    d.rounded_rectangle([cb_l, cb_t, cb_r, cb_b], radius=int(size * 0.05), fill=WHITE)

    # Clipboard clip at top
    clip_w = size * 0.22
    clip_h = size * 0.08
    clip_l = size / 2 - clip_w / 2
    d.rounded_rectangle([clip_l, cb_t - clip_h * 0.6, clip_l + clip_w, cb_t + clip_h * 0.4],
                         radius=int(clip_h * 0.3), fill=NAVY_DARK)

    # Checklist lines
    line_x1 = cb_l + size * 0.08
    line_x2 = cb_r - size * 0.08
    for i, y_frac in enumerate([0.32, 0.44, 0.56]):
        y = size * y_frac
        color = NAVY if i < 2 else (0, 0, 0, 0)
        # small checkbox squares
        box = size * 0.045
        d.rectangle([line_x1, y - box / 2, line_x1 + box, y + box / 2],
                     outline=NAVY, width=max(2, int(size * 0.008)))
        d.line([line_x1 + box * 1.6, y, line_x2, y], fill=(180, 180, 180, 255),
               width=max(2, int(size * 0.012)))

    # Checkmark in the last row's box (shows "done")
    y = size * 0.56
    box = size * 0.045
    cx, cy = line_x1 + box / 2, y
    d.line([cx - box * 0.35, cy, cx - box * 0.05, cy + box * 0.35], fill=GREEN, width=max(2, int(size * 0.012)))
    d.line([cx - box * 0.05, cy + box * 0.35, cx + box * 0.45, cy - box * 0.35], fill=GREEN, width=max(2, int(size * 0.012)))

    # Small clock badge bottom-right, over the clipboard, on navy bg circle
    clock_r = size * 0.18
    ccx, ccy = cb_r - size * 0.02, cb_b - size * 0.02
    d.ellipse([ccx - clock_r, ccy - clock_r, ccx + clock_r, ccy + clock_r], fill=GOLD, outline=NAVY_DARK,
              width=max(2, int(size * 0.01)))
    d.ellipse([ccx - clock_r * 0.8, ccy - clock_r * 0.8, ccx + clock_r * 0.8, ccy + clock_r * 0.8],
              fill=WHITE)
    d.line([ccx, ccy, ccx, ccy - clock_r * 0.55], fill=NAVY_DARK, width=max(2, int(size * 0.02)))
    d.line([ccx, ccy, ccx + clock_r * 0.4, ccy], fill=NAVY_DARK, width=max(2, int(size * 0.02)))

    return img


def build():
    master = draw_master(512)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [master.resize((s, s), Image.LANCZOS) for s in sizes]
    imgs[0].save("/home/claude/dea_app/assets/icon.ico", format="ICO",
                 sizes=[(s, s) for s in sizes], append_images=imgs[1:])
    master.save("/home/claude/dea_app/assets/icon_preview.png")
    print("Saved assets/icon.ico and icon_preview.png")


if __name__ == "__main__":
    build()
