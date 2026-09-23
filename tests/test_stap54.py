"""Stap 54: de detailpagina (/mijn -> details) in de stijl van het dashboard.

WAAROM DEZE TEST BESTAAT

Het dashboard op /mijn staat sinds 18 september in optie B: witte kaarten,
dunne lijnen, labels in de schrijfmachineletter. De detailpagina met de
dertien controlepunten was blijven hangen: een zwart blok met een
gecentreerd cijfer, blauwe staven en de winkel als "https://..." in de kop.
Wie van het dashboard doorklikte kwam op een pagina die van een andere site
leek. Deze test legt vast dat dat niet terugsluipt.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pad import lees  # noqa: E402

fouten = []


def klopt(omschrijving, voorwaarde):
    if voorwaarde:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}")
        fouten.append(omschrijving)


s = lees("templates/monitoring_details.html")

print("\n== HET CIJFER STAAT IN EEN WITTE KAART ==")
klopt("geen zwart blok meer", ".huidig{background:var(--ink)" not in s)
klopt("een witte kaart met een dunne lijn",
      ".huidig{background:#fff; border:1px solid var(--line)" in s)

print("\n== HET VERLOOP ZOALS OP HET DASHBOARD ==")
klopt("grijze staven", ".balk{width:100%; background:#ECECF0" in s)
klopt("de laatste groen", ".balk.laatste{background:var(--teal);}" in s)

print("\n== DE KOP IS EEN DOMEIN, GEEN WEBADRES ==")
klopt("https wordt weggehaald", "webshop_url | replace('https://','')" in s)

print("\n== DE PAGINA IS ENGELS ==")
import importlib  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
paginataal = importlib.import_module("paginataal")
t = paginataal.teksten("en")
klopt("de titel is Engels", t["d_titel"] == "All measurements")
klopt("geen oud tarief in de teksten",
      not any("39" in str(v) for k, v in t.items() if k.startswith("d_")))

print()
if fouten:
    print(f"FOUT: {len(fouten)} controle(s) mislukt")
    sys.exit(1)
print("Alles goed: de detailpagina hoort bij het dashboard.")
