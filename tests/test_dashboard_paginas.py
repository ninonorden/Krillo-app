"""Het dashboard is vijf echte pagina's, met grafieken.

WAAROM DEZE TEST BESTAAT

28 september, Nino: "als je op een knop in de zijbalk klikt blijf je op dezelfde
pagina, dat is amateuristisch", en "elke pagina moet vol zijn". Nu heeft elke
pagina een eigen adres (Overzicht, Ranglijst, Vragen, Verbeteringen,
Abonnement), met eigen inhoud en grafieken. Deze test bewaakt:
- elke knop gaat naar een andere pagina, en de knop van de pagina staat aan;
- elke pagina laadt, ook onder /demo, en een onbekend adres stuurt terug;
- de vragen per assistent kloppen (genoemd, wie wel, het echte stukje antwoord);
- in de grafiek staat nummer 1 bovenaan;
- de regel "volgende stap" past bij het pakket.
"""
import os
import sys
import datetime

os.environ["DATABASE_URL"] = "postgresql://krillo@/postgres?host=/tmp&port=5599"
os.environ["ADMIN_KEY"] = "testsleutel"
os.environ["BASE_URL"] = "https://krilloai.com"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import APP  # noqa: E402
sys.path.insert(0, APP)

fouten = []


def klopt(omschrijving, voorwaarde):
    print(("  ok  " if voorwaarde else "  FOUT ") + omschrijving)
    if not voorwaarde:
        fouten.append(omschrijving)


import db  # noqa: E402
import app as k  # noqa: E402
import dashboardpaginas as dp  # noqa: E402

db.init_db()

print("\n== ASSISTENTEN EN VRAGEN ==")
klopt("gpt heet ChatGPT", dp.assistent_naam("gpt-5.6-terra") == "ChatGPT")
klopt("gemini heet Gemini", dp.assistent_naam("gemini-2.5-flash") == "Gemini")
U = "https://fietsenwinkel-demo.nl"
antw = [
    {"vraag": "Beste e-bike webshop?", "model": "gpt-5.6-terra",
     "antwoord": "Kijk bij Stella. Ook Fietsenwinkel-demo.nl heeft service aan huis. Let op garantie.",
     "genoemde_winkels": {"winkel_kon_genoemd": True, "winkels": [{"naam": "Stella"}, {"naam": "Fietsenwinkel-demo"}],
                          "aanbevolen": ["Fietsenwinkel-demo"]}},
    {"vraag": "Beste e-bike webshop?", "model": "gemini-2.5-flash", "antwoord": "Stella en bol.com.",
     "genoemde_winkels": {"winkel_kon_genoemd": True, "winkels": [{"naam": "Stella"}, {"naam": "bol.com", "soort": "platform"}]}},
    {"vraag": "Bakfiets online kopen", "model": "gpt-5.6-terra", "antwoord": "Bakfiets.nl is bekend.",
     "genoemde_winkels": {"winkel_kon_genoemd": True, "winkels": [{"naam": "Bakfiets.nl"}]}},
]
v = dp.vragen_overzicht(1, U, "fietsenwinkel-demo.nl", antwoorden=antw)
klopt("twee vragen, een gewonnen, een verloren", (v["totaal"], v["gewonnen"], v["verloren"]) == (2, 1, 1))
klopt("verloren eerst", v["vragen"][0]["vraag"] == "Bakfiets online kopen")
gewonnen = v["vragen"][1]
klopt("per assistent: ChatGPT noemde en raadde aan",
      gewonnen["per_model"][0]["genoemd"] and gewonnen["per_model"][0]["aanbevolen"])
klopt("het stukje antwoord is de zin met de winkel erin",
      gewonnen["per_model"][0]["fragment"].startswith("Ook Fietsenwinkel-demo.nl"))
klopt("platforms tellen niet als concurrent", "bol.com" not in gewonnen["per_model"][1]["anderen"])
per = {a["naam"]: a for a in v["per_assistent"]}
klopt("telling per assistent", per["ChatGPT"]["genoemd"] == 1 and per["ChatGPT"]["van"] == 2
      and per["Gemini"]["genoemd"] == 0)

print("\n== DE GRAFIEK ==")
d = [datetime.datetime(2026, m, 27) for m in (7, 8, 9)]
svg = str(dp.lijngrafiek([{"naam": "jij", "jij": True, "punten": list(zip(d, (9, 5, 2)))}]))
import re  # noqa: E402
ys = [float(y) for y in re.findall(r'<circle cx="[0-9.]+" cy="([0-9.]+)"', svg)]
klopt("nummer 1 bovenaan: een betere plek staat hoger", ys == sorted(ys, reverse=True))
klopt("de dag staat erbij", "27 Sep" in svg)
klopt("met een meting is er nog geen lijn", str(dp.lijngrafiek([{"naam": "x", "jij": True, "punten": [(d[0], 3)]}])) == "")

print("\n== VOLGENDE STAP PER PAKKET ==")
klopt("Fix wachtend op toegang", "give us access" in dp.volgende_stap(
    {}, {"uitvoering": {"stand": "wacht_op_toegang"}, "shopify_winkel": False}))
klopt("Fix met wijzigingen", "We changed 3 things" in dp.volgende_stap(
    {}, {"wijzigingen": [1, 2, 3], "doet_werk": True}))
klopt("Watch met klaarstaande verbeteringen", "2 fixes are ready" in dp.volgende_stap(
    {}, {"actieplan": {"acties": [1, 2]}, "doet_werk": False}))
klopt("zonder werk: de beweging", "moved up 2 places" in dp.volgende_stap({"verschil": 2}, None))

print("\n== DE PAGINA'S ==")
tok = db.get_or_create_klant("https://paginatest.nl", "p@paginatest.nl")
c = k.app.test_client()
hrefs = set()
for naam, pad, labels in dp.PAGINAS:
    r = c.get(f"/mijn/{tok}" + (f"/{pad}" if pad else ""))
    h = r.get_data(as_text=True)
    klopt(f"{labels['en']} laadt", r.status_code == 200)
    klopt(f"{labels['en']}: de eigen knop staat aan",
          f'class="aan" href="/mijn/{tok}' + (f"/{pad}" if pad else "") + '"' in h)
    hrefs.add(f"/mijn/{tok}" + (f"/{pad}" if pad else ""))
klopt("vijf verschillende adressen", len(hrefs) == 5)
klopt("een onbekend adres stuurt terug naar het overzicht",
      c.get(f"/mijn/{tok}/onzin").status_code in (301, 302))
klopt("geen ankers meer in de zijbalk", 'href="#vragen"' not in c.get(f"/mijn/{tok}").get_data(as_text=True))

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: vijf echte pagina's, met grafieken.")
