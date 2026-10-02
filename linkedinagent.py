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
import re
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
    # 30 september (stap 207, 208, 212): de link staat in een eigen reactie,
    # de winkels uit de top worden onthouden voor de deelmail, en Nino vult de
    # link naar de geplaatste post en later de weergaven in.
    for kolom in ("reactie TEXT", "winkels JSONB", "post_url TEXT", "weergaven INTEGER",
                  "reacties INTEGER", "gedeeld_gemaild INTEGER"):
        cur.execute(f"ALTER TABLE linkedin_posts ADD COLUMN IF NOT EXISTS {kolom}")
    cur.execute("ALTER TABLE benadering ADD COLUMN IF NOT EXISTS linkedin_op TIMESTAMPTZ")


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
        # Een vraag die mensen willen beantwoorden (30 september). Reacties
        # wegen voor LinkedIn zwaarder dan likes, en elke winkel die iemand
        # noemt is een winkel voor de index.
        f"Which {naam_en.lower()} store is missing from this top {len(top)}? Tell us below.",
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


def link_naar_reactie(tekst, basis_url):
    """Haalt de link uit de post en zet hem in een eigen eerste reactie (stap 207).

    WAAROM: posts met een link naar buiten krijgen volgens de meeste metingen
    minder bereik op LinkedIn. De zin blijft in de post staan, met "link in the
    first comment" waar de link stond. In de reactie komt altijd ook de gratis
    check: die is sinds de verhuizing naar Frankfurt snel genoeg om aan te bieden.
    Geeft (post, reactie)."""
    post, links = [], []
    for regel in tekst.split("\n"):
        if basis_url in regel:
            links.append(regel)
            post.append(re.sub(r"\s*https?://\S+", " link in the first comment.", regel).replace(":  ", ": "))
        else:
            post.append(regel)
    gratis = f"{basis_url}/?utm_source=linkedin&utm_campaign=reactie"
    if not any("utm_campaign=cijfer" in l or "utm_campaign=reactie" in l for l in links):
        links.append(f"Check your own store's rank in 10 seconds, free: {gratis}")
    return "\n".join(post), "\n\n".join(links)


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
        taggen, onderwerp, winkels = None, None, None
        if soort == "ranglijst":
            keuze = kies_categorie(categorieen, ranglijst)
            if not keuze:
                soort = "tip"
            else:
                onderwerp, rijen = keuze
                tekst, beeld, taggen = post_ranglijst(onderwerp, rijen, naam_en(onderwerp), landnaam, basis_url)
                # De top 3 voor de deelmail (stap 208), met plek.
                winkels = [{"webshop_url": r["webshop_url"], "positie": r["positie"]}
                           for r in rijen if (r.get("genoemd") or 0) > 0][:3]
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
        tekst, reactie = link_naar_reactie(tekst, basis_url)
        _sql("""INSERT INTO linkedin_posts (dag, soort, onderwerp, tekst, beeld, taggen, reactie, winkels)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (dag) DO NOTHING""",
             (dag, soort, onderwerp, tekst, json.dumps(beeld), taggen, reactie,
              json.dumps(winkels) if winkels else None))
        gemaakt.append((dag.isoformat(), soort))
    return {"gemaakt": gemaakt}


# ------------------------------------------------------------------ stap 208
# DE DEELMAIL. Een bedrijfspagina bereikt uit zichzelf maar een klein deel van
# de volgers. De winkels die in een ranglijstpost staan hebben volgers die
# precies onze doelgroep zijn, en winkels delen graag dat AI ze aanbeveelt.
# Dus: staat een winkel in de top 3 van een post die Nino net plaatste, dan
# krijgt hij een korte mail met de link naar de post en zijn badge.
#
# Dezelfde regels als elke extra mail: alleen winkels op onze lijst met een
# adres, niet afgemeld, geen bounce of klacht, niet wie terugmailde, 30 dagen
# rust na een andere extra mail (seizoen_op), en per winkel een keer per 90
# dagen een LinkedIn-mail. Afmeldlink en afmeldkop in elke mail.
DEEL_RUST_DAGEN = 90


def deel_kandidaten(winkels):
    urls = [w["webshop_url"] for w in (winkels or []) if w.get("webshop_url")]
    if not urls:
        return []
    return _sql(f"""
        SELECT b.webshop_url, b.email FROM benadering b
         WHERE b.webshop_url = ANY(%s)
           AND b.email IS NOT NULL AND b.email <> ''
           AND NOT b.afgemeld AND b.bounce_op IS NULL AND b.klacht_op IS NULL AND b.antwoord_op IS NULL
           AND coalesce(b.soort, 'winkel') = 'winkel'
           AND (b.seizoen_op IS NULL OR b.seizoen_op < now() - interval '30 days')
           AND (b.linkedin_op IS NULL OR b.linkedin_op < now() - interval '{DEEL_RUST_DAGEN} days')""",
                (urls,), alles=True) or []


def deelmail_tekst(naam, positie, van, categorie, landnaam, post_url):
    """Onderwerp en alinea's. Kort en feitelijk: wat er staat, en waar."""
    onderwerp = f"{naam} is #{positie} in our {categorie.lower()} post on LinkedIn"
    alineas = [
        "Hi,",
        f"We just posted this month's {categorie.lower()} ranking for {landnaam} on LinkedIn. "
        f"<strong>{naam} is #{positie}</strong>{f' of {van} stores' if van else ''}: when shoppers ask "
        f"ChatGPT and Gemini where to buy, your store is one of the names they give.",
        f"Here is the post, in case you want to share it with your followers: "
        f'<a href="{post_url}">{post_url}</a>',
        "And if you like, show it on your site with the badge below. It updates itself every month "
        "and only shows a rank while you are in the top 5.",
    ]
    slot = "Staying on top is the hard part. Watch shows you every month where you stand."
    return onderwerp, alineas, slot


def deelmails(post_id, basis_url, bouw_beeld, categorienaam, landnaam, verstuur=None):
    """Na Geplaatst mét link: de deelmail naar de winkels uit de top. Geeft het aantal verstuurd."""
    import json
    import badgeagent
    p = _sql("SELECT * FROM linkedin_posts WHERE id = %s", (post_id,))
    if not p or p.get("soort") != "ranglijst" or not (p.get("post_url") or "").startswith("https://"):
        return 0
    if p.get("gedeeld_gemaild") is not None:
        return 0   # een keer per post, ook als Nino twee keer op de knop drukt
    winkels = p.get("winkels") or []
    if isinstance(winkels, str):
        winkels = json.loads(winkels)
    if verstuur is None:
        import emailing
        verstuur = emailing.send_badge
    verstuurd = 0
    for w in deel_kandidaten(winkels):
        url = w["webshop_url"]
        try:
            beeld = bouw_beeld(url)
        except Exception:
            beeld = None
        gegevens = badgeagent.badge_gegevens(beeld, categorienaam(beeld) if beeld else None)
        # Alleen als de plek van NU nog in de top 3 staat: nooit een mail over
        # een plek die niet meer klopt.
        if not gegevens or gegevens["plek"] > 3:
            continue
        token = db.get_benchmark_token(url)
        if not token:
            continue
        naam = badgeagent._kaal(url)
        onderwerp, alineas, slot = deelmail_tekst(naam, gegevens["plek"], beeld.get("van"),
                                                  gegevens["categorie"] or "your category",
                                                  landnaam(beeld) or "your country", p["post_url"])
        pagina = f"{basis_url}/index/{(beeld.get('land') or '').lower()}/{beeld.get('categorie')}"
        code = badgeagent.embedcode(basis_url, token, pagina, gegevens)
        _sql("UPDATE benadering SET linkedin_op = now(), seizoen_op = now() WHERE webshop_url = %s", (url,))
        if verstuur(w["email"], onderwerp, alineas, code, slot, f"{basis_url}/uitkomst/{token}",
                    afmeld_url=f"{basis_url}/afmelden/{token}"):
            verstuurd += 1
    _sql("UPDATE linkedin_posts SET gedeeld_gemaild = %s WHERE id = %s", (verstuurd, post_id))
    return verstuurd


def zet_cijfers(post_id, weergaven, reacties):
    """Stap 212: LinkedIn geeft zijn cijfers niet aan ons door, dus Nino vult ze in."""
    _sql("UPDATE linkedin_posts SET weergaven = %s, reacties = %s WHERE id = %s",
         (weergaven, reacties, post_id))


def beste_soort():
    """Welk soort post gemiddeld de meeste weergaven haalt. None bij te weinig cijfers."""
    rijen = _sql("""SELECT soort, round(avg(weergaven)) AS gem, count(*) AS n FROM linkedin_posts
                     WHERE weergaven IS NOT NULL GROUP BY soort ORDER BY avg(weergaven) DESC""",
                 alles=True) or []
    if sum(r["n"] for r in rijen) < 3:
        return None
    return rijen


def posts(limiet=30):
    return _sql("""SELECT * FROM linkedin_posts
                    WHERE dag >= current_date - 14 ORDER BY dag LIMIT %s""", (limiet,), alles=True) or []


def zet_geplaatst(post_id, post_url=None):
    return _sql("UPDATE linkedin_posts SET stand = 'geplaatst', geplaatst_op = now(), "
                "post_url = coalesce(%s, post_url) WHERE id = %s", (post_url, post_id))


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
    elif soort in ("omslag", "slot"):
        # Stap 209: de eerste en laatste pagina van het maandrapport.
        d.text((80 * S, 300 * S), beeld.get("boven", ""), font=_font("IBMPlexMono-Medium.ttf", 30 * S),
               fill=BLAUW, anchor="ls")
        y = 420 * S
        kopfont = _font("SpaceGrotesk-Bold.ttf", 96 * S)
        for regel in _regels_passend(d, beeld["kop"], kopfont, W - 160 * S)[:3]:
            d.text((80 * S, y), regel, font=kopfont, fill=INKT, anchor="ls")
            y += 110 * S
        y += 40 * S
        tf = _font("SpaceGrotesk-Medium.ttf", 44 * S)
        for regel in _regels_passend(d, beeld.get("tekst", ""), tf, W - 160 * S)[:6]:
            d.text((80 * S, y), regel, font=tf, fill=GRIJS, anchor="ls")
            y += 60 * S
    elif soort == "stijgers":
        titel = _font("SpaceGrotesk-Bold.ttf", 76 * S)
        d.text((80 * S, 260 * S), "Biggest climbers", font=titel, fill=INKT, anchor="ls")
        d.text((80 * S, 330 * S), f"{beeld.get('land', '')} · since the previous measurement",
               font=_font("IBMPlexMono-Medium.ttf", 26 * S), fill=GRIJS, anchor="ls")
        y = 400 * S
        naamfont = _font("SpaceGrotesk-Medium.ttf", 38 * S)
        pijlfont = _font("SpaceGrotesk-Bold.ttf", 44 * S)
        for r in beeld["rijen"][:6]:
            d.line((80 * S, y, W - 80 * S, y), fill=LIJN, width=2 * S)
            d.text((80 * S, y + 70 * S), f"+{r['plekken']}", font=pijlfont, fill=BLAUW, anchor="ls")
            naam = f"{r['naam']} · {r['categorie']} · now #{r['positie']}"
            while d.textlength(naam, font=naamfont) > W - 420 * S and len(naam) > 4:
                naam = naam[:-2]
            d.text((230 * S, y + 70 * S), naam, font=naamfont, fill=INKT, anchor="ls")
            y += 110 * S
        d.line((80 * S, y, W - 80 * S, y), fill=LIJN, width=2 * S)
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



# ------------------------------------------------------------------ stap 209
# HET MAANDRAPPORT ALS DOCUMENTPOST. Na elke maandmeting een PDF van zes tot
# acht pagina's die Nino op LinkedIn als document plaatst. Mensen bladeren
# erdoorheen; dat is aandacht die een gewone post niet krijgt. Alleen echte
# cijfers uit de index, dezelfde als op de openbare pagina's.
RAPPORT_CATEGORIEEN = 4


def rapport_paginas(categorieen, ranglijst, naam_en, landnaam, maand, land=LAND):
    """De pagina's (als beeld-woordenboeken) van het maandrapport."""
    totaal, nooit = cijfer(categorieen, ranglijst, land)
    paginas = [{"soort": "omslag", "boven": f"KRILLO INDEX · {maand.upper()}",
                "kop": f"Which webshops AI recommends in {landnaam}",
                "tekst": f"{totaal} stores, {len(categorieen)} categories. We asked ChatGPT and Gemini the "
                         f"buying questions shoppers ask, and counted who they name. Swipe through."}]
    if totaal >= 50:
        procent = round(100 * nooit / totaal) if totaal else 0
        paginas.append({"soort": "cijfer", "groot": f"{procent}%",
                        "onder": f"of {totaal} webshops in {landnaam} were never named by AI"})
    stijgers = []
    for c in sorted(categorieen, key=lambda c: -(c.get("winkels") or 0))[:RAPPORT_CATEGORIEEN]:
        rijen = (ranglijst(c["categorie"], land, 1000) or {}).get("rijen") or []
        top = [r for r in rijen if (r.get("genoemd") or 0) > 0][:5]
        if len(top) >= 3:
            paginas.append({"soort": "ranglijst", "titel": naam_en(c["categorie"]), "land": landnaam,
                            "rijen": [{"positie": r["positie"], "naam": _naam(r), "genoemd": r.get("genoemd") or 0}
                                      for r in top]})
    for c in categorieen:
        for r in (ranglijst(c["categorie"], land, 1000) or {}).get("rijen") or []:
            if r.get("vorige_positie") and r["vorige_positie"] - r["positie"] >= 3 and (r.get("genoemd") or 0) > 0:
                stijgers.append({"naam": _naam(r), "categorie": naam_en(c["categorie"]),
                                 "positie": r["positie"], "plekken": r["vorige_positie"] - r["positie"]})
    if stijgers:
        stijgers.sort(key=lambda r: -r["plekken"])
        paginas.append({"soort": "stijgers", "land": landnaam, "rijen": stijgers[:6]})
    paginas.append({"soort": "slot", "boven": "YOUR STORE",
                    "kop": "Where does your store rank?",
                    "tekst": "Free check, no account, ten seconds: krilloai.com. Every ranking is public, "
                             "measured the same way for every store. Nobody can pay for a better place."})
    return paginas


def rapport_pdf(paginas, maand=""):
    """De pagina's als een PDF, klaar om als document te plaatsen."""
    from PIL import Image
    beelden = [Image.open(io.BytesIO(beeld_png(p, maand=maand))).convert("RGB") for p in paginas]
    uit = io.BytesIO()
    beelden[0].save(uit, "PDF", save_all=True, append_images=beelden[1:], resolution=150)
    return uit.getvalue()


# ------------------------------------------------------------------ volgen en uitnodigen (30 september)
# Nino: "kan er op de linkedin admin pagina iets komen dat er mensen of
# bedrijven worden voorgesteld die echt het meest geschikt zijn, voor inviting
# en following, die gelijk loopt met de markten". Elke dag een paar:
# - PAGINA'S OM TE VOLGEN: winkels uit de top van onze eigen ranglijsten (die
#   zien dat Krillo ze volgt, en het is precies de doelgroep), gevonden bureaus,
#   en de vaste e-commercepartijen van het land. Alleen landen die de index
#   meet (markten.index_landen), dus nu Nederland en Belgie.
# - WIE UITNODIGEN: LinkedIn laat alleen je eigen connecties uitnodigen, en die
#   zien wij niet. Dus zoekwoorden om in het uitnodigscherm te typen, zodat
#   Nino de passende mensen vindt. Er zijn 50 uitnodigingen per maand: liever
#   een paar goede per dag dan alles in een keer.
# De links zijn zoekopdrachten op LinkedIn, geen geraden paginanamen: een
# verzonnen adres dat naar een verkeerde pagina gaat is erger dan zoeken.
VOLGEN_PER_DAG = 5
UITNODIG_PER_DAG = 3
VASTE_PAGINAS = {
    "nl": ["Thuiswinkel.org", "Emerce", "Twinkle", "Frankwatching", "Marketingfacts", "ShoppingTomorrow",
           "Webwinkel Vakdagen", "Dutch Digital Agencies", "Channable", "Sendcloud", "MyParcel", "Mollie"],
    "be": ["BeCommerce", "Comeos", "RetailDetail", "Gondola"],
}
UITNODIG_WOORDEN = ["webshop", "e-commerce", "Shopify", "WooCommerce", "online marketing", "SEO",
                    "marketing manager", "eigenaar", "founder", "retail", "Lightspeed", "Magento"]
_GEHAD = "linkedin_volg_gehad"


def _zoeklink(naam, soort="companies"):
    from urllib.parse import quote
    return f"https://www.linkedin.com/search/results/{soort}/?keywords={quote(naam)}"


def _kandidaat_paginas(landen, ranglijst=None, categorieen_per_land=None):
    """(naam, waarom) van alles wat de moeite van volgen waard is."""
    uit = []
    ranglijst = ranglijst or (lambda slug, land, *a: db.ranglijst_per_land(slug, land, 1000))
    categorieen_per_land = categorieen_per_land or db.categorieen_per_land
    for land in landen:
        for c in categorieen_per_land(land) or []:
            for r in ((ranglijst(c["categorie"], land) or {}).get("rijen") or [])[:3]:
                if (r.get("genoemd") or 0) > 0:
                    uit.append((_naam(r), f"#{r['positie']} in {c['categorie']} ({land.upper()}), een winkel uit de index"))
    try:
        for b in _sql("SELECT site, naam FROM bureaus WHERE coalesce(stand, '') <> 'afgemeld' "
                      "ORDER BY site LIMIT 200", alles=True) or []:
            uit.append((b.get("naam") or b["site"].replace("https://", ""), "webbureau dat voor webshops werkt"))
    except Exception:
        pass
    for land in landen:
        for naam in VASTE_PAGINAS.get(land, []):
            uit.append((naam, f"e-commerce in {land.upper()}: hun volgers zijn onze doelgroep"))
    return uit


def suggesties(vandaag=None, ranglijst=None, categorieen_per_land=None, landen=None):
    """Wat Nino vandaag volgt en in welke hoek hij uitnodigt. Elke dag andere
    pagina's, tot alles een keer langs is geweest."""
    import json
    import markten
    vandaag = vandaag or date.today()
    landen = landen or list(markten.index_landen())
    try:
        gehad = json.loads(db.get_instelling(_GEHAD) or "{}")
    except ValueError:
        gehad = {}
    dag = vandaag.isoformat()
    if dag in gehad.get("per_dag", {}):
        namen = gehad["per_dag"][dag]
    else:
        al = set(gehad.get("namen", []))
        pool = [n for n, _ in _kandidaat_paginas(landen, ranglijst, categorieen_per_land)]
        vers = [n for n in dict.fromkeys(pool) if n not in al]
        if len(vers) < VOLGEN_PER_DAG:          # alles gehad: opnieuw beginnen
            al, vers = set(), list(dict.fromkeys(pool))
        namen = vers[:VOLGEN_PER_DAG]
        per_dag = dict(list(gehad.get("per_dag", {}).items())[-6:])
        per_dag[dag] = namen
        db.zet_instelling(_GEHAD, json.dumps({"namen": sorted(al | set(namen))[-2000:], "per_dag": per_dag}))
    waarom = dict(_kandidaat_paginas(landen, ranglijst, categorieen_per_land))
    start = vandaag.toordinal() * UITNODIG_PER_DAG % len(UITNODIG_WOORDEN)
    woorden = [UITNODIG_WOORDEN[(start + i) % len(UITNODIG_WOORDEN)] for i in range(UITNODIG_PER_DAG)]
    return {"volgen": [{"naam": n, "waarom": waarom.get(n, ""), "link": _zoeklink(n)} for n in namen],
            "uitnodigen": woorden}


# ---------------------------------------------------------------------------
# DE DAGELIJKSE GROEIROUTINE (2 oktober 2026, Nino).
#
# Nino stuurde een draad van mensen met meer dan 10.000 volgers. De kern, in
# zijn eigen woorden: geen willekeurige connecties, en dan vijf dingen:
# 1. profiel optimaliseren met woorden waarop gezocht wordt;
# 2. twee of drie onderwerpen kiezen;
# 3. consequent waardevolle posts (dat doet de agent al: drie per week);
# 4. twintig mensen uit de branche kiezen en elke dag op hun posts reageren;
# 5. elke dag vijf nieuwe, passende mensen connecten, en iets toevoegen.
# De draad zelf konden wij niet openen (Reddit weigert ons), dus dit zijn de
# punten die Nino eruit haalde.
#
# EERLIJK OVER WAT KAN: een bedrijfspagina kan niet connecten; dat gaat via het
# eigen profiel van Nino (net als het uitnodigen, dat al van zijn naam komt).
# Reageren kan als Krillo of als Nino; als persoon werkt het beter. LinkedIn
# laat ons geen mensen opzoeken via een koppeling: de agent geeft daarom
# zoeklinks met de juiste woorden, en Nino bewaart zijn twintig mensen hier.
# Niets wordt automatisch verstuurd: dat mag niet en kost het account.
# ---------------------------------------------------------------------------
EXPERTS_SLEUTEL = "linkedin_experts"
PROFIEL_SLEUTEL = "linkedin_profiel_gedaan"
EXPERTS_MAX = 20
REAGEREN_PER_DAG = 3
CONNECTEN_PER_DAG = 5

ONDERWERPEN = [
    ("AI-zichtbaarheid van webshops", "Wie ChatGPT en Gemini noemen als iemand vraagt waar hij iets koopt, en waarom."),
    ("De Krillo Index in cijfers", "Elke maand echte metingen per categorie: wie stijgt, wie zakt, waar niemand genoemd wordt."),
    ("Kleine fixes die werken", "Eén concrete verbetering per post: robots.txt, producttekst, productgegevens, reviews."),
]

# Zoekwoorden om de twintig experts te vinden (mensen, niet bedrijven).
EXPERT_ZOEKWOORDEN = ["AI search ecommerce", "generative engine optimization", "GEO SEO", "ecommerce Nederland",
                      "Shopify expert Nederland", "WooCommerce specialist", "e-commerce consultant",
                      "conversie optimalisatie webshop", "Thuiswinkel", "retail tech"]
# Zoekwoorden voor de vijf connecties per dag: wie een webshop heeft of runt.
CONNECT_ZOEKWOORDEN = ["eigenaar webshop", "founder webshop", "e-commerce manager", "webshop owner",
                       "Shopify store owner Nederland", "online marketing webshop", "head of ecommerce",
                       "oprichter webwinkel", "ecommerce lead Belgie", "marketing manager webshop"]

PROFIEL_TAKEN = [
    "Kopregel van je profiel (Headline) met zoekwoorden, bijvoorbeeld: \"Founder Krillo | AI visibility for "
    "webshops | ChatGPT, Gemini, GEO\".",
    "Info (About): drie zinnen. Wat Krillo meet, voor wie, en een cijfer uit de index. Woorden waarop gezocht "
    "wordt: AI search, GEO, ecommerce, webshop, Shopify, WooCommerce.",
    "Bij Ervaring: Krillo met de bedrijfspagina gekoppeld, zodat je profiel en de pagina elkaar versterken.",
    "Bedrijfspagina Krillo: bij Over dezelfde zoekwoorden, en de website krilloai.com.",
]

CONNECT_NOTITIE = ("Hi {naam}, I measure which webshops ChatGPT and Gemini recommend (the Krillo Index). "
                   "I saw you work on {wat}, so I thought it is nice to be connected. No sales pitch.")


def _zoek_mensen(woorden):
    return _zoeklink(woorden, soort="people")


def experts():
    import json
    try:
        lijst = json.loads(db.get_instelling(EXPERTS_SLEUTEL) or "[]")
    except ValueError:
        lijst = []
    return [e for e in lijst if e.get("naam")][:EXPERTS_MAX]


def bewaar_experts(tekst):
    """Een per regel: "Naam | link" (de link mag weg). Hoogstens twintig."""
    import json
    lijst = []
    for regel in (tekst or "").splitlines():
        delen = [d.strip() for d in regel.split("|")]
        if not delen or not delen[0]:
            continue
        link = delen[1] if len(delen) > 1 and delen[1].startswith("https://") else ""
        lijst.append({"naam": delen[0][:80], "link": link[:300]})
    lijst = lijst[:EXPERTS_MAX]
    db.zet_instelling(EXPERTS_SLEUTEL, json.dumps(lijst))
    return lijst


def index_feit(categorieen=None, ranglijst=None, land=LAND):
    """Een echt cijfer uit de index om in een reactie te gebruiken. Een reactie
    met een cijfer voegt iets toe; "great post!" niet."""
    try:
        categorieen = categorieen if categorieen is not None else db.categorieen_per_land(land) or []
        ranglijst = ranglijst or (lambda slug, l, *a: db.ranglijst_per_land(slug, l, 1000))
        totaal, nooit = cijfer(categorieen, ranglijst, land)
    except Exception:
        return None
    if not totaal:
        return None
    procent = round(100 * nooit / totaal)
    return (f"In our measurements {procent}% of {totaal} webshops in "
            f"{'the Netherlands' if land == 'nl' else land.upper()} were not named by ChatGPT or Gemini in a single "
            f"buying question.")


def dag_routine(vandaag=None, categorieen=None, ranglijst=None):
    """De taken van vandaag, met de tactiek erbij. Ongeveer 15 minuten."""
    vandaag = vandaag or date.today()
    n = vandaag.toordinal()
    lijst = experts()
    if lijst:
        start = (n * REAGEREN_PER_DAG) % len(lijst)
        reageren = [lijst[(start + i) % len(lijst)] for i in range(min(REAGEREN_PER_DAG, len(lijst)))]
    else:
        reageren = []
    zoek_expert = EXPERT_ZOEKWOORDEN[n % len(EXPERT_ZOEKWOORDEN)]
    zoek_connect = CONNECT_ZOEKWOORDEN[n % len(CONNECT_ZOEKWOORDEN)]
    onderwerp = ONDERWERPEN[n % len(ONDERWERPEN)]
    profiel_klaar = (db.get_instelling(PROFIEL_SLEUTEL) or "") == "ja"
    return {
        "reageren": reageren,
        "experts_aantal": len(lijst),
        "experts_zoek": {"woorden": zoek_expert, "link": _zoek_mensen(zoek_expert)},
        "connecten": {"aantal": CONNECTEN_PER_DAG, "woorden": zoek_connect, "link": _zoek_mensen(zoek_connect),
                      "notitie": CONNECT_NOTITIE},
        "feit": index_feit(categorieen, ranglijst),
        "onderwerp": {"naam": onderwerp[0], "uitleg": onderwerp[1]},
        "profiel": [] if profiel_klaar else PROFIEL_TAKEN,
    }


def routine_taak():
    """Een regel voor de dagtaken in het ochtendbericht."""
    r = dag_routine()
    if r["experts_aantal"] < EXPERTS_MAX:
        return (f"LinkedIn (15 min): zoek {min(5, EXPERTS_MAX - r['experts_aantal'])} experts voor je lijst van 20 "
                f"(zoek op \"{r['experts_zoek']['woorden']}\"), reageer op 3 posts, connect met 5 mensen.", 15)
    namen = ", ".join(e["naam"] for e in r["reageren"])
    return (f"LinkedIn (15 min): reageer met iets dat toevoegt op een post van {namen}, en connect met 5 mensen "
            f"(zoek op \"{r['connecten']['woorden']}\").", 15)
