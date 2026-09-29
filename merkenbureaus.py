"""De pagina voor merken en bureaus (/agencies), 29 september.

WAAROM DIT BESTAAT. Op de prijzenpagina stond bij "Brands and agencies" een
knop "Talk to us" die meteen een lege mail opende. Nino: "dat moet beter". Wie
op zo'n knop drukt wil eerst zien wat hij krijgt; een lege mail schrijven is
een drempel waar de meeste mensen niet overheen gaan.

Wat de concurrenten doen: Peec heeft een eigen pagina voor bureaus met
"pitch workspaces" (gratis een merk laten zien aan een prospect) en een
aparte prijspagina; Otterly en Profound hebben "Book a demo". Allemaal een
formulier of een afspraak, en het echte beeld komt pas na dat gesprek.

Wat wij beter doen: het beeld komt EERST. Een bureau plakt tot tien
webshops van klanten of prospects en ziet meteen, zonder account, waar elk van
die winkels in de Krillo Index staat. Dat is precies het gesprek dat het bureau
met zijn klant wil voeren ("ChatGPT noemt je concurrent, jou niet"), en het
kost ons niets: het komt uit de ranglijsten die er al liggen. Daarna een kort
formulier; Nino krijgt meteen bericht en de aanvrager een bevestiging.

Wat er NIET gebeurt: geen verzonnen cijfers. Staat een winkel niet in de index,
dan staat er dat, met een link naar de gratis check.
"""
import db

MAX_WINKELS_PITCH = 10


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
    cur.execute("""
        CREATE TABLE IF NOT EXISTS merkaanvragen (
            id SERIAL PRIMARY KEY,
            naam TEXT, bedrijf TEXT, email TEXT NOT NULL, website TEXT,
            aantal TEXT, soort TEXT, bericht TEXT, winkels TEXT,
            stand TEXT DEFAULT 'nieuw',
            gemaakt_op TIMESTAMPTZ DEFAULT now()
        );
    """)


def schoon_adres(tekst):
    """Van 'https://www.Winkel.nl/pagina' naar 'winkel.nl'."""
    t = (tekst or "").strip().lower()
    for voor in ("https://", "http://"):
        if t.startswith(voor):
            t = t[len(voor):]
    if t.startswith("www."):
        t = t[4:]
    return t.split("/")[0].split("?")[0].strip()


def lees_winkels(tekst):
    """Een lijst adressen uit wat iemand plakt: regels, komma's of spaties."""
    uit = []
    for stuk in (tekst or "").replace(",", "\n").replace(";", "\n").split():
        a = schoon_adres(stuk)
        if "." in a and a not in uit and len(a) < 120:
            uit.append(a)
    return uit[:MAX_WINKELS_PITCH]


def pitch(winkels, landen, categorieen_van, ranglijst_van, naam_van, slug_van):
    """Per winkel: waar staat hij in de index. Alles uit de bewaarde ranglijsten.

    De functies komen van de aanroeper (app.py) zodat dit dezelfde bewaarde
    lijsten gebruikt als de site, en in de test zonder database kan draaien.
    Per winkel de BESTE plek over alle categorieen, plus in hoeveel
    categorieen hij voorkomt."""
    gevonden = {w: [] for w in winkels}
    if not winkels:
        return []
    for land in landen:
        for cat in categorieen_van(land):
            lijst = ranglijst_van(cat, land) or {}
            rijen = lijst.get("rijen") or []
            for r in rijen:
                a = schoon_adres(r.get("webshop_url"))
                if a in gevonden:
                    gevonden[a].append({
                        "land": land, "categorie": cat, "categorienaam": naam_van(cat),
                        "positie": r.get("positie"), "van": len(rijen),
                        "genoemd": r.get("genoemd") or 0,
                        "eerste": next((schoon_adres(x.get("webshop_url")) for x in rijen
                                        if x.get("positie") == 1), None),
                        "pad": (f"/index/{land}/{cat}/{slug_van(r['webshop_url'])}"
                                if (r.get("genoemd") or 0) > 0 else f"/index/{land}/{cat}"),
                    })
    uit = []
    for w in winkels:
        plekken = sorted(gevonden[w], key=lambda p: (-(p["genoemd"] > 0), p["positie"] or 999))
        uit.append({"winkel": w, "beste": plekken[0] if plekken else None,
                    "categorieen": len(plekken)})
    return uit


def bewaar(naam, bedrijf, email, website, aantal, soort, bericht, winkels):
    return _sql("""INSERT INTO merkaanvragen (naam, bedrijf, email, website, aantal, soort, bericht, winkels)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (naam, bedrijf, email, website, aantal, soort, bericht, winkels))


def aanvragen(limiet=50):
    return _sql("SELECT * FROM merkaanvragen ORDER BY gemaakt_op DESC LIMIT %s", (limiet,), alles=True) or []


def bevestiging(naam, soort):
    """De automatische bevestiging. Kort, en zegt wat er nu gebeurt."""
    aanhef = f"Hi {naam.split()[0]}," if naam else "Hi,"
    wie = "your brand" if soort == "brand" else "your clients"
    return {
        "onderwerp": "We got your request: Krillo for brands and agencies",
        "alineas": [
            aanhef,
            f"Thanks for your request. Within one working day you get a personal reply from Nino, the founder, "
            f"about where ChatGPT and Gemini recommend {wie} and how we set it up.",
            "The plan is EUR 490 a month for up to 25 stores, each with its own dashboard, and you can cancel "
            "any month. Want to add something before we reply? Just reply to this email.",
        ],
    }
