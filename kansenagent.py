"""De kansenagent: winkeliers die zelf om hulp vragen, met een antwoord klaar (15 oktober 2026).

WAAROM. Nino: "LinkedIn werkt niet, ik weet niet wie ik moet bereiken en wat ik
moet zeggen." Koude mail (1100 mails, 0 klanten) en LinkedIn-berichten
benaderen mensen die niet om ons vroegen. De tools in deze markt (Peec, en de
Shopify-apps die het redden) kregen hun eerste klanten op een andere manier:
door te helpen op de plekken waar winkeliers ZELF de vraag stellen. Op Reddit
(r/shopify, r/ecommerce, r/SEO), het Shopify-forum en Indie Hackers staan elke
week draadjes als "Why doesn't ChatGPT recommend my store?" of "traffic from AI
search?". Wie daar een goed antwoord geeft, wordt gelezen door iedereen die
later met dezelfde vraag zoekt, en AI-assistenten halen die draadjes zelf aan.

Wat de agent doet, een keer per werkdag:
1. zoekt met een paar vaste zoekvragen naar draadjes van de laatste tijd op die
   plekken (bronnen.zoek, ongeveer een halve cent per zoekvraag);
2. slaat over wat hij al eerder zag;
3. schrijft per nieuw draadje een kort, behulpzaam antwoord in de taal van het
   draadje: echt advies dat ook zonder Krillo werkt, geen link, en hooguit een
   eerlijke zin aan het eind dat Nino dit meet (dat eisen die plekken ook);
4. zet ze op /admin/groei. Nino leest, past aan waar nodig en plaatst zelf
   (automatisch plaatsen is daar verboden en wordt herkend als spam).

Kosten: hoogstens ZOEK_PER_DAG zoekvragen en ANTWOORD_PER_DAG modelvragen per
dag, samen een paar cent, binnen de dagrem.
"""
import json
import os
import re
from datetime import datetime, timezone

import db

ZOEK_PER_DAG = int(os.environ.get("KANSEN_ZOEK_PER_DAG", "6"))
ANTWOORD_PER_DAG = int(os.environ.get("KANSEN_ANTWOORD_PER_DAG", "8"))
MODEL = os.environ.get("KANSEN_MODEL", "claude-sonnet-4-6")
SLEUTEL_GEZIEN = "kansen_gezien"
SLEUTEL_LIJST = "kansen_lijst"
SLEUTEL_BEURT = "kansen_beurt"
# 15 oktober (Nino: "de reddit dingen zijn oud", een draadje van vier jaar,
# gearchiveerd, reageren kan niet eens). Nu: alleen zoeken in de laatste maand,
# een resultaat met een bekende datum ouder dan MAX_DAGEN overslaan, en een
# draadje zonder bekende datum alleen als de zoekmachine zelf op versheid filterde.
# Reddit sluit draadjes na zes maanden; wat ouder is, is onbruikbaar.
MAX_DAGEN = 45

# Plekken waar winkeliers zelf vragen stellen en waar een antwoord mag.
PLEKKEN = {"reddit.com": "Reddit", "community.shopify.com": "Shopify Community",
           "indiehackers.com": "Indie Hackers", "tweakers.net": "Tweakers",
           "community.wix.com": "Wix Community", "wordpress.org": "WordPress forum"}

# (zoekvraag, land, taal). Wisselt per dag, zodat elke zoekvraag regelmatig langskomt.
ZOEKVRAGEN = [
    ("site:reddit.com shopify store ChatGPT recommend", "us", "en"),
    ("site:reddit.com ecommerce traffic from ChatGPT AI search", "us", "en"),
    ("site:community.shopify.com ChatGPT store visibility", "us", "en"),
    ("site:reddit.com GEO generative engine optimization ecommerce store", "us", "en"),
    ("site:reddit.com \"AI Overviews\" ecommerce sales drop", "us", "en"),
    ("site:reddit.com how to get products shown in ChatGPT shopping", "us", "en"),
    ("site:community.shopify.com AI search traffic products", "us", "en"),
    ("site:reddit.com shopify SEO for AI assistants Perplexity Gemini", "us", "en"),
    ("site:indiehackers.com AI search visibility ecommerce", "us", "en"),
    ("webshop vindbaar in ChatGPT forum", "nl", "nl"),
    ("site:tweakers.net webshop ChatGPT", "nl", "nl"),
    ("site:reddit.com webshop ChatGPT Nederland", "nl", "nl"),
]


def plek_van(url):
    host = re.sub(r"^[a-z]+://", "", (url or "").lower()).split("/")[0]
    host = host[4:] if host.startswith("www.") else host
    for domein, naam in PLEKKEN.items():
        if host == domein or host.endswith("." + domein):
            return naam
    return None


def lijkt_draadje(url):
    """Een losse vraag of discussie, geen overzichtspagina of profiel."""
    u = (url or "").lower()
    return ("/comments/" in u or "/t/" in u or "/post/" in u or "/topic/" in u
            or "/forum/" in u or "/list/message/" in u or "gathering.tweakers.net" in u)


def _json(sleutel, standaard):
    try:
        return json.loads(db.get_instelling(sleutel) or "null") or standaard
    except (TypeError, ValueError):
        return standaard


def lijst():
    """De kansen die nog open staan, nieuwste eerst. Kansen van voor de
    datumcontrole (zonder "vers") tonen we niet meer: daar zaten oude,
    gesloten draadjes tussen."""
    return [k for k in _json(SLEUTEL_LIJST, []) if k.get("stand") == "open" and k.get("vers")]


def te_oud(datum, nu, max_dagen=None):
    """True als de datum (JJJJ-MM-DD) bekend is en ouder dan max_dagen."""
    if not datum:
        return False
    try:
        d = datetime.strptime(str(datum)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (nu - d).days > (MAX_DAGEN if max_dagen is None else max_dagen)


def zet_stand(url, stand):
    alles = _json(SLEUTEL_LIJST, [])
    for k in alles:
        if k.get("url") == url:
            k["stand"] = stand
    db.zet_instelling(SLEUTEL_LIJST, json.dumps(alles[-200:]))


def prompt(kans):
    taal = "Dutch" if kans.get("taal") == "nl" else "English"
    return (
        "A store owner asked this in an online forum. Write a reply they would find genuinely useful.\n\n"
        f"Forum: {kans['plek']}\nTitle: {kans['titel']}\nSnippet: {kans.get('omschrijving') or ''}\n\n"
        f"Rules:\n- Write in {taal}, 80 to 150 words, plain and friendly, like an experienced store owner.\n"
        "- Give concrete advice that works without any tool: check that product pages are readable "
        "without JavaScript and not blocked for AI crawlers, add clear product facts (materials, sizes, "
        "who it is for) and FAQ answers, get mentioned on the comparison and review sites that AI cites "
        "in your category, and test the real buying questions in ChatGPT and Gemini yourself.\n"
        "- Pick only what fits the question. No hype, no promises, no links, no emojis, never a long dash.\n"
        "- End with at most one honest sentence: the writer runs Krillo, which measures which stores "
        "ChatGPT and Gemini recommend (Netherlands and Belgium for now), and is happy to look if useful.\n"
        "Return only the reply.")


def _vraag_model(tekst):
    import time
    import kosten
    from lui_anthropic import anthropic
    rem = kosten.mag_doorgaan()
    if not rem["mag"]:
        raise RuntimeError(rem["reden"])
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    gestart = time.monotonic()
    antwoord = client.messages.create(model=MODEL, max_tokens=600,
                                      messages=[{"role": "user", "content": tekst}])
    try:
        kosten.registreer_aanroep("anthropic", MODEL, antwoord.usage.input_tokens,
                                  antwoord.usage.output_tokens, soort="kansenagent",
                                  duur_ms=int((time.monotonic() - gestart) * 1000))
    except Exception:
        pass
    return antwoord.content[0].text


def ronde(zoek=None, vraag_model=None, nu=None):
    """Een ronde. Geeft {"gezocht", "nieuw", "geschreven"}."""
    if zoek is None:
        import bronnen
        if not bronnen.beschikbaar():
            return {"gezocht": 0, "nieuw": 0, "geschreven": 0, "reden": "geen zoekmachine"}
        zoek = bronnen.zoek
    vraag_model = vraag_model or _vraag_model
    nu = nu or datetime.now(timezone.utc)
    gezien = set(_json(SLEUTEL_GEZIEN, []))
    beurt = int(db.get_instelling(SLEUTEL_BEURT) or 0)
    vragen = [ZOEKVRAGEN[(beurt + i) % len(ZOEKVRAGEN)] for i in range(min(ZOEK_PER_DAG, len(ZOEKVRAGEN)))]
    db.zet_instelling(SLEUTEL_BEURT, str((beurt + len(vragen)) % len(ZOEKVRAGEN)))
    nieuw = []
    for vraag, land, taal in vragen:
        for r in zoek(vraag, land=land, taal=taal, vers=True) or []:
            url = (r.get("url") or "").split("?")[0].split("#")[0]
            plek = plek_van(url)
            if not plek or not lijkt_draadje(url) or url in gezien or te_oud(r.get("datum"), nu):
                continue
            gezien.add(url)
            nieuw.append({"url": url, "plek": plek, "titel": r.get("titel") or "", "taal": taal,
                          "omschrijving": (r.get("omschrijving") or "")[:400], "datum": r.get("datum"),
                          "vers": True})
    geschreven = []
    for kans in nieuw[:ANTWOORD_PER_DAG]:
        try:
            tekst = (vraag_model(prompt(kans)) or "").strip().replace("—", ",").replace("–", "-")
        except Exception as e:
            print(f"Kansenagent, antwoord schrijven mislukt: {e}")
            break
        if tekst:
            geschreven.append(dict(kans, antwoord=tekst, gevonden_op=nu.isoformat()[:10], stand="open"))
    db.zet_instelling(SLEUTEL_GEZIEN, json.dumps(sorted(gezien)[-3000:]))
    if geschreven:
        db.zet_instelling(SLEUTEL_LIJST, json.dumps((_json(SLEUTEL_LIJST, []) + geschreven)[-200:]))
    return {"gezocht": len(vragen), "nieuw": len(nieuw), "geschreven": len(geschreven)}
