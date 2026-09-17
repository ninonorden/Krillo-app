"""Alles wat op het dashboard van een winkel staat, in een keer opgehaald.

WAAROM DIT EEN EIGEN BESTAND IS

Hetzelfde beeld wordt op drie plekken getoond: het openbare voorbeelddashboard
(/demo), de klantpagina achter een geheime link, en straks de mail met het
maandbericht. Als elk van die drie zijn eigen berekening doet, gaan ze na drie
wijzigingen uit elkaar lopen en staat er in de mail een andere positie dan op
het scherm. Dat is het soort fout waar een klant je op afrekent, want hij ziet
twee cijfers die allebei van jou komen en die elkaar tegenspreken.

NUL MODELAANROEPEN. Alles hier komt uit wat er al gemeten en bewaard is. Het
dashboard openen kost dus niets, hoe vaak iemand ook ververst.

DE VRAGEN DIE JE VERLIEST

Dit is het stuk waar een klant iets aan heeft. Niet "je staat veertiende", maar:
bij deze vraag werd je niet genoemd, en deze drie concurrenten wel. Dat komt uit
de bewaarde antwoorden, dus het is letterlijk wat de assistent zei.
"""
import categoriemeting
import db
import scan_engine

# Hoeveel gemiste vragen er hoogstens getoond worden. Meer dan een handvol leest
# niemand, en de bedoeling is dat er iets mee GEDAAN wordt.
MAX_VRAGEN = int(__import__("os").environ.get("DASHBOARD_MAX_VRAGEN", "6"))

# Hoeveel concurrenten er per gemiste vraag bij staan.
MAX_CONCURRENTEN = 3


def bouw(webshop_url, land=None, max_vragen=MAX_VRAGEN):
    """Het volledige beeld van een winkel. Geeft None als hij nergens in staat."""
    winkel = db.winkel_kort(webshop_url)
    if not winkel or not winkel.get("categorie"):
        return None
    categorie = winkel["categorie"]
    land = (land or winkel.get("land") or "").lower() or None

    lijst = db.ranglijst_per_land(categorie, land, limiet=500)
    if not lijst or not lijst.get("ronde"):
        return None

    rijen = lijst["rijen"]
    mij = next((r for r in rijen if r["webshop_url"] == webshop_url), None)
    if mij is None:
        return None

    verloop = db.positieverloop(webshop_url, categorie, land)
    vorige = verloop[-2]["positie"] if len(verloop) > 1 else None

    boven = [r for r in rijen if r["positie"] < mij["positie"]][-3:]

    return {
        "webshop_url": webshop_url,
        "naam": winkel.get("naam") or webshop_url,
        "categorie": categorie,
        "land": land,
        "ronde": lijst["ronde"],
        "positie": mij["positie"],
        "van": len(rijen),
        "vorige_positie": vorige,
        "verschil": (vorige - mij["positie"]) if vorige else None,
        "genoemd": mij.get("genoemd") or 0,
        "aanbevolen": mij.get("aanbevolen") or 0,
        "telbaar": lijst.get("telbaar") or 0,
        "gemeten_op": mij.get("gemeten_op"),
        "verloop": verloop,
        "boven_mij": boven,
        "gemiste_vragen": gemiste_vragen(lijst["ronde"], webshop_url,
                                         max_vragen=max_vragen),
    }


def gemiste_vragen(ronde, webshop_url, max_vragen=MAX_VRAGEN):
    """De koopvragen waarbij deze winkel NIET genoemd werd, met wie wel.

    Waarom hier niet gewoon op naam vergeleken wordt: een assistent schrijft
    "Dille & Kamille", "Dille en Kamille" of "dille-kamille.nl" en dat is drie
    keer dezelfde winkel. scan_engine.is_eigen_winkel weet dat, en dat is
    precies dezelfde vergelijking die bij het meten gebruikt is. Twee keer
    hetzelfde bouwen is twee keer dezelfde fout kunnen maken."""
    uit = []
    gezien = set()
    for rij in db.antwoorden_van_ronde(ronde):
        genoemde = rij.get("genoemde_winkels") or {}
        if isinstance(genoemde, str):
            import json
            genoemde = json.loads(genoemde)
        if not genoemde.get("winkel_kon_genoemd"):
            continue
        vraag = rij["vraag"]
        if vraag in gezien:
            continue

        namen = [w.get("naam") for w in genoemde.get("winkels", []) if w.get("naam")]
        if any(scan_engine.is_eigen_winkel(webshop_url, n) for n in namen):
            continue

        gezien.add(vraag)
        uit.append({
            "vraag": vraag,
            "model": rij.get("model"),
            "concurrenten": namen[:MAX_CONCURRENTEN],
            "aanbevolen": [n for n in genoemde.get("aanbevolen", [])][:MAX_CONCURRENTEN],
        })
        if len(uit) >= max_vragen:
            break
    return uit


def balkhoogtes(verloop, hoogte=88):
    """De hoogte van elk staafje in het verloop, in pixels.

    In Python en niet in het sjabloon: rekenwerk in een sjabloon is niet te
    testen, en dit is precies het soort som dat stilletjes fout gaat bij een
    lege lijst of bij een positie van een."""
    if not verloop:
        return []
    slechtste = max((r["positie"] or 1) for r in verloop)
    uit = []
    for r in verloop:
        p = r["positie"] or 1
        # Lager is beter, dus een lage positie hoort een LAAG staafje te zijn.
        deel = p / slechtste if slechtste else 1
        uit.append({
            "positie": p,
            "van": r.get("van"),
            "datum": r.get("afgerond_op"),
            "hoogte": max(10, int(round(hoogte * deel))),
        })
    return uit
