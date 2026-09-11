"""Test van de herkomstregistratie tegen een echte Postgres.

Wat hier fout kan gaan zonder dat je het merkt: de omzet komt wel binnen maar
belandt niet bij de juiste bron, of een bron die alleen omzet heeft en geen
scans valt uit de tabel. Dan lijkt een partner nul klanten op te leveren.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

import db

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen != verwacht:
        fouten.append(f"FOUT: {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
    else:
        print(f"  ok  {omschrijving}")


conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()

print("\n== de tabellen worden aangemaakt, inclusief de nieuwe bronkolom ==")
db.init_db()
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("""SELECT column_name FROM information_schema.columns
                        WHERE table_name = 'facturen' ORDER BY column_name""")
        kolommen = [r[0] for r in cur.fetchall()]
conn.close()
zo("facturen heeft een bronkolom", "bron" in kolommen, True)

print("\n== init_db draait twee keer zonder te klappen ==")
db.init_db()
zo("tweede keer ging goed", True, True)

print("\n== een factuur met en zonder bron ==")
# maak_factuur geeft nu {"factuurnummer": ..., "nieuw": True/False} terug. Dat
# "nieuw" is er omdat de factuurmail er onvoorwaardelijk achteraan ging, en bij
# een mislukte levering komt Mollie meerdere keren langs: dan kreeg iemand drie
# keer dezelfde factuur voor iets wat hij niet had.
u1 = db.maak_factuur("tr_A", "a@shop.nl", "Shop A", "Audit", 79.00, bron="webwinkelkeur")
u2 = db.maak_factuur("tr_B", "b@shop.nl", "Shop B", "Audit", 79.00, bron=None)
u3 = db.maak_factuur("tr_C", "c@shop.nl", "Shop C", "Monitoring", 39.00, bron="webwinkelkeur")
n1, n2, n3 = u1["factuurnummer"], u2["factuurnummer"], u3["factuurnummer"]
zo("drie verschillende factuurnummers", len({n1, n2, n3}), 3)
zo("alle drie zijn nieuw", [u1["nieuw"], u2["nieuw"], u3["nieuw"]], [True, True, True])
opnieuw = db.maak_factuur("tr_A", "a@shop.nl", "Shop A", "Audit", 79.00, bron="anders")
zo("dezelfde betaling geeft hetzelfde nummer", opnieuw["factuurnummer"], n1)
zo("maar hij is dan NIET nieuw, dus er gaat geen tweede factuurmail uit",
   opnieuw["nieuw"], False)

conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("SELECT bron FROM facturen WHERE payment_id = 'tr_A'")
        zo("de bron staat erbij", cur.fetchone()[0], "webwinkelkeur")
        cur.execute("SELECT bron FROM facturen WHERE payment_id = 'tr_B'")
        zo("geen bron blijft leeg, niet 'None'", cur.fetchone()[0], None)
        # Een tweede aanroep met een andere bron mag de eerste niet overschrijven.
        cur.execute("SELECT bron FROM facturen WHERE payment_id = 'tr_A'")
        zo("bron wordt niet overschreven bij een herhaling", cur.fetchone()[0], "webwinkelkeur")

print("\n== gratis scans erbij, ook van een bron die niets opleverde ==")
with conn:
    with conn.cursor() as cur:
        for bron, aantal in [("webwinkelkeur", 5), ("linkedin", 12), (None, 3)]:
            for _ in range(aantal):
                cur.execute("""INSERT INTO gratis_scans (webshop_url, score, gelukt, herkomst)
                               VALUES ('https://x.nl', 60, true, %s)""", (bron,))
conn.close()

print("\n== het overzicht per bron ==")
ov = db.scanoverzicht(dagen=30)
per_bron = {r["bron"]: r for r in ov["per_bron"]}
zo("webwinkelkeur staat erin", "webwinkelkeur" in per_bron, True)
zo("scans van webwinkelkeur", per_bron["webwinkelkeur"]["scans"], 5)
zo("klanten van webwinkelkeur", per_bron["webwinkelkeur"]["klanten"], 2)
zo("omzet van webwinkelkeur", float(per_bron["webwinkelkeur"]["omzet"]), 118.00)
zo("linkedin leverde bezoekers maar geen klanten", per_bron["linkedin"]["klanten"], 0)
zo("linkedin omzet is nul en niet None", float(per_bron["linkedin"]["omzet"]), 0.0)
zo("scans zonder bron heten rechtstreeks", per_bron["rechtstreeks"]["scans"], 3)
zo("de factuur zonder bron telt bij rechtstreeks", per_bron["rechtstreeks"]["klanten"], 1)

print("\n== een bron met alleen omzet en geen enkele scan valt niet weg ==")
db.maak_factuur("tr_D", "d@shop.nl", "Shop D", "Audit", 79.00, bron="becom")["factuurnummer"]
per_bron = {r["bron"]: r for r in db.scanoverzicht(dagen=30)["per_bron"]}
zo("becom staat er toch in", "becom" in per_bron, True)
zo("becom heeft nul scans", per_bron["becom"]["scans"], 0)
zo("becom heeft wel een klant", per_bron["becom"]["klanten"], 1)

print("\n== de oude tabel blijft ook werken ==")
zo("per_herkomst bestaat nog", len(db.scanoverzicht(dagen=30)["per_herkomst"]) >= 2, True)

print("\n== het winkelplatform ==")
db.zet_platform("https://winkel.nl", "WooCommerce")
zo("platform opgeslagen", (db.get_winkelprofiel("https://winkel.nl") or {}).get("platform"), "WooCommerce")
db.zet_platform("https://winkel.nl", None)
zo("niets overschrijft het bestaande platform niet",
   (db.get_winkelprofiel("https://winkel.nl") or {}).get("platform"), "WooCommerce")
db.zet_platform("https://winkel.nl", "Shopify")
zo("een nieuw platform overschrijft wel",
   (db.get_winkelprofiel("https://winkel.nl") or {}).get("platform"), "Shopify")
zo("onbekende winkel geeft geen platform",
   (db.get_winkelprofiel("https://bestaatniet.nl") or {}).get("platform"), None)

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
