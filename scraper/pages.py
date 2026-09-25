"""Statiske sider for søkemotorer: én side per land, en A–Å-oversikt,
sitemap.xml og robots.txt. Kalles fra build.py med ferdig beregnede data."""
import html
import shutil
import json
import math
import urllib.parse

SITE = "https://reiserad.no"
REPO = "https://github.com/jobha/reiserad"
LEVEL_TXT = {
    "all": "UD fraråder alle reiser",
    "necessary": "UD fraråder reiser som ikke er strengt nødvendige",
}
COLORS = {"all": "#b3122e", "necessary": "#ef6a3a"}

e = html.escape


def issue_url(name, url):
    q = urllib.parse.urlencode({
        "template": "feil-i-kartet.yml",
        "title": f"Feil i kartet: {name}",
        "land": name,
        "ud": url,
    })
    return f"{REPO}/issues/new?{q}"


def svg_map(country, zones):
    """Lite kart over landet med sonene, som inline SVG."""
    minx, miny, maxx, maxy = country.bounds
    # Land som krysser datolinjen (Russland, Fiji, Kiribati) blir for brede; ta største del.
    if maxx - minx > 180:
        parts = sorted(getattr(country, "geoms", [country]), key=lambda g: g.area, reverse=True)
        minx, miny, maxx, maxy = parts[0].bounds
    k = math.cos(math.radians((miny + maxy) / 2))
    w, h = max((maxx - minx) * k, 1e-3), max(maxy - miny, 1e-3)
    W = 640
    H = max(160, min(520, W * h / w))
    s = min((W - 20) / w, (H - 20) / h)
    ox = (W - w * s) / 2
    oy = (H - h * s) / 2

    def path(g):
        out = []
        for poly in getattr(g, "geoms", [g]):
            if poly.geom_type != "Polygon":
                continue
            for ring in [poly.exterior, *poly.interiors]:
                pts = [f"{ox + (x - minx) * k * s:.1f},{oy + (maxy - y) * s:.1f}" for x, y in ring.coords]
                out.append("M" + "L".join(pts) + "Z")
        return "".join(out)

    body = [f'<path d="{path(country)}" fill="var(--land)" stroke="var(--land-line)" stroke-width="1"/>']
    for z, level, partial in zones:
        fill = "url(#hatch)" if partial else COLORS[level]
        body.append(f'<path d="{path(z)}" fill="{fill}" fill-opacity="{1 if partial else .85}" stroke="{COLORS[level]}" stroke-width=".6"/>')
    return (f'<svg viewBox="0 0 {W} {H:.0f}" role="img" aria-label="Kart over reiseadvarselen" class="mini">'
            '<defs><pattern id="hatch" patternUnits="userSpaceOnUse" width="7" height="7" patternTransform="rotate(45)">'
            '<rect width="7" height="7" fill="#ef6a3a" fill-opacity=".18"/>'
            '<line x1="0" y1="0" x2="0" y2="7" stroke="#ef6a3a" stroke-width="3.2"/></pattern></defs>'
            + "".join(body) + "</svg>")


STYLE = """
:root { --bg:#f4f1ec; --card:#fff; --text:#1d1d1f; --muted:#66646b; --line:#e2ddd5; --all:#b3122e; --nec:#ef6a3a;
  --land:#fbfaf7; --land-line:#cfc8bc; --link:#0b5cad; --warn-bg:#fff3d6; --warn:#7a5200; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#121316; --card:#1c1d21; --text:#ecebef;
  --muted:#a4a2ab; --line:#34353b; --all:#e0314f; --nec:#f08a4b; --land:#24262b; --land-line:#3b3d44; --link:#7cb6ff;
  --warn-bg:#3a2f14; --warn:#f3cf7a; } }
:root[data-theme="dark"] { --bg:#121316; --card:#1c1d21; --text:#ecebef; --muted:#a4a2ab; --line:#34353b; --all:#e0314f;
  --nec:#f08a4b; --land:#24262b; --land-line:#3b3d44; --link:#7cb6ff; --warn-bg:#3a2f14; --warn:#f3cf7a; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font:16px/1.6 Inter, system-ui, -apple-system, sans-serif; }
main { max-width:760px; margin:0 auto; padding:24px 16px 48px; }
a { color:var(--link); }
nav.crumbs { font-size:14px; color:var(--muted); margin-bottom:8px; }
nav.crumbs a { color:var(--muted); }
h1 { font-size:30px; line-height:1.2; letter-spacing:-.015em; margin:4px 0 12px; }
h2 { font-size:18px; margin:28px 0 8px; }
.badge { display:inline-block; padding:6px 12px; border-radius:8px; font-weight:600; font-size:15px; color:#fff; }
.badge.all { background:var(--all); } .badge.necessary { background:var(--nec); }
.badge.none { background:transparent; color:var(--text); border:1px solid var(--line); font-weight:500; }
.status { color:var(--muted); font-size:13px; text-transform:uppercase; letter-spacing:.03em; margin-top:10px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; margin:16px 0; }
svg.mini { width:100%; height:auto; display:block; }
.lead { font-size:17px; }
ul.zones { padding-left:0; list-style:none; }
ul.zones li { display:flex; gap:10px; align-items:baseline; margin:6px 0; }
.sw { width:14px; height:11px; border-radius:3px; flex:none; transform:translateY(1px); }
.note { background:var(--warn-bg); color:var(--warn); padding:10px 12px; border-radius:10px; font-size:14px; }
.actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:20px; }
.btn { display:inline-block; padding:10px 14px; border-radius:10px; text-decoration:none; font-weight:600; border:1px solid var(--line); }
.btn.primary { background:var(--link); color:#fff; border-color:var(--link); }
footer { color:var(--muted); font-size:13px; margin-top:40px; border-top:1px solid var(--line); padding-top:14px; }
footer a { color:var(--muted); }
.az { columns:2 220px; padding:0; list-style:none; }
.az li { break-inside:avoid; margin:3px 0; display:flex; gap:8px; align-items:baseline; }
.az .dot { width:9px; height:9px; border-radius:50%; flex:none; transform:translateY(-1px); }
.az .tag { color:var(--muted); font-size:13px; }
.vax { margin-top:24px; padding:14px 16px; border-radius:12px; background:var(--card); border:1px solid var(--line); font-size:15px; }
.vax a { font-weight:600; white-space:nowrap; }
"""


SITE_CFG = {}  # settes av write_all fra data/site.json


def utm(url, campaign):
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}utm_source=reiserad&utm_medium=referral&utm_campaign={campaign}"


def vax_box(rec):
    if not rec.get("vax_url"):
        return ""
    return (f'<aside class="vax"><b>Skal du til {e(rec["name"])}?</b> '
            f'{e(SITE_CFG["publisher"]["name"])} gir råd om reisevaksiner og reisemedisin før reisen. '
            f'<a href="{e(utm(rec["vax_url"], "landside"))}">Reisevaksiner for {e(rec["name"])} →</a></aside>')


def page(title, desc, canonical, body, jsonld=None):
    ld = f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>' if jsonld else ""
    return f"""<!doctype html>
<html lang="nb">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:locale" content="nb_NO">
<meta property="og:site_name" content="Reiserådkart">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="{SITE}/og.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap">
<style>{STYLE}</style>
{ld}
</head>
<body>
<main>
{body}
<footer>
  Reiserådkart viser Utenriksdepartementets reiseadvarsler på kart. Teksten er hentet automatisk fra
  <a href="https://www.regjeringen.no/no/tema/utenrikssaker/reiseinformasjon/velg-land/id2414273/">regjeringen.no</a>
  og oppdateres hver tredje time. Regionale grenser er tegnet etter UDs beskrivelse og kan være omtrentlige –
  UDs egen side gjelder alltid. Dette er ikke en offisiell tjeneste fra UD.<br>
  Reiserådkart er et gratis verktøy fra <a href="{utm(SITE_CFG["publisher"]["url"], "bunntekst")}">{e(SITE_CFG["publisher"]["name"])}</a>.<br>
  <a href="/">Verdenskart</a> · <a href="/land/">Alle land A–Å</a> ·
  <a href="{REPO}">Kildekode på GitHub</a> · <a href="{REPO}/issues/new/choose">Meld feil eller foreslå endring</a>
</footer>
</main>
</body>
</html>
"""


def describe(rec):
    """Kort, søkevennlig beskrivelse (meta description)."""
    name = rec["name"]
    if not rec["level"]:
        lead = f"UD har ingen reiseadvarsel for {name}."
    elif rec.get("regional") or rec.get("unmapped"):
        lead = f"UD fraråder reiser til deler av {name}."
    else:
        lead = f"{LEVEL_TXT[rec['level']]} til {name}."
    rest = rec.get("ingress") or " ".join(rec.get("paragraphs") or [])
    text = f"{lead} {rest}".strip()
    return text if len(text) <= 158 else text[:155].rsplit(" ", 1)[0] + " …"


def country_page(iso, rec, country, zones, fetched):
    name = rec["name"]
    slug = rec["slug"]
    canonical = f"{SITE}/land/{slug}/"
    if not rec["level"]:
        badge = '<span class="badge none">Ingen reiseadvarsel fra UD</span>'
    elif rec.get("regional") or rec.get("unmapped"):
        badge = f'<span class="badge {rec["level"]}">UD fraråder reiser til deler av landet</span>'
    else:
        badge = f'<span class="badge {rec["level"]}">{LEVEL_TXT[rec["level"]]} til hele landet</span>'

    b = [f'<nav class="crumbs"><a href="/">Reiserådkart</a> › <a href="/land/">Alle land</a> › {e(name)}</nav>',
         f"<h1>Reiseråd for {e(name)}</h1>", badge]
    if rec.get("status"):
        b.append(f'<div class="status">{e(rec["status"])}</div>')
    if zones:
        b.append(f'<div class="card">{svg_map(country, [(z, l, p) for z, l, p, _ in zones])}</div>')
    if rec.get("ingress"):
        b.append(f'<p class="lead">{e(rec["ingress"])}</p>')
    if rec.get("paragraphs"):
        b.append("<h2>UDs reiseadvarsel</h2>")
        b += [f"<p>{e(p)}</p>" for p in rec["paragraphs"]]
    if rec.get("regional"):
        items = []
        seen = set()
        for _, level, _, label in zones:
            if label and (label, level) not in seen:
                seen.add((label, level))
                items.append(f'<li><span class="sw" style="background:{COLORS[level]}"></span>'
                             f'<span><b>{e(label)}</b> – {e(LEVEL_TXT[level].replace("UD fraråder", "fraråder"))}</span></li>')
        if items:
            b.append("<h2>Områder på kartet</h2><ul class=\"zones\">" + "".join(items) + "</ul>")
        if rec.get("exceptions"):
            b.append("<p><b>Ikke omfattet:</b> " + ", ".join(e(x) for x in rec["exceptions"]) + ".</p>")
    if rec.get("unmapped"):
        b.append('<p class="note">UD har en regional advarsel her som ikke er tegnet inn på kartet ennå. Les UDs tekst for hvilke områder den gjelder.</p>')
    if rec.get("stale"):
        b.append('<p class="note">UD har endret teksten siden områdene ble tegnet inn. Les UDs tekst.</p>')
    b.append(f'<div class="actions"><a class="btn primary" href="{e(rec["url"])}">Les hele reiserådet hos UD</a>'
             f'<a class="btn" href="/#{slug}">Se på verdenskartet</a>'
             f'<a class="btn" href="{e(issue_url(name, rec["url"]))}">Meld feil i kartet</a></div>')
    b.append(vax_box(rec))

    title = f"Reiseråd for {name} – UDs reiseadvarsel på kart"
    ld = {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "url": canonical,
        "inLanguage": "nb",
        "dateModified": fetched[:10],
        "isBasedOn": rec["url"],
        "publisher": {"@type": "Organization", "name": SITE_CFG["publisher"]["name"], "url": SITE_CFG["publisher"]["url"]},
        "breadcrumb": {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Reiserådkart", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Alle land", "item": SITE + "/land/"},
            {"@type": "ListItem", "position": 3, "name": name, "item": canonical},
        ]},
    }
    return page(title, describe(rec), canonical, "\n".join(b), ld)


def index_page(info):
    rows = list(info.values())
    # Norsk alfabetisk: Æ Ø Å til slutt.
    order = {c: i for i, c in enumerate("abcdefghijklmnopqrstuvwxyzæøå")}
    rows.sort(key=lambda r: [order.get(ch, 99) for ch in r["name"].lower()])
    n = sum(1 for r in rows if r["level"])
    li = []
    for r in rows:
        col = COLORS.get(r["level"], "transparent")
        tag = ("ingen advarsel" if not r["level"]
               else "deler av landet" if r.get("regional") or r.get("unmapped") else "hele landet")
        border = "" if r["level"] else "border:1px solid var(--line);"
        li.append(f'<li><span class="dot" style="background:{col};{border}"></span>'
                  + (f'<a href="/land/{r["slug"]}/">{e(r["name"])}</a>' if r["level"]
                     else f'<a href="{e(r["url"])}" rel="noopener">{e(r["name"])}</a>')
                  + f'<span class="tag">{tag}</span></li>')
    body = (f'<nav class="crumbs"><a href="/">Reiserådkart</a> › Alle land</nav>'
            f"<h1>Reiseråd for alle land A–Å</h1>"
            f'<p class="lead">Utenriksdepartementet har reiseadvarsel for {n} av {len(rows)} land. '
            f'Rødt betyr at UD fraråder alle reiser, oransje at UD fraråder reiser som ikke er strengt nødvendige. '
            f'Se alt samlet på <a href="/">verdenskartet</a>.</p>'
            f'<ul class="az">{"".join(li)}</ul>')
    desc = f"Oversikt over UDs reiseråd for alle land. UD fraråder i dag reiser til {n} land, helt eller delvis. Se reiseadvarslene på kart."
    return page("Reiseråd for alle land A–Å – UDs reiseadvarsler", desc, SITE + "/land/", body)


def write_all(out_dir, info, geoms, zones_by_iso, fetched, site):
    SITE_CFG.clear()
    SITE_CFG.update(site)
    """out_dir = site/. geoms[iso] = landflate, zones_by_iso[iso] = [(geom, level, partial, label)]."""
    # Bare land med reiseadvarsel får egen side. For de andre ville siden bare
    # gjentatt UDs ingress – tynt innhold som konkurrerer med UD og LegeOnline.
    land = out_dir / "land"
    shutil.rmtree(land, ignore_errors=True)
    land.mkdir()
    urls = [(SITE + "/", fetched[:10], "1.0"), (SITE + "/land/", fetched[:10], "0.8")]
    for iso, rec in info.items():
        if not rec["level"]:
            continue
        d = land / rec["slug"]
        d.mkdir(exist_ok=True)
        (d / "index.html").write_text(country_page(iso, rec, geoms[iso], zones_by_iso.get(iso, []), fetched))
        urls.append((f"{SITE}/land/{rec['slug']}/", fetched[:10], "0.7"))
    (land / "index.html").write_text(index_page(info))
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    sm += [f"<url><loc>{u}</loc><lastmod>{m}</lastmod><priority>{p}</priority></url>" for u, m, p in urls]
    sm.append("</urlset>")
    (out_dir / "sitemap.xml").write_text("\n".join(sm) + "\n")
    (out_dir / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")
    return len(urls)

