"""Bewaakt de drie dingen die de lijst dagenlang hebben stilgelegd.

Wat er gebeurd was: 67 winkels met een adres, 35 op "meten", nul gemeten, nul
gemaild, en dat drie dagen achter elkaar precies gelijk. Elke ronde draaide,
de schakelaar stond aan, en de pagina wees naar een onderbroken wachtrij. Dat
was de verkeerde diagnose.

De echte oorzaak was een samenloop van twee dingen:

 1. De dagpot was niet op ("mag" stond op waar) maar er was te weinig over voor
    nog een hele meting, dus past_nog stond op nul en er werd niets ingepland.
    Nergens stond dat.
 2. Vastgelopen metingen werden alleen vrijgemaakt binnen te_meten, en juist die
    functie wordt bij past_nog nul niet aangeroepen. Winkels die bleven hangen
    kwamen daardoor nooit meer los, ook niet toen er de volgende dag weer geld
    was.

Deze test houdt alle drie de reparaties vast: het logboek, het vrijmaken los van
het geld, en de diagnoseregel die het bij naam noemt.
"""
import os
import sys
from datetime import datetime, timedelta

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from pad import APP, TEMPLATES  # noqa: E402
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

print("\n== het logboek bewaart en leest terug ==")
db.zet_instelling(benadering.VERSLAG_SLEUTEL, "")
zo("leeg logboek geeft een lege lijst", benadering.rondeverslagen(), [])

benadering.onthoud_rondeverslag({"ingepland": 2, "gemaild": 1})
uit = benadering.rondeverslagen()
zo("er staat er nu een in", len(uit), 1)
zo("de inhoud klopt", uit[0]["ingepland"], 2)
klopt("er staat vanzelf een moment bij", bool(uit[0].get("moment")))

benadering.onthoud_rondeverslag({"ingepland": 9})
zo("de nieuwste staat bovenaan", benadering.rondeverslagen()[0]["ingepland"], 9)

for i in range(benadering.VERSLAGEN_BEWAREN + 5):
    benadering.onthoud_rondeverslag({"ingepland": i})
zo("het logboek loopt niet vol",
   len(benadering.rondeverslagen()), benadering.VERSLAGEN_BEWAREN)

print("\n== rommel in het logboek gooit de pagina niet om ==")
db.zet_instelling(benadering.VERSLAG_SLEUTEL, "geen json")
zo("onleesbare inhoud geeft een lege lijst", benadering.rondeverslagen(), [])
db.zet_instelling(benadering.VERSLAG_SLEUTEL, '{"geen": "lijst"}')
zo("een object in plaats van een lijst ook", benadering.rondeverslagen(), [])
db.zet_instelling(benadering.VERSLAG_SLEUTEL, '["los stuk tekst", {"ingepland": 1}]')
zo("losse tekst tussen de regels wordt overgeslagen",
   len(benadering.rondeverslagen()), 1)
db.zet_instelling(benadering.VERSLAG_SLEUTEL, "")

print("\n== een vastgelopen meting komt los, ook zonder dat te_meten draait ==")
VAST = "https://vasttest1.nl"
LOOPT = "https://vasttest2.nl"
for u in (VAST, LOOPT):
    db.zet_benadering(u, stand="afgevallen")
db.voeg_benaderingen_toe([(u, None, "NL", None) for u in (VAST, LOOPT)])
for u in (VAST, LOOPT):
    db.zet_benadering(u, stand="meten", email="info@vasttest.nl",
                      afgemeld=False, meting_gestart=True)

# De ene ver in het verleden zetten, de andere laten staan zoals hij is. Dit
# gaat met de hand omdat zet_benadering met opzet alleen "nu" kan zetten: een
# meting mag niet ergens anders in de code op een oud moment gezet worden.
lang_geleden = datetime.now(benadering.KLOK) - timedelta(
    hours=benadering.METING_VASTGELOPEN_NA_UUR + 2)
_conn = db._get_connection()
with _conn.cursor() as _cur:
    _cur.execute("UPDATE benadering SET meting_gestart_op = %s WHERE webshop_url = %s",
                 (lang_geleden, VAST))
_conn.commit()
_conn.close()

vrij = benadering.maak_vastgelopen_metingen_vrij()
standen = {r["webshop_url"]: r["stand"]
           for r in db.get_benaderingen(alleen_niet_afgemeld=False)
           if r["webshop_url"] in (VAST, LOOPT)}
zo("de vastgelopen meting staat weer op adres", standen.get(VAST), "adres")
zo("de lopende meting blijft met rust", standen.get(LOOPT), "meten")
klopt("er wordt er minstens een vrijgemaakt", vrij >= 1)

print("\n== een winkel die intussen wel gemeten is gaat door naar gemeten ==")
benadering.maak_vastgelopen_metingen_vrij(al_gemeten=[LOOPT])
standen = {r["webshop_url"]: r["stand"]
           for r in db.get_benaderingen(alleen_niet_afgemeld=False)
           if r["webshop_url"] == LOOPT}
zo("hij staat nu op gemeten", standen.get(LOOPT), "gemeten")

print("\n== een ronde schrijft op wat hij gedaan heeft ==")
# Dit is de kern van de reparatie: een ronde die niets deed moet dat zelf
# opschrijven, anders is hij van buitenaf niet te onderscheiden van een ronde
# die helemaal niet gedraaid heeft.
import app as krillo  # noqa: E402

# Eerst alles wegparkeren wat de eerdere stukken hier hebben laten staan.
# Anders gaat de ronde gewoon aan het werk en meet deze test niets: het gaat er
# juist om dat een ronde die NIETS te doen heeft dat zelf opschrijft.
for rij in db.get_benaderingen(stand=("nieuw", "adres", "meten", "gemeten")):
    db.zet_benadering(rij["webshop_url"], stand="afgevallen")
db.zet_instelling(benadering.VERSLAG_SLEUTEL, "")
db.zet_instelling("benadering_aan", "ja")
krillo._benadering_ronde()
v = benadering.rondeverslagen()
zo("er staat een verslag van de ronde", len(v), 1)
klopt("met een tijdstip", bool(v[0].get("moment")))
klopt("met de dagpot erin", v[0].get("dagpot") is not None)
klopt("met minstens een reden waarom er niets uitging",
      len(v[0].get("redenen") or []) >= 1)
klopt("de redenen stapelen, meten en mailen allebei",
      len(v[0].get("redenen") or []) >= 2)

# En andersom: staat de schakelaar uit, dan hoort dat er met zoveel woorden te
# staan. Dat was een van de zeven oorzaken die van buitenaf hetzelfde leken.
db.zet_instelling(benadering.VERSLAG_SLEUTEL, "")
db.zet_instelling("benadering_aan", "nee")
krillo._benadering_ronde()
klopt("een uitgezette schakelaar staat in het logboek",
      any("staat uit" in r for r in benadering.rondeverslagen()[0]["redenen"]))
db.zet_instelling("benadering_aan", "ja")

print("\n== de handknop schrijft ook op, ook als er niets gebeurt ==")
db.zet_instelling(benadering.VERSLAG_SLEUTEL, "")
krillo._nu_meten_en_mailen("https://staat-niet-op-de-lijst-test.nl")
h = benadering.rondeverslagen()
zo("er staat een verslag", len(h), 1)
zo("met de winkel erbij", h[0].get("handmatig"),
   "https://staat-niet-op-de-lijst-test.nl")
klopt("en een reden", "niet op de benaderlijst" in " ".join(h[0]["redenen"]))
zo("er is niets gemaild", h[0]["gemaild"], 0)

AL = "https://algemaild-logboektest.nl"
db.zet_benadering(AL, stand="afgevallen")
db.voeg_benaderingen_toe([(AL, None, "NL", None)])
db.zet_benadering(AL, stand="gemaild", email="info@x.nl", gemaild=True, afgemeld=False)
krillo._nu_meten_en_mailen(AL)
klopt("een winkel die al post had krijgt niets nog een keer",
      "al post gehad" in " ".join(benadering.rondeverslagen()[0]["redenen"]))
zo("en er gaat niets uit", benadering.rondeverslagen()[0]["gemaild"], 0)

print("\n== de diagnose noemt een te kleine restpot bij naam ==")
# Dit is precies het geval dat drie dagen verkeerd gemeld werd: de pot mag nog,
# maar er past geen hele meting meer in.
# Er moet wel iets staan te wachten, anders is er ook niets om over te melden.
WACHT = "https://wachttest-logboek.nl"
db.zet_benadering(WACHT, stand="afgevallen")
db.voeg_benaderingen_toe([(WACHT, None, "NL", None)])
db.zet_benadering(WACHT, stand="adres", email="info@wachttest.nl", afgemeld=False)

krap = {"mag": True, "reden": None, "besteed": 12.40, "grens": 12.50, "past_nog": 0}
regels = benadering.waarom_gaat_er_niets_uit(
    moment_laatste_ronde=datetime.now(benadering.KLOK),
    meetruimte=krap, metingen_bezig=0)
tekst = " ".join(r for _, r in regels)
klopt("de restpot wordt genoemd", "dagpot" in tekst)
klopt("de bedragen staan erbij", "12.40" in tekst and "12.50" in tekst)
klopt("er wordt niet meer naar een onderbroken wachtrij gewezen",
      "onderbroken meting" not in tekst)

ruim = {"mag": True, "reden": None, "besteed": 1.00, "grens": 12.50, "past_nog": 9}
tekst_ruim = " ".join(r for _, r in benadering.waarom_gaat_er_niets_uit(
    moment_laatste_ronde=datetime.now(benadering.KLOK),
    meetruimte=ruim, metingen_bezig=0))
klopt("bij genoeg pot wordt die regel niet getoond",
      "te weinig dagpot" not in tekst_ruim)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
