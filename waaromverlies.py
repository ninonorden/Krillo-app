"""De pagina "Why you lose": per verloren koopvraag wat AI zei, wie won, en waarom (8 oktober 2026, stap 335).

WAAROM DIT BESTAAT

Het overzicht zei al WELKE vragen een winkel verliest en aan wie. Het bord
Diagnose.dc.html van Nino wil daar een stap achter: kijk naast de pagina van de
winnaar en zie wat die heeft en jij niet. Zonder die stap blijft "je verliest"
een uitspraak waar een winkelier niets mee kan.

WAT WE ECHT WETEN, EN DUS ALLEEN TONEN
- de vraag, en het echte antwoord per assistent (bewaard bij de meting);
- welke winkels in dat antwoord genoemd werden en wie de winnaar is;
- de sites die AI in de antwoorden op DEZE vraag noemt (bronnenkaart);
- de dertien sitechecks van de winnaar naast die van de klant. Een reden is
  alleen: een check waar de winnaar slaagt en de klant niet.
- "geen pagina over deze vraag": alleen als de wekelijkse paginacheck draaide
  en geen pagina van de winkel bij het onderwerp vond.
WAT WE NIET WETEN: of de klant op de review- of vergelijksites staat die AI
noemt. Dat tonen we dus als lijst om na te lopen, nooit als reden. Ook geen
verzonnen redenen als de site van de winnaar niet te lezen is: dan staat er
dat, en geen gok.

DE SCAN VAN DE WINNAAR (run_scan, dertien checks) duurt seconden en haalt
andermans website op. Daarom NIET tijdens het opbouwen van de pagina, maar in
een aparte JSON-route die de pagina met fetch aanroept. Het resultaat blijft
zeven dagen bewaard (instelling 'scancache:'+url), zodat een winnaar die voor
tien vragen wint maar een keer bezocht wordt.
"""
import json
import re
import threading
import time
from collections import Counter

from markupsafe import Markup, escape

import db
import scan_engine

CACHE_DAGEN = 7
FOUT_UREN = 1        # een mislukte scan niet meteen opnieuw: de site van een ander hoeven we niet te bestoken
SCAN_TIMEOUT = 40    # seconden wachten in een verzoek; daarna "probeer zo opnieuw"
PREFIX = "scancache:"
FOUTPREFIX = "scanfout:"

# De scan draait in een aparte draad. Twee klanten die dezelfde winnaar
# bekijken wachten op dezelfde scan in plaats van twee keer te scannen.
_bezig = {}
_slot = threading.Lock()

CATEGORIE_EN = {"toegang": "Access", "leesbaarheid": "Readability", "structuur": "Structure", "inhoud": "Content"}
CATEGORIE_NL = {"toegang": "Toegang", "leesbaarheid": "Leesbaarheid", "structuur": "Structuur", "inhoud": "Inhoud"}
IMPACT_VOLGORDE = {"hoog": 0, "middel": 1, "midden": 1, "laag": 2}
GESLAAGD = ("ok", "goed")


# ---------------------------------------------------------------------------
# De vraag en de winnaar
# ---------------------------------------------------------------------------
def verloren_vragen(vragen_overzicht):
    return [v for v in (vragen_overzicht or {}).get("vragen", []) if not v.get("gewonnen")]


def kies_vraag(vragen_overzicht, gewenst=None, eigen=None):
    """De vraag voor de pagina: ?vraag= als die bestaat, anders de eerste verloren vraag.

    eigen: de eigen vragen van de klant (eigenvragen.overzicht). Een eigen vraag
    heeft geen bewaarde antwoordtekst, maar wel wie er genoemd werd; daarom
    bouwen we hem om tot dezelfde vorm als een gewone vraag."""
    vragen = (vragen_overzicht or {}).get("vragen", [])
    gewenst = (gewenst or "").strip()
    if gewenst:
        for v in vragen:
            if v["vraag"] == gewenst:
                return v
        for e in eigen or []:
            if e["vraag"] == gewenst:
                return eigen_als_vraag(e)
    verloren = verloren_vragen(vragen_overzicht)
    if verloren:
        return verloren[0]
    return vragen[0] if vragen else None


def eigen_als_vraag(e):
    """Een eigen vraag in de vorm van vragen_overzicht()["vragen"][n]."""
    per_model = []
    for a in e.get("assistenten") or []:
        per_model.append({"assistent": a.get("naam"), "genoemd": bool(a.get("genoemd")), "aanbevolen": False,
                          "anderen": list(a.get("anderen") or [])[:5], "fragment": ""})
    return {"vraag": e["vraag"], "per_model": per_model, "eigen": True, "eigen_id": e.get("id"),
            "gewonnen": any(m["genoemd"] for m in per_model), "aanbevolen": False,
            "gemeten": bool(per_model)}


def alle_anderen(v):
    """Alle andere winkels die bij deze vraag genoemd werden, in volgorde van verschijnen."""
    namen = []
    for m in v.get("per_model") or []:
        for n in m.get("anderen") or []:
            if n not in namen:
                namen.append(n)
    return namen


def winnaar_naam(v):
    """De winkel die AI het vaakst noemt in plaats van de klant (bij gelijke stand: de eerste)."""
    telling, eerste = Counter(), {}
    for m in v.get("per_model") or []:
        for i, n in enumerate(m.get("anderen") or []):
            telling[n] += 1
            eerste.setdefault(n, (len(eerste), i))
    if not telling:
        return None
    return sorted(telling, key=lambda n: (-telling[n], eerste[n]))[0]


def _kern(tekst):
    t = (tekst or "").lower().replace("https://", "").replace("http://", "").replace("www.", "")
    return re.sub(r"[^a-z0-9]", "", t.split("/")[0].rsplit(".", 1)[0] if "." in t.split("/")[0] else t)


def winnaar_url(naam, ranglijst_rijen):
    """Het webadres van de winnaar. Eerst de ranglijst van de categorie (daar staan
    naam en adres naast elkaar), anders een naam die zelf een domein is. Anders
    None: dan zeggen we dat we de site niet konden vinden, we raden niet."""
    if not naam:
        return None
    for r in ranglijst_rijen or []:
        url = r.get("webshop_url")
        if not url:
            continue
        if scan_engine.is_eigen_winkel(url, naam) or _kern(r.get("naam")) == _kern(naam) != "":
            return url
    schoon = naam.strip().lower()
    if re.fullmatch(r"(https?://)?(www\.)?[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}(/.*)?", schoon):
        return scan_engine.normalize_url(schoon)
    return None


# ---------------------------------------------------------------------------
# Het antwoord per assistent, met de winkels gemarkeerd
# ---------------------------------------------------------------------------
def markeer_html(tekst, eigen_naam, anderen):
    """De tekst veilig als HTML, met de winkelnamen in <mark>. De klant krijgt
    class="jij" (blauw), de rest grijs. Eerst escapen, dan markeren: een naam met
    een < erin kan zo nooit opmaak worden."""
    html = str(escape(tekst or ""))
    namen = [(eigen_naam, True)] if eigen_naam else []
    namen += [(a, False) for a in anderen or []]
    for naam, jij in sorted(namen, key=lambda x: -len(x[0] or "")):
        if not naam or len(naam) < 3:
            continue
        patroon = re.compile(re.escape(str(escape(naam))), re.I)
        html = patroon.sub(lambda m: f'<mark class="{"jij" if jij else ""}">{m.group(0)}</mark>', html)
    return Markup(html)


def antwoorden_per_assistent(v, antwoord_rijen, winkelnaam, assistent_naam, opschonen, lengte=1100):
    """Per assistent: de volledige antwoordtekst (opgeschoond, hooguit `lengte` tekens)
    en wie er genoemd werd. Valt terug op het bewaarde fragment als de volledige
    tekst er niet (meer) is."""
    per_assistent = {}
    for r in antwoord_rijen or []:
        if r.get("vraag") == v["vraag"]:
            per_assistent.setdefault(assistent_naam(r.get("model")), r.get("antwoord") or "")
    uit = []
    for m in v.get("per_model") or []:
        tekst = opschonen(per_assistent.get(m["assistent"]) or "")
        tekst = re.sub(r"\s*\n\s*", " ", tekst).strip()
        if len(tekst) > lengte:
            tekst = tekst[:lengte].rsplit(" ", 1)[0] + "..."
        if not tekst:
            tekst = m.get("fragment") or ""
        uit.append({"assistent": m["assistent"], "genoemd": m["genoemd"], "aanbevolen": m.get("aanbevolen"),
                    "anderen": m.get("anderen") or [], "tekst": tekst,
                    "html": markeer_html(tekst, winkelnaam if m["genoemd"] else None, m.get("anderen"))})
    return uit


def bronnen_voor_vraag(antwoord_rijen, vraag, maximaal=5):
    """De sites die AI in de antwoorden op deze vraag noemt (review-, vergelijk-, community-
    en marktplaatssites). Lijst om na te lopen: we weten niet of de klant er staat."""
    import bronnenkaart
    rijen = [r for r in antwoord_rijen or [] if r.get("vraag") == vraag]
    return bronnenkaart.bronnen(rijen, maximaal=maximaal) if rijen else []


# ---------------------------------------------------------------------------
# De scan van de winnaar, met zeven dagen geheugen
# ---------------------------------------------------------------------------
def _schone_url(url):
    return scan_engine.normalize_url(url).rstrip("/").lower()


def lees_cache(url, nu=None):
    """{"op", "score", "checks"} of None. Ouder dan zeven dagen telt niet."""
    nu = nu or time.time()
    try:
        ruw = db.get_instelling(PREFIX + _schone_url(url))
        if not ruw:
            return None
        d = json.loads(ruw)
        if nu - float(d.get("op") or 0) > CACHE_DAGEN * 86400 or not d.get("checks"):
            return None
        return d
    except Exception:
        return None


def _lees_fout(url, nu=None):
    nu = nu or time.time()
    try:
        ruw = db.get_instelling(FOUTPREFIX + _schone_url(url))
        d = json.loads(ruw) if ruw else None
        if d and nu - float(d.get("op") or 0) < FOUT_UREN * 3600:
            return d
    except Exception:
        pass
    return None


def _bewaar_cache(url, uitkomst, nu=None):
    d = {"op": nu or time.time(), "score": uitkomst.get("score"), "checks": uitkomst.get("checks") or []}
    db.zet_instelling(PREFIX + _schone_url(url), json.dumps(d))
    return d


def _scan_en_bewaar(url, resultaat):
    """In een eigen draad: scan, en bewaar het resultaat ook als de wachtende
    aanvraag al opgaf. De volgende keer staat het dan klaar."""
    try:
        uit = scan_engine.run_scan(url)
        if not isinstance(uit, dict) or uit.get("error") or not uit.get("checks"):
            fout = (uit or {}).get("error") if isinstance(uit, dict) else None
            resultaat["fout"] = fout or "We could not read this website."
            try:
                db.zet_instelling(FOUTPREFIX + _schone_url(url), json.dumps({"op": time.time(), "fout": resultaat["fout"]}))
            except Exception:
                pass
        else:
            resultaat["cache"] = _bewaar_cache(url, uit)
    except Exception as e:
        resultaat["fout"] = f"Scan failed: {e}"
    finally:
        resultaat["klaar"] = True
        with _slot:
            _bezig.pop(_schone_url(url), None)


def scan_winnaar(url, timeout=SCAN_TIMEOUT, nu=None):
    """De checks van de winnaar. Geeft:
      {"ok": True, "checks", "score", "op", "uit_cache": bool}
      {"ok": False, "fout": tekst, "soort": "niet_leesbaar" | "te_traag"}
    Nooit een uitzondering: de pagina moet altijd een nette uitleg kunnen tonen."""
    gecached = lees_cache(url, nu=nu)
    if gecached:
        return {"ok": True, "checks": gecached["checks"], "score": gecached.get("score"),
                "op": gecached["op"], "uit_cache": True}
    eerder = _lees_fout(url, nu=nu)
    if eerder:
        return {"ok": False, "soort": "niet_leesbaar", "fout": eerder.get("fout") or "We could not read this website."}
    sleutel = _schone_url(url)
    with _slot:
        resultaat = _bezig.get(sleutel)
        if resultaat is None:
            resultaat = {"klaar": False}
            _bezig[sleutel] = resultaat
            threading.Thread(target=_scan_en_bewaar, args=(url, resultaat), daemon=True).start()
    einde = time.time() + timeout
    while not resultaat.get("klaar") and time.time() < einde:
        time.sleep(0.05)
    if not resultaat.get("klaar"):
        return {"ok": False, "soort": "te_traag",
                "fout": "Their website is slow to read. Try again in a minute; the result is kept once it is done."}
    if resultaat.get("cache"):
        c = resultaat["cache"]
        return {"ok": True, "checks": c["checks"], "score": c.get("score"), "op": c["op"], "uit_cache": False}
    return {"ok": False, "soort": "niet_leesbaar", "fout": resultaat.get("fout") or "We could not read this website."}


# ---------------------------------------------------------------------------
# Het laatste sitecheck-rapport van de klant (zoals app._sitecheck het haalt)
# ---------------------------------------------------------------------------
def klant_checks(klant_token):
    """{"checks", "score", "op"} uit het laatste rapport van de klant, of None."""
    try:
        rapporten = db.get_klant_rapporten(klant_token, limit=1) or []
    except Exception:
        return None
    if not rapporten:
        return None
    r = rapporten[0]
    checks = r.get("checks") or []
    if isinstance(checks, str):
        try:
            checks = json.loads(checks)
        except Exception:
            checks = []
    if not checks:
        return None
    return {"checks": checks, "score": r.get("score"), "op": r.get("aangemaakt_op")}


def _in_taal(checks, taal):
    if taal == "nl":
        return checks
    import checktaal
    return checktaal.naar_het_engels({"checks": checks})["checks"]


# ---------------------------------------------------------------------------
# De vergelijking en de redenen
# ---------------------------------------------------------------------------
def vergelijk(winnaar_checks, eigen_checks, taal="en"):
    """Rijen voor "Their page next to yours", op volgorde van de checks van de klant.

    verschil:
      "jij_mist"   winnaar slaagt, jij niet  (dit is een reden)
      "beide_ok"   beiden slagen
      "beide_niet" geen van beiden slaagt (geen reden: de winnaar heeft het ook niet)
      "jij_beter"  jij slaagt, de winnaar niet
      "onbekend"   een van de twee kon niet gemeten worden"""
    w = {c.get("id"): c for c in _in_taal(winnaar_checks or [], taal)}
    namen = CATEGORIE_NL if taal == "nl" else CATEGORIE_EN
    rijen = []
    for c in _in_taal(eigen_checks or [], taal):
        cw = w.get(c.get("id"))
        if cw is None:
            continue
        sw, sk = cw.get("status"), c.get("status")
        if "onbekend" in (sw, sk):
            verschil = "onbekend"
        elif sw in GESLAAGD and sk not in GESLAAGD:
            verschil = "jij_mist"
        elif sw in GESLAAGD and sk in GESLAAGD:
            verschil = "beide_ok"
        elif sw not in GESLAAGD and sk in GESLAAGD:
            verschil = "jij_beter"
        else:
            verschil = "beide_niet"
        rijen.append({"id": c.get("id"), "titel": c.get("titel"), "categorie": namen.get(c.get("categorie"), c.get("categorie")),
                      "impact": c.get("impact"), "winnaar": sw, "jij": sk, "verschil": verschil,
                      "uitleg_jij": c.get("uitleg") if verschil == "jij_mist" else ""})
    return rijen


def paginareden(onderwerp, paginacheck_paginas, pagina_gevonden):
    """Alleen als de wekelijkse paginacheck draaide (er zijn pagina's gelezen) en
    daar geen pagina bij het onderwerp zat. Anders None: dan weten we het niet."""
    if paginacheck_paginas and not pagina_gevonden:
        return onderwerp
    return None


def redenen(rijen, winnaar, onderwerp=None, pagina_ontbreekt=False, taal="en"):
    """De redenen, belangrijkste eerst. Alleen wat we echt zien."""
    nl = taal == "nl"
    uit = []
    if pagina_ontbreekt and onderwerp:
        uit.append({"soort": "Content" if not nl else "Inhoud", "bron": "paginacheck",
                    "tekst": (f"De wekelijkse paginacheck vond geen pagina van je winkel over “{onderwerp}”."
                              if nl else f"The weekly page check found no page of your store about “{onderwerp}”.")})
    mist = [r for r in rijen if r["verschil"] == "jij_mist"]
    mist.sort(key=lambda r: IMPACT_VOLGORDE.get((r.get("impact") or "").lower(), 1))
    for r in mist:
        uit.append({"soort": r["categorie"], "bron": "check", "id": r["id"],
                    "tekst": (f"{winnaar} slaagt voor “{r['titel']}”, jij niet." if nl
                              else f"{winnaar} passes “{r['titel']}” and you do not.")})
    return uit


def tel_redenen_uit_cache(winnaar_naam_, ranglijst_rijen, eigen_checks, taal="en", pagina_ontbreekt=False):
    """Voor de doelkaart: hoeveel redenen, maar ALLEEN als de scan van de winnaar al
    bewaard is. Nooit een scan starten bij het opbouwen van een pagina.
    None als dat niet zo is."""
    url = winnaar_url(winnaar_naam_, ranglijst_rijen)
    if not url or not eigen_checks:
        return None
    c = lees_cache(url)
    if not c:
        return None
    rijen = vergelijk(c["checks"], eigen_checks, taal)
    return len(redenen(rijen, winnaar_naam_, onderwerp="x" if pagina_ontbreekt else None,
                       pagina_ontbreekt=pagina_ontbreekt, taal=taal))


def _fout_zin(naam, soort, ruw, taal):
    nl = taal == "nl"
    ruw = ruw or ""
    if soort == "te_traag":
        return (f"De website van {naam} reageert traag. Probeer het over een minuut opnieuw; het resultaat blijft bewaard zodra het klaar is."
                if nl else f"The website of {naam} is slow to read. Try again in a minute; the result is kept once it is done.")
    if ruw.startswith("Deze winkel staat achter een wachtwoord"):
        return (f"{naam} staat achter een wachtwoord, dus we kunnen de pagina niet lezen. AI ook niet."
                if nl else f"{naam} is behind a password, so we cannot read the page.")
    if ruw.startswith(("Deze website weigerde", "Deze website gaf ons geen antwoord", "Deze website stuurde")):
        return (f"De website van {naam} liet ons niet binnen, dus er is niets om te vergelijken."
                if nl else f"The website of {naam} did not let us in, so there is nothing to compare.")
    return (f"We konden de website van {naam} niet lezen, dus we vergelijken niet."
            if nl else f"We could not read the website of {naam}, so we do not compare.")


def vergelijking_json(v, ranglijst_rijen, eigen, taal="en", onderwerp=None, pagina_ontbreekt=False, timeout=SCAN_TIMEOUT):
    """Het antwoord van de JSON-route /mijn/<token>/waarom/vergelijk.

    v: de vraag (vorm van vragen_overzicht). eigen: klant_checks(). Geeft altijd
    een dict met "ok"; bij een fout een "fout" die de pagina zo kan tonen."""
    naam = winnaar_naam(v)
    if not naam:
        return {"ok": False, "soort": "geen_winnaar",
                "fout": ("Geen winkel genoemd bij deze vraag, dus er is geen pagina om naast de jouwe te leggen." if taal == "nl"
                         else "No store is named for this question, so there is no page to put next to yours.")}
    if not eigen:
        return {"ok": False, "soort": "geen_eigen_check", "winnaar": naam,
                "fout": ("Je eigen sitecheck is er nog niet. Zodra die klaar is, staat de vergelijking hier." if taal == "nl"
                         else "Your own site check is not ready yet. As soon as it is, the comparison shows here.")}
    url = winnaar_url(naam, ranglijst_rijen)
    if not url:
        return {"ok": False, "soort": "geen_adres", "winnaar": naam,
                "fout": (f"We konden het webadres van {naam} niet vinden, dus we vergelijken niet." if taal == "nl"
                         else f"We could not find the web address of {naam}, so we do not compare.")}
    scan = scan_winnaar(url, timeout=timeout)
    if not scan["ok"]:
        # De meldingen van de scan zijn geschreven voor een klant ("je winkel"),
        # en hier gaat het om de site van een ander. Daarom eigen zinnen.
        return {"ok": False, "soort": scan["soort"], "winnaar": naam, "winnaar_url": url,
                "fout": _fout_zin(naam, scan["soort"], scan.get("fout"), taal)}
    rijen = vergelijk(scan["checks"], eigen["checks"], taal)
    reden = redenen(rijen, naam, onderwerp=onderwerp, pagina_ontbreekt=pagina_ontbreekt, taal=taal)
    return {"ok": True, "winnaar": naam, "winnaar_url": url, "score_winnaar": scan.get("score"),
            "score_jij": eigen.get("score"), "uit_cache": scan["uit_cache"], "rijen": rijen, "redenen": reden}


# ---------------------------------------------------------------------------
# Wat je eraan doet: de bestaande aanpak per vraag, met een status
# ---------------------------------------------------------------------------
def acties(v, gekozen, landnaam=None, en=True):
    """De drie stappen van vraagaanpak voor deze vraag, met status:
    Won (de vraag is gewonnen), On your list (de klant koos hem), Suggested.
    Geen verzonnen tijden of effecten."""
    import vraagaanpak
    a = vraagaanpak.aanpak(v["vraag"], alle_anderen(v), landnaam, en)
    if v.get("gewonnen"):
        status, soort = ("Won" if en else "Gewonnen"), "win"
    elif v["vraag"] in (gekozen or []) or v.get("eigen"):
        status, soort = ("On your list" if en else "Op je lijst"), "lijst"
    else:
        status, soort = ("Suggested" if en else "Voorgesteld"), "voorstel"
    kopjes_en = ["One clear page", "Questions and answers on it", "Read their page"]
    kopjes_nl = ["Een duidelijke pagina", "Vragen en antwoorden erop", "Lees hun pagina"]
    waar_en = ["Collection or category page", "On that page", "Their page, then yours"]
    waar_nl = ["Collectie- of categoriepagina", "Op die pagina", "Hun pagina, dan de jouwe"]
    if not alle_anderen(v):
        kopjes_en[2], kopjes_nl[2] = "Be the first", "Wees de eerste"
        waar_en[2], waar_nl[2] = "Your page about it", "Je pagina erover"
    return {"onderwerp": a["onderwerp"], "stappen": [
        {"nr": i + 1, "kop": (kopjes_en if en else kopjes_nl)[i], "waar": (waar_en if en else waar_nl)[i],
         "tekst": t, "status": status, "soort": soort} for i, t in enumerate(a["stappen"])]}


def pagina_ontbreekt(vraag, paginas):
    """(onderwerp, ontbreekt): de paginacheck draaide (er zijn pagina's gelezen) en vond
    geen pagina bij het onderwerp van deze vraag. Zonder paginacheck: nooit "ontbreekt"."""
    import vraagaanpak
    onderwerp = vraagaanpak.onderwerp(vraag)
    return onderwerp, bool(paginas) and not pagina_voor_onderwerp(onderwerp, paginas)


def pagina_voor_onderwerp(onderwerp, paginas):
    """Welke pagina van de winkel het onderwerp beantwoordt, volgens de paginacheck
    (dezelfde regel als vraagaanpak.verrijk). None als er geen is."""
    import vraagaanpak
    rij = vraagaanpak.verrijk([{"vraag": "", "onderwerp": onderwerp}], [], paginas)
    return rij[0].get("pagina")


def pagina_gegevens(v, antwoord_rijen, ranglijst_rijen, winkelnaam, webshop_url, gekozen, taal, landnaam,
                    paginacheck_paginas, assistent_naam, opschonen):
    """Alles wat het sjabloon voor de pagina nodig heeft. Geen netwerk, geen scan."""
    en = taal != "nl"
    antw = antwoorden_per_assistent(v, antwoord_rijen, winkelnaam, assistent_naam, opschonen)
    naam = winnaar_naam(v)
    act = acties(v, gekozen, landnaam, en)
    onderwerp = act["onderwerp"]
    pagina = pagina_voor_onderwerp(onderwerp, paginacheck_paginas) if paginacheck_paginas else None
    return {"vraag": v["vraag"], "eigen": bool(v.get("eigen")), "gewonnen": bool(v.get("gewonnen")),
            "aanbevolen": bool(v.get("aanbevolen")), "antwoorden": antw, "winnaar": naam,
            "anderen": alle_anderen(v), "onderwerp": onderwerp, "acties": act,
            "bronnen": [] if v.get("eigen") else bronnen_voor_vraag(antwoord_rijen, v["vraag"]),
            "pagina": pagina, "pagina_ontbreekt": bool(paginacheck_paginas) and not pagina,
            "al_gekozen": v["vraag"] in (gekozen or []),
            "winnaar_url": winnaar_url(naam, ranglijst_rijen)}
