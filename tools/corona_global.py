#!/usr/bin/env python3
"""UDs globale koronareiseråd (mars 2020 – 1. oktober 2021) med unntak, til data/global_advice.json.

Kjøres for hånd:  python3 tools/corona_global.py

Kilde: faktaboksen «Reiseråd for alle land» / «Hva er UDs reiseråd til nordmenn?» i
arkivkopiene av UDs landsider (cachet av tools/wayback_history.py i .cache/wayback/).
Hver versjon har UDs egen dato («SIST OPPDATERT: 15. JULI») og en liste over unntak:
hele land, «EU/EØS, Sveits og Storbritannia», og regioner i Sverige, Danmark og Finland
(fylker/regioner, sykehusdistrikter). Hoveddatoene er kontrollert mot UDs pressemeldinger
i data/ud_archive.json (14.03.2020, 15.07.2020, 05.07.2021, 01.10.2021).
"""
import glob
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scraper"))
from scrape import text  # noqa: E402

OUT = ROOT / "data" / "global_advice.json"
END = "2021-10-01"  # «UDs globale reiseråd fjernes fra 1. oktober» (pressemelding 24.09.2021)
MONTHS = {m: i + 1 for i, m in enumerate(["januar", "februar", "mars", "april", "mai", "juni", "juli",
                                          "august", "september", "oktober", "november", "desember"])}
EU_EOS = ["Belgia", "Bulgaria", "Danmark", "Estland", "Finland", "Frankrike", "Hellas", "Irland", "Island", "Italia",
          "Kroatia", "Kypros", "Latvia", "Liechtenstein", "Litauen", "Luxembourg", "Malta", "Nederland", "Polen",
          "Portugal", "Romania", "Slovakia", "Slovenia", "Spania", "Sverige", "Tsjekkia", "Tyskland", "Ungarn",
          "Østerrike", "Sveits", "Storbritannia"]
NORDEN = ["Danmark", "Finland", "Island", "Sverige", "Grønland", "Færøyene"]
# UDs regionnavn -> geoBoundaries ADM1. Finske sykehusdistrikter er lagt på landskapet de ligger i.
REGION = {
    "SWE": {"adm": "SWE/ADM1", "names": {}},  # fylles under: «Blekinge» -> «Blekinge län»
    "DNK": {"adm": "DNK/ADM1", "names": {"Nordjylland": "Nordjylland", "Sjælland": "Sjælland", "Midtjylland": "Midtjylland",
                                         "Syddanmark": "Syddanmark", "Hovedstaden": "Hovedstaden", "Hovedstadsregionen": "Hovedstaden"}},
    "FIN": {"adm": "FIN/ADM1", "names": {
        "Lappland": "Lapland", "Länsi-Pohja": "Lapland", "Norra Österbotten": "Northern Ostrobothnia", "Kajanaland": "Kainuu",
        "Kainuu": "Kainuu", "Norra Karelen": "North Karelia", "Norra Savolax": "Northern Savonia", "Östra Savolax": "Southern Savonia",
        "Södra Savolax": "Southern Savonia", "Mellersta Finland": "Central Finland", "Mellersta Österbotten": "Keski-Pohjanmaa",
        "Syd-Österbotten": "South Ostrobothnia", "Vasa": "Ostrobothnia", "Satakunta": "Satakunta", "Birkaland": "Pirkanmaa",
        "Egentliga Finland": "Finland Proper", "Centrala Tavastland": "Tavastia Proper", "Päijänne-Tavastland": "Päijät-Häme",
        "Kymmenedalen": "Kymenlaakso", "Södra Karelen": "South Karelia", "Åland": "Åland Islands",
        "Helsingfors och Nyland": "Uusimaa", "Helsingfors och Nylands": "Uusimaa", "HUS": "Uusimaa"}},
}
SWE_LAN = ["Västernorrland", "Västerbotten", "Jämtland", "Gävleborg", "Dalarna", "Uppsala", "Västmanland", "Örebro", "Värmland",
           "Västra Götaland", "Halland", "Skåne", "Kronoberg", "Blekinge", "Kalmar", "Jönköping", "Stockholm", "Östergötland",
           "Södermanland", "Norrbotten", "Gotland"]
for n in SWE_LAN:
    REGION["SWE"]["names"][n] = n + ("s län" if n not in ("Skåne", "Västra Götaland", "Uppsala", "Stockholm", "Örebro", "Västmanland", "Jönköping", "Kalmar", "Blekinge", "Halland", "Gotland", "Dalarna", "Värmland", "Västernorrland", "Västerbotten", "Jämtland", "Gävleborg", "Södermanland", "Norrbotten", "Östergötland", "Kronoberg") else "")
REGION["SWE"]["names"].update({
    "Skåne": "Skåne län", "Västra Götaland": "Västra Götalands län", "Uppsala": "Uppsala län", "Stockholm": "Stockholms län",
    "Örebro": "Örebro län", "Västmanland": "Västmanlands län", "Jönköping": "Jönköpings län", "Kalmar": "Kalmar län",
    "Blekinge": "Blekinge län", "Halland": "Hallands län", "Gotland": "Gotlands län", "Dalarna": "Dalarnas län",
    "Värmland": "Värmlands län", "Västernorrland": "Västernorrlands län", "Västerbotten": "Västerbottens län",
    "Jämtland": "Jämtlands län", "Jämtland Härjedalen": "Jämtlands län", "Gävleborg": "Gävleborgs län",
    "Södermanland": "Södermanlands län", "Norrbotten": "Norrbottens län", "Östergötland": "Östergötlands län",
    "Kronoberg": "Kronobergs län"})
COUNTRY_OF_REGION = {"Sverige": "SWE", "Danmark": "DNK", "Finland": "FIN"}
# Versjoner der unntakene står som fritekst eller gjelder fra en senere dato, satt for hånd:
# - 12. og 25. juni 2020: «alle land utenfor Norden», men ikke områder i Norden med høy smitte
#   etter FHIs kriterier. Fra 15. juni var det Danmark, Finland og Island (pressemelding 29.05
#   om Danmark; Sverige var rødt hele sommeren).
# - 10. juli 2020: unntakene i EØS/Schengen og Sør-Sverige gjelder først fra 15. juli (egen versjon).
OVERRIDES = {
    "2020-06-12": {"from": "2020-06-15", "exempt": ["danmark", "faeroyene", "finland", "gronland", "island"]},
    "2020-06-25": {"exempt": ["danmark", "faeroyene", "finland", "gronland", "island"]},
    "2020-07-10": {"exempt": ["danmark", "faeroyene", "finland", "gronland", "island"]},
}
# Skrivemåter i UDs lister som ikke står likt i tabellen over.
FIX = {"Õ": "Ö", "Päijät-Häme": "Päijänne-Tavastland", "Helsingfors": "Helsingfors och Nyland",
       "Nyland": "Helsingfors och Nyland", "Etelä-Savo": "Södra Savolax"}


def status_date(status, fallback_year=2020):
    s = status.lower()
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", s)
    if m:
        y = int(m.group(3)); y += 2000 if y < 100 else 0
        return f"{y}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{1,2})\.\s*([a-zæøå]+)(?:\s+(\d{4}))?", s)
    if not m or m.group(2) not in MONTHS:
        return None
    month = MONTHS[m.group(2)]
    year = int(m.group(3)) if m.group(3) else (2021 if month == 1 else fallback_year)
    return f"{year}-{month:02d}-{int(m.group(1)):02d}"


def collect():
    """{dato: tekst} fra de cachede arkivkopiene."""
    versions = {}
    for p in glob.glob(str(ROOT / ".cache" / "wayback" / "*.html")):
        t = open(p, errors="replace").read()
        if "factbox" not in t:
            continue
        for m in re.finditer(r'<div class="factbox"[^>]*>(.*?)<div id="factbox\d+" class="factbox-content">(.*?)</div>\s*</div>', t, re.S):
            head, body = m.groups()
            h = re.search(r'class="factbox-title">(.*?)</h[23]>', head, re.S)
            title = text(h.group(1)) if h else ""
            if not re.search(r"alle land|hva er uds reiseråd|globale", title, re.I):
                continue
            pre = re.search(r'class="factbox-pre-title">(.*?)</p>', head, re.S)
            d = status_date(text(pre.group(1)) if pre else "")
            body_t = text(body)
            if d and "fraråd" in body_t + "opphevet" and (d not in versions or len(body_t) > len(versions[d])):
                versions[d] = body_t
    return versions


def split_names(s):
    s = re.sub(r"^(Sykehusdistriktene|Sykehusdistriktet|Regionene|Regionen|regionen|Følgende regioner i \w+)\s*", "", s.strip())
    s = re.sub(r"\s*\([^)]*\)", "", s)  # «Mellersta Finland (Keski-Suomi)»
    parts = re.split(r",\s*|\s+og\s+|\s+samt\s+|\bsamt\s+", s)
    out = []
    for p in parts:
        p = re.sub(r"^(regionen|regionene|sykehusdistriktet|sykehusdistriktene|og|samt)\s+", "", p.strip(" .:"), flags=re.I)
        p = p.replace("Õ", "Ö")
        if "/" in p:  # «Etelä-Savo/Södra Savolax»: bruk det svenske navnet
            p = p.split("/")[-1].strip()
        if p:
            out.append(FIX.get(p, p))
    return out


def parse(t, names_to_key):
    """(unntatte land-nøkler, {ISO: {"exempt": [...]} | {"warned": [...]}})"""
    exempt, regions = set(), {}
    if re.search(r"(utenfor|opphevet reiserådet for) EU/EØS(-landene)?, Sveits og Storbritannia", t):
        exempt |= {names_to_key[n] for n in EU_EOS if n in names_to_key}
    if re.search(r"(utenfor Norden|med unntak av land og regioner i Norden)", t):
        exempt |= {names_to_key[n] for n in NORDEN if n in names_to_key}
    m = re.search(r"(unntak for|unntatt fra UDs globale reiseråd:|unntak for noen land og områder utenfor EU:)(.*)", t, re.S)
    seg = m.group(2) if m else ""
    seg = re.split(r"\s(Disse (landene|områdene)|Dette er land|Landlisten|Kart over|Mer informasjon|Reiserådet gjelder|Det globale reiserådet gjelder|Dette reiserådet gjelder)", seg)[0]
    # Setninger: «I Sverige: A, B og C.», «Følgende regioner i Sverige: …», «Norden: …», ellers land.
    for sent in re.split(r"(?<=[a-zæøå)])\.\s+(?=[A-ZÆØÅ])|(?=\bI (?:Sverige|Danmark|Finland)\s*:)|(?=Følgende regioner i )|(?=Regioner i )", seg):
        sent = sent.strip(" .")
        if not sent:
            continue
        rm = re.match(r"(?:I|Følgende regioner i|Regioner i) (Sverige|Danmark|Finland)\s*:?\s*(.*)", sent, re.S)
        if rm:
            iso = COUNTRY_OF_REGION[rm.group(1)]
            rest = rm.group(2)
            inv = re.match(r"(?:Alle (?:regioner|sykehusdistrikter)|Hele landet) (?:med unntak av|bortsett fra)\s*(?:sykehusdistriktene\s*)?(.*)", rest, re.I)
            names = split_names(inv.group(1) if inv else rest)
            table = REGION[iso]["names"]
            found, other = [], []
            for n in names:
                if n in table:
                    found.append(table[n])
                elif n in names_to_key:
                    exempt.add(names_to_key[n])  # f.eks. «Grønland» i Danmark-setningen
                else:
                    other.append(n)
            if other:
                print(f"  ukjente regionnavn i {rm.group(1)}: {other}", file=sys.stderr)
            if found:
                regions[iso] = {"warned" if inv else "exempt": sorted(set(found))}
            continue
        sent = re.sub(r"^følgende [^:]*:\s*", "", sent, flags=re.I)
        sent = re.sub(r"^[^:]*\b(land|områder)\b[^:]*:\s*", "", sent)  # «noen land og områder utenfor EU: …»
        sent = re.sub(r"^(Norden|Øvrige land i EØS/Schengen-området|Øvrige land i EØS/Schengen)\s*:\s*", "", sent)
        for n in split_names(sent):
            if n in names_to_key:
                exempt.add(names_to_key[n])
    return sorted(exempt), regions


def main():
    adv = json.loads((ROOT / "data" / "advisories.json").read_text())["countries"]
    names_to_key = {c["name"]: k for k, c in adv.items()}
    names_to_key.update({"Storbritannia": "uk", "Bosnia-Hercegovina": names_to_key.get("Bosnia-Hercegovina", "bosnia"),
                         "USA": "usa", "Sør-Korea": "sorkorea"})
    # Områder uten egen side hos UD, som likevel er nevnt i unntakene (build.py TERRITORIES).
    names_to_key.update({"Grønland": "gronland", "Færøyene": "faeroyene", "Taiwan": "taiwan",
                         "Hongkong": "hongkong", "Hong Kong": "hongkong", "Macao": "macao", "Macau": "macao"})
    iso_of_region = {"SWE": "sverige", "DNK": "danmark", "FIN": "finland"}
    versions = collect()
    out = []
    for d in sorted(versions):
        if d > END:
            continue
        t = versions[d]
        exempt, regions = parse(t, names_to_key)
        o = OVERRIDES.get(d, {})
        if "exempt" in o:
            exempt, regions = o["exempt"], {}
        d = o.get("from", d)
        # Region-unntak for et land som også er helt unntatt, er overflødige.
        regions = {iso_of_region[i]: dict(r, adm=REGION[i]["adm"]) for i, r in regions.items() if iso_of_region[i] not in exempt}
        out.append({"from": d, "text": t, "exempt": exempt, "regions": regions})
    # Like påfølgende versjoner slås sammen.
    merged = []
    for v in out:
        if merged and (merged[-1]["exempt"], merged[-1]["regions"]) == (v["exempt"], v["regions"]):
            continue
        merged.append(v)
    for a, b in zip(merged, merged[1:]):
        a["until"] = b["from"]
    merged[-1]["until"] = END
    OUT.write_text(json.dumps({"source": "UDs faktaboks for globale reiseråd i arkivkopier av landsidene",
                               "end": END, "versions": merged}, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(merged)} versjoner {merged[0]['from']}–{END} -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
