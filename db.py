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


def save_report(report_type, webshop_url, email, score, checks, fixes=None, payment_id=None):
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
                    """INSERT INTO rapporten (token, type, webshop_url, email, score, checks, fixes, payment_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (token, report_type, webshop_url, email, score,
                     json.dumps(checks), json.dumps(fixes) if fixes is not None else None, payment_id),
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
