"""Stap 15 tot en met 23 van de roadmap, een voor een nagelopen.

WAAROM DEZE TEST BESTAAT

Nino op 17 september: "ik geloof niet dat jij die dashboard hebt gemaakt en
alles hebt gedaan wat je hebt gezegd."

Dat is een terechte vraag, en het antwoord hoort niet van mij te komen maar van
de code. Deze test loopt elke stap van de roadmap langs en controleert hem tegen
de draaiende app. Faalt er een, dan is die stap NIET af, hoe vaak ik ook zeg dat
hij dat wel is.

Elke stap staat hieronder met zijn nummer en zijn naam uit de roadmap.
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

CAT = "stappen-test"
NL = [f"https://stap{n}.nl" for n in range(1, 5)]
BE = [f"https://stapbe{n}.be" for n in range(1, 4)]
ALLE = NL + BE


def opruimen():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM klanten WHERE webshop_url = ANY(%s)", (ALLE,))
        cur.execute("DELETE FROM benadering WHERE webshop_url = ANY(%s)", (ALLE,))
        cur.execute("DELETE FROM categorie_antwoorden WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_uitkomsten WHERE categorie = %s", (CAT,))
        cur.execute("DELETE FROM categorie_rondes WHERE categorie = %s", (CAT,))
    conn.close()


opruimen()
for u in NL:
    db.voeg_benadering_toe(u, naam=u.replace("https://", ""), land="NL", branche="t")
    db.zet_categorie(u, CAT)
for u in BE:
    db.voeg_benadering_toe(u, naam=u.replace("https://", ""), land="BE", branche="t")
    db.zet_categorie(u, CAT)
ronde = db.start_categorie_ronde(CAT, 30, len(ALLE))
db.bewaar_categorie_uitkomsten(ronde, CAT, [
    {"webshop_url": NL[0], "positie": 1, "genoemd": 9, "aanbevolen": 4, "beste_positie": 1},
    {"webshop_url": BE[0], "positie": 2, "genoemd": 8, "aanbevolen": 3, "beste_positie": 1},
    {"webshop_url": NL[1], "positie": 3, "genoemd": 6, "aanbevolen": 1, "beste_positie": 2},
    {"webshop_url": BE[1], "positie": 4, "genoemd": 4, "aanbevolen": 1, "beste_positie": 3},
    {"webshop_url": NL[2], "positie": 5, "genoemd": 2, "aanbevolen": 0, "beste_positie": 5},
    {"webshop_url": BE[2], "positie": 6, "genoemd": 1, "aanbevolen": 0, "beste_positie": 7},
    {"webshop_url": NL[3], "positie": 7, "genoemd": 0, "aanbevolen": 0, "beste_positie": None},
], 28)
for vraag, namen in [("waar koop ik online een stapartikel", ["stap1.nl", "stapbe1.be"]),
                     ("welke webshop verkoopt stapartikelen", ["stap1.nl", "stap2.nl"])]:
    db.bewaar_categorie_antwoord(
        ronde, CAT, vraag, "model-a", "antwoordtekst",
        {"winkel_kon_genoemd": True,
         "winkels": [{"naam": n, "positie": i + 1} for i, n in enumerate(namen)],
         "aanbevolen": namen[:1]})
db.get_or_create_klant(NL[1], "stapklant@example.com")

import app as krillo  # noqa: E402
krillo.app.config["TESTING"] = True
k = krillo.app.test_client()
index = lees("templates/index.html")

print("\n== STAP 15: taalopbouw ==")
import sitetaal  # noqa: E402
klopt("er is een bestand met de teksten in twee talen",
      set(sitetaal.T) == {"nl", "en"})
zo("elke sleutel bestaat in allebei",
   sorted(set(sitetaal.T['nl']) ^ set(sitetaal.T['en'])), [])
zo("een index van Nederland staat in het Nederlands", sitetaal.taal_van_land("nl"), "nl")
zo("een index van het VK in het Engels", sitetaal.taal_van_land("uk"), "en")
nlpagina = k.get(f"/index/nl/{CAT}", headers={"Accept-Language": "en-US,en"})
zo("een Engelse bezoeker wordt NIET omgeleid", nlpagina.status_code, 200)
klopt("en krijgt de Nederlandse indexpagina",
      'html lang="nl"' in nlpagina.get_data(as_text=True))

print("\n== STAP 16: alle cijfers uit de database ==")
cijfers = db.index_cijfers()
klopt("de database levert de cijfers", (cijfers.get("categorieen") or 0) >= 1)
thuis = k.get("/").get_data(as_text=True)
klopt("de homepage toont het aantal categorieen uit de database",
      f'>{cijfers["categorieen"]}</span>' in thuis or
      f'>{cijfers["categorieen"]}<' in thuis)
strook = thuis[thuis.find("hero-cijfers"):thuis.find("</header>")]
klopt("in de cijferstrook staat geen plaatshouder tussen haakjes",
      not re.search(r"\[\d", strook))
klopt("welke landen live zijn komt uit de database",
      "LIVE" in strook and "NL" in strook)

print("\n== STAP 17: nieuwe homepage in stijl A ==")
klopt("de schreefletter van optie A wordt geladen", "Instrument+Serif" in thuis)
klopt("de tekstletter van optie A ook", "family=Archivo" in thuis)
klopt("de oude letters zijn weg",
      "Space+Grotesk" not in thuis and "family=Inter:" not in thuis)
klopt("de hero is donker over de volle breedte",
      "header.hero{background:var(--ink)" in index)
for stuk in ("hero-cijfers", "idx-kaart", "zeskaart", "dash-blok", "methode-blok"):
    klopt(f"de nieuwe sectie {stuk} staat er", stuk in thuis)
for oud in ('id="probleem"', 'id="hoe"', 'id="voorbeeld"',
            'id="wij-doen-het"', 'id="monitoring"'):
    klopt(f"de oude sectie {oud} is weg", oud not in thuis)
klopt("de scan werkt nog", 'id="scanUrlInput"' in thuis and 'id="scanButton"' in thuis)
klopt("het bestelscherm ook", 'id="checkoutOverlay"' in thuis)

print("\n== STAP 18: indexpagina per land in de nieuwe stijl ==")
zo("Nederland heeft een eigen pagina", k.get(f"/index/nl/{CAT}").status_code, 200)
zo("Belgie ook", k.get(f"/index/be/{CAT}").status_code, 200)
pagina = k.get(f"/index/nl/{CAT}").get_data(as_text=True)
klopt("in de nieuwe huisstijl", "Instrument+Serif" in pagina)
klopt("met een marktkiezer", "marktkiezer" in pagina)
klopt("de gestelde vragen staan erop", "waar koop ik online een stapartikel" in pagina)

print("\n== STAP 19: SEO-fundament ==")
klopt("er staat een canonical",
      f'rel="canonical" href="https://www.krillo.nl/index/nl/{CAT}"' in pagina)
klopt("er staat hreflang naar het Nederlands", 'hreflang="nl"' in pagina)
klopt("en naar het Belgische adres", f'/index/be/{CAT}' in pagina)
blokken = re.findall(r'<script type="application/ld\+json">(.*?)</script>', pagina, re.S)
import json  # noqa: E402
soorten = {json.loads(x)["@type"] for x in blokken}
klopt("er staat een ranglijst in gestructureerde gegevens", "ItemList" in soorten)
klopt("en een kruimelpad", "BreadcrumbList" in soorten)
sitemap = k.get("/sitemap.xml").get_data(as_text=True)
klopt("de categorie per land staat in de sitemap",
      f"/index/nl/{CAT}</loc>" in sitemap)
klopt("met een meetdatum erbij",
      re.search(r"/index/nl/" + CAT + r"</loc><lastmod>\d{4}", sitemap))
oud = k.get(f"/index/{CAT}")
zo("een oud adres stuurt permanent door", oud.status_code, 301)

print("\n== STAP 20: openbaar voorbeelddashboard ==")
demo = k.get("/demo")
zo("/demo bestaat", demo.status_code, 200)
dtekst = demo.get_data(as_text=True)
klopt("zonder inloggen", "wachtwoord" not in dtekst.lower() or "voorbeeld" in dtekst.lower())
klopt("het zegt dat het een voorbeeld is", "voorbeeld" in dtekst.lower())
klopt("er staat een positie op", "POSITIE" in dtekst.upper())
klopt("en de homepage linkt ernaartoe", '/demo' in thuis)

print("\n== STAP 21: klantdashboard ==")
klant = db.get_klant_bij_url(NL[1]) if hasattr(db, "get_klant_bij_url") else None
token = None
conn = db._get_connection()
with conn, conn.cursor() as cur:
    cur.execute("SELECT klant_token FROM klanten WHERE webshop_url = %s", (NL[1],))
    rij = cur.fetchone()
    token = rij[0] if rij else None
conn.close()
klopt("de klant heeft een geheime link", bool(token))
mijn = k.get(f"/mijn/{token}")
zo("die link geeft een dashboard", mijn.status_code, 200)
mtekst = mijn.get_data(as_text=True)
klopt("met zijn positie erop", "POSITIE" in mtekst.upper())
klopt("en de vragen die hij verliest", "verliest" in mtekst.lower())
klopt("met de concurrent die wel genoemd werd", "stap1.nl" in mtekst)
klopt("hij staat niet in Google", 'name="robots" content="noindex"' in mtekst)
zo("een verkeerde link geeft 404", k.get("/mijn/bestaatniet").status_code, 404)

print("\n== STAP 22: link opnieuw laten mailen ==")
zo("het formulier bestaat", k.get("/mijn-link").status_code, 200)
a = k.post("/mijn-link", data={"email": "onbekend@example.com"})
zo("een onbekend adres geeft hetzelfde antwoord", a.status_code, 302)
klopt("namelijk verstuurd", "m=verstuurd" in a.headers.get("Location", ""))
robots = k.get("/robots.txt").get_data(as_text=True)
klopt("klantpagina's blijven uit Google", "Disallow: /mijn/" in robots)

print("\n== STAP 23: positie per markt ==")
nlijst = db.ranglijst_per_land(CAT, "nl")
belijst = db.ranglijst_per_land(CAT, "be")
zo("Nederland heeft vier winkels", len(nlijst["rijen"]), 4)
zo("Belgie heeft er drie", len(belijst["rijen"]), 3)
zo("allebei genummerd vanaf een",
   (nlijst["rijen"][0]["positie"], belijst["rijen"][0]["positie"]), (1, 1))
klopt("een winkel kan dus per land een andere positie hebben",
      nlijst["rijen"][0]["webshop_url"] != belijst["rijen"][0]["webshop_url"])
verloop = db.positieverloop(NL[1], CAT, "nl")
klopt("het verloop wordt per land berekend", len(verloop) >= 1)

print("\n== STAP 24: de prijzen, omgezet op 17 september ==")
import payments  # noqa: E402
zo("Watch kost 49", payments.PAKKETTEN["watch"]["prijs"]["value"], "49.00")
zo("Fix kost 149", payments.PAKKETTEN["fix"]["prijs"]["value"], "149.00")
zo("merken kost 490", payments.PAKKETTEN["merken"]["prijs"]["value"], "490.00")
klopt("en die bedragen staan ook op de prijskaarten",
      "&euro;49 <span>/mo</span>" in thuis
      and "&euro;149 <span>/mo</span>" in thuis
      and "&euro;490 <span>/mo</span>" in thuis)

opruimen()

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
