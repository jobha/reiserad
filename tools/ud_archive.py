#!/usr/bin/env python3
"""UDs eldre reiseråd fra offisielle kilder som ikke dekkes av de andre verktøyene.

Kjøres for hånd (regjeringen.no svarer bare fra en vanlig hjemmetilkobling), i tre steg:
    python3 tools/ud_archive.py            # søk i dokumentarkivet og hent sidene (struper med 429)
    python3 tools/ud_archive.py --wayback  # arkivkopier fra web.archive.org og Datawrapper
    python3 tools/ud_archive.py --write    # les alt fra .cache og skriv data/ud_archive.json

Kilder:
- regjeringen.no dokumentarkiv (id115322), søk på reiseråd-ord: UDs pressemeldinger,
  nyheter og dokumenter 1995→, hver side hentet for dato og tekst.
- Samlelister i arkivet: «Gjeldende reiseråd» (2004), «Utenriksdepartementets reiseråd»
  (2003) og «Land med reiseråd fra og med 1. oktober» (2021): alle land med reiseråd
  på datoen.
- «Tidligere reiseråd for X» (2016–2017) under regjeringen-solberg/ud/…/reiseinformasjon.
- odin.dep.no (regjeringens nettsted før 2008) via Wayback Machine.
- «Land med reiseadvarsel» (regjeringen.no, 2018→) via Wayback: alle land med advarsel
  på kopidatoen; et land som mangler, har ingen advarsel.
- Datawrapper-kartet på samme side (XzH25), alle versjoner.

Rå sider caches i .cache/regjeringen/ og .cache/wayback/. Skriver data/ud_archive.json:
{"items": [{"date", "title", "url", "text", "kind": press|list|tidligere, "countries"}],
 "advice": [{"date", "key", "paragraphs", "url", "source", "mode": "fill"}],
 "lists": [{"date", "source", "url", "complete", "countries": {UD-nøkkel: [avsnitt]}}],
 "datawrapper": {versjon: {UD-nøkkel: kategori}}}.
scraper/history.py gjør listene om til historikk med eksakte datoer og pressemeldingene
til nyheter på landsidene.
"""
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "scraper"))
from scrape import BASE, text  # noqa: E402
import wayback_history  # noqa: E402

CACHE = ROOT / ".cache" / "regjeringen"
OUT = ROOT / "data" / "ud_archive.json"
UA = "reiserad-kart/1.0 (+https://xn--reiserd-jxa.no; historikk)"
SEARCH = BASE + "/no/dokumentarkiv/id115322/"
TERMS = ["reiseråd", "Gjeldende reiseråd", "offisielt reiseråd", "reiseadvarsel", "fraråder alle reiser",
         "fraråder reiser", "Tidligere reiseråd", "reiserådet", "reiseinformasjon", "frarår"]
DELAY = 3.5


def get(url, tries=8):
    """regjeringen.no struper raskt (429): minst DELAY sekunder mellom kall, lengre ved 429."""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read().decode("utf-8", errors="replace")
            time.sleep(DELAY)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                raise
            wait = 60 * (i + 1) if e.code == 429 else 10 * (i + 1)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            wait = 10 * (i + 1)
        print(f"  vent {wait}s ({url[:90]})", file=sys.stderr)
        time.sleep(wait)
    raise RuntimeError(f"ga opp: {url}")


def cached(url):
    f = CACHE / f"{hashlib.sha1(url.encode()).hexdigest()}.html"
    if f.exists():
        return f.read_text()
    page = get(url)
    CACHE.mkdir(parents=True, exist_ok=True)
    f.write_text(page)
    return page


def search(term):
    """Treff i dokumentarkivet, nyeste først. Søkesidene caches ikke (treffene kan endre seg)."""
    items, page = [], 1
    while True:
        q = urllib.parse.urlencode({"term": term, "sortby": 1, "page": page})
        t = get(f"{SEARCH}?{q}")
        found = re.findall(r'<li class="listItem"\s*>(.*?)</li>', t, re.S)
        for li in found:
            a = re.search(r'<a href="([^"]+)"[^>]*>(.*?)</a>', li, re.S)
            d = re.search(r'class="date">([^<]+)<', li)
            ty = re.search(r'class="type">([^<]+)<', li)
            dep = re.search(r'class="department">([^<]+)<', li)
            if a and d:
                dd, mm, yy = d.group(1).strip().split(".")
                url = BASE + html.unescape(a.group(1)).split("?")[0]
                items.append({"date": f"{yy}-{mm}-{dd}", "title": text(a.group(2)), "url": url,
                              "type": text(ty.group(1)) if ty else "", "department": text(dep.group(1)) if dep else ""})
        total = re.search(r"av (\d+) treff", t)
        print(f"  {term} s.{page}: {len(found)} ({total.group(1) if total else '?'} treff)", file=sys.stderr)
        if not found or not total or page * 20 >= int(total.group(1)):
            return items
        page += 1


SKIP_TYPES = ("Tale", "Rapport", "Plan", "Svar til Stortinget", "Brev")


def is_ud(it):
    """UDs egne saker. Taler, rapporter og stortingssvar nevner reiseråd bare i forbifarten."""
    if it.get("type", "").startswith(SKIP_TYPES):
        return False
    return "utenriks" in it["department"].lower() or re.search(r"/ud/", it["url"], re.I)


def listing():
    path = CACHE / "listing.json"
    seen = json.loads(path.read_text()) if path.exists() else {}
    done = set(seen.pop("_terms", []))
    for term in TERMS:
        if term in done:
            continue
        for it in search(term):
            seen.setdefault(it["url"], it)
        done.add(term)
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**seen, "_terms": sorted(done)}, ensure_ascii=False))
        print(f"{term}: {len(seen)} til sammen", file=sys.stderr)
    return seen


def cdx(prefix, **extra):
    """[(timestamp, original)] med distinkt innhold. Ren http: https avvises av og til."""
    q = urllib.parse.urlencode({"url": prefix, "matchType": "prefix", "output": "json",
                                "fl": "timestamp,original,digest", "filter": "statuscode:200",
                                "collapse": "digest", **extra})
    rows = json.loads(wayback_history.get("http://web.archive.org/cdx/search/cdx?" + q) or "[]")[1:]
    return sorted((ts, orig) for ts, orig, _ in rows)


ODIN = "odin.dep.no/ud/norsk/landinfo/reise/"
LAND = "www.regjeringen.no/no/tema/utenrikssaker/reiseinformasjon/reiserad_land/id2589040/"
DW = "https://datawrapper.dwcdn.net/XzH25/"


def wayback_caps():
    """Alle arkivkopier vi bruker: odin.dep.no-reiseinformasjonen og «Land med reiseråd»."""
    # Hver side finnes i fire varianter (bokmål/nynorsk, normal/utskrift): oversikten i alle
    # (kopidatoene er ulike), landsidene bare i bokmål normalvisning.
    odin = [(ts, o) for ts, o in cdx(ODIN) if re.search(r"/reise/(index-[bn]-[nf]-a|[\d-]+/index-dok000-b-n-a)\.html", o)]
    land = [(ts, o) for ts, o in cdx(LAND) if re.search(r"/id2589040/?$", o)]
    return odin, land


def fetch_wayback():
    odin, land = wayback_caps()
    print(f"{len(odin)} odin-kopier, {len(land)} kopier av «Land med reiseråd»", file=sys.stderr)
    for i, (ts, o) in enumerate(land + odin):
        try:
            wayback_history.fetch(ts, o)
        except Exception as e:  # noqa: BLE001
            print(f"  hopper over {ts} {o}: {e}", file=sys.stderr)
        if i % 50 == 0:
            print(f"  {i}/{len(land) + len(odin)}", file=sys.stderr)
    # Datawrapper-kartet: versjonene ligger fortsatt ute (1, 2, …).
    n = 1
    while True:
        try:
            for f in ("", "dataset.csv"):
                cached(f"{DW}{n}/{f}")
        except urllib.error.HTTPError:
            break
        n += 1
    print(f"Datawrapper: {n - 1} versjoner", file=sys.stderr)


def seeds():
    """Sider i dokumentarkivet med reiseråd i adressen som Wayback kjenner til (bl.a. «Tidligere
    reiseråd for X» 2016–17), i tilfelle søket ikke finner dem. Dato og tittel leses fra siden."""
    path = CACHE / "seeds.json"
    if path.exists():
        return json.loads(path.read_text())
    q = urllib.parse.urlencode({"url": "www.regjeringen.no/no/dokumentarkiv/", "matchType": "prefix", "fl": "original",
                                "collapse": "urlkey", "filter": "original:.*(reiseinfo|reiserad|reiseraad|reiseadvarsel).*"})
    rows = wayback_history.get("http://web.archive.org/cdx/search/cdx?" + q).split()
    urls = sorted({BASE + re.sub(r"^https?://[^/]+", "", u).split("?")[0] for u in rows if re.search(r"/id\d+/?(\?|$)", u)})
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(urls))
    return urls


# Navn i UDs tekster som ikke står likt i UDs landliste i dag (norsk og engelsk).
ALIASES = {"emiratene": ["Emiratene", "De forente arabiske emirater", "Forente Arabiske Emirater"],
           "stkittsnevis": ["St. Kitts-Nevis", "St. KITTS & NEVIS"], "stlucia": ["St. Lucia"],
           "stvincentgrenadinene": ["St. Vincent & Grenadinene", "St. Vincent & Grendinene"],
           "trinidadtobago": ["Trinidad & Tobago"], "kina": ["Hong Kong"],
           "palestina": ["De palestinske områdene", "Det palestinske området", "Det palestinske selvstyreområdet",
                         "Palestinske området", "Gaza", "Vestbredden", "Palestine", "Palestinian Territories",
                         "Palestinian Territory", "West Bank and Gaza",
                         "Israel og Det palestinske området"],
           "drkongo": ["DR Kongo", "Den demokratiske republikken Kongo", "Den demokratiske republikk Kongo",
                       "Kongo-Kinshasa", "Kongo DRC", "Democratic Republic of the Congo", "Democratic Republic of Congo", "Dem. Rep. Congo", "DR Congo"],
           "repkongo": ["Kongo-Brazzaville", "Republikken Kongo", "Republic of the Congo", "Congo"],
           "elfernbenskysten": ["Côte d'Ivoire", "Elfenbenskysten", "Ivory Coast", "Cote d'Ivoire"],
           "uk": ["Storbritannia"], "usa": ["USA"], "osttimor": ["Øst-Timor", "East Timor", "Timor-Leste"],
           "myanmar": ["Burma"],
           "belarus": ["Hviterussland"], "mauritania": ["Mauretania"], "jemen": ["Yemen"],
           "sar": ["Sentralafrikanske Rep.", "Sentralafrikanske republikk", "Den sentralafrikanske republikk",
                   "Central African Republic", "Central African Rep."],
           "sorsudan": ["South Sudan", "S. Sudan"], "nordkorea": ["North Korea"], "sorkorea": ["South Korea"],
           "kasakhstan": ["Kasakstan"], "kirgisistan": ["Kirgisistan", "Kyrgyzstan"],
           "bosnia": ["Bosnia-Hercegovina", "Bosnia og Hercegovina", "Bosnia and Herzegovina", "Rebuplika Srpska", "Republika Srpska"],
           "eswatini": ["Swaziland", "eSwatini"], "nordmakedonia": ["North Macedonia", "Makedonia", "Den tidligere jugoslaviske republikken Makedonia"],
           "tsjekkia": ["Czechia", "Czech Republic"], "russland": ["Russia"]}


def norm(name):
    return re.sub(r"[^a-zæøåéô]", "", name.lower())


def country_keys():
    """{normalisert navn: UD-nøkkel} fra UDs landliste, aliasene og Natural Earths engelske navn."""
    adv = json.loads((ROOT / "data" / "advisories.json").read_text())["countries"]
    keys = {norm(c["name"]): k for k, c in adv.items()}
    iso = json.loads((ROOT / "data" / "countries.json").read_text())
    ne = Path(__import__("os").environ.get("REISERAD_CACHE", ROOT / ".cache")) / "ne_50m_admin_0_countries.geojson"
    if ne.exists():
        by_iso = {}
        for f in json.loads(ne.read_text())["features"]:
            p = f["properties"]
            for a3 in {p.get("ADM0_A3"), p.get("ISO_A3"), p.get("SOV_A3")} - {None, "-99"}:
                by_iso.setdefault(a3, []).extend(p.get(n) for n in ("NAME", "NAME_LONG", "ADMIN", "NAME_EN") if p.get(n))
        for k, a3 in iso.items():
            for n in by_iso.get(a3, []):
                keys.setdefault(norm(n), k)
    for k, names in ALIASES.items():
        if k in adv:
            for n in names:
                keys[norm(n)] = k
    slugs = {re.search(r"/(reiseinfo_[^/]+)/", c["url"]).group(1): k for k, c in adv.items()
             if re.search(r"/(reiseinfo_[^/]+)/", c["url"])}
    return keys, slugs


UNKNOWN = set()


def key_of(name, keys):
    k = keys.get(norm(name))
    if not k and name.strip():
        UNKNOWN.add(name.strip())
    return k


def wb_date(ts):
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"


def ud_date(s):
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", s or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else None


def land_lists(keys, slugs):
    """«Land med reiseråd» (2019→): én liste per kopi, datert med «Sist oppdatert» (UDs dato)."""
    _, land = wayback_caps()
    out = {}
    for ts, o in land:
        try:
            page = wayback_history.fetch(ts, o)
        except Exception:  # noqa: BLE001
            continue
        body = re.search(r'class="article-body[^"]*"[^>]*>(.*?)(<footer|class="article-footer|<aside|Til toppen)', page, re.S)
        upd = re.search(r"Sist oppdatert:\s*([\d.]+)", page)
        if not body or not upd:
            continue
        found = {}
        for href, name in re.findall(r'<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>', body.group(1), re.S):
            m = re.search(r"/(reiseinfo_[^/]+)/", href)
            k = slugs.get(m.group(1)) if m else None
            if "velg-land" in href or m:
                k = k or key_of(text(name), keys)
                if k:
                    found[k] = []
        d = ud_date(upd.group(1))
        if len(found) > 10 and d not in out:
            dw = re.search(r"XzH25/(\d+)", page)
            out[d] = {"date": d, "source": "regjeringen.no «Land med reiseråd» via web.archive.org", "seen": wb_date(ts),
                      "url": f"https://web.archive.org/web/{ts}/{o}", "countries": dict(sorted(found.items())),
                      **({"datawrapper": int(dw.group(1))} if dw else {})}
    return list(out.values())


def datawrapper(keys):
    """Versjonene av Datawrapper-kartet XzH25: {versjon: {UD-nøkkel: nivå}}. Versjonene er ikke
    datert; de brukes bare til kontroll mot listene på siden."""
    import csv
    import io
    out = {}
    n = 1
    while (CACHE / f"{hashlib.sha1(f'{DW}{n}/dataset.csv'.encode()).hexdigest()}.html").exists():
        rows = list(csv.reader(io.StringIO(cached(f"{DW}{n}/dataset.csv"))))
        out[n] = {k: r[1].strip() for r in rows if len(r) > 1 and r[1].strip() and (k := key_of(r[0].strip(), keys))}
        n += 1
    return out


MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober",
          "november", "desember"]


def long_date(s):
    m = re.search(r"(\d{1,2})\.\s*(" + "|".join(MONTHS) + r")\s+(\d{4})", s, re.I)
    return f"{m.group(3)}-{MONTHS.index(m.group(2).lower()) + 1:02d}-{int(m.group(1)):02d}" if m else None


def odin(keys):
    """odin.dep.no/ud/norsk/landinfo/reise/ (2001–2005): oversikten nevner landene med eget
    reiseråd («Departementet gir for tiden også reiseråd for disse landene»), og landsidene har
    av og til en setning om reiserådet («Utenriksdepartementet har i et reiseråd av 12. juni 2000
    frarådet …»). Oversikten er ikke fullstendig, så den gir bare «står på listen»."""
    pats = name_patterns(keys)
    caps, _ = wayback_caps()
    lists, advice = [], []
    for ts, o in caps:
        f = wayback_history.CACHE / f"{hashlib.sha1(f'{ts} {o}'.encode()).hexdigest()}.html"
        if not f.exists():
            continue
        page = f.read_text(errors="replace")
        if "/reise/index-" in o:
            m = re.search(r"gir for tiden ogs(?:å|&aring;) reiser(?:å|&aring;)d for disse landene:(.*?)</ul>", page, re.S)
            if m:
                found = {k: [] for n in re.findall(r"<a[^>]*>(.*?)</a>", m.group(1), re.S)
                         for k in countries_in(text(n), pats)}
                lists.append({"date": wb_date(ts), "source": "odin.dep.no via web.archive.org", "complete": False,
                              "url": f"https://web.archive.org/web/{ts}/{o}", "countries": found})
            continue
        t = text(page)
        t = t[t.find("Language") + 8:] if "Language" in t else t
        name = t.split(" Offisielt navn")[0].strip()
        if len(name) > 40:
            continue
        k = key_of(name, keys)
        if not k:
            continue
        s_ = r"(?:[^.]|(?<=\d)\.)"  # punktum i datoer («12. juni») avslutter ikke setningen
        for sent in re.findall(rf"(?:(?<=\. )|^){s_}*?(?:Utenriksdepartementet|UD)\b{s_}*?frar(?:å|aa)d{s_}*\.", t):
            d = long_date(sent) or wb_date(ts)
            advice.append({"date": min(d, wb_date(ts)), "key": k, "paragraphs": [sent.strip()],
                           "url": f"https://web.archive.org/web/{ts}/{o}", "source": "odin", "mode": "fill"})
    seen, out = set(), []
    for a in sorted(advice, key=lambda a: (a["key"], a["date"])):
        if (a["key"], a["paragraphs"][0]) not in seen:
            seen.add((a["key"], a["paragraphs"][0]))
            out.append(a)
    return lists, out


def write():
    keys, slugs = country_keys()
    lists = land_lists(keys, slugs)
    items, advice, more = archive_items(keys)
    lists += more
    olists, oadvice = odin(keys)
    lists += olists
    advice = sorted(advice + oadvice, key=lambda x: (x["date"], x["key"]))
    lists.sort(key=lambda x: x["date"])
    dw = datawrapper(keys)
    OUT.write_text(json.dumps({
        "source": "regjeringen.no (dokumentarkivet, «Land med reiseråd» via web.archive.org), odin.dep.no via "
                  "web.archive.org, datawrapper.dwcdn.net/XzH25",
        "items": items, "advice": advice, "lists": lists, "datawrapper": dw,
    }, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(items)} saker, {len(advice)} tekster, {len(lists)} lister, {len(dw)} Datawrapper-versjoner -> {OUT}",
          file=sys.stderr)
    if UNKNOWN:
        print("Ukjente navn:", sorted(UNKNOWN), file=sys.stderr)


JUNK = re.compile(r"^(P R E S S E|Pressemelding|Utenriksdepartementet$|Utanriksdepartementet$|Lagt inn|Nr\.?\s*:?\s*\d|"
                  r"\d{1,2}\.\s*\w+\s+\d{4}$|Pressekontakt|Kontaktperson|Se også|Les mer)", re.I)
# Koronatiden: UDs globale reiseråd og reiseråd for europeiske land etter smittetall. Sakene blir
# nyheter på landsidene, men ikke tekster i historikken.
CORONA = ("2020-03-01", "2021-10-01")
# Ord som viser at et avsnitt er selve reiserådet.
ADVICE = re.compile(r"frarå|advar|oppfordr|unngå|bør ikke|forlate|forlata|vurdere nødvendig|aktsom|forsiktig", re.I)
RELEVANT = re.compile(r"reiseråd|reiserådet|reiseadvarsel|frarå|reiseinformasjon|norske borgere|reisende|evakuer", re.I)
TEXT_MAX = 4000  # tegn per sak i ud_archive.json
LIFT = re.compile(r"opphev|oppheving|opphevelse|fjern|lempe", re.I)
LIST_TITLES = re.compile(r"^(Gjeldende reiseråd|Utenriksdepartementets reiseråd|Land med reiseråd fra og med)", re.I)


def paragraphs(page):
    """Avsnittene i artikkelen (ingress + brødtekst), uten pressemeldingshoder og -haler."""
    ingress = re.search(r'class="article-ingress">(.*?)</div>', page, re.S)
    body = re.search(r'<div class="article-body">(.*?)(<aside|<div class="to-top-of-page|<footer)', page, re.S)
    b = (ingress.group(1) if ingress else "") + "<p>" + (body.group(1) if body else "")
    b = re.sub(r"<(script|style|title)[^>]*>.*?</\1>", "", b, flags=re.S)
    b = b.replace("\n", " ")
    b = re.sub(r"<h[1-6][^>]*>.*?</h[1-6]>", "\n\n", b, flags=re.S)
    b = re.sub(r"</?(p|div|hr|li|ul|ol|table|tr|td|th|br)\b[^>]*>", "\n\n", b, flags=re.I)
    out = []
    for p in (text(x) for x in re.split(r"\n\s*\n", b)):
        if p and not JUNK.search(p) and p not in out:
            out.append(p)
    return out


def clip(paras):
    out, n = [], 0
    for p in paras:
        if n + len(p) > TEXT_MAX:
            break
        out.append(p)
        n += len(p)
    return out


def name_patterns(keys):
    """{UD-nøkkel: regex} med norske navn (UDs liste og aliasene)."""
    adv = json.loads((ROOT / "data" / "advisories.json").read_text())["countries"]
    names = {k: [c["name"]] + [a for a in ALIASES.get(k, []) if not re.search(r"[a-z]{3,} [A-Z]|Congo|Coast", a)]
             for k, c in adv.items()}
    return {k: re.compile(r"(?<![\wæøå-])(" + "|".join(re.escape(n) for n in sorted(v, key=len, reverse=True))
                          + r")(s|en|et)?(?![\wæøå-])") for k, v in names.items()}


def countries_in(s, pats):
    return [k for k, p in pats.items() if p.search(s)]


def item_date(page, fallback):
    m = re.search(r'class="date">\s*(?:Dato|Publisert)?:?\s*([\d.]+)', page)
    return ud_date(m.group(1)) if m else fallback


def short_date(s):
    """«2.10.05» / «10.07.2003» -> ISO."""
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", s)
    if not m:
        return None
    y = int(m.group(3))
    return f"{y + 2000 if y < 100 else y}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"


def list_doc(d, paras, keys, pats):
    """Samlelistene i arkivet («Gjeldende reiseråd» o.l.): (dato, {UD-nøkkel: avsnitt}). Listene
    består av overskrifter (landnavn, ofte med store bokstaver) med tekst under. Regionoverskrifter
    («SØRØST-ASIA») gir teksten til landene den nevner, når de ikke har egen overskrift. Sidene ble
    redigert i ettertid («Endret 2.10.05», «Oppdatert 26. august 2005»): listen gjelder fra siste
    endring."""
    found, region, cur, dates = {}, {}, None, [d]
    for p in paras:
        if re.match(r"^\(?(Endret|Oppdatert|Dato)\b", p, re.I):
            dates.append(short_date(p) or long_date(p))
            continue
        if len(p) < 60 and not p.endswith("."):
            name = re.sub(r"\s*\(.*\)$", "", p)
            hits = [keys.get(norm(n)) for n in re.split(r"\s+og\s+|/|,", name, flags=re.I)]
            k = keys.get(norm(name)) or next((h for h in hits if h), None)
            if k:
                cur = k
                found.setdefault(k, [])
                for h in hits:  # «Israel og Det palestinske området»: begge
                    if h and h != k:
                        found.setdefault(h, [])
                        found[h] = found[k]
                continue
            if name.isupper() or name.istitle():
                cur = ("region", name)
                continue
        if cur is None:
            continue  # innledningen
        if isinstance(cur, tuple):
            for k in countries_in(p, pats):
                region.setdefault(k, []).append(p)
        else:
            found[cur].append(p)
    for k, v in region.items():
        found.setdefault(k, v)
    return max(x for x in dates if x), {k: list(v) for k, v in found.items()}


def archive_items(keys):
    """(saker, tekster, lister) fra sidene i dokumentarkivet."""
    path = CACHE / "listing.json"
    seen = json.loads(path.read_text()) if path.exists() else {}
    seen.pop("_terms", None)
    for u in seeds():
        seen.setdefault(u, {"date": "", "title": "", "url": u, "type": "", "department": "", "seed": True})
    pats = name_patterns(keys)
    items, advice, lists = [], [], []
    for it in seen.values():
        f = CACHE / f"{hashlib.sha1(it['url'].encode()).hexdigest()}.html"
        if not is_ud(it) or not (f.exists() or it["date"]):
            continue
        page = f.read_text() if f.exists() else ""  # ikke hentet (se needs_page): bare tittel og dato
        title = it["title"] or text((re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S) or [None, ""])[1])
        d = item_date(page, it["date"]) if it.get("seed") or not it["date"] else it["date"]
        if not d or not title:
            continue
        paras = paragraphs(page)
        # Fulltekstsøket treffer også dokumenter som bare nevner ordene langt nede (EØS-oversikter o.l.).
        if not RELEVANT.search(title + " " + " ".join(paras[:4])):
            continue
        kind = "tidligere" if "/reiseinformasjon/" in it["url"] else "press"
        in_title = countries_in(title, pats)
        about = in_title
        if not about and re.search(r"reiseråd|reiseadvarsel|frarå|advar|evakuer|norske borgere", title, re.I):
            about = countries_in(" ".join(paras), pats)
            if len(about) > 8:  # generelle saker som nevner mange land
                about = []
        if LIST_TITLES.search(title):
            ld, found = list_doc(d, paras, keys, pats)
            if len(found) >= 5:
                kind = "list"
                lists.append({"date": ld, "published": d, "source": "regjeringen.no dokumentarkiv", "url": it["url"], "title": title,
                              "complete": True, "countries": dict(sorted(found.items()))})
                about = []
        items.append({"date": d, "title": title, "url": it["url"], "kind": kind, "type": it.get("type", ""),
                      "countries": about, "text": clip(paras)})
        # Tekster med UDs dato, før arkivkopiene av landsidene tar over og utenom koronatiden.
        if kind == "list" or not re.search(r"reiseråd|reiseadvarsel|frarå", title + " " + " ".join(paras[:2]), re.I):
            continue
        if CORONA[0] <= d < CORONA[1] or d >= "2018-02-01":
            continue
        if LIFT.search(title):
            for k in in_title:
                advice.append({"date": d, "key": k, "paragraphs": [], "url": it["url"], "source": kind, "mode": "fill"})
            continue
        targets = in_title or (about if len(about) == 1 else [])
        for k in targets:
            mine = [p for p in paras if ADVICE.search(p) and (len(targets) == 1 or pats[k].search(p))]
            if mine:
                advice.append({"date": d, "key": k, "paragraphs": mine[:6], "url": it["url"], "source": kind,
                               "mode": "fill"})
    items.sort(key=lambda x: (x["date"], x["url"]))
    advice.sort(key=lambda x: (x["date"], x["key"]))
    return items, advice, lists


def needs_page(it):
    """Sider vi trenger teksten fra: alt før koronatiden (tekster og samlelister), sidene om
    reiseinformasjon og samlelistene. Nyere saker brukes bare som nyheter (tittel og dato)."""
    return (not it["date"] or it["date"] < CORONA[0] or "/reiseinformasjon/" in it["url"]
            or LIST_TITLES.search(it["title"]))


def main():
    if "--wayback" in sys.argv:
        fetch_wayback()
        return
    if "--write" in sys.argv:
        write()
        return
    seen = listing()
    for u in seeds():
        seen.setdefault(u, {"date": "", "title": "", "url": u, "type": "", "department": "", "seed": True})
    ud = [it for it in seen.values() if is_ud(it) and needs_page(it)]
    print(f"{len(seen)} treff, {len(ud)} fra UD; henter sidene", file=sys.stderr)
    for i, it in enumerate(sorted(ud, key=lambda x: x["date"])):
        try:
            cached(it["url"])
        except Exception as e:  # noqa: BLE001
            print(f"  hopper over {it['url']}: {e}", file=sys.stderr)
        if i % 25 == 0:
            print(f"  {i}/{len(ud)}", file=sys.stderr)


if __name__ == "__main__":
    main()
