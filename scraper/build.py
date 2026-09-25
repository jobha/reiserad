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

import shapely
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import transform, unary_union

import gb
import pages

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "site" / "data"
NE_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
CACHE = Path(os.environ.get("REISERAD_CACHE", ROOT / ".cache"))
NE_PATH = CACHE / "ne_50m_admin_0_countries.geojson"
PLACES_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_populated_places_simple.geojson"
PLACES_PATH = CACHE / "ne_10m_populated_places_simple.geojson"

WORLD_TOL = 0.03

# Natural Earth deler noen land i flere flater; UD har én side.
MERGE = {"SOM": ["SOM", "SOL"], "CYP": ["CYP", "CYN"]}

REGIONAL_HINTS = re.compile(
    r"område|region|provins|grense|delstat|distrikt|fylke|bortsett|unntatt|unntak|"
    r"utenfor|innenfor|nærmere enn|\bkm\b|kilometer|hovedstad|byen|øya|øyer",
    re.I,
)


def fetch(url, path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, path)
    return json.loads(path.read_text())


NAMES = {k: v for k, v in json.loads((DATA / "names.json").read_text()).items() if not k.startswith("_")}


def labels(ne_feats, info):
    """Egne kartetiketter (landnavn på norsk, byer), så kartet ikke trenger flisleverandør."""
    countries = []
    for f in ne_feats:
        p = f["properties"]
        if p["ADM0_A3"] in ("SOL", "CYN"):
            continue
        rec = info.get(p["ADM0_A3"])
        name = rec["name"] if rec else NAMES.get(p["ADM0_A3"], p["NAME"])
        countries.append([name, round(p["LABEL_X"], 2), round(p["LABEL_Y"], 2), p["MIN_LABEL"]])
    places = []
    for f in fetch(PLACES_URL, PLACES_PATH)["features"]:
        p = f["properties"]
        if p["min_zoom"] <= 7:
            places.append([p["name"], round(p["longitude"], 3), round(p["latitude"], 3),
                           p["min_zoom"], 1 if p["adm0cap"] else 0])
    places.sort(key=lambda r: (r[3], -r[4]))
    return {"countries": countries, "places": places}


def load_ne():
    fetch(NE_URL, NE_PATH)
    feats = json.loads(NE_PATH.read_text())["features"]
    # Forenkle alle land samlet, så naboer deler nøyaktig samme grenselinje
    # (ingen glipper eller overlapp). Alt annet bygges på disse flatene og
    # forenkles ikke på nytt.
    simple = shapely.coverage_simplify([shape(f["geometry"]).buffer(0) for f in feats], WORLD_TOL)
    for f, g in zip(feats, simple):
        f["geom"] = g
    geoms = {}
    for f in feats:
        geoms.setdefault(f["properties"]["ADM0_A3"], []).append(f["geom"])
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


SNAP_KM = 12


def adm_geom(ref, names, country=None, proj=None):
    """Regioner fra geoBoundaries. Med country: strekk regionene ut til Natural
    Earths landegrense, siden de to kildene tegner grensen litt ulikt og
    ellers etterlater hvite striper langs grensen."""
    iso, adm = ref.split("/")
    feats = gb.load(iso, adm)["features"]
    picked = [f for f in feats if f["properties"]["shapeName"] in names]
    missing = set(names) - {f["properties"]["shapeName"] for f in picked}
    if missing:
        raise SystemExit(f"{ref}: fant ikke {sorted(missing)}")
    g = unary_union([shape(f["geometry"]).buffer(0) for f in picked])
    if country is None:
        return g
    everything = unary_union([shape(f["geometry"]).buffer(0) for f in feats])
    uncovered = country.difference(everything)
    return g.union(proj.buffer(g, SNAP_KM).intersection(uncovered))


def zone_geom(z, country, ne, proj, iso=None):
    if z.get("country"):
        g = country
    elif "adm" in z:
        same = z["adm"].split("/")[0] == iso
        g = adm_geom(z["adm"], z["names"], country if same else None, proj)
    elif "border" in z:
        nb = unary_union([ne[i] for i in z["border"] if i in ne])
        if "clip" in z:
            from shapely.geometry import box
            nb = nb.intersection(box(*z["clip"]))
        g = proj.buffer(nb, z["km"])
    elif "near" in z:
        g = proj.buffer(zone_geom(z["near"], country, ne, proj, iso), z["km"])
    elif "poly" in z:
        g = shape({"type": "Polygon", "coordinates": [z["poly"] + [z["poly"][0]]]})
    elif "point" in z:
        g = proj.buffer(Point(z["point"]), z["km"])
    elif "line" in z:
        g = proj.buffer(LineString(z["line"]), z["km"])
    else:
        raise SystemExit(f"ukjent sone: {z}")
    if "and" in z:
        g = g.intersection(zone_geom(z["and"], country, ne, proj, iso))
    return g


def auto_level(paragraphs):
    txt = " ".join(paragraphs).lower()
    return "necessary" if "nødvendig" in txt else "all"


def round_coords(obj, nd=4):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(v, nd) for v in obj]
        return [round_coords(v, nd) for v in obj]
    return obj


def feature(geom, props):
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
    zones_by_iso = {}  # iso -> [(geom, level, partial, label)] til landsidene
    for slug, c in adv["countries"].items():
        iso = iso_of[slug]
        rec = {"slug": slug, "name": c["name"], "url": c["url"], "level": None, "ingress": c.get("ingress", "")}
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
                zones.append(feature(country, {"iso": iso, "level": level, "partial": True, "unmapped": True}))
                zones_by_iso[iso] = [(country, level, True, "")]
            else:
                zones.append(feature(country, {"iso": iso, "level": level, "label": "Hele landet"}))
                zones_by_iso[iso] = [(country, level, False, "")]
            continue

        if reviewed.get(slug) != c.get("hash"):
            rec["stale"] = True
        proj = Proj(country)
        painted = []  # [(geom, zone)]
        for z in spec["zones"]:
            g = zone_geom(z, country, ne, proj, iso).intersection(country)
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
                zones_by_iso.setdefault(iso, []).append((g, z["level"], bool(z.get("partial")), z.get("label", "")))
        rec["level"] = "all" if "all" in levels else "necessary"
        rec["regional"] = True
        rec["exceptions"] = [z["label"] for z in spec["zones"] if z["level"] == "none"]

    known = set(info)
    world = []
    for f in ne_feats:
        a3 = f["properties"]["ADM0_A3"]
        iso = next((k for k, v in MERGE.items() if a3 in v), a3)
        name = info[iso]["name"] if iso in info else NAMES.get(a3, f["properties"]["NAME"])
        world.append(feature(f["geom"], {"iso": iso if iso in known else None, "ne": name}))

    OUT.mkdir(parents=True, exist_ok=True)
    dump = lambda p, o: (OUT / p).write_text(json.dumps(o, ensure_ascii=False, separators=(",", ":")))
    dump("world.json", {"type": "FeatureCollection", "features": [f for f in world if f]})
    dump("zones.json", {"type": "FeatureCollection", "features": [f for f in zones if f]})
    dump("labels.json", labels(ne_feats, info))
    site = json.loads((DATA / "site.json").read_text())
    dump("info.json", {"fetched": adv["fetched"], "source": adv["source"],
                       "donate": site.get("donate_url") or None, "countries": info})
    n_pages = pages.write_all(OUT.parent, info, ne, zones_by_iso, adv["fetched"], site.get("donate_url"))

    n = sum(1 for r in info.values() if r["level"])
    stale = [r["slug"] for r in info.values() if r.get("stale")]
    unmapped = [r["slug"] for r in info.values() if r.get("unmapped")]
    print(f"{n_pages} sider i sitemap.")
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
