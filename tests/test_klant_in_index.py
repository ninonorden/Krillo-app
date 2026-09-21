"""Een betalende klant komt in de index, en krijgt nooit de benaderingsmail.

WAAROM DEZE TEST BESTAAT

Gevonden op 21 september bij het nakijken van de Shopify-prijskaart. Watch
belooft "your rank every month, in your category and your country". Die
positie komt uit de maandmeting van een categorie, en een winkel krijgt alleen
een categorie als hij op de winkellijst (benadering) staat. Een klant die daar
niet al op stond, bijvoorbeeld iemand die via de Shopify-app binnenkwam, kreeg
dus nooit een categorie en nooit een positie. Hij betaalde voor iets dat niet
kon gebeuren.

Tegelijk is die winkellijst ook de lijst voor de koude benaderingsmail. Een
klant mag daar dus op staan, maar mag nooit in de mailrij terechtkomen.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
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


def rij(url):
    conn = db._get_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT stand, categorie, afgemeld, gemaild_op, land "
                        "FROM benadering WHERE webshop_url = %s", (url,))
            r = cur.fetchone()
    conn.close()
    return r


def opruimen():
    conn = db._get_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM benadering WHERE webshop_url LIKE 'https://kii-%'")
    conn.close()


db.init_db()
opruimen()

print("\n== EEN NIEUWE KLANT KOMT OP DE LIJST ==")
klopt("het lukt", db.zet_klant_op_lijst("https://kii-nieuw.nl", land="NL"))
r = rij("https://kii-nieuw.nl")
klopt("hij staat erop", r is not None)
klopt("met stand klant", r and r[0] == "klant")
klopt("nog zonder categorie, zodat het nachtelijk indelen hem oppakt", r and r[1] is None)
klopt("met zijn land", r and r[4] == "NL")
zonder = [w["webshop_url"] for w in db.winkels_zonder_categorie(5000)]
klopt("en het indelen ziet hem", "https://kii-nieuw.nl" in zonder)

print("\n== HIJ KOMT NOOIT IN DE MAILRIJ ==")
for stand in ("nieuw", "geen_adres", "adres", "meten", "gemeten"):
    rij_stand = [w["webshop_url"] for w in db.get_benaderingen(stand=stand, limiet=5000)]
    klopt(f"niet bij stand {stand!r}", "https://kii-nieuw.nl" not in rij_stand)

print("\n== STOND HIJ AL OP DE LIJST ==")
db.voeg_benadering_toe("https://kii-oud.nl", naam="Oud", land="NL")
db.zet_klant_op_lijst("https://kii-oud.nl", land="NL")
klopt("nooit gemaild: hij gaat naar klant", rij("https://kii-oud.nl")[0] == "klant")

db.voeg_benadering_toe("https://kii-gemaild.nl", naam="Gemaild", land="NL")
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("UPDATE benadering SET stand = 'gemaild', gemaild_op = now(), "
                    "afgemeld = TRUE WHERE webshop_url = 'https://kii-gemaild.nl'")
conn.close()
db.zet_klant_op_lijst("https://kii-gemaild.nl", land="NL")
r = rij("https://kii-gemaild.nl")
klopt("al gemaild: zijn geschiedenis blijft staan", r[0] == "gemaild")
# Afgemeld betekende "geen post meer". Maar hij is nu klant, en een afgemelde
# winkel telt niet mee in de index (categorieen_om_te_meten filtert erop).
klopt("en hij telt weer mee in de index", r[2] is False)

print("\n== ELKE NIEUWE KLANT, EN DE WEKELIJKSE RONDE ALS VANGNET ==")
bron = lees("app.py")
klopt("bij elke nieuwe klant", "_zet_in_index(webshop_url)" in bron)
klopt("en in de wekelijkse ronde", '_zet_in_index(c["webshop_url"])' in bron)

opruimen()
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: een betalende klant komt in de index en krijgt geen koude mail.")
