"""Het mailadres van een webshop opzoeken op zijn eigen site.

Waarom dit bestaat: de lijst met winkels is zo gemaakt, maar de adressen erbij
zoeken is uren klikken. Dat is werk dat een server kan doen.

Waarom het voorzichtig is: een verkeerd adres is een bounce, en genoeg bounces
maken je domein waardeloos. Daarom raden wij nooit. Wij pakken alleen wat de
winkel zelf op zijn site heeft gezet, en als wij niets vinden laten wij het leeg.

En één regel die niet technisch is maar juridisch: wij pakken alleen algemene
adressen (info@, contact@, hallo@). Naar een algemeen adres van een bedrijf mag
je in Nederland en in Belgie zakelijk mailen. Naar het persoonlijke adres van
een medewerker mag dat in Belgie niet. Een adres met een voornaam erin slaan wij
dus over, ook als het het enige is dat we vinden.
"""

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import scan_engine

# Waar een webwinkel zijn adres neerzet. In deze volgorde, want op de
# contactpagina staat het adres waar hij post op wil, en in de voettekst van de
# homepage staat soms het adres van de bouwer.
PADEN = [
    "/pages/contact", "/contact", "/contact-us", "/nl/contact", "/contactez-nous",
    "/pages/contact-us", "/pages/over-ons", "/over-ons", "/pages/about-us",
    "/klantenservice", "/pages/klantenservice", "/service", "/algemene-voorwaarden",
    "/pages/algemene-voorwaarden", "/policies/terms-of-service",
]

ADRES = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Adressen die nooit een echte mailbox van de winkel zijn. Dit zijn de adressen
# van bouwers, plugins en foutmelders die in de broncode van bijna elke shop
# staan. Mail je daarheen, dan mail je niemand.
ONZIN = (
    "example.com", "sentry.io", "wixpress.com", "shopify.com", "myshopify.com",
    "wordpress.com", "lightspeed", "mijnwebwinkel", "webador", "squarespace",
    "godaddy", "domain.com", "email.com", "yourdomain", "jouwdomein",
    "sentry-next", "cloudflare", "google.com", "gstatic", "facebook.com",
    "instagram.com", "png", "jpg", "jpeg", "gif", "webp", "svg", "css", "js",
)

# Postbussen die met opzet niet gelezen worden.
NIET_LEZEN = ("noreply", "no-reply", "donotreply", "geenantwoord", "mailer-daemon",
              "postmaster", "abuse", "webmaster@")

# Wat wij als algemeen adres beschouwen. Alles wat hier niet in staat behandelen
# wij als persoonlijk en slaan wij over.
ALGEMEEN = ("info", "contact", "hallo", "hello", "sales", "verkoop", "shop",
            "winkel", "klantenservice", "service", "support", "bestellingen",
            "orders", "vragen", "mail", "post", "administratie", "office",
            "bonjour", "onthaal", "klanten", "webshop", "team")


def _domein(url):
    try:
        netloc = urlparse(url if "://" in url else "https://" + url).netloc.lower()
    except Exception:
        return ""
    return netloc[4:] if netloc.startswith("www.") else netloc


def _bruikbaar(adres, winkeldomein):
    """Of wij dit adres mogen gebruiken. Bij twijfel: nee."""
    adres = (adres or "").strip().lower().strip(".,;:)('\"")
    if not adres or adres.count("@") != 1 or len(adres) > 120:
        return None
    gebruiker, _, gastheer = adres.partition("@")
    if not gebruiker or "." not in gastheer:
        return None
    if any(rommel in adres for rommel in ONZIN):
        return None
    if any(adres.startswith(dood) or dood in gebruiker for dood in NIET_LEZEN):
        return None
    # Het adres moet bij de winkel horen. Een gmail-adres in de voettekst is
    # vaak van de bouwer, maar bij eenmanszaken juist wel het echte adres, dus
    # dat laten wij toe zolang de rest klopt.
    eigen_domein = gastheer == winkeldomein or gastheer.endswith("." + winkeldomein)
    vrij = gastheer in ("gmail.com", "hotmail.com", "outlook.com", "live.nl",
                        "ziggo.nl", "kpnmail.nl", "telenet.be", "skynet.be")
    if not (eigen_domein or vrij):
        return None
    # Algemeen of persoonlijk. Alleen het deel voor de @ telt.
    kaal = re.split(r"[.\-_+0-9]", gebruiker)
    if not any(deel in ALGEMEEN for deel in kaal if deel):
        return {"adres": adres, "algemeen": False, "eigen_domein": eigen_domein}
    return {"adres": adres, "algemeen": True, "eigen_domein": eigen_domein}


def _uit_pagina(html, basis_url, winkeldomein):
    """Alle bruikbare adressen op één pagina, mailto-links eerst.

    Een mailto-link is betrouwbaarder dan een adres in de lopende tekst: die
    heeft iemand er expres neergezet om post op te krijgen."""
    gevonden = []
    try:
        soep = BeautifulSoup(html, "html.parser")
    except Exception:
        soep = None

    if soep is not None:
        for link in soep.find_all("a", href=True):
            href = link["href"]
            if href.lower().startswith("mailto:"):
                adres = href[7:].split("?")[0]
                oordeel = _bruikbaar(adres, winkeldomein)
                if oordeel:
                    oordeel["vandaan"] = "mailto-link"
                    gevonden.append(oordeel)
        # Scripts en stijlen eruit, anders vissen wij adressen uit de code van
        # de winkelsoftware in plaats van van de pagina.
        for weg in soep(["script", "style", "noscript"]):
            weg.decompose()
        tekst = soep.get_text(" ")
    else:
        tekst = html

    for adres in ADRES.findall(tekst or ""):
        oordeel = _bruikbaar(adres, winkeldomein)
        if oordeel:
            oordeel["vandaan"] = "tekst op de pagina"
            gevonden.append(oordeel)
    return gevonden


def zoek_adres(webshop_url, timeout=12, max_paginas=5):
    """Zoekt het mailadres van deze winkel.

    Geeft altijd hetzelfde soort antwoord terug, ook als het niets vond, zodat
    de aanroeper niet hoeft te raden:

      {"adres": "info@winkel.nl" of None,
       "algemeen": True/False,
       "vandaan": waar wij het vandaan hebben,
       "alles": alle adressen die wij zagen,
       "reden": waarom er niets is, als er niets is}
    """
    url = scan_engine.normalize_url((webshop_url or "").strip())
    winkeldomein = _domein(url)
    leeg = {"adres": None, "algemeen": False, "vandaan": None, "alles": [], "reden": None}
    if not winkeldomein:
        return dict(leeg, reden="Geen geldig webadres.")

    alles, bekeken = [], 0
    for pad in [""] + PADEN:
        if bekeken >= max_paginas:
            break
        doel = urljoin(url + "/", pad.lstrip("/")) if pad else url
        try:
            antwoord = requests.get(doel, headers=scan_engine.HEADERS,
                                    timeout=timeout, allow_redirects=True)
        except Exception:
            continue
        if antwoord.status_code >= 400:
            continue
        bekeken += 1
        if scan_engine.lijkt_op_blokkadepagina(antwoord.text):
            continue
        alles.extend(_uit_pagina(antwoord.text, doel, winkeldomein))
        # Zodra wij een algemeen adres op het eigen domein hebben, is verder
        # zoeken zonde van de tijd en van de server van de winkel.
        if any(a["algemeen"] and a["eigen_domein"] for a in alles):
            break

    # Ontdubbelen met de volgorde erin, want de eerste vondst is de beste.
    uniek, gezien = [], set()
    for a in alles:
        if a["adres"] not in gezien:
            gezien.add(a["adres"])
            uniek.append(a)

    if not uniek:
        return dict(leeg, reden="Geen mailadres op de site gevonden.")

    # De volgorde van voorkeur: algemeen op het eigen domein, dan algemeen
    # elders, en anders niets. Een persoonlijk adres geven wij bewust niet
    # terug als keuze, alleen als vermelding in "alles" zodat jij het met de
    # hand kunt overnemen als je dat wilt.
    for eis in (lambda a: a["algemeen"] and a["eigen_domein"],
                lambda a: a["algemeen"]):
        for a in uniek:
            if eis(a):
                return {"adres": a["adres"], "algemeen": True, "vandaan": a["vandaan"],
                        "alles": [x["adres"] for x in uniek], "reden": None}

    return dict(leeg, alles=[x["adres"] for x in uniek],
                reden="Alleen persoonlijke adressen gevonden. Die slaan wij over.")
