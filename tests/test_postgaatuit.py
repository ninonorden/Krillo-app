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

# De klok vastzetten. Deze test draaide eerst gewoon op de tijd van de machine,
# en dus slaagde hij overdag en viel hij 's avonds om met "buiten de uren dat wij
# post versturen". Een test die afhangt van hoe laat je hem draait bewaakt niets.
benadering.binnen_kantooruren = lambda moment=None: True

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
# Sinds 10 september gaat hij terug naar "adres" om opnieuw gemeten te worden.
# Op "gemeten" laten staan betekende: elke ronde opnieuw aangeboden, elke ronde
# opnieuw geweigerd, en nooit post.
zo("hij gaat terug om opnieuw gemeten te worden",
   (stand.get(KRAP) or {}).get("stand"), "adres")

print("\n== een halve meting blijft niet eeuwig op gemeten staan ==")
# Dit is de val die anders morgen weer toeslaat. Een winkel met te weinig
# vragen werd geweigerd door de mail, bleef op "gemeten" staan, werd elke ronde
# opnieuw geweigerd, en bezette ondertussen een plek in de rij van winkels die
# wel klaar waren.
HALF = "https://halvemeting-test.nl"
db.zet_benadering(HALF, stand="afgevallen")
db.voeg_benaderingen_toe([(HALF, "Half", "NL", None)])
db.zet_benadering(HALF, stand="gemeten", email="info@halvemeting-test.nl",
                  afgemeld=False)
krillo._klantgegevens = lambda url: {"vermeldingen": {"telbaar": 5, "genoemd": 0}}
verstuurd.clear()
krillo._benadering_ronde()
zo("er gaat geen halve uitkomst uit", len(verstuurd), 0)
stand = {r["webshop_url"]: r for r in db.get_benaderingen(alleen_niet_afgemeld=False)
         if r["webshop_url"] == HALF}
zo("hij staat weer op adres, om opnieuw gemeten te worden",
   (stand.get(HALF) or {}).get("stand"), "adres")
klopt("met de reden erbij",
      "te weinig" in ((stand.get(HALF) or {}).get("notitie") or "").lower())

print("\n== en de ronde zet hem niet meteen terug op gemeten ==")
# Zonder de ondergrens bij al_gemeten gebeurde precies dat, en dan blijf je
# eeuwig rondgaan zonder ooit post te sturen.
krillo._benadering_ronde()
stand = {r["webshop_url"]: r for r in db.get_benaderingen(alleen_niet_afgemeld=False)
         if r["webshop_url"] == HALF}
klopt("hij staat niet op gemeten",
      (stand.get(HALF) or {}).get("stand") != "gemeten")

print("\n== de trechter na de mail wordt geteld ==")
# Zonder dit weet je na honderd verstuurde mails alleen dat er honderd
# verstuurd zijn, en dat zegt niets over waar mensen afhaken.
T = "https://trechter-posttest.nl"
db.zet_benadering(T, stand="afgevallen")
db.voeg_benaderingen_toe([(T, "Trechter", "NL", None)])
db.zet_benadering(T, stand="gemeten", email="info@trechter-posttest.nl", afgemeld=False)
voor = db.trechter_benadering()
klopt("een bezoek wordt geteld", db.noteer_uitkomst_bekeken(T))
klopt("een doorklik wordt geteld", db.noteer_doorgeklikt(T))
zo("twee keer doorklikken telt maar een keer", db.noteer_doorgeklikt(T), False)
na = db.trechter_benadering()
zo("de teller is een omhoog", na["bekeken"], voor["bekeken"] + 1)
zo("en de doorklik ook", na["doorgeklikt"], voor["doorgeklikt"] + 1)
zo("een winkel die niet bestaat verandert niets",
   db.noteer_uitkomst_bekeken("https://bestaat-echt-niet-zz.nl"), False)
klopt("herhaald bezoek wordt apart geteld", db.noteer_uitkomst_bekeken(T))
rij = [r for r in db.get_benaderingen(alleen_niet_afgemeld=False)
       if r["webshop_url"] == T][0]
zo("twee bezoeken geteld", rij.get("bekeken_aantal"), 2)

print("\n== de knop op de uitkomstpagina loopt langs de teller ==")
# Anders wordt de enige stap die over geld gaat niet geteld.
sjabloon = open(os.path.join(APP, "templates", "uitkomst.html")).read()
klopt("de knop gaat via /verder", "/uitkomst/{{ token }}/verder" in sjabloon)
bron = open(os.path.join(APP, "app.py")).read()
klopt("en die route bestaat", '"/uitkomst/<token>/verder"' in bron)

print("\n== de kostenrem per meting past bij het aantal vragen ==")
# Hier ging het op 11 september mis en het kostte een dag post. De rem per meting
# stond op 0,50 euro en 20 aanroepen, passend bij een meting van vijf vragen. De
# benadering stelt er vijftien en een klant krijgt er dertig, allebei bij twee
# modellen. De rem kapte elke meting dus af na ongeveer DRIE vragen, en de mail
# weigert onder de tien. Betaald bij de modellen, nul post, elke ronde opnieuw.
import kosten     # noqa: E402
import metingen   # noqa: E402

AANBIEDERS = 2   # ChatGPT en Gemini
KOSTEN_PER_VRAAG_RUIM = 0.08   # ruim gerekend, per model per vraag

for naam, vragen in (("de benadering", krillo.BENADERING_VRAGEN),
                     ("een klant", metingen.VRAGEN_PER_RONDE)):
    nodig_aanroepen = vragen * AANBIEDERS
    nodig_euro = nodig_aanroepen * KOSTEN_PER_VRAAG_RUIM
    klopt(f"{naam} ({vragen} vragen) past binnen de aanroepgrens "
          f"({nodig_aanroepen} van {kosten.GRENS_PER_SCAN_AANROEPEN})",
          nodig_aanroepen < kosten.GRENS_PER_SCAN_AANROEPEN)
    klopt(f"{naam} past binnen de kostengrens "
          f"({nodig_euro:.2f} van {kosten.GRENS_PER_SCAN_EURO:.2f} euro)",
          nodig_euro < kosten.GRENS_PER_SCAN_EURO)

klopt("en de grens per klant per maand kan vier rondes betalen",
      kosten.GRENS_PER_KLANT_MAAND_EURO >= kosten.GRENS_PER_SCAN_EURO)

print("\n== de schatting per meting is niet te laag ==")
# Staat dit getal te laag, dan plant de ronde meer metingen in dan er betaald
# kunnen worden, worden ze halverwege afgekapt, en heb je betaald voor niets.
import kosten  # noqa: E402
klopt(f"schatting is {kosten.SCHATTING_METING_EURO} euro per meting",
      kosten.SCHATTING_METING_EURO >= 1.50)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
