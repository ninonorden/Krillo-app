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
                # Waar deze betalende klant vandaan kwam. Voor bestaande
                # installaties bijgezet, want de tabel bestond al.
                cur.execute("ALTER TABLE facturen ADD COLUMN IF NOT EXISTS bron TEXT;")
                # De winkels die onze Shopify-app geïnstalleerd hebben.
                #
                # De toegangssleutel staat hier in platte tekst. Dat is niet
                # mooi, maar het is wel hoe het werkt: we moeten hem kunnen
                # gebruiken en Shopify geeft hem maar één keer. Wat we er wel
                # aan doen: bij het verwijderen van de app wordt hij meteen
                # gewist, en shop/redact gooit alles weg.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS shopify_winkels (
                        winkel TEXT PRIMARY KEY,
                        toegangssleutel TEXT,
                        rechten TEXT,
                        webshop_url TEXT,
                        email TEXT,
                        naam TEXT,
                        actief BOOLEAN NOT NULL DEFAULT true,
                        geinstalleerd_op TIMESTAMPTZ DEFAULT now(),
                        verwijderd_op TIMESTAMPTZ
                    );
                """)
                # Wat wij in de winkel van een klant veranderd hebben, met de
                # oude tekst erbij. Dit is geen logboek voor onszelf maar het
                # product: we beloven dat de klant alles kan terugzetten, en
                # zonder de oude waarde is die belofte niet waar te maken.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS wijzigingen (
                        id SERIAL PRIMARY KEY,
                        webshop_url TEXT NOT NULL,
                        taak_id TEXT NOT NULL,
                        wat TEXT NOT NULL,
                        waar TEXT,
                        oude_waarde TEXT,
                        nieuwe_waarde TEXT,
                        gedaan_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS wijzigingen_uniek
                               ON wijzigingen (webshop_url, taak_id);""")
                # De werklijst voor "wij voeren het uit". Dit is bewust een
                # eigen tabel en geen vlaggetje bij het rapport: het is een
                # opdracht die dagen loopt en die van hand tot hand gaat.
                # Zolang dit handwerk is, is deze tabel het product.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS uitvoeringen (
                        id SERIAL PRIMARY KEY,
                        payment_id TEXT UNIQUE,
                        webshop_url TEXT NOT NULL,
                        email TEXT NOT NULL,
                        platform TEXT,
                        stand TEXT NOT NULL DEFAULT 'wacht_op_toegang',
                        notitie TEXT,
                        aangemaakt_op TIMESTAMPTZ DEFAULT now(),
                        toegang_op TIMESTAMPTZ,
                        opgeleverd_op TIMESTAMPTZ
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
                cur.execute("ALTER TABLE winkelprofielen ADD COLUMN IF NOT EXISTS platform TEXT;")
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
                        soort_vermelding TEXT,
                        winkels JSONB,
                        merken JSONB,
                        aanbevolen_winkels JSONB,
                        beoordeeld_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur.execute("ALTER TABLE beoordelingen ADD COLUMN IF NOT EXISTS bewijs TEXT;")
                cur.execute("ALTER TABLE beoordelingen ADD COLUMN IF NOT EXISTS soort_vermelding TEXT;")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS uitspraakcontroles (
                        id SERIAL PRIMARY KEY,
                        meting_id TEXT NOT NULL,
                        webshop_url TEXT NOT NULL,
                        vraag TEXT,
                        uitspraak TEXT,
                        oordeel TEXT,
                        watzegtdesite TEXT,
                        toelichting TEXT,
                        gecontroleerd_op TIMESTAMPTZ DEFAULT now(),
                        UNIQUE (meting_id, uitspraak)
                    );
                """)
                # Fase 5 punt 14: waar staan de winkels die AI wel noemt.
                # Per externe pagina leggen we vast wie erop voorkwam. Bewust
                # de losse vindplaatsen bewaren en niet alleen de optelling:
                # leren we later beter zoeken of beter matchen, dan willen we
                # dat op de oude vindplaatsen opnieuw kunnen doen. Dezelfde
                # afspraak als bij de AI-antwoorden.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS bronvindplaatsen (
                        id SERIAL PRIMARY KEY,
                        meting_id TEXT NOT NULL,
                        webshop_url TEXT NOT NULL,
                        vraag TEXT,
                        bron_url TEXT NOT NULL,
                        bron_titel TEXT,
                        bron_domein TEXT,
                        eigen_site_van TEXT,
                        wij_genoemd BOOLEAN DEFAULT false,
                        concurrenten JSONB,
                        gevonden_op TIMESTAMPTZ DEFAULT now(),
                        UNIQUE (meting_id, vraag, bron_url)
                    );
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_bronnen_meting "
                            "ON bronvindplaatsen (webshop_url, meting_id);")
                # Fase 5 punt 15: de kant-en-klare oplossing bij elke taak.
                # Eén keer laten schrijven en dan bewaren. Elke week opnieuw
                # laten schrijven kost geld en levert alleen een andere
                # formulering op voor hetzelfde probleem.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS taakoplossingen (
                        webshop_url TEXT NOT NULL,
                        taak_id TEXT NOT NULL,
                        titel TEXT,
                        oplossing TEXT,
                        waar TEXT,
                        gemaakt_op TIMESTAMPTZ DEFAULT now(),
                        PRIMARY KEY (webshop_url, taak_id)
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS gratis_scans (
                        id SERIAL PRIMARY KEY,
                        webshop_url TEXT,
                        score INTEGER,
                        gelukt BOOLEAN DEFAULT true,
                        foutsoort TEXT,
                        herkomst TEXT,
                        gedaan_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_gratis_scans_dag ON gratis_scans (gedaan_op);")
                # De gratis zichtbaarheidstest. Hier staat wel een e-mailadres
                # in, anders dan bij gratis_scans, want de uitslag wordt
                # gemaild. Daarom ook nieuwsbrief_akkoord apart: het aanvragen
                # van de uitslag is iets anders dan toestemming voor latere
                # berichten, en die twee moeten los vastliggen.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS zichtbaarheidstests (
                        id SERIAL PRIMARY KEY,
                        webshop_url TEXT NOT NULL,
                        email TEXT NOT NULL,
                        status TEXT DEFAULT 'wachtrij',
                        resultaat JSONB,
                        meting_id TEXT,
                        foutsoort TEXT,
                        nieuwsbrief_akkoord BOOLEAN DEFAULT false,
                        hergebruikt BOOLEAN DEFAULT false,
                        akkoord_op TIMESTAMPTZ,
                        herkomst TEXT,
                        aangevraagd_op TIMESTAMPTZ DEFAULT now(),
                        klaar_op TIMESTAMPTZ
                    );
                """)
                cur.execute("ALTER TABLE zichtbaarheidstests ADD COLUMN IF NOT EXISTS hergebruikt BOOLEAN DEFAULT false;")
                cur.execute("ALTER TABLE zichtbaarheidstests ADD COLUMN IF NOT EXISTS soort TEXT DEFAULT 'volledig';")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_zichtbaarheid_url ON zichtbaarheidstests (webshop_url, aangevraagd_op);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_zichtbaarheid_dag ON zichtbaarheidstests (aangevraagd_op);")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_controles_meting ON uitspraakcontroles (webshop_url, meting_id);")
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
        # Zonder database kunnen we niet vastleggen dat we deze betaling al
        # gezien hebben. Dan NIET doorgaan: anders levert elke herhaling van
        # Mollie een tweede factuur, een tweede audit en een tweede mail op.
        # Een gemiste verwerking is te herstellen, een dubbele niet.
        print("Betaling niet geclaimd: geen database. Verwerking overgeslagen.")
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO verwerkte_betalingen (payment_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (payment_id,),
                )
                return cur.rowcount > 0
    except Exception as e:
        print(f"Betaling claimen mislukt, verwerking overgeslagen: {e}")
        return False
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


def bewaar_shopify_winkel(winkel, toegangssleutel, rechten=None, webshop_url=None,
                          email=None, naam=None):
    """Legt een geïnstalleerde Shopify-winkel vast, of werkt hem bij.

    Installeert iemand opnieuw, dan hoort de nieuwe sleutel de oude te
    vervangen en moet de winkel weer op actief. Anders blijft er een dode
    sleutel staan van een winkel die wel gewoon werkt."""
    if not winkel or not toegangssleutel:
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO shopify_winkels
                           (winkel, toegangssleutel, rechten, webshop_url, email, naam,
                            actief, geinstalleerd_op, verwijderd_op)
                       VALUES (%s, %s, %s, %s, %s, %s, true, now(), NULL)
                       ON CONFLICT (winkel) DO UPDATE
                       SET toegangssleutel = EXCLUDED.toegangssleutel,
                           rechten = EXCLUDED.rechten,
                           webshop_url = coalesce(EXCLUDED.webshop_url, shopify_winkels.webshop_url),
                           email = coalesce(EXCLUDED.email, shopify_winkels.email),
                           naam = coalesce(EXCLUDED.naam, shopify_winkels.naam),
                           actief = true,
                           geinstalleerd_op = now(),
                           verwijderd_op = NULL""",
                    (winkel, toegangssleutel, rechten, webshop_url, email, naam),
                )
        return True
    except Exception as e:
        print(f"Shopify-winkel bewaren mislukt voor {winkel}: {e}")
        return False
    finally:
        conn.close()


def get_shopify_winkel(winkel):
    """Eén geïnstalleerde winkel, of None."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM shopify_winkels WHERE winkel = %s", (winkel,))
                return cur.fetchone()
    except Exception as e:
        print(f"Shopify-winkel ophalen mislukt voor {winkel}: {e}")
        return None
    finally:
        conn.close()


def get_shopify_winkels(alleen_actief=True):
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if alleen_actief:
                    cur.execute("""SELECT * FROM shopify_winkels WHERE actief
                                    ORDER BY geinstalleerd_op DESC""")
                else:
                    cur.execute("SELECT * FROM shopify_winkels ORDER BY geinstalleerd_op DESC")
                return cur.fetchall()
    except Exception as e:
        print(f"Shopify-winkels ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def shopify_verwijderd(winkel):
    """De app is uit deze winkel gehaald.

    De toegangssleutel wordt meteen gewist. Hij werkt toch niet meer, en een
    sleutel die nergens meer voor dient hoort niet in een database te staan."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE shopify_winkels
                                  SET actief = false, toegangssleutel = NULL,
                                      verwijderd_op = now()
                                WHERE winkel = %s""", (winkel,))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Shopify-verwijdering vastleggen mislukt voor {winkel}: {e}")
        return False
    finally:
        conn.close()


def wis_shopify_winkel(winkel):
    """Alles van deze winkel weggooien, voor de verplichte shop/redact.

    Shopify stuurt die 48 uur nadat de app verwijderd is, en dan MOET alles
    weg. Niet alleen de rij hierboven: ook wat we over die webshop gemeten en
    geschreven hebben, want dat gaat over hem."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT webshop_url FROM shopify_winkels WHERE winkel = %s",
                            (winkel,))
                rij = cur.fetchone()
                webshop_url = (rij or {}).get("webshop_url")
                cur.execute("DELETE FROM shopify_winkels WHERE winkel = %s", (winkel,))

                if webshop_url:
                    # Alle tabellen die op de webshop-URL staan. Bewust een
                    # vaste lijst en geen slimmigheid over alle tabellen heen:
                    # een tabel die je vergeet valt zo op bij het lezen, een
                    # lus over de hele database niet.
                    for tabel in ("wijzigingen", "uitvoeringen", "taakoplossingen",
                                  "bronvindplaatsen", "winkelprofielen", "klanten",
                                  "rapporten", "gratis_scans", "zichtbaarheidstests",
                                  "beoordelingen", "uitspraakcontroles", "koopvragen",
                                  "ai_antwoorden"):
                        # Elk wissen in een eigen tussenstap. Een tabel die niet
                        # bestaat of geen webshop_url heeft laat anders de hele
                        # transactie sneuvelen, en dan wordt er NIETS gewist
                        # terwijl Shopify eist dat alles weg is.
                        cur.execute("SAVEPOINT per_tabel")
                        try:
                            cur.execute(
                                f"DELETE FROM {tabel} WHERE webshop_url = %s",
                                (webshop_url,))
                            cur.execute("RELEASE SAVEPOINT per_tabel")
                        except Exception as e:
                            print(f"Wissen uit {tabel} overgeslagen: {e}")
                            cur.execute("ROLLBACK TO SAVEPOINT per_tabel")

                    # De kostenregels blijven staan maar zonder de winkelnaam.
                    # De regels zelf zijn onze eigen boekhouding: gooi je die
                    # weg, dan klopt je uitgavenoverzicht niet meer. Het adres
                    # van de winkel hoeft er niet in te blijven staan.
                    cur.execute("SAVEPOINT per_tabel")
                    try:
                        cur.execute("""UPDATE kostengebeurtenissen SET webshop_url = NULL
                                        WHERE webshop_url = %s""", (webshop_url,))
                        cur.execute("RELEASE SAVEPOINT per_tabel")
                    except Exception as e:
                        print(f"Kostenregels anonimiseren overgeslagen: {e}")
                        cur.execute("ROLLBACK TO SAVEPOINT per_tabel")

                    # BEWUST NIET GEWIST: facturen, toestemmingen en
                    # herroepingen. Daar zit een wettelijke bewaarplicht op:
                    # een factuur moet zeven jaar bewaard blijven, en een
                    # vastgelegd akkoord en een herroepingsverzoek zijn het
                    # bewijs dat wij ons aan de regels gehouden hebben. Die
                    # plicht gaat voor op een wisverzoek. Dit hoort meegenomen
                    # te worden in de juridische controle die al op de roadmap
                    # staat, want het is een afweging en geen zekerheid.
        return True
    except Exception as e:
        print(f"Shopify-winkel wissen mislukt voor {winkel}: {e}")
        return False
    finally:
        conn.close()


def bewaar_wijziging(webshop_url, taak_id, wat, waar=None, oude_waarde=None,
                     nieuwe_waarde=None):
    """Legt vast wat wij bij een klant veranderd hebben.

    Per taak per winkel één regel: sla je hem nog eens op, dan wordt de vorige
    bijgewerkt. Zo kan je tijdens het werk tussentijds opslaan zonder dat er
    tien halve regels ontstaan.

    De oude waarde is het belangrijkste veld van de hele tabel. Zonder dat kan
    een klant niets terugzetten, en dat is wel wat we hem beloofd hebben."""
    if not webshop_url or not taak_id:
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO wijzigingen
                           (webshop_url, taak_id, wat, waar, oude_waarde, nieuwe_waarde)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (webshop_url, taak_id) DO UPDATE
                       SET wat = EXCLUDED.wat,
                           waar = EXCLUDED.waar,
                           oude_waarde = EXCLUDED.oude_waarde,
                           nieuwe_waarde = EXCLUDED.nieuwe_waarde,
                           gedaan_op = now()""",
                    (webshop_url, taak_id, wat, waar, oude_waarde, nieuwe_waarde),
                )
        return True
    except Exception as e:
        print(f"Wijziging bewaren mislukt voor {webshop_url}, taak {taak_id}: {e}")
        return False
    finally:
        conn.close()


def get_wijzigingen(webshop_url):
    """Alles wat wij bij deze winkel veranderd hebben, oudste eerst.

    Oudste eerst omdat dit als overzicht naar de klant gaat en dan de volgorde
    van het werk aanhoudt."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""SELECT * FROM wijzigingen WHERE webshop_url = %s
                                ORDER BY gedaan_op""", (webshop_url,))
                return cur.fetchall()
    except Exception as e:
        print(f"Wijzigingen ophalen mislukt voor {webshop_url}: {e}")
        return []
    finally:
        conn.close()


def verwijder_wijziging(webshop_url, taak_id):
    """Haalt één vastgelegde wijziging weg. Voor als je je vergist hebt."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM wijzigingen WHERE webshop_url = %s AND taak_id = %s",
                            (webshop_url, taak_id))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Wijziging verwijderen mislukt voor {webshop_url}: {e}")
        return False
    finally:
        conn.close()


# De standen die een uitvoering kan hebben, op volgorde. Bewust een korte,
# vaste lijst: elke extra stand is een vraag die je jezelf elke dag opnieuw moet
# stellen, en dat is precies wat een werklijst onbruikbaar maakt.
UITVOERING_STANDEN = ["wacht_op_toegang", "bezig", "opgeleverd", "afgebroken"]

UITVOERING_STAND_TEKST = {
    "wacht_op_toegang": "Wacht op toegang",
    "bezig": "Bezig",
    "opgeleverd": "Opgeleverd",
    "afgebroken": "Afgebroken",
}


def start_uitvoering(payment_id, webshop_url, email, platform=None):
    """Zet een betaalde uitvoering op de werklijst.

    Geeft True terug als hij nu op de lijst staat, ook als hij er al stond.
    Bewust niet klappen bij een herhaling: Mollie kan dezelfde betaling twee
    keer melden, en een dubbele opdracht op de lijst is verwarrender dan een
    ontbrekende foutmelding."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO uitvoeringen (payment_id, webshop_url, email, platform)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (payment_id) DO NOTHING""",
                    (payment_id, webshop_url, email, (platform or None)),
                )
        return True
    except Exception as e:
        print(f"Uitvoering op de werklijst zetten mislukt voor {webshop_url}: {e}")
        return False
    finally:
        conn.close()


def get_uitvoeringen(webshop_url=None):
    """De werklijst, nieuwste eerst. Met een webshop-URL erbij alleen die winkel."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if webshop_url:
                    cur.execute("""SELECT * FROM uitvoeringen WHERE webshop_url = %s
                                    ORDER BY aangemaakt_op DESC""", (webshop_url,))
                else:
                    cur.execute("SELECT * FROM uitvoeringen ORDER BY aangemaakt_op DESC LIMIT 100")
                return cur.fetchall()
    except Exception as e:
        print(f"Werklijst ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def zet_uitvoering_stand(uitvoering_id, stand, notitie=None):
    """Verandert de stand van een opdracht, en zet meteen de bijbehorende datum.

    Een onbekende stand wordt geweigerd in plaats van opgeslagen. Anders staat
    er over een maand "bezigg" in de database en filtert de werklijst hem weg."""
    if stand not in UITVOERING_STANDEN:
        print(f"Onbekende stand geweigerd: {stand!r}")
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE uitvoeringen
                          SET stand = %s,
                              notitie = coalesce(%s, notitie),
                              toegang_op = CASE WHEN %s IN ('bezig','opgeleverd')
                                                 AND toegang_op IS NULL
                                                THEN now() ELSE toegang_op END,
                              opgeleverd_op = CASE WHEN %s = 'opgeleverd'
                                                   THEN now() ELSE opgeleverd_op END
                        WHERE id = %s""",
                    (stand, notitie, stand, stand, int(uitvoering_id)),
                )
                return cur.rowcount > 0
    except Exception as e:
        print(f"Stand aanpassen mislukt voor uitvoering {uitvoering_id}: {e}")
        return False
    finally:
        conn.close()


def maak_factuur(payment_id, email, bedrijfsnaam, omschrijving, bedrag, bron=None):
    """Legt een factuur vast en geeft het factuurnummer terug. Elk nummer wordt
    maar één keer uitgegeven, en per betaling kan er maar één factuur bestaan.

    "bron" is het campagnelabel waarmee deze klant binnenkwam, zoals het uit de
    metadata van Mollie terugkomt. Dit is de enige plek waar omzet en herkomst
    bij elkaar staan: de bezoekerstabel weet wel waar de klikken vandaan komen,
    maar niet welke klik geld werd."""
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
                    """INSERT INTO facturen (payment_id, email, bedrijfsnaam, omschrijving, bedrag, bron)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING factuurnummer""",
                    (payment_id, email, bedrijfsnaam, omschrijving, bedrag, (bron or None)),
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


def get_rapporten_voor_webshop(webshop_url, limit=20):
    """Alle scans van een webshop, ongeacht of er een klant aan hangt.

    Gebruikt door de voorbeeldweergave, zodat je de klantpagina kan bekijken
    voor een webshop waar nog geen abonnement op zit."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM rapporten WHERE webshop_url = %s
                       ORDER BY aangemaakt_op DESC LIMIT %s""",
                    (webshop_url, limit),
                )
                return cur.fetchall()
    except Exception as e:
        print(f"Rapporten van webshop ophalen mislukt: {e}")
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
                        aanbevolen, toon, bewijs, soort_vermelding,
                        winkels, merken, aanbevolen_winkels)
                       VALUES (%(antwoord_id)s, %(meting_id)s, %(webshop_url)s, %(vraag)s,
                               %(intentie)s, %(model)s, %(winkel_kon_genoemd)s, %(genoemd)s,
                               %(positie)s, %(aantal_winkels)s, %(aanbevolen)s, %(toon)s,
                               %(bewijs)s, %(soort_vermelding)s,
                               %(winkels)s, %(merken)s, %(aanbevolen_winkels)s)
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


def bewaar_uitspraakcontroles(webshop_url, meting_id, uitkomsten):
    """Bewaart wat de controle van elke uitspraak vond. Dezelfde uitspraak in
    dezelfde ronde komt er maar een keer in."""
    if not uitkomsten:
        return 0
    conn = _get_connection()
    if conn is None:
        return 0
    bewaard = 0
    try:
        with conn:
            with conn.cursor() as cur:
                for u in uitkomsten:
                    cur.execute(
                        """INSERT INTO uitspraakcontroles
                           (meting_id, webshop_url, vraag, uitspraak, oordeel,
                            watzegtdesite, toelichting)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (meting_id, uitspraak) DO NOTHING""",
                        (meting_id, webshop_url, u.get("vraag"), u.get("uitspraak"),
                         u.get("oordeel"), u.get("watzegtdesite"), u.get("toelichting")),
                    )
                    bewaard += cur.rowcount
        return bewaard
    except Exception as e:
        print(f"Uitspraakcontroles bewaren mislukt: {e}")
        return 0
    finally:
        conn.close()


def get_uitspraakcontroles(webshop_url, meting_id=None, limit=100):
    """De controles van de laatste ronde, of van een ronde naar keuze."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if meting_id:
                    cur.execute(
                        """SELECT * FROM uitspraakcontroles
                            WHERE webshop_url = %s AND meting_id = %s
                         ORDER BY id LIMIT %s""",
                        (webshop_url, meting_id, limit),
                    )
                else:
                    cur.execute(
                        """SELECT * FROM uitspraakcontroles
                            WHERE webshop_url = %s
                              AND meting_id = (
                                  SELECT meting_id FROM uitspraakcontroles
                                   WHERE webshop_url = %s
                                ORDER BY gecontroleerd_op DESC LIMIT 1)
                         ORDER BY id LIMIT %s""",
                        (webshop_url, webshop_url, limit),
                    )
                return cur.fetchall()
    except Exception as e:
        print(f"Uitspraakcontroles ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def bewaar_bronvindplaatsen(webshop_url, meting_id, vindplaatsen):
    """Bewaart wat de bronanalyse per externe pagina vond.

    Dezelfde pagina bij dezelfde vraag in dezelfde ronde komt er maar een keer
    in. Zo kan je de bronanalyse veilig opnieuw starten na een storing zonder
    dubbele regels te krijgen."""
    if not vindplaatsen:
        return 0
    conn = _get_connection()
    if conn is None:
        return 0
    bewaard = 0
    try:
        with conn:
            with conn.cursor() as cur:
                for v in vindplaatsen:
                    cur.execute(
                        """INSERT INTO bronvindplaatsen
                           (meting_id, webshop_url, vraag, bron_url, bron_titel,
                            bron_domein, eigen_site_van, wij_genoemd, concurrenten)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (meting_id, vraag, bron_url) DO NOTHING""",
                        (meting_id, webshop_url, v.get("vraag"), v.get("bron_url"),
                         v.get("bron_titel"), v.get("bron_domein"), v.get("eigen_site_van"),
                         bool(v.get("wij_genoemd")),
                         json.dumps(v.get("concurrenten") or [], ensure_ascii=False)),
                    )
                    bewaard += cur.rowcount
        return bewaard
    except Exception as e:
        print(f"Bronvindplaatsen bewaren mislukt: {e}")
        return 0
    finally:
        conn.close()


def get_bronvindplaatsen(webshop_url, meting_id=None, limit=200):
    """De vindplaatsen van de laatste ronde, of van een ronde naar keuze."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if meting_id:
                    cur.execute(
                        """SELECT * FROM bronvindplaatsen
                            WHERE webshop_url = %s AND meting_id = %s
                         ORDER BY id LIMIT %s""",
                        (webshop_url, meting_id, limit),
                    )
                else:
                    cur.execute(
                        """SELECT * FROM bronvindplaatsen
                            WHERE webshop_url = %s
                              AND meting_id = (
                                  SELECT meting_id FROM bronvindplaatsen
                                   WHERE webshop_url = %s
                                ORDER BY gevonden_op DESC LIMIT 1)
                         ORDER BY id LIMIT %s""",
                        (webshop_url, webshop_url, limit),
                    )
                return cur.fetchall()
    except Exception as e:
        print(f"Bronvindplaatsen ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def bewaar_taakoplossing(webshop_url, taak_id, titel, oplossing, waar):
    """Bewaart de kant-en-klare oplossing bij een taak uit het actieplan.

    Bewust bewaren en niet elke week opnieuw laten schrijven. Een oplossing
    voor "zet vragen en antwoorden op je site" verandert niet zolang de winkel
    niet verandert, dus opnieuw laten schrijven kost geld en levert alleen maar
    een andere formulering op. Erger nog: dan krijgt een klant elke week iets
    anders te lezen voor hetzelfde probleem, en dan lijkt het alsof er iets
    veranderd is terwijl dat niet zo is."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO taakoplossingen
                       (webshop_url, taak_id, titel, oplossing, waar)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (webshop_url, taak_id) DO UPDATE
                       SET titel = EXCLUDED.titel, oplossing = EXCLUDED.oplossing,
                           waar = EXCLUDED.waar, gemaakt_op = now()""",
                    (webshop_url, taak_id, titel, oplossing, waar),
                )
        return True
    except Exception as e:
        print(f"Taakoplossing bewaren mislukt: {e}")
        return False
    finally:
        conn.close()


def get_taakoplossingen(webshop_url):
    """Alle bewaarde oplossingen voor een winkel, als {taak_id: {...}}."""
    conn = _get_connection()
    if conn is None:
        return {}
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM taakoplossingen WHERE webshop_url = %s",
                    (webshop_url,),
                )
                return {r["taak_id"]: dict(r) for r in cur.fetchall()}
    except Exception as e:
        print(f"Taakoplossingen ophalen mislukt: {e}")
        return {}
    finally:
        conn.close()


def verwijder_taakoplossing(webshop_url, taak_id):
    """Gooit een bewaarde oplossing weg, zodat hij opnieuw geschreven wordt."""
    conn = _get_connection()
    if conn is None:
        return 0
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM taakoplossingen WHERE webshop_url = %s AND taak_id = %s",
                    (webshop_url, taak_id),
                )
                return cur.rowcount
    except Exception as e:
        print(f"Taakoplossing verwijderen mislukt: {e}")
        return 0
    finally:
        conn.close()


def verwijder_bronvindplaatsen(webshop_url, meting_id):
    """Gooit de vindplaatsen van een ronde weg, zodat een nieuwe zoekronde ze
    vervangt in plaats van erbij te zetten.

    Dit moet, en dat is met schade en schande geleerd bij de koopvragen: daar
    stapelde "opnieuw genereren" tot 478 vragen voor een winkel. Hier is het nog
    vervelender, want oude vindplaatsen zijn opgehaald met oudere, soepelere
    regels. Laat je ze staan, dan blijft afgekeurde rommel voor altijd naast de
    goede resultaten zichtbaar en zie je nooit of een verbetering geholpen
    heeft."""
    if not meting_id:
        return 0
    conn = _get_connection()
    if conn is None:
        return 0
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM bronvindplaatsen WHERE webshop_url = %s AND meting_id = %s",
                    (webshop_url, meting_id),
                )
                return cur.rowcount
    except Exception as e:
        print(f"Bronvindplaatsen verwijderen mislukt: {e}")
        return 0
    finally:
        conn.close()


def laatste_beoordeelde_meting_id(webshop_url):
    """Het id van de nieuwste meetronde die ook echt BEOORDEELD is.

    Dat is iets anders dan de nieuwste meetronde. Wordt er wel gemeten maar niet
    beoordeeld, bijvoorbeeld omdat het beoordelen afbrak, dan blijft er een
    ronde achter met antwoorden en zonder oordelen.

    Dit is de ronde die de klant op zijn pagina ziet, want get_beoordelingen()
    kiest zonder meting_id ook de nieuwste beoordeelde ronde. Alles wat naast
    die cijfers komt te staan moet dus dezelfde ronde gebruiken, anders staan er
    twee waarheden op een pagina."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT meting_id FROM beoordelingen
                        WHERE webshop_url = %s
                     ORDER BY beoordeeld_op DESC LIMIT 1""",
                    (webshop_url,),
                )
                rij = cur.fetchone()
                return rij[0] if rij else None
    except Exception as e:
        print(f"Laatste beoordeelde meting ophalen mislukt: {e}")
        return None
    finally:
        conn.close()


def laatste_meting_id(webshop_url):
    """Het id van de nieuwste meetronde van deze webshop."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT meting_id FROM ai_antwoorden WHERE webshop_url = %s
                       ORDER BY gesteld_op DESC LIMIT 1""",
                    (webshop_url,),
                )
                rij = cur.fetchone()
                return rij[0] if rij else None
    except Exception as e:
        print(f"Laatste meting ophalen mislukt: {e}")
        return None
    finally:
        conn.close()


def get_beoordelingen_rondes(webshop_url, rondes=2, limit=600):
    """De beoordelingen van de laatste paar meetrondes samen.

    get_beoordelingen geeft bewust alleen de nieuwste ronde terug, want dat is
    wat de klant moet zien. Maar om te kunnen zeggen of iemand gestegen of
    gedaald is heb je er minstens twee nodig. Zonder deze functie zou de
    vergelijking altijd op een enkele ronde uitkomen en dus nooit iets melden."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM beoordelingen
                        WHERE webshop_url = %s
                          AND meting_id IN (
                              SELECT meting_id FROM beoordelingen
                               WHERE webshop_url = %s
                            GROUP BY meting_id
                            ORDER BY max(beoordeeld_op) DESC
                               LIMIT %s)
                     ORDER BY beoordeeld_op DESC LIMIT %s""",
                    (webshop_url, webshop_url, rondes, limit),
                )
                return cur.fetchall()
    except Exception as e:
        print(f"Beoordelingen van meerdere rondes ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def verwijder_beoordelingen(webshop_url, meting_id=None):
    """Gooit de beoordelingen van een ronde weg zodat ze opnieuw gedaan worden.

    Nodig omdat de beoordelaar zelf verbetert. Voegen we een nieuw oordeel toe,
    bijvoorbeeld of het om de winkel of om een product ging, dan blijven oude
    beoordelingen dat veld leeg houden. Zonder deze functie zou je moeten
    wachten op een nieuwe meetronde om een verbetering te kunnen zien.

    De antwoorden zelf blijven staan, alleen de oordelen erover verdwijnen."""
    conn = _get_connection()
    if conn is None:
        return 0
    try:
        with conn:
            with conn.cursor() as cur:
                if meting_id:
                    cur.execute(
                        "DELETE FROM beoordelingen WHERE webshop_url = %s AND meting_id = %s",
                        (webshop_url, meting_id),
                    )
                else:
                    cur.execute(
                        """DELETE FROM beoordelingen
                            WHERE webshop_url = %s
                              AND meting_id = (
                                  SELECT meting_id FROM beoordelingen
                                   WHERE webshop_url = %s
                                ORDER BY beoordeeld_op DESC LIMIT 1)""",
                        (webshop_url, webshop_url),
                    )
                return cur.rowcount
    except Exception as e:
        print(f"Beoordelingen verwijderen mislukt: {e}")
        return 0
    finally:
        conn.close()


def bewaar_gratis_scan(webshop_url, score=None, gelukt=True, foutsoort=None, herkomst=None):
    """Legt vast dat er een gratis scan gedaan is.

    Bewust zonder IP-adres en zonder cookie. Wat we willen weten is hoeveel
    mensen scannen, welke winkels, en waar ze vandaan komen. Daar is geen enkel
    persoonsgegeven voor nodig, en dat scheelt een hoop uitleg in het
    privacybeleid.

    Mislukt dit, dan gaat de scan gewoon door. Een bezoeker mag nooit een
    foutmelding krijgen omdat wij iets niet konden opschrijven."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO gratis_scans (webshop_url, score, gelukt, foutsoort, herkomst)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (webshop_url, score, gelukt, (foutsoort or None), (herkomst or None)),
                )
        return True
    except Exception as e:
        print(f"Gratis scan vastleggen mislukt: {e}")
        return False
    finally:
        conn.close()


def scanoverzicht(dagen=30):
    """De cijfers voor de beheerpagina: per dag, per herkomst, en welke winkels
    het vaakst gescand worden.

    Sinds vandaag ook de omzet per bron. Dat is de vraag waar het bij adverteren
    en bij partners om draait: niet hoeveel bezoekers een plek oplevert, maar
    hoeveel betalende klanten. Scans en omzet worden aan elkaar geplakt op het
    label, en een bron die alleen aan de ene kant voorkomt blijft gewoon staan.
    Anders zie je een partner die drie klanten opleverde niet terug omdat er
    toevallig geen gratis scan bij zat."""
    leeg = {"totaal": {}, "per_dag": [], "per_herkomst": [], "per_bron": [],
            "top_winkels": []}
    conn = _get_connection()
    if conn is None:
        return leeg
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                sinds = f"now() - interval '{int(dagen)} days'"

                cur.execute(f"""SELECT count(*) AS scans,
                                       count(*) FILTER (WHERE gelukt) AS gelukt,
                                       count(*) FILTER (WHERE NOT gelukt) AS mislukt,
                                       count(DISTINCT webshop_url) AS winkels,
                                       round(avg(score) FILTER (WHERE gelukt)) AS gemiddelde_score
                                  FROM gratis_scans WHERE gedaan_op > {sinds}""")
                totaal = cur.fetchone() or {}

                cur.execute(f"""SELECT date_trunc('day', gedaan_op)::date AS dag, count(*) AS scans
                                  FROM gratis_scans WHERE gedaan_op > {sinds}
                              GROUP BY dag ORDER BY dag DESC LIMIT 60""")
                per_dag = cur.fetchall()

                cur.execute(f"""SELECT coalesce(herkomst, 'rechtstreeks') AS herkomst,
                                       count(*) AS scans
                                  FROM gratis_scans WHERE gedaan_op > {sinds}
                              GROUP BY 1 ORDER BY scans DESC LIMIT 20""")
                per_herkomst = cur.fetchall()

                cur.execute(f"""
                    SELECT coalesce(s.bron, f.bron) AS bron,
                           coalesce(s.scans, 0)      AS scans,
                           coalesce(f.klanten, 0)    AS klanten,
                           coalesce(f.omzet, 0)      AS omzet
                      FROM (SELECT coalesce(herkomst, 'rechtstreeks') AS bron,
                                   count(*) AS scans
                              FROM gratis_scans WHERE gedaan_op > {sinds}
                          GROUP BY 1) s
                 FULL OUTER JOIN
                           (SELECT coalesce(bron, 'rechtstreeks') AS bron,
                                   count(*) AS klanten, sum(bedrag) AS omzet
                              FROM facturen WHERE aangemaakt_op > {sinds}
                          GROUP BY 1) f
                        ON f.bron = s.bron
                  ORDER BY omzet DESC, scans DESC LIMIT 25""")
                per_bron = cur.fetchall()

                cur.execute(f"""SELECT webshop_url, count(*) AS scans, max(score) AS score
                                  FROM gratis_scans
                                 WHERE gedaan_op > {sinds} AND webshop_url IS NOT NULL
                              GROUP BY webshop_url ORDER BY scans DESC, webshop_url LIMIT 25""")
                top_winkels = cur.fetchall()

                cur.execute(f"""SELECT count(*) AS betaald FROM rapporten
                                 WHERE aangemaakt_op > {sinds} AND payment_id IS NOT NULL""")
                betaald = (cur.fetchone() or {}).get("betaald") or 0

                return {
                    "totaal": dict(totaal, betaald=betaald),
                    "per_dag": per_dag,
                    "per_herkomst": per_herkomst,
                    "per_bron": per_bron,
                    "top_winkels": top_winkels,
                }
    except Exception as e:
        print(f"Scanoverzicht ophalen mislukt: {e}")
        return leeg
    finally:
        conn.close()


def get_demo_webshops():
    """De webshops waarvoor een demo-meting gedraaid is.

    Demo's herkennen we aan het rapporttype, zodat er geen aparte tabel voor
    nodig is. Per winkel de laatste scan, en hoeveel vragen er beoordeeld zijn.
    Dat laatste is het echte teken dat de demo af is: een rapport zonder
    beoordelingen betekent dat de meting nog liep of misging."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT r.webshop_url,
                              MAX(r.aangemaakt_op) AS laatste,
                              MAX(r.score) AS score,
                              (SELECT COUNT(DISTINCT b.vraag) FROM beoordelingen b
                                WHERE b.webshop_url = r.webshop_url) AS vragen
                         FROM rapporten r
                        WHERE r.type = 'demo'
                     GROUP BY r.webshop_url
                     ORDER BY MAX(r.aangemaakt_op) DESC"""
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"Demo-webshops ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# De gratis zichtbaarheidstest (fase 5 punt 12)
# ---------------------------------------------------------------------------

def start_zichtbaarheidstest(webshop_url, email, nieuwsbrief=False, herkomst=None,
                             hergebruikt=False, soort='volledig'):
    """Legt een aanvraag vast en geeft het id terug.

    Het akkoordmoment wordt hier gezet en niet later, want dat is het bewijs
    dat iemand er zelf om gevraagd heeft. Zonder dat moment kan je bij een
    klacht niet aantonen dat een mail gevraagd was."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO zichtbaarheidstests
                       (webshop_url, email, nieuwsbrief_akkoord, akkoord_op, herkomst,
                        status, hergebruikt, soort)
                       VALUES (%s, %s, %s, now(), %s, %s, %s, %s) RETURNING id""",
                    (webshop_url, email, bool(nieuwsbrief), (herkomst or None),
                     'klaar' if hergebruikt else 'wachtrij', bool(hergebruikt), soort),
                )
                return cur.fetchone()[0]
    except Exception as e:
        print(f"Zichtbaarheidstest vastleggen mislukt: {e}")
        return None
    finally:
        conn.close()


def zet_zichtbaarheidstest(test_id, status, resultaat=None, meting_id=None, foutsoort=None):
    """Werkt een lopende test bij. Alleen de velden die meegegeven worden."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE zichtbaarheidstests
                          SET status = %s,
                              resultaat = COALESCE(%s, resultaat),
                              meting_id = COALESCE(%s, meting_id),
                              foutsoort = COALESCE(%s, foutsoort),
                              klaar_op = CASE WHEN %s IN ('klaar','mislukt') THEN now() ELSE klaar_op END
                        WHERE id = %s""",
                    (status,
                     json.dumps(resultaat, ensure_ascii=False, default=str) if resultaat is not None else None,
                     meting_id, foutsoort, status, test_id),
                )
        return True
    except Exception as e:
        print(f"Zichtbaarheidstest bijwerken mislukt: {e}")
        return False
    finally:
        conn.close()


def get_zichtbaarheidstest(test_id):
    """Een losse test op id, voor het ophalen van de uitslag door de pagina."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM zichtbaarheidstests WHERE id = %s", (test_id,))
                rij = cur.fetchone()
                return dict(rij) if rij else None
    except Exception as e:
        print(f"Zichtbaarheidstest ophalen mislukt: {e}")
        return None
    finally:
        conn.close()


def laatste_geslaagde_test(webshop_url, dagen=30, soort=None):
    """De laatste geslaagde test voor deze winkel binnen zoveel dagen.

    Hiermee hoeft dezelfde winkel niet elke keer opnieuw gemeten te worden. Dat
    scheelt niet alleen geld: iemand die de uitslag deelt en drie collega's laat
    kijken, hoort drie keer hetzelfde te zien en geen drie verschillende
    cijfers door de dagelijkse ruis in AI-antwoorden."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT * FROM zichtbaarheidstests
                        WHERE webshop_url = %s AND status = 'klaar' AND resultaat IS NOT NULL
                          AND aangevraagd_op > now() - (%s || ' days')::interval
                          AND (%s IS NULL OR COALESCE(soort, 'volledig') = %s)
                     ORDER BY aangevraagd_op DESC LIMIT 1""",
                    (webshop_url, str(int(dagen)), soort, soort),
                )
                rij = cur.fetchone()
                return dict(rij) if rij else None
    except Exception as e:
        print(f"Laatste zichtbaarheidstest ophalen mislukt: {e}")
        return None
    finally:
        conn.close()


def tel_tests_vandaag():
    """Hoeveel tests er vandaag gestart zijn. De rem op de gratis test."""
    conn = _get_connection()
    if conn is None:
        return 0
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT COUNT(*) FROM zichtbaarheidstests
                        WHERE aangevraagd_op::date = (now() AT TIME ZONE 'UTC')::date
                          AND COALESCE(hergebruikt, false) = false"""
                )
                return cur.fetchone()[0] or 0
    except Exception as e:
        print(f"Tests van vandaag tellen mislukt: {e}")
        return 0
    finally:
        conn.close()


def zichtbaarheidstest_leads(limit=200):
    """De lijst voor de beheerpagina: wie heeft de test aangevraagd."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT id, webshop_url, email, status, nieuwsbrief_akkoord,
                              herkomst, aangevraagd_op, resultaat
                         FROM zichtbaarheidstests
                        WHERE COALESCE(soort, 'volledig') = 'volledig'
                     ORDER BY aangevraagd_op DESC LIMIT %s""",
                    (limit,),
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"Leads ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def zet_platform(webshop_url, platform):
    """Bewaart op welk winkelplatform een site draait.

    Staat bij het winkelprofiel en niet bij het rapport, want het platform hoort
    bij de winkel en niet bij een losse meting. Is het onbekend, dan schrijven we
    niets weg: een gat is eerlijker dan een gok."""
    if not platform:
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO winkelprofielen (webshop_url, platform)
                       VALUES (%s, %s)
                       ON CONFLICT (webshop_url) DO UPDATE SET platform = EXCLUDED.platform""",
                    (webshop_url, platform),
                )
        return True
    except Exception as e:
        print(f"Platform bewaren mislukt: {e}")
        return False
    finally:
        conn.close()


def benchmark_regels():
    """Eén regel per winkel waarvoor een demo gedraaid is.

    Genoemd wordt per VRAAG geteld en niet per antwoord, net als overal waar een
    klant meekijkt. Anders verdubbelen de cijfers zodra er twee modellen meedoen
    en klopt de benchmark niet met wat een klant op zijn eigen pagina ziet.

    Alleen de laatste meetronde per winkel telt mee."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    WITH demos AS (
                        SELECT webshop_url,
                               MAX(score)         AS score,
                               MAX(aangemaakt_op) AS gemeten_op
                          FROM rapporten
                         WHERE type = 'demo'
                      GROUP BY webshop_url
                    ),
                    blokkade AS (
                        SELECT DISTINCT r.webshop_url
                          FROM rapporten r, jsonb_array_elements(r.checks) c
                         WHERE r.type = 'demo'
                           AND c->>'id' = 'robots'
                           AND (c->>'score')::int = 0
                    ),
                    ronde AS (
                        SELECT DISTINCT ON (webshop_url) webshop_url, meting_id
                          FROM beoordelingen
                      ORDER BY webshop_url, beoordeeld_op DESC
                    ),
                    per_vraag AS (
                        SELECT b.webshop_url, b.vraag,
                               bool_or(b.winkel_kon_genoemd)  AS telt_mee,
                               bool_or(b.genoemd)             AS genoemd,
                               bool_or(b.aanbevolen)          AS aanbevolen
                          FROM beoordelingen b
                          JOIN ronde r ON r.webshop_url = b.webshop_url
                                      AND r.meting_id  = b.meting_id
                      GROUP BY b.webshop_url, b.vraag
                    ),
                    per_winkel AS (
                        SELECT webshop_url,
                               COUNT(*) FILTER (WHERE telt_mee)                AS vragen,
                               COUNT(*) FILTER (WHERE telt_mee AND genoemd)    AS genoemd,
                               COUNT(*) FILTER (WHERE telt_mee AND aanbevolen) AS aanbevolen
                          FROM per_vraag
                      GROUP BY webshop_url
                    )
                    SELECT d.webshop_url,
                           d.score,
                           d.gemeten_op,
                           w.platform,
                           COALESCE(p.vragen, 0)     AS vragen,
                           COALESCE(p.genoemd, 0)    AS genoemd,
                           COALESCE(p.aanbevolen, 0) AS aanbevolen,
                           (bl.webshop_url IS NOT NULL) AS blokkeert_robots
                      FROM demos d
                      LEFT JOIN per_winkel p        ON p.webshop_url  = d.webshop_url
                      LEFT JOIN winkelprofielen w   ON w.webshop_url  = d.webshop_url
                      LEFT JOIN blokkade bl         ON bl.webshop_url = d.webshop_url
                  ORDER BY d.gemeten_op DESC
                """)
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"Benchmarkregels ophalen mislukt: {e}")
        return []
    finally:
        conn.close()
