#!/usr/bin/env python3
"""Pressehistorikk for UDs reiseråd fra Nasjonalbibliotekets digitaliserte aviser.

Kjøres for hånd:  python3 tools/nb_press.py [--offline]
Søker i avisene via DH-lab-API-et til NB (api.nb.no/dhlab): build_corpus finner
utgavene med søkefrasen, conc gir korte tekstutdrag (konkordanser) rundt treffet –
den teksten NB selv gjør tilgjengelig, også for aviser som ellers bare kan leses på
bibliotek. Avisnavn slås opp i katalogen (api.nb.no/catalog). Alt mellomlagres i
$REISERAD_CACHE/nb/ (standard .cache/nb/); --offline bygger bare om fra mellomlageret.

Skriver data/press_nb.json:
  {"generated", "queries": {frase: antall utgaver}, "countries": {UD-nøkkel: {
      "mentions": [{"date", "paper", "url", "text", "kind"}],
      "events": [{"from", "until", "papers", "kind", "mentions": [indekser]}]}},
   "unmatched": [{"date", "paper", "url", "text", "kind", "names": [gamle landnavn]}]}
kind: "all" (fraråder alle reiser), "necessary" (ikke strengt nødvendige), "lifted"
(opphever/lemper), "leave" (oppfordrer til å forlate), "against" (fraråder reiser), "none" (UD har ikke noe reiseråd)
eller "" (uklart).
Dekningen er tilfeldig (det avisene skrev om), så dette farger ikke kartet.
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get("REISERAD_CACHE", ROOT / ".cache")) / "nb"
OUT = ROOT / "data" / "press_nb.json"
DHLAB = "https://api.nb.no/dhlab"
CATALOG = "https://api.nb.no/catalog/v1/items"
UA = "reiserad.no (https://github.com/jobha/reiserad)"

QUERIES = ['"Utenriksdepartementet fraråder"', '"Utenriksdepartementet frarådet"', '"UD fraråder"', '"UD frarådet"',
           '"fraråder reiser til"', '"fraråder alle reiser"', '"fraråder nordmenn"', '"offisielle reiseråd"',
           '"offisielt reiseråd"', "reiseadvarsel", "reiseadvarselen", '"oppfordrer nordmenn til å forlate"',
           "reiserådet", "reiseråd"]
WINDOW = 25  # ord på hver side av treffet

# Navn i avisene som ikke står likt i UDs landliste. Gamle navn er bare tatt med når
# landet i praksis er det samme i dag.
ALIASES = {
    "palestina": ["De palestinske områdene", "Det palestinske området", "Gaza", "Gazastripen", "Vestbredden"],
    "drkongo": ["DR Kongo", "Den demokratiske republikken Kongo", "Kongo-Kinshasa", "Zaïre", "Zaire", "Kongo"],
    "repkongo": ["Kongo-Brazzaville", "Republikken Kongo"],
    "elfernbenskysten": ["Elfenbenskysten", "Côte d'Ivoire"], "uk": ["Storbritannia", "England", "Nord-Irland"],
    "usa": ["USA", "De forente stater"], "emiratene": ["Emiratene", "De forente arabiske emirater", "Dubai"],
    "myanmar": ["Burma"], "belarus": ["Hviterussland"], "mauritania": ["Mauretania"],
    "kina": ["Tibet", "Hongkong"], "russland": ["Tsjetsjenia", "Dagestan"], "ukraina": ["Krim"],
    "sudan": ["Darfur"], "indonesia": ["Bali"], "zimbabwe": ["Rhodesia"], "srilanka": ["Ceylon"],
    "kambodsja": ["Kampuchea"], "ewatini": ["Swaziland", "Eswatini"], "nordmakedonia": ["Makedonia"],
    "burkinafaso": ["Øvre Volta"], "kirgisistan": ["Kirgisia", "Kirgisistan"], "osttimor": ["Øst-Timor", "Timor-Leste"],
    "tsjekkia": ["Tsjekkia"], "bosnia": ["Bosnia-Hercegovina", "Bosnia"], "hellas": ["Hellas"],
    "sorkorea": ["Sør-Korea"], "nordkorea": ["Nord-Korea"], "sorafrika": ["Sør-Afrika"],
    "kappverde": ["Kapp Verde"], "saudiarabia": ["Saudi-Arabia"], "sar": ["Den sentralafrikanske republikk"],
    "dominikanske": ["Den dominikanske republikk"], "filippinene": ["Filippinene"], "maldivene": ["Maldivene"],
}
# Land som ikke finnes i dag: beholdes, men knyttes ikke til noen landside.
FORMER = ["Jugoslavia", "Sovjetunionen", "Tsjekkoslovakia", "Serbia-Montenegro", "Serbia og Montenegro"]

KEYWORD = re.compile(r"fraråd|reiseråd|reiseadvars|forlate landet|oppfordrer nordmenn", re.I)
KINDS = [  # første treff vinner
    ("none", re.compile(r"(ikke|ikkje|ingen|inga)\s+(noen\s+|noko\s+|gjeve\s+(noko\s+)?(offisielt\s+)?|offisielt\s+|noen\s+|noe\s+|utstedt\s+(noen\s+|noe\s+)?|særlig\s+\w+\s+)?(reiseråd|reiseadvars)"
                        r"|ikke\s+(har\s+)?frarå|frarår\s+ikke", re.I)),
    ("lifted", re.compile(r"opphev|trukket tilbake|trekker tilbake|ikke lenger fraråd|lemp|myk(er|et) opp|fjern(er|et) reiseråd", re.I)),
    ("necessary", re.compile(r"(ikke|unødvendig)\w*\s+(er\s+)?(strengt\s+)?nødvendig|unødvendige reiser|ikke-nødvendige", re.I)),
    ("all", re.compile(r"alle reiser|all reise|enhver reise", re.I)),
    ("leave", re.compile(r"forlate|reise ut av|reise hjem", re.I)),
    ("against", re.compile(r"fraråd|frårå|advarer mot", re.I)),
]


def _cache(name):
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / name


def _req(url, body=None, tries=4):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": UA, "Content-Type": "application/json"} if data else {"User-Agent": UA}
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=300) as r:
                out = json.load(r)
            time.sleep(1)  # høflig mot NB
            return out
        except Exception as ex:  # noqa: BLE001
            if i == tries - 1:
                raise
            print(f"  feil ({ex}), prøver igjen", file=sys.stderr)
            time.sleep(5 * (i + 1))


def _slug(q):
    return re.sub(r"\W+", "_", q).strip("_").lower()


def corpus(q, offline):
    """{dhlabid: {"urn", "date", "slug"}} for alle avisutgaver med frasen."""
    path = _cache(f"corpus_{_slug(q)}.json")
    if not path.exists():
        if offline:
            return {}
        d = _req(f"{DHLAB}/build_corpus", {"doctype": "digavis", "fulltext": q, "limit": 50000,
                                            "from_year": 1900, "to_year": date.today().year + 1})
        path.write_text(json.dumps(d, ensure_ascii=False))
    d = json.loads(path.read_text())
    out = {}
    for i, did in d["dhlabid"].items():
        ts = str(d["timestamp"][i])
        urn = d["urn"][i]
        m = re.search(r"digavis_(.+?)_null", urn)
        out[str(did)] = {"urn": urn, "date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "slug": m.group(1) if m else d["title"][i]}
    return out


def concordances(q, ids, offline):
    """[(dhlabid, tekst)] for frasen i utgavene, i satser på 200 med mellomlager per sats."""
    out = []
    ids = sorted(ids)
    for n in range(0, len(ids), 200):
        batch = ids[n:n + 200]
        path = _cache(f"conc_{_slug(q)}_{n:05d}_{len(batch)}_{batch[0]}.json")
        if not path.exists():
            if offline:
                continue
            d = _req(f"{DHLAB}/conc", {"dhlabids": batch, "query": q, "window": WINDOW, "limit": 20000,
                                       "html_formatting": False})
            path.write_text(json.dumps(d, ensure_ascii=False))
            print(f"  {q}: {n + len(batch)}/{len(ids)}", file=sys.stderr)
        d = json.loads(path.read_text())
        out += [(str(d["docid"][i]), d["conc"][i]) for i in (d.get("conc") or {})]
    return out


def paper_names(samples, offline):
    """{avisslug: avisnavn} fra katalogen, ett oppslag per avis (én URN som eksempel)."""
    path = _cache("papers.json")
    names = json.loads(path.read_text()) if path.exists() else {}
    for slug, urn in sorted(samples.items()):
        if slug in names or offline:
            continue
        try:
            d = _req(CATALOG + "?" + urllib.parse.urlencode({"q": f'"{urn}"', "size": 1}))
            items = d.get("_embedded", {}).get("items", [])
            md = items[0]["metadata"] if items else {}
            series = (md.get("series") or [md.get("title") or slug])[0]
            names[slug] = series.strip()
        except Exception as ex:  # noqa: BLE001
            print(f"  fant ikke avisnavn for {slug}: {ex}", file=sys.stderr)
            continue
        path.write_text(json.dumps(names, ensure_ascii=False, indent=1))
    return names


def patterns():
    adv = json.loads((ROOT / "data" / "advisories.json").read_text())["countries"]
    pairs = []
    for k, c in adv.items():
        for n in {c["name"], *ALIASES.get(k, [])}:
            pairs.append((n, k))
    pairs += [(n, None) for n in FORMER]
    pairs.sort(key=lambda p: -len(p[0]))  # lengste navn først, så «Papua Ny-Guinea» ikke blir «Guinea»
    rx = re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n, _ in pairs) + r")s?(?![\w-])")
    return rx, dict(pairs)


# Andre lands UD («svenske UD fraråder …») gjelder ikke norske reiseråd for det landet.
FOREIGN_UD = {"svensk": "sverige", "dansk": "danmark", "britisk": "uk", "amerikansk": "usa", "finsk": "finland",
              "tysk": "tyskland", "fransk": "frankrike", "islandsk": "island", "kanadisk": "canada",
              "australsk": "australia", "nederlandsk": "nederland", "japansk": "japan", "kinesisk": "kina"}
FOREIGN_RX = re.compile(r"\b(" + "|".join(FOREIGN_UD) + r")e? (UD|utenriksdepartement|utanriksdepartement|myndighet)", re.I)


NEIGHBOURS = {"sverige", "danmark", "finland", "island"}
MONTHS = ["januar", "februar", "mars", "april", "mai", "juni", "juli", "august", "september", "oktober",
          "november", "desember"]
RECAP_RX = re.compile(r"\b\d{1,2}\.\s*(" + "|".join(MONTHS) + r")\s*:", re.I)


def recap(text, day):
    """Årskrønike («26. januar: UD fraråder …»): omtalen gjelder en annen dato enn utgaven."""
    m = RECAP_RX.search(text)
    if not m:
        return False
    month, paper = MONTHS.index(m.group(1).lower()) + 1, int(day[5:7])
    return (paper - month) % 12 > 1


def countries_near(text, rx, names, day=""):
    """Land og gamle landnavn nær et nøkkelord (fraråd*, reiseråd*, …) i utdraget."""
    keys = [m.start() for m in KEYWORD.finditer(text)]
    foreign = {FOREIGN_UD[m.group(1).lower()] for m in FOREIGN_RX.finditer(text)}
    # Under pandemien frarådet UD reiser til «alle land» med unntak; da teller bare «til <land>».
    blanket = "2020-03" <= day[:7] <= "2022-03" and re.search(r"alle land|land utenfor|unnta|grønne land|gule land", text)
    hits, former = [], []
    for m in rx.finditer(text):
        if not any(-120 <= m.start() - k <= 200 for k in keys):
            continue
        before, after = text[max(0, m.start() - 30):m.start()], text[m.end():m.end() + 15]
        if (re.match(r"(\s+og\s+[A-ZÆØÅ]\w+)?\s+(fraråd|har frarådet|advarer|har også)", after)
                or re.search(r"(departementet|departementene|UD) i\s+([A-ZÆØÅ]\w+\s+og\s+)?$", before)):
            continue  # landet er avsender, ikke mål
        k = names[m.group(1)]
        # Nabolandene og pandemiens «alle land» nevnes mest i forbifarten: krev «til <land>».
        if (blanket or k in NEIGHBOURS) and not re.search(r"\btil\s+$", before):
            continue
        if k in foreign:
            continue
        if k is None:
            former.append(m.group(1))
        elif k not in hits:
            hits.append(k)
    return hits, former


def kind_of(text):
    for k, rx in KINDS:
        if rx.search(text):
            return k
    return ""


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def cluster(mentions, gap=14):
    """Omtaler av samme land med under to ukers mellomrom regnes som samme hendelse."""
    events = []
    for i, m in enumerate(mentions):
        if events and _days(events[-1]["until"], m["date"]) <= gap:
            ev = events[-1]
            ev["until"] = m["date"]
            ev["mentions"].append(i)
        else:
            events.append({"from": m["date"], "until": m["date"], "mentions": [i]})
    for ev in events:
        ms = [mentions[i] for i in ev["mentions"]]
        ev["papers"] = len({m["paper"] for m in ms})
        # Det mest spesifikke vinner over det generelle «fraråder».
        kinds = [m["kind"] for m in ms if m["kind"] not in ("", "against")] or [m["kind"] for m in ms if m["kind"]]
        ev["kind"] = max(sorted(set(kinds)), key=kinds.count) if kinds else ""
    return events


def clean(t):
    t = re.sub(r"\s+([,.;:!?»)])", r"\1", t)
    t = re.sub(r"([«(])\s+", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def main():
    offline = "--offline" in sys.argv
    docs, counts, concs = {}, {}, []
    for q in QUERIES:
        c = corpus(q, offline)
        counts[q] = len(c)
        docs.update(c)
        print(f"{q}: {len(c)} utgaver", file=sys.stderr)
        concs += [(did, txt, q) for did, txt in concordances(q, list(map(int, c)), offline)]
    samples = {}
    for d in docs.values():
        samples.setdefault(d["slug"], d["urn"])
    papers = paper_names(samples, offline)
    rx, names = patterns()

    # Én omtale per utgave og land; beste utdrag er det med tydeligst innhold.
    best, unmatched = {}, {}
    for did, txt, q in concs:
        d = docs.get(did)
        if not d:
            continue
        txt = clean(txt)
        if not KEYWORD.search(txt):
            continue
        # «reiseråd» alene er ofte reisetips; krev UD eller fraråding i utdraget.
        if q in ("reiseråd", "reiserådet") and not re.search(r"\bUD\b|Utenriksdep|fraråd", txt):
            continue
        if recap(txt, d["date"]) or d["date"] < "1945":
            continue
        # Bare et annet lands UD i utdraget, uten Norge: ikke et norsk reiseråd.
        if FOREIGN_RX.search(txt) and not re.search(r"\bnorsk|\bNorge|nordm[ae]nn|\bUD\b", txt):
            continue
        hits, former = countries_near(txt, rx, names, d["date"])
        paper = re.sub(r"\s*\([^)]*\d{4}[^)]*\)$", "", papers.get(d["slug"], d["slug"]))  # «Dagbladet (Oslo: 1869-)»
        m = {"date": d["date"], "paper": paper,
             "url": f"https://www.nb.no/items/{d['urn']}?searchText={urllib.parse.quote(q)}",
             "text": txt, "kind": kind_of(txt)}
        for k in hits:
            old = best.get((k, did))
            if not old or (bool(m["kind"]), len(m["text"])) > (bool(old["kind"]), len(old["text"])):
                best[(k, did)] = m
        if former and not hits:
            unmatched.setdefault(did, dict(m, names=sorted(set(former))))

    countries = {}
    for (k, _), m in sorted(best.items(), key=lambda x: (x[1]["date"], x[1]["paper"], x[0])):
        countries.setdefault(k, {"mentions": []})["mentions"].append(m)
    for c in countries.values():
        c["events"] = cluster(c["mentions"])
    out = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
           "source": "Nasjonalbiblioteket, digitaliserte aviser (api.nb.no/dhlab)",
           "queries": counts,
           "countries": dict(sorted(countries.items())),
           "unmatched": sorted(unmatched.values(), key=lambda m: (m["date"], m["paper"]))}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    n_m = sum(len(c["mentions"]) for c in countries.values())
    n_e = sum(len(c["events"]) for c in countries.values())
    print(f"{len(docs)} utgaver, {len(concs)} utdrag -> {n_m} omtaler, {n_e} hendelser i {len(countries)} land, "
          f"{len(unmatched)} med gamle landnavn -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
