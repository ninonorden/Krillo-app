"""Stap 10 (controle halverwege, 23 september): een categorie komt weer op dertig vragen.

WAAROM DEZE TEST BESTAAT

Bij de controle van de openbare index op 23 september, met 18 categorieen,
stond "Servies en tafelgerei" op 19 vragen, "Speelgoed" op 28 en "Hobby en
knutselen" op 29. Terwijl elke categorie met dertig hoort te meten.

De oorzaak: zwakke vragen worden na een ronde uitgezet en daarna aangevuld,
maar het model dat de nieuwe vragen bedenkt wist niet welke er al waren. Het
bedacht dezelfde, die vielen weg op de unieke sleutel (categorie, vraag), en
de categorie bleef ronde na ronde onder de dertig. Minder vragen is een
armere meting, en op de openbare pagina staat het aantal erbij.

Deze test kijkt of het model de bestaande vragen meekrijgt (ook de uitgezette)
en of het aanvullen een tweede poging doet als de eerste te weinig oplevert.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import categoriemeting  # noqa: E402

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


print("\n== HET MODEL KRIJGT DE BESTAANDE VRAGEN MEE ==")
gezien = {}


class NepAntwoord:
    class usage:
        input_tokens = 1
        output_tokens = 1
    content = [type("t", (), {"text": '{"vragen": [{"vraag": "nieuw", "intentie": "algemeen"}]}'})]


class NepClient:
    class messages:
        @staticmethod
        def create(model, max_tokens, messages):
            gezien["prompt"] = messages[0]["content"]
            return NepAntwoord()


categoriemeting._client = lambda: NepClient()
categoriemeting.kosten.registreer_aanroep = lambda **k: None
categoriemeting.bedenk_vragen("speelgoed", aantal=8,
                              vermijd=["waar koop ik een houten trein?",
                                       "welke webshop heeft goedkope lego?"])
p = gezien.get("prompt", "")
klopt("de opdracht noemt de vragen die er al zijn", "waar koop ik een houten trein?" in p)
klopt("met de uitleg dat het andere moeten zijn", "DEZE VRAGEN BESTAAN AL" in p)
categoriemeting.bedenk_vragen("speelgoed", aantal=8)
klopt("zonder bestaande vragen staat dat blok er niet", "DEZE VRAGEN BESTAAN AL" not in gezien["prompt"])

print("\n== HET AANVULLEN IN DE METING ==")
bron = lees("categoriemeting.py")
klopt("de meting geeft ALLE vragen mee, ook de uitgezette",
      "vermijd=db.alle_categorie_vragen_tekst(slug)" in bron)
klopt("en vraagt er ruim, want er vallen er altijd een paar af",
      "aantal=max(tekort + 5, 8)" in bron)
klopt("met een tweede poging", "for _poging in range(2):" in bron)
klopt("en zegt het hardop als het toch te weinig blijft", "meet met {len(vragen)} vragen in plaats van" in bron)

print("\n== DE DATABASE GEEFT OOK UITGEZETTE VRAGEN ==")
import db  # noqa: E402
db.init_db()
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM categorie_vragen WHERE categorie = 'va-test'")
db.bewaar_categorie_vragen("va-test", [{"vraag": "actief", "intentie": "algemeen"},
                                       {"vraag": "uitgezet", "intentie": "algemeen"}])
db.zet_vragen_uit("va-test", ["uitgezet"])
klopt("de gewone lijst geeft alleen de actieve",
      [v["vraag"] for v in db.categorie_vragen("va-test")] == ["actief"])
klopt("de lijst om te vermijden geeft ze allebei",
      sorted(db.alle_categorie_vragen_tekst("va-test")) == ["actief", "uitgezet"])
with conn:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM categorie_vragen WHERE categorie = 'va-test'")
conn.close()

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: een categorie vult weer aan tot dertig vragen.")
