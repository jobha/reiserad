# Reiserådkart

Verdenskart over Utenriksdepartementets reiseadvarsler, med regionale
advarsler og unntak tegnet inn. Live på **https://reiserad.haugsoen.com**
(reiseråd.haugsoen.com sender videre dit).

Feil i kartet? [Meld det her](https://github.com/jobha/reiserad/issues/new/choose).

- Mørk rød: UD fraråder alle reiser
- Oransjerød: UD fraråder reiser som ikke er strengt nødvendige
- Skravert: gjelder bare deler av området (eller ny regional advarsel som ikke er tegnet inn ennå)
- Klikk et område for UDs tekst og lenke til reiseinformasjonen

UDs side gjelder alltid. Regionale grenser er tegnet etter UDs tekst og er
omtrentlige der UD beskriver områder som ikke følger administrative grenser
(«innenfor 20 km fra grensen», «fjellområdene …»).

## Hvordan det virker

```
scraper/scrape.py   regjeringen.no  -> data/advisories.json   (alle ~195 landsider, faktaboksen «Reiseadvarsel»)
scraper/build.py    advisories + regions.json -> site/data/{info,world,zones}.json
scraper/pages.py    én side per land med advarsel (site/land/<slug>/), A–Å-oversikt, sitemap.xml, robots.txt
site/index.html     Leaflet-kart som leser site/data/
tools/og_image.py   site/og.png (delingsbilde) – kjøres for hånd
deploy/nginx.conf   nginx-oppsettet på Pi-en (301 fra reiseråd til reiserad)
```

- **Hele land** tegnes automatisk ut fra teksten («fraråder alle reiser til X»).
- **Regionale advarsler** er kartlagt for hånd i `data/regions.json`: provinser
  (geoBoundaries), buffere langs grenser (Natural Earth), punkter, linjer og
  håndtegnede polygoner. Soner tegnes i rekkefølge, senere soner overstyrer,
  og `level: "none"` skjærer ut unntak (f.eks. Nouakchott i Mauritania).
- `data/reviewed.json` holder en hash av UD-teksten da sonene ble tegnet. Endrer
  UD teksten, merkes landet «endret siden kartlegging» i kartet, og deploy-jobben
  åpner en issue. Et nytt land med regional advarsel som ikke er kartlagt, vises
  skravert i hele landet til det er tegnet inn.

## Oppdatere en kartlegging

```
python3 -m venv .venv && .venv/bin/pip install shapely
.venv/bin/python scraper/scrape.py                 # ferske data
# rediger data/regions.json
.venv/bin/python scraper/build.py                  # sjekk at alt bygger
.venv/bin/python scraper/build.py --stamp ukraina  # marker som gjennomgått
python3 -m http.server 8791 --directory site       # se på http://localhost:8791
git commit -am "..." && git push                   # deployer
```

## Drift

Hostes på **Vercel** i LegeOnline-teamet (prosjekt `reiserad`, domene `reiserad.no`;
`www.reiserad.no` sender videre). DNS for reiserad.no ligger i Cloudflare
(A `76.76.21.21`, www CNAME `cname.vercel-dns.com`, ikke proxied).

GitHub Actions (`.github/workflows/deploy.yml`) kjører ved push og hver tredje
time på en selvhostet runner på ig68-pi4 (`~/actions-runner-reiserad`, label
`reiserad`): skraper, bygger og deployer `site/` til Vercel med secret
`VERCEL_TOKEN`. Runneren må stå hjemme fordi regjeringen.no svarer 403 til
GitHubs datasentre. Er Pi-en nede, står siden bare med siste data. Endringer i UDs tekster committes tilbake til
`data/advisories.json`, så git-loggen er en historikk over reiserådene.

`reiserad.haugsoen.com` og `reiseråd.haugsoen.com` går fortsatt gjennom
Cloudflare-tunnelen til ig68-pi4, der nginx (`deploy/nginx.conf`) bare sender
videre til reiserad.no.

Vaksinelenkene går til LegeOnlines side for hvert land
(`legeonline.no/reisevaksiner/<slug>`); koblingen ligger i `data/legeonline.json`
og oppdateres med `tools/legeonline_slugs.py`.

Workflowen har bevisst ingen `pull_request`-trigger: repoet er offentlig, og
jobben har tilgang til Vercel-tokenet.

Reiserådkart er et gratis verktøy fra [LegeOnline](https://legeonline.no/). Avsender og reisevaksine-lenke styres i `data/site.json`.

Kartdata: Natural Earth (grenser, steder) og geoBoundaries (CC BY 4.0). Ingen kartfliser: etikettene tegnes av siden selv, så den trenger ingen API-nøkler.
