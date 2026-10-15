"""Wat moet ik publiceren om genoemd te worden? Een contentplan per winkel (15 oktober 2026).

Goedgekeurd voorstel 8. Peec (Actions) en Profound (Agents) geven grote merken
een plan; een kleine winkel weet nu niet WELKE pagina hij als volgende schrijft.

WAAROM ZONDER MODEL. Alles komt uit de meting van zijn categorie:
- welke soort bronnen AI aanhaalt (reviewsites, vergelijkers, fora, marktplaatsen);
- welke vragen hij verliest, en waarover (prijs, service, product; vraaglabels);
- of hij de koopklare of de orienterende vragen verliest;
- hoe AI de nummer 1 omschrijft (imago).
Daaruit hoogstens DRIE stukken, op volgorde van wat het meeste uitmaakt, elk met
het soort pagina (gids, vergelijking, productbeschrijving, vragen en antwoorden),
een titel op een echte verloren vraag, en waarom. Niets verzonnen: staat er geen
data, dan geen stuk.
"""

MAX = 3


def plan(vragen_overzicht, bronnen=None, kenmerken_een=None, taal="en"):
    """[{"soort", "titel", "waarom"}], hoogstens MAX."""
    nl = taal == "nl"
    vragen = (vragen_overzicht or {}).get("vragen") or []
    verloren = [v for v in vragen if not v.get("gewonnen")]
    if not vragen:
        return []
    soorten = {}
    for b in bronnen or []:
        soorten[b.get("soort")] = soorten.get(b.get("soort"), 0) + (b.get("aantal") or 0)
    uit = []

    orient = [v for v in verloren if v.get("intentie") == "orienterend"]
    if orient:
        v = orient[0]["vraag"]
        uit.append({"soort": "Koopgids" if nl else "Buying guide",
                    "titel": v[:1].upper() + v[1:],
                    "waarom": (f"Je verliest {len(orient)} vraag/vragen van kopers die nog kiezen. Een gids die die vraag "
                               "eerlijk beantwoordt, is wat AI dan aanhaalt.") if nl else
                              (f"You lose {len(orient)} question(s) from shoppers who are still choosing. A guide that "
                               "answers it honestly is what AI quotes then.")})

    if soorten.get("comparison", 0) or soorten.get("marketplace", 0):
        v = next((x["vraag"] for x in verloren if x.get("label") in ("product", "prijs")), None) or \
            (verloren[0]["vraag"] if verloren else vragen[0]["vraag"])
        uit.append({"soort": "Vergelijkingspagina" if nl else "Comparison page",
                    "titel": (f"Welke past bij jou? {v}" if nl else f"Which one fits you? {v}")[:90],
                    "waarom": ("AI haalt in jouw categorie vergelijkers en marktplaatsen aan. Een eerlijke vergelijking "
                               "van je eigen producten (voor wie, verschil, prijs) geeft AI een reden om jou te noemen.") if nl
                    else ("In your category AI cites comparison sites and marketplaces. An honest comparison of your "
                          "own products (who it is for, the difference, the price) gives AI a reason to name you.")})

    service = [v for v in verloren if v.get("label") == "service"]
    if service or soorten.get("reviews", 0):
        uit.append({"soort": "Vragen en antwoorden" if nl else "Questions and answers",
                    "titel": ("Levering, retour en garantie bij ons" if nl else "Delivery, returns and warranty"),
                    "waarom": (("Je verliest vragen over service (levering, retour). " if service else "") +
                               "Korte antwoorden in de woorden van de koper, met je reviews erbij, zijn wat AI als bewijs "
                               "van betrouwbaarheid overneemt.") if nl else
                              (("You lose questions about service (delivery, returns). " if service else "") +
                               "Short answers in the shopper's words, with your reviews next to them, are what AI "
                               "repeats as proof that a store can be trusted.")})

    if kenmerken_een:
        k = ", ".join(str(x[0] if isinstance(x, (list, tuple)) else x) for x in kenmerken_een[:3])
        uit.append({"soort": "Productbeschrijving" if nl else "Product description",
                    "titel": ("Je bestverkochte product, opnieuw beschreven" if nl else "Your best seller, described again"),
                    "waarom": (f"AI omschrijft de nummer 1 als: {k}. Zeg op je productpagina even duidelijk waar jij in "
                               "uitblinkt, met feiten (materiaal, maat, voor wie).") if nl else
                              (f"AI describes the #1 as: {k}. Say just as plainly on your product page what you are "
                               "good at, with facts (material, size, who it is for).")})
    return uit[:MAX]
