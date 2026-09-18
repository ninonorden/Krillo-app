"""De vaste teksten van de openbare pagina's, in het Nederlands en het Engels.

WAAROM DIT ZO IS OPGEZET

Krillo gaat naar meer landen. Dat betekent niet "de site vertalen", want er zijn
twee soorten pagina's met twee verschillende regels:

1. PRODUCTPAGINA'S (homepage, prijzen, methode) staan in de taal van de
   BEZOEKER. Standaard Engels, want daar komt de groei vandaan.

2. INDEXPAGINA'S staan in de taal van het LAND DAT GEMETEN IS. Dat is geen
   smaakkwestie. Een Nederlandse koper vraagt "waar koop ik online speelgoed",
   en op die vraag wordt een Engelse pagina nooit gevonden. De ranglijst van
   Nederland staat dus in het Nederlands, ook als de bezoeker de site verder in
   het Engels leest. Bij het Verenigd Koninkrijk is het andersom.

WAT ER NOOIT GEBEURT: doorsturen op IP-adres. Dat is de klassieke fout waarmee
je jezelf uit Google schrijft. Google haalt de site meestal op vanuit de
Verenigde Staten; stuur je die bezoeker automatisch naar een Engelse pagina, dan
ziet Google de Nederlandse index nooit en verdwijnt precies het verkeer dat je
wil hebben. Elk land heeft dus zijn eigen vaste adres, en het land van de
bezoeker bepaalt alleen wat er VOORGEKOZEN staat.

Een test bewaakt dat elke sleutel in beide talen bestaat en dat geen enkel
sjabloon een sleutel gebruikt die hier niet staat.
"""
import os

# De taal van de productpagina's als er niets anders is opgegeven.
STANDAARD = os.environ.get("STANDAARD_TAAL", "en")

TALEN = ("nl", "en")

# Welke taal bij welk land hoort. De index van een land staat altijd in deze
# taal, ongeacht wat de bezoeker verder leest.
TAAL_VAN_LAND = {
    "nl": "nl", "be": "nl", "de": "de", "uk": "en", "gb": "en",
    "fr": "fr", "us": "en",
}

# De landen zoals ze in de adresbalk staan, met hun naam in beide talen.
LANDEN = {
    "nl": {"nl": "Nederland", "en": "the Netherlands", "vlag": "NL"},
    "be": {"nl": "België", "en": "Belgium", "vlag": "BE"},
    "de": {"nl": "Duitsland", "en": "Germany", "vlag": "DE"},
    "uk": {"nl": "het Verenigd Koninkrijk", "en": "the United Kingdom", "vlag": "UK"},
    "fr": {"nl": "Frankrijk", "en": "France", "vlag": "FR"},
    "us": {"nl": "de Verenigde Staten", "en": "the United States", "vlag": "US"},
}


def landnaam(code, taal="nl"):
    rij = LANDEN.get((code or "").lower())
    if not rij:
        return (code or "").upper()
    return rij.get(taal) or rij.get("nl")


def taal_van_land(code):
    """De taal waarin de index van dit land geschreven staat."""
    return TAAL_VAN_LAND.get((code or "").lower(), "en")


def kies_taal(pad_taal=None, kop_taal=None):
    """Welke taal een productpagina krijgt.

    Volgorde: wat er in het adres staat wint, daarna wat de browser vraagt,
    daarna de standaard. De browser is bewust de zwakste van de drie: hij mag
    voorkiezen, nooit dwingen."""
    if pad_taal in TALEN:
        return pad_taal
    if kop_taal:
        for stuk in kop_taal.split(","):
            code = stuk.split(";")[0].strip().lower()[:2]
            if code in TALEN:
                return code
    return STANDAARD if STANDAARD in TALEN else "en"


def land_uit_kop(kop_taal=None, beschikbaar=None):
    """Welk land er voorgekozen staat in het keuzemenu.

    Alleen een suggestie. De bezoeker kan altijd wisselen, en de pagina waar hij
    op staat verandert er niet door."""
    beschikbaar = [c.lower() for c in (beschikbaar or [])]
    if not beschikbaar:
        return None
    if kop_taal:
        for stuk in kop_taal.split(","):
            code = stuk.split(";")[0].strip().lower()
            # nl-BE wint van nl, want die zegt iets over het land en niet
            # alleen over de taal.
            if "-" in code:
                land = code.split("-")[1]
                if land in beschikbaar:
                    return land
            if code[:2] in beschikbaar:
                return code[:2]
    return beschikbaar[0]


T = {
    "nl": {
        "index_titel": "De Krillo-index: welke webshops noemt AI?",
        "index_omschrijving": ("Per categorie meten we welke webshops door ChatGPT en "
                               "Gemini genoemd en aanbevolen worden. Bekijk de ranglijst "
                               "van jouw categorie."),
        "index_kop": "Welke webshops noemt AI als je iets wil kopen?",
        "index_inleiding": ("Wij stellen per categorie dezelfde koopvragen aan "
                            "AI-assistenten die een koper zou stellen, en kijken welke "
                            "webshops er in de antwoorden staan. Geen mening, geen "
                            "sterren: alleen wat de assistenten echt antwoordden, met de "
                            "datum en de vragen erbij."),
        "index_open": "De index is open",
        "index_open_uitleg": "Elke ranglijst is gratis te lezen. Geen account, geen mail.",
        "markt": "Markt",
        "alle_categorieen": "Alle categorieën",
        "categorieen": "categorieën",
        "winkels_gevolgd": "winkels gevolgd",
        "antwoorden_bewaard": "antwoorden bewaard",
        "live": "LIVE",
        "binnenkort": "BINNENKORT",
        "nog_leeg": ("De eerste categorieën worden op dit moment gemeten. Zodra een "
                     "categorie klaar is verschijnt hij hier."),
        "van_de": "van de",
        # TOEGEVOEGD 18 september 2026. Nino vroeg terecht: er zijn veel meer
        # webshops dan de webshops die wij meten. Staat er kaal "1 van de 24",
        # dan leest een speelgoedwinkelier dat als "1 van alle 24
        # speelgoedwebshops in Nederland", en dat klopt niet: het zijn de 24
        # winkels die WIJ in die categorie meten. Het getal was waar, het label
        # ontbrak. Zeggen waar een noemer over gaat kost een woord.
        "van_de_gemeten": "van de {n} die wij meten",
        "index_dekking": ("Deze ranglijst gaat over de {n} webshops die wij in deze "
                          "categorie meten. Dat zijn niet alle webshops in de markt."),
        "winkels_genoemd": "winkels genoemd",
        "koopvragen": "koopvragen",
        "webshop": "Webshop",
        "genoemd": "Genoemd",
        "aanbevolen": "Aanbevolen",
        "gemeten_op": "Gemeten op",
        "assistenten": "assistenten",
        "vragen_kop": "De vragen die we stelden",
        "vragen_uitleg": ("Alleen de vragen waarin echt om een winkel gevraagd kon "
                          "worden, want alleen die tellen mee."),
        "lezen_kop": "Hoe je dit moet lezen",
        "momentopname_kop": "Het is een momentopname",
        "momentopname": ("AI-assistenten veranderen hun antwoorden. Deze lijst is wat er "
                         "op de meetdatum uitkwam, niet een oordeel over de winkels. We "
                         "meten elke maand opnieuw."),
        "niet_inkopen_kop": "Wat er niet in zit",
        "niet_inkopen": ("Geen betaalde plekken. Een winkel kan zich hier niet inkopen, "
                         "en de volgorde volgt alleen uit de antwoorden."),
        "telbaar_kop": "Waarom niet alle dertig vragen meetellen",
        "telbaar": ("Vraagt iemand naar een merk of naar algemene informatie, dan komt "
                    "daar geen webshop in voor, ook de beste niet. Die vragen laten we "
                    "buiten de telling."),
        "genoemd_uitleg": ("Genoemd is: de webshop stond in het antwoord. Aanbevolen is: "
                           "de assistent raadde hem er duidelijk aan. In een rij staan is "
                           "iets anders dan aangeraden worden, dus dat tellen we apart."),
        "overige": "De overige {n} webshops werden bij geen enkele van deze vragen genoemd.",
        "niemand_genoemd": ("Bij deze meting werd geen enkele webshop uit onze lijst "
                            "genoemd."),
        "cta_kop": "Sta jij hier niet bij?",
        "cta_tekst": ("Doe de gratis check van je webshop. Je ziet meteen of "
                      "AI-assistenten je winkel kunnen vinden en lezen."),
        "cta_knop": "Gratis check",
        "zo_meten_we": "Zo meten we",
        "over_ons": "Over ons",
        "terug_index": "De index",
    },
    "en": {
        "index_titel": "The Krillo Index: which stores does AI name?",
        "index_omschrijving": ("Every month we measure which online stores ChatGPT and "
                               "Gemini name and recommend, category by category. Find "
                               "your category."),
        "index_kop": "When AI picks the shop, who does it name?",
        "index_inleiding": ("We put the same buying questions to AI assistants that a "
                            "buyer would ask, and record which stores appear in the "
                            "answers. No opinion, no stars: only what the assistants "
                            "actually said, with the date and the questions."),
        "index_open": "The index is open",
        "index_open_uitleg": "Every ranking is free to read. No account, no email.",
        "markt": "Market",
        "alle_categorieen": "All categories",
        "categorieen": "categories",
        "winkels_gevolgd": "stores tracked",
        "antwoorden_bewaard": "answers on record",
        "live": "LIVE",
        "binnenkort": "NEXT",
        "nog_leeg": ("The first categories are being measured right now. A category "
                     "appears here as soon as it is done."),
        "van_de": "of",
        # Zie de uitleg bij de Nederlandse versie hierboven.
        "van_de_gemeten": "of {n} we measure",
        "index_dekking": ("This ranking covers the {n} stores we measure in this "
                          "category. That is not every store in the market."),
        "winkels_genoemd": "stores named",
        "koopvragen": "buying questions",
        "webshop": "Store",
        "genoemd": "Named",
        "aanbevolen": "Recommended",
        "gemeten_op": "Measured on",
        "assistenten": "assistants",
        "vragen_kop": "The questions we asked",
        "vragen_uitleg": ("Only the questions that could really name a store, because "
                          "only those count."),
        "lezen_kop": "How to read this",
        "momentopname_kop": "This is a snapshot",
        "momentopname": ("AI assistants change their answers. This list is what came out "
                         "on the date measured, not a judgement about the stores. We "
                         "measure again every month."),
        "niet_inkopen_kop": "What is not in it",
        "niet_inkopen": ("No paid positions. A store cannot buy its way in, and the order "
                         "follows from the answers alone."),
        "telbaar_kop": "Why not all thirty questions count",
        "telbaar": ("If someone asks about a brand or for general information, no store "
                    "appears in the answer, not even the best one. Those questions are "
                    "left out of the count."),
        "genoemd_uitleg": ("Named means the store appeared in the answer. Recommended "
                           "means the assistant clearly advised it. Being in a list is "
                           "not the same as being advised, so we count them separately."),
        "overige": "The other {n} stores were named in none of these questions.",
        "niemand_genoemd": "No store from our list was named in this measurement.",
        "cta_kop": "Not on this list?",
        "cta_tekst": ("Run the free check on your store. You will see straight away "
                      "whether AI assistants can find and read it."),
        "cta_knop": "Free check",
        "zo_meten_we": "How we measure",
        "over_ons": "About us",
        "terug_index": "The index",
    },
}


def teksten(taal="nl"):
    """De teksten van een taal, met terugval op Engels.

    Terugvallen en niet omvallen: een ontbrekende sleutel hoort een lelijke
    pagina te geven en geen storing. De test vangt het ontbreken af voordat het
    ooit live komt."""
    basis = dict(T["en"])
    basis.update(T.get(taal) or {})
    return basis


# ---------------------------------------------------------------------------
# WELKE TAAL EEN BEZOEKER KRIJGT, EN WAAROM DAT AAN HET DOMEIN HANGT
# ---------------------------------------------------------------------------
#
# krillo.nl is Nederlands. krilloai.com is Engels. Zelfde code, zelfde ontwerp,
# alleen andere taal.
#
# Waarom niet alles Engels op krillo.nl: achter de knop zit een Nederlandse
# trechter. De uitslag van de scan, de mails, de facturen, de voorwaarden en de
# omschrijving op het bankafschrift van Mollie zijn Nederlands. Een Engelse
# voorkant op een Nederlandse achterkant is erger dan consequent Nederlands,
# want de bezoeker klikt en valt dan alsnog in het Nederlands.
#
# Waarom niet alles Nederlands: de groei komt uit andere landen, en krilloai.com
# ligt er al. Zo doet dat domein eindelijk iets.
#
# Een ?taal=en achter het adres wint altijd, zodat jij beide kanten kunt
# bekijken zonder een ander domein te openen.
DOMEIN_TAAL = {
    "krillo.nl": "nl",
    "www.krillo.nl": "nl",
    "krilloai.com": "en",
    "www.krilloai.com": "en",
}


def taal_van_domein(host, standaard=None):
    """De taal die bij dit domein hoort.

    Onbekend domein (een testomgeving, een voorbeeldadres van Render) valt terug
    op de standaard. Nooit omvallen: een bezoeker hoort een pagina te krijgen,
    geen foutmelding, ook als het adres nieuw is."""
    kaal = (host or "").split(":")[0].strip().lower()
    if kaal in DOMEIN_TAAL:
        return DOMEIN_TAAL[kaal]
    if kaal.endswith(".nl") or kaal.endswith(".be"):
        return "nl"
    if kaal.endswith(".com") or kaal.endswith(".co.uk"):
        return "en"
    return standaard or STANDAARD
