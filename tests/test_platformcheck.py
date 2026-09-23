"""Stap 74: de bestaande lijst een keer nakijken op platforms.

WAAROM DEZE TEST BESTAAT

Sinds 23 september kent Krillo het verschil tussen een winkel en een platform
(marktplaats, portaal, vergelijkingssite). Nieuwe winkels worden daar meteen op
beoordeeld. Maar de ruim duizend winkels die er al stonden niet: zo stond
Amazon gewoon op plaats 6 in de ranglijst elektronica. Deze stap kijkt ze
elke nacht in stukjes na, de zichtbaarste eerst.

Getest tegen een echte database, met het model vervangen door een vaste
uitkomst: wordt een platform echt als platform opgeslagen, valt het uit de
ranglijst, wordt niemand twee keer betaald nagekeken, en gebeurt er niets als
het model niet antwoordt.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import db  # noqa: E402
import onderhoud  # noqa: E402

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


def sql(opdracht, waarden=None, een=False):
    conn = db._get_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(opdracht, waarden)
            uit = cur.fetchone() if een else None
    conn.close()
    return uit


CAT = "pc-testcategorie"
db.init_db()
sql("DELETE FROM benadering WHERE categorie = %s", (CAT,))
# Alles wat er al stond even als nagekeken markeren, zodat deze test alleen
# zijn eigen winkels ziet.
sql("UPDATE benadering SET platform_gecheckt_op = now() WHERE platform_gecheckt_op IS NULL")
for url in ("https://amazon-test.nl", "https://gewone-winkel.nl"):
    sql("INSERT INTO benadering (webshop_url, categorie, soort) VALUES (%s, %s, 'winkel')",
        (url, CAT))

aanroepen = []


def nep_model(groep):
    aanroepen.append([w["webshop_url"] for w in groep])
    return {"https://amazon-test.nl": "platform", "https://gewone-winkel.nl": "winkel"}


onderhoud.opschonen.merken_in = nep_model
onderhoud.kosten.mag_doorgaan = lambda **k: {"mag": True}

print("\n== DE EERSTE NACHT ==")
v = onderhoud.stap_platformcheck(100)
print(f"  verslag: {v}")
soort = sql("SELECT soort FROM benadering WHERE webshop_url = 'https://amazon-test.nl'", een=True)[0]
klopt("het platform staat nu als platform", soort == "platform")
klopt("de winkel blijft winkel",
      sql("SELECT soort FROM benadering WHERE webshop_url = 'https://gewone-winkel.nl'",
          een=True)[0] == "winkel")
klopt("allebei als nagekeken vastgelegd",
      sql("SELECT count(*) FROM benadering WHERE categorie = %s "
          "AND platform_gecheckt_op IS NOT NULL", (CAT,), een=True)[0] == 2)
klopt("het verslag telt een platform", v["platforms"] == 1)

print("\n== DE TWEEDE NACHT KOST NIETS ==")
aanroepen.clear()
onderhoud.stap_platformcheck(100)
klopt("niemand wordt twee keer nagekeken", aanroepen == [])

print("\n== ZONDER ANTWOORD VAN HET MODEL WORDT NIETS VASTGELEGD ==")
sql("INSERT INTO benadering (webshop_url, categorie, soort) VALUES "
    "('https://nog-een.nl', %s, 'winkel')", (CAT,))
onderhoud.opschonen.merken_in = lambda groep: {}
onderhoud.stap_platformcheck(100)
klopt("dan komt hij de volgende nacht gewoon terug",
      sql("SELECT platform_gecheckt_op FROM benadering WHERE webshop_url = 'https://nog-een.nl'",
          een=True)[0] is None)

print("\n== HET HANGT IN DE NACHTRONDE, VOOR HET HERBEREKENEN ==")
bron = lees("onderhoud.py")
klopt("de nachtronde roept het aan", 'verslag["platformcheck"] = stap_platformcheck()' in bron)
klopt("en dat gebeurt voor het herberekenen",
      bron.index('verslag["platformcheck"]') < bron.index('verslag["herberekenen"]'))
klopt("de ranglijst laat alles wat geen winkel is weg",
      'if soort_van.get(doel, "winkel") != "winkel":' in lees("categoriemeting.py"))

sql("DELETE FROM benadering WHERE categorie = %s", (CAT,))
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de bestaande lijst wordt een keer nagekeken op platforms.")
