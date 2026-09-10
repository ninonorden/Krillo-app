"""Bewaakt de opvolging van mensen die zelf de gratis test aanvroegen.

Dit was het grootste gat in het hele bedrijf en het was geen fout: iemand vult
zijn mailadres in, krijgt zijn uitkomst, en hoort daarna nooit meer iets. Dat is
het warmste publiek dat Krillo heeft, warmer dan welke benaderlijst ook, want
deze mensen hebben er zelf om gevraagd.

Precies daarom moet het voorzichtig: een tweede mail is welkom, een derde is
spam. Wat hieronder bewaakt wordt is vooral wat er NIET mag gebeuren.
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import APP  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

from datetime import datetime, timedelta  # noqa: E402
import db          # noqa: E402
import benadering  # noqa: E402
import emailing    # noqa: E402
import app as krillo  # noqa: E402

# De echte functie bewaren VOORDAT wij hem vervangen. Deed ik dat niet, dan
# was het origineel weg en testte het laatste blok de namaak.
ECHTE_OPVOLGMAIL = emailing.send_opvolging_gratis_test

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

# Alles van eerdere keren afvinken, anders meet deze test die mee.
conn = db._get_connection()
with conn.cursor() as cur:
    cur.execute("UPDATE zichtbaarheidstests SET opgevolgd_op = now() "
                "WHERE opgevolgd_op IS NULL")
conn.commit()
conn.close()


# Elke keer draaien krijgt eigen winkels en adressen. Zonder dit vindt de tweede
# keer de aanvragen van de eerste keer terug, weigert de database een tweede test
# voor dezelfde winkel, en meet de test niets meer. Precies het soort test dat
# groen blijft terwijl er niets bewaakt wordt.
UNIEK = datetime.now().strftime("%H%M%S%f")


def zet_test(url, email, dagen_geleden, status="klaar"):
    """Een aanvraag van de gratis test neerzetten, zoveel dagen geleden."""
    uit = db.start_zichtbaarheidstest(url, email)
    if not uit:
        return None
    # Geeft {"id": ..., "kenmerk": ...} terug, niet een kaal nummer.
    tid = uit["id"]
    db.zet_zichtbaarheidstest(tid, status)
    c = db._get_connection()
    with c.cursor() as cur:
        cur.execute("UPDATE zichtbaarheidstests SET aangevraagd_op = %s, "
                    "opgevolgd_op = NULL WHERE id = %s",
                    (datetime.now(benadering.KLOK) - timedelta(days=dagen_geleden), tid))
    c.commit()
    c.close()
    return tid


print("\n== wie er wel en niet aan de beurt is ==")
oud = zet_test(f"https://opvolg-oud-{UNIEK}.nl", f"oud-{UNIEK}@opvolgtest.nl", 10)
vers = zet_test(f"https://opvolg-vers-{UNIEK}.nl", f"vers-{UNIEK}@opvolgtest.nl", 0)
half = zet_test(f"https://opvolg-half-{UNIEK}.nl", f"half-{UNIEK}@opvolgtest.nl", 10, status="bezig")

adressen = {r["email"] for r in db.leads_om_op_te_volgen(na_dagen=3, hoeveel=50)}
klopt("een test van tien dagen geleden is aan de beurt", f"oud-{UNIEK}@opvolgtest.nl" in adressen)
klopt("een test van vandaag nog niet", f"vers-{UNIEK}@opvolgtest.nl" not in adressen)
klopt("een test die nooit afgerond is ook niet", f"half-{UNIEK}@opvolgtest.nl" not in adressen)

print("\n== een klant krijgt geen verkoopmail ==")
# Die krijgt zijn eigen wekelijkse post al. Zou dit misgaan, dan schrijf je een
# betalende klant alsof hij nog niets gekocht heeft.
klant = zet_test(f"https://opvolg-klant-{UNIEK}.nl", f"klant-{UNIEK}@opvolgtest.nl", 10)
db.get_or_create_klant(f"https://opvolg-klant-{UNIEK}.nl", f"klant-{UNIEK}@opvolgtest.nl")
adressen = {r["email"] for r in db.leads_om_op_te_volgen(na_dagen=3, hoeveel=50)}
klopt("een klant staat er niet bij", f"klant-{UNIEK}@opvolgtest.nl" not in adressen)

print("\n== drie winkels testen levert geen drie mails op ==")
for n in (1, 2, 3):
    zet_test(f"https://opvolg-drie-{n}-{UNIEK}.nl", f"drie-{UNIEK}@opvolgtest.nl", 10)
regels = [r for r in db.leads_om_op_te_volgen(na_dagen=3, hoeveel=50)
          if r["email"] == f"drie-{UNIEK}@opvolgtest.nl"]
zo("maar een regel voor dat adres", len(regels), 1)

print("\n== afvinken doet dat voor het hele adres ==")
db.markeer_lead_opgevolgd(regels[0]["id"])
regels = [r for r in db.leads_om_op_te_volgen(na_dagen=3, hoeveel=50)
          if r["email"] == f"drie-{UNIEK}@opvolgtest.nl"]
zo("hij komt niet meer terug", len(regels), 0)

print("\n== er gaat maar een herinnering uit, nooit twee ==")
verstuurd = []
emailing.send_opvolging_gratis_test = (
    lambda to, url, basis=None, taal="nl": verstuurd.append(to) or True)
benadering.binnen_kantooruren = lambda moment=None: True
db.zet_instelling("benadering_aan", "ja")

krillo._volg_gratis_tests_op()
eerste = len(verstuurd)
klopt("de eerste ronde stuurt iets", eerste >= 1)
verstuurd.clear()
for _ in range(3):
    krillo._volg_gratis_tests_op()
klopt("daarna gaat er niets meer naar dezelfde mensen",
      f"oud-{UNIEK}@opvolgtest.nl" not in verstuurd)

print("\n== staat de schakelaar uit, dan gaat er niets uit ==")
zet_test(f"https://opvolg-uit-{UNIEK}.nl", f"uit-{UNIEK}@opvolgtest.nl", 10)
db.zet_instelling("benadering_aan", "nee")
verstuurd.clear()
zo("niets verstuurd", krillo._volg_gratis_tests_op(), 0)
db.zet_instelling("benadering_aan", "ja")

print("\n== buiten kantooruren ook niet ==")
benadering.binnen_kantooruren = lambda moment=None: False
verstuurd.clear()
zo("niets verstuurd", krillo._volg_gratis_tests_op(), 0)
benadering.binnen_kantooruren = lambda moment=None: True

print("\n== wie zich afgemeld heeft krijgt niets ==")
afgemeld = zet_test(f"https://opvolg-afgemeld-{UNIEK}.nl", f"afgemeld-{UNIEK}@opvolgtest.nl", 10)
# Eerst op de benaderlijst zetten. Afmelden staat in die tabel, dus zonder deze
# regel raakt zet_benadering geen enkele rij en is de test zinloos.
db.voeg_benaderingen_toe([(f"https://opvolg-afgemeld-{UNIEK}.nl", None, "NL", None)])
db.zet_benadering(f"https://opvolg-afgemeld-{UNIEK}.nl", stand="afgevallen", afgemeld=True)
verstuurd.clear()
krillo._volg_gratis_tests_op()
klopt("geen mail naar een afgemeld adres",
      f"afgemeld-{UNIEK}@opvolgtest.nl" not in verstuurd)

print("\n== de mail zelf klopt in beide talen ==")
import re  # noqa: E402
echt = emailing.send_email
gemaakt = []
emailing.send_email = lambda to, ond, html, koppen=None: gemaakt.append((ond, html)) or True
emailing.send_opvolging_gratis_test = ECHTE_OPVOLGMAIL
for taal in ("nl", "en"):
    gemaakt.clear()
    emailing.send_opvolging_gratis_test("a@b.nl", "https://winkel.nl",
                                        "https://krillo.nl", taal=taal)
    zo(f"[{taal}] er is een mail", len(gemaakt), 1)
    tekst = re.sub("<[^>]+>", " ", gemaakt[0][1])
    klopt(f"[{taal}] de winkel staat erin", "winkel.nl" in tekst)
    klopt(f"[{taal}] met een link naar de prijzen", "winkel=" in gemaakt[0][1])
    klopt(f"[{taal}] geen gedachtestreepje", "—" not in tekst and "–" not in tekst)
emailing.send_email = echt

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
