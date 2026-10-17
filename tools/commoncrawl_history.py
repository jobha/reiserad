#!/usr/bin/env python3
"""Hent UDs landsider fra Common Crawl (index.commoncrawl.org) for perioder Wayback Machine
mangler, særlig feb. 2018 – apr. 2019. Skriver .cache/commoncrawl/snapshots.json i samme form
som .cache/wayback/snapshots.json; tools/wayback_history.py slår dem sammen før den skriver
data/history_archive.json.

Kjøres for hånd (ikke i CI):  python3 tools/commoncrawl_history.py [CC-MAIN-2018-05 ...]

Hver kopi er én WARC-post, hentet med Range fra data.commoncrawl.org og cachet i .cache/commoncrawl/.
"""
import gzip
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from wayback_history import parse  # noqa: E402

CACHE = ROOT / ".cache" / "commoncrawl"
UA = "reiserad-kart/1.0 (+https://xn--reiserd-jxa.no; historikk fra Common Crawl)"
CRAWLS = ["CC-MAIN-2018-05", "CC-MAIN-2018-09", "CC-MAIN-2018-13", "CC-MAIN-2018-17", "CC-MAIN-2018-22",
          "CC-MAIN-2018-26", "CC-MAIN-2018-30", "CC-MAIN-2018-34", "CC-MAIN-2018-39", "CC-MAIN-2018-43",
          "CC-MAIN-2018-47", "CC-MAIN-2018-51", "CC-MAIN-2019-04", "CC-MAIN-2019-09", "CC-MAIN-2019-13",
          "CC-MAIN-2019-18"]
PREFIX = "www.regjeringen.no/no/tema/utenrikssaker/reiseinformasjon/*"


def get(url, headers=None, tries=8):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", None) == 404:
                return b""
            print(f"  vent {5 * (i + 1)}s ({e})", file=sys.stderr)
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"ga opp: {url}")


def index(crawl):
    f = CACHE / f"index-{crawl}.json"
    if f.exists():
        return json.loads(f.read_text())
    q = urllib.parse.urlencode({"url": PREFIX, "output": "json", "filter": "status:200"})
    rows = [json.loads(line) for line in get(f"https://index.commoncrawl.org/{crawl}-index?{q}").decode().splitlines()
            if line.strip()]
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(rows))
    return rows


def record(row):
    """HTML-en i WARC-posten."""
    f = CACHE / f"{hashlib.sha1((row['filename'] + row['offset']).encode()).hexdigest()}.html"
    if f.exists():
        return f.read_text()
    a = int(row["offset"])
    raw = get(f"https://data.commoncrawl.org/{row['filename']}", {"Range": f"bytes={a}-{a + int(row['length']) - 1}"})
    body = gzip.decompress(raw).decode("utf-8", "replace")
    html = body.split("\r\n\r\n", 2)[-1]  # WARC-hode, HTTP-hode, innhold
    f.write_text(html)
    time.sleep(0.3)
    return html


def main():
    adv = json.loads((ROOT / "data" / "advisories.json").read_text())["countries"]
    # Landsidene har samme id-nummer som i dag; ellers brukes navnet i adressen (reiseinfo_kenya).
    by_id, by_seg = {}, {}
    for key, c in adv.items():
        m = re.search(r"/id(\d+)/?$", c["url"])
        if m:
            by_id[m.group(1)] = key
        by_seg[c["url"].rstrip("/").rsplit("/", 2)[-2].lower()] = key
    out, seen = {}, set()
    for crawl in sys.argv[1:] or CRAWLS:
        try:
            rows = index(crawl)
        except RuntimeError as e:
            print(f"  HOPPER OVER {crawl}: {e}", file=sys.stderr)
            continue
        print(f"{crawl}: {len(rows)} kopier", file=sys.stderr)
        for row in rows:
            m = re.search(r"/velg-land/([^/]+)/id(\d+)/?$", row["url"])
            if not m or row.get("mime") != "text/html":
                continue
            key = by_id.get(m.group(2)) or by_seg.get(m.group(1).lower())
            if not key or row["digest"] in seen:
                continue
            seen.add(row["digest"])
            try:
                page = record(row)
            except Exception as e:  # noqa: BLE001
                print(f"  hopper over {row['url']}: {e}", file=sys.stderr)
                continue
            if "reiseinformasjon" not in page.lower():
                continue
            layout, w = parse(page)
            ts = row["timestamp"]
            out.setdefault(key, []).append({"date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "layout": layout,
                                            "warning": w, "source": "commoncrawl"})
    for v in out.values():
        v.sort(key=lambda s: s["date"])
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "snapshots.json").write_text(json.dumps(out, ensure_ascii=False))
    n = sum(len(v) for v in out.values())
    print(f"{n} kopier for {len(out)} land, {sum(1 for v in out.values() for s in v if s['warning'])} med advarsel",
          file=sys.stderr)


if __name__ == "__main__":
    main()
