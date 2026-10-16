#!/usr/bin/env python3
"""Forhåndsvis soner for eldre tekster i data/history_regions/<nøkkel>.json uten full bygging.

  .venv/bin/python tools/history_zones.py NØKKEL [UTMAPPE]

Skriver ut alle periodene for landet (hash, datoer, om teksten er tegnet), og for hver
tegnet tekst nivå, etikett, areal og andel av landet per sone. Lager et PNG-bilde per
tekst (UTMAPPE, standard .cache/history_zones/<nøkkel>/) med landet, naboene,
ADM1-grensene, byer og sonene, så man kan se at de stemmer med teksten.
Feiler som build.py hvis en hash ikke finnes i historikken eller et navn mangler i geoBoundaries.
"""
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import box, shape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scraper"))
import build  # noqa: E402
import gb  # noqa: E402
import history  # noqa: E402

def font(size):
    for f in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


COL = {"all": (179, 38, 47), "necessary": (232, 131, 58)}
W = 1000


def rings(g):
    for part in getattr(g, "geoms", [g]):
        if part.geom_type == "Polygon":
            yield list(part.exterior.coords)
            for r in part.interiors:
                yield list(r.coords)
        elif hasattr(part, "geoms"):
            yield from rings(part)


def polys(g):
    for part in getattr(g, "geoms", [g]):
        if part.geom_type == "Polygon":
            yield part
        elif hasattr(part, "geoms"):
            yield from polys(part)


def render(path, title, country, ne, iso, painted, places):
    bs = [country.bounds] + [g.bounds for g, _ in painted]
    x0, y0 = min(b[0] for b in bs), min(b[1] for b in bs)
    x1, y1 = max(b[2] for b in bs), max(b[3] for b in bs)
    pad = max(x1 - x0, y1 - y0) * 0.08
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    k = math.cos(math.radians((y0 + y1) / 2))
    sc = W / ((x1 - x0) * k)
    H = int((y1 - y0) * sc) + 60
    xy = lambda c: ((c[0] - x0) * k * sc, (y1 - c[1]) * sc + 60)
    img = Image.new("RGBA", (W, H), (200, 215, 225, 255))
    d = ImageDraw.Draw(img)
    view = box(x0, y0, x1, y1)
    for other, g in ne.items():
        if other != iso and g.intersects(view):
            for r in rings(g.intersection(view)):
                d.polygon([xy(c) for c in r], fill=(225, 225, 220), outline=(150, 150, 150))
    for r in rings(country):
        d.polygon([xy(c) for c in r], fill=(255, 255, 255), outline=(60, 60, 60))
    try:
        for f in gb.load(iso, "ADM1")["features"]:
            for r in rings(shape(f["geometry"])):
                d.line([xy(c) for c in r], fill=(170, 170, 200), width=1)
    except Exception:
        pass
    for g, z in painted:
        # Én maske per sone, så hull (unntak som level "none") blir stående tomme.
        col = COL[z["level"]]
        mask = Image.new("L", img.size, 0)
        md = ImageDraw.Draw(mask)
        for part in polys(g):
            md.polygon([xy(c) for c in part.exterior.coords], fill=90 if z.get("partial") else 150)
            for r in part.interiors:
                md.polygon([xy(c) for c in r.coords], fill=0)
        img.paste(Image.new("RGBA", img.size, col + (255,)), (0, 0), mask)
        d = ImageDraw.Draw(img)
        for r in rings(g):
            d.line([xy(c) for c in r], fill=col, width=1)
    d = ImageDraw.Draw(img)
    fnt = font(13)
    for name, lon, lat in places:
        if x0 < lon < x1 and y0 < lat < y1:
            px, py = xy((lon, lat))
            d.ellipse([px - 2, py - 2, px + 2, py + 2], fill=(0, 0, 0))
            d.text((px + 4, py - 7), name, fill=(0, 0, 0), font=fnt)
    d.rectangle([0, 0, W, 58], fill=(255, 255, 255))
    d.text((8, 4), title, fill=(0, 0, 0), font=font(15))
    legend = "  ".join(f"[{'rød' if z['level'] == 'all' else 'oransje'}{'/delvis' if z.get('partial') else ''}] {z.get('label', '')}"
                       for _, z in painted)
    d.text((8, 30), legend[:170], fill=(60, 60, 60), font=fnt)
    img.convert("RGB").save(path)


def main(key, out=None):
    iso = json.loads((build.DATA / "countries.json").read_text())[key]
    ne, _ = build.load_ne()
    country = ne[iso]
    proj = build.Proj(country)
    area = proj.fwd(country).area
    entries = history.build()[key]
    drawn = build.load_history_regions([key]).get(key, {})
    current = build.text_hash(entries[-1]["paragraphs"]) if entries[-1]["paragraphs"] else ""
    unknown = set(drawn) - {build.text_hash(h["paragraphs"]) for h in entries if h["paragraphs"]}
    if unknown:
        raise SystemExit(f"fant ikke tekstene {sorted(unknown)} i historikken for {key}")
    places = [(f["properties"]["name"], f["properties"]["longitude"], f["properties"]["latitude"])
              for f in build.fetch(build.PLACES_URL, build.PLACES_PATH)["features"]
              if f["properties"]["min_zoom"] <= 6]
    out = Path(out or build.CACHE / "history_zones" / key)
    out.mkdir(parents=True, exist_ok=True)
    print(f"{key} ({iso}), {area:,.0f} km²")
    for h in entries:
        hsh = build.text_hash(h["paragraphs"]) if h["paragraphs"] else ""
        tag = "gjeldende (regions.json)" if hsh and hsh == current else "tegnet" if hsh in drawn else ""
        print(f"  {h['from']}–{h['until'] or ''}  {hsh or '-' * 12}  {'(hull) ' if h.get('gap') else ''}{tag}")
    for hsh, zones in drawn.items():
        h = next(e for e in entries if e["paragraphs"] and build.text_hash(e["paragraphs"]) == hsh)
        painted = build.paint(zones, country, ne, proj, iso)
        print(f"\n{hsh}  {h['from']}–{h['until'] or ''}\n  {' '.join(h['paragraphs'])}")
        for g, z in painted:
            a = proj.fwd(g).area
            print(f"  {z['level']:9} {a:>10,.0f} km² {a / area:6.1%}  {z.get('label', '')}"
                  f"{' (delvis)' if z.get('partial') else ''}{' (omtrentlig)' if z.get('approx') else ''}")
        path = out / f"{hsh}.png"
        render(path, f"{key} {hsh} {h['from']}–{h['until'] or ''}", country, ne, iso, painted, places)
        print(f"  bilde: {path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(*sys.argv[1:3])
