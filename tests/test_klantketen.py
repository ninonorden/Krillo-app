"""De keten van een betalende klant, na de onafhankelijke controle van 23 september.

WAAROM DEZE TEST BESTAAT

Een tweede, onafhankelijke controle liep de weg van een betalende klant na in
de code en vond dingen die geen enkele bestaande test zag, omdat ze pas bij
echte aantallen of echte betalingen misgaan:

1. Mollie begon het abonnement op de dag van de eerste betaling: twee keer
   afschrijven voor de eerste maand.
2. Mollie geeft per pagina maar tien klanten terug. Na tien kassapogingen zag
   de code een betalende klant niet meer.
3. Mislukte de scan bij een nieuwe klant, dan kreeg hij niets: geen pagina,
   geen mail, geen plek in de index. Mollie meldt een betaling maar een keer.
4. Een Shopify-abonnee die opzegde zonder de app te verwijderen, bleef klant.
5. Een Shopify-abonnee kwam pas na een week in de klantentabel.
6. Watch-klanten lazen "wij voeren dit voor je uit".
7. Een beoordeling van een eigen meting mislukte stil (verkeerde sleutel).
8. De koude mail kon vastlopen op winkels zonder positie.

Elk punt hieronder houdt er een vast. Tegen een echte database waar het kan.
"""
import os
import sys
import types
from datetime import date

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


import payments  # noqa: E402  (de echte, voor de datum en het bladeren)
import db  # noqa: E402

print("\n== 1. HET ABONNEMENT BEGINT OVER EEN MAAND ==")
klopt("23 september wordt 23 oktober",
      payments.over_een_maand(date(2026, 9, 23)) == date(2026, 10, 23))
klopt("31 januari wordt de laatste dag van februari",
      payments.over_een_maand(date(2027, 1, 31)) == date(2027, 2, 28))
klopt("december wordt januari volgend jaar",
      payments.over_een_maand(date(2026, 12, 5)) == date(2027, 1, 5))
bron_pay = lees("payments.py")
klopt("de startdatum gaat mee naar Mollie", '"startDate"' in bron_pay)
klopt("en de webhook ook, voor maandfacturen", 'gegevens["webhookUrl"] = webhook_url' in bron_pay)


print("\n== 2. ALLE KLANTEN BIJ MOLLIE, NIET ALLEEN DE EERSTE PAGINA ==")


class Pagina(list):
    def __init__(self, items, volgende=None):
        super().__init__(items)
        self._volgende = volgende

    def get_next(self):
        return self._volgende


class NepKlanten:
    def list(self, **k):
        return Pagina([1, 2, 3], Pagina([4, 5], Pagina([6])))


class NepClient:
    customers = NepKlanten()


klopt("alle drie de pagina's", list(payments.alle_klanten(NepClient())) == [1, 2, 3, 4, 5, 6])
klopt("zoek_abonnement bladert", "alle_klanten(client)" in bron_pay
      and "for customer in client.customers.list():" not in bron_pay)

print("\n== DATABASE: DE MOLLIE-KLANT EN HET PAKKET BIJ DE KLANT ==")
db.init_db()


def sql(opdracht, waarden=None):
    conn = db._get_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(opdracht, waarden)
    conn.close()


URL = "https://keten-test.nl"
sql("DELETE FROM klanten WHERE webshop_url = %s", (URL,))
db.get_or_create_klant(URL, "eigenaar@keten-test.nl")
klopt("Mollie-klant en pakket bewaard", db.zet_mollie_klant(URL, "cst_test123", "watch"))
klopt("en terug te vinden", db.mollie_klant_van(URL) == "cst_test123")
klopt("het pakket staat bij de klant", (db.klant_bij_url(URL) or {}).get("pakket") == "watch")

print("\n== 3. EERST DE KLANT, DAN PAS DE SCAN ==")
bron = lees("app.py")
i = bron.index('elif payment_type == "monitoring_first_payment":')
blok = bron[i:bron.index('@app.route("/admin/inloggen"', i)]
klopt("een mislukte scan stopt de levering niet meer",
      "_levering_mislukt(payment_id, webshop_url, email, \"monitoring\"" not in blok)
klopt("wel een melding aan jou", "Scan mislukt bij een nieuwe klant" in blok)
klopt("de klant wordt altijd aangemaakt", "db.get_or_create_klant(webshop_url, email)" in blok)
klopt("de Mollie-klant wordt bewaard", "db.zet_mollie_klant(" in blok)
import emailing  # noqa: E402
_verstuurd = []
emailing.send_email = lambda to, onderwerp, html, **k: _verstuurd.append(html) or True
emailing.send_monitoring_welcome_email("a@b.nl", URL, {"score": 0, "checks": []},
                                       "https://krilloai.com/mijn/x", pakket="watch")
klopt("zonder scan geen verzonnen '0 of 100' in de welkomstmail",
      "0 of 100" not in _verstuurd[-1] and "first one follows within a week" in _verstuurd[-1])

print("\n== MAANDBETALINGEN ==")
klopt("een mislukte maandbetaling geeft jou een melding", "Maandbetaling mislukt" in bron)
klopt("een gelukte maandbetaling krijgt een factuur", 'payment_type = "maandbetaling"' in bron)

print("\n== 4 EN 5. SHOPIFY: OPZEGGEN, TERUGKOMEN, EN METEEN KLANT ==")
import shopify_app  # noqa: E402
klopt("de webhook voor abonnementen wordt aangemeld",
      ("app_subscriptions/update", "/shopify/webhooks/abonnement") in shopify_app.WEBHOOKS)
klopt("de route bestaat", '"/shopify/webhooks/abonnement"' in bron)
j = bron.index("def shopify_abonnement_gewijzigd(")
wh = bron[j:bron.index("\n@app.route", j)]
klopt("hij vraagt Shopify zelf wat er nu loopt", "huidig_abonnement(" in wh)
klopt("bij twijfel verandert er niets", 'if stand.get("fout"):' in wh)
klopt("lopend abonnement: klant", "_shopify_klant_actief(" in wh)
klopt("geen abonnement meer: opgezegd", "zet_klant_opgezegd(" in wh)
klopt("bij het openen van de app ook meteen klant",
      "_shopify_klant_actief(winkel, rij, stand.get(\"plan\"))" in bron)

print("\n== 6. WATCH LEEST NIET DAT WIJ HET DOEN ==")
werk = lees("templates/_werk.html")
klopt("de tekst hangt af van het pakket", "wt.taken_wij if doet_werk else wt.taken_zelf" in werk)
import paginataal  # noqa: E402
klopt("de Engelse zelf-doen-tekst bestaat", "yourself" in paginataal.teksten("en")["taken_zelf"])
sql("UPDATE klanten SET pakket = 'watch', opgezegd_op = NULL WHERE webshop_url = %s", (URL,))

print("\n== 7. BEOORDELINGEN: UNIEK OP ANTWOORD, WINKEL EN BRON ==")
sql("DELETE FROM beoordelingen WHERE webshop_url = %s", (URL,))
basis = dict(antwoord_id=987654, meting_id="m-test", webshop_url=URL, vraag="v", intentie=None,
             model="x", winkel_kon_genoemd=True, genoemd=False, positie=None,
             aantal_winkels=0, aanbevolen=False, toon=None, bewijs=None,
             soort_vermelding=None, winkels="[]", merken="[]", aanbevolen_winkels="[]")
klopt("een beoordeling van een eigen meting wordt echt bewaard", db.bewaar_beoordeling(basis))
rijen = db.bewaar_beoordelingen_veel([dict(basis, bron="categorie", winkels=[], merken=[],
                                           aanbevolen_winkels=[])])
klopt("hetzelfde nummer uit de maandmeting valt er niet meer stil af", rijen == 1)
sql("DELETE FROM beoordelingen WHERE webshop_url = %s", (URL,))

print("\n== 8. DE KOUDE MAIL: ALLEEN WINKELS MET EEN POSITIE ==")
klopt("in de database gefilterd", "EXISTS (" in lees("db.py")
      and "def te_mailen_met_positie" in lees("db.py"))
klopt("de rij gebruikt dat filter", "db.te_mailen_met_positie(hoeveel)" in lees("benadering.py"))

print("\n== KLEINERE PUNTEN ==")
klopt("drie categorieen per nacht", 'os.environ.get("ONDERHOUD_METEN", "3")' in lees("onderhoud.py"))
klopt("het maandbericht telt per land", "db.ranglijst_per_land(categorie, land" in lees("meldingen.py"))
klopt("merken en bureaus niet zelf af te rekenen", 'if pakket == "merken":' in bron)
klopt("Mollie-omschrijvingen Engels", "maandelijkse meting" not in bron_pay)
klopt("het oude onderzoek stuurt door naar de index",
      'return redirect("/index", code=301)' in bron)

print("\n== NA DE TWEEDE CONTROLE ==")
_verstuurd.clear()
emailing.send_onderzoeksmail("ik@voorbeeld.nl", "https://mediamarkt.nl",
                             "https://krilloai.com/uitkomst/x",
                             beeld={"positie": 1, "van": 20, "genoemd": 20, "telbaar": 30,
                                    "land": "nl", "categorie": "elektronica"},
                             afmeld_url=None, onderwerp_voor="[TEST] ")
klopt("een proefmail heeft geen echte afmeldlink", "/afmelden/" not in _verstuurd[-1])
klopt("de proefmail geeft proef=True mee", "proef=True" in bron
      and 'afmeld_url=None if proef else' in bron)
klopt("wie opzegde leest niet 'eenmalig betaald'", "{% elif opgezegd %}" in werk)
klopt("de Engelse opgezegd-tekst bestaat",
      paginataal.teksten("en")["opgezegd_kop"] == "Your plan is cancelled")
klopt("geen Nederlands 'Ongeldig verzoek' meer", "Ongeldig verzoek" not in bron)
klopt("de koude mail kijkt naar de eigen categorie", "u.categorie = b.categorie" in lees("db.py"))

sql("DELETE FROM klanten WHERE webshop_url = %s", (URL,))
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de keten van een betalende klant houdt.")
