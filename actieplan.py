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

# TWEETALIG. Elke vaste tekst staat er twee keer in: de Nederlandse onder
# "titel" en "hoe", de Engelse onder "titel_en" en "hoe_en". De sleutels van de
# acties zelf (robots, https, faq, ...) blijven overal gelijk, want daar hangt
# de bewaarde oplossing per taak aan. Zonder tegenhanger valt alles terug op
# Nederlands, zodat een vergeten vertaling nooit een lege tekst oplevert.
#
# De Engelse routes noemen de Engelse menunamen van Shopify en WordPress. Een
# Amerikaanse winkelier zoekt zich anders suf naar "Winkelinstellingen".

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
        "titel_en": "Let AI crawlers read your site",
        "hoe_en": (
            "The robots.txt file on your site currently says AI crawlers are not welcome. "
            "As long as that line is there, no AI assistant is allowed to read your pages, "
            "so it cannot recommend you either. In Shopify you find this under Online Store, "
            "then Themes, then Edit code, in the file robots.txt.liquid. In WordPress it is "
            "usually in your SEO plugin under Tools. Remove the rules that block GPTBot, "
            "ClaudeBot, PerplexityBot, OAI-SearchBot or Google-Extended."
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
        "titel_en": "Turn on a secure connection",
        "hoe_en": (
            "Your site still runs without https. Browsers warn visitors about that and AI "
            "systems treat such a site as less trustworthy. In Shopify and at most hosting "
            "companies this is one button and it is free. In Shopify you find it under "
            "Settings, then Domains. Ask your host for an SSL certificate if you cannot find it."
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
        "titel_en": "Put your text in the page itself",
        "hoe_en": (
            "There is hardly any text on your page that can be read right away. Your text only "
            "appears after scripts have run, so an AI that fetches your page sees a blank sheet. "
            "Ask whoever built your site to put the main text, product names and descriptions "
            "in the page itself."
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
        "titel_en": "Put questions and answers on your site",
        "hoe_en": (
            "Write down the ten questions customers ask you most, with a short answer for each "
            "one. Sizes, materials, delivery, returns, care. This is the kind of text AI "
            "assistants copy almost word for word most often, because it matches the way people "
            "ask questions."
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
        "titel_en": "Add machine readable product data to your pages",
        "hoe_en": (
            "Your product pages are missing the invisible data (schema.org) a computer needs to "
            "pick up price, stock and reviews reliably. Without it an AI has to guess from your "
            "running text. Most Shopify themes have this built in but switched off; in WordPress "
            "an SEO plugin does it."
        ),
    },
    "basis": {
        "titel": "Maak je paginatitel en omschrijving af",
        "hoe": (
            "De titel en de korte omschrijving van je pagina zijn onvolledig. Dat is letterlijk "
            "het eerste wat een AI van je pagina ziet. Zet er in gewone woorden in wat je "
            "verkoopt en voor wie, zonder trucjes."
        ),
        "titel_en": "Finish your page title and description",
        "hoe_en": (
            "The title and the short description of your page are incomplete. That is literally "
            "the first thing an AI sees of your page. Say in plain words what you sell and who "
            "you sell it to, without tricks."
        ),
    },
    "koppen": {
        "titel": "Breng orde in je koppen",
        "hoe": (
            "Je pagina heeft geen duidelijke koppenstructuur. Eén hoofdkop bovenaan die zegt "
            "waar de pagina over gaat, daaronder tussenkopjes per onderwerp. Zo kan een AI "
            "bepalen wat de kern is en wat bijzaak."
        ),
        "titel_en": "Bring order to your headings",
        "hoe_en": (
            "Your page has no clear heading structure. One main heading at the top that says what "
            "the page is about, and subheadings per topic below it. That lets an AI work out what "
            "is the point and what is a side note."
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
        "titel_en": "Submit a sitemap",
        "hoe_en": (
            "We found no sitemap. That is the list of all your pages. Shopify and WordPress build "
            "it for you; all you have to do is submit it to Google Search Console and Bing "
            "Webmaster Tools. Bing counts extra here, because ChatGPT leans on it when it searches."
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
        "titel_en": "Put an llms.txt on your site",
        "hoe_en": (
            "A small text file in which you explain in a few sentences what you sell and which "
            "pages matter most. To be honest, there is no proof yet that AI assistants do much "
            "with this, so do not expect too much from it. It costs you ten minutes."
        ),
    },
    "taal": {
        "titel": "Leg de taal van je pagina vast",
        "hoe": (
            "In de code van je pagina staat niet in welke taal hij geschreven is. "
            "Daardoor kan een systeem twijfelen voor welke markt je bedoeld bent. "
            "Eén regel in je thema lost dit op."
        ),
        "titel_en": "Set the language of your page",
        "hoe_en": (
            "The code of your page does not say which language it is written in. "
            "That can leave a system unsure which market you are meant for. "
            "One line in your theme fixes this."
        ),
    },
    "voorbeeldweergave": {
        "titel": "Vul de gegevens voor de voorbeeldweergave in",
        "hoe": (
            "Als iemand je link deelt in WhatsApp of op social media, is er geen plaatje en "
            "geen omschrijving. Dat kost je kliks, en die kliks zijn precies wat mensen ergens "
            "over je laat schrijven."
        ),
        "titel_en": "Fill in the details for the link preview",
        "hoe_en": (
            "When someone shares your link in WhatsApp or on social media, there is no image and "
            "no description. That costs you clicks, and those clicks are exactly what gets people "
            "writing about you somewhere."
        ),
    },
    "alt_tekst": {
        "titel": "Beschrijf je afbeeldingen",
        "hoe": (
            "Een deel van je afbeeldingen heeft geen beschrijving. Een AI ziet een plaatje "
            "niet, alleen de tekst eromheen. Beschrijf in een paar woorden wat erop staat."
        ),
        "titel_en": "Describe your images",
        "hoe_en": (
            "Some of your images have no description. An AI does not see a picture, only the text "
            "around it. Describe in a few words what is in it."
        ),
    },
    "snelheid": {
        "titel": "Maak je site sneller",
        "hoe": (
            "Je pagina reageert traag. Dat kost je bezoekers, en systemen die je pagina "
            "ophalen geven soms eerder op. Grote afbeeldingen zijn meestal de oorzaak."
        ),
        "titel_en": "Make your site faster",
        "hoe_en": (
            "Your page is slow to respond. That costs you visitors, and systems that fetch your "
            "page sometimes give up sooner. Large images are usually the cause."
        ),
    },
}


def _uit(sjabloon, sleutel, taal):
    """De tekst in de gevraagde taal, met Nederlands als vangnet.

    Ontbreekt de Engelse tegenhanger, dan komt de Nederlandse eruit. Een halve
    zin of een lege tekst op het scherm van een klant is erger dan een zin in
    de verkeerde taal."""
    if taal == "en":
        return sjabloon.get(sleutel + "_en") or sjabloon[sleutel]
    return sjabloon[sleutel]


# Het merkje dat bij een actie op het scherm komt. "soort" blijft altijd
# "feit" of "vermoeden", want daar rekent de rest van Krillo mee en daar hangen
# de opmaakregels aan. "merkje" is puur het woord dat de klant leest.
MERKJES = {
    "nl": {"feit": "gemeten", "vermoeden": "ons oordeel"},
    "en": {"feit": "measured", "vermoeden": "our view"},
}

# Waar het merkje voor staat, in een zin. Komt als tooltip op het merkje te
# staan.
#
# "feit" en "vermoeden" stonden er eerst kaal bij en dat riep vooral de vraag op
# waarom iets het een of het ander is. Het verschil is wel degelijk belangrijk:
# bij het ene hebben wij het echt op je site of in het antwoord van de AI gezien,
# bij het andere denken wij dat het helpt maar kunnen wij dat niet aantonen. Als
# je dat verschil niet uitlegt, lees je alles als even hard, en dan klopt het
# eerste type niet meer.
MERKJE_UITLEG = {
    "nl": {
        "feit": "Dit hebben wij zelf gezien op je site of in het antwoord van de AI.",
        "vermoeden": ("Wij denken dat dit helpt, maar wij kunnen niet aantonen dat "
                      "je hierdoor vaker genoemd wordt."),
    },
    "en": {
        "feit": "We saw this ourselves on your site or in the AI answer.",
        "vermoeden": ("We think this helps, but we cannot prove it gets you "
                      "mentioned more often."),
    },
}


def _actie(taak_id, soort, titel, waarom, hoe, links=None, taal="nl"):
    """Elke actie heeft een vast kenmerk (taak_id), zodat de kant-en-klare
    oplossing die erbij hoort eenmalig geschreven en daarna bewaard kan worden.
    Zonder zo'n kenmerk zou dezelfde taak elke week een nieuwe tekst krijgen."""
    return {"id": taak_id, "soort": soort,
            "merkje": MERKJES.get(taal, MERKJES["nl"]).get(soort, soort),
            "merkje_uitleg": MERKJE_UITLEG.get(taal, MERKJE_UITLEG["nl"]).get(soort, ""),
            "titel": titel, "waarom": waarom,
            "hoe": hoe, "links": links or [], "oplossing": None, "waar": None}


def _blokkade_acties(verklaring, taal="nl"):
    """Stap 1: wat AI aantoonbaar tegenhoudt. Altijd bovenaan."""
    if taal == "en":
        waarom = ("This demonstrably stops AI. As long as it is there the rest has little "
                  "point, because an AI assistant cannot read your site and so cannot "
                  "recommend it either.")
    else:
        waarom = ("Dit houdt AI aantoonbaar tegen. Zolang dit er staat heeft de rest weinig zin, "
                  "want dan kan een AI-assistent je site niet lezen en dus ook niet aanbevelen.")
    acties = []
    for b in (verklaring or {}).get("blokkades") or []:
        sjabloon = BLOKKADE_ACTIES.get(b.get("id"))
        if not sjabloon:
            continue
        acties.append(_actie(
            b.get("id"),
            "feit",
            _uit(sjabloon, "titel", taal),
            waarom,
            _uit(sjabloon, "hoe", taal),
            taal=taal,
        ))
    return acties


def _onjuistheid_acties(controle, winkelnaam, taal="nl"):
    """Stap 2: AI vertelt iets over je winkel dat niet klopt.

    Dit is de meest onderschatte actie in de hele lijst. Een winkel die weinig
    genoemd wordt mist omzet, maar een winkel waarover een verkeerde levertijd
    of een verkeerd retourbeleid rondgaat, verliest klanten die al bijna
    besloten hadden."""
    fouten = [f for f in (controle or {}).get("fouten") or [] if f.get("uitspraak")]
    if not fouten:
        return []

    naam = winkelnaam or ("your store" if taal == "en" else "je winkel")
    voorbeelden = []
    for f in fouten[:3]:
        zegt = (f.get("uitspraak") or "").strip()
        site = (f.get("watzegtdesite") or "").strip()
        if taal == "en":
            voorbeelden.append(f'AI says: "{zegt}"'
                               + (f' Your site says: "{site}"' if site else ""))
        else:
            voorbeelden.append(f'AI zegt: "{zegt}"'
                               + (f' Op je site staat: "{site}"' if site else ""))

    aantal = len(fouten)
    # Het kenmerk hangt aan de uitspraken zelf. Verandert er wat AI fout zegt,
    # dan hoort daar een nieuwe tekst bij. Zou het kenmerk alleen
    # "onjuistheden" zijn, dan bleef de tekst van vorige maand staan bij een
    # heel andere fout, en dat is erger dan geen tekst.
    kenmerk = "onjuistheden-" + hashlib.sha1(
        "|".join(sorted((f.get("uitspraak") or "") for f in fouten)).encode("utf-8")
    ).hexdigest()[:10]

    if taal == "en":
        titel = "Put right what AI gets wrong about you"
        waarom = (f"We found {aantal} {'statement' if aantal == 1 else 'statements'} about {naam} "
                  f"that {'does' if aantal == 1 else 'do'} not match what your site says. "
                  f"This weighs more than it looks: someone who reads this and comes by finds "
                  f"something other than expected. That is a customer who had almost decided.")
        hoe = ("Put the right answer clearly and in plain sentences on your own site, ideally on "
               "a questions and answers page. AI models build part of their picture of your store "
               "from your own pages, so that is where the correction starts. What is going wrong "
               "now:\n\n"
               + "\n".join(f"- {v}" for v in voorbeelden))
    else:
        titel = "Zet recht wat AI verkeerd over je vertelt"
        waarom = (f"We vonden {aantal} {'uitspraak' if aantal == 1 else 'uitspraken'} over {naam} die "
                  f"niet {'klopt' if aantal == 1 else 'kloppen'} met wat er op je site staat. "
                  f"Dit weegt zwaarder dan het lijkt: iemand die dit leest en langskomt, vindt iets "
                  f"anders dan hij verwachtte. Dat is een klant die al bijna besloten had.")
        hoe = ("Zet het juiste antwoord duidelijk en in gewone zinnen op je eigen site, het liefst "
               "op een vraag-en-antwoordpagina. AI-modellen halen hun beeld van je winkel deels bij "
               "je eigen pagina's op, dus daar begint de correctie. Wat er nu misgaat:\n\n"
               + "\n".join(f"- {v}" for v in voorbeelden))

    return [_actie(kenmerk, "feit", titel, waarom, hoe, taal=taal)]


def _bronnen_acties(bronnen, winkelnaam, taal="nl"):
    """Stap 3: de externe plekken waar je concurrent staat en jij niet.

    De grootste hefboom, want het meeste van wat AI over een winkel zegt komt
    van buiten die winkel. En het mooiste eraan: deze pagina's bestaan al."""
    gemist = (bronnen or {}).get("gemiste_paginas") or []
    if not gemist:
        return []

    naam = winkelnaam or ("your store" if taal == "en" else "je winkel")
    top = gemist[:4]
    namen = sorted({n for g in top for n in (g.get("concurrenten") or [])})
    if namen:
        wie = ", ".join(namen[:4])
    else:
        wie = "stores AI does mention" if taal == "en" else "winkels die AI wel noemt"

    # Tel de plekken die we ook ECHT laten zien. Dit stond op het totaal uit
    # de bronanalyse, dus bij dertig gemiste plekken las de klant "zorg dat je
    # op deze 30 plekken komt te staan" met vier links eronder.
    aantal = len(top)
    if taal == "en":
        plekken = "place" if aantal == 1 else "places"
        titel = f"Get {naam} listed on {'this' if aantal == 1 else 'these'} {aantal} {plekken}"
        waarom = (f"We put your shopping questions into an ordinary search engine and went "
                  f"through the pages that came back. On {'this' if aantal == 1 else 'these'} "
                  f"{plekken} {wie} are listed and {naam} is not. This is the biggest lever you "
                  f"have: most of what AI says about a store does not come from that store "
                  f"itself, but from what is written about it elsewhere. And these pages already "
                  f"exist, you do not have to make them.")
        hoe = ("Open the pages below and look at how the stores mentioned got there. Usually it "
               "is an editor who put a list together, or a conversation where someone gave a tip. "
               "Look on the page for contact, editorial or tips, and send a short message: who "
               "you are, what you sell, and what your store has that the listed stores do not. "
               "That last part is the only thing that counts, because without a reason to add you "
               "nothing happens. On a forum or a question thread you can answer yourself, but be "
               "open about the fact that it is your own store.")
    else:
        plekken = "plek" if aantal == 1 else "plekken"
        titel = f"Zorg dat {naam} op deze {aantal} {plekken} komt te staan"
        waarom = (f"We hebben jouw koopvragen in een gewone zoekmachine gezet en de pagina's nagelopen "
                  f"die daaruit kwamen. Op deze {plekken} staan {wie} wel, en {naam} niet. Dit is de "
                  f"grootste hefboom die je hebt: het meeste van wat AI over een winkel zegt komt niet "
                  f"van die winkel zelf, maar van wat er elders over geschreven staat. En deze pagina's "
                  f"bestaan al, je hoeft ze niet te maken.")
        hoe = ("Open de pagina's hieronder en kijk hoe de genoemde winkels er terechtgekomen zijn. "
               "Meestal is dat een redactie die een lijstje samenstelde, of een gesprek waar iemand "
               "een tip gaf. Zoek op de pagina naar contact, redactie of tips, en stuur een kort "
               "bericht: wie je bent, wat je verkoopt, en wat jouw winkel heeft dat de genoemde "
               "winkels niet hebben. Dat laatste is het enige dat telt, want zonder reden om je toe "
               "te voegen gebeurt er niets. Bij een forum of een vraagdraadje kan je zelf antwoorden, "
               "maar wees dan open over het feit dat het je eigen winkel is.")

    return [_actie(
        "bronnen",
        "feit",
        titel,
        waarom,
        hoe,
        links=[{"url": g["url"], "titel": g.get("titel") or g.get("domein"),
                "domein": g.get("domein")} for g in top],
        taal=taal,
    )]


def _belemmering_acties(verklaring, taal="nl"):
    """Stap 4: de leesbaarheid van je site. Nuttig, maar het blijft een
    vermoeden en het gaat over het kleinste deel van het verhaal."""
    aanwezig = {b.get("id") for b in (verklaring or {}).get("belemmeringen") or []}
    if taal == "en":
        waarom = ("This makes your site easier for AI to read. Whether it gets you mentioned more "
                  "often we do not know, so we do not claim it. It is cheap and it is in your own "
                  "hands.")
    else:
        waarom = ("Dit maakt je site beter leesbaar voor AI. Of je hierdoor vaker genoemd wordt "
                  "weten we niet, en dat beweren we dus ook niet. Het is wel goedkoop en je hebt "
                  "het zelf in de hand.")
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
            _uit(sjabloon, "titel", taal),
            waarom,
            _uit(sjabloon, "hoe", taal),
            taal=taal,
        ))
    return acties


def _plan_en(gekozen, rest, genoemd, telbaar, naam, bronnen):
    """De Engelse tegenhanger van de slotzinnen in maak_actieplan.

    Apart gezet zodat de Nederlandse tekst er woord voor woord bij blijft staan
    zoals hij was. De keuze en de volgorde zijn dan al gemaakt: hier komen
    alleen nog de zinnen omheen."""
    if not gekozen:
        # Zelfde voorbehoud als in het Nederlands: niet beweren dat we plekken
        # nagekeken hebben als de bronanalyse niets opgeleverd heeft.
        bronnen_gedaan = bool(bronnen and bronnen.get("paginas"))
        if bronnen_gedaan:
            kop = (f"{naam} is mentioned in {genoemd} of the {telbaar} questions, and right now we "
                   f"find nothing to fix. Your site is in order and you are listed on the places "
                   f"we checked. Keep it that way and watch what your competitors do.")
        else:
            kop = (f"{naam} is mentioned in {genoemd} of the {telbaar} questions. There are no open "
                   f"points on your site. We could not check any outside pages this round, so we "
                   f"cannot say anything about the places beyond your own site right now. Back "
                   f"next week.")
    elif genoemd == 0:
        kop = (f"{naam} was not mentioned in a single one of the {telbaar} questions this round. "
               f"Below is what you can do about it, most important first.")
    else:
        kop = (f"{naam} is mentioned in {genoemd} of the {telbaar} questions. Below is what you can "
               f"do this week to improve that, most important first.")

    return {
        "acties": gekozen,
        "kop": kop,
        "rest": rest,
        "toelichting": (
            "We deliberately keep it to three at most. A list of twelve points is the same as no "
            "list, because nobody starts on it. What is not here is not unimportant, it simply "
            "comes up next time."
            + (f" There {'is' if rest == 1 else 'are'} {rest} waiting." if rest > 0 else "")
        ),
    }


def maak_actieplan(verklaring=None, klantbeeld=None, bronnen=None, controle=None,
                   winkelnaam=None, maximum=None, taal="nl"):
    """Zet alles wat we van een winkel weten om in hoogstens drie acties.

    Krijgt de uitkomsten van de andere onderdelen en kiest daaruit. Rekent
    zelf niets uit en vraagt niets aan een AI: het is puur een volgorde. Dat is
    met opzet, want dezelfde meting hoort altijd hetzelfde advies te geven.

    taal is "nl" of "en". Alles wat niet "en" is wordt Nederlands, want dat is
    wat Krillo altijd al deed en wat voor alle bestaande klanten klopt. De
    volgorde, de kenmerken en het maximum zijn in beide talen precies gelijk:
    alleen de woorden veranderen.

    Geeft None terug als er nog niet gemeten is. Dan is er niets te adviseren
    en dat is beter dan iets verzinnen."""
    maximum = maximum or MAX_ACTIES
    taal = "en" if taal == "en" else "nl"

    if not klantbeeld or not klantbeeld.get("telbaar"):
        return None

    alles = (
        _blokkade_acties(verklaring, taal)
        + _onjuistheid_acties(controle, winkelnaam, taal)
        + _bronnen_acties(bronnen, winkelnaam, taal)
        + _belemmering_acties(verklaring, taal)
    )

    gekozen = alles[:maximum]
    rest = len(alles) - len(gekozen)

    genoemd = klantbeeld.get("genoemd") or 0
    telbaar = klantbeeld.get("telbaar") or 0
    naam = winkelnaam or ("Your store" if taal == "en" else "Je winkel")

    if taal == "en":
        return _plan_en(gekozen, rest, genoemd, telbaar, naam, bronnen)

    if not gekozen:
        # BELANGRIJK: niet beweren dat we plekken nagekeken hebben als de
        # bronanalyse niets opgeleverd heeft. Die geeft ook een lege uitkomst
        # als de zoeksleutel ontbreekt of de zoekmachine eruit lag, en dan las
        # een klant die bij nul van de 22 vragen genoemd werd: "je site is in
        # orde en op de plekken die we nakeken sta je erbij". Er was dan geen
        # enkele plek nagekeken.
        bronnen_gedaan = bool(bronnen and bronnen.get("paginas"))
        if bronnen_gedaan:
            kop = (f"{naam} wordt genoemd bij {genoemd} van de {telbaar} vragen, en we vinden op "
                   f"dit moment niets om aan te pakken. Je site is in orde en op de plekken die "
                   f"we nakeken sta je erbij. Houd het zo en let vooral op wat concurrenten doen.")
        else:
            kop = (f"{naam} wordt genoemd bij {genoemd} van de {telbaar} vragen. Er staan geen "
                   f"verbeterpunten op je site open. We hebben deze ronde geen externe pagina's "
                   f"kunnen nakijken, dus over de plekken buiten je site kunnen we nu niets "
                   f"zeggen. Volgende week weer.")
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
