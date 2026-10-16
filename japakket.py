"""Het ja-pakket: wie "ja" of "yes" terugmailt, krijgt meteen de ene wijziging (16 oktober 2026).

WAAROM. Nino: "ik wil dit geautomatiseerd, en niet alleen 'yes' maar ook 'ja',
want de mail is Nederlands". Koude mail versie e en de nieuwe opvolging vragen
om met ja te antwoorden. Wie dat doet, is de warmste lead die er is, en mag niet
wachten tot Nino tijd heeft. Dus:
1. Een kort "ja"/"yes"/"graag"/"ja graag"/"yes please" herkennen we op vaste
   woorden (geen AI-gok), in elke mail die terugkomt.
2. Er staat meteen een concept klaar met de ene wijziging voor hun eigen site:
   de vraag die ze verliezen, wie AI wel noemt, drie stappen (vraagaanpak.py),
   en een uitgeschreven voorbeeld (titel, eerste alinea, drie vragen) voor hun
   pagina. Plus hun eigen Krillo-pagina en de link naar 14 dagen gratis Watch.
   In het Nederlands als de winkel Nederlands is, anders in het Engels.
3. Staat "ja-antwoorden zelf versturen" aan (/admin/antwoorden, standaard AAN
   op verzoek van Nino), dan gaat het concept na WACHT_MINUTEN vanzelf weg,
   binnen kantooruren. Tot die tijd kan Nino het aanpassen of tegenhouden.
   Uit: alles wacht op Nino, zoals elk ander antwoord.

EERLIJK. Het voorbeeld verzint geen feiten over de winkel: waar we iets niet
weten (prijs, levertijd) staat een [invulplek]. De controleagent (tekstkeuring)
keurt het voor het weggaat; afgekeurd gaat niet vanzelf.
"""
import os
import re
import time
from datetime import datetime, timedelta, timezone

import db

SLEUTEL_ZELF = "ja_zelf_versturen"
WACHT_MINUTEN = 20
MODEL = os.environ.get("JA_MODEL", "claude-haiku-4-5-20251001")

_JA = re.compile(
    r"^(ja|jazeker|jawel|yes|yep|yeah|graag|zeker|prima|oke|ok|okay|okee|sure|please|top|"
    r"ja graag|ja hoor|ja prima|ja zeker|ja please|ja, graag|ja graag!|graag ja|ja stuur maar|stuur maar|"
    r"doe maar|stuur maar door|yes please|yes sure|sure thing|go ahead|send it|"
    r"ja,? (stuur|graag|dat wil ik|ik ben benieuwd|benieuwd)[\w\s]*|"
    r"yes,? (please|send|i would like)[\w\s]*)[\s.!,]*$", re.I)


def is_ja(tekst):
    """Een kort ja. Alleen de eerste regels zonder groet; lange mails zijn een gesprek."""
    regels = [r.strip() for r in (tekst or "").splitlines() if r.strip()]
    kern = []
    for r in regels[:4]:
        if re.match(r"^(groet|groeten|met vriendelijke groet|mvg|gr\.?|regards|best|thanks|bedankt|dank)\b", r, re.I):
            break
        kern.append(r)
    zin = re.sub(r"^(hoi|hi|hallo|hello|hey|beste|dear)\b[^,\n]*,?\s*", "", " ".join(kern), flags=re.I).strip()
    if not zin or len(zin) > 80:
        return False
    return bool(_JA.match(zin))


def zelf_versturen():
    return (db.get_instelling(SLEUTEL_ZELF) or "ja").lower() == "ja"


def _voorbeeld(onderwerp, vraag, winkel, nl, client):
    """Titel, eerste alinea en drie vragen, met [invulplekken] voor wat we niet weten."""
    if client is None:
        return None
    taal = "Dutch" if nl else "English"
    prompt = (
        f"Write example web copy in {taal} for the online store {winkel}, so that AI assistants can name it "
        f"when shoppers ask: \"{vraag}\". The page is about: {onderwerp}.\n"
        "Give exactly: one page title (max 60 characters), one first paragraph (2 or 3 sentences), and three "
        "short questions with a one-sentence answer each (price range, delivery, how to choose).\n"
        "RULES: Do not invent facts about the store. Where you would need a fact you do not know (prices, "
        "delivery times, brands, numbers), write a placeholder in square brackets, like [prijs vanaf] or "
        "[delivery time]. No long dashes. No superlatives like 'best'. Plain text, no markdown, no intro.\n"
        "Format:\nTitle: ...\nFirst paragraph: ...\nQ: ...\nA: ...\nQ: ...\nA: ...\nQ: ...\nA: ...")
    gestart = time.monotonic()
    antwoord = client.messages.create(model=MODEL, max_tokens=600, messages=[{"role": "user", "content": prompt}])
    try:
        import kosten
        kosten.registreer_aanroep(provider="anthropic", model=MODEL, invoer_tokens=antwoord.usage.input_tokens,
                                  uitvoer_tokens=antwoord.usage.output_tokens, soort="japakket",
                                  duur_ms=int((time.monotonic() - gestart) * 1000))
    except Exception:
        pass
    tekst = (antwoord.content[0].text or "").replace("—", ",").replace("–", "-")
    tekst = re.sub(r"<[^>]+>|\*\*|#+ ", "", tekst).strip()
    if nl:
        tekst = (tekst.replace("Title:", "Titel:").replace("First paragraph:", "Eerste alinea:")
                 .replace("Q:", "Vraag:").replace("A:", "Antwoord:"))
    return tekst or None


def concept(webshop_url, basis_url, nl=True, client=None, beeld=None):
    """Het ja-pakket als platte tekst, of None als er niets eerlijks te zeggen valt."""
    import vraagaanpak
    import verkoopagent as va
    if beeld is None:
        try:
            import klantbeeld
            beeld = klantbeeld.bouw(webshop_url)
        except Exception as e:
            print(f"Ja-pakket, beeld mislukt voor {webshop_url}: {e}")
            beeld = None
    if not beeld:
        return None
    vraag = va._vraag_voor(webshop_url, beeld) or next(
        (v for v in beeld.get("gemiste_vragen") or [] if v.get("vraag") and v.get("concurrenten")), None)
    if not vraag:
        return None
    winkel = va._kaal(webshop_url)
    namen = vraag["concurrenten"][:2]
    a = vraagaanpak.aanpak(vraag["vraag"], namen, en=not nl)
    try:
        voorbeeld = _voorbeeld(a["onderwerp"], vraag["vraag"], winkel, nl, client)
    except Exception as e:
        print(f"Ja-pakket, voorbeeld schrijven mislukt: {e}")
        voorbeeld = None
    token = db.get_benchmark_token(webshop_url)
    pagina = f"{basis_url}/uitkomst/{token}" if token else None
    proef = f"{basis_url}/uitkomst/{token}/verder?plan=watch" if token else f"{basis_url}/start"
    stappen = "\n".join(f"{i}. {s}" for i, s in enumerate(a["stappen"], 1))
    if nl:
        delen = [
            "Hoi,",
            f"Top, hier is de ene wijziging voor {winkel}.",
            f"De vraag: “{vraag['vraag']}”. AI noemt nu {' en '.join(namen)}, niet {winkel}.",
            f"Wat je doet:\n{stappen}",
        ]
        if voorbeeld:
            delen.append("Zo kan het eruitzien (vul de [plekken] zelf in):\n\n" + voorbeeld)
        if pagina:
            delen.append(f"Alle vragen die je verliest, met het echte antwoord van AI, staan hier: {pagina}")
        delen.append(f"Wil je dit elke maand, met alle teksten klaar om te plakken? Probeer Watch 14 dagen "
                     f"gratis: {proef}")
        delen.append("Vragen? Antwoord gewoon op deze mail.")
    else:
        delen = [
            "Hi,",
            f"Great, here is the one change for {winkel}.",
            f"The question: “{vraag['vraag']}”. AI now names {' and '.join(namen)}, not {winkel}.",
            f"What to do:\n{stappen}",
        ]
        if voorbeeld:
            delen.append("This is what it could look like (fill in the [brackets] yourself):\n\n" + voorbeeld)
        if pagina:
            delen.append(f"Every question you lose, with the real AI answer, is here: {pagina}")
        delen.append(f"Want this every month, with every text ready to paste? Try Watch free for 14 days: {proef}")
        delen.append("Questions? Just reply to this email.")
    return "\n\n".join(delen)


def te_versturen(nu=None):
    """Ja-concepten die lang genoeg klaarstonden en nog niet weg zijn."""
    nu = nu or datetime.now(timezone.utc)
    conn = db._get_connection()
    if conn is None:
        return []
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""SELECT id, concept FROM antwoorden
                                WHERE soort = 'ja' AND stand = 'concept' AND concept IS NOT NULL
                                  AND ontvangen_op < %s ORDER BY ontvangen_op LIMIT 10""",
                            (nu - timedelta(minutes=WACHT_MINUTEN),))
                return cur.fetchall()
    except Exception as e:
        print(f"Ja-pakket, wachtenden ophalen mislukt: {e}")
        return []
    finally:
        conn.close()


def ronde(binnen_kantooruren=True, nu=None):
    """Verstuurt klaarstaande ja-pakketten als dat aanstaat. Geeft het aantal."""
    if not zelf_versturen() or not binnen_kantooruren:
        return 0
    import antwoordagent
    import emailing
    n = 0
    for nr, tekst in te_versturen(nu):
        # Laatste hek: de controleagent. Afgekeurd blijft staan voor Nino.
        if not emailing._gekeurd("Re: ja-pakket", [a for a in tekst.split("\n\n") if a.strip()], "ja-pakket"):
            continue
        if antwoordagent.verstuur(nr, tekst):
            n += 1
    return n
