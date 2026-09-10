"""Bewaakt dat er nooit twee keer voor dezelfde meting betaald wordt.

Dit is geschreven na een dag waarop er 16,69 euro aan metingen uitging terwijl
de teller "gemeten" op nul bleef staan. Vijf winkels waren elk drie tot vijf
keer gemeten. De oorzaak: de wachtrij staat in het geheugen, Render zette de
app in slaap, de winkel stond nog op "adres" en kwam de volgende ronde gewoon
weer aan de beurt.

Het gaat hier om echt geld, dus deze test moet blijven staan.
"""
import os
import sys
from datetime import datetime, timedelta

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

import db          # noqa: E402
import benadering  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


db.init_db()

# Alles wat er van eerdere tests nog op "adres" of "meten" staat parkeren.
# Anders snoepen die de plekken van deze ronde op en meet je een fout die er
# niet is.
for rij in db.get_benaderingen(stand=("adres", "meten")):
    db.zet_benadering(rij["webshop_url"], stand="afgevallen")

WINKELS = [f"https://dubbeltest{i}.nl" for i in range(1, 6)]
for u in WINKELS:
    db.zet_benadering(u, stand="afgevallen")
db.voeg_benaderingen_toe([(u, None, "NL", None) for u in WINKELS])
for u in WINKELS:
    db.zet_benadering(u, stand="adres", email="info@dubbeltest.nl", afgemeld=False)
db.zet_instelling("metingen_per_ronde", 5)


def van_ons(lijst):
    return sorted(u for u in lijst if u in WINKELS)


print("\n== ronde 1: de winkels gaan de meting in ==")
eerste = van_ons(benadering.te_meten(al_gemeten=set()))
zo("vijf ingepland", len(eerste), 5)
benadering.markeer_in_meting(eerste)

print("\n== ronde 2, terwijl de meting nog loopt ==")
# Dit is de hele reden dat dit bestand bestaat. Komt hier iets uit, dan wordt
# er een tweede keer betaald voor een meting die al loopt.
zo("wordt NIET opnieuw ingepland", van_ons(benadering.te_meten(al_gemeten=set())), [])

print("\n== ronde 3, de meting is klaar ==")
zo("nog steeds niets in te plannen",
   van_ons(benadering.te_meten(al_gemeten=set(WINKELS))), [])
standen = [db.get_benadering(u)["stand"] for u in WINKELS]
zo("alle vijf staan op gemeten", sorted(set(standen)), ["gemeten"])

print("\n== een meting die onderweg omgevallen is ==")
db.zet_benadering(WINKELS[0], stand="meten", meting_gestart=True)
conn = db._get_connection()
with conn, conn.cursor() as cur:
    cur.execute("UPDATE benadering SET meting_gestart_op = now() - interval '%s hours' "
                "WHERE webshop_url = %%s" % (benadering.METING_VASTGELOPEN_NA_UUR + 1),
                (WINKELS[0],))
conn.close()
zo("wordt na de wachttijd opnieuw opgepakt",
   van_ons(benadering.te_meten(al_gemeten=set())), [WINKELS[0]])

print("\n== een meting die pas net begonnen is ==")
db.zet_benadering(WINKELS[1], stand="meten", meting_gestart=True)
zo("blijft met rust", WINKELS[1] in benadering.te_meten(al_gemeten=set()), False)

print("\n== de ronde markeert VOORDAT hij betaalt ==")
bron = open(os.path.join(APP, "app.py")).read()
markeer = bron.find("benadering.markeer_in_meting(klaar_te_meten)")
inplannen = bron.find("_demo_inplannen(klaar_te_meten")
zo("markeer_in_meting staat in de ronde", markeer > 0, True)
zo("en staat VOOR het inplannen", markeer < inplannen, True)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
