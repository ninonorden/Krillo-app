"""
Krillo - fase 5 stap 8: de dertien checks worden de verklaring.

De checks waren tot nu toe een los lijstje. Hier worden ze het antwoord op de
vraag die de klant echt heeft: waarom word ik wel of niet genoemd?

Maar met een grens die we niet overschrijden. Uit het onderzoek dat aan Krillo
ten grondslag ligt: ongeveer 85 procent van wat AI over een merk zegt komt uit
externe bronnen, en maar 13 procent van het eigen domein. Deze dertien checks
meten precies dat kleine deel. Zeggen "dit veroorzaakt dat je niet genoemd
wordt" is dus een claim die we niet kunnen waarmaken.

Daarom splitsen we alles in twee soorten, en dat staat er ook bij:

- FEIT. Aantoonbaar, gemeten op de site zelf. Een robots.txt die AI-robots
  weert is geen vermoeden, dat staat er gewoon. Zonder https ook.
- VERMOEDEN. Ontbrekende schema.org of een lege FAQ maken je slechter
  leesbaar. Dat het daardoor komt dat je niet genoemd wordt, weten we niet.

En het eerlijkste onderdeel: staat de site goed en word je toch weinig genoemd,
dan zeggen we dat de site niet je knelpunt is. Dan ligt het aan wat er buiten je
site over je geschreven wordt. Dat is precies het advies dat een klant nergens
anders krijgt, en het is beter dan vier technische puntjes aanwijzen die niets
gaan veranderen.
"""

# TWEETALIG, op dezelfde manier als in actieplan.py. Elke vaste tekst staat er
# twee keer in: de Nederlandse in BLOKKADES en BELEMMERINGEN, de Engelse in
# BLOKKADES_EN en BELEMMERINGEN_EN. De sleutels (robots, https, faq, ...) zijn
# in beide talen precies gelijk, want daar hangt de rest van Krillo aan: het
# actieplan zoekt zijn acties op diezelfde sleutel op. Ontbreekt een Engelse
# tegenhanger, dan komt de Nederlandse eruit. Een lege tekst op het scherm van
# een klant is erger dan een zin in de verkeerde taal.

# Deze drie zijn harde blokkades: als ze misgaan, kan een AI de site
# aantoonbaar slechter of niet lezen. Dat is een feit, geen inschatting.
BLOKKADES = {
    "robots": "AI-robots worden geweerd in je robots.txt. Ze mogen je site dus niet lezen, "
              "hoe goed de rest ook staat. Dit is het enige punt dat je met zekerheid tegenhoudt.",
    "https": "Je site heeft geen beveiligde verbinding (https). Browsers en AI-modellen "
             "vertrouwen onbeveiligde sites steeds minder.",
    "leesbaarheid": "Er staat nauwelijks direct leesbare tekst op de pagina. Verschijnt je "
                    "content pas nadat scripts zijn uitgevoerd, dan ziet een AI een lege pagina.",
}

# De rest maakt je beter leesbaar. Of het uitmaakt voor of je genoemd wordt,
# weten we niet, en dat zeggen we er ook bij.
BELEMMERINGEN = {
    "productinfo": "Er staat geen machine-leesbare informatie (schema.org) op de pagina. "
                   "Daarmee kan AI je gegevens minder betrouwbaar overnemen.",
    "faq": "Er staat geen vraag-en-antwoord-inhoud op je site. Dat is het soort tekst dat AI "
           "het vaakst letterlijk overneemt.",
    "basis": "Je titel of omschrijving is onvolledig. Dat is het eerste wat een AI van je "
             "pagina ziet.",
    "koppen": "De koppenstructuur is onduidelijk. Daardoor is lastiger te bepalen waar de "
              "pagina over gaat.",
    "sitemap": "Er is geen sitemap gevonden. Daarmee is minder duidelijk welke pagina's je hebt.",
    "llms_txt": "Er is geen llms.txt gevonden. Daarin kan je zelf uitleggen wat je verkoopt.",
    "taal": "De taal van de pagina is niet vastgelegd in de code.",
    "voorbeeldweergave": "De gegevens voor de voorbeeldweergave (Open Graph) ontbreken.",
    "alt_tekst": "Een deel van je afbeeldingen heeft geen beschrijving.",
    "snelheid": "De pagina reageert traag.",
}

BLOKKADES_EN = {
    "robots": "Your robots.txt keeps AI crawlers out. They are not allowed to read your site, "
              "however good the rest of it is. This is the only point that holds you back for "
              "certain.",
    "https": "Your site has no secure connection (https). Browsers and AI models trust "
             "unsecured sites less and less.",
    "leesbaarheid": "There is hardly any text on the page that can be read right away. If your "
                    "content only appears after scripts have run, an AI sees an empty page.",
}

BELEMMERINGEN_EN = {
    "productinfo": "There is no machine readable information (schema.org) on the page. That "
                   "makes it harder for AI to take over your details reliably.",
    "faq": "There are no questions and answers on your site. That is the kind of text AI copies "
           "most often, close to word for word.",
    "basis": "Your page title or description is incomplete. That is the first thing an AI sees "
             "of your page.",
    "koppen": "The heading structure is unclear. That makes it harder to work out what the page "
              "is about.",
    "sitemap": "No sitemap was found. That makes it less clear which pages you have.",
    "llms_txt": "No llms.txt was found. In that file you can explain yourself what you sell.",
    "taal": "The language of the page is not set in the code.",
    "voorbeeldweergave": "The details for the link preview (Open Graph) are missing.",
    "alt_tekst": "Some of your images have no description.",
    "snelheid": "The page is slow to respond.",
}


def _teksten(taal):
    """De twee woordenboeken in de gevraagde taal, Nederlands als vangnet."""
    if taal == "en":
        return BLOKKADES_EN, BELEMMERINGEN_EN
    return BLOKKADES, BELEMMERINGEN


def _knelpunt(aandeel, blokkades, belemmeringen):
    """Of de site zelf het knelpunt is. Staat los van de taal: dit is een
    uitkomst van de meting en die hoort in beide talen gelijk te zijn."""
    if blokkades:
        return True
    if aandeel < 0.67:
        return bool(belemmeringen)
    return False


def _conclusie_en(genoemd, telbaar, aandeel, blokkades, belemmeringen):
    """De Engelse tegenhanger van de conclusie in maak_verklaring.

    Dezelfde grenzen en dezelfde volgorde, alleen andere woorden. Wat hier
    staat is met opzet net zo voorzichtig als het Nederlands: de site is het
    kleinste deel van het verhaal en dat mogen we niet groter maken."""
    if blokkades:
        return (
            f"You are mentioned in {genoemd} of the {telbaar} questions. There is something on "
            f"your site that demonstrably holds AI back, and that is what you fix first. As long "
            f"as it is there, the rest has little effect."
        )
    if aandeel < 0.34:
        if belemmeringen:
            return (
                f"You are mentioned in {genoemd} of the {telbaar} questions. There are no hard "
                f"blocks on your site, but there is something to improve in how readable it is. "
                f"Be honest with yourself: that probably does not explain everything. Research "
                f"shows that most of what AI says about a store comes from outside sources, not "
                f"from the store itself. Think of comparison sites, articles, reviews and "
                f"forums. That is where most of the gain is here."
            )
        return (
            f"You are mentioned in {genoemd} of the {telbaar} questions, while your site is "
            f"technically in order. So your site is not the bottleneck here. That AI rarely "
            f"mentions you is almost certainly because there is little to find about you outside "
            f"your own site. Comparison sites, articles, reviews and forums weigh heavier than "
            f"your own pages. More work on your site is not going to solve this."
        )
    if aandeel < 0.67:
        return (
            f"You are mentioned in {genoemd} of the {telbaar} questions. That is a reasonable "
            f"base. "
            + ("There is still something to gain in how readable your site is, and that is the "
               "cheapest thing you can do."
               if belemmeringen else
               "Your site is in order, so the next step is outside it: making sure more gets "
               "written about you.")
        )
    return (
        f"You are mentioned in {genoemd} of the {telbaar} questions. That is strong. "
        + ("There are still a few points open. They are not the cause of your position, but "
           "clearing them up makes you less vulnerable if something changes."
           if belemmeringen else
           "Nothing is in the way. Keep it like this and watch what competitors do.")
    )


def maak_verklaring(checks, klantbeeld, taal="nl"):
    """Zet de scanuitkomst en de meting naast elkaar.

    checks: de lijst uit de laatste scan. klantbeeld: de uitkomst van
    beoordeling.klantbeeld(), of None als er nog niet gemeten is.

    taal is "nl" of "en". Alles wat niet "en" is wordt Nederlands, want dat is
    wat Krillo altijd al deed en wat voor alle bestaande klanten klopt. De
    sleutels, de grenzen en site_is_knelpunt zijn in beide talen precies gelijk:
    alleen de woorden veranderen.

    Geeft terug: blokkades (feit), belemmeringen (vermoeden), en een conclusie
    in gewone taal die eerlijk is over wat we wel en niet weten."""
    checks = checks or []
    taal = "en" if taal == "en" else "nl"
    blokkade_teksten, belemmering_teksten = _teksten(taal)
    problemen = {c["id"] for c in checks if c.get("status") == "probleem"}
    half = {c["id"] for c in checks if c.get("status") == "deels"}

    blokkades = [
        {"id": id_, "tekst": tekst, "soort": "feit"}
        for id_, tekst in blokkade_teksten.items() if id_ in problemen
    ]
    belemmeringen = [
        {"id": id_, "tekst": tekst, "soort": "vermoeden"}
        for id_, tekst in belemmering_teksten.items() if id_ in problemen or id_ in half
    ]

    if klantbeeld is None or not klantbeeld.get("telbaar"):
        if taal == "en":
            nog_niet = (
                "We have not measured yet whether AI mentions you, so we cannot tie these "
                "findings to an outcome. As soon as the first measurement is in, this is where "
                "you read what is down to your site and what is not."
            )
        else:
            nog_niet = (
                "Er is nog niet gemeten of AI je noemt, dus we kunnen deze bevindingen nog "
                "niet aan een uitkomst koppelen. Zodra de eerste meting binnen is, staat "
                "hier wat er wel en niet aan je site ligt."
            )
        return {
            "blokkades": blokkades,
            "belemmeringen": belemmeringen,
            "conclusie": nog_niet,
            "site_is_knelpunt": bool(blokkades),
        }

    telbaar = klantbeeld["telbaar"]
    genoemd = klantbeeld["genoemd"]
    aandeel = genoemd / telbaar if telbaar else 0

    if taal == "en":
        return {
            "blokkades": blokkades,
            "belemmeringen": belemmeringen,
            "conclusie": _conclusie_en(genoemd, telbaar, aandeel, blokkades, belemmeringen),
            "site_is_knelpunt": _knelpunt(aandeel, blokkades, belemmeringen),
        }

    if blokkades:
        conclusie = (
            f"Je wordt genoemd bij {genoemd} van de {telbaar} vragen. Er staat iets op je site "
            f"dat AI aantoonbaar tegenhoudt, en dat los je als eerste op. Zolang dat er staat, "
            f"heeft de rest weinig zin."
        )
        site_is_knelpunt = True
    elif aandeel < 0.34:
        if belemmeringen:
            conclusie = (
                f"Je wordt genoemd bij {genoemd} van de {telbaar} vragen. Er zijn geen harde "
                f"blokkades op je site, maar er is wel wat te verbeteren aan de leesbaarheid. "
                f"Wees eerlijk tegen jezelf: dat verklaart waarschijnlijk niet alles. Onderzoek "
                f"laat zien dat het grootste deel van wat AI over een winkel zegt uit externe "
                f"bronnen komt, niet van de winkel zelf. Denk aan vergelijkingssites, "
                f"artikelen, reviews en fora. Daar valt hier de meeste winst te halen."
            )
        else:
            conclusie = (
                f"Je wordt genoemd bij {genoemd} van de {telbaar} vragen, terwijl je site "
                f"technisch in orde is. Je site is hier dus niet het knelpunt. Dat AI je weinig "
                f"noemt komt vrijwel zeker doordat er buiten je site weinig over je te vinden "
                f"is. Vergelijkingssites, artikelen, reviews en fora wegen daarin zwaarder dan "
                f"je eigen pagina's. Meer sleutelen aan je site gaat dit niet oplossen."
            )
        site_is_knelpunt = bool(belemmeringen)
    elif aandeel < 0.67:
        conclusie = (
            f"Je wordt genoemd bij {genoemd} van de {telbaar} vragen. Dat is een redelijke "
            f"basis. "
            + (f"Er is nog wat te winnen aan de leesbaarheid van je site, en dat is het "
               f"goedkoopste wat je kan doen."
               if belemmeringen else
               "Je site is in orde, dus de volgende stap ligt buiten je site: zorgen dat er "
               "meer over je geschreven wordt.")
        )
        site_is_knelpunt = bool(belemmeringen)
    else:
        conclusie = (
            f"Je wordt genoemd bij {genoemd} van de {telbaar} vragen. Dat is sterk. "
            + (f"Er staan nog wat verbeterpunten open. Die veroorzaken je positie niet, maar "
               f"ze wegwerken maakt je minder kwetsbaar als er iets verandert."
               if belemmeringen else
               "Er staat niets in de weg. Houd het zo en let vooral op wat concurrenten doen.")
        )
        site_is_knelpunt = False

    return {
        "blokkades": blokkades,
        "belemmeringen": belemmeringen,
        "conclusie": conclusie,
        "site_is_knelpunt": site_is_knelpunt,
    }
