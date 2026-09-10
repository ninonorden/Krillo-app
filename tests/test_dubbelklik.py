"""Bewaakt dat een dubbelklik op de gratis test geen twee metingen start.

De gratis test en de voorproef staan op een publieke pagina zonder wachtwoord.
Twee keer klikken startte twee volledige metingen bij ChatGPT en Gemini: twee
keer betalen voor precies dezelfde uitslag, door iedereen die de site bezoekt.

Een controle vooraf in de code is hier niet genoeg, en dat is gemeten: van tien
gelijktijdige klikken kwamen er tien door, want ze kijken allemaal voordat er
een wegschrijft. Het slot moet dus in de database zelf zitten.
"""
import os
import sys
import threading

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

import db  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


db.init_db()
print("  ok  init_db loopt helemaal door")


def opruimen(url):
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("UPDATE zichtbaarheidstests SET status = 'mislukt' "
                    "WHERE webshop_url = %s AND status IN ('wachtrij','bezig')", (url,))
    conn.close()


print("\n== een gewone eerste test ==")
URL = "https://dubbelkliktest.nl"
opruimen(URL)
zo("er loopt nog niets", db.loopt_er_al_een_test(URL), False)
eerste = db.start_zichtbaarheidstest(URL, "a@b.nl", soort="voorproef")
zo("de test start", eerste is not None, True)

print("\n== een tweede klik terwijl de eerste loopt ==")
zo("wordt gezien als lopend", db.loopt_er_al_een_test(URL), True)
zo("en start geen tweede meting",
   db.start_zichtbaarheidstest(URL, "a@b.nl", soort="voorproef"), None)

print("\n== tien klikken in dezelfde milliseconde ==")
# Dit is het geval dat een controle vooraf niet kan winnen. Een dubbelklik
# stuurt twee verzoeken zo snel achter elkaar dat ze allebei kijken voordat er
# een wegschrijft.
SNEL = "https://snelleklikker.nl"
opruimen(SNEL)
door = []


def klik():
    if db.loopt_er_al_een_test(SNEL):
        return
    rij = db.start_zichtbaarheidstest(SNEL, "a@b.nl", soort="voorproef")
    if rij:
        door.append(rij["id"])


draden = [threading.Thread(target=klik) for _ in range(10)]
for d in draden:
    d.start()
for d in draden:
    d.join()
zo("er komt er precies EEN door", len(door), 1)

print("\n== na afloop mag er weer een ==")
db.zet_zichtbaarheidstest(door[0], "klaar", resultaat={"x": 1})
opnieuw = db.start_zichtbaarheidstest(SNEL, "a@b.nl", soort="voorproef")
zo("een nieuwe test kan gestart worden", opnieuw is not None, True)

print("\n== een andere winkel wordt nooit geblokkeerd ==")
ANDERS = "https://heelanderewinkel.nl"
opruimen(ANDERS)
zo("start gewoon",
   db.start_zichtbaarheidstest(ANDERS, "a@b.nl", soort="voorproef") is not None, True)
opruimen(ANDERS)

print("\n== een vastgelopen test blokkeert niet eeuwig ==")
VAST = "https://vastgelopen.nl"
opruimen(VAST)
vast = db.start_zichtbaarheidstest(VAST, "a@b.nl", soort="voorproef")
conn = db._get_connection()
with conn, conn.cursor() as conn_cur:
    conn_cur.execute(
        "UPDATE zichtbaarheidstests SET aangevraagd_op = now() - interval '%s minutes' "
        "WHERE id = %%s" % (db.TEST_VASTGELOPEN_NA_MINUTEN + 5), (vast["id"],))
conn.close()
zo("telt niet meer als lopend", db.loopt_er_al_een_test(VAST), False)
opruimen(VAST)

print("\n== het slot dekt de HELE meting, niet alleen het begin ==")
# Dit ging bijna mis. De eerste versie zocht op status 'wachtrij' of 'bezig',
# maar zodra de meting begint zet zichtbaarheid.py er vrije tekst in: "vragen
# bedenken", "vragen stellen aan AI", "antwoorden lezen". Het slot beschermde
# daardoor alleen de eerste seconden, terwijl een meting minuten duurt.
LOPEND = "https://lopendemeting.nl"
opruimen(LOPEND)
loopt = db.start_zichtbaarheidstest(LOPEND, "a@b.nl", soort="voorproef")
for stand in ("vragen bedenken", "vragen stellen aan AI", "antwoorden lezen", "bezig"):
    db.zet_zichtbaarheidstest(loopt["id"], stand)
    zo(f"bij status {stand!r} wordt een tweede meting geweigerd",
       db.start_zichtbaarheidstest(LOPEND, "a@b.nl"), None)
db.zet_zichtbaarheidstest(loopt["id"], "klaar", resultaat={"x": 1})
zo("en na 'klaar' mag er weer een",
   db.start_zichtbaarheidstest(LOPEND, "a@b.nl") is not None, True)
opruimen(LOPEND)

print("\n== de index in de database heeft de JUISTE voorwaarde ==")
# CREATE UNIQUE INDEX IF NOT EXISTS kijkt alleen naar de naam, niet naar de
# voorwaarde. Op een database waar de oude index al stond gebeurde er dus
# niets, en stond de reparatie wel in de code maar niet in de database.
conn = db._get_connection()
with conn, conn.cursor() as cur:
    cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname = "
                "'zichtbaarheidstests_een_lopende_per_winkel'")
    rij = cur.fetchone()
conn.close()
zo("de index bestaat", bool(rij), True)
zo("en sluit op klaar en mislukt uit, niet op wachtrij en bezig",
   bool(rij and "klaar" in rij[0] and "mislukt" in rij[0]
        and "wachtrij" not in rij[0]), True)

print("\n== beide publieke ingangen gebruiken het slot ==")
app_tekst = open(os.path.join(APP, "app.py")).read()
zo("op twee plekken aangeroepen", app_tekst.count("db.loopt_er_al_een_test(url)"), 2)

print("\n== het slot staat buiten de grote transactie van init_db ==")
# Stond het erbinnen, dan sloopte een mislukte index de hele opbouw van de
# database en startte de app helemaal niet meer op.
db_tekst = open(os.path.join(APP, "db.py")).read()
zo("als eigen functie", "def _zet_slot_op_lopende_tests():" in db_tekst, True)
zo("aangeroepen na conn.close()",
   db_tekst.find("conn.close()\n\n    # Bewust NA het sluiten") > 0, True)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
