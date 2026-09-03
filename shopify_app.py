"""
Krillo - de Shopify-app, stap 1: installeren en de verplichte webhooks.

Waarom deze app er is: zonder advertentiebudget en zonder koude berichten is de
Shopify App Store de enige gratis plek waar webshophouders uit zichzelf komen
zoeken, met hun betaalgegevens al gekoppeld. Dat is geen productkeuze maar een
distributiekeuze.

Wat Shopify verplicht stelt voor een app in de App Store, en wat hier dus in
zit:

1. OAuth. Een winkel moet toestemming geven voordat wij iets mogen. We krijgen
   daarna een sleutel die alleen voor die ene winkel geldt.
2. Handtekeningcontrole. Elk bericht van Shopify draagt een handtekening die
   met ons geheim te controleren is. Klopt die niet, dan antwoorden we met 401.
   Dat wordt bij de beoordeling getest.
3. Drie privacy-webhooks: customers/data_request, customers/redact en
   shop/redact. Die moeten er zijn voordat je mag indienen.

Twee dingen die er BEWUST in zitten en die je niet moet weghalen:

- De winkelnaam wordt gecontroleerd tegen een vast patroon voordat we ermee
  doorgaan. Zonder dat kan iemand ons met ?shop=kwaadaardig.nl naar een eigen
  server laten praten, en dan geven wij onze sleutel weg.
- Elke installatie krijgt een eenmalig kenmerk dat we terugverwachten. Zonder
  dat kan iemand een installatie in gang zetten namens iemand anders.

Vereist in Render: SHOPIFY_API_KEY en SHOPIFY_API_SECRET, uit het scherm van de
app in je Partner Dashboard. Nooit in de code.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import urllib.parse

import requests

# Welke rechten we vragen. Bewust zo min mogelijk: elke extra rechtenvraag is
# een reden voor een winkelier om af te haken, en een vraag bij de beoordeling.
#
# read_products en read_content hebben we nodig om te lezen wat er staat.
# write_products en write_content komen er pas bij in de stap waarin we ook
# echt aanpassen. Nu nog niet: vraag geen schrijfrechten voor iets wat je nog
# niet doet.
SCOPES = "read_products,read_content,read_themes"

API_VERSIE = "2025-07"

# Alleen echte Shopify-winkeladressen. Dit patroon is de belangrijkste
# beveiliging in dit bestand.
WINKEL_PATROON = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*\.myshopify\.com$")

# De verplichte webhooks. app/uninstalled staat er bij omdat we anders van een
# verwijderde app blijven denken dat hij nog geïnstalleerd is.
WEBHOOKS = [
    ("customers/data_request", "/shopify/webhooks/klantgegevens"),
    ("customers/redact", "/shopify/webhooks/klant-wissen"),
    ("shop/redact", "/shopify/webhooks/winkel-wissen"),
    ("app/uninstalled", "/shopify/webhooks/verwijderd"),
]

# Openstaande installaties: kenmerk -> tijdstip. Alleen in het geheugen, want
# het leeft maar een paar seconden. Na een herstart van Render is een halve
# installatie kwijt, en dan begint de winkelier gewoon opnieuw.
_openstaand = {}
_KENMERK_GELDIG_SECONDEN = 600


def _sleutels():
    return (os.environ.get("SHOPIFY_API_KEY"), os.environ.get("SHOPIFY_API_SECRET"))


def beschikbaar():
    """Of de app aanstaat. Zonder sleutels doen we niets en zeggen we dat."""
    api_key, geheim = _sleutels()
    return bool(api_key and geheim)


def waarom_niet():
    api_key, geheim = _sleutels()
    if not api_key:
        return "SHOPIFY_API_KEY ontbreekt in Render."
    if not geheim:
        return "SHOPIFY_API_SECRET ontbreekt in Render."
    return ""


def geldige_winkel(winkel):
    """Of dit een echt Shopify-winkeladres is.

    Bewust streng. Deze waarde komt uit een webadres dat iedereen kan typen, en
    we gebruiken hem om een verbinding op te zetten. Laat je hier van alles
    door, dan kan iemand ons naar zijn eigen server laten praten."""
    if not winkel or not isinstance(winkel, str):
        return False
    return bool(WINKEL_PATROON.match(winkel.strip().lower()))


def _schoon(winkel):
    return (winkel or "").strip().lower()


# ---------------------------------------------------------------------------
# Handtekeningen controleren
# ---------------------------------------------------------------------------

def klopt_query_handtekening(argumenten):
    """Controleert de handtekening op de terugkeerlink van Shopify.

    Shopify hangt aan die link een hmac, berekend over alle andere waarden op
    alfabetische volgorde. Klopt die niet, dan komt het verzoek niet van
    Shopify en doen we niets."""
    api_key, geheim = _sleutels()
    if not geheim:
        return False
    gegeven = argumenten.get("hmac")
    if not gegeven:
        return False

    delen = []
    for sleutel in sorted(k for k in argumenten if k not in ("hmac", "signature")):
        waarde = argumenten.get(sleutel)
        delen.append(f"{sleutel}={waarde}")
    bericht = "&".join(delen)

    verwacht = hmac.new(geheim.encode("utf-8"), bericht.encode("utf-8"),
                        hashlib.sha256).hexdigest()
    # compare_digest en niet ==, zodat de vergelijking altijd even lang duurt.
    return hmac.compare_digest(verwacht, gegeven)


def klopt_webhook_handtekening(ruwe_body, kop_handtekening):
    """Controleert de handtekening op een webhook van Shopify.

    Let op: dit moet over de RUWE body, precies zoals hij binnenkwam. Lees je
    hem eerst als JSON en bouw je hem opnieuw op, dan klopt de handtekening
    nooit meer, want dan staan de spaties anders."""
    api_key, geheim = _sleutels()
    if not geheim or not kop_handtekening:
        return False
    berekend = base64.b64encode(
        hmac.new(geheim.encode("utf-8"), ruwe_body or b"", hashlib.sha256).digest()
    ).decode("utf-8")
    return hmac.compare_digest(berekend, kop_handtekening)


# ---------------------------------------------------------------------------
# Installeren
# ---------------------------------------------------------------------------

def _ruim_oude_kenmerken_op():
    nu = time.time()
    for kenmerk, gezet in list(_openstaand.items()):
        if nu - gezet > _KENMERK_GELDIG_SECONDEN:
            _openstaand.pop(kenmerk, None)


def installatielink(winkel, basis_url):
    """De link waar we de winkelier heen sturen om toestemming te geven.

    Geeft None terug als er iets niet klopt. Bewust None en geen halve link:
    een installatie die stilletjes naar een verkeerde winkel wijst is erger dan
    een foutmelding."""
    api_key, geheim = _sleutels()
    winkel = _schoon(winkel)
    if not api_key or not geldige_winkel(winkel):
        return None

    _ruim_oude_kenmerken_op()
    kenmerk = secrets.token_urlsafe(24)
    _openstaand[kenmerk] = time.time()

    waarden = {
        "client_id": api_key,
        "scope": SCOPES,
        "redirect_uri": f"{basis_url}/shopify/callback",
        "state": kenmerk,
    }
    return f"https://{winkel}/admin/oauth/authorize?" + urllib.parse.urlencode(waarden)


def kenmerk_klopt(kenmerk):
    """Of dit kenmerk van ons komt en nog niet gebruikt is.

    Eenmalig: we halen hem meteen weg. Zo kan dezelfde terugkeerlink niet twee
    keer gebruikt worden."""
    _ruim_oude_kenmerken_op()
    return _openstaand.pop(kenmerk, None) is not None


def haal_toegangssleutel(winkel, code):
    """Wisselt de eenmalige code om voor de sleutel van deze winkel.

    Geeft een woordenboek terug met "gelukt". Bij een mislukking staat er ook
    "fout" in met de echte reden, want een lege uitkomst is niet te
    onderscheiden van "er is niets aan de hand"."""
    api_key, geheim = _sleutels()
    winkel = _schoon(winkel)
    if not api_key or not geheim:
        return {"gelukt": False, "fout": waarom_niet()}
    if not geldige_winkel(winkel):
        return {"gelukt": False, "fout": f"Geen geldig winkeladres: {winkel!r}"}

    try:
        antwoord = requests.post(
            f"https://{winkel}/admin/oauth/access_token",
            json={"client_id": api_key, "client_secret": geheim, "code": code},
            timeout=20,
        )
        if antwoord.status_code >= 300:
            return {"gelukt": False,
                    "fout": f"Shopify gaf {antwoord.status_code}: {antwoord.text[:200]}"}
        gegevens = antwoord.json()
        sleutel = gegevens.get("access_token")
        if not sleutel:
            return {"gelukt": False, "fout": "Shopify gaf geen toegangssleutel terug."}
        return {"gelukt": True, "sleutel": sleutel,
                "rechten": gegevens.get("scope") or SCOPES}
    except Exception as e:
        return {"gelukt": False, "fout": f"{type(e).__name__}: {e}"[:300]}


# ---------------------------------------------------------------------------
# Praten met de winkel
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# De nieuwe manier: Shopify regelt het installeren, wij ruilen een kaartje in
# ---------------------------------------------------------------------------
#
# Bij de nieuwe manier stuurt Shopify de winkelier rechtstreeks naar ons scherm
# en krijgen wij een kort geldig kaartje mee, een id_token. Dat is een JWT die
# ondertekend is met ons eigen geheim, en die een minuut geldig is. Wij
# controleren die handtekening en ruilen hem daarna in voor de echte sleutel
# van de winkel.
#
# Bewust zelf uitgerekend en geen extra pakket erbij. Het is HMAC-SHA256 en
# vier controles, en elk pakket dat je toevoegt is er een die op Render mis kan
# gaan bij een versie-update.


def _vul_aan(stuk):
    """Base64 uit een JWT mist soms de opvulling aan het eind."""
    return stuk + "=" * (-len(stuk) % 4)


def _hostnaam(waarde):
    """De kale hostnaam uit iets als https://winkel.myshopify.com/admin."""
    if not waarde:
        return ""
    tekst = str(waarde).strip().lower()
    tekst = tekst.split("://")[-1]
    return tekst.split("/")[0].split("?")[0]


def controleer_id_token(id_token, speling_seconden=10):
    """Controleert het kaartje van Shopify en geeft de inhoud terug.

    Geeft None terug als er iets niet klopt. De aanroeper hoort dan met 401 te
    antwoorden en NIET door te gaan naar het inwisselen, want dan zou iemand
    met een zelfgemaakt kaartje onze sleutel kunnen opvragen.

    Wat er gecontroleerd wordt, en dat is precies wat Shopify eist:
    de handtekening, dat hij nog niet verlopen is, dat hij al geldig is, dat
    hij voor onze app bedoeld is, en dat de afzender en de bestemming dezelfde
    winkel zijn.

    De speling van tien seconden is er omdat de klok van Render en die van
    Shopify nooit precies gelijk lopen. Zonder die speling faalt af en toe een
    geldig kaartje, en dat is een fout die je nooit kunt namaken."""
    api_key, geheim = _sleutels()
    if not api_key or not geheim or not id_token:
        return None

    delen = str(id_token).split(".")
    if len(delen) != 3:
        return None
    kop_deel, inhoud_deel, handtekening_deel = delen

    try:
        kop = json.loads(base64.urlsafe_b64decode(_vul_aan(kop_deel)))
        inhoud = json.loads(base64.urlsafe_b64decode(_vul_aan(inhoud_deel)))
    except Exception:
        return None

    # Alleen HS256. Zou je hier meegaan met wat er in de kop staat, dan kan
    # iemand "alg": "none" sturen en is de handtekening niets meer waard.
    if kop.get("alg") != "HS256":
        return None

    bericht = f"{kop_deel}.{inhoud_deel}".encode("ascii")
    verwacht = base64.urlsafe_b64encode(
        hmac.new(geheim.encode("utf-8"), bericht, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")
    if not hmac.compare_digest(verwacht, handtekening_deel.rstrip("=")):
        return None

    nu = time.time()
    try:
        if float(inhoud.get("exp", 0)) < nu - speling_seconden:
            return None
        if float(inhoud.get("nbf", 0)) > nu + speling_seconden:
            return None
    except (TypeError, ValueError):
        return None

    # Voor welke app is dit kaartje bedoeld.
    doel = inhoud.get("aud")
    if isinstance(doel, list):
        if api_key not in doel:
            return None
    elif doel != api_key:
        return None

    # Afzender en bestemming moeten dezelfde winkel zijn.
    afzender = _hostnaam(inhoud.get("iss"))
    bestemming = _hostnaam(inhoud.get("dest"))
    if not afzender or afzender != bestemming:
        return None
    if not geldige_winkel(bestemming):
        return None

    inhoud["winkel"] = bestemming
    return inhoud


def wissel_id_token(winkel, id_token):
    """Ruilt het kaartje in voor de echte sleutel van deze winkel.

    Vraagt bewust een blijvende sleutel (offline), want Krillo meet ook 's
    nachts door als er niemand in het beheerscherm zit. Een sleutel die aan een
    ingelogde gebruiker hangt is dan waardeloos.

    Roep dit ALLEEN aan nadat controleer_id_token gelukt is."""
    api_key, geheim = _sleutels()
    winkel = _schoon(winkel)
    if not api_key or not geheim:
        return {"gelukt": False, "fout": waarom_niet()}
    if not geldige_winkel(winkel):
        return {"gelukt": False, "fout": f"Geen geldig winkeladres: {winkel!r}"}

    try:
        antwoord = requests.post(
            f"https://{winkel}/admin/oauth/access_token",
            json={
                "client_id": api_key,
                "client_secret": geheim,
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": id_token,
                "subject_token_type": "urn:ietf:params:oauth:token-type:id_token",
                "requested_token_type":
                    "urn:shopify:params:oauth:token-type:offline-access-token",
            },
            timeout=20,
        )
        if antwoord.status_code >= 300:
            return {"gelukt": False,
                    "fout": f"Shopify gaf {antwoord.status_code}: {antwoord.text[:200]}"}
        gegevens = antwoord.json()
        sleutel = gegevens.get("access_token")
        if not sleutel:
            return {"gelukt": False, "fout": "Shopify gaf geen toegangssleutel terug."}
        return {"gelukt": True, "sleutel": sleutel,
                "rechten": gegevens.get("scope") or SCOPES}
    except Exception as e:
        return {"gelukt": False, "fout": f"{type(e).__name__}: {e}"[:300]}


def _kop(sleutel):
    return {"X-Shopify-Access-Token": sleutel, "Content-Type": "application/json"}


def winkelgegevens(winkel, sleutel):
    """Naam, e-mailadres en webadres van de winkel. None bij een fout."""
    winkel = _schoon(winkel)
    if not geldige_winkel(winkel) or not sleutel:
        return None
    try:
        antwoord = requests.get(
            f"https://{winkel}/admin/api/{API_VERSIE}/shop.json",
            headers=_kop(sleutel), timeout=20)
        if antwoord.status_code >= 300:
            print(f"Winkelgegevens ophalen mislukt voor {winkel}: {antwoord.status_code}")
            return None
        shop = (antwoord.json() or {}).get("shop") or {}
        return {
            "naam": shop.get("name"),
            "email": shop.get("email"),
            "domein": shop.get("domain"),
            "land": shop.get("country_code"),
            "taal": shop.get("primary_locale"),
        }
    except Exception as e:
        print(f"Winkelgegevens ophalen mislukt voor {winkel}: {e}")
        return None


def meld_webhooks_aan(winkel, sleutel, basis_url):
    """Meldt de verplichte webhooks aan bij deze winkel.

    Geeft terug welke gelukt zijn en welke niet, zodat een halve installatie
    zichtbaar is in de logs in plaats van dat je er bij de beoordeling van
    Shopify achterkomt.

    Een webhook die al bestaat geeft een foutmelding van Shopify terug. Dat is
    geen probleem en telt hier als gelukt: het doel is dat hij er is, niet dat
    wij hem net hebben aangemaakt."""
    winkel = _schoon(winkel)
    if not geldige_winkel(winkel) or not sleutel:
        return {"gelukt": [], "mislukt": [("alles", "geen geldige winkel of sleutel")]}

    gelukt, mislukt = [], []
    for onderwerp, pad in WEBHOOKS:
        try:
            antwoord = requests.post(
                f"https://{winkel}/admin/api/{API_VERSIE}/webhooks.json",
                headers=_kop(sleutel),
                json={"webhook": {"topic": onderwerp,
                                  "address": f"{basis_url}{pad}",
                                  "format": "json"}},
                timeout=20,
            )
            if antwoord.status_code < 300:
                gelukt.append(onderwerp)
            elif "already been taken" in antwoord.text or antwoord.status_code == 422:
                gelukt.append(onderwerp)
            else:
                mislukt.append((onderwerp, f"{antwoord.status_code}: {antwoord.text[:150]}"))
        except Exception as e:
            mislukt.append((onderwerp, f"{type(e).__name__}: {e}"[:150]))

    if mislukt:
        print(f"LET OP: webhooks niet aangemeld voor {winkel}: {mislukt}")
    return {"gelukt": gelukt, "mislukt": mislukt}


def winkeladres(winkel, sleutel=None):
    """Het gewone webadres van de winkel, zoals klanten het kennen.

    Krillo werkt overal met dat adres als sleutel, niet met het interne
    naam.myshopify.com. Lukt het ophalen niet, dan geven we het interne adres
    terug: liever een adres dat werkt dan niets."""
    winkel = _schoon(winkel)
    if sleutel:
        gegevens = winkelgegevens(winkel, sleutel)
        if gegevens and gegevens.get("domein"):
            return f"https://{gegevens['domein']}"
    return f"https://{winkel}" if winkel else ""
