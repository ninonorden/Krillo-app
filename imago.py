"""Stap 179: wat AI over een winkel zegt (30 september 2026).

WAAROM. Peec heeft "Sentiment" en "Brand perception". Voor een webshop betekent
dat iets concreets: noemt AI je goedkoop of duur, snel of traag, specialist of
generalist? Dat bepaalt bij welke koopvraag je genoemd wordt. Wie bij "waar
koop ik goedkoop ..." nooit opduikt maar wel bij "beste service", weet waar
zijn tekst iets mist.

HOE, EN WAAROM ZONDER MODEL. De antwoorden hebben we al. Uit elke zin waarin
de winkel genoemd wordt, tellen we vaste kenmerken (prijs, assortiment,
levering, service, ...), in het Nederlands en het Engels. Geen model: dat kost
niets, is elke keer hetzelfde, en we zetten AI geen woorden in de mond. De
citaten zijn letterlijk wat de assistent zei.
"""
import json
import re

import scan_engine

# (label, woorden). De labels staan in het Engels: ze komen op de Engelse site.
KENMERKEN = [
    ("Low prices", ["goedkoop", "goedkope", "voordelig", "voordelige", "scherpe prijs", "scherp geprijsd", "lage prijs",
                    "betaalbaar", "betaalbare", "budget", "affordable", "cheap", "low price", "good value"]),
    ("Premium", ["premium", "luxe", "luxueus", "high-end", "exclusief", "exclusieve", "prijzig", "duurder"]),
    ("Wide range", ["ruim assortiment", "groot assortiment", "breed assortiment", "uitgebreid assortiment",
                    "veel keuze", "ruime keuze", "grote keuze", "veel keus", "ruime keus", "grote keus", "wide range", "large selection", "wide selection"]),
    ("Fast delivery", ["snelle levering", "snel geleverd", "snel in huis", "morgen in huis", "volgende dag",
                       "next day", "same day", "fast delivery", "fast shipping", "snelle verzending", "vandaag besteld"]),
    ("Service and advice", ["klantenservice", "persoonlijk advies", "deskundig", "goed advies", "advies",
                            "customer service", "expert advice", "helpful"]),
    ("Trusted", ["betrouwbaar", "betrouwbare", "reviews", "beoordelingen", "keurmerk", "trusted", "reliable",
                 "bekende", "gerenommeerd"]),
    ("Sustainable", ["duurzaam", "duurzame", "biologisch", "biologische", "eco", "sustainable", "tweedehands",
                     "refurbished", "fair trade"]),
    ("Specialist", ["specialist", "gespecialiseerd", "gespecialiseerde", "specialised", "specialized", "niche"]),
    ("Quality", ["kwaliteit", "hoogwaardig", "hoogwaardige", "quality", "high quality"]),
]


def _genoemde(rij):
    g = rij.get("genoemde_winkels") or {}
    if isinstance(g, str):
        try:
            g = json.loads(g)
        except ValueError:
            g = {}
    return g


def _zinnen_over(tekst, webshop_url, naam):
    """De zinnen uit een antwoord waarin deze winkel staat."""
    tekst = re.sub(r"\s+", " ", tekst or "").strip()
    stam = (webshop_url or "").lower().replace("https://", "").replace("http://", "").replace(
        "www.", "").split("/")[0]
    sleutels = {s for s in (stam, stam.split(".")[0], (naam or "").lower()) if len(s) >= 3}
    uit = []
    for zin in re.split(r"(?<=[.!?])\s+|\n+|(?<=\S)\s+(?=\d+\.\s)|\s\*\s", tekst):
        laag = zin.lower()
        if any(s in laag for s in sleutels):
            uit.append(zin.strip(" *-#"))
    return uit


def beeld(webshop_url, naam=None, antwoorden=(), max_citaten=3):
    """{"kenmerken": [(label, aantal)], "citaten": [{"assistent", "vraag", "zin"}], "antwoorden": n}.

    antwoorden: rijen uit db.antwoorden_met_tekst_van_ronde."""
    from dashboardpaginas import assistent_naam
    telling, citaten, gezien, aantal = {}, [], set(), 0
    for rij in antwoorden or []:
        g = _genoemde(rij)
        namen = [w.get("naam") for w in g.get("winkels") or [] if w.get("naam")]
        if not any(scan_engine.is_eigen_winkel(webshop_url, n) for n in namen):
            continue
        aantal += 1
        zinnen = _zinnen_over(rij.get("antwoord"), webshop_url, naam)
        tekst = " ".join(zinnen).lower()
        for label, woorden in KENMERKEN:
            if any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", tekst) for w in woorden):
                telling[label] = telling.get(label, 0) + 1
        for zin in zinnen:
            kort = zin if len(zin) <= 240 else zin[:237].rsplit(" ", 1)[0] + "..."
            if len(citaten) < max_citaten and len(kort) > 30 and kort.lower() not in gezien:
                gezien.add(kort.lower())
                citaten.append({"assistent": assistent_naam(rij.get("model")), "vraag": rij.get("vraag"),
                                "zin": kort})
                break
    kenmerken = sorted(telling.items(), key=lambda kv: -kv[1])
    return {"kenmerken": kenmerken, "citaten": citaten, "antwoorden": aantal}
