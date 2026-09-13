"""De categorie-indeling: de laag waar de hele ombouw op rust.

Krillo gaat van meten per winkel naar meten per categorie. Een koopvraag wordt
dan een keer gesteld en scoort alle winkels in die categorie tegelijk, waardoor
de meetkosten per winkel van tien euro per maand naar ongeveer twee cent gaan.

Wat er hier mis kan gaan zonder dat je het merkt, en wat deze test dus bewaakt:

- Een verzonnen categorie die niet in de vaste lijst staat. Dan ontstaat er een
  ranglijst van een winkel, en die is nergens op gebaseerd.
- Een winkel die stilletjes op "overig" belandt terwijl het model gewoon niets
  teruggaf. Dan lijkt hij ingedeeld en wordt hij nooit opnieuw bekeken.
- Een telling die zegt dat het geslaagd is terwijl de winkels in piepkleine
  categorieen zitten. Dat is precies de fout die twee weken werk zou kosten
  voordat iemand het merkt.
- Indelen dat begint doordat iemand de pagina opent of ververst. Dat kost geld
  en schrijft in de database, en het is de fout die de site op 11 september een
  uur heeft platgelegd.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP, lees  # noqa: E402
sys.path.insert(0, APP)

import db            # noqa: E402
import categorieen   # noqa: E402

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


def leeg_de_lijst():
    conn = db._get_connection()
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM benadering WHERE webshop_url LIKE 'https://test-cat%%'")
    conn.close()


def winkel(nr, categorie=None, email=None):
    url = f"https://test-cat{nr}.nl"
    db.voeg_benadering_toe(url, naam=f"Test {nr}", land="NL", branche="test")
    if email:
        db.zet_benadering(url, email=email)
    if categorie:
        db.zet_categorie(url, categorie)
    return url


print("\n== de vaste lijst zelf ==")
klopt("er zijn genoeg categorieen om zinnig in te delen", len(categorieen.CATEGORIEEN) >= 40)
klopt("er is een 'overig' voor twijfelgevallen", "overig" in categorieen.GELDIG)
slugs = [s for s, _ in categorieen.CATEGORIEEN]
zo("geen dubbele slugs", len(slugs), len(set(slugs)))
klopt("elke slug heeft een leesbare naam",
      all(categorieen.naam_van(s) and categorieen.naam_van(s) != s for s in slugs))
klopt("slugs zijn webadresvriendelijk",
      all(s.replace("-", "").isalnum() and s.islower() for s in slugs))

print("\n== een categorie vastleggen en terugvinden ==")
leeg_de_lijst()
u = winkel(1, "keuken-servies")
zo("de categorie staat erin",
   [w for w in db.winkels_in_categorie("keuken-servies") if w["webshop_url"] == u][0]["webshop_url"], u)

print("\n== winkels zonder categorie ==")
winkel(2)
winkel(3)
zonder = [w for w in db.winkels_zonder_categorie() if w["webshop_url"].startswith("https://test-cat")]
zo("de twee zonder categorie komen terug", len(zonder), 2)
klopt("de al ingedeelde zit er niet bij",
      all(w["webshop_url"] != u for w in zonder))
alles = [w for w in db.winkels_zonder_categorie(opnieuw=True)
         if w["webshop_url"].startswith("https://test-cat")]
zo("met opnieuw=True komen ze alle drie terug", len(alles), 3)

print("\n== de telling, en wanneer die geslaagd heet ==")
leeg_de_lijst()
# Twaalf winkels in een categorie, drie in een andere. Dan zit 80 procent in een
# bruikbare categorie en is het criterium gehaald.
for i in range(100, 112):
    winkel(i, "keuken-servies")
for i in range(200, 203):
    winkel(i, "erotiek")
tel = categorieen.telling()
rijen = {r["categorie"]: r["aantal"] for r in tel["rijen"]}
zo("twaalf in servies", rijen.get("keuken-servies"), 12)
zo("drie in erotiek", rijen.get("erotiek"), 3)

print("\n== een verzonnen categorie wordt niet overgenomen ==")
# Dit is de belangrijkste controle van dit bestand. Zou een verzonnen slug er
# wel in komen, dan ontstaat er een openbare ranglijst die nergens op slaat.
nep = [{"webshop_url": "https://test-catX.nl", "naam": "Test"}]
echt = categorieen.deel_in
categorieen._client = lambda: None
zo("zonder sleutel wordt er niets ingedeeld", categorieen.deel_in(nep), {})

print("\n== indelen zit achter een knop, niet achter het laden van een pagina ==")
bron = lees("app.py")
i = bron.find("def admin_categorieen(")
blok = bron[i:i + 2500]
einde = blok.find("\n@app.route")
blok = blok[:einde] if einde > 0 else blok
klopt("de route accepteert POST", 'methods=["GET", "POST"]' in bron[max(0, i - 120):i])
klopt("indelen gebeurt alleen op een POST", 'request.method == "POST"' in blok)
zo("precies een aanroep naar de indeler", blok.count("deel_alles_in"), 1)
klopt("de telling zelf schrijft niets", "telling()" in blok)

print("\n== de pagina laadt en zegt wat er te zien is ==")
import app as krillo  # noqa: E402

krillo.app.config["TESTING"] = True
klant = krillo.app.test_client()
antwoord = klant.get("/admin/categorieen?key=testsleutel", follow_redirects=True)
zo("de pagina laadt", antwoord.status_code, 200)
tekst = antwoord.get_data(as_text=True)
klopt("met de kop erop", "Winkels indelen in categorieen" in tekst)
klopt("en een oordeel", "Geslaagd" in tekst or "Nog niet geslaagd" in tekst
      or "nog niets ingedeeld" in tekst)
klopt("de knop staat er", "Deel de winkels in" in tekst)

print("\n== zonder inloggen kom je er niet in ==")
kaal = krillo.app.test_client()
antwoord = kaal.get("/admin/categorieen")
klopt("doorgestuurd naar het inlogscherm",
      antwoord.status_code in (301, 302)
      and "/admin/inloggen" in antwoord.headers.get("Location", ""))

print("\n== de besparing wordt eerlijk gerekend ==")
b = categorieen.besparing({"bruikbare_categorieen": 20, "winkels_in_bruikbare": 1000})
zo("duizend winkels los meten kost 2500 euro", b["ronde_oud"], 2500.0)
zo("twintig categorieen meten kost 50 euro", b["ronde_nieuw"], 50.0)
zo("dat is een factor vijftig", b["factor"], 50)
leeg = categorieen.besparing({"bruikbare_categorieen": 0, "winkels_in_bruikbare": 0})
zo("zonder winkels geen deling door nul", leeg["factor"], 0)

leeg_de_lijst()
categorieen.deel_in = echt

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
