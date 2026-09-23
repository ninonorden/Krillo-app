"""Meten per categorie: een vraag, alle winkels tegelijk gescoord.

DIT IS HET HART VAN DE NIEUWE KRILLO.

Tot nu toe kreeg elke winkel zijn eigen dertig koopvragen, elke week opnieuw
gesteld aan twee modellen. Dat kost ongeveer tien euro per klant per maand,
waardoor de kosten even hard groeien als de omzet en het bedrijf vastloopt rond
de tienduizend euro.

Hier gebeurt het anders. De vraag "waar koop ik online emaille servies" wordt
EEN keer gesteld. Daarna kijken we welke van de veertig servieswinkels in dat
antwoord voorkomen. Een meting, veertig uitkomsten.

Op de lijst van 13 september: 924 winkels in 34 categorieen. Los meten is
2280 euro per ronde, per categorie meten 77,50 euro. Zesentwintig keer
goedkoper, en dat verschil groeit: de kosten hangen aan het aantal categorieen
en niet aan het aantal winkels. Bij tienduizend winkels in dezelfde categorieen
kost het nog steeds 77,50 euro.

WAT ER UIT DE METING KOMT DAT ER EERST NIET WAS: een POSITIE. Niet "genoemd bij
2 van de 30 vragen" maar "41e van de 62, en deze drie stonden boven je". Een
positie is scherper, hij verandert elke week, en hij geeft een reden om terug te
komen.

DRIE KEUZES MET REDEN:

1. De winkellijst uit een antwoord wordt EEN keer gelezen, niet een keer per
   winkel. Dat is waar de besparing echt vandaan komt: het dure werk (een model
   het antwoord laten lezen) is winkelonafhankelijk. Het koppelen aan onze
   winkels is daarna gewoon vergelijken in de database en kost niets.

2. Elk antwoord wordt volledig bewaard. Dat is de dataset die de historie
   opbouwt, en die kan niemand met terugwerkende kracht namaken. Over twee jaar
   is dat de belangrijkste bezitting van dit bedrijf.

3. Een vraag waarin geen enkele winkel genoemd kon worden telt niet mee. Vraagt
   iemand naar een merk of naar algemene informatie, dan komt daar geen webshop
   in voor, ook de beste niet. Zulke vragen meetellen maakt elk cijfer mooier of
   lelijker dan het is.
"""
import json
import os
import socket
import re
import threading
import time

import anthropic

import beoordeling
import categorieen
import db
import kosten
import metingen
import scan_engine

MODEL = os.environ.get("CATEGORIE_LEESMODEL", "claude-sonnet-4-6")

# Hoeveel koopvragen er per categorie bedacht worden. Dertig, net als bij de
# oude meting per winkel, zodat de cijfers vergelijkbaar blijven met wat er al
# gemeten is en de belofte op de site niet hoeft te veranderen.
VRAGEN_PER_CATEGORIE = int(os.environ.get("VRAGEN_PER_CATEGORIE", "30"))


# ---------------------------------------------------------------------------
# De koopvragen van een categorie
# ---------------------------------------------------------------------------

def _client():
    sleutel = os.environ.get("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=sleutel) if sleutel else None


def bedenk_vragen(slug, landnaam="Nederlandse", taal="Nederlands",
                  aantal=VRAGEN_PER_CATEGORIE, vermijd=None):
    """Bedenkt de koopvragen voor een hele categorie.

    Belangrijk verschil met koopvragen.py: die kijkt naar de pagina's van EEN
    winkel en bedenkt vragen die bij dat assortiment passen. Hier gaat het om de
    categorie zelf, want dezelfde vraag moet voor alle winkels erin gelden.

    De naam van geen enkele winkel komt in de vragen voor. Anders meet je of AI
    een naam kan herhalen in plaats van of een winkel uit zichzelf genoemd
    wordt."""
    client = _client()
    if client is None:
        return []
    naam = categorieen.naam_van(slug)
    # Welke vragen er al zijn, zodat het model niet opnieuw dezelfde bedenkt.
    # Zonder dit liep het aanvullen dood: een dubbele vraag valt weg op de
    # unieke sleutel, en dan blijft de categorie onder de dertig hangen.
    # Hoogstens veertig meesturen; meer maakt de opdracht onleesbaar.
    vermijd = [v for v in (vermijd or []) if v][:40]
    vermijd_blok = ""
    if vermijd:
        lijst = "\n".join(f"- {v}" for v in vermijd)
        vermijd_blok = (f"\n\nDEZE VRAGEN BESTAAN AL. Bedenk er andere, over andere "
                        f"stukken van de categorie. Een variant met andere woorden op "
                        f"dezelfde vraag telt als dezelfde vraag:\n{lijst}")
    verdeling = _verdeling(aantal, landnaam)
    intentie_uitleg = "\n".join(f"- {n} ({hoeveel} vragen): {u}"
                                for n, u, hoeveel in verdeling)

    prompt = f"""Je helpt bij het meten welke webshops door AI-assistenten aanbevolen worden.

De categorie is: {naam}
Het land is: {landnaam}

Bedenk {aantal} vragen die een koper in {taal} echt aan ChatGPT of Gemini zou
stellen als hij iets uit deze categorie wil kopen. Houd je aan deze verdeling:
{intentie_uitleg}

REGELS:
- Geen enkele winkelnaam of merknaam in de vragen. Anders meten we of AI een
  naam kan herhalen in plaats van of een winkel uit zichzelf genoemd wordt.
- DE BELANGRIJKSTE REGEL. In ELKE vraag moet om een WINKEL of een PLEK OM TE
  KOPEN gevraagd worden, ook bij de soorten die over prijs of doelgroep gaan.
  Een vraag die om een product, een merk of uitleg vraagt levert geen enkele
  webshop op. Zo'n antwoord telt niet mee in de meting en is dus betaald voor
  niets. Bij een echte meting telde maar 13 van de 30 vragen mee, en dat kwam
  hierdoor.
  Fout: "wat is de beste houten trein voor een peuter"
  Goed: "waar koop ik online een houten trein voor een peuter"
  Fout: "welk merk speelgoed gaat het langst mee"
  Goed: "welke webshop verkoopt speelgoed dat lang meegaat"
  Fout: "hoeveel kost een goede loopfiets"
  Goed: "welke {landnaam} webshop heeft goedkope loopfietsen"
- Controleer elke vraag voor je hem opschrijft: zou een assistent hierop met een
  of meer WINKELNAMEN antwoorden. Is dat nee, schrijf de vraag dan om.
- Schrijf ze zoals iemand ze intypt: gewone taal, geen zoekmachinetermen.
- Varieer in wat er gezocht wordt binnen de categorie, zodat de meting niet op
  een smal stukje van de markt hangt.{vermijd_blok}

Antwoord ALLEEN met JSON:
{{"vragen": [{{"vraag": "...", "intentie": "algemeen"}}]}}"""

    try:
        gestart = time.monotonic()
        antwoord = client.messages.create(
            model=MODEL, max_tokens=4096,
            messages=[{"role": "user", "content": prompt}])
        kosten.registreer_aanroep(
            provider="anthropic", model=MODEL,
            invoer_tokens=antwoord.usage.input_tokens,
            uitvoer_tokens=antwoord.usage.output_tokens,
            soort="categorievragen-bedenken",
            duur_ms=int((time.monotonic() - gestart) * 1000))
        data = beoordeling._schoon_json(antwoord.content[0].text) or {}
    except Exception as e:
        print(f"Vragen bedenken mislukt voor {slug}: {e}")
        return []

    geldig = {n for n, _ in koopintenties()}
    uit = []
    gezien = set()
    for v in data.get("vragen", []):
        tekst = (v.get("vraag") or "").strip()
        if not tekst or tekst.lower() in gezien:
            continue
        gezien.add(tekst.lower())
        intentie = v.get("intentie") if v.get("intentie") in geldig else "algemeen"
        uit.append({"vraag": tekst, "intentie": intentie})
    return uit[:aantal]


def koopintenties(landnaam="Nederlandse"):
    """Dezelfde zes soorten koopvragen als bij de meting per winkel, zodat de
    cijfers vergelijkbaar blijven met alles wat er al gemeten is.

    Blijft staan voor code die de oude lijst gebruikt. Het BEDENKEN van
    categorievragen gaat sinds 17 september via KOOPINTENTIES hieronder."""
    import koopvragen
    return koopvragen.intenties(landnaam)


# ---------------------------------------------------------------------------
# De zes soorten koopvragen, herschreven op 17 september
# ---------------------------------------------------------------------------
#
# WAT DE METING VAN SPEELGOED LIET ZIEN. Per soort vraag, hoeveel van de
# antwoorden er een webshop opleverden en dus meetelden:
#
#   winkel      10 van de 10   100%
#   praktisch    8 van de  8   100%
#   prijs        4 van de 10    40%
#   alternatief  1 van de 10    10%
#   algemeen     0 van de 10     0%
#   doelgroep    0 van de 12     0%
#
# Dat is geen toeval en het ligt niet aan de categorie. Winkel en praktisch zijn
# precies de twee omschrijvingen waarin letterlijk om een webshop gevraagd wordt.
# De andere vier vroegen om een PRODUCT ("iemand zoekt het beste product",
# "iemand zoekt iets voor beginners"), en op een productvraag antwoordt een
# assistent met productnamen en merken. Daar komt geen winkel in voor, ook niet
# als je de beste webshop van Nederland bent.
#
# Dus: alle zes omschrijvingen vragen nu om een WINKEL. Het onderwerp van de
# vraag verschilt nog steeds (prijs, doelgroep, levertijd), maar wat er gevraagd
# wordt is altijd een plek om te kopen.
#
# En de verdeling is niet meer gelijk. Winkel en praktisch bewezen zich, dus die
# krijgen er meer. De andere vier krijgen een eerlijke tweede kans met hun nieuwe
# omschrijving; blijkt die niet te werken, dan haalt het snoeien ze er vanzelf
# uit en zien we dat terug in dezelfde tabel.

def KOOPINTENTIES(landnaam="Nederlandse"):
    """De zes soorten, met hun gewicht. Elke omschrijving vraagt om een winkel."""
    return [
        ("winkel", 8,
         f"Iemand zoekt een betrouwbare {landnaam} webshop om iets uit deze "
         f"categorie te kopen, zonder verdere eisen."),
        ("praktisch", 6,
         f"Iemand zoekt een {landnaam} webshop die levertijd, retourneren, "
         f"voorraad of garantie goed geregeld heeft. Dus niet 'hoe lang duurt "
         f"levering', wel 'welke {landnaam} webshop levert het snelst'."),
        ("prijs", 5,
         f"Iemand zoekt een {landnaam} webshop die goedkoop is, of waar je het "
         f"meeste voor je geld krijgt. Vraag naar de WINKEL, niet naar wat iets "
         f"kost."),
        ("doelgroep", 4,
         f"Iemand zoekt een {landnaam} webshop die gespecialiseerd is in een "
         f"bepaalde situatie of persoon: beginners, kinderen, professioneel "
         f"gebruik. Vraag naar de WINKEL die daarin gespecialiseerd is, niet "
         f"naar het product."),
        ("algemeen", 4,
         f"Iemand weet nog niets en vraagt bij welke {landnaam} webshop hij dit "
         f"online het beste kan kopen. Vraag WAAR hij moet kopen, niet WAT hij "
         f"moet kopen."),
        ("alternatief", 3,
         f"Iemand kent alleen de grote bekende webshops en zoekt een andere "
         f"{landnaam} webshop, of juist een gespecialiseerde in plaats van een "
         f"warenhuis."),
    ]


def _verdeling(aantal, landnaam="Nederlandse"):
    """Hoeveel vragen er per soort bedacht worden, opgeteld precies `aantal`.

    De gewichten staan op dertig vragen. Wordt er om minder gevraagd, dan gaat
    alles naar verhouding omlaag en krijgt elke soort er minstens een, zodat de
    meting nooit op een enkel soort vraag komt te hangen."""
    soorten = KOOPINTENTIES(landnaam)
    # Vraag je om minder vragen dan er soorten zijn, dan kan niet elke soort aan
    # bod komen. Dan vallen de zwakste af en niet de sterkste: de lijst staat op
    # volgorde van wat zich bewezen heeft.
    soorten = soorten[:max(1, aantal)]
    totaal_gewicht = sum(g for _, g, _ in soorten)
    uit, gebruikt = [], 0
    for plek, (naam, gewicht, uitleg) in enumerate(soorten):
        if plek == len(soorten) - 1:
            hoeveel = max(1, aantal - gebruikt)
        else:
            hoeveel = max(1, round(aantal * gewicht / totaal_gewicht))
            hoeveel = min(hoeveel, max(1, aantal - gebruikt - (len(soorten) - plek - 1)))
        gebruikt += hoeveel
        uit.append((naam, uitleg, hoeveel))
    return uit


# ---------------------------------------------------------------------------
# Een antwoord lezen: welke winkels staan erin
# ---------------------------------------------------------------------------
#
# HIER ZIT DE HELE MEETPRIJS IN. Een categorie meten is dertig vragen aan twee
# modellen, dus zestig antwoorden, en elk antwoord moet gelezen worden. Het
# stellen van de vraag kunnen we niet goedkoper maken, want we meten juist wat
# ChatGPT en Gemini antwoorden. Het lezen wel: dat is een leesopdracht met een
# vast format eruit, en daar is geen duur model voor nodig.
#
# Op 14 september kostte een winkel ongeveer 35 cent per maand. Het leeswerk is
# daarvan het grootste deel. Met een goedkoper leesmodel gaat dat naar een paar
# cent.
#
# MAAR: dat mag de uitkomst niet veranderen. Een goedkoper model dat een winkel
# over het hoofd ziet, kost een klant zijn positie. Daarom staat het leesmodel
# in een omgevingsvariabele en zit er een vergelijking in (vergelijk_lezers)
# die het goedkope en het dure model over dezelfde bewaarde antwoorden laat
# lopen en vertelt hoe vaak ze het eens zijn. Pas overstappen als dat klopt.

_PROMPT_SJABLOON = """Je leest het antwoord dat een AI-assistent gaf op een koopvraag.
Haal eruit welke WEBSHOPS erin genoemd worden.

De vraag was:
{vraag}

Het antwoord was:
{antwoord}

WINKELS TEGENOVER MERKEN. Zet een naam alleen bij winkels als je er als
consument rechtstreeks iets kan kopen, dus een webshop of een winkelketen. Zet
hem niet in de lijst als het een merk of label is dat via andere winkels
verkocht wordt. Voorbeelden: fonQ, Loods 5, de Bijenkorf en Flinders zijn
winkels. Serax, HKliving en Ferm Living zijn merken. Een merk met een eigen
webshop telt als winkel.

KON ER UBERHAUPT EEN WINKEL GENOEMD WORDEN. Vraagt de vraag om een winkel of om
een plek om te kopen, dan is dat ja. Vraagt hij alleen naar merken, producten of
algemene informatie, dan is dat nee, ook als er toevallig toch een winkel
langskomt. Zo'n vraag telt niet mee in de meting.

AANBEVOLEN OF ALLEEN GENOEMD. Veel antwoorden geven eerst een lijst en sluiten
af met een advies ("ik zou vooral kijken naar X en Y"). Alleen wie in dat
slotadvies staat, of wie duidelijk als eerste keuze wordt aangeraden, is
aanbevolen. In een rij staan is genoemd, niet aanbevolen.

PLATFORM OF WINKEL. Dit is het verschil tussen een concurrent en een plek waar
je op moet staan, en het is niet hetzelfde. Een WINKEL verkoopt zelf: hij heeft
eigen voorraad of levert zelf, zoals fonQ, Loods 5 of de Bijenkorf. Een
PLATFORM brengt vraag en aanbod bij elkaar en verkoopt zelf niets: een
marktplaats, een portaal, een vergelijkingssite of een boekingssite. Pararius
en Funda zijn platforms voor makelaars, Marktplaats en bol.com voor verkopers,
Kieskeurig en Beslist zijn vergelijkingssites, Booking is een boekingssite.
Twijfel je, kijk dan naar wie de verkoper is in de bestelling: is dat een
derde, dan is het een platform.

POSITIE is de volgorde waarin de winkels in het antwoord voorkomen, te beginnen
bij 1.

WEBADRES. Zet bij elke winkel het domein van zijn webshop, zonder https en
zonder www, zoals "fonq.nl". Alleen als het in het antwoord staat of als je het
zeker weet. Twijfel je, zet dan null. Nooit gokken: een verzonnen adres is erger
dan geen adres.

Antwoord ALLEEN met geldige JSON, niets ervoor of erna:

{{
  "winkel_kon_genoemd": true,
  "winkels": [{{"naam": "fonQ", "adres": "fonq.nl", "positie": 1, "soort": "winkel"}},
              {{"naam": "bol.com", "adres": "bol.com", "positie": 2, "soort": "platform"}}],
  "aanbevolen": ["fonQ"]
}}"""


# BEWUST STAAT HIER HET DURE MODEL ALS STANDAARD. Het goedkope model gaat pas
# aan als de vergelijking op echte antwoorden groen licht geeft, en dat zetten
# wij dan in Render om. Andersom zou betekenen dat een nieuwe versie stilletjes
# de meetkwaliteit verandert van iedereen die al in de ranglijst staat, zonder
# dat iemand het gezien heeft.
#
# Overzetten doe je zo: LEES_PROVIDER op openai en LEES_MODEL op gpt-5.6-luna.
# Dat model is ongeveer vijftien keer goedkoper dan het huidige.
LEES_PROVIDER = os.environ.get("LEES_PROVIDER", "anthropic")
LEES_MODEL = os.environ.get("LEES_MODEL", MODEL)

# Het model waar wij naartoe WILLEN. Dit is wat de vergelijking test, en wat je
# in Render invult zodra die vergelijking groen licht geeft. Het staat hier
# apart van LEES_MODEL, want anders zou de vergelijking het huidige model met
# zichzelf vergelijken en altijd honderd procent zeggen.
KANDIDAAT_PROVIDER = os.environ.get("LEES_KANDIDAAT_PROVIDER", "openai")
KANDIDAAT_MODEL = os.environ.get("LEES_KANDIDAAT_MODEL", "gpt-5.6-luna")

# De modellen die het leeswerk zouden kunnen overnemen, van goedkoop naar duur.
# De prijzen staan in kosten.py; deze lijst is er zodat je ze kunt uitproberen
# zonder nieuwe versie. Wat er uitkomt bepaalt of de hele index vijftien euro
# kost of achtenzeventig.
def kandidaat_uit_naam(naam):
    """Maakt van een modelnaam een aanbieder, zodat je hem zelf kunt intypen.

    Waarom dit moet kunnen: op 16 september mislukten alle tien de leespogingen
    met gemini-2.5-flash-lite. Die naam had ik uit mijn hoofd opgeschreven en
    hij bestaat niet onder deze sleutel. Modelnamen veranderen per aanbieder en
    per account, dus een vaste lijst in de code loopt altijd achter.

    Op /admin/modellen staan de namen die deze sleutels echt mogen gebruiken.
    Daar kopieer je er een vandaan en die typ je hier in."""
    naam = (naam or "").strip()
    if not naam:
        return None
    if ":" in naam:
        provider, model = naam.split(":", 1)
        return {"provider": provider.strip().lower(), "model": model.strip()}
    kort = naam.lower()
    if kort.startswith("gpt") or kort.startswith("o1") or kort.startswith("o3"):
        provider = "openai"
    elif kort.startswith("gemini"):
        provider = "google"
    elif kort.startswith("claude"):
        provider = "anthropic"
    else:
        return None
    return {"provider": provider, "model": naam}


KANDIDATEN = [
    {"provider": "google", "model": "gemini-2.5-flash-lite", "toonnaam": "Gemini flash-lite (goedkoopst)"},
    {"provider": "openai", "model": "gpt-5.6-luna", "toonnaam": "GPT luna"},
    {"provider": "google", "model": "gemini-3.5-flash-lite", "toonnaam": "Gemini 3.5 flash-lite"},
    {"provider": "openai", "model": "gpt-5.4-mini", "toonnaam": "GPT mini"},
    {"provider": "google", "model": "gemini-3.7-flash", "toonnaam": "Gemini flash"},
]

SLEUTELS = {"openai": "OPENAI_API_KEY", "google": "GOOGLE_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY"}


def _lezer():
    """Welk model de antwoorden leest.

    Ontbreekt de sleutel van het goedkope model, dan valt hij terug op het dure.
    Stilletjes niets meten zou veel erger zijn dan iets duurder meten."""
    if os.environ.get(SLEUTELS.get(LEES_PROVIDER, "")):
        return {"provider": LEES_PROVIDER, "model": LEES_MODEL}
    return {"provider": "anthropic", "model": MODEL}


# De laatste leesfout, zodat de vergelijking kan laten zien WAAROM een model
# niets opleverde. Op 16 september mislukten er tien van de tien en stond er
# alleen "mislukt" op het scherm. Toen bleek de modelnaam wel te bestaan, en
# was er dus geen enkele aanwijzing meer over. Raden wat er misging kost meer
# tijd dan de fout gewoon opschrijven.
_laatste_leesfout = None


def _lees_met(aanbieder, prompt):
    """Laat een model de leesopdracht uitvoeren en geeft de JSON terug.

    Loopt via metingen.stel_een_vraag, want daar zitten de herkansingen, de
    wachtrij per aanbieder en de foutafhandeling al in. Twee keer hetzelfde
    bouwen is twee keer dezelfde fout kunnen maken."""
    global _laatste_leesfout
    uitkomst = metingen.stel_een_vraag(aanbieder, prompt, min_tekens=2)
    if not uitkomst["gelukt"]:
        _laatste_leesfout = f"{aanbieder['model']}: {uitkomst.get('foutsoort')}"
        print(f"Antwoord lezen mislukt met {aanbieder['model']}: {uitkomst['foutsoort']}")
        return None
    kosten.registreer_aanroep(
        provider=aanbieder["provider"], model=aanbieder["model"],
        invoer_tokens=uitkomst["invoer_tokens"],
        uitvoer_tokens=uitkomst["uitvoer_tokens"],
        soort="categorie-antwoord-lezen",
        duur_ms=uitkomst["duur_ms"])
    return beoordeling._schoon_json(uitkomst["antwoord"]) or {}


def winkels_uit_antwoord(vraag, antwoord):
    """Haalt uit een AI-antwoord welke WINKELS er genoemd worden, en wie er
    aanbevolen wordt. Zonder te weten om welke winkel het ons te doen is.

    Dat laatste is precies waarom dit goedkoop is. Het dure werk, een model het
    antwoord laten lezen, is winkelonafhankelijk. Voor veertig winkels in de
    categorie hoeft dat dus maar EEN keer, en het koppelen daarna is gewoon
    vergelijken."""
    if not antwoord:
        return None

    prompt = _leesprompt(vraag, antwoord)

    data = _lees_met(_lezer(), prompt)
    if data is None:
        return None

    winkels = []
    for w in data.get("winkels", []):
        naam = (w.get("naam") or "").strip()
        if naam:
            # Het webadres gaat mee de database in. Daarmee kan een winkel die
            # AI noemt maar die wij nog niet kenden later aan de lijst worden
            # toegevoegd (zie nieuwe_winkels_uit_antwoorden).
            # soort is "winkel" of "platform" (sinds 23 september, stap 73).
            # Een platform is geen concurrent maar een plek waar je op hoort te
            # staan, en het hoort dus niet in een ranglijst van winkels. Zegt
            # het model iets anders dan die twee, dan behandelen wij het als
            # winkel: dat is hoe het hiervoor altijd ging.
            soort = (w.get("soort") or "").strip().lower()
            winkels.append({"naam": naam, "positie": w.get("positie"),
                            "adres": _schoon_domein(w.get("adres")),
                            "soort": "platform" if soort == "platform" else "winkel"})
    return {
        "winkel_kon_genoemd": bool(data.get("winkel_kon_genoemd")),
        "winkels": winkels,
        "aanbevolen": [n.strip() for n in data.get("aanbevolen", []) if (n or "").strip()],
    }


# ---------------------------------------------------------------------------
# Stap 62: winkels die AI noemt maar die wij nog niet kenden
# ---------------------------------------------------------------------------
#
# WAT ER MIS WAS. Het leesmodel haalt uit elk antwoord welke winkels genoemd
# worden. Daarna legde koppel_aan_winkels die namen naast ONZE lijst, en elke
# naam die daar niet op stond viel stil weg. Terwijl dat juist de interessantste
# winkels zijn: de winkels die AI zelf aanraadt. En het maakte de ranglijst
# minder waar: een winkel die twintig keer genoemd werd maar toevallig niet op
# onze lijst stond, kwam er niet op, en dan is onze nummer 1 niet de echte
# nummer 1. Gevonden op 19 september, toen het plan om met Google Custom Search
# winkels te zoeken niet door kon (die dienst stopt).
#
# WAT ER NU GEBEURT. Het leesmodel geeft bij elke winkel ook het webadres. Na
# een meting gaan de genoemde winkels die wij nog niet kennen de lijst op, in
# deze categorie, en de ranglijst wordt meteen opnieuw geteld uit dezelfde
# bewaarde antwoorden. Dat kost niets: die antwoorden zijn al betaald.
#
# DE REMMEN:
# - Alleen een domein dat eruitziet als een domein EN echt bestaat (DNS). Een
#   model dat toch een adres verzint, komt zo meestal niet door.
# - Een winkel die al op de lijst staat wordt NOOIT verhuisd naar een andere
#   categorie. Een winkel hoort in precies een categorie (zie db.zet_categorie).
# - Hoogstens MAX_NIEUWE_WINKELS per ronde, zodat een rare meting de lijst niet
#   in een keer volgooit.
# - Wat merk of winkel is, en welke adressen een keten vormen, zoekt de
#   nachtronde daarna zelf uit (stap_opschonen). Daar hoeven wij hier niet te
#   raden.

MAX_NIEUWE_WINKELS = int(os.environ.get("MAX_NIEUWE_WINKELS", "25"))

_DOMEIN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")


def _schoon_domein(adres):
    """Maakt van wat het model als adres gaf een kaal domein, of None."""
    if not adres or not isinstance(adres, str):
        return None
    d = adres.strip().lower()
    for voor in ("https://", "http://"):
        if d.startswith(voor):
            d = d[len(voor):]
    d = d.split("/")[0].split("?")[0].split("#")[0].strip(".")
    if d.startswith("www."):
        d = d[4:]
    if not _DOMEIN.match(d) or len(d) > 100:
        return None
    return d


def _domein_bestaat(domein):
    """Of het domein in DNS bestaat. Een verzonnen adres valt hier meestal af."""
    try:
        socket.getaddrinfo(domein, 443)
        return True
    except Exception:
        return False


def _land_bij_domein(domein, standaard="NL"):
    if domein.endswith(".be"):
        return "BE"
    if domein.endswith(".nl"):
        return "NL"
    return standaard


def nieuwe_winkels_uit_antwoorden(genoemden, winkels, slug, bestaat=None):
    """Zet de winkels die AI noemde maar die wij nog niet kenden op de lijst.

    genoemden: wat winkels_uit_antwoord per antwoord teruggaf.
    Geeft de lijst met webadressen die echt nieuw zijn toegevoegd.
    `bestaat` is er voor de test, zodat die geen echte DNS-vragen stelt."""
    bestaat = bestaat or _domein_bestaat
    bekende_domeinen = {_schoon_domein(w["webshop_url"]) for w in winkels}
    kandidaten = {}
    for genoemde in genoemden:
        if not genoemde or not genoemde.get("winkel_kon_genoemd"):
            continue
        gekoppeld = {hoe["als_naam"] for hoe in
                     koppel_aan_winkels(genoemde, winkels).values()
                     if hoe.get("als_naam")}
        for w in genoemde.get("winkels", []):
            domein = w.get("adres")
            if not domein or w["naam"] in gekoppeld or domein in bekende_domeinen:
                continue
            kandidaten.setdefault(domein, (w["naam"], w.get("soort") or "winkel"))

    toegevoegd = []
    platforms = []
    for domein, (naam, soort) in kandidaten.items():
        if len(toegevoegd) >= MAX_NIEUWE_WINKELS:
            break
        if not bestaat(domein):
            continue
        url = scan_engine.normalize_url(domein)
        # Alleen als hij echt NIEUW is een categorie geven. Stond hij er al,
        # dan laten wij hem staan waar hij staat.
        if db.voeg_benadering_toe(url, naam=naam, land=_land_bij_domein(domein),
                                  branche="ai-antwoord"):
            db.zet_categorie(url, slug)
            # STAP 73: een platform komt er wel op, maar als platform.
            # Pararius hoort niet in een ranglijst van makelaars en bol.com
            # niet in een ranglijst van winkels: het zijn geen concurrenten
            # maar plekken waar je op hoort te staan. De ranglijst en de
            # meetwachtrij kijken alleen naar soort winkel, dus zo valt hij er
            # vanzelf buiten zonder dat wij hem kwijtraken.
            if soort == "platform":
                db.zet_soorten({url: "platform"})
                platforms.append(url)
            else:
                toegevoegd.append(url)
    if platforms:
        print(f"Platforms herkend en apart gezet: {platforms}")
    return toegevoegd


def koppel_aan_winkels(genoemde, onze_winkels):
    """Legt de namen uit een antwoord naast onze eigen winkels.

    Kost geen enkele modelaanroep. Dit is het stuk dat een meting van een
    categorie in veertig uitkomsten omzet.

    scan_engine.is_eigen_winkel doet het echte werk: die weet dat
    dille-kamille.nl hetzelfde is als "Dille & Kamille", "Dille en Kamille" en
    "Dille-Kamille"."""
    uit = {}
    namen = [w["naam"] for w in genoemde.get("winkels", [])]
    posities = {w["naam"]: w.get("positie") for w in genoemde.get("winkels", [])}
    aanbevolen = {n.lower() for n in genoemde.get("aanbevolen", [])}

    for winkel in onze_winkels:
        url = winkel["webshop_url"]
        treffer = None
        for naam in namen:
            if scan_engine.is_eigen_winkel(url, naam):
                treffer = naam
                break
        uit[url] = {
            "genoemd": treffer is not None,
            "aanbevolen": bool(treffer) and treffer.lower() in aanbevolen,
            "positie": posities.get(treffer) if treffer else None,
            "als_naam": treffer,
        }
    return uit


def _leesprompt(vraag, antwoord):
    """De leesopdracht, los, zodat de vergelijking dezelfde opdracht gebruikt."""
    return _PROMPT_SJABLOON.format(vraag=vraag, antwoord=antwoord)


def vergelijk_lezers(categorie, aantal=10, goedkoop=None, duur=None):
    """Legt het goedkope leesmodel naast het dure, op al bewaarde antwoorden.

    Dit is het bewijs dat de overstap mag. Er wordt geen enkele vraag opnieuw
    gesteld: de antwoorden van de laatste ronde staan er nog, en alleen het
    lezen wordt overgedaan. Twintig antwoorden kost een paar cent.

    WAT ER GEMETEN WORDT, EN WAAROM DAT NIET DE HELE NAMENLIJST IS.

    Op 16 september gaf de eerste vergelijking 100 procent over meetellen en
    60 procent over de namenlijst. Dat leek afkeuren, maar het meet te streng.
    Ziet het ene model vijf winkels en het andere dezelfde vijf plus een
    zesde die niet van ons is, dan zijn de namenlijsten ongelijk terwijl er in
    onze ranglijst geen letter verandert.

    Wat er wel toe doet: de winkels die in ONZE lijst staan. Alleen die krijgen
    een positie, en alleen daar kan een klant iets door verliezen. Daarom wordt
    het groene licht op dat cijfer gebaseerd, en staat het cijfer over de hele
    namenlijst er alleen als achtergrond bij."""
    goedkoop = goedkoop or {"provider": KANDIDAAT_PROVIDER, "model": KANDIDAAT_MODEL}
    duur = duur or {"provider": "anthropic", "model": MODEL}
    if (goedkoop["provider"], goedkoop["model"]) == (duur["provider"], duur["model"]):
        return {"categorie": categorie, "bekeken": 0, "mislukt": 0,
                "fout": "Het kandidaatmodel is hetzelfde als het huidige. Dan "
                        "vergelijk je een model met zichzelf en zegt de uitkomst niets."}

    rijen = db.bewaarde_antwoorden(categorie, aantal)
    _vgl_stand.update({"nu": 0, "totaal": len(rijen)})
    grens = time.monotonic() + MAX_VERGELIJK_SECONDEN
    uit = {"categorie": categorie, "bekeken": 0, "mislukt": 0,
           "eens_over_meetellen": 0, "eens_over_winkels": 0,
           "eens_over_onze_winkels": 0, "leesfouten": [],
           "goedkoop": goedkoop["model"], "duur": duur["model"], "verschillen": []}
    if not rijen:
        uit["fout"] = f"Geen bewaarde antwoorden voor {categorie}."
        return uit

    # De winkels van deze categorie, want alleen die kunnen een positie krijgen.
    onze_winkels = db.winkels_in_categorie_met_kinderen(categorie)

    for rij in rijen:
        # Een harde tijdslimiet. Zonder deze kon een vergelijking van tien
        # antwoorden in het slechtste geval anderhalf uur duren: tien antwoorden
        # maal twee modellen maal drie herkansingen maal negentig seconden
        # wachttijd. Dan sta je te kijken naar een scherm dat "bezig" zegt en
        # weet je niet of hij nog leeft. Liever een half antwoord met een
        # eerlijke melding dan eindeloos wachten.
        if time.monotonic() > grens:
            uit["afgekapt"] = (f"Gestopt na {MAX_VERGELIJK_SECONDEN // 60} minuten. "
                               f"{uit['bekeken']} van de {len(rijen)} antwoorden gedaan.")
            break
        _vgl_stand["nu"] += 1
        prompt = _leesprompt(rij["vraag"], rij["antwoord"])
        a = _lees_met(goedkoop, prompt)
        b = _lees_met(duur, prompt)
        if a is None or b is None:
            uit["mislukt"] += 1
            # De echte fout erbij, ontdubbeld. Hoogstens drie, want honderd keer
            # dezelfde regel helpt niemand.
            if _laatste_leesfout and _laatste_leesfout not in uit["leesfouten"]:
                if len(uit["leesfouten"]) < 3:
                    uit["leesfouten"].append(_laatste_leesfout)
            continue
        uit["bekeken"] += 1

        mee_a = bool(a.get("winkel_kon_genoemd"))
        mee_b = bool(b.get("winkel_kon_genoemd"))
        if mee_a == mee_b:
            uit["eens_over_meetellen"] += 1

        namen_a = {(w.get("naam") or "").strip().lower()
                   for w in a.get("winkels", []) if (w.get("naam") or "").strip()}
        namen_b = {(w.get("naam") or "").strip().lower()
                   for w in b.get("winkels", []) if (w.get("naam") or "").strip()}
        if namen_a == namen_b:
            uit["eens_over_winkels"] += 1

        # Het cijfer dat telt: zijn ze het eens over ONZE winkels. Alleen die
        # komen in de ranglijst en alleen daar kan iemand een positie door
        # verliezen.
        onze_a = {u for u, hoe in koppel_aan_winkels(a, onze_winkels).items()
                  if hoe["genoemd"]}
        onze_b = {u for u, hoe in koppel_aan_winkels(b, onze_winkels).items()
                  if hoe["genoemd"]}
        if onze_a == onze_b:
            uit["eens_over_onze_winkels"] += 1
        elif len(uit["verschillen"]) < 5:
            uit["verschillen"].append({
                "vraag": rij["vraag"],
                "alleen_goedkoop": sorted(onze_a - onze_b),
                "alleen_duur": sorted(onze_b - onze_a),
                "namen_alleen_goedkoop": sorted(namen_a - namen_b),
                "namen_alleen_duur": sorted(namen_b - namen_a),
            })

    if uit["bekeken"]:
        uit["aandeel_meetellen"] = round(uit["eens_over_meetellen"] / uit["bekeken"], 3)
        uit["aandeel_winkels"] = round(uit["eens_over_winkels"] / uit["bekeken"], 3)
        uit["aandeel_onze_winkels"] = round(
            uit["eens_over_onze_winkels"] / uit["bekeken"], 3)
        # De grens. Onder de negentig procent overeenstemming over ONZE winkels
        # gaat er een klant een positie verliezen die hij niet verloren heeft.
        # Dan is het goedkope model niet goed genoeg, hoeveel het ook scheelt.
        # Het cijfer over de hele namenlijst staat er wel bij, maar telt niet
        # mee: een extra winkel die niet van ons is verandert geen positie.
        uit["mag_over"] = (uit["aandeel_meetellen"] >= 0.95
                           and uit["aandeel_onze_winkels"] >= 0.90)
    return uit


# Hoe lang een vergelijking hoogstens mag duren. Tien antwoorden door twee
# modellen zou binnen een paar minuten moeten. Duurt het langer, dan hangt er
# iets en is doorwachten zinloos.
MAX_VERGELIJK_SECONDEN = int(os.environ.get("VERGELIJK_MAX_SECONDEN", "300"))

# Na deze tijd wordt een vergelijking die nog op "bezig" staat als vastgelopen
# beschouwd, zodat je opnieuw kunt beginnen. Anders zit de knop voorgoed op
# slot na een enkele hangende aanroep.
VASTGELOPEN_NA_SECONDEN = int(os.environ.get("VERGELIJK_VASTGELOPEN_NA", "600"))

_vgl_stand = {"bezig": False, "categorie": None, "uitkomst": None, "fout": None,
              "nu": 0, "totaal": 0, "gestart_op": None}
_vgl_slot = threading.Lock()


def vergelijkstand():
    """De stand, met voortgang en verstreken tijd.

    Een scherm dat alleen "bezig" zegt is niet te onderscheiden van een scherm
    dat vastzit. Daarom staat er nu bij welk antwoord hij is en hoe lang hij
    bezig is."""
    uit = dict(_vgl_stand)
    if uit["gestart_op"]:
        verstreken = int(time.time() - uit["gestart_op"])
        uit["verstreken_sec"] = verstreken
        uit["verstreken"] = (f"{verstreken} seconden" if verstreken < 60
                             else f"{verstreken // 60} minuten")
        uit["vastgelopen"] = uit["bezig"] and verstreken > VASTGELOPEN_NA_SECONDEN
    return uit


def _vgl_werk(categorie, aantal, kandidaat=None):
    try:
        _vgl_stand["uitkomst"] = vergelijk_lezers(categorie, aantal=aantal,
                                                  goedkoop=kandidaat)
    except Exception as e:
        _vgl_stand["fout"] = f"{type(e).__name__}: {e}"[:200]
        print(f"Vergelijking mislukt voor {categorie}: {e}")
    finally:
        _vgl_stand["bezig"] = False


def start_vergelijking(categorie, aantal=6, kandidaat=None):
    """Start de vergelijking van de twee leesmodellen op een eigen draad.

    Tien antwoorden door twee modellen is twintig leesopdrachten. Dat past niet
    binnen de twee minuten van gunicorn, en dat is precies de fout die op 11 en
    op 13 september allebei een omgevallen server opleverde."""
    with _vgl_slot:
        if _vgl_stand["bezig"]:
            # Loopt hij al te lang, dan is hij vastgelopen en mag er een nieuwe
            # beginnen. De oude draad doet verder geen kwaad: die schrijft
            # hoogstens een uitkomst weg die daarna overschreven wordt.
            begon = _vgl_stand.get("gestart_op") or 0
            if time.time() - begon < VASTGELOPEN_NA_SECONDEN:
                return False
            print("Vorige vergelijking lijkt vastgelopen, er wordt opnieuw gestart.")
        _vgl_stand.update({"bezig": True, "categorie": categorie,
                           "uitkomst": None, "fout": None,
                           "nu": 0, "totaal": 0, "gestart_op": time.time()})
    threading.Thread(target=_vgl_werk, args=(categorie, aantal, kandidaat),
                     daemon=True).start()
    return True


def rol_ketens_op(telling, winkels):
    """Telt de adressen van dezelfde keten bij elkaar op en laat eruit wat niet
    in een winkelranglijst hoort.

    Waarom dit moet. In de eerste echte ranglijst stond cookinglife.be eerste en
    cookinglife.nl tweede, met exact dezelfde cijfers. Dat is dezelfde winkel op
    twee plekken, waardoor een top tien er maar acht bevat en een echte
    concurrent onterecht wegzakt.

    Wat hier NIET gebeurt: een vermelding weggooien. cookinglife.be wordt nog
    steeds herkend in een antwoord, de treffer verhuist alleen naar het
    hoofdadres. Wordt een keten in dezelfde vraag onder twee adressen genoemd,
    dan telt dat een keer, want de telling gaat over vragen en niet over
    vermeldingen. Daarom zijn het verzamelingen en geen getallen.

    Eruit gaan: merken, want Brabantia is geen webshop, en regels zonder
    webadres, want die kunnen nooit aan een AI-antwoord gekoppeld worden en
    zouden dus eeuwig onterecht nul scoren."""
    aanwezig = {w["webshop_url"] for w in winkels}
    hoofd_van, soort_van = {}, {}
    for w in winkels:
        url = w["webshop_url"]
        hoofd = w.get("hoort_bij") or url
        # Wijst het hoofdadres naar een winkel buiten deze categorie, dan houdt
        # dit adres zichzelf. Anders verdwijnt de hele telling in het niets.
        hoofd_van[url] = hoofd if hoofd in aanwezig else url
        soort_van[url] = w.get("soort") or "winkel"

    samen = {}
    for url, t in telling.items():
        doel = hoofd_van.get(url, url)
        if soort_van.get(doel, "winkel") != "winkel":
            continue
        bij = samen.setdefault(doel, {"genoemd": set(), "aanbevolen": set(),
                                      "beste_positie": None})
        bij["genoemd"] |= t["genoemd"]
        bij["aanbevolen"] |= t["aanbevolen"]
        p = t["beste_positie"]
        if p and (bij["beste_positie"] is None or p < bij["beste_positie"]):
            bij["beste_positie"] = p
    return samen


def maak_ranglijst(telling, winkels):
    """Van een telling per adres naar een ranglijst met posities.

    Staat apart omdat er twee wegen naartoe leiden: een verse meting, en een
    herberekening uit bewaarde antwoorden. Zouden die twee elk hun eigen
    sorteerregels hebben, dan kan een herberekening een andere volgorde geven
    dan de meting, en dan weet niemand meer welke lijst waar is.

    Eerst opschonen: ketens bij elkaar, merken en adresloze regels eruit. Dat
    gebeurt na het tellen en niet ervoor, zodat een vermelding van
    cookinglife.be wel meetelt maar niet als eigen regel op de lijst komt.

    Aanbevolen weegt zwaarder dan genoemd, want in een rij staan is iets anders
    dan aangeraden worden."""
    opgeschoond = rol_ketens_op(telling, winkels)
    rangen = sorted(
        ({"webshop_url": u,
          "genoemd": len(t["genoemd"]),
          "aanbevolen": len(t["aanbevolen"]),
          "beste_positie": t["beste_positie"]} for u, t in opgeschoond.items()),
        key=lambda r: (-r["aanbevolen"], -r["genoemd"], r["webshop_url"]))
    for plek, rij in enumerate(rangen, start=1):
        rij["positie"] = plek
    return rangen


def tel_uit_antwoorden(rijen, winkels):
    """Telt bewaarde antwoorden uit zonder ook maar een model aan te roepen.

    Elk antwoord staat in de database met wat eruit gelezen is: welke winkels
    erin voorkwamen, wie er aanbevolen werd, en of er uberhaupt een winkel
    genoemd kon worden. Dat is precies wat het tellen nodig heeft. Het dure
    stuk, het lezen, is al betaald.

    Tellen gebeurt per VRAAG en niet per antwoord. Dezelfde vraag is aan twee
    modellen gesteld; wordt een winkel door allebei genoemd, dan is dat een
    vraag waarbij hij genoemd werd, niet twee. Daarom zijn het verzamelingen."""
    telling = {w["webshop_url"]: {"genoemd": set(), "aanbevolen": set(),
                                  "beste_positie": None} for w in winkels}
    telbaar = set()
    for rij in rijen:
        genoemde = rij.get("genoemde_winkels") or {}
        if isinstance(genoemde, str):
            genoemde = json.loads(genoemde)
        if not genoemde.get("winkel_kon_genoemd"):
            continue
        vraag = rij["vraag"]
        telbaar.add(vraag)
        for url, hoe in koppel_aan_winkels(genoemde, winkels).items():
            if hoe["genoemd"]:
                telling[url]["genoemd"].add(vraag)
                p = hoe["positie"]
                huidig = telling[url]["beste_positie"]
                if p and (huidig is None or p < huidig):
                    telling[url]["beste_positie"] = p
            if hoe["aanbevolen"]:
                telling[url]["aanbevolen"].add(vraag)
    return telling, telbaar


def herbereken_ranglijst(slug):
    """Rekent de ranglijst opnieuw uit de bewaarde antwoorden. Kost niets.

    WAAROM DEZE KNOP ER IS. In de eerste ranglijst van servies stonden
    cookinglife.be en cookinglife.nl als twee regels met dezelfde cijfers. Dat
    is een keten met twee adressen, en sinds het opschonen weet de database dat.
    Maar de ranglijst was al gemaakt, en de enige manier om hem te verbeteren
    was opnieuw meten. Opnieuw meten kost veertig cent en een half uur, terwijl
    er aan de gemeten werkelijkheid niets veranderd is: alleen onze kennis over
    welke adressen bij elkaar horen is beter geworden.

    Wat hier dus NIET gebeurt: er wordt geen enkele vraag opnieuw gesteld en er
    wordt geen enkel antwoord opnieuw gelezen. Nul modelaanroepen, nul euro.

    Gebruik hem na het opschonen, na het indelen in categorieen, en nadat je met
    de hand een adres als merk hebt gemarkeerd."""
    ronde = db.laatste_afgeronde_ronde(slug)
    if not ronde:
        return {"fout": f"Er is nog geen afgeronde meting van {slug}."}
    rijen = db.antwoorden_van_ronde(ronde)
    if not rijen:
        return {"fout": "Er zijn geen bewaarde antwoorden bij deze ronde."}
    winkels = db.winkels_in_categorie_met_kinderen(slug)
    if not winkels:
        return {"fout": f"Geen winkels in {slug}."}

    telling, telbaar = tel_uit_antwoorden(rijen, winkels)
    rangen = maak_ranglijst(telling, winkels)
    db.wis_categorie_uitkomsten(ronde)
    db.bewaar_categorie_uitkomsten(ronde, slug, rangen, len(telbaar))
    return {"ronde": ronde, "categorie": slug, "winkels": len(rangen),
            "antwoorden": len(rijen), "telbaar": len(telbaar),
            "gemeten_adressen": len(winkels), "ranglijst": rangen}


# ---------------------------------------------------------------------------
# Stap 6: meer vragen laten meetellen
# ---------------------------------------------------------------------------
#
# Bij Speelgoed telden er 13 van de 30 vragen mee. De andere zeventien leverden
# geen enkele webshop op, meestal omdat er om een product of een merk gevraagd
# werd en niet om een plek om te kopen. Dat is dubbel zonde: die vragen kosten
# wel geld en ze leveren geen enkel cijfer op.
#
# Twee dingen ertegen. Vooraf: de opdracht om vragen te bedenken is strenger
# geworden, met voorbeelden van goed en fout. Achteraf: een vraag die bij twee
# of meer antwoorden nooit een winkel opleverde gaat uit, en de volgende ronde
# wordt hij niet meer gesteld.

def snoei_vragen(slug, minstens=2):
    """Zet de koopvragen uit die nooit een winkel opleveren.

    Nooit op een enkele meting, want dan zet je een goede vraag uit omdat een
    model die ene keer een merkenlijstje gaf. Pas vanaf twee antwoorden die er
    allebei niets uit kregen."""
    zwak = db.vragen_die_nooit_meetelden(slug, minstens=minstens)
    if not zwak:
        return {"categorie": slug, "uitgezet": 0, "vragen": []}
    aantal = db.zet_vragen_uit(slug, [z["vraag"] for z in zwak])
    return {"categorie": slug, "uitgezet": aantal, "vragen": zwak}


# ---------------------------------------------------------------------------
# Een hele categorie meten
# ---------------------------------------------------------------------------

# Na deze tijd geldt een meting als vastgelopen en mag er opnieuw gestart
# worden. Een volledige meting is dertig vragen aan twee modellen; twintig
# minuten is normaal, drie kwartier niet meer.
METING_VASTGELOPEN_NA = int(os.environ.get("METING_VASTGELOPEN_NA", "2700"))

_stand = {"bezig": False, "categorie": None, "stap": None,
          "vraag_nu": 0, "vragen_totaal": 0, "antwoorden": 0, "mislukt": 0,
          "gestart_op": None, "klaar_op": None, "fout": None}
_slot = threading.Lock()


def stand():
    """De stand van de meting, met stap en verstreken tijd.

    "vraag 0 van 0" zei niets, want voordat er een vraag gesteld kan worden
    moeten de koopvragen van een categorie eerst bedacht worden, en dat is zelf
    ook een modelaanroep van een minuut of wat. Nu staat er wat hij doet."""
    uit = dict(_stand)
    if uit["gestart_op"]:
        verstreken = int(time.time() - uit["gestart_op"])
        uit["verstreken_sec"] = verstreken
        uit["verstreken"] = (f"{verstreken} seconden" if verstreken < 60
                             else f"{verstreken // 60} minuten")
        uit["vastgelopen"] = uit["bezig"] and verstreken > METING_VASTGELOPEN_NA
    return uit


def meet_categorie(slug, max_vragen=None):
    """Meet een categorie: elke vraag een keer per model, alle winkels gescoord.

    Draait op de aanroepende draad. De beheerpagina start hem via
    start_meting() op een eigen draad, want dit duurt minuten en dat hoort nooit
    aan een verzoek te hangen."""
    _stand["stap"] = "winkels ophalen"
    winkels = db.winkels_in_categorie_met_kinderen(slug)
    if not winkels:
        return {"fout": f"Geen winkels in {slug}."}

    _stand["stap"] = "koopvragen ophalen"
    vragen = db.categorie_vragen(slug)
    # Aanvullen tot er weer dertig actieve vragen zijn. Dat is nodig sinds
    # zwakke vragen na een ronde uitgezet worden: zonder aanvullen zou elke
    # ronde met minder vragen meten dan de vorige en zou de meting langzaam
    # uitdoven. Nu gaat er een vraag uit die niets oplevert en komt er een
    # nieuwe voor terug.
    # Twee pogingen, en met de bestaande vragen erbij (23 september). Tot
    # vandaag wist het model niet welke vragen er al waren: het bedacht dan
    # dezelfde, die vielen weg op de unieke sleutel, en de categorie bleef
    # onder de dertig steken. Op de openbare index was dat te zien: Servies
    # en tafelgerei mat met 19 vragen en Speelgoed met 28, ronde na ronde.
    for _poging in range(2):
        if len(vragen) >= VRAGEN_PER_CATEGORIE:
            break
        # Dit is een modelaanroep van een minuut of wat, en tot 16 september
        # stond er ondertussen "vraag 0 van 0" op het scherm. Dat leest als
        # vastgelopen terwijl er gewoon gewerkt wordt.
        tekort = VRAGEN_PER_CATEGORIE - len(vragen)
        _stand["stap"] = f"{tekort} koopvragen bedenken voor deze categorie"
        # Ruim vragen, want er vallen er altijd een paar af als dubbel.
        nieuw = bedenk_vragen(slug, aantal=max(tekort + 5, 8),
                              vermijd=db.alle_categorie_vragen_tekst(slug))
        if not nieuw:
            break
        db.bewaar_categorie_vragen(slug, nieuw)
        vragen = db.categorie_vragen(slug)
    if not vragen:
        return {"fout": "Er konden geen vragen bedacht worden."}
    if len(vragen) < VRAGEN_PER_CATEGORIE:
        # Niet stilhouden: met te weinig vragen is de meting minder waard, en
        # op de openbare pagina staat hoeveel vragen er gesteld zijn.
        print(f"LET OP: {slug} meet met {len(vragen)} vragen in plaats van "
              f"{VRAGEN_PER_CATEGORIE}. Het aanvullen leverde te weinig nieuwe op.")
    if not vragen:
        return {"fout": "Er zijn geen koopvragen voor deze categorie."}
    if max_vragen:
        vragen = vragen[:max_vragen]

    _stand["stap"] = "modellen nakijken"
    aanbieders = metingen.beschikbare_aanbieders()
    if not aanbieders:
        return {"fout": "Geen enkele AI-sleutel gevonden."}

    ronde = db.start_categorie_ronde(slug, len(vragen), len(winkels))
    _stand.update({"vragen_totaal": len(vragen) * len(aanbieders), "vraag_nu": 0,
                   "stap": "vragen stellen en antwoorden lezen"})

    # Per winkel bijhouden bij hoeveel vragen hij genoemd en aanbevolen werd.
    telling = {w["webshop_url"]: {"genoemd": set(), "aanbevolen": set(),
                                  "beste_positie": None} for w in winkels}
    telbaar = set()
    # Alles wat het leesmodel deze ronde uit de antwoorden haalde, voor stap 62.
    alle_genoemde = []

    for vraag in vragen:
        for aanbieder in aanbieders:
            _stand["vraag_nu"] += 1
            rem = kosten.mag_doorgaan()
            if not rem["mag"]:
                _stand["fout"] = f"Gestopt door de kostenrem: {rem['reden']}"
                break

            uitkomst = metingen.stel_een_vraag(aanbieder, vraag["vraag"])
            if not uitkomst["gelukt"]:
                _stand["mislukt"] += 1
                continue
            kosten.registreer_aanroep(
                provider=aanbieder["provider"], model=aanbieder["model"],
                invoer_tokens=uitkomst["invoer_tokens"],
                uitvoer_tokens=uitkomst["uitvoer_tokens"],
                soort="categoriemeting", duur_ms=uitkomst["duur_ms"])

            genoemde = winkels_uit_antwoord(vraag["vraag"], uitkomst["antwoord"])
            if genoemde is None:
                _stand["mislukt"] += 1
                continue

            db.bewaar_categorie_antwoord(
                ronde, slug, vraag["vraag"], aanbieder["model"],
                uitkomst["antwoord"], genoemde)
            _stand["antwoorden"] += 1
            alle_genoemde.append(genoemde)

            if not genoemde["winkel_kon_genoemd"]:
                # Een vraag waar geen enkele webshop in kon voorkomen telt niet
                # mee. Anders maak je elk cijfer mooier of lelijker dan het is.
                continue
            telbaar.add(vraag["vraag"])

            for url, hoe in koppel_aan_winkels(genoemde, winkels).items():
                if hoe["genoemd"]:
                    telling[url]["genoemd"].add(vraag["vraag"])
                    p = hoe["positie"]
                    huidig = telling[url]["beste_positie"]
                    if p and (huidig is None or p < huidig):
                        telling[url]["beste_positie"] = p
                if hoe["aanbevolen"]:
                    telling[url]["aanbevolen"].add(vraag["vraag"])

    # Stap 62: winkels die AI noemde maar die wij nog niet kenden gaan de lijst
    # op, en dan tellen wij opnieuw uit DEZELFDE bewaarde antwoorden. Zo staan
    # ze meteen in deze ranglijst en niet pas over dertig dagen. Geen enkele
    # extra modelaanroep. Mislukt dit, dan blijft de gewone telling staan: een
    # onvolledige ranglijst is beter dan geen ranglijst.
    nieuw = []
    try:
        _stand["stap"] = "nieuwe winkels uit de antwoorden toevoegen"
        nieuw = nieuwe_winkels_uit_antwoorden(alle_genoemde, winkels, slug)
        if nieuw:
            winkels = db.winkels_in_categorie_met_kinderen(slug)
            telling, telbaar = tel_uit_antwoorden(db.antwoorden_van_ronde(ronde), winkels)
    except Exception as e:
        print(f"Nieuwe winkels toevoegen mislukt voor {slug}: {e}")

    rangen = maak_ranglijst(telling, winkels)
    db.bewaar_categorie_uitkomsten(ronde, slug, rangen, len(telbaar))

    # Opruimen voor de volgende keer: vragen die nooit een winkel opleveren gaan
    # uit. Dat is wat het aandeel meetellende vragen omhoog brengt, en het maakt
    # de volgende ronde tegelijk goedkoper, want zo'n vraag wordt niet meer
    # gesteld en niet meer gelezen.
    _stand["stap"] = "zwakke vragen opruimen"
    gesnoeid = snoei_vragen(slug)

    return {"ronde": ronde, "categorie": slug, "winkels": len(rangen),
            "gemeten_adressen": len(winkels),
            "uitgezette_vragen": gesnoeid.get("uitgezet", 0),
            "vragen": len(vragen), "telbaar": len(telbaar),
            "antwoorden": _stand["antwoorden"], "mislukt": _stand["mislukt"],
            "nieuwe_winkels": nieuw,
            "ranglijst": rangen}


def _werk(slug, max_vragen):
    try:
        uitkomst = meet_categorie(slug, max_vragen=max_vragen)
        if uitkomst.get("fout"):
            _stand["fout"] = uitkomst["fout"]
        print(f"Categoriemeting klaar: {slug}, {uitkomst}")
    except Exception as e:
        _stand["fout"] = f"{type(e).__name__}: {e}"[:200]
        print(f"Categoriemeting mislukt voor {slug}: {e}")
    finally:
        _stand["bezig"] = False
        _stand["klaar_op"] = time.time()


def start_meting(slug, max_vragen=None):
    """Start een categoriemeting op een eigen draad.

    Nooit in het verzoek zelf: dertig vragen aan twee modellen is een minuut of
    tien, en gunicorn kapt na twee minuten af. Die fout is op 11 en op 13
    september allebei gemaakt en hoeft geen derde keer."""
    with _slot:
        if _stand["bezig"]:
            begon = _stand.get("gestart_op") or 0
            if time.time() - begon < METING_VASTGELOPEN_NA:
                return False
            print("Vorige meting lijkt vastgelopen, er wordt opnieuw gestart.")
        _stand.update({"bezig": True, "categorie": slug, "stap": "starten",
                       "vraag_nu": 0, "vragen_totaal": 0, "antwoorden": 0,
                       "mislukt": 0, "gestart_op": time.time(),
                       "klaar_op": None, "fout": None})
    threading.Thread(target=_werk, args=(slug, max_vragen), daemon=True).start()
    return True
