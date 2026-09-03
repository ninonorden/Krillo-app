"""
Krillo - in welke taal en voor welk land meten we deze winkel?

Waarom dit bestaat: Krillo was van binnen Nederlands. De koopvragen werden
letterlijk in het Nederlands geschreven en er stond in de opdracht dat het om
Nederlandse en Belgische webshops ging. Dat werkt prima zolang alle klanten
Nederlands zijn, maar zodra er via de Shopify App Store een Amerikaanse winkel
binnenkomt krijgt die Nederlandse vragen over Nederlandse webshops terug.

Dat is niet een beetje jammer maar gevaarlijk: een nieuwe app leeft van zijn
eerste beoordelingen, en een meting die niet klopt kost je die meteen.

Shopify vertelt ons bij het installeren zowel de taal als het land van de
winkel. Dit bestand zet dat om in iets waar de rest van Krillo mee kan werken.

BEWUST een korte lijst en geen volledige tabel van de wereld. Elke taal die
hier in staat is er een waarvan we kunnen nakijken of de meting klopt. Staat
een taal er niet in, dan vallen we terug op Engels, want dat is altijd beter
dan een winkel in Sao Paulo vragen stellen in het Nederlands.
"""

# Taalcode uit Shopify (primary_locale, bijvoorbeeld "nl" of "en-US") naar de
# naam van die taal, geschreven zoals we hem in de opdracht aan het model
# zetten.
TALEN = {
    "nl": "Nederlands",
    "en": "English",
    "de": "Deutsch",
    "fr": "français",
    "es": "español",
    "it": "italiano",
    "da": "dansk",
    "sv": "svenska",
    "nb": "norsk",
    "no": "norsk",
    "fi": "suomi",
    "pt": "português",
    "pl": "polski",
}

# Landcode naar de naam van het land zoals een koper hem zou typen, in de taal
# van dat land. "welke Nederlandse webshop" en "which UK webshop".
LANDEN = {
    "NL": "Nederlandse",
    "BE": "Belgische",
    "DE": "deutsche",
    "AT": "österreichische",
    "FR": "française",
    "ES": "española",
    "IT": "italiana",
    "GB": "UK",
    "IE": "Irish",
    "US": "US",
    "CA": "Canadian",
    "AU": "Australian",
    "NZ": "New Zealand",
    "DK": "danske",
    "SE": "svenska",
    "NO": "norske",
    "FI": "suomalainen",
    "PT": "portuguesa",
    "PL": "polskie",
}

STANDAARD_TAAL = "nl"
STANDAARD_LAND = "NL"


def taalcode(waarde):
    """Maakt van "en-US", "EN" of "en_us" gewoon "en".

    Shopify geeft de taal in verschillende vormen terug, afhankelijk van hoe de
    winkel is ingesteld. Alles wat we niet herkennen wordt Engels."""
    if not waarde or not isinstance(waarde, str):
        return STANDAARD_TAAL
    kern = waarde.strip().lower().replace("_", "-").split("-")[0]
    return kern if kern in TALEN else "en"


def landcode(waarde):
    """Maakt van "us" of " NL " gewoon "US" of "NL"."""
    if not waarde or not isinstance(waarde, str):
        return STANDAARD_LAND
    kern = waarde.strip().upper()
    return kern if len(kern) == 2 and kern.isalpha() else STANDAARD_LAND


def bepaal(taal=None, land=None):
    """Alles wat de rest van Krillo nodig heeft om in de goede taal te meten.

    Geeft altijd een volledig woordenboek terug, ook als er niets bekend is.
    Bewust geen None: een halve markt is de reden dat er straks een winkel
    gemeten wordt met vragen in de verkeerde taal, en dat merk je pas als een
    klant een slechte beoordeling achterlaat.

    De zoekcodes zijn de vorm die de zoekmachine wil: land in HOOFDLETTERS,
    taal in kleine letters. Dat is geen smaakkwestie, Brave geeft anders
    stilletjes niets terug. Die fout hebben we in augustus al een keer gemaakt.
    """
    tc = taalcode(taal)
    lc = landcode(land)
    return {
        "taalcode": tc,
        "landcode": lc,
        "taal": TALEN.get(tc, "English"),
        "land": LANDEN.get(lc, lc),
        "zoek_land": lc,
        "zoek_taal": tc,
        "is_nederlands": tc == "nl",
    }


def omschrijving(markt):
    """Eén regel voor op een beheerpagina: "Nederlands, Nederlandse winkels"."""
    if not markt:
        return "onbekend"
    return f"{markt.get('taal')} ({markt.get('landcode')})"
