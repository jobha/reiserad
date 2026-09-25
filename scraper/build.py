#!/usr/bin/env python3
"""Bygg kartdata fra data/advisories.json + data/regions.json.

Skriver:
  site/data/world.json   alle land (Natural Earth 1:50m), forenklet, med iso3
  site/data/zones.json   GeoJSON med én flate per (land, nivå, sone)
  site/data/info.json    tekst, lenker og status per land

  python scraper/build.py               bygg
  python scraper/build.py --stamp SLUG  marker kartleggingen av SLUG som oppdatert
  python scraper/build.py --stamp-all
"""
import json
import math
import os
import re
import sys
import urllib.request
from pathlib import Path

from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import transform, unary_union

import gb

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "site" / "data"
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
NE_PATH = Path(os.environ.get("REISERAD_CACHE", ROOT / ".cache")) / "ne_50m_admin_0_countries.geojson"

# Natural Earth deler noen land i flere flater; UD har én side.
MERGE = {"SOM": ["SOM", "SOL"], "CYP": ["CYP", "CYN"]}

REGIONAL_HINTS = re.compile(
    r"område|region|provins|grense|delstat|distrikt|fylke|bortsett|unntatt|unntak|"
    r"utenfor|innenfor|nærmere enn|\bkm\b|kilometer|hovedstad|byen|øya|øyer",
    re.I,
)


def load_ne():
    if not NE_PATH.exists():
        NE_PATH.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(NE_URL, NE_PATH)
    feats = json.loads(NE_PATH.read_text())["features"]
    geoms = {}
    for f in feats:
        geoms.setdefault(f["properties"]["ADM0_A3"], []).append(shape(f["geometry"]).buffer(0))
    out = {k: unary_union(v) for k, v in geoms.items()}
    for iso, parts in MERGE.items():
        out[iso] = unary_union([out[p] for p in parts if p in out])
    return out, feats


class Proj:
    """Lokal ekvirektangulær projeksjon i km, god nok for buffere på landnivå."""

    def __init__(self, geom):
        c = geom.centroid
        self.lon0, self.lat0 = c.x, c.y
        self.kx = 111.32 * math.cos(math.radians(self.lat0))
        self.ky = 110.57

    def fwd(self, g):
        return transform(lambda x, y, z=None: ((x - self.lon0) * self.kx, (y - self.lat0) * self.ky), g)

    def inv(self, g):
        return transform(lambda x, y, z=None: (x / self.kx + self.lon0, y / self.ky + self.lat0), g)

    def buffer(self, g, km):
        return self.inv(self.fwd(g).buffer(km, resolution=12))


def adm_geom(ref, names):
    iso, adm = ref.split("/")
    feats = gb.load(iso, adm)["features"]
    picked = [f for f in feats if f["properties"]["shapeName"] in names]
    missing = set(names) - {f["properties"]["shapeName"] for f in picked}
    if missing:
        raise SystemExit(f"{ref}: fant ikke {sorted(missing)}")
    return unary_union([shape(f["geometry"]).buffer(0) for f in picked])


def zone_geom(z, country, ne, proj):
    if z.get("country"):
        g = country
    elif "adm" in z:
        g = adm_geom(z["adm"], z["names"])
    elif "border" in z:
        nb = unary_union([ne[i] for i in z["border"] if i in ne])
        if "clip" in z:
            from shapely.geometry import box
            nb = nb.intersection(box(*z["clip"]))
        g = proj.buffer(nb, z["km"])
    elif "near" in z:
        g = proj.buffer(zone_geom(z["near"], country, ne, proj), z["km"])
    elif "poly" in z:
        g = shape({"type": "Polygon", "coordinates": [z["poly"] + [z["poly"][0]]]})
    elif "point" in z:
        g = proj.buffer(Point(z["point"]), z["km"])
    elif "line" in z:
        g = proj.buffer(LineString(z["line"]), z["km"])
    else:
        raise SystemExit(f"ukjent sone: {z}")
    if "and" in z:
        g = g.intersection(zone_geom(z["and"], country, ne, proj))
    return g


def auto_level(paragraphs):
    txt = " ".join(paragraphs).lower()
    return "necessary" if "nødvendig" in txt else "all"


def round_coords(obj, nd=3):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(v, nd) for v in obj]
        return [round_coords(v, nd) for v in obj]
    return obj


def feature(geom, props, tol=0.005):
    geom = geom.simplify(tol, preserve_topology=True)
    if geom.is_empty:
        return None
    m = mapping(geom)
    return {"type": "Feature", "properties": props,
            "geometry": {"type": m["type"], "coordinates": round_coords(m["coordinates"])}}


def build():
    adv = json.loads((DATA / "advisories.json").read_text())
    iso_of = json.loads((DATA / "countries.json").read_text())
    regions = {k: v for k, v in json.loads((DATA / "regions.json").read_text()).items() if not k.startswith("_")}
    reviewed = json.loads((DATA / "reviewed.json").read_text()) if (DATA / "reviewed.json").exists() else {}
    ne, ne_feats = load_ne()

    info, zones = {}, []
    for slug, c in adv["countries"].items():
        iso = iso_of[slug]
        rec = {"slug": slug, "name": c["name"], "url": c["url"], "level": None}
        w = c.get("warning")
        if w:
            rec.update(status=w["status"], paragraphs=w["paragraphs"])
        info[iso] = rec
        if not w:
            continue

        country = ne[iso]
        spec = regions.get(slug)
        if spec is None:
            regional = bool(REGIONAL_HINTS.search(" ".join(w["paragraphs"])))
            level = auto_level(w["paragraphs"])
            rec["level"] = level
            if regional:
                # Ny eller endret regional advarsel uten kartlegging: vis hele
                # landet skravert og be leseren sjekke UD.
                rec["unmapped"] = True
                zones.append(feature(country, {"iso": iso, "level": level, "partial": True, "unmapped": True}, 0.02))
            else:
                zones.append(feature(country, {"iso": iso, "level": level, "label": "Hele landet"}, 0.02))
            continue

        if reviewed.get(slug) != c.get("hash"):
            rec["stale"] = True
        proj = Proj(country)
        painted = []  # [(geom, zone)]
        for z in spec["zones"]:
            g = zone_geom(z, country, ne, proj).intersection(country)
            painted = [(pg.difference(g), pz) for pg, pz in painted]
            painted.append((g, z))
        levels = set()
        for g, z in painted:
            if g.is_empty or z["level"] == "none":
                continue
            levels.add(z["level"])
            props = {"iso": iso, "level": z["level"], "label": z.get("label", "")}
            for k in ("partial", "approx"):
                if z.get(k):
                    props[k] = True
            f = feature(g, props)
            if f:
                zones.append(f)
        rec["level"] = "all" if "all" in levels else "necessary"
        rec["regional"] = True
        rec["exceptions"] = [z["label"] for z in spec["zones"] if z["level"] == "none"]

    known = set(info)
    world = []
    for f in ne_feats:
        a3 = f["properties"]["ADM0_A3"]
        iso = next((k for k, v in MERGE.items() if a3 in v), a3)
        world.append(feature(shape(f["geometry"]).buffer(0), {"iso": iso if iso in known else None,
                                                                "ne": f["properties"]["NAME"]}, 0.02))

    OUT.mkdir(parents=True, exist_ok=True)
    dump = lambda p, o: (OUT / p).write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")))
    dump("world.json", {"type": "FeatureCollection", "features": [f for f in world if f]})
    dump("zones.json", {"type": "FeatureCollection", "features": [f for f in zones if f]})
    dump("info.json", {"fetched": adv["fetched"], "source": adv["source"], "countries": info})

    n = sum(1 for r in info.values() if r["level"])
    stale = [r["slug"] for r in info.values() if r.get("stale")]
    unmapped = [r["slug"] for r in info.values() if r.get("unmapped")]
    print(f"{n} land med advarsel, {len(zones)} soner. Endret siden kartlegging: {stale or '-'}. "
          f"Ikke kartlagt: {unmapped or '-'}")
    return stale, unmapped


def stamp(slugs):
    adv = json.loads((DATA / "advisories.json").read_text())["countries"]
    path = DATA / "reviewed.json"
    reviewed = json.loads(path.read_text()) if path.exists() else {}
    for s in slugs:
        reviewed[s] = adv[s].get("hash")
    path.write_text(json.dumps(dict(sorted(reviewed.items())), indent=1) + "\n")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--stamp"]:
        stamp(sys.argv[2:])
    elif sys.argv[1:2] == ["--stamp-all"]:
        stamp([k for k in json.loads((DATA / "regions.json").read_text()) if not k.startswith("_")])
    else:
        stale, unmapped = build()
        if "--strict" in sys.argv and (stale or unmapped):
            sys.exit(2)
