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
scraper/pages.py    én statisk side per land (site/land/<slug>/), A–Å-oversikt, sitemap.xml, robots.txt
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

GitHub Actions på en selvhostet runner på ig68-pi4 (`~/actions-runner-reiserad`,
label `reiserad`) kjører ved push og hver tredje time: skraper, bygger, kopierer
`site/` til `~/selfhost/haugsoen/reiserad`, som nginx-containeren `haugsoen-reiserad`
serverer bak Cloudflare-tunnelen `ig68-haugsoen` (begge vertsnavn, med
Access-unntak «public, bypass» siden `*.haugsoen.com` ellers krever innlogging). Endringer i UDs tekster
committes tilbake til `data/advisories.json`, så git-loggen er en historikk
over reiserådene.

Workflowen har bevisst ingen `pull_request`-trigger: repoet er offentlig, og
runneren kjører på hjemmenettet.

Reiserådkart er et gratis verktøy fra [LegeOnline](https://legeonline.no/). Avsender og reisevaksine-lenke styres i `data/site.json`.

Kartdata: Natural Earth (grenser, steder) og geoBoundaries (CC BY 4.0). Ingen kartfliser: etikettene tegnes av siden selv, så den trenger ingen API-nøkler.
