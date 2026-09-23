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
# Sinds 21 september Engels, welke taal er ook meegegeven wordt.
zo("ook zonder taal is het onderwerp engels", nl_mail["onderwerp"], en_mail["onderwerp"])
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
# Sinds 21 september is elke klantmail Engels, wat de taal ook zegt.
zo("ook zonder taal is hij engels", lijkt_engels(nl_mail["html"]), True)
zo("de engelse is engels", lijkt_engels(en_mail["html"]), True)
zo("zonder gedachtestreepjes", "—" in en_mail["html"], False)
zo("de link staat er in beide in",
   "https://k.nl/m/x" in nl_mail["html"] and "https://k.nl/m/x" in en_mail["html"], True)

print("\n== de weekmail bestaat niet meer (stap 66) ==")
zo("weg", hasattr(emailing, "send_weekly_update_email"), False)

print("\n== de vermeldingen-update ==")
verstuurd.clear()
emailing.send_vermeldingen_update("a@b.nl", "https://winkel.nl", "Er is iets veranderd.",
                                  "https://k.nl/m/x")
nl_mail = laatste()
emailing.send_vermeldingen_update("a@b.nl", "https://winkel.nl", "Something changed.",
                                  "https://k.nl/m/x", taal="en")
en_mail = laatste()
zo("het kader is engels", lijkt_engels(en_mail["html"]), True)
zo("zonder gedachtestreepjes", "—" in en_mail["html"], False)

# ---------------------------------------------------------------------------
# Tot 23 september was deze mail met opzet Nederlands. Sinds stap 36 is ook
# hij Engels: een adres, een taal, en hij noemt de positie uit de index.
print("\n== ook de onderzoeksmail is engels (stap 36) ==")
verstuurd.clear()
emailing.send_onderzoeksmail("info@winkel.nl", "https://winkel.nl",
                             "https://krilloai.com/uitkomst/abc",
                             beeld={"positie": 4, "van": 20, "genoemd": 2, "telbaar": 30,
                                    "land": "nl", "categorie": "testcat"},
                             categorienaam="Test", landnaam="the Netherlands",
                             afmeld_url="https://krilloai.com/afmelden/abc")
zo("hij is engels", lijkt_engels(laatste()["html"]), True)
# Niet lijkt_nederlands: "we" staat in beide lijstjes. Hier alleen woorden
# die in een Engelse zin nooit voorkomen.
_laag = laatste()["html"].lower()
zo("en niet nederlands", any(f" {w} " in _laag for w in ("je", "het", "wordt", "niet", "een")),
   False)

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
print("\n== welke taal krijgt welke winkel: altijd Engels (sinds 21 sep) ==")
# De taalregel van 18 september: een adres, een taal. De mail hoort bij de
# site en de site is Engels. Tot 21 september kreeg een .nl-winkel hier
# Nederlands, en dan kwam er Nederlandse post na een Engelse kassa.
for adres, markt in (("https://onbekend.nl", None), ("https://hollands.nl", ("nl-NL", "NL")),
                     ("https://vlaams.nl", ("nl-BE", "BE")), ("https://duits.nl", ("de-DE", "DE"))):
    if markt:
        db.zet_markt(adres, *markt)
    zo(f"{adres} krijgt Engels", krillo._mailtaal(adres), "en")
zo("zonder webadres ook", krillo._mailtaal(None), "en")

print()
if fouten:
    print("\n".join(fouten))
    print(f"\n{len(fouten)} FOUTEN")
    sys.exit(1)
print("Alles goed.")
