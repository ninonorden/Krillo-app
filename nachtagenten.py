"""Drie agents die 's nachts nakijken: de index, de concurrenten en de kosten (28 september).

- KWALITEIT (stap 97): na het meten zoeken naar dingen die niet kloppen, voordat
  een klant of een redactie ze ziet: een categorie waar niemand genoemd wordt,
  een winkel die in een maand 15 plekken of meer springt, een platform of merk
  in een ranglijst, dezelfde winkel twee keer (met en zonder www). Hij lost
  niets zelf op: een fout "oplossen" in een openbare ranglijst is erger dan hem
  melden. Het lijstje staat in het ochtendbericht en op /admin/controle.
- CONCURRENTEN (stap 100): een keer per week de prijspagina's uit
  vergelijkingen.py ophalen en nakijken of de bedragen die wij noemen er nog
  staan. Staat een bedrag er niet meer, dan klopt /compare niet meer, en dat
  moet eruit voordat iemand het ziet. Ook een seintje als GEKEKEN ouder is dan
  90 dagen.
- KOSTEN (stap 143): wat Krillo de laatste 7 dagen aan AI kostte, tegenover wat
  de betalende klanten per maand opbrengen. In het ochtendbericht, zodat een
  kostenstijging nooit een verrassing is.
"""
import json
import re
from datetime import date

import db

SPRONG = 15
PER_WEEK_DAG = 0   # maandag


def _sql(opdracht, waarden=None, alles=False):
    from psycopg2.extras import RealDictCursor
    conn = db._get_connection()
    if conn is None:
        return [] if alles else None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(opdracht, waarden)
                if cur.description is None:
                    return cur.rowcount
                return [dict(r) for r in cur.fetchall()] if alles else (dict(cur.fetchone() or {}) or None)
    finally:
        conn.close()


def _kaal(url):
    return (url or "").lower().replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


def bekijk_lijst(naam, rijen, soorten=None):
    """De bevindingen voor een ranglijst. rijen zoals db.ranglijst_per_land ze
    geeft; soorten: {webshop_url: soort} uit de winkellijst."""
    uit = []
    if rijen and not any((r.get("genoemd") or 0) > 0 for r in rijen):
        uit.append(f"{naam}: niemand genoemd in de laatste meting (koopvragen nakijken)")
    for r in rijen:
        if r.get("vorige_positie") and abs(r["positie"] - r["vorige_positie"]) >= SPRONG:
            uit.append(f"{naam}: {_kaal(r['webshop_url'])} sprong van #{r['vorige_positie']} naar #{r['positie']}")
        soort = (soorten or {}).get(r["webshop_url"])
        if soort in ("platform", "merk") and (r.get("genoemd") or 0) > 0:
            uit.append(f"{naam}: {_kaal(r['webshop_url'])} staat als {soort} aangemerkt maar in de ranglijst")
    gezien = {}
    for r in rijen:
        k = _kaal(r["webshop_url"])
        if k in gezien:
            uit.append(f"{naam}: {k} staat er twee keer in")
        gezien[k] = True
    return uit


def kwaliteit(ranglijst=None, landen=None, categorieen_per_land=None):
    """Alle bevindingen over de index. Nooit een fout naar buiten."""
    ranglijst = ranglijst or db.ranglijst_per_land
    landen = landen if landen is not None else [r["land"] for r in db.landen_in_index()]
    categorieen_per_land = categorieen_per_land or (lambda land: db.categorieen_per_land(land, ook_leeg=True))
    soorten = {r["webshop_url"]: r["soort"] for r in _sql(
        "SELECT webshop_url, soort FROM benadering WHERE soort IS NOT NULL AND soort <> 'winkel'",
        alles=True) or []}
    uit = []
    for land in landen:
        for c in categorieen_per_land(land):
            try:
                rijen = (ranglijst(c["categorie"], land, 1000) or {}).get("rijen") or []
            except Exception as e:
                uit.append(f"{c['categorie']} ({land}): ranglijst niet op te halen ({e})")
                continue
            bevindingen = bekijk_lijst(f"{c['categorie']} ({land})", rijen, soorten)
            # 30 september (wijn-drank be): "niemand genoemd" zei niet WAAROM.
            # Nu staat de oorzaak erbij, uit de antwoorden zelf.
            bevindingen = [b + " " + waarom_niemand(c["categorie"], land) if "niemand genoemd" in b else b
                           for b in bevindingen]
            uit += bevindingen
    return uit


def waarom_niemand(categorie, land, antwoorden=None, lijst=None):
    """Een zin met de reden dat in een categorie niemand genoemd werd.

    Drie oorzaken, elk met een andere oplossing:
    1. de assistenten noemden geen enkele winkel (weigeren, of alleen algemeen
       advies; bij drank gebeurt dat, omdat ze voorzichtig zijn met alcohol):
       dan passen de koopvragen niet;
    2. ze noemden wel winkels, maar niet die op onze lijst: dan mist de lijst
       de winkels die ertoe doen (en staan ze er na de volgende meting op,
       via nieuwe_winkels_uit_antwoorden);
    3. er zijn geen antwoorden: de meting liep niet goed.
    antwoorden en lijst zijn er voor de test."""
    import json
    algemeen = False
    if antwoorden is None:
        # 1 oktober (wijn-drank be): zoek dezelfde ronde als de ranglijst zelf.
        # Een land zonder eigen meting gebruikt de algemene ronde (land leeg);
        # hier stond "land = be", en dan kwam er "(Geen afgeronde meting
        # gevonden.)" terwijl de ranglijst er gewoon was.
        lijst_ronde = (db.ranglijst_per_land(categorie, land) or {}).get("ronde")
        if not lijst_ronde:
            return "(Geen afgeronde meting gevonden.)"
        ronde = _sql("SELECT id, land FROM categorie_rondes WHERE id = %s", (lijst_ronde,)) or {"id": lijst_ronde}
        algemeen = not ronde.get("land") and land.lower() != "nl"
        antwoorden = _sql("""SELECT winkel_kon_genoemd, genoemde_winkels, antwoord FROM categorie_antwoorden
                              WHERE ronde = %s""", (ronde["id"],), alles=True) or []
    if lijst is None:
        lijst = {_kaal(r["webshop_url"]) for r in _sql(
            "SELECT webshop_url FROM benadering WHERE categorie = %s AND lower(coalesce(land, 'nl')) = %s",
            (categorie, land.lower()), alles=True) or []}
    if not antwoorden:
        return "Oorzaak: er zijn geen antwoorden bewaard, de meting liep niet goed. Opnieuw meten."
    namen, zonder, leeg = {}, 0, 0
    for a in antwoorden:
        if not (a.get("antwoord") or "").strip():
            leeg += 1
            continue
        g = a.get("genoemde_winkels") or {}
        if isinstance(g, str):
            try:
                g = json.loads(g)
            except ValueError:
                g = {}
        winkels = [w for w in g.get("winkels", []) if (w.get("soort") or "winkel") == "winkel"]
        if not a.get("winkel_kon_genoemd") or not winkels:
            zonder += 1
        for w in winkels:
            sleutel = w.get("adres") or w.get("naam")
            if sleutel:
                namen[sleutel] = namen.get(sleutel, 0) + 1
    totaal = len(antwoorden)
    if leeg >= totaal / 2:
        return f"Oorzaak: {leeg} van de {totaal} antwoorden zijn leeg, de meting liep niet goed. Opnieuw meten."
    if zonder >= totaal * 0.8:
        return (f"Oorzaak: in {zonder} van de {totaal} antwoorden noemden de assistenten geen enkele winkel "
                f"(alleen algemeen advies). De koopvragen passen niet: maak ze concreter "
                f"(\"waar bestel ik ... online\"), of haal de categorie uit dit land.")
    top = sorted(namen.items(), key=lambda kv: -kv[1])[:5]
    buiten = [n for n, _ in top if _kaal(n) not in lijst]
    if algemeen:
        return (f"Oorzaak: {land.upper()} heeft voor deze categorie nog geen eigen meting met eigen vragen. "
                f"In de algemene meting noemt AI winkels uit een ander land"
                + (f" (het vaakst: {', '.join(n for n, _ in top[:3])})" if top else "") +
                f". De ranglijst staat daarom niet openbaar, en een eigen meting voor {land.upper()} volgt zodra "
                f"er genoeg winkels van dat land in zitten. Niets voor jou te doen.")
    if buiten:
        return (f"Oorzaak: de assistenten noemden wel winkels, maar niet die van onze lijst. Het vaakst: "
                f"{', '.join(buiten)}. Die komen bij de volgende meting vanzelf op de lijst; tot dan klopt "
                f"deze ranglijst niet en hoort hij niet in de openbare index.")
    return "Oorzaak onduidelijk: bekijk de antwoorden op /admin/metingen."


def _bedragen(prijs):
    """De bedragen die wij van hun site overnamen, zoals ze daar staan ($29, $189)."""
    return re.findall(r"\$\d[\d,]*", prijs or "")


def _zichtbare_bedragen(html):
    """De tekst van een pagina zonder opmaak, met "$ 29" samengetrokken tot "$29"."""
    import html as htmlmod
    tekst = re.sub(r"<!--.*?-->", "", html or "", flags=re.S)
    tekst = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", tekst, flags=re.S | re.I)
    tekst = re.sub(r"<[^>]+>", "", tekst)
    tekst = htmlmod.unescape(tekst)
    tekst = re.sub(r"\$\s+(?=\d)", "$", tekst)
    return tekst


# Alleen AthenaHQ: daar staat "$25 in credits" gewoon in de pagina en "$295"
# pas na het laden in de browser, dus de regel "alles weg = niet zeker" vangt
# het niet. Otterly viel al onder die regel (alle drie weg); dat het daar toch
# terugkwam, kwam door de oude uitkomst die tot maandag herhaald werd.
PRIJS_IN_BROWSER = {"athenahq"}


def concurrenten(haal=None, vandaag=None):
    """Staan de bedragen die wij noemen nog op hun prijspagina?"""
    import vergelijkingen
    vandaag = vandaag or date.today()
    if haal is None:
        import requests
        import scan_engine

        def haal(url):
            r = requests.get(url, headers=scan_engine.HEADERS, timeout=15, allow_redirects=True)
            return r.text if r.status_code < 400 else None
    uit = []
    oud = (vandaag - date.fromisoformat(vergelijkingen.GEKEKEN)).days
    if oud > 90:
        uit.append(f"De vergelijkingen zijn {oud} dagen geleden nagekeken: tijd om ze na te lopen")
    for slug, t in vergelijkingen.TOOLS.items():
        bedragen = _bedragen(t.get("prijs"))
        # "Varies per app" (de Shopify-apps) is een schatting over veel apps,
        # geen bedrag van een pagina: niet na te kijken.
        if not bedragen or "varies" in (t.get("prijs") or "").lower():
            continue
        try:
            html = haal(t["bron"]) or ""
        except Exception:
            html = ""
        if not html:
            continue   # niet bereikbaar zegt niets over hun prijs
        tekst = _zichtbare_bedragen(html)
        # 30 september: het ochtendbericht zei dat $29 en $295 niet meer op de
        # pagina's van Otterly en AthenaHQ stonden. Ze stonden er gewoon. Hun
        # pagina's zetten het dollarteken en het getal in aparte stukjes
        # opmaak ("$<!-- -->29"), of bouwen de prijzen pas in de browser op.
        # Nu kijken we naar de tekst zoals een bezoeker hem leest, en staat
        # er helemaal geen bedrag in, dan is de pagina niet na te kijken en
        # zeggen we niets (in plaats van een vals alarm).
        if not re.search(r"\$\d", tekst):
            continue
        weg = [b for b in bedragen if b not in tekst]
        # 1 oktober: weer vals alarm voor Otterly ($29, $189, $489) en AthenaHQ
        # ($295). Met de hand nagekeken: de bedragen staan er nog precies zo. Die
        # pagina's zetten de prijzen pas in de browser neer (of tonen eerst de
        # jaarprijs); de losse $ die wij zagen was iets anders ("$25 free credit").
        # Daarom: is ALLES wat wij noemen weg, dan is de pagina waarschijnlijk niet
        # te lezen, en dat is "niet zeker", geen taak voor Nino. Is een DEEL weg,
        # dan is er echt iets veranderd.
        # 2 oktober: AthenaHQ kwam elke ochtend terug, terwijl de prijs er met
        # de hand nagekeken nog precies zo staat (zie PRIJS_IN_BROWSER). Voor
        # zo'n pagina is het altijd "niet zeker"; de hand-controle elke 90
        # dagen (GEKEKEN) vangt een echte prijswijziging.
        if weg and slug in PRIJS_IN_BROWSER:
            uit.append(f"Niet zeker: {t['naam']} bouwt zijn prijzen in de browser op ({t['bron']}); "
                       f"met de hand nakijken bij de 90-dagencontrole")
        elif weg and len(weg) == len(bedragen):
            uit.append(f"Niet zeker: {t['naam']} toont zijn prijzen niet in de pagina zelf ({t['bron']}); "
                       f"met de hand nakijken als je toch op /compare bent")
        elif weg:
            uit.append(f"{t['naam']}: {', '.join(weg)} staat niet meer op {t['bron']}. /compare/{slug} nakijken")
    return uit


# 30 september: het ochtendbericht zei "Opbrengst per maand 198" en tegelijk
# "Nieuwe echte klanten 0". Die 198 was 49 + 149: klantregels die geen cent
# opleveren. Nu telt een regel alleen als er echt geld binnenkomt:
# - niet opgezegd, geen test, en niet het eigen adres van Nino;
# - niet midden in de gratis proef (dan betaalt hij nu nog niets);
# - en hij betaalt via Mollie (er staat een Mollie-klant bij), of via Shopify
#   terwijl de Shopify-facturen echt zijn (SHOPIFY_BILLING_TEST uit).
OPBRENGST_SQL = """
    SELECT k.pakket, k.periode FROM klanten k
     WHERE NOT k.is_test AND k.opgezegd_op IS NULL
       AND lower(coalesce(k.email, '')) <> %s
       AND (k.gratis_tot IS NULL OR k.gratis_tot < current_date)
       AND (k.mollie_klant_id IS NOT NULL
            OR (%s AND EXISTS (SELECT 1 FROM shopify_winkels s
                                WHERE s.webshop_url = k.webshop_url AND s.verwijderd_op IS NULL)))"""


def _eigen_adres():
    import os
    return ((os.environ.get("BEHEERDER_EMAIL") or os.environ.get("BEHEER_EMAIL") or "").strip().lower()
            or "-")


def _shopify_telt():
    import os
    return (os.environ.get("SHOPIFY_BILLING_TEST") or "").strip().lower() not in ("ja", "1", "true")


def kosten_week():
    """(AI-kosten laatste 7 dagen in euro, opbrengst per maand van betalende klanten)."""
    import payments
    rij = _sql("SELECT coalesce(sum(kosten), 0) AS k FROM kostengebeurtenissen "
               "WHERE moment > now() - interval '7 days'") or {}
    kosten = float(rij.get("k") or 0)
    opbrengst = 0.0
    for k in _sql(OPBRENGST_SQL, (_eigen_adres(), _shopify_telt()), alles=True) or []:
        try:
            if (k.get("periode") or "maand") == "jaar":
                opbrengst += float(payments.prijs_van(k.get("pakket"), "jaar")["value"]) / 12
            else:
                opbrengst += float(payments.prijs_van(k.get("pakket"), "maand")["value"])
        except Exception:
            pass
    return round(kosten, 2), round(opbrengst, 2)


def draai(melden=None, vandaag=None):
    """Voor de nachtronde. Bewaart alles in de instelling 'nachtagenten'."""
    vandaag = vandaag or date.today()
    uit = {"kwaliteit": [], "concurrenten": None, "datum": vandaag.isoformat()}
    try:
        uit["kwaliteit"] = kwaliteit()
    except Exception as e:
        uit["kwaliteit"] = [f"Kwaliteitsagent mislukt: {e}"]
    vorige = {}
    try:
        vorige = json.loads(db.get_instelling("nachtagenten") or "{}")
    except Exception:
        pass
    # 2 oktober: had de vorige keer bevindingen, dan elke nacht opnieuw kijken
    # (het kost niets). Anders bleef een opgelost vals alarm tot maandag staan.
    vorige_zeker = [c for c in vorige.get("concurrenten") or [] if not c.startswith("Niet zeker")]
    if vandaag.weekday() == PER_WEEK_DAG or vorige.get("concurrenten") is None or vorige_zeker:
        try:
            uit["concurrenten"] = concurrenten(vandaag=vandaag)
        except Exception as e:
            uit["concurrenten"] = [f"Concurrentieagent mislukt: {e}"]
    else:
        uit["concurrenten"] = vorige.get("concurrenten")
    try:
        db.zet_instelling("nachtagenten", json.dumps(uit)[:20000])
    except Exception as e:
        print(f"Nachtagenten bewaren mislukt: {e}")
    if melden and uit["concurrenten"] and vandaag.weekday() == PER_WEEK_DAG:
        melden("Concurrenten: /compare nakijken", "<br>".join(uit["concurrenten"]))
    return uit
