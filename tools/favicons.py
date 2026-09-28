"""Lag favicon.ico (16/32/48), favicon-192.png og apple-touch-icon.png fra samme
motiv som site/favicon.svg. Google vil ha et ikon på minst 48x48 i et format den
kjenner godt; SVG alene vises ikke alltid i søkeresultatene."""
from pathlib import Path

from PIL import Image, ImageDraw

SITE = Path(__file__).resolve().parent.parent / "site"
RED = (179, 18, 46)


def icon(size, pad=0.0625):
    S = size * 8  # tegn stort og skaler ned for glatte kanter
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = S * pad
    d.ellipse((m, m, S - m, S - m), fill=RED)
    w = S * 3.4 / 32
    x = S / 2
    d.line((x, S * 7 / 32, x, S * 18 / 32), fill="white", width=round(w))
    for y in (S * 7 / 32, S * 18 / 32):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill="white")
    r = w / 2
    d.ellipse((x - r, S * 22.5 / 32 - r, x + r, S * 24.5 / 32 + r), fill="white")
    return img.resize((size, size), Image.LANCZOS)


icon(48).save(SITE / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
icon(192).save(SITE / "favicon-192.png", optimize=True)
bg = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
bg.alpha_composite(icon(180, pad=0.08))
bg.convert("RGB").save(SITE / "apple-touch-icon.png", optimize=True)
print("favicon.ico, favicon-192.png, apple-touch-icon.png")
