"""Bewaakt dat de beheerpagina's achter een inlogscherm zitten.

De sleutel stond in het webadres van elke beheerpagina. Daarmee staat hij ook in
je browsergeschiedenis, in de logboeken van Render, en op elke schermafdruk die
je maakt. In augustus is er zo al een keer een sleutel in een chat beland.

De sleutel blijft bestaan en ?key= blijft werken, want de cron-taken gebruiken
hem en de bladwijzers ook. Wat er verandert: hij staat na een keer gebruiken
niet meer in de adresbalk.
"""
import os
import re
import sys

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HIER)
from pad import APP  # noqa: E402
sys.path.insert(0, APP)
os.environ.setdefault("SHOPIFY_API_KEY", "test-client-id")
os.environ.setdefault("SHOPIFY_API_SECRET", "testgeheim")
os.environ["ADMIN_KEY"] = "sleutelvoordetest"

import app as krillo  # noqa: E402

fouten = []


def zo(omschrijving, gekregen, verwacht):
    if gekregen == verwacht:
        print(f"  ok  {omschrijving}")
    else:
        print(f"  FOUT {omschrijving}: kreeg {gekregen!r}, verwacht {verwacht!r}")
        fouten.append(omschrijving)


def klopt(omschrijving, voorwaarde):
    zo(omschrijving, bool(voorwaarde), True)


print("\n== zonder inloggen kom je er niet in ==")
gast = krillo.app.test_client()
uit = gast.get("/admin/benadering")
zo("je wordt doorgestuurd", uit.status_code, 302)
zo("naar het inlogscherm", uit.headers.get("Location"), "/admin/inloggen")

print("\n== een verkeerde sleutel komt er niet in ==")
uit = gast.post("/admin/inloggen", data={"sleutel": "fout"})
zo("je blijft op het scherm", uit.status_code, 200)
klopt("met een foutmelding", "klopt niet" in uit.get_data(as_text=True))
klopt("en je bent niet binnen", gast.get("/admin/benadering").status_code == 302)
# Het scherm mag NIET verklappen of er wel een sleutel ingesteld is. Dat
# verschil vertelt een vreemde iets wat hij niet hoeft te weten.
klopt("het scherm verklapt de sleutel niet",
      "sleutelvoordetest" not in uit.get_data(as_text=True))

print("\n== met de goede sleutel kom je binnen, en blijf je binnen ==")
baas = krillo.app.test_client()
uit = baas.post("/admin/inloggen", data={"sleutel": "sleutelvoordetest"})
zo("je wordt doorgestuurd", uit.status_code, 302)
zo("de volgende pagina werkt zonder sleutel in het adres",
   baas.get("/admin/benadering").status_code, 200)

print("\n== de oude manier met ?key= blijft werken ==")
# Dit MOET blijven werken: de cron-taken en de bladwijzers gebruiken hem.
oud = krillo.app.test_client()
uit = oud.get("/admin/benadering?key=sleutelvoordetest")
zo("hij laat je binnen", uit.status_code, 302)
klopt("maar haalt de sleutel uit het adres",
      "key=" not in (uit.headers.get("Location") or ""))
zo("en daarna ben je gewoon binnen", oud.get("/admin/benadering").status_code, 200)

print("\n== uitloggen werkt ==")
oud.get("/admin/uitloggen")
zo("je staat weer buiten", oud.get("/admin/benadering").status_code, 302)

print("\n== elke beheerpagina zit erachter ==")
BRON = open(os.path.join(APP, "app.py")).read()
# Geen enkele route mag nog zelf op ?key= controleren voor de beheerpagina's.
# De cron-routes gebruiken een EIGEN sleutel (CRON_KEY) en die blijven zo.
resten = [r.strip() for r in BRON.split("\n")
          if '_sleutel_klopt(request.args.get("key")' in r
          and "cron_key" not in r and "admin_key" not in r]
zo("geen losse controle meer op de beheerpagina's", resten, [])
klopt("en er zijn er flink wat omgezet", BRON.count("_mag_bij_beheer()") >= 15)

print("\n== de cron-taken gaan niet door het inlogscherm ==")
# Die hebben geen browser en geen koekje. Zouden ze doorgestuurd worden naar het
# inlogscherm, dan draait de benadering nooit meer.
klopt("de cron-routes gebruiken hun eigen sleutel",
      BRON.count('_sleutel_klopt(request.args.get("key"), cron_key)') >= 2)

print()
if fouten:
    print(f"{len(fouten)} FOUT(EN):")
    for f in fouten:
        print(f"  - {f}")
    sys.exit(1)
print("Alles goed.")
