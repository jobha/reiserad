"""Historikk over UDs reiseadvarsler, hentet fra git-loggen til data/advisories.json
(deploy-jobben committer filen hver gang UD endrer noe). Krever full git-historikk
(fetch-depth: 0 i workflowen); uten den blir historikken bare kortere."""
import json
import subprocess
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


def archive():
    """Eldre tekster fra web.archive.org (tools/wayback_history.py), uten «until»."""
    path = ROOT / "data" / "history_archive.json"
    return json.loads(path.read_text())["countries"] if path.exists() else {}


def build():
    """{UD-nøkkel: [{"from", "until", "status", "paragraphs", "approx"?}]}, eldste først.
    Siste element er gjeldende tekst (until=None). En periode uten advarsel har
    paragraphs=[]. Land som mangler i et øyeblikksbilde (feilet skraping) hoppes over."""
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
    return {k: _prepend(arch.get(k, []), v) for k, v in hist.items()} if (arch := archive()) else hist


def _prepend(old, entries):
    """Legg arkivtekstene foran git-historikken. Arkivdatoer er omtrentlige (approx)."""
    start = entries[0]["from"]
    old = [dict(o, approx=True) for o in old if o["from"] < start]
    if old and old[-1]["paragraphs"] == entries[0]["paragraphs"]:
        entries[0] = dict(entries[0], **{"from": old[-1]["from"], "approx": True})
        old.pop()
    out = old + entries
    for a, b in zip(out, out[1:]):
        a["until"] = b["from"]
    return out
