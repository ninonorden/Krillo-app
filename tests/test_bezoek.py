"""De bezoekersteller: telt echte mensen, geen bots, en legt niets over ze vast.

Waarom deze test bestaat.

Er stond tot 12 september geen enkele bezoekersmeting op krillo.nl. Bij nul
verkopen was daardoor niet te zien welk probleem er was: komt er niemand, of
komt er wel iemand en haakt die af. Dat zijn twee heel verschillende problemen.

Deze teller hangt aan ELKE paginaweergave. Dat is precies de plek waar het op
11 september misging: er hing rekenwerk aan het laden van een pagina en de site
lag er een uur uit. Vandaar dat hier scherp bewaakt wordt dat het bij één regel
per bezoek blijft, dat een fout in de teller nooit de pagina meesleurt, en dat
er niets vastgelegd wordt wat tot een persoon te herleiden is. Dat laatste is
geen bijzaak: zodra er een koekje of een IP-adres in zou staan, hoort er een
cookiemelding op de site.
"""
import os
import re
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
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


db.init_db()


def leeg_de_tabel():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM bezoeken")
    conn.close()


print("\n== de tabel bestaat en neemt een bezoek aan ==")
leeg_de_tabel()
klopt("een bezoek wordt opgeslagen",
      db.noteer_bezoek("/", herkomst="linkedin", bezoeker="abc123", apparaat="telefoon"))
klopt("zonder pad gebeurt er niets", db.noteer_bezoek("") is False)

overzicht = db.bezoekoverzicht(30)
zo("er staat er een in", overzicht["totaal"]["bezoeken"], 1)
zo("van een persoon", overzicht["totaal"]["bezoekers"], 1)
zo("de bron staat erbij", overzicht["per_herkomst"][0]["herkomst"], "linkedin")
zo("en het apparaat", overzicht["per_apparaat"][0]["apparaat"], "telefoon")

print("\n== bezoeken en bezoekers zijn niet hetzelfde getal ==")
# Dit is het onderscheid waar de hele pagina om draait. Vier weergaven van twee
# mensen mag nooit als vier bezoekers op het scherm komen.
leeg_de_tabel()
for pad, wie in (("/", "een"), ("/prijzen", "een"), ("/", "twee"), ("/over-ons", "twee")):
    db.noteer_bezoek(pad, bezoeker=wie, apparaat="computer")
o = db.bezoekoverzicht(30)
zo("vier bezoeken", o["totaal"]["bezoeken"], 4)
zo("van twee mensen", o["totaal"]["bezoekers"], 2)
zo("drie verschillende pagina's", o["totaal"]["paginas"], 3)
zo("de drukste pagina staat bovenaan", o["per_pagina"][0]["pad"], "/")
zo("met twee bezoeken", o["per_pagina"][0]["bezoeken"], 2)
zo("zonder bron heet het rechtstreeks", o["per_herkomst"][0]["herkomst"], "rechtstreeks")

print("\n== een bezoek aan de site komt er echt in terecht ==")
leeg_de_tabel()
import app as krillo  # noqa: E402

krillo.app.config["TESTING"] = True
klant = krillo.app.test_client()

MENS = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) AppleWebKit/605.1.15"}

antwoord = klant.get("/", headers=MENS)
zo("de homepage laadt", antwoord.status_code, 200)
o = db.bezoekoverzicht(30)
zo("en is geteld", o["totaal"]["bezoeken"], 1)
zo("als telefoon", o["per_apparaat"][0]["apparaat"], "telefoon")

print("\n== wat er niet geteld hoort te worden ==")


def telt_niet(omschrijving, doe):
    """Tabel leeg, verzoek doen, en er hoort nog steeds niets in te staan."""
    leeg_de_tabel()
    doe()
    zo(omschrijving, db.bezoekoverzicht(30)["totaal"]["bezoeken"], 0)


telt_niet("een bot telt niet", lambda: klant.get(
    "/", headers={"User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"}))
telt_niet("een linkvoorvertoning ook niet", lambda: klant.get(
    "/", headers={"User-Agent": "WhatsApp/2.2 Link Preview Fetcher"}))
telt_niet("een verzoek zonder browsernaam ook niet", lambda: klant.get(
    "/", environ_base={"HTTP_USER_AGENT": ""}))
telt_niet("je eigen beheerpagina's tellen niet mee", lambda: klant.get(
    "/admin/bezoek?key=testsleutel", headers=MENS, follow_redirects=True))
telt_niet("een niet bestaande pagina telt niet", lambda: klant.get(
    "/bestaat-niet-12345", headers=MENS))
telt_niet("en een POST al helemaal niet", lambda: klant.post(
    "/api/scan", json={"url": "x"}, headers=MENS))

print("\n== dezelfde bezoeker wordt binnen een dag herkend ==")
leeg_de_tabel()
with krillo.app.test_request_context("/", headers=MENS,
                                     environ_base={"REMOTE_ADDR": "1.2.3.4"}):
    eerste = krillo._bezoeker_kenmerk()
with krillo.app.test_request_context("/prijzen", headers=MENS,
                                     environ_base={"REMOTE_ADDR": "1.2.3.4"}):
    tweede = krillo._bezoeker_kenmerk()
with krillo.app.test_request_context("/", headers=MENS,
                                     environ_base={"REMOTE_ADDR": "9.9.9.9"}):
    derde = krillo._bezoeker_kenmerk()
zo("twee pagina's van dezelfde persoon geven dezelfde code", eerste, tweede)
klopt("een ander adres geeft een andere code", eerste != derde)
klopt("de code is kort en onleesbaar", len(eerste) == 16 and eerste.isalnum())

# Dit is de kern van de privacybelofte op de pagina. Staat het IP-adres of de
# browsernaam er wel in, dan is het een persoonsgegeven en hoort er een
# cookiemelding en een stuk privacybeleid bij.
klopt("het IP-adres zit er niet in", "1.2.3.4" not in eerste)
klopt("de browsernaam ook niet", "Mozilla" not in eerste and "iPhone" not in eerste)

print("\n== een stukke teller mag de pagina niet meeslepen ==")
leeg_de_tabel()
echt = db.noteer_bezoek


def stuk(*a, **k):
    raise RuntimeError("database plat")


db.noteer_bezoek = stuk
try:
    antwoord = klant.get("/", headers=MENS)
    zo("de homepage laadt gewoon door", antwoord.status_code, 200)
finally:
    db.noteer_bezoek = echt

print("\n== de teller blijft één regel per bezoek ==")
bron = lees("app.py")
i = bron.find("def _tel_bezoek(")
blok = bron[i:i + 2500]
einde = blok.find("\n@app.route")
blok = blok[:einde] if einde > 0 else blok
zo("precies een schrijfopdracht in de teller", blok.count("db.noteer_bezoek"), 1)
# Geen echte lus. De twee `any(... for ...)` erin lopen over een handvol vaste
# woorden en raken de database niet; een for-opdracht op een eigen regel zou
# betekenen dat er per bezoek over rijen gelopen wordt, en dat is precies wat de
# site op 11 september platlegde.
klopt("en geen lus over rijen", "\n        for " not in blok)
klopt("alles staat in een try", "except Exception" in blok)

# De teller staat met opzet boven alle routes. Zakt hij ooit naar beneden, dan
# valt hij binnen het lichaam van een route en telt test_geenschrijfbijladen.py
# hem als een route die schrijft bij het laden.
klopt("de teller staat boven de eerste route",
      bron.find("def _tel_bezoek(") < bron.find('@app.route("/")'))

print("\n== de beheerpagina zelf ==")
# Eerst wat bezoek, anders toont de pagina terecht het lege scherm.
leeg_de_tabel()
for pad, wie in (("/", "een"), ("/prijzen", "een"), ("/", "twee")):
    db.noteer_bezoek(pad, bezoeker=wie, apparaat="computer")
antwoord = klant.get("/admin/bezoek?key=testsleutel", headers=MENS,
                     follow_redirects=True)
zo("de pagina laadt", antwoord.status_code, 200)
tekst = antwoord.get_data(as_text=True)
klopt("met de kop erop", "Bezoek aan de site" in tekst)
klopt("en de uitleg dat er geen koekje gebruikt wordt",
      "geen koekje" in tekst or "geen cookiemelding" in tekst)
klopt("de trechter van bezoek naar scan naar betaling staat erop",
      "Gratis scan gedaan" in tekst and "Betaald" in tekst)

print("\n== zonder inloggen kom je er niet in ==")
kaal = krillo.app.test_client()
antwoord = kaal.get("/admin/bezoek", headers=MENS)
klopt("doorgestuurd naar het inlogscherm",
      antwoord.status_code in (301, 302) and "/admin/inloggen" in antwoord.headers.get("Location", ""))

leeg_de_tabel()

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
