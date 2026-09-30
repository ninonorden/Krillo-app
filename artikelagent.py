"""De artikelagent: elke week een artikel voor /artikelen, Nino keurt goed (stap 203, 30 september).

WAAROM DIT BESTAAT. Nino: "moeten we een artikel agent maken die artikels
aanmaakt voor onze SEO en voor duidelijkheid?". Ja, maar niet zoals de meeste:
dunne AI-teksten in bulk negeren Google en de AI-assistenten zelf. Wat wel
werkt, is wat Krillo zijn klanten ook aanraadt: iets zeggen wat nergens anders
staat. Dat hebben wij: de cijfers uit de index. Dus:
- een artikel per week, over een vraag die webshop-eigenaren echt stellen
  (ONDERWERPEN, op volgorde, geen herhaling);
- elk artikel krijgt de echte cijfers mee uit de index (hoeveel winkels nooit
  genoemd, hoeveel winkels een assistent per antwoord noemt, een echte
  ranglijst) en mag ALLEEN die cijfers gebruiken;
- het concept gaat langs de tekstkeuring (geen beloftes, geen termijnen die
  niet in de voorwaarden staan), en daarna langs Nino op /admin/artikelen.
  Niets komt vanzelf online;
- een goedgekeurd artikel staat meteen op /artikelen, in de sitemap, met een
  eigen adres.

Taal: Engels, zoals de rest van de site. Gewone woorden, geen lange streepjes.
"""
import json
import os
import re
from datetime import date, timedelta

import db

MODEL = os.environ.get("ARTIKEL_MODEL", "claude-sonnet-4-6")
PER_WEEK_DAG = 1          # dinsdag
MIN_DAGEN_TUSSEN = 6

ONDERWERPEN = [
    ("how-to-get-recommended-by-chatgpt", "How do I get my webshop recommended by ChatGPT?"),
    ("what-is-geo-for-webshops", "What is GEO (generative engine optimisation) for a webshop, in plain words?"),
    ("chatgpt-vs-gemini-different-stores", "Why ChatGPT and Gemini name different stores for the same question"),
    ("supplier-product-texts-ai", "Why copied supplier product texts keep your store out of AI answers"),
    ("reviews-and-ai-recommendations", "Do reviews help a webshop get named by AI assistants?"),
    ("price-questions-ai", "How AI assistants answer 'where can I buy X cheap', and what that means for your prices page"),
    ("small-webshop-vs-big-players-ai", "Can a small webshop beat the big players in AI answers?"),
    ("faq-page-for-ai", "Does a questions page (FAQ) help AI recommend your store?"),
    ("comparison-sites-and-ai", "Why comparison sites and lists matter for being named by AI"),
    ("measure-ai-visibility-yourself", "How to check your own AI visibility for free, step by step"),
    ("shopify-store-ai-visibility", "AI visibility for Shopify stores: the five things that matter most"),
    ("woocommerce-ai-visibility", "AI visibility for WooCommerce stores: where to start"),
]


def maak_tabellen(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS artikel_concepten (
            id SERIAL PRIMARY KEY,
            slug TEXT UNIQUE NOT NULL,
            onderwerp TEXT,
            titel TEXT NOT NULL,
            samenvatting TEXT,
            inhoud JSONB NOT NULL,
            leestijd TEXT,
            stand TEXT DEFAULT 'concept',
            keuring TEXT,
            gemaakt_op TIMESTAMPTZ DEFAULT now(),
            gepubliceerd_op TIMESTAMPTZ
        );
    """)


_tabel_klaar = [False]


def _sql(opdracht, waarden=None, alles=False):
    from psycopg2.extras import RealDictCursor
    conn = db._get_connection()
    if conn is None:
        return [] if alles else None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if not _tabel_klaar[0]:
                    maak_tabellen(cur)
                    _tabel_klaar[0] = True
                cur.execute(opdracht, waarden)
                if cur.description is None:
                    return cur.rowcount
                return [dict(r) for r in cur.fetchall()] if alles else (dict(cur.fetchone() or {}) or None)
    finally:
        conn.close()


# ------------------------------------------------------------------ gegevens

def feiten():
    """De echte cijfers die een artikel mag gebruiken. Alleen wat er is."""
    uit = []
    try:
        import linkedinagent
        import markten
        land = linkedinagent.LAND
        cats = db.categorieen_per_land(land) or []
        totaal, nooit = linkedinagent.cijfer(cats, lambda s, l, *a: db.ranglijst_per_land(s, l, 1000), land)
        if totaal >= 50:
            uit.append(f"In the latest Krillo Index measurement, {round(100 * nooit / totaal)}% of the {totaal} "
                       f"webshops we measured in {markten.index_landen_en()} were not named by ChatGPT or Gemini "
                       f"in a single buying question ({len(cats)} categories).")
    except Exception as e:
        print(f"Artikelagent, cijfer mislukt: {e}")
    try:
        import trackerpaginas
        for naam, c in trackerpaginas.assistent_cijfers().items():
            uit.append(f"{naam} named at least one store in {c['procent_met_winkel']}% of {c['antwoorden']} "
                       f"buying questions, and {c['gemiddeld']:g} stores per answer on average.")
    except Exception as e:
        print(f"Artikelagent, assistentcijfers mislukt: {e}")
    return uit


def volgend_onderwerp():
    gehad = {r["onderwerp"] for r in _sql("SELECT onderwerp FROM artikel_concepten", alles=True) or []}
    import artikelen
    gehad |= {a["slug"] for a in artikelen.ARTIKELEN}
    for slug, vraag in ONDERWERPEN:
        if slug not in gehad:
            return slug, vraag
    return None


# ------------------------------------------------------------------ schrijven

def _prompt(vraag, cijfers):
    lijst = "\n".join(f"- {c}" for c in cijfers) or "- (no numbers available this week: use none)"
    return f"""You write one article for the website of Krillo, a service that measures which webshops
ChatGPT and Gemini name and recommend, and helps stores get named more often.

The question the article answers: {vraag}

Rules:
- Plain, calm English for webshop owners. No jargon, no hype, no marketing phrases.
- Never use the long dash character. Use commas or full stops.
- Use ONLY these numbers, exactly as written, and say they come from the Krillo Index. Invent no other
  numbers, percentages, studies or quotes:
{lijst}
- Do not promise results ("guaranteed", "rank first", "in days"). Say what helps and why.
- Practical: give steps a store owner can do this week.
- End with one short paragraph that mentions the free check on krilloai.com, without pressure.
- 600 to 900 words.

Answer ONLY with JSON:
{{"titel": "...", "samenvatting": "one or two sentences", "inhoud": [["section heading or empty", "paragraph"], ...]}}"""


def _vraag_model(prompt):
    import anthropic
    import kosten
    rem = kosten.mag_doorgaan()
    if not rem["mag"]:
        raise RuntimeError(rem["reden"])
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    antwoord = client.messages.create(model=MODEL, max_tokens=4000, messages=[{"role": "user", "content": prompt}])
    try:
        kosten.registreer_aanroep("anthropic", MODEL, antwoord.usage.input_tokens,
                                  antwoord.usage.output_tokens, soort="artikel")
    except Exception:
        pass
    return antwoord.content[0].text


def _lees_json(tekst):
    m = re.search(r"\{.*\}", tekst or "", re.S)
    if not m:
        raise ValueError("geen JSON in het antwoord")
    return json.loads(m.group(0))


def _leestijd(inhoud):
    woorden = sum(len((k or "").split()) + len((a or "").split()) for k, a in inhoud)
    return f"{max(2, round(woorden / 200))} min"


def schrijf_concept(vraag_model=None, onderwerp=None, cijfers=None):
    """Schrijft een concept. Geeft {"gelukt", "id" of "fout"}."""
    keuze = onderwerp or volgend_onderwerp()
    if not keuze:
        return {"gelukt": False, "fout": "Alle onderwerpen zijn geweest. Voeg nieuwe toe in artikelagent.ONDERWERPEN."}
    slug, vraag = keuze
    cijfers = feiten() if cijfers is None else cijfers
    try:
        ruw = (vraag_model or _vraag_model)(_prompt(vraag, cijfers))
        data = _lees_json(ruw)
        inhoud = [(str(k or "").strip(), str(a or "").strip()) for k, a in data.get("inhoud") or [] if (a or "").strip()]
        titel = str(data.get("titel") or vraag).strip()
    except Exception as e:
        return {"gelukt": False, "fout": f"Schrijven mislukt: {type(e).__name__}: {e}"[:300]}
    if len(inhoud) < 4:
        return {"gelukt": False, "fout": "Het concept was te kort."}
    # Lange streepjes eruit: Nino's regel, en een kenmerk van AI-tekst.
    schoon = lambda t: re.sub("\\s*[\u2014\u2013]\\s*", ", ", t)  # noqa: E731
    inhoud = [(schoon(k), schoon(a)) for k, a in inhoud]
    titel = schoon(titel)
    samenvatting = schoon(str(data.get("samenvatting") or "").strip())
    import tekstkeuring
    keuring = tekstkeuring.keur(" ".join([titel, samenvatting] + [k + " " + a for k, a in inhoud]))
    # Getallen die niet uit de cijfers komen: markeren voor Nino (hij beslist).
    toegestaan = set(re.findall(r"\d+(?:[.,]\d+)?", " ".join(cijfers)))
    vreemd = sorted({g for g in re.findall(r"\d+(?:[.,]\d+)?%?", " ".join(a for _, a in inhoud))
                     if g.rstrip("%") not in toegestaan and len(g.rstrip("%")) > 1})
    opmerkingen = list(keuring.get("fouten") or []) + list(keuring.get("waarschuwingen") or [])
    if vreemd:
        opmerkingen.append("getallen die niet uit de index komen, nakijken: " + ", ".join(vreemd[:10]))
    uit = _sql("""INSERT INTO artikel_concepten (slug, onderwerp, titel, samenvatting, inhoud, leestijd, keuring)
                  VALUES (%s, %s, %s, %s, %s, %s, %s)
                  ON CONFLICT (slug) DO NOTHING RETURNING id""",
               (slug, slug, titel, samenvatting, json.dumps(inhoud), _leestijd(inhoud),
                "; ".join(opmerkingen) or None))
    if not uit:
        return {"gelukt": False, "fout": "Er bestaat al een artikel met dit adres."}
    return {"gelukt": True, "id": uit["id"], "keuring_ok": keuring.get("ok", True) and not vreemd}


def ronde(vandaag=None, vraag_model=None):
    """Voor de uurronde: op dinsdag een concept, als er de laatste zes dagen geen kwam."""
    vandaag = vandaag or date.today()
    if vandaag.weekday() != PER_WEEK_DAG:
        return {"overgeslagen": "niet de dag"}
    recent = _sql("SELECT 1 AS x FROM artikel_concepten WHERE gemaakt_op > %s LIMIT 1",
                  (vandaag - timedelta(days=MIN_DAGEN_TUSSEN),))
    if recent:
        return {"overgeslagen": "deze week al"}
    return schrijf_concept(vraag_model=vraag_model)


# ------------------------------------------------------------------ beheer en site

def concepten():
    return _sql("SELECT * FROM artikel_concepten ORDER BY gemaakt_op DESC LIMIT 50", alles=True) or []


def publiceer(concept_id):
    return _sql("UPDATE artikel_concepten SET stand = 'gepubliceerd', gepubliceerd_op = now() WHERE id = %s",
                (concept_id,))


def wijs_af(concept_id):
    return _sql("UPDATE artikel_concepten SET stand = 'afgewezen' WHERE id = %s", (concept_id,))


def gepubliceerd():
    """De goedgekeurde artikelen, in dezelfde vorm als artikelen.ARTIKELEN."""
    uit = []
    for r in _sql("SELECT * FROM artikel_concepten WHERE stand = 'gepubliceerd' ORDER BY gepubliceerd_op DESC",
                  alles=True) or []:
        inhoud = r["inhoud"] if isinstance(r["inhoud"], list) else json.loads(r["inhoud"] or "[]")
        uit.append({"slug": r["slug"], "titel": r["titel"], "samenvatting": r.get("samenvatting") or "",
                    "datum": (r.get("gepubliceerd_op") or r["gemaakt_op"]).strftime("%Y-%m-%d"),
                    "leestijd": r.get("leestijd") or "5 min", "inhoud": [tuple(x) for x in inhoud]})
    return uit
