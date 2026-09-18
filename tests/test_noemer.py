"""Een noemer op de site zegt altijd waar hij over gaat.

WAAROM DEZE TEST BESTAAT

Nino op 18 september: "er zijn natuurlijk veel meer stores dan alleen de stores
die wij laten zien in de index. het kan zo zijn dat een store misschien 200
staat maar stel er zijn maar 30 stores in de index."

Dat is de kern van wat Krillo verkoopt. Onze positie is GEEN rangorde onder
alle webshops van Nederland, maar een rangorde onder de winkels die wij meten.
Stond er kaal "1 van de 24", dan leest een speelgoedwinkelier die weet dat er
honderden speelgoedwebshops zijn daar twee dingen in, en allebei zijn ze slecht
voor ons:

1. "Ze meten maar 24 winkels, dus die meting stelt niets voor."
2. "Ik sta 1e van alle speelgoedwebshops in Nederland." Dat is een claim die
   wij niet waar kunnen maken.

Het getal was altijd waar, het label ontbrak. Deze test bewaakt dat het label
er blijft.

En de andere kant ervan: een winkel die bij GEEN ENKELE vraag genoemd is krijgt
geen positie. Niet 31, niet 200. Wij weten niet waar hij zou staan, want er is
geen signaal. Een nummer verzinnen zou een meting suggereren die er niet is, en
"AI noemde je nergens" is geen ontbrekend gegeven maar juist de uitslag.
"""
import os
import re
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import sitetaal  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


print("\n== DE TEKSTEN BESTAAN IN BEIDE TALEN ==")
for sleutel in ("van_de_gemeten", "index_dekking"):
    for taal in ("nl", "en"):
        klopt(f"{sleutel} bestaat in {taal}", sleutel in sitetaal.T[taal])
    # Zonder {n} valt het getal weg en staat er een zin zonder noemer.
    for taal in ("nl", "en"):
        klopt(f"{sleutel} in {taal} heeft een plek voor het getal",
              "{n}" in sitetaal.T[taal][sleutel])

print("\n== DE NOEMER STAAT NERGENS MEER KAAL ==")
dash = lees("templates/dashboard.html")
klopt("het dashboard gebruikt de tekst met label",
      "van_de_gemeten" in dash)
klopt("het dashboard gebruikt de kale versie niet meer",
      "{{ t.van_de }} {{ beeld.van }}" not in dash)

thuis = lees("templates/index.html")
klopt("de homepage zegt waar de noemer over gaat",
      "we measure" in thuis)
klopt("de homepage heeft geen kale noemer meer",
      "of {{ index.top.winkels }}<" not in thuis)

cat = lees("templates/index_categorie.html")
klopt("de categoriepagina legt uit wat de index dekt",
      "index_dekking" in cat)

print("\n== DE ZIN ZEGT OOK ECHT DAT HET NIET DE HELE MARKT IS ==")
# Het label mag niet verwateren tot iets dat alleen maar netjes klinkt. De hele
# reden dat deze zin er staat is dat hij de grens benoemt.
klopt("de Nederlandse zin benoemt de grens",
      "niet alle webshops in de markt" in sitetaal.T["nl"]["index_dekking"])
klopt("de Engelse zin benoemt de grens",
      "not every store in the market" in sitetaal.T["en"]["index_dekking"])

print("\n== EEN NIET-GENOEMDE WINKEL KRIJGT GEEN POSITIE ==")
# De openbare ranglijst toont alleen winkels die genoemd zijn, en telt de rest
# als aantal. Dat stond al zo in de code; deze controle legt vast dat het zo
# blijft, want het is dezelfde belofte als hierboven.
klopt("de overige winkels worden als AANTAL genoemd en niet bij naam",
      "{n}" in sitetaal.T["nl"]["overige"] and "{n}" in sitetaal.T["en"]["overige"])
klopt("en de zin zegt dat ze nergens genoemd zijn",
      "geen enkele" in sitetaal.T["nl"]["overige"]
      and "none of these" in sitetaal.T["en"]["overige"])

print("\n== DE PAGINA RENDERT NOG ==")
import app  # noqa: E402

app.app.config["TESTING"] = True
k = app.app.test_client()
zo("de homepage laadt", k.get("/").status_code, 200)
zo("de indexpagina laadt", k.get("/index").status_code, 200)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed: elke noemer op de site zegt waar hij over gaat.")
