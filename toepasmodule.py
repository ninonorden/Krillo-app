"""Eén stekker per winkelplatform, zodat "wij doen het" niet alleen voor
Shopify werkt.

Waarom dit bestaat. Het actieplan zegt wat er moet gebeuren, en dat is voor
elke winkel hetzelfde: zet er een vraag-en-antwoordpagina bij, vul de
alt-teksten, schrijf de productteksten uit. Waar je dat doet verschilt per
platform, en dat is precies het stuk dat nu ontbrak. In het werkbriefje stond
"dit pas je aan in de instellingen van je webshop", en dan zit je alsnog een
kwartier te zoeken in een beheerscherm dat je niet kent. Bij twee klanten is
dat vervelend, bij twintig is het de reden dat het niet schaalt.

Wat een stekker is: een platform met daarbij, per taak uit het actieplan, de
weg door het beheerscherm. Meer niet. Geen slimmigheid, geen model dat het ter
plekke verzint, want die verzint een menu dat er niet is en dan klik je op iets
dat niet bestaat. Dit is opgeschreven kennis, en als er iets verandert bij een
platform pas je één regel aan.

En wat een stekker NIET is, zolang dat niet waar is: automatisch. Alleen
Shopify kan Krillo echt zelf in de winkel schrijven, want daar bestaat een app
met toestemming van de winkelier en een knop om alles terug te zetten
(shopify_werk.py). Voor de rest staat hier eerlijk `automatisch: False`. Een
stekker die doet alsof hij schrijft terwijl hij dat niet doet is erger dan geen
stekker: dan denkt iedereen dat het werk gedaan is.

Een nieuw platform erbij is één regel in STEKKERS. Een platform dat later WEL
automatisch kan krijgt er een `motor` bij, en de rest van Krillo hoeft daar
niets van te weten.
"""

# De namen zoals scan_engine.herken_platform ze teruggeeft. Alles wat daar
# uitkomt hoort hier een sleutel te hebben, anders val je terug op het algemene
# verhaal en merkt niemand dat er een platform ontbreekt. Daar staat een test op.
#
# De sleutel is kleingeschreven en zonder spaties, zodat "CCV Shop", "ccvshop"
# en "CCV shop" allemaal dezelfde stekker vinden.

# Wat er in elke winkel moet gebeuren, per taak uit het actieplan. De sleutels
# komen uit actieplan.py (BLOKKADE_ACTIES en BELEMMERING_ACTIES) en veranderen
# niet zomaar: er hangt een test aan die controleert dat elke taak die het
# actieplan kan maken hier ook echt een weg heeft.

_SHOPIFY = {
    "faq": ("Winkel beheren, Online winkel, Pagina's, Pagina toevoegen. Titel "
            "\"Veelgestelde vragen\", tekst erin plakken, Opslaan. Daarna via "
            "Navigatie in het hoofdmenu zetten, anders vindt niemand hem."),
    "productinfo": ("Producten, het product openen, en de omschrijving invullen bij "
                    "Beschrijving. Onder Zoekmachinevermelding staat de korte tekst "
                    "die Google en AI vaak overnemen."),
    "basis": ("Winkel beheren, Online winkel, Voorkeuren. Daar staan de titel en de "
              "omschrijving van de hele winkel."),
    "koppen": ("In de themabewerker: Online winkel, Thema's, Aanpassen. Koppen zet je "
               "per sectie, en let erop dat er maar één hoofdkop per pagina is."),
    "sitemap": ("Die maakt Shopify zelf op /sitemap.xml. Staat hij er niet in Google "
                "Search Console, dien hem daar dan in."),
    "llms_txt": ("Shopify laat geen los bestand in de hoofdmap toe. Zet de inhoud op een "
                 "gewone pagina, bijvoorbeeld /pages/over-onze-winkel, en verwijs daar "
                 "vanuit het menu naartoe."),
    "taal": ("Winkel beheren, Instellingen, Talen. Staat de winkeltaal verkeerd, dan "
             "leest AI de hele winkel in de verkeerde taal."),
    "voorbeeldweergave": ("Online winkel, Voorkeuren, bij Afbeelding voor sociale media. "
                          "Per pagina kan het in de themabewerker."),
    "alt_tekst": ("Producten, product openen, op een afbeelding klikken, dan Alt-tekst "
                  "bewerken. Beschrijf wat er te zien is, niet de zoekterm."),
    "snelheid": ("Online winkel, Thema's, en dan de apps nalopen die meeladen. Elke app "
                 "die je niet gebruikt is winst."),
    "robots": ("Online winkel, Voorkeuren, en zet de vink bij \"Zoekmachines "
               "verhinderen\" uit. Staat er een eigen robots.txt.liquid, kijk daar dan ook."),
    "https": "Shopify regelt het slot zelf. Staat het toch fout, dan zit het in de domeininstellingen.",
    "leesbaarheid": ("Meestal een app of thema dat de pagina pas na het laden opbouwt. Zet "
                     "de apps een voor een uit en kijk wanneer de tekst weer in de bron staat."),
}

_WOOCOMMERCE = {
    "faq": ("WordPress-beheer, Pagina's, Nieuwe pagina. Titel \"Veelgestelde vragen\", "
            "tekst erin, Publiceren. Daarna Weergave, Menu's, en de pagina in het "
            "hoofdmenu zetten."),
    "productinfo": ("Producten, product openen. Het grote tekstvak bovenin is de lange "
                    "beschrijving, het vak \"Korte productomschrijving\" staat eronder. "
                    "Vul ze allebei."),
    "basis": ("Instellingen, Algemeen: sitetitel en slogan. Heb je Yoast of Rank Math, "
              "dan zet je de omschrijving daar."),
    "koppen": ("In de paginabewerker per blok kiezen: Kop 1 voor de titel, Kop 2 voor de "
               "stukken eronder. Niet vet maken en het een kop noemen."),
    "sitemap": ("Yoast of Rank Math maakt hem op /sitemap_index.xml. Zonder zo'n plug-in "
                "maakt WordPress zelf /wp-sitemap.xml."),
    "llms_txt": ("Zet het bestand met FTP of de bestandsbeheerder van je hosting in de "
                 "hoofdmap, naast wp-config.php. Het moet te openen zijn op "
                 "jouwwinkel.nl/llms.txt."),
    "taal": ("Instellingen, Algemeen, Taal van de site. En in WooCommerce, Instellingen, "
             "Algemeen staat het land van de winkel."),
    "voorbeeldweergave": ("Met Yoast of Rank Math per pagina onder Sociaal. Zonder zo'n "
                          "plug-in pakt hij de uitgelichte afbeelding."),
    "alt_tekst": ("Media, afbeelding aanklikken, veld Alternatieve tekst. Doe het daar en "
                  "niet per product, dan geldt het overal waar de afbeelding staat."),
    "snelheid": ("Plug-ins nalopen en uitzetten wat je niet gebruikt. Elke plug-in laadt "
                 "zijn eigen bestanden mee op elke pagina."),
    "robots": ("Instellingen, Lezen, en zet de vink bij \"Zoekmachines ontmoedigen\" uit. "
               "Dit is de bekendste: die vink blijft na een verhuizing vaak aan staan."),
    "https": ("Bij je hosting een certificaat aanzetten, en daarna in Instellingen, "
              "Algemeen beide adressen op https zetten."),
    "leesbaarheid": ("Meestal een pagebuilder of een lazy-load-plug-in die de tekst pas na "
                     "het laden neerzet. Zet ze een voor een uit."),
}

_LIGHTSPEED = {
    "faq": ("Beheer, Content, Pagina's, Nieuwe pagina. Titel \"Veelgestelde vragen\", tekst "
            "erin, en bij Navigatie aanzetten zodat hij in het menu komt."),
    "productinfo": ("Producten, product openen, tabblad Content. Daar staan de korte en de "
                    "lange omschrijving, per taal apart."),
    "basis": ("Instellingen, Webwinkel, Winkelgegevens, en bij Design de titel van de "
              "winkel."),
    "koppen": ("In de tekstbewerker van een pagina met de opmaakkiezer: Kop 1 voor de titel, "
               "Kop 2 eronder."),
    "sitemap": "Lightspeed maakt hem zelf op /sitemap.xml. Dien hem in bij Google Search Console.",
    "llms_txt": ("Lightspeed laat geen los bestand in de hoofdmap toe. Zet de inhoud op een "
                 "gewone pagina en verwijs daarnaartoe vanuit het menu."),
    "taal": ("Instellingen, Talen. Let op dat de hoofdtaal klopt, want Lightspeed toont "
             "anders een halfvertaalde winkel."),
    "voorbeeldweergave": "Bij Design, Instellingen, en per pagina bij de SEO-velden.",
    "alt_tekst": ("Producten, product openen, tabblad Afbeeldingen, en per afbeelding het "
                  "veld Alt-tekst."),
    "snelheid": "Design, en dan de apps nalopen die je via de App Store hebt toegevoegd.",
    "robots": ("Instellingen, Webwinkel, en kijk of de winkel op zichtbaar staat. Staat hij "
               "in onderhoudsmodus, dan komt er geen enkele AI binnen."),
    "https": "Instellingen, Domeinen, en zet het certificaat aan voor het hoofddomein.",
    "leesbaarheid": ("Vaak een thema dat de tekst pas na het laden ophaalt. Wissel tijdelijk "
                     "naar een standaardthema en kijk of het verschil maakt."),
}

_CCVSHOP = {
    "faq": ("Beheer, Website, Pagina's, Pagina toevoegen. Titel \"Veelgestelde vragen\", "
            "tekst erin, en bij Menu's in het hoofdmenu zetten."),
    "productinfo": "Producten, product openen, en het veld Omschrijving invullen.",
    "basis": "Instellingen, Webwinkelgegevens, en bij SEO de titel en omschrijving.",
    "koppen": "In de tekstbewerker van de pagina met de opmaakkiezer.",
    "sitemap": "CCV maakt hem zelf op /sitemap.xml.",
    "llms_txt": ("CCV laat geen los bestand in de hoofdmap toe. Zet de inhoud op een gewone "
                 "pagina en verwijs daarnaartoe."),
    "taal": ("Instellingen, Talen, en kijk of de hoofdtaal van de winkel klopt. Staat die "
             "verkeerd, dan leest AI de hele winkel in de verkeerde taal."),
    "voorbeeldweergave": ("Bij de SEO-velden van de pagina zelf, en voor de hele winkel bij "
                          "Instellingen, Webwinkelgegevens."),
    "alt_tekst": "Producten, product openen, tabblad Afbeeldingen, veld Alt-tekst.",
    "snelheid": "Beheer, Apps, en uitzetten wat je niet gebruikt.",
    "robots": "Instellingen, en kijk of de winkel niet op onderhoud of offline staat.",
    "https": "Instellingen, Domeinnamen, certificaat aanzetten.",
    "leesbaarheid": "Wissel tijdelijk naar een standaardthema en kijk of de tekst dan wel in de bron staat.",
}

# Wat je doet als wij het platform niet kennen of niet herkennen. Bewust geen
# verzonnen menupad: dan klik je op iets dat er niet is en vertrouw je de rest
# ook niet meer.
_ALGEMEEN = {
    "faq": ("Maak een gewone pagina met de kop \"Veelgestelde vragen\", zet de tekst erop en "
            "zet hem in het hoofdmenu. Elk platform kan dit."),
    "productinfo": "Open het product in je beheerscherm en vul de omschrijving.",
    "basis": "In de instellingen van je winkel, bij de titel en de omschrijving van de site.",
    "koppen": "In de tekstbewerker de opmaak op Kop zetten, niet alleen vet maken.",
    "sitemap": "Kijk of jouwwinkel.nl/sitemap.xml bestaat en dien hem in bij Google Search Console.",
    "llms_txt": ("Het bestand moet in de hoofdmap staan en te openen zijn op "
                 "jouwwinkel.nl/llms.txt. Kan dat niet, zet de inhoud dan op een gewone pagina."),
    "taal": "In de instellingen van je winkel, bij taal en land.",
    "voorbeeldweergave": "Bij de SEO- of deelinstellingen van de pagina.",
    "alt_tekst": "Bij de afbeelding zelf, in het veld alt of alternatieve tekst.",
    "snelheid": "Loop de apps en plug-ins na en zet uit wat je niet gebruikt.",
    "robots": ("Zoek in je instellingen naar zoekmachines, zichtbaarheid of onderhoud, en zet "
               "de blokkade uit. Kijk daarna op jouwwinkel.nl/robots.txt."),
    "https": "Bij je hosting of domeinbeheerder een certificaat aanzetten.",
    "leesbaarheid": ("De tekst staat pas na het laden op de pagina. Meestal doet een app of "
                     "thema dat. Zet ze een voor een uit en kijk wanneer het terugkomt."),
}


STEKKERS = {
    # Als enige automatisch: hier bestaat een app met toestemming en een knop om
    # alles terug te zetten. De motor staat in shopify_werk.py.
    "shopify": {"naam": "Shopify", "automatisch": True, "beheer": "Winkel beheren",
                "motor": "shopify_werk", "stappen": _SHOPIFY},
    "woocommerce": {"naam": "WooCommerce", "automatisch": False, "beheer": "WordPress-beheer",
                    "motor": None, "stappen": _WOOCOMMERCE},
    # WordPress zonder WooCommerce is hetzelfde beheerscherm. Dezelfde stappen
    # dus, en geen tweede lijst om uit elkaar te laten lopen.
    "wordpress": {"naam": "WordPress", "automatisch": False, "beheer": "WordPress-beheer",
                  "motor": None, "stappen": _WOOCOMMERCE},
    "lightspeed": {"naam": "Lightspeed", "automatisch": False, "beheer": "Lightspeed-beheer",
                   "motor": None, "stappen": _LIGHTSPEED},
    "ccvshop": {"naam": "CCV Shop", "automatisch": False, "beheer": "CCV-beheer",
                "motor": None, "stappen": _CCVSHOP},
    "magento": {"naam": "Magento", "automatisch": False, "beheer": "Magento-beheer",
                "motor": None, "stappen": _ALGEMEEN},
    "prestashop": {"naam": "PrestaShop", "automatisch": False, "beheer": "PrestaShop-beheer",
                   "motor": None, "stappen": _ALGEMEEN},
    "shopware": {"naam": "Shopware", "automatisch": False, "beheer": "Shopware-beheer",
                 "motor": None, "stappen": _ALGEMEEN},
    "wix": {"naam": "Wix", "automatisch": False, "beheer": "Wix-beheer",
            "motor": None, "stappen": _ALGEMEEN},
    "squarespace": {"naam": "Squarespace", "automatisch": False, "beheer": "Squarespace-beheer",
                    "motor": None, "stappen": _ALGEMEEN},
}

ONBEKEND = {"naam": "onbekend platform", "automatisch": False, "beheer": "je beheerscherm",
            "motor": None, "stappen": _ALGEMEEN}


def _sleutel(platform):
    """"CCV Shop", "ccvshop" en "CCV shop" horen bij dezelfde stekker."""
    if not platform:
        return ""
    return "".join(c for c in str(platform).lower() if c.isalnum())


def stekker(platform):
    """De stekker bij een platform. Altijd een woordenboek, nooit None.

    Onbekend is geen fout: de meeste winkels draaien op iets dat wij niet
    herkennen, en die klant heeft evengoed een werkbriefje nodig."""
    return STEKKERS.get(_sleutel(platform), ONBEKEND)


def stappen_voor(platform, taak_id):
    """De weg door het beheerscherm voor één taak.

    Valt terug op het algemene verhaal, want een taak zonder uitleg is een taak
    waar iemand op vastloopt."""
    if not taak_id:
        return None
    s = stekker(platform)
    return s["stappen"].get(taak_id) or _ALGEMEEN.get(taak_id)


def kan_automatisch(platform):
    """Of Krillo dit platform zelf kan bijwerken, met toestemming van de winkel.

    Nu alleen Shopify. Dit is met opzet een vraag met één antwoord: zodra er
    ergens anders in de code "als het Shopify is" staat, is het de volgende keer
    vergeten."""
    return bool(stekker(platform)["automatisch"])


def verrijk_plan(plan, platform):
    """Zet bij elke actie in het plan de stappen voor dit platform.

    Verandert het plan zelf niet van vorm: er komt één veld bij. Zo kan een
    sjabloon dat er niets van weet gewoon blijven werken."""
    if not plan or not plan.get("acties"):
        return plan
    for actie in plan["acties"]:
        actie["stappen"] = stappen_voor(platform, actie.get("id"))
    return plan


def overzicht():
    """Alle stekkers op een rij, voor de beheerpagina. Gesorteerd met de
    automatische bovenaan, want dat is het verschil dat telt."""
    regels = [
        {"platform": s["naam"], "automatisch": s["automatisch"],
         "taken": len(s["stappen"]), "motor": s["motor"]}
        for s in STEKKERS.values()
    ]
    # Twee sleutels met dezelfde naam kan niet, maar WordPress en WooCommerce
    # delen wel hun stappen. Die blijven allebei staan: het zijn voor een klant
    # twee verschillende antwoorden op de vraag "wat draai ik".
    regels.sort(key=lambda r: (not r["automatisch"], r["platform"].lower()))
    return regels
