"""Zelf webshops vinden, zodat er nooit met de hand een lijst geplakt hoeft te
worden.

Waarom dit bestaat: de benaderlijst raakte gewoon op. Bij vijftien mails per dag
is een lijst van tweehonderd winkels binnen twee weken leeg, en dan staat de
machine stil zonder dat er iets kapot is. Dat is geen fout maar het voelt wel zo,
en het betekent dat er handwerk in de enige lopende motor zit.

Hoe: met dezelfde zoekmachine die de bronanalyse al gebruikt. Wij zoeken op
manieren waarop een winkel zichzelf beschrijft ("webshop", "online kopen",
"gratis verzending") binnen een branche, en halen uit de resultaten de domeinen.

Wat dit met opzet NIET doet:

- Geen adressen scrapen. Het zoeken levert alleen webadressen op. Het mailadres
  wordt daarna door contactvinder op de site van de winkel zelf gezocht, precies
  zoals bij een lijst die met de hand geplakt is. Dat is de plek waar de regels
  over zakelijke post al staan en die willen wij niet omzeilen.
- Geen marktplaatsen, prijsvergelijkers, blogs of kranten. Die staan bovenaan bij
  dit soort zoekopdrachten en het zijn geen webshops. De lijst hieronder houdt ze
  eruit. Hij is niet volledig, en dat hoeft ook niet: wat er toch doorheen komt
  levert geen algemeen e-mailadres op of valt af bij de meting.
- Geen winkels die al op de lijst staan. Dat controleert db.voeg_benaderingen_toe
  al, dus een dubbele vondst kost niets en levert geen tweede mail op.
"""

import os
import re

import bronnen
import db
import scan_engine

# Zoeken kost geld, dus met een rem erop. Vier zoekopdrachten per ronde is
# ongeveer twee cent en levert bij genoeg branches tientallen winkels per dag.
ZOEKOPDRACHTEN_PER_RONDE = int(os.environ.get("VINDER_ZOEKOPDRACHTEN", "4"))

# Onder hoeveel winkels zonder adres wij op zoek gaan naar nieuwe. Zolang er nog
# genoeg te doen is hoeft er niets bij: dan geef je geld uit aan namen die weken
# blijven liggen.
VOORRAAD_ONDERGRENS = int(os.environ.get("VINDER_ONDERGRENS", "40"))

# Waar wij zoeken. Nederland en Belgie, want daar mag zakelijke post naar het
# algemene adres van een bedrijf.
LANDEN = [
    {"land": "NL", "taal": "nl", "naam": "NL"},
    {"land": "BE", "taal": "nl", "naam": "BE"},
]

# De branches waar wij winkels zoeken. Bewust breed en concreet: "webshop" alleen
# levert vooral artikelen over webshops beginnen op.
BRANCHES = [
    "kleding", "schoenen", "sieraden", "wonen en interieur", "meubels",
    "verlichting", "planten", "tuin", "speelgoed", "babyspullen",
    "sport en fitness", "outdoor", "fietsen", "elektronica", "audio",
    "boeken", "kantoorartikelen", "keukenspullen", "servies", "beddengoed",
    "verzorging", "cosmetica", "parfum", "thee en koffie", "delicatessen",
    "wijn", "dierenbenodigdheden", "hobby en knutselen", "kunst en posters",
    "gereedschap",
]

# Manieren waarop een winkel zichzelf beschrijft. Een zoekopdracht is steeds
# branche plus een van deze, plus het land.
VORMEN = [
    "webshop",
    "online kopen gratis verzending",
    "online bestellen webwinkel",
    "kopen bij onze webshop",
]

# Wat geen webshop is. Marktplaatsen, prijsvergelijkers, kranten, sociale
# netwerken en alles wat een winkel wel noemt maar er zelf geen is.
GEEN_WINKEL = {
    "bol.com", "amazon.nl", "amazon.com", "amazon.be", "marktplaats.nl",
    "vinted.nl", "vinted.be", "etsy.com", "aliexpress.com", "temu.com",
    "wish.com", "ebay.nl", "ebay.com", "zalando.nl", "zalando.be",
    "beslist.nl", "kieskeurig.nl", "tweakers.net", "vergelijk.nl",
    "google.com", "google.nl", "youtube.com", "facebook.com", "instagram.com",
    "pinterest.com", "pinterest.nl", "linkedin.com", "tiktok.com", "x.com",
    "twitter.com", "reddit.com", "wikipedia.org", "wikiwand.com",
    "shopify.com", "woocommerce.com", "lightspeedhq.com", "ccvshop.nl",
    "mijnwebwinkel.nl", "wix.com", "squarespace.com", "webnode.nl",
    "kvk.nl", "belastingdienst.nl", "rijksoverheid.nl", "consuwijzer.nl",
    "thuiswinkel.org", "trustpilot.com", "kiyoh.nl", "feedbackcompany.com",
    "nu.nl", "ad.nl", "telegraaf.nl", "volkskrant.nl", "nrc.nl", "rtl.nl",
    "nos.nl", "hln.be", "vrt.be", "standaard.be", "emerce.nl", "twinkle.nl",
    "frankwatching.com", "marketingfacts.nl", "sprout.nl", "mkbservicedesk.nl",
    "ondernemenmetpersoneel.nl", "hostnet.nl", "strato.nl", "transip.nl",
    "yoast.com", "semrush.com", "ahrefs.com", "hubspot.com", "mailchimp.com",
    "klarna.com", "mollie.com", "adyen.com", "paypal.com", "postnl.nl",
    "dhl.com", "dpd.com", "gls-group.com", "bpost.be",
}

# Achtervoegsels die nooit een Nederlandse of Belgische webshop zijn.
GEEN_DOMEIN = re.compile(
    r"\.(gov|edu|mil|int|museum|wikipedia\.org)$|"
    r"(^|\.)(blog|nieuws|news|forum|wiki|support|help|docs|api|cdn|static)\.",
    re.I)


def _domein(url):
    """Het kale domein van een webadres, zonder www en zonder pad."""
    if not url:
        return ""
    _, _, rest = str(url).partition("://")
    host = rest.split("/")[0].split("?")[0].lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]


def _is_bruikbaar(host):
    """Of dit domein een webshop KAN zijn. Streng genoeg om de bekende
    niet-winkels eruit te houden, mild genoeg om niets echts weg te gooien.

    Wat hier doorheen komt is nog geen winkel. Dat blijkt pas bij de scan en bij
    het zoeken naar een adres, en dat is precies de goede volgorde: die stappen
    bestaan al en zijn al voorzichtig."""
    if not host or "." not in host or len(host) > 100:
        return False
    if host in GEEN_WINKEL:
        return False
    # Ook een subdomein van een bekende niet-winkel eruit, zoals
    # winkel.bol.com.
    if any(host.endswith("." + kaal) for kaal in GEEN_WINKEL):
        return False
    if GEEN_DOMEIN.search(host):
        return False
    return True


def _zoekopdrachten(hoeveel, ronde=0):
    """De zoekopdrachten voor deze ronde.

    Rouleert door de branches op basis van het rondenummer, zodat je niet elke
    ronde dezelfde vijftien winkels terugkrijgt. Zonder dit levert ronde twee
    precies hetzelfde op als ronde een en betaal je voor niets."""
    uit = []
    totaal = len(BRANCHES) * len(VORMEN) * len(LANDEN)
    for i in range(hoeveel):
        n = (ronde * hoeveel + i) % totaal
        branche = BRANCHES[n % len(BRANCHES)]
        vorm = VORMEN[(n // len(BRANCHES)) % len(VORMEN)]
        gebied = LANDEN[(n // (len(BRANCHES) * len(VORMEN))) % len(LANDEN)]
        uit.append({
            "vraag": f"{branche} {vorm} {'Nederland' if gebied['land'] == 'NL' else 'Belgie'}",
            "branche": branche,
            "land": gebied["land"],
            "taal": gebied["taal"],
        })
    return uit


def hoeveel_voorraad():
    """Hoeveel winkels er nog wachten op een adres of op een meting.

    Dit is de voorraad die bepaalt of er nieuwe namen bij moeten. Winkels die al
    gemaild zijn tellen niet mee, die zijn klaar."""
    tellingen = db.tel_benaderingen() or {}
    per_stand = tellingen.get("per_stand") or {}
    return (per_stand.get("nieuw", 0) + per_stand.get("adres", 0)
            + per_stand.get("meten", 0) + per_stand.get("gemeten", 0))


def zoek_nieuwe_winkels(hoeveel_zoekopdrachten=None, ronde=0):
    """Zoekt webshops en zet ze op de benaderlijst.

    Geeft een verslagje terug: hoeveel zoekopdrachten, hoeveel domeinen gezien,
    hoeveel er nieuw op de lijst gekomen zijn, en waarom er eventueel niets
    gebeurd is."""
    verslag = {"gezocht": 0, "gezien": 0, "nieuw": 0, "reden": None}

    if not bronnen.beschikbaar():
        verslag["reden"] = f"Zoekmachine niet beschikbaar: {bronnen.waarom_niet()}"
        return verslag

    hoeveel = (hoeveel_zoekopdrachten if hoeveel_zoekopdrachten is not None
               else ZOEKOPDRACHTEN_PER_RONDE)
    if hoeveel < 1:
        verslag["reden"] = "Er staan nul zoekopdrachten per ronde ingesteld."
        return verslag

    gevonden = {}
    for opdracht in _zoekopdrachten(hoeveel, ronde):
        verslag["gezocht"] += 1
        try:
            resultaten = bronnen.zoek(opdracht["vraag"], land=opdracht["land"],
                                      taal=opdracht["taal"])
        except Exception as e:
            print(f"Winkels zoeken mislukt voor {opdracht['vraag']}: {e}")
            continue
        for r in resultaten or []:
            host = _domein(r.get("url"))
            verslag["gezien"] += 1
            if not _is_bruikbaar(host):
                continue
            # Eerste vondst wint. Een domein dat in twee branches opduikt hoort
            # maar een keer op de lijst.
            gevonden.setdefault(host, opdracht)

    if not gevonden:
        verslag["reden"] = ("De zoekopdrachten leverden geen bruikbare winkels op. "
                            "Dat kan aan de zoekmachine liggen of aan de branches "
                            "die deze ronde aan de beurt waren.")
        return verslag

    regels = [(scan_engine.normalize_url(host), None, opdracht["land"],
               opdracht["branche"])
              for host, opdracht in gevonden.items()]
    try:
        # Geeft een getal terug, niet een woordenboek: hoeveel er echt bij
        # gekomen zijn. Winkels die er al op stonden blijven staan zoals ze
        # staan, dus een tweede vondst kost niets en levert geen tweede mail op.
        verslag["nieuw"] = int(db.voeg_benaderingen_toe(regels) or 0)
    except Exception as e:
        verslag["reden"] = f"Toevoegen aan de lijst mislukt: {e}"
        return verslag

    if not verslag["nieuw"]:
        verslag["reden"] = (f"{len(gevonden)} winkels gevonden, maar die stonden "
                            f"allemaal al op de lijst.")
    return verslag


def vul_aan_indien_nodig(ronde=0, ondergrens=None):
    """Zoekt alleen nieuwe winkels als de voorraad onder de grens zakt.

    Zo betaal je niet elke ronde voor zoekopdrachten terwijl er nog honderd
    winkels liggen te wachten."""
    grens = ondergrens if ondergrens is not None else VOORRAAD_ONDERGRENS
    voorraad = hoeveel_voorraad()
    if voorraad >= grens:
        return {"gezocht": 0, "gezien": 0, "nieuw": 0, "voorraad": voorraad,
                "reden": None}
    uit = zoek_nieuwe_winkels(ronde=ronde)
    uit["voorraad"] = voorraad
    return uit
