"""Wachtlijst per land (stap 165, 28 september).

WAAROM DIT BESTAAT. Een winkel uit Duitsland, het VK of de VS die de gratis
check doet, las "we meten jouw land nog niet" en was weg. Nu laat hij zijn
adres achter. Zo zien we per land hoeveel vraag er is (welk land eerst, stap
81 en 44), en heeft elk nieuw land op dag een een rij winkels die er zelf om
vroegen. Geen koude mail: zij vroegen het, dus ook in Duitsland toegestaan.

Zodra een land in markten.index_landen() staat (INDEX_LANDEN in Render),
krijgt iedereen op de lijst van dat land EEN bericht, en komt zijn winkel op
de lijst om gemeten te worden.
"""
import db
import markten

PER_RONDE = 20


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


def maak_tabellen(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS wachtlijst_land (
                       id SERIAL PRIMARY KEY,
                       email TEXT NOT NULL,
                       webshop_url TEXT,
                       land TEXT NOT NULL,
                       op TIMESTAMPTZ NOT NULL DEFAULT now(),
                       gemeld_op TIMESTAMPTZ,
                       UNIQUE (email, land))""")


def zet_op_lijst(email, webshop_url, land):
    """Geeft True als hij erop staat (ook als hij er al stond)."""
    land = (land or "").lower()[:10]
    if not email or not land:
        return False
    if webshop_url:
        import scan_engine
        webshop_url = scan_engine.normalize_url(webshop_url)
    _sql("""INSERT INTO wachtlijst_land (email, webshop_url, land) VALUES (%s, %s, %s)
            ON CONFLICT (email, land) DO UPDATE SET webshop_url = coalesce(EXCLUDED.webshop_url,
                wachtlijst_land.webshop_url)""", (email.lower()[:200], (webshop_url or None), land))
    return True


def telling():
    """Per land: hoeveel wachten er, en hoeveel kregen al bericht. Grootste eerst."""
    return _sql("""SELECT land, count(*) FILTER (WHERE gemeld_op IS NULL) AS wachtend,
                          count(*) FILTER (WHERE gemeld_op IS NOT NULL) AS gemeld
                   FROM wachtlijst_land GROUP BY land ORDER BY count(*) DESC""", alles=True) or []


def bericht(rij, basis_url):
    """Onderwerp, alinea's en link voor iemand wiens land nu aan staat."""
    naam = markten.landnaam_en(rij["land"])
    winkel = (rij.get("webshop_url") or "").replace("https://", "").replace("http://", "").rstrip("/")
    link = f"{basis_url}/?winkel={winkel}#scan" if winkel else f"{basis_url}/#scan"
    return (f"Krillo now measures {naam}",
            [f"You asked us to let you know when the Krillo Index measures {naam}. It does now.",
             ("Check " + (f"<strong>{winkel}</strong>" if winkel else "your store")
              + " for free: you see your rank and the buying questions where AI names someone else. "
                "If your category is still filling up, your store is in the next monthly measurement."),
             "This is the only email we send about it."],
            link)


def ronde(basis_url, verstuur=None):
    """Iedereen op de lijst van een land dat nu aan staat, een keer bericht."""
    landen = markten.index_landen()
    if verstuur is None:
        import emailing
        verstuur = emailing.send_klantbericht
    uit = {"gemeld": 0}
    rijen = _sql("""SELECT * FROM wachtlijst_land WHERE gemeld_op IS NULL AND land = ANY(%s)
                    ORDER BY op LIMIT %s""", (list(landen), PER_RONDE), alles=True) or []
    for rij in rijen:
        # Eerst afvinken: nooit twee keer, ook niet als het versturen hapert.
        _sql("UPDATE wachtlijst_land SET gemeld_op = now() WHERE id = %s", (rij["id"],))
        onderwerp, alineas, link = bericht(rij, basis_url)
        if rij.get("webshop_url"):
            try:
                db.zet_klant_op_lijst(rij["webshop_url"], land=rij["land"].upper(), stand="wachtlijst")
            except Exception as e:
                print(f"Wachtlijstwinkel op de lijst zetten mislukt: {e}")
        if verstuur(rij["email"], onderwerp, alineas, link, knop="Check my store"):
            uit["gemeld"] += 1
    return uit
