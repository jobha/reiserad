#!/usr/bin/env python3
"""Hent eldre reiseadvarsler fra Wayback Machine (web.archive.org) og skriv
data/history_archive.json, som scraper/history.py legger foran git-historikken.

Kjøres for hånd (ikke i CI):  python3 tools/wayback_history.py [slug ...]

Rå kopier caches i .cache/wayback/, så en avbrutt kjøring kan fortsette.
Datoene er datoen for arkivkopien, ikke når UD endret teksten, og er derfor omtrentlige.

UD har brukt to faktaboks-utforminger: «Reiseadvarsel for X» (i dag) og
«X - reiseråd» (rundt 2018–2021). Boksen «Reiseråd for alle land» (korona) hoppes
over. Før faktaboksene sto advarslene i løpende tekst; de kopiene brukes ikke,
og en kopi uten advarselsboks teller bare som «ingen advarsel» etter at boksene
ble tatt i bruk (FIRST_BOX).
"""
import gzip
import hashlib
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))
from scrape import text  # noqa: E402

CACHE = ROOT / ".cache" / "wayback"
OUT = ROOT / "data" / "history_archive.json"
UA = "reiserad-kart/1.0 (+https://xn--reiserd-jxa.no; historikk fra web.archive.org)"
# «Reiseadvarsel for X» eller «X - reiseråd». Ikke «Reiseråd for alle land» / «Hva er UDs reiseråd …».
COUNTRY_BOX = re.compile(r"^reiseadvarsel\b|\s[-–]\s*reiseråd$", re.I)
WORKERS = 2
MAX_GAP_DAYS = 183
FIRST_BOX = "2018-01-01"  # justeres etter første kjøring, se main()


def get(url, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            return data.decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                raise
            wait = 30 * (i + 1) if isinstance(e, urllib.error.HTTPError) and e.code == 429 else 5 * (i + 1)
            print(f"  vent {wait}s ({e})", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"ga opp: {url}")


def captures(url):
    """[(timestamp, original)] med distinkt innhold, eldste først."""
    path = re.sub(r"^https?://", "", url)
    prefix = re.sub(r"id\d+/?$", "", path)  # id-nummeret har endret seg opp gjennom årene
    segment = "/" + prefix.rstrip("/").rsplit("/", 1)[1].lower() + "/"
    q = urllib.parse.urlencode({"url": prefix, "matchType": "prefix", "output": "json",
                                "fl": "timestamp,original,digest", "filter": "statuscode:200"})
    rows = json.loads(get("https://web.archive.org/cdx/search/cdx?" + q) or "[]")[1:]
    seen, out = set(), []
    for ts, orig, digest in sorted(rows):
        # CDX matcher prefikset uten avsluttende skråstrek: reiseinfo_uk/ treffer også reiseinfo_ukraina/.
        if digest in seen or not re.search(r"/id\d+/?(\?|$)", orig) or segment not in orig.lower():
            continue
        seen.add(digest)
        out.append((ts, orig))
    return out


def fetch(ts, orig):
    f = CACHE / f"{hashlib.sha1(f'{ts} {orig}'.encode()).hexdigest()}.html"
    if f.exists():
        return f.read_text()
    page = get(f"https://web.archive.org/web/{ts}id_/{orig}")
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(page)
    time.sleep(1)
    return page


def parse(page):
    """("box", advarsel|None) hvis siden har faktaboks-utformingen, ellers (None, None)."""
    boxes = list(re.finditer(
        r'<div class="factbox"[^>]*>(.*?)<div id="factbox\d+" class="factbox-content">(.*?)</div>', page, re.S))
    global_box = False
    for fb in boxes:
        head, body = fb.groups()
        h = re.search(r'class="factbox-title">(.*?)</h[23]>', head, re.S)
        title = text(h.group(1)) if h else ""
        if not COUNTRY_BOX.search(title):
            global_box = global_box or "reiseråd" in title.lower()
            continue
        pre = re.search(r'class="factbox-pre-title">(.*?)</p>', head, re.S)
        paras = [p for p in (text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S)) if p] or [text(body)]
        return "box", {"title": title, "status": text(pre.group(1)) if pre else "", "paragraphs": paras}
    # Bare det globale koronarådet (2020–21): landets egen status er ukjent.
    return ("box", None) if boxes and not global_box else (None, None)


def country(url):
    """Halvering: er advarselen lik i begge ender av et intervall som er kortere enn
    MAX_GAP_DAYS, hentes ikke kopiene imellom. Wayback struper hardt, og de fleste land
    har få endringer. Lengre intervaller deles uansett, så en advarsel som kom og gikk
    mellom to like kopier bare kan bli oversett hvis den varte kortere enn det."""
    caps = captures(url)
    seen = {}

    def snap(i):
        if i not in seen:
            ts, orig = caps[i]
            seen[i] = None
            try:
                page = fetch(ts, orig)
            except Exception as e:  # noqa: BLE001
                print(f"  hopper over {ts}: {e}", file=sys.stderr)
                return None
            if "reiseinformasjon" in page.lower():  # ellers feilside, omdirigering e.l.
                layout, w = parse(page)
                seen[i] = {"date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "layout": layout, "warning": w}
        return seen[i]

    def key(s):
        return None if s is None else (s["layout"], s["warning"]["paragraphs"] if s["warning"] else None)

    def days(i, j):
        a, b = (datetime.strptime(caps[k][0][:8], "%Y%m%d") for k in (i, j))
        return (b - a).days

    def bisect(lo, hi):
        a, b = snap(lo), snap(hi)
        if hi - lo <= 1:
            return
        if a is not None and b is not None and key(a) == key(b) and days(lo, hi) <= MAX_GAP_DAYS:
            return
        mid = (lo + hi) // 2
        bisect(lo, mid)
        bisect(mid, hi)

    if caps:
        bisect(0, len(caps) - 1)
    return [seen[i] for i in sorted(seen) if seen[i]]


def collapse(snaps, first_box):
    """Like tekster etter hverandre slås sammen; kopier uten advarsel før first_box hoppes over."""
    entries = []
    for s in snaps:
        w = s["warning"]
        if not w and (s["layout"] is None or s["date"] < first_box):
            continue
        paragraphs = w["paragraphs"] if w else []
        if entries and entries[-1]["paragraphs"] == paragraphs:
            if w:
                entries[-1]["status"] = w["status"]
            continue
        entries.append({"from": s["date"], "status": w["status"] if w else "", "paragraphs": paragraphs})
    return entries


def main():
    adv = json.loads((ROOT / "data" / "advisories.json").read_text())["countries"]
    only = set(sys.argv[1:])
    raw_path = CACHE / "snapshots.json"
    raw = json.loads(raw_path.read_text()) if raw_path.exists() else {}
    # Land med advarsel i dag først: bare de har egen side.
    todo = sorted(((k, c) for k, c in adv.items() if (k in only if only else k not in raw)),
                  key=lambda kc: (not kc[1].get("warning"), kc[0]))
    lock = threading.Lock()

    def one(item):
        key, c = item
        try:
            snaps = country(c["url"])
        except Exception as e:  # noqa: BLE001
            print(f"  FEIL {key}: {e}", file=sys.stderr)
            return
        with lock:
            raw[key] = snaps
            CACHE.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(json.dumps(raw, ensure_ascii=False))
            print(f"{len(raw):3d}/{len(adv)} {key} ({len(snaps)} kopier)", file=sys.stderr)

    # Noen få parallelle land; Wayback avviser tilkoblinger hvis det går for fort.
    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(one, todo))

    # Første dato der noe land har en advarselsboks: fra da betyr «ingen boks» «ingen advarsel».
    boxed = [s["date"] for snaps in raw.values() for s in snaps if s["warning"]]
    first_box = min(boxed) if boxed else FIRST_BOX
    hist = {k: e for k, e in ((k, collapse(v, first_box)) for k, v in sorted(raw.items())) if e}
    OUT.write_text(json.dumps({"source": "web.archive.org", "first_box": first_box, "countries": hist},
                              ensure_ascii=False, indent=1) + "\n")
    print(f"{len(hist)} land med arkivhistorikk fra {first_box} -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
