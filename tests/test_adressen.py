"""Bewaakt dat dezelfde winkel altijd onder EEN sleutel terechtkomt.

In de kostentabel stond dezelfde winkel twee keer, als "dille-kamille.nl" en
als "https://dille-kamille.nl". Dat is geen schoonheidsfoutje: twee sleutels is
twee keer koopvragen bedenken, twee keer meten, twee keer betalen, en een
maandgrens per klant die de helft van de uitgaven niet ziet. Een bestaande
klant die zijn adres net anders intypt krijgt bovendien een gloednieuwe pagina
zonder zijn eigen geschiedenis.
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

from scan_engine import normalize_url  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


print("\n== alle schrijfwijzen van dezelfde winkel geven dezelfde sleutel ==")
zelfde = [
    "dille-kamille.nl",
    "https://dille-kamille.nl",
    "http://dille-kamille.nl",
    "https://www.dille-kamille.nl",
    "http://www.dille-kamille.nl",
    "www.dille-kamille.nl",
    "https://dille-kamille.nl/",
    "https://www.dille-kamille.nl/",
    "HTTPS://Dille-Kamille.NL/",
    "  dille-kamille.nl  ",
    "https://dille-kamille.nl:443",
]
uitkomsten = {normalize_url(u) for u in zelfde}
zo(f"{len(zelfde)} schrijfwijzen geven 1 sleutel", len(uitkomsten), 1)
zo("en die sleutel is de nette vorm", uitkomsten.pop() if len(uitkomsten) == 1 else None,
   "https://dille-kamille.nl")

print("\n== verschillende winkels blijven verschillend ==")
anders = ["winkel.nl", "winkel.be", "winkel.com", "anderewinkel.nl",
          "winkel.nl/shop", "shop.winkel.nl"]
zo("blijven allemaal apart", len({normalize_url(u) for u in anders}), len(anders))

print("\n== het pad blijft hoofdlettergevoelig ==")
# Op sommige servers is /Producten echt iets anders dan /producten.
zo("pad blijft staan zoals het is",
   normalize_url("winkel.nl/Producten/Schoenen"), "https://winkel.nl/Producten/Schoenen")
zo("schuine streep aan het eind gaat eraf",
   normalize_url("winkel.nl/producten/"), "https://winkel.nl/producten")

print("\n== randgevallen ==")
zo("leeg blijft leeg", normalize_url(""), "")
zo("None blijft leeg", normalize_url(None), "")
zo("alleen spaties blijft leeg", normalize_url("   "), "")
zo("een andere poort blijft staan",
   normalize_url("winkel.nl:8080"), "https://winkel.nl:8080")
# "www" midden in een naam mag niet sneuvelen.
zo("wwwinkel.nl blijft heel", normalize_url("wwwinkel.nl"), "https://wwwinkel.nl")

print("\n== de opruiming van bestaande winkels staat in db.py ==")
db_tekst = open(os.path.join(APP, "db.py")).read()
zo("db.py ruimt oude schrijfwijzen op",
   "scan_engine.normalize_url(oud_adres)" in db_tekst, True)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
