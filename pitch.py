"""Pitchlink voor bureaus (stap 185, 16 oktober 2026).

WAAROM. Peec geeft bureaus een pitch-werkruimte om een prospect te laten zien.
Wij hadden de gratis check van tien winkels op /agencies, maar een bureau kon
daar niets van doorsturen. Nu: per winkel uit de index een eigen pagina, 14
dagen geldig, met de naam van het bureau erop en een knop naar HET BUREAU (niet
naar onze proef: het bureau verkoopt zijn eigen werk, Krillo is het meetwerk
eronder). Klein onderaan: gemeten door de Krillo Index.

Een bureau dat dit gebruikt, is een warme lead voor het bureaupakket; daarom
een melding aan beheer bij elke nieuwe link. De pagina zelf schrijft niets
(een link kan vooraf geopend worden door een mailprogramma).
"""
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

import db

SLEUTEL = "pitch:"
GELDIG_DAGEN = 14


def maak(webshop_url, bureau, email, website="", nu=None):
    """Geeft het kenmerk, of None bij ongeldige invoer."""
    nu = nu or datetime.now(timezone.utc)
    bureau = re.sub(r"\s+", " ", (bureau or "")).strip()[:80]
    email = (email or "").strip()[:190]
    website = (website or "").strip()[:200]
    if len(bureau) < 2 or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return None
    if website and not re.match(r"^(https?://)?[a-z0-9.-]+\.[a-z]{2,}(/\S*)?$", website, re.I):
        website = ""
    if website and not website.startswith("http"):
        website = "https://" + website
    token = secrets.token_urlsafe(12)
    db.zet_instelling(SLEUTEL + token, json.dumps({"url": webshop_url, "bureau": bureau, "email": email,
                                                   "website": website, "tot": (nu + timedelta(days=GELDIG_DAGEN)).isoformat()}))
    return token


def lees(token, nu=None):
    """De pitch, of None als hij niet bestaat of verlopen is."""
    nu = nu or datetime.now(timezone.utc)
    if not token or len(token) > 40:
        return None
    try:
        p = json.loads(db.get_instelling(SLEUTEL + token) or "null")
    except (TypeError, ValueError):
        return None
    if not p:
        return None
    try:
        if datetime.fromisoformat(p["tot"]) < nu:
            return None
    except (KeyError, ValueError):
        return None
    return p
