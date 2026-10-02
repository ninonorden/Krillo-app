"""De wekelijkse snelmeting: elke week de vijf belangrijkste vragen opnieuw (stap 198, 1 oktober 2026).

WAAROM DIT BESTAAT. Nino keurde het voorstel goed: "Nu meten we maandelijks. Wie
betaalt en iets verandert, wil binnen een week zien of het werkt. Peec meet
dagelijks." De grote meting blijft maandelijks (die maakt de ranglijst eerlijk:
iedereen dezelfde vragen op hetzelfde moment). Daarnaast krijgt elke betalende
klant elke week een kleine meting van zijn eigen vijf belangrijkste vragen.

WELKE VIJF VRAGEN
1. Eerst de vragen die de klant zelf koos ("Add to my fixes").
2. Dan de vragen die hij in de maandmeting verloor (daar werkt hij aan).
3. Dan de vragen die hij won (om te zien of hij ze houdt).
Alles uit dezelfde ronde als zijn plek, dus dezelfde vragen als op zijn dashboard.

HOE
Per vraag een keer aan elke assistent (ChatGPT en Gemini), en het antwoord laten
lezen door hetzelfde leesmodel als de maandmeting, met dezelfde herkenning van
de winkelnaam (scan_engine.is_eigen_winkel). Dus geen tweede manier van tellen.
Op de vaste meetdag van de klant, samen met de wekelijkse scan (app.meetdag).

KOSTEN. Vijf vragen, twee assistenten, plus het lezen: ongeveer 10 tot 15 cent
per klant per week. Langs de kostenrem per klant en per dag, en geteld in de
kosten als "snelmeting".

WAT HET NIET IS. Geen nieuwe plek in de ranglijst. Die komt alleen uit de
maandmeting, waar iedereen dezelfde vragen krijgt. Het dashboard zegt dat ook.
"""
import json
from datetime import datetime, timezone

import db

AANTAL = 5


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
                    return None
                return [dict(r) for r in cur.fetchall()] if alles else (
                    dict(cur.fetchone()) if cur.rowcount else None)
    finally:
        conn.close()


def maak_tabel():
    _sql("""CREATE TABLE IF NOT EXISTS snelmetingen (
                id SERIAL PRIMARY KEY,
                webshop_url TEXT NOT NULL,
                ronde_op TIMESTAMPTZ NOT NULL,
                vraag TEXT NOT NULL,
                assistent TEXT NOT NULL,
                genoemd BOOLEAN NOT NULL DEFAULT FALSE,
                aanbevolen BOOLEAN NOT NULL DEFAULT FALSE,
                anderen JSONB)""")
    _sql("CREATE INDEX IF NOT EXISTS snelmetingen_winkel ON snelmetingen (webshop_url, ronde_op)")
    # 2 oktober (productkaart.py): welke producten van de winkel in het antwoord staan.
    _sql("ALTER TABLE snelmetingen ADD COLUMN IF NOT EXISTS producten JSONB")


def kies_vragen(vragen_overzicht, gekozen=None, aantal=AANTAL):
    """Uit dashboardpaginas.vragen_overzicht: gekozen eerst, dan verloren, dan gewonnen."""
    gekozen = list(gekozen or [])
    alle = [v["vraag"] for v in (vragen_overzicht or {}).get("vragen", [])]
    verloren = [v["vraag"] for v in (vragen_overzicht or {}).get("vragen", []) if not v.get("gewonnen")]
    gewonnen = [v["vraag"] for v in (vragen_overzicht or {}).get("vragen", []) if v.get("gewonnen")]
    uit = []
    for v in [g for g in gekozen if g in alle] + verloren + gewonnen:
        if v not in uit:
            uit.append(v)
    return uit[:aantal]


def vragen_voor(webshop_url):
    """De vijf vragen voor deze winkel, of [] als hij (nog) nergens in staat."""
    import klantbeeld
    import dashboardpaginas as dp
    beeld = klantbeeld.bouw(webshop_url, max_vragen=1)
    if not beeld:
        return []
    vo = dp.vragen_overzicht(beeld["ronde"], webshop_url, beeld.get("naam"))
    return kies_vragen(vo, db.gekozen_vragen(webshop_url))


def meet(webshop_url, vragen=None, aanbieders=None, vraag_aan=None, lees=None, nu=None, haal_producten=None):
    """De snelmeting voor een winkel. Geeft een verslag.

    vraag_aan en lees zijn alleen voor de test (geen echte AI-aanroepen)."""
    import kosten
    import metingen
    import scan_engine
    import categoriemeting
    import dashboardpaginas as dp
    maak_tabel()
    vragen = vragen if vragen is not None else vragen_voor(webshop_url)
    if not vragen:
        return {"gemeten": 0, "reden": "geen vragen (de winkel staat nog in geen ranglijst)"}
    aanbieders = aanbieders if aanbieders is not None else metingen.beschikbare_aanbieders()
    if not aanbieders:
        return {"gemeten": 0, "reden": "geen AI-sleutels"}
    vraag_aan = vraag_aan or metingen.stel_een_vraag
    lees = lees or categoriemeting.winkels_uit_antwoord
    moment = nu or datetime.now(timezone.utc)
    verslag = {"gemeten": 0, "mislukt": 0, "gestopt": None}
    # De productlijst (productkaart.py), een keer per week uit de sitemap.
    try:
        import productkaart
        producten = productkaart.producten_van(webshop_url, haal=haal_producten) if haal_producten is not False \
            else []
    except Exception as e:
        print(f"Productlijst voor de snelmeting mislukt: {e}")
        producten = []
    for vraag in vragen:
        for a in aanbieders:
            rem = kosten.mag_doorgaan(webshop_url=webshop_url)
            if not rem.get("mag"):
                verslag["gestopt"] = rem.get("reden")
                break
            uitkomst = vraag_aan(a, vraag)
            if not uitkomst or not uitkomst.get("gelukt"):
                verslag["mislukt"] += 1
                continue
            kosten.registreer_aanroep(provider=a["provider"], model=a["model"],
                                      invoer_tokens=uitkomst.get("invoer_tokens", 0),
                                      uitvoer_tokens=uitkomst.get("uitvoer_tokens", 0),
                                      soort="snelmeting", duur_ms=uitkomst.get("duur_ms", 0),
                                      webshop_url=webshop_url)
            genoemde = lees(vraag, uitkomst.get("antwoord"))
            if genoemde is None:
                verslag["mislukt"] += 1
                continue
            namen = [w.get("naam") for w in genoemde.get("winkels", []) if w.get("naam")]
            genoemd = any(scan_engine.is_eigen_winkel(webshop_url, n) for n in namen)
            aanbevolen = any(scan_engine.is_eigen_winkel(webshop_url, n) for n in genoemde.get("aanbevolen", []))
            anderen = [w.get("naam") for w in genoemde.get("winkels", [])
                       if w.get("naam") and (w.get("soort") or "winkel") != "platform"
                       and not scan_engine.is_eigen_winkel(webshop_url, w.get("naam"))][:3]
            try:
                import productkaart
                in_antwoord = productkaart.genoemd_in(producten, uitkomst.get("antwoord"))
            except Exception:
                in_antwoord = []
            _sql("""INSERT INTO snelmetingen (webshop_url, ronde_op, vraag, assistent, genoemd, aanbevolen, anderen,
                                              producten)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                 (webshop_url, moment, vraag, dp.assistent_naam(a["model"]), genoemd, aanbevolen,
                  json.dumps(anderen), json.dumps(in_antwoord)))
            verslag["gemeten"] += 1
        if verslag["gestopt"]:
            break
    return verslag


def overzicht(webshop_url):
    """Voor het dashboard: de laatste snelmeting en de vorige, per vraag.

    Geeft None als er nog geen is, anders
    {"op", "genoemd", "van", "vorige_genoemd", "vorige_van", "vragen": [
        {"vraag", "assistenten": [{"naam", "genoemd", "aanbevolen", "anderen"}], "was": bool|None}]}"""
    maak_tabel()
    rondes = _sql("""SELECT DISTINCT ronde_op FROM snelmetingen WHERE webshop_url = %s
                     ORDER BY ronde_op DESC LIMIT 2""", (webshop_url,), alles=True) or []
    if not rondes:
        return None
    laatste = rondes[0]["ronde_op"]
    rijen = _sql("""SELECT * FROM snelmetingen WHERE webshop_url = %s AND ronde_op = %s ORDER BY id""",
                 (webshop_url, laatste), alles=True) or []
    vorige = []
    if len(rondes) > 1:
        vorige = _sql("""SELECT * FROM snelmetingen WHERE webshop_url = %s AND ronde_op = %s""",
                      (webshop_url, rondes[1]["ronde_op"]), alles=True) or []
    was = {}
    for r in vorige:
        was[r["vraag"]] = was.get(r["vraag"], False) or r["genoemd"]
    vragen, volgorde = {}, []
    for r in rijen:
        if r["vraag"] not in vragen:
            vragen[r["vraag"]] = {"vraag": r["vraag"], "assistenten": [],
                                  "was": was.get(r["vraag"]) if vorige else None}
            volgorde.append(r["vraag"])
        anderen = r.get("anderen") or []
        if isinstance(anderen, str):
            anderen = json.loads(anderen)
        vragen[r["vraag"]]["assistenten"].append({"naam": r["assistent"], "genoemd": r["genoemd"],
                                                 "aanbevolen": r["aanbevolen"], "anderen": anderen})
    for v in vragen.values():
        v["nu"] = any(a["genoemd"] for a in v["assistenten"])
    return {"op": laatste, "genoemd": sum(1 for r in rijen if r["genoemd"]), "van": len(rijen),
            "vorige_genoemd": sum(1 for r in vorige if r["genoemd"]) if vorige else None,
            "vorige_van": len(vorige) if vorige else None,
            "vragen": [vragen[v] for v in volgorde]}
