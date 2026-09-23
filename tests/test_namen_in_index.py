"""Namen en landen in de openbare index, uit wat AI zelf zei.

WAAROM DEZE TEST BESTAAT

Op 23 september keek Nino naar de ranglijst elektronica. Daar stond
"https://mediamarkt.nl" op plaats 1, "https://expert.nl" op plaats 7, en op
plaats 6 amazon.de, in de NEDERLANDSE ranglijst.

Twee oorzaken:
- van veel winkels op de lijst hadden wij alleen het webadres, geen naam, en
  dan toonde de pagina het ruwe adres. Terwijl AI de naam in elk antwoord
  gewoon noemt ("MediaMarkt");
- een domein dat geen .nl of .be was, viel terug op Nederland. Ook .de.

Deze test zet een echte meetronde in de database, laat de nachtelijke
herberekening lopen (die kost niets, het zijn de bewaarde antwoorden) en kijkt
of de namen er daarna staan, of amazon.de uit de Nederlandse lijst is, en of
een naam die er al stond blijft staan.
"""
import json
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import categoriemeting  # noqa: E402
import db  # noqa: E402

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


CAT = "ni-testelektronica"


def opruimen():
    sql("DELETE FROM categorie_uitkomsten WHERE categorie = %s", (CAT,))
    sql("DELETE FROM categorie_antwoorden WHERE categorie = %s", (CAT,))
    sql("DELETE FROM categorie_rondes WHERE categorie = %s", (CAT,))
    sql("DELETE FROM benadering WHERE categorie = %s", (CAT,))


db.init_db()
opruimen()

# Drie winkels: een zonder naam, een met een webadres als naam, en een met een
# naam die wij met de hand kozen en die dus moet blijven staan. Plus amazon.de,
# die als Nederland op de lijst kwam.
for url, naam, land in (("https://mediamarkt.nl", None, "NL"),
                        ("https://expert.nl", "https://expert.nl", "NL"),
                        ("https://coolblue.nl", "Coolblue (met de hand)", "NL"),
                        ("https://amazon.de", "Amazon.de", "NL")):
    sql("INSERT INTO benadering (webshop_url, naam, land, categorie, soort) "
        "VALUES (%s, %s, %s, %s, 'winkel')", (url, naam, land, CAT))

ronde = sql("INSERT INTO categorie_rondes (categorie, vragen, winkels, afgerond_op) "
            "VALUES (%s, 2, 4, now()) RETURNING id", (CAT,), een=True)[0]
for genoemde in (
    {"winkel_kon_genoemd": True, "aanbevolen": ["MediaMarkt"],
     "winkels": [{"naam": "MediaMarkt", "positie": 1}, {"naam": "Expert", "positie": 2},
                 {"naam": "Coolblue", "positie": 3}, {"naam": "Amazon.de", "positie": 4}]},
    {"winkel_kon_genoemd": True, "aanbevolen": [],
     "winkels": [{"naam": "MediaMarkt", "positie": 1}, {"naam": "Expert", "positie": 2}]},
):
    sql("""INSERT INTO categorie_antwoorden
           (ronde, categorie, vraag, model, antwoord, winkel_kon_genoemd, genoemde_winkels)
           VALUES (%s, %s, 'v', 'm', 'a', TRUE, %s)""", (ronde, CAT, json.dumps(genoemde)))

print("\n== DE NACHTELIJKE HERBEREKENING ==")
uit = categoriemeting.herbereken_ranglijst(CAT)
klopt(f"hij draait zonder fout ({uit.get('fout')})", not uit.get("fout"))


def naam(url):
    return sql("SELECT naam FROM benadering WHERE webshop_url = %s", (url,), een=True)[0]


def land(url):
    return sql("SELECT land FROM benadering WHERE webshop_url = %s", (url,), een=True)[0]


klopt(f"een winkel zonder naam krijgt de naam die AI gebruikte (kreeg {naam('https://mediamarkt.nl')!r})",
      naam("https://mediamarkt.nl") == "MediaMarkt")
klopt(f"een webadres als naam wordt vervangen (kreeg {naam('https://expert.nl')!r})",
      naam("https://expert.nl") == "Expert")
klopt("een naam die er al stond blijft staan",
      naam("https://coolblue.nl") == "Coolblue (met de hand)")
klopt(f"amazon.de hoort bij Duitsland (kreeg {land('https://amazon.de')!r})",
      land("https://amazon.de") == "DE")

nl = [r["webshop_url"] for r in db.ranglijst_per_land(CAT, "nl")["rijen"]]
klopt(f"en staat dus niet in de Nederlandse ranglijst (kreeg {nl})",
      "https://amazon.de" not in nl and "https://mediamarkt.nl" in nl)

print("\n== DE PAGINA TOONT NOOIT EEN KAAL WEBADRES ALS NAAM ==")
sjabloon = lees("templates/index_categorie.html")
klopt("zonder naam komt het domein zonder https", "r.naam.startswith('http')" in sjabloon)
klopt("de oude terugval op het volledige adres is weg", "r.naam or r.webshop_url" not in sjabloon)

print("\n== HET LAND UIT HET DOMEIN ==")
for domein, verwacht in (("winkel.nl", "NL"), ("winkel.be", "BE"), ("amazon.de", "DE"),
                         ("shop.co.uk", "GB"), ("winkel.com", "NL")):
    klopt(f"{domein} is {verwacht}", categoriemeting._land_bij_domein(domein) == verwacht)
klopt("een algemene extensie zonder standaard geeft niets (geen gok)",
      categoriemeting._land_bij_domein("winkel.com", standaard=None) is None)

opruimen()
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de index toont namen, en een Duitse winkel staat niet in de Nederlandse lijst.")
