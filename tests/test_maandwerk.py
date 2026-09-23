"""Stap 72: elke maand nieuw werk voor een klant, uit de meting van zijn categorie.

WAAROM DEZE TEST BESTAAT

Sinds stap 66 (21 september) meet Krillo niet meer elke week apart per klant.
Daardoor kwam het beeld van een klant, en dus ook zijn drie oplossingen, uit
de ENE eigen meting bij de start van zijn abonnement. Een klant van drie
maanden zag nog steeds de drie dingen van zijn eerste dag, terwijl Fix belooft
dat wij elke maand de drie dingen doen die het meeste opleveren. Een controle
van de mails tegen de code vond dat op 21 september.

De oplossing is niet zijn eigen meting terugzetten (twee keer dezelfde vragen,
twee keer betalen), maar zijn beeld halen uit de maandmeting van zijn
categorie. Die stelt dezelfde dertig koopvragen al, voor alle winkels tegelijk.

Deze test draait tegen een echte database: een verzonnen meetronde met echte
antwoorden erin, en dan kijken of de klant daar zijn cijfers, zijn bewijs en
zijn oplossingen uit krijgt, en of een tweede ronde niets dubbel doet.
"""
import json
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import db  # noqa: E402
import beoordeling  # noqa: E402
import klantwerk  # noqa: E402
import payments  # noqa: E402

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


CAT = "mw-testcategorie"
WINKEL = "https://mijntestwinkel.nl"
ANDER = "https://anderewinkel.nl"


def opruimen():
    sql("DELETE FROM beoordelingen WHERE webshop_url IN (%s, %s)", (WINKEL, ANDER))
    sql("DELETE FROM categorie_antwoorden WHERE categorie = %s", (CAT,))
    sql("DELETE FROM categorie_rondes WHERE categorie = %s", (CAT,))
    sql("DELETE FROM klanten WHERE webshop_url IN (%s, %s)", (WINKEL, ANDER))
    sql("DELETE FROM benadering WHERE categorie = %s", (CAT,))


db.init_db()
opruimen()

# Twee winkels in dezelfde categorie, allebei klant.
for url, naam in ((WINKEL, "Mijn Testwinkel"), (ANDER, "Andere Winkel")):
    sql("INSERT INTO benadering (webshop_url, naam, categorie, soort) "
        "VALUES (%s, %s, %s, 'winkel')", (url, naam, CAT))
    db.get_or_create_klant(url, f"eigenaar@{url.replace('https://', '')}")

ronde = sql("INSERT INTO categorie_rondes (categorie, vragen, winkels) "
            "VALUES (%s, 2, 2) RETURNING id", (CAT,), een=True)[0]

# Twee antwoorden. In het eerste wordt onze winkel genoemd en aanbevolen, in
# het tweede niet. Precies zoals het leesmodel ze wegschrijft.
ANTWOORD1 = ("Voor emaille servies kun je bij een paar winkels terecht. "
             "Mijn Testwinkel heeft de mooiste emaille mokken en levert snel. "
             "Ook Andere Winkel verkoopt ze.")
ANTWOORD2 = "Kijk eens bij Grote Keten of bij Andere Winkel voor pannen."
for vraag, antwoord, genoemde in (
    ("waar koop ik mooi emaille servies?", ANTWOORD1,
     {"winkel_kon_genoemd": True,
      "winkels": [{"naam": "Mijn Testwinkel", "positie": 1, "adres": "mijntestwinkel.nl"},
                  {"naam": "Andere Winkel", "positie": 2, "adres": "anderewinkel.nl"}],
      "aanbevolen": ["Mijn Testwinkel"]}),
    ("welke winkel heeft de beste pannen?", ANTWOORD2,
     {"winkel_kon_genoemd": True,
      "winkels": [{"naam": "Grote Keten", "positie": 1, "adres": "groteketen.nl"},
                  {"naam": "Andere Winkel", "positie": 2, "adres": "anderewinkel.nl"}],
      "aanbevolen": []}),
):
    sql("""INSERT INTO categorie_antwoorden
           (ronde, categorie, vraag, model, antwoord, winkel_kon_genoemd, genoemde_winkels)
           VALUES (%s, %s, %s, 'gpt-test', %s, TRUE, %s)""",
        (ronde, CAT, vraag, antwoord, json.dumps(genoemde)))

print("\n== DE MEETRONDE WORDT HET BEELD VAN DE KLANT ==")
uit = klantwerk.beoordelingen_uit_ronde(ronde, CAT)
print(f"  verslag: {uit}")
klopt("beide klanten zijn meegenomen", uit["klanten"] == 2)
klopt("en elk antwoord levert per klant een regel op (2 x 2)", uit["regels"] == 4)

rijen = {(b["vraag"], b["webshop_url"]): b for b in db.get_beoordelingen(WINKEL)}
eerste = rijen.get(("waar koop ik mooi emaille servies?", WINKEL))
tweede = rijen.get(("welke winkel heeft de beste pannen?", WINKEL))
klopt("de eerste vraag staat er", eerste is not None)
klopt("daar wordt hij genoemd", eerste and eerste["genoemd"] is True)
klopt("en ook echt aanbevolen", eerste and eerste["aanbevolen"] is True)
klopt("met zijn positie", eerste and eerste["positie"] == 1)
klopt("en met de zin als bewijs, uit het echte antwoord",
      eerste and eerste["bewijs"] and "mooiste emaille mokken" in eerste["bewijs"])
klopt("bij de tweede vraag staat hij er niet bij", tweede and tweede["genoemd"] is False)
klopt("en dan is er ook geen bewijs", tweede and not tweede["bewijs"])
klopt("de herkomst staat erbij, zodat je weet dat het uit de index komt",
      eerste and eerste.get("bron") == "categorie")

print("\n== DE CIJFERS OP HET DASHBOARD KLOPPEN ERMEE ==")
beeld = beoordeling.klantbeeld(WINKEL, [dict(b) for b in db.get_beoordelingen(WINKEL)])
klopt("twee vragen geteld", beeld["telbaar"] == 2)
klopt("bij een genoemd", beeld["genoemd"] == 1)
klopt("bij een aanbevolen", beeld["aanbevolen"] == 1)
namen = [c["naam"] for c in beeld["concurrenten"]]
klopt(f"de andere winkels staan erbij (kreeg {namen})", "Andere Winkel" in namen)

print("\n== TWEE KEER DRAAIEN DOET NIETS DUBBEL ==")
opnieuw = klantwerk.beoordelingen_uit_ronde(ronde, CAT)
klopt("geen nieuwe regels", opnieuw["regels"] == 0)
klopt("en nog steeds twee regels voor deze winkel",
      len(db.get_beoordelingen(WINKEL)) == 2)

print("\n== WIE OPZEGT KRIJGT GEEN NIEUW WERK MEER ==")
db.zet_klant_opgezegd(ANDER)
klanten = [k["webshop_url"] for k in db.klanten_in_categorie(CAT)]
klopt(f"de opzegger valt af (kreeg {klanten})", klanten == [WINKEL])
db.zet_klant_opgezegd(ANDER, opgezegd=False)
klopt("en terugkomen kan", len(db.klanten_in_categorie(CAT)) == 2)

print("\n== HET HANGT ECHT AAN DE NACHTRONDE ==")
onderhoudbron = lees("onderhoud.py")
appbron = lees("app.py")
klopt("de nachtronde roept het aan na een meting", "NA_METING(uit[\"ronde\"]" in onderhoudbron)
klopt("app zet zijn eigen functie erin", "onderhoud.NA_METING = _ververs_klantwerk" in appbron)
klopt("en die vernieuwt de oplossingen", "_maak_taakoplossingen(url, plan)" in appbron)
klopt("langs de kostenrem", "kosten.mag_doorgaan(webshop_url=url)" in appbron)
klopt("Fix komt op de werklijst, Watch niet", "_doet_werk_voor(url)" in appbron)

print("\n== WELK PAKKET IEMAND HEEFT, KOMT VAN HET BEDRAG ==")
klopt("49 euro is Watch", payments.pakket_bij_bedrag("49.00") == "watch")
klopt("149 euro is Fix", payments.pakket_bij_bedrag("149.00") == "fix")
klopt("490 euro is het pakket voor merken", payments.pakket_bij_bedrag("490.00") == "merken")
klopt("een onbekend bedrag geeft niets terug", payments.pakket_bij_bedrag("12.00") is None)

opruimen()
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: elke maandmeting levert de klant nieuw werk op.")
