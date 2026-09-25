"""Oppdater data/legeonline.json: iso3 -> slug for LegeOnlines vaksinesider per land
(legeonline.no/reisevaksiner/<slug>). Leser den offentlige site_config fra
LegeOnlines Supabase med anon-nøkkelen i ~/legeonline/app/.env. Kjøres for hånd
når LegeOnline legger til land: .venv/bin/python tools/legeonline_slugs.py"""
import json
import re
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = Path.home() / "legeonline/app/.env"
NORDIC = {"NO", "SE", "DK", "IS", "FI"}  # LegeOnline indekserer ikke disse


def slugify_no(v):  # samme som app/src/utils/vaccineSlugs.js
    v = v.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a")
    v = "".join(c for c in unicodedata.normalize("NFKD", v) if not unicodedata.combining(c))
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", v))


env = dict(l.split("=", 1) for l in ENV.read_text().splitlines() if "=" in l and not l.startswith("#"))
url = env["VITE_SUPABASE_URL"].strip().strip('"')
key = env["VITE_SUPABASE_ANON_KEY"].strip().strip('"')
req = urllib.request.Request(f"{url}/rest/v1/site_config?id=eq.main&select=data",
                             headers={"apikey": key, "Authorization": f"Bearer {key}"})
countries = json.loads(urllib.request.urlopen(req, timeout=30).read())[0]["data"]["countries"]

a2_to_a3 = {}
for f in json.loads((ROOT / ".cache/ne_50m_admin_0_countries.geojson").read_text())["features"]:
    p = f["properties"]
    for a2 in (p["ISO_A2"], p["ISO_A2_EH"]):
        if a2 and a2 != "-99":
            a2_to_a3.setdefault(a2, p["ADM0_A3"])

out = {}
for c in countries:
    if c["country_id"] in NORDIC:
        continue
    a3 = a2_to_a3.get(c["country_id"])
    if a3:
        out[a3] = slugify_no(c.get("country_name_no") or c.get("country_name_en") or c["country_id"])
(ROOT / "data/legeonline.json").write_text(json.dumps(dict(sorted(out.items())), ensure_ascii=False, indent=1) + "\n")
print(f"{len(out)} land -> data/legeonline.json")
