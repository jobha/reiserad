"""Lag site/og.png (delingsbilde, 1200x630) fra ferdigbygde site/data. Kjøres for hånd
ved behov: .venv/bin/python tools/og_image.py (krever pillow)."""
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 1200, 630
SEA, LAND, LINE = (221, 231, 238), (251, 250, 247), (207, 200, 188)
COL = {"all": (179, 18, 46), "necessary": (239, 106, 58)}
FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_R = "/System/Library/Fonts/Supplemental/Arial.ttf"

# Utsnitt: lon -20..150, lat -40..62 (der advarslene er), tegnet til høyre.
LON0, LON1, LAT0, LAT1 = -25, 150, -38, 64
MX0, MX1 = 330, 1200
sx = (MX1 - MX0) / (LON1 - LON0)
sy = H / (LAT1 - LAT0)
s = min(sx, sy)


def xy(lon, lat):
    return MX0 + (lon - LON0) * s, (LAT1 - lat) * s + (H - (LAT1 - LAT0) * s) / 2


def polys(geom):
    c = geom["coordinates"]
    return c if geom["type"] == "MultiPolygon" else [c]


img = Image.new("RGB", (W * 2, H * 2), SEA)
d = ImageDraw.Draw(img)
S = 2
def pts(ring): return [(x * S, y * S) for x, y in (xy(*p) for p in ring)]

for f in json.loads((ROOT / "site/data/world.json").read_text())["features"]:
    for poly in polys(f["geometry"]):
        d.polygon(pts(poly[0]), fill=LAND, outline=LINE)
for f in json.loads((ROOT / "site/data/zones.json").read_text())["features"]:
    col = COL[f["properties"]["level"]]
    for poly in polys(f["geometry"]):
        d.polygon(pts(poly[0]), fill=col)
        for hole in poly[1:]:
            d.polygon(pts(hole), fill=LAND)
img = img.resize((W, H), Image.LANCZOS)

# Tekstfelt til venstre
d = ImageDraw.Draw(img, "RGBA")
d.rounded_rectangle((36, 150, 520, 480), 28, fill=(255, 255, 255, 238))
d.text((72, 190), "Reiserådkart", font=ImageFont.truetype(FONT, 58), fill=(29, 29, 31))
body = ImageFont.truetype(FONT_R, 27)
d.text((72, 272), "UDs reiseråd og reiseadvarsler", font=body, fill=(60, 58, 64))
d.text((72, 306), "på et zoombart verdenskart", font=body, fill=(60, 58, 64))
small = ImageFont.truetype(FONT_R, 22)
for i, (lvl, txt) in enumerate([("all", "Fraråder alle reiser"), ("necessary", "Fraråder ikke-nødvendige reiser")]):
    y = 372 + i * 38
    d.rounded_rectangle((72, y + 3, 100, y + 23), 5, fill=COL[lvl])
    d.text((114, y), txt, font=small, fill=(60, 58, 64))
d.text((72, 530), "reiserad.no", font=ImageFont.truetype(FONT, 26), fill=(29, 29, 31))
img.save(ROOT / "site/og.png", optimize=True)
print("site/og.png", (ROOT / "site/og.png").stat().st_size, "bytes")
