"""De site moet opstarten, ook als de database niet bereikbaar is.

WAAROM DEZE TEST BESTAAT

Op 18 september gaf krillo.nl 502 Bad Gateway, en soms bleef de pagina eindeloos
laden. Ook /robots.txt, die helemaal geen database nodig heeft. De oorzaak zat
in twee dingen die elkaar versterkten:

1. Er stond geen tijdslimiet op het verbinden met de database. Is Neon even weg,
   dan blijft psycopg2 minutenlang wachten in plaats van een fout te geven.
2. app.py roept db.init_db() aan bij het IMPORTEREN. Hangt of mislukt dat, dan
   komt gunicorn nooit klaar met opstarten en geeft Render 502 op ELKE pagina.

Deze test bewaakt allebei de reparaties. Hij gaat niet over mooie foutmeldingen
maar over de vraag of de site nog bestaat als de database er even niet is.
"""
import os
import sys

os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


print("\n== er staat een tijdslimiet op het verbinden ==")
import db  # noqa: E402
klopt("er is een tijdslimiet", db.VERBIND_TIJDSLIMIET > 0)
klopt("en hij is niet zo lang dat Render eerder opgeeft",
      db.VERBIND_TIJDSLIMIET <= 30)
klopt("connect_timeout gaat mee naar psycopg2",
      db.VERBIND_OPTIES.get("connect_timeout") == db.VERBIND_TIJDSLIMIET)
klopt("de keepalives staan aan", db.VERBIND_OPTIES.get("keepalives") == 1)

bron = open(os.path.join(APP, "db.py"), encoding="utf-8").read()
klopt("de pool gebruikt ze", "POOL_MIN, POOL_MAX, db_url, **VERBIND_OPTIES" in bron)
klopt("de losse verbinding ook", "psycopg2.connect(db_url, **VERBIND_OPTIES)" in bron)

print("\n== het opstarten valt niet om op de database ==")
app_bron = open(os.path.join(APP, "app.py"), encoding="utf-8").read()
kop = app_bron[:app_bron.find("def get_base_url")]
klopt("db.init_db() staat in een try bij het opstarten",
      "try:\n    db.init_db()\nexcept Exception" in kop)
klopt("en er staat uitgelegd waarom", "502" in kop)

print("\n== zonder database start de site nog steeds ==")
# Een adres dat nergens naartoe gaat. Zonder tijdslimiet zou dit minuten hangen;
# met de limiet geeft het binnen een paar tellen een fout en gaat de site door.
import importlib  # noqa: E402
import time  # noqa: E402

oud = os.environ.get("DATABASE_URL")
os.environ["DATABASE_URL"] = "postgresql://niemand@192.0.2.1:5432/bestaatniet"
db._POOL = None
begin = time.monotonic()
verbinding = db._get_connection()
duur = time.monotonic() - begin
os.environ["DATABASE_URL"] = oud or ""
db._POOL = None

zo("een onbereikbare database geeft niets terug in plaats van te hangen",
   verbinding, None)
klopt(f"en geeft het snel op (deed er {duur:.1f} seconden over)",
      duur < db.VERBIND_TIJDSLIMIET * 3 + 5)

print("\n== zwaar opstartwerk gebeurt maar een keer ==")
# Het gelijktrekken van de webadressen liep bij ELKE herstart. Dat zoekt alle
# tabellen met een webadres op, haalt uit elk de verschillende adressen, en
# werkt ze een voor een bij. Dat gebeurde voordat de site een bezoeker kon
# bedienen, en Render geeft 502 zolang er nog niets luistert. Bovendien groeit
# de tabel met AI-antwoorden elke nacht, dus het werd elke dag erger.
klopt("er is een eenmalig-slot", hasattr(db, "_eenmalig"))

geteld = {"n": 0}


def _tel():
    geteld["n"] += 1
    return geteld["n"]


db.zet_instelling("migratie_teststap", "")
db._eenmalig("teststap", _tel)
db._eenmalig("teststap", _tel)
db._eenmalig("teststap", _tel)
zo("drie keer aangeroepen, een keer gedaan", geteld["n"], 1)
zo("en het staat onthouden", db.get_instelling("migratie_teststap"), "gedaan")
db.zet_instelling("migratie_teststap", "")

db_bron = open(os.path.join(APP, "db.py"), encoding="utf-8").read()
klopt("de omzetting van webadressen hangt aan dat slot",
      '_eenmalig("webadressen_op_een_schrijfwijze"' in db_bron)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
