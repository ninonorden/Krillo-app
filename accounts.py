"""Accounts: inloggen met wachtwoord, Google of Microsoft (9 oktober 2026, stap 353).

Nino: "wanneer ik op Log in klik krijg ik nog het oude scherm met een mail.
Ik wil sign up met Gmail en Microsoft, en een wachtwoord voor wie met een
gewoon mailadres begint." Tot nu toe was de geheime link in de mail de enige
sleutel tot het dashboard. Die blijft bestaan (oude mails, wachtwoord vergeten),
maar wie een account heeft komt nu direct binnen.

Een account is een mailadres. Een mailadres kan bij meer winkels horen
(klanten.email); na het inloggen kiest hij welke, of gaat hij direct naar de
enige. Een account zonder winkel gaat naar /start.

Veiligheid:
- wachtwoorden alleen als hash (werkzeug, scrypt/pbkdf2), nooit leesbaar;
- na 10 foute pogingen in 15 minuten wacht een adres een kwartier;
- Google en Microsoft alleen met een geverifieerd mailadres, en met een
  'state' in de sessie tegen een vervalst terugverzoek;
- de knoppen staan er alleen als de sleutels in Render staan (GOOGLE_CLIENT_ID
  en GOOGLE_CLIENT_SECRET, MICROSOFT_CLIENT_ID en MICROSOFT_CLIENT_SECRET).
"""
import os
import secrets
import time
from urllib.parse import urlencode

import requests
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash

import db

MIN_LENGTE = 8
_POGINGEN = {}            # email -> [tijdstippen van foute pogingen]
MAX_FOUT, VENSTER = 10, 15 * 60

AANBIEDERS = {
    "google": {
        "naam": "Google",
        "auth": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "info": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "id": "GOOGLE_CLIENT_ID", "geheim": "GOOGLE_CLIENT_SECRET",
    },
    "microsoft": {
        "naam": "Microsoft",
        "auth": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "info": "https://graph.microsoft.com/v1.0/me",
        "scope": "openid email profile User.Read",
        "id": "MICROSOFT_CLIENT_ID", "geheim": "MICROSOFT_CLIENT_SECRET",
    },
}


def _sql(opdracht, waarden=None, een=False, alles=False):
    conn = db._get_connection()
    if conn is None:
        return None
    try:
        with conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(opdracht, waarden)
                if een:
                    return cur.fetchone()
                if alles:
                    return cur.fetchall()
                return True
    except Exception as e:
        print(f"Accounts: database mislukt: {e}")
        return None
    finally:
        conn.close()


def maak_tabellen(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS accounts (
                email TEXT PRIMARY KEY,
                wachtwoord TEXT,
                google_sub TEXT,
                microsoft_sub TEXT,
                gemaakt_op TIMESTAMPTZ DEFAULT now(),
                laatst_ingelogd TIMESTAMPTZ)""")


def _schoon(email):
    return (email or "").strip().lower()


def account(email):
    return _sql("SELECT * FROM accounts WHERE email = %s", (_schoon(email),), een=True)


def heeft_wachtwoord(email):
    a = account(email)
    return bool(a and a.get("wachtwoord"))


def zet_wachtwoord(email, wachtwoord):
    """Maakt het account als het nog niet bestaat. Geeft een fout of None."""
    if len(wachtwoord or "") < MIN_LENGTE:
        return f"Use at least {MIN_LENGTE} characters."
    ok = _sql("""INSERT INTO accounts (email, wachtwoord) VALUES (%s, %s)
                 ON CONFLICT (email) DO UPDATE SET wachtwoord = EXCLUDED.wachtwoord""",
              (_schoon(email), generate_password_hash(wachtwoord)))
    return None if ok else "Saving failed. Try again."


def _geblokkeerd(email):
    nu = time.time()
    lijst = [t for t in _POGINGEN.get(email, []) if nu - t < VENSTER]
    _POGINGEN[email] = lijst
    return len(lijst) >= MAX_FOUT


def controleer(email, wachtwoord):
    """(ok, fout). Altijd dezelfde fout bij onbekend adres of fout wachtwoord,
    zodat niemand kan uitzoeken welke adressen een account hebben."""
    email = _schoon(email)
    if _geblokkeerd(email):
        return False, "Too many attempts. Wait 15 minutes, or email yourself a login link."
    a = account(email)
    if a and a.get("wachtwoord") and check_password_hash(a["wachtwoord"], wachtwoord or ""):
        _POGINGEN.pop(email, None)
        _sql("UPDATE accounts SET laatst_ingelogd = now() WHERE email = %s", (email,))
        return True, None
    _POGINGEN.setdefault(email, []).append(time.time())
    return False, "That email and password do not match. Forgot it? Email yourself a login link below."


def winkels(email):
    """De winkels van dit mailadres, betalende en proef, nieuwste eerst."""
    return _sql("""SELECT webshop_url, klant_token, pakket, opgezegd_op FROM klanten
                    WHERE lower(email) = %s ORDER BY opgezegd_op IS NOT NULL, webshop_url""",
                (_schoon(email),), alles=True) or []


# ------------------------------------------------------------------ Google en Microsoft
def actief(aanbieder):
    a = AANBIEDERS.get(aanbieder)
    return bool(a and os.environ.get(a["id"]) and os.environ.get(a["geheim"]))


def actieve():
    return [k for k in AANBIEDERS if actief(k)]


def begin_url(aanbieder, terug_url, state):
    a = AANBIEDERS[aanbieder]
    return a["auth"] + "?" + urlencode({
        "client_id": os.environ.get(a["id"]), "redirect_uri": terug_url, "response_type": "code",
        "scope": a["scope"], "state": state, "prompt": "select_account"})


def nieuwe_state():
    return secrets.token_urlsafe(24)


def ruil_code(aanbieder, code, terug_url, post=requests.post, get=requests.get):
    """Code -> geverifieerd mailadres en vast id bij de aanbieder. (email, sub) of (None, fout)."""
    a = AANBIEDERS[aanbieder]
    try:
        t = post(a["token"], data={"code": code, "client_id": os.environ.get(a["id"]),
                                   "client_secret": os.environ.get(a["geheim"]),
                                   "redirect_uri": terug_url, "grant_type": "authorization_code"}, timeout=15)
        toegang = (t.json() or {}).get("access_token")
        if not toegang:
            return None, f"{a['naam']} did not let us in. Try again."
        info = get(a["info"], headers={"Authorization": f"Bearer {toegang}"}, timeout=15).json() or {}
    except Exception as e:
        print(f"Inloggen via {aanbieder} mislukt: {e}")
        return None, f"{a['naam']} did not answer. Try again."
    if aanbieder == "google":
        if not info.get("email") or not info.get("email_verified"):
            return None, "Your Google account has no verified email address."
        return (_schoon(info["email"]), str(info.get("sub") or "")), None
    email = info.get("mail") or info.get("userPrincipalName") or ""
    if "@" not in email:
        return None, "Your Microsoft account has no email address we can use."
    return (_schoon(email), str(info.get("id") or "")), None


def koppel(aanbieder, email, sub):
    kolom = "google_sub" if aanbieder == "google" else "microsoft_sub"
    _sql(f"""INSERT INTO accounts (email, {kolom}, laatst_ingelogd) VALUES (%s, %s, now())
             ON CONFLICT (email) DO UPDATE SET {kolom} = EXCLUDED.{kolom}, laatst_ingelogd = now()""",
         (_schoon(email), sub))
