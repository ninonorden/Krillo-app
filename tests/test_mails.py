"""Elke mail die een klant kan krijgen, echt opgebouwd en nagekeken.

WAAROM DEZE TEST BESTAAT

Op 21 september liet Nino de gratis test lopen op zijn eigen adres. De mail
die binnenkwam was Nederlands op een Engelse site, zei "dit zijn vijf vragen"
boven drie vragen, beloofde "elke week meten" en "dertig vragen per week" uit
het model van voor de index, telde Pararius en Pararius.nl als twee winkels,
en had de rode knop van het oude ontwerp.

Daarna bleek het breder. Van de veertien mails hoorden er drie bij producten
die niet meer bestaan, kreeg een Watch-klant de mail "we hebben toegang tot je
winkel nodig" (die hoort bij Fix), stond op de factuur "Krillo monitoring",
beloofde de welkomstmail "elke week hoogstens drie dingen", en zei het
maandbericht "vier weken geleden" en "je krijgt de oplossingen ter
goedkeuring" terwijl er geen goedkeurknop bestaat.

Deze test bouwt ELKE klantmail echt op, met de echte functie, en kijkt:
- is hij Engels (de taalregel: een adres, een taal);
- staat er geen belofte van het oude model in;
- is hij in de huisstijl (blauwe knop, geen rood van toen);
- geen gedachtestreep (huisregel van Nino);
- gaat tekst van buiten door de escaping.
Komt er een mail bij, zet hem dan in MAILS hieronder.
"""
import os
import re
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
os.environ["BREVO_API_KEY"] = "test"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import emailing  # noqa: E402

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


gevangen = []
emailing.send_email = lambda naar, onderwerp, html, koppen=None: (
    gevangen.append({"naar": naar, "onderwerp": onderwerp, "html": html}) or True)


def laatste():
    return gevangen[-1]


SCAN = {"score": 62, "checks": [], "platform": "WooCommerce"}
UITSLAG = {
    "gesteld": 5, "telbaar": 3, "genoemd": 0, "aanbevolen": 0,
    "modellen": ["ChatGPT", "Gemini"],
    "concurrenten": [{"naam": "Pararius", "genoemd": 3, "wij": False},
                     {"naam": "Kamernet", "genoemd": 2, "wij": False}],
    "regels": [{"vraag": "hoe kan ik als expat in Nederland een huurwoning vinden?",
                "genoemd": False, "aanbevolen": False},
               {"vraag": "wat is de beste manier om een huurwoning te vinden?",
                "genoemd": False, "aanbevolen": False},
               {"vraag": "alternatieven voor een makelaar?", "genoemd": False,
                "aanbevolen": False}],
}

# Elke klantmail, met de echte functie en echte invoer.
MAILS = {
    "factuur": lambda: emailing.send_factuur_email(
        "a@b.nl", 7, "Krillo Fix, first month, for https://winkel.nl", 149.0, "Winkel BV"),
    "herroeping": lambda: emailing.send_herroeping_bevestiging("a@b.nl", 3, "https://winkel.nl"),
    "opzegging": lambda: emailing.send_opzegging_bevestiging("a@b.nl", "https://winkel.nl"),
    "toegang": lambda: emailing.send_uitvoering_welkom(
        "a@b.nl", "https://winkel.nl", "WooCommerce", "https://krilloai.com/mijn/x"),
    "toegang zonder platform": lambda: emailing.send_uitvoering_welkom(
        "a@b.nl", "https://winkel.nl", None, None),
    "oplevering": lambda: emailing.send_oplevering(
        "a@b.nl", "https://winkel.nl",
        [{"wat": "FAQ", "waar": "Home", "oude_waarde": "", "nieuwe_waarde": "Nieuw"}],
        "https://krilloai.com/mijn/x"),
    "welkom watch": lambda: emailing.send_monitoring_welcome_email(
        "a@b.nl", "https://winkel.nl", SCAN, "https://krilloai.com/mijn/x", pakket="watch"),
    "welkom fix": lambda: emailing.send_monitoring_welcome_email(
        "a@b.nl", "https://winkel.nl", SCAN, "https://krilloai.com/mijn/x", pakket="fix"),
    "opvolging": lambda: emailing.send_opvolging_gratis_test(
        "a@b.nl", "https://winkel.nl", "https://krilloai.com", taal="nl"),
    "maandbericht": lambda: emailing.send_vermeldingen_update(
        "a@b.nl", "https://winkel.nl", "You dropped 3 places.\n\nMore here.",
        "https://krilloai.com/mijn/x", taal="nl"),
    "gratis test": lambda: emailing.send_zichtbaarheidstest(
        "a@b.nl", "https://brixt.nl", UITSLAG, "Summary line.", "https://krilloai.com"),
    "shopify aangevuld": lambda: emailing.send_shopify_bijgewerkt(
        "a@b.nl", "https://winkel.com", [{"wat": "Product description", "waar": "Jacket",
                                          "nieuw": "Warm."}],
        "https://admin.shopify.com/x", taal="nl"),
}

# Woorden die in een Engelse mail niets te zoeken hebben. Losse woorden met
# spaties eromheen, zodat "de" in "made" niet telt.
NEDERLANDS = (" je ", " jouw ", " wij ", " het ", " een ", " niet ", " voor ",
              " webshop ", " bekijk ", " deze ", " wordt ")
# Beloftes en namen van voor de index.
OUD = ("every week we ask", "weekly update", "per week instead", "five questions",
       "monitoring", "39 euro", "$39", "for approval", "four weeks ago",
       "press approve", "the moment you drop")


def zichtbaar(html):
    tekst = re.sub(r"<(style|script)\b.*?</\1>", " ", html, flags=re.S)
    tekst = re.sub(r"<[^>]+>", " ", tekst)
    return " " + re.sub(r"\s+", " ", tekst).lower() + " "


print("\n== ELKE KLANTMAIL ==")
for naam, maak in MAILS.items():
    gevangen.clear()
    maak()
    klopt(f"{naam}: er gaat een mail uit", len(gevangen) == 1)
    if not gevangen:
        continue
    m = laatste()
    tekst = zichtbaar(m["html"]) + " " + m["onderwerp"].lower() + " "
    nl = [w.strip() for w in NEDERLANDS if w in tekst]
    # De koopvragen zelf blijven in de taal van de markt (taalregel 18 sep).
    # In de uitslag van de gratis test staan ze dus bewust in het Nederlands.
    if naam != "gratis test":
        klopt(f"{naam}: Engels (gevonden: {nl})", not nl)
    oud = [w for w in OUD if w in tekst]
    klopt(f"{naam}: geen belofte of naam van voor de index (gevonden: {oud})", not oud)
    klopt(f"{naam}: geen gedachtestreep", "—" not in m["html"] + m["onderwerp"])
    klopt(f"{naam}: geen rood uit het oude ontwerp", "#FF4B3E" not in m["html"].upper())
    klopt(f"{naam}: het woordmerk van de site", "KRILLO" in m["html"] and "INDEX" in m["html"])
    klopt(f"{naam}: geen https:// in het onderwerp", "https://" not in m["onderwerp"])
    if "href=" in m["html"] and "Open your dashboard" in m["html"]:
        klopt(f"{naam}: blauwe knop", emailing.BLAUW in m["html"])

print("\n== WATCH EN FIX KRIJGEN WAT ZE KOCHTEN ==")
gevangen.clear()
MAILS["welkom watch"]()
w = zichtbaar(laatste()["html"])
klopt("Watch: onderwerp noemt Watch", "Watch" in laatste()["onderwerp"])
klopt("Watch: de oplossingen om zelf te doen", "ready to copy" in w)
klopt("Watch: geen vraag om toegang", "access" not in w)
gevangen.clear()
MAILS["welkom fix"]()
f = zichtbaar(laatste()["html"])
klopt("Fix: onderwerp noemt Fix", "Fix" in laatste()["onderwerp"])
klopt("Fix: wij installeren", "we install them in your store" in f)
klopt("Fix: er komt een aparte mail over toegang", "separate email" in f)
klopt("beide: elke maand je categorie", "every month" in w and "every month" in f)

bron = lees("app.py")
klopt("de toegangsmail na betaling gaat alleen naar wie geen Watch nam",
      'if pakket != "watch":' in bron)
klopt("de factuur noemt het pakket", 'omschrijving = f"Krillo {pakketnaam}, first month' in bron)

print("\n== DE GRATIS TEST TELT EERLIJK ==")
gevangen.clear()
MAILS["gratis test"]()
g = zichtbaar(laatste()["html"])
klopt("zegt hoeveel vragen er gesteld zijn", "we asked 5 buying questions" in g)
klopt("en hoeveel er meetelden", "in 3 of them ai named stores" in g)
klopt("belooft de maandmeting, niet een wekelijkse", "every month" in g and "per week" not in g)
klopt("de knop gaat naar de plannen", "#prijzen" in laatste()["html"])
klopt("het onderwerp noemt de winkel zonder https", laatste()["onderwerp"] == "What AI says about brixt.nl")

import beoordeling  # noqa: E402
klopt("Pararius en Pararius.nl zijn een winkel",
      beoordeling.naamsleutel("Pararius") == beoordeling.naamsleutel("Pararius.nl"))
klopt("en www ervoor ook", beoordeling.naamsleutel("www.pararius.nl") == "pararius")
klopt("maar Funda Huur en funda.nl blijven twee (geen gokwerk)",
      beoordeling.naamsleutel("Funda Huur") != beoordeling.naamsleutel("funda.nl"))

# Echt tellen: een ronde waarin het model de ene keer Pararius en de andere keer
# Pararius.nl schrijft. Dat moet een regel worden met twee vermeldingen.
beoordelingen = [
    {"vraag": "v1", "winkel_kon_genoemd": True, "winkels": [{"naam": "Pararius"}],
     "aanbevolen_winkels": [], "genoemd": False, "aanbevolen": False, "model": "gpt"},
    {"vraag": "v2", "winkel_kon_genoemd": True, "winkels": [{"naam": "Pararius.nl"}],
     "aanbevolen_winkels": ["pararius.nl"], "genoemd": False, "aanbevolen": False,
     "model": "gpt"},
]
try:
    beeld = beoordeling.klantbeeld("https://brixt.nl", beoordelingen)
    namen = [c["naam"] for c in beeld["concurrenten"]]
    klopt(f"een regel voor Pararius (kreeg {namen})", namen.count("Pararius") == 1
          and "Pararius.nl" not in namen)
    par = [c for c in beeld["concurrenten"] if c["naam"] == "Pararius"]
    klopt("met beide vermeldingen", par and par[0]["genoemd"] == 2)
    klopt("en de aanbeveling hangt eraan", par and par[0]["aanbevolen"] == 1)
except Exception as e:
    klopt(f"klantbeeld draait ({type(e).__name__}: {e})", False)

import zichtbaarheid  # noqa: E402
zin = zichtbaarheid.samenvattingszin(UITSLAG)
klopt(f"de samenvattingszin op de pagina is Engels ({zin!r})",
      "buying questions" in zin and " je " not in f" {zin} ")

print("\n== ESCAPING: TEKST UIT DE WINKEL KAN DE MAIL NIET OVERNEMEN ==")
gevangen.clear()
emailing.send_shopify_bijgewerkt(
    "a@b.nl", "https://winkel.com",
    [{"wat": "x", "waar": '<a href="https://nep.example">Klik</a>', "nieuw": "<img src=x>"}],
    None)
h = laatste()["html"]
klopt("geen link uit een productnaam", 'href="https://nep.example"' not in h)
klopt("geen plaatje uit een producttekst", "<img src=x>" not in h)

print("\n== DODE MAILS ZIJN WEG ==")
for weg in ("send_weekly_update_email", "_weekly_en", "_vermeldingenblok"):
    klopt(f"{weg} bestaat niet meer", not hasattr(emailing, weg))

print("\n== DE TAAL KOMT NIET MEER UIT HET DOMEIN ==")
import meldingen  # noqa: E402
klopt("meldingen: ook een .nl-winkel krijgt Engels", meldingen._taal_van("https://a.nl") == "en")
klopt("app: ook een .nl-winkel krijgt Engels", "def _mailtaal(webshop_url):" in bron
      and bron.split("def _mailtaal(webshop_url):")[1].split('return "en"')[0].count("\n") < 14)
klant = {"positie": 4, "van": 20, "genoemd": 3, "telbaar": 30, "aanbevolen": 1}
for soort in ("nameting", "daling", "maand"):
    t = meldingen.tekst(klant, {"soort": soort, "verschil": -3}, "Tableware", taal="en").lower()
    klopt(f"maandbericht {soort}: geen 'four weeks' en geen goedkeuring",
          "four weeks" not in t and "approval" not in t)

print("\n== WAT DE CONTROLE VAN 21 SEPTEMBER (MIDDAG) VOND ==")
# Een tweede, losse controle legde elke belofte uit de mails naast de code.
import db  # noqa: E402
db.init_db()
dbbron = lees("db.py")
klopt("Fix komt op de werklijst (anders geen overzicht en geen nameting)",
      "db.start_uitvoering(payment_id, webshop_url, email," in bron
      and bron.rindex("db.start_uitvoering(payment_id, webshop_url, email,")
      > bron.index('if pakket != "watch":'))
klopt("wie opzegt krijgt geen maandbericht meer",
      "AND k.opgezegd_op IS NULL" in dbbron)
db.get_or_create_klant("https://opzeg-test.nl", "o@opzeg-test.nl")
db.zet_klant_opgezegd("https://opzeg-test.nl")
conn = db._get_connection()
with conn:
    with conn.cursor() as cur:
        cur.execute("SELECT opgezegd_op FROM klanten WHERE webshop_url = 'https://opzeg-test.nl'")
        klopt("opzeggen wordt echt vastgelegd", cur.fetchone()[0] is not None)
db.zet_klant_opgezegd("https://opzeg-test.nl", opgezegd=False)
with conn:
    with conn.cursor() as cur:
        cur.execute("SELECT opgezegd_op FROM klanten WHERE webshop_url = 'https://opzeg-test.nl'")
        klopt("en wie terugkomt is weer actief", cur.fetchone()[0] is None)
        cur.execute("DELETE FROM klanten WHERE webshop_url = 'https://opzeg-test.nl'")
conn.close()
klopt("opzeggen via de site legt het vast", 'db.zet_klant_opgezegd(klant["webshop_url"])' in bron)
klopt("opzeggen in de app ook", 'db.zet_klant_opgezegd(rij["webshop_url"])' in bron)
klopt("en de app verwijderen ook", 'db.zet_klant_opgezegd(rij_weg["webshop_url"])' in bron)

gevangen.clear()
MAILS["welkom fix"]()
f = zichtbaar(laatste()["html"])
klopt("de welkomstmail belooft de positie pas na de meting van de categorie",
      "once your category has been measured" in f)
gevangen.clear()
emailing.send_monitoring_welcome_email("a@b.nl", "https://w.nl", SCAN, "https://k/x", pakket="merken")
klopt("het pakket voor merken heet geen Fix", "Fix" not in laatste()["onderwerp"])
gevangen.clear()
MAILS["opzegging"]()
o = zichtbaar(laatste()["html"])
klopt("de opzegmail belooft geen twaalf maanden en geen verdere scans",
      "twelve months" not in o and "no more" not in o and "monthly position email" in o)
t = meldingen.tekst(klant, {"soort": "nameting", "verschil": 2}, "Tableware", taal="en")
klopt("de nameting belooft niet 'dezelfde vragen' (zwakke vragen worden vervangen)",
      "same questions" not in t)
klopt("geen monitoringpagina meer in de waarschuwing",
      "monitoring page" not in lees("waarschuwing.py"))

print("\n== DE OUDE KASSA'S ZIJN DICHT ==")
os.environ.pop("OUDE_KASSA_AAN", None)
import app as krillo  # noqa: E402
c = krillo.app.test_client()
for route in ("/api/checkout/audit", "/api/checkout/uitvoering"):
    r = c.post(route, json={"url": "winkel.nl", "email": "a@b.nl",
                            "voorwaarden_akkoord": True, "directe_uitvoering_akkoord": True})
    klopt(f"{route} geeft 410", r.status_code == 410)

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: elke klantmail is Engels, eerlijk en in de huisstijl.")
