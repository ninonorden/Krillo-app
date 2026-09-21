"""De homepage raakt de database niet meer bij elk bezoek.

WAAROM DEZE TEST BESTAAT

Op 19 september kon Google Search Console krilloai.com niet verifieren: "er is
een time-out opgetreden bij de verbinding met uw server". Nino zag hetzelfde als
bezoeker, tien seconden voor de homepage er stond.

Gemeten: elk bezoek aan de homepage haalde 9 keer een databaseverbinding op en
stelde samen 24 vragen, plus een schrijfopdracht voor de bezoekteller waar de
bezoeker op wachtte. Bij het testen
merk je dat niet, want de database staat dan op dezelfde machine. Live staat hij
bij Neon in Frankfurt, en valt hij na een paar minuten stilte in slaap.

De cijfers op de homepage veranderen maar een keer per nacht. Ze worden nu
onthouden en op de achtergrond ververst. Deze test telt hoe vaak een bezoek nog
een databaseverbinding ophaalt. Dat hoort nul te zijn. Komt er ooit weer een
databasevraag in het pad van de bezoeker, dan valt deze test om.

(Eerst geprobeerd met de tellers van Postgres zelf, pg_stat_database. Die
worden met vertraging bijgewerkt en gaven een verschil van -1. Een meting die
niet klopt is erger dan geen meting, dus nu wordt er in de code geteld.)
"""
import os
import sys
import time

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

import db  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


_geleend = [0]
_echte_verbinding = db._get_connection


def _tellende_verbinding(*a, **kw):
    """Telt elke keer dat de code een verbinding bij de database ophaalt.

    Elke functie in db.py begint met _get_connection(), en elke keer is dat bij
    Neon minstens een heenreis (er zit een gezondheidscontrole in). Dus het
    aantal keren dat deze functie aangeroepen wordt is precies het aantal keren
    dat een bezoeker op Frankfurt wacht."""
    _geleend[0] += 1
    return _echte_verbinding(*a, **kw)


def vragen_teller():
    return _geleend[0]


db.init_db()
db._get_connection = _tellende_verbinding
import app  # noqa: E402

app.app.config["TESTING"] = True
k = app.app.test_client()
MENS = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15", "Host": "krilloai.com"}

print("\n== BIJ HET TESTEN STAAT HET GEHEUGEN UIT ==")
# Anders zien alle andere tests de homepage van een vorige test.
klopt("uit bij het testen", app._thuis_onthouden_aan() is False)

print("\n== MET GEHEUGEN: EEN BEZOEK RAAKT DE DATABASE NIET ==")
app.THUIS_ONTHOUDEN = True
app._thuis.update(waarde=None, op=0.0, bezig=False)
try:
    zo("de eerste keer laadt hij", k.get("/", headers=MENS).status_code, 200)
    klopt("en daarna staat het in het geheugen", app._thuis["waarde"] is not None)

    # De bezoekteller schrijft bij het testen direct weg (zie _tel_bezoek), dus
    # een bot-browser gebruiken die niet geteld wordt. Dan meten we alleen wat
    # de homepage zelf vraagt.
    BOT = dict(MENS, **{"User-Agent": "Googlebot/2.1"})
    voor = vragen_teller()
    for _ in range(5):
        k.get("/", headers=BOT)
    na = vragen_teller()
    zo("vijf bezoeken halen nul keer een databaseverbinding op", na - voor, 0)

    print("\n== EEN VEROUDERD GEHEUGEN WORDT OP DE ACHTERGROND VERVERST ==")
    app._thuis["op"] = time.time() - app.THUIS_VERS_SECONDEN - 5
    oud = app._thuis["op"]
    t0 = time.time()
    zo("de bezoeker krijgt meteen een pagina", k.get("/", headers=BOT).status_code, 200)
    klopt("zonder te wachten op het verversen", time.time() - t0 < 2)
    for _ in range(50):
        if app._thuis["op"] != oud and not app._thuis["bezig"]:
            break
        time.sleep(0.1)
    klopt("en op de achtergrond is hij ververst", app._thuis["op"] > oud)

    print("\n== EEN LEGE UITKOMST BLIJFT NIET TIEN MINUTEN HANGEN ==")
    echt = app._bereken_thuis
    app._bereken_thuis = lambda: {"gescand": None, "index": {}, "eigen_cijfer": None}
    try:
        app._thuis["bezig"] = True
        app._ververs_thuis()
        leeftijd = time.time() - app._thuis["op"]
        klopt("een lege index wordt over een minuut opnieuw geprobeerd",
              leeftijd > app.THUIS_VERS_SECONDEN - 61)
    finally:
        app._bereken_thuis = echt
finally:
    app.THUIS_ONTHOUDEN = None
    app._thuis.update(waarde=None, op=0.0, bezig=False)

print("\n== DE INDEXPAGINA'S RAKEN DE DATABASE OOK NIET MEER ==")
# Die stelden 10 tot 11 vragen per bezoek. Zelfde reden, zelfde oplossing.
app.THUIS_ONTHOUDEN = True
app._bewaard_opslag.clear()
try:
    BOT = dict(MENS, **{"User-Agent": "Googlebot/2.1"})
    k.get("/index", headers=BOT)
    voor = vragen_teller()
    for _ in range(3):
        zo("het overzicht laadt", k.get("/index", headers=BOT).status_code, 200)
    zo("drie keer het overzicht kost nul verbindingen", vragen_teller() - voor, 0)

    # Een categoriepagina, als er in deze testdatabase een gemeten is.
    cats = db.categorieen_per_land("nl", 3)
    if cats:
        pad = f"/index/nl/{cats[0]['categorie']}"
        k.get(pad, headers=BOT)
        voor = vragen_teller()
        a = k.get(pad, headers=BOT)
        zo("een categoriepagina laadt", a.status_code, 200)
        zo("en kost daarna ook nul verbindingen", vragen_teller() - voor, 0)
    else:
        print("  (geen gemeten categorie in deze testdatabase, categoriepagina overgeslagen)")

    # Een route die een lijst sorteert of een veld toevoegt, mag het onthouden
    # origineel niet veranderen. Anders ziet de volgende bezoeker iets anders.
    eerste = app._bewaard(("proef",), lambda: [{"a": 1}])
    eerste[0]["a"] = 99
    eerste.append("rommel")
    zo("wat je terugkrijgt is een kopie", app._bewaard(("proef",), lambda: None), [{"a": 1}])
finally:
    app.THUIS_ONTHOUDEN = None
    app._bewaard_opslag.clear()

print("\n== DE BEZOEKTELLER WACHT NIET MEER OP DE DATABASE ==")
bron = open(os.path.join(APP, "app.py"), encoding="utf-8").read()
blok = bron[bron.find("def _tel_bezoek("):bron.find('@app.route("/")')]
klopt("buiten het testen schrijft hij op de achtergrond",
      "threading.Thread(target=_schrijf" in blok)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed: een bezoek aan de homepage wacht niet meer op de database.")
