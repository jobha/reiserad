"""geoBoundaries (gbOpen, forenklet geometri) med lokal cache i .cache/gb/."""
import json
import os
import urllib.request
from pathlib import Path

CACHE = Path(os.environ.get("REISERAD_CACHE", Path(__file__).resolve().parent.parent / ".cache")) / "gb"
API = "https://www.geoboundaries.org/api/current/gbOpen/{iso}/{adm}/"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "reiserad-kart/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def load(iso, adm):
    """Returnerer FeatureCollection for iso/ADMn (lastes ned første gang)."""
    path = CACHE / f"{iso}-{adm}.geojson"
    if not path.exists():
        meta = json.loads(_get(API.format(iso=iso, adm=adm)))
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_get(meta["simplifiedGeometryGeoJSON"]))
    return json.loads(path.read_text())


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:]:
        iso, adm = arg.split("/")
        names = sorted(f["properties"]["shapeName"] for f in load(iso, adm)["features"])
        print(f"{iso}/{adm} ({len(names)}):", "; ".join(names))
