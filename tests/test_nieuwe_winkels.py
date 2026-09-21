"""Stap 62: winkels die AI noemt maar die wij nog niet kenden komen op de lijst.

WAAROM DEZE TEST BESTAAT

Tot 21 september viel elke winkelnaam uit een AI-antwoord die niet op onze
eigen lijst stond stil weg. Dat waren juist de interessantste winkels: die AI
zelf aanraadt. En het maakte de ranglijst minder waar, want een winkel die
twintig keer genoemd werd maar niet op onze lijst stond, kwam er niet in voor.

Nu gaan ze de lijst op. Maar een lijst die zichzelf aanvult kan ook dingen
kapot maken, en daar gaat deze test over:
- Een verzonnen adres mag er niet op (DNS-controle).
- Een winkel die al in een ANDERE categorie staat mag niet stilletjes verhuizen.
- Een winkel die we al kenden onder een andere schrijfwijze mag niet dubbel.
- Een rare meting mag de lijst niet in een keer volgooien (maximum per ronde).
- Wat er bijkomt moet ook echt meetellen in de ranglijst.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

import db  # noqa: E402
import categoriemeting as cm  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


CAT = "test-nieuwe-winkels"
ANDERE = "test-andere-categorie"
ALLE = ["https://bekend.nl", "https://nieuwewinkel.nl", "https://belgischewinkel.be",
        "https://elders.nl", "https://verzonnen-winkel.nl"] + \
       [f"https://extra{i}.nl" for i in range(40)]

db.init_db()


def opruimen():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM benadering WHERE webshop_url = ANY(%s)", (ALLE,))
    conn.close()


opruimen()
db.voeg_benadering_toe("https://bekend.nl", naam="Bekend", land="NL")
db.zet_categorie("https://bekend.nl", CAT)
db.voeg_benadering_toe("https://elders.nl", naam="Elders", land="NL")
db.zet_categorie("https://elders.nl", ANDERE)

print("\n== EEN ADRES SCHOONMAKEN ==")
zo("met https en www en pad", cm._schoon_domein("https://www.FonQ.nl/servies?x=1"), "fonq.nl")
zo("kaal domein blijft kaal", cm._schoon_domein("bol.com"), "bol.com")
zo("null blijft niets", cm._schoon_domein(None), None)
zo("geen domein wordt niets", cm._schoon_domein("weet ik niet"), None)
zo("zonder punt is geen domein", cm._schoon_domein("fonq"), None)

print("\n== HET LEESMODEL VRAAGT OM HET ADRES, EN NIET OM TE GOKKEN ==")
prompt = cm._leesprompt("vraag", "antwoord")
klopt("de opdracht vraagt om het webadres", "WEBADRES" in prompt)
klopt("en zegt uitdrukkelijk niet te gokken", "Nooit gokken" in prompt)

echt_lezen = cm._lees_met
cm._lees_met = lambda aanbieder, p: {
    "winkel_kon_genoemd": True,
    "winkels": [{"naam": "Nieuwe Winkel", "adres": "https://www.nieuwewinkel.nl/", "positie": 1},
                {"naam": "Zonder Adres", "adres": None, "positie": 2}],
    "aanbevolen": ["Nieuwe Winkel"]}
try:
    gelezen = cm.winkels_uit_antwoord("vraag", "antwoord")
finally:
    cm._lees_met = echt_lezen
zo("het adres komt schoon uit het lezen", gelezen["winkels"][0]["adres"], "nieuwewinkel.nl")
zo("zonder adres blijft het leeg", gelezen["winkels"][1]["adres"], None)

print("\n== NIEUWE WINKELS GAAN DE LIJST OP, MET DE REMMEN ==")
winkels = db.winkels_in_categorie_met_kinderen(CAT)
genoemden = [
    {"winkel_kon_genoemd": True,
     "winkels": [{"naam": "Bekend", "adres": "bekend.nl", "positie": 1},
                 {"naam": "Nieuwe Winkel", "adres": "nieuwewinkel.nl", "positie": 2},
                 {"naam": "Belgische Winkel", "adres": "belgischewinkel.be", "positie": 3},
                 {"naam": "Elders", "adres": "elders.nl", "positie": 4},
                 {"naam": "Verzonnen", "adres": "verzonnen-winkel.nl", "positie": 5},
                 {"naam": "Zonder Adres", "adres": None, "positie": 6}],
     "aanbevolen": ["Nieuwe Winkel"]},
    # Een vraag waar geen winkel in kon: daar halen wij niets uit.
    {"winkel_kon_genoemd": False,
     "winkels": [{"naam": "Extra", "adres": "extra0.nl", "positie": 1}],
     "aanbevolen": []},
]
bestaat = lambda d: d != "verzonnen-winkel.nl"  # noqa: E731
nieuw = cm.nieuwe_winkels_uit_antwoorden(genoemden, winkels, CAT, bestaat=bestaat)
zo("precies de twee echt nieuwe winkels",
   sorted(nieuw), ["https://belgischewinkel.be", "https://nieuwewinkel.nl"])

in_cat = {w["webshop_url"] for w in db.winkels_in_categorie_met_kinderen(CAT)}
klopt("de nieuwe winkel staat nu in de categorie", "https://nieuwewinkel.nl" in in_cat)
klopt("een verzonnen adres staat er niet in", "https://verzonnen-winkel.nl" not in in_cat)
klopt("een winkel uit een andere categorie is NIET verhuisd",
      "https://elders.nl" not in in_cat)
anders = {w["webshop_url"] for w in db.winkels_in_categorie_met_kinderen(ANDERE)}
klopt("hij staat nog gewoon in zijn eigen categorie", "https://elders.nl" in anders)
klopt("uit een vraag zonder winkel is niets gehaald",
      "https://extra0.nl" not in in_cat)

conn = db._get_connection()
with conn.cursor() as cur:
    cur.execute("SELECT webshop_url, land, branche FROM benadering WHERE webshop_url = ANY(%s)",
                (["https://nieuwewinkel.nl", "https://belgischewinkel.be"],))
    rijen = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
conn.close()
zo("een .be-winkel krijgt Belgie als land", rijen["https://belgischewinkel.be"][0], "BE")
zo("een .nl-winkel krijgt Nederland", rijen["https://nieuwewinkel.nl"][0], "NL")
zo("en we zien later waar hij vandaan kwam", rijen["https://nieuwewinkel.nl"][1], "ai-antwoord")

zo("een tweede keer voegt niets meer toe",
   cm.nieuwe_winkels_uit_antwoorden(genoemden, db.winkels_in_categorie_met_kinderen(CAT),
                                    CAT, bestaat=bestaat), [])

print("\n== HOOGSTENS EEN HANDVOL PER RONDE ==")
veel = [{"winkel_kon_genoemd": True, "aanbevolen": [],
         "winkels": [{"naam": f"Extra {i}", "adres": f"extra{i}.nl", "positie": i}
                     for i in range(40)]}]
oud_max = cm.MAX_NIEUWE_WINKELS
cm.MAX_NIEUWE_WINKELS = 5
try:
    n = cm.nieuwe_winkels_uit_antwoorden(veel, db.winkels_in_categorie_met_kinderen(CAT),
                                         CAT, bestaat=lambda d: True)
finally:
    cm.MAX_NIEUWE_WINKELS = oud_max
zo("niet meer dan het maximum", len(n), 5)

print("\n== WAT ERBIJ KOMT, TELT OOK MEE IN DE RANGLIJST ==")
winkels = db.winkels_in_categorie_met_kinderen(CAT)
rijen = [{"vraag": "waar koop ik dit", "genoemde_winkels": genoemden[0]}]
telling, telbaar = cm.tel_uit_antwoorden(rijen, winkels)
klopt("de nieuwe winkel is genoemd bij die vraag",
      len(telling["https://nieuwewinkel.nl"]["genoemd"]) == 1)
klopt("en aanbevolen", len(telling["https://nieuwewinkel.nl"]["aanbevolen"]) == 1)

print("\n== DE METING ROEPT HET OOK ECHT AAN ==")
bron = open(os.path.join(APP, "categoriemeting.py"), encoding="utf-8").read()
meet = bron[bron.find("def meet_categorie("):bron.find("def _werk(")]
klopt("meet_categorie voegt nieuwe winkels toe", "nieuwe_winkels_uit_antwoorden(" in meet)
klopt("en telt daarna opnieuw uit de bewaarde antwoorden",
      "tel_uit_antwoorden(db.antwoorden_van_ronde(ronde)" in meet)
klopt("een fout daarin blijft binnen de meting", "Nieuwe winkels toevoegen mislukt" in meet)

print("\n== EEN HELE METING, MET NEPMODELLEN ==")
# De onderdelen hierboven los testen bewijst niet dat ze in een echte ronde
# goed samenwerken. Dus een hele meet_categorie, met nepmodellen in plaats van
# echte, zodat het niets kost en elke keer hetzelfde uitkomt.
import kosten  # noqa: E402
import metingen  # noqa: E402

RONDECAT = "test-hele-ronde"
opruimen()
conn = db._get_connection()
with conn, conn.cursor() as cur:
    for tabel in ("categorie_antwoorden", "categorie_uitkomsten", "categorie_rondes",
                  "categorie_vragen"):
        cur.execute(f"DELETE FROM {tabel} WHERE categorie = %s", (RONDECAT,))
conn.close()
for u, n in [("https://bekend.nl", "Bekend"), ("https://extra1.nl", "Extra 1"),
             ("https://extra2.nl", "Extra 2")]:
    db.voeg_benadering_toe(u, naam=n, land="NL")
    db.zet_categorie(u, RONDECAT)
db.bewaar_categorie_vragen(RONDECAT, [{"vraag": "waar koop ik dit online", "intentie": "algemeen"}])

nep = {
    "cm.VRAGEN_PER_CATEGORIE": (cm, "VRAGEN_PER_CATEGORIE", 1),
    "aanbieders": (metingen, "beschikbare_aanbieders",
                   lambda: [{"provider": "nep", "model": "nepmodel"}]),
    "vraag": (metingen, "stel_een_vraag", lambda a, v, **k: {
        "gelukt": True, "antwoord": "Kijk bij Bekend en bij Nieuwe Winkel.",
        "invoer_tokens": 1, "uitvoer_tokens": 1, "duur_ms": 1}),
    "lezen": (cm, "winkels_uit_antwoord", lambda v, a: {
        "winkel_kon_genoemd": True, "aanbevolen": ["Nieuwe Winkel"],
        "winkels": [{"naam": "Bekend", "adres": "bekend.nl", "positie": 2},
                    {"naam": "Nieuwe Winkel", "adres": "nieuwewinkel.nl", "positie": 1}]}),
    "rem": (kosten, "mag_doorgaan", lambda *a, **k: {"mag": True, "reden": None}),
    "boek": (kosten, "registreer_aanroep", lambda **k: None),
    "dns": (cm, "_domein_bestaat", lambda d: True),
}
bewaard = {k: getattr(m, n) for k, (m, n, _) in nep.items()}
for k, (m, n, w) in nep.items():
    setattr(m, n, w)
try:
    uit = cm.meet_categorie(RONDECAT)
finally:
    for k, (m, n, _) in nep.items():
        setattr(m, n, bewaard[k])

zo("de meting liep zonder fout", uit.get("fout"), None)
zo("en meldt de nieuwe winkel", uit.get("nieuwe_winkels"), ["https://nieuwewinkel.nl"])
rang = {r["webshop_url"]: r for r in uit.get("ranglijst", [])}
klopt("de nieuwe winkel staat in DEZE ranglijst, niet pas volgende maand",
      "https://nieuwewinkel.nl" in rang)
klopt("en hij is genoemd geteld", (rang.get("https://nieuwewinkel.nl") or {}).get("genoemd"))
klopt("de bekende winkel staat er ook nog gewoon in", "https://bekend.nl" in rang)

conn = db._get_connection()
with conn, conn.cursor() as cur:
    for tabel in ("categorie_antwoorden", "categorie_uitkomsten", "categorie_rondes",
                  "categorie_vragen"):
        cur.execute(f"DELETE FROM {tabel} WHERE categorie = %s", (RONDECAT,))
conn.close()

opruimen()
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed: winkels die AI noemt komen op de lijst, met de remmen erop.")
