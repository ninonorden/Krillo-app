"""
Krillo - database.

Bewaart audit-resultaten en scan-geschiedenis, zodat elke klant een eigen,
blijvende rapportpagina heeft in plaats van dat alles alleen in een e-mail
staat. Gebruikt een gratis Neon Postgres-database.

Vereist de omgevingsvariabele DATABASE_URL in Render (de connection string
uit Neon).
"""

import os
import json
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor


def _get_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    return psycopg2.connect(db_url)


def init_db():
    """Maakt de benodigde tabel aan als die nog niet bestaat. Veilig om
    bij elke opstart opnieuw aan te roepen."""
    conn = _get_connection()
    if conn is None:
        print("Database niet geconfigureerd, sla init_db over.")
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS rapporten (
                        token TEXT PRIMARY KEY,
                        type TEXT NOT NULL,
                        webshop_url TEXT NOT NULL,
                        email TEXT NOT NULL,
                        score INTEGER NOT NULL,
                        checks JSONB NOT NULL,
                        fixes JSONB,
                        payment_id TEXT,
                        aangemaakt_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                # Voor bestaande installaties: kolom toevoegen als die nog mist.
                cur.execute("ALTER TABLE rapporten ADD COLUMN IF NOT EXISTS payment_id TEXT;")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS verwerkte_betalingen (
                        payment_id TEXT PRIMARY KEY,
                        verwerkt_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS klanten (
                        klant_token TEXT PRIMARY KEY,
                        webshop_url TEXT NOT NULL UNIQUE,
                        email TEXT NOT NULL,
                        aangemaakt_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS facturen (
                        factuurnummer SERIAL PRIMARY KEY,
                        payment_id TEXT UNIQUE,
                        email TEXT,
                        bedrijfsnaam TEXT,
                        omschrijving TEXT,
                        bedrag NUMERIC(10,2),
                        aangemaakt_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS toestemmingen (
                        id SERIAL PRIMARY KEY,
                        payment_id TEXT,
                        email TEXT,
                        webshop_url TEXT,
                        type TEXT,
                        voorwaarden_akkoord BOOLEAN,
                        directe_uitvoering_akkoord BOOLEAN,
                        vastgelegd_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS herroepingen (
                        id SERIAL PRIMARY KEY,
                        email TEXT NOT NULL,
                        webshop_url TEXT,
                        toelichting TEXT,
                        status TEXT DEFAULT 'ontvangen',
                        ontvangen_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS koopvragen (
                        id SERIAL PRIMARY KEY,
                        webshop_url TEXT NOT NULL,
                        vraag TEXT NOT NULL,
                        intentie TEXT,
                        actief BOOLEAN DEFAULT true,
                        aangemaakt_op TIMESTAMPTZ DEFAULT now(),
                        UNIQUE (webshop_url, vraag)
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS winkelprofielen (
                        webshop_url TEXT PRIMARY KEY,
                        omschrijving TEXT,
                        bijgewerkt_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ai_antwoorden (
                        id SERIAL PRIMARY KEY,
                        meting_id TEXT NOT NULL,
                        webshop_url TEXT NOT NULL,
                        vraag_id INTEGER,
                        vraag TEXT NOT NULL,
                        intentie TEXT,
                        provider TEXT,
                        model TEXT,
                        antwoord TEXT,
                        gelukt BOOLEAN DEFAULT true,
                        foutsoort TEXT,
                        invoer_tokens INTEGER DEFAULT 0,
                        uitvoer_tokens INTEGER DEFAULT 0,
                        duur_ms INTEGER,
                        gesteld_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS beoordelingen (
                        id SERIAL PRIMARY KEY,
                        antwoord_id INTEGER NOT NULL UNIQUE,
                        meting_id TEXT NOT NULL,
                        webshop_url TEXT NOT NULL,
                        vraag TEXT,
                        intentie TEXT,
                        model TEXT,
                        winkel_kon_genoemd BOOLEAN,
                        genoemd BOOLEAN,
                        positie INTEGER,
                        aantal_winkels INTEGER,
                        aanbevolen BOOLEAN,
                        toon TEXT,
                        bewijs TEXT,
                        winkels JSONB,
                        merken JSONB,
                        aanbevolen_winkels JSONB,
                        beoordeeld_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur.execute("ALTER TABLE beoordelingen ADD COLUMN IF NOT EXISTS bewijs TEXT;")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_beoordelingen_meting ON beoordelingen (webshop_url, meting_id);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_antwoorden_webshop ON ai_antwoorden (webshop_url, gesteld_op);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_antwoorden_meting ON ai_antwoorden (meting_id);")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS kostengebeurtenissen (
                        gebeurtenis_id TEXT PRIMARY KEY,
                        soort TEXT NOT NULL,
                        provider TEXT,
                        model TEXT,
                        invoer_tokens INTEGER DEFAULT 0,
                        uitvoer_tokens INTEGER DEFAULT 0,
                        kosten NUMERIC(12,6),
                        kosten_status TEXT,
                        prijsversie TEXT,
                        webshop_url TEXT,
                        email TEXT,
                        scan_id TEXT,
                        duur_ms INTEGER,
                        gelukt BOOLEAN DEFAULT true,
                        foutsoort TEXT,
                        pogingen INTEGER DEFAULT 1,
                        moment TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_kosten_webshop ON kostengebeurtenissen (webshop_url, moment);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_kosten_scan ON kostengebeurtenissen (scan_id);")
                cur.execute("ALTER TABLE rapporten ADD COLUMN IF NOT EXISTS klant_token TEXT;")
    finally:
        conn.close()


def claim_payment(payment_id):
    """Probeert een betaling als 'in behandeling' te markeren. Geeft True terug
    als dit de eerste keer is, en False als deze betaling al eerder verwerkt is.
    Voorkomt dat een herhaalde melding van Mollie een tweede e-mail oplevert."""
    conn = _get_connection()
    if conn is None:
        # Zonder database kunnen we niets vastleggen, dan maar doorgaan.
        return True
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO verwerkte_betalingen (payment_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (payment_id,),
                )
                return cur.rowcount > 0
    except Exception as e:
        print(f"Betaling claimen mislukt: {e}")
        return True
    finally:
        conn.close()


def bewaar_kostengebeurtenis(gegevens):
    """Legt een kostenveroorzakende verrichting vast. Dezelfde gebeurtenis
    wordt nooit twee keer geteld, ook niet bij een herhaalde melding."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO kostengebeurtenissen
                       (gebeurtenis_id, soort, provider, model, invoer_tokens, uitvoer_tokens,
                        kosten, kosten_status, prijsversie, webshop_url, email, scan_id,
                        duur_ms, gelukt, foutsoort, pogingen)
                       VALUES (%(gebeurtenis_id)s, %(soort)s, %(provider)s, %(model)s,
                               %(invoer_tokens)s, %(uitvoer_tokens)s, %(kosten)s, %(kosten_status)s,
                               %(prijsversie)s, %(webshop_url)s, %(email)s, %(scan_id)s,
                               %(duur_ms)s, %(gelukt)s, %(foutsoort)s, %(pogingen)s)
                       ON CONFLICT (gebeurtenis_id) DO NOTHING""",
                    gegevens,
                )
                return cur.rowcount > 0
    except Exception as e:
        print(f"Kostengebeurtenis bewaren mislukt: {e}")
        return False
    finally:
        conn.close()


def kosten_per_scan(scan_id):
    return _kosten_optellen("scan_id = %s", (scan_id,))


def kosten_per_klant_deze_maand(webshop_url):
    return _kosten_optellen(
        "webshop_url = %s AND moment >= date_trunc('month', now())", (webshop_url,)
    )


def kosten_vandaag():
    return _kosten_optellen("moment >= date_trunc('day', now())", ())


def _kosten_optellen(voorwaarde, waarden):
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    f"""SELECT COUNT(*) AS aantal,
                               COALESCE(SUM(kosten), 0) AS kosten,
                               COALESCE(SUM(invoer_tokens + uitvoer_tokens), 0) AS tokens,
                               COUNT(*) FILTER (WHERE NOT gelukt) AS mislukt,
                               COUNT(*) FILTER (WHERE kosten_status = 'onbekend') AS onbekende_prijs
                        FROM kostengebeurtenissen WHERE {voorwaarde}""",
                    waarden,
                )
                rij = cur.fetchone()
                if rij:
                    rij = dict(rij)
                    rij["kosten"] = float(rij["kosten"] or 0)
                return rij
    except Exception as e:
        print(f"Kosten optellen mislukt: {e}")
        return None
    finally:
        conn.close()


def kostenoverzicht(dagen=30):
    """Overzicht voor de beheerpagina: per klant en per model."""
    conn = _get_connection()
    if conn is None:
        return {"per_klant": [], "per_model": [], "totaal": None}
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT webshop_url, COUNT(*) AS aantal,
                              COALESCE(SUM(kosten),0) AS kosten,
                              COALESCE(SUM(invoer_tokens + uitvoer_tokens),0) AS tokens
                       FROM kostengebeurtenissen
                       WHERE moment >= now() - (%s || ' days')::interval
                       GROUP BY webshop_url ORDER BY kosten DESC LIMIT 25""",
                    (dagen,),
                )
                per_klant = [dict(r) for r in cur.fetchall()]

                cur.execute(
                    """SELECT provider, model, COUNT(*) AS aantal,
                              COALESCE(SUM(kosten),0) AS kosten,
                              COALESCE(SUM(invoer_tokens + uitvoer_tokens),0) AS tokens
                       FROM kostengebeurtenissen
                       WHERE moment >= now() - (%s || ' days')::interval
                       GROUP BY provider, model ORDER BY kosten DESC""",
                    (dagen,),
                )
                per_model = [dict(r) for r in cur.fetchall()]

        totaal = _kosten_optellen(
            "moment >= now() - (%s || ' days')::interval", (dagen,)
        )
        for lijst in (per_klant, per_model):
            for r in lijst:
                r["kosten"] = float(r["kosten"] or 0)
        return {"per_klant": per_klant, "per_model": per_model, "totaal": totaal}
    except Exception as e:
        print(f"Kostenoverzicht ophalen mislukt: {e}")
        return {"per_klant": [], "per_model": [], "totaal": None}
    finally:
        conn.close()


def bewaar_koopvragen(webshop_url, omschrijving, vragen, vervang=False):
    """Bewaart de gegenereerde koopvragen.

    vervang=True zet eerst alle bestaande vragen van deze webshop op inactief en
    maakt daarna alleen de nieuwe set actief. Dat is wat 'opnieuw genereren'
    hoort te doen. Zonder dat stapelen de rondes op elkaar: alleen letterlijk
    identieke zinnen werden overgeslagen, dus je hield tientallen bijna-gelijke
    vragen over. De oude rijen blijven staan, ze zijn alleen niet meer actief,
    zodat we later kunnen terugkijken wat er ooit bedacht is."""
    conn = _get_connection()
    if conn is None:
        return 0
    nieuw = 0
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO winkelprofielen (webshop_url, omschrijving)
                       VALUES (%s, %s)
                       ON CONFLICT (webshop_url) DO UPDATE
                       SET omschrijving = EXCLUDED.omschrijving, bijgewerkt_op = now()""",
                    (webshop_url, omschrijving),
                )
                if vervang:
                    cur.execute(
                        "UPDATE koopvragen SET actief = false WHERE webshop_url = %s",
                        (webshop_url,),
                    )
                for v in vragen:
                    cur.execute(
                        """INSERT INTO koopvragen (webshop_url, vraag, intentie)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (webshop_url, vraag) DO UPDATE
                           SET actief = true, intentie = EXCLUDED.intentie""",
                        (webshop_url, v["vraag"], v.get("intentie")),
                    )
                    nieuw += cur.rowcount
        return nieuw
    except Exception as e:
        print(f"Koopvragen bewaren mislukt: {e}")
        return 0
    finally:
        conn.close()


def zet_vraag_uit(webshop_url, vraag):
    """Zet een vraag op inactief in plaats van hem te verwijderen, zodat we
    later nog kunnen zien wat er ooit bedacht is."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE koopvragen SET actief = false WHERE webshop_url = %s AND vraag = %s",
                    (webshop_url, vraag),
                )
                return cur.rowcount > 0
    except Exception as e:
        print(f"Vraag uitzetten mislukt: {e}")
        return False
    finally:
        conn.close()


def get_winkelprofiel(webshop_url):
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM winkelprofielen WHERE webshop_url = %s", (webshop_url,))
                return cur.fetchone()
    except Exception as e:
        print(f"Winkelprofiel ophalen mislukt: {e}")
        return None
    finally:
        conn.close()


def get_koopvragen(webshop_url, alleen_actief=True):
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if alleen_actief:
                    cur.execute(
                        "SELECT * FROM koopvragen WHERE webshop_url = %s AND actief = true ORDER BY intentie, id",
                        (webshop_url,),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM koopvragen WHERE webshop_url = %s ORDER BY intentie, id",
                        (webshop_url,),
                    )
                return cur.fetchall()
    except Exception as e:
        print(f"Koopvragen ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def bewaar_ai_antwoord(gegevens):
    """Bewaart een antwoord van een AI-model op een koopvraag, inclusief de
    volledige tekst. Die tekst is het hele punt: als we later slimmer leren
    beoordelen, willen we dat op oude antwoorden opnieuw kunnen doen."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO ai_antwoorden
                       (meting_id, webshop_url, vraag_id, vraag, intentie, provider, model,
                        antwoord, gelukt, foutsoort, invoer_tokens, uitvoer_tokens, duur_ms)
                       VALUES (%(meting_id)s, %(webshop_url)s, %(vraag_id)s, %(vraag)s,
                               %(intentie)s, %(provider)s, %(model)s, %(antwoord)s,
                               %(gelukt)s, %(foutsoort)s, %(invoer_tokens)s,
                               %(uitvoer_tokens)s, %(duur_ms)s)""",
                    gegevens,
                )
                return True
    except Exception as e:
        print(f"AI-antwoord bewaren mislukt: {e}")
        return False
    finally:
        conn.close()


def get_metingen(webshop_url, limit=20):
    """Overzicht van de meetrondes van een webshop, nieuwste eerst."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT meting_id,
                              min(gesteld_op) AS gestart_op,
                              count(*) AS aantal,
                              count(*) FILTER (WHERE gelukt) AS gelukt,
                              count(*) FILTER (WHERE NOT gelukt) AS mislukt,
                              count(DISTINCT model) AS modellen
                         FROM ai_antwoorden
                        WHERE webshop_url = %s
                     GROUP BY meting_id
                     ORDER BY min(gesteld_op) DESC
                        LIMIT %s""",
                    (webshop_url, limit),
                )
                return cur.fetchall()
    except Exception as e:
        print(f"Metingen ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def get_ai_antwoorden(webshop_url, meting_id=None, limit=200):
    """De bewaarde antwoorden zelf. Zonder meting_id de laatste ronde."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if meting_id:
                    cur.execute(
                        """SELECT * FROM ai_antwoorden
                            WHERE webshop_url = %s AND meting_id = %s
                         ORDER BY vraag, provider LIMIT %s""",
                        (webshop_url, meting_id, limit),
                    )
                else:
                    cur.execute(
                        """SELECT * FROM ai_antwoorden
                            WHERE webshop_url = %s
                              AND meting_id = (
                                  SELECT meting_id FROM ai_antwoorden
                                   WHERE webshop_url = %s
                                ORDER BY gesteld_op DESC LIMIT 1)
                         ORDER BY vraag, provider LIMIT %s""",
                        (webshop_url, webshop_url, limit),
                    )
                return cur.fetchall()
    except Exception as e:
        print(f"AI-antwoorden ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def get_webshops_met_koopvragen():
    """Voor de beheerpagina: welke webshops hebben al vragen klaarstaan."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT webshop_url,
                              count(*) FILTER (WHERE actief) AS actieve_vragen
                         FROM koopvragen
                     GROUP BY webshop_url
                     ORDER BY webshop_url"""
                )
                return cur.fetchall()
    except Exception as e:
        print(f"Webshops met koopvragen ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def leg_toestemming_vast(payment_id, email, webshop_url, type_, voorwaarden, directe_uitvoering):
    """Legt vast dat de klant akkoord ging, en waarmee precies. Dit moet je
    kunnen aantonen: een clausule in de voorwaarden alleen is niet genoeg."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO toestemmingen
                       (payment_id, email, webshop_url, type, voorwaarden_akkoord, directe_uitvoering_akkoord)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (payment_id, email, webshop_url, type_, voorwaarden, directe_uitvoering),
                )
        return True
    except Exception as e:
        print(f"Toestemming vastleggen mislukt: {e}")
        return False
    finally:
        conn.close()


def leg_herroeping_vast(email, webshop_url, toelichting):
    """Legt een herroepingsverzoek vast en geeft het volgnummer terug."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """INSERT INTO herroepingen (email, webshop_url, toelichting)
                       VALUES (%s, %s, %s) RETURNING id""",
                    (email, webshop_url, toelichting),
                )
                return cur.fetchone()["id"]
    except Exception as e:
        print(f"Herroeping vastleggen mislukt: {e}")
        return None
    finally:
        conn.close()


def maak_factuur(payment_id, email, bedrijfsnaam, omschrijving, bedrag):
    """Legt een factuur vast en geeft het factuurnummer terug. Elk nummer wordt
    maar één keer uitgegeven, en per betaling kan er maar één factuur bestaan."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT factuurnummer FROM facturen WHERE payment_id = %s", (payment_id,))
                bestaand = cur.fetchone()
                if bestaand:
                    return bestaand["factuurnummer"]
                cur.execute(
                    """INSERT INTO facturen (payment_id, email, bedrijfsnaam, omschrijving, bedrag)
                       VALUES (%s, %s, %s, %s, %s) RETURNING factuurnummer""",
                    (payment_id, email, bedrijfsnaam, omschrijving, bedrag),
                )
                return cur.fetchone()["factuurnummer"]
    except Exception as e:
        print(f"Factuur aanmaken mislukt: {e}")
        return None
    finally:
        conn.close()


def get_or_create_klant(webshop_url, email):
    """Geeft het vaste token van deze klant terug, en maakt het aan als het nog
    niet bestaat. Zo houdt een monitoring-klant altijd dezelfde pagina, ook na
    tien wekelijkse scans."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT klant_token FROM klanten WHERE webshop_url = %s", (webshop_url,))
                bestaand = cur.fetchone()
                if bestaand:
                    return bestaand["klant_token"]
                token = uuid.uuid4().hex[:16]
                cur.execute(
                    "INSERT INTO klanten (klant_token, webshop_url, email) VALUES (%s, %s, %s)",
                    (token, webshop_url, email),
                )
                return token
    except Exception as e:
        print(f"Klant aanmaken mislukt: {e}")
        return None
    finally:
        conn.close()


def get_klant(klant_token):
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM klanten WHERE klant_token = %s", (klant_token,))
                return cur.fetchone()
    except Exception as e:
        print(f"Klant ophalen mislukt: {e}")
        return None
    finally:
        conn.close()


def get_klant_rapporten(klant_token, limit=20):
    """Alle scans van deze klant, nieuwste eerst, voor de vaste klantpagina."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM rapporten WHERE klant_token = %s
                       ORDER BY aangemaakt_op DESC LIMIT %s""",
                    (klant_token, limit),
                )
                return cur.fetchall()
    except Exception as e:
        print(f"Klantrapporten ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def report_bestaat_al(payment_id):
    """Tweede blokkade: kijkt of er voor deze betaling al een rapport gemaakt is.
    Werkt ook als de eerste blokkade om wat voor reden dan ook niet aansloeg."""
    if not payment_id:
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM rapporten WHERE payment_id = %s LIMIT 1", (payment_id,))
                return cur.fetchone() is not None
    except Exception as e:
        print(f"Controle op bestaand rapport mislukt: {e}")
        return False
    finally:
        conn.close()


def save_report(report_type, webshop_url, email, score, checks, fixes=None, payment_id=None, klant_token=None):
    """Slaat een rapport op en geeft een uniek token terug waarmee het
    later opgehaald kan worden (via /rapport/<token>)."""
    conn = _get_connection()
    if conn is None:
        return None
    token = uuid.uuid4().hex[:12]
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO rapporten (token, type, webshop_url, email, score, checks, fixes, payment_id, klant_token)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (token, report_type, webshop_url, email, score,
                     json.dumps(checks), json.dumps(fixes) if fixes is not None else None,
                     payment_id, klant_token),
                )
        return token
    except Exception as e:
        print(f"Rapport opslaan mislukt: {e}")
        return None
    finally:
        conn.close()


def get_report(token):
    """Haalt één rapport op."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM rapporten WHERE token = %s", (token,))
                return cur.fetchone()
    except Exception as e:
        print(f"Rapport ophalen mislukt: {e}")
        return None
    finally:
        conn.close()


def get_previous_score(webshop_url):
    """Geeft de meest recente eerdere score voor deze webshop terug (los van
    het type rapport), voor een simpele voor/na-vergelijking bij een nieuwe
    scan. Geeft None terug als er nog geen eerder rapport is."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT score, aangemaakt_op FROM rapporten
                       WHERE webshop_url = %s
                       ORDER BY aangemaakt_op DESC LIMIT 1""",
                    (webshop_url,),
                )
                return cur.fetchone()
    except Exception as e:
        print(f"Vorige score ophalen mislukt: {e}")
        return None
    finally:
        conn.close()


def get_history(webshop_url):
    """Haalt alle eerdere monitoring-rapporten voor een webshop op, oplopend
    op datum, voor de score-geschiedenis op de rapportpagina."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT token, score, aangemaakt_op FROM rapporten
                       WHERE webshop_url = %s AND type = 'monitoring'
                       ORDER BY aangemaakt_op ASC""",
                    (webshop_url,),
                )
                return cur.fetchall()
    except Exception as e:
        print(f"Geschiedenis ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def onbeoordeelde_antwoorden(webshop_url, meting_id=None, limit=200):
    """De gelukte antwoorden van een ronde die nog niet beoordeeld zijn.

    Beoordelen kost per antwoord een AI-aanroep, dus we doen het maar een keer
    en slaan over wat al gedaan is. Zo kan je een onderbroken ronde gewoon
    hervatten zonder dubbel te betalen."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if meting_id:
                    cur.execute(
                        """SELECT a.* FROM ai_antwoorden a
                            LEFT JOIN beoordelingen b ON b.antwoord_id = a.id
                           WHERE a.webshop_url = %s AND a.meting_id = %s
                             AND a.gelukt AND b.id IS NULL
                        ORDER BY a.id LIMIT %s""",
                        (webshop_url, meting_id, limit),
                    )
                else:
                    cur.execute(
                        """SELECT a.* FROM ai_antwoorden a
                            LEFT JOIN beoordelingen b ON b.antwoord_id = a.id
                           WHERE a.webshop_url = %s AND a.gelukt AND b.id IS NULL
                             AND a.meting_id = (
                                 SELECT meting_id FROM ai_antwoorden
                                  WHERE webshop_url = %s
                               ORDER BY gesteld_op DESC LIMIT 1)
                        ORDER BY a.id LIMIT %s""",
                        (webshop_url, webshop_url, limit),
                    )
                return cur.fetchall()
    except Exception as e:
        print(f"Onbeoordeelde antwoorden ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def bewaar_beoordeling(gegevens):
    """Bewaart wat de AI uit een antwoord gehaald heeft. Een antwoord wordt maar
    een keer beoordeeld, vandaar ON CONFLICT DO NOTHING op antwoord_id."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO beoordelingen
                       (antwoord_id, meting_id, webshop_url, vraag, intentie, model,
                        winkel_kon_genoemd, genoemd, positie, aantal_winkels,
                        aanbevolen, toon, bewijs, winkels, merken, aanbevolen_winkels)
                       VALUES (%(antwoord_id)s, %(meting_id)s, %(webshop_url)s, %(vraag)s,
                               %(intentie)s, %(model)s, %(winkel_kon_genoemd)s, %(genoemd)s,
                               %(positie)s, %(aantal_winkels)s, %(aanbevolen)s, %(toon)s,
                               %(bewijs)s, %(winkels)s, %(merken)s, %(aanbevolen_winkels)s)
                       ON CONFLICT (antwoord_id) DO NOTHING""",
                    gegevens,
                )
        return True
    except Exception as e:
        print(f"Beoordeling bewaren mislukt: {e}")
        return False
    finally:
        conn.close()


def get_beoordelingen(webshop_url, meting_id=None, limit=200):
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if meting_id:
                    cur.execute(
                        """SELECT * FROM beoordelingen
                            WHERE webshop_url = %s AND meting_id = %s
                         ORDER BY intentie, vraag, model LIMIT %s""",
                        (webshop_url, meting_id, limit),
                    )
                else:
                    cur.execute(
                        """SELECT * FROM beoordelingen
                            WHERE webshop_url = %s
                              AND meting_id = (
                                  SELECT meting_id FROM beoordelingen
                                   WHERE webshop_url = %s
                                ORDER BY beoordeeld_op DESC LIMIT 1)
                         ORDER BY intentie, vraag, model LIMIT %s""",
                        (webshop_url, webshop_url, limit),
                    )
                return cur.fetchall()
    except Exception as e:
        print(f"Beoordelingen ophalen mislukt: {e}")
        return []
    finally:
        conn.close()
