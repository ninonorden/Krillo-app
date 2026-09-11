"""Het onderzoek: de publieke pagina, de eigen uitkomst per winkel, en de mail.

Waar het hier mis kan gaan zonder dat je het merkt:
- Namen van winkels op de publieke pagina. Dan is het geen onderzoek meer maar
  een lijst met wie het slecht doet, en dan opent niemand hem meer.
- Een link naar de uitkomst die te raden is. Die gaat naar iemand die er niet
  om vroeg, en hij kan hem doorsturen.
- Een winkel die als gemaild geldt terwijl de mail mislukte. Dan sla je hem
  over en heeft hij nooit iets gehad.
"""
import os
import sys
import types

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

fouten = []


def klopt(omschrijving, voorwaarde):
    return zo(omschrijving, bool(voorwaarde), True)


def zo(omschrijving, gekregen, verwacht):
    if gekregen != verwacht:
        fouten.append(f"FOUT: {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
    else:
        print(f"  ok  {omschrijving}")


nep = types.ModuleType("payments")
nep.AUDIT_PRICE = nep.MONITORING_PRICE = nep.UITVOERING_PRICE = {"currency": "EUR", "value": "1"}
for naam in ("create_audit_payment", "create_monitoring_signup", "create_uitvoering_payment"):
    setattr(nep, naam, lambda *a, **k: {"error": "niet in deze test"})
nep.get_payment_status = lambda pid: None
nep.create_subscription = lambda cid: {}
nep.list_active_monitoring_customers = lambda: []
nep.list_recent_orders = lambda limit=25: []
nep.zoek_abonnement = lambda u: None
nep.zeg_abonnement_op = lambda a, b: {"ok": True}
sys.modules["payments"] = nep

import db
import app as krillo
import emailing

WINKEL = "https://geheimewinkel.nl"

verstuurd = []
emailing.send_email = lambda to, onderwerp, html, koppen=None: (
    verstuurd.append({"to": to, "onderwerp": onderwerp, "html": html,
                      "koppen": koppen}) or True)

krillo._klantgegevens = lambda url: {
    "vermeldingen": {"genoemd": 2, "telbaar": 20, "aanbevolen": 0,
                     "concurrenten": [{"naam": "Bol.com", "genoemd": 7, "wij": False},
                                      {"naam": "Coolblue", "genoemd": 5, "wij": False}]},
    "actieplan": {"kop": "x", "acties": [
        {"id": "faq", "soort": "feit", "titel": "Zet je teksten direct in de pagina",
         "waarom": "AI kan je productteksten nu niet lezen.", "hoe": "x",
         "links": [], "oplossing": None, "waar": None}], "rest": 0},
    "controle": None, "beweging": None, "bronnen": None}

conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()
db.init_db()
client = krillo.app.test_client()

print("\n== het kenmerk per winkel ==")
token = db.get_benchmark_token(WINKEL)
zo("er komt een kenmerk", bool(token), True)
zo("het is niet te raden", len(token) >= 24, True)
zo("twee keer vragen geeft hetzelfde", db.get_benchmark_token(WINKEL), token)
zo("een andere winkel krijgt een ander kenmerk",
   db.get_benchmark_token("https://andere.nl") != token, True)
zo("we vinden de winkel terug", db.winkel_bij_benchmark_token(token), WINKEL)
zo("een verzonnen kenmerk geeft niets", db.winkel_bij_benchmark_token("zelfbedacht"), None)
zo("leeg geeft niets", db.winkel_bij_benchmark_token(""), None)

print("\n== de eigen uitkomstpagina ==")
r = client.get(f"/uitkomst/{token}")
zo("laadt", r.status_code, 200)
p = r.get_data(as_text=True)
zo("toont het cijfer", "genoemd bij 2 van de 20" in p.lower() or "2 van de 20" in p, True)
zo("noemt de concurrenten", "Bol.com" in p, True)
zo("legt uit waarom hij deze mail kreeg", "meegenomen in ons onderzoek" in p, True)
zo("zegt hoe je eraf komt", "weghalen" in p, True)
zo("wordt niet geindexeerd", 'name="robots" content="noindex' in p, True)
zo("bevat geen kant-en-klare tekst om te plakken", "Neem dit letterlijk over" in p, False)

zo("een verzonnen kenmerk geeft 404", client.get("/uitkomst/onzin").status_code, 404)

print("\n== de publieke onderzoekspagina ==")
r = client.get("/onderzoek")
zo("laadt", r.status_code, 200)
p = r.get_data(as_text=True)
zo("meldt eerlijk dat er te weinig gemeten is", "loopt nog" in p, True)
zo("noemt GEEN winkelnamen", "geheimewinkel" in p, False)
zo("legt de methode uit", "per vraag en niet per antwoord" in p, True)

print("\n== de beheerpagina voor de mails ==")
# Sinds de beheerpagina's achter een inlogscherm zitten is 302 (doorsturen naar
# /admin/inloggen) het goede antwoord, en geen 404 meer. En let op: een client
# die eerder MET sleutel binnenkwam blijft ingelogd, dus voor de dichte kant
# hoort een VERSE bezoeker gebruikt te worden.
zo("zonder sleutel dicht",
   krillo.app.test_client().get("/admin/onderzoeksmail").status_code, 302)
zo("met sleutel open",
   krillo.app.test_client().get("/admin/onderzoeksmail?key=testsleutel",
                                follow_redirects=True).status_code, 200)

print("\n== een adres bewaren ==")
r = client.post("/admin/onderzoeksmail?key=testsleutel",
                data={"url": "geheimewinkel.nl", "email": "eigenaar@geheimewinkel.nl",
                      "actie": "bewaren"})
zo("geeft een pagina terug", r.status_code, 200)
zo("het adres is bewaard",
   (db.get_winkelprofiel(WINKEL) or {}).get("contact_email"), "eigenaar@geheimewinkel.nl")
zo("er is niets verstuurd", len(verstuurd), 0)
zo("en niets als gemaild gemarkeerd",
   (db.get_winkelprofiel(WINKEL) or {}).get("onderzoeksmail_op"), None)

print("\n== een verkeerd adres wordt geweigerd ==")
r = client.post("/admin/onderzoeksmail?key=testsleutel",
                data={"url": "geheimewinkel.nl", "email": "geenadres", "actie": "versturen"})
zo("wordt gemeld", "geldig e-mailadres" in r.get_data(as_text=True), True)
zo("en er gaat niets uit", len(verstuurd), 0)

print("\n== versturen ==")
r = client.post("/admin/onderzoeksmail?key=testsleutel",
                data={"url": "geheimewinkel.nl", "email": "eigenaar@geheimewinkel.nl",
                      "actie": "versturen"})
zo("er is een mail verstuurd", len(verstuurd), 1)
zo("naar het juiste adres", verstuurd[0]["to"], "eigenaar@geheimewinkel.nl")
h = verstuurd[0]["html"]
zo("met het eigen cijfer erin", "2 van de 20" in h, True)
zo("zonder https in de zin", "https://geheimewinkel" in h.split("<a ")[0], False)
zo("met de link naar zijn pagina", f"/uitkomst/{token}" in h, True)
# De afmeldregel. Zonder afmeldlink meegegeven valt hij terug op "antwoord
# op deze mail", en dat moet er dan ook echt staan.
zo("met de afmeldregel", ("antwoord dan op deze mail" in h) or ("/afmelden/" in h), True)
# BEWUST geen prijs in deze mail. Toetsen op het cijfer 79 kan niet: het
# kenmerk in de link is willekeurig en bevat soms toevallig die cijfers.
zo("zonder prijs in de mail", ("euro" in h.lower()) or ("&euro;" in h) or ("€" in h), False)
zo("staat nu als gemaild",
   (db.get_winkelprofiel(WINKEL) or {}).get("onderzoeksmail_op") is not None, True)

print("\n== als de mail mislukt blijft hij ongemarkeerd ==")
db.get_benchmark_token("https://tweede.nl")
emailing.send_email = lambda *a, **k: False
r = client.post("/admin/onderzoeksmail?key=testsleutel",
                data={"url": "tweede.nl", "email": "info@tweede.nl", "actie": "versturen"})
zo("wordt gemeld", "NIET verstuurd" in r.get_data(as_text=True), True)
zo("en niet als gemaild gemarkeerd",
   (db.get_winkelprofiel("https://tweede.nl") or {}).get("onderzoeksmail_op"), None)

print("\n== de mail weigert zonder link ==")
zo("geen link, geen mail",
   emailing.send_onderzoeksmail("a@b.nl", "https://x.nl", None), False)
zo("geen adres, geen mail",
   emailing.send_onderzoeksmail("", "https://x.nl", "https://k.nl/uitkomst/x"), False)

print("\n== het eigen cijfer op de homepage ==")
# De probleemsectie leunde op een Amerikaans onderzoek naar merken. Zodra wij
# genoeg Nederlandse webshops zelf gemeten hebben hoort ons eigen cijfer daar te
# staan, en daaronder niet. Een eigen cijfer over negen winkels is geen
# onderzoek, en het zo noemen is precies de overpromising waar Krillo van weg
# wil blijven.
import jinja2  # noqa: E402
import app as _krillo  # noqa: E402

_env = jinja2.Environment(loader=jinja2.FileSystemLoader(
    os.path.join(APP, "templates")))
_env.filters.setdefault("urlencode", lambda s: s)
_index = _env.get_template("index.html")

_zonder = _index.render(gescand=None, eigen_cijfer=None)
klopt("zonder eigen cijfer blijft het onderzoek staan", "21.000 vermeldingen" in _zonder)
klopt("en staat ons cijfer er niet", "die wij zelf maten" not in _zonder)

_met = _index.render(gescand=200, eigen_cijfer={"gemeten": 40, "nooit": 26, "deel": 65})
klopt("met eigen cijfer staat ons cijfer er", "die wij zelf maten" in _met)
klopt("met het percentage", "65%" in _met)
klopt("en het aantal winkels", "40 Nederlandse webshops" in _met)
klopt("het Amerikaanse onderzoek is dan weg", "21.000 vermeldingen" not in _met)

print("\n== de ondergrens is dezelfde als in de mail ==")
# Twee verschillende ondergrenzen voor hetzelfde woord "onderzoek" is hoe je
# jezelf tegenspreekt: op de site een onderzoek noemen bij 25 winkels en in de
# mail bij 40, of andersom.
klopt("de homepage gebruikt dezelfde grens als de onderzoeksmail",
      _krillo.MINIMUM_WINKELS_VOOR_VERGELIJKING >= 25)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
