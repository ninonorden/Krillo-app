"""Stap 56: de koude mail, twee versies, en wat er na de klik gebeurt.

WAAROM DEZE TEST BESTAAT

De koude mail is de enige weg naar klanten die niets kost. Vier dingen die
daar in september misgingen of ontbraken:

1. Er was een versie van de mail. Dan weet je nooit of een andere beter werkt.
   Nu zijn er twee (a: positie voorop, b: vraag voorop), vast per winkel, en
   het beheerscherm telt per versie: link geklikt, naar de prijzen, klant
   geworden. Openen telt NIET mee: dat meet een pixel die Gmail zelf laadt.
2. De vraag in de mail begon met een kleine letter en stond er zonder uitleg
   in het Nederlands. Nu met hoofdletter en "in Dutch" erbij.
3. Wie op de link klikte, kwam op een lijst vol andere winkels zonder te zien
   wat hij nu moest. Nu staat er een balk met zijn eigen plek en een knop.
   Nummer 1 krijgt een ander verhaal (houden, niet repareren).
4. Een winkel moest eerst zelf gemeten zijn ("gemeten") voor hij post kreeg,
   terwijl de mail over zijn plek in de INDEX gaat. Nu is een adres genoeg.
"""
import os
import sys

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
os.environ.pop("MAIL_VARIANTEN", None)
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


import emailing  # noqa: E402

print("\n== 1. TWEE VERSIES, VAST PER WINKEL ==")
urls = [f"https://winkel{i}.nl" for i in range(200)]
versies = [emailing.kies_variant(u) for u in urls]
klopt("beide versies komen voor", set(versies) == {"a", "b"})
klopt("ongeveer de helft elk", 70 < versies.count("a") < 130)
klopt("dezelfde winkel krijgt altijd dezelfde versie",
      all(emailing.kies_variant(u) == v for u, v in zip(urls, versies)))
os.environ["MAIL_VARIANTEN"] = "b"
klopt("MAIL_VARIANTEN laat een versie afvallen",
      {emailing.kies_variant(u) for u in urls} == {"b"})
os.environ["MAIL_VARIANTEN"] = "onzin"
klopt("een tikfout valt terug op versie a", {emailing.kies_variant(u) for u in urls} == {"a"})
os.environ.pop("MAIL_VARIANTEN")

print("\n== 2. DE MAIL ZELF ==")
verstuurd = []
emailing.send_email = lambda to, onderwerp, html, **k: verstuurd.append((onderwerp, html)) or True
beeld = {"positie": 6, "van": 54, "genoemd": 4, "telbaar": 30, "land": "nl",
         "categorie": "speelgoed",
         "gemiste_vragen": [{"vraag": "beste speelgoedwinkel online",
                             "concurrenten": ["Intertoys", "Bart Smit"]}]}
for v in ("a", "b"):
    emailing.send_onderzoeksmail("x@y.nl", "https://www.speel.nl", "https://krilloai.com/uitkomst/t",
                                 beeld=beeld, categorienaam="Speelgoed",
                                 landnaam="the Netherlands", afmeld_url="https://krilloai.com/afmelden/t",
                                 variant=v)
(onderwerp_a, html_a), (onderwerp_b, html_b) = verstuurd
klopt("versie a: de positie in het onderwerp", onderwerp_a == "speel.nl: #6 of 54 in the Krillo index")
klopt("versie b: de vraag in het onderwerp",
      onderwerp_b == "Who AI recommends: Speelgoed in the Netherlands")
klopt("de eerste zin verschilt", "Every month we ask" in html_a and "Every month we ask" not in html_b)
klopt("de rest is hetzelfde: positie in beide", "#6 of 54" in html_a and "#6 of 54" in html_b)
klopt("de vraag begint met een hoofdletter", "Beste speelgoedwinkel online" in html_a)
klopt("met de taal erbij", "One of the questions we asked, in Dutch" in html_a)
klopt("het merk bovenaan: KRILLO INDEX", "KRILLO <span" in html_a and "INDEX</span>" in html_a)
klopt("de knop is blauw zoals de site", "background:#1B3FE0" in html_a)
klopt("geen https in de zin", "https://www.speel.nl" not in html_a)

print("\n== NUMMER 1 LEEST GEEN TEGENSPRAAK ==")
verstuurd.clear()
emailing.send_onderzoeksmail("x@y.nl", "https://mediamarkt.nl", "https://krilloai.com/uitkomst/t",
                             beeld=dict(beeld, positie=1, van=42, genoemd=23),
                             categorienaam="Elektronica algemeen", landnaam="the Netherlands",
                             variant="a")
een = verstuurd[-1][1]
klopt("nummer 1 krijgt een eigen kop boven de gemiste vraag", "Even at #1: a question where you were missing, in Dutch" in een)
klopt("en een zin over vasthouden", "Staying #1 is the hard part" in een)
klopt("de anderen niet", "Staying #1" not in html_a and "Even at #1" not in html_a)

print("\n== DE PROEFMAIL STUURT BEIDE VERSIES ==")
bron = lees("app.py")
klopt("de proef loopt over beide versies", "for v in emailing.MAILVARIANTEN:" in bron)
klopt("met de versie in het onderwerp", 'f"[TEST {variant}] " if proef else ""' in bron)
klopt("alleen een echte mail wordt bij de winkel bewaard",
      "if gelukt and not proef:\n            db.zet_mail_variant(webshop_url, variant)" in bron)

print("\n== 3. DE BALK NA DE KLIK ==")
klopt("de link uit de mail geeft het kenmerk mee", '?jij={token}#p{beeld[\'positie\']}' in bron)
import app as appmod  # noqa: E402
import sitetaal  # noqa: E402


def balk(jij):
    with appmod.app.test_request_context("/index/nl/speelgoed"):
        return appmod.render_template(
            "index_categorie.html", t=sitetaal.teksten("en"), taal="en", land="nl",
            slug="speelgoed", naam="Speelgoed", landnaam="the Netherlands", jij=jij,
            kruimels=[], andere_landen=[], lijst_voor_ai=[], ranglijst=[], niet_genoemd=0,
            totaal=54, telbaar=30, gemeten_op=None, vragen=[], modellen=[],
            canonical="/index/nl/speelgoed", basis_url="https://krilloai.com",
            basis="https://krilloai.com")


zonder = balk(None)
klopt("zonder kenmerk geen balk", 'class="jijbalk"' not in zonder)
zes = balk({"positie": 6, "van": 54, "genoemd": 4, "telbaar": 30, "naam": "speel.nl",
            "verder": "/uitkomst/t/verder"})
klopt("met kenmerk: de eigen plek", "speel.nl is #6 of 54" in zes)
klopt("hoeveel er boven staan", "5 stores rank above you" in zes)
klopt("een knop die telt", 'href="/uitkomst/t/verder"' in zes and "How to move up" in zes)
een = balk({"positie": 1, "van": 54, "genoemd": 20, "telbaar": 30, "naam": "speel.nl",
            "verder": "/uitkomst/t/verder"})
klopt("nummer 1 krijgt een ander verhaal", "Staying there is the hard part" in een
      and "How to keep it" in een and "rank above you" not in een)
nul = balk({"positie": 40, "van": 54, "genoemd": 0, "telbaar": 30, "naam": "speel.nl",
            "verder": "/uitkomst/t/verder"})
klopt("niet genoemd: dat staat er eerlijk", "did not name you in any of the 30" in nul)
klopt("het kenmerk komt alleen in de knop, niet los op de pagina", zes.count("/uitkomst/t") == 1)
klopt("een kenmerk van een andere lijst doet niets",
      'if r["webshop_url"] == eigen_url:' in bron)

print("\n== 4. EEN ADRES IS GENOEG, EIGEN METING NIET NODIG ==")
import db  # noqa: E402
db.init_db()


def sql(opdracht, waarden=None, een=False):
    conn = db._get_connection()
    with conn:
        with conn.cursor() as cur:
            cur.execute(opdracht, waarden)
            uit = cur.fetchone() if een else None
    conn.close()
    return uit


U = "https://stap56-adres.nl"
sql("DELETE FROM benadering WHERE webshop_url = %s", (U,))
db.voeg_benadering_toe(U)
db.zet_benadering(U, stand="adres", email="info@stap56-adres.nl")
sql("UPDATE benadering SET categorie = 'stap56cat' WHERE webshop_url = %s", (U,))
ronde = sql("INSERT INTO categorie_rondes (categorie, afgerond_op) VALUES ('stap56cat', now()) "
            "RETURNING id", een=True)[0]
sql("INSERT INTO categorie_uitkomsten (ronde, categorie, webshop_url, positie, genoemd, telbaar) "
    "VALUES (%s, 'stap56cat', %s, 2, 3, 30)", (ronde, U))
klopt("een winkel met alleen een adres en een positie is aan de beurt",
      U in [w["webshop_url"] for w in db.te_mailen_met_positie(5000)])

print("\n== DE TELLING PER VERSIE ==")
sql("UPDATE benadering SET gemaild_op = now(), bekeken_op = now() WHERE webshop_url = %s", (U,))
klopt("de versie wordt bewaard", db.zet_mail_variant(U, "b"))
rijen = {r["variant"]: r for r in db.trechter_per_variant()}
klopt("en geteld", (rijen.get("b") or {}).get("gemaild", 0) >= 1
      and (rijen.get("b") or {}).get("bekeken", 0) >= 1)
oordeel = appmod._varianten_met_oordeel()
klopt("met te weinig mails geen winnaar",
      oordeel["oordeel"] is None or "Nog geen winnaar" in oordeel["oordeel"]
      or len(oordeel["rijen"]) < 2)
klopt("het scherm toont het", "Welke mail werkt beter" in lees("templates/admin_benadering.html"))

sql("DELETE FROM categorie_uitkomsten WHERE ronde = %s", (ronde,))
sql("DELETE FROM categorie_rondes WHERE id = %s", (ronde,))
sql("DELETE FROM benadering WHERE webshop_url = %s", (U,))

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: twee versies, een nette vraag, een balk na de klik.")
