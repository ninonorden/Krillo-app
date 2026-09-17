"""De openbare index: per categorie een ranglijst op krillo.nl.

WAAROM DEZE PAGINA'S HET BELANGRIJKSTE ZIJN DAT ER NU BIJ KOMT

Krillo heeft geen advertentiebudget en doet geen verkoopgesprekken. De index is
het kanaal: een winkelier die zoekt of AI hem noemt, vindt zijn categorie, ziet
wie er wel genoemd wordt, en heeft dan pas een reden om op de knop te drukken.
Dat kost ons niets per bezoeker.

WAT DEZE TEST BEWAAKT

- Een categorie die nooit gemeten is heeft geen pagina. Een lege ranglijst
  publiceren zou beweren dat er gemeten is terwijl dat niet zo is.
- De namen van winkels die bij GEEN ENKELE vraag genoemd werden staan er niet
  op. Het aantal wel. Meten wat er niet gebeurt is eerlijk; iemand bij naam op
  een lijst van niet-genoemden zetten is iets anders, en dat doen wij niet.
- De gestructureerde gegevens zijn geldige JSON. Op 16 september stond er een
  parseerfout in de veelgestelde vragen doordat er aanhalingstekens in een
  waarde zaten. Dat was onzichtbaar tot Google het meldde.
- De pagina staat in de sitemap, met de meetdatum van die categorie.
- De pagina noemt de meetdatum en de gestelde vragen. Een ranglijst zonder
  datum en zonder methode is een ranglijst die niemand kan narekenen.
"""
import json
import os
import re
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

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

CAT = "openbare-index-test"
GENOEMD = "https://welgenoemd.nl"
OOK = "https://ookgenoemd.nl"
STIL = "https://nooitgenoemd.nl"
ALLE = [GENOEMD, OOK, STIL] + [f"https://vuller{n}.nl" for n in range(1, 4)]


def opruimen():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM benadering WHERE webshop_url = ANY(%s)", (ALLE,))
        cur.execute("DELETE FROM categorie_antwoorden WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_uitkomsten WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_rondes WHERE categorie = %s", (CAT,))
    conn.close()


opruimen()
for url in ALLE:
    db.voeg_benadering_toe(url, naam=url.replace("https://", ""), land="NL", branche="test")
    db.zet_categorie(url, CAT)

import app as krillo  # noqa: E402
krillo.app.config["TESTING"] = True
klant = krillo.app.test_client()

print("\n== zonder meting is er geen pagina ==")
antwoord = klant.get(f"/index/nl/{CAT}")
zo("een ongemeten categorie geeft 404", antwoord.status_code, 404)
klopt("met uitleg in plaats van een kale foutpagina",
      "nog niet gemeten" in antwoord.get_data(as_text=True))
overzicht = klant.get("/index/nl").get_data(as_text=True)
klopt("en hij staat niet in het overzicht", f"/index/nl/{CAT}" not in overzicht)

print("\n== na een meting staat hij er wel ==")
VRAAG_A = "waar koop ik online een testartikel"
VRAAG_B = "welke webshop verkoopt testartikelen"
ronde = db.start_categorie_ronde(CAT, 2, len(ALLE))
for vraag in (VRAAG_A, VRAAG_B):
    for model in ("model-een", "model-twee"):
        db.bewaar_categorie_antwoord(
            ronde, CAT, vraag, model, "antwoordtekst",
            {"winkel_kon_genoemd": True,
             "winkels": [{"naam": "welgenoemd.nl", "positie": 1}],
             "aanbevolen": ["welgenoemd.nl"]})
# Een vraag die niet meetelde hoort NIET op de openbare pagina te komen.
db.bewaar_categorie_antwoord(
    ronde, CAT, "wat is het beste merk testartikelen", "model-een", "tekst",
    {"winkel_kon_genoemd": False, "winkels": [], "aanbevolen": []})

db.bewaar_categorie_uitkomsten(ronde, CAT, [
    {"webshop_url": GENOEMD, "positie": 1, "genoemd": 2, "aanbevolen": 2, "beste_positie": 1},
    {"webshop_url": OOK, "positie": 2, "genoemd": 1, "aanbevolen": 0, "beste_positie": 2},
    {"webshop_url": STIL, "positie": 3, "genoemd": 0, "aanbevolen": 0, "beste_positie": None},
    {"webshop_url": ALLE[3], "positie": 4, "genoemd": 0, "aanbevolen": 0, "beste_positie": None},
    {"webshop_url": ALLE[4], "positie": 5, "genoemd": 0, "aanbevolen": 0, "beste_positie": None},
], 2)

pagina = klant.get(f"/index/nl/{CAT}")
zo("de pagina bestaat nu", pagina.status_code, 200)
tekst = pagina.get_data(as_text=True)
klopt("de genoemde winkel staat erop", "welgenoemd.nl" in tekst)
klopt("de tweede ook", "ookgenoemd.nl" in tekst)

print("\n== niet-genoemde winkels worden niet bij naam genoemd ==")
klopt("de stille winkel staat er niet bij naam op", "nooitgenoemd.nl" not in tekst)
klopt("maar het aantal staat er wel", "overige 3" in tekst)

print("\n== de methode staat erbij ==")
klopt("de meetdatum staat erop", "gemeten op" in tekst.lower())
klopt("de gestelde vragen staan erop", VRAAG_A in tekst and VRAAG_B in tekst)
klopt("de vraag die niet meetelde staat er niet op",
      "beste merk testartikelen" not in tekst)
klopt("welke assistenten er bevraagd zijn", "model-een" in tekst)
klopt("er staat dat niemand zich kan inkopen", "inkopen" in tekst)

print("\n== de gestructureerde gegevens zijn geldige JSON ==")
blokken = re.findall(
    r'<script type="application/ld\+json">(.*?)</script>', tekst, re.S)
zo("er staan twee blokken: de ranglijst en het kruimelpad", len(blokken), 2)
data = [json.loads(x) for x in blokken if json.loads(x)["@type"] == "ItemList"][0]
zo("het is een lijst", data["@type"], "ItemList")
zo("met twee winkels erin", data["numberOfItems"], 2)
zo("de eerste is de meest genoemde", data["itemListElement"][0]["url"], GENOEMD)
klopt("de stille winkel zit er ook hier niet in",
      STIL not in json.dumps(data))

print("\n== een land dat niet bestaat ==")
zo("geeft netjes 404", klant.get(f"/index/zz/{CAT}").status_code, 404)

print("\n== het overzicht en de sitemap ==")
overzicht = klant.get("/index/nl").get_data(as_text=True)
klopt("de categorie staat in het overzicht", f"/index/nl/{CAT}" in overzicht)
sitemap = klant.get("/sitemap.xml").get_data(as_text=True)
klopt("en in de sitemap", f"https://www.krillo.nl/index/nl/{CAT}" in sitemap)
klopt("het overzicht staat er ook in", "https://www.krillo.nl/index<" in sitemap)
klopt("met een lastmod erbij",
      re.search(r"/index/nl/" + CAT + r"</loc><lastmod>\d{4}-\d{2}-\d{2}", sitemap))

print("\n== robots houdt de index open en het beheer dicht ==")
robots = klant.get("/robots.txt").get_data(as_text=True)
klopt("beheer blijft dicht", "Disallow: /admin/" in robots)
klopt("de index wordt niet verboden", "Disallow: /index" not in robots)

print("\n== een te kleine categorie komt er niet op ==")
groot = [r["categorie"] for r in db.categorieen_per_land("nl", 99)]
klopt("vijf winkels is te weinig bij een minimum van negenennegentig",
      CAT not in groot)

opruimen()

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
