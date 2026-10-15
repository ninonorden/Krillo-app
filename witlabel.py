"""Wit-label rapport en export voor bureaus (15 oktober 2026).

Goedgekeurd voorstel 4 (roadmap 246), hoort bij het pakket voor bureaus en
merken (490). Een bureau verkoopt Krillo door als het de cijfers onder EIGEN
naam aan zijn klant kan geven:
- het maandrapport als PDF met de naam en het logo van het bureau, zonder
  verwijzing naar Krillo (report.pdf?label=1);
- een export als CSV (Excel opent hem): de plek, en per koopvraag of de winkel
  genoemd werd en wie wel. Die is er voor elke betalende klant.

Het logo is een link naar een plaatje (https), dat we bij het maken van de PDF
ophalen: hoogstens 5 MB (begrenzing.py), alleen PNG of JPG.
"""
import csv
import io
import json
import re

import db

SLEUTEL = "witlabel:"
PAKKETTEN = {"merken", "bureau", "agency"}


def mag(pakket):
    return (pakket or "").lower() in PAKKETTEN


def zet(klant_token, naam, logo_url):
    naam = re.sub(r"\s+", " ", (naam or "")).strip()[:60]
    logo_url = (logo_url or "").strip()
    if logo_url and not re.match(r"^https://[^\s]{4,400}$", logo_url):
        return False
    db.zet_instelling(SLEUTEL + klant_token, json.dumps({"naam": naam, "logo_url": logo_url}))
    return True


def van(klant_token):
    try:
        return json.loads(db.get_instelling(SLEUTEL + (klant_token or "")) or "null")
    except (TypeError, ValueError):
        return None


def merk(klant_token, haal=None):
    """{"naam", "logo"} voor klantrapport.pdf, of None als er niets ingesteld is."""
    w = van(klant_token)
    if not w or not (w.get("naam") or w.get("logo_url")):
        return None
    logo = None
    if w.get("logo_url"):
        try:
            if haal is None:
                import requests
                r = requests.get(w["logo_url"], timeout=10)
                soort = (r.headers.get("Content-Type") or "").lower()
                logo = r.content if r.status_code == 200 and ("png" in soort or "jpeg" in soort or "jpg" in soort) else None
            else:
                logo = haal(w["logo_url"])
        except Exception as e:
            print(f"Logo ophalen mislukt: {e}")
    return {"naam": w.get("naam") or "", "logo": logo}


def csv_export(beeld, vragen_overzicht):
    """De export als tekst (CSV, puntkomma voor Nederlandse Excel)."""
    uit = io.StringIO()
    w = csv.writer(uit, delimiter=";")
    w.writerow(["store", "category", "country", "rank", "of", "named in", "questions", "recommended in"])
    w.writerow([beeld.get("webshop_url"), beeld.get("categorie"), beeld.get("land"), beeld.get("positie"),
                beeld.get("van"), beeld.get("genoemd"), beeld.get("telbaar"), beeld.get("aanbevolen")])
    w.writerow([])
    w.writerow(["question", "named", "recommended", "ready to buy", "who AI named instead"])
    for v in (vragen_overzicht or {}).get("vragen") or []:
        anderen = []
        for m in v.get("per_model") or []:
            for n in m.get("anderen") or []:
                if n not in anderen:
                    anderen.append(n)
        w.writerow([v.get("vraag"), "yes" if v.get("gewonnen") else "no", "yes" if v.get("aanbevolen") else "no",
                    "yes" if v.get("intentie", "koopklaar") == "koopklaar" else "no", ", ".join(anderen[:5])])
    return "﻿" + uit.getvalue()
