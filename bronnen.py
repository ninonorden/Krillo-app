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
import unicodedata
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

# Hoeveel concurrenten we op de gevonden pagina's opzoeken. Ruimer dan wat de
# klant uiteindelijk te zien krijgt, en dat is met opzet: hoe meer bekende
# winkels we kunnen herkennen, hoe beter we kunnen zien of een pagina een
# vergelijkingslijstje is of een toevallige vermelding.
MAX_CONCURRENTEN = int(os.environ.get("BRONNEN_MAX_CONCURRENTEN", "8"))

# Hoeveel bekende winkels er minstens op een pagina moeten staan voordat we hem
# meetellen.
#
# Dit is de belangrijkste kwaliteitsrem. Zonder deze regel komt er van alles
# binnen: een blog over designverlichting waar toevallig IKEA in staat, of een
# pagina over gratis retourneren waar HEMA op staat. Dat zijn echte pagina's,
# maar het zijn geen plekken waar winkels in deze categorie vergeleken worden,
# en een klant die daarop afgaat verspilt zijn tijd.
#
# Staan er twee of meer bekende winkels op, dan gaat de pagina ergens over
# kiezen tussen winkels. Dat is precies het soort pagina waar het om gaat.
# Staan wij er zelf op, dan telt de pagina altijd mee, want dan is het nieuws
# dat we er al staan.
MIN_WINKELS_OP_PAGINA = int(os.environ.get("BRONNEN_MIN_WINKELS", "2"))

# Hoeveel pagina's van hetzelfde webadres we per vraag meenemen.
#
# Eén website kan met drie eigen pagina's in de zoekresultaten staan. Tellen we
# die alle drie, dan lijkt het alsof een concurrent op drie plekken genoemd
# wordt terwijl het één site is, en dan klopt de ranglijst niet meer.
MAX_PER_DOMEIN = int(os.environ.get("BRONNEN_MAX_PER_DOMEIN", "1"))

# Welke soorten koopvragen de beste zoektermen opleveren, beste eerst.
#
# Dit is uit de eerste echte proef gekomen. Een vraag als "welke webshop voor
# keukenspullen levert het snelst" is een prima vraag aan een AI, maar een
# slechte zoekterm: je krijgt pagina's over levertijden terug, niet pagina's
# waar webshops in die categorie vergeleken worden. Een vraag naar een winkel
# of naar de beste in een categorie levert dat wel op.
INTENTIE_VOLGORDE = ["winkel", "algemeen", "prijs", "doelgroep", "alternatief", "praktisch"]

# Soorten vragen die we liever helemaal overslaan als er genoeg andere zijn.
#
# "Welke winkel heeft een goed retourbeleid" levert pagina's over retourneren
# op, met daarop de grote ketens die overal gratis retour aanbieden. Dat is
# geen plek waar winkels in een categorie vergeleken worden, en er valt voor
# een kleine winkel niets te halen. Zo'n vraag kost wel een zoekopdracht en
# acht paginabezoeken, dus die slaan we over zolang er betere zijn.
ZWAKKE_INTENTIES = {"praktisch"}

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

# Land en taal van de zoekresultaten. LET OP: Brave wil de landcode in
# HOOFDLETTERS (NL) en de taalcode in kleine letters (nl). Dat door elkaar
# halen levert een afgekeurd verzoek op, en dat ziet er hetzelfde uit als een
# zoekopdracht die niets vindt. Google Custom Search wil juist allebei klein.
# Waar we standaard zoeken. Per winkel kan dit anders zijn: een winkel in
# Texas moet in Amerikaanse zoekresultaten gezocht worden, niet in Nederlandse.
# De aanroeper geeft land en taal mee; deze twee zijn alleen de terugval.
ZOEK_LAND = os.environ.get("BRONNEN_LAND", "NL").strip()
ZOEK_TAAL = os.environ.get("BRONNEN_TAAL", "nl").strip().lower()

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


def _zoek_brave(vraag, land=None, taal=None):
    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        headers={
            "X-Subscription-Token": os.environ["BRAVE_API_KEY"],
            "Accept": "application/json",
        },
        params={
            "q": vraag,
            # Brave staat hoogstens 20 resultaten per pagina toe. Meer vragen
            # levert een afgekeurd verzoek op, en dat is niet te onderscheiden
            # van een zoekopdracht zonder resultaten.
            "count": min(MAX_RESULTATEN, 20),
            # LET OP: land in HOOFDLETTERS en taal in kleine letters. Andersom
            # geeft Brave stilletjes niets terug, en dat is niet te
            # onderscheiden van een zoekopdracht zonder resultaten. Die fout
            # hebben we in augustus al een keer gemaakt.
            "country": (land or ZOEK_LAND).upper(),
            "search_lang": (taal or ZOEK_TAAL).lower(),
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


def _zoek_google(vraag, land=None, taal=None):
    resp = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": os.environ["GOOGLE_ZOEK_API_KEY"],
            "cx": os.environ["GOOGLE_ZOEK_CX"],
            "q": vraag,
            # Google staat hoogstens 10 resultaten per verzoek toe, en wil land
            # en taal juist allebei in kleine letters.
            "num": min(MAX_RESULTATEN, 10),
            "gl": (land or ZOEK_LAND).lower(),
            "hl": (taal or ZOEK_TAAL).lower(),
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


def zoek(vraag, webshop_url=None, land=None, taal=None):
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
        resultaten = zoeker(vraag, land=land, taal=taal)
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
    echte teken, accenten eraf, en alle witruimte tot een spatie.

    De accenten moeten eraf omdat de naamherkenning op letters en cijfers
    splitst. Zonder dat werd "Bébé-Jou" opgeknipt tot b, b en jou, en werd die
    winkel op geen enkele pagina meer gevonden."""
    laag = (tekst or "").lower()
    laag = laag.replace("&amp;", "&").replace("&#38;", "&").replace("&nbsp;", " ")
    laag = unicodedata.normalize("NFKD", laag)
    laag = "".join(t for t in laag if not unicodedata.combining(t))
    return " ".join(laag.split())


def test_zoekmachine(vraag=None, webshop_url=None, land=None, taal=None):
    """Eén losse zoekopdracht, met de echte foutmelding erbij.

    Voor de beheerpagina. Levert de bronanalyse niets op, dan wil je als eerste
    weten of de zoekmachine überhaupt antwoordt. Dat kost een halve cent en
    scheelt een middag zoeken in logboeken.

    Bewust apart van zoek(): die geeft bij een storing gewoon een lege lijst
    terug omdat een meetronde niet mag klappen op een zoekmachine. Hier wil je
    juist wél zien wat er misging."""
    vraag = vraag or "beste webshop voor cadeaus"
    if not beschikbaar():
        return {"gelukt": False, "vraag": vraag, "resultaten": [], "fout": waarom_niet()}

    zoeker = _ZOEKERS.get(ZOEK_AANBIEDER)
    gestart = time.monotonic()
    try:
        _wacht_je_beurt()
        resultaten = zoeker(vraag, land=land, taal=taal)
        gelukt, fout = True, None
    except Exception as e:
        resultaten, gelukt = [], False
        body = getattr(getattr(e, "response", None), "text", "") or ""
        fout = (f"{type(e).__name__}: {e}"[:200]
                + (" | " + " ".join(body.split())[:300] if body else ""))[:500]

    kosten.registreer_vaste_kosten(
        soort="bronnen-zoeken-test",
        provider=ZOEK_AANBIEDER,
        bedrag=PRIJS_PER_ZOEKOPDRACHT_EURO if gelukt else 0.0,
        webshop_url=webshop_url,
        duur_ms=int((time.monotonic() - gestart) * 1000),
        gelukt=gelukt,
        foutsoort=fout,
    )

    if gelukt and not resultaten:
        fout = ("De zoekmachine antwoordde wel, maar gaf nul resultaten terug. "
                "Dat wijst meestal op een abonnement dat nog niet actief is, of op "
                "instellingen die te streng staan.")
    return {"gelukt": gelukt, "vraag": vraag, "resultaten": resultaten, "fout": fout}


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

    # Mag het lidwoord weggelaten worden?
    #
    # "de Bijenkorf" staat op de meeste pagina's gewoon als "Bijenkorf", dus
    # daar moet het weg mogen. Maar "De Tuinen" wordt dan het patroon "tuinen",
    # en dan telt elke pagina met dat doodgewone woord als vermelding.
    #
    # Het onderscheid: blijft er meer dan een woord over, dan is het veilig.
    # Blijft er een woord over, dan alleen als dat woord lang genoeg is om
    # geen alledaags Nederlands woord te zijn. Dat is een vuistregel en geen
    # wet, maar hij valt de goede kant op: bij twijfel eisen we het lidwoord,
    # en missen we hoogstens een vermelding in plaats van er een te verzinnen.
    echte_delen = [d for d in delen if d not in _LIDWOORDEN]
    lidwoord_optioneel = (len(echte_delen) > 1
                          or (len(echte_delen) == 1 and len(echte_delen[0]) >= 8))

    stukken = []
    for i, deel in enumerate(delen):
        vast = re.escape(deel)
        if i == 0 and deel in _LIDWOORDEN and len(delen) > 1 and lidwoord_optioneel:
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
        if kern and len(kern) >= 4:
            # MET woordgrenzen. Dit stond als een kale substring-test op de
            # hele pagina met alle leestekens eruit, en dan zit "hema" in
            # "thema" en "bever" in "web everything". We zoeken het domein
            # zoals het in een link staat: de naam gevolgd door een punt en
            # een landcode, of los tussen leestekens.
            patroon = (r"(?<![a-z0-9])" + re.escape(kern)
                       + r"(?:[\-_.][a-z0-9]+)*\.[a-z]{2,6}(?![a-z0-9])")
            if re.search(patroon, laag):
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

    # Eerst op soort vraag, dan pas op drukte. Zonder die eerste sortering
    # winnen de vragen over levertijd en retourbeleid, want daar noemt AI de
    # meeste winkels in. Als zoekterm zijn dat juist de slechtste: die leveren
    # pagina's over levertijden op in plaats van pagina's waar winkels in deze
    # categorie vergeleken worden.
    def rangschik(regel):
        intentie = regel.get("intentie") or "algemeen"
        try:
            plek = INTENTIE_VOLGORDE.index(intentie)
        except ValueError:
            plek = len(INTENTIE_VOLGORDE)
        return (plek, -(regel.get("aantal_winkels") or 0))

    gemist.sort(key=rangschik)

    # De zwakke soorten vragen alleen gebruiken als we anders te weinig
    # overhouden. Zijn er genoeg goede, dan besparen ze een zoekopdracht en een
    # hoop paginabezoeken die toch niets opleveren.
    sterk = [r for r in gemist if (r.get("intentie") or "algemeen") not in ZWAKKE_INTENTIES]
    if len(sterk) >= grens:
        gemist = sterk

    return [r["vraag"] for r in gemist[:grens] if r.get("vraag")]


def kies_concurrenten(klantbeeld, grens=None):
    """De concurrenten die we op de gevonden pagina's opzoeken.

    Onze eigen winkel gaat er expres uit: die staat apart in de uitkomst, want
    de hele vraag is waar zij wel staan en wij niet."""
    grens = grens or MAX_CONCURRENTEN
    lijst = [c for c in ((klantbeeld or {}).get("concurrenten") or []) if not c.get("wij")]
    lijst.sort(key=lambda c: (c.get("aanbevolen") or 0, c.get("genoemd") or 0), reverse=True)
    return [c["naam"] for c in lijst[:grens] if c.get("naam")]


def analyseer(webshop_url, klantbeeld, winkelnaam=None, meting_id=None, melden=None,
              land=None, taal=None):
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
        resultaten = zoek(vraag, webshop_url=webshop_url, land=land, taal=taal)
        if not resultaten:
            continue

        bekeken = 0
        per_domein = {}
        for r in resultaten:
            if bekeken >= MAX_PAGINAS:
                break

            url = r["url"]
            domein_kern = _kern_van_domein(url)

            # De eigen site van de klant is geen externe bron. Dat jij op je
            # eigen website staat wisten we al.
            if ons_domein and domein_kern == ons_domein:
                continue

            # Hoogstens een paar pagina's van dezelfde website. Anders vult één
            # site de hele uitkomst en lijkt een concurrent op vier plekken te
            # staan terwijl het vier pagina's van één website zijn.
            if per_domein.get(domein_kern, 0) >= MAX_PER_DOMEIN:
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

            # De kwaliteitsdrempel. Een pagina telt mee als wij erop staan, of
            # als er genoeg bekende winkels op staan om te zeggen dat hij over
            # het kiezen tussen winkels gaat.
            #
            # Zonder deze regel komen er pagina's binnen waar toevallig één
            # grote keten op voorkomt, zoals een blog over verlichting waar
            # IKEA in staat. Dat is een echte pagina, maar het is geen plek
            # waar winkels in deze categorie vergeleken worden, en een klant
            # die daar achteraan gaat is zijn tijd kwijt. Liever vijf pagina's
            # die ergens over gaan dan dertig die dat niet doen.
            #
            # De eigen site van een concurrent is hiervan uitgezonderd. Die
            # telt toch nooit mee in de cijfers, maar hij blijft wel zichtbaar
            # op de beheerpagina, zodat je kan zien dat hij overgeslagen is en
            # niet dat hij gemist is.
            if not gevonden and not wij:
                continue
            if not eigen_site_van and not wij and len(gevonden) < MIN_WINKELS_OP_PAGINA:
                continue

            per_domein[domein_kern] = per_domein.get(domein_kern, 0) + 1
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
                # Hoeveel bekende winkels er op deze pagina staan. Hoe hoger,
                # hoe zwaarder de pagina weegt: een lijstje met zes winkels
                # waar jij niet bij staat is een groter gemis dan een pagina
                # waar er twee op staan.
                "winkels_op_pagina": len(gevonden) + (1 if wij else 0),
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

    # Tellen per WEBSITE en niet per pagina. Drie pagina's van dezelfde site
    # zijn één plek waar je genoemd wordt, geen drie. Zonder dat onderscheid
    # kan één website in zijn eentje een concurrent bovenaan de lijst zetten.
    per_concurrent = {}
    for v in extern:
        for naam in (v.get("concurrenten") or []):
            regel = per_concurrent.setdefault(naam, {"naam": naam, "domeinen": set(), "voorbeelden": []})
            regel["domeinen"].add(v.get("bron_domein"))
            if len(regel["voorbeelden"]) < 3 and not v.get("wij_genoemd"):
                regel["voorbeelden"].append({
                    "url": v["bron_url"],
                    "titel": v.get("bron_titel") or v.get("bron_domein"),
                    "domein": v.get("bron_domein"),
                })

    ranglijst = sorted(
        ({"naam": c["naam"], "paginas": len(c["domeinen"]), "voorbeelden": c["voorbeelden"]}
         for c in per_concurrent.values()),
        key=lambda c: -c["paginas"],
    )

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
    # De pagina met de meeste winkels erop bovenaan. Daar is jouw afwezigheid
    # het meest opvallend, en daar is de kans het grootst dat het een lijstje is
    # waar je op zou horen te staan.
    gemiste.sort(key=lambda g: -len(g["concurrenten"]))
    dubbel = set()
    ontdubbeld = []
    for g in gemiste:
        # Eén regel per website. Dat een site drie pagina's over hetzelfde
        # onderwerp heeft is geen drie kansen, het is één plek waar je niet
        # staat.
        if g["domein"] in dubbel:
            continue
        dubbel.add(g["domein"])
        ontdubbeld.append(g)
    gemiste = ontdubbeld

    sites = {v.get("bron_domein") for v in extern if v.get("bron_domein")}

    def telwoord(aantal, enkel, meer):
        """Nette Nederlandse zin bij 1 en bij meer. "1 pagina's op 1
        verschillende websites" leest als machinetaal, en dat is precies het
        soort detail waar een klant aan ziet dat er niemand naar gekeken
        heeft."""
        return f"{aantal} {enkel}" if aantal == 1 else f"{aantal} {meer}"

    aantal_paginas = telwoord(len(extern), "pagina", "pagina's")
    aantal_sites = telwoord(len(sites), "website", "verschillende websites")
    bekeken = f"We bekeken {aantal_paginas} op {aantal_sites}"

    naam = winkelnaam or "je winkel"
    if not gemiste:
        conclusie = (
            f"Op de plekken die we bij deze vragen vonden, staat {naam} er net zo vaak bij als "
            f"de winkels die AI noemt. Hier ligt je knelpunt dus niet."
        )
    elif not wij_erop:
        daarvan = ("Op die ene staat" if len(gemiste) == 1
                   else f"Op {len(gemiste)} daarvan staat")
        conclusie = (
            f"{bekeken} waar "
            f"winkels in jouw categorie naast elkaar gezet worden. {daarvan} wel een winkel die "
            f"AI noemt, en {naam} op geen enkele. Dat is het verschil waar je zelf iets aan kan "
            f"doen: deze pagina's bestaan al, je hoeft ze niet te maken."
        )
    else:
        plekken = ("op nog 1 andere plek staat" if len(gemiste) == 1
                   else f"op nog {len(gemiste)} andere plekken staat")
        conclusie = (
            f"{bekeken}. {naam} "
            f"staat op {len(wij_erop)} daarvan, en {plekken} wel een concurrent en {naam} niet."
        )

    return {
        "paginas": len(extern),
        "sites": len(sites),
        "wij_erop": len(wij_erop),
        "gemist": len(gemiste),
        "concurrenten": ranglijst[:8],
        "gemiste_paginas": gemiste[:12],
        "vragen": sorted({v.get("vraag") for v in extern if v.get("vraag")}),
        "conclusie": conclusie,
    }
