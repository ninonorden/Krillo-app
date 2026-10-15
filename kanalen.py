"""Per kanaal: wat een klant kost en wat hij oplevert (stap 143, 15 oktober 2026).

WAAROM. Het ochtendbericht gaf al de AI-kosten van de week tegenover de omzet
per maand, maar niet WAAR die vandaan kwamen. Met de eerste klanten wil je
weten: levert de koude mail klanten op voor wat hij kost, en de Shopify-app,
en de index? Dan weet je waar het geld en de tijd heen moeten.

DRIE KANALEN, op een eenvoudige en eerlijke manier ingedeeld:
- "shopify": de klant heeft de app (staat in shopify_winkels);
- "koude mail": de winkel kreeg van ons een koude mail voordat hij klant werd;
- "site": de rest (index, gidsen, gratis check, zoeken).
De kosten per kanaal zijn de AI-kosten van het werk dat bij dat kanaal hoort
(KOSTEN_PER_KANAAL). Gedeeld werk (de index meten) zit bij "site", want de
index is er voor iedereen. Vaste kosten (Render, Neon, Brevo) staan er niet
in: die betaal je toch.
"""
import db

KOSTEN_PER_KANAAL = {
    "koude mail": ("winkelvinder-ai", "winkels-indelen", "winkels-opschonen", "categoriecheck",
                   "koopvraag-stellen", "volledig", "antwoordagent"),
    "site": ("categoriemeting", "categorievragen-bedenken", "categorie-antwoord-lezen", "vraagkeuze",
             "voorproef", "lijstjesagent", "artikel"),
}
KANALEN = ("koude mail", "shopify", "site")


def _sql(opdracht, waarden=None):
    from psycopg2.extras import RealDictCursor
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(opdracht, waarden)
                return [dict(r) for r in cur.fetchall()] if cur.description else []
    except Exception as e:
        print(f"Kanalen, ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def kanaal_van(klant):
    """klant: {"shopify": bool, "koude_mail": bool}."""
    if klant.get("shopify"):
        return "shopify"
    if klant.get("koude_mail"):
        return "koude mail"
    return "site"


def _maandbedrag(pakket, periode):
    import payments
    try:
        if (periode or "maand") == "jaar":
            return float(payments.prijs_van(pakket, "jaar")["value"]) / 12
        return float(payments.prijs_van(pakket, "maand")["value"])
    except Exception:
        return 0.0


def overzicht(dagen=30, klanten=None, kosten=None):
    """{kanaal: {"klanten", "omzet_maand", "ai_kosten"}} over de laatste dagen."""
    if klanten is None:
        klanten = _sql("""
            SELECT k.pakket, k.periode,
                   EXISTS (SELECT 1 FROM shopify_winkels s WHERE s.webshop_url = k.webshop_url) AS shopify,
                   EXISTS (SELECT 1 FROM benadering b WHERE b.webshop_url = k.webshop_url
                            AND b.gemaild_op IS NOT NULL AND b.gemaild_op < k.aangemaakt_op) AS koude_mail
              FROM klanten k
             WHERE NOT k.is_test AND k.opgezegd_op IS NULL
               AND (k.gratis_tot IS NULL OR k.gratis_tot < current_date)""")
    if kosten is None:
        kosten = _sql(f"""SELECT soort, coalesce(sum(kosten), 0) AS kosten FROM kostengebeurtenissen
                          WHERE moment > now() - interval '{int(dagen)} days' GROUP BY soort""")
    uit = {k: {"klanten": 0, "omzet_maand": 0.0, "ai_kosten": 0.0} for k in KANALEN}
    for k in klanten:
        rij = uit[kanaal_van(k)]
        rij["klanten"] += 1
        rij["omzet_maand"] += _maandbedrag(k.get("pakket"), k.get("periode"))
    for r in kosten:
        for kanaal, soorten in KOSTEN_PER_KANAAL.items():
            if r.get("soort") in soorten:
                uit[kanaal]["ai_kosten"] += float(r.get("kosten") or 0)
    for rij in uit.values():
        rij["omzet_maand"] = round(rij["omzet_maand"], 2)
        rij["ai_kosten"] = round(rij["ai_kosten"], 2)
    return uit


def ochtendregel(o=None):
    """Een regel voor het ochtendbericht."""
    o = o or overzicht()
    delen = []
    for k in KANALEN:
        r = o[k]
        stuk = f"{k}: {r['klanten']} klant{'en' if r['klanten'] != 1 else ''}, {r['omzet_maand']:.0f} euro per maand"
        if k in KOSTEN_PER_KANAAL:
            stuk += f", {r['ai_kosten']:.2f} euro AI in 30 dagen"
        delen.append(stuk)
    return "; ".join(delen)


# 15 oktober (Nino: "als er echt boven de 20k verdiend wordt moet het
# veranderd worden toch?"). Ja. Krillo valt onder de kleineondernemersregeling
# (KOR): geen btw zolang de omzet in een kalenderjaar onder 20.000 euro blijft.
# Gaat hij erover, dan geldt de KOR vanaf die betaling niet meer en moet er btw
# op de factuur, en moeten de prijzen, de site, de voorwaarden en de facturen
# mee (stap 412). Daarom telt het ochtendbericht de omzet van dit jaar en
# waarschuwt het ruim voor de grens. Geen fiscaal advies: bij de waarschuwing
# met een boekhouder overleggen.
KOR_GRENS = 20000
KOR_WAARSCHUW = 15000


def omzet_dit_jaar(rijen=None):
    """Som van de Mollie-facturen dit kalenderjaar (de 1 cent-checks tellen niet)."""
    if rijen is None:
        rijen = _sql("""SELECT coalesce(sum(bedrag), 0) AS som FROM facturen
                        WHERE aangemaakt_op >= date_trunc('year', now()) AND bedrag >= 1""")
    return float((rijen[0] if rijen else {}).get("som") or 0)


def kor_regel(omzet=None, shopify_maand=None):
    """Een regel voor het ochtendbericht, of None onder de waarschuwgrens."""
    omzet = omzet_dit_jaar() if omzet is None else omzet
    if shopify_maand is None:
        try:
            shopify_maand = overzicht()["shopify"]["omzet_maand"]
        except Exception:
            shopify_maand = 0.0
    if omzet + shopify_maand * 3 < KOR_WAARSCHUW:
        return None
    return (f"Omzet dit kalenderjaar via Mollie: {omzet:,.0f} euro (Shopify-uitbetalingen komen erbij, nu ongeveer "
            f"{shopify_maand:,.0f} euro per maand). De grens van de kleineondernemersregeling is {KOR_GRENS:,} euro. "
            "Plan nu met je boekhouder het overstappen op btw, en zeg het tegen Claude: dan passen we prijzen, "
            "site, voorwaarden en facturen aan").replace(",", ".")
