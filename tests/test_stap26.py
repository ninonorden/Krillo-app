"""Stap 26: de Shopify-app werkt zoals krilloai.com.

WAAROM DEZE TEST BESTAAT

Tot 23 september was de Shopify-app een ander product dan de site. De ingang
was een knop "Measure my store" die per installatie een eigen meting startte:
geld per installatie, en een tweede cijfer dat kon botsen met de openbare
ranglijst. De site zegt: "je positie in de index". Dus de app nu ook.

Deze test legt vast:
- een winkel in NL of BE ziet zijn positie uit de index, met wie net boven hem
  staat en de vragen waar hij ontbrak (platforms apart, want bol.com is geen
  concurrent);
- zonder positie staat er eerlijk "komt eraan", en buiten NL/BE eerlijk "we
  meten jouw markt nog niet";
- de winkel komt bij het openen op de winkellijst, maar nooit in de koude
  mailrij, en een betalende klant blijft klant;
- de oude meting start niets meer;
- een winkel kan nooit twee keer betalen, via de site en via de app.
"""
import json
import os
import sys
import time
import types
import base64
import hashlib
import hmac

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["SHOPIFY_API_KEY"] = "test-client-id"
os.environ["SHOPIFY_API_SECRET"] = "test-geheim"
os.environ["BASE_URL"] = "https://krilloai.com"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


# Een nep-betaalmodule: Mollie mag in een test nooit echt aangeroepen worden.
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
nep.pakket_van = lambda p: {"naam": "Watch"}
sys.modules["payments"] = nep

import db  # noqa: E402
import klantbeeld  # noqa: E402
import shopify_app  # noqa: E402
import shopify_billing  # noqa: E402
import app as krillo  # noqa: E402

WINKEL = "stap26-test.myshopify.com"
URL = "https://stap26-test.nl"


def maak_kaartje(winkel=WINKEL):
    nu = int(time.time())

    def stuk(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    romp = (stuk({"alg": "HS256", "typ": "JWT"}) + "." +
            stuk({"iss": f"https://{winkel}/admin", "dest": f"https://{winkel}",
                  "aud": "test-client-id", "sub": "1", "exp": nu + 60, "nbf": nu - 10,
                  "iat": nu, "jti": "a", "sid": "b"}))
    teken = base64.urlsafe_b64encode(
        hmac.new(b"test-geheim", romp.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    return f"{romp}.{teken}"


def sql(opdracht, waarden=None, een=False):
    conn = db._get_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(opdracht, waarden)
            uit = cur.fetchone() if een else None
    conn.close()
    return uit


shopify_app.wissel_id_token = lambda w, t: {
    "gelukt": True, "sleutel": "shpat_x", "rechten": shopify_app.SCOPES,
    "geldig_seconden": 3599, "verversleutel": "shprt_x", "verversleutel_seconden": 7775999}
shopify_app.winkelgegevens = lambda w, s: {
    "naam": "Stap26 Test", "email": "eigenaar@stap26-test.nl", "domein": "stap26-test.nl",
    "taal": "nl-NL", "land": "NL"}
shopify_app.meld_webhooks_aan = lambda w, s, b: {"gelukt": [], "mislukt": []}
gemeten = []
krillo._meet_en_beoordeel = lambda url, **kw: gemeten.append(url)
shopify_billing.huidig_abonnement = lambda w, s: {"actief": False}

db.init_db()
sql("DELETE FROM shopify_winkels WHERE winkel LIKE 'stap26%%'")
sql("DELETE FROM benadering WHERE webshop_url LIKE 'https://stap26%%'")
client = krillo.app.test_client()


def scherm():
    return client.get(f"/shopify?shop={WINKEL}&id_token={maak_kaartje()}").get_data(as_text=True)


print("\n== ZONDER POSITIE: EERLIJK 'KOMT ERAAN' ==")
krillo.klantbeeld.bouw = lambda url, land=None, **k: None
p = scherm()
klopt("de kop zegt dat de positie eraan komt", "Your rank is <em>on its way.</em>" in p)
klopt("geen knop om zelf te meten", 'id="metenknop"' not in p)
klopt("geen verzonnen cijfer", "#1 of" not in p)

print("\n== ZONDER POSITIE: EEN ECHT VOORBEELD ERONDER (24 september) ==")
_vb = {"positie": 4, "van": 54, "genoemd": 11, "aanbevolen": 3, "telbaar": 30, "verschil": None,
       "gemeten_op": None, "land": "nl", "categorie": "elektronica",
       "categorienaam": "Elektronica", "landnaam": "the Netherlands", "winkelnaam": "Voorbeeldwinkel",
       "boven_mij": [], "gemiste_vragen": []}
_echt_vb = krillo._voorbeeld_voor_app
krillo._voorbeeld_voor_app = lambda: _vb
p = scherm()
klopt("het voorbeeld staat eronder, als voorbeeld gemarkeerd", "What your ranking will look like" in p and "EXAMPLE &middot; VOORBEELDWINKEL" in p)
klopt("met echte cijfers van die winkel", "#4<small" in p and "/ 54" in p)
krillo._voorbeeld_voor_app = _echt_vb

print("\n== BIJ HET OPENEN KOMT DE WINKEL OP DE LIJST ==")
r = sql("SELECT stand, land, gemaild_op FROM benadering WHERE webshop_url = %s", (URL,), een=True)
klopt("hij staat op de winkellijst", r is not None)
klopt("met stand shopify", r and r[0] == "shopify")
klopt("en is nooit gemaild", r and r[2] is None)
for stand in ("nieuw", "geen_adres", "adres", "meten", "gemeten"):
    rij_stand = [w["webshop_url"] for w in db.get_benaderingen(stand=stand, limiet=5000)]
    klopt(f"niet in de mailrij bij stand {stand!r}", URL not in rij_stand)
zonder = [w["webshop_url"] for w in db.winkels_zonder_categorie(5000)]
klopt("het nachtelijk indelen ziet hem", URL in zonder)

print("\n== EEN BETALENDE KLANT BLIJFT KLANT ==")
db.zet_klant_op_lijst("https://stap26-klant.nl", land="NL")
db.zet_klant_op_lijst("https://stap26-klant.nl", land="NL", stand="shopify")
klopt("de installatie overschrijft 'klant' niet",
      sql("SELECT stand FROM benadering WHERE webshop_url = 'https://stap26-klant.nl'",
          een=True)[0] == "klant")

print("\n== MET POSITIE: DE KAART UIT DE INDEX ==")
beeld = {
    "webshop_url": URL, "naam": "Stap26 Test", "categorie": "koffie", "land": "nl",
    "ronde": 1, "positie": 4, "van": 23, "vorige_positie": 6, "verschil": 2,
    "genoemd": 7, "aanbevolen": 3, "telbaar": 30, "gemeten_op": None, "verloop": [],
    "boven_mij": [{"positie": 3, "naam": "Koffie Centrale", "webshop_url": "https://kc.nl",
                   "genoemd": 9}],
    "gemiste_vragen": [{"vraag": "Waar koop ik goede espressobonen?",
                        "concurrenten": ["Koffie Centrale"], "platforms": ["bol.com"],
                        "aanbevolen": []},
                       {"vraag": "Beste koffiemolen voor thuis?",
                        "concurrenten": ["GeheimeConcurrent"], "platforms": [],
                        "aanbevolen": []}],
}
krillo.klantbeeld.bouw = lambda url, land=None, **k: beeld
p = scherm()
klopt("de positie staat erop", "<em>#4</em> of 23 in" in p)
klopt("met categorie en land", "Netherlands" in p or "Nederland" in p)
klopt("hoe vaak genoemd, per vraag", "AI named you in 7 of 30 buying questions" in p)
klopt("de stijging staat erbij", ">+2<" in p)
klopt("de link naar de volledige ranglijst", "https://krilloai.com/index/nl/koffie#p4" in p)
klopt("dezelfde bouwstenen als de homepage", "indexkaart" in p and "idx-kaart" in p and "sectiekop" in p)
klopt("wie net boven hem staat", "Your ranking" in p and "Koffie Centrale" in p and "jijrij" in p)
klopt("de vraag waar hij ontbrak", "Waar koop ik goede espressobonen?" in p)
klopt("de concurrent bij de gemiste vraag", "<strong>Koffie Centrale</strong>" in p)
klopt("bol.com apart als platform", "PLATFORMS: BOL.COM" in p)
klopt("bol.com NIET als concurrent", "<strong>bol.com</strong>" not in p)

print("\n== GRATIS ZIET EEN DEEL, WATCH ZIET ALLES (24 september) ==")
klopt("de tweede vraag staat er wel", "Beste koffiemolen voor thuis?" in p)
klopt("maar wie er in plaats van hem genoemd werd NIET, ook niet in de broncode",
      "GeheimeConcurrent" not in p)
klopt("met een slot en de weg naar Watch", "Unlock with Watch" in p and "See who beat you on 1 more question" in p)
klopt("de proef wordt genoemd zolang hij die nog niet had", "Try Watch free" in p)
shopify_billing.huidig_abonnement = lambda w, s: {"actief": True, "plan": "watch"}
p = scherm()
klopt("met een abonnement staat alles erop", "GeheimeConcurrent" in p)
klopt("en geen slot meer", "Unlock with Watch" not in p)
shopify_billing.huidig_abonnement = lambda w, s: {"actief": False, "fout": "storing"}
p = scherm()
klopt("weten we het niet (storing bij Shopify), dan alles tonen", "GeheimeConcurrent" in p)
shopify_billing.huidig_abonnement = lambda w, s: {"actief": False}

print("\n== DE GEMISTE VRAGEN SPLITSEN WINKELS EN PLATFORMS ==")
klantbeeld.db.antwoorden_van_ronde = lambda ronde: [
    {"vraag": "Beste koffiebonen online?", "model": "x", "genoemde_winkels": {
        "winkel_kon_genoemd": True,
        "winkels": [{"naam": "Koffie Centrale", "soort": "winkel"},
                    {"naam": "bol.com", "soort": "platform"},
                    {"naam": "Oude Rij Zonder Soort"}]}},
]
gemist = klantbeeld.gemiste_vragen(1, URL)
klopt("een vraag gevonden", len(gemist) == 1)
klopt("winkels als concurrent (ook oude rijen zonder soort)",
      gemist and gemist[0]["concurrenten"] == ["Koffie Centrale", "Oude Rij Zonder Soort"])
klopt("platforms apart", gemist and gemist[0]["platforms"] == ["bol.com"])

print("\n== BUITEN NL EN BE: EERLIJK ZEGGEN DAT WE DAT NIET METEN ==")
shopify_app.winkelgegevens = lambda w, s: {
    "naam": "US", "email": "us@stap26-us.com", "domein": "stap26-us.com",
    "taal": "en-US", "land": "US"}
p = client.get("/shopify?shop=stap26-us.myshopify.com&id_token="
               + maak_kaartje("stap26-us.myshopify.com")).get_data(as_text=True)
klopt("de kop zegt het eerlijk", "We do not measure <em>your market</em> yet" in p)
klopt("geen 'komt eraan'", "Your rank is <em>on its way.</em>" not in p)
klopt("en hij komt niet op de lijst",
      sql("SELECT 1 FROM benadering WHERE webshop_url = 'https://stap26-us.com'",
          een=True) is None)

print("\n== ZET DE WINKELIER ZIJN LAND OP NEDERLAND, DAN ZIET DE APP DAT (24 september) ==")
# Eerst werd het land alleen bij het installeren opgehaald. Nino zette zijn
# testwinkel op Nederland en de app bleef "we meten jouw markt nog niet" zeggen.
shopify_app.winkelgegevens = lambda w, s: {
    "naam": "US", "email": "us@stap26-us.com", "domein": "stap26-us.com",
    "taal": "nl-NL", "land": "NL"}
krillo.klantbeeld.bouw = lambda url, land=None, **k: None  # nog geen positie
p = client.get("/shopify?shop=stap26-us.myshopify.com&id_token="
               + maak_kaartje("stap26-us.myshopify.com")).get_data(as_text=True)
klopt("bij de volgende keer openen staat hij in de markt", "Your rank is <em>on its way.</em>" in p)
klopt("en niet meer 'we meten jouw markt niet'", "your market</em> yet" not in p)

print("\n== DE OUDE METING START NIETS MEER ==")
r = client.post("/shopify/api/meten", headers={"Authorization": "Bearer " + maak_kaartje()})
klopt("410 met uitleg", r.status_code == 410 and "Krillo index" in r.get_json()["error"])
time.sleep(0.3)
klopt("er is niets gemeten", gemeten == [])

print("\n== NOOIT TWEE KEER BETALEN ==")
nep.zoek_abonnement = lambda u: {"id": "sub_1", "bedrag": "29.00"}
r = client.post("/shopify/api/abonneren", json={"plan": "watch"},
                headers={"Authorization": "Bearer " + maak_kaartje()})
klopt("app weigert als er al een plan via de site loopt", r.status_code == 409)
klopt("met uitleg", "krilloai.com" in (r.get_json() or {}).get("error", ""))
nep.zoek_abonnement = lambda u: None

bron = open(os.path.join(APP, "app.py"), encoding="utf-8").read()
i = bron.index('@app.route("/api/checkout/monitoring", methods=["POST"])')
j = bron.index("result = payments.create_monitoring_signup(", i)
klopt("de kassa op de site kijkt naar een Shopify-abonnement",
      "shopify_winkel_bij_url" in bron[i:j] and "huidig_abonnement" in bron[i:j])

sql("DELETE FROM shopify_winkels WHERE winkel LIKE 'stap26%%'")
sql("DELETE FROM benadering WHERE webshop_url LIKE 'https://stap26%%'")
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de Shopify-app werkt zoals krilloai.com.")
