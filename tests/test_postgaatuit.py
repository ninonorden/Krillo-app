"""Loopt de hele benadering door en kijkt of er echt post uitgaat.

Waarom dit bestaat: er is drie dagen lang niets verstuurd terwijl elk onderdeel
op zichzelf werkte. Elke losse test was groen. Wat niemand naliep was de keten
van begin tot eind, en juist daar zaten de fouten.

De derde en ergste: de benadering mat met de benchmarkstand, en die stelt vijf
vragen. De mail weigert onder de tien meegetelde vragen. Elke winkel werd dus
netjes gemeten, kostte geld, en kreeg daarna te horen dat het te weinig was.
Nul post, elke dag opnieuw, met de rekening er wel bij. Er stond nergens een
foutmelding, want beide getallen waren op zichzelf verdedigbaar.

Deze test doet twee dingen die de andere tests niet doen:
 1. Hij bewaakt dat de twee getallen elkaar niet meer kunnen tegenspreken.
 2. Hij laat een echte ronde draaien met de dure stappen vervangen door
    namaak, en eist dat er aan het eind een mail de deur uit gaat en dat de
    winkel op "gemaild" komt te staan.
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

import db          # noqa: E402
import benadering  # noqa: E402
import emailing    # noqa: E402
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

# Alles wegparkeren wat er van eerdere tests of eerdere keren draaien nog staat.
# Zonder dit mailt de ronde hieronder ook die winkels mee en meet je een fout
# die er niet is. Dat gebeurde bij het schrijven van deze test ook echt.
for rij in db.get_benaderingen(stand=("nieuw", "adres", "meten", "gemeten")):
    db.zet_benadering(rij["webshop_url"], stand="afgevallen")

# En de datum van een eerdere keer draaien wissen bij de winkels van deze test.
# zet_benadering kan dat met opzet niet: een verstuurde mail hoort nergens in de
# gewone code ongedaan gemaakt te kunnen worden. In een test mag het wel, anders
# meet de tweede keer draaien iets anders dan de eerste.
TESTWINKELS = ("https://postgaatuit-test.nl", "https://tekrap-test.nl")
_conn = db._get_connection()
with _conn.cursor() as _cur:
    _cur.execute("UPDATE benadering SET gemaild_op = NULL WHERE webshop_url = ANY(%s)",
                 (list(TESTWINKELS),))
_conn.commit()
_conn.close()

print("\n== de meting stelt genoeg vragen voor de mail ==")
# Dit is de bewaking. Zakt BENADERING_VRAGEN ooit onder de drempel, dan valt
# deze test om in plaats van dat er stilletjes een maand geen post uitgaat.
klopt(f"benadering meet {krillo.BENADERING_VRAGEN} vragen, mail eist minstens "
      f"{krillo.MINIMUM_VRAGEN_VOOR_POST}",
      krillo.BENADERING_VRAGEN > krillo.MINIMUM_VRAGEN_VOOR_POST)
klopt("en er zit marge op, want niet elke vraag telt mee",
      krillo.BENADERING_VRAGEN >= krillo.MINIMUM_VRAGEN_VOOR_POST + 3)
klopt("de benchmarkstand alleen is niet genoeg voor post",
      krillo.BENCHMARK_VRAGEN < krillo.MINIMUM_VRAGEN_VOOR_POST)

print("\n== het aantal vragen komt echt bij de meting aan ==")
# Niet de bedoeling nameten maar de doorgifte: gaat het getal door de wachtrij
# heen tot bij de meting. Daar zat de fout, dus daar moet de test op staan.
gezien = {}
echte_draaien = krillo._demo_draaien
krillo._demo_draaien = lambda url, benchmark_stand=False, vragen=None: gezien.update(
    {"url": url, "benchmark": benchmark_stand, "vragen": vragen})
krillo._demo_inplannen(["https://doorgiftest.nl"], benchmark_stand=True,
                       vragen=krillo.BENADERING_VRAGEN, opnieuw=True)
import time  # noqa: E402
for _ in range(50):
    if gezien:
        break
    time.sleep(0.1)
zo("de meting krijgt het aantal vragen mee", gezien.get("vragen"),
   krillo.BENADERING_VRAGEN)
krillo._demo_draaien = echte_draaien

print("\n== een hele ronde levert een verstuurde mail op ==")
WINKEL = "https://postgaatuit-test.nl"
db.zet_benadering(WINKEL, stand="afgevallen")
db.voeg_benaderingen_toe([(WINKEL, "Posttest", "NL", None)])
db.zet_benadering(WINKEL, stand="gemeten", email="info@postgaatuit-test.nl",
                  afgemeld=False)

# De dure kant vervangen door namaak. Wat hier NIET vervangen wordt is de
# beslissing of er gemaild mag worden, want dat is precies wat getest wordt.
verstuurd = []
emailing.send_onderzoeksmail = lambda *a, **kw: verstuurd.append((a, kw)) or True
krillo._klantgegevens = lambda url: {
    "vermeldingen": {"telbaar": krillo.BENADERING_VRAGEN, "genoemd": 3,
                     "nooit_genoemd": 8},
}
db.zet_instelling("benadering_aan", "ja")

krillo._benadering_ronde()

zo("er is precies een mail verstuurd", len(verstuurd), 1)
zo("naar het adres van de winkel", verstuurd[0][0][0] if verstuurd else None,
   "info@postgaatuit-test.nl")
stand = {r["webshop_url"]: r for r in db.get_benaderingen(alleen_niet_afgemeld=False)
         if r["webshop_url"] == WINKEL}
zo("de winkel staat nu op gemaild", (stand.get(WINKEL) or {}).get("stand"), "gemaild")
klopt("met een datum erbij", bool((stand.get(WINKEL) or {}).get("gemaild_op")))
zo("het logboek telt de mail mee", benadering.rondeverslagen()[0]["gemaild"], 1)

print("\n== dezelfde winkel krijgt geen tweede mail ==")
verstuurd.clear()
krillo._benadering_ronde()
zo("er gaat niets meer heen", len(verstuurd), 0)

print("\n== een winkel die te weinig vragen haalt krijgt geen post ==")
KRAP = "https://tekrap-test.nl"
db.zet_benadering(KRAP, stand="afgevallen")
db.voeg_benaderingen_toe([(KRAP, "Krap", "NL", None)])
db.zet_benadering(KRAP, stand="gemeten", email="info@tekrap-test.nl", afgemeld=False)
krillo._klantgegevens = lambda url: {"vermeldingen": {"telbaar": 4, "genoemd": 0}}
verstuurd.clear()
krillo._benadering_ronde()
zo("er gaat geen halve uitkomst de deur uit", len(verstuurd), 0)
klopt("en de reden staat in het logboek",
      any("vragen" in m for m in benadering.rondeverslagen()[0]["mislukt"]))
stand = {r["webshop_url"]: r for r in db.get_benaderingen(alleen_niet_afgemeld=False)
         if r["webshop_url"] == KRAP}
zo("hij blijft op gemeten staan en komt dus later terug",
   (stand.get(KRAP) or {}).get("stand"), "gemeten")

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
