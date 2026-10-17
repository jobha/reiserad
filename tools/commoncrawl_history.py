#!/usr/bin/env python3
"""Hent UDs landsider fra Common Crawl (index.commoncrawl.org) for perioder Wayback Machine
mangler, særlig feb. 2018 – apr. 2019. Skriver .cache/commoncrawl/snapshots.json i samme form
som .cache/wayback/snapshots.json; tools/wayback_history.py slår dem sammen før den skriver
data/history_archive.json.

Kjøres for hånd (ikke i CI):  python3 tools/commoncrawl_history.py [--old] [CC-MAIN-2018-05 ...]

--old: også alle runder 2008–2017, med landsider.no (hele domenet) og regjeringen.no/…/velg-reiserad.
Disse kopiene leses med tools/landsider_history.py sin parser og skrives til
.cache/commoncrawl/landsider_rows.json, som landsider_history.py slår sammen med Wayback-kopiene.

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
OLD = ["CC-MAIN-2008-2009", "CC-MAIN-2009-2010", "CC-MAIN-2012", "CC-MAIN-2013-20", "CC-MAIN-2013-48",
       "CC-MAIN-2014-10", "CC-MAIN-2014-15", "CC-MAIN-2014-23", "CC-MAIN-2014-35", "CC-MAIN-2014-41", "CC-MAIN-2014-42",
       "CC-MAIN-2014-49", "CC-MAIN-2014-52", "CC-MAIN-2015-06", "CC-MAIN-2015-11", "CC-MAIN-2015-14", "CC-MAIN-2015-18",
       "CC-MAIN-2015-22", "CC-MAIN-2015-27", "CC-MAIN-2015-32", "CC-MAIN-2015-35", "CC-MAIN-2015-40", "CC-MAIN-2015-48",
       "CC-MAIN-2016-07", "CC-MAIN-2016-18", "CC-MAIN-2016-22", "CC-MAIN-2016-26", "CC-MAIN-2016-30", "CC-MAIN-2016-36",
       "CC-MAIN-2016-40", "CC-MAIN-2016-44", "CC-MAIN-2016-50", "CC-MAIN-2017-04", "CC-MAIN-2017-09", "CC-MAIN-2017-13",
       "CC-MAIN-2017-17", "CC-MAIN-2017-22", "CC-MAIN-2017-26", "CC-MAIN-2017-30", "CC-MAIN-2017-34", "CC-MAIN-2017-39",
       "CC-MAIN-2017-43", "CC-MAIN-2017-47", "CC-MAIN-2017-51"]


def get(url, headers=None, tries=20):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            if getattr(e, "code", None) in (400, 404):
                return b""  # 400: siden finnes ikke i indeksen (eller spørringen støttes ikke i eldre runder)
            print(f"  vent {min(60, 5 * (i + 1))}s ({e})", file=sys.stderr)
            time.sleep(min(60, 5 * (i + 1)))
    raise RuntimeError(f"ga opp: {url}")


DATA = "https://data.commoncrawl.org/cc-index/collections/{crawl}/indexes/{name}"


def _line_at(crawl, size, pos):
    """Første hele linje i cluster.idx fra byte pos: (start, linje)."""
    raw = get(DATA.format(crawl=crawl, name="cluster.idx"), {"Range": f"bytes={pos}-{min(size, pos + 8192) - 1}"})
    if pos:
        cut = raw.find(b"\n")
        raw, pos = raw[cut + 1:], pos + cut + 1
    return pos, raw.split(b"\n", 1)[0].decode("utf-8", "replace")


def index_direct(crawl, surt):
    """Treff for SURT-prefikset rett fra indeksfilene på data.commoncrawl.org (som indeksserveren
    gjør): halvering i cluster.idx med Range-kall, så bare de aktuelle cdx-blokkene hentes."""
    import gzip as _gz
    size = int(urllib.request.urlopen(urllib.request.Request(
        DATA.format(crawl=crawl, name="cluster.idx"), method="HEAD", headers={"User-Agent": UA}), timeout=60)
        .headers["Content-Length"])
    lo, hi = 0, size
    while hi - lo > 8192:  # siste linje med nøkkel < prefikset
        mid = (lo + hi) // 2
        _, line = _line_at(crawl, size, mid)
        if line.split(" ", 1)[0] < surt:
            lo = mid
        else:
            hi = mid
    pos, blocks = lo, []
    while pos < size:
        raw = get(DATA.format(crawl=crawl, name="cluster.idx"), {"Range": f"bytes={pos}-{min(size, pos + 65536) - 1}"})
        if pos == lo and lo:
            raw = raw[raw.find(b"\n") + 1:]
        lines = raw.decode("utf-8", "replace").split("\n")
        done = False
        for line in lines[:-1]:
            f = line.split("\t")
            if len(f) < 4:
                continue
            key = f[0].split(" ", 1)[0]
            if blocks and key > surt and not key.startswith(surt):
                done = True
                break
            if key <= surt or key.startswith(surt):
                blocks = blocks[-1:] if key <= surt and not key.startswith(surt) else blocks
                blocks.append((f[1], int(f[2]), int(f[3])))
        if done or len(lines) < 2:
            break
        pos += len(raw) - len(lines[-1].encode())
    rows = []
    for name, off, length in blocks:
        data = _gz.decompress(get(DATA.format(crawl=crawl, name=name), {"Range": f"bytes={off}-{off + length - 1}"}))
        for line in data.decode("utf-8", "replace").splitlines():
            key, ts, js = line.split(" ", 2)
            if key.startswith(surt):
                rows.append(json.loads(js) | {"timestamp": ts})
    return rows


def index(crawl, url=PREFIX, match=None, tag=""):
    """Alle treff i én runde, side for side (indeksserveren deler store svar opp)."""
    f = CACHE / f"index-{crawl}{tag}.json"
    if f.exists():
        return json.loads(f.read_text())
    base = {"url": url, "output": "json"}
    if match:
        base["matchType"] = match
    api = f"https://index.commoncrawl.org/{crawl}-index?"
    pages = json.loads(get(api + urllib.parse.urlencode({**base, "showNumPages": "true"})) or b'{"pages": 0}').get("pages", 0)
    rows = []
    for page in range(pages):
        for attempt in range(4):  # avkuttede svar forekommer: hent siden på nytt
            body = get(api + urllib.parse.urlencode({**base, "page": page})).decode("utf-8", "replace")
            try:
                rows += [json.loads(line) for line in body.splitlines() if line.strip().startswith("{")]
                break
            except json.JSONDecodeError:
                print(f"  avkuttet svar, prøver igjen ({crawl} side {page})", file=sys.stderr)
                time.sleep(10)
        else:
            raise RuntimeError(f"avkuttet svar fra {crawl} side {page}")
    rows = [r for r in rows if str(r.get("status", "200")) == "200"]
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
    body = gzip.decompress(raw)
    # WARC: WARC-hode, HTTP-hode, innhold. ARC (2008–2012): én hodelinje + HTTP-hode, innhold.
    parts = body.split(b"\r\n\r\n", 2 if body.startswith(b"WARC/") else 1)
    raw_html = parts[-1]
    m = re.search(rb"charset=([\w-]+)", b"\r\n\r\n".join(parts[:-1]) + raw_html[:2000], re.I)
    enc = m.group(1).decode() if m else "utf-8"
    try:
        html = raw_html.decode(enc, "replace")
    except LookupError:
        html = raw_html.decode("utf-8", "replace")
    f.write_text(html)
    time.sleep(0.3)
    return html


def landsider_rows():
    """Kopier av landsider.no og regjeringen.no/…/velg-reiserad i rundene 2008–2018, lest som i
    tools/landsider_history.py (samme radformat som dens .cache/wayback/landsider.json)."""
    import landsider_history as lh
    rows, seen = [], set()
    for crawl in OLD + CRAWLS[:4]:
        hits = []
        # Domenesøket dekker landsider.no og www.landsider.no; prefikssøkene bare der det ikke gir noe
        # (eldre runder). Indeksserveren er treg, så færrest mulig spørringer.
        f = CACHE / f"index-{crawl}-direct.json"
        if f.exists():
            hits = json.loads(f.read_text())
        else:
            try:
                hits = [h for surt in ("no,landsider)", "no,regjeringen)/no/tema/utenrikssaker/reiseinformasjon/velg-reiserad")
                        for h in index_direct(crawl, surt)]
                hits = [h for h in hits if str(h.get("status", "200")) == "200"]
                f.write_text(json.dumps(hits))
            except Exception as e:  # noqa: BLE001
                print(f"  direkte indeks feilet for {crawl}: {e}", file=sys.stderr)
        for url, match, tag in (() if hits else (("landsider.no", "domain", "-landsider"), ("landsider.no/*", None, "-landsider-p"),
                                ("www.landsider.no/*", None, "-landsider-w"),
                                ("www.regjeringen.no/no/tema/utenrikssaker/reiseinformasjon/velg-reiserad/*", None, "-velgreiserad"))):
            if tag in ("-landsider-p", "-landsider-w") and any("landsider.no" in h["url"] for h in hits):
                continue
            if tag == "-velgreiserad" and crawl < "CC-MAIN-2015":
                continue  # velg-reiserad fantes fra 2016
            try:
                hits += index(crawl, url, match, tag)
            except RuntimeError as e:
                print(f"  HOPPER OVER {crawl}{tag}: {e}", file=sys.stderr)
        n = 0
        for row in hits:
            p = lh.path(row["url"])
            ok = (re.fullmatch(r"/traveladvice(\.html|/([^/]+/)?)?", p) or p.startswith("/velg-reiserad/")
                  or re.fullmatch(r"/land/[^/]+/raad(\.htm)?/?", p) or re.fullmatch(r"/land/[^/]+/?", p))
            if not ok or row.get("digest") in seen or "html" not in row.get("mime", "html"):
                continue
            seen.add(row.get("digest"))
            try:
                page = record(row)
            except Exception as e:  # noqa: BLE001
                print(f"  hopper over {row['url']}: {e}", file=sys.stderr)
                continue
            ts = row["timestamp"]
            rows.append({"date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "path": p, "found": lh.parse(page, p),
                         "source": "commoncrawl"})
            n += 1
        print(f"{crawl}: {len(hits)} treff, {n} sider lest", file=sys.stderr)
        (CACHE / "landsider_rows.json").write_text(json.dumps(rows, ensure_ascii=False))
    print(f"{len(rows)} sider, {sum(1 for r in rows if r['found'])} med funn", file=sys.stderr)


def main():
    if "--old" in sys.argv:
        landsider_rows()
        sys.argv.remove("--old")
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
