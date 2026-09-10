"""Losse test van de bronanalyse, zonder database en zonder API-sleutels.

Test precies het stuk dat fout kan gaan zonder dat je het merkt: het herkennen
van een winkelnaam op een pagina. Een verzonnen vindplaats is erger dan geen
vindplaats.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

import bronnen

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen != verwacht:
        fouten.append(f"FOUT: {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
    else:
        print(f"  ok  {omschrijving}")


print("\n== naam herkennen op een pagina ==")
tekst = ("De leukste winkels voor servies zijn Dille &amp; Kamille, fonQ en Loods 5. "
         "Ook Flinders heeft een mooi assortiment. Bekijk ook dille-kamille.nl voor meer.")

zo("gewone naam", bronnen.komt_voor(tekst, "fonQ"), True)
zo("naam met spatie en cijfer", bronnen.komt_voor(tekst, "Loods 5"), True)
zo("naam met ampersand, geschreven met en", bronnen.komt_voor(tekst, "Dille en Kamille"), True)
zo("naam met koppelteken in een link", bronnen.komt_voor(tekst, "Dille-Kamille"), True)
zo("winkel die er niet op staat", bronnen.komt_voor(tekst, "Xenos"), False)
zo("winkel die er niet op staat 2", bronnen.komt_voor(tekst, "de Bijenkorf"), False)
zo("ampersand als los teken", bronnen.komt_voor("Bij Dille & Kamille vind je", "Dille & Kamille"), True)
zo("aan elkaar geschreven", bronnen.komt_voor("zie dillekamille voor meer", "Dille & Kamille"), True)
zo("lang lidwoordloos woord mag", bronnen.komt_voor("Ook Bijenkorf verkoopt dit", "de Bijenkorf"), True)
zo("kort alledaags woord mag NIET", bronnen.komt_voor("Onze tuinen zijn mooi", "De Tuinen"), False)
zo("maar voluit wel", bronnen.komt_voor("Bij De Tuinen kan je terecht", "De Tuinen"), True)
zo("lidwoord wel aanwezig", bronnen.komt_voor("Ook de Bijenkorf verkoopt dit", "de Bijenkorf"), True)

print("\n== geen toevalstreffers binnen een langer woord ==")
zo("Xenos niet in xenostudio", bronnen.komt_voor("Bekijk xenostudio.nl vandaag", "Xenos"), False)
zo("Coolblue wel als los woord", bronnen.komt_voor("Wij raden Coolblue aan.", "Coolblue"), True)
zo("naam aan het eind van een zin", bronnen.komt_voor("Onze favoriet is Flinders.", "Flinders"), True)
zo("naam tussen haakjes", bronnen.komt_voor("Goede optie (Flinders) hier", "Flinders"), True)
zo("te korte naam telt niet", bronnen.komt_voor("iets over abc hier", "abc"), False)

print("\n== herkennen via het webadres ==")
zo("eigen domein in een link",
   bronnen.komt_voor("Ga naar https://www.bergzicht-outdoor.nl/shop voor meer",
                     "Bergzicht Outdoor", ook_domein="bergzicht-outdoor.nl"), True)
zo("ander domein telt niet",
   bronnen.komt_voor("Ga naar https://www.anderewinkel.nl/shop",
                     "Bergzicht Outdoor", ook_domein="bergzicht-outdoor.nl"), False)

print("\n== kern van een domein ==")
zo("met www en https", bronnen._kern_van_domein("https://www.dille-kamille.nl/servies"), "dillekamille")
zo("zonder protocol", bronnen._kern_van_domein("fonq.nl"), "fonq")
zo("met poortnummer", bronnen._kern_van_domein("http://localhost:5000/test"), "localhost")

print("\n== welke vragen trekken we na ==")
klantbeeld = {
    "regels": [
        {"vraag": "beste webshop voor servies", "telt_mee": True, "genoemd": False, "aantal_winkels": 7},
        {"vraag": "waar koop ik emaille mokken", "telt_mee": True, "genoemd": False, "aantal_winkels": 3},
        {"vraag": "leukste woonwinkel online", "telt_mee": True, "genoemd": True, "aanbevolen": False, "aantal_winkels": 9},
        {"vraag": "telt niet mee", "telt_mee": False, "genoemd": False, "aantal_winkels": 20},
    ],
    "concurrenten": [
        {"naam": "fonQ", "genoemd": 8, "aanbevolen": 4, "wij": False},
        {"naam": "Loods 5", "genoemd": 6, "aanbevolen": 1, "wij": False},
        {"naam": "Onze Winkel", "genoemd": 2, "aanbevolen": 0, "wij": True},
    ],
}
gekozen = bronnen.kies_vragen(klantbeeld)
zo("alleen vragen waar we ontbreken", len(gekozen), 2)
zo("drukste vraag eerst", gekozen[0], "beste webshop voor servies")
zo("vraag die niet meetelt valt af", "telt niet mee" in gekozen, False)

conc = bronnen.kies_concurrenten(klantbeeld)
zo("onze eigen winkel gaat eruit", "Onze Winkel" in conc, False)
zo("meest aanbevolen concurrent eerst", conc[0], "fonQ")

print("\n== als we overal genoemd worden ==")
overal = {"regels": [
    {"vraag": "vraag a", "telt_mee": True, "genoemd": True, "aanbevolen": False, "aantal_winkels": 5},
    {"vraag": "vraag b", "telt_mee": True, "genoemd": True, "aanbevolen": True, "aantal_winkels": 4},
], "concurrenten": []}
zo("dan kijken we naar niet-aanbevolen", bronnen.kies_vragen(overal), ["vraag a"])

print("\n== de samenvatting voor de klant ==")
vindplaatsen = [
    {"vraag": "v1", "bron_url": "https://blog.nl/a", "bron_titel": "Top 10 servieswinkels",
     "bron_domein": "blog.nl", "wij_genoemd": False, "concurrenten": ["fonQ", "Loods 5"]},
    {"vraag": "v1", "bron_url": "https://vergelijk.nl/b", "bron_titel": "Vergelijking",
     "bron_domein": "vergelijk.nl", "wij_genoemd": False, "concurrenten": ["fonQ"]},
    {"vraag": "v1", "bron_url": "https://fonq.nl/c", "bron_titel": "fonQ zelf",
     "bron_domein": "fonq.nl", "wij_genoemd": False, "concurrenten": ["fonQ"],
     "eigen_site_van": "fonQ"},
    {"vraag": "v2", "bron_url": "https://forum.nl/d", "bron_titel": "Forumdraadje",
     "bron_domein": "forum.nl", "wij_genoemd": True, "concurrenten": ["Loods 5"]},
]
s = bronnen.vat_samen(vindplaatsen, "Onze Winkel")
zo("eigen site van de concurrent telt niet mee", s["paginas"], 3)
zo("waar wij op staan", s["wij_erop"], 1)
zo("pagina's met concurrent zonder ons", s["gemist"], 2)
zo("fonQ staat op twee externe pagina's",
   next(c["paginas"] for c in s["concurrenten"] if c["naam"] == "fonQ"), 2)
zo("drukste gemiste pagina bovenaan", s["gemiste_paginas"][0]["url"], "https://blog.nl/a")
print("  conclusie:", s["conclusie"])

print("\n== lege invoer laat niets klappen ==")
zo("geen vindplaatsen", bronnen.vat_samen([]), None)
zo("None", bronnen.vat_samen(None), None)
zo("leeg klantbeeld", bronnen.kies_vragen(None), [])
zo("leeg klantbeeld concurrenten", bronnen.kies_concurrenten(None), [])

print("\n== zonder sleutel doet hij niets, en klapt niet ==")
zo("niet beschikbaar zonder sleutel", bronnen.beschikbaar(), False)
zo("uitleg is er wel", bool(bronnen.waarom_niet()), True)
zo("analyseer geeft lege lijst", bronnen.analyseer("winkel.nl", klantbeeld, "Onze Winkel"), [])

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
