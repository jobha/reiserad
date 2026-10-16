#!/usr/bin/env python3
"""Reiseråd fra UDs gamle landsider.no (2006–2015), hentet fra Wayback Machine.

Kjøres for hånd:  python3 tools/landsider_history.py [--fetch]

Kilder (alle arkivkopier, cachet i .cache/wayback/ som i wayback_history.py):
- /traveladvice/            oversikt: alle land med offisielt reiseråd på kopidatoen
- /traveladvice/<x>/        «Offisielt reiseråd for X»: tekst (div.intro) og UDs dato
- /land/<x>/                landsiden; sideboksen «Offisielt reiseråd for X» med dato og tekst

Skriver rå funn per kopi til .cache/wayback/landsider.json og historikk per land til
data/history_landsider.json, som scraper/history.py legger foran resten.
"""
import json
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "scraper"))
from scrape import text  # noqa: E402
from wayback_history import CACHE, fetch, get  # noqa: E402

OUT = CACHE / "landsider.json"
HIST = ROOT / "data" / "history_landsider.json"


def cdx(prefix, **extra):
    q = urllib.parse.urlencode({"url": prefix, "matchType": "prefix", "output": "json",
                                "fl": "timestamp,original,digest", "filter": "statuscode:200",
                                "collapse": "digest", **extra})
    return [(ts, orig) for ts, orig, _ in json.loads(get("https://web.archive.org/cdx/search/cdx?" + q) or "[]")[1:]]


def path(orig):
    return re.sub(r"^https?://(www\.)?landsider\.no(:80)?", "", orig).split("?")[0].lower()


def wanted():
    out = []
    for ts, orig in cdx("landsider.no/traveladvice/"):
        p = path(orig)
        if re.fullmatch(r"/traveladvice/([^/]+/)?", p):
            out.append((ts, orig))
    if "--landsider-land" in sys.argv:
        # Landsidene er mange (~3000 kopier) og gjentar stort sett reiserådssidene; bare ved behov.
        for ts, orig in cdx("landsider.no/land/", **{"from": "2010"}):
            if re.fullmatch(r"/land/[^/]+/?", path(orig)):
                out.append((ts, orig))
    return sorted(set(out))


DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


def iso(d):
    m = DATE.search(d or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def clean(t):
    t = re.split(r"\s*<", t)[0]  # rester av ufullstendig HTML i sideboksen
    return t.strip().strip("«»\"").strip()


def same(a, b):
    """Lik tekst sett bort fra tegnsetting, anførselstegn og mellomrom."""
    return [norm(x) for x in a] == [norm(x) for x in b]


def parse(page, p):
    """Liste over funn: {"kind": "list", "names": [...]} eller
    {"kind": "advice", "name", "ud_date", "text"}."""
    found = []
    if p.rstrip("/") == "/traveladvice":
        # Oversikten: lenker til hvert lands reiseråd.
        body = page.split("Alle land og regioner", 1)[-1] if "Alle land og regioner" in page else page
        names = [text(n) for n in re.findall(r'<a[^>]+href="[^"]*/traveladvice/[^"]+"[^>]*>(.*?)</a>', body, re.S)]
        names = [re.sub(r"^Offisielt reiseråd (for )?", "", n) for n in names]
        names = sorted({n for n in names if n and len(n) < 60})
        if names:
            found.append({"kind": "list", "names": names})
        return found
    # Sideboksen på landsidene (2010–2015).
    for box in re.finditer(r'class="box alert reiseraad">(.*?)class="readmore|class="box alert reiseraad">(.*?)</div>\s*</div>\s*</div>', page, re.S):
        b = box.group(1) or box.group(2)
        name = re.search(r'<span>\s*Offisielt reiseråd for (.*?)</span>', b, re.S)
        content = re.search(r'class="content">(.*)', b, re.S)
        if name and content:
            c = content.group(1)
            d = iso(text(c))
            t = re.sub(r"^\s*\d{1,2}\.\d{1,2}\.\d{4}\s*", "", text(c))
            t = re.split(r"\s*Les mer »", t)[0].strip()
            if t:
                found.append({"kind": "advice", "name": text(name.group(1)), "ud_date": d, "text": clean(t)})
    if p.startswith("/traveladvice/"):
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
        title = re.search(r"<title>(.*?)</title>", page, re.S)
        name = None
        if h1:
            span = re.search(r"<span>(.*?)</span>", h1.group(1), re.S)
            name = text(span.group(1) if span else h1.group(1))
        if (not name or "reiseråd" in name.lower() and " for " not in name) and title:
            name = text(title.group(1))
        name = re.sub(r"^.*?Offisielt reiseråd (for )?", "", name or "").strip()
        intro = re.search(r"<div class='intro'[^>]*>(.*?)</div>", page, re.S)
        foot = re.search(r'class="footer">\s*<div class="left">[^<]*<span[^>]*>([^<]+)</span>', page)
        if name and intro and text(intro.group(1)):
            found.append({"kind": "advice", "name": name, "ud_date": iso(foot.group(1)) if foot else None,
                          "text": clean(text(intro.group(1))), "source": "intro"})
    # Én lesning per side: brødteksten (div.intro) foran sideboksen, som kan være forkortet.
    intro = [f for f in found if f.get("source") == "intro"]
    return intro[:1] or found[:1]


# landsider.no-navn som ikke står likt i UDs landliste i dag.
ALIASES = {"Det palestinske området": "palestina", "De palestinske områdene": "palestina",
           "Mauretania": "mauritania", "Øst-Timor": "osttimor", "Hviterussland": "belarus",
           "Burma": "myanmar", "Elfenbenskysten": "elfernbenskysten", "Kongo": "repkongo",
           "Den demokratiske republikk Kongo": "drkongo", "DR Kongo": "drkongo",
           "Den demokratiske republikken Kongo": "drkongo", "Kongo DRC": "drkongo",
           "Kongo-Brazzaville": "repkongo", "Palestinske området": "palestina",
           "Sentralafrikanske Rep.": "sar", "Sentralafrikanske republikk": "sar"}


def norm(name):
    return re.sub(r"[^a-zæøå]", "", name.lower())


def build(rows):
    """{UD-nøkkel: [{"from", "paragraphs", "status", "approx"?}]}. Datoen er UDs egen
    (approx=False) når siden har den, ellers kopidatoen. Et land som mangler i oversikten
    over offisielle reiseråd, har ingen advarsel på kopidatoen."""
    adv = json.loads((ROOT / "data" / "advisories.json").read_text())["countries"]
    keys = {norm(c["name"]): k for k, c in adv.items()}
    keys.update({norm(a): k for a, k in ALIASES.items()})
    unknown = set()

    def key(name):
        name = re.sub(r"^(Oppdatert )?(offisielt|offisielle) reiseråd (for )?", "", name, flags=re.I)
        k = keys.get(norm(name))
        if not k:
            unknown.add(name)
        return k

    obs = {}  # nøkkel -> [(dato, eksakt, tekst|None)]
    lists = []
    for r in rows:
        for f in r["found"]:
            if f["kind"] == "list":
                lists.append((r["date"], {key(n) for n in f["names"]} - {None}))
            elif (k := key(f["name"])):
                exact = bool(f["ud_date"]) and f["ud_date"] <= r["date"]
                obs.setdefault(k, []).append((f["ud_date"] if exact else r["date"], exact, f["text"]))
    for date, present in lists:
        for k in adv:
            if k not in present:
                obs.setdefault(k, []).append((date, False, None))
    out = {}
    for k, o in obs.items():
        entries = []
        for date, exact, t in sorted(o, key=lambda x: (x[0], x[2] is None)):
            paragraphs = [t] if t else []
            if entries and same(entries[-1]["paragraphs"], paragraphs):
                continue
            e = {"from": date, "status": "", "paragraphs": paragraphs}
            if not exact:
                e["approx"] = True
            entries.append(e)
        if any(e["paragraphs"] for e in entries):
            out[k] = entries
    if unknown:
        print("Ukjente navn:", sorted(unknown), file=sys.stderr)
    return out


def main():
    caps = wanted()
    print(f"{len(caps)} arkivkopier", file=sys.stderr)
    done = [0]

    def one(c):
        ts, orig = c
        try:
            page = fetch(ts, orig)
        except Exception as e:  # noqa: BLE001
            print(f"  hopper over {ts} {orig}: {e}", file=sys.stderr)
            return None
        done[0] += 1
        if done[0] % 50 == 0:
            print(f"  {done[0]}/{len(caps)}", file=sys.stderr)
        return {"date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "path": path(orig), "found": parse(page, path(orig))}

    if "--fetch" in sys.argv:
        with ThreadPoolExecutor(2) as pool:
            rows = [r for r in pool.map(one, caps) if r]
    else:
        rows = [r for r in map(one, caps) if r]
    OUT.write_text(json.dumps(rows, ensure_ascii=False))
    n = sum(1 for r in rows if r["found"])
    print(f"{len(rows)} kopier lest, {n} med funn -> {OUT}", file=sys.stderr)
    hist = build(rows)
    list_dates = sorted(r["date"] for r in rows for f in r["found"] if f["kind"] == "list")
    first = min((r["date"] for r in rows), default=None)
    last = max((r["date"] for r in rows), default=None)
    HIST.write_text(json.dumps({"source": "landsider.no via web.archive.org", "first": first, "last": last,
                                "list_first": list_dates[0] if list_dates else None,
                                "list_last": list_dates[-1] if list_dates else None,
                                "countries": dict(sorted(hist.items()))}, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(hist)} land med reiseråd på landsider.no -> {HIST}", file=sys.stderr)


if __name__ == "__main__":
    main()
