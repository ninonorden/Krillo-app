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


def deze_maand(webshop_url, nu=None):
    nu = nu or datetime.now(timezone.utc)
    return [p for p in _lees(webshop_url) if (p.get("op") or "")[:7] == nu.strftime("%Y-%m")]


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


def schrijf(webshop_url, vraag, winkelnaam, producten, taal, vraag_json, nu=None):
    """Schrijft een pagina en bewaart hem. vraag_json(prompt) -> dict. Geeft de pagina of None."""
    nu = nu or datetime.now(timezone.utc)
    uit = vraag_json(prompt(vraag, winkelnaam, producten, taal))
    if not isinstance(uit, dict) or not uit.get("titel") or not uit.get("secties"):
        return None
    body, leesbaar = maak_html(uit)
    pagina = {"vraag": vraag, "titel": str(uit["titel"]).replace("—", ",")[:120], "html": body,
              "leesbaar": leesbaar, "op": nu.isoformat(), "handle": HANDLE_BEGIN + slug(vraag),
              "geplaatst": False}
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
