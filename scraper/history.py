"""Historikk over UDs reiseadvarsler. Nyeste del fra git-loggen til data/advisories.json
(deploy-jobben committer filen hver gang UD endrer noe; krever fetch-depth: 0 i workflowen),
eldre deler fra arkivfilene i data/ (se build())."""
import json
import subprocess
from datetime import date
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
    """{UD-nøkkel: [{"date", "title", "url"}]} fra data/ud_news.json (tools/ud_news.py), eldste først."""
    out = {}
    for n in _load("ud_news.json") or []:
        for k in n["countries"]:
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
        out[k] = _sharpen(entries, by_country.get(k, []))
    return out


def _prepend(old, entries):
    """Legg eldre tekster foran. Er siste eldre tekst lik den første nyere, slås de sammen."""
    if not old:
        return entries
    start = entries[0]["from"]
    old = [dict(o) for o in old if o["from"] < start]
    if old and not old[-1].get("gap") and old[-1]["paragraphs"] == entries[0]["paragraphs"]:
        entries[0] = dict(entries[0], **{"from": old[-1]["from"], "approx": old[-1].get("approx", False)})
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
