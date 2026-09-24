"""De gratis check in het Engels (24 september).

WAAROM DIT BESTAND BESTAAT

De homepage is Engels, maar de uitslag van de gratis check kwam rechtstreeks
uit scan_engine.py, en die schrijft Nederlands: "Gebruikt de site een
beveiligde verbinding?". Een Engelse bezoeker kreeg dus een Nederlandse
uitslag, precies het soort slordigheid waardoor iemand afhaakt.

scan_engine.py zelf blijft Nederlands: zijn teksten worden ook intern
gebruikt (actieplan, beheer) en er hangen tests aan. Hier wordt de uitslag
vertaald op het moment dat hij naar de bezoeker gaat. Per controle een vaste
Engelse titel, en een uitleg per uitkomst: goed, of wat er mis is (dezelfde
zinnen als in verklaring.py, zodat er geen tweede versie van ontstaat).
"""
import verklaring

TITELS = {
    "https": "Does the site use a secure connection?",
    "robots": "Can AI crawlers visit your site?",
    "snelheid": "Does the page load fast enough?",
    "leesbaarheid": "Is the main text visible without clicking?",
    "koppen": "Is the page built up clearly with headings?",
    "taal": "Is the language of the page set?",
    "productinfo": "Can AI read the content of this page reliably?",
    "sitemap": "Can AI find all your pages easily?",
    "llms_txt": "Does the site have instructions for AI (llms.txt)?",
    "voorbeeldweergave": "Does the page have a clear summary for AI and social media?",
    "basis": "Does the page have a clear title and description?",
    "faq": "Does the page answer common questions directly?",
    "alt_tekst": "Do images have a description for AI?",
}

GOED = {
    "https": "The site uses a secure connection (https).",
    "robots": "AI crawlers are allowed to visit your site.",
    "snelheid": "The page responds quickly enough.",
    "leesbaarheid": "The main text can be read right away, without scripts.",
    "koppen": "The page has a clear heading structure.",
    "taal": "The language of the page is set in the code.",
    "productinfo": "The page has machine readable information (schema.org).",
    "sitemap": "A sitemap was found.",
    "llms_txt": "An llms.txt was found.",
    "voorbeeldweergave": "The page has the details for a link preview (Open Graph).",
    "basis": "The page has a title and a description.",
    "faq": "The page answers questions directly.",
    "alt_tekst": "Your images have descriptions.",
}

NIET_GEMETEN = "We could not load this part of your site, so we did not score it."

FOUTEN = {
    "Dat is geen geldige URL.": "That is not a valid web address.",
    "Dat is geen openbare webshop. Vul het gewone webadres in.":
        "That is not a public online store. Enter its normal web address.",
    "We konden deze website niet bereiken.":
        "We could not reach this website. Check the address and whether the site is "
        "online, and try again in a moment.",
    "Deze website stuurde ons een beveiligingscontrole":
        "This website sent us a security check instead of the real page, so we cannot "
        "give a reliable score. Try again in a few minutes.",
}


def fout_in_het_engels(tekst):
    """Een bekende Nederlandse foutmelding van de scan in het Engels.
    Onbekend: een nette algemene zin, nooit de Nederlandse tekst."""
    for begin, engels in FOUTEN.items():
        if (tekst or "").startswith(begin):
            return engels
    return "The check did not work for this address. Try again in a moment."


def uitleg_in_het_engels(check):
    cid, status = check.get("id"), check.get("status")
    if status == "onbekend":
        return NIET_GEMETEN
    if status == "goed":
        return GOED.get(cid) or "This point is fine."
    return (verklaring.BLOKKADES_EN.get(cid) or verklaring.BELEMMERINGEN_EN.get(cid)
            or "This point can be better.")


def naar_het_engels(uitslag):
    """De uitslag van scan_engine.run_scan, klaar voor een Engelse bezoeker.
    Verandert niets aan de cijfers, alleen aan de teksten."""
    if not isinstance(uitslag, dict):
        return uitslag
    uit = dict(uitslag)
    if "error" in uit:
        uit["error"] = fout_in_het_engels(uit["error"])
    uit["checks"] = [dict(c, titel=TITELS.get(c.get("id"), c.get("titel")),
                          uitleg=uitleg_in_het_engels(c))
                     for c in (uitslag.get("checks") or [])]
    # De voorbeeldfixes zijn Nederlandse sjablonen uit de tijd van de audit en
    # worden op de homepage niet getoond. Niet meesturen, dan kan er ook niets
    # Nederlands uit lekken.
    uit.pop("fix_previews", None)
    return uit
