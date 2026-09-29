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
    categorieen_per_land = categorieen_per_land or db.categorieen_per_land
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
            uit += bekijk_lijst(f"{c['categorie']} ({land})", rijen, soorten)
    return uit


def _bedragen(prijs):
    """De bedragen die wij van hun site overnamen, zoals ze daar staan ($29, $189)."""
    return re.findall(r"\$\d[\d,]*", prijs or "")


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
        tekst = html.replace("&#36;", "$")
        weg = [b for b in bedragen if b not in tekst]
        if weg:
            uit.append(f"{t['naam']}: {', '.join(weg)} staat niet meer op {t['bron']}. /compare/{slug} nakijken")
    return uit


def kosten_week():
    """(AI-kosten laatste 7 dagen in euro, opbrengst per maand van betalende klanten)."""
    import payments
    rij = _sql("SELECT coalesce(sum(kosten), 0) AS k FROM kostengebeurtenissen "
               "WHERE moment > now() - interval '7 days'") or {}
    kosten = float(rij.get("k") or 0)
    opbrengst = 0.0
    for k in _sql("SELECT pakket, periode FROM klanten WHERE NOT is_test AND opgezegd_op IS NULL",
                  alles=True) or []:
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
    if vandaag.weekday() == PER_WEEK_DAG or vorige.get("concurrenten") is None:
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
