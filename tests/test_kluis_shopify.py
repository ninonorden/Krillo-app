"""Bewaakt dat Shopify-sleutels versleuteld in de database staan.

Met zo'n sleutel kan je in de winkel van een ander schrijven: producten,
pagina's, bestanden. Ze stonden in platte tekst. Lekt de database ooit, dan
heeft iemand schrijftoegang tot elke winkel die de app geinstalleerd heeft, en
dat is een heel andere ramp dan een gelekte lijst met webadressen.

Twee dingen worden hier even hard bewaakt:
- dat de sleutel echt niet leesbaar in de database staat
- dat de app blijft draaien als KLUIS_SLEUTEL nog niet ingesteld is
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

TESTSLEUTEL = "een-heel-lange-testsleutel-van-minstens-32-tekens"
os.environ["KLUIS_SLEUTEL"] = TESTSLEUTEL

import db  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


db.init_db()
WINKEL = "kluistest.myshopify.com"


def ruw(veld="toegangssleutel"):
    """Wat er ECHT in de database staat, zonder de kluis ertussen."""
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute(f"SELECT {veld} FROM shopify_winkels WHERE winkel = %s", (WINKEL,))
        rij = cur.fetchone()
    conn.close()
    return rij[0] if rij else None


print("\n== een nieuwe winkel wordt versleuteld opgeslagen ==")
db.bewaar_shopify_winkel(WINKEL, "shpat_geheim123", geldig_seconden=3599,
                         verversleutel="shprt_geheim456",
                         verversleutel_seconden=7775999,
                         webshop_url="https://kluistest.nl")
klopt("de toegangssleutel staat NIET leesbaar in de database",
      "shpat_geheim123" not in (ruw() or ""))
klopt("de verversleutel ook niet",
      "shprt_geheim456" not in (ruw("verversleutel") or ""))
klopt("er staat een merkje voor", (ruw() or "").startswith("kluis1:"))

print("\n== maar de app leest hem gewoon terug ==")
rij = db.get_shopify_winkel(WINKEL)
zo("toegangssleutel", rij["toegangssleutel"], "shpat_geheim123")
zo("verversleutel", rij["verversleutel"], "shprt_geheim456")

print("\n== een sleutel die nog in platte tekst staat blijft werken ==")
# Zo staan de winkels erin die er al waren voordat dit gebouwd werd.
conn = db._get_connection()
with conn, conn.cursor() as cur:
    cur.execute("UPDATE shopify_winkels SET toegangssleutel = 'shpat_oud_plat', "
                "verversleutel = 'shprt_oud_plat' WHERE winkel = %s", (WINKEL,))
conn.close()
zo("wordt gewoon gelezen",
   db.get_shopify_winkel(WINKEL)["toegangssleutel"], "shpat_oud_plat")

print("\n== en wordt bij het opstarten alsnog weggeborgen ==")
db._sluit_bestaande_shopify_sleutels_weg()
klopt("staat nu versleuteld", "shpat_oud_plat" not in (ruw() or ""))
zo("en is nog steeds leesbaar voor de app",
   db.get_shopify_winkel(WINKEL)["toegangssleutel"], "shpat_oud_plat")
zo("een tweede opstart doet niets extra",
   db._sluit_bestaande_shopify_sleutels_weg(), 0)

print("\n== het verversen van het sleutelpaar versleutelt ook ==")
db.vervang_shopify_sleutelpaar(WINKEL, "shpat_nieuw", 3599, "shprt_nieuw", 7775999)
klopt("niet leesbaar in de database", "shpat_nieuw" not in (ruw() or ""))
zo("wel leesbaar voor de app",
   db.get_shopify_winkel(WINKEL)["toegangssleutel"], "shpat_nieuw")

print("\n== de lijst met alle winkels ontsleutelt ook ==")
alle = [w for w in db.get_shopify_winkels(alleen_actief=False)
        if w["winkel"] == WINKEL]
klopt("de winkel staat in de lijst", bool(alle))
zo("met een leesbare sleutel", alle[0]["toegangssleutel"] if alle else None,
   "shpat_nieuw")

print("\n== zonder KLUIS_SLEUTEL blijft de app draaien ==")
# Dit is de belangrijkste controle van dit bestand. Een nieuwe versie die de app
# laat omvallen omdat er een instelling ontbreekt is erger dan het probleem dat
# hij oplost.
ZONDER = "zonderkluis.myshopify.com"
del os.environ["KLUIS_SLEUTEL"]
zo("opslaan lukt nog",
   db.bewaar_shopify_winkel(ZONDER, "shpat_plat", geldig_seconden=3599,
                            verversleutel="shprt_plat",
                            verversleutel_seconden=7775999,
                            webshop_url="https://zonderkluis.nl"), True)
zo("en teruglezen ook",
   db.get_shopify_winkel(ZONDER)["toegangssleutel"], "shpat_plat")

print("\n== een versleutelde sleutel zonder de kluissleutel geeft None ==")
# Bewust None en niet iets halfs: met een kapotte sleutel naar Shopify gaan
# levert alleen verwarrende foutmeldingen op.
zo("geen halve sleutel", db.get_shopify_winkel(WINKEL)["toegangssleutel"], None)
os.environ["KLUIS_SLEUTEL"] = TESTSLEUTEL
zo("en met de sleutel weer gewoon leesbaar",
   db.get_shopify_winkel(WINKEL)["toegangssleutel"], "shpat_nieuw")

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
