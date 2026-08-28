"""
Krillo - fase 5 punt 15: van meting naar hoogstens drie concrete stappen.

Dit is het antwoord op wat Vitalii op het ondernemersforum zei: "voor mij, als
gewone ondernemer, is dit niet interessant, ik vraag de specialisten om dit
voor mij te doen."

Daar zit alles in. Een cijfer vraagt om een specialist. Een lijstje met drie
dingen die je deze week kan doen, niet. Zolang Krillo alleen meet dat je bij 4
van de 22 vragen genoemd wordt, verkoop je een dashboard dat mensen wegklikken.
Dit bestand is wat het abonnement 39 euro waard moet maken.

DRIE REGELS DIE HIER VASTLIGGEN:

1. HOOGSTENS DRIE ACTIES. Niet vijf, niet tien. Iemand met een webshop heeft
   geen tijd en geen zin in een lijst. Twaalf verbeterpunten is hetzelfde als
   nul verbeterpunten, want er wordt niet aan begonnen. Wat afvalt is niet
   onbelangrijk, het komt gewoon volgende keer.

2. DE VOLGORDE IS EEN VAST REKENMODEL, GEEN AI. Dezelfde meting moet altijd
   dezelfde drie acties opleveren, in dezelfde volgorde. Zou een model de
   prioriteit bepalen, dan krijgt een klant deze week een ander advies dan
   vorige week zonder dat er iets veranderd is, en dan is het geen advies meer
   maar een gok. Zelfde afspraak als bij de kostenberekening.

3. FEIT GAAT VOOR VERMOEDEN. Eerst wat aantoonbaar misgaat, dan pas wat we
   vermoeden. Een actie die begint met "waarschijnlijk helpt het als" hoort
   nooit boven een actie die begint met "dit houdt AI tegen".

DE LADDER, van meeste naar minste opbrengst:

  1. Blokkades op je eigen site. Zolang AI je site niet mag of kan lezen, heeft
     al het andere geen zin. Dit is een feit, gemeten op de site zelf.
  2. Onjuistheden die AI over je vertelt. Zegt een model iets over jouw winkel
     dat niet klopt, dan kost dat je direct klanten, en het is te repareren met
     tekst op je eigen site. Ook een feit, want we hebben het naast je site
     gelegd.
  3. Externe plekken waar je niet staat. Dit komt uit de bronanalyse en het is
     de grootste hefboom die er is, want het meeste van wat AI over een winkel
     zegt komt van buiten die winkel. Feit, met een adres erbij dat je zelf kan
     openen.
  4. Leesbaarheid van je site. Nuttig, goedkoop, maar het is een vermoeden en
     het gaat over het kleinste deel van het verhaal. Daarom onderaan.
"""

import hashlib

# Hoeveel acties een klant maximaal krijgt. Zie regel 1 hierboven.
MAX_ACTIES = 3

# Wat je doet bij een harde blokkade. Per controlepunt uit de scan, in gewone
# taal en met de route erbij voor de twee platformen die het vaakst voorkomen.
BLOKKADE_ACTIES = {
    "robots": {
        "titel": "Geef AI-robots toegang tot je site",
        "hoe": (
            "In het bestand robots.txt op je site staat nu dat AI-robots niet welkom zijn. "
            "Zolang dat er staat mag geen enkele AI-assistent je pagina's lezen, en dan kan "
            "hij je ook niet aanbevelen. In Shopify vind je dit onder Winkelinstellingen, dan "
            "robots.txt.liquid. In WordPress zit het meestal in je SEO-plugin onder "
            "Gereedschap. Haal de regels weg die GPTBot, ClaudeBot, PerplexityBot, "
            "OAI-SearchBot of Google-Extended blokkeren."
        ),
    },
    "https": {
        "titel": "Zet een beveiligde verbinding aan",
        "hoe": (
            "Je site draait nog zonder https. Browsers waarschuwen bezoekers daarvoor en "
            "AI-systemen behandelen zo'n site als minder betrouwbaar. Bij Shopify en de "
            "meeste hostingpartijen zet je dit met een knop aan en is het gratis. Vraag je "
            "hostingpartij om een SSL-certificaat als je het zelf niet kan vinden."
        ),
    },
    "leesbaarheid": {
        "titel": "Zorg dat je teksten direct in de pagina staan",
        "hoe": (
            "Op je pagina staat nauwelijks tekst die meteen te lezen is. Je teksten "
            "verschijnen pas nadat scripts zijn uitgevoerd, en een AI die je pagina ophaalt "
            "ziet dan een lege bladzijde. Vraag je websitebouwer om de belangrijkste teksten, "
            "productnamen en omschrijvingen gewoon in de pagina zelf te zetten."
        ),
    },
}

# De leesbaarheidspunten, op volgorde van wat het meeste oplevert voor of AI je
# begrijpt. Vraag en antwoord staat bovenaan omdat dat het soort tekst is dat
# modellen het vaakst bijna letterlijk overnemen.
#
# llms.txt staat expres helemaal onderaan, ook al is het snel gedaan. Krillo
# heeft er zelf een artikel over geschreven dat zegt dat je het waarschijnlijk
# niet nodig hebt. Dan kan je het niet even later als actiepunt drie aan een
# betalende klant verkopen. Je eigen eerlijke verhaal en je eigen advies mogen
# elkaar nooit tegenspreken.
BELEMMERING_VOLGORDE = [
    "faq", "productinfo", "basis", "koppen", "sitemap",
    "taal", "voorbeeldweergave", "alt_tekst", "snelheid", "llms_txt",
]

BELEMMERING_ACTIES = {
    "faq": {
        "titel": "Zet vragen en antwoorden op je site",
        "hoe": (
            "Schrijf de tien vragen op die klanten je het vaakst stellen, met per vraag een "
            "kort antwoord. Over maten, materiaal, levering, retour, onderhoud. Dit is het "
            "soort tekst dat AI-assistenten het vaakst bijna letterlijk overnemen, omdat het "
            "precies past bij hoe mensen vragen stellen."
        ),
    },
    "productinfo": {
        "titel": "Zet machine-leesbare productgegevens op je pagina's",
        "hoe": (
            "Je productpagina's missen de onzichtbare gegevens (schema.org) waarmee een "
            "computer prijs, voorraad en beoordelingen betrouwbaar kan overnemen. Zonder dat "
            "moet een AI het uit je lopende tekst raden. Shopify-thema's hebben dit meestal "
            "ingebouwd maar staat het uit; in WordPress doet een SEO-plugin dit."
        ),
    },
    "basis": {
        "titel": "Maak je paginatitel en omschrijving af",
        "hoe": (
            "De titel en de korte omschrijving van je pagina zijn onvolledig. Dat is letterlijk "
            "het eerste wat een AI van je pagina ziet. Zet er in gewone woorden in wat je "
            "verkoopt en voor wie, zonder trucjes."
        ),
    },
    "koppen": {
        "titel": "Breng orde in je koppen",
        "hoe": (
            "Je pagina heeft geen duidelijke koppenstructuur. Eén hoofdkop bovenaan die zegt "
            "waar de pagina over gaat, daaronder tussenkopjes per onderwerp. Zo kan een AI "
            "bepalen wat de kern is en wat bijzaak."
        ),
    },
    "sitemap": {
        "titel": "Dien een sitemap in",
        "hoe": (
            "Er is geen sitemap gevonden. Dat is de lijst met al je pagina's. Shopify en "
            "WordPress maken hem automatisch; je hoeft hem alleen in te dienen bij Google "
            "Search Console en Bing Webmaster Tools. Bing telt hier extra, want ChatGPT leunt "
            "daarop bij het zoeken."
        ),
    },
    "llms_txt": {
        "titel": "Zet een llms.txt op je site",
        "hoe": (
            "Een klein tekstbestand waarin je zelf in een paar zinnen uitlegt wat je verkoopt "
            "en welke pagina's het belangrijkst zijn. Eerlijk gezegd is nog niet bewezen dat "
            "AI-assistenten hier veel mee doen, dus verwacht er niet te veel van. Het kost je "
            "tien minuten."
        ),
    },
    "taal": {
        "titel": "Leg de taal van je pagina vast",
        "hoe": (
            "In de code van je pagina staat niet dat hij Nederlands is. Daardoor kan een "
            "systeem twijfelen of je voor de Nederlandse markt bedoeld bent. Eén regel in je "
            "thema lost dit op."
        ),
    },
    "voorbeeldweergave": {
        "titel": "Vul de gegevens voor de voorbeeldweergave in",
        "hoe": (
            "Als iemand je link deelt in WhatsApp of op social media, is er geen plaatje en "
            "geen omschrijving. Dat kost je kliks, en die kliks zijn precies wat mensen ergens "
            "over je laat schrijven."
        ),
    },
    "alt_tekst": {
        "titel": "Beschrijf je afbeeldingen",
        "hoe": (
            "Een deel van je afbeeldingen heeft geen beschrijving. Een AI ziet een plaatje "
            "niet, alleen de tekst eromheen. Beschrijf in een paar woorden wat erop staat."
        ),
    },
    "snelheid": {
        "titel": "Maak je site sneller",
        "hoe": (
            "Je pagina reageert traag. Dat kost je bezoekers, en systemen die je pagina "
            "ophalen geven soms eerder op. Grote afbeeldingen zijn meestal de oorzaak."
        ),
    },
}


def _actie(taak_id, soort, titel, waarom, hoe, links=None):
    """Elke actie heeft een vast kenmerk (taak_id), zodat de kant-en-klare
    oplossing die erbij hoort eenmalig geschreven en daarna bewaard kan worden.
    Zonder zo'n kenmerk zou dezelfde taak elke week een nieuwe tekst krijgen."""
    return {"id": taak_id, "soort": soort, "titel": titel, "waarom": waarom,
            "hoe": hoe, "links": links or [], "oplossing": None, "waar": None}


def _blokkade_acties(verklaring):
    """Stap 1: wat AI aantoonbaar tegenhoudt. Altijd bovenaan."""
    acties = []
    for b in (verklaring or {}).get("blokkades") or []:
        sjabloon = BLOKKADE_ACTIES.get(b.get("id"))
        if not sjabloon:
            continue
        acties.append(_actie(
            b.get("id"),
            "feit",
            sjabloon["titel"],
            "Dit houdt AI aantoonbaar tegen. Zolang dit er staat heeft de rest weinig zin, "
            "want dan kan een AI-assistent je site niet lezen en dus ook niet aanbevelen.",
            sjabloon["hoe"],
        ))
    return acties


def _onjuistheid_acties(controle, winkelnaam):
    """Stap 2: AI vertelt iets over je winkel dat niet klopt.

    Dit is de meest onderschatte actie in de hele lijst. Een winkel die weinig
    genoemd wordt mist omzet, maar een winkel waarover een verkeerde levertijd
    of een verkeerd retourbeleid rondgaat, verliest klanten die al bijna
    besloten hadden."""
    fouten = [f for f in (controle or {}).get("fouten") or [] if f.get("uitspraak")]
    if not fouten:
        return []

    naam = winkelnaam or "je winkel"
    voorbeelden = []
    for f in fouten[:3]:
        zegt = (f.get("uitspraak") or "").strip()
        site = (f.get("watzegtdesite") or "").strip()
        voorbeelden.append(f'AI zegt: "{zegt}"' + (f' Op je site staat: "{site}"' if site else ""))

    aantal = len(fouten)
    # Het kenmerk hangt aan de uitspraken zelf. Verandert er wat AI fout zegt,
    # dan hoort daar een nieuwe tekst bij. Zou het kenmerk alleen
    # "onjuistheden" zijn, dan bleef de tekst van vorige maand staan bij een
    # heel andere fout, en dat is erger dan geen tekst.
    kenmerk = "onjuistheden-" + hashlib.sha1(
        "|".join(sorted((f.get("uitspraak") or "") for f in fouten)).encode("utf-8")
    ).hexdigest()[:10]

    return [_actie(
        kenmerk,
        "feit",
        "Zet recht wat AI verkeerd over je vertelt",
        (f"We vonden {aantal} uitspraak over {naam} die niet klopt met wat er op je site staat. "
         f"Dit weegt zwaarder dan het lijkt: iemand die dit leest en langskomt, vindt iets "
         f"anders dan hij verwachtte. Dat is een klant die al bijna besloten had."),
        ("Zet het juiste antwoord duidelijk en in gewone zinnen op je eigen site, het liefst "
         "op een vraag-en-antwoordpagina. AI-modellen halen hun beeld van je winkel deels bij "
         "je eigen pagina's op, dus daar begint de correctie. Wat er nu misgaat:\n\n"
         + "\n".join(f"- {v}" for v in voorbeelden)),
    )]


def _bronnen_acties(bronnen, winkelnaam):
    """Stap 3: de externe plekken waar je concurrent staat en jij niet.

    De grootste hefboom, want het meeste van wat AI over een winkel zegt komt
    van buiten die winkel. En het mooiste eraan: deze pagina's bestaan al."""
    gemist = (bronnen or {}).get("gemiste_paginas") or []
    if not gemist:
        return []

    naam = winkelnaam or "je winkel"
    top = gemist[:4]
    namen = sorted({n for g in top for n in (g.get("concurrenten") or [])})
    wie = ", ".join(namen[:4]) if namen else "winkels die AI wel noemt"

    aantal = (bronnen or {}).get("gemist") or len(gemist)
    plekken = "plek" if aantal == 1 else "plekken"

    return [_actie(
        "bronnen",
        "feit",
        f"Zorg dat {naam} op deze {aantal} {plekken} komt te staan",
        (f"We hebben jouw koopvragen in een gewone zoekmachine gezet en de pagina's nagelopen "
         f"die daaruit kwamen. Op deze {plekken} staan {wie} wel, en {naam} niet. Dit is de "
         f"grootste hefboom die je hebt: het meeste van wat AI over een winkel zegt komt niet "
         f"van die winkel zelf, maar van wat er elders over geschreven staat. En deze pagina's "
         f"bestaan al, je hoeft ze niet te maken."),
        ("Open de pagina's hieronder en kijk hoe de genoemde winkels er terechtgekomen zijn. "
         "Meestal is dat een redactie die een lijstje samenstelde, of een gesprek waar iemand "
         "een tip gaf. Zoek op de pagina naar contact, redactie of tips, en stuur een kort "
         "bericht: wie je bent, wat je verkoopt, en wat jouw winkel heeft dat de genoemde "
         "winkels niet hebben. Dat laatste is het enige dat telt, want zonder reden om je toe "
         "te voegen gebeurt er niets. Bij een forum of een vraagdraadje kan je zelf antwoorden, "
         "maar wees dan open over het feit dat het je eigen winkel is."),
        links=[{"url": g["url"], "titel": g.get("titel") or g.get("domein"),
                "domein": g.get("domein")} for g in top],
    )]


def _belemmering_acties(verklaring):
    """Stap 4: de leesbaarheid van je site. Nuttig, maar het blijft een
    vermoeden en het gaat over het kleinste deel van het verhaal."""
    aanwezig = {b.get("id") for b in (verklaring or {}).get("belemmeringen") or []}
    acties = []
    for id_ in BELEMMERING_VOLGORDE:
        if id_ not in aanwezig:
            continue
        sjabloon = BELEMMERING_ACTIES.get(id_)
        if not sjabloon:
            continue
        acties.append(_actie(
            id_,
            "vermoeden",
            sjabloon["titel"],
            "Dit maakt je site beter leesbaar voor AI. Of je hierdoor vaker genoemd wordt "
            "weten we niet, en dat beweren we dus ook niet. Het is wel goedkoop en je hebt "
            "het zelf in de hand.",
            sjabloon["hoe"],
        ))
    return acties


def maak_actieplan(verklaring=None, klantbeeld=None, bronnen=None, controle=None,
                   winkelnaam=None, maximum=None):
    """Zet alles wat we van een winkel weten om in hoogstens drie acties.

    Krijgt de uitkomsten van de andere onderdelen en kiest daaruit. Rekent
    zelf niets uit en vraagt niets aan een AI: het is puur een volgorde. Dat is
    met opzet, want dezelfde meting hoort altijd hetzelfde advies te geven.

    Geeft None terug als er nog niet gemeten is. Dan is er niets te adviseren
    en dat is beter dan iets verzinnen."""
    maximum = maximum or MAX_ACTIES

    if not klantbeeld or not klantbeeld.get("telbaar"):
        return None

    alles = (
        _blokkade_acties(verklaring)
        + _onjuistheid_acties(controle, winkelnaam)
        + _bronnen_acties(bronnen, winkelnaam)
        + _belemmering_acties(verklaring)
    )

    gekozen = alles[:maximum]
    rest = len(alles) - len(gekozen)

    genoemd = klantbeeld.get("genoemd") or 0
    telbaar = klantbeeld.get("telbaar") or 0
    naam = winkelnaam or "Je winkel"

    if not gekozen:
        kop = (f"{naam} wordt genoemd bij {genoemd} van de {telbaar} vragen, en we vinden op dit "
               f"moment niets om aan te pakken. Je site is in orde en op de plekken die we "
               f"nakeken sta je erbij. Houd het zo en let vooral op wat concurrenten doen.")
    elif genoemd == 0:
        kop = (f"{naam} werd deze ronde bij geen enkele van de {telbaar} vragen genoemd. "
               f"Hieronder staat wat je daaraan kan doen, belangrijkste eerst.")
    else:
        kop = (f"{naam} wordt genoemd bij {genoemd} van de {telbaar} vragen. Hieronder staat "
               f"wat je deze week kan doen om dat te verbeteren, belangrijkste eerst.")

    return {
        "acties": gekozen,
        "kop": kop,
        "rest": rest,
        "toelichting": (
            "We houden het bewust bij hoogstens drie. Een lijst met twaalf verbeterpunten is "
            "hetzelfde als geen lijst, want er wordt niet aan begonnen. Wat hier niet bij "
            "staat is niet onbelangrijk, het komt gewoon een volgende keer aan de beurt."
            + (f" Er staan er nu nog {rest} in de wacht." if rest > 0 else "")
        ),
    }
