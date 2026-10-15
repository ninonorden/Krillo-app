"""Werkte de nieuwe titel of tekst? Voor en na, per wijziging (15 oktober 2026).

Goedgekeurd voorstel 3 (roadmap 245). Fix past titels en productteksten aan;
de wekelijkse snelmeting (snelmeting.py) stelt elke week dezelfde vijf vragen.
Hier zetten we die twee naast elkaar: per wijziging hoe vaak AI de winkel (en,
als de wijziging op een productpagina was, dat product) noemde in de weken
ervoor en in de weken erna.

EERLIJK, EN ZO STAAT HET OOK OP HET SCHERM.
- Twee versies tegelijk live zetten (zoals een A/B-test op een website) kan
  niet: een AI-assistent ziet maar een versie van een pagina. Dit is voor en na.
- AI-antwoorden wisselen van week tot week. Daarom pas een oordeel na minstens
  MIN_NA weken erna, en alleen "beter" of "slechter" bij een verschil van
  minstens DREMPEL procentpunt; anders "geen verschil te zien".
- De wijziging is niet de enige oorzaak die er kan zijn. We zeggen "na de
  wijziging", nooit "door de wijziging".
"""
import json
from datetime import timedelta

import db

MIN_NA = 2          # weken snelmeting na de wijziging
VOOR_WEKEN = 4
DREMPEL = 15        # procentpunt
TEKSTSOORTEN = ("titel", "title", "tekst", "text", "omschrijving", "description", "product", "faq", "alinea")


def _sql(opdracht, waarden=None):
    from psycopg2.extras import RealDictCursor
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(opdracht, waarden)
                return [dict(r) for r in cur.fetchall()] if cur.description else []
    except Exception as e:
        print(f"Tekstproef, ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def _deel(rijen, product_url=None):
    """(genoemd, van) over snelmetingrijen; met product_url: hoe vaak dat product erin stond."""
    van = len(rijen)
    if product_url:
        def heeft(r):
            p = r.get("producten") or []
            if isinstance(p, str):
                try:
                    p = json.loads(p)
                except ValueError:
                    p = []
            return any(product_url.rstrip("/") in str(x) for x in p)
        return sum(1 for r in rijen if heeft(r)), van
    return sum(1 for r in rijen if r.get("genoemd")), van


def oordeel(voor, na, weken_na):
    if weken_na < MIN_NA or not voor[1] or not na[1]:
        return "wacht"
    verschil = 100 * na[0] / na[1] - 100 * voor[0] / voor[1]
    if verschil >= DREMPEL:
        return "beter"
    if verschil <= -DREMPEL:
        return "slechter"
    return "gelijk"


def per_wijziging(webshop_url, wijzigingen=None, metingen=None):
    """[{"wat", "waar", "op", "voor": (g, van), "na": (g, van), "weken_na", "oordeel"}], nieuwste eerst."""
    if wijzigingen is None:
        wijzigingen = _sql("SELECT taak_id, wat, waar, gedaan_op FROM wijzigingen WHERE webshop_url = %s "
                           "ORDER BY gedaan_op DESC LIMIT 20", (webshop_url,))
    if metingen is None:
        metingen = _sql("SELECT ronde_op, genoemd, producten FROM snelmetingen WHERE webshop_url = %s "
                        "ORDER BY ronde_op", (webshop_url,))
    uit = []
    for w in wijzigingen:
        soort = f"{w.get('taak_id') or ''} {w.get('wat') or ''}".lower()
        if not any(t in soort for t in TEKSTSOORTEN) or not w.get("gedaan_op"):
            continue
        op = w["gedaan_op"]
        voor_rijen = [m for m in metingen if op - timedelta(weeks=VOOR_WEKEN) <= m["ronde_op"] < op]
        na_rijen = [m for m in metingen if m["ronde_op"] > op]
        weken_na = len({m["ronde_op"] for m in na_rijen})
        product = w.get("waar") if (w.get("waar") or "").count("/products/") else None
        voor, na = _deel(voor_rijen, product), _deel(na_rijen, product)
        uit.append({"wat": w.get("wat"), "waar": w.get("waar"), "op": op, "voor": voor, "na": na,
                    "weken_na": weken_na, "product": bool(product), "oordeel": oordeel(voor, na, weken_na)})
    return uit
