"""De contentmotor: elke maand nieuwe pagina's voor vragen die je verliest (stap 239, 16 oktober 2026).

WAAROM. Nino: "het verschil tussen Watch en Fix is niet groot, alleen dat wij
het doen". Klopt. Watch ziet welke koopvragen hij verliest en krijgt het plan
(contentplan.py: hoogstens drie stukken om te schrijven). Fix krijgt die
stukken GESCHREVEN: elke maand hoogstens PER_MAAND koopgidsen, elk op een vraag
waarbij AI een andere winkel noemde. Bij Shopify zetten wij ze als pagina live
(en ze kunnen terug met een klik, zoals elke wijziging); bij andere winkels
staan ze klaar in het dashboard om te plakken.

WAT DE TEKST WEL EN NIET DOET
- Hij beantwoordt de koopvraag eerlijk en helpt kiezen, met de producten van
  de winkel zelf als voorbeeld. Dat is wat AI leest en aanhaalt.
- Hij noemt GEEN concurrenten, GEEN prijzen, levertijden, garanties of
  keurmerken die we niet weten, en belooft niets over AI.
- In de taal van de winkel.
Kosten: een modelvraag per pagina, langs de kostenrem met voorrang (klantwerk).
"""
import html
import json
import re
from datetime import datetime, timezone

import db

PER_MAAND = 2
SLEUTEL = "contentmotor:"
HANDLE_BEGIN = "krillo-gids-"


def _lees(webshop_url):
    try:
        return json.loads(db.get_instelling(SLEUTEL + (webshop_url or "")[:180]) or "[]")
    except (TypeError, ValueError):
        return []


def _schrijf(webshop_url, lijst):
    db.zet_instelling(SLEUTEL + webshop_url[:180], json.dumps(lijst[-24:], ensure_ascii=False))


def pagina_s(webshop_url):
    """Alle geschreven pagina's, nieuwste eerst (voor het dashboard)."""
    return list(reversed(_lees(webshop_url)))


def deze_maand(webshop_url, nu=None, ook_terugwin=False):
    """De pagina's van deze maand. Terugwinpagina's tellen niet mee voor de
    maandgrens (PER_MAAND): die komen erbij, zie terugwin_vraag."""
    nu = nu or datetime.now(timezone.utc)
    return [p for p in _lees(webshop_url) if (p.get("op") or "")[:7] == nu.strftime("%Y-%m")
            and (ook_terugwin or p.get("soort") != "terugwin")]


# 16 oktober (Nino: "is Fix echt 100 euro meer waard?"): TERUGWINNEN BINNEN EEN
# WEEK. Watch krijgt een seintje als AI hem bij een vraag niet meer noemt. Fix
# krijgt dezelfde week een nieuwe pagina voor precies die vraag, bovenop de twee
# per maand. Hoogstens een per week, en niet opnieuw voor een vraag waar al een
# pagina voor is.
def terugwin_vraag(webshop_url, verloren, nu=None):
    """De verloren vraag waar deze week een pagina voor komt, of None."""
    nu = nu or datetime.now(timezone.utc)
    week = nu.strftime("%G-%V")
    lijst = _lees(webshop_url)
    if any(p.get("soort") == "terugwin" and p.get("week") == week for p in lijst):
        return None
    al = {p.get("vraag") for p in lijst}
    for v in verloren or []:
        if v.get("vraag") and v["vraag"] not in al:
            return v["vraag"]
    return None


def slug(tekst):
    s = re.sub(r"[^a-z0-9]+", "-", (tekst or "").lower()).strip("-")
    return s[:50].rstrip("-") or "gids"


def onderwerpen(webshop_url, gemiste, nu=None):
    """De verloren vragen die deze maand nog een pagina krijgen (hoogstens PER_MAAND,
    nooit twee keer dezelfde vraag)."""
    ruimte = PER_MAAND - len(deze_maand(webshop_url, nu))
    if ruimte <= 0:
        return []
    al = {p.get("vraag") for p in _lees(webshop_url)}
    uit = []
    for v in gemiste or []:
        vraag = (v.get("vraag") if isinstance(v, dict) else v) or ""
        if vraag and vraag not in al and vraag not in uit:
            uit.append(vraag)
        if len(uit) >= ruimte:
            break
    return uit


def prompt(vraag, winkelnaam, producten, taal):
    return f"""You write one page for the online store "{winkelnaam}". Shoppers ask AI assistants this buying
question, and AI named other stores, not this one:

"{vraag}"

Write a helpful buying guide that answers this question honestly, so a shopper can choose. Use the store's
own products below as examples where they fit.

Rules:
- Write in {taal}, plain words, no jargon, never a long dash.
- 350 to 550 words: a short intro, three or four sections with a heading, then three short questions with answers.
- Do NOT name other stores or brands that are not in the product list.
- Do NOT state prices, delivery times, shipping costs, return terms, guarantees, certificates or awards.
- Do NOT promise anything about AI, Google or rankings.

The store's products (name and short description):
{json.dumps(producten[:20], ensure_ascii=False, indent=1)}

Answer ONLY with JSON:
{{"titel": "...", "intro": "...", "secties": [{{"kop": "...", "tekst": "..."}}],
  "vragen": [{{"vraag": "...", "antwoord": "..."}}]}}"""


def maak_html(uit):
    """(html, leesbaar) uit het antwoord van het model. Alles ge-escaped."""
    e = html.escape
    delen = [f"<p>{e(uit.get('intro') or '')}</p>"] if uit.get("intro") else []
    leesbaar = [uit.get("intro") or ""]
    for s in uit.get("secties") or []:
        if s.get("kop") and s.get("tekst"):
            delen.append(f"<h2>{e(s['kop'])}</h2><p>{e(s['tekst'])}</p>")
            leesbaar.append(f"{s['kop']}\n{s['tekst']}")
    vragen = [v for v in uit.get("vragen") or [] if v.get("vraag") and v.get("antwoord")]
    if vragen:
        delen.append("".join(f"<h3>{e(v['vraag'])}</h3><p>{e(v['antwoord'])}</p>" for v in vragen))
        leesbaar.append("\n\n".join(f"{v['vraag']}\n{v['antwoord']}" for v in vragen))
    return "".join(delen), "\n\n".join(x for x in leesbaar if x).replace("—", ",")


def schrijf(webshop_url, vraag, winkelnaam, producten, taal, vraag_json, nu=None, soort="maand"):
    """Schrijft een pagina en bewaart hem. vraag_json(prompt) -> dict. Geeft de pagina of None."""
    nu = nu or datetime.now(timezone.utc)
    uit = vraag_json(prompt(vraag, winkelnaam, producten, taal))
    if not isinstance(uit, dict) or not uit.get("titel") or not uit.get("secties"):
        return None
    body, leesbaar = maak_html(uit)
    pagina = {"vraag": vraag, "titel": str(uit["titel"]).replace("—", ",")[:120], "html": body,
              "leesbaar": leesbaar, "op": nu.isoformat(), "handle": HANDLE_BEGIN + slug(vraag),
              "geplaatst": False, "soort": soort, "week": nu.strftime("%G-%V")}
    _schrijf(webshop_url, _lees(webshop_url) + [pagina])
    return pagina


def markeer_geplaatst(webshop_url, handle, waar=None):
    lijst = _lees(webshop_url)
    for p in lijst:
        if p.get("handle") == handle:
            p["geplaatst"] = True
            p["waar"] = waar
    _schrijf(webshop_url, lijst)


def voorstel(pagina, winkel_link):
    """Als voorstel voor shopify_werk.pas_toe (soort "gids")."""
    return {"id": "shopify:gids:" + pagina["handle"][len(HANDLE_BEGIN):], "soort": "gids",
            "titel": pagina["titel"], "handle": pagina["handle"], "wat": "Buying guide page",
            "waar": pagina["titel"], "link": winkel_link, "afbeelding": "", "oud": "",
            "nieuw": pagina["leesbaar"], "nieuw_html": pagina["html"]}


# 16 oktober (idee, akkoord Nino): VOOR EN NA VAN EEN KOOPGIDS in de maandmail.
# Een Fix-klant ziet met eigen ogen of het werk effect heeft: voor een gids die
# minstens een week staat, wat AI op die vraag antwoordde voor de gids er was,
# en wat bij de laatste wekelijkse meting. Alleen uit de bewaarde snelmetingen,
# alleen als de vraag voor en na gemeten is. Geen effect gezien: dat zeggen we.
EFFECT_NA_DAGEN = 7


def _snelrijen(webshop_url, vraag):
    from psycopg2.extras import RealDictCursor
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""SELECT ronde_op, assistent, genoemd, anderen FROM snelmetingen
                               WHERE webshop_url = %s AND vraag = %s ORDER BY ronde_op""", (webshop_url, vraag))
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"Contentmotor, effect ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def _namen(rij):
    a = rij.get("anderen") or []
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except ValueError:
            a = []
    return [str(x) for x in a][:3]


def effect(webshop_url, nu=None, rijen_van=None):
    """{"vraag", "titel", "op", "voor": {"genoemd", "anderen"}, "na": {...}} of None."""
    nu = nu or datetime.now(timezone.utc)
    rijen_van = rijen_van or (lambda v: _snelrijen(webshop_url, v))
    for p in pagina_s(webshop_url):
        try:
            op = datetime.fromisoformat(p["op"])
        except (KeyError, ValueError):
            continue
        if (nu - op).days < EFFECT_NA_DAGEN:
            continue
        rijen = rijen_van(p["vraag"])
        voor = [r for r in rijen if r["ronde_op"] < op]
        na = [r for r in rijen if r["ronde_op"] > op]
        if not voor or not na:
            continue
        laatste_voor = [r for r in voor if r["ronde_op"] == voor[-1]["ronde_op"]]
        laatste_na = [r for r in na if r["ronde_op"] == na[-1]["ronde_op"]]

        def samen(rs):
            namen = []
            for r in rs:
                for n in _namen(r):
                    if n not in namen:
                        namen.append(n)
            return {"genoemd": [r["assistent"] for r in rs if r.get("genoemd")], "anderen": namen[:3]}
        return {"vraag": p["vraag"], "titel": p.get("titel"), "op": op, "voor": samen(laatste_voor),
                "na": samen(laatste_na)}
    return None


def effect_zin(e, taal="en"):
    """Een alinea voor de maandmail, of None."""
    if not e:
        return None
    datum = e["op"].strftime("%-d %B")
    voor = (f"AI named {', '.join(e['voor']['anderen'])}" if e["voor"]["anderen"] else "AI named other stores") \
        if not e["voor"]["genoemd"] else f"{' and '.join(e['voor']['genoemd'])} already named you"
    if e["na"]["genoemd"]:
        na = f"At the last weekly check, {' and '.join(e['na']['genoemd'])} named you."
    else:
        na = ("At the last weekly check, AI did not name you yet"
              + (f" (it named {', '.join(e['na']['anderen'])})" if e["na"]["anderen"] else "")
              + ". A new page often takes a few weeks to be picked up.")
    if taal == "nl":
        voor_nl = (f"noemde AI {', '.join(e['voor']['anderen'])}" if e["voor"]["anderen"] else "noemde AI andere winkels") \
            if not e["voor"]["genoemd"] else f"noemde {' en '.join(e['voor']['genoemd'])} je al"
        na_nl = (f"Bij de laatste wekelijkse meting noemde {' en '.join(e['na']['genoemd'])} jou." if e["na"]["genoemd"]
                 else "Bij de laatste wekelijkse meting noemde AI je nog niet"
                 + (f" (wel {', '.join(e['na']['anderen'])})" if e["na"]["anderen"] else "")
                 + ". Een nieuwe pagina wordt vaak pas na een paar weken opgepikt.")
        return f"Onze koopgids voor “{e['vraag']}” staat er sinds {e['op'].strftime('%-d-%-m')}. Daarvoor {voor_nl}. {na_nl}"
    return f"Our buying guide for “{e['vraag']}” has been up since {datum}. Before it, {voor}. {na}"
