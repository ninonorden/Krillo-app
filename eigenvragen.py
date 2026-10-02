"""Eigen vragen: Watch vijf, Fix vijftien, alleen voor die klant gemeten (2 oktober 2026, stap 180).

Goedgekeurd door Nino. Het eerste wat een klant bij Peec doet: zijn eigen
vragen toevoegen. Wij meten vaste vragen per categorie, en dat houdt de index
eerlijk (iedere winkel dezelfde vragen). De eigen vragen tellen daarom NIET mee
voor de plek in de index; ze staan alleen in het dashboard van die klant.

HOE
- De klant typt een vraag zoals een koper hem stelt. Hoogstens MAX[pakket].
- Meteen na het toevoegen een keer gemeten (ChatGPT en Gemini), daarna elke
  week mee met de snelmeting. Langs de kostenrem per klant.
- Voorstellen om toe te voegen: uit zijn producten (productkaart.py) en zijn
  categorie, in de taal van zijn markt. Geen AI, dus geen kosten.
"""
import json
import re
from datetime import datetime, timezone

import db

MAX = {"watch": 5, "fix": 15, "merken": 15}
MIN_TEKENS, MAX_TEKENS = 8, 200


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


def maak_tabellen():
    _sql("""CREATE TABLE IF NOT EXISTS eigen_vragen (
                id SERIAL PRIMARY KEY,
                webshop_url TEXT NOT NULL,
                vraag TEXT NOT NULL,
                toegevoegd_op TIMESTAMPTZ NOT NULL DEFAULT now())""")
    _sql("CREATE UNIQUE INDEX IF NOT EXISTS eigen_vragen_uniek ON eigen_vragen (webshop_url, lower(vraag))")
    _sql("""CREATE TABLE IF NOT EXISTS eigen_metingen (
                id SERIAL PRIMARY KEY,
                vraag_id INTEGER NOT NULL,
                webshop_url TEXT NOT NULL,
                op TIMESTAMPTZ NOT NULL,
                assistent TEXT NOT NULL,
                genoemd BOOLEAN NOT NULL DEFAULT FALSE,
                aanbevolen BOOLEAN NOT NULL DEFAULT FALSE,
                anderen JSONB)""")
    _sql("CREATE INDEX IF NOT EXISTS eigen_metingen_vraag ON eigen_metingen (vraag_id, op)")


def maximum(pakket):
    return MAX.get((pakket or "").lower(), MAX["watch"])


def vragen(webshop_url):
    maak_tabellen()
    return _sql("SELECT id, vraag, toegevoegd_op FROM eigen_vragen WHERE webshop_url = %s ORDER BY id",
                (webshop_url,), alles=True) or []


def schoon(vraag):
    vraag = re.sub(r"<[^>]+>", " ", str(vraag or ""))
    vraag = " ".join(vraag.replace("—", ",").split())
    return vraag


def voeg_toe(webshop_url, vraag, pakket):
    """{"ok": bool, "fout": tekst|None, "id": int|None}. Fouten in het Engels (dashboard)."""
    vraag = schoon(vraag)
    if len(vraag) < MIN_TEKENS:
        return {"ok": False, "fout": "Type a question of at least a few words, the way a shopper would ask it."}
    if len(vraag) > MAX_TEKENS:
        return {"ok": False, "fout": f"Keep it under {MAX_TEKENS} characters."}
    if re.search(r"https?://|www\.", vraag, re.I):
        return {"ok": False, "fout": "Leave out web addresses: ask it the way a shopper would."}
    huidige = vragen(webshop_url)
    if any(v["vraag"].lower() == vraag.lower() for v in huidige):
        return {"ok": False, "fout": "That question is already on your list."}
    if len(huidige) >= maximum(pakket):
        return {"ok": False, "fout": f"Your plan has room for {maximum(pakket)} own questions. Remove one first."}
    rij = _sql("INSERT INTO eigen_vragen (webshop_url, vraag) VALUES (%s, %s) RETURNING id", (webshop_url, vraag))
    return {"ok": bool(rij), "fout": None if rij else "Saving failed. Try again.", "id": (rij or {}).get("id")}


def verwijder(webshop_url, vraag_id):
    maak_tabellen()
    _sql("DELETE FROM eigen_metingen WHERE vraag_id = %s AND webshop_url = %s", (int(vraag_id), webshop_url))
    _sql("DELETE FROM eigen_vragen WHERE id = %s AND webshop_url = %s", (int(vraag_id), webshop_url))


def meet(webshop_url, alleen_id=None, aanbieders=None, vraag_aan=None, lees=None, nu=None):
    """Meet de eigen vragen (of alleen de vraag met alleen_id). Geeft een verslag.
    aanbieders, vraag_aan en lees zijn er voor de test."""
    import kosten
    import metingen
    import scan_engine
    import categoriemeting
    import dashboardpaginas as dp
    lijst = [v for v in vragen(webshop_url) if alleen_id is None or v["id"] == alleen_id]
    if not lijst:
        return {"gemeten": 0, "reden": "geen eigen vragen"}
    aanbieders = aanbieders if aanbieders is not None else metingen.beschikbare_aanbieders()
    if not aanbieders:
        return {"gemeten": 0, "reden": "geen AI-sleutels"}
    vraag_aan = vraag_aan or metingen.stel_een_vraag
    lees = lees or categoriemeting.winkels_uit_antwoord
    moment = nu or datetime.now(timezone.utc)
    verslag = {"gemeten": 0, "mislukt": 0, "gestopt": None}
    for v in lijst:
        for a in aanbieders:
            rem = kosten.mag_doorgaan(webshop_url=webshop_url)
            if not rem.get("mag"):
                verslag["gestopt"] = rem.get("reden")
                return verslag
            uitkomst = vraag_aan(a, v["vraag"])
            if not uitkomst or not uitkomst.get("gelukt"):
                verslag["mislukt"] += 1
                continue
            kosten.registreer_aanroep(provider=a["provider"], model=a["model"],
                                      invoer_tokens=uitkomst.get("invoer_tokens", 0),
                                      uitvoer_tokens=uitkomst.get("uitvoer_tokens", 0),
                                      soort="eigen_vragen", duur_ms=uitkomst.get("duur_ms", 0),
                                      webshop_url=webshop_url)
            genoemde = lees(v["vraag"], uitkomst.get("antwoord"))
            if genoemde is None:
                verslag["mislukt"] += 1
                continue
            namen = [w.get("naam") for w in genoemde.get("winkels", []) if w.get("naam")]
            anderen = [w.get("naam") for w in genoemde.get("winkels", [])
                       if w.get("naam") and (w.get("soort") or "winkel") != "platform"
                       and not scan_engine.is_eigen_winkel(webshop_url, w.get("naam"))][:3]
            _sql("""INSERT INTO eigen_metingen (vraag_id, webshop_url, op, assistent, genoemd, aanbevolen, anderen)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                 (v["id"], webshop_url, moment, dp.assistent_naam(a["model"]),
                  any(scan_engine.is_eigen_winkel(webshop_url, n) for n in namen),
                  any(scan_engine.is_eigen_winkel(webshop_url, n) for n in genoemde.get("aanbevolen", [])),
                  json.dumps(anderen)))
            verslag["gemeten"] += 1
    return verslag


def overzicht(webshop_url):
    """Per eigen vraag de laatste meting per assistent, en of hij vorige keer genoemd werd.
    [{"id", "vraag", "op", "assistenten": [{"naam", "genoemd", "anderen"}], "was": bool|None}]"""
    uit = []
    for v in vragen(webshop_url):
        rijen = _sql("""SELECT op, assistent, genoemd, anderen FROM eigen_metingen WHERE vraag_id = %s
                        ORDER BY op DESC, id""", (v["id"],), alles=True) or []
        momenten = sorted({r["op"] for r in rijen}, reverse=True)
        laatste = [r for r in rijen if momenten and r["op"] == momenten[0]]
        vorige = [r for r in rijen if len(momenten) > 1 and r["op"] == momenten[1]]
        uit.append({"id": v["id"], "vraag": v["vraag"], "op": momenten[0] if momenten else None,
                    "assistenten": [{"naam": r["assistent"], "genoemd": r["genoemd"],
                                     "anderen": (json.loads(r["anderen"]) if isinstance(r["anderen"], str)
                                                 else r["anderen"]) or []} for r in laatste],
                    "was": any(r["genoemd"] for r in vorige) if vorige else None})
    return uit


def voorstellen(webshop_url, categorienaam=None, land="nl", al=None, aantal=3):
    """Drie vragen om toe te voegen, uit zijn producten en zijn categorie. Geen AI."""
    nl = (land or "nl").lower() in ("nl", "be")
    al = {a.lower() for a in (al or [])}
    uit = []
    try:
        import productkaart
        producten = productkaart.producten_van(webshop_url)
    except Exception:
        producten = []
    for p in producten[:6]:
        naam = (p.get("naam") or "").lower()
        if len(naam.split()) >= 2:
            uit.append(f"waar koop ik {naam} online?" if nl else f"where can I buy {naam} online?")
    if categorienaam:
        c = categorienaam.lower()
        uit += ([f"beste webshop voor {c} met snelle levering", f"betrouwbare webshop voor {c} in nederland"]
                if nl else [f"best online store for {c} with fast delivery", f"trusted online store for {c}"])
    gezien, schoon_uit = set(), []
    for v in uit:
        if v.lower() not in al and v.lower() not in gezien:
            gezien.add(v.lower())
            schoon_uit.append(v)
    return schoon_uit[:aantal]
