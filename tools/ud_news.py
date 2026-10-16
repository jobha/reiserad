#!/usr/bin/env python3
"""UDs nyheter og pressemeldinger om reiseråd fra regjeringen.no-søket, med land.

Kjøres for hånd (regjeringen.no svarer 403 til datasentre):  python3 tools/ud_news.py
Skriver data/ud_news.json: [{"date", "title", "url", "type", "excerpt", "countries": [UD-nøkkel]}].
history.py bruker dem til å tidfeste endringer som ellers bare er datert etter arkivkopier.
"""
import html
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))
from scrape import BASE, get, text  # noqa: E402

OUT = ROOT / "data" / "ud_news.json"
TERMS = ["reiserådet", "reiseråd", "reiserådene", "reiseadvarsel", "reiseadvarselen", "fraråder alle reiser",
         "fraråder reiser"]
# Navn i nyhetene som ikke står likt i UDs landliste.
ALIASES = {"palestina": ["De palestinske områdene", "Det palestinske området", "Gaza", "Vestbredden"],
           "drkongo": ["DR Kongo", "Den demokratiske republikken Kongo", "Kongo-Kinshasa"],
           "elfernbenskysten": ["Côte d'Ivoire"], "uk": ["Storbritannia"], "usa": ["USA"],
           "emiratene": ["Emiratene", "De forente arabiske emirater"], "myanmar": ["Burma"],
           "belarus": ["Hviterussland"], "mauritania": ["Mauretania"], "kina": ["Shanghai"]}


def search(term):
    items, page = [], 1
    while True:
        q = urllib.parse.urlencode({"ownerid": 833, "term": term, "sortby": 1, "page": page})
        t = get(f"{BASE}/no/aktuelt/nyheter/id2006120/?{q}")
        found = re.findall(r'<li class="listItem"\s*>(.*?)</li>', t, re.S)
        for li in found:
            a = re.search(r'<a href="([^"]+)"[^>]*>(.*?)</a>', li, re.S)
            d = re.search(r'class="date">([^<]+)<', li)
            ty = re.search(r'class="type">([^<]+)<', li)
            ex = re.search(r'class="excerpts">(.*?)</p>', li, re.S)
            if a and d:
                dd, mm, yy = d.group(1).strip().split(".")
                items.append({"date": f"{yy}-{mm}-{dd}", "title": text(a.group(2)), "url": BASE + html.unescape(a.group(1)),
                              "type": text(ty.group(1)) if ty else "", "excerpt": text(ex.group(1)) if ex else ""})
        total = re.search(r"av (\d+) treff", t)
        if not found or not total or page * 20 >= int(total.group(1)):
            return items
        page += 1
        time.sleep(0.5)


def main():
    adv = json.loads((ROOT / "data" / "advisories.json").read_text())["countries"]
    names = {k: [c["name"]] + ALIASES.get(k, []) for k, c in adv.items()}
    pats = {k: re.compile(r"\b(" + "|".join(re.escape(n) for n in v) + r")s?\b") for k, v in names.items()}
    news = {}
    for term in TERMS:
        for it in search(term):
            news[it["url"]] = it
        print(f"{term}: {len(news)} til sammen", file=sys.stderr)
    out = []
    for it in sorted(news.values(), key=lambda x: (x["date"], x["url"])):
        title_hits = [k for k, p in pats.items() if p.search(it["title"])]
        it["countries"] = title_hits or [k for k, p in pats.items() if p.search(it["excerpt"])]
        out.append(it)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(out)} saker, {sum(1 for x in out if x['countries'])} med land -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
