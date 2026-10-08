"""De gegevens en grafieken voor de pagina's van het klantdashboard.

WAAROM DIT BESTAAT (28 september). Het dashboard was een lange pagina met een
zijbalk waarvan elke knop alleen naar beneden scrolde. Nino: "amateuristisch,
dat is niet echt een dashboard". Nu zijn het vijf echte pagina's met een eigen
adres (Overzicht, Ranglijst, Vragen, Verbeteringen, Abonnement), en die hebben
elk hun eigen gegevens nodig. Die staan hier, los van app.py, zodat ze te
testen zijn zonder een hele pagina te bouwen.

De grafieken zijn SVG, hier in Python getekend. Geen grafiekbibliotheek uit het
netwerk: die kan traag laden, geblokkeerd worden of van uiterlijk veranderen,
en een dashboard waar de grafiek ontbreekt is erger dan een eenvoudige grafiek.
"""
import re
from markupsafe import Markup, escape

import db
import scan_engine
import vraaglabels

# De pagina's, in de volgorde van de zijbalk. Het tweede veld is het stukje
# achter /mijn/<token>/ (leeg voor het overzicht).
PAGINAS = [
    ("overzicht", "", {"en": "Overview", "nl": "Overzicht"}),
    ("ranglijst", "ranking", {"en": "Ranking", "nl": "Ranglijst"}),
    ("vragen", "questions", {"en": "Questions", "nl": "Vragen"}),
    ("verbeteringen", "fixes", {"en": "Fixes", "nl": "Verbeteringen"}),
    ("abonnement", "plan", {"en": "Plan", "nl": "Abonnement"}),
]
PAD_NAAR_PAGINA = {pad: naam for naam, pad, _ in PAGINAS}

# In de gratis voorproef (na de koude mail) zijn zoveel vragen helemaal open.
PROEF_OPEN_VRAGEN = 2


def assistent_naam(model):
    """Van "gpt-5.6-terra" naar "ChatGPT". Een klant kent de merknaam, niet het model."""
    m = (model or "").lower()
    if m.startswith(("gpt", "o1", "o3", "o4", "openai", "chatgpt")):
        return "ChatGPT"
    if m.startswith("gemini") or "google" in m:
        return "Gemini"
    if m.startswith("claude"):
        return "Claude"
    if "perplexity" in m or m.startswith("sonar"):
        return "Perplexity"
    return model or "AI"


def _genoemde(rij):
    import json
    g = rij.get("genoemde_winkels") or {}
    if isinstance(g, str):
        try:
            g = json.loads(g)
        except Exception:
            g = {}
    return g


def zonder_opmaak(tekst):
    """De opmaak van een AI-antwoord eruit, de woorden blijven (1 oktober).

    De klantblik vond op /demo/questions "- **Kunstveiling.nl** — groot
    Nederlands": sterretjes, een opsommingsteken en een lang streepje, zo op het
    scherm. Nu: geen sterretjes of codetekens, opsommingstekens aan het begin
    van een regel weg, en een gedachtestreepje wordt een komma."""
    t = tekst or ""
    t = re.sub(r"\*\*|__|`", "", t)
    t = re.sub(r"(?<!\w)\*(?=\S)|(?<=\S)\*(?!\w)", "", t)
    t = re.sub(r"(?m)^\s*(#+|[-*\u2022]|\d+[.)])\s+", "", t)
    t = re.sub(r"\s*[\u2013\u2014]\s*", ", ", t)
    # 2 oktober (Nino, Partywinkel.nl): een tabel in het antwoord stond er als
    # "| Waar | Vaak het goedkoopst voor | |---|---|". Scheidingsregels weg, en
    # elke rij wordt een gewone zin: cellen met een komma, de rij met een punt.
    sep = r"[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(?:\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t]*"
    # De kopregel (vlak boven de scheidingsregel) en de scheidingsregel samen weg.
    t = re.sub(r"(?m)^[ \t]*\|[^\n]*\|[ \t]*\n" + sep + r"$", "", t)
    t = re.sub(r"(?m)^" + sep + r"$", "", t)

    def _rij(m):
        cellen = [c.strip() for c in m.group(0).strip().strip("|").split("|") if c.strip()]
        return ", ".join(cellen) + "." if cellen else ""
    t = re.sub(r"(?m)^[ \t]*\|[^\n]*\|[ \t]*$", _rij, t)
    t = re.sub(r"\s*\|\s*", ", ", t)
    return t


def _fragment(tekst, webshop_url, winkelnaam=None, lengte=260):
    """De zin uit het antwoord waarin de winkel staat, anders het begin.

    Dit is het bewijs: de klant ziet wat de assistent echt zei."""
    tekst = zonder_opmaak(tekst)
    tekst = re.sub(r"\s+", " ", (tekst or "")).strip()
    if not tekst:
        return ""
    stam = (webshop_url or "").lower().replace("https://", "").replace("http://", "")
    stam = stam.replace("www.", "").split("/")[0].split(".")[0]
    sleutels = [s for s in {stam, (winkelnaam or "").lower().split(".")[0]} if len(s) >= 3]
    zinnen = re.split(r"(?<=[.!?])\s+", tekst)
    for zin in zinnen:
        laag = zin.lower()
        if any(s in laag for s in sleutels):
            return (zin[:lengte] + "...") if len(zin) > lengte else zin
    return (tekst[:lengte] + "...") if len(tekst) > lengte else tekst


def vragen_overzicht(ronde, webshop_url, winkelnaam=None, antwoorden=None):
    """Elke koopvraag van de ronde: per assistent genoemd of niet, wie wel, en
    het stukje uit het echte antwoord.

    Geeft {"vragen": [...], "gewonnen": n, "verloren": n, "totaal": n,
    "per_assistent": [{"naam", "genoemd", "van"}]} terug."""
    rijen = antwoorden if antwoorden is not None else db.antwoorden_met_tekst_van_ronde(ronde)
    per_vraag, volgorde = {}, []
    per_assistent = {}
    for rij in rijen:
        g = _genoemde(rij)
        if not g.get("winkel_kon_genoemd", rij.get("winkel_kon_genoemd", True)):
            continue
        vraag = rij.get("vraag")
        if vraag not in per_vraag:
            per_vraag[vraag] = {"vraag": vraag, "per_model": []}
            volgorde.append(vraag)
        winkels = g.get("winkels") or []
        namen = [w.get("naam") for w in winkels if w.get("naam")]
        genoemd = any(scan_engine.is_eigen_winkel(webshop_url, n) for n in namen)
        aanbevolen = any(scan_engine.is_eigen_winkel(webshop_url, n)
                         for n in (g.get("aanbevolen") or []))
        anderen = [w.get("naam") for w in winkels
                   if w.get("naam") and (w.get("soort") or "winkel") != "platform"
                   and not scan_engine.is_eigen_winkel(webshop_url, w.get("naam"))][:5]
        naam = assistent_naam(rij.get("model"))
        per_vraag[vraag]["per_model"].append({
            "assistent": naam, "genoemd": genoemd, "aanbevolen": aanbevolen,
            "anderen": anderen,
            "fragment": _fragment(rij.get("antwoord"), webshop_url, winkelnaam),
        })
        stand = per_assistent.setdefault(naam, {"naam": naam, "genoemd": 0, "van": 0})
        stand["van"] += 1
        stand["genoemd"] += 1 if genoemd else 0
    vragen = []
    for v in volgorde:
        item = per_vraag[v]
        item["gewonnen"] = any(m["genoemd"] for m in item["per_model"])
        item["aanbevolen"] = any(m["aanbevolen"] for m in item["per_model"])
        # Stap 193: het label (prijs, service, ...) voor het filter op de vragenpagina.
        item["label"] = vraaglabels.label(v)
        vragen.append(item)
    # Verloren eerst: daar valt iets te winnen.
    vragen.sort(key=lambda x: (x["gewonnen"], x["aanbevolen"]))
    gewonnen = sum(1 for v in vragen if v["gewonnen"])
    return {"vragen": vragen, "gewonnen": gewonnen, "verloren": len(vragen) - gewonnen,
            "totaal": len(vragen), "labels": vraaglabels.telling(vragen), "per_assistent": sorted(per_assistent.values(),
                                                           key=lambda a: a["naam"])}


def open_plekken(vragen_overzicht, maximaal=5, hooguit=2):
    """Koopvragen die je verliest maar waar AI weinig winkels noemt (1 oktober).

    Drie voorstellen van de agents (een "zoekvragenonderzoeker", "veelgestelde
    koopvragen per categorie") kwamen op hetzelfde neer: laat zien over welke
    vragen een winkel moet schrijven. Wat wij echt weten: de koopvragen van de
    categorie (gemaakt zoals kopers ze stellen) en hoeveel winkels AI per vraag
    noemt. Een vraag waar AI geen of maar een of twee winkels noemt is het
    makkelijkst te winnen: daar is nog weinig concurrentie.
    Wat wij NIET hebben en dus niet tonen: hoe vaak een vraag gesteld wordt
    (zoekvolumes). Daar is voor AI-assistenten geen betrouwbare bron voor."""
    uit = []
    for v in (vragen_overzicht or {}).get("vragen", []):
        if v.get("gewonnen"):
            continue
        namen = []
        for m in v.get("per_model") or []:
            for n in m.get("anderen") or []:
                if n not in namen:
                    namen.append(n)
        if len(namen) <= hooguit:
            uit.append({"vraag": v["vraag"], "aantal": len(namen), "namen": namen})
    uit.sort(key=lambda x: x["aantal"])
    return uit[:maximaal]


def buren_verloop(beeld, maximaal=3):
    """Het verloop van de winkel zelf en van de winkels vlak boven hem."""
    if not beeld:
        return []
    reeksen = [{"naam": beeld.get("naam") or beeld["webshop_url"], "jij": True,
                "punten": [(r.get("afgerond_op"), r["positie"]) for r in beeld.get("verloop") or []]}]
    for b in (beeld.get("achter_mij") if beeld.get("boven_is_achter") else beeld.get("boven_mij") or [])[-maximaal:]:
        try:
            verloop = db.positieverloop(b["webshop_url"], beeld["categorie"], beeld.get("land"))
        except Exception:
            verloop = []
        reeksen.append({"naam": b.get("naam") or b["webshop_url"].replace("https://", ""),
                        "jij": False,
                        "punten": [(r.get("afgerond_op"), r["positie"]) for r in verloop]})
    return reeksen


# Kleuren van de grafiek: de winkel zelf in het blauw van Krillo, de rest grijs
# in drie tinten. Nooit rood/groen voor concurrenten: dat leest als goed/fout.
KLEUR_JIJ = "#1B3FE0"
KLEUREN_ANDEREN = ("#9C9AA6", "#C4C2CC", "#6E6E7A")


def lijngrafiek(reeksen, breedte=720, hoogte=240, taal="en"):
    """Een lijngrafiek van de plek per meting, met nummer 1 BOVENAAN.

    reeksen: [{"naam", "jij", "punten": [(datum, positie), ...]}]. Alle reeksen
    delen dezelfde metingen (x-as) op volgorde van datum."""
    datums = sorted({d for r in reeksen for d, _ in r["punten"] if d is not None})
    if len(datums) < 2:
        return Markup("")
    posities = [p for r in reeksen for _, p in r["punten"] if p]
    beste, slechtste = max(1, min(posities) - 1), max(posities) + 1
    links, rechts, boven, onder = 44, 16, 16, 34
    bw, bh = breedte - links - rechts, hoogte - boven - onder

    def x(d):
        return links + bw * datums.index(d) / (len(datums) - 1)

    def y(p):
        return boven + bh * (p - beste) / max(1, (slechtste - beste))

    delen = [f'<svg viewBox="0 0 {breedte} {hoogte}" width="100%" role="img" '
             f'aria-label="{escape("Position per measurement" if taal == "en" else "Plek per meting")}" '
             'style="display:block; overflow:visible;">']
    # Hulplijnen met de plek erbij, hooguit vijf.
    stap = max(1, round((slechtste - beste) / 4))
    for p in range(beste, slechtste + 1, stap):
        delen.append(f'<line x1="{links}" x2="{breedte - rechts}" y1="{y(p):.1f}" y2="{y(p):.1f}" '
                     'stroke="#ECECF0" stroke-width="1"/>')
        delen.append(f'<text x="{links - 10}" y="{y(p) + 4:.1f}" text-anchor="end" '
                     f'font-family="IBM Plex Mono, monospace" font-size="11" fill="#9C9AA6">#{p}</text>')
    for d in datums:
        # De dag erbij: zes metingen in een maand gaven anders zes keer "Sep".
        label = d.strftime("%d %b") if hasattr(d, "strftime") else str(d)
        delen.append(f'<text x="{x(d):.1f}" y="{hoogte - 10}" text-anchor="middle" '
                     f'font-family="IBM Plex Mono, monospace" font-size="11" fill="#9C9AA6">{escape(label)}</text>')
    # Eerst de anderen, dan de winkel zelf erboven.
    anderen = [r for r in reeksen if not r.get("jij")]
    for i, r in enumerate(anderen + [r for r in reeksen if r.get("jij")]):
        punten = [(x(d), y(p)) for d, p in r["punten"] if d in datums and p]
        if not punten:
            continue
        kleur = KLEUR_JIJ if r.get("jij") else KLEUREN_ANDEREN[i % len(KLEUREN_ANDEREN)]
        dik = 3 if r.get("jij") else 1.6
        pad = " ".join(f"{'M' if j == 0 else 'L'}{px:.1f},{py:.1f}" for j, (px, py) in enumerate(punten))
        delen.append(f'<path d="{pad}" fill="none" stroke="{kleur}" stroke-width="{dik}" '
                     'stroke-linejoin="round" stroke-linecap="round"/>')
        for px, py in punten:
            delen.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{4 if r.get("jij") else 3}" '
                         f'fill="#fff" stroke="{kleur}" stroke-width="2"/>')
    delen.append("</svg>")
    return Markup("".join(delen))


def balken_per_assistent(per_assistent):
    """Per assistent een balk: in hoeveel van zijn antwoorden sta je. HTML, geen SVG,
    zodat de tekst op elk scherm scherp en leesbaar blijft."""
    if not per_assistent:
        return Markup("")
    delen = []
    for a in per_assistent:
        deel = (a["genoemd"] / a["van"]) if a["van"] else 0
        delen.append(
            '<div class="assbalk"><div class="assnaam">' + str(escape(a["naam"])) + '</div>'
            '<div class="assbak"><div class="assvul" style="width:' + f"{max(2, round(deel * 100))}" + '%;"></div></div>'
            '<div class="asscijfer">' + f'{a["genoemd"]} / {a["van"]}' + '</div></div>')
    return Markup("".join(delen))


def volgende_stap(beeld, werkblok, taal="en"):
    """Een regel bovenaan: wat is nu het belangrijkste voor deze klant.

    Concurrenten laten tien cijfers zien; een webshophouder wil weten wat er
    nu speelt. Een zin, geen dashboard-taal."""
    en = taal != "nl"
    if werkblok:
        u = werkblok.get("uitvoering")
        if werkblok.get("afgelopen"):
            return ("Your plan has ended. Your earlier results stay here." if en else
                    "Je abonnement is afgelopen. Je eerdere uitkomsten blijven hier staan.")
        if u and u.get("stand") == "wacht_op_toegang" and not werkblok.get("shopify_winkel"):
            return ("Next step: give us access to your store, so we can start. See Fixes."
                    if en else "Volgende stap: geef ons toegang tot je winkel, dan beginnen we. Zie Verbeteringen.")
        wijz = werkblok.get("wijzigingen") or []
        if wijz and werkblok.get("doet_werk"):
            return (f"We changed {len(wijz)} thing{'s' if len(wijz) != 1 else ''} in your store. See Fixes."
                    if en else f"We veranderden {len(wijz)} dingen in je winkel. Zie Verbeteringen.")
        acties = ((werkblok.get("actieplan") or {}).get("acties") or [])
        if acties and not werkblok.get("doet_werk"):
            return (f"{len(acties)} fixes are ready for you to put in. See Fixes." if en else
                    f"{len(acties)} verbeteringen staan klaar om in te zetten. Zie Verbeteringen.")
    if beeld and beeld.get("verschil"):
        v = beeld["verschil"]
        if v > 0:
            return (f"You moved up {v} place{'s' if v != 1 else ''} since the last measurement."
                    if en else f"Je steeg {v} plaats(en) sinds de vorige meting.")
        return (f"You dropped {-v} place{'s' if v != -1 else ''}. See Questions for where you lose."
                if en else f"Je zakte {-v} plaats(en). Bij Vragen zie je waar je verliest.")
    return ""


# 29 september: de kaart "Ranglijst" op het overzicht. De top 5 en, als je daar
# niet bij zit, een puntjesregel en jouw eigen regel. Zichtbaarheid is in hoeveel
# van de koopvragen een winkel genoemd werd, in procenten.
KLEUREN_TOP = ["#E0782B", "#7A8BD9", "#C9A227", "#5FA88E", "#D98BA8"]


def topkaart(rijen, eigen_url, telbaar, aantal=5):
    def regel(r, i):
        jij = r.get("webshop_url") == eigen_url
        naam = r.get("naam")
        if not naam or str(naam).startswith("http"):
            naam = (r.get("webshop_url") or "").replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
        vorige, nu = r.get("vorige_positie"), r.get("positie")
        # Versie 8: de beweging sinds de vorige meting, net als op /index.
        beweging = ("" if not vorige or not nu else
                    (f"▲{vorige - nu}" if vorige > nu else (f"▼{nu - vorige}" if nu > vorige else "=")))
        return {"positie": r.get("positie"), "naam": naam, "jij": jij, "beweging": beweging,
                "zicht": int(round(100 * (r.get("genoemd") or 0) / telbaar)) if telbaar else 0,
                "kleur": KLEUR_JIJ if jij else KLEUREN_TOP[i % len(KLEUREN_TOP)], "gat": False}
    uit = [regel(r, i) for i, r in enumerate(rijen[:aantal])]
    if not any(u["jij"] for u in uit):
        eigen = next((r for r in rijen if r.get("webshop_url") == eigen_url), None)
        if eigen:
            e = regel(eigen, 0)
            e["gat"] = True
            uit.append(e)
    return uit


# ---------------------------------------------------------------------------
# DASHBOARD VERSIE 8 (30 september). De grafiek op het overzicht wordt in de
# browser getekend, zodat je met de tegels kan wisselen tussen plek,
# zichtbaarheid en aangeraden, en op een meting kan klikken. Daarvoor gaan de
# echte meetpunten als gegevens mee in plaats van als kant-en-klaar plaatje.
# ---------------------------------------------------------------------------
GRAFIEK_KLEUREN = ("#0A0A0B", "#6E7079", "#A9AAB2")


def _punt(r):
    telbaar = r.get("telbaar") or 0
    d = r.get("afgerond_op")
    return {"d": d.strftime("%d %b").upper() if d else "",
            "positie": r.get("positie"),
            "zicht": int(round(100 * (r.get("genoemd") or 0) / telbaar)) if telbaar else 0,
            "aanbevolen": r.get("aanbevolen") or 0}


def grafiek_reeksen(beeld, maximaal=3):
    """Jij en de winkels vlak boven je, met per meting plek, zichtbaarheid en
    aangeraden. De x-as is die van de winkel zelf: een buur die in een ronde
    ontbrak krijgt daar een gat (None) in plaats van een verzonnen punt.

    Geeft [] terug bij minder dan twee metingen: een lijn van een punt zegt
    niets, en het scherm zegt dan eerlijk dat de lijn na de volgende meting komt."""
    if not beeld:
        return []
    eigen = beeld.get("verloop") or []
    if len(eigen) < 2:
        return []
    datums = [r.get("afgerond_op") for r in eigen]
    reeksen = [{"naam": beeld.get("naam") or beeld["webshop_url"].replace("https://", ""),
                "kleur": KLEUR_JIJ, "jij": True, "punten": [_punt(r) for r in eigen]}]
    # 2 oktober: op 1 staat niemand boven je; dan de winkels vlak achter je.
    lijst = beeld.get("achter_mij") if beeld.get("boven_is_achter") else beeld.get("boven_mij")
    for i, b in enumerate((lijst or [])[-maximaal:]):
        try:
            verloop = db.positieverloop(b["webshop_url"], beeld["categorie"], beeld.get("land"))
        except Exception:
            verloop = []
        per_datum = {r.get("afgerond_op"): r for r in verloop}
        reeksen.append({"naam": b.get("naam") or b["webshop_url"].replace("https://", ""),
                        "kleur": GRAFIEK_KLEUREN[i % len(GRAFIEK_KLEUREN)], "jij": False,
                        "punten": [(_punt(per_datum[d]) if d in per_datum else None) for d in datums]})
    return reeksen


def vonkje(verloop, sleutel, breedte=200, hoogte=26):
    """De punten van een klein lijntje in een tegel (sparkline). Bij de plek
    staat nummer 1 bovenaan, bij de rest is hoger beter."""
    waarden = [_punt(r)[sleutel] for r in (verloop or [])]
    waarden = [w for w in waarden if w is not None]
    if len(waarden) < 2:
        return ""
    laag, hoog = min(waarden), max(waarden)
    bereik = (hoog - laag) or 1
    uit = []
    for i, w in enumerate(waarden):
        x = round(i * breedte / (len(waarden) - 1), 1)
        deel = (w - laag) / bereik
        y = round(3 + (deel if sleutel == "positie" else 1 - deel) * (hoogte - 6), 1)
        uit.append(f"{x},{y}")
    return " ".join(uit)
