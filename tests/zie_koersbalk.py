"""Geen test maar een kijkhulp: rendert de homepage met drie gemeten
categorieen en zet hem als bestand neer, zodat de koersbalk met een echte
browser bekeken kan worden.

WAAROM DIT BESTAAT
Een test die "class=ticker staat er" zegt bewijst niet dat de balk loopt. De
duurste fout in dit project was zeggen dat iets af was terwijl het er niet
anders uitzag. Dus: renderen, in een browser zetten, ernaar kijken.

Dit bestand draait NIET mee in de testronde: die pakt alleen test_*.py. Het
staat in tests/ omdat het dezelfde opzet gebruikt, en het blijft staan zodat de
balk later opnieuw bekeken kan worden zonder hem eerst na te bouwen.

Gebruik: python3 tests/zie_koersbalk.py, daarna /tmp/koersbalk.html openen.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://www.krillo.nl"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

import db  # noqa: E402

# Dezelfde drie categorieen als op de echte site, zodat wat ik zie lijkt op wat
# Nino ziet.
CATS = [
    ("kijk-servies", "servies en tafelgerei",
     [("cookinglife.nl", 7), ("dekbedovertrek.nl", 5), ("kookwinkel.nl", 3)]),
    ("kijk-speelgoed", "speelgoed",
     [("lobbes.nl", 20), ("ilovespeelgoed.nl", 14), ("top1toys.nl", 9)]),
    ("kijk-wijn", "wijn en sterke drank",
     [("drankdozijn.nl", 17), ("wijnvoordeel.nl", 11), ("gall.nl", 6)]),
]

db.init_db()
conn = db._get_connection()
with conn, conn.cursor() as cur:
    for slug, _, winkels in CATS:
        urls = [f"https://{n}" for n, _ in winkels]
        cur.execute("DELETE FROM benadering WHERE webshop_url = ANY(%s)", (urls,))
        for tabel in ("categorie_antwoorden", "categorie_uitkomsten", "categorie_rondes"):
            cur.execute(f"DELETE FROM {tabel} WHERE categorie = %s", (slug,))
conn.close()

for slug, _naam, winkels in CATS:
    for naam, _ in winkels:
        db.voeg_benadering_toe(f"https://{naam}", naam=naam, land="NL", branche="t")
        db.zet_categorie(f"https://{naam}", slug)
    ronde = db.start_categorie_ronde(slug, 30, len(winkels))
    db.bewaar_categorie_uitkomsten(ronde, slug, [
        {"webshop_url": f"https://{naam}", "positie": i + 1, "genoemd": g,
         "aanbevolen": max(0, g // 3), "beste_positie": 1}
        for i, (naam, g) in enumerate(winkels)
    ], 28)
    db.bewaar_categorie_antwoord(
        ronde, slug, "waar koop ik dit online", "model-a", "antwoordtekst",
        {"winkel_kon_genoemd": True,
         "winkels": [{"naam": n, "positie": i + 1} for i, (n, _) in enumerate(winkels)],
         "aanbevolen": [winkels[0][0]]})

import app  # noqa: E402

app.app.config["TESTING"] = True
k = app.app.test_client()
html = k.get("/").get_data(as_text=True)

doel = "/tmp/koersbalk.html"
with open(doel, "w") as f:
    f.write(html)

import re  # noqa: E402

balk = 'class="ticker"' in html
helften = html.count('class="helft"')
m = re.search(r"--loopduur:([0-9.]+)s", html)
berichten = len(re.findall(r'<span class="post">', html))

print(f"Homepage weggeschreven naar {doel} ({len(html)} tekens)")
print(f"Balk aanwezig: {balk}")
print(f"Aantal helften (hoort 2 te zijn): {helften}")
print(f"Loopduur: {m.group(0) if m else 'NIET GEVONDEN'}")
print(f"Aantal berichten in totaal (2 kopieen): {berichten}")
