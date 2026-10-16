#!/usr/bin/env python3
"""Mer tekst rundt uklare avisutdrag fra tools/nb_press.py, til gjennomlesing.

Kjøres for hånd:  python3 tools/nb_context.py ID-FIL UT-FIL
DH-lab gir høyst 25 ord rundt et treff. For hvert utdrag (id fra data/press_nb_review.json)
«går» vi utover ved å søke på utdragets første og siste ord i samme avisutgave, inntil
tre steg hver vei (NB_STEPS) (stopper ved avsnittsgrenser), og henter i tillegg alle andre treff på
UD/Utenriksdepartementet/fraråd*/reiseråd* i utgaven. Mellomlagres i $REISERAD_CACHE/nb/context/.
ID-FIL er en JSON-liste med id-er; UT-FIL blir {id: {"before", "text", "after", "issue": [utdrag]}}.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nb_press as nb  # noqa: E402

ISSUE_Q = ("UD OR Utenriksdepartementet OR Utanriksdepartementet OR Utenriksdepartementets OR fraråd* "
           "OR frårå* OR reiseråd* OR reiseadvars*")
STEPS = int(os.environ.get("NB_STEPS", 3))
nb.PAUSE = 1
nb.TIMEOUT, nb.TRIES = 60, 2  # noen frasesøk henger; hopp over dem


def conc(did, q):
    key = hashlib.sha1(f"{did}|{q}".encode()).hexdigest()[:16]
    path = nb._cache(f"context/{key}.json")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            d = nb._req(f"{nb.DHLAB}/conc", {"dhlabids": [int(did)], "query": q, "window": 25, "limit": 200,
                                             "html_formatting": False})
        except Exception as ex:  # noqa: BLE001
            print(f"  hoppet over {q[:40]}: {ex}", file=sys.stderr)
            return []
        path.write_text(json.dumps(list((d.get("conc") or {}).values()), ensure_ascii=False))
    return json.loads(path.read_text())


def _phrase(words):
    return '"' + " ".join(w.replace('"', "") for w in words) + '"'


def walk(did, words):
    """(før, etter): tekst foran og bak utdraget, funnet ved å søke på kantordene."""
    before, after = [], []
    head, tail = words[:3], words[-3:]
    for _ in range(STEPS):
        if len(tail) < 2:
            break
        got = None
        for t in conc(did, _phrase(tail)):
            w = t.split()
            for i in range(len(w) - len(tail) + 1):
                if w[i:i + len(tail)] == tail and len(w) > i + len(tail):
                    got = w[i + len(tail):]
                    break
            if got:
                break
        if not got:
            break
        after += got
        tail = got[-3:]
    for _ in range(STEPS):
        if len(head) < 2:
            break
        got = None
        for t in conc(did, _phrase(head)):
            w = t.split()
            for i in range(1, len(w) - len(head) + 1):
                if w[i:i + len(head)] == head:
                    got = w[:i]
                    break
            if got:
                break
        if not got:
            break
        before = got + before
        head = got[:3]
    return nb.clean(" ".join(before)), nb.clean(" ".join(after))


def main():
    want = set(json.loads(Path(sys.argv[1]).read_text()))
    out_path = Path(sys.argv[2])
    out = json.loads(out_path.read_text()) if out_path.exists() else {}
    # Samme id-er som nb_press: sha1(urn|renset tekst); rå tekst trengs til ordsøkene.
    docs, raw = {}, {}
    for q in nb.QUERIES:
        c = nb.corpus(q, True)
        docs.update(c)
        for did, txt in nb.concordances(q, list(map(int, c)), True):
            d = docs.get(did)
            if not d:
                continue
            sid = hashlib.sha1(f"{d['urn']}|{nb.clean(txt)}".encode()).hexdigest()[:12]
            if sid in want:
                raw.setdefault(sid, (did, txt))
    print(f"{len(raw)} av {len(want)} utdrag funnet", file=sys.stderr)
    for n, (sid, (did, txt)) in enumerate(sorted(raw.items())):
        if sid in out:
            continue
        before, after = walk(did, txt.split())
        issue = [nb.clean(t) for t in conc(did, ISSUE_Q)]
        out[sid] = {"before": before, "text": nb.clean(txt), "after": after,
                    "issue": [t for t in dict.fromkeys(issue) if t != nb.clean(txt)]}
        if n % 5 == 0:
            out_path.write_text(json.dumps(out, ensure_ascii=False, indent=0))
            print(f"  {n}/{len(raw)}", file=sys.stderr)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=0))


if __name__ == "__main__":
    main()
