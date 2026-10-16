#!/usr/bin/env python3
"""Bygg kartdata fra data/advisories.json + data/regions.json.

Skriver:
  site/data/world.json   alle land (Natural Earth 1:50m), forenklet, med iso3
  site/data/zones.json   GeoJSON med én flate per (land, nivå, sone)
  site/data/info.json    tekst, lenker og status per land
  site/data/timeline.json        tidslinjen: nivå og tekst per land over tid
  site/data/timeline_zones.json  tegnede soner for historiske tekster (data/history_regions/)

  python scraper/build.py               bygg
  python scraper/build.py --stamp SLUG  marker kartleggingen av SLUG som oppdatert
  python scraper/build.py --stamp-all
  python scraper/build.py --missing-history-zones [UD-NØKKEL ...]
                                        historiske regionale tekster uten tegnede soner
"""
import hashlib
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
import history
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


def paint(spec_zones, country, ne, proj, iso):
    """[(geom, sone)] i rekkefølge; senere soner skjærer bort det de dekker fra tidligere.
    outside=True: ikke klipp til Natural Earths landegrense (Krym ligger i RUS der)."""
    painted = []
    for z in spec_zones:
        g = zone_geom(z, country, ne, proj, iso)
        if not z.get("outside"):
            g = g.intersection(country)
        painted = [(pg.difference(g), pz) for pg, pz in painted]
        painted.append((g, z))
    return [(g, z) for g, z in painted if not g.is_empty and z["level"] != "none"]


def text_hash(paragraphs):
    """Samme hash som scrape.py lagrer for gjeldende tekst."""
    return hashlib.sha1(" ".join(paragraphs).encode()).hexdigest()[:12]


HISTORY_REGIONS = DATA / "history_regions"


def load_history_regions(keys=None):
    """{UD-nøkkel: {hash: [soner]}} fra data/history_regions/<nøkkel>.json.
    {"same": "<hash>"} gjenbruker sonene til en annen tekst for samme land."""
    out = {}
    for path in sorted(HISTORY_REGIONS.glob("*.json")):
        if keys is not None and path.stem not in keys:
            continue
        raw = {k: v for k, v in json.loads(path.read_text()).items() if not k.startswith("_")}
        out[path.stem] = {h: raw[v["same"]]["zones"] if "same" in v else v["zones"] for h, v in raw.items()}
    return out


def zones_level(zones):
    """(nivå, delvis) for en tegnet tekst: strengeste nivå, og om den bare gjelder deler av landet."""
    levels = {z["level"] for z in zones if z["level"] != "none"}
    whole = len(zones) == 1 and zones[0].get("country")
    return ("all" if "all" in levels else "necessary" if levels else None), not whole


def slugify_no(v):
    """Samme som LegeOnlines slugifyNo (app/src/utils/vaccineSlugs.js)."""
    import unicodedata
    v = v.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a")
    v = "".join(ch for ch in unicodedata.normalize("NFKD", v) if not unicodedata.combining(ch))
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", v))


def auto_level(paragraphs):
    txt = " ".join(paragraphs).lower()
    return "necessary" if "nødvendig" in txt else "all"


def history_level(paragraphs):
    """(nivå, delvis) for en historisk tekst uten tegnede soner. Bare aktsomhet = ingen advarsel.
    Regionale advarsler vises som skravert hele land, som ukartlagte advarsler i dag."""
    txt = " ".join(paragraphs).lower()
    has_all = bool(re.search(r"(fraråder|advarer mot) alle reise|frarådes mot alle|alle reiser .{0,80}frarådes", txt))
    has_nec = "nødvendig" in txt
    if not (has_all or has_nec or "fraråd" in txt or "advarer mot" in txt):
        return None, False
    rest = re.search(r"øvrige deler|resten av landet|for øvrig|landet for øvrig", txt)
    if has_nec and rest:
        return "necessary", False
    level = "all" if has_all else "necessary"
    return level, bool(REGIONAL_HINTS.search(txt))


def timeline(hist, info, lands, hregions=None):
    """Per land (ISO): [[fra, nivå|None|"?", delvis, tekstindeks, hash]] eldst først, og tekstene.
    "?" = ukjent (ingen arkivdata), "listed" = på UDs liste over reiseråd, men teksten er ikke arkivert. hash = tekst-hash, "" uten tekst; har teksten
    tegnede soner i data/history_regions/, ligger de i timeline_zones.json under "ISO:hash". Land uten advarsel på landsider.no i perioden
    oversiktene dekker, regnes som uten advarsel der."""
    texts, index, out = [], {}, {}
    list_first, list_last = lands.get("list_first"), lands.get("list_last")
    for iso, rec in info.items():
        entries = hist.get(rec["key"], [])
        rows = []
        drawn = (hregions or {}).get(rec["key"], {})
        if list_first and rec["key"] not in lands.get("countries", {}):
            rows += [[list_first, None, 0, -1, ""], [list_last, "?", 0, -1, ""]]
        for h in entries:
            if rows and h["from"] < rows[-1][0]:
                continue
            if h.get("gap"):
                rows.append([h["from"], "?", 0, -1, ""])
                continue
            if h.get("listed"):
                rows.append([h["from"], "listed", 1, -1, ""])
                continue
            hsh = text_hash(h["paragraphs"]) if h["paragraphs"] else ""
            level, partial = zones_level(drawn[hsh]) if hsh in drawn else history_level(h["paragraphs"])
            t = " ".join(h["paragraphs"])
            if t and t not in index:
                index[t] = len(texts)
                texts.append(t)
            rows.append([h["from"], level, int(partial), index.get(t, -1), hsh])
        # Fyll hull mellom kildene: fra slutten av landsider til første senere kilde er ukjent.
        if rows:
            out[iso] = rows
    start = min(r[0][0] for r in out.values())
    return {"start": start, "countries": out, "texts": texts}


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
        # slug = adressen (/land/<slug>/, #<slug>), laget fra det norske navnet som
        # hos LegeOnline; key = UDs egen nøkkel, som regions.json bruker.
        rec = {"slug": slugify_no(c["name"]), "key": slug, "name": c["name"], "url": c["url"],
               "level": None, "ingress": c.get("ingress", "")}
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
        levels = set()
        for g, z in paint(spec["zones"], country, ne, Proj(country), iso):
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
    # Reisevaksine-boksen gir mening utenfor Europa, Nord-Amerika, Australia og New Zealand.
    for f in ne_feats:
        p = f["properties"]
        iso = next((k for k, v in MERGE.items() if p["ADM0_A3"] in v), p["ADM0_A3"])
        if iso in info and p["CONTINENT"] not in ("Europe", "North America", "Antarctica") and iso not in ("AUS", "NZL"):
            info[iso]["vax"] = True
        if iso in info and p["SUBREGION"] in ("Central America", "Caribbean"):
            info[iso]["vax"] = True
    # ISO2 per land, så andre sider (legeonline.no) kan slå opp på landkode.
    for f in ne_feats:
        p = f["properties"]
        iso = next((k for k, v in MERGE.items() if p["ADM0_A3"] in v), p["ADM0_A3"])
        a2 = p["ISO_A2"] if p["ISO_A2"] != "-99" else p["ISO_A2_EH"]
        if iso in info and a2 and a2 != "-99":
            info[iso].setdefault("iso2", a2)
    # Egen vaksineside hos LegeOnline for landet, der den finnes (tools/legeonline_slugs.py).
    lo = json.loads((DATA / "legeonline.json").read_text())
    for iso, rec in info.items():
        if iso in lo:
            rec["vax"] = True
            rec["vax_url"] = f'{site["vax_url"].rstrip("/")}/{lo[iso]}'
        elif rec.get("vax"):
            rec["vax_url"] = site["vax_url"]
    # Egen side for land med advarsel i dag, og for land som har hatt en tidligere eller omtales i UDs nyheter
    # eller i avisene (Nasjonalbiblioteket).
    hist, news, press = history.build(), history.news(), history.press()
    for rec in info.values():
        old = hist.get(rec["key"], [])[:-1]
        rec["history"] = (bool(old) if rec["level"] else any(h["paragraphs"] for h in old)) or rec["key"] in news or rec["key"] in press
        rec["page"] = bool(rec["level"]) or rec["history"]
    dump("info.json", {"fetched": adv["fetched"], "source": adv["source"],
                       "publisher": site["publisher"], "countries": info})
    lands = json.loads((DATA / "history_landsider.json").read_text()) if (DATA / "history_landsider.json").exists() else {}
    hregions = load_history_regions()
    dump("timeline.json", timeline(hist, info, lands, hregions))
    dump("timeline_zones.json", history_zones(hist, info, ne, hregions))
    n_pages = pages.write_all(OUT.parent, info, ne, zones_by_iso, adv["fetched"], site, hist, news, press)

    n = sum(1 for r in info.values() if r["level"])
    stale = [r["slug"] for r in info.values() if r.get("stale")]
    unmapped = [r["slug"] for r in info.values() if r.get("unmapped")]
    print(f"{n_pages} sider i sitemap.")
    print(f"{n} land med advarsel, {len(zones)} soner. Endret siden kartlegging: {stale or '-'}. "
          f"Ikke kartlagt: {unmapped or '-'}")
    return stale, unmapped


HIST_TOL = 0.01


def polygonal(g):
    """Bare flatene: snitt og forenkling kan etterlate linjer og punkter langs kanter."""
    if g.geom_type in ("Polygon", "MultiPolygon"):
        return g
    return unary_union([p for p in getattr(g, "geoms", []) if p.geom_type in ("Polygon", "MultiPolygon")])


def history_zones(hist, info, ne, hregions):
    """{"ISO:hash": [features] | "ISO:annen-hash"} for historiske tekster med tegnede soner.
    Lastes først når noen drar i tidslinjen. Like soner lagres én gang (streng = samme som),
    og flatene forenkles til ~1 km og tre desimaler for å holde filen liten."""
    iso_of_key = {rec["key"]: iso for iso, rec in info.items()}
    out, seen = {}, {}
    for key, texts in hregions.items():
        iso = iso_of_key.get(key)
        if iso is None or iso not in ne:
            raise SystemExit(f"history_regions/{key}.json: ukjent UD-nøkkel")
        known = {text_hash(h["paragraphs"]) for h in hist.get(key, []) if h["paragraphs"]}
        unknown = set(texts) - known
        if unknown:
            raise SystemExit(f"history_regions/{key}.json: fant ikke tekstene {sorted(unknown)} i historikken")
        country = ne[iso]
        proj = Proj(country)
        for hsh, zones in texts.items():
            feats = []
            for g, z in paint(zones, country, ne, proj, iso):
                props = {"iso": iso, "level": z["level"], "label": z.get("label", "")}
                for k in ("partial", "approx"):
                    if z.get(k):
                        props[k] = True
                g = polygonal(g.simplify(HIST_TOL, preserve_topology=True))
                if g.is_empty:
                    continue
                m = mapping(g)
                feats.append({"type": "Feature", "properties": props,
                              "geometry": {"type": m["type"], "coordinates": round_coords(m["coordinates"], 3)}})
            k = f"{iso}:{hsh}"
            first = seen.setdefault(json.dumps(feats, sort_keys=True), k)
            out[k] = feats if first == k else first
    return out


def missing_history_zones(keys=()):
    """Historiske tekster som ser regionale ut og mangler soner, gruppert per land.
    Gjeldende tekst hører til regions.json og telles ikke, heller ikke eldre perioder med samme tekst.
    Med UD-nøkler: skriv ut hele teksten, klar til å tegne."""
    hist, hregions = history.build(), load_history_regions()
    total, out = 0, []
    for key in sorted(hist):
        if keys and key not in keys:
            continue
        entries = hist[key]
        current = text_hash(entries[-1]["paragraphs"]) if entries[-1]["paragraphs"] else ""
        drawn, seen, todo = hregions.get(key, {}), set(), []
        for h in entries[:-1]:
            if not h["paragraphs"] or h.get("gap"):
                continue
            hsh = text_hash(h["paragraphs"])
            if hsh in drawn or hsh == current or hsh in seen:
                continue
            seen.add(hsh)
            level, _ = history_level(h["paragraphs"])
            if level and REGIONAL_HINTS.search(" ".join(h["paragraphs"])):
                todo.append((hsh, h, level))
        if todo:
            total += len(todo)
            out.append((key, todo))
    for key, todo in sorted(out, key=lambda x: (-len(x[1]), x[0])):
        print(f"{key}: {len(todo)}")
        for hsh, h, level in todo:
            t = " ".join(h["paragraphs"])
            print(f"  {hsh}  {h['from']}–{h['until'] or ''}  {level}  {t if keys else t[:110] + ('…' if len(t) > 110 else '')}")
    print(f"{total} tekster i {len(out)} land mangler soner (data/history_regions/<nøkkel>.json).")


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
    elif sys.argv[1:2] == ["--missing-history-zones"]:
        missing_history_zones(sys.argv[2:])
    elif sys.argv[1:2] == ["--stamp-all"]:
        stamp([k for k in json.loads((DATA / "regions.json").read_text()) if not k.startswith("_")])
    else:
        stale, unmapped = build()
        if "--strict" in sys.argv and (stale or unmapped):
            sys.exit(2)
