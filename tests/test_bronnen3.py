"""Derde testronde: de hele bronanalyse van begin tot eind, met nagebootste
zoekresultaten en nagebootste pagina's.

Dit is de test die er echt toe doet: hij bewijst dat de losse stukken samen
het goede antwoord geven, en dat de eigen site van de klant en die van een
concurrent er netjes uit vallen.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

import os
os.environ["BRAVE_API_KEY"] = "nep-sleutel-voor-de-test"

import bronnen

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen != verwacht:
        fouten.append(f"FOUT: {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
    else:
        print(f"  ok  {omschrijving}")


# De nagebootste wereld: vier pagina's die een zoekmachine oplevert.
PAGINAS = {
    "https://woonblog.nl/top-10-servies": """
        <html><body><h1>De 10 leukste servieswinkels</h1>
        <p>Onze favorieten zijn fonQ, Loods 5 en Dille &amp; Kamille.</p>
        </body></html>""",
    "https://vergelijk.nl/servies": """
        <html><body><h1>Servies vergelijken</h1>
        <p>Bij fonQ vind je het grootste aanbod.</p>
        <a href="https://www.fonq.nl/servies">Naar fonQ</a>
        </body></html>""",
    "https://forum.nl/draadje-servies": """
        <html><body><p>Ik bestel altijd bij Bergzicht Outdoor, prima service.
        Ook Loods 5 is een aanrader.</p></body></html>""",
    "https://www.fonq.nl/servies": """
        <html><body><h1>Servies bij fonQ</h1><p>Ons complete assortiment.</p>
        </body></html>""",
    "https://www.bergzicht-outdoor.nl/servies": """
        <html><body><h1>Servies</h1><p>Onze eigen webshop.</p></body></html>""",
    "https://leeg.nl/niets": """
        <html><body><p>Hier staat geen enkele winkelnaam in.</p></body></html>""",
}

ZOEKRESULTATEN = [
    {"url": "https://woonblog.nl/top-10-servies", "titel": "De 10 leukste servieswinkels", "omschrijving": ""},
    {"url": "https://vergelijk.nl/servies", "titel": "Servies vergelijken", "omschrijving": ""},
    {"url": "https://forum.nl/draadje-servies", "titel": "Draadje over servies", "omschrijving": ""},
    {"url": "https://www.fonq.nl/servies", "titel": "Servies bij fonQ", "omschrijving": ""},
    {"url": "https://www.bergzicht-outdoor.nl/servies", "titel": "Onze eigen pagina", "omschrijving": ""},
    {"url": "https://leeg.nl/niets", "titel": "Niets te zien", "omschrijving": ""},
]

gezochte_vragen = []


def nep_zoek(vraag, webshop_url=None, land=None, taal=None):
    gezochte_vragen.append(vraag)
    return list(ZOEKRESULTATEN)


def nep_haal_pagina(url):
    html = PAGINAS.get(url)
    if not html:
        return ""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    linkjes = " ".join(a.get("href") or "" for a in soup.find_all("a", href=True))
    return " ".join(soup.get_text(" ", strip=True).split()) + " " + linkjes


class NepKosten:
    @staticmethod
    def mag_doorgaan(**kw):
        return {"mag": True}

    @staticmethod
    def registreer_vaste_kosten(**kw):
        return None


bronnen.zoek = nep_zoek
bronnen._haal_pagina = nep_haal_pagina
bronnen.kosten = NepKosten

KLANTBEELD = {
    "regels": [
        {"vraag": "beste webshop voor servies", "telt_mee": True, "genoemd": False, "aantal_winkels": 7},
    ],
    "concurrenten": [
        {"naam": "fonQ", "genoemd": 6, "aanbevolen": 3, "wij": False},
        {"naam": "Loods 5", "genoemd": 4, "aanbevolen": 1, "wij": False},
        {"naam": "Dille & Kamille", "genoemd": 2, "aanbevolen": 0, "wij": False},
        {"naam": "Bergzicht Outdoor", "genoemd": 1, "aanbevolen": 0, "wij": True},
    ],
}

print("\n== de hele bronanalyse van begin tot eind ==")
vind = bronnen.analyseer(
    "bergzicht-outdoor.nl", KLANTBEELD,
    winkelnaam="Bergzicht Outdoor", meting_id="test123",
)

zo("de juiste vraag is gezocht", gezochte_vragen, ["beste webshop voor servies"])

adressen = {v["bron_url"]: v for v in vind}
zo("onze eigen site is overgeslagen",
   "https://www.bergzicht-outdoor.nl/servies" in adressen, False)
zo("pagina zonder enige winkelnaam valt weg", "https://leeg.nl/niets" in adressen, False)
zo("pagina met maar een winkel valt weg (te dun)",
   "https://vergelijk.nl/servies" in adressen, False)
zo("drie pagina's over", len(vind), 3)

blog = adressen["https://woonblog.nl/top-10-servies"]
zo("blog: drie concurrenten gevonden", sorted(blog["concurrenten"]),
   ["Dille & Kamille", "Loods 5", "fonQ"])
zo("blog: wij staan er niet op", blog["wij_genoemd"], False)
zo("blog: het domein klopt", blog["bron_domein"], "woonblog.nl")
zo("blog: geen eigen site van iemand", blog["eigen_site_van"], None)

forum = adressen["https://forum.nl/draadje-servies"]
zo("forum: wij staan er wel op", forum["wij_genoemd"], True)
zo("forum: en Loods 5 ook", forum["concurrenten"], ["Loods 5"])

fonq = adressen["https://www.fonq.nl/servies"]
zo("fonQ's eigen site blijft zichtbaar met een label", fonq["eigen_site_van"], "fonQ")

print("\n== wat de klant hiervan te zien krijgt ==")
s = bronnen.vat_samen(vind, "Bergzicht Outdoor")
zo("eigen site van fonQ telt niet mee in de noemer", s["paginas"], 2)
zo("wij staan op een pagina", s["wij_erop"], 1)
zo("een plek met een concurrent en zonder ons", s["gemist"], 1)
zo("Loods 5 staat op de meeste websites", s["concurrenten"][0]["naam"], "Loods 5")
zo("Loods 5 op twee websites", s["concurrenten"][0]["paginas"], 2)
zo("fonQ op een website",
   next(c["paginas"] for c in s["concurrenten"] if c["naam"] == "fonQ"), 1)
zo("drukste gemiste pagina bovenaan",
   s["gemiste_paginas"][0]["url"], "https://woonblog.nl/top-10-servies")
zo("elke gemiste pagina heeft een echt adres",
   all(g["url"].startswith("http") for g in s["gemiste_paginas"]), True)
print("  conclusie:", s["conclusie"])

print("\n== hoogstens een pagina per website ==")
VEEL = [{"url": f"https://gratisretourneren.nl/pagina-{i}", "titel": f"Lijst {i}", "omschrijving": ""}
        for i in range(1, 5)]
VEEL.append({"url": "https://woonblog.nl/top-10-servies", "titel": "Blog", "omschrijving": ""})
for i in range(1, 5):
    PAGINAS[f"https://gratisretourneren.nl/pagina-{i}"] = (
        "<html><body><p>Bij fonQ en Loods 5 kan je gratis retourneren.</p></body></html>")

bronnen.zoek = lambda vraag, webshop_url=None, land=None, taal=None: list(VEEL)
uit = bronnen.analyseer("bergzicht-outdoor.nl", KLANTBEELD, winkelnaam="Bergzicht Outdoor")
domeinen = [v["bron_domein"] for v in uit]
zo("die ene site komt maar een keer terug", domeinen.count("gratisretourneren.nl"), 1)
s2 = bronnen.vat_samen(uit, "Bergzicht Outdoor")
zo("en telt dus als een plek, niet als vier",
   next(c["paginas"] for c in s2["concurrenten"] if c["naam"] == "fonQ"), 2)

print("\n== de soort vraag bepaalt de volgorde ==")
gemengd = {"regels": [
    {"vraag": "welke webshop levert het snelst", "telt_mee": True, "genoemd": False,
     "aantal_winkels": 12, "intentie": "praktisch"},
    {"vraag": "beste webshop voor servies", "telt_mee": True, "genoemd": False,
     "aantal_winkels": 4, "intentie": "winkel"},
    {"vraag": "goedkoop servies waar", "telt_mee": True, "genoemd": False,
     "aantal_winkels": 9, "intentie": "prijs"},
], "concurrenten": []}
volgorde = bronnen.kies_vragen(gemengd)
zo("winkelvraag wint van de drukste vraag", volgorde[0], "beste webshop voor servies")
zo("de praktische vraag zakt naar achteren", volgorde[-1], "welke webshop levert het snelst")

print("\n== zwakke soorten vragen worden overgeslagen ==")
genoeg = {"regels": [
    {"vraag": "beste servieswinkel", "telt_mee": True, "genoemd": False, "aantal_winkels": 3, "intentie": "winkel"},
    {"vraag": "mooiste servies online", "telt_mee": True, "genoemd": False, "aantal_winkels": 3, "intentie": "algemeen"},
    {"vraag": "goedkoop servies", "telt_mee": True, "genoemd": False, "aantal_winkels": 3, "intentie": "prijs"},
    {"vraag": "servies voor kinderen", "telt_mee": True, "genoemd": False, "aantal_winkels": 3, "intentie": "doelgroep"},
    {"vraag": "welke winkel heeft goed retourbeleid", "telt_mee": True, "genoemd": False,
     "aantal_winkels": 20, "intentie": "praktisch"},
], "concurrenten": []}
gekozen = bronnen.kies_vragen(genoeg, grens=4)
zo("de retourvraag valt af als er genoeg goede zijn",
   "welke winkel heeft goed retourbeleid" in gekozen, False)
zo("vier goede vragen gekozen", len(gekozen), 4)

weinig = {"regels": [
    {"vraag": "beste servieswinkel", "telt_mee": True, "genoemd": False, "aantal_winkels": 3, "intentie": "winkel"},
    {"vraag": "welke winkel heeft goed retourbeleid", "telt_mee": True, "genoemd": False,
     "aantal_winkels": 20, "intentie": "praktisch"},
], "concurrenten": []}
gekozen = bronnen.kies_vragen(weinig, grens=4)
zo("maar hij telt wel mee als er te weinig zijn", len(gekozen), 2)
zo("en dan staat de goede nog steeds vooraan", gekozen[0], "beste servieswinkel")

print("\n== als de kostenrem dichtgaat ==")


class RemDicht:
    @staticmethod
    def mag_doorgaan(**kw):
        return {"mag": False, "reden": "dagbudget op"}

    @staticmethod
    def registreer_vaste_kosten(**kw):
        return None


bronnen.kosten = RemDicht
zo("dan wordt er niets gezocht",
   bronnen.analyseer("bergzicht-outdoor.nl", KLANTBEELD, winkelnaam="Bergzicht Outdoor"), [])
bronnen.kosten = NepKosten

print("\n== als de zoekmachine niets teruggeeft ==")
bronnen.zoek = lambda vraag, webshop_url=None, land=None, taal=None: []
zo("geen resultaten geeft geen vindplaatsen",
   bronnen.analyseer("bergzicht-outdoor.nl", KLANTBEELD, winkelnaam="Bergzicht Outdoor"), [])

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
