"""De prijs op de site is altijd gelijk aan wat er afgeschreven wordt.

WAAROM DIT DE STRENGSTE TEST VAN DE HELE SITE IS

Een bedrag op een verkooppagina dat niet klopt met wat er van iemands rekening
gaat, is geen schoonheidsfoutje. Het is een onjuiste mededeling over een
betalingsverplichting, en dat is precies waar een consument je op kan pakken.

Het gaat ook makkelijk mis: de prijs staat in payments.py, op de prijskaarten,
in het bestelscherm, in de gestructureerde gegevens en in de veelgestelde
vragen. Verander je er een, dan spreken de rest je tegen.

DE OMZETTING VAN 17 SEPTEMBER 2026

Van "149 euro eenmalig plus 39 per maand" naar drie maandpakketten:
Watch 49, Fix 149, merken en bureaus 490. Reden: het product is maandelijks
geworden, en de markt vraagt 189 tot 420 dollar per maand voor alleen een
rapport terwijl Krillo het werk uitvoert.

WAT DEZE TEST BEWAAKT

- Elk bedrag op de homepage komt uit payments.PAKKETTEN.
- Watch en Fix gaan allebei naar de abonnementsroute, met hun eigen pakket.
- Een onbekend of leeg pakket wordt nooit gratis en nooit een fout, maar valt
  terug op het standaardpakket.
- Het pakket gaat mee in de metadata van de eerste betaling, want de webhook
  maakt daarna het doorlopende abonnement aan en moet weten hoeveel.
"""
import os
import re
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import payments  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


print("\n== de pakketten zelf ==")
zo("Watch kost 49 euro", payments.PAKKETTEN["watch"]["prijs"]["value"], "49.00")
zo("Fix kost 149 euro", payments.PAKKETTEN["fix"]["prijs"]["value"], "149.00")
zo("merken en bureaus kost 490 euro",
   payments.PAKKETTEN["merken"]["prijs"]["value"], "490.00")
zo("alles is in euro's",
   sorted({p["prijs"]["currency"] for p in payments.PAKKETTEN.values()}), ["EUR"])

print("\n== een onbekend pakket valt netjes terug ==")
zo("leeg wordt het standaardpakket",
   payments.pakket_van("")["naam"], payments.PAKKETTEN[payments.STANDAARD_PAKKET]["naam"])
zo("None ook", payments.pakket_van(None)["naam"],
   payments.PAKKETTEN[payments.STANDAARD_PAKKET]["naam"])
zo("onzin ook", payments.pakket_van("gratisjegek")["naam"],
   payments.PAKKETTEN[payments.STANDAARD_PAKKET]["naam"])
zo("hoofdletters maken niet uit", payments.pakket_van("WATCH")["naam"], "Watch")
klopt("en terugvallen levert nooit nul euro op",
      float(payments.pakket_van("onzin")["prijs"]["value"]) > 0)

print("\n== de bedragen op de homepage komen uit payments ==")
index = lees("templates/index.html")
for sleutel in ("watch", "fix", "merken"):
    bedrag = payments.PAKKETTEN[sleutel]["prijs"]["value"].split(".")[0]
    klopt(f"{sleutel} staat met {bedrag} euro op de prijskaart",
          f"&euro;{bedrag} <span>/mo</span>" in index)

print("\n== de oude prijzen staan er niet meer ==")
prijzenblok = index[index.find('<section id="prijzen"'):index.find('<div class="checkout-overlay"')]
klopt("geen 39 euro per maand meer", "&euro;39" not in prijzenblok)
klopt("geen eenmalig bedrag meer", "eenmalig" not in prijzenblok)
klopt("wel drie maandbedragen", prijzenblok.count("/mo<") == 3)

print("\n== het bestelscherm noemt dezelfde bedragen ==")
klopt("Watch staat op 49 in het bestelscherm",
      "'Watch \\u00b7 \\u20ac49 /mo'" in index)
klopt("Fix staat op 149 in het bestelscherm",
      "'Fix \\u00b7 \\u20ac149 /mo'" in index)

print("\n== de knoppen gaan naar de goede route met het goede pakket ==")
klopt("er is een knop voor Watch", 'id="watchCheckoutBtn"' in index)
klopt("en een voor Fix", 'id="fixCheckoutBtn"' in index)
klopt("allebei naar de abonnementsroute",
      "watch: '/api/checkout/monitoring'" in index and "fix: '/api/checkout/monitoring'" in index)
klopt("en het pakket gaat mee in het verzoek", "pakket: pakketten[currentType]" in index)
klopt("merken en bureaus gaat naar de mail, niet naar een kassa",
      "mailto:hello@krilloai.com" in prijzenblok)

print("\n== de gestructureerde gegevens kloppen ==")
klopt("Watch staat erin met 49",
      '"name": "Watch", "price": "49"' in index)
klopt("Fix staat erin met 149",
      '"name": "Fix", "price": "149"' in index)

print("\n== het pakket gaat mee naar Mollie ==")
bron = lees("payments.py")
klopt("de eerste betaling gebruikt de prijs van het gekozen pakket",
      '"amount": gekozen["prijs"]' in bron)
klopt("en het pakket staat in de metadata", '"pakket": (pakket or STANDAARD_PAKKET)' in bron)
klopt("het doorlopende abonnement kent het pakket ook",
      "def create_subscription(customer_id, pakket=STANDAARD_PAKKET)" in bron)
appbron = lees("app.py")
klopt("de webhook geeft het pakket door",
      'pakket=metadata.get("pakket")' in appbron)
klopt("de kassa leest het pakket uit het verzoek",
      'data.get("pakket")' in appbron)

print("\n== nergens op de site nog een oude prijs ==")
for bestand in ("templates/faq.html", "templates/index.html"):
    inhoud = lees(bestand)
    klopt(f"{bestand} belooft geen 39 euro per maand meer",
          "39 euro per maand" not in inhoud)
# Deze controle keek eerst of de bedragen letterlijk in de BRON van app.py
# stonden. Sinds 18 september bouwt llms.txt zijn prijsregels op uit
# payments.PAKKETTEN, juist zodat dat bestand nooit meer iets anders kan
# beweren dan het bestelscherm. Daarmee staan de bedragen niet meer als tekst
# in de bron en sloeg de oude controle nergens meer op.
#
# Wat er nu gecontroleerd wordt is sterker: niet wat er getypt staat, maar wat
# er daadwerkelijk uitgeserveerd wordt.
os.environ.setdefault("BASE_URL", "https://krilloai.com")
import app as _app  # noqa: E402

_app.app.config["TESTING"] = True
_llms = _app.app.test_client().get("/llms.txt").get_data(as_text=True)
for _sleutel in ("watch", "fix", "merken"):
    _bedrag = int(float(payments.PAKKETTEN[_sleutel]["prijs"]["value"]))
    klopt(f"llms.txt serveert {_bedrag} euro per maand voor {_sleutel}",
          f"{_bedrag} euro per month" in _llms)
klopt("llms.txt noemt geen vervallen audit van 79 euro meer",
      "79 euro" not in _llms)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
