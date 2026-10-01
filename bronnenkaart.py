"""Stap 178 en 179: waar AI kopers naartoe stuurt, uit de antwoorden zelf (1 oktober 2026).

WAAROM. Peec laat zien welke sites AI aanhaalt. Wij laten de assistenten
antwoorden zoals een koper ze krijgt, zonder zoekfunctie, dus er staan geen
bronlinks in. Maar in de antwoorden zelf staat wel waar AI kopers naartoe
stuurt: "kijk ook op Kieskeurig", "de reviews op Trustpilot", "bij bol.com
vind je...". Voor een webshop is dat precies de actielijst: op die plekken moet
je staan, met goede reviews en volledige productgegevens.

HOE, ZONDER BRAVE EN ZONDER MODEL.
- Platforms die de meting zelf al als platform herkende (genoemde_winkels,
  soort "platform": marktplaatsen en vergelijkers).
- Plus een vaste lijst van review-, vergelijk- en communitysites, die we
  letterlijk in de antwoordtekst zoeken (hele woorden, hoofdletters maakt niet uit).
Per plek: in hoeveel van de antwoorden hij voorkomt. Gratis en elke keer hetzelfde.
"""
import json
import re

# (naam zoals hij op het scherm komt, soort, zoekpatronen)
BEKENDE_BRONNEN = [
    ("Trustpilot", "reviews", ["trustpilot"]),
    ("Kiyoh", "reviews", ["kiyoh"]),
    ("Feedback Company", "reviews", ["feedback company", "feedbackcompany"]),
    ("WebwinkelKeur", "reviews", ["webwinkelkeur"]),
    ("Thuiswinkel Waarborg", "reviews", ["thuiswinkel waarborg", "thuiswinkel.org"]),
    ("Google reviews", "reviews", ["google reviews", "google-reviews", "googlereviews"]),
    ("Kieskeurig", "comparison", ["kieskeurig"]),
    ("Tweakers", "comparison", ["tweakers"]),
    ("Beslist", "comparison", ["beslist.nl", "beslist"]),
    ("Consumentenbond", "comparison", ["consumentenbond"]),
    ("Test Aankoop", "comparison", ["test aankoop", "test-aankoop", "testaankoop"]),
    ("Google Shopping", "comparison", ["google shopping"]),
    ("Reddit", "community", ["reddit"]),
    ("YouTube", "community", ["youtube"]),
    ("Instagram", "community", ["instagram"]),
    ("TikTok", "community", ["tiktok"]),
    ("Facebook", "community", ["facebook"]),
    ("Pinterest", "community", ["pinterest"]),
    ("Bol", "marketplace", ["bol.com"]),   # niet los "bol": dat is ook een gewoon Nederlands woord
    ("Amazon", "marketplace", ["amazon"]),
    ("Marktplaats", "marketplace", ["marktplaats"]),
    ("Etsy", "marketplace", ["etsy"]),
    ("Zalando", "marketplace", ["zalando"]),
    ("Vinted", "marketplace", ["vinted"]),
]
SOORT_EN = {"reviews": "Review site", "comparison": "Comparison or test site", "community": "Community",
            "marketplace": "Marketplace", "platform": "Platform"}
ADVIES = {
    "reviews": "Collect reviews there: AI quotes them as proof that a store can be trusted.",
    "comparison": "Make sure your products are listed there with full and correct data.",
    "community": "Be present there with useful posts or answers; AI repeats what people say.",
    "marketplace": "AI sends shoppers there. Selling there too, or being clearly better on your own site, both help.",
    "platform": "AI sends shoppers there. Check whether you can be listed.",
}


def _genoemde(rij):
    g = rij.get("genoemde_winkels") or {}
    if isinstance(g, str):
        try:
            g = json.loads(g)
        except ValueError:
            g = {}
    return g


def _kern(naam):
    return re.sub(r"[^a-z0-9]", "", (naam or "").lower().replace(".com", "").replace(".nl", "").replace(".be", ""))


def bronnen(antwoorden, maximaal=8):
    """[{"naam", "soort", "soort_en", "aantal", "van", "advies"}], vaakst eerst.

    antwoorden: rijen met antwoord en genoemde_winkels (db.antwoorden_met_tekst_van_ronde)."""
    rijen = [r for r in antwoorden or [] if (r.get("antwoord") or "").strip()]
    van = len(rijen)
    telling = {}   # kern -> [naam, soort, aantal]
    patronen = [(naam, soort, re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(p) for p in pats) + r")(?![a-z0-9])",
                                         re.I)) for naam, soort, pats in BEKENDE_BRONNEN]
    for r in rijen:
        tekst = r.get("antwoord") or ""
        gezien = set()
        for naam, soort, patroon in patronen:
            if patroon.search(tekst):
                gezien.add((_kern(naam), naam, soort))
        for w in _genoemde(r).get("winkels") or []:
            if w.get("soort") == "platform" and w.get("naam"):
                k = _kern(w["naam"])
                if k and not any(g[0] == k for g in gezien):
                    gezien.add((k, w["naam"], "platform"))
        for k, naam, soort in gezien:
            vak = telling.setdefault(k, [naam, soort, 0])
            vak[2] += 1
            # Een bekende soort wint van "platform".
            if vak[1] == "platform" and soort != "platform":
                vak[0], vak[1] = naam, soort
    uit = [{"naam": n, "soort": s, "soort_en": SOORT_EN.get(s, s), "aantal": a, "van": van,
            "advies": ADVIES.get(s, "")} for n, s, a in telling.values()]
    uit.sort(key=lambda b: (-b["aantal"], b["naam"]))
    return uit[:maximaal]
