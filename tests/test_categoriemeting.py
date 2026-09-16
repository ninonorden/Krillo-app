"""De categoriemeting: een vraag, alle winkels tegelijk gescoord.

Dit is het hart van de nieuwe opzet. Wat er hier misgaat gaat niet een beetje
mis maar helemaal, want de uitkomst belandt straks in een openbare ranglijst en
in de post naar winkels die er niet om vroegen.

Wat deze test bewaakt:

- De koppeling van een naam uit een antwoord aan onze eigen winkel. Zegt het
  antwoord "Dille & Kamille" en staat bij ons dille-kamille.nl, dan moet dat
  dezelfde winkel zijn. Gaat dat mis, dan krijgt een winkel een positie die
  nergens op slaat.
- Vragen waarin geen enkele webshop genoemd kon worden mogen NIET meetellen.
  Anders maak je elk cijfer mooier of lelijker dan het is.
- Aanbevolen weegt zwaarder dan genoemd in de ranglijst. In een rij staan is
  iets anders dan aangeraden worden, en dat verschil is precies wat wij
  verkopen.
- Meten hoort op een eigen draad, nooit aan een verzoek. Dertig vragen aan twee
  modellen is tien minuten; gunicorn kapt na twee minuten af. Die fout is op 11
  en op 13 september allebei gemaakt.
"""
import os
import sys
import time

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import db               # noqa: E402
import categorieen      # noqa: E402
import categoriemeting  # noqa: E402

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

CAT = "keuken-servies"
WINKELS = ["https://kookhuis.nl", "https://de-pannenwinkel.nl", "https://tafelgoed.nl"]


def opruimen():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM benadering WHERE webshop_url = ANY(%s)", (WINKELS,))
        cur.execute("DELETE FROM categorie_vragen WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_antwoorden WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_uitkomsten WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_rondes WHERE categorie = %s", (CAT,))
    conn.close()


opruimen()
for url in WINKELS:
    db.voeg_benadering_toe(url, naam=url.split("//")[1].split(".")[0], land="NL", branche="test")
    db.zet_categorie(url, CAT)

print("\n== de winkels van een categorie, inclusief de kinderen ==")
kind = "https://pannen-extra.nl"
db.voeg_benadering_toe(kind, naam="Pannen Extra", land="NL", branche="test")
db.zet_categorie(kind, "kookgerei")   # kookgerei rolt op in keuken-servies
WINKELS.append(kind)
lijst = db.winkels_in_categorie_met_kinderen(CAT)
zo("de kindcategorie telt mee", len([w for w in lijst if w["webshop_url"] == kind]), 1)
klopt("en de eigen winkels ook", len(lijst) >= 4)

print("\n== een naam uit een antwoord koppelen aan onze winkel ==")
# Dit is de belangrijkste controle. Gaat dit mis, dan staat er straks een
# verkeerde positie op een openbare pagina.
genoemde = {
    "winkel_kon_genoemd": True,
    "winkels": [{"naam": "Kookhuis", "positie": 1},
                {"naam": "De Pannenwinkel", "positie": 2},
                {"naam": "Iemand Anders", "positie": 3}],
    "aanbevolen": ["Kookhuis"],
}
uit = categoriemeting.koppel_aan_winkels(genoemde, [{"webshop_url": u} for u in WINKELS])
klopt("kookhuis.nl is herkend", uit["https://kookhuis.nl"]["genoemd"])
klopt("en als aanbevolen", uit["https://kookhuis.nl"]["aanbevolen"])
zo("met zijn positie", uit["https://kookhuis.nl"]["positie"], 1)
klopt("de-pannenwinkel.nl ook, ondanks het streepje",
      uit["https://de-pannenwinkel.nl"]["genoemd"])
klopt("maar die is niet aanbevolen", uit["https://de-pannenwinkel.nl"]["aanbevolen"] is False)
klopt("tafelgoed.nl stond er niet in", uit["https://tafelgoed.nl"]["genoemd"] is False)
zo("en heeft dus geen positie", uit["https://tafelgoed.nl"]["positie"], None)

print("\n== een antwoord zonder winkels raakt niemand ==")
leeg = categoriemeting.koppel_aan_winkels(
    {"winkel_kon_genoemd": False, "winkels": [], "aanbevolen": []},
    [{"webshop_url": u} for u in WINKELS])
klopt("niemand genoemd", not any(v["genoemd"] for v in leeg.values()))

print("\n== de vragen van een categorie bewaren en teruglezen ==")
db.bewaar_categorie_vragen(CAT, [
    {"vraag": "Waar koop ik online emaille servies?", "intentie": "winkel"},
    {"vraag": "Welke webshop heeft mooi servies onder de 50 euro?", "intentie": "prijs"},
])
vragen = db.categorie_vragen(CAT)
zo("twee vragen bewaard", len(vragen), 2)
db.bewaar_categorie_vragen(CAT, [{"vraag": "Waar koop ik online emaille servies?",
                                  "intentie": "winkel"}])
zo("dezelfde vraag komt er niet twee keer in", len(db.categorie_vragen(CAT)), 2)

print("\n== een hele meting, met nagemaakte modelantwoorden ==")
# De modellen worden hier vervangen, want een test mag nooit echte aanroepen
# doen. Wat getest wordt is de keten eromheen: tellen, rangschikken, bewaren.
echte_vraag = categoriemeting.metingen.stel_een_vraag
echte_lezer = categoriemeting.winkels_uit_antwoord
echte_aanbieders = categoriemeting.metingen.beschikbare_aanbieders

categoriemeting.metingen.beschikbare_aanbieders = lambda: [
    {"provider": "openai", "model": "gpt-test", "toonnaam": "ChatGPT (test)"}]
categoriemeting.metingen.stel_een_vraag = lambda a, v, min_tekens=None: {
    "gelukt": True, "antwoord": f"antwoord op {v}", "invoer_tokens": 10,
    "uitvoer_tokens": 20, "duur_ms": 5, "pogingen": 1, "foutsoort": None}


def nep_lezer(vraag, antwoord):
    # De tweede vraag is er een waarin geen webshop genoemd kon worden. Die
    # hoort buiten de telling te blijven.
    if "onder de 50 euro" in vraag:
        return {"winkel_kon_genoemd": False, "winkels": [], "aanbevolen": []}
    return {"winkel_kon_genoemd": True,
            "winkels": [{"naam": "Kookhuis", "positie": 1},
                        {"naam": "De Pannenwinkel", "positie": 4}],
            "aanbevolen": ["Kookhuis"]}


categoriemeting.winkels_uit_antwoord = nep_lezer
try:
    uitkomst = categoriemeting.meet_categorie(CAT)
    zo("er is geen fout", uitkomst.get("fout"), None)
    zo("twee vragen gesteld", uitkomst["vragen"], 2)
    zo("maar er telt er maar een mee", uitkomst["telbaar"], 1)
    rang = {r["webshop_url"]: r for r in uitkomst["ranglijst"]}
    zo("kookhuis staat eerste", rang["https://kookhuis.nl"]["positie"], 1)
    zo("want aanbevolen weegt zwaarder dan genoemd",
       rang["https://de-pannenwinkel.nl"]["positie"], 2)
    zo("de pannenwinkel is wel genoemd", rang["https://de-pannenwinkel.nl"]["genoemd"], 1)
    zo("maar niet aanbevolen", rang["https://de-pannenwinkel.nl"]["aanbevolen"], 0)
    klopt("tafelgoed staat onderaan", rang["https://tafelgoed.nl"]["positie"] >= 3)

    print("\n== de ranglijst komt uit de database terug ==")
    lijst = db.laatste_ranglijst(CAT)
    klopt("er is een ronde", lijst["ronde"] is not None)
    zo("met alle winkels erin", len(lijst["rijen"]), 4)
    zo("en het aantal meetellende vragen", lijst["telbaar"], 1)
    zo("de eerste is kookhuis", lijst["rijen"][0]["webshop_url"], "https://kookhuis.nl")

    print("\n== en een winkel kan zijn eigen positie opvragen ==")
    eigen = db.positie_van_winkel("https://kookhuis.nl")
    zo("positie 1", eigen["positie"], 1)
    zo("van vier winkels", eigen["van"], 4)
    zo("in de goede categorie", eigen["categorie"], CAT)

    print("\n== de volledige antwoorden zijn bewaard ==")
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM categorie_antwoorden WHERE categorie = %s", (CAT,))
        aantal = cur.fetchone()[0]
    conn.close()
    zo("twee antwoorden bewaard", aantal, 2)
finally:
    categoriemeting.metingen.stel_een_vraag = echte_vraag
    categoriemeting.winkels_uit_antwoord = echte_lezer
    categoriemeting.metingen.beschikbare_aanbieders = echte_aanbieders

print("\n== meten draait op een eigen draad ==")
bron = lees("app.py")
i = bron.find("def admin_ranglijst(")
blok = bron[i:i + 2600]
einde = blok.find("\n@app.route")
blok = blok[:einde] if einde > 0 else blok
klopt("de route accepteert POST", 'methods=["GET", "POST"]' in bron[max(0, i - 120):i])
klopt("meten gebeurt alleen op een POST", 'request.method == "POST"' in blok)
zo("via start_meting en niet rechtstreeks", blok.count("start_meting"), 1)
klopt("meet_categorie wordt niet in het verzoek aangeroepen",
      "meet_categorie(" not in blok)

print("\n== de meting zegt bij welke stap hij is ==")
# Op 16 september stond er tien minuten "vraag 0 van 0". Dat leest als
# vastgelopen, terwijl hij de dertig koopvragen van een nieuwe categorie aan
# het bedenken was. Een stap zonder teller moet dus zijn naam noemen.
import time as _t  # noqa: E402
categoriemeting._stand.update({"bezig": True, "categorie": CAT,
                               "stap": "dertig koopvragen bedenken voor deze categorie",
                               "vraag_nu": 0, "vragen_totaal": 0,
                               "gestart_op": _t.time() - 120})
st = categoriemeting.stand()
klopt("er staat een stap bij", st["stap"])
klopt("en hoe lang hij bezig is", "minuten" in st["verstreken"])
klopt("na twee minuten is hij niet vastgelopen", st["vastgelopen"] is False)
categoriemeting._stand["gestart_op"] = _t.time() - (categoriemeting.METING_VASTGELOPEN_NA + 60)
klopt("maar na de grens wel", categoriemeting.stand()["vastgelopen"])
klopt("en dan mag je opnieuw starten",
      categoriemeting.start_meting("bestaat-niet", max_vragen=1) is True)
_t.sleep(0.5)
categoriemeting._stand.update({"bezig": False, "gestart_op": None, "stap": None})

bron_sjabloon = open(os.path.join(APP, "templates", "admin_ranglijst.html")).read()
klopt("de pagina toont de stap", "stand.stap" in bron_sjabloon)
klopt("en meldt een vastgelopen meting", "stand.vastgelopen" in bron_sjabloon)
klopt("het testen van leesmodellen staat uit de weg",
      "<details" in bron_sjabloon)

print("\n== de beheerpagina laadt ==")
import app as krillo  # noqa: E402

krillo.app.config["TESTING"] = True
klant = krillo.app.test_client()
antwoord = klant.get("/admin/ranglijst?key=testsleutel", follow_redirects=True)
zo("de pagina laadt", antwoord.status_code, 200)
tekst = antwoord.get_data(as_text=True)
klopt("met de kop erop", "Ranglijst per categorie" in tekst)
klopt("en een knop om te meten", "Meet deze categorie" in tekst)

kaal = krillo.app.test_client()
antwoord = kaal.get("/admin/ranglijst")
klopt("zonder inloggen kom je er niet in",
      antwoord.status_code in (301, 302)
      and "/admin/inloggen" in antwoord.headers.get("Location", ""))

opruimen()

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
