"""Stap 76: Belgie (en elk volgend land) met eigen koopvragen.

WAAROM DEZE TEST BESTAAT

Tot 24 september kwam de Belgische ranglijst uit de NEDERLANDSE vragen
("welke Nederlandse webshop..."), met alleen de Belgische winkels erin. Een
Belgische koper vraagt naar een Belgische webshop en krijgt andere namen.
Nu kan een land eigen rondes krijgen. Wat daarbij mis kan gaan, en wat deze
test dus vasthoudt:

1. De Nederlandse ranglijst mag NOOIT uit een Belgische ronde komen, ook niet
   als die nieuwer is (dat zou elke query "nieuwste ronde" doen).
2. Zolang Belgie geen eigen ronde heeft, blijft alles zoals het was.
3. Heeft Belgie er een, dan komen de Belgische ranglijst, de landpagina en het
   positieverloop daaruit.
4. Een Belgische klant krijgt geen bericht over de gewone ronde meer, en een
   Nederlandse klant geen bericht over de Belgische.
5. De vragen worden automatisch bedacht met "Belgische", en bewaard onder een
   eigen sleutel, zodat aanvullen en snoeien per land werken.
6. Een nieuw land is een regel in vraaglanden.py.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


import db  # noqa: E402
import vraaglanden  # noqa: E402

db.init_db()
CAT = "stap76cat"


def sql(opdracht, waarden=None, een=False):
    conn = db._get_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(opdracht, waarden)
            uit = cur.fetchone() if een else None
    conn.close()
    return uit


def opruimen():
    sql("DELETE FROM categorie_uitkomsten WHERE categorie = %s", (CAT,))
    sql("DELETE FROM categorie_rondes WHERE categorie = %s", (CAT,))
    sql("DELETE FROM categorie_vragen WHERE categorie IN (%s, %s)", (CAT, CAT + "@be"))
    sql("DELETE FROM klanten WHERE webshop_url LIKE 'https://s76-%%'")
    sql("DELETE FROM benadering WHERE webshop_url LIKE 'https://s76-%%'")


opruimen()
NL = [f"https://s76-nl{i}.nl" for i in range(4)]
BE = [f"https://s76-be{i}.be" for i in range(5)]
for u in NL + BE:
    db.voeg_benadering_toe(u, naam=None, land="BE" if u.endswith(".be") else "NL")
    sql("UPDATE benadering SET categorie = %s, soort = 'winkel' WHERE webshop_url = %s", (CAT, u))


def ronde(land, volgorde):
    """Een afgeronde ronde; volgorde = winkels van meest naar minst genoemd."""
    r = db.start_categorie_ronde(CAT, 30, len(volgorde), land=land)
    for plek, u in enumerate(volgorde, start=1):
        sql("INSERT INTO categorie_uitkomsten (ronde, categorie, webshop_url, positie, "
            "genoemd, aanbevolen, telbaar) VALUES (%s, %s, %s, %s, %s, 0, 20)",
            (r, CAT, u, plek, 50 - plek))
    sql("UPDATE categorie_rondes SET afgerond_op = now(), telbaar = 20 WHERE id = %s", (r,))
    return r


print("\n== 2. ZONDER EIGEN RONDE: ZOALS HET WAS ==")
gewoon = ronde(None, NL + BE)
be = db.ranglijst_per_land(CAT, "be")
klopt("Belgie valt terug op de gewone ronde", be["ronde"] == gewoon)
klopt("met alleen Belgische winkels", [r["webshop_url"] for r in be["rijen"]] == BE)
klopt("geen landen met eigen ronde", db.landen_met_eigen_ronde(CAT) == set())
klopt("de gewone ronde heeft geen land", db.ronde_land(gewoon) is None)
klopt("Belgie staat in de rij voor een eigen ronde",
      CAT in [r["categorie"] for r in db.landrondes_om_te_meten("be", 5, 30)])
klopt("met te weinig Belgische winkels niet",
      CAT not in [r["categorie"] for r in db.landrondes_om_te_meten("be", 6, 30)])

print("\n== 1 EN 3. MET EEN BELGISCHE RONDE ==")
BE_ANDERS = list(reversed(BE))
belgisch = ronde("be", NL + BE_ANDERS)
klopt("de ronde heeft land be", db.ronde_land(belgisch) == "be")
be = db.ranglijst_per_land(CAT, "be")
klopt("de Belgische ranglijst komt uit de Belgische ronde", be["ronde"] == belgisch)
klopt("met de Belgische volgorde", [r["webshop_url"] for r in be["rijen"]] == BE_ANDERS)
klopt("genummerd vanaf 1", [r["positie"] for r in be["rijen"]] == [1, 2, 3, 4, 5])
nl = db.ranglijst_per_land(CAT, "nl")
klopt("Nederland blijft uit de gewone ronde, ook al is de Belgische nieuwer",
      nl["ronde"] == gewoon)
klopt("de gewone lijst zonder land ook", db.ranglijst_per_land(CAT, None)["ronde"] == gewoon)
klopt("de laatste gewone ronde is de gewone", db.laatste_afgeronde_ronde(CAT) == gewoon)
klopt("de laatste Belgische is de Belgische", db.laatste_afgeronde_ronde(CAT, land="be") == belgisch)
klopt("een land zonder eigen ronde krijgt geen gewone terug bij exact vragen",
      db.laatste_afgeronde_ronde(CAT, land="de") is None)
klopt("de beheerlijst toont de gewone ronde", db.laatste_ranglijst(CAT)["ronde"] == gewoon)
klopt("Belgie heeft nu een eigen ronde", db.landen_met_eigen_ronde(CAT) == {"be"})

per_be = {r["categorie"]: r for r in db.categorieen_per_land("be", 3)}
klopt("de Belgische landpagina telt de Belgische ronde",
      CAT in per_be and per_be[CAT]["winkels"] == 5)
klopt("de openbare index (alle landen) gebruikt de gewone ronde",
      all(r["categorie"] != CAT or r["winkels"] == 9 for r in db.openbare_categorieen(1)))
klopt("de gewone rij meet de categorie niet dubbel",
      CAT not in [r["categorie"] for r in db.landrondes_om_te_meten("be", 5, 30)])

verloop = db.positieverloop(BE[0], CAT, "be")
klopt("het Belgische verloop komt alleen uit Belgische rondes",
      [v["ronde"] for v in verloop] == [belgisch])
klopt("met de Belgische positie", verloop and verloop[-1]["positie"] == 5)
klopt("het Nederlandse verloop blijft uit de gewone rondes",
      [v["ronde"] for v in db.positieverloop(NL[0], CAT, "nl")] == [gewoon])

print("\n== 4. BERICHTEN EN KLANTWERK: WIE HOORT BIJ WELKE RONDE ==")
h = vraaglanden.hoort_bij_ronde
klopt("Belgische ronde: Belgische klant ja", h("be", "be", {"be"}))
klopt("Belgische ronde: Nederlandse klant nee", not h("nl", "be", {"be"}))
klopt("gewone ronde: Nederlandse klant ja", h("nl", None, {"be"}))
klopt("gewone ronde: Belgische klant nee als Belgie een eigen ronde heeft", not h("be", None, {"be"}))
klopt("gewone ronde: Belgische klant ja zolang Belgie geen eigen ronde heeft", h("be", None, set()))
db.get_or_create_klant(BE[0], "be@s76.be")
db.get_or_create_klant(NL[0], "nl@s76.nl")
sql("UPDATE klanten SET klant_token = 'tok-s76-' || md5(webshop_url) "
    "WHERE webshop_url IN (%s, %s) AND klant_token IS NULL", (BE[0], NL[0]))
in_be = {k["webshop_url"]: k for k in db.klanten_in_ronde(belgisch)}
klopt("klanten_in_ronde geeft het land mee", (in_be.get(BE[0]) or {}).get("land") == "be")
klopt("en de vorige ronde van hetzelfde land (hier: geen)",
      (in_be.get(BE[0]) or {}).get("vorige_positie") is None)
import meldingen  # noqa: E402
na = meldingen.na_meting(belgisch, CAT, verstuur=False)
klopt("na de Belgische ronde alleen de Belgische klant",
      [r["webshop_url"] for r in na["regels"]] == [BE[0]])
klopt("met zijn Belgische plek", na["regels"][0]["positie"] == 5)
na = meldingen.na_meting(gewoon, CAT, verstuur=False)
klopt("na de gewone ronde alleen de Nederlandse klant",
      [r["webshop_url"] for r in na["regels"]] == [NL[0]])
bron = lees("app.py")
klopt("het klantwerk filtert ook", "vraaglanden.hoort_bij_ronde(" in bron)

print("\n== 5. DE VRAGEN: AUTOMATISCH, BELGISCH, EIGEN SLEUTEL ==")
klopt("de sleutel voor Belgie", vraaglanden.vraagsleutel(CAT, "be") == CAT + "@be")
klopt("Nederland en onbekende landen: de gewone", vraaglanden.vraagsleutel(CAT, "nl") == CAT
      and vraaglanden.vraagsleutel(CAT, "de") == CAT and vraaglanden.vraagsleutel(CAT) == CAT)
import categoriemeting  # noqa: E402
import metingen  # noqa: E402
gevraagd = {}


def nep_bedenk(slug, aantal=30, vermijd=None, **k):
    gevraagd.update(k, slug=slug)
    return [{"vraag": f"welke Belgische webshop verkoopt ding {i}", "intentie": "algemeen"}
            for i in range(aantal)]


categoriemeting.bedenk_vragen = nep_bedenk
metingen.beschikbare_aanbieders = lambda: []   # stopt voor er iets gesteld wordt
uit = categoriemeting.meet_categorie(CAT, land="be")
klopt("de vragen worden bedacht met 'Belgische'", gevraagd.get("landnaam") == "Belgische")
klopt("in het Nederlands", "Nederlands" in (gevraagd.get("taal") or ""))
klopt("voor de categorie zelf", gevraagd.get("slug") == CAT)
klopt("en bewaard onder de Belgische sleutel", len(db.categorie_vragen(CAT + "@be")) >= 30)
klopt("de gewone vragen blijven leeg", db.categorie_vragen(CAT) == [])
gevraagd.clear()
categoriemeting.meet_categorie(CAT, land="nl")
klopt("Nederland meet met de gewone vragen (geen landnaam meegegeven)",
      "landnaam" not in gevraagd)

print("\n== 6. EEN NIEUW LAND IS EEN REGEL ==")
klopt("Belgie staat in de lijst", "be" in vraaglanden.VRAAGLANDEN)
klopt("de nachtronde loopt alle landen uit de lijst langs",
      "for land in vraaglanden.VRAAGLANDEN" in lees("onderhoud.py"))
klopt("herberekenen doet de landrondes ook",
      "herbereken_ranglijst(slug, land=land)" in lees("onderhoud.py"))
klopt("de beheerknop kan per land meten", "land=(request.form.get(\"land\")" in bron)

print("\n== NA DE CONTROLE ==")
klopt("een lege landronde wordt niet afgerond",
      "if land and not telbaar:" in lees("categoriemeting.py"))
klopt("positie_van_winkel kijkt alleen naar gewone rondes",
      "AND u.ronde IN (SELECT id FROM categorie_rondes WHERE land IS NULL)" in lees("db.py"))
import onderhoud  # noqa: E402
import kosten  # noqa: E402
gemeten = []
onderhoud.db.categorieen_om_te_meten = lambda *a: [{"categorie": f"g{i}"} for i in range(10)]
onderhoud.db.landrondes_om_te_meten = lambda land, *a: [{"categorie": "l1"}, {"categorie": "l2"}]
onderhoud.kosten.mag_doorgaan = lambda: {"mag": True}
onderhoud.kosten.ruimte_vandaag = lambda: {"past_een_categorie": True}
onderhoud.categoriemeting.meet_categorie = \
    lambda slug, land=None: gemeten.append((slug, land)) or {"fout": "test"}
onderhoud.stap_meten(3)
klopt("landrondes komen BOVENOP de gewone, ook bij een achterstand",
      gemeten == [("g0", None), ("g1", None), ("g2", None), ("l1", "be"), ("l2", "be")])
gemeten.clear()
onderhoud.METEN_LAND_PER_NACHT = 1
onderhoud.stap_meten(1)
klopt("met eigen plekken voor het land", gemeten == [("g0", None), ("l1", "be")])
gemeten.clear()
onderhoud.stap_meten(0)
klopt("op nul meet er niets", gemeten == [])

opruimen()
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: een land met eigen vragen, zonder de rest te breken.")
