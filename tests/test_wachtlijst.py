"""De belofte uit de mail waarmaken als de dagpot op is.

In de onderzoeksmail staat: open je pagina, dan gaat er meteen een grotere
meting overheen. Dat was tot 12 september niet altijd waar. Was het geld voor
die dag op op het moment dat iemand klikte, dan sloeg de meting over EN kwam
die winkel er nooit meer langs. De kostenrem zat namelijk voor de plek waar wij
onthouden dat het nog moest. Er stond nergens een foutmelding: de winkel wachtte
gewoon voor eeuwig op iets wat hem beloofd was.

Dat is het gat dat hier dichtgezet wordt. Wie klikt terwijl er geen geld is komt
op een wachtlijst, en de eerstevolgende ronde met ruimte pakt hem alsnog op.
Iemand die klikt is het beste wat er op een dag gebeurt; juist aan hem hoort die
dure meting besteed te worden, desnoods een dag later.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

import db          # noqa: E402
import benadering  # noqa: E402

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


def leeg():
    db.zet_instelling(benadering.WACHT_VOLLEDIG_SLEUTEL, "[]")


A = "https://winkel-een.nl"
B = "https://winkel-twee.nl"
C = "https://winkel-drie.nl"

print("\n== op de wachtlijst en er weer af ==")
leeg()
klopt("de eerste komt erop", benadering.zet_op_wachtlijst_volledige_meting(A))
klopt("dezelfde winkel komt er niet twee keer op",
      benadering.zet_op_wachtlijst_volledige_meting(A) is False)
benadering.zet_op_wachtlijst_volledige_meting(B)
benadering.zet_op_wachtlijst_volledige_meting(C)
zo("er staan er drie", len(benadering._wachtlijst()), 3)

print("\n== een ronde pakt er hoogstens een paar tegelijk ==")
# Een volledige meting kost ongeveer 2,50 euro. Zou een ronde de hele lijst
# oppakken, dan maakt een ochtend met veel klikken in een klap de dagpot op en
# blijft er niets over voor nieuwe winkels.
nu = benadering.wachtenden_op_volledige_meting(hoeveel=2)
zo("twee opgepakt", len(nu), 2)
zo("in de volgorde waarin ze klikten", nu[0].endswith("winkel-een.nl"), True)
zo("de rest blijft staan", len(benadering._wachtlijst()), 1)
zo("en komt de ronde erna", len(benadering.wachtenden_op_volledige_meting(hoeveel=2)), 1)
zo("daarna is de lijst leeg", benadering.wachtenden_op_volledige_meting(hoeveel=2), [])

print("\n== afmelden haalt je ook van deze lijst ==")
leeg()
benadering.zet_op_wachtlijst_volledige_meting(A)
benadering.zet_op_wachtlijst_volledige_meting(B)
benadering.haal_van_wachtlijst(A)
zo("alleen de ander blijft over", len(benadering._wachtlijst()), 1)
klopt("en dat is de goede", benadering._wachtlijst()[0].endswith("winkel-twee.nl"))

print("\n== de klik zelf: geen geld, dus later ==")
leeg()
import app as krillo  # noqa: E402
import kosten         # noqa: E402

echte_rem = kosten.mag_doorgaan
ingepland = []
krillo._demo_inplannen = lambda urls, **k: ingepland.extend(urls)

kosten.mag_doorgaan = lambda **k: {"mag": False, "reden": "dagpot op"}
try:
    zo("de meting gaat nu niet door",
       krillo._volledige_meting_na_klik("https://klikker.nl"), False)
    zo("maar hij staat wel in de rij", len(benadering._wachtlijst()), 1)
    zo("en er is niets ingepland", ingepland, [])
    klopt("en hij geldt niet als gemeten, anders komt hij er nooit meer langs",
          benadering.volledige_meting_gedaan("https://klikker.nl") is False)

    # Nog een keer klikken mag niet twee plekken in de rij opleveren.
    krillo._volledige_meting_na_klik("https://klikker.nl")
    zo("twee keer klikken is een plek in de rij", len(benadering._wachtlijst()), 1)
finally:
    kosten.mag_doorgaan = echte_rem

print("\n== en zodra er weer geld is ==")
kosten.mag_doorgaan = lambda **k: {"mag": True, "reden": ""}
try:
    wachtenden = benadering.wachtenden_op_volledige_meting(hoeveel=2)
    zo("de wachtende winkel komt eruit", len(wachtenden), 1)
    for url in wachtenden:
        krillo._volledige_meting_na_klik(url)
    zo("nu wordt hij wel ingepland", len(ingepland), 1)
    klopt("en geldt hij als gedaan",
          benadering.volledige_meting_gedaan("https://klikker.nl"))
    zo("de wachtlijst is leeg", benadering._wachtlijst(), [])

    # En niet nog een keer, want dan betaal je twee keer voor hetzelfde.
    krillo._volledige_meting_na_klik("https://klikker.nl")
    zo("een tweede poging doet niets", len(ingepland), 1)
finally:
    kosten.mag_doorgaan = echte_rem
    leeg()

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
