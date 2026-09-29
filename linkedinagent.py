"""De LinkedIn-agent: drie posts per week voor de bedrijfspagina van Krillo.

WAAROM DIT BESTAAT (29 september). Nino maakte de bedrijfspagina Krillo aan en
vroeg of een agent daar kan posten om bezoek te krijgen. Zijn eigen profiel
gebruiken we niet (besluit Nino), dus alles gaat via de bedrijfspagina.

Eerlijk over wat wel en niet kan:
- Zelf plaatsen via LinkedIn kan pas als LinkedIn ons toegang geeft tot hun
  Community Management API. Die aanvraag loopt via developer.linkedin.com, duurt
  weken en is niet zeker voor een klein bedrijf. Tot dan zet de agent de post
  en het plaatje klaar en plaatst Nino hem: kopieren, plakken, plaatje erbij,
  een minuut werk. Staat LINKEDIN_TOKEN later in Render, dan kan dezelfde agent
  het zelf (stap 173).
- Berichten sturen aan mensen op LinkedIn doen we NIET: dat mag niet volgens
  LinkedIn en kost het account (roadmap, groeioptie 16).
- Een bedrijfspagina met weinig volgers bereikt weinig mensen. Wat wel werkt:
  winkels noemen en taggen die in de post staan. Die krijgen een melding, en
  een winkel die op 1 staat deelt dat graag. Daarom zegt de beheerpagina bij
  elke ranglijstpost welke winkels je moet taggen.

Soorten posts, allemaal uit echte meetdata of vaste, juiste adviezen:
- "ranglijst" (maandag en vrijdag): de top 5 van een categorie, met plaatje.
  Elke keer een andere categorie, de grootste eerst, niet binnen 60 dagen twee
  keer dezelfde.
- "cijfer" (woensdag, om en om met "tip"): hoeveel van de gemeten winkels AI
  in geen enkele koopvraag noemt. Uitgerekend over alle ranglijsten.
- "tip": een concrete verbetering, met een link naar de gratis tools.
Elke link heeft utm_source=linkedin, zodat /admin/bezoek laat zien wat het oplevert.
"""
import io
import os
from datetime import date, timedelta

import db

POSTDAGEN = {0: "ranglijst", 2: "wissel", 4: "ranglijst"}  # maandag, woensdag, vrijdag
DAGEN_VOORUIT = 7
NIET_HERHALEN_DAGEN = 60
LAND = os.environ.get("LINKEDIN_LAND", "nl")

TIPS = [
    ("Let AI in", "Check your robots.txt. If it blocks GPTBot, OAI-SearchBot or Google-Extended, ChatGPT and "
     "Gemini cannot read your store, and they will not recommend what they cannot read. It is one line to fix."),
    ("Answer the question, not the keyword", "Shoppers ask AI full questions: \"which running shoe is best for flat "
     "feet under 100 euros\". Category pages that answer that in plain sentences get named. A list of products "
     "without text does not."),
    ("Product data AI can read", "Structured product data (schema.org Product with price, stock and reviews) is "
     "how AI assistants check your offer. Many stores have it on the product page but not on category pages."),
    ("Be named elsewhere", "AI assistants lean on what others say about you: reviews, comparison articles, "
     "forums. A store that only talks about itself on its own site is rarely the one AI recommends."),
    ("Say who you are for", "\"The largest range\" says nothing to AI. \"Organic baby clothes, made in Europe, "
     "shipped in 1 day in the Netherlands\" gives it a reason to name you for a specific question."),
    ("Measure before you change", "AI answers differ per question and per month. Measure the questions your "
     "buyers ask first, change one thing, and measure again. Otherwise you do not know what worked."),
]


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
        CREATE TABLE IF NOT EXISTS linkedin_posts (
            id SERIAL PRIMARY KEY,
            dag DATE NOT NULL UNIQUE,
            soort TEXT NOT NULL,
            onderwerp TEXT,
            tekst TEXT NOT NULL,
            beeld JSONB,
            taggen TEXT,
            stand TEXT DEFAULT 'klaar',
            geplaatst_op TIMESTAMPTZ,
            gemaakt_op TIMESTAMPTZ DEFAULT now()
        );
    """)


def _naam(rij):
    naam = rij.get("naam")
    if naam and not str(naam).startswith("http"):
        return str(naam)
    return (rij.get("webshop_url") or "").replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")


def _link(basis_url, pad, campagne):
    return f"{basis_url}{pad}?utm_source=linkedin&utm_campaign={campagne}"


def kies_categorie(categorieen, ranglijst, land=LAND):
    """De grootste categorie die de laatste 60 dagen niet aan de beurt was."""
    gehad = {r["onderwerp"] for r in (_sql(
        "SELECT onderwerp FROM linkedin_posts WHERE soort = 'ranglijst' AND dag > current_date - %s",
        (NIET_HERHALEN_DAGEN,), alles=True) or [])}
    kandidaten = []
    for c in categorieen:
        if c["categorie"] in gehad:
            continue
        rijen = (ranglijst(c["categorie"], land) or {}).get("rijen") or []
        genoemd = [r for r in rijen if (r.get("genoemd") or 0) > 0]
        if len(genoemd) >= 5:
            kandidaten.append((len(rijen), c["categorie"], rijen))
    if not kandidaten:
        return None
    kandidaten.sort(key=lambda k: -k[0])
    return kandidaten[0][1], kandidaten[0][2]


def post_ranglijst(slug, rijen, naam_en, landnaam, basis_url):
    top = [r for r in rijen if (r.get("genoemd") or 0) > 0][:5]
    telbaar = max((r.get("telbaar") or 0) for r in top) or None
    # 30 september (Nino's idee): de vraag van de homepage als eerste regel. Een
    # lezer die een webshop heeft, leest hem als een vraag aan zichzelf.
    regels = [f"Is your store one of the three AI names for {naam_en.lower()} in {landnaam}?", "",
              "Which webshops ChatGPT and Gemini recommend right now:", ""]
    for r in top:
        regels.append(f"#{r['positie']} {_naam(r)}")
    regels += [
        "",
        f"We asked the questions shoppers ask{f' ({telbaar} buying questions)' if telbaar else ''} and counted "
        f"which stores AI names. {len(rijen)} stores in this category, measured the same way.",
        "",
        f"The full ranking, and where your store is: {_link(basis_url, f'/index/{LAND}/{slug}', 'ranglijst')}",
        "",
        "#ecommerce #AIsearch #GEO #webshop",
    ]
    beeld = {"soort": "ranglijst", "titel": naam_en, "land": landnaam,
             "rijen": [{"positie": r["positie"], "naam": _naam(r), "genoemd": r.get("genoemd") or 0} for r in top]}
    return "\n".join(regels), beeld, ", ".join(_naam(r) for r in top)


def cijfer(categorieen, ranglijst, land=LAND):
    """Over alle ranglijsten: hoeveel winkels, en hoeveel daarvan nooit genoemd."""
    totaal = nooit = 0
    for c in categorieen:
        for r in (ranglijst(c["categorie"], land) or {}).get("rijen") or []:
            totaal += 1
            if not (r.get("genoemd") or 0):
                nooit += 1
    return totaal, nooit


def post_cijfer(totaal, nooit, aantal_cat, landnaam, basis_url):
    procent = round(100 * nooit / totaal) if totaal else 0
    regels = [
        f"{procent}% of the webshops we measured in {landnaam} were not named by ChatGPT or Gemini in a single "
        "buying question.",
        "",
        f"{totaal} stores, {aantal_cat} categories, the same questions for every store. When a shopper asks AI "
        "where to buy, most stores simply do not exist for that shopper.",
        "",
        f"Is yours one of them? Free check, no account: {_link(basis_url, '/', 'cijfer')}",
        "",
        "#ecommerce #AIsearch #GEO",
    ]
    return "\n".join(regels), {"soort": "cijfer", "groot": f"{procent}%",
                               "onder": f"of {totaal} webshops in {landnaam} were never named by AI"}


def post_tip(nummer, basis_url):
    kop, tekst = TIPS[nummer % len(TIPS)]
    regels = [f"{kop}.", "", tekst, "",
              f"Our free tools check this for your store in a minute: {_link(basis_url, '/tools', 'tip')}",
              "", "#ecommerce #AIsearch #GEO"]
    return "\n".join(regels), {"soort": "tip", "kop": kop, "tekst": tekst}


def klaarzetten(basis_url, categorieen, ranglijst, naam_en, landnaam, vandaag=None):
    """Zorgt dat voor elke postdag in de komende week een post klaarstaat."""
    if os.environ.get("LINKEDINAGENT") == "uit":
        return {"uit": True}
    vandaag = vandaag or date.today()
    gemaakt = []
    for i in range(DAGEN_VOORUIT):
        dag = vandaag + timedelta(days=i)
        soort = POSTDAGEN.get(dag.weekday())
        if not soort or _sql("SELECT 1 AS x FROM linkedin_posts WHERE dag = %s", (dag,)):
            continue
        if soort == "wissel":
            vorige = _sql("SELECT soort FROM linkedin_posts WHERE extract(isodow FROM dag) = 3 AND dag < %s ORDER BY dag DESC LIMIT 1",
                          (dag,))
            soort = "tip" if (vorige or {}).get("soort") == "cijfer" else "cijfer"
        taggen, onderwerp = None, None
        if soort == "ranglijst":
            keuze = kies_categorie(categorieen, ranglijst)
            if not keuze:
                soort = "tip"
            else:
                onderwerp, rijen = keuze
                tekst, beeld, taggen = post_ranglijst(onderwerp, rijen, naam_en(onderwerp), landnaam, basis_url)
        if soort == "cijfer":
            totaal, nooit = cijfer(categorieen, ranglijst)
            if totaal < 50:
                soort = "tip"
            else:
                tekst, beeld = post_cijfer(totaal, nooit, len(categorieen), landnaam, basis_url)
        if soort == "tip":
            n = (_sql("SELECT count(*) AS n FROM linkedin_posts WHERE soort = 'tip'") or {}).get("n") or 0
            onderwerp = str(n % len(TIPS))
            tekst, beeld = post_tip(n, basis_url)
        import json
        _sql("""INSERT INTO linkedin_posts (dag, soort, onderwerp, tekst, beeld, taggen)
                VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (dag) DO NOTHING""",
             (dag, soort, onderwerp, tekst, json.dumps(beeld), taggen))
        gemaakt.append((dag.isoformat(), soort))
    return {"gemaakt": gemaakt}


def posts(limiet=30):
    return _sql("""SELECT * FROM linkedin_posts
                    WHERE dag >= current_date - 14 ORDER BY dag LIMIT %s""", (limiet,), alles=True) or []


def zet_geplaatst(post_id):
    return _sql("UPDATE linkedin_posts SET stand = 'geplaatst', geplaatst_op = now() WHERE id = %s", (post_id,))


def vandaag_klaar():
    return _sql("SELECT * FROM linkedin_posts WHERE dag = current_date AND stand = 'klaar'")


# ---------------------------------------------------------------------------
# Het plaatje: 1200 x 1200, want vierkant neemt op een telefoon het meeste
# scherm in. Zelfde stijl als het deelbeeld van de site.
# ---------------------------------------------------------------------------
BLAUW, WIT, INKT, LICHT, GRIJS, LIJN = (27, 63, 224), (255, 255, 255), (11, 12, 20), (168, 182, 245), (107, 109, 133), (228, 229, 236)
_FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fonts")


def _font(naam, grootte):
    from PIL import ImageFont
    return ImageFont.truetype(os.path.join(_FONTS, naam), grootte)


def _regels_passend(d, tekst, font, breedte):
    woorden, regels, huidig = tekst.split(), [], ""
    for w in woorden:
        proef = (huidig + " " + w).strip()
        if d.textlength(proef, font=font) <= breedte:
            huidig = proef
        else:
            regels.append(huidig)
            huidig = w
    if huidig:
        regels.append(huidig)
    return regels


def beeld_png(beeld, maand=""):
    """Geeft de PNG als bytes."""
    from PIL import Image, ImageDraw
    S, N = 2, 1200
    W = N * S
    im = Image.new("RGB", (W, W), WIT)
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 16 * S), fill=BLAUW)
    kop = _font("SpaceGrotesk-Bold.ttf", 44 * S)
    d.text((80 * S, 120 * S), "KRILLO", font=kop, fill=INKT, anchor="ls")
    d.text((80 * S + d.textlength("KRILLO", font=kop) + 16 * S, 120 * S), "INDEX",
           font=_font("IBMPlexMono-Medium.ttf", 24 * S), fill=GRIJS, anchor="ls")
    soort = beeld.get("soort")
    if soort == "ranglijst":
        titel = _font("SpaceGrotesk-Bold.ttf", 76 * S)
        y = 250 * S
        for regel in _regels_passend(d, f"Who AI recommends: {beeld['titel']}", titel, W - 160 * S)[:2]:
            d.text((80 * S, y), regel, font=titel, fill=INKT, anchor="ls")
            y += 88 * S
        d.text((80 * S, y + 10 * S), f"{beeld['land']} · ChatGPT and Gemini{(' · ' + maand) if maand else ''}",
               font=_font("IBMPlexMono-Medium.ttf", 26 * S), fill=GRIJS, anchor="ls")
        y += 80 * S
        rijen = beeld["rijen"]
        hoogste = max(r["genoemd"] for r in rijen) or 1
        naamfont = _font("SpaceGrotesk-Medium.ttf", 40 * S)
        nrfont = _font("SpaceGrotesk-Bold.ttf", 44 * S)
        for r in rijen:
            d.line((80 * S, y, W - 80 * S, y), fill=LIJN, width=2 * S)
            y += 30 * S
            d.text((80 * S, y + 40 * S), str(r["positie"]), font=nrfont, fill=INKT, anchor="ls")
            naam = r["naam"]
            while d.textlength(naam, font=naamfont) > 560 * S and len(naam) > 4:
                naam = naam[:-2]
            d.text((160 * S, y + 40 * S), naam, font=naamfont, fill=INKT, anchor="ls")
            bx, bl = 760 * S, int(360 * S * r["genoemd"] / hoogste)
            d.rounded_rectangle((bx, y + 16 * S, bx + max(bl, 20 * S), y + 36 * S), 10 * S,
                                fill=BLAUW if r["positie"] <= 3 else LICHT)
            y += 70 * S
        d.line((80 * S, y, W - 80 * S, y), fill=LIJN, width=2 * S)
    elif soort == "cijfer":
        d.text((80 * S, 560 * S), beeld["groot"], font=_font("SpaceGrotesk-Bold.ttf", 300 * S), fill=BLAUW, anchor="ls")
        y = 680 * S
        onder = _font("SpaceGrotesk-Bold.ttf", 60 * S)
        for regel in _regels_passend(d, beeld["onder"], onder, W - 160 * S)[:3]:
            d.text((80 * S, y), regel, font=onder, fill=INKT, anchor="ls")
            y += 76 * S
    else:
        d.text((80 * S, 300 * S), "TIP", font=_font("IBMPlexMono-Medium.ttf", 30 * S), fill=BLAUW, anchor="ls")
        y = 400 * S
        kopfont = _font("SpaceGrotesk-Bold.ttf", 80 * S)
        for regel in _regels_passend(d, beeld["kop"], kopfont, W - 160 * S)[:2]:
            d.text((80 * S, y), regel, font=kopfont, fill=INKT, anchor="ls")
            y += 96 * S
        y += 30 * S
        tf = _font("SpaceGrotesk-Medium.ttf", 40 * S)
        for regel in _regels_passend(d, beeld["tekst"], tf, W - 160 * S)[:8]:
            d.text((80 * S, y), regel, font=tf, fill=GRIJS, anchor="ls")
            y += 56 * S
    d.text((80 * S, W - 80 * S), "krilloai.com/index", font=_font("IBMPlexMono-Medium.ttf", 30 * S),
           fill=BLAUW, anchor="ls")
    uit = io.BytesIO()
    im.resize((N, N), Image.LANCZOS).save(uit, "PNG", optimize=True)
    return uit.getvalue()
