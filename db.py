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
import secrets

import kluis
import scan_engine
import threading
import time

import psycopg2
import psycopg2.pool
from psycopg2.extras import RealDictCursor, execute_values


# Verbindingen hergebruiken in plaats van er telkens een nieuwe opzetten.
#
# Waarom dit nodig is: elke functie in dit bestand opende een eigen verbinding
# naar Neon, en dat zijn er drieennegentig. Het openen van een winkel in de
# Shopify-app doet er acht achter elkaar, elk met een eigen TLS-handdruk naar
# een database die ergens anders staat. Dat is een halve tot een hele seconde
# aan wachten waar niets gebeurt, en het is precies wat opviel bij het openen
# van de app.
#
# Hoe het werkt zonder die drieennegentig plekken aan te passen: _get_connection
# geeft geen kale verbinding meer terug maar een omhulsel. Dat omhulsel doet
# alles door naar de echte verbinding, behalve close(). Die geeft hem terug aan
# de pool in plaats van hem echt te sluiten. Elke bestaande "finally:
# conn.close()" blijft dus staan en doet nu het goede.
_POOL = None
_POOL_SLOT = threading.Lock()

# Klein houden. Neon rekent verbindingen af en Render draait maar een paar
# processen. Twee tot acht is ruim voor het werk dat hier gebeurt.
POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
POOL_MAX = int(os.environ.get("DB_POOL_MAX", "8"))
# Hoe lang wij wachten op een vrije verbinding voordat wij er zelf een opzetten.
# Vijftig keer twintig milliseconden is een seconde. Een databaseaanroep duurt
# hier milliseconden, dus in de praktijk is het bijna altijd de eerste poging.
POOL_WACHT_POGINGEN = 50
POOL_WACHT_SECONDEN = 0.02
# Hoe vaak wij een dode verbinding weggooien en de volgende proberen voordat wij
# opgeven en er zelf een opzetten. Drie is ruim: na een lange stilte zijn ze
# meestal allemaal dood, en dan zijn er ook niet meer dan een paar.
POOL_GEZONDE_POGINGEN = 3


class _Geleend:
    """Een geleende verbinding die zichzelf teruggeeft in plaats van te sluiten.

    Alles gaat door naar de echte verbinding. Alleen close() is anders, en
    __enter__ en __exit__ moeten expliciet doorgegeven worden omdat Python die
    op de klasse opzoekt en niet via __getattr__."""

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool
        self._terug = False

    def __getattr__(self, naam):
        return getattr(self._conn, naam)

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, *fout):
        return self._conn.__exit__(*fout)

    def close(self):
        if self._terug:
            return
        self._terug = True
        try:
            # Een verbinding die stuk is mag niet terug in de pool, anders
            # krijgt de volgende aanroeper hem en gaat die ook stuk.
            if self._conn.closed:
                self._pool.putconn(self._conn, close=True)
            else:
                self._pool.putconn(self._conn)
        except Exception:
            try:
                self._conn.close()
            except Exception:
                pass


def _get_connection():
    global _POOL
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        return None
    try:
        if _POOL is None:
            with _POOL_SLOT:
                if _POOL is None:
                    _POOL = psycopg2.pool.ThreadedConnectionPool(
                        POOL_MIN, POOL_MAX, db_url)
        # Zijn alle verbindingen in gebruik, dan even wachten in plaats van
        # meteen een losse verbinding opzetten. Een aanroep duurt milliseconden,
        # dus er komt bijna altijd binnen een oogwenk een vrij. Zonder dit zette
        # een meting met twintig draden twintig losse verbindingen op, en dat is
        # precies wat de pool moest voorkomen.
        # Een verbinding uit de pool halen, en pas teruggeven als hij ECHT werkt.
        #
        # Dit is waar het misging. conn.closed is alleen een vlag aan onze kant.
        # Neon doet een verbinding die een tijd stil ligt aan zijn kant weg, en
        # dan staat onze vlag nog gewoon op open. De eerste aanroep erna gaf
        # "connection already closed", en dat gebeurde precies bij de ronde die
        # elk uur draait: die komt langs na een uur stilte.
        #
        # Dus vragen wij het aan de database zelf met een piepklein zinnetje.
        # Dat kost een enkele heenreis, ergens tussen de vijf en twintig
        # milliseconde bij Neon. Een nieuwe verbinding opzetten kost er honderd
        # tot driehonderd. Zekerheid is die reis waard.
        for ronde in range(POOL_GEZONDE_POGINGEN):
            conn = None
            for poging in range(POOL_WACHT_POGINGEN):
                try:
                    conn = _POOL.getconn()
                    break
                except psycopg2.pool.PoolError:
                    if poging == POOL_WACHT_POGINGEN - 1:
                        raise
                    time.sleep(POOL_WACHT_SECONDEN)
            if conn is None:
                break
            try:
                if conn.closed:
                    raise psycopg2.InterfaceError("verbinding stond al dicht")
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchone()
                conn.rollback()
                return _Geleend(conn, _POOL)
            except (psycopg2.InterfaceError, psycopg2.OperationalError,
                    psycopg2.DatabaseError):
                # Deze is dood. Weggooien en de volgende proberen. De pool maakt
                # er vanzelf een nieuwe aan.
                try:
                    _POOL.putconn(conn, close=True)
                except Exception:
                    pass
        # Alle pogingen op, dan een losse verbinding hieronder.
        raise psycopg2.OperationalError("geen gezonde verbinding uit de pool")
    except Exception as e:
        # Lukt de pool niet, dan gewoon een losse verbinding. Liever langzaam
        # dan helemaal niet: dit is de laag waar alles op draait.
        print(f"Verbindingenpool niet beschikbaar, losse verbinding gebruikt: {e}")
        try:
            return psycopg2.connect(db_url)
        except Exception as e2:
            print(f"Verbinden met de database mislukt: {e2}")
            return None


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
                        -- Mag leeg zijn: een demo hoort bij geen klant.
                        email TEXT,
                        score INTEGER NOT NULL,
                        checks JSONB NOT NULL,
                        fixes JSONB,
                        payment_id TEXT,
                        aangemaakt_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                # Voor bestaande installaties: kolom toevoegen als die nog mist.
                cur.execute("ALTER TABLE rapporten ADD COLUMN IF NOT EXISTS payment_id TEXT;")
                # Een demo heeft geen e-mailadres, want er is geen klant. De
                # kolom stond op NOT NULL, dus ELKE poging om een demorapport te
                # bewaren mislukte, met alleen een regel in de logboeken van
                # Render. Gevolg: 55 winkels met beoordeelde antwoorden, nul
                # demorapporten, een lege benchmarkpagina, en geen eigen cijfer
                # op de homepage. Er is dagenlang voor die metingen betaald
                # terwijl de uitkomst nergens bewaard werd.
                cur.execute("ALTER TABLE rapporten ALTER COLUMN email DROP NOT NULL;")
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
                # Of deze winkel al eens een gratis proefperiode gehad heeft.
                # Zonder dit kan iemand opzeggen en meteen opnieuw starten, en
                # zo eindeloos zeven gratis dagen blijven krijgen.
                cur.execute("ALTER TABLE shopify_winkels "
                            "ADD COLUMN IF NOT EXISTS proef_gehad_op TIMESTAMPTZ;")
                # Of wij bij deze winkel uit onszelf mogen aanvullen.
                #
                # Standaard aan, want dat is precies wat een abonnee koopt: wij
                # doen het. Maar het moet uit kunnen, en hij moet weten dat het
                # aanstaat. Een app die ongevraagd in andermans winkel schrijft
                # zonder dat je het uit kunt zetten, is een app waar terecht
                # over geklaagd wordt.
                cur.execute("ALTER TABLE shopify_winkels "
                            "ADD COLUMN IF NOT EXISTS automatisch BOOLEAN NOT NULL "
                            "DEFAULT true;")
                cur.execute("ALTER TABLE shopify_winkels "
                            "ADD COLUMN IF NOT EXISTS automatisch_op TIMESTAMPTZ;")
                # Hoeveel wijzigingen wij OOIT in deze winkel gezet hebben.
                # Loopt alleen op, ook als er iets teruggezet wordt. Zonder dit
                # kon je drie keer toepassen, drie keer terugzetten, en had je
                # weer drie gratis wijzigingen.
                cur.execute("ALTER TABLE shopify_winkels "
                            "ADD COLUMN IF NOT EXISTS wijzigingen_ooit INTEGER "
                            "NOT NULL DEFAULT 0;")
                # Sleutels van Shopify verlopen tegenwoordig na een uur. Wij
                # bewaren dus niet alleen de sleutel maar ook tot wanneer hij
                # geldig is, plus de verversleutel waarmee wij een nieuwe
                # kunnen halen.
                #
                # Staat sleutel_tot leeg, dan is het nog een sleutel van de
                # oude soort. Die wordt door Shopify geweigerd en moet opnieuw
                # opgehaald worden. Dat is met opzet te zien aan een lege kolom
                # en niet aan een aparte vlag: een lege kolom kan niet per
                # ongeluk op "goed" blijven staan.
                cur.execute("ALTER TABLE shopify_winkels "
                            "ADD COLUMN IF NOT EXISTS sleutel_tot TIMESTAMPTZ;")
                cur.execute("ALTER TABLE shopify_winkels "
                            "ADD COLUMN IF NOT EXISTS verversleutel TEXT;")
                cur.execute("ALTER TABLE shopify_winkels "
                            "ADD COLUMN IF NOT EXISTS verversleutel_tot TIMESTAMPTZ;")
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
                # De winkels die wij benaderen, met per winkel hoe ver wij zijn.
                # Eén regel per winkel en de stand erin, zodat een herstart van
                # de server niet betekent dat iemand twee keer post krijgt. Dat
                # is hier het echte risico: een dubbele mail aan iemand die er
                # niet om vroeg kost je het adres en het domein.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS benadering (
                        webshop_url TEXT PRIMARY KEY,
                        naam TEXT,
                        land TEXT,
                        branche TEXT,
                        stand TEXT NOT NULL DEFAULT 'nieuw',
                        email TEXT,
                        email_bron TEXT,
                        notitie TEXT,
                        afgemeld BOOLEAN NOT NULL DEFAULT FALSE,
                        gemaild_op TIMESTAMPTZ,
                        toegevoegd_op TIMESTAMPTZ DEFAULT now(),
                        bijgewerkt_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                # Wanneer de meting voor deze winkel begonnen is. Zonder dit
                # kunnen wij een meting die nog loopt niet onderscheiden van een
                # meting die onderweg is omgevallen, en dan blijft een winkel
                # ofwel eeuwig hangen ofwel wordt hij eeuwig opnieuw betaald.
                cur.execute("ALTER TABLE benadering "
                            "ADD COLUMN IF NOT EXISTS meting_gestart_op TIMESTAMPTZ;")
                # De trechter na de mail. Zonder deze drie kolommen weet je na
                # honderd verstuurde mails alleen dat er honderd verstuurd zijn,
                # en dat is precies niets. Wat je wilt weten is: hoeveel mensen
                # openen hun uitkomst, en hoeveel klikken door naar de prijzen.
                # Pas dan weet je of de mail werkt of de pagina, en dus wat je
                # moet veranderen.
                cur.execute("ALTER TABLE benadering "
                            "ADD COLUMN IF NOT EXISTS bekeken_op TIMESTAMPTZ;")
                cur.execute("ALTER TABLE benadering "
                            "ADD COLUMN IF NOT EXISTS bekeken_aantal INTEGER NOT NULL DEFAULT 0;")
                cur.execute("ALTER TABLE benadering "
                            "ADD COLUMN IF NOT EXISTS doorgeklikt_op TIMESTAMPTZ;")
                cur.execute("""CREATE INDEX IF NOT EXISTS benadering_stand
                               ON benadering (stand);""")
                # Koppelingen met winkels die niet op Shopify draaien.
                #
                # De sleutels staan hier versleuteld in, niet in platte tekst.
                # Bij Shopify konden we dat verantwoorden omdat een sleutel per
                # winkel geldt en meteen gewist wordt bij verwijderen. Hier is
                # het anders: dit zijn sleutels die de eigenaar zelf heeft
                # aangemaakt in zijn eigen beheerscherm, en waarmee je in zijn
                # hele winkel kunt schrijven. Die horen niet leesbaar in een
                # database te staan.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS koppelingen (
                        webshop_url TEXT PRIMARY KEY,
                        platform TEXT NOT NULL,
                        basis_url TEXT NOT NULL,
                        geheim TEXT,
                        stand TEXT NOT NULL DEFAULT 'nieuw',
                        laatste_fout TEXT,
                        gecontroleerd_op TIMESTAMPTZ,
                        aangemaakt_op TIMESTAMPTZ DEFAULT now(),
                        bijgewerkt_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
                # Knoppen die aan of uit staan zonder dat er een nieuwe versie
                # van de site voor nodig is. Nu alleen voor de dagrem op de
                # post, maar bewust algemeen gehouden.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS instellingen (
                        sleutel TEXT PRIMARY KEY,
                        waarde TEXT,
                        bijgewerkt_op TIMESTAMPTZ DEFAULT now()
                    );
                """)
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
                # In welke taal en voor welk land we deze winkel meten. Zonder
                # dit kreeg elke winkel Nederlandse koopvragen, ook een winkel
                # in Texas.
                cur.execute("ALTER TABLE winkelprofielen ADD COLUMN IF NOT EXISTS taal TEXT;")
                cur.execute("ALTER TABLE winkelprofielen ADD COLUMN IF NOT EXISTS land TEXT;")
                # Het kenmerk waarmee een gemeten winkel zijn eigen uitkomst
                # opent. Alleen voor winkels uit de benchmark, en bewust niet
                # hetzelfde kenmerk als dat van een betalende klant.
                cur.execute("ALTER TABLE winkelprofielen "
                            "ADD COLUMN IF NOT EXISTS benchmark_token TEXT;")
                # Het adres waarop we de eigenaar van een gemeten winkel
                # bereiken, en of we hem al bericht hebben. Dat laatste is geen
                # bijzaak: twee keer dezelfde mail naar een winkelier die er
                # niet om vroeg is het verschil tussen een onderzoek en spam.
                cur.execute("ALTER TABLE winkelprofielen "
                            "ADD COLUMN IF NOT EXISTS contact_email TEXT;")
                cur.execute("ALTER TABLE winkelprofielen "
                            "ADD COLUMN IF NOT EXISTS onderzoeksmail_op TIMESTAMPTZ;")
                # Of iemand gezegd heeft dat hij niets meer wil. Dit staat hier
                # en niet alleen bij de benaderlijst, want een winkel kan ook
                # via een andere weg gemeten en gemaild zijn. Stond het alleen
                # daar, dan zou een afmelding van zo'n winkel nergens landen en
                # kreeg hij gewoon opnieuw post. Dit veld is de enige waarheid
                # over afmeldingen.
                cur.execute("ALTER TABLE winkelprofielen "
                            "ADD COLUMN IF NOT EXISTS afgemeld_op TIMESTAMPTZ;")
                # De merknaam zoals de winkel zichzelf noemt. Werd hiervoor
                # geraden door de omschrijving op " is " te splitsen. Dat gaf
                # bij "Deze webshop is gespecialiseerd in servies" de naam
                # "Deze webshop", en met die naam telde elke pagina waar die
                # twee woorden toevallig staan als vermelding.
                cur.execute("ALTER TABLE winkelprofielen "
                            "ADD COLUMN IF NOT EXISTS winkelnaam TEXT;")
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS winkelprofielen_bmtoken "
                            "ON winkelprofielen (benchmark_token) "
                            "WHERE benchmark_token IS NOT NULL;")
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
                # In welke taal deze oplossing geschreven is. Zonder dit kreeg
                # een Amerikaanse winkel een Engels scherm met een Nederlandse
                # tekst eronder die hij letterlijk moest overnemen. Bewaarde
                # teksten worden namelijk niet opnieuw gemaakt, en dus bleef de
                # oude taal hangen.
                cur.execute("ALTER TABLE taakoplossingen "
                            "ADD COLUMN IF NOT EXISTS taal TEXT DEFAULT 'nl';")
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
                # Wanneer wij deze aanvrager nog een keer geschreven hebben.
                #
                # Dit ontbrak, en dat was het grootste gat in het hele bedrijf:
                # iemand vult zijn mailadres in voor de gratis test, krijgt zijn
                # uitkomst, en hoort daarna nooit meer iets. Dat is het warmste
                # publiek dat Krillo heeft, warmer dan welke benaderlijst ook,
                # want deze mensen hebben er zelf om gevraagd.
                cur.execute("ALTER TABLE zichtbaarheidstests "
                            "ADD COLUMN IF NOT EXISTS opgevolgd_op TIMESTAMPTZ;")
                # Tests die uren geleden begonnen en nooit afgemaakt zijn, zijn
                # omgevallen processen. Die vrijgeven, anders blokkeren ze de
                # winkel voorgoed zodra het slot hieronder actief wordt.
                cur.execute("""UPDATE zichtbaarheidstests
                                  SET status = 'mislukt', foutsoort = 'vastgelopen'
                                WHERE status NOT IN ('klaar', 'mislukt')
                                  AND aangevraagd_op < now() - interval '30 minutes'""")

                cur.execute("ALTER TABLE zichtbaarheidstests ADD COLUMN IF NOT EXISTS soort TEXT DEFAULT 'volledig';")
                # Een niet te raden kenmerk per test. Het rijnummer telde
                # gewoon op: wie zelf een test deed en nummer 812 kreeg, kon
                # 1 tot en met 811 opvragen en zag van elke andere bezoeker de
                # winkel en de volledige uitslag.
                cur.execute("ALTER TABLE zichtbaarheidstests "
                            "ADD COLUMN IF NOT EXISTS kenmerk TEXT;")
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS zichtbaarheid_kenmerk "
                            "ON zichtbaarheidstests (kenmerk) WHERE kenmerk IS NOT NULL;")
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

    # Bewust NA het sluiten van de verbinding hierboven, met een eigen
    # verbinding. Mislukt dit, dan is alleen deze stap mislukt en start de app
    # gewoon op.
    _zet_slot_op_lopende_tests()
    _sluit_bestaande_shopify_sleutels_weg()
    _zet_webadressen_op_een_schrijfwijze()


def ontclaim_payment(payment_id):
    """Maakt de claim op een betaling ongedaan, zodat hij opnieuw geprobeerd wordt.

    Dit hoort bij het geval waarin er wel betaald is maar de levering mislukte,
    bijvoorbeeld omdat de webshop onze scanner blokkeerde. Zonder dit blijft de
    claim staan, stopt elke herhaling van Mollie er meteen op, en heeft de klant
    betaald zonder ooit iets te krijgen. Mollie probeert het uit zichzelf nog
    een paar keer, en dan is er nog een kans."""
    if not payment_id:
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM verwerkte_betalingen WHERE payment_id = %s",
                            (payment_id,))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Claim op {payment_id} terugdraaien mislukt: {e}")
        return False
    finally:
        conn.close()


def claim_payment(payment_id):
    """Probeert een betaling als 'in behandeling' te markeren.

    Drie mogelijke antwoorden, en het verschil tussen de laatste twee is geld:
      True  dit is de eerste keer, ga door.
      False deze betaling is al eerder verwerkt, niets doen.
      None  wij KONDEN niet claimen (geen database of een fout).

    Dat None stond hier eerst ook op False, en dat is gevaarlijk: de aanroeper
    las dat als "al verwerkt" en stopte. Een geslaagde betaling verdween dan
    stilletjes bij een databasestoring, en tegen de tijd dat de database weer
    werkte was Mollie door zijn herhalingen heen. Betaald, geen klant, geen
    mail, geen melding."""
    conn = _get_connection()
    if conn is None:
        # Zonder database kunnen we niet vastleggen dat we deze betaling al
        # gezien hebben. Dan NIET doorgaan: anders levert elke herhaling van
        # Mollie een tweede factuur, een tweede audit en een tweede mail op.
        # Een gemiste verwerking is te herstellen, een dubbele niet.
        print("Betaling niet geclaimd: geen database. Verwerking overgeslagen.")
        return None
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
        return None
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


def onbekende_modellen(dagen=30):
    """Welke modelnamen als 'onbekend' geboekt zijn, met hoeveel aanroepen.

    Zonder deze lijst zegt de kostenpagina alleen DAT er aanroepen zonder prijs
    zijn, en moet je in de logs gaan zoeken welke. Dan voeg je de prijs nooit
    toe en blijft de dagpot te ruim."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT provider, model, COUNT(*) AS aanroepen,
                              SUM(COALESCE(invoer_tokens, 0)) AS invoer,
                              SUM(COALESCE(uitvoer_tokens, 0)) AS uitvoer
                         FROM kostengebeurtenissen
                        WHERE kosten_status = 'onbekend'
                          AND moment >= now() - (%s || ' days')::interval
                        GROUP BY provider, model
                        ORDER BY COUNT(*) DESC""",
                    (str(int(dagen)),),
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"Onbekende modellen ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def herstel_onbekende_kosten(prijs_zoeker, dagen=60):
    """Rekent alsnog de kosten uit van aanroepen die als 'onbekend' geboekt zijn.

    Waarom dit nodig is. De prijs wordt vastgelegd op het moment van de
    aanroep. Een modelnaam die toen niet in de prijslijst stond is geboekt als
    onbekend, en dus als nul euro. Voeg je de prijs later toe, dan tellen alleen
    NIEUWE aanroepen mee en blijven de oude voor altijd op nul staan. Zo bleef
    de melding op de kostenpagina staan nadat de prijs toegevoegd was, en bleef
    de dagpot te ruim: de rem dacht dat er minder uitgegeven was dan waar.

    `prijs_zoeker` is `kosten.zoek_prijs`. Dat wordt meegegeven en niet hier
    geimporteerd, zodat db.py niets van de prijslijst hoeft te weten en dit los
    te testen is.

    Geeft terug hoeveel regels er bijgewerkt zijn."""
    conn = _get_connection()
    if conn is None:
        return 0
    bijgewerkt = 0
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT gebeurtenis_id, provider, model, invoer_tokens, uitvoer_tokens
                         FROM kostengebeurtenissen
                        WHERE kosten_status = 'onbekend'
                          AND moment >= now() - (%s || ' days')::interval""",
                    (str(int(dagen)),),
                )
                regels = [dict(r) for r in cur.fetchall()]

                for r in regels:
                    prijs = prijs_zoeker(r.get("provider"), r.get("model"))
                    if not prijs:
                        continue
                    bedrag = (
                        (int(r.get("invoer_tokens") or 0) / 1_000_000)
                        * prijs["invoer_per_miljoen"]
                        + (int(r.get("uitvoer_tokens") or 0) / 1_000_000)
                        * prijs["uitvoer_per_miljoen"]
                    )
                    cur.execute(
                        """UPDATE kostengebeurtenissen
                              SET kosten = %s, kosten_status = 'berekend',
                                  prijsversie = %s
                            WHERE gebeurtenis_id = %s""",
                        (round(bedrag, 6), prijs.get("prijsversie"), r["gebeurtenis_id"]),
                    )
                    bijgewerkt += cur.rowcount
    except Exception as e:
        print(f"Onbekende kosten herstellen mislukt: {e}")
        return bijgewerkt
    finally:
        conn.close()
    return bijgewerkt


def kosten_per_scan(scan_id):
    return _kosten_optellen("scan_id = %s", (scan_id,))


def kosten_per_klant_deze_maand(webshop_url):
    return _kosten_optellen(
        "webshop_url = %s AND moment >= date_trunc('month', now())", (webshop_url,)
    )


def kosten_vandaag():
    """Wat er vandaag uitgegeven is, met "vandaag" volgens de klok in Nederland.

    Stond hier zonder tijdzone, en dan rekent de database in UTC. Daar begint de
    dag om 02:00 Nederlandse tijd. Het bericht van 08:00 meldde daardoor al
    14,39 euro gebruikt, want alles wat er tussen 02:00 en 08:00 gemeten was
    telde mee terwijl de dag voor jouw gevoel nog moest beginnen. Het getal was
    niet fout, het sloeg alleen op een andere dag dan die op je klok."""
    return _kosten_optellen(
        "moment >= date_trunc('day', now() AT TIME ZONE 'Europe/Amsterdam') "
        "AT TIME ZONE 'Europe/Amsterdam'", ())


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


def bewaar_koopvragen(webshop_url, omschrijving, vragen, vervang=False, winkelnaam=None):
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
                    """INSERT INTO winkelprofielen (webshop_url, omschrijving, winkelnaam)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (webshop_url) DO UPDATE
                       SET omschrijving = EXCLUDED.omschrijving,
                           winkelnaam = coalesce(EXCLUDED.winkelnaam,
                                                 winkelprofielen.winkelnaam),
                           bijgewerkt_op = now()""",
                    (webshop_url, omschrijving, (winkelnaam or None)),
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


# ---------------------------------------------------------------------------
# De sleutels van Shopify-winkels versleuteld bewaren
# ---------------------------------------------------------------------------
#
# Met zo'n sleutel kan je in de winkel van een ander schrijven: producten,
# pagina's, bestanden. Ze stonden hier in platte tekst. Lekt de database ooit,
# dan heeft iemand schrijftoegang tot elke winkel die de app geinstalleerd
# heeft, en dat is een heel andere ramp dan een gelekte lijst met webadressen.
#
# Waarom er een merkje voor staat en niet gewoon versleutelde tekst: er staan nu
# al sleutels in platte tekst in de database. Zonder merkje kan je die twee niet
# uit elkaar houden en zou de app na het bijwerken elke bestaande winkel als
# onleesbaar beschouwen. Met het merkje weet elke leesactie precies wat hij
# voor zich heeft.
#
# Staat KLUIS_SLEUTEL niet ingesteld, dan bewaren wij zoals het was en zeggen
# wij dat in het logboek. Beter een app die draait met een waarschuwing dan een
# app die er na een nieuwe versie mee ophoudt.
SLEUTEL_MERKJE = "kluis1:"


def _sluit_bestaande_shopify_sleutels_weg():
    """Zet sleutels die nog in platte tekst staan alsnog in de kluis.

    Draait bij elke opstart en doet daarna niets meer, want een sleutel met het
    merkje ervoor wordt overgeslagen. Zonder deze stap zou alleen een winkel die
    opnieuw installeert versleuteld raken, en blijven de bestaande winkels
    voorgoed in platte tekst staan."""
    if not kluis.beschikbaar():
        print("LET OP: KLUIS_SLEUTEL ontbreekt. Shopify-sleutels staan in platte "
              "tekst in de database. Zet in Render een KLUIS_SLEUTEL van minstens "
              "32 willekeurige tekens, dan worden ze bij de volgende start "
              "versleuteld.")
        return 0
    conn = _get_connection()
    if conn is None:
        return 0
    gedaan = 0
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT winkel, toegangssleutel, verversleutel "
                            "FROM shopify_winkels")
                rijen = cur.fetchall()
                for winkel, sleutel, ververs in rijen:
                    nieuw_s = _sluit_sleutel_weg(sleutel)
                    nieuw_v = _sluit_sleutel_weg(ververs)
                    if nieuw_s == sleutel and nieuw_v == ververs:
                        continue
                    cur.execute("UPDATE shopify_winkels SET toegangssleutel = %s, "
                                "verversleutel = %s WHERE winkel = %s",
                                (nieuw_s, nieuw_v, winkel))
                    gedaan += 1
        if gedaan:
            print(f"{gedaan} Shopify-sleutel(s) alsnog versleuteld opgeborgen.")
        return gedaan
    except Exception as e:
        print(f"Bestaande Shopify-sleutels wegsluiten mislukt: {e}")
        return 0
    finally:
        conn.close()


def _sluit_sleutel_weg(waarde):
    """Versleutelt een toegangssleutel. Lukt dat niet, dan onveranderd terug."""
    if not waarde or str(waarde).startswith(SLEUTEL_MERKJE):
        return waarde
    if not kluis.beschikbaar():
        print("LET OP: KLUIS_SLEUTEL ontbreekt, Shopify-sleutels worden in platte "
              "tekst bewaard. Zet in Render een KLUIS_SLEUTEL van minstens 32 tekens.")
        return waarde
    try:
        return SLEUTEL_MERKJE + kluis.sluit({"s": waarde})
    except Exception as e:
        print(f"Sleutel wegsluiten mislukt, onveranderd bewaard: {e}")
        return waarde


def _haal_sleutel_op(waarde):
    """Draait _sluit_sleutel_weg terug. Platte tekst gaat onveranderd door."""
    if not waarde or not str(waarde).startswith(SLEUTEL_MERKJE):
        return waarde
    geopend = kluis.open_(str(waarde)[len(SLEUTEL_MERKJE):])
    if not geopend:
        # De kluissleutel is veranderd of de regel is aangepast. Niets
        # teruggeven is hier het juiste: met een halve sleutel naar Shopify gaan
        # levert alleen verwarrende foutmeldingen op.
        print("LET OP: een bewaarde Shopify-sleutel is niet te openen. "
              "Is KLUIS_SLEUTEL veranderd? De winkel moet opnieuw installeren.")
        return None
    return geopend.get("s")


def _rij_met_open_sleutels(rij):
    """Een rij uit shopify_winkels met leesbare sleutels erin."""
    if not rij:
        return rij
    uit = dict(rij)
    for veld in ("toegangssleutel", "verversleutel"):
        if veld in uit:
            uit[veld] = _haal_sleutel_op(uit[veld])
    return uit


def bewaar_shopify_winkel(winkel, toegangssleutel, rechten=None, webshop_url=None,
                          email=None, naam=None, geldig_seconden=None,
                          verversleutel=None, verversleutel_seconden=None):
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
                            sleutel_tot, verversleutel, verversleutel_tot,
                            actief, geinstalleerd_op, verwijderd_op)
                       VALUES (%s, %s, %s, %s, %s, %s,
                               now() + make_interval(secs => %s), %s,
                               now() + make_interval(secs => %s),
                               true, now(), NULL)
                       ON CONFLICT (winkel) DO UPDATE
                       SET toegangssleutel = EXCLUDED.toegangssleutel,
                           rechten = EXCLUDED.rechten,
                           webshop_url = coalesce(EXCLUDED.webshop_url, shopify_winkels.webshop_url),
                           email = coalesce(EXCLUDED.email, shopify_winkels.email),
                           naam = coalesce(EXCLUDED.naam, shopify_winkels.naam),
                           sleutel_tot = EXCLUDED.sleutel_tot,
                           verversleutel = EXCLUDED.verversleutel,
                           verversleutel_tot = EXCLUDED.verversleutel_tot,
                           actief = true,
                           geinstalleerd_op = now(),
                           verwijderd_op = NULL""",
                    (winkel, _sluit_sleutel_weg(toegangssleutel), rechten,
                     webshop_url, email, naam,
                     float(geldig_seconden or 0), _sluit_sleutel_weg(verversleutel),
                     float(verversleutel_seconden or 0)),
                )
        return True
    except Exception as e:
        print(f"Shopify-winkel bewaren mislukt voor {winkel}: {e}")
        return False
    finally:
        conn.close()


def vervang_shopify_sleutelpaar(winkel, toegangssleutel, geldig_seconden,
                                verversleutel, verversleutel_seconden, rechten=None):
    """Zet een vers sleutelpaar neer, zonder de rest van de rij aan te raken.

    Bewust apart van bewaar_shopify_winkel: die zet ook geinstalleerd_op op nu
    en actief op waar, en dat hoort niet te gebeuren omdat er toevallig een
    sleutel ververst is.

    Dit moet gebeuren VOORDAT de nieuwe sleutel ergens voor gebruikt wordt.
    Shopify laat de oude verversleutel vervallen zodra je de nieuwe gebruikt,
    dus als wij hem niet eerst opslaan zijn wij de winkel kwijt. Daarom geeft
    deze functie ook eerlijk False terug als het opslaan mislukt."""
    if not winkel or not toegangssleutel:
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE shopify_winkels
                          SET toegangssleutel = %s,
                              sleutel_tot = now() + make_interval(secs => %s),
                              verversleutel = %s,
                              verversleutel_tot = now() + make_interval(secs => %s),
                              rechten = coalesce(%s, rechten)
                        WHERE winkel = %s""",
                    (_sluit_sleutel_weg(toegangssleutel), float(geldig_seconden or 0),
                     _sluit_sleutel_weg(verversleutel),
                     float(verversleutel_seconden or 0), rechten, winkel),
                )
                return cur.rowcount > 0
    except Exception as e:
        print(f"Shopify-sleutelpaar bijwerken mislukt voor {winkel}: {e}")
        return False
    finally:
        conn.close()


def wis_shopify_verversleutel(winkel):
    """Gooit een verversleutel weg die Shopify voorgoed geweigerd heeft.

    Blijft hij staan, dan probeert elke wekelijkse ronde het opnieuw met een
    sleutel waarvan wij weten dat hij dood is. De winkel blijft wel op actief
    staan: de winkelier heeft de app nog gewoon, en zodra hij hem opent halen
    wij een nieuw paar op."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE shopify_winkels "
                            "SET verversleutel = NULL, verversleutel_tot = NULL, "
                            "    sleutel_tot = NULL "
                            "WHERE winkel = %s", (winkel,))
        return True
    except Exception as e:
        print(f"Verversleutel wissen mislukt voor {winkel}: {e}")
        return False
    finally:
        conn.close()


def tel_shopify_wijziging(winkel):
    """Telt er een op bij het aantal wijzigingen dat wij ooit gedaan hebben."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE shopify_winkels "
                            "SET wijzigingen_ooit = coalesce(wijzigingen_ooit, 0) + 1 "
                            "WHERE winkel = %s", (winkel,))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Wijziging tellen mislukt voor {winkel}: {e}")
        return False
    finally:
        conn.close()


def zet_shopify_automatisch(winkel, aan):
    """Zet het uit onszelf aanvullen aan of uit voor deze winkel."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE shopify_winkels SET automatisch = %s WHERE winkel = %s",
                            (bool(aan), winkel))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Automatisch aanvullen instellen mislukt voor {winkel}: {e}")
        return False
    finally:
        conn.close()


def markeer_shopify_automatisch(winkel):
    """Legt vast wanneer wij voor het laatst uit onszelf hebben aangevuld.

    Nodig om te voorkomen dat een ronde die twee keer draait ook twee keer
    aanvult, met dubbele kosten bij het model."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE shopify_winkels SET automatisch_op = now() "
                            "WHERE winkel = %s", (winkel,))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Bijwerkmoment vastleggen mislukt voor {winkel}: {e}")
        return False
    finally:
        conn.close()


def markeer_proef_gehad(winkel):
    """Legt vast dat deze winkel zijn gratis proefperiode gehad heeft."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE shopify_winkels
                                  SET proef_gehad_op = coalesce(proef_gehad_op, now())
                                WHERE winkel = %s""", (winkel,))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Proefperiode vastleggen mislukt voor {winkel}: {e}")
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
                return _rij_met_open_sleutels(cur.fetchone())
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
                return [_rij_met_open_sleutels(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"Shopify-winkels ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def noteer_uitkomst_bekeken(webshop_url):
    """Legt vast dat iemand zijn eigen uitkomst geopend heeft.

    Alleen tellen, geen persoonsgegevens. Wat er bewaard wordt is: hoe vaak en
    wanneer voor het laatst. Dat is genoeg om te weten of de mail werkt, en het
    is het minste dat daarvoor nodig is."""
    if not webshop_url:
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE benadering
                                  SET bekeken_op = now(),
                                      bekeken_aantal = COALESCE(bekeken_aantal, 0) + 1
                                WHERE webshop_url = %s""", (webshop_url,))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Bezoek aan de uitkomst noteren mislukt voor {webshop_url}: {e}")
        return False
    finally:
        conn.close()


def noteer_doorgeklikt(webshop_url):
    """Legt vast dat iemand vanaf zijn uitkomst doorgeklikt heeft naar de
    prijzen. Dit is de enige stap in de trechter die echt over geld gaat."""
    if not webshop_url:
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE benadering SET doorgeklikt_op = now()
                                WHERE webshop_url = %s
                                  AND doorgeklikt_op IS NULL""", (webshop_url,))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Doorklik noteren mislukt voor {webshop_url}: {e}")
        return False
    finally:
        conn.close()


def trechter_benadering():
    """Hoeveel er gemaild, geopend en doorgeklikt is. Altijd een woordenboek."""
    leeg = {"gemaild": 0, "bekeken": 0, "doorgeklikt": 0}
    conn = _get_connection()
    if conn is None:
        return leeg
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT
                        COUNT(*) FILTER (WHERE gemaild_op IS NOT NULL),
                        COUNT(*) FILTER (WHERE bekeken_op IS NOT NULL),
                        COUNT(*) FILTER (WHERE doorgeklikt_op IS NOT NULL)
                    FROM benadering""")
                rij = cur.fetchone() or (0, 0, 0)
                return {"gemaild": rij[0] or 0, "bekeken": rij[1] or 0,
                        "doorgeklikt": rij[2] or 0}
    except Exception as e:
        print(f"Trechter ophalen mislukt: {e}")
        return leeg
    finally:
        conn.close()


def tel_gescande_webshops():
    """Hoeveel verschillende webshops er ooit gescand zijn.

    Bij nul klanten en nul recensies is dit het enige eerlijke sociale bewijs
    dat er is: een getal dat al vastligt en dat wij niet verzinnen. Daarom telt
    hij ECHTE scans en geen bezoeken, en daarom staat hier geen afronding naar
    boven.

    Geeft 0 terug als het niet lukt. Liever geen getal op de pagina dan een
    verzonnen getal."""
    conn = _get_connection()
    if conn is None:
        return 0
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(DISTINCT webshop_url) FROM rapporten")
                rij = cur.fetchone()
                return int(rij[0]) if rij and rij[0] else 0
    except Exception as e:
        print(f"Gescande webshops tellen mislukt: {e}")
        return 0
    finally:
        conn.close()


def shopify_winkel_bij_webadres(webshop_url):
    """De Shopify-winkel die bij dit webadres hoort, of None.

    Nodig omdat de klantpagina moet weten of iemand via Shopify betaalt of via
    Mollie. Stond dat onderscheid er niet, dan las een winkelier die via Shopify
    afrekent op zijn eigen pagina dat hij 39 euro per maand via ons betaalt, met
    een opzegknop die zijn Shopify-abonnement niet eens raakt."""
    if not webshop_url:
        return None
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""SELECT * FROM shopify_winkels
                                WHERE webshop_url = %s AND actief
                                ORDER BY geinstalleerd_op DESC LIMIT 1""",
                            (webshop_url,))
                rij = cur.fetchone()
                return _rij_met_open_sleutels(rij) if rij else None
    except Exception as e:
        print(f"Shopify-winkel zoeken mislukt voor {webshop_url}: {e}")
        return None
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
                                  # De benaderlijst hoort hier ook bij. Daar staat
                                  # het gevonden contactadres van de winkel in,
                                  # waar wij dat vandaan haalden en onze notities.
                                  # Bij een winkel die eerst benaderd is en later
                                  # de app installeerde, bleef dat na een
                                  # wisverzoek allemaal gewoon staan.
                                  "benadering", "koppelingen",
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
    """Legt een factuur vast en geeft {"factuurnummer": ..., "nieuw": True/False}
    terug, of None als het niet lukte. Elk nummer wordt maar één keer uitgegeven,
    en per betaling kan er maar één factuur bestaan.

    Die "nieuw" is er omdat de aanroeper de factuurmail onvoorwaardelijk
    verstuurde. Bij een mislukte levering komt Mollie meerdere keren langs, en
    dan kreeg iemand drie keer dezelfde factuur voor iets wat hij niet had.

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
                    # Er bestond al een factuur voor deze betaling. Dat is geen
                    # fout, maar de aanroeper moet het weten: die verstuurde de
                    # factuurmail er onvoorwaardelijk achteraan, en bij een
                    # mislukte levering komt Mollie meerdere keren langs. Dan
                    # kreeg iemand drie keer dezelfde factuur van 79 euro voor
                    # iets wat hij nog steeds niet had.
                    return {"factuurnummer": bestaand["factuurnummer"], "nieuw": False}
                cur.execute(
                    """INSERT INTO facturen (payment_id, email, bedrijfsnaam, omschrijving, bedrag, bron)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING factuurnummer""",
                    (payment_id, email, bedrijfsnaam, omschrijving, bedrag, (bron or None)),
                )
                return {"factuurnummer": cur.fetchone()["factuurnummer"], "nieuw": True}
    except Exception as e:
        print(f"Factuur aanmaken mislukt: {e}")
        return None
    finally:
        conn.close()


def get_or_create_klant(webshop_url, email):
    """Geeft het vaste token van deze klant terug, en maakt het aan als het nog
    niet bestaat. Zo houdt een monitoring-klant altijd dezelfde pagina, ook na
    tien wekelijkse scans.

    LET OP, dit is een beveiligingscontrole en geen formaliteit: hoort er bij
    deze webshop al een klant met een ANDER e-mailadres, dan geven wij het
    bestaande token NIET terug. Zonder die controle kon iemand de URL van een
    bestaande klant invullen bij een bestelling, kreeg hij diens token in zijn
    eigen mailbox, en zag hij alle rapporten van die klant. Hij kon er zelfs
    diens abonnement mee opzeggen."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT klant_token, email FROM klanten WHERE webshop_url = %s",
                            (webshop_url,))
                bestaand = cur.fetchone()
                if bestaand:
                    oud_adres = (bestaand.get("email") or "").strip().lower()
                    nieuw_adres = (email or "").strip().lower()
                    if oud_adres and nieuw_adres and oud_adres != nieuw_adres:
                        print(f"LET OP: {nieuw_adres} vroeg de pagina van {webshop_url} op, "
                              f"maar die hoort bij {oud_adres}. Geweigerd.")
                        return None
                    return bestaand["klant_token"]
                token = secrets.token_urlsafe(24)
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
    token = secrets.token_urlsafe(24)
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


def bewaar_taakoplossing(webshop_url, taak_id, titel, oplossing, waar, taal="nl"):
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
                       (webshop_url, taak_id, titel, oplossing, waar, taal)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (webshop_url, taak_id) DO UPDATE
                       SET titel = EXCLUDED.titel, oplossing = EXCLUDED.oplossing,
                           waar = EXCLUDED.waar, taal = EXCLUDED.taal,
                           gemaakt_op = now()""",
                    (webshop_url, taak_id, titel, oplossing, waar, taal or "nl"),
                )
        return True
    except Exception as e:
        print(f"Taakoplossing bewaren mislukt: {e}")
        return False
    finally:
        conn.close()


def get_taakoplossingen(webshop_url, taal=None):
    """Alle bewaarde oplossingen voor een winkel, als {taak_id: {...}}.

    Geef je een taal mee, dan krijg je alleen de oplossingen die in die taal
    geschreven zijn. Dat is met opzet streng: liever geen tekst dan een
    Nederlandse tekst onder een Engels kopje. De ontbrekende worden bij de
    volgende ronde gewoon opnieuw gemaakt, nu wel in de goede taal."""
    conn = _get_connection()
    if conn is None:
        return {}
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if taal:
                    cur.execute(
                        """SELECT * FROM taakoplossingen
                            WHERE webshop_url = %s AND coalesce(taal, 'nl') = %s""",
                        (webshop_url, taal),
                    )
                else:
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

# Hoe lang een test mag lopen voordat wij hem als vastgelopen beschouwen.
# Een test duurt minuten. Blijft hij langer dan dit op wachtrij of bezig staan,
# dan is het proces omgevallen en mag er een nieuwe gestart worden.
TEST_VASTGELOPEN_NA_MINUTEN = 30


def _zet_webadressen_op_een_schrijfwijze():
    """Zet elk bewaard webadres om naar de vorm die normalize_url nu maakt.

    Waarom dit over ALLE tabellen moet en niet alleen over de benaderlijst:
    normalize_url haalt sinds september 2026 ook "www." weg, maakt van http
    https en haalt de schuine streep aan het eind eraf. Elke aanroep zoekt dus
    voortaan op de kale vorm. Alles wat er voor die wijziging in ging staat nog
    in de oude vorm, en die twee vinden elkaar nooit meer.

    Wat er dan gebeurt, en dat is geen theorie: een klant met adres
    "https://www.klant.nl" start zijn wekelijkse meting, get_or_create_klant
    zoekt naar "https://klant.nl", vindt zijn rij niet, en maakt een nieuwe
    klant aan met een nieuw token. Hij kijkt op zijn eigen gebookmarkte pagina
    en ziet daar nooit meer een update, terwijl er ergens anders een lege
    pagina ontstaat. Zijn koopvragen en zijn geschiedenis raken hij ook kwijt,
    en die worden opnieuw gemaakt, met kosten.

    Elke tabel in een eigen transactie, en elke rij apart. Botst een rij met een
    rij die er al staat, dan slaan wij die over in plaats van de hele omzetting
    te laten omvallen. Beter negentien tabellen waarvan er achttien klaar zijn
    dan een app die niet opstart."""
    conn = _get_connection()
    if conn is None:
        return 0
    veranderd = 0
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT table_name FROM information_schema.columns
                                WHERE column_name = 'webshop_url'
                                  AND table_schema = 'public'
                                ORDER BY table_name""")
                tabellen = [r[0] for r in cur.fetchall()]

        for tabel in tabellen:
            try:
                with conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            f"SELECT DISTINCT webshop_url FROM {tabel} "
                            "WHERE webshop_url IS NOT NULL")
                        adressen = [r[0] for r in cur.fetchall()]
            except Exception as e:
                print(f"Adressen lezen uit {tabel} mislukt: {e}")
                continue

            for oud_adres in adressen:
                nieuw_adres = scan_engine.normalize_url(oud_adres)
                if not nieuw_adres or nieuw_adres == oud_adres:
                    continue
                try:
                    with conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                f"UPDATE {tabel} SET webshop_url = %s "
                                "WHERE webshop_url = %s", (nieuw_adres, oud_adres))
                            veranderd += cur.rowcount
                except Exception as e:
                    # Meestal: er staat al een rij op de nieuwe schrijfwijze en
                    # de twee kunnen niet naast elkaar. Laten staan.
                    print(f"{tabel}: {oud_adres} kon niet omgezet worden: "
                          f"{type(e).__name__}")
        if veranderd:
            print(f"{veranderd} rij(en) omgezet naar de nieuwe schrijfwijze van "
                  f"webadressen.")
        return veranderd
    except Exception as e:
        print(f"Webadressen gelijktrekken mislukt: {e}")
        return 0
    finally:
        conn.close()


def _zet_slot_op_lopende_tests():
    """Zorgt dat er per winkel hoogstens EEN test tegelijk kan lopen.

    Waarom dit een index in de database is en geen controle in de code: een
    dubbelklik stuurt twee verzoeken binnen milliseconden. Allebei kijken of er
    al een test loopt, allebei zien van niet, en allebei starten er een. Dat is
    met een controle vooraf niet te winnen, hoe je hem ook schrijft. Ik heb dat
    gemeten: van tien gelijktijdige klikken kwamen er tien door. De database kan
    het wel, want die kan twee regels tegelijk weigeren.

    Dit staat met opzet in een EIGEN verbinding, buiten de grote opbouw van
    init_db. Mislukt het aanmaken van deze index, dan is de transactie waarin
    hij zit kapot en faalt alles wat erna komt. Dat is precies wat er gebeurde
    toen dit er nog binnen stond, en dan start de app helemaal niet meer op."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                # Eerst opruimen. Staan er nu meerdere lopende tests voor
                # dezelfde winkel, dan kan de index niet aangemaakt worden.
                # Wij houden de nieuwste en geven de rest vrij, want die zijn
                # toch nooit afgemaakt.
                cur.execute("""
                    UPDATE zichtbaarheidstests
                       SET status = 'mislukt', foutsoort = 'dubbel gestart'
                     WHERE status NOT IN ('klaar', 'mislukt')
                       AND id NOT IN (
                           SELECT max(id) FROM zichtbaarheidstests
                            WHERE status NOT IN ('klaar', 'mislukt')
                            GROUP BY webshop_url)""")
        with conn:
            with conn.cursor() as cur:
                # Let op de omkering: wij noemen NIET op wat "loopt" maar wat
                # "af" is.
                #
                # Dit ging mis. De eerste versie zocht op status in wachtrij of
                # bezig. Maar zodra de meting begint zet zichtbaarheid.py de
                # status op vrije tekst: "vragen bedenken", "vragen stellen aan
                # AI", "antwoorden lezen". Die vallen buiten die twee, dus het
                # slot beschermde alleen de eerste seconden, terwijl een meting
                # minuten duurt. Precies de periode waarin het moest werken.
                #
                # Met "alles behalve klaar en mislukt" valt elke voortgangstekst
                # eronder, ook eentje die er later bij komt.
                # Eerst weggooien, dan opnieuw maken.
                #
                # Dit moet, en het is bijna misgegaan. De eerste versie van deze
                # index had een andere voorwaarde. "CREATE UNIQUE INDEX IF NOT
                # EXISTS" kijkt alleen naar de NAAM, niet naar de voorwaarde, dus
                # op een database waar de oude index al staat gebeurt er
                # helemaal niets en blijft de oude voorwaarde gelden. De
                # reparatie zou dan wel in de code staan en niet in de database,
                # en dat is het soort verschil waar je weken naar zoekt.
                cur.execute("DROP INDEX IF EXISTS "
                            "zichtbaarheidstests_een_lopende_per_winkel")
                cur.execute("""CREATE UNIQUE INDEX
                               zichtbaarheidstests_een_lopende_per_winkel
                               ON zichtbaarheidstests (webshop_url)
                               WHERE status NOT IN ('klaar', 'mislukt')""")
        return True
    except Exception as e:
        # De app draait gewoon door. Zonder de index is er nog steeds de
        # controle vooraf, die vangt alles behalve twee klikken in dezelfde
        # milliseconde.
        print(f"Slot op lopende tests kon niet gezet worden: {e}")
        return False
    finally:
        conn.close()


def loopt_er_al_een_test(webshop_url):
    """Of er voor deze winkel op dit moment al een test loopt.

    Dit is een slot tegen dubbel betalen, en het staat in de database en niet in
    het geheugen. Twee redenen: Render herstart de server vaker dan je denkt, en
    er kan meer dan een werker tegelijk draaien. Een slot in het geheugen ziet
    de klik van de andere werker niet.

    Waarom dit nodig is: de gratis test en de voorproef staan op een publieke
    pagina zonder wachtwoord. Twee keer klikken, of een dubbelklik, startte twee
    volledige metingen bij de modellen. Dat kost twee keer geld en levert twee
    keer dezelfde uitslag op. Precies dezelfde soort fout als bij de benadering,
    alleen dan bereikbaar voor iedereen die de site bezoekt.

    Een test die vastgelopen is telt niet meer mee, anders kan een winkel na een
    omgevallen meting nooit meer getest worden."""
    if not webshop_url:
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT 1 FROM zichtbaarheidstests
                        WHERE webshop_url = %s
                          AND status NOT IN ('klaar', 'mislukt')
                          AND aangevraagd_op > now() - make_interval(mins => %s)
                        LIMIT 1""",
                    (webshop_url, TEST_VASTGELOPEN_NA_MINUTEN))
                return cur.fetchone() is not None
    except Exception as e:
        # Bij twijfel niet blokkeren. Een bezoeker die geen uitslag krijgt is
        # erger dan een test die een keer dubbel loopt.
        print(f"Nakijken of er al een test loopt mislukt voor {webshop_url}: {e}")
        return False
    finally:
        conn.close()


def start_zichtbaarheidstest(webshop_url, email, nieuwsbrief=False, herkomst=None,
                             hergebruikt=False, soort='volledig'):
    """Legt een aanvraag vast en geeft {"id": ..., "kenmerk": ...} terug.

    Het kenmerk is wat naar de browser gaat, het id blijft binnen. Zo kan
    niemand met een opgeteld nummer de uitslag van een ander opvragen.

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
                        status, hergebruikt, soort, kenmerk)
                       VALUES (%s, %s, %s, now(), %s, %s, %s, %s, %s)
                       RETURNING id, kenmerk""",
                    (webshop_url, email, bool(nieuwsbrief), (herkomst or None),
                     'klaar' if hergebruikt else 'wachtrij', bool(hergebruikt), soort,
                     secrets.token_urlsafe(18)),
                )
                rij = cur.fetchone()
                return {"id": rij[0], "kenmerk": rij[1]}
    except psycopg2.errors.UniqueViolation:
        # Het slot heeft toegeslagen: er loopt al een test voor deze winkel.
        # Dat is geen fout maar precies de bedoeling. Een dubbelklik komt hier
        # terecht en krijgt netjes None terug in plaats van een tweede meting.
        print(f"Tweede test voor {webshop_url} tegengehouden, er loopt er al een.")
        return None
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


def get_zichtbaarheidstest_op_kenmerk(kenmerk):
    """Een test op zijn niet te raden kenmerk. Dit is wat de pagina gebruikt."""
    if not kenmerk or len(kenmerk) < 12:
        return None
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM zichtbaarheidstests WHERE kenmerk = %s",
                            (kenmerk,))
                rij = cur.fetchone()
                return dict(rij) if rij else None
    except Exception as e:
        print(f"Zichtbaarheidstest ophalen mislukt: {e}")
        return None
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


def leads_om_op_te_volgen(na_dagen=3, hoeveel=5):
    """Aanvragers van de gratis test die nog nooit een tweede bericht kregen.

    Alleen wie zijn test echt afgerond heeft, want anders schrijf je iemand over
    een uitkomst die hij nooit gezien heeft. En alleen wie geen klant is: een
    klant krijgt zijn eigen wekelijkse post al.

    Per e-mailadres maar een keer, ook als iemand drie winkels getest heeft.
    Drie mails op een dag naar hetzelfde adres is hoe je in de spammap komt."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """SELECT DISTINCT ON (z.email)
                              z.id, z.webshop_url, z.email, z.aangevraagd_op
                         FROM zichtbaarheidstests z
                    LEFT JOIN klanten k ON k.webshop_url = z.webshop_url
                        WHERE z.status = 'klaar'
                          AND z.opgevolgd_op IS NULL
                          AND z.email IS NOT NULL AND z.email <> ''
                          AND z.aangevraagd_op < now() - (%s || ' days')::interval
                          AND k.webshop_url IS NULL
                     ORDER BY z.email, z.aangevraagd_op DESC
                        LIMIT %s""",
                    (str(int(na_dagen)), hoeveel),
                )
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"Leads om op te volgen ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def markeer_lead_opgevolgd(test_id):
    """Zet vast dat deze aanvrager een tweede bericht gehad heeft.

    Per e-mailadres en niet per test, want iemand die drie winkels getest heeft
    hoort geen drie mails te krijgen."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE zichtbaarheidstests SET opgevolgd_op = now()
                                WHERE email = (SELECT email FROM zichtbaarheidstests
                                                WHERE id = %s)
                                  AND opgevolgd_op IS NULL""", (test_id,))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Lead als opgevolgd markeren mislukt: {e}")
        return False
    finally:
        conn.close()


def get_benchmark_token(webshop_url, maak_aan=True):
    """Het vaste kenmerk waarmee een gemeten winkel zijn eigen uitkomst opent.

    Bewust GEEN klant_token: dat hangt aan een betalende klant en geeft toegang
    tot de klantpagina met alles erop. Dit is een eigen, kortere weg naar één
    leesbare pagina, en het bestaat alleen voor winkels die we in de benchmark
    gemeten hebben.

    Het kenmerk is niet te raden, want de link gaat naar iemand die er niet om
    gevraagd heeft en die hem kan doorsturen."""
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""SELECT benchmark_token FROM winkelprofielen
                                WHERE webshop_url = %s""", (webshop_url,))
                rij = cur.fetchone()
                if rij and rij.get("benchmark_token"):
                    return rij["benchmark_token"]
                if not maak_aan:
                    return None
                token = uuid.uuid4().hex
                cur.execute(
                    """INSERT INTO winkelprofielen (webshop_url, benchmark_token)
                       VALUES (%s, %s)
                       ON CONFLICT (webshop_url) DO UPDATE
                       SET benchmark_token = coalesce(winkelprofielen.benchmark_token,
                                                      EXCLUDED.benchmark_token)
                       RETURNING benchmark_token""",
                    (webshop_url, token),
                )
                uit = cur.fetchone()
                return (uit or {}).get("benchmark_token") or token
    except Exception as e:
        print(f"Benchmark-token ophalen mislukt voor {webshop_url}: {e}")
        return None
    finally:
        conn.close()


def zet_contact_email(webshop_url, email):
    """Het adres waarop we de eigenaar van een gemeten winkel bereiken."""
    if not webshop_url or not email:
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO winkelprofielen (webshop_url, contact_email)
                       VALUES (%s, %s)
                       ON CONFLICT (webshop_url) DO UPDATE
                       SET contact_email = EXCLUDED.contact_email""",
                    (webshop_url, email.strip()),
                )
        return True
    except Exception as e:
        print(f"Contactadres bewaren mislukt voor {webshop_url}: {e}")
        return False
    finally:
        conn.close()


def markeer_onderzoeksmail(webshop_url):
    """Legt vast dat deze winkel bericht heeft gehad.

    Alleen als het er nog niet stond. Zo kan dezelfde knop twee keer ingedrukt
    worden zonder dat de datum verspringt, en zie je altijd wanneer iemand voor
    het eerst iets van ons hoorde.

    Bewust een INSERT en geen UPDATE. Een winkel van de benaderlijst heeft nog
    geen winkelprofiel, en met een UPDATE raakte dit dan nul regels: de post
    ging wel de deur uit maar op de beheerpagina bleef de kolom leeg, en dan
    druk je met de hand nog een keer op versturen. Dan krijgt iemand die er
    niet om vroeg twee keer dezelfde mail."""
    if not webshop_url:
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO winkelprofielen (webshop_url, onderzoeksmail_op)
                       VALUES (%s, now())
                       ON CONFLICT (webshop_url) DO UPDATE
                       SET onderzoeksmail_op = coalesce(
                               winkelprofielen.onderzoeksmail_op, now())""",
                    (webshop_url,))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Onderzoeksmail vastleggen mislukt voor {webshop_url}: {e}")
        return False
    finally:
        conn.close()


def winkel_bij_benchmark_token(token):
    """Welke winkel hoort bij dit kenmerk. None als het niet bestaat."""
    if not token:
        return None
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""SELECT webshop_url FROM winkelprofielen
                                WHERE benchmark_token = %s""", (token,))
                rij = cur.fetchone()
                return (rij or {}).get("webshop_url")
    except Exception as e:
        print(f"Winkel bij benchmark-token zoeken mislukt: {e}")
        return None
    finally:
        conn.close()


def zet_markt(webshop_url, taal, land):
    """Bewaart in welke taal en voor welk land we deze winkel meten.

    Komt bij Shopify uit de winkel zelf. Bij een winkel die via krillo.nl
    binnenkomt weten we het niet, en dan blijft het leeg en valt alles terug op
    Nederlands, precies zoals het altijd al werkte."""
    if not webshop_url or (not taal and not land):
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO winkelprofielen (webshop_url, taal, land)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (webshop_url) DO UPDATE
                       SET taal = coalesce(EXCLUDED.taal, winkelprofielen.taal),
                           land = coalesce(EXCLUDED.land, winkelprofielen.land)""",
                    (webshop_url, taal or None, land or None),
                )
        return True
    except Exception as e:
        print(f"Markt bewaren mislukt voor {webshop_url}: {e}")
        return False
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


def winkels_met_genoeg_vragen(minimum=10):
    """De winkels waarvan de meting bruikbaar is, als verzameling webadressen.

    Waarom dit los staat van get_demo_webshops: die eist ook een demorapport, en
    juist dat rapport werd maandenlang niet bewaard door een NOT NULL op de
    kolom email. Daardoor gold geen enkele meting als bruikbaar, terwijl er 55
    winkels met beoordeelde antwoorden in de database stonden.

    "Bruikbaar" hoort te hangen aan het enige dat ertoe doet: zijn er genoeg
    vragen meegeteld om een uitkomst te sturen. Niet aan de vraag of er ergens
    een rapportregel naast staat."""
    conn = _get_connection()
    if conn is None:
        return set()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT webshop_url FROM beoordelingen
                                WHERE winkel_kon_genoemd
                             GROUP BY webshop_url
                               HAVING COUNT(DISTINCT vraag) >= %s""", (int(minimum),))
                return {r[0] for r in cur.fetchall()}
    except Exception as e:
        print(f"Winkels met genoeg vragen ophalen mislukt: {e}")
        return set()
    finally:
        conn.close()


def benchmark_diagnose():
    """Ruwe tellingen om te zien WAAROM de benchmark leeg is.

    Dit bestaat omdat de benaderpagina 45 gemeten winkels meldde terwijl de
    benchmarkpagina "er is nog geen enkele demo gedraaid" liet zien. Die twee
    kunnen niet allebei waar zijn, en zonder deze cijfers is van buitenaf niet te
    zien welke van de twee liegt. Een lege pagina is geen antwoord.

    Elk getal apart, want het verschil tussen "geen rapport" en "wel een rapport
    maar geen beoordelingen" wijst naar een heel andere oorzaak."""
    leeg = {"demorapporten": 0, "winkels_met_demo": 0, "winkels_met_beoordelingen": 0,
            "winkels_genoeg_vragen": 0, "rapporten_totaal": 0, "soorten": []}
    conn = _get_connection()
    if conn is None:
        return leeg
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT COUNT(*) AS n FROM rapporten WHERE type = 'demo'")
                leeg["demorapporten"] = cur.fetchone()["n"]
                cur.execute("SELECT COUNT(DISTINCT webshop_url) AS n FROM rapporten "
                            "WHERE type = 'demo'")
                leeg["winkels_met_demo"] = cur.fetchone()["n"]
                cur.execute("SELECT COUNT(*) AS n FROM rapporten")
                leeg["rapporten_totaal"] = cur.fetchone()["n"]
                cur.execute("SELECT type, COUNT(*) AS n FROM rapporten "
                            "GROUP BY type ORDER BY n DESC")
                leeg["soorten"] = [(r["type"], r["n"]) for r in cur.fetchall()]
                cur.execute("SELECT COUNT(DISTINCT webshop_url) AS n FROM beoordelingen")
                leeg["winkels_met_beoordelingen"] = cur.fetchone()["n"]
                cur.execute("""SELECT COUNT(*) AS n FROM (
                                 SELECT webshop_url FROM beoordelingen
                                  GROUP BY webshop_url
                                 HAVING COUNT(DISTINCT vraag) >= 10) x""")
                leeg["winkels_genoeg_vragen"] = cur.fetchone()["n"]
                return leeg
    except Exception as e:
        print(f"Benchmarkdiagnose mislukt: {e}")
        return leeg
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


# ---------------------------------------------------------------------------
# De benaderlijst
#
# Eén tabel met per winkel hoe ver we zijn. De standen, in volgorde:
#   nieuw        -> net toegevoegd, we weten nog niets
#   geen_adres   -> gezocht, niets bruikbaars gevonden. Hier stopt het.
#   adres        -> er is een algemeen mailadres
#   gemeten      -> de meting bij ChatGPT en Gemini is klaar
#   gemaild      -> hij heeft zijn eigen uitkomst gehad
#   gereageerd / klant / afgevallen -> met de hand gezet
#
# Een winkel gaat nooit twee keer door dezelfde stap. Dat is niet netjesheid,
# dat is de reden dat deze tabel bestaat.
# ---------------------------------------------------------------------------

# "meten" zit hier bewust tussen "adres" en "gemeten".
#
# Zonder die tussenstand kwam een winkel die in de meting zat de volgende ronde
# gewoon weer aan de beurt, want hij stond nog op "adres". Er is toen vijf keer
# voor dezelfde vijf winkels betaald zonder dat er ooit iets afkwam. Zestien
# euro op een dag, en de teller "gemeten" bleef op nul staan.
BENADER_STANDEN = ("nieuw", "geen_adres", "adres", "meten", "gemeten", "gemaild",
                   "gereageerd", "klant", "afgevallen")


def voeg_benadering_toe(webshop_url, naam=None, land=None, branche=None):
    """Zet een winkel op de lijst. Stond hij er al, dan verandert er niets.

    Met opzet DO NOTHING en geen bijwerken: als jij de lijst twee keer plakt,
    mag een winkel die al gemaild is niet terug naar 'nieuw'."""
    if not webshop_url:
        return False
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO benadering (webshop_url, naam, land, branche)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (webshop_url) DO NOTHING""",
                    (webshop_url, naam, land, branche))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Winkel op de benaderlijst zetten mislukt ({webshop_url}): {e}")
        return False
    finally:
        conn.close()


def voeg_benaderingen_toe(regels):
    """Zet een hele lijst winkels in een keer op de benaderlijst.

    Dit bestaat omdat de losse versie hierboven per winkel een eigen verbinding
    met de database opende. Bij tweehonderd winkels zijn dat tweehonderd
    verbindingen achter elkaar: dat duurt te lang en de database kapt hem af,
    en dan zie je een halve lijst en een foutmelding. Een verbinding, een
    opdracht, klaar.

    Elke regel is (webadres, naam, land, branche). Winkels die er al op staan
    blijven staan zoals ze staan. Geeft terug hoeveel er echt bij gekomen zijn.
    """
    regels = [r for r in (regels or []) if r and r[0]]
    if not regels:
        return 0
    conn = _get_connection()
    if conn is None:
        return 0
    try:
        with conn:
            with conn.cursor() as cur:
                gedaan = execute_values(
                    cur,
                    """INSERT INTO benadering (webshop_url, naam, land, branche)
                       VALUES %s
                       ON CONFLICT (webshop_url) DO NOTHING
                       RETURNING webshop_url""",
                    regels, page_size=200, fetch=True)
                return len(gedaan)
    except Exception as e:
        print(f"Winkels op de benaderlijst zetten mislukt: {e}")
        return 0
    finally:
        conn.close()


def get_benadering(webshop_url):
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM benadering WHERE webshop_url = %s",
                            (webshop_url,))
                return cur.fetchone()
    except Exception as e:
        print(f"Benadering ophalen mislukt ({webshop_url}): {e}")
        return None
    finally:
        conn.close()


def get_benaderingen(stand=None, limiet=None, alleen_niet_afgemeld=True):
    """De lijst, oudste eerst. Oudste eerst omdat dat de volgorde van het werk is."""
    conn = _get_connection()
    if conn is None:
        return []
    vraag = "SELECT * FROM benadering"
    waarden, voorwaarden = [], []
    if stand:
        if isinstance(stand, (list, tuple, set)):
            voorwaarden.append("stand = ANY(%s)")
            waarden.append(list(stand))
        else:
            voorwaarden.append("stand = %s")
            waarden.append(stand)
    if alleen_niet_afgemeld:
        voorwaarden.append("afgemeld = FALSE")
    if voorwaarden:
        vraag += " WHERE " + " AND ".join(voorwaarden)
    vraag += " ORDER BY toegevoegd_op, webshop_url"
    if limiet:
        vraag += " LIMIT %s"
        waarden.append(int(limiet))
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(vraag, waarden)
                return cur.fetchall()
    except Exception as e:
        print(f"Benaderlijst ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def zet_benadering(webshop_url, stand=None, email=None, email_bron=None,
                   notitie=None, gemaild=False, afgemeld=None, meting_gestart=False):
    """Werkt één winkel bij. Alleen wat je meegeeft verandert."""
    if not webshop_url:
        return False
    stukken, waarden = ["bijgewerkt_op = now()"], []
    if stand is not None:
        if stand not in BENADER_STANDEN:
            print(f"Onbekende stand geweigerd: {stand}")
            return False
        stukken.append("stand = %s")
        waarden.append(stand)
    for kolom, waarde in (("email", email), ("email_bron", email_bron),
                          ("notitie", notitie)):
        if waarde is not None:
            stukken.append(f"{kolom} = %s")
            waarden.append(waarde)
    if afgemeld is not None:
        stukken.append("afgemeld = %s")
        waarden.append(bool(afgemeld))
    if gemaild:
        stukken.append("gemaild_op = now()")
    if meting_gestart:
        stukken.append("meting_gestart_op = now()")
    waarden.append(webshop_url)
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE benadering SET {', '.join(stukken)} WHERE webshop_url = %s",
                    waarden)
                return cur.rowcount > 0
    except Exception as e:
        print(f"Benadering bijwerken mislukt ({webshop_url}): {e}")
        return False
    finally:
        conn.close()


def tel_benaderingen():
    """Hoeveel winkels er in elke stand staan, plus hoeveel er vandaag gemaild zijn.

    Dat laatste getal is de dagrem. Het telt tegen de klok van de database aan
    en niet tegen een teller in het geheugen, want Render herstart de server
    vaker dan je denkt en een teller in het geheugen staat dan weer op nul."""
    leeg = {"per_stand": {}, "totaal": 0, "vandaag_gemaild": 0}
    conn = _get_connection()
    if conn is None:
        return leeg
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT stand, COUNT(*) FROM benadering GROUP BY stand")
                per_stand = {rij[0]: rij[1] for rij in cur.fetchall()}
                cur.execute("""SELECT COUNT(*) FROM benadering
                                WHERE gemaild_op >= date_trunc('day', now())""")
                vandaag = cur.fetchone()[0]
        return {"per_stand": per_stand, "totaal": sum(per_stand.values()),
                "vandaag_gemaild": vandaag}
    except Exception as e:
        print(f"Benaderlijst tellen mislukt: {e}")
        return leeg
    finally:
        conn.close()


def meld_benadering_af(webshop_url):
    """Iemand wil geen post meer. Dat is definitief en gaat voor alles.

    Het wordt op TWEE plekken vastgelegd, en dat is met opzet. De benaderlijst
    is de werklijst, maar een winkel kan ook langs een andere weg gemeten en
    gemaild zijn en dan staat hij daar helemaal niet op. Zou de afmelding
    alleen daar landen, dan zou zo iemand op een bevestigingsscherm kijken
    terwijl er niets bewaard is, en gewoon opnieuw post krijgen.

    Het winkelprofiel is daarom de plek die telt. De benaderlijst wordt
    bijgewerkt als de winkel er toevallig op staat."""
    if not webshop_url:
        return False
    gelukt = False
    conn = _get_connection()
    if conn is not None:
        try:
            with conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO winkelprofielen (webshop_url, afgemeld_op)
                           VALUES (%s, now())
                           ON CONFLICT (webshop_url) DO UPDATE
                           SET afgemeld_op = coalesce(winkelprofielen.afgemeld_op, now())""",
                        (webshop_url,))
                    gelukt = True
        except Exception as e:
            print(f"Afmelding bewaren mislukt voor {webshop_url}: {e}")
        finally:
            conn.close()
    zet_benadering(webshop_url, stand="afgevallen", afgemeld=True,
                   notitie="Afgemeld via de link in de mail.")
    return gelukt


def is_afgemeld(webshop_url):
    """Of deze winkel gezegd heeft geen post meer te willen.

    Bij twijfel JA. Kunnen wij het niet nakijken omdat de database hapert, dan
    gaat er geen post uit. Een mail te weinig is een ongemak, een mail naar
    iemand die zich heeft afgemeld is een klacht."""
    if not webshop_url:
        return True
    conn = _get_connection()
    if conn is None:
        return True
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT afgemeld_op FROM winkelprofielen
                                WHERE webshop_url = %s""", (webshop_url,))
                rij = cur.fetchone()
                if rij and rij[0]:
                    return True
                cur.execute("""SELECT afgemeld FROM benadering
                                WHERE webshop_url = %s""", (webshop_url,))
                rij = cur.fetchone()
                return bool(rij and rij[0])
    except Exception as e:
        print(f"Afmelding nakijken mislukt voor {webshop_url}: {e}")
        return True
    finally:
        conn.close()


def get_instelling(sleutel, standaard=None):
    conn = _get_connection()
    if conn is None:
        return standaard
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT waarde FROM instellingen WHERE sleutel = %s",
                            (sleutel,))
                rij = cur.fetchone()
                return rij[0] if rij else standaard
    except Exception as e:
        print(f"Instelling ophalen mislukt ({sleutel}): {e}")
        return standaard
    finally:
        conn.close()


def zet_instelling(sleutel, waarde):
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO instellingen (sleutel, waarde)
                       VALUES (%s, %s)
                       ON CONFLICT (sleutel) DO UPDATE
                       SET waarde = EXCLUDED.waarde, bijgewerkt_op = now()""",
                    (sleutel, str(waarde)))
        return True
    except Exception as e:
        print(f"Instelling bewaren mislukt ({sleutel}): {e}")
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Koppelingen met winkels die niet op Shopify draaien
#
# De sleutels gaan versleuteld de database in. Zie kluis.py voor waarom.
# ---------------------------------------------------------------------------

def bewaar_koppeling(webshop_url, platform, basis_url, geheimen):
    """Legt een koppeling vast. De sleutels worden versleuteld.

    Lukt het versleutelen niet, dan bewaren wij NIETS. Liever een klant die
    zijn sleutels opnieuw moet invullen dan sleutels waarmee je in zijn hele
    winkel kunt schrijven, leesbaar in een database."""
    import kluis
    if not webshop_url or not platform or not basis_url:
        return False
    try:
        gesloten = kluis.sluit(geheimen or {})
    except kluis.GeenSleutel as e:
        print(f"Koppeling NIET bewaard voor {webshop_url}: {e}")
        return False
    except Exception as e:
        print(f"Koppeling versleutelen mislukt voor {webshop_url}: {e}")
        return False

    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO koppelingen
                           (webshop_url, platform, basis_url, geheim, stand, bijgewerkt_op)
                       VALUES (%s, %s, %s, %s, 'nieuw', now())
                       ON CONFLICT (webshop_url) DO UPDATE
                       SET platform = EXCLUDED.platform,
                           basis_url = EXCLUDED.basis_url,
                           geheim = EXCLUDED.geheim,
                           stand = 'nieuw',
                           laatste_fout = NULL,
                           bijgewerkt_op = now()""",
                    (webshop_url, platform, basis_url, gesloten),
                )
        return True
    except Exception as e:
        print(f"Koppeling bewaren mislukt voor {webshop_url}: {e}")
        return False
    finally:
        conn.close()


def get_koppeling(webshop_url, met_geheimen=False):
    """De koppeling van deze winkel.

    Zonder met_geheimen krijg je hem ZONDER de sleutels. Dat is de standaard,
    zodat een beheerpagina of een logregel er nooit per ongeluk bij kan."""
    import kluis
    conn = _get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM koppelingen WHERE webshop_url = %s",
                            (webshop_url,))
                rij = cur.fetchone()
    except Exception as e:
        print(f"Koppeling ophalen mislukt voor {webshop_url}: {e}")
        return None
    finally:
        conn.close()

    if not rij:
        return None
    uit = dict(rij)
    versleuteld = uit.pop("geheim", None)
    uit["heeft_sleutels"] = bool(versleuteld)
    if met_geheimen:
        geopend = kluis.open_(versleuteld)
        if geopend is None and versleuteld:
            print(f"LET OP: de sleutels van {webshop_url} zijn niet te openen.")
        uit.update(geopend or {})
    return uit


def zet_koppeling_stand(webshop_url, stand, fout=None):
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE koppelingen
                          SET stand = %s, laatste_fout = %s,
                              gecontroleerd_op = now(), bijgewerkt_op = now()
                        WHERE webshop_url = %s""",
                    (stand, (fout or None), webshop_url),
                )
                return cur.rowcount > 0
    except Exception as e:
        print(f"Koppelingstand bijwerken mislukt voor {webshop_url}: {e}")
        return False
    finally:
        conn.close()


def wis_koppeling(webshop_url):
    """Haalt de koppeling en de sleutels weg. Moet altijd kunnen, in een klik."""
    conn = _get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM koppelingen WHERE webshop_url = %s",
                            (webshop_url,))
                return cur.rowcount > 0
    except Exception as e:
        print(f"Koppeling wissen mislukt voor {webshop_url}: {e}")
        return False
    finally:
        conn.close()


def get_koppelingen():
    """Alle koppelingen, zonder sleutels. Voor de beheerpagina."""
    conn = _get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""SELECT webshop_url, platform, basis_url, stand,
                                      laatste_fout, gecontroleerd_op, aangemaakt_op
                                 FROM koppelingen ORDER BY aangemaakt_op DESC""")
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"Koppelingen ophalen mislukt: {e}")
        return []
    finally:
        conn.close()
