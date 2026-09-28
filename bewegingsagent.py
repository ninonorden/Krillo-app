"""De bewegingsagent: wie gemaild is en na de maandmeting echt verschoof, hoort het.

WAAROM DIT BESTAAT (stap 116, 28 september). De koude mail gaat een keer. Wie
dan niets doet, hoorde tot nu toe nooit meer iets, ook niet als zijn plek in de
index daarna flink veranderde. Juist dat is nieuws: "je zakte van 4 naar 9" of
"je staat nu in de top 3" wordt gelezen, reclame niet. Deze agent kijkt na elke
maandmeting welke eerder gemailde winkels echt bewogen, en stuurt die een kort
bericht met de beweging (dezelfde tekst als het maandbericht na de gratis check).

WANNEER ECHT BEWOGEN
- minstens BEWEGING_MIN plekken omhoog of omlaag, of
- nieuw in de top 3, of weg uit de top 3.
Een plek erbij of eraf is ruis in een meting; daar mailen we niet over.

REGELS DIE NOOIT LOSSEN
- Alleen wie al een koude mail kreeg, minstens 14 dagen geleden.
- Per meting hoogstens een keer (beweging_ronde), en minstens 30 dagen na de
  vorige extra mail (seizoen_op wordt gedeeld met de seizoensagent: twee extra
  mails in een week is er een te veel).
- Nooit naar afgemeld, bounce, klacht, klant of wie terugmailde.
- Alleen als de benadering aanstaat, binnen kantooruren, met een dagmaximum.
"""
import os

import db

PER_RONDE = int(os.environ.get("BEWEGING_PER_RONDE", "5"))
PER_DAG = int(os.environ.get("BEWEGING_PER_DAG", "20"))
BEWEGING_MIN = int(os.environ.get("BEWEGING_MIN", "3"))
RUST_DAGEN = 30


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
                return [dict(r) for r in cur.fetchall()] if alles else (dict(cur.fetchone() or {}) or None)
    finally:
        conn.close()


def is_beweging(nu, vorige):
    """Is dit nieuws? nu en vorige zijn plekken (1 is de beste)."""
    if not nu or not vorige or nu == vorige:
        return False
    if abs(nu - vorige) >= BEWEGING_MIN:
        return True
    return (nu <= 3) != (vorige <= 3)


def kandidaten(limiet=200):
    """Gemailde winkels met een NIEUWERE afgeronde meting dan waar we ze al over mailden."""
    return _sql(f"""
        SELECT b.webshop_url, b.email, u.ronde
          FROM benadering b
          JOIN LATERAL (SELECT u.ronde FROM categorie_uitkomsten u JOIN categorie_rondes r ON r.id = u.ronde
                         WHERE u.webshop_url = b.webshop_url AND r.afgerond_op IS NOT NULL
                           AND coalesce(u.telbaar, 0) >= 3
                      ORDER BY u.ronde DESC LIMIT 1) u ON TRUE
         WHERE b.email IS NOT NULL AND b.email <> ''
           AND b.gemaild_op IS NOT NULL AND b.gemaild_op < now() - interval '14 days'
           AND NOT b.afgemeld AND b.bounce_op IS NULL AND b.klacht_op IS NULL AND b.antwoord_op IS NULL
           AND coalesce(b.soort, 'winkel') = 'winkel'
           AND (b.seizoen_op IS NULL OR b.seizoen_op < now() - interval '{RUST_DAGEN} days')
           AND u.ronde <> coalesce(b.beweging_ronde, 0)
           AND NOT EXISTS (SELECT 1 FROM klanten k WHERE k.webshop_url = b.webshop_url)
      ORDER BY b.gemaild_op
         LIMIT %s""", (limiet,), alles=True) or []


def vandaag_verstuurd():
    rij = _sql("SELECT count(*) AS n FROM benadering WHERE beweging_op >= date_trunc('day', now())")
    return int((rij or {}).get("n") or 0)


def ronde(basis_url, bouw_beeld, categorienaam=None, verstuur=None, binnen_kantooruren=True, aan=True):
    verslag = {"verstuurd": 0, "geen_nieuws": 0}
    if not aan or not binnen_kantooruren:
        return verslag
    ruimte = min(PER_RONDE, max(0, PER_DAG - vandaag_verstuurd()))
    if not ruimte:
        return verslag
    import verkoopagent as va
    if verstuur is None:
        import emailing
        verstuur = emailing.send_opvolging
    for w in kandidaten():
        if verslag["verstuurd"] >= ruimte:
            break
        url = w["webshop_url"]
        try:
            beeld = bouw_beeld(url)
        except Exception:
            beeld = None
        # Deze meting is bekeken, wat er ook uitkomt: niet elke ronde opnieuw.
        _sql("UPDATE benadering SET beweging_ronde = %s WHERE webshop_url = %s", (w["ronde"], url))
        if not beeld or not is_beweging(beeld.get("positie"), beeld.get("vorige_positie")):
            verslag["geen_nieuws"] += 1
            continue
        token = db.get_benchmark_token(url)
        bericht = va.maak_maandbericht(beeld, link_url=f"{basis_url}/uitkomst/{token}" if token else basis_url,
                                       categorienaam=categorienaam(beeld) if categorienaam else None)
        if not bericht:
            continue
        _sql("UPDATE benadering SET seizoen_op = now(), beweging_op = now() WHERE webshop_url = %s", (url,))
        afmeld = f"{basis_url}/afmelden/{token}" if token else None
        if verstuur(w["email"], bericht["onderwerp"], bericht["alineas"], bericht["link"], afmeld_url=afmeld):
            verslag["verstuurd"] += 1
    return verslag
