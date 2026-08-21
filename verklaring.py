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


def maak_verklaring(checks, klantbeeld):
    """Zet de scanuitkomst en de meting naast elkaar.

    checks: de lijst uit de laatste scan. klantbeeld: de uitkomst van
    beoordeling.klantbeeld(), of None als er nog niet gemeten is.

    Geeft terug: blokkades (feit), belemmeringen (vermoeden), en een conclusie
    in gewone taal die eerlijk is over wat we wel en niet weten."""
    checks = checks or []
    problemen = {c["id"] for c in checks if c.get("status") == "probleem"}
    half = {c["id"] for c in checks if c.get("status") == "deels"}

    blokkades = [
        {"id": id_, "tekst": tekst, "soort": "feit"}
        for id_, tekst in BLOKKADES.items() if id_ in problemen
    ]
    belemmeringen = [
        {"id": id_, "tekst": tekst, "soort": "vermoeden"}
        for id_, tekst in BELEMMERINGEN.items() if id_ in problemen or id_ in half
    ]

    if klantbeeld is None or not klantbeeld.get("telbaar"):
        return {
            "blokkades": blokkades,
            "belemmeringen": belemmeringen,
            "conclusie": (
                "Er is nog niet gemeten of AI je noemt, dus we kunnen deze bevindingen nog "
                "niet aan een uitkomst koppelen. Zodra de eerste meting binnen is, staat "
                "hier wat er wel en niet aan je site ligt."
            ),
            "site_is_knelpunt": bool(blokkades),
        }

    telbaar = klantbeeld["telbaar"]
    genoemd = klantbeeld["genoemd"]
    aandeel = genoemd / telbaar if telbaar else 0

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
