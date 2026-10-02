"""De leeragent: agents die zichzelf voeden met onderzoek en zo beter worden (28 september).

WAAROM DIT BESTAAT. Nino, 28 september: "agents moeten zichzelf kunnen voeden
met informatie, zelf strategie bepalen en vinden door onderzoek in hun line of
work, alles om Krillo sterk te maken, alles geautomatiseerd."

HOE HET WERKT (elke maand per onderwerp, vanzelf in de nachtronde)
1. VOEDEN. Elk onderwerp krijgt zijn eigen cijfers mee (scorebord van de
   verkoopagent, de trechter van de laatste 30 dagen, wat de concurrentie-
   agent vond) en zijn eigen eerdere bevindingen, zodat hij voortbouwt in
   plaats van elke maand opnieuw begint.
2. ONDERZOEK. Claude zoekt op het web (de zoekfunctie van de Anthropic-API)
   naar wat nu werkt in zijn vak, met bronnen.
3. BESLISSEN, met een grens die nooit lost:
   - Wat meetbaar is, voert hij ZELF door, als uitdager naast de huidige
     versie. Nu: de uitleg in de mail van de verkoopagent. De uitdager wordt
     pas de standaard als hij aantoonbaar beter scoort (verkoopagent.
     beslis_uitdager). Een slechtere versie gaat dus nooit vast live.
   - Wat niet meetbaar is of geld kost (een nieuw land, een prijs, een nieuw
     kanaal) wordt een VOORSTEL in het ochtendbericht en op /admin/leren. Een
     agent die zelf prijzen verandert of geld uitgeeft zonder dat iemand het
     ziet, is een risico dat Krillo niet kan dragen.
4. Alles wat naar buiten gaat, gaat eerst langs de controleagent (stap 38).

Kosten: een aanroep met hoogstens 5 zoekopdrachten per onderwerp per maand,
drie onderwerpen. Geteld in de kosten zoals elke andere AI-aanroep.
"""
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import db

MODEL = os.environ.get("LEER_MODEL", os.environ.get("CONTROLE_MODEL", "claude-sonnet-4-6"))
ELKE_DAGEN = 30
# 1 oktober: Nino wil elke dag taken en voorstellen. Groei (kanalen, taken voor
# Nino) is het belangrijkst en komt elke drie dagen; product (wat de
# concurrenten hebben en wij niet) elke week. Nog steeds hoogstens een
# onderzoek per nacht, dus hoogstens een paar dubbeltjes per dag.
ELKE = {"groei": 3, "product": 7, "markt": 14, "verkoop": 30}
MAX_ZOEKEN = 5

ONDERWERPEN = {
    "verkoop": {
        "naam": "Verkoop: de opvolgmail",
        "rol": ("You improve one paragraph in a short follow-up email from Krillo to a webshop owner who just "
                "looked at their rank in the Krillo Index (which stores ChatGPT and Gemini recommend, per "
                "category). The paragraph explains that it is fixable and what Krillo does: Watch (EUR 49/month, "
                "fixes written out to do yourself) and Fix (EUR 149/month, we make the changes in the store)."),
        "zoek": ("Research what currently works in short, personal follow-up emails to small online store "
                 "owners (B2B, Europe): tone, length, what makes them click. Also recent facts about shoppers "
                 "using AI assistants to find where to buy."),
        "uitdager": True,
    },
    "markt": {
        "naam": "Markt en concurrentie",
        "rol": ("You watch the market for Krillo: an AI visibility service for online stores with a public "
                "monthly ranking per category and country, that also makes the fixes. Competitors: Otterly.AI, "
                "Peec AI, Profound, AthenaHQ, and AI visibility apps on Shopify."),
        "zoek": ("Research the last 30 days: new features, prices or funding of these competitors, and changes "
                 "in how ChatGPT, Gemini, Perplexity and Google AI Mode recommend products and stores."),
        "uitdager": False,
    },
    "groei": {
        "naam": "Groei: klanten vinden",
        "rol": ("You find customers for Krillo (online stores, Europe, now measuring the Netherlands and Belgium). "
                "Krillo has a free check, free tools, a partner program for agencies (20 percent while the client pays, up to 12 months) "
                "and a Shopify app in review."),
        "zoek": ("Research concrete, low-cost channels where small online store owners and webshop agencies in "
                 "Europe look for tools right now: communities, newsletters, directories, events, partner programs "
                 "of platforms. Prefer channels that fit a small team and are allowed under EU rules."),
        "uitdager": False,
        "extra": ('"taken": [{"taak": "one concrete task for the owner (in Dutch), at most 30 minutes, naming the exact '
                  'place (site, group or person) and what to post or send", "minuten": 15}]'),
    },
    "product": {
        "naam": "Product: wat de concurrenten hebben",
        "rol": ("You are the product lead of Krillo: an AI visibility service for online stores (EU). Krillo now has: "
                "a public monthly ranking per category and country (ChatGPT and Gemini), a customer dashboard with "
                "rank, lost buying questions and who AI names instead, a weekly 13-point site scan, fixes written "
                "out (Watch) or carried out in the store via Shopify and WordPress (Fix), sources AI cites, a PDF "
                "monthly report, free tools and a partner program for agencies."),
        "zoek": ("Research the current features of Peec AI, Profound, Otterly.AI, AthenaHQ, Semrush AI toolkit and "
                 "AI visibility apps in the Shopify App Store. Which features do they have that Krillo lacks and "
                 "that small online stores would pay for? Think of marketing, SEO and content, not only tracking."),
        "uitdager": False,
        "extra": ('"functies": [{"titel": "a feature Krillo could add (in Dutch, one sentence)", '
                  '"waarom": "which competitor has it and why a small store would pay for it (in Dutch)"}]'),
    },
}

OPDRACHT = """{rol}

{zoek}

What we measured ourselves (last 30 days, real numbers):
{cijfers}

What you found last time (build on it, do not repeat it):
{vorige}

Answer ONLY with one JSON object, no text around it:
{{"bevindingen": [{{"tekst": "one finding in one sentence", "bron": "https://..."}}],
  "voorstellen": ["one concrete next step for Krillo, in one sentence, in Dutch"],
  {uitdager_veld}{extra_veld}}}
Rules: at most 5 findings, each with a real source URL you actually read. At most 3 proposals, at most 3 tasks,
at most 3 features.
Plain words, no hype, no em dashes. Findings and the paragraph in English; proposals, tasks and features in
Dutch. Never promise results, rankings, guarantees or delivery times."""

UITDAGER_VELD = ('"uitdager": "a new version of the paragraph, 30 to 70 words, plain English, mentions Watch and '
                 'Fix, promises no result"')


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
    cur.execute("""CREATE TABLE IF NOT EXISTS agent_inzichten (
                       id SERIAL PRIMARY KEY,
                       onderwerp TEXT NOT NULL,
                       op TIMESTAMPTZ NOT NULL DEFAULT now(),
                       bevindingen JSONB,
                       voorstellen JSONB,
                       uitdager TEXT,
                       uitdager_stand TEXT,
                       fout TEXT)""")


def _cijfers(onderwerp):
    """Wat Krillo zelf mat: dit voedt het onderzoek."""
    regels = []
    try:
        import ochtendbericht
        for wat, sql in ochtendbericht.GISTEREN:
            n = ochtendbericht._tel(sql.replace("24 hours", "30 days"))
            if n:
                regels.append(f"- {wat}: {n}")
    except Exception:
        pass
    if onderwerp == "verkoop":
        try:
            import verkoopagent
            for r in verkoopagent.scorebord():
                regels.append(f"- mail version {r['versie']}: sent {r['verstuurd']}, clicked {r['doorgeklikt']}, "
                              f"customers {r['klant']}")
            winnaar = db.get_instelling(verkoopagent.SLEUTEL_WINNAAR) or "a"
            regels.append(f"- current best paragraph: \"{verkoopagent.versie_tekst(winnaar)}\"")
        except Exception:
            pass
    if onderwerp == "markt":
        try:
            na = json.loads(db.get_instelling("nachtagenten") or "{}")
            regels += [f"- {c}" for c in (na.get("concurrenten") or [])]
        except Exception:
            pass
    return "\n".join(regels) or "- nothing yet (no customers so far)"


def _vorige(onderwerp):
    rij = _sql("""SELECT bevindingen, voorstellen FROM agent_inzichten WHERE onderwerp = %s AND fout IS NULL
                  ORDER BY op DESC LIMIT 1""", (onderwerp,))
    if not rij:
        return "- nothing yet"
    b = [f"- {x.get('tekst')}" for x in (rij.get("bevindingen") or [])]
    v = [f"- proposal: {x}" for x in (rij.get("voorstellen") or [])]
    return "\n".join(b + v) or "- nothing yet"


def lees_json(tekst):
    """Het JSON-object uit het antwoord, ook als er toch tekst omheen staat."""
    m = re.search(r"\{.*\}", tekst or "", re.S)
    if not m:
        return None
    try:
        uit = json.loads(m.group(0))
    except Exception:
        return None
    return uit if isinstance(uit, dict) else None


def schoon(uit):
    """Alleen bevindingen met een echte bron, en alles kort."""
    bevindingen = [{"tekst": str(b.get("tekst"))[:400], "bron": str(b.get("bron"))[:300]}
                   for b in (uit.get("bevindingen") or [])[:5]
                   if isinstance(b, dict) and str(b.get("bron") or "").startswith("http") and b.get("tekst")]
    voorstellen = [str(v)[:300] for v in (uit.get("voorstellen") or [])[:3] if v]
    return bevindingen, voorstellen, (str(uit.get("uitdager") or "").strip() or None)


def keur_uitdager(tekst):
    """Mag deze tekst als uitdager live? Controleagent plus eigen regels."""
    import tekstkeuring
    if not tekst:
        return "leeg"
    woorden = len(tekst.split())
    if woorden < 20 or woorden > 90:
        return f"lengte {woorden} woorden"
    if "Fix" not in tekst:
        return "noemt Fix niet"
    k = tekstkeuring.keur(tekst)
    if not k["ok"]:
        return "controleagent: " + "; ".join(k["fouten"])
    if k["waarschuwingen"]:
        return "controleagent: " + "; ".join(k["waarschuwingen"])
    return None


def vraag_claude(opdracht, client=None):
    """Een aanroep met de zoekfunctie. Geeft (tekst, invoer_tokens, uitvoer_tokens)."""
    if client is None:
        import anthropic
        sleutel = os.environ.get("ANTHROPIC_API_KEY")
        if not sleutel:
            raise RuntimeError("ANTHROPIC_API_KEY ontbreekt in Render")
        client = anthropic.Anthropic(api_key=sleutel)
    antwoord = client.messages.create(
        model=MODEL, max_tokens=2000,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_ZOEKEN}],
        messages=[{"role": "user", "content": opdracht}])
    tekst = "".join(getattr(b, "text", "") or "" for b in antwoord.content if getattr(b, "type", "") == "text")
    gebruik = getattr(antwoord, "usage", None)
    return tekst, getattr(gebruik, "input_tokens", 0) or 0, getattr(gebruik, "output_tokens", 0) or 0


def onderzoek(onderwerp, client=None):
    """Een onderzoek voor een onderwerp: voeden, zoeken, beslissen. Geeft de rij."""
    o = ONDERWERPEN[onderwerp]
    opdracht = OPDRACHT.format(rol=o["rol"], zoek=o["zoek"], cijfers=_cijfers(onderwerp),
                               vorige=_vorige(onderwerp),
                               uitdager_veld=UITDAGER_VELD if o["uitdager"] else '"uitdager": null',
                               extra_veld=(",\n  " + o["extra"]) if o.get("extra") else "")
    begin = time.time()
    try:
        tekst, tin, tuit = vraag_claude(opdracht, client)
    except Exception as e:
        _sql("INSERT INTO agent_inzichten (onderwerp, fout) VALUES (%s, %s)", (onderwerp, str(e)[:500]))
        return {"onderwerp": onderwerp, "fout": str(e)}
    try:
        import kosten
        kosten.registreer_aanroep("anthropic", MODEL, tin, tuit, soort=f"leeragent_{onderwerp}",
                                  duur_ms=int((time.time() - begin) * 1000))
    except Exception as e:
        print(f"Kosten leeragent vastleggen mislukt: {e}")
    uit = lees_json(tekst)
    if not uit:
        _sql("INSERT INTO agent_inzichten (onderwerp, fout) VALUES (%s, %s)", (onderwerp, "geen JSON in het antwoord"))
        return {"onderwerp": onderwerp, "fout": "geen JSON"}
    bevindingen, voorstellen, uitdager = schoon(uit)
    stand = None
    if o["uitdager"] and uitdager:
        reden = keur_uitdager(uitdager)
        stand = "afgekeurd: " + reden if reden else zet_uitdager(uitdager)
    _sql("""INSERT INTO agent_inzichten (onderwerp, bevindingen, voorstellen, uitdager, uitdager_stand)
            VALUES (%s, %s, %s, %s, %s)""",
         (onderwerp, json.dumps(bevindingen), json.dumps(voorstellen), uitdager, stand))
    klaargezet = naar_voorstellen(onderwerp, voorstellen, uit)
    return {"onderwerp": onderwerp, "bevindingen": bevindingen, "voorstellen": voorstellen,
            "uitdager": uitdager, "uitdager_stand": stand, "klaargezet": klaargezet}


def _kaal(tekst, lengte=300):
    """Kort, en zonder lange streepjes (Nino's regel geldt ook voor agents)."""
    t = " ".join(str(tekst or "").split())
    t = t.replace(" \u2014 ", ", ").replace("\u2014", ", ").replace(" \u2013 ", ", ")
    return t[:lengte]


def naar_voorstellen(onderwerp, voorstellen_lijst, uit):
    """1 oktober: wat de leeragent vindt, wordt een voorstel met een akkoordlink
    in het ochtendbericht (voorstellen.py). Groei levert taken voor Nino, product
    levert functies om te bouwen, en de losse voorstellen van markt en verkoop
    zijn dingen om te bouwen of te veranderen. Geeft het aantal nieuwe."""
    import voorstellen as vs
    naam = ONDERWERPEN.get(onderwerp, {}).get("naam", onderwerp)
    n = 0
    try:
        for t in (uit.get("taken") or [])[:3]:
            if isinstance(t, dict) and t.get("taak"):
                try:
                    minuten = max(5, min(60, int(t.get("minuten") or 20)))
                except (TypeError, ValueError):
                    minuten = 20
                if vs.stel_voor("leeragent", "taak", _kaal(t["taak"]), waarom=f"Uit het onderzoek: {naam}",
                                minuten=minuten):
                    n += 1
        for f in (uit.get("functies") or [])[:3]:
            if isinstance(f, dict) and f.get("titel"):
                if vs.stel_voor("leeragent", "bouwen", _kaal(f["titel"]), waarom=_kaal(f.get("waarom"), 600)):
                    n += 1
        soort = "taak" if onderwerp == "groei" else "bouwen"
        for v in voorstellen_lijst or []:
            if vs.stel_voor("leeragent", soort, _kaal(v), waarom=f"Uit het onderzoek: {naam}"):
                n += 1
    except Exception as e:
        print(f"Leeragent, voorstellen klaarzetten mislukt: {e}")
    return n


def zet_uitdager(tekst):
    """Een goedgekeurde tekst wordt de uitdager van de verkoopagent, maar alleen
    als er al een winnaar is en er nog geen uitdager loopt (een lopende proef
    breek je niet af)."""
    import verkoopagent as va
    if not db.get_instelling(va.SLEUTEL_WINNAAR):
        return "bewaard: eerst moet versie a of b winnen"
    if va.uitdager():
        return "bewaard: er loopt al een uitdager"
    rij = _sql("SELECT count(*) AS n FROM agent_inzichten WHERE uitdager_stand = 'live als uitdager'") or {}
    nummer = int(rij.get("n") or 0) + 1
    db.zet_instelling(va.SLEUTEL_UITDAGER, json.dumps({"versie": f"u{nummer}", "tekst": tekst}))
    return "live als uitdager"


def aan_de_beurt(nu=None):
    """Het onderwerp dat het langst niet onderzocht is, als het weer aan de beurt
    is (ELKE: groei elke 3 dagen, product elke week, markt 14, verkoop 30).
    Een per nacht, zodat de kosten gespreid zijn."""
    nu = nu or datetime.now(timezone.utc)
    oudste, keuze = None, None
    for onderwerp in ONDERWERPEN:
        rij = _sql("SELECT max(op) AS op FROM agent_inzichten WHERE onderwerp = %s", (onderwerp,)) or {}
        laatst = rij.get("op")
        if laatst and laatst > nu - timedelta(days=ELKE.get(onderwerp, ELKE_DAGEN)):
            continue
        if keuze is None or (laatst or datetime.min.replace(tzinfo=timezone.utc)) < oudste:
            keuze, oudste = onderwerp, (laatst or datetime.min.replace(tzinfo=timezone.utc))
    return keuze


def draai(client=None):
    """Voor de nachtronde: hoogstens een onderzoek per nacht."""
    if os.environ.get("LEERAGENT", "aan").lower() in ("uit", "0", "nee"):
        return None
    # Goedkope dag of eigen deel op: een dag overslaan. Het onderwerp blijft
    # aan de beurt, dus morgen gaat hij gewoon verder.
    import kosten
    rem = kosten.mag_eigen_agent("leeragent")
    if not rem["mag"]:
        print(f"Leeragent overgeslagen: {rem['reden']}")
        return {"overgeslagen": True, "reden": rem["reden"]}
    onderwerp = aan_de_beurt()
    return onderzoek(onderwerp, client) if onderwerp else None


def laatste():
    """Per onderwerp het laatste onderzoek, voor het ochtendbericht en /admin/leren."""
    return _sql("""SELECT DISTINCT ON (onderwerp) * FROM agent_inzichten
                   ORDER BY onderwerp, op DESC""", alles=True) or []
