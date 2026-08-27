"""
Krillo - fase 5 punt 14: bronanalyse. Waaróm noemt AI die andere winkels wel?

Tot nu toe meet Krillo dát een winkel niet genoemd wordt. Niet waardoor. Dat is
precies de kritiek die op het ondernemersforum kwam: een cijfer vraagt om een
specialist, en een winkelier kan er zelf niets mee. Op de eigen site staat al
dat ongeveer 85 procent van wat AI over een merk zegt uit externe bronnen komt.
De hefboom ligt dus buiten de winkel, en daar keek Krillo nog helemaal niet.

DE REGEL DIE HIER VASTLIGT, EN DIE NOOIT GEBROKEN MAG WORDEN:

    Vraag NOOIT aan een AI-model waarom het een winkel aanbeveelt.

Een model weet dat niet. Het herkent een patroon uit zijn training en verzint
achteraf een verklaring die overtuigend klinkt. Dat is geen bron, dat is een
gok met een net pak aan. Het zou ook Krillo's eigen regel over FEIT tegenover
VERMOEDEN breken, en dat is het enige waar dit product op drijft.

WAT WE IN PLAATS DAARVAN DOEN:

1. We nemen de koopvraag zelf en stoppen die in een echte zoekmachine. Dat is
   letterlijk wat een koper zou intypen, en het levert de pagina's op die over
   dat onderwerp gaan.
2. We halen die pagina's op en lezen ze.
3. We kijken met platte tekstvergelijking wie erop staat: de concurrenten die
   in het AI-antwoord genoemd werden, en onze eigen winkel.

Wat er uitkomt is een feit met een adres erbij: op zeven van de elf pagina's
over dit onderwerp staat je concurrent, en jij op geen enkele. Hier zijn die
zeven pagina's. Geen mening, geen model dat iets interpreteert, en dus altijd
dezelfde uitkomst bij dezelfde invoer. Net als de kostenberekening: bewust een
vast rekenmodel en geen AI.

Wat dit BEWUST NIET beweert: dat je genoemd wordt zodra je op die pagina's
staat. Dat weten we niet en dat meten we niet. We laten zien waar het verschil
zit, niet wat het verschil veroorzaakt.
"""

import os
import re
import time
from urllib.parse import urlparse

import requests

import kosten
import scan_engine

# Noodrem, net als METINGEN_AAN. Zet BRONNEN_AAN op "nee" in Render en er wordt
# niets meer gezocht, zonder dat er code aangepast hoeft te worden.
BRONNEN_AAN = os.environ.get("BRONNEN_AAN", "ja").strip().lower() not in ("nee", "no", "false", "0")

# Welke zoekmachine. Twee mogelijkheden, allebei ongeveer 5 dollar per duizend
# zoekopdrachten. Bewust twee, zodat een prijswijziging of een dichtgaande
# gratis laag bij de een geen code-aanpassing kost: het is één regel in Render.
ZOEK_AANBIEDER = os.environ.get("ZOEK_AANBIEDER", "brave").strip().lower()

# Hoeveel koopvragen we per meetronde natrekken. Bewust laag. Dertig vragen
# natrekken zou dertig zoekopdrachten en tweehonderd paginabezoeken kosten, en
# de winst zit in de eerste paar: als dezelfde vergelijkingssite bij drie
# vragen bovendrijft, weet je genoeg.
MAX_VRAGEN_PER_RONDE = int(os.environ.get("BRONNEN_MAX_VRAGEN", "4"))

# Hoeveel zoekresultaten we per vraag ophalen en echt bezoeken. Verder dan de
# eerste pagina van een zoekmachine kijkt een koper ook niet.
MAX_RESULTATEN = int(os.environ.get("BRONNEN_MAX_RESULTATEN", "10"))
MAX_PAGINAS = int(os.environ.get("BRONNEN_MAX_PAGINAS", "8"))

# Hoeveel concurrenten we volgen. Meer dan dit maakt de uitkomst een tabel in
# plaats van een antwoord.
MAX_CONCURRENTEN = int(os.environ.get("BRONNEN_MAX_CONCURRENTEN", "5"))

# Wat een zoekopdracht kost, in euro. Vijf dollar per duizend is de prijs bij
# zowel Brave als Google, omgerekend ongeveer 0,0045 euro per stuk.
#
# LET OP: net als bij de tokenprijzen in kosten.py is dit een startpunt en geen
# contract. Controleer het in je eigen facturatie-overzicht bij de aanbieder
# voordat je er marges op baseert.
PRIJS_PER_ZOEKOPDRACHT_EURO = float(os.environ.get("BRONNEN_PRIJS_PER_ZOEKOPDRACHT", "0.0045"))

# Minimaal aantal seconden tussen twee zoekopdrachten. De goedkopere plannen bij
# beide aanbieders laten er maar een paar per seconde toe, en een 429 hier is
# net zo vervelend als bij de metingen.
MIN_INTERVAL = float(os.environ.get("BRONNEN_INTERVAL", "1.2"))

# Tijdslimiet per opgehaalde pagina. Korter dan bij de eigen scan van een klant:
# dit zijn vreemde sites en er zijn er veel, dus een trage pagina mag de hele
# ronde niet ophouden. Missen we er een, dan telt die gewoon niet mee.
PAGINA_TIJDSLIMIET = int(os.environ.get("BRONNEN_PAGINA_TIJDSLIMIET", "12"))

# Hoeveel tekst we per pagina meenemen. Een naam die pas in de voettekst van
# een pagina van 200.000 tekens staat, is geen vermelding waar iemand iets aan
# heeft.
MAX_PAGINATEKENS = int(os.environ.get("BRONNEN_MAX_PAGINATEKENS", "60000"))

_laatste_zoekopdracht = [0.0]


# ---------------------------------------------------------------------------
# De zoekmachines
# ---------------------------------------------------------------------------

def beschikbaar():
    """Of er een werkende zoekmachine ingesteld is.

    Staat er geen sleutel, dan doet de bronanalyse niets en draait de rest van
    Krillo gewoon door. Nooit crashen op een ontbrekende sleutel: dat is
    dezelfde afspraak als bij de metingen."""
    if not BRONNEN_AAN:
        return False
    if ZOEK_AANBIEDER == "brave":
        return bool(os.environ.get("BRAVE_API_KEY"))
    if ZOEK_AANBIEDER == "google":
        return bool(os.environ.get("GOOGLE_ZOEK_API_KEY") and os.environ.get("GOOGLE_ZOEK_CX"))
    return False


def waarom_niet():
    """In gewone taal waarom de bronanalyse niet draait. Voor de beheerpagina,
    zodat je niet hoeft te raden waarom er niets gebeurt."""
    if not BRONNEN_AAN:
        return "De bronanalyse staat uit (BRONNEN_AAN)."
    if ZOEK_AANBIEDER == "brave":
        return "Er is geen BRAVE_API_KEY ingesteld in Render."
    if ZOEK_AANBIEDER == "google":
        return ("Er is geen GOOGLE_ZOEK_API_KEY en GOOGLE_ZOEK_CX ingesteld in Render. "
                "Dat zijn andere waarden dan de GOOGLE_API_KEY voor Gemini.")
    return (f"ZOEK_AANBIEDER staat op '{ZOEK_AANBIEDER}', en dat kent Krillo niet. "
            f"Gebruik 'brave' of 'google'.")


def _wacht_je_beurt():
    te_wachten = MIN_INTERVAL - (time.monotonic() - _laatste_zoekopdracht[0])
    if te_wachten > 0:
        time.sleep(te_wachten)
    _laatste_zoekopdracht[0] = time.monotonic()


def _zoek_brave(vraag):
    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={
            "X-Subscription-Token": os.environ["BRAVE_API_KEY"],
            "Accept": "application/json",
        },
        params={
            "q": vraag,
            "count": MAX_RESULTATEN,
            "country": "nl",
            "search_lang": "nl",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    uit = []
    for r in ((data.get("web") or {}).get("results") or []):
        if r.get("url"):
            uit.append({
                "url": r["url"],
                "titel": (r.get("title") or "").strip(),
                "omschrijving": (r.get("description") or "").strip(),
            })
    return uit


def _zoek_google(vraag):
    resp = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": os.environ["GOOGLE_ZOEK_API_KEY"],
            "cx": os.environ["GOOGLE_ZOEK_CX"],
            "q": vraag,
            "num": min(MAX_RESULTATEN, 10),
            "gl": "nl",
            "hl": "nl",
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    uit = []
    for r in (data.get("items") or []):
        if r.get("link"):
            uit.append({
                "url": r["link"],
                "titel": (r.get("title") or "").strip(),
                "omschrijving": (r.get("snippet") or "").strip(),
            })
    return uit


_ZOEKERS = {"brave": _zoek_brave, "google": _zoek_google}


def zoek(vraag, webshop_url=None):
    """Eén zoekopdracht, met de kosten erbij geregistreerd.

    Geeft altijd een lijst terug, ook bij een storing. Een zoekmachine die
    even niet werkt mag de meetronde niet omgooien: dan is er die week geen
    bronanalyse, en dat staat er dan gewoon bij."""
    zoeker = _ZOEKERS.get(ZOEK_AANBIEDER)
    if zoeker is None:
        return []

    gestart = time.monotonic()
    try:
        _wacht_je_beurt()
        resultaten = zoeker(vraag)
        gelukt, foutsoort = True, None
    except Exception as e:
        resultaten = []
        gelukt = False
        body = getattr(getattr(e, "response", None), "text", "") or ""
        foutsoort = (f"{type(e).__name__}: {e}"[:200]
                     + (" | " + " ".join(body.split())[:200] if body else ""))[:400]
        print(f"Zoekopdracht mislukt: {foutsoort}")

    kosten.registreer_vaste_kosten(
        soort="bronnen-zoeken",
        provider=ZOEK_AANBIEDER,
        bedrag=PRIJS_PER_ZOEKOPDRACHT_EURO if gelukt else 0.0,
        webshop_url=webshop_url,
        duur_ms=int((time.monotonic() - gestart) * 1000),
        gelukt=gelukt,
        foutsoort=foutsoort,
    )
    return resultaten


# ---------------------------------------------------------------------------
# Namen herkennen op een pagina
# ---------------------------------------------------------------------------

# Wat er tussen twee delen van een winkelnaam mag staan. Dille & Kamille komt
# voor als "Dille & Kamille", "Dille en Kamille", "dille-kamille" in een link en
# "dillekamille" in een bestandsnaam. Dat is allemaal dezelfde winkel. Zoeken we
# alleen op de letterlijke schrijfwijze, dan tellen we een vermelding als
# afwezig, en dat is de ergste fout die deze stap kan maken: dan vertel je een
# klant dat hij ergens niet staat terwijl hij er wel staat.
_SCHEIDING = r"(?:[\s\-_/&.,'’]|\ben\b|\band\b)*"

# Lidwoorden vooraan mogen ontbreken. De Bijenkorf staat op veel pagina's
# gewoon als Bijenkorf.
_LIDWOORDEN = {"de", "het", "een", "the"}

# Deze woorden zijn geen deel van de naam maar een verbinding ertussen.
_VERBINDINGEN = {"en", "and"}


def _normaliseer(tekst):
    """Maakt tekst vergelijkbaar: kleine letters, HTML-tekens terug naar hun
    echte teken, en alle witruimte tot een spatie."""
    laag = (tekst or "").lower()
    laag = laag.replace("&amp;", "&").replace("&#38;", "&").replace("&nbsp;", " ")
    return " ".join(laag.split())


def _naampatroon(naam):
    """Zet een winkelnaam om in één zoekpatroon dat alle schrijfwijzen vangt.

    Bewust één patroon en geen lijstje varianten: met een lijstje mis je altijd
    de schrijfwijze waar je niet aan gedacht had. Zo staat er tussen elk deel
    van de naam simpelweg dat er van alles mag zitten, of niets.

    Geeft None terug bij een naam die te kort is om betrouwbaar te herkennen.
    Drie letters leveren toevalstreffers op, en een verzonnen vindplaats is
    erger dan een gemiste."""
    delen = [d for d in re.split(r"[^a-z0-9]+", _normaliseer(naam)) if d]
    delen = [d for d in delen if d not in _VERBINDINGEN]
    if not delen:
        return None
    if len("".join(delen)) < 4:
        return None

    stukken = []
    for i, deel in enumerate(delen):
        vast = re.escape(deel)
        # Een lidwoord vooraan mag weggelaten zijn, maar alleen als er nog een
        # echt deel achter komt.
        if i == 0 and deel in _LIDWOORDEN and len(delen) > 1:
            stukken.append(f"(?:{vast}{_SCHEIDING})?")
        else:
            stukken.append(vast)
            if i < len(delen) - 1:
                stukken.append(_SCHEIDING)

    return r"(?<![a-z0-9])" + "".join(stukken) + r"(?![a-z0-9])"


def _kern_van_domein(url):
    """Het herkenbare deel van een webadres: bergzicht-outdoor.nl wordt
    bergzichtoutdoor."""
    try:
        netloc = urlparse(url if "//" in url else "https://" + url).netloc.lower()
    except ValueError:
        return ""
    netloc = netloc.split(":")[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    kern = netloc.split(".")[0]
    return re.sub(r"[^a-z0-9]", "", kern)


def komt_voor(tekst, naam, ook_domein=None):
    """Staat deze winkel op deze pagina?

    Bewust streng op woordgrenzen. Zonder dat zou "Xenos" ook meetellen in
    "xenostudio", en dan zeg je tegen een klant dat zijn concurrent ergens
    staat terwijl dat niet zo is. Liever een vermelding missen dan er een
    verzinnen: dit hele product hangt aan de belofte dat we niets beweren wat
    we niet kunnen aanwijzen."""
    if not tekst:
        return False

    laag = _normaliseer(tekst)

    # Een link naar het webadres is het sterkste bewijs dat er is. Een pagina
    # die naar bergzicht-outdoor.nl linkt noemt die winkel, ook als de naam er
    # anders geschreven staat of alleen een logo te zien is.
    if ook_domein:
        kern = _kern_van_domein(ook_domein)
        if kern and len(kern) >= 4 and kern in re.sub(r"[^a-z0-9]", "", laag):
            return True

    patroon = _naampatroon(naam)
    return bool(patroon and re.search(patroon, laag))


def _haal_pagina(url):
    """De leesbare tekst van een externe pagina. Eén poging, korte limiet.

    Anders dan bij de eigen scan van een klant proberen we het hier niet drie
    keer. Dit zijn tientallen vreemde sites per ronde en een enkele die niet
    reageert mag de rest niet ophouden."""
    try:
        resp = requests.get(url, headers=scan_engine.HEADERS, timeout=PAGINA_TIJDSLIMIET)
        if resp.status_code >= 400:
            return ""
        soort = (resp.headers.get("Content-Type") or "").lower()
        if soort and "html" not in soort and "text" not in soort:
            return ""
        html = resp.text[:400000]
    except requests.RequestException:
        return ""

    if scan_engine.lijkt_op_blokkadepagina(html):
        return ""

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()
        # De links tellen mee: een vergelijkingssite noemt een winkel vaak
        # alleen in de link eronder, en dat is net zo goed een vermelding.
        linkjes = " ".join(a.get("href") or "" for a in soup.find_all("a", href=True))
        tekst = " ".join(soup.get_text(" ", strip=True).split())
        return (tekst + " " + linkjes)[:MAX_PAGINATEKENS]
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# De analyse
# ---------------------------------------------------------------------------

def kies_vragen(klantbeeld, grens=None):
    """Welke koopvragen trekken we na.

    De vragen waar we NIET genoemd worden zijn de interessante: daar zit het
    gat. Vragen waar we wel al bovendrijven hoeven we niet na te trekken, want
    daar is niets op te lossen. Binnen die groep pakken we eerst de vragen waar
    de meeste concurrenten opdoken, want daar is het onderwerp duidelijk druk
    en valt er dus echt iets te halen."""
    grens = grens or MAX_VRAGEN_PER_RONDE
    regels = [r for r in ((klantbeeld or {}).get("regels") or []) if r.get("telt_mee")]
    gemist = [r for r in regels if not r.get("genoemd")]

    # Word je overal genoemd, dan is er geen gat. Dan kijken we naar de vragen
    # waar je wel genoemd maar niet aanbevolen wordt: daar staat het verschil
    # tussen erbij staan en aangeraden worden.
    if not gemist:
        gemist = [r for r in regels if not r.get("aanbevolen")]

    gemist.sort(key=lambda r: -(r.get("aantal_winkels") or 0))
    return [r["vraag"] for r in gemist[:grens] if r.get("vraag")]


def kies_concurrenten(klantbeeld, grens=None):
    """De concurrenten die we op de gevonden pagina's opzoeken.

    Onze eigen winkel gaat er expres uit: die staat apart in de uitkomst, want
    de hele vraag is waar zij wel staan en wij niet."""
    grens = grens or MAX_CONCURRENTEN
    lijst = [c for c in ((klantbeeld or {}).get("concurrenten") or []) if not c.get("wij")]
    lijst.sort(key=lambda c: (c.get("aanbevolen") or 0, c.get("genoemd") or 0), reverse=True)
    return [c["naam"] for c in lijst[:grens] if c.get("naam")]


def analyseer(webshop_url, klantbeeld, winkelnaam=None, meting_id=None, melden=None):
    """De hele bronanalyse voor één webshop.

    Geeft een lijst vindplaatsen terug: per externe pagina wie erop staat.
    Bewaren doet de aanroeper, zodat deze functie zelf niets van de database
    hoeft te weten en dus los te testen is."""
    def zeg(tekst):
        if melden:
            try:
                melden(tekst)
            except Exception:
                pass

    if not beschikbaar():
        print(f"Bronanalyse overgeslagen voor {webshop_url}: {waarom_niet()}")
        return []

    vragen = kies_vragen(klantbeeld)
    concurrenten = kies_concurrenten(klantbeeld)
    if not vragen:
        print(f"Bronanalyse overgeslagen voor {webshop_url}: geen vragen om na te trekken.")
        return []
    if not concurrenten:
        print(f"Bronanalyse overgeslagen voor {webshop_url}: geen concurrenten gevonden.")
        return []

    ons_domein = _kern_van_domein(webshop_url)
    onze_namen = [n for n in (winkelnaam, ons_domein) if n]

    vindplaatsen = []
    gezien = set()

    for nummer, vraag in enumerate(vragen, start=1):
        rem = kosten.mag_doorgaan(webshop_url=webshop_url)
        if not rem["mag"]:
            print(f"Bronanalyse gestopt door de kostenrem: {rem['reden']}")
            break

        zeg(f"externe bronnen zoeken ({nummer} van {len(vragen)})")
        resultaten = zoek(vraag, webshop_url=webshop_url)
        if not resultaten:
            continue

        bekeken = 0
        for r in resultaten:
            if bekeken >= MAX_PAGINAS:
                break

            url = r["url"]
            domein_kern = _kern_van_domein(url)

            # De eigen site van de klant is geen externe bron. Dat jij op je
            # eigen website staat wisten we al.
            if ons_domein and domein_kern == ons_domein:
                continue

            # Dezelfde pagina bij twee vragen tellen we een keer per vraag,
            # maar we halen hem niet twee keer op.
            sleutel = (vraag, url)
            if sleutel in gezien:
                continue
            gezien.add(sleutel)

            tekst = _haal_pagina(url)
            bekeken += 1
            if not tekst:
                continue

            # Staat de pagina op het domein van een concurrent zelf, dan is het
            # zijn eigen website en geen externe bron. Dat wij daar niet op
            # staan zegt niets.
            eigen_site_van = next(
                (c for c in concurrenten
                 if domein_kern and domein_kern == re.sub(r"[^a-z0-9]", "", c.lower().replace(" ", ""))),
                None,
            )

            gevonden = [c for c in concurrenten if komt_voor(tekst, c)]
            wij = any(komt_voor(tekst, n, ook_domein=webshop_url) for n in onze_namen) \
                if onze_namen else komt_voor(tekst, "", ook_domein=webshop_url)

            # Een pagina waar niemand op staat zegt niets over het verschil
            # tussen jou en je concurrent. Die laten we weg, anders verzuipt de
            # uitkomst in ruis.
            if not gevonden and not wij:
                continue

            vindplaatsen.append({
                "meting_id": meting_id,
                "webshop_url": webshop_url,
                "vraag": vraag,
                "bron_url": url,
                "bron_titel": r.get("titel") or "",
                "bron_domein": (urlparse(url).netloc or "").replace("www.", ""),
                "eigen_site_van": eigen_site_van,
                "wij_genoemd": bool(wij),
                "concurrenten": gevonden,
            })

    print(f"Bronanalyse klaar voor {webshop_url}: {len(vindplaatsen)} vindplaatsen "
          f"over {len(vragen)} vragen.")
    return vindplaatsen


def vat_samen(vindplaatsen, winkelnaam=None):
    """Het beeld dat de klant te zien krijgt.

    Aantallen, geen percentages, net als overal in Krillo. En alleen echte
    externe bronnen: de eigen website van een concurrent telt niet mee, want
    dat iemand op zijn eigen site staat is geen verdienste."""
    extern = [v for v in (vindplaatsen or []) if not v.get("eigen_site_van")]
    if not extern:
        return None

    wij_erop = [v for v in extern if v.get("wij_genoemd")]

    per_concurrent = {}
    for v in extern:
        for naam in (v.get("concurrenten") or []):
            regel = per_concurrent.setdefault(naam, {"naam": naam, "paginas": 0, "voorbeelden": []})
            regel["paginas"] += 1
            if len(regel["voorbeelden"]) < 3 and not v.get("wij_genoemd"):
                regel["voorbeelden"].append({
                    "url": v["bron_url"],
                    "titel": v.get("bron_titel") or v.get("bron_domein"),
                    "domein": v.get("bron_domein"),
                })

    ranglijst = sorted(per_concurrent.values(), key=lambda c: -c["paginas"])

    # De pagina's waar wel een concurrent staat en wij niet. Dat is de hele
    # boodschap: dit zijn de adressen waar het verschil zit.
    gemiste = [
        {
            "url": v["bron_url"],
            "titel": v.get("bron_titel") or v.get("bron_domein"),
            "domein": v.get("bron_domein"),
            "vraag": v.get("vraag"),
            "concurrenten": v.get("concurrenten") or [],
        }
        for v in extern
        if v.get("concurrenten") and not v.get("wij_genoemd")
    ]
    gemiste.sort(key=lambda g: -len(g["concurrenten"]))

    naam = winkelnaam or "je winkel"
    if not gemiste:
        conclusie = (
            f"Op de externe pagina's die we bij deze vragen vonden, staat {naam} er net zo "
            f"vaak bij als de winkels die AI noemt. Hier ligt je knelpunt dus niet."
        )
    elif not wij_erop:
        conclusie = (
            f"We vonden {len(extern)} externe pagina's over deze onderwerpen. Op {len(gemiste)} "
            f"daarvan staat wel een winkel die AI noemt, en {naam} op geen enkele. Dat is het "
            f"verschil waar je iets aan kan doen: dit zijn bestaande pagina's, geen pagina's die "
            f"je zelf moet maken."
        )
    else:
        conclusie = (
            f"We vonden {len(extern)} externe pagina's over deze onderwerpen. {naam} staat op "
            f"{len(wij_erop)} daarvan. Op {len(gemiste)} pagina's staat wel een concurrent en "
            f"{naam} niet."
        )

    return {
        "paginas": len(extern),
        "wij_erop": len(wij_erop),
        "gemist": len(gemiste),
        "concurrenten": ranglijst[:8],
        "gemiste_paginas": gemiste[:12],
        "vragen": sorted({v.get("vraag") for v in extern if v.get("vraag")}),
        "conclusie": conclusie,
    }
