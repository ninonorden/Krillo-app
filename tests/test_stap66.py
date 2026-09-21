"""Stap 66: geen eigen wekelijkse AI-meting per klant meer, een bericht per maand.

WAAROM DEZE TEST BESTAAT

Tot 21 september deed Krillo twee dingen naast elkaar. De index mat elke
categorie een keer per maand en gaf elke winkel een positie. En daarnaast mat
de wekelijkse scan voor elke betalende klant nog eens apart of hij genoemd
werd, en stuurde hem daar elke week een mail over.

Dat botste. Twee metingen van dezelfde vraag gaven twee verschillende getallen
op hetzelfde dashboard, de klant kreeg een wekelijkse mail naast het
maandbericht uit meldingen.py (terwijl de rem daar juist zegt: hooguit een
bericht per veertien dagen), en elke klant kostte elke week AI-geld dat niets
toevoegde aan wat de index al wist.

Het besluit (stap 66): de positie komt alleen nog uit de index. De scan van
dertien punten op de site blijft wekelijks, want die kost niets en vindt
kapotte dingen. En de categorie van een betalende klant gaat voor bij de
nachtelijke meting, zodat zijn positie nooit ouder wordt dan nodig.

Deze test bewaakt dat de dubbele meting niet terugkomt, dat de scan zelf blijft
bestaan, en dat de klanttekst niet meer belooft dat we elke week meten.
"""
import os
import re
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import paginataal  # noqa: E402

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


def functie(bron, naam):
    """De tekst van een functie, van zijn def tot de volgende def op regelbegin."""
    m = re.search(rf"^def {naam}\(.*?(?=^def |\Z)", bron, flags=re.S | re.M)
    return m.group(0) if m else ""


def zonder_commentaar(tekst):
    """Commentaar en docstrings eruit. Die mogen de oude aanpak uitleggen."""
    tekst = re.sub(r'"""(.*?)"""', "", tekst, flags=re.S)
    return "\n".join(r for r in tekst.splitlines() if not r.strip().startswith("#"))


print("\n== DE WEKELIJKSE SCAN MEET NIET MEER ZELF ==")
scan = zonder_commentaar(functie(lees("app.py"), "_draai_wekelijkse_scans"))
klopt("de functie bestaat nog", "run_scan" in scan)
klopt("geen eigen AI-meting per klant", "_meet_en_beoordeel" not in scan)
klopt("geen wekelijkse mail", "send_weekly_update_email" not in scan)
klopt("het rapport wordt nog bewaard (daaraan zien we wie abonnee is)",
      'save_report' in scan and '"monitoring"' in scan)
klopt("Shopify wordt nog aangevuld", "_shopify_automatisch_aanvullen" in scan)

print("\n== DE EENMALIGE METING BIJ DE START BLIJFT ==")
# Een nieuwe klant moet meteen iets zien, ook als zijn categorie nog niet in de
# index zit. Die ene meting bij de eerste betaling is dus bewust gebleven.
klopt("_meet_en_beoordeel bestaat nog", "def _meet_en_beoordeel(" in lees("app.py"))

print("\n== DE CATEGORIE VAN EEN KLANT GAAT VOOR ==")
cat = functie(lees("db.py"), "categorieen_om_te_meten")
klopt("winkels worden uniek geteld", "count(DISTINCT b.webshop_url)" in cat)
klopt("klanten worden erbij gezocht", "LEFT JOIN klanten" in cat)
klopt("een categorie met een klant gaat eerst",
      "ORDER BY bool_or(k.klant_token IS NOT NULL) DESC" in cat)

print("\n== EN DAT GEBEURT OOK ECHT IN DE DATABASE ==")
# Hierboven staat alleen dat de tekst van de query klopt. Hier draait hij.
# Drie verzonnen categorieen met elk drie winkels:
#   s66-oud    : 40 dagen geleden gemeten, geen klant
#   s66-nooit  : nog nooit gemeten, geen klant
#   s66-klant  : 35 dagen geleden gemeten, met een betalende klant
# Zonder voorrang zou s66-nooit eerst gaan. Met voorrang gaat de klant eerst.
# En s66-oud heeft drie rondes gehad: telt hij zijn winkels dubbel, dan komt
# hij met drie winkels over een ondergrens van vijf.
import db  # noqa: E402
db.init_db()
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM benadering WHERE categorie LIKE 's66-%'")
        cur.execute("DELETE FROM categorie_rondes WHERE categorie LIKE 's66-%'")
        cur.execute("DELETE FROM klanten WHERE webshop_url LIKE 'https://s66-%'")
        for cat in ("s66-oud", "s66-nooit", "s66-klant"):
            for i in range(3):
                cur.execute("INSERT INTO benadering (webshop_url, categorie, soort) "
                            "VALUES (%s, %s, 'winkel')", (f"https://{cat}-{i}.nl", cat))
        for dagen in (40, 45, 50):
            cur.execute("INSERT INTO categorie_rondes (categorie, afgerond_op) "
                        "VALUES ('s66-oud', now() - %s * interval '1 day')", (dagen,))
        cur.execute("INSERT INTO categorie_rondes (categorie, afgerond_op) "
                    "VALUES ('s66-klant', now() - interval '35 days')")
db.get_or_create_klant("https://s66-klant-0.nl", "k@example.com")

rij = [r["categorie"] for r in db.categorieen_om_te_meten(3, 30)
       if r["categorie"].startswith("s66-")]
klopt(f"de klant gaat voor (kreeg {rij})", rij[:1] == ["s66-klant"])
klopt("daarna wat nog nooit gemeten is", rij[1:2] == ["s66-nooit"])
rij5 = [r["categorie"] for r in db.categorieen_om_te_meten(5, 30)
        if r["categorie"].startswith("s66-")]
klopt(f"drie winkels halen een ondergrens van vijf niet, ook na drie rondes (kreeg {rij5})",
      rij5 == [])

with conn:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM benadering WHERE categorie LIKE 's66-%'")
        cur.execute("DELETE FROM categorie_rondes WHERE categorie LIKE 's66-%'")
        cur.execute("DELETE FROM klanten WHERE webshop_url LIKE 'https://s66-%'")

print("\n== DE KLANTTEKST BELOOFT GEEN WEKELIJKSE AI-METING ==")
for taal, d in paginataal.TEKSTEN.items():
    for sleutel in ("niets_tekst", "d_vermeld_uitleg_a", "eerste_tekst"):
        tekst = d[sleutel].lower()
        klopt(f"{taal}:{sleutel} zegt geen 'elke week meten'",
              "every week we ask" not in tekst and "elke week meten" not in tekst
              and "stellen elke week" not in tekst and "this week" not in tekst
              and "deze week" not in tekst)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de positie komt alleen uit de index.")
