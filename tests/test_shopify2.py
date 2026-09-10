"""Stap 2: het kaartje van Shopify en het scherm binnen het beheerscherm.

Het kaartje (id_token) is hier de hele beveiliging. Wie een geldig kaartje kan
namaken, kan onze toegangssleutel tot een winkel opvragen. Daarom test dit
bestand vooral wat er NIET door mag: een verlopen kaartje, een kaartje voor een
andere app, een kaartje met een andere handtekening, en het klassieke trucje
waarbij iemand "geen ondertekening" opgeeft.
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import types

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["SHOPIFY_API_KEY"] = "test-client-id"
os.environ["SHOPIFY_API_SECRET"] = "test-geheim"
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

import db
import shopify_app
import app as krillo

WINKEL = "krillo-test.myshopify.com"
GEHEIM = "test-geheim"

ingewisseld = []
shopify_app.wissel_id_token = lambda winkel, token: (
    ingewisseld.append(winkel) or {"gelukt": True, "sleutel": "shpat_nieuw",
                                   "rechten": shopify_app.SCOPES,
                                   # De geldigheid moet mee, anders slaan wij
                                   # een sleutel op die meteen verlopen is en
                                   # wisselt de app bij elke pagina opnieuw in.
                                   "geldig_seconden": 3599,
                                   "verversleutel": "shprt_test",
                                   "verversleutel_seconden": 7775999})
shopify_app.winkelgegevens = lambda winkel, sleutel: {
    "naam": "Krillo Test", "email": "eigenaar@krillo-test.nl", "domein": "krillo-test.nl"}
shopify_app.meld_webhooks_aan = lambda w, s, b: {"gelukt": [], "mislukt": []}

gemeten = []
krillo._meet_en_beoordeel = lambda url, **kw: gemeten.append(url)
krillo.run_scan = lambda url: {"url": url, "score": 62, "checks": []}


def maak_kaartje(winkel=WINKEL, aud="test-client-id", geheim=GEHEIM,
                 exp=None, nbf=None, alg="HS256", dest=None):
    nu = int(time.time())
    kop = {"alg": alg, "typ": "JWT"}
    inhoud = {
        "iss": f"https://{winkel}/admin",
        "dest": dest if dest is not None else f"https://{winkel}",
        "aud": aud,
        "sub": "1",
        "exp": exp if exp is not None else nu + 60,
        "nbf": nbf if nbf is not None else nu - 10,
        "iat": nu,
        "jti": "abc",
        "sid": "def",
    }

    def stuk(d):
        return base64.urlsafe_b64encode(
            json.dumps(d).encode()).decode().rstrip("=")

    romp = f"{stuk(kop)}.{stuk(inhoud)}"
    if alg == "none":
        return f"{romp}."
    handtekening = base64.urlsafe_b64encode(
        hmac.new(geheim.encode(), romp.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    return f"{romp}.{handtekening}"


conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()
db.init_db()
client = krillo.app.test_client()

print("\n== een goed kaartje ==")
inhoud = shopify_app.controleer_id_token(maak_kaartje())
zo("wordt geaccepteerd", inhoud is not None, True)
zo("en levert de winkel op", inhoud["winkel"], WINKEL)

print("\n== en alles wat er NIET door mag ==")
for omschrijving, kaartje in [
    ("verlopen kaartje", maak_kaartje(exp=int(time.time()) - 300)),
    ("nog niet geldig", maak_kaartje(nbf=int(time.time()) + 300)),
    ("voor een andere app", maak_kaartje(aud="andere-app")),
    ("met een ander geheim ondertekend", maak_kaartje(geheim="fout-geheim")),
    ("zonder ondertekening", maak_kaartje(alg="none")),
    ("afzender en bestemming verschillen", maak_kaartje(dest="https://andere.myshopify.com")),
    ("geen Shopify-winkel", maak_kaartje(winkel="kwaadaardig.nl")),
    ("onzin", "dit.is.geenjwt"),
    ("leeg", ""),
    ("None", None),
    ("alleen twee delen", "aa.bb"),
]:
    zo(omschrijving, shopify_app.controleer_id_token(kaartje), None)

print("\n== een verlopen kaartje binnen de speling mag wel ==")
zo("vijf seconden verlopen is goed",
   shopify_app.controleer_id_token(maak_kaartje(exp=int(time.time()) - 5)) is not None, True)

print("\n== het scherm openen met een goed kaartje ==")
r = client.get(f"/shopify?shop={WINKEL}&id_token={maak_kaartje()}")
zo("de pagina laadt", r.status_code, 200)
p = r.get_data(as_text=True)
zo("het kaartje is ingewisseld", ingewisseld, [WINKEL])
zo("de winkel staat in de database", db.get_shopify_winkel(WINKEL) is not None, True)
zo("met de sleutel", db.get_shopify_winkel(WINKEL)["toegangssleutel"], "shpat_nieuw")
# Zonder vervaldatum en verversleutel is de winkel morgen onbruikbaar, want
# Shopify weigert eeuwige sleutels. Dus dat moet vastliggen.
zo("de vervaldatum is opgeslagen",
   db.get_shopify_winkel(WINKEL)["sleutel_tot"] is not None, True)
zo("de verversleutel is opgeslagen",
   db.get_shopify_winkel(WINKEL)["verversleutel"], "shprt_test")
zo("App Bridge staat bovenaan", "cdn.shopify.com/shopifycloud/app-bridge.js" in p, True)
zo("met onze client id erbij", 'data-api-key="test-client-id"' in p, True)
zo("er staat een knop om te meten", 'id="metenknop"' in p, True)
zo("en nog geen cijfers", "van de" in p and "koopvragen" in p, False)

print("\n== een tweede keer openen wisselt niet opnieuw in ==")
client.get(f"/shopify?shop={WINKEL}&id_token={maak_kaartje()}")
zo("nog steeds een keer ingewisseld", len(ingewisseld), 1)

print("\n== het scherm openen met een slecht kaartje ==")
zo("verlopen", client.get(f"/shopify?id_token={maak_kaartje(exp=1)}").status_code, 401)
zo("ander geheim",
   client.get(f"/shopify?id_token={maak_kaartje(geheim='fout')}").status_code, 401)

print("\n== een kaartje van winkel A met winkel B in de link ==")
r = client.get(f"/shopify?shop=andere.myshopify.com&id_token={maak_kaartje()}")
zo("wordt geweigerd", r.status_code, 401)

print("\n== de meting starten ==")
zo("zonder kaartje geweigerd", client.post("/shopify/api/meten").status_code, 401)
zo("met onzin geweigerd",
   client.post("/shopify/api/meten",
               headers={"Authorization": "Bearer onzin"}).status_code, 401)
zo("zonder het woord Bearer geweigerd",
   client.post("/shopify/api/meten",
               headers={"Authorization": maak_kaartje()}).status_code, 401)

r = client.post("/shopify/api/meten",
                headers={"Authorization": "Bearer " + maak_kaartje()})
zo("met een goed kaartje gaat hij lopen", r.status_code, 200)
zo("en meldt hij dat hij bezig is", r.get_json()["stand"]["klaar"], False)

for _ in range(50):
    stand = krillo._shopify_status.get(WINKEL) or {}
    if stand.get("klaar"):
        break
    time.sleep(0.1)
zo("de meting is gedraaid", gemeten, ["https://krillo-test.nl"])
zo("en staat op klaar", (krillo._shopify_status.get(WINKEL) or {}).get("klaar"), True)

# Dit ging eerst stilletjes mis: het rapport werd geweigerd omdat er geen
# e-mailadres bij zat, en dat zag je alleen in de logs. Zonder rapport is er
# geen verklaring en blijft het actieplan leeg terwijl er wel gemeten is.
rapporten = db.get_rapporten_voor_webshop("https://krillo-test.nl")
zo("het scanrapport is bewaard", len(rapporten), 1)
zo("met de score erin", rapporten[0]["score"], 62)
zo("en het adres van de winkelier", rapporten[0]["email"], "eigenaar@krillo-test.nl")

print("\n== de stand opvragen ==")
zo("zonder kaartje geweigerd", client.get("/shopify/api/stand").status_code, 401)
r = client.get("/shopify/api/stand",
               headers={"Authorization": "Bearer " + maak_kaartje()})
zo("met kaartje geeft de stand", r.get_json()["stand"]["klaar"], True)

print("\n== twee metingen tegelijk kunnen niet ==")
krillo._shopify_status[WINKEL] = {"tekst": "bezig", "klaar": False, "mislukt": False}
voor = len(gemeten)
client.post("/shopify/api/meten", headers={"Authorization": "Bearer " + maak_kaartje()})
zo("er wordt niets extra's gestart", len(gemeten), voor)

print("\n== een winkel die niet ingelezen kan worden ==")
krillo._shopify_status.pop(WINKEL, None)
krillo.run_scan = lambda url: {"error": "geblokkeerd"}
client.post("/shopify/api/meten", headers={"Authorization": "Bearer " + maak_kaartje()})
for _ in range(50):
    if (krillo._shopify_status.get(WINKEL) or {}).get("klaar"):
        break
    time.sleep(0.1)
stand = krillo._shopify_status.get(WINKEL) or {}
zo("staat als mislukt", stand.get("mislukt"), True)
zo("met een uitleg in gewone taal", "wachtwoord" in stand.get("tekst", ""), True)

print("\n== een winkel die de app al heeft krijgt GEEN tweede toestemmingsscherm ==")
# Dit is een van de dingen waarop Shopify een app afkeurt. Iemand die al
# toestemming gaf en de app opent via een bewaarde link, kreeg opnieuw de vraag
# of Krillo bij zijn producten mag.
db.bewaar_shopify_winkel(WINKEL, "shpat_al_geinstalleerd",
                         geldig_seconden=3599, verversleutel="shprt_test",
                         verversleutel_seconden=7775999, webshop_url="https://testwinkel.nl", email="a@b.nl")
r = client.get(f"/shopify?shop={WINKEL}")
zo("hij krijgt gewoon het scherm", r.status_code, 200)
p = r.get_data(as_text=True)
zo("en geen toestemmingsscherm", "/admin/oauth" in p, False)
zo("het is echt het app-scherm", "Krillo" in p, True)

print("\n== een winkel die de app NIET heeft, gaat wel naar Shopify ==")
db.shopify_verwijderd(WINKEL)
r = client.get(f"/shopify?shop={WINKEL}")
zo("krijgt een pagina in plaats van een doorverwijzing", r.status_code, 200)
p = r.get_data(as_text=True)
zo("met de link naar de goedkeuringspagina", f"https://{WINKEL}/admin/oauth" in p, True)
zo("die het bovenste venster verplaatst", "window.top" in p, True)

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")

print("\n== taal en land per winkel ==")
import markt as markt_mod
zo("Nederlands blijft de terugval", markt_mod.bepaal(None, None)["taal"], "Nederlands")
zo("en-US wordt Engels", markt_mod.bepaal("en-US", "US")["taal"], "English")
zo("het land komt mee", markt_mod.bepaal("en-US", "US")["land"], "US")
zo("zoekland is hoofdletters", markt_mod.bepaal("en-US", "us")["zoek_land"], "US")
zo("zoektaal is kleine letters", markt_mod.bepaal("EN-us", "US")["zoek_taal"], "en")
zo("onbekende taal wordt Engels", markt_mod.bepaal("sw", "KE")["taal"], "English")
zo("onzin land valt terug", markt_mod.bepaal("nl", "onzin")["landcode"], "NL")
zo("None klapt niet", markt_mod.bepaal(None, None)["landcode"], "NL")
zo("een getal klapt niet", markt_mod.bepaal(123, 456)["taalcode"], "nl")

print("\n== de markt van de Shopify-winkel wordt vastgelegd ==")
shopify_app.winkelgegevens = lambda w, s: {
    "naam": "US Test", "email": "us@test.com", "domein": "ustest.com",
    "taal": "en-US", "land": "US"}
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM shopify_winkels WHERE winkel = 'ustest.myshopify.com'")
conn.close()
client.get("/shopify?id_token=" + maak_kaartje(winkel="ustest.myshopify.com"))
profiel = db.get_winkelprofiel("https://ustest.com") or {}
zo("taal opgeslagen", profiel.get("taal"), "en-US")
zo("land opgeslagen", profiel.get("land"), "US")
m = krillo._markt_van("https://ustest.com")
zo("wordt Engels", m["taal"], "English")
zo("en zoekt in de VS", m["zoek_land"], "US")

print("\n== de koopvragen krijgen die taal mee ==")
gevangen = {}
import koopvragen as kv
kv.genereer_koopvragen = lambda url, extra=None, aantal=30, taal="Nederlands", landnaam="Nederlandse": (
    gevangen.update({"taal": taal, "land": landnaam}) or None)
krillo.run_scan = lambda url: {"url": url, "score": 60, "checks": []}
krillo._genereer_koopvragen_achtergrond("https://ustest.com")
zo("in het Engels", gevangen.get("taal"), "English")
zo("voor Amerikaanse winkels", gevangen.get("land"), "US")

gevangen.clear()
krillo._genereer_koopvragen_achtergrond("https://onbekend.nl")
zo("een winkel zonder markt blijft Nederlands", gevangen.get("taal"), "Nederlands")

print("\n== het scherm is Engels en legt uit wat het doet ==")
p = client.get("/shopify?id_token=" + maak_kaartje(winkel="ustest.myshopify.com")).get_data(as_text=True)
for moet in ["Does ChatGPT mention your store?", "How it works", "Plans",
             "Questions people ask us", "Does this change anything in my store?",
             "Will this get me mentioned by ChatGPT?", "$39", "Cancel any time"]:
    zo(f"bevat {moet!r}", moet in p, True)
zo("noemt de taal van deze winkel", "English (US)" in p, True)
zo("belooft geen vermeldingen", "We cannot promise that" in p, True)

print()
if fouten:
    print("\n".join(fouten)); print(f"\n{len(fouten)} FOUTEN"); sys.exit(1)
print("Alles goed (tweede ronde).")
