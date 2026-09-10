"""Test van fase 5 punt 15: het actieplan.

De belangrijkste eis is niet dat er iets uitkomt, maar dat de VOLGORDE altijd
klopt en altijd hetzelfde is. Een klant die deze week ander advies krijgt dan
vorige week zonder dat er iets veranderd is, gelooft er terecht niets meer van.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

import actieplan

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen != verwacht:
        fouten.append(f"FOUT: {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
    else:
        print(f"  ok  {omschrijving}")


KLANTBEELD = {"genoemd": 15, "telbaar": 22, "aanbevolen": 4}

VERKLARING_SCHOON = {"blokkades": [], "belemmeringen": []}
VERKLARING_BLOK = {
    "blokkades": [{"id": "robots", "tekst": "...", "soort": "feit"}],
    "belemmeringen": [{"id": "faq", "tekst": "...", "soort": "vermoeden"},
                      {"id": "sitemap", "tekst": "...", "soort": "vermoeden"}],
}
BRONNEN = {
    "paginas": 11,
    "gemist": 3,
    "gemiste_paginas": [
        {"url": "https://vtwonen.nl/shopgids", "titel": "Shopgids: zo kies je de beste servieset",
         "domein": "vtwonen.nl", "concurrenten": ["HEMA", "fonQ", "Xenos"]},
        {"url": "https://gadgetbusiness.nl/top5", "titel": "Beste Serviessets Top 5",
         "domein": "gadgetbusiness.nl", "concurrenten": ["Cookinglife", "bol.com"]},
    ],
}
CONTROLE = {
    "gecontroleerd": 8, "klopt": 6, "klopt_niet": 1, "onbekend": 1,
    "fouten": [{"uitspraak": "Dille & Kamille levert binnen 24 uur",
                "watzegtdesite": "Bezorging binnen 2 tot 3 werkdagen",
                "oordeel": "klopt niet"}],
}

print("\n== de volgorde: feit voor vermoeden, blokkade bovenaan ==")
plan = actieplan.maak_actieplan(
    verklaring=VERKLARING_BLOK, klantbeeld=KLANTBEELD, bronnen=BRONNEN,
    controle=CONTROLE, winkelnaam="Dille & Kamille")
titels = [a["titel"] for a in plan["acties"]]
zo("hoogstens drie acties", len(plan["acties"]), 3)
zo("de blokkade staat bovenaan", titels[0], "Geef AI-robots toegang tot je site")
zo("daarna de onjuiste uitspraak", titels[1], "Zet recht wat AI verkeerd over je vertelt")
zo("dan de externe plekken", "2 plekken" in titels[2], True)
zo("de titel belooft niet meer dan er links onder staan",
   str(len(plan["acties"][2]["links"])) + " plekken" in titels[2], True)
zo("de eerste drie zijn allemaal feiten",
   [a["soort"] for a in plan["acties"]], ["feit", "feit", "feit"])
zo("de leesbaarheidspunten wachten", plan["rest"], 2)
zo("en dat staat er ook bij", "nog 2 in de wacht" in plan["toelichting"], True)

print("\n== schone site, weinig vermeldingen: dan is extern het antwoord ==")
plan = actieplan.maak_actieplan(
    verklaring=VERKLARING_SCHOON, klantbeeld={"genoemd": 1, "telbaar": 22},
    bronnen=BRONNEN, controle=None, winkelnaam="Dille & Kamille")
zo("een actie", len(plan["acties"]), 1)
zo("en die gaat over de externe plekken", "plekken komt te staan" in plan["acties"][0]["titel"], True)
zo("met echte links erbij", len(plan["acties"][0]["links"]), 2)
zo("het eerste adres klopt", plan["acties"][0]["links"][0]["url"], "https://vtwonen.nl/shopgids")
zo("de concurrenten staan in de reden", "HEMA" in plan["acties"][0]["waarom"], True)

print("\n== geen externe bronnen: dan pas de site-punten ==")
plan = actieplan.maak_actieplan(
    verklaring=VERKLARING_BLOK, klantbeeld=KLANTBEELD, bronnen=None,
    controle=None, winkelnaam="Dille & Kamille")
titels = [a["titel"] for a in plan["acties"]]
zo("blokkade eerst", titels[0], "Geef AI-robots toegang tot je site")
zo("dan vraag en antwoord", titels[1], "Zet vragen en antwoorden op je site")
zo("dan de sitemap", titels[2], "Dien een sitemap in")
zo("de laatste twee zijn vermoedens",
   [a["soort"] for a in plan["acties"][1:]], ["vermoeden", "vermoeden"])

print("\n== alles in orde: dan geen verzonnen acties ==")
plan = actieplan.maak_actieplan(
    verklaring=VERKLARING_SCHOON, klantbeeld={"genoemd": 20, "telbaar": 22},
    bronnen={"paginas": 9, "gemist": 0, "gemiste_paginas": []}, controle=None, winkelnaam="Dille & Kamille")
zo("geen acties", plan["acties"], [])
zo("en dat wordt eerlijk gezegd", "niets om aan te pakken" in plan["kop"], True)

print("\n== geen bronanalyse gedraaid: dan niets beweren over externe plekken ==")
plan = actieplan.maak_actieplan(
    verklaring=VERKLARING_SCHOON, klantbeeld={"genoemd": 0, "telbaar": 22},
    bronnen=None, controle=None, winkelnaam="Dille & Kamille")
zo("geen acties", plan["acties"], [])
zo("beweert NIET dat we plekken nagekeken hebben",
   "op de plekken die we nakeken sta je erbij" in plan["kop"], False)
zo("zegt eerlijk dat we niets konden nakijken",
   "geen externe pagina's kunnen nakijken" in plan["kop"], True)

print("\n== nog niet gemeten: dan helemaal geen plan ==")
zo("geen klantbeeld", actieplan.maak_actieplan(klantbeeld=None), None)
zo("leeg klantbeeld", actieplan.maak_actieplan(klantbeeld={"telbaar": 0}), None)
zo("alles leeg", actieplan.maak_actieplan(), None)

print("\n== nul vermeldingen krijgt een eigen zin ==")
plan = actieplan.maak_actieplan(
    verklaring=VERKLARING_BLOK, klantbeeld={"genoemd": 0, "telbaar": 22},
    bronnen=None, controle=None, winkelnaam="Bergzicht Outdoor")
zo("de kop zegt het eerlijk", "bij geen enkele van de 22 vragen genoemd" in plan["kop"], True)

print("\n== dezelfde invoer geeft altijd hetzelfde plan ==")
een = actieplan.maak_actieplan(verklaring=VERKLARING_BLOK, klantbeeld=KLANTBEELD,
                               bronnen=BRONNEN, controle=CONTROLE, winkelnaam="Dille & Kamille")
twee = actieplan.maak_actieplan(verklaring=VERKLARING_BLOK, klantbeeld=KLANTBEELD,
                                bronnen=BRONNEN, controle=CONTROLE, winkelnaam="Dille & Kamille")
zo("twee keer draaien, hetzelfde resultaat", een, twee)

print("\n== elke actie is compleet ==")
alle = []
for v in (VERKLARING_BLOK, VERKLARING_SCHOON):
    for b in (BRONNEN, None):
        for c in (CONTROLE, None):
            p = actieplan.maak_actieplan(verklaring=v, klantbeeld=KLANTBEELD, bronnen=b,
                                         controle=c, winkelnaam="Testwinkel")
            alle.extend(p["acties"])
zo("overal een titel", all(a["titel"] for a in alle), True)
zo("overal een reden", all(len(a["waarom"]) > 40 for a in alle), True)
zo("overal een hoe", all(len(a["hoe"]) > 40 for a in alle), True)
zo("soort is altijd feit of vermoeden",
   all(a["soort"] in ("feit", "vermoeden") for a in alle), True)
zo("geen gedachtestreepjes in de teksten",
   any("—" in a["hoe"] or "—" in a["waarom"] or "—" in a["titel"] for a in alle), False)

print("\n== alle sjablonen zijn compleet ingevuld ==")
import verklaring as verklaring_mod
zo("elke blokkade heeft een actie",
   set(verklaring_mod.BLOKKADES) - set(actieplan.BLOKKADE_ACTIES), set())
zo("elke belemmering heeft een actie",
   set(verklaring_mod.BELEMMERINGEN) - set(actieplan.BELEMMERING_ACTIES), set())
zo("de volgorde noemt ze allemaal",
   set(verklaring_mod.BELEMMERINGEN) - set(actieplan.BELEMMERING_VOLGORDE), set())
zo("en niets extra's",
   set(actieplan.BELEMMERING_VOLGORDE) - set(verklaring_mod.BELEMMERINGEN), set())

print("\n== taal=en geeft Engels, en verandert verder niets ==")
nl = actieplan.maak_actieplan(
    verklaring=VERKLARING_BLOK, klantbeeld=KLANTBEELD, bronnen=BRONNEN,
    controle=CONTROLE, winkelnaam="Dille & Kamille")
en = actieplan.maak_actieplan(
    verklaring=VERKLARING_BLOK, klantbeeld=KLANTBEELD, bronnen=BRONNEN,
    controle=CONTROLE, winkelnaam="Dille & Kamille", taal="en")
zo("even veel acties als in het Nederlands", len(en["acties"]), len(nl["acties"]))
zo("dezelfde kenmerken in dezelfde volgorde",
   [a["id"] for a in en["acties"]], [a["id"] for a in nl["acties"]])
zo("dezelfde soorten", [a["soort"] for a in en["acties"]], [a["soort"] for a in nl["acties"]])
zo("dezelfde links", en["acties"][2]["links"], nl["acties"][2]["links"])
zo("de blokkade staat er in het Engels", en["acties"][0]["titel"],
   "Let AI crawlers read your site")
zo("de onjuiste uitspraak ook", en["acties"][1]["titel"],
   "Put right what AI gets wrong about you")
zo("en de externe plekken ook", "places" in en["acties"][2]["titel"], True)
zo("de kop is Engels", "is mentioned in 15 of the 22 questions" in en["kop"], True)
zo("de toelichting is Engels", "three at most" in en["toelichting"], True)
zo("en het aantal in de wacht staat erbij", "There are 2 waiting" in en["toelichting"], True)
zo("het merkje heet measured", en["acties"][0]["merkje"], "measured")

print("\n== taal=nl blijft precies wat het was ==")
zo("nl is de standaard", actieplan.maak_actieplan(
    verklaring=VERKLARING_BLOK, klantbeeld=KLANTBEELD, bronnen=BRONNEN,
    controle=CONTROLE, winkelnaam="Dille & Kamille", taal="nl"), nl)
zo("de blokkadetitel is onveranderd", nl["acties"][0]["titel"],
   "Geef AI-robots toegang tot je site")
zo("de kop is onveranderd", nl["kop"],
   "Dille & Kamille wordt genoemd bij 15 van de 22 vragen. Hieronder staat wat je deze week "
   "kan doen om dat te verbeteren, belangrijkste eerst.")
zo("het merkje heet gewoon feit", nl["acties"][0]["merkje"], "feit")
zo("een onbekende taal valt terug op Nederlands", actieplan.maak_actieplan(
    verklaring=VERKLARING_BLOK, klantbeeld=KLANTBEELD, bronnen=BRONNEN,
    controle=CONTROLE, winkelnaam="Dille & Kamille", taal="fr"), nl)

print("\n== de Engelse teksten zijn compleet en in dezelfde toon ==")
engels = []
for v in (VERKLARING_BLOK, VERKLARING_SCHOON):
    for b in (BRONNEN, None):
        for c in (CONTROLE, None):
            p = actieplan.maak_actieplan(verklaring=v, klantbeeld=KLANTBEELD, bronnen=b,
                                         controle=c, winkelnaam="Testwinkel", taal="en")
            engels.append(p)
acties_en = [a for p in engels for a in p["acties"]]
zo("overal een titel", all(a["titel"] for a in acties_en), True)
zo("overal een reden", all(len(a["waarom"]) > 40 for a in acties_en), True)
zo("overal een hoe", all(len(a["hoe"]) > 40 for a in acties_en), True)
zo("het merkje is measured of our reading",
   sorted({a["merkje"] for a in acties_en}), ["measured", "our reading"])
zo("geen gedachtestreepjes in de Engelse teksten",
   any("—" in a["hoe"] or "—" in a["waarom"] or "—" in a["titel"] for a in acties_en), False)
zo("geen gedachtestreepjes in de koppen",
   any("—" in p["kop"] or "—" in p["toelichting"] for p in engels), False)
zo("geen Nederlands blijven staan in de Engelse acties",
   any(" je " in a["hoe"] or " je " in a["waarom"] for a in acties_en), False)

print("\n== elk sjabloon heeft een Engelse tegenhanger ==")
for naam, boek in (("blokkades", actieplan.BLOKKADE_ACTIES),
                   ("belemmeringen", actieplan.BELEMMERING_ACTIES)):
    zo(f"{naam}: overal een titel_en", all(s.get("titel_en") for s in boek.values()), True)
    zo(f"{naam}: overal een hoe_en", all(s.get("hoe_en") for s in boek.values()), True)

print("\n== ook zonder acties klopt het Engels ==")
leeg_en = actieplan.maak_actieplan(
    verklaring=VERKLARING_SCHOON, klantbeeld={"genoemd": 20, "telbaar": 22},
    bronnen={"paginas": 9, "gemist": 0, "gemiste_paginas": []}, controle=None,
    winkelnaam="Dille & Kamille", taal="en")
zo("geen acties", leeg_en["acties"], [])
zo("en dat wordt eerlijk gezegd in het Engels", "nothing to fix" in leeg_en["kop"], True)
niets_en = actieplan.maak_actieplan(
    verklaring=VERKLARING_SCHOON, klantbeeld={"genoemd": 0, "telbaar": 22},
    bronnen=None, controle=None, winkelnaam="Dille & Kamille", taal="en")
zo("beweert NIET dat we plekken nagekeken hebben",
   "you are listed on the places we checked" in niets_en["kop"], False)
zo("zegt eerlijk dat we niets konden nakijken",
   "could not check any outside pages" in niets_en["kop"], True)

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
