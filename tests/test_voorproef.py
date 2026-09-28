"""De uitkomstpagina na de koude mail verkoopt (stap 135).

WAAROM DEZE TEST BESTAAT

27 september: van de 24 winkels die hun uitkomst openden ging er 1 naar de
prijzen. Ze kwamen op een openbare lijst vol andere winkels. Nu krijgen ze hun
EIGEN dashboard als gratis voorproef, met een knop die meteen het afrekenen
opent met hun winkel ingevuld. Van de vragen zijn er twee helemaal open; bij de
rest gaat het antwoord en wie er genoemd werd NIET mee naar de browser.
Ook de demo kreeg lege pagina's Fixes en Plan (Nino, 28 september); die tonen
nu wat Watch en Fix doen.
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


def klopt(o, v):
    print(("  ok  " if v else "  FOUT ") + o)
    if not v:
        fouten.append(o)


import db  # noqa: E402
import app as k  # noqa: E402
import dashboardpaginas as dp  # noqa: E402
db.init_db()
U = "https://voorproef-winkel.nl"
beeld = {"webshop_url": U, "naam": "voorproef-winkel.nl", "categorie": "fietsen", "land": "nl", "ronde": 1,
         "positie": 7, "van": 42, "vorige_positie": None, "verschil": None, "genoemd": 6, "aanbevolen": 2,
         "telbaar": 30, "gemeten_op": None, "verloop": [], "boven_mij": [],
         "gemiste_vragen": [{"vraag": "V1", "concurrenten": ["Stella"], "platforms": [], "aanbevolen": []}]}
k.klantbeeld.bouw = lambda url, land=None, **kw: dict(beeld)
antw = [{"vraag": f"Vraag {i}", "model": "gpt-5", "antwoord": f"Geheim antwoord {i} over Stella.",
         "genoemde_winkels": {"winkel_kon_genoemd": True, "winkels": [{"naam": "Stella"}]}} for i in range(5)]
db.antwoorden_met_tekst_van_ronde = lambda r: antw
db.winkel_bij_benchmark_token = lambda t: U if t == "tok135" else None
db.noteer_uitkomst_bekeken = lambda u: None
geklikt = []
db.noteer_doorgeklikt = lambda u: geklikt.append(u)
db.ranglijst_per_land = lambda c, l, limiet=500: {"ronde": 1, "telbaar": 30, "rijen": []}
c = k.app.test_client()

r = c.get("/uitkomst/tok135")
h = r.get_data(as_text=True)
klopt("de uitkomst is zijn eigen dashboard, geen doorverwijzing", r.status_code == 200 and "free preview" in h)
klopt("met knoppen voor Watch en Fix", "/uitkomst/tok135/verder?plan=watch" in h and "/uitkomst/tok135/verder?plan=fix" in h)
klopt("en afmelden staat erbij", "/afmelden/tok135" in h)
klopt("de zijbalk blijft in de voorproef", 'href="/uitkomst/tok135/questions"' in h)
v = c.get("/uitkomst/tok135/questions").get_data(as_text=True)
klopt("de eerste twee antwoorden zijn open", "Geheim antwoord 0" in v and "Geheim antwoord 1" in v)
klopt("de rest gaat niet mee naar de browser", "Geheim antwoord 3" not in v and "Geheim antwoord 4" not in v)
klopt("maar de vraag zelf wel", "Vraag 4" in v)
f = c.get("/uitkomst/tok135/fixes").get_data(as_text=True)
klopt("Fixes toont wat we zouden doen, met beide pakketten", "WHAT WE WOULD DO" in f and "Start Fix" in f)
r = c.get("/uitkomst/tok135/verder?plan=fix")
klopt("de knop telt de doorklik", geklikt == [U])
klopt("en opent het afrekenen voor Fix met de winkel ingevuld",
      "plan=fix" in r.headers["Location"] and "winkel=" in r.headers["Location"])
klopt("een onbekend plan wordt genegeerd", "plan=" not in c.get("/uitkomst/tok135/verder?plan=gratis").headers["Location"])
klopt("de homepage opent het venster bij ?plan=", "plan === 'watch' || plan === 'fix'" in lees("templates/index.html"))
db.voorbeeldwinkel = lambda: {"webshop_url": U, "categorie": "fietsen", "land": "nl"}
d = c.get("/demo/fixes").get_data(as_text=True)
klopt("de demo heeft een gevulde pagina Fixes", "WHAT WE WOULD DO" in d and "/?plan=fix#pricing" in d)
klopt("de demo heeft een gevulde pagina Plan", "Start Watch" in c.get("/demo/plan").get_data(as_text=True))
klopt("de ranglijst legt de volgorde uit", "then by how often it <strong>names</strong>" in lees("templates/dashboard.html"))
print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de voorproef verkoopt.")
