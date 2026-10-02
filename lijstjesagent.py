"""De lijstjesagent: artikelen "beste GEO-tools" vinden en de schrijver mailen.

WAAROM DIT BESTAAT (29 september). Nino: "maak Deel 3, de lijstjes met beste
GEO-tools, automatisch". Die lijstjes zijn precies de pagina's die ChatGPT en
Gemini lezen als iemand vraagt welke tool hij moet nemen. Staat Krillo er niet
in, dan bestaat Krillo niet voor die vraag. Nino mailde de eerste vijf met de
hand (Blazity, Stackmatix, Subscribe PR, Bliss Drive, Industry Lens); die staan
hieronder als "met de hand gedaan" zodat niemand twee keer post krijgt.

Hoe het werkt:
- Een keer per week zoekt Claude (met de zoekfunctie, net als de leeragent)
  naar nieuwe artikelen. Alleen artikelen die tools opsommen, geen reclame,
  geen pagina van een concurrent zelf.
- Elk uur binnen kantooruren: hoogstens een mail, en hoogstens LIJSTJES_PER_WEEK
  per week. Een per domein, nooit opnieuw. Het adres komt van de adresvinder
  (dezelfde regels: alleen algemene adressen, nooit gokken).
- De mail is kort, zegt wat Krillo anders doet (de openbare index per categorie,
  echte cijfers) en heeft een afmeldlink. Hij gaat langs de controleagent.

Wat er NIET gebeurt: geen opvolgmail, geen betaalde vermelding, geen belofte
van een tegenprestatie. Een schrijver die "stop" zegt of op de link klikt hoort
nooit meer iets.

Uit te zetten met LIJSTJESAGENT=uit in Render.
"""
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

import db

PER_WEEK = int(os.environ.get("LIJSTJES_PER_WEEK", "3"))
ZOEK_ELKE_DAGEN = 7
ZOEKSLEUTEL = "lijstjes_laatst_gezocht"

# Door Nino met de hand gemaild (takenlijst, 29 september).
MET_DE_HAND = ("blazity.com", "stackmatix.com", "subscribepr.com", "blissdrive.com", "industrylens.com")

# Onszelf en de concurrenten zelf mailen heeft geen zin: hun lijst eindigt met
# hun eigen product.
NIET = ("krilloai.com", "krillo.nl", "peec.ai", "otterly.ai", "profound.com", "tryprofound.com",
        "semrush.com", "ahrefs.com", "athenahq.ai", "scrunchai.com", "goodie.ai", "rankscale.ai",
        "writesonic.com", "hubspot.com", "g2.com", "capterra.com", "reddit.com", "youtube.com",
        "linkedin.com", "medium.com", "x.com", "twitter.com", "facebook.com")

OPDRACHT = """You help a small Dutch company, Krillo (krilloai.com), get listed in articles
that compare "GEO tools" / "AI visibility tools" / "AI search monitoring tools"
(tools that track whether ChatGPT, Gemini or Perplexity mention a brand).

Search the web for such list or comparison articles published in 2025 or 2026,
in English or Dutch. Good examples: "best GEO tools", "best AI visibility tools",
"Peec AI alternatives", "Otterly alternatives", "generative engine optimization tools".

Only include articles that:
- list several tools from different companies (not a page selling one tool);
- are on a blog, agency site or magazine that accepts suggestions;
- do NOT already mention Krillo.

Answer ONLY with JSON, no other text:
{{"artikelen": [{{"url": "...", "titel": "...", "waarom": "one short line"}}]}}
At most 10 articles. Skip these domains: {overslaan}."""


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
        CREATE TABLE IF NOT EXISTS lijstjes (
            domein TEXT PRIMARY KEY,
            url TEXT, titel TEXT, waarom TEXT,
            stand TEXT DEFAULT 'nieuw',
            adres TEXT, notitie TEXT,
            token TEXT UNIQUE,
            gevonden_op TIMESTAMPTZ DEFAULT now(),
            verstuurd_op TIMESTAMPTZ
        );
    """)
    for d in MET_DE_HAND:
        cur.execute("""INSERT INTO lijstjes (domein, stand, notitie, token)
                       VALUES (%s, 'met de hand', 'Door Nino met de hand gemaild op 29 september.', %s)
                       ON CONFLICT (domein) DO NOTHING""", (d, secrets.token_urlsafe(12)))


def domein_van(url):
    t = (url or "").strip().lower()
    t = re.sub(r"^https?://", "", t)
    t = t[4:] if t.startswith("www.") else t
    return t.split("/")[0].split("?")[0]


def bewaar_artikelen(artikelen):
    """Nieuwe artikelen erbij. Een domein dat er al staat blijft zoals het is."""
    nieuw = 0
    for a in artikelen or []:
        url = (a.get("url") or "").strip()
        d = domein_van(url)
        if not d or "." not in d or any(d == n or d.endswith("." + n) for n in NIET):
            continue
        n = _sql("""INSERT INTO lijstjes (domein, url, titel, waarom, token) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (domein) DO NOTHING""",
                 (d, url[:500], (a.get("titel") or "")[:300], (a.get("waarom") or "")[:300],
                  secrets.token_urlsafe(12)))
        nieuw += n or 0
    return nieuw


def moet_zoeken(nu=None):
    nu = nu or datetime.now(timezone.utc)
    laatst = db.get_instelling(ZOEKSLEUTEL)
    if not laatst:
        return True
    try:
        return nu - datetime.fromisoformat(laatst) >= timedelta(days=ZOEK_ELKE_DAGEN)
    except Exception:
        return True


def zoek(client=None):
    """Een keer per week: nieuwe artikelen zoeken. Voor de nachtronde."""
    if os.environ.get("LIJSTJESAGENT") == "uit" or not moet_zoeken():
        return {"overgeslagen": True}
    # Goedkope dag: overslaan zonder de zoekdatum te zetten, dus morgen opnieuw.
    import kosten
    rem = kosten.mag_eigen_agent("lijstjesagent")
    if not rem["mag"]:
        return {"overgeslagen": True, "reden": rem["reden"]}
    db.zet_instelling(ZOEKSLEUTEL, datetime.now(timezone.utc).isoformat())
    import leeragent
    gehad = [r["domein"] for r in (_sql("SELECT domein FROM lijstjes", alles=True) or [])]
    opdracht = OPDRACHT.format(overslaan=", ".join(sorted(set(gehad) | set(NIET)))[:3000])
    begin = time.time()
    try:
        tekst, tin, tuit = leeragent.vraag_claude(opdracht, client)
    except Exception as e:
        print(f"Lijstjesagent zoeken mislukt: {e}")
        return {"fout": str(e)[:300]}
    try:
        import kosten
        kosten.registreer_aanroep("anthropic", leeragent.MODEL, tin, tuit, soort="lijstjesagent",
                                  duur_ms=int((time.time() - begin) * 1000))
    except Exception as e:
        print(f"Kosten lijstjesagent vastleggen mislukt: {e}")
    uit = leeragent.lees_json(tekst) or {}
    return {"gevonden": len(uit.get("artikelen") or []), "nieuw": bewaar_artikelen(uit.get("artikelen"))}


def mail_tekst(rij, basis_url):
    """De mail aan de schrijver. Engels, kort, zonder beloftes."""
    titel = rij.get("titel") or "your article"
    alineas = [
        "Hi,",
        f"I read {titel} and have a suggestion for it. I am Nino, the founder of Krillo, a small Dutch "
        "tool that checks whether ChatGPT and Gemini recommend a webshop.",
        "What is different from the tools you list: Krillo publishes an open index per product category, "
        "so anyone can see which stores AI names today without an account. There is a free check, "
        "Watch costs EUR 49 a month with the first 14 days free, and Fix EUR 149.",
        f"If it fits, the index is at {basis_url}/index and a short overview at {basis_url}. Happy to answer "
        "questions or send screenshots. If it does not fit, no reply needed, and you will not hear from me again.",
    ]
    return "A tool for your list of GEO tools: Krillo", alineas


def aantal_deze_week():
    r = _sql("""SELECT count(*) AS n FROM lijstjes
                 WHERE verstuurd_op > now() - interval '7 days' AND stand = 'gemaild'""")
    return (r or {}).get("n") or 0


def ronde(basis_url, zoek_adres=None, verstuur=None):
    """Elk uur: hoogstens een mail, en niet meer dan PER_WEEK per week."""
    if os.environ.get("LIJSTJESAGENT") == "uit":
        return {"uit": True}
    if aantal_deze_week() >= PER_WEEK:
        return {"weekmaximum": True}
    if zoek_adres is None:
        import contactvinder
        zoek_adres = contactvinder.zoek_adres
    if verstuur is None:
        import emailing
        verstuur = emailing.send_lijstje_mail
    for rij in _sql("""SELECT * FROM lijstjes WHERE stand = 'nieuw' ORDER BY gevonden_op LIMIT 5""",
                    alles=True) or []:
        if _was_afgemeld(rij["domein"]):
            _sql("UPDATE lijstjes SET stand = 'afgemeld' WHERE domein = %s", (rij["domein"],))
            continue
        try:
            gevonden = zoek_adres(f"https://{rij['domein']}") or {}
        except Exception as e:
            gevonden = {"reden": str(e)[:200]}
        adres = gevonden.get("adres")
        if not adres:
            _sql("UPDATE lijstjes SET stand = 'geen adres', notitie = %s WHERE domein = %s",
                 ((gevonden.get("reden") or "Geen adres gevonden.")
                  + (f" Formulier: {gevonden['formulier']}" if gevonden.get("formulier") else ""),
                  rij["domein"]))
            continue
        onderwerp, alineas = mail_tekst(rij, basis_url)
        stop = f"{basis_url}/lijstje/{rij['token']}/stop"
        gelukt = verstuur(adres, onderwerp, alineas, f"{basis_url}/index", stop)
        _sql("""UPDATE lijstjes SET stand = %s, adres = %s, verstuurd_op = now() WHERE domein = %s""",
             ("gemaild" if gelukt else "niet verstuurd", adres, rij["domein"]))
        return {"gemaild": rij["domein"] if gelukt else None, "adres": adres}
    return {"niets": True}


def _was_afgemeld(domein):
    """Alleen een echte afmelding van deze site telt, niet de voorzichtige 'ja'
    die is_afgemeld geeft als de database hapert."""
    r = _sql("SELECT afgemeld_op FROM winkelprofielen WHERE webshop_url = %s", (f"https://{domein}",))
    return bool(r and r.get("afgemeld_op"))


def stop(token):
    r = _sql("UPDATE lijstjes SET stand = 'afgemeld' WHERE token = %s RETURNING domein", (token,))
    return (r or {}).get("domein")


def overzicht():
    return _sql("""SELECT * FROM lijstjes ORDER BY
                     CASE stand WHEN 'gemaild' THEN 0 WHEN 'nieuw' THEN 1 ELSE 2 END,
                     coalesce(verstuurd_op, gevonden_op) DESC LIMIT 200""", alles=True) or []
