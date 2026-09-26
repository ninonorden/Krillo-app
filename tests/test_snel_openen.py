"""De app opent snel, ook als Shopify traag antwoordt.

WAAROM DEZE TEST BESTAAT

26 september: Nino merkte dat de app rond 30 seconden nodig had voordat er iets
te zien was. Een beoordelaar van Shopify die dat ziet, keurt de app af, en een
winkelier klikt hem weg. In de code liepen twee vragen aan Shopify (het land
en het abonnement) na elkaar, en het voorbeeld van een echte winkel werd bij
elke opening opnieuw uitgerekend.

Deze test legt vast:
- de vragen aan Shopify lopen tegelijk, niet na elkaar;
- een winkel in NL of BE wacht niet op de landcheck;
- een winkel buiten NL/BE wacht er wel op (anders ziet hij zijn nieuwe land niet);
- het voorbeeld wordt bewaard en niet elke keer opnieuw gebouwd;
- wie traag opent, komt in de log met de tijd per stap.
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

WINKEL = "snel-test.myshopify.com"
URL = "https://snel-test.nl"


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
    "naam": "Stap26 Test", "email": "eigenaar@snel-test.nl", "domein": "snel-test.nl",
    "taal": "nl-NL", "land": "NL"}
shopify_app.meld_webhooks_aan = lambda w, s, b: {"gelukt": [], "mislukt": []}
gemeten = []
krillo._meet_en_beoordeel = lambda url, **kw: gemeten.append(url)
shopify_billing.huidig_abonnement = lambda w, s: {"actief": False}


import io  # noqa: E402
import contextlib  # noqa: E402

TRAAG = 1.7


def traag_land(w, s):
    time.sleep(TRAAG)
    return {"naam": "Snel", "email": "e@snel-test.nl", "domein": "snel-test.nl",
            "taal": "nl-NL", "land": "NL"}


def traag_abo(w, s):
    time.sleep(TRAAG)
    return {"actief": False}


db.init_db()
sql("DELETE FROM shopify_winkels WHERE winkel LIKE 'snel%%'")
client = krillo.app.test_client()


def open_scherm():
    t = time.monotonic()
    uit = io.StringIO()
    with contextlib.redirect_stdout(uit):
        p = client.get(f"/shopify?shop={WINKEL}&id_token={maak_kaartje()}").get_data(as_text=True)
    return p, time.monotonic() - t, uit.getvalue()


# Eerste keer openen: installeren, land komt binnen.
open_scherm()
db.zet_markt(URL, "nl-NL", "NL")

print("\n== NL-WINKEL MET POSITIE: SHOPIFY-VRAGEN TEGELIJK ==")
shopify_app.winkelgegevens = traag_land
shopify_billing.huidig_abonnement = traag_abo
krillo._land_ververst_op.clear()
krillo.klantbeeld.bouw = lambda url, land=None, **k: {
    "webshop_url": URL, "naam": "Snel", "categorie": "koffie", "land": "nl", "ronde": 1,
    "positie": 4, "van": 20, "vorige_positie": None, "verschil": None, "genoemd": 3,
    "aanbevolen": 1, "telbaar": 30, "gemeten_op": None, "verloop": [], "boven_mij": [],
    "gemiste_vragen": [{"vraag": "beste koffie", "concurrenten": ["A"], "platforms": [],
                        "aanbevolen": []}]}
p, duur, log = open_scherm()
klopt(f"opent in {duur:.1f}s, niet {2 * TRAAG:.1f}s of meer (na elkaar)", duur < 2 * TRAAG - 0.3)
klopt("het scherm is er echt", "#4" in p or "4" in p)
klopt("trage opening komt in de log met de stappen",
      "Shopify-scherm" in log and "abonnement" in log and "positie" in log)

print("\n== BINNEN 10 MINUTEN NOG EENS: DE LANDCHECK SLAAT OVER ==")
tel = []
shopify_app.winkelgegevens = lambda w, s: tel.append(1) or traag_land(w, s)
shopify_billing.huidig_abonnement = lambda w, s: {"actief": False}
p, duur, log = open_scherm()
time.sleep(0.2)
klopt("geen nieuwe landvraag", tel == [])
klopt(f"en dus snel ({duur:.2f}s)", duur < 1.0)

print("\n== BUITEN NL/BE: WEL WACHTEN OP HET LAND ==")
db.zet_markt(URL, "en-US", "US")
shopify_app.winkelgegevens = traag_land
krillo.klantbeeld.bouw = lambda url, land=None, **k: None
p, duur, log = open_scherm()
klopt("de landvraag is afgewacht", duur >= TRAAG - 0.1)
klopt("en het nieuwe land (NL) staat er meteen", "your market</em> yet" not in p)

print("\n== HET VOORBEELD WORDT BEWAARD ==")
gebouwd = []
krillo._voorbeeld_cache.update(op=0.0, waarde=None)
echt = krillo._voorbeeld_bouwen
krillo._voorbeeld_bouwen = lambda: gebouwd.append(1) or {"naam": "vb"}
krillo._voorbeeld_voor_app()
krillo._voorbeeld_voor_app()
krillo._voorbeeld_voor_app()
klopt("drie keer gevraagd, een keer gebouwd", len(gebouwd) == 1)
krillo._voorbeeld_cache["op"] -= krillo.VOORBEELD_BEWAAR_SECONDEN + 1
krillo._voorbeeld_voor_app()
klopt("na tien minuten opnieuw", len(gebouwd) == 2)
krillo._voorbeeld_bouwen = lambda: gebouwd.append(1) or None
krillo._voorbeeld_cache.update(op=0.0, waarde=None)
krillo._voorbeeld_voor_app()
krillo._voorbeeld_voor_app()
klopt("geen voorbeeld wordt niet bewaard (volgende keer opnieuw proberen)", len(gebouwd) == 4)
krillo._voorbeeld_bouwen = echt

sql("DELETE FROM shopify_winkels WHERE winkel LIKE 'snel%%'")
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de app opent snel.")
