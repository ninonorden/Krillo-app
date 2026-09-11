"""Bewaakt het pad van de eerste betalende klant.

Er zijn nul betalende klanten en er gaan voor het eerst mails uit, dus er kan
voor het eerst echt iemand betalen. Dat pad was nooit end to end nagelopen, en
een audit vond er zeven blokkerende dingen in. Wat ze gemeen hadden: de klant
betaalt, krijgt niets, en er gaat NERGENS een belletje.

Elke controle hieronder hoort bij een van die zeven.
"""
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

import db          # noqa: E402
import app as krillo  # noqa: E402

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
BRON = open(os.path.join(APP, "app.py")).read()

print("\n== een vertypt e-mailadres wordt geweigerd VOOR de betaling ==")
# Wie zich vertypte betaalde 79 euro, Brevo weigerde stilletjes, en niemand
# merkte iets. Niet de klant, niet wij.
klant = krillo.app.test_client()
for route in ("/api/checkout/audit", "/api/checkout/uitvoering",
              "/api/checkout/monitoring"):
    uit = klant.post(route, json={"url": "winkel.nl", "email": "geenadres",
                                  "voorwaarden_akkoord": True,
                                  "directe_uitvoering_akkoord": True})
    zo(f"{route} weigert een onzinnig adres", uit.status_code, 400)
    klopt(f"{route} zegt waarom", "klopt niet" in uit.get_data(as_text=True))

print("\n== een geldig adres komt wel door de controle heen ==")
# Belangrijk: de controle mag niet zo streng zijn dat echte adressen afvallen.
uit = klant.post("/api/checkout/audit",
                 json={"url": "winkel.nl", "email": "info+krillo@mijn-winkel.co.uk",
                       "voorwaarden_akkoord": True,
                       "directe_uitvoering_akkoord": True})
klopt("een gewoon zakelijk adres wordt niet geweigerd om zijn vorm",
      "klopt niet" not in uit.get_data(as_text=True))

print("\n== een betaling die wij niet konden claimen is iets anders dan al verwerkt ==")
# Dit is het pad waarin iemand wel betaalt en geen klantrecord krijgt. Stond
# eerst allebei op False, en dan las de aanroeper "al verwerkt" en stopte.
zo("de eerste claim lukt", db.claim_payment("tr_eersteklant"), True)
zo("een tweede keer is False, niet None", db.claim_payment("tr_eersteklant"), False)
klopt("de code kijkt op None en meldt dat apart", "geclaimd is None" in BRON)
klopt("met een bericht naar jezelf", "Betaling niet geclaimd" in BRON)
db.ontclaim_payment("tr_eersteklant")

print("\n== een fout na de claim laat de betaling niet doodlopen ==")
# De claim staat dan al vast, dus zonder terugdraaien stopt elke volgende
# melding van Mollie bij "was al verwerkt" en is de betaling voorgoed weg.
staart = BRON[BRON.index("def _verwerk_betaling"):]
staart = staart[:staart.index("@app.route(\"/webhooks/mollie\"")]
klopt("de claim gaat terug bij een fout", "db.ontclaim_payment(payment_id)" in staart)
klopt("en jij krijgt bericht", "Betaling niet verwerkt" in staart)

print("\n== de factuurmail gaat maar een keer uit ==")
uit1 = db.maak_factuur("tr_factuurtest", "a@b.nl", "Shop", "Audit", 79.00)
uit2 = db.maak_factuur("tr_factuurtest", "a@b.nl", "Shop", "Audit", 79.00)
zo("hetzelfde nummer", uit1["factuurnummer"], uit2["factuurnummer"])
zo("de eerste is nieuw", uit1["nieuw"], True)
zo("de tweede niet", uit2["nieuw"], False)
klopt("en de code mailt alleen bij nieuw", 'factuurnummer.get("nieuw")' in BRON)

print("\n== er komt geen tweede abonnement bij een herhaling van Mollie ==")
# Twee keer 39 euro per maand, en opzeggen haalt er maar een weg.
klopt("er wordt eerst gekeken of er al een abonnement loopt",
      "Er loopt al een abonnement voor" in BRON)

print("\n== de noodmeldingen komen echt aan ==")
# Alle vangnetten hingen aan BEHEER_EMAIL terwijl de rest van de code en de
# README BEHEERDER_EMAIL gebruiken. Dan kwam er nergens iets aan.
klopt("BEHEERDER_EMAIL wordt als eerste gelezen",
      'os.environ.get("BEHEERDER_EMAIL") or os.environ.get("BEHEER_EMAIL")' in BRON)

print("\n== de garantie belooft per product wat de voorwaarden geven ==")
# Een onvoorwaardelijke belofte van dertig dagen geld terug klopt alleen bij de
# audit. Bij het abonnement geldt veertien dagen, bij de uitvoering geldt
# terugdraaien. Anders staat er een onjuiste mededeling over een
# betalingsverplichting op het scherm waar iemand afrekent.
index = open(os.path.join(TEMPLATES, "index.html")).read()
klopt("de belofte op de prijskaart noemt de audit", "Levert de audit je niets op" in index)
klopt("er staat geen onvoorwaardelijke belofte meer",
      "Levert het je niets op, dan krijg je binnen dertig dagen" not in index)
klopt("het bestelscherm vult de regel per product",
      "checkoutGarantie" in index and "content.garantie" in index)
for zin in ("Levert de audit je niets op", "dan draaien wij hem terug",
            "Zeg je binnen veertien dagen"):
    klopt(f"er is een eigen regel: {zin[:30]}", zin in index)

print("\n== de klantpagina spreekt zichzelf niet tegen over geld ==")
mon = open(os.path.join(TEMPLATES, "monitoring.html")).read()
klopt("Monitoring actief hangt aan een echt abonnement",
      "{% elif abonnement %}{{ t.d_nav_actief }}" in mon)

print("\n== wie 149 euro betaalt krijgt de audit die erbij hoort ==")
# De prijskaart belooft "Alles uit de volledige audit zit erbij", maar die tak
# scande niet, bewaarde geen rapport en mat niet. De klantpagina was leeg en er
# was geen werkbriefje, dus zelfs Nino wist niet wat hij moest doen.
klopt("er wordt werk klaargezet na een uitvoering",
      "_uitvoering_voorbereiden" in BRON)
voorbereiden = BRON[BRON.index("def _uitvoering_voorbereiden"):]
voorbereiden = voorbereiden[:voorbereiden.index("\ndef _levering_mislukt")]
klopt("er wordt gescand", "_scan_met_herkansing" in voorbereiden)
klopt("het rapport wordt bewaard", "db.save_report" in voorbereiden)
klopt("en er wordt gemeten, want daar hangt het werkbriefje aan",
      "_meet_en_beoordeel" in voorbereiden)
klopt("mislukt het, dan krijg jij bericht", "_meld_aan_beheer" in voorbereiden)
klopt("de toegangsmail wordt nagekeken", "Toegangsmail niet verstuurd" in BRON)

print("\n== de audit valt niet terug op de gratis voorbeeldteksten ==")
# Anders betaalt iemand 79 euro voor precies de drie voorbeelden die hij een
# minuut eerder gratis op de homepage zag.
klopt("bij geen AI-tekst gaat er GEEN mail uit",
      "had de klant de gratis" in BRON)
klopt("en de betaling blijft open staan voor een nieuwe poging",
      'if ai_fixes is None:' in BRON and "_levering_mislukt(" in BRON)
klopt("de stille terugval is weg",
      'scan_result.get("voorbeeldfixes", [])' not in BRON)

print("\n== een mislukte meting bij een klant geeft een signaal ==")
klopt("er gaat bericht uit", "Meting mislukt bij een klant" in BRON)
klopt("alleen bij een klant, niet bij elke demo", "if klant_token:" in BRON)

print("\n== de bedanktpagina liegt niet meer ==")
bedankt = open(os.path.join(TEMPLATES, "bedankt.html")).read()
klopt("het vinkje hangt aan een echte betaling", "{% if gelukt %}" in bedankt)
klopt("bij een afgebroken betaling staat er geen bedankje",
      "De betaling is niet afgerond" in BRON)
betaal = open(os.path.join(APP, "payments.py")).read()
klopt("het betaalkenmerk gaat mee in de terugkeerlink",
      "_zet_terugkeerlink_met_kenmerk" in betaal)
# Alleen de aanroepen tellen, niet de regel waar de functie gedefinieerd wordt.
zo("voor alle drie de producten",
   len([r for r in betaal.split("\n")
        if r.strip().startswith("_zet_terugkeerlink_met_kenmerk(client")]), 3)
klopt("en als dat mislukt gaat de betaling gewoon door",
      "Terugkeerlink met kenmerk zetten mislukt" in betaal)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
