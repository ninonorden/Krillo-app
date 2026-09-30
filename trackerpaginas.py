"""Trackerpagina's: een pagina per assistent en een voor Shopify (stap 183 en 156, 30 september).

WAAROM DIT BESTAAT. Mensen zoeken letterlijk op "ChatGPT visibility tracker"
of "Shopify AI visibility". Peec heeft daar eigen pagina's voor en wordt
daarop gevonden. Wij hebben iets wat een losse tool niet heeft: echte cijfers
uit de index. Dus elke pagina heeft:
- de gratis check bovenaan (dezelfde als op de homepage: plek plus 13 punten);
- cijfers die NIEMAND anders heeft, uitgerekend uit de laatste meting per
  categorie, nooit verzonnen. Zijn er te weinig metingen, dan staat er geen
  cijfer in plaats van een half cijfer;
- uitleg en vragen, zodat Google en AI-assistenten de pagina kunnen citeren.

De Shopify-pagina is deel 3 van stap 156: kleine Shopify-winkels die zelf
zoeken, vinden hier de check. Met de vergelijking Shopify tegen de rest van de
index, omdat dat de vraag is die een Shopify-eigenaar heeft.

Taal: Engels (klantteksten), zoals de rest van de site.

EERLIJK: de Shopify-app ligt ter beoordeling bij Shopify. Deze pagina belooft
dus niets wat de app doet; er staat dat hij in beoordeling is. Pas de tekst aan
zodra de app in de App Store staat (stap 160).
"""
import json

import db
import dashboardpaginas as dp
import payments


def _prijs(pakket):
    """De prijs uit payments, zodat deze pagina nooit een oud bedrag noemt."""
    return payments.PAKKETTEN[pakket]["prijs"]["value"].split(".")[0]

# Onder dit aantal antwoorden of winkels zeggen we niets: een percentage over
# vijf antwoorden is toeval, geen cijfer.
MINIMUM_ANTWOORDEN = 30
MINIMUM_WINKELS = 20

PAGINAS = {
    "chatgpt-visibility-tracker": {
        "assistent": "ChatGPT",
        "titel": "ChatGPT visibility tracker for webshops",
        "h1": "Does ChatGPT name your webshop?",
        "kort": "Track whether ChatGPT names and recommends your store when shoppers ask where to buy. "
                "Free rank check, then monthly tracking with Watch.",
        "intro": "When a shopper asks ChatGPT where to buy, it gives a handful of store names. Krillo asks "
                 "ChatGPT the buying questions of your category every month, counts which stores it names "
                 "and recommends, and ranks every store the same way.",
    },
    "gemini-visibility-tracker": {
        "assistent": "Gemini",
        "titel": "Gemini visibility tracker for webshops",
        "h1": "Does Gemini name your webshop?",
        "kort": "Track whether Google's Gemini names and recommends your store for the buying questions in "
                "your category. Free rank check, then monthly tracking with Watch.",
        "intro": "Gemini answers shopping questions with its own shortlist of stores, and it does not always "
                 "agree with ChatGPT. Krillo asks Gemini the same buying questions as ChatGPT, every month, "
                 "and shows where the two differ for your store.",
    },
    "shopify-ai-visibility": {
        "platform": "shopify",
        "titel": "AI visibility for Shopify stores",
        "h1": "Is your Shopify store named by ChatGPT and Gemini?",
        "kort": "Free check for Shopify stores: your rank in the Krillo Index and 13 checks on what AI can "
                "read on your site. Then Watch every month, or Fix: we make the changes for you.",
        "intro": "Many Shopify stores use the product texts their supplier wrote. Hundreds of other stores use "
                 "the same texts, so AI has no reason to name yours. Krillo measures which stores ChatGPT and "
                 "Gemini name in your category, and shows what holds your store back.",
    },
}

VRAGEN = {
    "chatgpt-visibility-tracker": [
        ("How do I know if ChatGPT recommends my store?",
         "Type your store address in the check on this page. If your category is in the Krillo Index you see "
         "your rank right away, based on the buying questions we ask ChatGPT and Gemini every month."),
        ("Why does ChatGPT name some stores and not others?",
         "It names stores it can read clearly and that other sites mention: specific product pages, clear "
         "facts (price, delivery, returns), reviews and mentions on comparison sites. Our 13 checks show "
         "which of those your store is missing."),
        ("How often do you measure?",
         "Every month, for every store in the category, with the same questions. That is what makes the "
         "ranking fair: nobody can pay for a better place."),
    ],
    "gemini-visibility-tracker": [
        ("Is Gemini different from ChatGPT?",
         "Yes. The two often name different stores for the same question. That is why Krillo measures both "
         "and shows them side by side for every question."),
        ("Does Google search ranking decide what Gemini says?",
         "It helps, but it is not the same. A store on page one of Google can be missing from Gemini's answer, "
         "and the other way round."),
        ("How do I check my store?",
         "Type your store address in the check on this page: your rank and 13 checks, free, no account."),
    ],
    "shopify-ai-visibility": [
        ("Does Krillo work with Shopify?",
         "Yes. The free check works for any Shopify store. With Fix we make the changes in your store: better "
         "product texts, image descriptions and a questions page. Our Shopify app, which does this from inside "
         "your admin, is in review at Shopify now."),
        ("Why do supplier product texts hurt?",
         "AI looks for a reason to name one store over another. If your product text is word for word the "
         "same as on a hundred other stores, there is no reason to pick yours."),
        ("What does it cost?",
         f"The check on this page is free. Watch is {_prijs('watch')} euro a month with 14 days free; Fix, "
         f"where we make the changes, is {_prijs('fix')} euro a month. Cancel any time."),
    ],
}


@db._minuten
def assistent_cijfers():
    """Per assistent, over de nieuwste afgeronde meting van elke categorie:
    hoeveel antwoorden, in hoeveel procent ervan minstens een winkel genoemd
    werd, en hoeveel winkels er gemiddeld in een antwoord staan."""
    conn = db._get_connection()
    if conn is None:
        return {}
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    WITH nieuwste AS (
                        SELECT DISTINCT ON (categorie, coalesce(land, '')) id
                          FROM categorie_rondes WHERE afgerond_op IS NOT NULL
                      ORDER BY categorie, coalesce(land, ''), id DESC)
                    SELECT a.model, a.winkel_kon_genoemd, a.genoemde_winkels
                      FROM categorie_antwoorden a JOIN nieuwste n ON n.id = a.ronde""")
                rijen = cur.fetchall()
    except Exception as e:
        print(f"Assistentcijfers mislukt: {e}")
        return {}
    finally:
        conn.close()
    per = {}
    for model, kon, genoemd in rijen:
        naam = dp.assistent_naam(model)
        p = per.setdefault(naam, {"antwoorden": 0, "met_winkel": 0, "winkels": 0})
        if isinstance(genoemd, str):
            try:
                genoemd = json.loads(genoemd)
            except ValueError:
                genoemd = {}
        winkels = [w for w in (genoemd or {}).get("winkels", []) if (w.get("soort") or "winkel") == "winkel"]
        p["antwoorden"] += 1
        p["winkels"] += len(winkels)
        if kon and winkels:
            p["met_winkel"] += 1
    uit = {}
    for naam, p in per.items():
        if p["antwoorden"] < MINIMUM_ANTWOORDEN:
            continue
        uit[naam] = {"antwoorden": p["antwoorden"],
                     "procent_met_winkel": round(100 * p["met_winkel"] / p["antwoorden"]),
                     "gemiddeld": round(p["winkels"] / p["antwoorden"], 1)}
    return uit


@db._minuten
def platform_cijfers(platform):
    """Hoeveel gemeten winkels op dit platform draaien, en hoeveel procent van
    hen nooit genoemd werd, naast hetzelfde cijfer voor de rest van de index."""
    conn = db._get_connection()
    if conn is None:
        return {}
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    WITH nieuwste AS (
                        SELECT DISTINCT ON (categorie, coalesce(land, '')) id
                          FROM categorie_rondes WHERE afgerond_op IS NOT NULL
                      ORDER BY categorie, coalesce(land, ''), id DESC),
                    laatst AS (
                        SELECT DISTINCT ON (u.webshop_url) u.webshop_url, u.genoemd
                          FROM categorie_uitkomsten u JOIN nieuwste n ON n.id = u.ronde
                      ORDER BY u.webshop_url, u.ronde DESC)
                    SELECT (lower(coalesce(w.platform, '')) = %s) AS op_platform,
                           count(*) AS winkels, count(*) FILTER (WHERE coalesce(l.genoemd, 0) = 0) AS nooit
                      FROM laatst l LEFT JOIN winkelprofielen w ON w.webshop_url = l.webshop_url
                  GROUP BY 1""", (platform.lower(),))
                rijen = {bool(r[0]): (r[1], r[2]) for r in cur.fetchall()}
    except Exception as e:
        print(f"Platformcijfers mislukt: {e}")
        return {}
    finally:
        conn.close()
    op, rest = rijen.get(True, (0, 0)), rijen.get(False, (0, 0))
    if op[0] < MINIMUM_WINKELS or rest[0] < MINIMUM_WINKELS:
        return {}
    return {"winkels": op[0], "procent_nooit": round(100 * op[1] / op[0]),
            "rest_procent_nooit": round(100 * rest[1] / rest[0]), "rest_winkels": rest[0]}


def cijferzinnen(slug):
    """De zinnen met echte cijfers voor deze pagina. Leeg als er te weinig is."""
    pagina = PAGINAS[slug]
    zinnen = []
    if pagina.get("assistent"):
        alle = assistent_cijfers()
        eigen = alle.get(pagina["assistent"])
        if eigen:
            zinnen.append(f"In our latest measurement, {pagina['assistent']} named at least one store in "
                          f"{eigen['procent_met_winkel']}% of {eigen['antwoorden']} buying questions, and "
                          f"{eigen['gemiddeld']:g} stores per answer on average.")
            anderen = [(n, c) for n, c in alle.items() if n != pagina["assistent"]]
            for naam, c in anderen[:1]:
                zinnen.append(f"{naam}, asked the same questions: {c['gemiddeld']:g} stores per answer. "
                              f"Being named by one does not mean you are named by the other.")
    if pagina.get("platform"):
        c = platform_cijfers(pagina["platform"])
        if c:
            zinnen.append(f"{c['procent_nooit']}% of the {c['winkels']} Shopify stores we measured were not "
                          f"named by ChatGPT or Gemini in a single buying question. For the other "
                          f"{c['rest_winkels']} stores in the index that is {c['rest_procent_nooit']}%.")
    return zinnen
