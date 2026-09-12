"""Bewaakt de omslag van 11 september: honderd benaderingen per dag, en een
abonnement waarbij WIJ het werk doen.

Twee veranderingen die allebei uit dezelfde rekensom komen.

**De eerste meting is klein geworden.** Een volledige benadering van vijftien
vragen bij twee modellen kost ongeveer een euro. Vijftien per dag is vijftien
euro; honderd per dag zou honderd euro per dag zijn, drieduizend per maand. Dat
gaat niet. De vraag is dan ook niet hoeveel vragen wij KUNNEN stellen maar
hoeveel er nodig zijn om iemand te laten schrikken, en dat zijn er geen vijftien.
Het geld gaat naar achteren in de trechter: de volledige meting draait pas als
iemand zijn uitkomst opent. Betalen na het signaal in plaats van ervoor.

**Het abonnement draait om.** Monitoring was "hier is elke week je huiswerk",
tegen een doelgroep die uitdrukkelijk omschreven is als mensen zonder tijd en
zonder technische kennis. Dat was het duurste product qua moeite en het
goedkoopste in prijs, precies omgekeerd aan wat mensen kopen. Nu voeren wij het
uit, en wie ons geen toegang geeft krijgt het kant en klaar om zelf te doen.

Wat hier bewaakt wordt is vooral dat deze twee elkaar niet stilletjes
tegenspreken, want dat is in september al een keer een maand lang gebeurd.
"""
import os
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import APP, TEMPLATES, lees  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")

import db             # noqa: E402
import benadering     # noqa: E402
import paginataal     # noqa: E402
import winkelvinder   # noqa: E402
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

print("\n== de eerste meting is klein, de tweede pas na een klik ==")
klopt("de eerste meting stelt hoogstens acht vragen", krillo.BENADERING_VRAGEN <= 8)
klopt("bij een aanbieder", krillo.BENADERING_AANBIEDERS == 1)
klopt("de volledige meting is groter", krillo.MEET_VRAGEN_NA_KLIK >= 12)
klopt("en de mailgrens past bij de kleine meting",
      krillo.MINIMUM_VRAGEN_VOOR_POST < krillo.BENADERING_VRAGEN)
klopt("maar niet zo laag dat een uitkomst niets zegt",
      krillo.MINIMUM_VRAGEN_VOOR_POST >= 3)

print("\n== de volledige meting gebeurt precies een keer per winkel ==")
# Zonder dit kost iemand die zijn uitkomst drie keer opent drie volledige
# metingen. Dat is precies het soort lek dat je pas op de rekening ziet.
WINKEL = f"https://klik-{os.urandom(4).hex()}.nl"
klopt("nog niet gedaan", not benadering.volledige_meting_gedaan(WINKEL))
benadering.onthoud_volledige_meting(WINKEL)
klopt("nu wel", benadering.volledige_meting_gedaan(WINKEL))
klopt("en een andere winkel heeft daar geen last van",
      not benadering.volledige_meting_gedaan(WINKEL + "x"))

gestart = []
echte_inplannen = krillo._demo_inplannen
echte_rem = krillo.kosten.mag_doorgaan
krillo.kosten.mag_doorgaan = lambda **kw: {"mag": True, "reden": None}
krillo._demo_inplannen = lambda urls, **kw: gestart.append((list(urls), kw))
TWEEDE = f"https://klik2-{os.urandom(4).hex()}.nl"
zo("de eerste klik start de meting", krillo._volledige_meting_na_klik(TWEEDE), True)
zo("de tweede klik doet niets meer", krillo._volledige_meting_na_klik(TWEEDE), False)
zo("er is dus een keer ingepland", len(gestart), 1)
zo("met het volledige aantal vragen", gestart[0][1].get("vragen"),
   krillo.MEET_VRAGEN_NA_KLIK)

print("\n== en niet als de dagpot op is ==")
krillo.kosten.mag_doorgaan = lambda **kw: {"mag": False, "reden": "dagpot op"}
DERDE = f"https://klik3-{os.urandom(4).hex()}.nl"
zo("geen meting bij een lege dagpot", krillo._volledige_meting_na_klik(DERDE), False)
klopt("en hij blijft open staan voor later",
      not benadering.volledige_meting_gedaan(DERDE))
krillo.kosten.mag_doorgaan = echte_rem
krillo._demo_inplannen = echte_inplannen

print("\n== het volume groeit in stappen, niet in een sprong ==")
# Van vijftien naar honderd op een dag is het patroon van een gekaapt domein.
# Gmail en Outlook kijken vooral naar hoe SNEL het oploopt.
db.zet_instelling("mail_per_dag", "25")
db.zet_instelling(benadering.OPBOUW_SLEUTEL, "")
uit = benadering.verhoog_volume_stapsgewijs()
klopt("er is verhoogd", uit.get("verhoogd"))
zo("van 25 naar 50", (uit.get("van"), uit.get("naar")), (25, 50))
uit2 = benadering.verhoog_volume_stapsgewijs()
klopt("en niet twee keer op een dag", not uit2.get("verhoogd"))
klopt("met de reden erbij", "vandaag" in (uit2.get("reden") or "").lower())

db.zet_instelling("mail_per_dag", str(benadering.OPBOUW_DOEL))
db.zet_instelling(benadering.OPBOUW_SLEUTEL, "")
uit3 = benadering.verhoog_volume_stapsgewijs()
klopt("op het doel stopt het", not uit3.get("verhoogd"))
klopt("het doel is echt honderd", benadering.OPBOUW_DOEL >= 100)
db.zet_instelling("mail_per_dag", str(benadering.STANDAARD_PER_DAG))

print("\n== de winkelvinder groeit mee ==")
# Bij honderd mails per dag en ongeveer de helft zonder algemeen mailadres heb
# je tweehonderd nieuwe winkels per dag nodig. Blijft de ondergrens laag, dan
# zoekt de machine pas als de lijst al leeg is en staat de post een dag stil.
klopt("de voorraadgrens past bij honderd mails per dag",
      winkelvinder.VOORRAAD_ONDERGRENS >= 200)
klopt("en er wordt per ronde meer gezocht",
      winkelvinder.ZOEKOPDRACHTEN_PER_RONDE >= 8)


print("\n== monitoring: wij doen het werk, de klant krijgt een verslag ==")
index = lees("templates/index.html")
klopt("de kop belooft niet meer een lijstje",
      "En met monitoring krijg je elke week een lijstje" not in index)
klopt("maar dat wij het bijhouden", "En daarna houden wij het voor je bij" in index)
# Per week en niet per maand. Op de regel eronder stond al "hoogstens drie
# dingen per week", en de keten draait wekelijks, dus "elke maand" was een
# tweede tempo voor hetzelfde werk.
klopt("de prijskaart zegt dat wij het uitvoeren, en in het goede tempo",
      "Wij voeren elke week de verbeteringen uit" in index)
klopt("en niet in twee tempo's tegelijk",
      "Wij voeren elke maand de verbeteringen uit" not in index)
klopt("en is eerlijk over wat er gebeurt zonder toegang",
      "Geen toegang? Dan krijg je alles kant en klaar om zelf te doen" in index)
klopt("het nagemaakte scherm toont wat er gedaan is",
      "Wat wij deze week voor je gedaan hebben" in index)

print("\n== ook in het betaalscherm en de veelgestelde vragen ==")
klopt("het betaalscherm noemt de toegang",
      "Wij voeren de verbeteringen uit in je winkel" in index)
faq = lees("templates/faq.html")
klopt("de veelgestelde vragen zijn omgezet",
      "Je krijgt elke week een lijstje" not in faq)
klopt("en zeggen dat wij het uitvoeren", "voeren wij uit in je winkel" in faq)

print("\n== de klantpagina zegt het in allebei de talen ==")
for taal in ("nl", "en"):
    t = paginataal.teksten(taal)
    klopt(f"[{taal}] de kop is waar in beide gevallen",
          "doet" not in t["titel_taken"] and "to do" not in t["titel_taken"])
    klopt(f"[{taal}] er is een regel over wie het uitvoert", bool(t.get("taken_wij")))
mon = open(os.path.join(TEMPLATES, "monitoring.html")).read()
klopt("de pagina toont die regel", "t.taken_wij" in mon)
klopt("alleen bij een abonnement zonder losse opdracht",
      "{% if abonnement and not uitvoering %}" in mon)

print("\n== en een monitoringklant krijgt de vraag om toegang ==")
# Zonder toegang kunnen wij niets uitvoeren, dus die mail hoort er nu net zo
# hard bij als bij "wij doen het".
bron = lees("app.py")
klopt("de toegangsmail gaat ook bij monitoring uit",
      bron.count("emailing.send_uitvoering_welkom(") >= 2)
klopt("en een mislukte toegangsmail breekt de betaling niet",
      "Toegangsmail bij monitoring mislukt" in bron)

print("\n== de dagpot rekent met de JUISTE prijs per benadering ==")
# Dit was een stille rem waar niemand om gevraagd had. De dagpot bepaalt hoeveel
# metingen er per ronde ingepland mogen worden door de resterende ruimte te delen
# door wat een meting kost. Bleef dat op 2,50 staan terwijl een benadering er nog
# maar 0,20 kost, dan zei hij "er passen er nog zes in" terwijl er zestig in
# pasten, en kwam het volume nooit boven de tien per dag uit, hoe hoog je de pot
# ook zette.
import kosten as _kosten  # noqa: E402
klopt("er is een eigen schatting voor de benadering",
      hasattr(_kosten, "SCHATTING_BENADERING_EURO"))
klopt("en die is veel lager dan die voor een volledige klantmeting",
      _kosten.SCHATTING_BENADERING_EURO < _kosten.SCHATTING_METING_EURO / 3)
klopt("maar niet nul", _kosten.SCHATTING_BENADERING_EURO > 0)
# De rekensom die het doel van honderd per dag mogelijk maakt: bij een volle
# dagpot die helemaal naar de benadering mag, moeten er honderd in passen.
_past_bij_vol = int(_kosten.GRENS_TOTAAL_DAG_EURO / _kosten.SCHATTING_BENADERING_EURO)
klopt(f"bij een volle dagpot passen er {_past_bij_vol} benaderingen in, "
      f"genoeg voor het doel van {benadering.OPBOUW_DOEL}",
      _past_bij_vol >= benadering.OPBOUW_DOEL)
# En de waarschuwing die daarbij hoort: DEEL_VOOR_BENADERING bepaalt hoeveel van
# die pot de benadering echt mag opmaken. Staat die op de helft, dan haal je de
# honderd niet, hoe goedkoop de meting ook is.
_echt = int((_kosten.GRENS_TOTAAL_DAG_EURO * _kosten.DEEL_VOOR_BENADERING)
            / _kosten.SCHATTING_BENADERING_EURO)
print(f"       (met DEEL_VOOR_BENADERING={_kosten.DEEL_VOOR_BENADERING} zijn dat er "
      f"in de praktijk {_echt} per dag)")

print("\n== het zoeken naar adressen kijkt ver genoeg ==")
# Op 12 september stonden er 302 winkels op "geen adres" tegenover 108 met een
# adres: van elke vier gevonden winkels vielen er drie af. Niet omdat die
# winkels geen adres hebben, maar omdat wij er maar vijf pagina's per winkel
# bekeken en de contactpagina vaak een formulier is zonder adres.
#
# Een webwinkel is wettelijk verplicht contactgegevens te noemen, en in de
# praktijk staan die in het privacybeleid en de algemene voorwaarden. Die staan
# nu hoog in de lijst. Dit kost geen AI-geld, alleen paginabezoeken, en elke
# winkel die hierdoor wel een adres krijgt is een winkel waarvoor de meting al
# betaald is.
import contactvinder as _cv  # noqa: E402

klopt("er worden meer dan vijf pagina's bekeken", _cv.MAX_PAGINAS >= 8)
klopt("de contactpagina staat vooraan", _cv.PADEN[0] in ("/contact", "/pages/contact"))
for _pad in ("/privacybeleid", "/algemene-voorwaarden", "/klantenservice"):
    klopt(f"{_pad} staat in de lijst", _pad in _cv.PADEN)
# De juridische pagina's moeten BINNEN het aantal pagina's vallen dat wij echt
# bekijken, anders staan ze er wel maar worden ze nooit bereikt.
_privacy = _cv.PADEN.index("/privacybeleid")
klopt(f"en het privacybeleid wordt echt bereikt (plek {_privacy + 2} van {_cv.MAX_PAGINAS})",
      _privacy + 2 <= _cv.MAX_PAGINAS)

print("\n== winkels zonder adres krijgen een tweede kans ==")
# Op 12 september stonden er 476 winkels op "geen adres" tegen 157 met een
# adres. Driekwart van alles wat de vinder oplevert werd dus weggegooid, en dat
# zijn winkels waarvoor al betaald is om ze te vinden.
#
# Het zoeken is die nacht verbeterd (tien pagina's in plaats van vijf, en de
# juridische pagina's hoog in de lijst), maar zoek_adressen kijkt alleen naar
# winkels op "nieuw". Voor die 476 was de verbetering dus voor niets. Deze
# herkansing geeft ze alsnog een kans, precies een keer per winkel.
import contactvinder as _cv2  # noqa: E402

_UNIEK = os.urandom(4).hex()
_MET = f"https://herkans-wel-{_UNIEK}.nl"
_ZONDER = f"https://herkans-niet-{_UNIEK}.nl"
for _u in (_MET, _ZONDER):
    db.voeg_benaderingen_toe([(_u, "Herkanstest", "NL", None)])
    db.zet_benadering(_u, stand="geen_adres", notitie="Niets gevonden.")

_echt_zoeken = _cv2.zoek_adres
_gezien = []


def _nep_zoek(url, **kw):
    _gezien.append(url)
    if _MET in url:
        return {"adres": "info@herkans.nl", "algemeen": True,
                "vandaan": "privacybeleid", "alles": [], "reden": None}
    return {"adres": None, "algemeen": False, "vandaan": None, "alles": [],
            "reden": "Niets gevonden."}


_cv2.zoek_adres = _nep_zoek
benadering.contactvinder.zoek_adres = _nep_zoek
_uit = benadering.herkans_adressen(hoeveel=50)
klopt("er zijn winkels opnieuw bekeken", _uit["bekeken"] >= 2)
klopt("en er is er minstens een gevonden", _uit["gevonden"] >= 1)

_standen = {r["webshop_url"]: r["stand"]
            for r in db.get_benaderingen(alleen_niet_afgemeld=False)}
zo("de winkel met een adres staat nu op 'adres'", _standen.get(_MET), "adres")
zo("die zonder blijft op 'geen_adres'", _standen.get(_ZONDER), "geen_adres")

print("\n== maar precies een keer, niet elke ronde opnieuw ==")
# Zonder deze rem loopt elke ronde dezelfde honderden winkels opnieuw langs.
# Dat is niet netjes tegenover die winkels en het levert niets op.
_voor = len(_gezien)
benadering.herkans_adressen(hoeveel=50)
_nieuw_bekeken = [u for u in _gezien[_voor:] if _ZONDER in u]
zo("dezelfde winkel wordt niet nog eens bekeken", _nieuw_bekeken, [])

_cv2.zoek_adres = _echt_zoeken
benadering.contactvinder.zoek_adres = _echt_zoeken

print("\n== en de ronde doet het uit zichzelf ==")
_bron = lees("app.py")
klopt("de ronde roept de herkansing aan", "benadering.herkans_adressen()" in _bron)
klopt("en zet het in het verslag", 'verslag["herkansing"]' in _bron)
klopt("een fout daarin legt de ronde niet stil", "adressen herkansen" in _bron)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
