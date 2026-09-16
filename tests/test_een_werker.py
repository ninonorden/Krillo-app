"""De app draait op EEN gunicorn-werker, en dat is geen detail.

WAT ER MISGING OP 16 SEPTEMBER

Nino drukte op "Test het goedkope leesmodel". Er verscheen "de vergelijking is
gestart, ververs over een minuut". Na tien keer verversen stond er nog steeds
precies hetzelfde, en nooit een uitkomst.

De oorzaak zit niet in de vergelijking maar in hoe de app draait. Het Procfile
zei alleen "gunicorn app:app --timeout 120". Hoeveel werkers daarbij horen
stond er niet, en dan bepaalt de omgeving dat. Render zet daar een getal voor.

Elke werker is een apart proces met een eigen geheugen. En alle voortgang die
deze app bijhoudt, staat in het geheugen: of het opschonen bezig is, hoe ver de
meting is, wat de vergelijking opleverde. Bij twee werkers gebeurt dit:

- Je drukt op de knop. Werker A start het werk.
- Je ververst. Het verzoek komt bij werker B. Die weet van niets, ziet geen
  lopend werk, en laat het beginscherm zien.
- Je drukt nog eens. Werker B start het werk NOG EEN KEER.

Dat verklaart ook waarom het indelen van de winkels op 13 september vier keer
aangeklikt moest worden voordat het af was. Dat leek toen een tijdslimiet, maar
dit past beter bij wat er gebeurde.

Het ergste eraan is niet de verwarring maar de rekening: elke extra klik is
een tweede keer dezelfde modelaanroepen betalen, terwijl het slot dat dat moet
voorkomen in het geheugen van de andere werker zit en dus niets doet.

DE OPLOSSING VOOR NU: een werker vastzetten, met meerdere threads zodat de site
snel blijft terwijl er op de achtergrond gemeten wordt.

DE OPLOSSING VOOR LATER: de voortgang in de database in plaats van in het
geheugen. Dan mag het weer met meerdere werkers, en overleeft de stand ook een
herstart. Dat hoort erbij zodra er echt bezoek is; vandaag is een werker ruim
genoeg voor 85 bezoekers per maand.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


print("\n== het Procfile ==")
proc = lees("Procfile")
print(f"  {proc.strip()}")
klopt("er wordt met gunicorn gestart", "gunicorn app:app" in proc)
klopt("het aantal werkers staat vast", "--workers" in proc)

m = re.search(r"--workers\s+(\d+)", proc)
klopt("en dat is een getal", m is not None)
if m:
    zo("precies een werker", int(m.group(1)), 1)

klopt("met meerdere threads, zodat de site snel blijft tijdens achtergrondwerk",
      "--threads" in proc)
m = re.search(r"--threads\s+(\d+)", proc)
if m:
    klopt("en dat zijn er meer dan een", int(m.group(1)) > 1)

klopt("de tijdslimiet staat er nog steeds op", "--timeout 120" in proc)

print("\n== waar de voortgang wordt bijgehouden ==")
# Zolang de stand in het geheugen staat, MOET het een werker blijven. Deze test
# legt die afspraak vast: verhuist de stand ooit naar de database, dan mag deze
# test veranderen, en niet eerder.
for bestand, naam in (("opschonen.py", "het opschonen"),
                      ("categoriemeting.py", "de meting"),
                      ("onderhoud.py", "het onderhoud")):
    bron = lees(bestand)
    klopt(f"{naam} houdt zijn stand in het geheugen bij",
          "_stand = {" in bron)
    klopt(f"{naam} heeft een slot tegen dubbel starten",
          "threading.Lock()" in bron)

print("\n== een mislukking mag nooit onzichtbaar zijn ==")
# Dit was het tweede probleem van 16 september: de vergelijking kon stukgaan
# zonder dat er iets op het scherm veranderde. Een scherm dat niets zegt laat
# iemand tien keer verversen en daarna nog een keer op de knop drukken.
sjabloon = open(os.path.join(APP, "templates", "admin_ranglijst.html")).read()
klopt("de ranglijstpagina toont een fout van de vergelijking",
      "vergelijking.fout" in sjabloon)
klopt("en zegt het ook als er niets gelezen kon worden",
      "not v.bekeken" in sjabloon)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
