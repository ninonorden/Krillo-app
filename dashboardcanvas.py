"""De gegevens voor het dashboard in de vorm van het canvas (8 oktober 2026, versie 10).

WAAROM DIT BESTAAT

Nino keurde de borden Dashboard.dc.html en Diagnose.dc.html goed en wil het
echte dashboard er precies zo uit laten zien: een zijbalk met groepen
Measure / Understand / Improve, een samenvattingsregel, vijf tegels, een rij
"Why you lose / What to do now / Sources AI quotes" en een doelkaart.
Al die blokken hebben gegevens nodig die app.py niet had. Ze staan hier, los
van app.py (dat tegelijk door een andere werker wordt bewerkt) en los van het
sjabloon, zodat ze zonder een hele pagina te bouwen te testen zijn.

DE REGEL VOOR ELK CIJFER: alleen wat we echt gemeten hebben. Een badge in de
zijbalk toont dus een echt aantal of niets. De bronnen-donut telt in hoeveel
antwoorden een site genoemd wordt (AI geeft geen bronlinks), en zegt dat ook.
Een doel toont "redenen" alleen als de scan van de winnaar al bewaard is.
"""
from markupsafe import Markup

import waaromverlies as wv

# Welke pagina in welke groep staat. De volgorde binnen een groep is die van
# dashboardpaginas.PAGINAS.
GROEPEN = [
    ("measure", {"en": "Measure", "nl": "Meten"}, ("overzicht", "ranglijst", "vragen")),
    ("understand", {"en": "Understand", "nl": "Begrijpen"}, ("waarom", "sitecheck")),
    ("improve", {"en": "Improve", "nl": "Verbeteren"}, ("verbeteringen", "abonnement")),
]

# Kleine lijniconen (14px), een per pagina. Eigen tekeningen, geen bibliotheek:
# die kan traag laden of blokkeren, en de zijbalk staat op elke pagina.
_ICOON = {
    "overzicht": '<rect x="2" y="2" width="5" height="5" rx="1.2"/><rect x="9" y="2" width="5" height="5" rx="1.2"/><rect x="2" y="9" width="5" height="5" rx="1.2"/><rect x="9" y="9" width="5" height="5" rx="1.2"/>',
    "ranglijst": '<path d="M3 13V8M8 13V3M13 13V6"/>',
    "vragen": '<path d="M3 4h10M3 8h10M3 12h6"/>',
    "waarom": '<circle cx="8" cy="8" r="5.5"/><path d="M8 5v3.4M8 10.8v.2"/>',
    "sitecheck": '<path d="M3 8.5l3 3 7-7"/>',
    "verbeteringen": '<path d="M8 13V3M4 7l4-4 4 4"/>',
    "abonnement": '<rect x="2" y="4" width="12" height="9" rx="1.6"/><path d="M2 7.5h12"/>',
}


def icoon(naam):
    pad = _ICOON.get(naam, '<rect x="3" y="3" width="10" height="10" rx="2"/>')
    return Markup('<svg class="zi" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" '
                  f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{pad}</svg>')


def badges(beeld, gekozen, sitescore, taal="en"):
    """{paginanaam: {"tekst", "kleur"}}. Alleen echte cijfers; ontbreekt het cijfer, dan geen badge.

    kleur: "goed" (groen), "slecht" (oranje) of "stil" (grijs)."""
    uit = {}
    if beeld:
        if beeld.get("positie") and not beeld.get("nul"):
            uit["ranglijst"] = {"tekst": f"#{beeld['positie']}", "kleur": "goed"}
        telbaar = beeld.get("telbaar") or 0
        if telbaar:
            uit["vragen"] = {"tekst": str(telbaar), "kleur": "stil"}
            verloren = telbaar - (beeld.get("genoemd") or 0)
            if verloren > 0:
                uit["waarom"] = {"tekst": str(verloren), "kleur": "slecht"}
    if sitescore is not None:
        uit["sitecheck"] = {"tekst": str(sitescore), "kleur": "stil"}
    if gekozen:
        uit["verbeteringen"] = {"tekst": str(len(gekozen)), "kleur": "stil"}
    return uit


def menu(links, badge_van, taal="en"):
    """De zijbalk in groepen. links: [{"naam","label","href","aan"}] uit app._dashboard."""
    per_naam = {l["naam"]: l for l in links}
    uit = []
    for sleutel, kop, namen in GROEPEN:
        items = []
        for n in namen:
            if n in per_naam:
                l = dict(per_naam[n])
                l["icoon"] = icoon(n)
                l["badge"] = badge_van.get(n)
                items.append(l)
        if items:
            uit.append({"sleutel": sleutel, "kop": kop.get(taal, kop["en"]), "knoppen": items})
    return uit


def gids_regel(gids, taal="en"):
    """De kleine voortgangskaart onderaan de zijbalk: x/y en de eerste open stap.
    Komt uit dezelfde gids als de grote kaart op het overzicht (echte vinkjes)."""
    if not gids or not gids.get("totaal"):
        return None
    volgende = next((s for s in gids.get("stappen") or [] if not s.get("klaar") and not s.get("info")), None)
    tijd = (volgende or {}).get("tijd") or ""
    return {"klaar": gids["klaar"], "totaal": gids["totaal"],
            "deel": round(100 * gids["klaar"] / gids["totaal"]),
            "volgende": (volgende or {}).get("titel"), "tijd": tijd}


def samenvatting(beeld, vragen, taal="en"):
    """De regel boven de tegels: beweging sinds de vorige meting, en wie AI noemt waar jij mist."""
    nl = taal == "nl"
    delen = []
    v = (beeld or {}).get("verschil")
    if v and v > 0:
        delen.append((f"Je steeg {v} plaats(en) sinds de vorige meting." if nl
                      else f"You moved up {v} place{'s' if v != 1 else ''} since the last measurement."))
    elif v and v < 0:
        delen.append((f"Je zakte {-v} plaats(en) sinds de vorige meting." if nl
                      else f"You dropped {-v} place{'s' if v != -1 else ''} since the last measurement."))
    verloren = wv.verloren_vragen(vragen)
    if verloren:
        telling = {}
        for q in verloren:
            n = wv.winnaar_naam(q)
            if n:
                telling[n] = telling.get(n, 0) + 1
        if telling:
            naam = sorted(telling, key=lambda n: -telling[n])[0]
            delen.append((f"{naam} wordt bij {telling[naam]} van je {len(verloren)} verloren vragen genoemd." if nl
                          else f"{naam} is named instead of you in {telling[naam]} of your {len(verloren)} lost questions."))
    elif vragen and vragen.get("totaal"):
        delen.append("Je wordt bij elke gemeten vraag genoemd." if nl else "You are named in every question we measured.")
    return " ".join(delen)


KLEUREN_BRON = {"reviews": "#0A0A0B", "comparison": "#7C5CDB", "community": "#D97706", "marketplace": "#0E7490",
                "platform": "#9A9BA3"}
NAAM_BRON = {"reviews": ("Review sites", "Reviewsites"), "comparison": ("Comparison sites", "Vergelijkers"),
             "community": ("Communities", "Communities"), "marketplace": ("Marketplaces", "Marktplaatsen"),
             "platform": ("Other platforms", "Andere platforms")}


def bronnen_donut(bronnen, taal="en"):
    """Uit bronnenkaart.bronnen(): per soort site het aandeel van alle keren dat een
    bron genoemd werd. Geeft {"stukken": [...], "totaal", "van", "top": [...]} of None.

    Eerlijk: dit zijn sites die in de antwoordTEKST staan (AI geeft geen links), en het
    aandeel is dat van de bronvermeldingen, niet van alle antwoorden."""
    if not bronnen:
        return None
    per_soort = {}
    for b in bronnen:
        per_soort[b["soort"]] = per_soort.get(b["soort"], 0) + b["aantal"]
    totaal = sum(per_soort.values())
    if not totaal:
        return None
    stukken, opgeteld = [], 0.0
    for soort, n in sorted(per_soort.items(), key=lambda x: -x[1]):
        deel = 100.0 * n / totaal
        stukken.append({"soort": soort, "naam": NAAM_BRON.get(soort, (soort, soort))[0 if taal != "nl" else 1],
                        "procent": round(deel), "kleur": KLEUREN_BRON.get(soort, "#9A9BA3"),
                        "da": f"{deel:.2f} {100 - deel:.2f}", "off": f"{-opgeteld:.2f}"})
        opgeteld += deel
    return {"stukken": stukken, "totaal": totaal, "van": bronnen[0].get("van"),
            "top": [b["naam"] for b in bronnen[:3]]}


def acties_nu(verloren, gekozen, werkblok, taal="en", maximaal=5, href_waarom=None):
    """"What to do now": korte regels uit de aanpak per verloren vraag (vraagaanpak,
    bestaande tekst), met de status die we echt weten: Op je lijst als de klant de vraag
    koos, anders Voorgesteld. Bij een Fix-klant ook hoeveel wijzigingen wij al deden."""
    from urllib.parse import quote
    en = taal != "nl"
    rijen = []
    for v in sorted(verloren, key=lambda q: q["vraag"] not in (gekozen or []))[:3]:
        a = wv.acties(v, gekozen, None, en)
        # Alleen de eerste twee stappen per vraag: wat je op je eigen site doet.
        # De derde (lees hun pagina) staat op de pagina Why you lose.
        for st in a["stappen"][:2]:
            titel = (f"{st['kop']} voor “{a['onderwerp']}”" if not en
                     else f"{st['kop']} for “{a['onderwerp']}”")
            if st["nr"] == 2:
                titel = (f"{st['kop']} over “{a['onderwerp']}”" if not en
                         else f"{st['kop']} about “{a['onderwerp']}”")
            rijen.append({"kop": titel, "waar": st["waar"], "status": st["status"], "soort": st["soort"],
                          "href": (f"{href_waarom}?vraag={quote(v['vraag'])}" if href_waarom else None)})
    wijz = len((werkblok or {}).get("wijzigingen") or [])
    if wijz and (werkblok or {}).get("doet_werk"):
        rijen.insert(0, {"kop": (f"{wijz} wijziging(en) door ons gedaan" if not en
                                 else f"{wijz} change{'s' if wijz != 1 else ''} we made"),
                         "waar": "Fixes", "status": "Live", "soort": "live", "href": None})
    return rijen[:maximaal]


# ---------------------------------------------------------------------------
# De doelkaart: "What do you want to win?"
# ---------------------------------------------------------------------------
def _plek_tekst(v, taal):
    nl = taal == "nl"
    per_model = v.get("per_model") or []
    if not per_model:
        return ("Wordt gemeten" if nl else "Being measured"), None
    genoemd = [m["assistent"] for m in per_model if m.get("genoemd")]
    aanbevolen = [m["assistent"] for m in per_model if m.get("aanbevolen")]
    if aanbevolen:
        return (("Aangeraden door " if nl else "Advised by ") + ", ".join(aanbevolen)), True
    if genoemd:
        return (("Genoemd door " if nl else "Named by ") + ", ".join(genoemd)), True
    return ("Niet genoemd" if nl else "Not named"), False


def doelen(vragen, gekozen, eigen, taal, href_waarom, ranglijst_rijen=None, eigen_checks=None, paginas=None):
    """Elk doel is een koopvraag die de klant koos ("Add to my fixes") of een eigen vraag.

    Per doel: waar je staat, de beste concurrent (de eerste andere genoemde winkel), het
    aantal redenen (alleen uit een bewaarde scan van de winnaar) en de link naar Why you lose.
    href_waarom: het adres van de pagina Why you lose, zonder vraag."""
    from urllib.parse import quote
    import vraagaanpak
    nl = taal == "nl"
    per_vraag = {q["vraag"]: q for q in (vragen or {}).get("vragen", [])}
    uit = []

    def maak(soort, v, eigen_id=None):
        plek, goed = _plek_tekst(v, taal)
        anderen = wv.alle_anderen(v)
        beste = anderen[0] if anderen else None
        aantal = None
        if beste and eigen_checks:
            onderwerp = vraagaanpak.onderwerp(v["vraag"])
            ontbreekt = bool(paginas) and not wv.pagina_voor_onderwerp(onderwerp, paginas)
            aantal = wv.tel_redenen_uit_cache(wv.winnaar_naam(v), ranglijst_rijen, eigen_checks, taal,
                                              pagina_ontbreekt=ontbreekt)
        uit.append({"soort": soort, "vraag": v["vraag"], "plek": plek, "plek_goed": goed, "beste": beste,
                    "redenen": aantal,
                    "meting": (("Elke maand gemeten" if nl else "Measured every month") if soort == "vraag"
                               else ("Elke week gemeten" if nl else "Measured every week")),
                    "href": f"{href_waarom}{'&' if '?' in href_waarom else '?'}vraag={quote(v['vraag'])}"})
    for q in gekozen or []:
        if q in per_vraag:
            maak("vraag", per_vraag[q])
    for e in eigen or []:
        maak("eigen", wv.eigen_als_vraag(e))
    for d in uit:
        d["soort_label"] = (("Eigen vraag" if nl else "Own question") if d["soort"] == "eigen"
                            else ("Koopvraag" if nl else "Question"))
    return uit


def voorstellen(vragen, gekozen, aantal=3):
    """De drie grootste verloren vragen die nog geen doel zijn: de vragen waar AI de meeste
    verschillende andere winkels noemt (daar verlies je aan de meeste concurrentie)."""
    kandidaten = [q for q in wv.verloren_vragen(vragen) if q["vraag"] not in (gekozen or [])]
    kandidaten.sort(key=lambda q: -len(wv.alle_anderen(q)))
    return [q["vraag"] for q in kandidaten[:aantal]]
