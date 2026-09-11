"""Bewaakt dat dezelfde winkel niet elke dag opnieuw geld kost.

Dit is de duurste fout die er op 11 september in zat, en hij liep al dagen.

Twee lussen, allebei zonder rem:

1. **De onbereikbare winkel.** woefwinkel.be stond op een dag acht keer in het
   foutenlogboek, steeds met "we konden deze website niet bereiken". Er zat wel
   een teller op, maar die telde uit een logboek van tien regels. Bij vijftien
   metingen per dag is de vorige poging daar allang uit gerold, dus begon het
   tellen elke keer weer bij nul en viel de winkel nooit af.

2. **De winkel waar AI nooit een winkel noemt.** Een meting is pas bruikbaar
   als er genoeg vragen meetellen, en een vraag telt pas mee als AI daarin
   uberhaupt winkels noemt. Bij sommige winkels gebeurt dat gewoon nooit. Die
   werden elke dag opnieuw gemeten, kostten elke dag een paar euro, en werden
   elke dag opnieuw geweigerd voor de mail. Dat is geen storing die overgaat.

En een derde gat dat die twee in stand hield: bij het afronden van een meting
werd de winkel alleen opgezocht tussen wat op "meten" stond. Was hij tijdens de
meting door de opruimronde teruggezet op "adres", dan werd hij niet gevonden en
werd de mislukking helemaal niet geteld.
"""
import os
import sys
import uuid

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

import db           # noqa: E402
import benadering   # noqa: E402

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
UNIEK = uuid.uuid4().hex[:8]
WINKEL = f"https://pogingtest-{UNIEK}.nl"
ANDERE = f"https://pogingtest-anders-{UNIEK}.nl"


print("\n== de teller begint bij nul en loopt op ==")
zo("nog nooit geprobeerd", benadering.meetpogingen(WINKEL), 0)
klopt("dus hij mag gemeten worden", benadering.mag_nog_een_poging(WINKEL))
zo("eerste poging", benadering.tel_meetpoging(WINKEL), 1)
zo("tweede poging", benadering.tel_meetpoging(WINKEL), 2)
zo("en dat blijft staan", benadering.meetpogingen(WINKEL), 2)

print("\n== de teller overleeft een logboek vol andere winkels ==")
# Dit is precies waar het op stukliep: het foutenlogboek bewaart tien regels, en
# bij vijftien metingen per dag is jouw winkel daar allang uit gerold.
for i in range(15):
    benadering.onthoud_meetfout(f"https://ruis-{UNIEK}-{i}.nl", "mislukt: test")
zo("de teller staat er nog steeds", benadering.meetpogingen(WINKEL), 2)
zo("het logboek is hem wel kwijt", benadering.tel_meetfouten(WINKEL), 0)

print("\n== na genoeg pogingen mag hij niet meer ==")
while benadering.meetpogingen(WINKEL) < benadering.MAX_MEETPOGINGEN:
    benadering.tel_meetpoging(WINKEL)
klopt("nu is het klaar", not benadering.mag_nog_een_poging(WINKEL))
klopt("een andere winkel heeft daar geen last van",
      benadering.mag_nog_een_poging(ANDERE))

print("\n== een geslaagde meting wist de geschiedenis ==")
benadering.vergeet_meetpogingen(WINKEL)
zo("terug op nul", benadering.meetpogingen(WINKEL), 0)
klopt("en hij mag weer", benadering.mag_nog_een_poging(WINKEL))
# Twee keer vergeten mag geen fout geven.
benadering.vergeet_meetpogingen(WINKEL)
zo("nog steeds nul", benadering.meetpogingen(WINKEL), 0)

print("\n== het is een echte rem, geen getal van nul ==")
klopt("er zitten meer pogingen in dan een", benadering.MAX_MEETPOGINGEN >= 2)
klopt("en het loopt niet uit de hand", benadering.MAX_MEETPOGINGEN <= 5)


print("\n== de ronde geeft een winkel op in plaats van eeuwig te herhalen ==")
bron = lees("app.py")
klopt("de ronde telt een poging bij te weinig vragen",
      "benadering.tel_meetpoging(winkel[\"webshop_url\"])" in bron)
klopt("en zet hem op afgevallen als het genoeg is geweest",
      "poging >= benadering.MAX_MEETPOGINGEN" in bron)
klopt("met een reden die uitlegt waarom wij stoppen",
      "Hier valt geen eerlijke uitkomst" in bron)
klopt("een winkel die het wel haalde begint schoon",
      "benadering.vergeet_meetpogingen(winkel[\"webshop_url\"])" in bron)

print("\n== een mislukte meting wordt altijd geteld ==")
begin = bron.find("def _meting_afgerond_melden")
blok = bron[begin:begin + 2600]
klopt("hij zoekt over de hele lijst, niet alleen op 'meten'",
      "db.get_benaderingen(alleen_niet_afgemeld=False)" in blok)
klopt("en laat een afgevallen winkel met rust",
      'if (rij.get("stand") or "") == "afgevallen"' in blok)
klopt("de mislukking telt mee in de eigen teller",
      "benadering.tel_meetpoging(rij[\"webshop_url\"])" in blok)

print("\n== en wie opgegeven is komt niet meer in de meetrij ==")
begin = bron.find("def _demo_inplannen")
blok = bron[begin:begin + 2600]
klopt("de wachtrij kijkt naar de afgevallen winkels",
      'db.get_benaderingen(stand="afgevallen"' in blok)
klopt("en slaat ze over", "is al afgevallen" in blok)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
