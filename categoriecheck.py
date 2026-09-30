"""De categoriecheck: lees de site zelf voordat een winkel post krijgt of in een ranglijst staat (30 september).

WAAROM DIT BESTAAT. bel-air.be, een autoverhuur met chauffeur, kreeg de koude
mail "Who AI recommends: Clothing in Belgium" en mailde terug dat het niet
klopt. Terecht. De oorzaak zat in ons, niet in AI: de winkelvinder zocht op
"kleding webshop Belgie", nam wat de zoekmachine gaf, en de indeling keek
daarna alleen naar het webadres en de naam. Niemand las de site zelf. Een
naam als "Bel-Air" klinkt als mode; het is een limousineservice.

Nino: "dit kan echt niet gebeuren, alles moet goed staan." Dus nu:
- voordat een winkel een koude mail krijgt, leest deze check zijn homepage:
  titel, omschrijving, koppen, het begin van de tekst, en of er een winkelmand
  of producten met een prijs op staan;
- een model beoordeelt met DIE tekst: is dit een webshop die aan consumenten
  verkoopt, en in welke van onze categorieen hoort hij;
- geen webshop: hij gaat uit de post EN uit elke ranglijst (soort geen-webshop);
- webshop in een andere categorie: hij krijgt de goede categorie;
- twijfel of een site die niet opent: geen post, over 14 dagen opnieuw;
- de koude mail gaat ALLEEN nog naar winkels waarvan de check "klopt" zei
  (db.te_mailen_met_positie). Liever een dag minder post dan een foute mail.
Daarna ook de winkels die al in een openbare ranglijst staan, zodat de index
zelf schoon wordt.

Kosten: een aanroep per CHECK_PER_AANROEP winkels (een paar cent). Dit is
kwaliteitsbewaking van wat er naar buiten gaat, dus met voorrang op de dagpot.
"""
import json
import os
import re
import time

import db

CHECK_PER_AANROEP = int(os.environ.get("CATEGORIECHECK_PER_AANROEP", "12"))
CHECK_PER_RONDE = int(os.environ.get("CATEGORIECHECK_PER_RONDE", "36"))
OPNIEUW_NA_DAGEN = 14
MODEL = os.environ.get("CATEGORIECHECK_MODEL", "claude-sonnet-4-6")
SOORT_GEEN_WEBSHOP = "geen-webshop"

_WINKELTEKENS = re.compile(
    r"winkelwagen|winkelmand|in mijn mand|add to cart|add to basket|shopping cart|\bcart\b|checkout|"
    r"afrekenen|bestel nu|in winkelwagen|warenkorb|panier|ajouter au panier|woocommerce|shopify|"
    r"lightspeed|ccvshop|/product/|/products/|/collections/|gratis verzending|free shipping", re.I)
_PRIJS = re.compile(r"(€|eur)\s?\d+[.,]\d{2}|\d+[.,]\d{2}\s?(€|eur)", re.I)


def lees_site(url, ophalen=None):
    """Wat de homepage over zichzelf zegt, of None als hij niet opent."""
    try:
        if ophalen is not None:
            r = ophalen(url)
        else:
            import scan_engine
            r = scan_engine.fetch(url, pogingen=1)
    except Exception:
        return None
    if r is None or getattr(r, "status_code", 500) >= 400:
        return None
    html = r.text or ""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    titel = (soup.title.string or "").strip() if soup.title and soup.title.string else ""
    meta = soup.find("meta", attrs={"name": "description"})
    omschrijving = (meta.get("content") or "").strip() if meta else ""
    koppen = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2"])][:6]
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    tekst = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:700]
    return {"titel": titel[:200], "omschrijving": omschrijving[:300], "koppen": koppen,
            "tekst": tekst, "winkeltekens": bool(_WINKELTEKENS.search(html)),
            "prijzen": len(_PRIJS.findall(html))}


def _prompt(groep, categorieen_lijst):
    regels = []
    for w in groep:
        s = w["site"]
        regels.append(json.dumps({
            "url": w["webshop_url"], "nu_in": w["categorie"], "titel": s["titel"],
            "omschrijving": s["omschrijving"], "koppen": s["koppen"], "tekst": s["tekst"],
            "winkelmand_op_de_site": s["winkeltekens"], "prijzen_op_de_homepage": s["prijzen"]},
            ensure_ascii=False))
    cats = ", ".join(f"{slug} ({naam})" for slug, naam in categorieen_lijst)
    return f"""Below are websites with what their homepage says. For each, decide from THE TEXT
(not from the name or address):

soort:
- "winkel": an online store that sells products to consumers on this site (a shop you can order from).
- "geen_webshop": not a store: a service (car rental, taxi, repair, hairdresser, agency, restaurant),
  a blog, a company page, a school, a manufacturer without a consumer shop.
- "merk": a brand that mainly sells through other stores.
- "platform": a marketplace or comparison site where others sell.
- "onbekend": the text does not make it clear. Choose this rather than guessing.

categorie: only for "winkel": the ONE best fitting category slug from this list, or null if none fits:
{cats}

Sites:
{chr(10).join(regels)}

Answer only with JSON: {{"uitkomst": [{{"url": "...", "soort": "winkel", "categorie": "slug or null"}}]}}"""


def _vraag_model(prompt):
    import anthropic
    import kosten
    rem = kosten.mag_doorgaan(voorrang=True)
    if not rem["mag"]:
        raise RuntimeError(rem["reden"])
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    gestart = time.monotonic()
    antwoord = client.messages.create(model=MODEL, max_tokens=3000,
                                      messages=[{"role": "user", "content": prompt}])
    try:
        kosten.registreer_aanroep("anthropic", MODEL, antwoord.usage.input_tokens,
                                  antwoord.usage.output_tokens, soort="categoriecheck",
                                  duur_ms=int((time.monotonic() - gestart) * 1000))
    except Exception:
        pass
    return antwoord.content[0].text


def _categorieen_lijst():
    import categorieen
    ouders = {ouder for _, _, ouder in categorieen.CATEGORIEEN if ouder}
    return [(slug, naam) for slug, naam, _ in categorieen.CATEGORIEEN if slug not in ouders]


def _familie(slug):
    """De categorie en zijn bovencategorie: kleding-dames past ook bij kleding."""
    import categorieen
    ouder = {s: o for s, _, o in categorieen.CATEGORIEEN}.get(slug)
    return {slug, ouder} - {None}


def kandidaten(hoeveel):
    """Eerst wie op het punt staat post te krijgen, daarna wie in een ranglijst staat."""
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT b.webshop_url, b.categorie FROM benadering b
                     WHERE b.categorie IS NOT NULL AND NOT b.afgemeld
                       AND coalesce(b.soort, 'winkel') = 'winkel'
                       AND (b.categorie_gecheckt_op IS NULL
                            OR (b.categorie_klopt IS NULL
                                AND b.categorie_gecheckt_op < now() - interval '{OPNIEUW_NA_DAGEN} days'))
                       AND (
                           (b.email IS NOT NULL AND b.email <> '' AND b.gemaild_op IS NULL
                            AND b.stand IN ('adres', 'meten', 'gemeten'))
                           OR EXISTS (SELECT 1 FROM categorie_uitkomsten u WHERE u.webshop_url = b.webshop_url))
                  ORDER BY (b.email IS NOT NULL AND b.gemaild_op IS NULL) DESC, b.toegevoegd_op
                     LIMIT %s""", (int(hoeveel),))
                return [{"webshop_url": r[0], "categorie": r[1]} for r in cur.fetchall()]
    except Exception as e:
        print(f"Categoriecheck, kandidaten mislukt: {e}")
        return []
    finally:
        conn.close()


def _leg_vast(url, klopt, soort=None, categorie=None):
    conn = db._get_connection()
    if conn is None:
        return
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""UPDATE benadering SET categorie_gecheckt_op = now(), categorie_klopt = %s,
                                      soort = coalesce(%s, soort), categorie = coalesce(%s, categorie),
                                      bijgewerkt_op = now()
                                WHERE webshop_url = %s""", (klopt, soort, categorie, url))
    finally:
        conn.close()


def ronde(hoeveel=None, ophalen=None, vraag_model=None):
    """Een ronde. Geeft een verslag: {"bekeken", "klopt", "verplaatst", "geen_webshop", "twijfel"}."""
    hoeveel = CHECK_PER_RONDE if hoeveel is None else hoeveel
    verslag = {"bekeken": 0, "klopt": 0, "verplaatst": [], "geen_webshop": [], "twijfel": 0}
    lijst = kandidaten(hoeveel)
    if not lijst:
        return verslag
    geldig = {slug for slug, _ in _categorieen_lijst()}
    te_beoordelen = []
    for w in lijst:
        site = lees_site(w["webshop_url"], ophalen)
        if site is None:
            # Opent niet: geen post (de link in de mail moet werken), later opnieuw.
            _leg_vast(w["webshop_url"], None)
            verslag["twijfel"] += 1
            continue
        te_beoordelen.append(dict(w, site=site))
    for begin in range(0, len(te_beoordelen), CHECK_PER_AANROEP):
        groep = te_beoordelen[begin:begin + CHECK_PER_AANROEP]
        try:
            ruw = (vraag_model or _vraag_model)(_prompt(groep, _categorieen_lijst()))
            m = re.search(r"\{.*\}", ruw or "", re.S)
            uitkomst = {u.get("url"): u for u in json.loads(m.group(0)).get("uitkomst", [])} if m else {}
        except Exception as e:
            print(f"Categoriecheck, beoordelen mislukt: {e}")
            break   # geen oordeel is geen oordeel: niets vastleggen, volgende ronde opnieuw
        for w in groep:
            u = uitkomst.get(w["webshop_url"]) or {}
            soort = (u.get("soort") or "onbekend").lower()
            nieuw = u.get("categorie") if u.get("categorie") in geldig else None
            verslag["bekeken"] += 1
            if soort == "winkel" and nieuw and nieuw not in _familie(w["categorie"]) \
                    and w["categorie"] not in _familie(nieuw):
                _leg_vast(w["webshop_url"], True, categorie=nieuw)
                verslag["verplaatst"].append(f"{w['webshop_url']}: {w['categorie']} -> {nieuw}")
            elif soort == "winkel":
                _leg_vast(w["webshop_url"], True)
                verslag["klopt"] += 1
            elif soort in ("geen_webshop", "merk", "platform"):
                _leg_vast(w["webshop_url"], False, soort={"geen_webshop": SOORT_GEEN_WEBSHOP}.get(soort, soort))
                verslag["geen_webshop"].append(f"{w['webshop_url']} ({soort})")
            else:
                _leg_vast(w["webshop_url"], None)
                verslag["twijfel"] += 1
    return verslag


def zet_uit_index(webshop_url):
    """Met de hand: deze site is geen webshop (bijvoorbeeld na een mail als die
    van bel-air.be). Uit de post, uit elke ranglijst, en nooit meer gemaild."""
    _leg_vast(webshop_url, False, soort=SOORT_GEEN_WEBSHOP)
    db.meld_benadering_af(webshop_url)
