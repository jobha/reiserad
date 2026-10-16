"""Historikk over UDs reiseadvarsler. Nyeste del fra git-loggen til data/advisories.json
(deploy-jobben committer filen hver gang UD endrer noe; krever fetch-depth: 0 i workflowen),
eldre deler fra arkivfilene i data/ (se build())."""
import json
import re
import subprocess
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = "data/advisories.json"


def _git(*args):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, check=True).stdout


def snapshots():
    """[(dato, advisories)] fra eldste til nyeste, pluss arbeidskopien til slutt."""
    try:
        log = _git("log", "--reverse", "--format=%H %cs", "--", PATH).split("\n")
    except (OSError, subprocess.CalledProcessError):
        log = []
    out = []
    for line in filter(None, log):
        sha, date = line.split()
        try:
            out.append((date, json.loads(_git("show", f"{sha}:{PATH}"))))
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            continue
    current = json.loads((ROOT / PATH).read_text())
    out.append((current["fetched"][:10], current))
    return out


def _load(name):
    path = ROOT / "data" / name
    return json.loads(path.read_text()) if path.exists() else {}


def news():
    """{UD-nøkkel: [{"date", "title", "url"}]}, eldste først: data/ud_news.json (tools/ud_news.py, 2021→)
    og UDs pressemeldinger og nyheter i dokumentarkivet (data/ud_archive.json, tools/ud_archive.py)."""
    out, seen = {}, set()
    items = (_load("ud_news.json") or []) + _load("ud_archive.json").get("items", [])
    for n in sorted(items, key=lambda n: n["date"]):
        for k in n.get("countries", []):
            if (k, n["url"]) not in seen:
                seen.add((k, n["url"]))
                out.setdefault(k, []).append({"date": n["date"], "title": n["title"], "url": n["url"]})
    return out


def press():
    """{UD-nøkkel: [{"from", "until", "papers", "kind", "mentions": [omtale]}]} fra
    data/press_nb.json (tools/nb_press.py): avisomtaler i Nasjonalbiblioteket, eldste først."""
    out = {}
    for k, c in _load("press_nb.json").get("countries", {}).items():
        out[k] = [dict(ev, mentions=[c["mentions"][i] for i in ev["mentions"]]) for ev in c["events"]]
    return out


def build():
    """{UD-nøkkel: [{"from", "until", "status", "paragraphs", "approx"?, "gap"?, "news"?}]}, eldste først.
    Siste element er gjeldende tekst (until=None). En periode uten advarsel har
    paragraphs=[]; gap=True er en periode uten arkivdata. Kilder, eldste først:
    landsider.no (tools/landsider_history.py), regjeringen.no i Wayback Machine
    (tools/wayback_history.py) og git-loggen til data/advisories.json. UDs nyheter
    (tools/ud_news.py) tidfester endringer som ellers bare er datert etter arkivkopier."""
    hist = {}
    for date, adv in snapshots():
        for key, c in adv["countries"].items():
            w = c.get("warning")
            paragraphs = w["paragraphs"] if w else []
            entries = hist.setdefault(key, [])
            if entries and entries[-1]["paragraphs"] == paragraphs:
                if w:
                    entries[-1]["status"] = w["status"]
                continue
            if entries:
                entries[-1]["until"] = date
            entries.append({"from": date, "until": None, "status": w["status"] if w else "",
                            "paragraphs": paragraphs})
    arch = _load("history_archive.json").get("countries", {})
    lands = _load("history_landsider.json")
    by_country = news()
    obs = _observations(hist, lands)
    out = {}
    for k, entries in hist.items():
        entries = _prepend([dict(o, approx=True) for o in arch.get(k, [])], entries)
        old = lands.get("countries", {}).get(k)
        if old:
            # Mellom landsider.no (til 2015) og faktaboksene på regjeringen.no (fra 2018)
            # finnes ingen tekst vi kan lese: marker hullet i stedet for å strekke perioden.
            old = [o for o in old if o["from"] < entries[0]["from"]]
            if old and lands.get("last") and lands["last"] < entries[0]["from"]:
                old.append({"from": lands["last"], "status": "", "paragraphs": [], "gap": True, "approx": True})
            entries = _prepend(old, entries)
        entries = _overlay(entries, obs.get(k, []))
        out[k] = _sharpen(entries, by_country.get(k, []))
    return out


LIST_DAYS = 400  # så lenge en observasjon gjelder hvis ingen nyere kilde sier noe


def _plus(d, days):
    return (date.fromisoformat(d) + timedelta(days=days)).isoformat()


def _observations(keys, lands):
    """{UD-nøkkel: [(dato, art, avsnitt, horisont)]} fra data/ud_archive.json (tools/ud_archive.py).
    art: "text" (UDs tekst med UDs dato), "listed" (på UDs fullstendige liste over land med
    reiseråd, uten tekst), "absent" (mangler på listen: ingen advarsel), "fill"/"lift" (reiseråd
    gitt/opphevet i en pressemelding: fyller bare perioder uten kjent tekst). Observasjonen gjelder
    til horisonten: neste liste, høyst LIST_DAYS dager. Land som mangler på alle oversiktene på
    landsider.no/regjeringen.no 2006–2018, er uten advarsel i hele den perioden."""
    a = _load("ud_archive.json")
    lists = sorted(a.get("lists", []), key=lambda x: x["date"])
    dates = sorted({x["date"] for x in lists})
    out = {}

    def add(k, *o):
        out.setdefault(k, []).append(o)

    for x in lists:
        later = [d for d in dates if d > x["date"]]
        horizon = min([_plus(x["date"], LIST_DAYS)] + later[:1])
        for k in keys:
            p = x["countries"].get(k)
            if p is None:
                if x.get("complete", True):
                    add(k, x["date"], "absent", [], horizon)
            elif x.get("complete", True):
                add(k, x["date"], "text" if p else "listed", p, horizon)
            else:  # ufullstendig oversikt: fyller bare ukjente perioder
                add(k, x["date"], "fill" if p else "seen", p, horizon)
    for t in a.get("advice", []):
        kind = "text" if t.get("mode") != "fill" else "fill" if t["paragraphs"] else "lift"
        add(t["key"], t["date"], kind, t["paragraphs"], _plus(t["date"], LIST_DAYS))
    if lands.get("list_first"):
        for k in keys:
            if k not in lands.get("countries", {}):
                add(k, lands["list_first"], "absent", [], lands["list_last"])
    return out


def _norm(paragraphs):
    return re.sub(r"[^a-zæøå0-9]", "", " ".join(paragraphs).lower())


def _overlay(entries, obs):
    """Legg observasjoner med sikker dato inn i historikken. En liste der landet mangler, gir
    «ingen advarsel» fra listedatoen; står landet på listen uten tekst og en omtrentlig datert
    tekst begynner før neste liste, flyttes tekstens dato tilbake til listedatoen. Er det ingen
    kilde etter horisonten, er perioden etter den ukjent."""
    entries = [dict(e) for e in entries]

    def extend(i, horizon):
        """Tilstanden i entries[i] er bekreftet til horisonten: et senere «ukjent» flyttes dit."""
        j = i + 1
        if j >= len(entries):
            return
        if entries[j].get("gap") and entries[j]["from"] < horizon:
            if j + 1 < len(entries) and entries[j + 1]["from"] <= horizon:
                del entries[j]
            else:
                entries[j]["from"] = horizon
        elif entries[i].get("obs") and not entries[j].get("gap") and entries[j]["from"] > horizon:
            # Bare observasjonen sier noe om perioden; etter horisonten er tilstanden ukjent.
            entries.insert(j, {"from": horizon, "status": "", "paragraphs": [], "gap": True, "approx": True})

    for d, kind, paras, horizon in sorted(obs, key=lambda o: o[0]):
        i = max((j for j, e in enumerate(entries) if e["from"] <= d), default=-1)
        if i > 0 and entries[i].get("gap") and entries[i]["from"] >= _plus(d, -31):
            del entries[i]  # et kort hull rett før en ny observasjon er ikke verdt å vise
            i -= 1
        cur = entries[i] if i >= 0 else None
        nxt = entries[i + 1] if i + 1 < len(entries) else None
        state = None if cur is None or cur.get("gap") else (
            "listed" if cur.get("listed") else _norm(cur["paragraphs"]))
        want = "listed" if kind in ("listed", "seen") else _norm(paras)
        if state == want or (kind in ("listed", "seen") and state):
            if kind != "seen":
                extend(i, horizon)
            continue  # stemmer med det vi vet (en tekst er mer enn «står på listen»)
        # Er tilstanden sett på landsiden etter listedatoen (egen daglige henting i git, eller en arkivkopi
        # med «seen» senere), tok listen feil.
        page = cur is not None and not cur.get("obs") and not cur.get("gap") and (
            not cur.get("approx") or cur.get("seen", "") > d)
        if kind == "absent" and state and state != "listed" and page:
            # Arkivkopier viser teksten på landsiden både før og etter listen (Afghanistan manglet på
            # listen 2.7.2019): listen tok feil, teksten gjelder.
            extend(i, horizon)
            continue
        if kind == "listed" and state == "" and page:
            # Arkivkopier av landsiden etter listedatoen viser ingen advarsel, men «Land med reiseråd» ble
            # ikke alltid ryddet (Kina til aug. 2021, Kasakhstan til aug. 2022): siden vinner.
            continue
        if kind == "fill" and state and state != "listed":
            continue  # pressemeldingen erstatter ikke UDs egen tekst
        if kind == "lift" and not state:
            continue
        if kind == "seen":
            if cur is not None and not cur.get("gap"):
                continue
            kind = "listed"
        if nxt and nxt.get("approx") and not nxt.get("gap") and nxt["from"] <= horizon and (
                _norm(nxt["paragraphs"]) == want or (kind == "listed" and nxt["paragraphs"])):
            nxt["from"] = d  # samme tilstand, men tidligere og sikrere datert
            del nxt["approx"]
            continue
        new = {"from": d, "status": "", "paragraphs": list(paras), "obs": True}
        if kind == "listed":
            new["listed"] = True
        if cur is not None and cur["from"] == d:
            if not (cur.get("approx") or cur.get("gap")):
                continue
            entries[i] = new
        else:
            entries.insert(i + 1, new)
            i += 1
        extend(i, horizon)
    # Like perioder etter hverandre slås sammen.
    merged = []
    for e in entries:
        e.pop("obs", None)
        p = merged[-1] if merged else None
        if p and bool(p.get("gap")) == bool(e.get("gap")) and bool(p.get("listed")) == bool(e.get("listed")) \
                and _norm(p["paragraphs"]) == _norm(e["paragraphs"]):
            if e.get("news"):
                p["news"] = p.get("news", []) + e["news"]
            continue
        merged.append(e)
    return _until(merged)


def _prepend(old, entries):
    """Legg eldre tekster foran. Er siste eldre tekst lik den første nyere, slås de sammen."""
    if not old:
        return entries
    start = entries[0]["from"]
    old = [dict(o) for o in old if o["from"] < start]
    if old and not old[-1].get("gap") and old[-1]["paragraphs"] == entries[0]["paragraphs"]:
        # Samme tilstand er sett på landsiden helt fram til den egne hentingen begynte («seen»).
        entries[0] = dict(entries[0], **{"from": old[-1]["from"], "approx": old[-1].get("approx", False),
                                         "seen": max(old[-1].get("seen", ""), entries[0]["from"])})
        if not entries[0]["approx"]:
            del entries[0]["approx"]
        old.pop()
    return _until(old + entries)


def _until(entries):
    for a, b in zip(entries, entries[1:]):
        a["until"] = b["from"]
    entries[-1]["until"] = None
    return entries


def _days(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _sharpen(entries, items):
    """En omtrentlig dato (første arkivkopi med ny tekst) erstattes av datoen for UDs siste
    nyhet om landet mellom forrige og denne kopien. Nyheter knyttes også til endringer
    med sikker dato når de kom innen en uke."""
    for i, e in enumerate(entries):
        if e.get("gap"):
            continue
        if e.get("approx") and i > 0:
            hits = [n for n in items if entries[i - 1]["from"] < n["date"] <= e["from"]]
            if hits:
                n = hits[-1]
                e["from"], e["news"] = n["date"], [n]
                del e["approx"]
                continue
        near = [n for n in items if abs(_days(e["from"], n["date"])) <= 7]
        if near and not e.get("approx"):
            e["news"] = near
    return _until(entries)
