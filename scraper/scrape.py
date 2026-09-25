#!/usr/bin/env python3
"""Hent UDs reiseinformasjon for alle land og trekk ut reiseadvarslene.

Skriver data/advisories.json: én post per land med URL, ingress, eventuell
reiseadvarsel (tittel, dato-linje, avsnitt) og en hash av advarselsteksten,
slik at build.py kan se om en manuelt kartlagt region-definisjon er utdatert.

Kun standardbibliotek, så den kjører på Pi-runneren uten venv.
"""
import hashlib
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://www.regjeringen.no"
INDEX = BASE + "/no/tema/utenrikssaker/reiseinformasjon/velg-land/id2414273/"
UA = "reiserad-kart/1.0 (+https://reiserad.haugsoen.com)"
OUT = Path(__file__).resolve().parent.parent / "data" / "advisories.json"


def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  retry {url}: {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))


def text(fragment):
    fragment = re.sub(r"<br\s*/?>", " ", fragment)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return re.sub(r"\s+", " ", html.unescape(fragment)).strip()


def country_links(index_html):
    seen = {}
    for m in re.finditer(
        r'<a[^>]+href="(/no/tema/utenrikssaker/reiseinformasjon/velg-land/'
        r'([^/"]+)/id\d+/)"[^>]*>(.*?)</a>',
        index_html,
        re.S,
    ):
        path, slug, label = m.groups()
        slug = re.sub(r"reiseinformasjon-for-|reiseinfo(rmasjon)?|[_-]+", " ", slug).strip()
        slug = slug.replace(" ", "")
        if slug not in seen:
            seen[slug] = (BASE + path, text(label))
    return seen


def parse_country(page):
    title = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    name = text(title.group(1)) if title else ""
    name = re.sub(r"\s*-\s*reiseinformasjon\s*$", "", name, flags=re.I)

    updated = re.search(r"Sist oppdatert:\s*([\d.]+)", page)
    ingress = re.search(r'<div class="article-ingress">(.*?)</div>', page, re.S)

    warning = None
    for fb in re.finditer(
        r'<div class="factbox"[^>]*>(.*?)<div id="factbox\d+" class="factbox-content">(.*?)</div>',
        page,
        re.S,
    ):
        head, body = fb.groups()
        h = re.search(r'class="factbox-title">(.*?)</h2>', head, re.S)
        if not h or "reiseadvarsel" not in text(h.group(1)).lower():
            continue
        pre = re.search(r'class="factbox-pre-title">(.*?)</p>', head, re.S)
        paras = [text(p) for p in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S)]
        paras = [p for p in paras if p]
        if not paras:
            paras = [text(body)]
        warning = {
            "title": text(h.group(1)),
            "status": text(pre.group(1)) if pre else "",
            "paragraphs": paras,
        }
        break

    rec = {
        "name": name,
        "page_updated": updated.group(1) if updated else None,
        "ingress": text(ingress.group(1)) if ingress else "",
        "warning": warning,
    }
    if warning:
        rec["hash"] = hashlib.sha1(" ".join(warning["paragraphs"]).encode()).hexdigest()[:12]
    return rec


def main():
    links = country_links(get(INDEX))
    if len(links) < 150:
        sys.exit(f"Fant bare {len(links)} land på indekssiden – har UD endret sidene?")

    old = {}
    if OUT.exists():
        old = json.loads(OUT.read_text()).get("countries", {})

    countries, failed = {}, []
    for i, (slug, (url, label)) in enumerate(sorted(links.items())):
        try:
            rec = parse_country(get(url))
        except Exception as e:  # noqa: BLE001
            print(f"FEIL {slug}: {e}", file=sys.stderr)
            failed.append(slug)
            if slug in old:
                countries[slug] = old[slug]  # behold forrige kjente
            continue
        rec["name"] = rec["name"] or label
        rec["url"] = url
        countries[slug] = rec
        flag = "!" if rec["warning"] else " "
        print(f"{i + 1:3d} {flag} {slug}", file=sys.stderr)
        time.sleep(0.4)

    if len(failed) > 20:
        sys.exit(f"{len(failed)} land feilet – skriver ikke over data.")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "fetched": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "source": INDEX,
                "failed": failed,
                "countries": countries,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n"
    )
    n = sum(1 for c in countries.values() if c["warning"])
    print(f"{len(countries)} land, {n} med reiseadvarsel -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
