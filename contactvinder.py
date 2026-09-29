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

import os
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import scan_engine

# Waar een webwinkel zijn adres neerzet. In deze volgorde, want op de
# contactpagina staat het adres waar hij post op wil, en in de voettekst van de
# homepage staat soms het adres van de bouwer.
# Hoeveel pagina's wij per winkel bekijken voor wij het opgeven.
#
# Dit stond op vijf, en dat is te weinig: de homepagina plus vier paden, terwijl
# het adres vaak pas op de zevende of achtste staat. Tien pagina's kost een paar
# seconden per winkel en geen cent, en levert winkels op waarvoor de meting
# anders voor niets betaald was.
MAX_PAGINAS = int(os.environ.get("CONTACT_MAX_PAGINAS", "10"))


# De pagina's waar een mailadres staat, op volgorde van hoe vaak het daar echt
# staat. Die volgorde doet ertoe, want wij stoppen zodra wij iets gevonden
# hebben.
#
# WAAROM DE JURIDISCHE PAGINA'S HOOG STAAN. Op 12 september stonden er 302
# winkels op "geen adres" tegenover 108 met een adres: van elke vier gevonden
# winkels vielen er drie af. De oorzaak was niet dat die winkels geen adres
# hebben, maar dat wij er maar vijf pagina's per winkel bekeken en de
# contactpagina vaak een formulier is zonder adres. Een webwinkel is wettelijk
# verplicht zijn contactgegevens te noemen, en in de praktijk staan die in het
# privacybeleid en de algemene voorwaarden. Die pagina's bestaan bijna altijd,
# ze zijn zelden een formulier, en er staat bijna altijd een echt mailadres in.
#
# Dit kost geen AI-geld, alleen wat paginabezoeken. Elke winkel die hierdoor
# wel een adres krijgt, is een winkel waarvoor wij de meting al betaald hebben
# en die anders weggegooid werd.
PADEN = [
    "/contact", "/pages/contact", "/contact-us", "/pages/contact-us",
    "/klantenservice", "/pages/klantenservice", "/nl/contact", "/contactez-nous",
    "/privacybeleid", "/privacy", "/privacy-policy", "/pages/privacybeleid",
    "/policies/privacy-policy", "/pages/privacy-policy",
    "/algemene-voorwaarden", "/voorwaarden", "/pages/algemene-voorwaarden",
    "/policies/terms-of-service", "/pages/terms-of-service",
    "/over-ons", "/pages/over-ons", "/pages/about-us", "/about", "/service",
    "/disclaimer", "/impressum",
    # Stap 128 deel 2 (28 september): de vaste beleidspagina's van Shopify. In
    # de EU moet een Shopify-winkel zijn contactgegevens tonen, en dat staat
    # op /policies/contact-information, ook als de winkel geen eigen
    # contactpagina met adres heeft. Retourbeleid en verzendbeleid noemen ook
    # vaak "mail ons op ...".
    "/policies/contact-information", "/policies/legal-notice",
    "/policies/refund-policy", "/policies/shipping-policy",
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
            "bonjour", "onthaal", "klanten", "webshop", "team",
            # 27 september erbij: gangbare algemene postbussen die wij misten.
            "hoi", "hi", "hey", "help", "helpdesk", "klantcontact", "customerservice",
            "customercare", "care", "bestelling", "order", "algemeen", "receptie",
            "inkoop", "store", "boutique", "atelier", "studio")

# Vrije mailboxen: bij een eenmanszaak is dit vaak het echte adres.
VRIJ = ("gmail.com", "hotmail.com", "hotmail.nl", "outlook.com", "outlook.nl", "live.nl",
        "live.com", "icloud.com", "me.com", "yahoo.com", "ziggo.nl", "kpnmail.nl",
        "planet.nl", "home.nl", "xs4all.nl", "telenet.be", "skynet.be", "proximus.be",
        "protonmail.com", "proton.me")

# Woorden in een link die naar een pagina met contactgegevens wijzen. De link
# die de winkel ZELF op zijn homepage zet is betrouwbaarder dan een pad dat wij
# raden (27 september: 1299 winkels zonder adres, vaak omdat het adres op
# /klantenservice/contact of /contact.html stond en niet op /contact).
LINKWOORDEN = ("contact", "klantenservice", "customer-service", "service", "privacy",
               "voorwaarden", "terms", "impressum", "colofon", "over-ons", "about",
               "overons", "faq", "veelgestelde", "help", "disclaimer")


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
    # Dezelfde naam met een andere extensie (winkel.nl met info@winkel.com) is
    # dezelfde winkel. Alleen de naam voor de eerste punt telt, en die moet
    # minstens vier tekens zijn: "ab.nl" en "ab.com" kunnen twee bedrijven zijn.
    naam_winkel = (winkeldomein or "").split(".")[0]
    if (not eigen_domein and len(naam_winkel) >= 4
            and gastheer.split(".")[0] == naam_winkel and gastheer.count(".") == 1):
        eigen_domein = True
    vrij = gastheer in VRIJ
    if not (eigen_domein or vrij):
        return None
    # Algemeen of persoonlijk. Alleen het deel voor de @ telt.
    #
    # ELK stuk moet algemeen zijn (of de naam van de winkel zelf), niet een
    # stuk. Tot 21 september was een algemeen stuk genoeg, en dan telde
    # jan.info@winkel.nl als algemeen adres: er zit "info" in. Dat is het adres
    # van Jan. In Belgie mag je daar niet ongevraagd heen mailen, en het
    # privacybeleid belooft dat wij nooit een adres met een naam erin gebruiken.
    kaal = [d for d in re.split(r"[.\-_+0-9]", gebruiker) if d]
    winkelnaam = (winkeldomein or "").split(".")[0]
    algemeen = (any(deel in ALGEMEEN for deel in kaal)
                and all(deel in ALGEMEEN or deel == winkelnaam for deel in kaal))
    return {"adres": adres, "algemeen": algemeen, "eigen_domein": eigen_domein}


def _uit_pagina(html, basis_url, winkeldomein):
    """Alle bruikbare adressen op één pagina, mailto-links eerst.

    Een mailto-link is betrouwbaarder dan een adres in de lopende tekst: die
    heeft iemand er expres neergezet om post op te krijgen."""
    gevonden = []
    try:
        soep = BeautifulSoup(html, "html.parser")
    except Exception:
        soep = None

    def neem(adres, vandaan):
        oordeel = _bruikbaar(adres, winkeldomein)
        if oordeel:
            oordeel["vandaan"] = vandaan
            gevonden.append(oordeel)

    if soep is not None:
        for link in soep.find_all("a", href=True):
            href = link["href"]
            if href.lower().startswith("mailto:"):
                from urllib.parse import unquote
                neem(unquote(href[7:].split("?")[0]), "mailto-link")
            # Door Cloudflare verborgen adres: /cdn-cgi/l/email-protection#<hex>
            if "email-protection#" in href:
                neem(_cloudflare(href.split("#", 1)[1]), "verborgen adres (Cloudflare)")
        for el in soep.find_all(attrs={"data-cfemail": True}):
            neem(_cloudflare(el.get("data-cfemail")), "verborgen adres (Cloudflare)")
        # Gestructureerde gegevens: "email" in de Organization of LocalBusiness.
        # Staat in een script, dus VOOR het weghalen van de scripts.
        for blok in soep.find_all("script", attrs={"type": "application/ld+json"}):
            for adres in re.findall(r'"email"\s*:\s*"(?:mailto:)?([^"]+)"', blok.string or ""):
                neem(adres, "gestructureerde gegevens")
        # Scripts en stijlen eruit, anders vissen wij adressen uit de code van
        # de winkelsoftware in plaats van van de pagina.
        for weg in soep(["script", "style", "noscript"]):
            weg.decompose()
        tekst = soep.get_text(" ")
    else:
        tekst = html

    for adres in ADRES.findall(tekst or ""):
        neem(adres, "tekst op de pagina")
    # Uitgeschreven tegen spam: "info [at] winkel.nl", "info(at)winkel(dot)nl",
    # "info @ winkel . nl". Het staat er, de winkel wil er post op.
    for adres in _ontwarren(tekst or ""):
        neem(adres, "uitgeschreven adres")
    return gevonden


_AT = r"\s*(?:\[\s*at\s*\]|\(\s*at\s*\)|\{\s*at\s*\}|\s+at\s+|\[\s*@\s*\]|\s@\s)\s*"
_DOT = r"\s*(?:\[\s*(?:dot|punt)\s*\]|\(\s*(?:dot|punt)\s*\)|\s+(?:dot|punt)\s+|\s\.\s|\.)\s*"
_VERSTOPT = re.compile(r"\b([A-Za-z0-9._%+\-]{2,40})" + _AT
                       + r"([A-Za-z0-9\-]{2,60})" + _DOT + r"([A-Za-z]{2,10})\b", re.I)


def _ontwarren(tekst):
    """Adressen die om spam te vermijden anders geschreven zijn."""
    uit = []
    for gebruiker, domein, extensie in _VERSTOPT.findall(tekst):
        if gebruiker.lower() in ("at", "dot", "punt"):
            continue
        uit.append(f"{gebruiker}@{domein}.{extensie}".lower())
    return uit


def _cloudflare(hexcode):
    """Een door Cloudflare verborgen adres terugvertalen.

    Cloudflare zet het adres als hex, met de eerste byte als sleutel waarmee de
    rest ge-xord is. Dat is geen geheim, het is alleen tegen domme spambots."""
    try:
        data = bytes.fromhex((hexcode or "").strip())
        sleutel = data[0]
        return "".join(chr(b ^ sleutel) for b in data[1:])
    except Exception:
        return ""


def _contactlinks(html, basis_url, winkeldomein, max_links=8):
    """De links op een pagina die naar contact, klantenservice, privacy en
    voorwaarden wijzen, op hetzelfde domein. De winkel wijst zelf de weg."""
    try:
        soep = BeautifulSoup(html, "html.parser")
    except Exception:
        return []
    uit = []
    for link in soep.find_all("a", href=True):
        href = link["href"].strip()
        if href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        volledig = urljoin(basis_url, href).split("#")[0]
        if _domein(volledig) != winkeldomein:
            continue
        waar = (href + " " + link.get_text(" ", strip=True)).lower()
        if any(w in waar for w in LINKWOORDEN) and volledig not in uit:
            uit.append(volledig)
        if len(uit) >= max_links:
            break
    # Contact en klantenservice eerst: daar staat het adres het vaakst.
    uit.sort(key=lambda u: 0 if ("contact" in u.lower() or "klantenservice" in u.lower()) else 1)
    return uit


# Stap 128 deel 3 (29 september): de sitemap als wegwijzer. Veel winkels zetten
# hun contact- of klantenservicepagina niet in het menu maar alleen in de
# voettekst van een script, of onder een eigen naam ("/service/vragen",
# "/pages/over-ons"). Die raden wij nooit, maar ze staan wel in sitemap.xml,
# die er is voor zoekmachines. Hoogstens twee extra verzoeken: de sitemap en,
# is dat een index, het deel met de gewone pagina's.
SITEMAPWOORDEN = ("contact", "klantenservice", "customer-service", "service", "impressum",
                  "over-ons", "about", "privacy", "retour", "returns", "voorwaarden",
                  "terms", "legal", "colofon", "faq", "veelgestelde")
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def _uit_sitemap(url, winkeldomein, timeout=8, max_links=4):
    def haal(adres):
        try:
            r = requests.get(adres, headers=scan_engine.HEADERS, timeout=timeout, allow_redirects=True)
            return r.text[:2_000_000] if r.status_code < 400 else ""
        except Exception:
            return ""

    tekst = haal(urljoin(url + "/", "sitemap.xml"))
    if not tekst:
        return []
    adressen = _LOC.findall(tekst)
    if "<sitemapindex" in tekst.lower():
        # Een index: het deel met de losse pagina's (Shopify: sitemap_pages_1.xml).
        deel = next((a for a in adressen if "page" in a.lower() or "pagina" in a.lower()), None)
        adressen = _LOC.findall(haal(deel)) if deel else []
    uit = []
    for a in adressen:
        a = a.replace("&amp;", "&")
        if _domein(a) != winkeldomein:
            continue
        pad = a.lower().split(winkeldomein, 1)[-1]
        if any(w in pad for w in SITEMAPWOORDEN) and a not in uit:
            uit.append(a)
    uit.sort(key=lambda u: 0 if ("contact" in u.lower() or "klantenservice" in u.lower()) else 1)
    return uit[:max_links]


# Stap 156 (28 september): een contactformulier herkennen. Veel kleine
# (Shopify-)winkels hebben geen info@ maar wel een formulier. Dat vullen wij
# NIET automatisch in: vaak zit er een captcha op, en een formulier dat een
# machine invult is precies het soort post waar een winkelier een hekel aan
# heeft. Wij onthouden alleen WAAR het formulier staat, en zetten een
# persoonlijk bericht klaar dat Nino er met de hand in plakt.
_FORM = re.compile(r"<form\b[^>]*>(.*?)</form>", re.I | re.S)


def is_shopify(html):
    """Draait deze winkel op Shopify? Aan vaste sporen in de broncode."""
    t = (html or "")[:400000]
    return "cdn.shopify.com" in t or "Shopify.theme" in t or "myshopify.com" in t


def heeft_formulier(html):
    """True als deze pagina een contactformulier heeft (een tekstvak plus een
    mailveld, of het vaste contactformulier van Shopify)."""
    for m in _FORM.finditer(html or ""):
        blok = m.group(0).lower()
        if 'value="contact"' in blok and "form_type" in blok:
            return True  # Shopify: <input type="hidden" name="form_type" value="contact">
        if "<textarea" in blok and ('type="email"' in blok or "email" in blok):
            if "search" not in blok[:200] and "newsletter" not in blok and "nieuwsbrief" not in blok:
                return True
    return False


def zoek_adres(webshop_url, timeout=12, max_paginas=None):
    """Zoekt het mailadres van deze winkel.

    Geeft altijd hetzelfde soort antwoord terug, ook als het niets vond, zodat
    de aanroeper niet hoeft te raden:

      {"adres": "info@winkel.nl" of None,
       "algemeen": True/False,
       "vandaan": waar wij het vandaan hebben,
       "alles": alle adressen die wij zagen,
       "reden": waarom er niets is, als er niets is}
    """
    max_paginas = MAX_PAGINAS if max_paginas is None else max_paginas
    url = scan_engine.normalize_url((webshop_url or "").strip())
    winkeldomein = _domein(url)
    leeg = {"adres": None, "algemeen": False, "vandaan": None, "alles": [], "reden": None,
            "formulier": None, "platform": None}
    if not winkeldomein:
        return dict(leeg, reden="Geen geldig webadres.")
    if scan_engine.is_intern_adres(url):
        return dict(leeg, reden="Dat is geen openbaar webadres.")

    alles, bekeken = [], 0
    formulier = None
    platform = None
    # Eerst de homepage, dan de links die de winkel zelf naar contact en
    # voorwaarden zet, en pas daarna de paden die wij raden.
    wachtrij = [url]
    gehad = set()
    while wachtrij and bekeken < max_paginas:
        doel = wachtrij.pop(0)
        sleutel = doel.rstrip("/").lower()
        if sleutel in gehad:
            continue
        gehad.add(sleutel)
        try:
            antwoord = requests.get(doel, headers=scan_engine.HEADERS,
                                    timeout=timeout, allow_redirects=True)
        except Exception:
            antwoord = None
        if antwoord is not None and antwoord.status_code < 400:
            bekeken += 1
            if not scan_engine.lijkt_op_blokkadepagina(antwoord.text):
                alles.extend(_uit_pagina(antwoord.text, doel, winkeldomein))
                if not formulier and heeft_formulier(antwoord.text):
                    formulier = doel
                if doel == url:
                    wachtrij.extend(_contactlinks(antwoord.text, url, winkeldomein))
        if doel == url:
            # Stap 128 deel 3: wat de sitemap aanwijst komt voor de geraden paden.
            wachtrij.extend(_uit_sitemap(url, winkeldomein))
        if doel == url:
            # Na de homepage (ook als die niet laadde): de geraden paden achteraan.
            paden = list(PADEN)
            # Een Shopify-winkel: eerst zijn vaste beleidspagina's, want daar
            # staat in de EU verplicht een contactadres (stap 128 deel 2).
            if antwoord is not None and is_shopify(antwoord.text):
                platform = "shopify"
                eerst = ["/policies/contact-information", "/policies/legal-notice"]
                shopify = eerst + [p for p in PADEN if p.startswith("/policies/") and p not in eerst]
                paden = shopify + [p for p in paden if p not in shopify]
            wachtrij.extend(urljoin(url + "/", p.lstrip("/")) for p in paden)
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

    leeg["formulier"] = formulier
    leeg["platform"] = platform
    if not uniek:
        return dict(leeg, reden="Geen mailadres op de site gevonden."
                    + (" Wel een contactformulier." if formulier else ""))

    # De volgorde van voorkeur: algemeen op het eigen domein, dan algemeen
    # elders, en anders niets. Een persoonlijk adres geven wij bewust niet
    # terug als keuze, alleen als vermelding in "alles" zodat jij het met de
    # hand kunt overnemen als je dat wilt.
    for eis in (lambda a: a["algemeen"] and a["eigen_domein"],
                lambda a: a["algemeen"]):
        for a in uniek:
            if eis(a):
                return {"adres": a["adres"], "algemeen": True, "vandaan": a["vandaan"],
                        "alles": [x["adres"] for x in uniek], "reden": None, "formulier": formulier,
                        "platform": platform}

    return dict(leeg, alles=[x["adres"] for x in uniek],
                reden="Alleen persoonlijke adressen gevonden. Die slaan wij over.")
