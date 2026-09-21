"""Stap 71: wat het privacybeleid over bewaren belooft, gebeurt ook echt.

WAAROM DEZE TEST BESTAAT

Het privacybeleid noemt twaalf maanden voor de gratis check en de gratis
zichtbaarheidstest. Tot 21 september verwijderde geen enkele regel code iets.
Een controle van het beleid tegen de code vond dat. Deze test draait tegen een
echte database en kijkt of het oude weg is, het nieuwe blijft, en wat bewust
moet blijven (het adres van wie het vinkje zette, rapporten van klanten) ook
echt blijft.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import db  # noqa: E402

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


def sql(opdracht, waarden=(), een=False):
    conn = db._get_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(opdracht, waarden or None)
            uit = cur.fetchone() if een else None
    conn.close()
    return uit


def opruimen():
    sql("DELETE FROM gratis_scans WHERE webshop_url LIKE 'https://bt-%'")
    sql("DELETE FROM zichtbaarheidstests WHERE webshop_url LIKE 'https://bt-%'")
    sql("DELETE FROM rapporten WHERE webshop_url LIKE 'https://bt-%'")
    sql("DELETE FROM klanten WHERE webshop_url LIKE 'https://bt-%'")


db.init_db()
opruimen()

OUD = "now() - interval '13 months'"
NIEUW = "now() - interval '2 months'"

sql(f"INSERT INTO gratis_scans (webshop_url, score, gedaan_op) VALUES ('https://bt-oud.nl', 50, {OUD})")
sql(f"INSERT INTO gratis_scans (webshop_url, score, gedaan_op) VALUES ('https://bt-nieuw.nl', 50, {NIEUW})")
for naam, vink, wanneer in (("oud-zonder", False, OUD), ("oud-met", True, OUD),
                            ("nieuw-zonder", False, NIEUW)):
    sql(f"""INSERT INTO zichtbaarheidstests (webshop_url, email, status, resultaat,
            nieuwsbrief_akkoord, aangevraagd_op)
            VALUES ('https://bt-{naam}.nl', '{naam}@bt-test.nl', 'klaar', '{{"x": 1}}',
                    {vink}, {wanneer})""")
sql(f"""INSERT INTO rapporten (token, type, webshop_url, score, checks, aangemaakt_op)
        VALUES ('bt-demo', 'demo', 'https://bt-demo.nl', 40, '[]', {OUD})""")
sql(f"""INSERT INTO rapporten (token, type, webshop_url, email, score, checks, aangemaakt_op)
        VALUES ('bt-klant', 'monitoring', 'https://bt-klant.nl', 'k@bt-test.nl', 40, '[]', {OUD})""")
db.get_or_create_klant("https://bt-klant.nl", "k@bt-test.nl")

print("\n== DE OPRUIMING ==")
uit = db.ruim_verlopen_gegevens(12)
print(f"  verslag: {uit}")

klopt("een gratis check van dertien maanden oud is weg",
      sql("SELECT 1 FROM gratis_scans WHERE webshop_url = 'https://bt-oud.nl'", een=True) is None)
klopt("een van twee maanden blijft",
      sql("SELECT 1 FROM gratis_scans WHERE webshop_url = 'https://bt-nieuw.nl'", een=True))
klopt("een oude test zonder vinkje is helemaal weg, met het adres",
      sql("SELECT 1 FROM zichtbaarheidstests WHERE email = 'oud-zonder@bt-test.nl'", een=True) is None)
r = sql("SELECT email, resultaat FROM zichtbaarheidstests WHERE email = 'oud-met@bt-test.nl'", een=True)
klopt("een oude test met vinkje houdt het adres (tot afmelden)", r is not None)
klopt("maar de uitslag is weg", r is not None and r[1] is None)
klopt("een recente test blijft heel",
      sql("SELECT resultaat FROM zichtbaarheidstests WHERE email = 'nieuw-zonder@bt-test.nl'",
          een=True))
klopt("een oud rapport zonder klant is weg",
      sql("SELECT 1 FROM rapporten WHERE token = 'bt-demo'", een=True) is None)
klopt("een oud rapport van een klant blijft (dat gebeurt met de hand)",
      sql("SELECT 1 FROM rapporten WHERE token = 'bt-klant'", een=True))

print("\n== HET DRAAIT ELKE NACHT, EN HET BELEID ZEGT HET EERLIJK ==")
klopt("de nachtronde roept het aan", "db.ruim_verlopen_gegevens(12)" in lees("onderhoud.py"))
pb = lees("templates/privacybeleid.html")
klopt("het beleid zegt dat gratis uitslagen vanzelf verdwijnen",
      "deleted automatically once their twelve months are up" in pb)
klopt("en eerlijk dat oud-klanten nog met de hand gaan", "still delete by hand" in pb)
klopt("de oude zin 'being built' is weg", "being built" not in pb)

opruimen()
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: wat het privacybeleid belooft over bewaren, gebeurt.")
