"""Bewaakt dat een demorapport ook echt bewaard wordt.

Dit ging maandenlang mis zonder dat iemand het kon zien. De kolom email in de
rapportentabel stond op NOT NULL, terwijl een demo geen klant heeft en dus geen
e-mailadres. Elke poging om een demorapport te bewaren mislukte, met alleen een
regel in de logboeken van Render.

Het gevolg was groter dan het klinkt: 55 winkels met beoordeelde antwoorden, nul
demorapporten, een lege benchmarkpagina, geen eigen cijfer op de homepage en geen
persverhaal. Er is dagenlang betaald voor metingen waarvan de uitkomst nergens
bewaard werd.
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import APP  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

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

print("\n== een demo zonder e-mailadres wordt bewaard ==")
token = db.save_report("demo", "https://demobewaartest.nl", None, 61,
                       [{"id": "robots", "titel": "Robots", "status": "ok", "score": 1}])
klopt("er komt een token terug", bool(token))
zo("en het rapport is terug te vinden",
   (db.get_report(token) or {}).get("type"), "demo")

print("\n== de kolom mag echt leeg zijn ==")
# De reparatie zit in init_db en moet ook werken op een database waar de kolom
# nog op NOT NULL staat, want dat is de situatie op de echte server.
conn = db._get_connection()
with conn.cursor() as cur:
    cur.execute("""SELECT is_nullable FROM information_schema.columns
                    WHERE table_name = 'rapporten' AND column_name = 'email'""")
    nullable = cur.fetchone()[0]
conn.close()
zo("email mag leeg zijn", nullable, "YES")

print("\n== de benchmark ziet de demo ==")
regels = db.benchmark_regels()
klopt("er staat minstens een regel in", len(regels) >= 1)
klopt("onze winkel zit erbij",
      any(r["webshop_url"] == "https://demobewaartest.nl" for r in regels))

print("\n== de diagnose telt hem mee ==")
d = db.benchmark_diagnose()
klopt("er is minstens een demorapport", d["demorapporten"] >= 1)
klopt("over minstens een winkel", d["winkels_met_demo"] >= 1)

print("\n== een mislukte opslag valt op in plaats van stil te blijven ==")
# De aanroeper negeerde de uitkomst van save_report volledig. Daardoor liep de
# meting gewoon door, kwam de winkel op "gemeten" te staan, en bleef de
# benchmark leeg zonder dat er ergens iets over te zien was.
bron = open(os.path.join(APP, "app.py")).read()
klopt("de demo kijkt de uitkomst van het opslaan na",
      'if not db.save_report("demo"' in bron)
# De tekst staat in de code over twee regels verdeeld, dus op een stuk zoeken.
klopt("en meldt het als het misging", "kon niet bewaard worden" in bron)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
