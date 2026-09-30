"""Vragen labelen op wat de koper zoekt (stap 193, 30 september).

WAAROM. Peec labelt vragen automatisch. Voor een winkelier werkt een label pas
als hij het meteen snapt: Prijs, Product, Service, Waarden, Lokaal. Dan zie je
in een oogopslag "je verliest alle prijsvragen, maar wint de servicevragen", en
dat zegt wat je moet doen (prijs duidelijker op de pagina, of juist inzetten op
service).

WAAROM MET WOORDEN EN NIET MET EEN MODEL. Het kost niets, het is voor elke
vraag hetzelfde, en een winkelier kan nagaan waarom een vraag een label kreeg.
Past geen enkel woord, dan "Algemeen": liever eerlijk algemeen dan verzonnen.
De vragen staan in de taal van de markt (Nederlands, straks Duits of Frans),
dus de woorden staan er in die talen bij. Volgorde telt: de eerste die past wint.
"""
import re

LABELS = [
    ("prijs", {"en": "Price", "nl": "Prijs"},
     r"goedkoop|goedkope|voordelig|budget|korting|aanbieding|uitverkoop|sale\b|prijs|prijzen|cheap|"
     r"affordable|discount|\bdeals?\b|price|g[üu]nstig|billig|rabatt|pas cher|moins cher|promo"),
    ("lokaal", {"en": "Local", "nl": "Lokaal"},
     r"\bin de buurt\b|\bnear me\b|\bin (amsterdam|rotterdam|utrecht|den haag|eindhoven|antwerpen|gent|"
     r"brussel|leuven|groningen)\b|winkel in|afhalen|ophalen|in der n[äa]he|pr[èe]s de chez"),
    ("service", {"en": "Service", "nl": "Service"},
     r"snel|snelle|levering|bezorg|verzend|verzending|morgen in huis|retour|ruilen|garantie|klantenservice|"
     r"betrouwbaar|achteraf betalen|fast|delivery|shipping|return|warranty|reliable|lieferung|versand|"
     r"livraison|retour|fiable"),
    ("waarden", {"en": "Values", "nl": "Waarden"},
     r"duurzaam|duurzame|biologisch|bio\b|eerlijk|\bfair\b|tweedehands|refurbished|vegan|milieu|gerecycled|"
     r"handgemaakt|lokaal gemaakt|sustainable|organic|\beco\b|\beco-|second.?hand|handmade|nachhaltig|durable|[ée]thique"),
    ("product", {"en": "Product", "nl": "Product"},
     r"beste|goede|kwaliteit|groot aanbod|ruim assortiment|merk|merken|welke|specialist|best\b|quality|"
     r"brand|range|selection|beste[rn]?\b|meilleur"),
]
ALGEMEEN = ("algemeen", {"en": "General", "nl": "Algemeen"})
_GECOMPILEERD = [(s, n, re.compile(p, re.I)) for s, n, p in LABELS]


def label(vraag):
    """De sleutel van het label: prijs, lokaal, service, waarden, product of algemeen."""
    for sleutel, _, patroon in _GECOMPILEERD:
        if patroon.search(vraag or ""):
            return sleutel
    return ALGEMEEN[0]


def naam(sleutel, taal="en"):
    for s, namen, _ in _GECOMPILEERD:
        if s == sleutel:
            return namen.get(taal, namen["en"])
    return ALGEMEEN[1].get(taal, ALGEMEEN[1]["en"])


def telling(vragen):
    """Per label: hoeveel vragen en hoeveel verloren, in vaste volgorde, alleen
    de labels die voorkomen. vragen: items met "label" en "gewonnen"."""
    per = {}
    for v in vragen:
        p = per.setdefault(v.get("label") or ALGEMEEN[0], {"totaal": 0, "verloren": 0})
        p["totaal"] += 1
        p["verloren"] += 0 if v.get("gewonnen") else 1
    volgorde = [s for s, _, _ in _GECOMPILEERD] + [ALGEMEEN[0]]
    return [dict(sleutel=s, **per[s]) for s in volgorde if s in per]
