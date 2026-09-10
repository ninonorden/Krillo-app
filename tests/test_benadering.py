"""De automatische benadering: adres zoeken, de rem, en de afmelding.

Waar dit stil fout kan gaan, en dus waar deze test op let:
- Een persoonlijk mailadres dat er toch doorheen glipt. In Belgie mag dat niet.
- Een winkel die twee keer post krijgt omdat de stand niet omging.
- Een winkel die als gemaild geldt terwijl de mail mislukte. Dan krijgt hij
  nooit meer iets.
- Een rem die niet remt: uit staan, nacht, of de dagrem bereikt moeten alle
  drie op nul uitkomen.
- Een afmelding die niet werkt. Dat is het verschil tussen een afmelding en een
  spamklacht, en een spamklacht kost je het domein.
"""
import os
import sys
import types
from datetime import datetime

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["CRON_KEY"] = "cronsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, TEMPLATES  # noqa: E402
sys.path.insert(0, APP)

fouten = []


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

import contactvinder
import db
import benadering
import emailing
import app as krillo

conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()
db.init_db()
client = krillo.app.test_client()

# ---------------------------------------------------------------- adressen

print("\n== welk adres mogen wij gebruiken ==")
D = "winkel.nl"
zo("algemeen op eigen domein mag",
   (contactvinder._bruikbaar("info@winkel.nl", D) or {}).get("algemeen"), True)
zo("hallo@ mag ook",
   (contactvinder._bruikbaar("hallo@winkel.nl", D) or {}).get("algemeen"), True)
zo("klantenservice@ mag",
   (contactvinder._bruikbaar("klantenservice@winkel.nl", D) or {}).get("algemeen"), True)
zo("een voornaam is niet algemeen",
   (contactvinder._bruikbaar("sanne@winkel.nl", D) or {}).get("algemeen"), False)
zo("voornaam.achternaam is niet algemeen",
   (contactvinder._bruikbaar("sanne.dejong@winkel.nl", D) or {}).get("algemeen"), False)
zo("noreply valt af", contactvinder._bruikbaar("noreply@winkel.nl", D), None)
zo("een adres van de bouwer valt af",
   contactvinder._bruikbaar("support@shopify.com", D), None)
zo("een plaatjesnaam valt af",
   contactvinder._bruikbaar("logo@2x.png", D), None)
zo("een vreemd domein valt af",
   contactvinder._bruikbaar("info@heelietsanders.nl", D), None)
zo("gmail van de eigenaar mag wel",
   (contactvinder._bruikbaar("info@gmail.com", D) or {}).get("algemeen"), True)
zo("geen apenstaartje valt af", contactvinder._bruikbaar("gewoontekst", D), None)
zo("twee apenstaartjes vallen af", contactvinder._bruikbaar("a@b@c.nl", D), None)

print("\n== adressen van een pagina plukken ==")
pagina = """
<html><body>
  <script>var melder = "fout@sentry.io";</script>
  <p>Bel ons of mail naar sanne@winkel.nl</p>
  <a href="mailto:info@winkel.nl?subject=hoi">Mail ons</a>
  <a href="mailto:noreply@winkel.nl">niet doen</a>
</body></html>
"""
uit = contactvinder._uit_pagina(pagina, "https://winkel.nl", D)
adressen = [a["adres"] for a in uit]
zo("de mailto-link staat er als eerste in", adressen[0], "info@winkel.nl")
zo("het persoonlijke adres wordt wel gezien", "sanne@winkel.nl" in adressen, True)
zo("de foutmelder komt er niet in", any("sentry" in a for a in adressen), False)
zo("noreply komt er niet in", any("noreply" in a for a in adressen), False)

print("\n== een winkel afzoeken ==")


class NepAntwoord:
    def __init__(self, tekst, code=200):
        self.text, self.status_code = tekst, code


bezochte = []


def nep_get(url, **kw):
    bezochte.append(url)
    if url.rstrip("/").endswith("contact"):
        return NepAntwoord('<a href="mailto:info@testwinkel.nl">mail</a>')
    return NepAntwoord("<p>Welkom in onze winkel</p>")


contactvinder.requests.get = nep_get
uit = contactvinder.zoek_adres("testwinkel.nl")
zo("vindt het adres", uit["adres"], "info@testwinkel.nl")
zo("noemt het algemeen", uit["algemeen"], True)
zo("zegt waar het vandaan komt", uit["vandaan"], "mailto-link")
zo("stopt na de vondst", len(bezochte) <= 3, True)

contactvinder.requests.get = lambda url, **kw: NepAntwoord("<p>Niks hier</p>")
uit = contactvinder.zoek_adres("leegwinkel.nl")
zo("geen adres geeft geen adres", uit["adres"], None)
zo("met een reden erbij", bool(uit["reden"]), True)

contactvinder.requests.get = lambda url, **kw: NepAntwoord(
    '<a href="mailto:sanne@persoonlijk.nl">Sanne</a>')
uit = contactvinder.zoek_adres("persoonlijk.nl")
zo("een persoonlijk adres wordt niet gebruikt", uit["adres"], None)
zo("maar wel getoond zodat jij het zelf kan bekijken",
   "sanne@persoonlijk.nl" in uit["alles"], True)

# ---------------------------------------------------------------- de lijst

print("\n== de lijst erin ==")
uit = benadering.voeg_lijst_toe("""
# dit is een opmerking
eerstewinkel.nl ; Eerste ; NL ; wonen
tweedewinkel.be;Tweede;BE;mode
https://derdewinkel.nl
onzin zonder punt
""")
zo("drie nieuwe winkels", uit["nieuw"], 3)
zo("een regel overgeslagen", len(uit["fout"]), 1)
zo("het land is bewaard",
   (db.get_benadering("https://tweedewinkel.be") or {}).get("land"), "BE")

uit = benadering.voeg_lijst_toe("eerstewinkel.nl ; Eerste ; NL ; wonen")
zo("dezelfde winkel komt er niet nog een keer bij", uit["nieuw"], 0)
zo("hij wordt herkend als bekend", uit["al_bekend"], 1)

db.zet_benadering("https://eerstewinkel.nl", stand="gemaild", gemaild=True)
benadering.voeg_lijst_toe("eerstewinkel.nl")
zo("een gemailde winkel valt niet terug naar nieuw",
   db.get_benadering("https://eerstewinkel.nl")["stand"], "gemaild")

print("\n== een grote lijst in een keer ==")
import time as _tijd
grote = "\n".join(f"winkel{i}.nl ; Winkel {i} ; NL ; test" for i in range(250))
_start = _tijd.monotonic()
uit = benadering.voeg_lijst_toe(grote)
_duur = _tijd.monotonic() - _start
zo("alle 250 komen erin", uit["nieuw"], 250)
zo("en het duurt geen halve minuut", _duur < 15, True)

uit = benadering.voeg_lijst_toe(grote)
zo("dezelfde lijst nog een keer voegt niets toe", uit["nieuw"], 0)
zo("en telt ze als bekend", uit["al_bekend"], 250)

# Twee keer dezelfde winkel in een geplakte lijst. Zonder afvangen valt de hele
# invoer om en zie je een foutmelding in plaats van je lijst.
uit = benadering.voeg_lijst_toe("dubbel.nl\ndubbel.nl\ndubbel.nl")
zo("een dubbele regel laat de rest niet omvallen", uit["nieuw"], 1)

zo("een onbekende stand wordt geweigerd",
   db.zet_benadering("https://eerstewinkel.nl", stand="zomaarwat"), False)
zo("en verandert niets",
   db.get_benadering("https://eerstewinkel.nl")["stand"], "gemaild")

# ---------------------------------------------------------------- de rem

print("\n== de rem ==")
db.zet_instelling("benadering_aan", "nee")
mag, reden = benadering.hoeveel_mag_er_nu()
zo("uit betekent nul", mag, 0)
zo("met uitleg", "uit" in (reden or ""), True)

db.zet_instelling("benadering_aan", "ja")
db.zet_instelling("mail_per_dag", 15)
db.zet_instelling("mail_per_ronde", 3)
nacht = datetime(2026, 9, 4, 3, 0)
zo("drie uur 's nachts is geen kantooruur", benadering.binnen_kantooruren(nacht), False)
zo("tien uur 's ochtends wel",
   benadering.binnen_kantooruren(datetime(2026, 9, 4, 10, 0)), True)
zo("acht uur is de eerste", benadering.binnen_kantooruren(datetime(2026, 9, 4, 8, 0)), True)
zo("acht uur 's avonds niet meer",
   benadering.binnen_kantooruren(datetime(2026, 9, 4, 20, 0)), False)
mag, reden = benadering.hoeveel_mag_er_nu(nacht)
zo("'s nachts gaat er niets uit", mag, 0)

overdag = datetime(2026, 9, 4, 11, 0)
mag, reden = benadering.hoeveel_mag_er_nu(overdag)
zo("overdag mag er wel wat", mag, 3)
zo("zonder reden om te stoppen", reden, None)

db.zet_instelling("mail_per_dag", 1)
mag, reden = benadering.hoeveel_mag_er_nu(overdag)
zo("de dagrem gaat voor de rondelimiet", mag, 0)
zo("en wordt uitgelegd", "dagrem" in (reden or "").lower(), True)

db.zet_instelling("mail_per_dag", 5)
mag, reden = benadering.hoeveel_mag_er_nu(overdag)
zo("er is er al een gemaild vandaag, dus vier over", mag, 3)

db.zet_instelling("mail_per_ronde", 10)
mag, reden = benadering.hoeveel_mag_er_nu(overdag)
zo("de rondelimiet wordt door de dagrem begrensd", mag, 4)

# ---------------------------------------------------------------- wie is er aan de beurt

print("\n== wie er post krijgt ==")
db.voeg_benadering_toe("https://klaar.nl", land="NL")
db.zet_benadering("https://klaar.nl", stand="gemeten", email="info@klaar.nl")
db.voeg_benadering_toe("https://zonderadres.nl")
db.zet_benadering("https://zonderadres.nl", stand="gemeten")
db.voeg_benadering_toe("https://afgemeld.nl")
db.zet_benadering("https://afgemeld.nl", stand="gemeten", email="info@afgemeld.nl")
db.meld_benadering_af("https://afgemeld.nl")

beurt = [w["webshop_url"] for w in benadering.te_mailen(10)]
zo("de gemeten winkel met adres is aan de beurt", "https://klaar.nl" in beurt, True)
zo("zonder adres geen post", "https://zonderadres.nl" in beurt, False)
zo("afgemeld is afgemeld", "https://afgemeld.nl" in beurt, False)
zo("de al gemailde winkel komt niet terug", "https://eerstewinkel.nl" in beurt, False)

print("\n== een mislukte verzending ==")
benadering.markeer_gemaild("https://klaar.nl", False, "Brevo deed het niet")
r = db.get_benadering("https://klaar.nl")
zo("de stand blijft gemeten", r["stand"], "gemeten")
zo("er staat geen datum bij", r["gemaild_op"], None)
zo("de reden is bewaard", "Brevo" in (r["notitie"] or ""), True)
zo("hij komt gewoon weer langs",
   "https://klaar.nl" in [w["webshop_url"] for w in benadering.te_mailen(10)], True)

print("\n== een gelukte verzending ==")
benadering.markeer_gemaild("https://klaar.nl", True)
r = db.get_benadering("https://klaar.nl")
zo("de stand gaat om", r["stand"], "gemaild")
zo("met een datum erbij", r["gemaild_op"] is not None, True)
zo("en hij komt niet nog een keer langs",
   "https://klaar.nl" in [w["webshop_url"] for w in benadering.te_mailen(10)], False)

# ---------------------------------------------------------------- de mail

print("\n== de mail zelf ==")
verstuurd = []
emailing.send_email = lambda to, onderwerp, html, koppen=None: (
    verstuurd.append({"to": to, "onderwerp": onderwerp, "html": html,
                      "koppen": koppen}) or True)

gelukt = emailing.send_onderzoeksmail(
    "info@klaar.nl", "https://klaar.nl", "https://www.krillo.nl/uitkomst/abc",
    genoemd=2, telbaar=20, nooit_genoemd=31, gemeten=60,
    afmeld_url="https://www.krillo.nl/afmelden/abc", land="NL")
zo("hij gaat eruit", gelukt, True)
h = verstuurd[0]["html"]
zo("met het eigen cijfer", "2 van de 20" in h, True)
zo("met een werkende afmeldlink", "/afmelden/abc" in h, True)
zo("met de afmeldkop erbij",
   verstuurd[0]["koppen"].get("List-Unsubscribe"), "<https://www.krillo.nl/afmelden/abc>")
zo("met de een-klik-kop",
   verstuurd[0]["koppen"].get("List-Unsubscribe-Post"), "List-Unsubscribe=One-Click")
zo("zonder prijs", ("euro" in h.lower()) or ("€" in h), False)

verstuurd.clear()
emailing.send_onderzoeksmail(
    "info@tweedewinkel.be", "https://tweedewinkel.be", "https://www.krillo.nl/uitkomst/x",
    afmeld_url="https://www.krillo.nl/afmelden/x", land="BE")
zo("een Belgische winkel heet geen Nederlandse webshop",
   "Belgische en Nederlandse" in verstuurd[0]["html"], True)

zo("zonder link gaat er niets uit",
   emailing.send_onderzoeksmail("a@b.nl", "https://x.nl", None), False)

# ---------------------------------------------------------------- de pagina's

print("\n== de pagina's ==")
zo("de beheerpagina is dicht zonder sleutel",
   client.get("/admin/benadering").status_code, 404)
zo("en open met sleutel",
   client.get("/admin/benadering?key=testsleutel").status_code, 200)
zo("de cron is dicht zonder sleutel",
   client.get("/api/cron/benadering").status_code, 404)
zo("en open met sleutel",
   client.get("/api/cron/benadering?key=cronsleutel").status_code, 200)

print("\n== afmelden ==")
db.voeg_benadering_toe("https://afmelder.nl")
db.zet_benadering("https://afmelder.nl", stand="gemaild", email="info@afmelder.nl")
kenmerk = db.get_benchmark_token("https://afmelder.nl")
r = client.get(f"/afmelden/{kenmerk}")
zo("de pagina laadt", r.status_code, 200)
zo("hij zegt dat het gelukt is", "geregeld" in r.get_data(as_text=True), True)
zo("wordt niet geindexeerd", 'content="noindex' in r.get_data(as_text=True), True)
r = db.get_benadering("https://afmelder.nl")
zo("hij staat als afgemeld", r["afgemeld"], True)
zo("en op afgevallen", r["stand"], "afgevallen")

zo("een verzonnen link geeft 404", client.get("/afmelden/verzonnen").status_code, 404)
zo("een verzonnen link op POST ook",
   client.post("/afmelden/verzonnen").status_code, 404)

db.voeg_benadering_toe("https://tweedeafmelder.nl")
db.zet_benadering("https://tweedeafmelder.nl", stand="gemaild")
kenmerk2 = db.get_benchmark_token("https://tweedeafmelder.nl")
zo("de knop van Gmail werkt ook (POST)",
   client.post(f"/afmelden/{kenmerk2}").status_code, 200)
zo("en meldt hem echt af",
   db.get_benadering("https://tweedeafmelder.nl")["afgemeld"], True)

print("\n== een afmelding houdt overal stand ==")
# Een winkel die WEL gemeten is maar NIET op de benaderlijst staat. Dat is het
# geval waarin de afmelding stilzwijgend nergens landde.
LOS = "https://losgemeten.nl"
los_kenmerk = db.get_benchmark_token(LOS)
zo("hij staat niet op de benaderlijst", db.get_benadering(LOS), None)
r = client.get(f"/afmelden/{los_kenmerk}")
zo("afmelden lukt toch", r.status_code, 200)
zo("en zegt dat het geregeld is", "geregeld" in r.get_data(as_text=True), True)
zo("en het is echt bewaard", db.is_afgemeld(LOS), True)

emailing.send_email = lambda *a, **k: True
gelukt, reden = krillo._stuur_onderzoeksmail(LOS, "info@losgemeten.nl", "NL")
zo("er gaat geen post meer heen", gelukt, False)
zo("met de juiste reden", "afgemeld" in (reden or ""), True)

zo("een winkel die zich niet afmeldde is niet afgemeld",
   db.is_afgemeld("https://tweedewinkel.be"), False)
zo("een lege winkel geldt als afgemeld (bij twijfel niet mailen)",
   db.is_afgemeld(""), True)

print("\n== de knop met de hand respecteert de afmelding ==")
r = client.post("/admin/onderzoeksmail?key=testsleutel",
                data={"url": "losgemeten.nl", "email": "info@losgemeten.nl",
                      "actie": "versturen"})
zo("hij weigert", "afgemeld" in r.get_data(as_text=True), True)

print("\n== de automatische ronde markeert op beide plekken ==")
db.voeg_benadering_toe("https://beide.nl", land="NL")
db.zet_benadering("https://beide.nl", stand="gemeten", email="info@beide.nl")
krillo._stuur_onderzoeksmail = lambda u, e, l=None: (True, None)
db.zet_instelling("benadering_aan", "ja")
db.zet_instelling("mail_per_dag", 50)
db.zet_instelling("mail_per_ronde", 5)
if benadering.binnen_kantooruren():
    for w in benadering.te_mailen(5):
        gelukt, fout = krillo._stuur_onderzoeksmail(w["webshop_url"], w["email"])
        benadering.markeer_gemaild(w["webshop_url"], gelukt, fout)
        if gelukt:
            db.markeer_onderzoeksmail(w["webshop_url"])
    zo("de benaderlijst weet het",
       db.get_benadering("https://beide.nl")["gemaild_op"] is not None, True)
    zo("en het winkelprofiel ook",
       (db.get_winkelprofiel("https://beide.nl") or {}).get("onderzoeksmail_op") is not None,
       True)
else:
    print("  --  overgeslagen, het is nu buiten de verzenduren")

print("\n== tellen ==")
t = db.tel_benaderingen()
zo("het totaal klopt", t["totaal"], len(db.get_benaderingen(alleen_niet_afgemeld=False)))
zo("er is er vandaag een gemaild", t["vandaag_gemaild"] >= 1, True)

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
