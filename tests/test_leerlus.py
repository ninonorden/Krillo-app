"""Bewaakt de leerlus: Krillo leert van zijn eigen metingen.

Nino's punt, en hij had gelijk: een agent hoort sterker te worden van wat er
bewaard is, en dat gebeurde niet. Koopvragen werden voor elke winkel opnieuw
bedacht met een schone lei, terwijl er duizenden beoordeelde antwoorden in de
database staan die precies vertellen welke soort vragen iets opleveren.

Waarom dat geld kost. Een vraag telt alleen mee als AI in dat antwoord winkels
noemt. Haalt een winkel te weinig meetellende vragen, dan mag er geen post uit
en wordt hij morgen opnieuw gemeten. Zolang wij vragen blijven bedenken van een
soort waar nooit een winkel in het antwoord staat, betalen wij dus voor metingen
die per definitie niets kunnen opleveren.

Twee dingen worden hier bewaakt:

1. Dat er geleerd wordt, en dat het pas gebeurt bij genoeg bewijs. Een soort
   vraag afschrijven op drie antwoorden is geen leren maar gokken.
2. Dat het zichtbaar is. Iets dat zijn eigen opdracht aanpast op grond van
   geschiedenis hoort te laten zien waarop dat gebaseerd is. Anders is het een
   zwarte doos die duurder wordt zonder dat iemand kan nagaan waarom.
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import APP, TEMPLATES, lees  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

import db           # noqa: E402
import koopvragen   # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


print("\n== zonder genoeg metingen wordt er niets beweerd ==")
# Dit is het geval bij de eerste winkels. Dan hoort de opdracht aan het model
# precies te zijn zoals hij altijd was, en niet een regel te bevatten die op
# drie antwoorden gebaseerd is.
echte_prestaties = db.intentie_prestaties
db.intentie_prestaties = lambda minimum=20: []
uit = koopvragen.wat_wij_geleerd_hebben()
zo("geen zin voor het model", uit["zin"], "")
zo("en geen cijfers om te tonen", uit["regels"], [])

print("\n== met genoeg metingen wordt de zwakke soort benoemd ==")
db.intentie_prestaties = lambda minimum=20: [
    {"intentie": "winkel", "antwoorden": 400, "telden_mee": 340, "genoemd": 90,
     "aandeel": 0.85},
    {"intentie": "algemeen", "antwoorden": 380, "telden_mee": 260, "genoemd": 70,
     "aandeel": 0.68},
    {"intentie": "praktisch", "antwoorden": 300, "telden_mee": 36, "genoemd": 4,
     "aandeel": 0.12},
]
uit = koopvragen.wat_wij_geleerd_hebben()
klopt("de zwakke soort staat erin", "praktisch" in uit["zin"])
klopt("met de opdracht om er hooguit een of twee te maken",
      "hooguit een of twee" in uit["zin"])
klopt("de sterke soorten staan er ook in",
      "winkel" in uit["zin"] and "algemeen" in uit["zin"])
klopt("en het zwaartepunt gaat daarheen", "zwaartepunt" in uit["zin"])
klopt("de cijfers gaan mee zodat je het kan nakijken", len(uit["regels"]) == 3)

print("\n== is alles sterk, dan verandert er niets aan de opdracht ==")
db.intentie_prestaties = lambda minimum=20: [
    {"intentie": "winkel", "antwoorden": 400, "telden_mee": 340, "genoemd": 90,
     "aandeel": 0.85},
]
uit = koopvragen.wat_wij_geleerd_hebben()
zo("geen loze regel in de opdracht", uit["zin"], "")
klopt("de cijfers blijven wel zichtbaar", len(uit["regels"]) == 1)

print("\n== een kapotte database legt het bedenken niet stil ==")
def stuk(minimum=20):
    raise RuntimeError("database weg")
db.intentie_prestaties = stuk
uit = koopvragen.wat_wij_geleerd_hebben()
zo("gewoon niets geleerd, geen fout", uit, {"zin": "", "regels": []})
db.intentie_prestaties = echte_prestaties

print("\n== de grens is een echte grens ==")
klopt("er moet echt bewijs zijn", koopvragen.GENOEG_OM_IETS_TE_ZEGGEN >= 10)
klopt("en de zwakgrens ligt ergens redelijk",
      0.2 <= koopvragen.ZWAK_ONDER <= 0.7)

print("\n== het geleerde gaat mee in de opdracht aan het model ==")
bron = lees("koopvragen.py")
klopt("de opdracht roept het geleerde op", 'wat_wij_geleerd_hebben()["zin"]' in bron)
klopt("en het staat in de tekst van de opdracht", "{geleerd}" in bron)

print("\n== en je kan zien wat er geleerd is ==")
app_tekst = lees("app.py")
klopt("de beheerpagina krijgt het mee",
      "geleerd=koopvragen.wat_wij_geleerd_hebben()" in app_tekst)
pagina = open(os.path.join(TEMPLATES, "admin_koopvragen.html")).read()
klopt("er staat een tabel met de cijfers", "geleerd.regels" in pagina)
klopt("met het aantal antwoorden eronder", "r.antwoorden" in pagina)
klopt("en hoeveel er meetelden", "r.telden_mee" in pagina)
klopt("de zwakke soorten vallen op", "zwak_onder" in pagina)
klopt("en de opdrachtregel zelf is te lezen", "geleerd.zin" in pagina)

print("\n== de echte query telt het goede ==")
# winkel_kon_genoemd is het veld dat zegt of de vraag meetelde. Telt deze query
# per ongeluk 'genoemd', dan meet hij of ONZE winkel genoemd werd, en dat is een
# heel andere vraag: dan zou een soort vraag zwak lijken omdat de winkels slecht
# scoren in plaats van omdat AI er geen winkels noemt.
dbtekst = lees("db.py")
start = dbtekst.find("def intentie_prestaties")
functie = dbtekst[start:dbtekst.find("\ndef ", start + 10)]
klopt("het telt de meetellende antwoorden",
      "FILTER (WHERE winkel_kon_genoemd)" in functie)
klopt("en groepeert per soort vraag", "GROUP BY COALESCE(intentie" in functie)
klopt("met een ondergrens op het aantal antwoorden", "HAVING COUNT(*) >=" in functie)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
