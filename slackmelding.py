"""Meldingen in Slack bij een verandering in je plek (15 oktober 2026).

Goedgekeurd voorstel 5. Een mail wordt gemist; een bericht in het Slack-kanaal
van het team niet. De klant plakt een "incoming webhook" van Slack in zijn
dashboard (Plan). Na elke maandmeting gaat dezelfde melding als de mail daar
ook heen, kort.

WhatsApp bewust niet: dat kan alleen via de betaalde, door Meta goedgekeurde
WhatsApp Business-koppeling, met vooraf goedgekeurde berichtsjablonen. Te veel
gedoe voor nu; bij vraag van klanten opnieuw bekijken.

Veilig: alleen adressen van hooks.slack.com worden geaccepteerd (anders kon
iemand onze server elk willekeurig adres laten aanroepen).
"""
import re

import db

SLEUTEL = "slack_webhook:"
# 16 oktober (Nino akkoord): Slack-meldingen horen bij Fix (en Agencies), niet
# bij Watch. Watch houdt de mail. Ook in de app, niet alleen op /pricing:
# een Watch-klant kan niet koppelen en krijgt geen Slack-bericht.
PAKKETTEN = {"fix", "merken", "bureau", "agency"}


def mag(pakket):
    return (pakket or "").lower() in PAKKETTEN


def _mag_token(klant_token):
    try:
        return mag((db.get_klant(klant_token) or {}).get("pakket"))
    except Exception:
        return False
_GELDIG = re.compile(r"^https://hooks\.slack\.com/services/[A-Za-z0-9/_-]{20,200}$")


def geldig(url):
    return bool(_GELDIG.match((url or "").strip()))


def zet(klant_token, url):
    """Bewaar (of wis met een lege url). Geeft True als het gelukt is."""
    url = (url or "").strip()
    if url and not geldig(url):
        return False
    db.zet_instelling(SLEUTEL + klant_token, url)
    return True


def van(klant_token):
    return (db.get_instelling(SLEUTEL + (klant_token or "")) or "").strip() or None


def stuur(klant_token, tekst, link=None, post=None):
    """Stuurt een bericht als de klant Slack koppelde. Geeft True/False/None (niet gekoppeld)."""
    url = van(klant_token)
    if not url or not geldig(url):
        return None
    if not _mag_token(klant_token):
        return None
    if post is None:
        import requests
        post = requests.post
    bericht = tekst.strip() + (f"\n<{link}|Open your Krillo dashboard>" if link else "")
    try:
        r = post(url, json={"text": bericht}, timeout=10)
        return getattr(r, "status_code", 500) < 300
    except Exception as e:
        print(f"Slack-melding mislukt: {e}")
        return False
