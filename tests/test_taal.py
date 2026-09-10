"""De taal van alles wat een klant te zien of te lezen krijgt.

Waarom dit bestand er is: een winkel in het buitenland kan klant worden via de
Shopify App Store. Die kreeg tot nu toe een Engels scherm met Nederlandse
adviesteksten eronder, en daarna elke week een Nederlandse mail.

Waar het hier stil fout kan gaan, en dus waar deze test op let:
- Een halve vertaling. Engelse kop, Nederlandse inhoud. Dat is erger dan
  helemaal Nederlands, want dan lijkt het alsof er iets kapot is.
- Een verandering voor Nederlandse klanten. Die mogen NIETS merken. Elke regel
  hieronder die "nl" toetst, bewaakt dat.
- Gedachtestreepjes in het Engels. Vaste huisregel, en in het Engels sluipen ze
  er zo in.
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
import emailing
import verklaring
import waarschuwing
import actieplan
import app as krillo

conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
conn.close()
db.init_db()

verstuurd = []
emailing.send_email = lambda to, onderwerp, html, koppen=None: (
    verstuurd.append({"to": to, "onderwerp": onderwerp, "html": html}) or True)


def laatste():
    return verstuurd[-1] if verstuurd else {"onderwerp": "", "html": ""}


def lijkt_nederlands(tekst):
    """Grof, maar goed genoeg: deze woordjes staan in bijna elke Nederlandse
    zin en in geen enkele Engelse."""
    laag = (tekst or "").lower()
    return any(f" {w} " in laag for w in ("je", "het", "wordt", "niet", "wij", "we", "een"))


def lijkt_engels(tekst):
    laag = (tekst or "").lower()
    return any(f" {w} " in laag for w in ("your", "the", "we", "and", "is", "you"))


SCAN = {"score": 62, "checks": [
    {"id": "robots", "titel": "robots.txt", "status": "probleem", "geslaagd": False,
     "categorie": "toegang", "uitleg": "AI-robots worden geblokkeerd."},
    {"id": "https", "titel": "https", "status": "ok", "geslaagd": True,
     "categorie": "toegang", "uitleg": "Beveiligde verbinding staat aan."},
    {"id": "faq", "titel": "veelgestelde vragen", "status": "probleem", "geslaagd": False,
     "categorie": "inhoud", "uitleg": "Er staat geen pagina met vragen op de site."},
]}
BEELD = {"gesteld": 20, "telbaar": 20, "genoemd": 2, "aanbevolen": 0,
         "concurrenten": [{"naam": "Bol.com", "genoemd": 7, "aanbevolen": 3, "wij": False}],
         "modellen": ["ChatGPT", "Gemini"]}

# ---------------------------------------------------------------------------
print("\n== de verklaring ==")
nl = verklaring.maak_verklaring(SCAN["checks"], BEELD)
en = verklaring.maak_verklaring(SCAN["checks"], BEELD, taal="en")
zo("nederlands is de standaard",
   verklaring.maak_verklaring(SCAN["checks"], BEELD, taal="nl"), nl)
zo("een onbekende taal valt terug op nederlands",
   verklaring.maak_verklaring(SCAN["checks"], BEELD, taal="klingon"), nl)
zo("het engels is echt anders", en != nl, True)
zo("de conclusie is in het engels", lijkt_engels(str(en.get("conclusie"))), True)
zo("en niet nederlands", lijkt_nederlands(str(en.get("conclusie"))), False)
zo("zonder gedachtestreepjes", "—" in str(en), False)
zo("de sleutels blijven gelijk", sorted(en.keys()), sorted(nl.keys()))

# ---------------------------------------------------------------------------
print("\n== de duiding bij stijgen en dalen ==")
rondes = [
    {"meting_id": 2, "vraag": "waar koop ik servies", "winkel_kon_genoemd": True,
     "winkel_genoemd": False, "winkels": [{"naam": "Bol.com"}], "aanbevolen_winkels": []},
    {"meting_id": 1, "vraag": "waar koop ik servies", "winkel_kon_genoemd": True,
     "winkel_genoemd": True, "winkels": [{"naam": "Bol.com"}], "aanbevolen_winkels": []},
]
b_nl = waarschuwing.vergelijk(rondes, "MijnWinkel")
b_en = waarschuwing.vergelijk(rondes, "MijnWinkel", taal="en")
zo("de cijfers zijn in beide talen gelijk", b_nl.get("nu"), b_en.get("nu"))
if b_nl.get("duiding"):
    zo("de duiding verschilt wel", b_nl["duiding"] != b_en["duiding"], True)
    zo("en is engels", lijkt_engels(b_en["duiding"]), True)
    zo("zonder gedachtestreepjes", "—" in b_en["duiding"], False)

# ---------------------------------------------------------------------------
print("\n== de auditmail ==")
verstuurd.clear()
emailing.send_audit_email("a@b.nl", "https://winkel.nl", SCAN, [], "https://k.nl/r/x")
nl_mail = laatste()
emailing.send_audit_email("a@b.nl", "https://winkel.nl", SCAN, [], "https://k.nl/r/x",
                          taal="en")
en_mail = laatste()
zo("het onderwerp verschilt", nl_mail["onderwerp"] != en_mail["onderwerp"], True)
zo("het engelse onderwerp is engels", lijkt_engels(en_mail["onderwerp"])
   or not lijkt_nederlands(en_mail["onderwerp"]), True)
zo("de body is engels", lijkt_engels(en_mail["html"]), True)
zo("zonder gedachtestreepjes", "—" in en_mail["html"], False)
zo("het cijfer staat er in beide talen in",
   "62" in nl_mail["html"] and "62" in en_mail["html"], True)

print("\n== de welkomstmail bij monitoring ==")
verstuurd.clear()
emailing.send_monitoring_welcome_email("a@b.nl", "https://winkel.nl", SCAN, "https://k.nl/m/x")
nl_mail = laatste()
emailing.send_monitoring_welcome_email("a@b.nl", "https://winkel.nl", SCAN, "https://k.nl/m/x",
                                       taal="en")
en_mail = laatste()
zo("de body verschilt", nl_mail["html"] != en_mail["html"], True)
zo("de engelse is engels", lijkt_engels(en_mail["html"]), True)
zo("zonder gedachtestreepjes", "—" in en_mail["html"], False)
zo("de link staat er in beide in",
   "https://k.nl/m/x" in nl_mail["html"] and "https://k.nl/m/x" in en_mail["html"], True)

print("\n== de weekmail ==")
verstuurd.clear()
emailing.send_weekly_update_email("a@b.nl", "https://winkel.nl", SCAN, "https://k.nl/m/x", 70)
nl_mail = laatste()
emailing.send_weekly_update_email("a@b.nl", "https://winkel.nl", SCAN, "https://k.nl/m/x", 70,
                                  taal="en")
en_mail = laatste()
zo("het onderwerp verschilt", nl_mail["onderwerp"] != en_mail["onderwerp"], True)
zo("de body is engels", lijkt_engels(en_mail["html"]), True)
zo("zonder gedachtestreepjes", "—" in en_mail["html"], False)

print("\n== de vermeldingen-update ==")
verstuurd.clear()
emailing.send_vermeldingen_update("a@b.nl", "https://winkel.nl", "Er is iets veranderd.",
                                  "https://k.nl/m/x")
nl_mail = laatste()
emailing.send_vermeldingen_update("a@b.nl", "https://winkel.nl", "Something changed.",
                                  "https://k.nl/m/x", taal="en")
en_mail = laatste()
zo("het onderwerp verschilt", nl_mail["onderwerp"] != en_mail["onderwerp"], True)
zo("zonder gedachtestreepjes", "—" in en_mail["html"], False)

# ---------------------------------------------------------------------------
print("\n== de onderzoeksmail blijft met opzet nederlands ==")
verstuurd.clear()
emailing.send_onderzoeksmail("info@winkel.nl", "https://winkel.nl",
                             "https://www.krillo.nl/uitkomst/abc",
                             genoemd=2, telbaar=20,
                             afmeld_url="https://www.krillo.nl/afmelden/abc")
zo("hij is nederlands", lijkt_nederlands(laatste()["html"]), True)

# ---------------------------------------------------------------------------
print("\n== het actieplan ==")
plan_nl = actieplan.maak_actieplan(verklaring=verklaring.maak_verklaring(SCAN["checks"], BEELD),
                                   klantbeeld=BEELD, winkelnaam="MijnWinkel")
plan_en = actieplan.maak_actieplan(
    verklaring=verklaring.maak_verklaring(SCAN["checks"], BEELD, taal="en"),
    klantbeeld=BEELD, winkelnaam="MijnWinkel", taal="en")
zo("beide plannen bestaan", bool(plan_nl) and bool(plan_en), True)
zo("evenveel acties", len(plan_nl["acties"]), len(plan_en["acties"]))
zo("dezelfde kenmerken in dezelfde volgorde",
   [a["id"] for a in plan_nl["acties"]], [a["id"] for a in plan_en["acties"]])
zo("dezelfde soorten",
   [a["soort"] for a in plan_nl["acties"]], [a["soort"] for a in plan_en["acties"]])
zo("de titels verschillen wel",
   [a["titel"] for a in plan_nl["acties"]] != [a["titel"] for a in plan_en["acties"]], True)
zo("de engelse kop is engels", lijkt_engels(plan_en["kop"]), True)
zo("zonder gedachtestreepjes", "—" in str(plan_en), False)

# ---------------------------------------------------------------------------
print("\n== welke taal krijgt welke winkel ==")
zo("zonder profiel nederlands", krillo._mailtaal("https://onbekend.nl"), "nl")
db.zet_markt("https://amerikaans.nl", "en-US", "US")
zo("een amerikaanse winkel engels", krillo._mailtaal("https://amerikaans.nl"), "en")
db.zet_markt("https://hollands.nl", "nl-NL", "NL")
zo("een nederlandse winkel nederlands", krillo._mailtaal("https://hollands.nl"), "nl")
db.zet_markt("https://vlaams.nl", "nl-BE", "BE")
zo("een vlaamse winkel ook nederlands", krillo._mailtaal("https://vlaams.nl"), "nl")
db.zet_markt("https://duits.nl", "de-DE", "DE")
zo("een duitse winkel krijgt engels en geen nederlands",
   krillo._mailtaal("https://duits.nl"), "en")
zo("zonder webadres nederlands", krillo._mailtaal(None), "nl")
zo("met een leeg webadres nederlands", krillo._mailtaal(""), "nl")

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
