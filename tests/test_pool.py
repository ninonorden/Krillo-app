"""Bewaakt dat de verbindingenpool een dode verbinding overleeft.

Dit is geschreven nadat er in productie stond:
    Instelling bewaren mislukt (benadering_laatste_ronde): connection already closed

Oorzaak: conn.closed is alleen een vlag aan onze kant. Neon gooit een
verbinding die een tijd stil ligt aan zijn kant weg, en dan staat onze vlag nog
gewoon op open. De eerste aanroep erna viel om. Dat trof precies de ronde die
elk uur draait, want die komt langs na een uur stilte.
"""
import os
import sys
import threading
import time

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

import psycopg2  # noqa: E402
import db        # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


db.init_db()
db.zet_instelling("pooltest", "ja")


def warm_de_pool_op(n=6):
    """Dwingt de pool om verbindingen aan te maken en te bewaren."""
    vast, klaar = [], threading.Event()

    def houd_vast():
        c = db._get_connection()
        vast.append(c)
        klaar.wait()
        c.close()

    draden = [threading.Thread(target=houd_vast) for _ in range(n)]
    for d in draden:
        d.start()
    while len(vast) < n:
        time.sleep(0.01)
    klaar.set()
    for d in draden:
        d.join()


def gooi_eruit():
    """Bootst na wat Neon doet na een periode stilte: de verbinding weggooien.

    Vanaf een LOSSE verbinding, zodat de pool het niet ziet gebeuren. Dat is
    precies het geval waar het misging."""
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    c.autocommit = True
    with c.cursor() as cur:
        cur.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE pid <> pg_backend_pid() AND datname = current_database()")
        aantal = len(cur.fetchall())
    c.close()
    return aantal


print("\n== een dode verbinding uit de pool ==")
warm_de_pool_op()
weg = gooi_eruit()
zo("er zijn echt verbindingen weggegooid", weg > 0, True)
zo("schrijven werkt daarna gewoon",
   db.zet_instelling("benadering_laatste_ronde", "2026-09-09T14:10:00"), True)
zo("en lezen ook",
   db.get_instelling("benadering_laatste_ronde"), "2026-09-09T14:10:00")

print("\n== drie keer achter elkaar ==")
overleefd = True
for _ in range(3):
    warm_de_pool_op()
    gooi_eruit()
    if db.get_instelling("pooltest") != "ja":
        overleefd = False
zo("drie keer overleefd", overleefd, True)

print("\n== twintig draden meteen na een uitgooi ==")
warm_de_pool_op()
gooi_eruit()
mislukt = []


def werk():
    try:
        for _ in range(10):
            db.get_instelling("pooltest")
    except Exception as e:
        mislukt.append(repr(e))


draden = [threading.Thread(target=werk) for _ in range(20)]
for d in draden:
    d.start()
for d in draden:
    d.join()
zo("geen fouten", mislukt, [])
zo("geen verbindingen blijven hangen", len(db._POOL._used), 0)

print("\n== de pool is nog steeds sneller dan losse verbindingen ==")
t = time.monotonic()
for _ in range(40):
    db.get_instelling("pooltest")
met_pool = time.monotonic() - t
t = time.monotonic()
for _ in range(40):
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    with c, c.cursor() as cur:
        cur.execute("SELECT waarde FROM instellingen WHERE sleutel='pooltest'")
        cur.fetchone()
    c.close()
zonder = time.monotonic() - t
print(f"      met pool {met_pool*1000:.0f} ms, zonder {zonder*1000:.0f} ms")
zo("sneller dan zonder", met_pool < zonder, True)

print("\n== de ronde plant niet meer metingen in dan er betaald kunnen worden ==")
import kosten  # noqa: E402
ruimte = kosten.ruimte_voor_benadering()
zo("de ruimte zegt hoeveel er nog past", "past_nog" in ruimte, True)
app_tekst = open(os.path.join(APP, "app.py")).read()
zo("en de ronde gebruikt dat", 'ruimte.get("past_nog")' in app_tekst, True)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
