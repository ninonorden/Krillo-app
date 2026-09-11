"""Bewaakt dat je bericht krijgt zodra iemand betaalt.

Dit ontbrak volledig, en als je erover nadenkt is dat de omgekeerde wereld: er
ging wel een mail naar het eigen adres als er iets MISGING, maar niet als het
goed ging. De belangrijkste gebeurtenis van het hele bedrijf, de eerste
betalende klant, kwam nergens binnen behalve in de mail van Mollie en op een
beheerpagina die je zelf moet openen.

Bij "wij doen het" is dat niet alleen jammer maar riskant. Daar moet een mens
binnen een paar dagen echt aan de slag in de winkel van de klant. Blijft het
stil, dan gebeurt er niets en zit iemand die 149 euro betaald heeft te wachten.

Bij Shopify speelt er nog iets: daar loopt de betaling niet via Mollie, dus komt
er ook geen bevestiging van Mollie binnen. Zonder eigen bericht valt zo'n abonnee
pas op bij de wekelijkse ronde.
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import lees  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


bron = lees("app.py")

print("\n== er is een bericht bij een nieuwe klant ==")
klopt("de functie bestaat", "def _meld_nieuwe_klant(" in bron)
begin = bron.find("def _meld_nieuwe_klant(")
functie = bron[begin:bron.find("\ndef ", begin + 10)]
klopt("hij gaat naar het eigen adres", "_meld_aan_beheer(" in functie)
klopt("met het bedrag erbij", "Bedrag:" in functie)
klopt("en het mailadres van de klant", "E-mailadres:" in functie)
klopt("en een directe weg naar het werkbriefje", "/admin/werkbriefje" in functie)
klopt("en naar de bestellingen", "/admin/bestellingen" in functie)
# De beheersleutel hoort in het webadres mee, anders klik je op een link die je
# naar het inlogscherm stuurt terwijl je juist snel wil kijken.
klopt("de link neemt de beheersleutel mee", "ADMIN_KEY" in functie)
klopt("en het webadres wordt netjes ontsmet", "quote(" in functie)

print("\n== alle drie de manieren waarop iemand klant wordt ==")
for soort, herkenning in (
        ("wij doen het", '_meld_nieuwe_klant("Wij doen het"'),
        ("monitoring via Mollie", '_meld_nieuwe_klant(\n                        "Monitoring"'),
        ("monitoring via de Shopify-app", '"Monitoring via de Shopify-app"')):
    klopt(f"{soort} geeft een bericht", herkenning in bron)

print("\n== bij wij doen het staat erbij waar hij op draait ==")
begin = bron.find('_meld_nieuwe_klant("Wij doen het"')
stuk = bron[begin:begin + 500]
klopt("het platform staat in het bericht", "Platform:" in stuk)
klopt("en als het onbekend is staat dat er ook",
      "Platform onbekend" in stuk)

print("\n== het bericht bij Shopify komt precies een keer ==")
# Dit hangt aan het moment waarop wij voor het eerst een lopend abonnement zien,
# en dat gebeurt per winkel precies een keer. Zou het aan de wekelijkse ronde
# hangen, dan kreeg je elke week opnieuw bericht over dezelfde klant.
begin = bron.find("def shopify_api_abonnement(")
stuk = bron[begin:begin + 1400]
klopt("het hangt aan de eerste keer dat het abonnement loopt",
      'if stand["actief"] and not rij.get("proef_gehad_op")' in stuk)
klopt("en het bericht staat in datzelfde blok",
      "_meld_nieuwe_klant(" in stuk)

print("\n== zonder adres in de omgeving valt er niets om ==")
# BEHEERDER_EMAIL kan ontbreken. Dan hoort het bij de logs te blijven en mag er
# geen fout ontstaan midden in het afhandelen van een betaling.
begin = bron.find("def _meld_aan_beheer(")
stuk = bron[begin:begin + 1200]
klopt("geen adres betekent gewoon stoppen", "if not adres:" in stuk)
klopt("en het staat altijd in de logs", "BEHEERMELDING:" in stuk)
klopt("een mislukte mail laat de betaling met rust", "except Exception" in stuk)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
