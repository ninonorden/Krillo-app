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
