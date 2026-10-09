"""
Krillo - lokale ontwikkelserver / webserver.

Dit koppelt de landingspagina aan de echte scan-logica, zodat de
"Scan gratis"-knop een werkelijk resultaat teruggeeft, en aan de
Mollie-betaalkoppeling voor de audit en het abonnement.

Starten:
    pip install -r requirements.txt
    python3 app.py

Ga daarna naar http://127.0.0.1:5000 in je browser.
"""

import collections
import copy
import hashlib
import hmac
import json
import os
import re
import threading
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

from flask import (Flask, request, jsonify, render_template, redirect, Response, send_from_directory,
                   has_request_context, session, url_for)
from markupsafe import escape
import scan_engine
from scan_engine import run_scan
import payments
import emailing
import ai_content
import db
import artikelen
import koopvragen
import kosten
import paginataal
import winkelvinder
import metingen
import actieplan
import beoordeling
import bronnen
import controle
import verklaring
import waarschuwing
import zichtbaarheid
import benchmark
import markt
import shopify_app
import sitetaal
import commandocentrum
import markten
import shopify_werk
import toepasmodule
import shopify_billing
import benadering
import categorieen
import categoriemeting
import vraaglanden
import checktaal
import vraagkeuze
import klantbeeld
import klantwerk
import meldingen
import onderhoud
import opschonen

app = Flask(__name__)

# DE SITE MOET OPSTARTEN, OOK ALS DE DATABASE EVEN NIET MEEDOET.
#
# Dit stond hier kaal, en dat is de tweede helft van de storing van 18
# september: gaat het aanmaken van de tabellen mis, dan mislukt het IMPORTEREN
# van app.py, gunicorn komt niet omhoog en Render geeft 502 Bad Gateway op elke
# pagina. Ook op /robots.txt, die helemaal geen database nodig heeft.
#
# Nu start de site gewoon op. De pagina's die de database nodig hebben vangen
# hun eigen fouten al af, dus wat er dan overblijft is een site die het grootste
# deel nog doet in plaats van een site die weg is. Zodra de database terug is,
# maakt de eerstvolgende aanroep de tabellen alsnog aan.
try:
    db.init_db()
except Exception as e:
    print(f"init_db bij het opstarten mislukt, de site start toch op: {e}")


def get_base_url():
    """Geeft de basis-URL van de site, werkt zowel lokaal als op Render."""
    configured = os.environ.get("BASE_URL")
    if configured:
        return configured.rstrip("/")
    # Buiten een bezoek aan de site is er geen verzoek om het adres uit te
    # halen. Dat is niet zeldzaam: de ronde van de benadering, de wekelijkse
    # klantketen en de cron-taken draaien allemaal op een eigen draad. Zonder
    # deze terugval gooit Flask daar "Working outside of request context", en
    # dan mislukt elke mail die een link nodig heeft. Stil, want de fout wordt
    # verderop opgevangen en de winkel blijft gewoon op zijn oude stand staan.
    if has_request_context():
        return request.url_root.rstrip("/")
    return "https://krilloai.com"


# ---------------------------------------------------------------------------
# DE VERHUIZING NAAR KRILLOAI.COM, 18 september 2026
#
# Waarom wij verhuisd zijn staat in krillo-domeinbesluit-18-09-2026: kort
# gezegd is een .nl voor Google een landdomein en kun je dat signaal niet
# uitzetten, en Krillo gaat naar het buitenland.
#
# Krillo.nl blijft bestaan en wordt nooit opgezegd. Hij stuurt alles door met
# een 301, want dat is het enige antwoord waarmee een zoekmachine begrijpt dat
# een pagina VERHUISD is en niet tijdelijk ergens anders staat. Bij een 302
# blijft het oude adres in de zoekresultaten staan en begint de nieuwe bij nul.
#
# LET OP: /.well-known/ gaat er BEWUST niet doorheen. Daar komen de controles
# binnen waarmee een beveiligingscertificaat vernieuwd wordt. Sturen wij die
# door, dan kan het certificaat van krillo.nl op een dag niet vernieuwd worden,
# en dan werkt juist de doorverwijzing zelf niet meer over https. Dat is een
# fout die pas maanden later opvalt.
# ---------------------------------------------------------------------------
OUDE_DOMEINEN = {"krillo.nl", "www.krillo.nl"}


@app.before_request
def stuur_oud_domein_door():
    host = (request.host or "").split(":")[0].lower()
    if host not in OUDE_DOMEINEN:
        return None
    if request.path.startswith("/.well-known/"):
        return None
    # robots.txt WORDT OOK NIET DOORGESTUURD. Toegevoegd op 21 september.
    #
    # De adreswijziging in Search Console faalde met "kan de pagina niet
    # ophalen", voor de homepage en voor elke voorbeeldpagina, terwijl de 301
    # zelf gewoon werkte. De oorzaak: Google haalt van een domein altijd EERST
    # robots.txt op, en eist dat die op het oude domein direct antwoordt met een
    # 200 of een 404. Kreeg hij een doorverwijzing, dan behandelde hij het hele
    # oude domein als onbereikbaar.
    #
    # Dus hier geen doorverwijzing maar gewoon de robots.txt. Die staat alles
    # toe, en dat is precies wat moet: Google moet de oude adressen kunnen
    # ophalen om de 301's erachter te zien. Blokkeer je ze, dan ziet hij de
    # verhuizing nooit.
    if request.path == "/robots.txt":
        return None
    # WEBHOOKS WORDEN OOK NIET DOORGESTUURD (25 september). Shopify stuurde
    # de verplichte privacy-webhooks nog naar www.krillo.nl, kreeg een 301 en
    # keurde de app af: een webhook moet zelf antwoorden, en bij een foute
    # handtekening met een 401. Een 301 volgt Shopify niet. Mollie ook niet.
    # Dus een webhook wordt op het oude domein gewoon hier afgehandeld.
    if request.path.startswith("/shopify/webhooks/") or request.path.startswith("/webhooks/"):
        return None
    # DE NOODREM.
    #
    # Staat BASE_URL nog op het OUDE domein, dan zou deze functie krillo.nl
    # naar krillo.nl sturen. Dat is geen foutmelding maar een lus: de browser
    # blijft doorsturen tot hij het opgeeft, en de site is weg. Precies het
    # soort storing van vanochtend, en dan door onszelf veroorzaakt.
    #
    # Dat kan echt gebeuren: de code wordt geupload voordat BASE_URL in Render
    # omgezet is, en tussen die twee momenten zit een deploy. Daarom hangt dit
    # niet af van de juiste volgorde, maar controleert de code het zelf. Staat
    # het doel op een oud domein, dan sturen wij niemand door en blijft de site
    # gewoon werken op het oude adres tot de instelling klopt.
    doelhost = get_base_url().split("//")[-1].split("/")[0].split(":")[0].lower()
    if doelhost in OUDE_DOMEINEN or not doelhost:
        return None
    # Het pad en de zoekopdracht blijven staan. Iemand die op een ranglijst
    # uitkomt via een oude link hoort op diezelfde ranglijst te landen en niet
    # op de homepage: een doorverwijzing naar de voorpagina telt voor Google
    # als een verdwenen pagina.
    doel = get_base_url().rstrip("/") + request.path
    if request.query_string:
        doel += "?" + request.query_string.decode("utf-8", "ignore")
    return redirect(doel, code=301)


def _labelnaam(sleutel, taal="en"):
    import vraaglabels
    return vraaglabels.naam(sleutel, taal)


def logo_bestaat(naam):
    """Of er een officieel merklogo staat in static/logos (8 oktober, versie 10).

    Waarom: Nino wil de echte logo's van ChatGPT, Gemini, Shopify en de rest,
    want dat geeft vertrouwen. Een deel kon ik uit Simple Icons halen; OpenAI
    en xAI staan daar niet in. Die moet Nino zelf van hun merkpagina halen. Tot
    dan toont het sjabloon een neutraal vakje in plaats van een kapot plaatje,
    en zodra het bestand er staat verschijnt het logo vanzelf."""
    import re as _re
    if not _re.fullmatch(r"[a-z0-9-]+", naam or ""):
        return False
    return os.path.exists(os.path.join(app.root_path, "static", "logos", naam + ".svg"))


# De assistenten (8 oktober, versie 10). "gemeten" zijn de assistenten die we
# nu echt vragen; de rest komt eraan en een klant kan zich ervoor aanmelden in
# het dashboard. Staat hier op EEN plek, zodat homepage en dashboard nooit
# verschillende dingen zeggen.
ASSISTENTEN = [
    {"sleutel": "chatgpt", "naam": "ChatGPT", "logo": "chatgpt", "gemeten": True},
    {"sleutel": "gemini", "naam": "Gemini", "logo": "gemini", "gemeten": True},
    {"sleutel": "perplexity", "naam": "Perplexity", "logo": "perplexity", "gemeten": False},
    {"sleutel": "google_ai", "naam": "Google AI Mode", "logo": "google", "gemeten": False},
    {"sleutel": "claude", "naam": "Claude", "logo": "claude", "gemeten": False},
    {"sleutel": "grok", "naam": "Grok", "logo": "grok", "gemeten": False},
]
# Ook als globale waarde in Jinja: sommige pagina's en tests renderen een
# sjabloon buiten een verzoek om, en dan draait de context processor niet.
app.jinja_env.globals.update(logo_bestaat=logo_bestaat, assistenten=ASSISTENTEN)


@app.context_processor
def zet_basis_url_klaar():
    """Maakt basis_url in ELK sjabloon beschikbaar.

    Waarom dit er is: bij de verhuizing bleek dat de canonical van de homepage,
    de og:url van elke pagina en de adressen in de gestructureerde gegevens
    hardgecodeerd op www.krillo.nl stonden. Een canonical die naar het oude
    domein wijst vertelt Google dat de echte pagina daar staat, en dan doet de
    hele verhuizing niets. Nu komt het adres overal uit BASE_URL, zodat een
    volgende verhuizing een instelling is en geen zoektocht."""
    import markten
    # En de landen die de index nu meet, uit markten.py: nooit meer "Nederland
    # en Belgie" in een sjabloon zelf (28 september, we gaan groeien).
    return {"basis_url": get_base_url().rstrip("/"), "index_landen_en": markten.index_landen_en(), "index_landen_nl": markten.index_landen_nl(),
            "meting_zin_en": markten.meting_zin_en(),
            "index_landen_kaal_en": markten.index_landen_kaal_en(),
            "vraagtaal_en": markten.vraagtaal_en,
            "labelnaam": _labelnaam,
            "logo_bestaat": logo_bestaat,
            "assistenten": ASSISTENTEN,
            "wachtlijst_landen": {c: n for c, n in markten.WACHTLIJST_LANDEN.items() if not markten.in_index(c)}}


# Vanaf hoeveel gescande webshops wij dat aantal op de site zetten.
MINIMUM_VOOR_TELLER = int(os.environ.get("MINIMUM_VOOR_TELLER", "50"))


# ---------------------------------------------------------------------------
# Bezoekers tellen
#
# Waarom dit hier staat en niet bij Google Analytics: dat kost een cookiebanner,
# het vertraagt elke pagina met een script van een derde partij, en de cijfers
# zijn er niet beter van. Wij hebben al een database. Eén regel per bezoek is
# genoeg om te zien of er iemand komt.
#
# Waarom het staat waar het staat, boven de eerste route: deze functie schrijft
# iets weg bij een GET, en dat is precies de fout die de site op 11 september
# heeft platgelegd. Door hem boven alle routes te zetten hoort hij bij geen
# enkele route, en blijft `tests/test_geenschrijfbijladen.py` scherp op wat er
# in de routes zelf gebeurt. Het verschil met die fout van toen: dit is één
# INSERT met een vaste kostprijs, geen lus over duizenden rijen.
#
# Wat er NIET vastgelegd wordt: geen IP-adres, geen koekje, geen naam. Daarmee
# is er niets te herleiden tot een persoon en is er geen cookiemelding nodig.
# ---------------------------------------------------------------------------

# Paden die niets zeggen over bezoek: plaatjes en stijlbestanden, je eigen
# beheerpagina's, de machinekamer, en alles wat een computer ophaalt in plaats
# van een mens.
#
# /wakker staat er bij sinds de eerste dag dat de teller aanstond. Die wordt elk
# uur door onze eigen taak opgehaald om Render wakker te houden, en dat leverde
# meteen 16 van de 27 "bezoeken" op, allemaal van dezelfde niet bestaande
# bezoeker. Een teller die voor de helft uit je eigen machines bestaat is erger
# dan geen teller, want je gaat conclusies trekken uit ruis.
# /embed: de ranglijst in het venster op de site van een ander. Dat is geen
# bezoek aan onze site, en daar hoort ook geen script in.
BEZOEK_NEGEREN = ("/static", "/admin", "/api", "/cron", "/wakker", "/shopify", "/embed", "/v/",
                  "/webhook", "/favicon", "/robots.txt", "/sitemap", "/healthz",
                  "/.well-known")

# Wat zich meldt als bot, spin, crawler of voorvertoning is geen bezoeker. Zonder
# deze regel is de helft van je cijfers Google en LinkedIn die je eigen link
# ophalen, en dan lijkt het druk terwijl er niemand is.
BEZOEK_ROBOTS = ("bot", "spider", "crawl", "slurp", "preview", "fetch",
                 "monitor", "pingdom", "headless", "python-requests", "curl",
                 "wget", "lighthouse", "uptime")


def _bezoeker_kenmerk():
    """Een korte code die één bezoeker één dag lang herkenbaar maakt.

    Waarom dit nodig is: zonder zoiets kun je alleen paginaweergaven tellen. Tien
    weergaven van één persoon zien er dan uit als tien bezoekers, en juist dat
    tweede getal is het getal waar je iets aan hebt.

    Hoe het werkt: het IP-adres en de browsernaam gaan samen met de datum en
    onze eigen sleutel door een eenrichtingsfunctie. Wat er overblijft is zestien
    tekens waar niets uit terug te rekenen is, en dat morgen anders is voor
    dezelfde persoon. Het IP-adres zelf wordt nergens opgeslagen.

    Dit is dezelfde aanpak die privacyvriendelijke tellers als Plausible
    gebruiken, en het is de reden dat er geen cookiebanner op de site hoeft."""
    try:
        adres = (request.headers.get("X-Forwarded-For", "")
                 .split(",")[0].strip() or request.remote_addr or "")
        browser = request.headers.get("User-Agent", "")[:200]
        zout = (os.environ.get("SESSIE_SLEUTEL")
                or os.environ.get("ADMIN_KEY") or "krillo")
        ruw = f"{datetime.utcnow():%Y-%m-%d}|{zout}|{adres}|{browser}"
        return hashlib.sha256(ruw.encode("utf-8")).hexdigest()[:16]
    except Exception:
        return None


def _apparaat():
    """Telefoon, tablet of computer. Grof, en dat is genoeg.

    Het enige waar dit voor dient: als driekwart van je bezoek van een telefoon
    komt en de pagina leest daar slecht, dan is dat je eerste probleem."""
    ua = (request.headers.get("User-Agent", "") or "").lower()
    if "ipad" in ua or "tablet" in ua:
        return "tablet"
    if "mobi" in ua or "android" in ua or "iphone" in ua:
        return "telefoon"
    return "computer"


# ---------------------------------------------------------------------------
# TRAGE PAGINA'S METEN (29 september). Nino: "alle pagina's laden lang". Wij
# zagen de logboeken van Render niet, dus we wisten niet WELKE pagina traag was.
# Nu houdt de app zelf bij welke verzoeken langer dan TRAAG_SECONDEN duurden:
# in het geheugen (de laatste 200), op /admin/traag en in het ochtendbericht.
# ---------------------------------------------------------------------------
TRAAG_SECONDEN = float(os.environ.get("TRAAG_SECONDEN", "2"))
_GESTART_OP = time.time()
_traag = collections.deque(maxlen=200)
_verzoeken = {"totaal": 0, "traag": 0}


@app.before_request
def _start_klok():
    from flask import g
    g._krillo_start = time.time()
    _warm_op_na_start()


@app.after_request
def _meet_duur(antwoord):
    try:
        from flask import g
        duur = time.time() - getattr(g, "_krillo_start", time.time())
        # De klantblik (eigen controle) telt niet mee bij de trage pagina's.
        if not request.path.startswith("/static") and \
                not (request.headers.get("User-Agent") or "").startswith("KrilloKlantblik"):
            _verzoeken["totaal"] += 1
            if duur >= TRAAG_SECONDEN:
                _verzoeken["traag"] += 1
                tel = getattr(g, "_db_tel", None) or {"vragen": 0, "ms": 0.0, "los": 0}
                _traag.append({"pad": request.path, "sec": round(duur, 1),
                               "op": datetime.now().strftime("%d-%m %H:%M"),
                               "vragen": tel["vragen"], "db_sec": round(tel["ms"] / 1000, 1),
                               "los": tel["los"],
                               "na_start": round(time.time() - _GESTART_OP) < 120})
                print(f"TRAAG: {request.path} duurde {duur:.1f} s "
                      f"({tel['vragen']} databasevragen, {tel['ms'] / 1000:.1f} s database, "
                      f"{tel['los']} losse verbindingen)")
    except Exception:
        pass
    return antwoord


def traag_overzicht():
    """Per pad: hoe vaak traag en de langste duur. Voor /admin/traag en het ochtendbericht."""
    per = {}
    for t in list(_traag):
        p = per.setdefault(t["pad"], {"pad": t["pad"], "keer": 0, "max": 0.0, "laatst": t["op"],
                                      "vragen": 0, "db_sec": 0.0, "los": 0, "na_start": 0})
        p["keer"] += 1
        if t["sec"] >= p["max"]:
            # De cijfers van het langste verzoek: daar zit de oorzaak.
            p["vragen"] = t.get("vragen", 0)
            p["db_sec"] = t.get("db_sec", 0.0)
            p["los"] = t.get("los", 0)
        p["max"] = max(p["max"], t["sec"])
        p["na_start"] += 1 if t.get("na_start") else 0
        p["laatst"] = t["op"]
    return {"totaal": _verzoeken["totaal"], "traag": _verzoeken["traag"],
            "paden": sorted(per.values(), key=lambda p: -p["max"])}


# Na een deploy zijn alle bewaarde ranglijsten leeg, en betaalde de eerste
# bezoeker van /news, /sitemap.xml of een winkelpagina de hele rekening
# (tientallen zware vragen aan de database). Nu warmt een achtergrondtaak ze
# een keer op, direct na het eerste verzoek.
_opgewarmd = {"gestart": False}


def _warm_op_na_start():
    if _opgewarmd["gestart"] or app.testing or not _thuis_onthouden_aan():
        return
    _opgewarmd["gestart"] = True
    _start_wachtklok()

    def _warm():
        try:
            # 30 september: eerst de homepage, want daar komt bijna iedereen
            # binnen. Zo wacht de eerste bezoeker na een herstart niet zelf op
            # het uitrekenen (Nino zag 17 seconden op /).
            try:
                _thuisgegevens()
            except Exception as e:
                print(f"Homepage opwarmen mislukt: {e}")
            time.sleep(2)
            for rij in db.landen_in_index():
                land = rij["land"]
                for c in db.categorieen_per_land(land):
                    _ranglijst_bewaard(c["categorie"], land)
                    # Rustig aan (29 september). Zonder pauze legde het opwarmen
                    # beslag op de verbindingen met de database precies op het
                    # moment dat de eerste echte bezoekers binnenkwamen, en die
                    # wachtten dan 14 seconden op de homepage.
                    time.sleep(0.3)
            sitemap_inhoud()
            # De voorbeeldpagina achter "Product" alvast opbouwen, zodat de
            # eerste bezoeker na een upload niet op het opbouwen wacht.
            # 30 september: alle tabbladen van het voorbeeld, niet alleen het
            # overzicht. Anders wachtte wie op "Ranking" klikte alsnog.
            import dashboardpaginas as dp
            for pad in [""] + [p for p in dp.PAD_NAAR_PAGINA if p]:
                with app.test_request_context("/demo" + (f"/{pad}" if pad else "")):
                    demo = _maak_demo(pad)
                    if demo:
                        _demo_bewaard[(pad, "")] = (time.time(), demo)
                time.sleep(0.3)
        except Exception as e:
            print(f"Opwarmen mislukt: {e}")
    threading.Thread(target=_warm, daemon=True).start()


def _ranglijst_bewaard(slug, land, limiet=1000):
    """De ranglijst uit het geheugen (10 minuten), zoals de categoriepagina hem ook leest."""
    return _bewaard(("ranglijst", slug, land), db.ranglijst_per_land, slug, land, 1000)


@app.after_request
def _tel_bezoek(antwoord):
    """Schrijft één regel weg per bekeken pagina.

    Alles hierin staat in een try, en bij twijfel doet hij niets. Een teller mag
    nooit de reden zijn dat iemand de site niet ziet."""
    try:
        if request.method != "GET":
            return antwoord
        # Alleen echte pagina's. Een plaatje, een JSON-antwoord of een
        # doorverwijzing is geen bezoek.
        if antwoord.status_code != 200:
            return antwoord
        if "text/html" not in (antwoord.content_type or ""):
            return antwoord
        pad = request.path or "/"
        if any(pad.startswith(n) for n in BEZOEK_NEGEREN):
            return antwoord
        ua = (request.headers.get("User-Agent", "") or "").lower()
        if not ua or any(r in ua for r in BEZOEK_ROBOTS):
            return antwoord
        # De gegevens NU uit het verzoek halen, want de achtergrondtaak
        # hieronder draait buiten het verzoek en kan er dan niet meer bij.
        gegevens = {"herkomst": _herkomst(), "bezoeker": _bezoeker_kenmerk(),
                    "apparaat": _apparaat()}

        # Het wegschrijven gebeurt op de achtergrond, sinds 19 september.
        # Daarvoor wachtte elke bezoeker tot deze regel bij Neon in Frankfurt
        # stond voordat hij zijn pagina kreeg, en als Neon net sliep kon dat
        # seconden duren. Een teller mag nooit de reden zijn dat iemand wacht.
        # Bij het testen wel meteen, want de test kijkt direct daarna in de tabel.
        def _schrijf():
            try:
                db.noteer_bezoek(pad, **gegevens)
            except Exception as fout:
                print(f"Bezoek wegschrijven mislukt: {fout}")

        if app.testing:
            _schrijf()
        else:
            threading.Thread(target=_schrijf, daemon=True).start()

        # 29 september: een klein stukje script dat pas iets meldt als de
        # bezoeker scrolt, tikt, typt of de muis beweegt. Mailbeveiliging die
        # de links in onze mails controleert doet dat niet, een mens wel. Zo
        # zie je op /admin/bezoek hoeveel van de "bezoekers" echt mensen zijn.
        if not antwoord.direct_passthrough and not antwoord.is_streamed:
            html = antwoord.get_data(as_text=True)
            plek = html.rfind("</body>")
            if plek != -1:
                script = MENS_SCRIPT
                # Op de uitkomst uit de koude mail: het kenmerk mee, zodat de
                # verkoopagent weet dat er een mens keek en geen controlerobot.
                delen = pad.split("/")
                if (len(delen) >= 3 and delen[1] == "uitkomst"
                        and re.fullmatch(r"[A-Za-z0-9_-]{6,80}", delen[2] or "")):
                    script = script.replace("'/api/mens'", f"'/api/mens?t={delen[2]}'")
                antwoord.set_data(html[:plek] + script + html[plek:])
    except Exception as e:
        print(f"Bezoek tellen mislukt: {e}")
    return antwoord


# 8 oktober (Nino: "40 mensen naar de kassa en evenveel echte mensen als
# doorklikken, dat klopt niet"): virusscanners van mailprogramma's openen elke
# link, draaien het script en scrollen de pagina met een programma (scroll- en
# mousemove-gebeurtenissen). Die telden als mens. Nu alleen wat een hand doet:
# klikken of tikken, een toets, of het wieltje van een echte muis.
MENS_SCRIPT = ("<script>(function(){var s=0;function m(){if(s)return;s=1;try{"
               "if(navigator.sendBeacon){navigator.sendBeacon('/api/mens')}"
               "else{fetch('/api/mens',{method:'POST',keepalive:true})}}catch(e){}}"
               "['pointerdown','keydown','touchstart','wheel'].forEach("
               "function(e){addEventListener(e,m,{once:true,passive:true})})})();</script>")


@app.route("/api/mens", methods=["POST"])
def api_mens():
    """Zie MENS_SCRIPT. Zelfde dagcode als de bezoekersteller, niets meer."""
    ua = (request.headers.get("User-Agent", "") or "").lower()
    if ua and not any(r in ua for r in BEZOEK_ROBOTS):
        kenmerk = _bezoeker_kenmerk()
        token = (request.args.get("t") or "")[:80]
        if token:
            try:
                winkel = db.winkel_bij_benchmark_token(token)
                if winkel:
                    db.noteer_uitkomst_mens(winkel)
            except Exception as e:
                print(f"Mens op de uitkomst mislukt: {e}")
        if app.testing:
            db.noteer_mens(kenmerk)
        else:
            threading.Thread(target=db.noteer_mens, args=(kenmerk,), daemon=True).start()
    return ("", 204)


# ---------------------------------------------------------------------------
# DE HOMEPAGE ONTHOUDT ZIJN CIJFERS, 19 september 2026
#
# Wat er misging: Google Search Console kon krilloai.com niet verifieren, met
# de melding "time-out bij de verbinding met uw server". Nino zag hetzelfde als
# bezoeker: tien seconden voordat de homepage er stond.
#
# De oorzaak: elk bezoek aan de homepage stelde 24 vragen aan de database. Bij
# het testen merk je dat niet, want daar staat de database op dezelfde machine
# en duren 24 vragen samen 12 milliseconden. Live staat de database bij Neon in
# Frankfurt en is elke vraag een reis over het internet. Bovendien valt Neon op
# een klein plan na een paar minuten stilte in slaap, en de eerste bezoeker
# daarna moet hem wakker maken. Vierentwintig keer.
#
# Terwijl die cijfers maar EEN KEER PER NACHT veranderen, na de meting.
#
# Wat er nu gebeurt: de cijfers worden onthouden. Een bezoeker krijgt altijd
# meteen de onthouden versie. Is die ouder dan THUIS_VERS_SECONDEN, dan wordt hij
# op de achtergrond ververst, zonder dat iemand daarop wacht. Alleen de allereerste
# bezoeker na een herstart wacht een keer op de database.
#
# Waarom niet gewoon tien minuten onthouden en dan opnieuw opvragen: dan is om
# de tien minuten een bezoeker de klos, en dat is precies de bezoeker die Neon
# net in slaap heeft zien vallen. Zo wacht er nooit iemand op het verversen.
# ---------------------------------------------------------------------------
THUIS_VERS_SECONDEN = int(os.environ.get("THUIS_VERS_SECONDEN", "600"))

# Bij het testen staat het onthouden uit. Tests vullen de database en kijken
# daarna meteen of de homepage het laat zien; met een geheugen ertussen zien ze
# de stand van een vorige test. Een test die het geheugen zelf wil bewaken zet
# dit op True (zie tests/test_snelheid.py).
THUIS_ONTHOUDEN = None  # None: aan, behalve bij het testen

_thuis = {"waarde": None, "op": 0.0, "bezig": False}
_thuis_slot = threading.Lock()


def _thuis_onthouden_aan():
    if THUIS_ONTHOUDEN is not None:
        return THUIS_ONTHOUDEN
    return not app.testing


def _ververs_thuis():
    """Rekent de homepage opnieuw uit en onthoudt het resultaat."""
    try:
        waarde = _bereken_thuis()
        op = time.time()
        # Kwam er geen index uit, omdat de database even weg was of omdat er
        # nog niets gemeten is, dan niet tien minuten lang die lege versie
        # laten zien. Over een minuut opnieuw proberen.
        if not waarde.get("index"):
            op = op - THUIS_VERS_SECONDEN + 60
        _thuis.update(waarde=waarde, op=op)
        return waarde
    finally:
        _thuis["bezig"] = False


def _thuisgegevens():
    if not _thuis_onthouden_aan():
        return _bereken_thuis()
    if _thuis["waarde"] is None:
        # De allereerste keer na een herstart is er niets om te laten zien,
        # dan wacht deze ene bezoeker wel.
        with _thuis_slot:
            if _thuis["waarde"] is None:
                _thuis["bezig"] = True
                return _ververs_thuis()
        return _thuis["waarde"]
    if time.time() - _thuis["op"] > THUIS_VERS_SECONDEN:
        with _thuis_slot:
            starten = not _thuis["bezig"]
            if starten:
                _thuis["bezig"] = True
        if starten:
            threading.Thread(target=_ververs_thuis, daemon=True).start()
    return _thuis["waarde"]


# Hetzelfde onthouden, maar dan per gegeven, voor de indexpagina's. Die stelden
# 10 tot 11 databasevragen per bezoek, om dezelfde reden als de homepage: de
# cijfers veranderen maar een keer per nacht. Onthouden per GEGEVEN en niet per
# pagina, want de pagina hangt ook af van de taal en het voorgekozen land.
# Elke aanroeper krijgt een kopie, zodat een route die een lijst sorteert of
# een veld toevoegt niet het onthouden origineel verandert.
_bewaard_opslag = {}
_bewaard_slot = threading.Lock()
BEWAARD_MAX = int(os.environ.get("BEWAARD_MAX", "500"))


def _bewaard(sleutel, functie, *args):
    if not _thuis_onthouden_aan():
        return functie(*args)
    with _bewaard_slot:
        # 1 oktober (geheugen): nooit onbeperkt. Elke winkelpagina en elke kaart
        # die Google opvraagt kreeg een eigen vak, en die bleven allemaal staan.
        if sleutel not in _bewaard_opslag and len(_bewaard_opslag) >= BEWAARD_MAX:
            grens = time.time() - THUIS_VERS_SECONDEN
            for k in [k for k, v in _bewaard_opslag.items() if v["op"] < grens and not v["bezig"]]:
                _bewaard_opslag.pop(k, None)
            if len(_bewaard_opslag) >= BEWAARD_MAX:
                _bewaard_opslag.clear()
        vak = _bewaard_opslag.setdefault(
            sleutel, {"waarde": None, "op": 0.0, "bezig": False, "gevuld": False})
    if not vak["gevuld"]:
        waarde = functie(*args)
        # Leeg is verdacht (database even weg): over een minuut opnieuw.
        op = time.time() if waarde else time.time() - THUIS_VERS_SECONDEN + 60
        vak.update(waarde=waarde, op=op, gevuld=True)
        return copy.deepcopy(waarde)
    if time.time() - vak["op"] > THUIS_VERS_SECONDEN:
        with _bewaard_slot:
            starten = not vak["bezig"]
            if starten:
                vak["bezig"] = True
        if starten:
            def _ververs():
                try:
                    w = functie(*args)
                    op = time.time() if w else time.time() - THUIS_VERS_SECONDEN + 60
                    vak.update(waarde=w, op=op)
                except Exception as e:
                    print(f"Verversen van {sleutel} mislukt: {e}")
                finally:
                    vak["bezig"] = False
            threading.Thread(target=_ververs, daemon=True).start()
    return copy.deepcopy(vak["waarde"])


_laatste_indexcijfers = {}


@app.route("/")
def home():
    g = _thuisgegevens()
    return render_template("index.html",
                           gescand=g["gescand"],
                           index=g["index"],
                           eigen_cijfer=g["eigen_cijfer"])


def _bereken_thuis():
    """Alles wat de homepage uit de database nodig heeft. Wordt onthouden, zie
    de uitleg bij THUIS_VERS_SECONDEN hierboven."""
    # Het aantal gescande webshops als sociaal bewijs. Onder een ondergrens
    # laten wij het weg: "wij scanden al 3 webshops" is slechter dan niets, want
    # het zegt precies hoe klein je bent op de plek waar je vertrouwen wilt
    # wekken. Mislukt het tellen, dan komt er 0 uit en valt het vanzelf weg.
    try:
        gescand = db.tel_gescande_webshops()
    except Exception as e:
        print(f"Teller ophalen mislukt: {e}")
        gescand = 0
    # De index op de homepage. Dit is het bewijs: geen belofte dat wij meten,
    # maar een echte ranglijst die iemand kan aanklikken. Alles komt uit de
    # database, dus er staat nooit een verouderd getal.
    #
    # Valt het ophalen om, dan blijft de homepage gewoon staan zonder dit blok.
    # Een homepage die niet laadt kost klanten; een homepage zonder proefblokje
    # niet.
    index = {}
    try:
        landen = db.landen_in_index()
        cijfers = db.index_cijfers()
        # Lukt het even niet (28 september: het blok "The index today" liet
        # alleen nog het percentage zien), dan de laatste goede cijfers.
        if cijfers and cijfers.get("categorieen"):
            _laatste_indexcijfers.update(cijfers)
        elif _laatste_indexcijfers:
            print("Indexcijfers leeg, laatste goede cijfers gebruikt.")
            cijfers = dict(_laatste_indexcijfers)
        # 7 oktober: dezelfde telling als op /index, alleen wat er openbaar
        # staat (niet elke categorie die ooit gemeten is).
        try:
            openbaar = db.openbare_categorieen(MINIMUM_PER_LAND)
            if openbaar:
                cijfers = dict(cijfers or {})
                cijfers["categorieen"] = len({r["categorie"] for r in openbaar})
                cijfers["winkels"] = sum(int(r.get("winkels") or 0) for r in openbaar)
            # 8 oktober: elke winkel een keer (zie db.index_unieke_winkels), zodat
            # "stores ranked" en "stores in the index" hetzelfde getal zijn.
            uniek = db.index_unieke_winkels(MINIMUM_PER_LAND)
            if uniek and uniek.get("gemeten"):
                cijfers = dict(cijfers or {})
                cijfers["winkels"] = uniek["gemeten"]
        except Exception as e:
            print(f"Openbare telling voor de homepage mislukt: {e}")
        voorbeeldland = landen[0]["land"] if landen else None
        rijen = (db.categorieen_per_land(voorbeeldland, MINIMUM_PER_LAND)
                 if voorbeeldland else [])
        top = None
        if rijen:
            beste = max(rijen, key=lambda r: r["winkels"])
            # DE HELE RANGLIJST OPHALEN, MAAR ER VIER LATEN ZIEN.
            #
            # Dit stond op limiet=4, en daarmee klopten twee getallen niet. Het
            # aantal winkels dat bij geen enkele vraag genoemd werd, werd geteld
            # binnen die vier, dus daar kon nooit meer dan vier uitkomen terwijl
            # het er in werkelijkheid twintig zijn. En het kaartje eronder zei
            # "1 van de 4+" terwijl er vierentwintig winkels in die categorie
            # staan. Een getal dat kleiner is dan de waarheid is net zo fout als
            # een getal dat groter is: het is precies de meting die wij verkopen.
            lijst = db.ranglijst_per_land(beste["categorie"], voorbeeldland, limiet=500)
            alle = lijst.get("rijen", [])
            genoemd = [r for r in alle if (r["genoemd"] or 0) > 0]
            top = {
                "categorie": beste["categorie"],
                "naam": categorieen.naam_van(beste["categorie"]),
                "land": voorbeeldland,
                "landnaam": sitetaal.landnaam(voorbeeldland, "nl"),
                "telbaar": lijst.get("telbaar") or 0,
                # Vier rijen op het scherm. Meer is een ranglijst en geen
                # voorproefje, en daar is de indexpagina zelf voor.
                "rijen": genoemd[:4],
                "winkels": len(alle),
                "niet_genoemd": len(alle) - len(genoemd),
            }
        # HOMEPAGE VERSIE 9 (30 september). De kaart "The index today" heeft
        # tabs: de drie grootste categorieen, elk met hun top 7, de beweging
        # sinds de vorige meting, en per winkel genoemd en aangeraden. Plus het
        # kwadrant (genoemd tegen aangeraden) en een echte koopvraag voor het
        # typende kaartje. Alles uit de database: geen voorbeeldnamen op de
        # echte site. Is er iets niet, dan valt dat stukje weg.
        tabs = []
        for rij in sorted(rijen, key=lambda r: -r["winkels"])[:3]:
            try:
                l3 = (lijst if top and rij["categorie"] == top["categorie"]
                      else db.ranglijst_per_land(rij["categorie"], voorbeeldland, limiet=500))
            except Exception as e:
                print(f"Tab {rij['categorie']} voor de homepage overslaan: {e}")
                continue
            tabs.append(_thuis_tab(rij["categorie"], voorbeeldland, l3))
        tabs = [t for t in tabs if t and t["rijen"]]
        # De koersbalk bovenaan de homepage. Per categorie de winkel die op
        # dit moment bovenaan staat, met de dag waarop dat gemeten is. Dit is
        # het eerste dat een bezoeker ziet, dus het moet uit de database komen
        # en niet uit een sjabloon: een verzonnen regel in een koersbalk is
        # precies de overpromise waar wij anderen op controleren.
        ticker = []
        for rij in rijen[:3]:
            kop = db.ranglijst_per_land(rij["categorie"], voorbeeldland, limiet=1)
            eerste = (kop.get("rijen") or [None])[0]
            ticker.append({
                "categorie": categorieen.naam_van(rij["categorie"]),
                "land": voorbeeldland,
                "slug": rij["categorie"],
                "leider": (eerste.get("naam") or eerste.get("webshop_url", "")
                           .replace("https://", "")) if eerste else None,
                "genoemd": eerste.get("genoemd") if eerste else None,
                "telbaar": kop.get("telbaar") if eerste else None,
            })
        index = {"cijfers": cijfers, "landen": landen, "top": top,
                 "ticker": ticker, "tabs": tabs,
                 "gemeten_op": (top.get("rijen")[0].get("gemeten_op")
                                if top and top.get("rijen") else None),
                 "binnenkort": [c for c in sitetaal.LANDEN
                                if c not in {r["land"] for r in landen}]}
    except Exception as e:
        print(f"Index op homepage overslaan: {e}")

    return {"gescand": gescand if gescand >= MINIMUM_VOOR_TELLER else None,
            "index": index,
            "eigen_cijfer": _eigen_benchmarkcijfer()}


def _assistenten(modellen):
    """Modelnamen (gpt-5.6-terra) als de namen die een winkelier kent (ChatGPT).
    30 september: op de categoriepagina stonden de ruwe modelnamen, en dat is
    jargon voor een webshop-eigenaar."""
    import dashboardpaginas as dp
    return sorted({dp.assistent_naam(m) for m in (modellen or [])})


def _kale_naam(r):
    naam = r.get("naam")
    if not naam or str(naam).startswith("http"):
        naam = (r.get("webshop_url") or "").replace("https://", "").replace("http://", "").replace("www.", "").rstrip("/")
    return naam


def _thuis_tab(categorie, land, lijst):
    """Een tab van de kaart "The index today" op de homepage (versie 9).

    WAAROM ZO: de top 7 met genoemd, aangeraden en de beweging sinds de vorige
    meting. De beweging komt uit vorige_positie (dezelfde bron als de
    indexpagina), dus de pijltjes op de homepage en op /index zeggen hetzelfde.
    De grootste stijger krijgt het zwevende kaartje "moved up"; is er geen
    stijger, dan is er ook geen kaartje. Het kwadrant gebruikt de winkels die
    minstens een keer genoemd zijn (een stip op nul zegt niets)."""
    alle = (lijst or {}).get("rijen") or []
    telbaar = (lijst or {}).get("telbaar") or 0
    genoemd = [r for r in alle if (r.get("genoemd") or 0) > 0]
    if not genoemd or not telbaar:
        return None

    def beweging(r):
        vorige, nu = r.get("vorige_positie"), r.get("positie")
        if not vorige or not nu:
            return ""
        return f"▲{vorige - nu}" if vorige > nu else (f"▼{nu - vorige}" if nu > vorige else "=")

    rijen = [{"positie": r.get("positie"), "naam": _kale_naam(r), "genoemd": r.get("genoemd") or 0,
              "aanbevolen": r.get("aanbevolen") or 0, "vorige": r.get("vorige_positie"),
              "beweging": beweging(r), "breedte": int(round(100 * (r.get("genoemd") or 0) / telbaar))}
             for r in genoemd[:7]]
    stijgers = [r for r in genoemd if r.get("vorige_positie") and r.get("positie")
                and r["vorige_positie"] - r["positie"] >= 2]
    stijger = None
    if stijgers:
        s = max(stijgers, key=lambda r: r["vorige_positie"] - r["positie"])
        stijger = {"naam": _kale_naam(s), "plekken": s["vorige_positie"] - s["positie"],
                   "positie": s["positie"]}
    punten = [{"naam": _kale_naam(r), "positie": r.get("positie"),
               "x": int(round(100 * (r.get("genoemd") or 0) / telbaar)),
               "y": int(round(100 * (r.get("aanbevolen") or 0) / telbaar)),
               "genoemd": r.get("genoemd") or 0, "aanbevolen": r.get("aanbevolen") or 0}
              for r in genoemd[:10]]
    vraag = None
    try:
        vragen = db.categorie_vragen(categorie) or []
        if vragen:
            vraag = vragen[0].get("vraag")
    except Exception as e:
        print(f"Voorbeeldvraag voor de homepage overslaan: {e}")
    return {"categorie": categorie, "naam": categorieen.naam_en(categorie), "land": land,
            "telbaar": telbaar, "winkels": len(alle), "niet_genoemd": len(alle) - len(genoemd),
            "rijen": rijen, "stijger": stijger, "beweging": any(r["beweging"] for r in rijen),
            "punten": punten, "vraag": vraag}


def _eigen_benchmarkcijfer():
    """Het eigen cijfer over Nederlandse webshops, of None.

    De probleemsectie op de homepage leunt op een Amerikaans onderzoek naar
    21.000 vermeldingen. Dat is een goed cijfer maar het is niet van ons, het
    gaat over merken en niet over Nederlandse webshops, en het is precies het
    soort verwijzing waar de doelgroep overheen leest.

    Zodra wij genoeg winkels zelf gemeten hebben is er een beter cijfer: hoeveel
    Nederlandse webshops bij koopvragen NOOIT genoemd worden. Dat is van ons, het
    is controleerbaar, en het is de enige reden om over Krillo te schrijven die
    geen verkooppraatje is.

    Onder de ondergrens geven wij None terug en blijft het Amerikaanse cijfer
    staan. Een eigen cijfer over negen winkels is geen onderzoek, en het zo
    noemen is precies de overpromising waar Krillo van weg wil blijven. Dit gaat
    dus vanzelf aan zodra het klopt, zonder dat er iemand aan te pas komt."""
    # Sinds 28 september uit de hele index (alle landen), niet uit de oude
    # proefmetingen van 209 Nederlandse winkels.
    # 8 oktober: dezelfde telling als "stores ranked" op de homepage.
    cijfers = db.index_unieke_winkels(MINIMUM_PER_LAND) or db.index_nooit_genoemd()
    if not cijfers or not cijfers.get("gemeten"):
        try:
            cijfers = benchmark.tel_op(db.benchmark_regels())
            cijfers = {"gemeten": cijfers.get("gemeten"), "nooit": cijfers.get("nooit_genoemd")}
        except Exception as e:
            print(f"Eigen benchmarkcijfer ophalen mislukt: {e}")
            return None
    gemeten = cijfers.get("gemeten") or 0
    if gemeten < MINIMUM_WINKELS_VOOR_VERGELIJKING:
        return None
    nooit = cijfers.get("nooit") or 0
    if not nooit:
        return None
    return {"gemeten": gemeten, "nooit": nooit,
            "deel": round(nooit * 100 / gemeten)}


@app.route("/privacy")
def privacybeleid():
    return render_template("privacybeleid.html")


# Engelse adressen (25 september). De site is Engels, maar deze pagina's
# heetten nog /privacybeleid en /veelgestelde-vragen, en zo stonden ze ook in
# de Shopify-listing. De oude adressen blijven werken met een 301, zodat links
# in verstuurde mails en in Google niet breken.
@app.route("/privacybeleid")
def privacybeleid_oud():
    return redirect("/privacy", code=301)


@app.route("/veelgestelde-vragen")
def veelgestelde_vragen_oud():
    return redirect("/faq", code=301)


# Stap 204 en 114 (30 september): de laatste Nederlandse adressen onder Engelse
# pagina's. Zelfde aanpak als hierboven: nieuw Engels adres, het oude blijft met
# een 301 werken (links in verstuurde mails, in Google en bij andere sites).
OUDE_ADRESSEN = {"/zo-meten-we": "/how-we-measure", "/over-ons": "/about", "/voorwaarden": "/terms",
                 "/herroepen": "/withdrawal", "/artikelen": "/articles"}


def _oud_adres(nieuw):
    def doorsturen():
        doel = nieuw + (("?" + request.query_string.decode()) if request.query_string else "")
        return redirect(doel, code=301)
    return doorsturen


for _oud, _nieuw in OUDE_ADRESSEN.items():
    app.add_url_rule(_oud, "oud_" + _oud.strip("/").replace("-", "_"), _oud_adres(_nieuw))


@app.route("/artikelen/<slug>")
def artikel_oud(slug):
    return redirect(f"/articles/{slug}", code=301)


@app.route("/terms")
def voorwaarden():
    return render_template("voorwaarden.html")


@app.route("/faq")
def veelgestelde_vragen():
    return render_template("faq.html")


@app.route("/how-we-measure")
def zo_meten_we():
    return render_template("zo-meten-we.html")


@app.route("/proof")
def bewijs():
    """7 oktober: "genoemd worden is nog geen verkoop". Hoe je het zelf ziet."""
    # De uitkomst van alle klanten samen, pas vanaf drie winkels (aiverkeer.samen).
    try:
        import aiverkeer
        samen = aiverkeer.samen()
    except Exception as e:
        print(f"Bewijs samen mislukt: {e}")
        samen = None
    return render_template("proof.html", samen=samen)


@app.route("/about")
def over_ons():
    return render_template("over-ons.html")


@app.route("/withdrawal")
def herroepen_pagina():
    return render_template("herroepen.html")


@app.route("/api/herroepen", methods=["POST"])
def api_herroepen():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    webshop_url = scan_engine.normalize_url((data.get("url") or "").strip())
    toelichting = (data.get("toelichting") or "").strip()
    if not email:
        return jsonify({"error": "Fill in the email address you ordered with."}), 400

    nummer = db.leg_herroeping_vast(email, webshop_url, toelichting)
    if nummer is None:
        # Niets vastgelegd. Dan NIET bevestigen dat we het ontvangen hebben:
        # dit is een wettelijk verzoek met een termijn van veertien dagen, en
        # een bevestiging op iets dat nergens staat is het ergste antwoord.
        print(f"HERROEPING NIET VASTGELEGD voor {email} ({webshop_url}). "
              f"Toelichting: {toelichting}")
        return jsonify({
            "error": "Saving did not work. Email your withdrawal to "
                     "hello@krilloai.com and we will handle it by hand. "
                     "Your right of withdrawal stays valid."
        }), 500
    emailing.send_herroeping_bevestiging(email, nummer, webshop_url)

    # HET ABONNEMENT STOPPEN (27 september, bij de controle voor de eerste
    # klant). Hier werd de herroeping vastgelegd en bevestigd, maar het
    # abonnement bij Mollie liep gewoon door: de klant kreeg "we regelen het"
    # en een maand later toch een afschrijving. Nu zoeken we zijn abonnement
    # (op het winkeladres, of anders via zijn mailadres) en zeggen het meteen op.
    gestopt = "niet gevonden"
    try:
        if not webshop_url:
            gevonden = db.klant_bij_email(email) or {}
            webshop_url = gevonden.get("webshop_url") or ""
        if webshop_url:
            abonnement = payments.zoek_abonnement(webshop_url)
            if abonnement:
                uit = payments.zeg_abonnement_op(abonnement["customer_id"],
                                                 abonnement["subscription_id"])
                gestopt = "fout: " + str(uit.get("error")) if "error" in uit else "opgezegd"
            else:
                gestopt = "geen actief abonnement bij Mollie"
            if gestopt in ("opgezegd", "geen actief abonnement bij Mollie"):
                db.zet_klant_opgezegd(webshop_url)
    except Exception as e:
        gestopt = f"fout: {e}"
        print(f"Herroeping: abonnement stoppen mislukt voor {email}: {e}")

    beheerder = (os.environ.get("BEHEERDER_EMAIL") or os.environ.get("BEHEER_EMAIL")
                 or os.environ.get("SMTP_REPLY_TO") or "").strip()
    if beheerder:
        emailing.send_herroeping_melding(beheerder, email, webshop_url, toelichting, nummer)
    actie = ("Het abonnement is bij Mollie opgezegd." if gestopt == "opgezegd"
             else f"<b>Let op: het abonnement kon niet automatisch gestopt worden ({gestopt}).</b> "
                  "Ga in Mollie naar Klanten, zoek dit adres en zeg het abonnement op.")
    _meld_aan_beheer(
        "Herroeping: geld terugbetalen",
        f"{email} ({webshop_url or 'winkel onbekend'}) heeft herroepen, kenmerk {nummer}. {actie} "
        "<b>Actie nodig:</b> betaal binnen 14 dagen terug in Mollie (Betalingen, zoek dit "
        "adres, open de betaling, Terugbetalen). Heeft de klant bij het bestellen "
        "toegestemd dat we meteen begonnen, dan mag je het deel voor de dagen tot nu inhouden.")
    return jsonify({"ok": True})


@app.route("/api/naar-fix/<klant_token>", methods=["POST"])
def api_naar_fix(klant_token):
    """Stap 130: de knop "Switch to Fix" op de pagina Plan (tot 1 oktober een mailto)."""
    klant = db.get_klant(klant_token)
    if klant is None:
        return jsonify({"error": "This page is no longer valid."}), 404
    if klant.get("opgezegd_op"):
        return jsonify({"error": "Your plan is cancelled. Email hello@krilloai.com and we set up Fix for you."}), 400
    url = klant["webshop_url"]
    uit = payments.wissel_naar(url, "fix")
    if "error" in uit:
        return jsonify(uit), 400
    db.zet_klant_pakket(url, "fix")
    # Net als bij een nieuwe Fix-klant: op de werklijst en de toegangsmail.
    platform = (db.get_winkelprofiel(url) or {}).get("platform")
    db.start_uitvoering(f"wissel:{url}:{datetime.now(timezone.utc).date().isoformat()}", url, klant["email"], platform)
    try:
        emailing.send_uitvoering_welkom(klant["email"], url, platform,
                                        f"{get_base_url().rstrip('/')}/mijn/{klant_token}")
    except Exception as e:
        print(f"Toegangsmail na wissel naar Fix mislukt voor {url}: {e}")
    _meld_aan_beheer("Van Watch naar Fix",
                     f"{url} ({klant['email']}) stapte zelf over naar Fix. Vanaf de volgende betaling "
                     f"({uit.get('volgende_betaling') or 'onbekend'}) EUR {uit.get('bedrag')}. De toegangsmail is verstuurd; "
                     f"de opdracht staat op de werklijst.")
    return jsonify({"ok": True, "volgende_betaling": uit.get("volgende_betaling"), "bedrag": uit.get("bedrag")})


@app.route("/mijn/<klant_token>/weekmail/uit", methods=["GET", "POST"])
def weekmail_uit(klant_token):
    """De weekmail uitzetten (2 oktober). GET toont alleen een knop, POST zet
    hem uit: mailbeveiliging opent elke link in een mail, en die zou anders de
    weekmail voor de klant uitzetten zonder dat hij iets deed."""
    import weekmail
    klant = db.get_klant(klant_token)
    if not klant:
        return render_template("fout.html", titel="This link no longer works",
                               bericht="Open your dashboard and try again."), 404
    if request.method == "POST":
        aan = request.form.get("aan") == "ja"
        weekmail.zet_uit(klant["webshop_url"], uit=not aan)
        tekst = ("The weekly email is on again." if aan else
                 "Done. You no longer get the weekly email. Your dashboard and the monthly report stay as they are.")
        knop = ""
    else:
        uit = weekmail.staat_uit(klant["webshop_url"])
        tekst = ("The weekly email is off." if uit else
                 "You get a short email every week with how often AI named your store.")
        knop = (f"<form method='post'><input type='hidden' name='aan' value='{'ja' if uit else ''}'>"
                f"<button style='padding:10px 16px;font-size:15px'>{'Turn it on' if uit else 'Turn it off'}"
                f"</button></form>")
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Weekly email | Krillo</title><body style='font-family:Arial,sans-serif;max-width:560px;"
            f"margin:60px auto;padding:0 16px;line-height:1.6'><h1 style='font-size:22px'>Weekly email</h1>"
            f"<p>{escape(tekst)}</p>{knop}<p><a href='/mijn/{escape(klant_token)}'>Back to your dashboard</a></p>")


@app.route("/api/pixel", methods=["POST", "OPTIONS"])
def api_pixel():
    """Stap 304: meldingen van de Krillo-pixel op de site van een klant.

    Komt van een ander domein (de winkel), dus open voor elke herkomst. Neemt
    alleen aan wat pixel.noteer goedkeurt: een bekende sleutel, sessie of
    order, een redelijk bedrag. Altijd 204: een winkel mag nooit een fout zien
    of trager worden door Krillo."""
    if request.method == "POST":
        try:
            import pixel
            import gratistools
            ruw = request.get_data(cache=False, as_text=True)[:2000]
            d = json.loads(ruw) if ruw else {}
            # Rem per bezoeker (zelfde als de gratis tools): een bezoeker doet
            # hooguit een sessie en een bestelling, meer is misbruik.
            if isinstance(d, dict) and gratistools.mag_nu("pixel:" + (request.remote_addr or "?")):
                pixel.noteer(d.get("k"), d.get("t"), bron=d.get("b"), bedrag=d.get("v"),
                             valuta=d.get("c"), order_id=d.get("o"))
        except Exception as e:
            print(f"Pixelmelding mislukt: {e}")
    antwoord = app.response_class(status=204)
    antwoord.headers["Access-Control-Allow-Origin"] = "*"
    antwoord.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    antwoord.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return antwoord


@app.route("/mijn/<klant_token>/pixelcheck")
def pixelcheck(klant_token):
    """De knop "Check my pixel" (8 oktober, Nino). Het dashboard opent de winkel
    met ?utm_source=krillo-check en vraagt hier elke paar seconden of er sinds
    het klikken iets van de pixel binnenkwam. Alleen ja of nee, geen gegevens."""
    import pixel
    klant = db.get_klant(klant_token)
    if not klant:
        return jsonify({"fout": "onbekend"}), 404
    try:
        vanaf = datetime.fromtimestamp(float(request.args.get("sinds") or 0), tz=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        vanaf = datetime.now(timezone.utc) - timedelta(minutes=5)
    # Nooit verder terug dan een uur: dan zegt de knop iets over nu.
    vanaf = max(vanaf, datetime.now(timezone.utc) - timedelta(hours=1))
    uit = pixel.sinds(klant["webshop_url"], vanaf)
    antwoord = jsonify(uit)
    antwoord.headers["Cache-Control"] = "no-store"
    return antwoord


@app.route("/mijn/<klant_token>/aiverkeer", methods=["POST"])
def aiverkeer_bewaren(klant_token):
    """De klant zet zijn AI-bezoek, bestellingen en omzet van een maand in het
    dashboard (7 oktober, zie aiverkeer.py). Daarna terug naar het overzicht."""
    import aiverkeer
    klant = db.get_klant(klant_token)
    if not klant:
        return render_template("fout.html", titel="This link no longer works",
                               bericht="Open your dashboard and try again."), 404
    aiverkeer.bewaar(klant["webshop_url"], request.form.get("maand"), request.form.get("bezoek"),
                     request.form.get("orders"), request.form.get("omzet"))
    return redirect(f"/mijn/{klant_token}#aiverkeer", code=303)


CATEGORIEVERZOEK = "categorieverzoek:"


@app.route("/mijn/<klant_token>/categorie", methods=["POST"])
def categorie_kiezen(klant_token):
    """De klant kiest zelf zijn categorie en land (8 oktober).

    Nino testte met een nieuwe winkel en zag "We have not placed your store in a
    category yet. That happens within a night". Wie net betaald heeft, wacht
    geen nacht. Het indelen gaat meestal vanzelf, maar lukt het niet (een
    testwinkel, een winkel achter een wachtwoord, een te dunne pagina), dan
    weet de eigenaar zelf in twee klikken wat hij verkoopt. Daarna meteen:
    is de categorie al gemeten, dan plaatsen uit de antwoorden van deze maand
    (kost niets); zo niet, dan voor in de klantmeetrij."""
    klant = db.get_klant(klant_token)
    if not klant:
        return render_template("fout.html", titel="This link no longer works",
                               bericht="Open your dashboard and try again."), 404
    slug = (request.form.get("categorie") or "").strip()
    land = (request.form.get("land") or "nl").strip().lower()
    terug = request.form.get("terug") or ""
    terug = terug if terug in ("", "ranking", "questions") else ""
    basis = f"/mijn/{klant_token}" + (f"/{terug}" if terug else "")
    # 8 oktober (Nino: "als iemands categorie er niet in staat, wat dan?").
    # "My category is not here": bewaren wat hij verkoopt en Nino een mail
    # sturen. Nino kiest dan in het dashboard van de klant een bestaande
    # categorie, of laat Claude een nieuwe toevoegen. Geen belofte van een
    # meting morgen: de klant hoort binnen een werkdag wat er gebeurt.
    if slug == "anders":
        wat = (request.form.get("wat") or "").strip()[:200]
        if len(wat) < 3:
            return redirect(basis + "?categorie=fout", code=303)
        db.zet_instelling(CATEGORIEVERZOEK + scan_engine.normalize_url(klant["webshop_url"]),
                          json.dumps({"wat": wat, "land": land, "op": datetime.now(timezone.utc).isoformat()}))
        _meld_aan_beheer("Klant mist zijn categorie",
                         f"{klant['webshop_url']} schrijft: \"{wat}\" ({land.upper()}).\n\n"
                         f"Kies voor hem een bestaande categorie in zijn dashboard: "
                         f"{get_base_url().rstrip('/')}/mijn/{klant_token} (stap 3, Not right? Choose it yourself), "
                         f"of vraag Claude een nieuwe categorie toe te voegen. De klant ziet dat hij binnen "
                         f"een werkdag hoort wat er gebeurt.")
        return redirect(basis + "?categorie=verzoek", code=303)
    if slug not in categorieen.GELDIG or slug in categorieen.NIET_MEETBAAR or land not in ("nl", "be"):
        return redirect(basis + "?categorie=fout", code=303)
    url = scan_engine.normalize_url(klant["webshop_url"])
    db.zet_klant_op_lijst(url, land=land)
    db.zet_categorie(url, slug)
    db.zet_land(url, land)
    # Een eerdere mislukte poging mag deze nieuwe niet tegenhouden.
    _plaatsen_bezig.pop(url, None)
    _plaatsen_mislukt.pop(url, None)
    db.zet_instelling(CATEGORIEVERZOEK + url, "")
    if any(db.laatste_afgeronde_ronde(c) for c in categorieen.familie(slug)):
        _plaats_in_ranglijst(url)
    # 8 oktober (Nino koos Winter sports en bleef in Sports and fitness): is zijn
    # EIGEN categorie nog nooit gemeten, dan die voor in de rij, ook als de
    # bovencategorie wel gemeten is. Tot dan ziet hij de bovencategorie, met
    # een melding erbij (eigen_categorie in het dashboard).
    if not db.laatste_afgeronde_ronde(slug):
        zet_in_klantmeetrij(slug)
    return redirect(basis + "?categorie=gekozen", code=303)


# Stap-tellers van de kassa (7 oktober). 36 mensen gingen naar de prijzen en
# niemand betaalde, maar wij wisten niet WAAR ze afhaakten: openden ze het
# venster niet, vulden ze het niet in, of haakten ze af bij de bank? Elke stap
# telt nu als bezoek aan een vast pad, en verschijnt zo vanzelf op /admin/bezoek.
KASSA_STAPPEN = {"venster_watch", "venster_fix", "auto_watch", "auto_fix", "verstuurd_watch", "verstuurd_fix",
                 "fout_watch", "fout_fix", "naar_bank_watch", "naar_bank_fix"}


@app.route("/api/stap/<naam>", methods=["POST"])
def api_kassastap(naam):
    ua = (request.headers.get("User-Agent", "") or "").lower()
    if naam in KASSA_STAPPEN and ua and not any(r in ua for r in BEZOEK_ROBOTS):
        db.noteer_bezoek("/stap/" + naam, bezoeker=_bezoeker_kenmerk())
    return ("", 204)


@app.route("/api/opzeggen/<klant_token>", methods=["POST"])
def api_opzeggen(klant_token):
    klant = db.get_klant(klant_token)
    if klant is None:
        return jsonify({"error": "This page is no longer valid."}), 404

    abonnement = payments.zoek_abonnement(klant["webshop_url"])
    if abonnement is None:
        return jsonify({"error": "We could not find an active plan. Email hello@krilloai.com and we will sort it out."}), 400

    resultaat = payments.zeg_abonnement_op(abonnement["customer_id"], abonnement["subscription_id"])
    if "error" in resultaat:
        return jsonify(resultaat), 400

    # De veertien dagen (24 september). De site belooft: binnen veertien dagen
    # na de eerste betaling opzeggen is die maand terug. Dat terugbetalen doe
    # jij in Mollie; deze melding zegt of het moet, zodat het niet vergeten wordt.
    dagen = None
    try:
        begon = klant.get("aangemaakt_op")
        if begon:
            dagen = (datetime.now(timezone.utc) - begon).days
    except Exception:
        dagen = None
    # Binnen veertien dagen krijgt hij zijn geld terug, dan stopt de toegang nu.
    # Daarna betaalde hij de lopende maand, en die houdt hij (voorwaarden).
    tot = None
    # Stap 167: tijdens de gratis proef. Er is niets betaald (alleen de cent), dus
    # niets terug; hij houdt toegang tot het einde van zijn gratis dagen.
    gratis_tot = klant.get("gratis_tot")
    if gratis_tot and gratis_tot >= datetime.now(timezone.utc).date():
        tot = datetime.combine(gratis_tot, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
        db.zet_klant_opgezegd(klant["webshop_url"], tot=tot)
        emailing.send_opzegging_bevestiging(klant["email"], klant["webshop_url"], tot=tot, terug=False,
                                            proef_tot=gratis_tot,
                                            dashboard_url=f"{get_base_url().rstrip('/')}/mijn/{klant_token}")
        _meld_aan_beheer("Gratis proef gestopt",
                         f"{klant['email']} stopte de gratis proef van {klant['webshop_url']}. "
                         f"Er is niets betaald en niets terug te betalen.")
        return jsonify({"ok": True})
    # 8 oktober (Nino, akkoord): geld terug binnen veertien dagen alleen nog bij
    # Fix. Watch heeft de veertien gratis dagen als garantie; daarna betaalde
    # hij de lopende maand en die houdt hij gewoon.
    # Onbekend pakket: de belofte houden (zo was het voor iedereen).
    fix_klant = (klant.get("pakket") or "fix").lower() != "watch"
    if dagen is not None and dagen <= 14 and not fix_klant:
        dagen = 15
    if dagen is not None and dagen > 14:
        # Een jaarklant houdt toegang tot het eind van zijn betaalde jaar.
        jaar = (abonnement.get("periode") == "jaar") or (klant.get("periode") == "jaar")
        # 8 oktober (controle): na een gratis proef begint het betalen op dag 15,
        # niet bij de aanmelding. Anders verloor een ex-proefklant twee weken.
        betaald_vanaf = klant.get("aangemaakt_op")
        if gratis_tot:
            betaald_vanaf = datetime.combine(gratis_tot, datetime.min.time(), tzinfo=timezone.utc) + timedelta(days=1)
        tot = _einde_betaalde_maand(betaald_vanaf, maanden=12 if jaar else 1)
        db.zet_klant_opgezegd(klant["webshop_url"], tot=tot)
    else:
        db.zet_klant_opgezegd(klant["webshop_url"])
    emailing.send_opzegging_bevestiging(klant["email"], klant["webshop_url"], tot=tot,
                                        terug=(dagen is not None and dagen <= 14),
                                        dashboard_url=f"{get_base_url().rstrip('/')}/mijn/{klant_token}")
    if dagen is not None and dagen <= 14:
        terug = (f"<p><b>Actie nodig: geld terug.</b> Deze klant is {dagen} dagen klant, dus "
                 f"binnen de veertien dagen. Ga in Mollie naar Betalingen, zoek {klant['email']}, "
                 f"open de eerste betaling en klik op Terugbetalen.</p>")
    else:
        terug = "<p>Buiten de veertien dagen: niets terug te betalen.</p>"
    _meld_aan_beheer("Opzegging bij Krillo",
                     f"{klant['email']} heeft {klant['webshop_url']} opgezegd. {terug}")
    return jsonify({"ok": True})


@app.route("/changelog")
def changelog_pagina():
    """Stap 182: wat er nieuw is (changelog.py)."""
    import changelog
    return render_template("changelog.html", maanden=changelog.regels())


@app.route("/articles")
def artikelen_overzicht():
    return render_template("artikelen.html", artikelen=artikelen.alle())


@app.route("/articles/<slug>")
def artikel_pagina(slug):
    artikel = artikelen.get_artikel(slug)
    if artikel is None:
        return render_template("fout.html"), 404
    andere = [a for a in artikelen.alle() if a["slug"] != slug][:3]
    return render_template("artikel.html", artikel=artikel, andere=andere)


@app.errorhandler(404)
def pagina_niet_gevonden(e):
    # 1 oktober (sitecontrole): /mijn/<link>/ met een schuine streep erachter gaf
    # een foutpagina, terwijl /mijn/<link> gewoon bestaat. Iemand die de link
    # overtypt of een mailprogramma dat er een / achter zet, landt nu goed.
    pad = request.path
    if len(pad) > 1 and pad.endswith("/") and request.method == "GET":
        kaal = pad.rstrip("/")
        try:
            app.url_map.bind("").match(kaal, method="GET")
            return redirect(kaal + (("?" + request.query_string.decode()) if request.query_string else ""),
                            code=301)
        except Exception:
            pass
    return render_template("fout.html"), 404


@app.route("/favicon.ico")
def favicon_ico():
    """Browsers en chatapps vragen /favicon.ico op zonder naar de pagina te
    kijken. Die gaf de oude rode stip (24 september), dus hier het nieuwe
    icoon, met een week cache zodat een volgende wijziging snel doorkomt."""
    return send_from_directory(os.path.join(app.root_path, "static"), "favicon.ico",
                               mimetype="image/x-icon", max_age=7 * 24 * 3600)


@app.route("/robots.txt")
def robots_txt():
    # LET OP: één groep per User-agent. Twee keer "User-agent: *" in hetzelfde
    # bestand is precies de fout waar Krillo bij klanten op controleert: de
    # meeste robots pakken dan alleen de eerste groep en negeren de tweede, en
    # dan staan de privépagina's alsnog open. Nieuwe verboden horen dus hier
    # bij de eerste groep en niet onderaan in een tweede.
    # Het adres van de sitemap komt uit BASE_URL en staat hier niet vast. Bij
    # de verhuizing naar krilloai.com bleek dit een van de plekken waar het
    # oude domein nog hardgecodeerd stond, en een robots.txt die naar de
    # sitemap van een ander domein wijst is precies het soort stille fout waar
    # wij bij klanten op controleren.
    # /get-my-link staat hier bewust NIET meer in. Die pagina heeft een
    # noindex-tag, maar Google leest die tag alleen als hij de pagina mag
    # ophalen. Met een Disallow erbij meldde Search Console "geindexeerd,
    # hoewel geblokkeerd door robots.txt": het adres kwam in Google zonder dat
    # Google de noindex kon zien. Zonder Disallow ziet hij de tag en haalt hij
    # de pagina er zelf uit.
    basis = get_base_url().rstrip("/")
    inhoud = f"""User-agent: *
Allow: /
Disallow: /uitkomst/
Disallow: /monitoring/
Disallow: /rapport/
Disallow: /mijn/
Disallow: /admin/

User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: OAI-SearchBot
Allow: /

Sitemap: {basis}/sitemap.xml
"""
    return Response(inhoud, mimetype="text/plain")


@app.route("/tools")
@app.route("/tools/<slug>")
def gratis_tools(slug=None):
    """Stap 162: gratis losse tools, een pagina per tool."""
    import gratistools
    if slug and slug not in gratistools.TOOLS:
        return redirect("/tools", code=302)
    return render_template("tools.html", tools=gratistools.TOOLS, slug=slug,
                           tool=gratistools.TOOLS.get(slug) if slug else None)


@app.route("/chatgpt-visibility-tracker")
@app.route("/gemini-visibility-tracker")
@app.route("/shopify-ai-visibility")
def trackerpagina():
    """Stap 183 en 156 deel 3: een pagina per assistent en een voor Shopify,
    met de gratis check en echte cijfers uit de index (zie trackerpaginas.py)."""
    import trackerpaginas
    slug = request.path.strip("/")
    return render_template("tracker.html", slug=slug, pagina=trackerpaginas.PAGINAS[slug],
                           vragen=trackerpaginas.VRAGEN[slug], cijfers=trackerpaginas.cijferzinnen(slug),
                           andere={s: p["titel"] for s, p in trackerpaginas.PAGINAS.items() if s != slug},
                           prijs_watch=trackerpaginas._prijs("watch"),
                           faq_ld=[{"@type": "Question", "name": v,
                                    "acceptedAnswer": {"@type": "Answer", "text": t}}
                                   for v, t in trackerpaginas.VRAGEN[slug]])


@app.route("/api/tools/<slug>", methods=["POST"])
def gratis_tool_api(slug):
    """De check zelf. Geen AI-geld, alleen de pagina's van de winkel lezen, met
    een rem per bezoeker zodat niemand ons als gratis robot gebruikt."""
    import gratistools
    if slug not in gratistools.TOOLS:
        return jsonify({"fout": "Unknown tool."}), 404
    if not gratistools.mag_nu(_bezoeker_kenmerk() or request.remote_addr or "?"):
        return jsonify({"fout": "That is a lot of checks in a short time. Try again in ten minutes."}), 429
    url = ((request.get_json(silent=True) or {}).get("url") or "").strip()[:300]
    if slug == "ai-crawler-check":
        uit = gratistools.crawler_check(url)
    elif slug == "supplier-text-check":
        uit = gratistools.leverancierstekst_check(url)
    elif slug == "product-data-check":
        uit = gratistools.productdata_check(url)
    else:
        uit = gratistools.index_check(url)
    gratistools.bewaar_gebruik(slug, url, uit.get("oordeel") or ("fout" if uit.get("fout") else "ok"))
    return jsonify(uit), (400 if uit.get("fout") else 200)


@app.route("/compare")
@app.route("/compare/<slug>")
def vergelijk(slug=None):
    """Stap 163: eerlijke vergelijkingen met de andere tools."""
    import vergelijkingen
    if slug and slug not in vergelijkingen.TOOLS:
        return redirect("/compare", code=302)
    return render_template("vergelijk.html", tools=vergelijkingen.TOOLS, slug=slug,
                           tool=vergelijkingen.TOOLS.get(slug) if slug else None,
                           krillo=vergelijkingen.KRILLO, gekeken=vergelijkingen.GEKEKEN)


@app.route("/news")
@app.route("/news/<land>")
def index_nieuws(land="nl"):
    """Stap 92: het nieuws van de laatste meting, per land (Engels, openbaar)."""
    import indexnieuws
    land = (land or "nl").lower()
    if land not in sitetaal.LANDEN:
        return redirect("/news/nl", code=302)
    ov = _bewaard(("nieuws", land), lambda l: indexnieuws.overzicht(l, ranglijst=_ranglijst_bewaard), land)
    return render_template("nieuws.html", ov=ov, landnaam=sitetaal.landnaam(land, "en"))


@app.route("/admin/persbericht")
def admin_persbericht():
    """Stap 92: het persbericht in het Nederlands, klaar om te kopieren."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import indexnieuws
    blokken = ""
    for land in markten.index_landen():
        # Via de bewaarde ranglijsten: zonder dat vroeg deze pagina tientallen
        # zware ranglijsten tegelijk op en bleef hij laden (29 september).
        ov = _bewaard(("nieuws", land), lambda l: indexnieuws.overzicht(l, ranglijst=_ranglijst_bewaard), land)
        tekst = indexnieuws.persbericht_nl(ov, get_base_url().rstrip("/"), embed=embed_code)
        post = indexnieuws.linkedin_post(ov, get_base_url().rstrip("/"))
        blokken += (f"<h2>{escape(sitetaal.landnaam(land, 'nl'))}</h2>"
                    + (f"<textarea readonly rows='22' style='width:100%;font:inherit;font-size:14px;padding:10px' "
                       f"onclick='this.select()'>{escape(tekst)}</textarea>" if tekst else
                       "<p>Nog te weinig gemeten categorieen voor een bericht.</p>")
                    # Stap 131: de post voor de LinkedIn-bedrijfspagina van Krillo.
                    + (f"<h3>Post voor de LinkedIn-pagina van Krillo (Engels)</h3>"
                       f"<textarea readonly rows='10' style='width:100%;font:inherit;font-size:14px;padding:10px' "
                       f"onclick='this.select()'>{escape(post)}</textarea>" if post else ""))
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Persbericht | Krillo</title><body style='font-family:Arial,sans-serif;max-width:820px;"
            f"margin:40px auto;padding:0 16px;line-height:1.5'><h1>Persbericht van deze maand</h1>"
            f"<p>Dit gaat VANZELF (sinds 29 september): een keer per maand, binnen kantooruren, alleen als er "
            f"nieuws is, naar de redacties hieronder. Je krijgt een melding als het weg is. Hier zie je de tekst.</p>"
            f"{_pers_stand()}{blokken}</body>")


def _pers_stand():
    import persagent
    rijen = persagent._sql("SELECT land, maand, adres, op FROM pers_verstuurd ORDER BY op DESC LIMIT 20",
                           alles=True) or []
    naar = "".join(f"<li>{escape(n)} ({escape(a)}, {escape(l.upper())})</li>"
                   for l, lijst in persagent.REDACTIES.items() for n, a, _ in lijst)
    gedaan = "".join(f"<li>{escape(r['maand'])} {escape(r['land'].upper())}: {escape(r['adres'])}</li>" for r in rijen)
    return (f"<h2>Naar wie</h2><ul>{naar}</ul><h2>Al verstuurd</h2><ul>{gedaan or '<li>Nog niets.</li>'}</ul>")


@app.route("/lijstje/<token>/stop", methods=["GET", "POST"])
def lijstje_stop(token):
    """De afmeldlink uit de mail van de lijstjesagent. Een klik, klaar."""
    import lijstjesagent
    domein = lijstjesagent.stop(token)
    if domein:
        _meld_aan_beheer("Lijstje afgemeld", f"{escape(domein)} wil geen mail meer over GEO-lijstjes.")
    return render_template("fout.html", titel="Done",
                           bericht="You will not hear from us again. Sorry for the interruption."), 200


@app.route("/admin/linkedin", methods=["GET", "POST"])
def admin_linkedin():
    """De posts van de LinkedIn-agent: kopieren, plaatje downloaden, geplaatst.

    30 september: de link staat in een eigen eerste reactie (stap 207). Bij
    Geplaatst plakt Nino de link naar de post; dan krijgen de winkels uit de
    top een deelmail (stap 208). En per post vult hij later de weergaven in
    (stap 212), zodat we zien welk soort post werkt."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import linkedinagent
    basis = get_base_url().rstrip("/")
    melding = ""
    if request.method == "POST" and request.form.get("actie") in ("experts", "profiel_klaar"):
        # 2 oktober: de groeiroutine (linkedinagent.dag_routine).
        if request.form.get("actie") == "experts":
            n = len(linkedinagent.bewaar_experts(request.form.get("experts")))
            melding_r = f"{n} van de {linkedinagent.EXPERTS_MAX} experts bewaard."
        else:
            db.zet_instelling(linkedinagent.PROFIEL_SLEUTEL, "ja")
            melding_r = "Profiel staat op gedaan."
        return redirect("/admin/linkedin?m=" + quote(melding_r) + "#routine")
    if request.method == "POST":
        actie = request.form.get("actie")
        post_id = int(request.form.get("id") or 0)
        if actie == "geplaatst":
            post_url = (request.form.get("post_url") or "").strip()
            if post_url and not post_url.startswith("https://www.linkedin.com/"):
                post_url = ""
            linkedinagent.zet_geplaatst(post_id, post_url or None)
            if post_url:
                try:
                    n = linkedinagent.deelmails(
                        post_id, basis, lambda url: klantbeeld.bouw(url),
                        categorienaam=lambda b: categorieen.naam_en(b["categorie"]),
                        landnaam=lambda b: sitetaal.landnaam(b["land"], "en") if b.get("land") else None)
                    melding = f"Geplaatst. {n} winkel(s) uit de top kregen een mail met de link naar de post."
                except Exception as e:
                    print(f"Deelmail na LinkedIn-post mislukt: {e}")
                    melding = "Geplaatst, maar de deelmail lukte niet. Staat in de logs."
        elif actie == "cijfers":
            def _getal(naam):
                try:
                    return max(0, int((request.form.get(naam) or "").strip()))
                except ValueError:
                    return None
            linkedinagent.zet_cijfers(post_id, _getal("weergaven"), _getal("reacties"))
        elif actie == "vullen":
            linkedinagent.klaarzetten(
                basis,
                db.categorieen_per_land(linkedinagent.LAND, MINIMUM_PER_LAND) or [],
                _ranglijst_bewaard, categorieen.naam_en, sitetaal.landnaam(linkedinagent.LAND, "en"))
        return redirect("/admin/linkedin" + (f"?m={quote(melding)}" if melding else ""))
    melding = request.args.get("m") or ""

    def _kopieer(veld_id, label):
        return (f"<button onclick=\"navigator.clipboard.writeText(document.getElementById('{veld_id}').value);"
                f"this.textContent='Gekopieerd'\">{label}</button>")

    blokken = []
    for p in linkedinagent.posts():
        # Posts die voor 30 september klaargezet werden hebben de link nog in
        # de tekst. Nog niet geplaatst? Dan hier alsnog splitsen.
        if not p.get("reactie") and p["stand"] != "geplaatst" and basis in (p.get("tekst") or ""):
            p["tekst"], p["reactie"] = linkedinagent.link_naar_reactie(p["tekst"], basis)
            linkedinagent._sql("UPDATE linkedin_posts SET tekst = %s, reactie = %s WHERE id = %s",
                               (p["tekst"], p["reactie"], p["id"]))
        tag = (f"<p><b>Tag deze winkels</b> (typ @ en de naam in de post, als ze een bedrijfspagina hebben): "
               f"{escape(p['taggen'])}</p>") if p.get("taggen") else ""
        reactie = ""
        if p.get("reactie"):
            reactie = (f"<p style='margin:14px 0 4px'><b>Eerste reactie</b> (direct na het plaatsen, als Krillo): "
                       f"</p><textarea id='r{p['id']}' rows='4' style='width:100%;font:14px system-ui'>"
                       f"{escape(p['reactie'])}</textarea><p>{_kopieer('r' + str(p['id']), 'Kopieer reactie')}</p>")
        if p["stand"] == "geplaatst":
            gedeeld = ""
            if p.get("gedeeld_gemaild") is not None:
                gedeeld = f" {p['gedeeld_gemaild']} winkel(s) kregen de deelmail."
            elif p.get("soort") == "ranglijst" and not p.get("post_url"):
                gedeeld = " Zonder link naar de post: geen deelmail verstuurd."
            knop = (f"<p style='color:#0B7C5E'>Geplaatst.{gedeeld}</p>"
                    f"<form method='post' style='display:flex;gap:8px;flex-wrap:wrap;align-items:center'>"
                    f"<input type='hidden' name='id' value='{p['id']}'>"
                    f"<label>Weergaven <input name='weergaven' size='6' value='{p.get('weergaven') or ''}'></label>"
                    f"<label>Reacties <input name='reacties' size='4' value='{p.get('reacties') or ''}'></label>"
                    f"<button name='actie' value='cijfers'>Bewaar cijfers</button></form>")
        else:
            uitleg = (" Plak de link van je post (de drie puntjes op de post, <i>Copy link to post</i>): dan "
                      "krijgen de winkels uit de top een mail om hem te delen." if p.get("soort") == "ranglijst" else "")
            knop = (f"<form method='post'><input type='hidden' name='id' value='{p['id']}'>"
                    f"<p style='margin:8px 0'>{uitleg}</p>"
                    f"<input name='post_url' placeholder='https://www.linkedin.com/posts/...' "
                    f"style='width:100%;max-width:420px;padding:6px'> "
                    f"<button name='actie' value='geplaatst'>Geplaatst</button></form>")
        blokken.append(
            f"<div style='border:1px solid #ddd;border-radius:10px;padding:16px;margin:16px 0;display:flex;gap:20px;flex-wrap:wrap'>"
            f"<div style='flex:1;min-width:300px'><h3>{p['dag']:%A %d %B} &middot; {escape(p['soort'])}</h3>"
            f"<textarea id='t{p['id']}' rows='12' style='width:100%;font:14px system-ui'>{escape(p['tekst'])}</textarea>"
            f"<p>{_kopieer('t' + str(p['id']), 'Kopieer tekst')} "
            f"<a href='/admin/linkedin/beeld/{p['id']}.png' download='krillo-{p['dag']}.png'>Download plaatje</a></p>"
            f"{reactie}{tag}{knop}</div>"
            f"<img src='/admin/linkedin/beeld/{p['id']}.png' style='width:300px;height:300px;border:1px solid #eee'></div>")
    melding_html = (f"<p style='background:#E8F6EF;padding:10px 14px;border-radius:8px'>{escape(melding)}</p>"
                    if melding else "")
    beste = linkedinagent.beste_soort()
    # Volgen en uitnodigen (30 september): elke dag een paar, uit onze markten.
    try:
        sug = linkedinagent.suggesties()
    except Exception as e:
        print(f"LinkedIn-suggesties mislukt: {e}")
        sug = {"volgen": [], "uitnodigen": []}
    volg_html = "".join(f"<li><a href='{escape(v['link'])}' target='_blank'>{escape(v['naam'])}</a>"
                        f" <span style='color:#6E7079'>{escape(v['waarom'])}</span></li>" for v in sug["volgen"])
    suggestie_html = (
        "<div style='border:1px solid #ddd;border-radius:10px;padding:14px 18px;margin:18px 0'>"
        "<h2 style='margin-top:0'>Vandaag: volgen en uitnodigen</h2>"
        "<p><b>Volg als Krillo</b> (op de bedrijfspagina rechtsboven <i>Follow other Pages</i>, of open de link "
        "en klik op Follow terwijl je als Krillo werkt):</p>"
        f"<ul>{volg_html or '<li>Nog niets; er is nog geen ranglijst.</li>'}</ul>"
        "<p><b>Nodig uit</b> (op de bedrijfspagina <i>Invite connections</i>): typ een van deze woorden in het "
        f"zoekveld en kies de mensen die echt een webshop hebben of voor webshops werken: "
        f"<b>{escape(', '.join(sug['uitnodigen']))}</b>. Je hebt 50 uitnodigingen per maand: een paar goede per "
        "dag werkt beter dan alles in een keer. Let op: de uitnodiging komt van jouw eigen naam.</p></div>")
    # 2 oktober: de dagelijkse groeiroutine, met de tactiek uitgeschreven.
    try:
        r = linkedinagent.dag_routine()
    except Exception as e:
        print(f"LinkedIn-routine mislukt: {e}")
        r = None
    routine_html = ""
    if r:
        reageer = "".join(
            (f"<li><a href='{escape(x['link'])}' target='_blank'>{escape(x['naam'])}</a></li>" if x.get("link")
             else f"<li>{escape(x['naam'])}</li>") for x in r["reageren"])
        profiel = ("<h3>Een keer: je profiel vindbaar maken</h3><ol>" + "".join(f"<li>{escape(t)}</li>" for t in r["profiel"])
                   + "</ol><form method='post'><button name='actie' value='profiel_klaar'>Gedaan</button></form>"
                   if r["profiel"] else "")
        lijst_tekst = "\n".join(f"{x['naam']} | {x['link']}" if x.get("link") else x["naam"]
                                for x in linkedinagent.experts())
        routine_html = (
            "<div id='routine' style='border:2px solid #1B3FE0;border-radius:10px;padding:14px 18px;margin:18px 0'>"
            "<h2 style='margin-top:0'>Vandaag: de groeiroutine (15 minuten)</h2>"
            "<p style='color:#52525B'>Geen willekeurige connecties. Wel: elke dag reageren bij dezelfde twintig "
            "mensen uit de branche, en vijf nieuwe mensen die echt een webshop hebben of runnen.</p>"
            f"<p><b>Onderwerp van vandaag</b> (voor je reacties en je eigen post): {escape(r['onderwerp']['naam'])}. "
            f"{escape(r['onderwerp']['uitleg'])}</p>"
            "<h3>1. Reageer op 3 posts van je experts (5 min)</h3>"
            + (f"<ul>{reageer}</ul>" if reageer else "<p>Je lijst is nog leeg. Zie stap 3.</p>")
            + "<p>Hoe: open hun laatste post en voeg iets toe, geen \"great post\". Een eigen ervaring, een vraag "
              "terug, of een cijfer"
            + (f". Cijfer van vandaag: <i>{escape(r['feit'])}</i>" if r["feit"] else "")
            + ". Twee of drie zinnen, binnen het uur na hun post werkt het best.</p>"
            f"<h3>2. Connect met {r['connecten']['aantal']} mensen (5 min)</h3>"
            f"<p><a href='{escape(r['connecten']['link'])}' target='_blank'>Zoek op \"{escape(r['connecten']['woorden'])}\"</a>, "
            "kies alleen mensen met een webshop of die er een runnen, en stuur een korte notitie. Voorbeeld:</p>"
            f"<p style='background:#F4F4F5;padding:8px 12px;border-radius:8px'>{escape(r['connecten']['notitie'])}</p>"
            "<p>Na het accepteren: niets verkopen. Like of reageer een keer op iets van hen; de Krillo-posts zien "
            "ze vanzelf.</p>"
            f"<h3>3. Je twintig experts ({r['experts_aantal']} van {linkedinagent.EXPERTS_MAX})</h3>"
            f"<p>Mensen die over e-commerce, AI-zoeken of webshops posten, met publiek dat jouw klant is. "
            f"<a href='{escape(r['experts_zoek']['link'])}' target='_blank'>Zoek op \"{escape(r['experts_zoek']['woorden'])}\"</a> "
            "en kies wie vaak post en reacties krijgt. Een per regel: Naam | link naar profiel.</p>"
            "<form method='post'><textarea name='experts' rows='6' style='width:100%;font:14px system-ui'>"
            f"{escape(lijst_tekst)}</textarea><button name='actie' value='experts'>Bewaar lijst</button></form>"
            f"{profiel}</div>")
    beste_html = ("<p><b>Wat werkt:</b> " + ", ".join(
        f"{escape(r['soort'])} gemiddeld {int(r['gem'])} weergaven ({r['n']} posts)" for r in beste) + "</p>"
        if beste else "<p><b>Wat werkt:</b> vul na een paar dagen bij elke geplaatste post de weergaven in. "
                      "Vanaf drie posts staat hier welk soort post het best loopt.</p>")
    return (f"<!doctype html><meta charset='utf-8'><title>LinkedIn</title>"
            f"<body style='font-family:system-ui;max-width:1000px;margin:30px auto;padding:0 16px'>"
            f"<h1>LinkedIn-posts voor de bedrijfspagina</h1>"
            f"{melding_html}"
            f"<p>Maandag, woensdag en vrijdag een post, een week vooruit klaargezet uit de echte meetdata.</p>"
            f"<ol><li>Open de bedrijfspagina Krillo en klik <b>Start a post</b> (je post dan als Krillo).</li>"
            f"<li>Plak de tekst, klik op het fotoicoon, kies het plaatje, en <b>Post</b>. Tag de winkels die erbij staan.</li>"
            f"<li>Plaats meteen daarna de <b>eerste reactie</b> met de link, ook als Krillo. De link staat bewust "
            f"niet in de post: posts met een link naar buiten krijgen minder bereik.</li>"
            f"<li>Kopieer de link van je post, plak hem hieronder en klik <b>Geplaatst</b>.</li>"
            f"<li>Na een dag of drie: de weergaven en reacties invullen.</li></ol>"
            f"<p>Beste moment: tussen 8:00 en 9:30.</p>{routine_html}{beste_html}{suggestie_html}"
            f"<p><b>Maandrapport:</b> <a href='/admin/linkedin/rapport.pdf'>Download de PDF</a> en plaats hem na de "
            f"maandmeting als document (Start a post, het documenticoon, titel: Krillo Index {datetime.now():%B %Y}). "
            f"Mensen bladeren erdoorheen, en dat geeft meer bereik dan een gewone post.</p>"
            f"<form method='post'><button name='actie' value='vullen'>Nu de komende week klaarzetten</button></form>"
            f"{''.join(blokken) or '<p>Nog geen posts. Klik hierboven of wacht op de volgende uurronde.</p>'}</body>")


@app.route("/admin/artikelen", methods=["GET", "POST"])
def admin_artikelen():
    """Stap 203: de concepten van de artikelagent. Niets gaat vanzelf online."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import artikelagent
    melding = ""
    if request.method == "POST":
        actie, cid = request.form.get("actie"), int(request.form.get("id") or 0)
        if actie == "plaats":
            artikelagent.publiceer(cid)
            melding = "Geplaatst op /articles."
        elif actie == "weg":
            artikelagent.wijs_af(cid)
            melding = "Afgewezen."
        elif actie == "schrijf":
            artikelagent._voorrang[0] = True
            try:
                uit = artikelagent.schrijf_concept()
            finally:
                artikelagent._voorrang[0] = False
            melding = "Nieuw concept staat hieronder." if uit.get("gelukt") else uit.get("fout", "Mislukt.")
        return redirect("/admin/artikelen?m=" + quote(melding))
    melding = request.args.get("m") or ""
    e = escape
    blokken = []
    for c in artikelagent.concepten():
        inhoud = c["inhoud"] if isinstance(c["inhoud"], list) else _json_los(c["inhoud"])
        tekst = "".join((f"<h3>{e(k)}</h3>" if k else "") + f"<p>{e(a)}</p>" for k, a in inhoud)
        knoppen = ("" if c["stand"] != "concept" else
                   f"<form method='post' style='display:flex;gap:8px'><input type='hidden' name='id' value='{c['id']}'>"
                   f"<button name='actie' value='plaats'>Plaatsen</button>"
                   f"<button name='actie' value='weg'>Afwijzen</button></form>")
        let_op = (f"<p style='background:#FFF4E5;padding:8px 12px;border-radius:8px'><b>Let op:</b> {e(c['keuring'])}</p>"
                  if c.get("keuring") else "")
        blokken.append(f"<details style='border:1px solid #ddd;border-radius:10px;padding:14px;margin:12px 0'"
                       f"{' open' if c['stand'] == 'concept' else ''}><summary><b>{e(c['titel'])}</b> &middot; "
                       f"{e(c['stand'])} &middot; {c['gemaakt_op']:%d %B}</summary>{let_op}"
                       f"<p><i>{e(c.get('samenvatting') or '')}</i></p>{tekst}{knoppen}</details>")
    melding_html = (f"<p style='background:#E8F6EF;padding:10px 14px;border-radius:8px'>{e(melding)}</p>"
                    if melding else "")
    return (f"<!doctype html><meta charset='utf-8'><title>Artikelen | Krillo</title>"
            f"<body style='font-family:system-ui;max-width:900px;margin:30px auto;padding:0 16px;line-height:1.55'>"
            f"<h1>Artikelen</h1>{melding_html}"
            f"<p>Elke dinsdag schrijft de artikelagent een concept over een vraag die webshop-eigenaren stellen, "
            f"met alleen echte cijfers uit de index. Lees het, en klik Plaatsen of Afwijzen. Niets komt vanzelf "
            f"online. Staat er een Let op, kijk dat stuk dan extra na.</p>"
            f"<form method='post'><button name='actie' value='schrijf'>Nu een concept schrijven</button></form>"
            f"{''.join(blokken) or '<p>Nog geen concepten.</p>'}</body>")


def _json_los(tekst):
    import json as _j
    try:
        return _j.loads(tekst or "[]")
    except ValueError:
        return []


@app.route("/admin/linkedin/rapport.pdf")
def admin_linkedin_rapport():
    """Stap 209: het maandrapport als PDF voor een documentpost op LinkedIn."""
    mag, _ = _mag_bij_beheer()
    if not mag:
        return "", 404
    import linkedinagent
    maand = datetime.now().strftime("%B %Y")
    paginas = linkedinagent.rapport_paginas(
        db.categorieen_per_land(linkedinagent.LAND, MINIMUM_PER_LAND) or [], _ranglijst_bewaard,
        categorieen.naam_en, sitetaal.landnaam(linkedinagent.LAND, "en"), maand)
    if not any(p["soort"] == "ranglijst" for p in paginas):
        # Nooit een rapport met "0 stores": dan liever niets.
        return ("Nog te weinig metingen voor een maandrapport: er is geen ranglijst met drie genoemde "
                "winkels. Na de volgende maandmeting opnieuw.", 200, {"Content-Type": "text/plain; charset=utf-8"})
    return Response(linkedinagent.rapport_pdf(paginas, maand=maand), mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename=krillo-index-{maand.lower().replace(' ', '-')}.pdf"})


@app.route("/admin/linkedin/beeld/<int:post_id>.png")
def admin_linkedin_beeld(post_id):
    mag, _ = _mag_bij_beheer()
    if not mag:
        return "", 404
    import linkedinagent
    p = linkedinagent._sql("SELECT beeld, dag FROM linkedin_posts WHERE id = %s", (post_id,))
    if not p:
        return "", 404
    png = linkedinagent.beeld_png(p["beeld"], maand=p["dag"].strftime("%B %Y"))
    return Response(png, mimetype="image/png", headers={"Cache-Control": "private, max-age=3600"})


@app.route("/admin/agents", methods=["GET", "POST"])
def admin_agents():
    """Het commandocentrum (stap 172): alle agents op een plek, met schakelaars."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    if request.method == "POST":
        commandocentrum.zet(request.form.get("agent", ""), request.form.get("actie") == "aan")
        return redirect("/admin/agents")
    import ochtendbericht
    ov = commandocentrum.overzicht(te_doen=ochtendbericht.te_doen(get_base_url().rstrip("/")))
    return render_template("admin_agents.html", ov=ov)


@app.route("/api/agents")
def api_agents():
    """Hetzelfde als /admin/agents, als JSON (voor de Claude-app later, stap 150).
    Alleen met de beheersleutel of een beheersessie."""
    mag, _ = _mag_bij_beheer()
    if not mag:
        return jsonify({"fout": "niet ingelogd"}), 404
    import ochtendbericht
    ov = commandocentrum.overzicht(te_doen=ochtendbericht.te_doen(get_base_url().rstrip("/")))
    ov["te_doen"] = [{"tekst": t, "link": l} for t, l in ov["te_doen"]]
    return jsonify(ov)


@app.route("/admin/lijstjes")
def admin_lijstjes():
    """Wat de lijstjesagent vond en mailde."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import lijstjesagent
    rijen = "".join(
        f"<tr><td>{escape(r['domein'])}</td><td>{escape(r['stand'] or '')}</td>"
        f"<td>{('<a href=' + chr(39) + escape(r['url']) + chr(39) + ' target=_blank>' + escape(r.get('titel') or r['url']) + '</a>') if r.get('url') else ''}</td>"
        f"<td>{escape(r.get('adres') or '')}</td>"
        f"<td>{r['verstuurd_op'].strftime('%d-%m %H:%M') if r.get('verstuurd_op') else ''}</td>"
        f"<td>{escape(r.get('notitie') or r.get('waarom') or '')}</td></tr>"
        for r in lijstjesagent.overzicht())
    return (f"<!doctype html><meta charset='utf-8'><title>Lijstjes GEO-tools</title>"
            f"<body style='font-family:system-ui;max-width:1100px;margin:30px auto;padding:0 16px'>"
            f"<p><a href='/admin'>Terug</a></p><h1>Lijstjes met beste GEO-tools</h1>"
            f"<p>De lijstjesagent zoekt een keer per week nieuwe artikelen en mailt de schrijver een keer, "
            f"hoogstens {lijstjesagent.PER_WEEK} per week. Een antwoord komt binnen op hello@ en staat op "
            f"/admin/antwoorden. Staat er 'geen adres' met een formulier, dan kun je dat met de hand doen.</p>"
            f"<table cellpadding='8' style='border-collapse:collapse;width:100%'>"
            f"<tr><th align=left>Site</th><th align=left>Stand</th><th align=left>Artikel</th>"
            f"<th align=left>Adres</th><th align=left>Gemaild</th><th align=left>Notitie</th></tr>"
            f"{rijen or '<tr><td colspan=6>Nog niets gevonden.</td></tr>'}</table></body>")


@app.route("/r/<code>")
def doorverwijslink(code):
    """Stap 94: de link van een klant of partner. Stuurt door naar de gratis
    check met de code in de link; GEEN cookie (zie doorverwijzen.py waarom).
    Een onbekende code stuurt gewoon door: een oude link mag nooit een
    foutpagina geven."""
    import doorverwijzen
    wie = doorverwijzen.bij_code(code)
    if not wie:
        return redirect("/#scan", code=302)
    doorverwijzen.tel_bezoek(wie["code"])
    return redirect(f"/?ref={wie['code']}&utm_source=doorverwijzing#scan", code=302)


@app.route("/partners")
def partners_pagina():
    """Stap 94: de pagina voor bureaus, freelancers en Shopify-partners."""
    import doorverwijzen
    return render_template("partners.html", procent=doorverwijzen.PROCENT_PARTNER,
                           maanden=doorverwijzen.MAANDEN_PARTNER, basis_url=get_base_url().rstrip("/"))


@app.route("/api/partners", methods=["POST"])
def partners_aanvraag():
    """Een aanmelding als partner. Niet meteen actief: Nino keurt goed op
    /admin/doorverwijzen, want een partner spreekt namens Krillo."""
    import doorverwijzen
    data = request.get_json(silent=True) or {}
    naam = (data.get("naam") or "").strip()[:120]
    email = (data.get("email") or "").strip()[:200]
    website = (data.get("website") or "").strip()[:200]
    bericht = (data.get("bericht") or "").strip()[:2000]
    if not naam or not email or not _EMAIL_VORM.match(email):
        return jsonify({"fout": "Enter your name or company and a valid email address."}), 400
    # Zelfde rem als de gratis tools: niemand vult dit formulier honderd keer.
    import gratistools
    if not gratistools.mag_nu("partner:" + (_bezoeker_kenmerk() or request.remote_addr or "?")):
        return jsonify({"fout": "We already have your request. We reply within one working day."}), 429
    try:
        code = doorverwijzen.partner_aanvragen(naam, email, website, bericht)
    except Exception as e:
        print(f"Partneraanvraag bewaren mislukt: {e}")
        return jsonify({"fout": "Something went wrong. Email hello@krilloai.com and we set it up."}), 500
    _meld_aan_beheer("Nieuwe partneraanvraag",
                     f"{escape(naam)} ({escape(email)}, {escape(website or 'geen site')}) wil partner worden. "
                     f"Bericht: {escape(bericht or '-')}. Goedkeuren of afwijzen op /admin/doorverwijzen "
                     f"(voorgestelde code: {escape(code)}).")
    return jsonify({"ok": True})


@app.route("/agencies")
@app.route("/brands")
def merken_en_bureaus():
    """De pagina voor merken en bureaus. Zie merkenbureaus.py waarom."""
    return render_template("agencies.html", basis_url=get_base_url().rstrip("/"),
                           soort="brand" if request.path == "/brands" else "agency")


def _pitch_uitkomst(winkels):
    import merkenbureaus
    landen = [r["land"] for r in (_bewaard(("landen",), db.landen_in_index) or [])]
    return merkenbureaus.pitch(
        winkels, landen,
        lambda land: [c["categorie"] for c in (_bewaard(("perland", land), db.categorieen_per_land, land,
                                                        MINIMUM_PER_LAND) or [])],
        _ranglijst_bewaard, categorieen.naam_en, _winkel_slug)


@app.route("/api/agencies/check", methods=["POST"])
def api_merken_check():
    """Tot tien winkels in een keer opzoeken in de index. Geen account nodig,
    kost niets (alles uit de bewaarde ranglijsten), met dezelfde rem als de
    gratis tools zodat niemand er een robot van maakt."""
    import merkenbureaus
    import gratistools
    data = request.get_json(silent=True) or {}
    winkels = merkenbureaus.lees_winkels(data.get("winkels"))
    if not winkels:
        return jsonify({"fout": "Paste one or more store addresses, like store.com."}), 400
    if not gratistools.mag_nu("merkcheck:" + (_bezoeker_kenmerk() or request.remote_addr or "?")):
        return jsonify({"fout": "You just ran a check. Try again in a minute."}), 429
    return jsonify({"ok": True, "uitkomst": _pitch_uitkomst(winkels)})


@app.route("/api/agencies", methods=["POST"])
def api_merken_aanvraag():
    """Het korte formulier op /agencies: bewaren, Nino een seintje, de aanvrager
    een bevestiging. Geen lege mail meer die iemand zelf moet schrijven."""
    import merkenbureaus
    import gratistools
    data = request.get_json(silent=True) or {}
    naam = (data.get("naam") or "").strip()[:120]
    bedrijf = (data.get("bedrijf") or "").strip()[:160]
    email = (data.get("email") or "").strip()[:200]
    website = (data.get("website") or "").strip()[:200]
    aantal = (data.get("aantal") or "").strip()[:20]
    soort = "brand" if data.get("soort") == "brand" else "agency"
    bericht = (data.get("bericht") or "").strip()[:2000]
    winkels = ", ".join(merkenbureaus.lees_winkels(data.get("winkels")))
    if not naam or not email or not _EMAIL_VORM.match(email):
        return jsonify({"fout": "Enter your name and a valid work email address."}), 400
    if not gratistools.mag_nu("merken:" + (_bezoeker_kenmerk() or request.remote_addr or "?")):
        return jsonify({"fout": "We already have your request. We reply within one working day."}), 429
    try:
        merkenbureaus.bewaar(naam, bedrijf, email, website, aantal, soort, bericht, winkels)
    except Exception as e:
        print(f"Merkaanvraag bewaren mislukt: {e}")
        return jsonify({"fout": "Something went wrong. Email hello@krilloai.com and we reply the same day."}), 500
    _meld_aan_beheer("Nieuwe aanvraag merken/bureaus",
                     f"{escape(naam)} van {escape(bedrijf or '-')} ({escape(email)}, {escape(website or '-')}), "
                     f"{escape(soort)}, {escape(aantal or '?')} winkels. Winkels: {escape(winkels or '-')}. "
                     f"Bericht: {escape(bericht or '-')}. Alles op /admin/merkaanvragen. Antwoord binnen een werkdag.")
    try:
        b = merkenbureaus.bevestiging(naam, soort)
        emailing.send_klantbericht(email, b["onderwerp"], b["alineas"],
                                   f"{get_base_url().rstrip('/')}/index", knop="See the Krillo Index")
    except Exception as e:
        print(f"Bevestiging merkaanvraag mislukt: {e}")
    return jsonify({"ok": True})


@app.route("/admin/merkaanvragen")
def admin_merkaanvragen():
    """De aanvragen van /agencies, nieuwste eerst. (/admin/merken bestond al:
    dat is de lijst winkels die als merk zijn aangemerkt.)"""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import merkenbureaus
    rijen = "".join(
        f"<tr><td>{a['gemaakt_op']:%d-%m %H:%M}</td><td>{escape(a.get('naam') or '')}<br>"
        f"<small>{escape(a.get('bedrijf') or '')}</small></td>"
        f"<td><a href='mailto:{escape(a['email'])}'>{escape(a['email'])}</a></td>"
        f"<td>{escape(a.get('soort') or '')}, {escape(a.get('aantal') or '?')}</td>"
        f"<td>{escape(a.get('winkels') or '')}</td><td>{escape(a.get('bericht') or '')}</td></tr>"
        for a in merkenbureaus.aanvragen())
    return (f"<!doctype html><meta charset='utf-8'><title>Merken en bureaus</title>"
            f"<body style='font-family:system-ui;max-width:1100px;margin:30px auto;padding:0 16px'>"
            f"<p><a href='/admin'>Terug</a></p><h1>Aanvragen merken en bureaus</h1>"
            f"<p>Van de pagina /agencies. Antwoord binnen een werkdag, persoonlijk.</p>"
            f"<table cellpadding='8' style='border-collapse:collapse;width:100%'>"
            f"<tr><th align=left>Wanneer</th><th align=left>Wie</th><th align=left>Mail</th>"
            f"<th align=left>Soort, aantal</th><th align=left>Winkels</th><th align=left>Bericht</th></tr>"
            f"{rijen or '<tr><td colspan=6>Nog geen aanvragen.</td></tr>'}</table></body>")


@app.route("/admin/doorverwijzen", methods=["GET", "POST"])
def admin_doorverwijzen():
    """Stap 94: partneraanvragen goedkeuren, en zien wat er openstaat om uit te
    betalen. Uitbetalen gebeurt met de hand (zie doorverwijzen.py waarom)."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import doorverwijzen
    basis = get_base_url().rstrip("/")
    melding = ""
    if request.method == "POST":
        actie = request.form.get("actie")
        code = request.form.get("code") or ""
        if actie in ("goedkeuren", "afwijzen"):
            wie = doorverwijzen.zet_stand(code, "actief" if actie == "goedkeuren" else "afgewezen")
            if wie and actie == "goedkeuren":
                verstuurd = False
                try:
                    verstuurd = emailing.send_partner_welkom(wie["email"], wie.get("naam"), f"{basis}/r/{wie['code']}",
                                                             doorverwijzen.PROCENT_PARTNER, doorverwijzen.MAANDEN_PARTNER)
                except Exception as e:
                    print(f"Partnermail mislukt: {e}")
                melding = (f"{wie.get('naam')} is partner. " + ("De mail met de link is verstuurd."
                           if verstuurd else f"De mail ging NIET weg; stuur zelf de link {basis}/r/{wie['code']}"))
            elif wie:
                melding = f"{wie.get('naam')} afgewezen. Er gaat geen mail uit."
        elif actie == "uitbetaald":
            try:
                doorverwijzen.zet_uitbetaald(request.form.get("id"), request.form.get("bedrag"))
                melding = "Uitbetaald bijgewerkt."
            except (TypeError, ValueError):
                melding = "Dat bedrag klopt niet. Gebruik een punt, bijvoorbeeld 29.80."
    ov = doorverwijzen.overzicht()
    knop = "padding:6px 12px;border-radius:6px;border:1px solid #ccc;background:#fff;cursor:pointer"
    aanvragen = "".join(
        f"<div style='border:1px solid #ddd;border-radius:10px;padding:12px 16px;margin:10px 0'>"
        f"<strong>{escape(a.get('naam') or '')}</strong> &middot; {escape(a.get('email') or '')} &middot; "
        f"{escape(a.get('website') or '')}<p style='margin:6px 0;color:#555'>{escape(a.get('bericht') or '')}</p>"
        f"<form method='post' style='margin:0'><input type='hidden' name='code' value='{escape(a['code'])}'>"
        f"<button name='actie' value='goedkeuren' style='{knop};background:#1B3FE0;color:#fff;border:0'>"
        f"Goedkeuren (code {escape(a['code'])})</button> "
        f"<button name='actie' value='afwijzen' style='{knop}'>Afwijzen</button></form></div>"
        for a in ov["aanvragen"])
    rijen = "".join(
        f"<tr><td>{r['op'].strftime('%d-%m-%Y')}</td><td>{escape(r['webshop_url'])}</td>"
        f"<td>{escape(r.get('naam') or r.get('door_winkel') or r['code'])}<br><small>{escape(r['soort'])}, "
        f"{escape(r.get('door_email') or '')}</small></td>"
        f"<td>{escape(r['verdiend']['uitleg'])}</td><td>&euro; {r['verdiend']['bedrag']:.2f}</td>"
        f"<td>&euro; {float(r.get('uitbetaald') or 0):.2f}</td><td><strong>&euro; {r['open']:.2f}</strong></td>"
        f"<td><form method='post' style='margin:0;display:flex;gap:4px'><input type='hidden' name='id' value='{r['id']}'>"
        f"<input name='bedrag' size='7' value='{r['verdiend']['bedrag']:.2f}'>"
        f"<button name='actie' value='uitbetaald' style='{knop}'>Betaald</button></form></td></tr>"
        for r in ov["doorverwijzingen"])
    wie = "".join(
        f"<tr><td>{escape(d['code'])}</td><td>{escape(d['soort'])}</td>"
        f"<td>{escape(d.get('naam') or d.get('webshop_url') or '')}</td><td>{d['bezoeken']}</td><td>{d['klanten']}</td></tr>"
        for d in ov["doorverwijzers"] if d["soort"] == "partner" or d["bezoeken"] or d["klanten"])
    tabel = "border-collapse:collapse;font-size:14px;width:100%"
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Doorverwijzen | Krillo</title><body style='font-family:Arial,sans-serif;max-width:1000px;"
            f"margin:40px auto;padding:0 16px;line-height:1.5'><h1>Doorverwijzen</h1>"
            f"<p style='color:#0B7C5E'>{escape(melding)}</p>"
            f"<h2>Partneraanvragen ({len(ov['aanvragen'])})</h2>"
            f"{aanvragen or '<p>Geen open aanvragen. De pagina staat op /partners.</p>'}"
            f"<h2>Uit te betalen: &euro; {ov['open_totaal']:.2f}</h2>"
            f"<p>Een partner krijgt {doorverwijzen.PROCENT_PARTNER} procent van wat de klant betaalt (zonder btw), "
            f"{doorverwijzen.MAANDEN_PARTNER} maanden. Een klant die doorverwijst krijgt een maand van zijn eigen "
            f"pakket terug, na {doorverwijzen.WACHTDAGEN} dagen. Maak het over (partner: vraag om een factuur; "
            f"klant: terugbetaling van zijn laatste betaling in Mollie) en vul het totaal dat nu betaald is in.</p>"
            f"<table cellpadding='6' style='{tabel}'><tr style='text-align:left'><th>Sinds</th><th>Nieuwe klant</th>"
            f"<th>Via</th><th>Hoe</th><th>Verdiend</th><th>Betaald</th><th>Open</th><th></th></tr>"
            f"{rijen or '<tr><td colspan=8>Nog geen klanten via een doorverwijzing.</td></tr>'}</table>"
            f"<h2>Links in gebruik</h2><table cellpadding='6' style='{tabel}'><tr style='text-align:left'>"
            f"<th>Code</th><th>Soort</th><th>Wie</th><th>Kliks</th><th>Klanten</th></tr>"
            f"{wie or '<tr><td colspan=5>Nog niemand.</td></tr>'}</table></body>")


def _bureau_beelden(site, maximaal=60):
    """De klantbeelden van de winkels van een bureau (stap 115)."""
    import bureauvinder
    beelden = []
    for url in bureauvinder.winkels_van(site)[:maximaal]:
        try:
            beeld = klantbeeld.bouw(url)
        except Exception:
            beeld = None
        if beeld:
            beeld = dict(beeld, categorienaam=categorieen.naam_en(beeld["categorie"]),
                         landnaam=sitetaal.landnaam(beeld.get("land"), "en") if beeld.get("land") else "")
        beelden.append(beeld)
    return bureauvinder.samenvatting(beelden)


def _stuur_bureaumail(bureau, basis, met_de_hand):
    """Een mail aan een bureau, en de stand bijwerken. Geeft True als hij weg is."""
    import bureauvinder
    if not bureau.get("email") or bureau.get("stand") != "nieuw":
        return False
    samen = _bureau_beelden(bureau["site"])
    if samen["winkels"] < bureauvinder.BUREAU_MIN:
        return False
    onderwerp, alineas = bureauvinder.mail_tekst(bureau.get("naam"), samen, None)
    ok = emailing.send_bureau_mail(bureau["email"], onderwerp, alineas, f"{basis}/bureau/{bureau['token']}",
                                   f"{basis}/bureau/{bureau['token']}/afmelden", partners_url=f"{basis}/partners")
    if ok:
        bureauvinder.zet_stand(bureau["site"], "gemaild", met_de_hand=met_de_hand)
    return bool(ok)


@app.route("/bureau/<token>")
def bureau_pagina(token):
    """Stap 115: de pagina voor een bureau. Niet in Google (noindex): het gaat
    over zijn klanten. Een onbekend kenmerk gaat naar de partnerpagina."""
    import bureauvinder
    bureau = bureauvinder.bij_token(token)
    if not bureau or bureau.get("stand") == "afgemeld":
        return redirect("/partners", code=302)
    bureauvinder._sql("UPDATE bureaus SET bekeken_op = now() WHERE site = %s", (bureau["site"],))
    antwoord = app.make_response(render_template(
        "bureau.html", bureau=bureau, samen=_bureau_beelden(bureau["site"]), token=token,
        basis_url=get_base_url().rstrip("/")))
    antwoord.headers["X-Robots-Tag"] = "noindex, nofollow"
    return antwoord


@app.route("/bureau/<token>/afmelden", methods=["GET", "POST"])
def bureau_afmelden(token):
    """Afmelden met een klik (ook de knop in de mail-app, via POST). Daarna nooit meer."""
    import bureauvinder
    bureau = bureauvinder.bij_token(token)
    if bureau:
        bureauvinder.zet_stand(bureau["site"], "afgemeld")
    if request.method == "POST":
        return "", 204
    return render_template("fout.html", titel="You will not hear from us again",
                           bericht="We removed your address. Sorry for the bother.")


@app.route("/admin/bureaus", methods=["GET", "POST"])
def admin_bureaus():
    """Stap 115: bureaus uit de voettekst van winkels. De eerste tien mails
    verstuur je hier met de hand; daarna kan het vanzelf (BUREAUMAIL_AUTO=1)."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import bureauvinder
    basis = get_base_url().rstrip("/")
    melding = ""
    if request.method == "POST":
        site = request.form.get("site") or ""
        actie = request.form.get("actie")
        bureau = bureauvinder._sql("SELECT * FROM bureaus WHERE site = %s", (site,))
        if bureau and actie == "adres":
            adres = (request.form.get("email") or "").strip().lower()
            if _EMAIL_VORM.match(adres):
                bureauvinder._sql("UPDATE bureaus SET email = %s, email_gezocht_op = now() WHERE site = %s",
                                  (adres, site))
                melding = f"Adres van {site} opgeslagen."
            else:
                melding = "Dat adres klopt niet."
        elif bureau and actie == "mailen":
            melding = (f"Mail aan {site} verstuurd." if _stuur_bureaumail(bureau, basis, True)
                       else f"Mail aan {site} NIET verstuurd (geen adres, al gemaild, of te weinig gemeten winkels).")
        elif bureau and actie == "overslaan":
            bureauvinder.zet_stand(site, "overgeslagen", met_de_hand=True)
            melding = f"{site} overgeslagen."
    rijen = ""
    for b in bureauvinder.groepen():
        knoppen = ""
        if b["stand"] == "nieuw":
            knoppen = (f"<form method='post' style='margin:4px 0;display:flex;gap:4px;flex-wrap:wrap'>"
                       f"<input type='hidden' name='site' value='{escape(b['site'])}'>"
                       f"<input name='email' size='22' placeholder='info@...' value='{escape(b.get('email') or '')}'>"
                       f"<button name='actie' value='adres'>Adres opslaan</button>"
                       + (f"<button name='actie' value='mailen' style='background:#1B3FE0;color:#fff;border:0;"
                          f"border-radius:4px;padding:3px 10px'>Mail versturen</button>" if b.get("email") else "")
                       + "<button name='actie' value='overslaan'>Overslaan</button></form>")
        rijen += (f"<tr><td><a href='{escape(b['site'])}' target='_blank' rel='noopener'>{escape(b.get('naam') or b['site'])}</a>"
                  f"<br><small>{escape(b['site'])}</small></td><td>{b['winkels']}</td>"
                  f"<td>{escape(b['stand'])}{' (bekeken)' if b.get('bekeken_op') else ''}</td>"
                  f"<td><a href='{basis}/bureau/{escape(b['token'])}' target='_blank'>Zijn pagina</a></td>"
                  f"<td>{knoppen}</td></tr>")
    telling = bureauvinder._sql("""SELECT count(*) AS bekeken, count(bureau_site) AS met_bureau,
                                          count(DISTINCT bureau_site) AS bureaus FROM bureau_winkels""") or {}
    hand = bureauvinder._sql("SELECT count(*) AS n FROM bureaus WHERE met_de_hand AND stand = 'gemaild'") or {}
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Bureaus | Krillo</title><body style='font-family:Arial,sans-serif;max-width:1000px;"
            f"margin:40px auto;padding:0 16px;line-height:1.5'><h1>Bureaus</h1>"
            f"<p style='color:#0B7C5E'>{escape(melding)}</p>"
            f"<p>{telling.get('bekeken', 0)} winkels uit de index bekeken, bij {telling.get('met_bureau', 0)} staat een "
            f"bureau onderaan ({telling.get('bureaus', 0)} verschillende). Hieronder de bureaus met "
            f"{bureauvinder.BUREAU_MIN} of meer winkels. Open eerst zijn pagina: klopt het, verstuur dan de mail. "
            f"Met de hand verstuurd: {hand.get('n', 0)} van de eerste {bureauvinder.HANDMATIG_EERST}; daarna kan "
            f"BUREAUMAIL_AUTO=1 in Render ({bureauvinder.AUTO_PER_DAG} per dag).</p>"
            f"<table cellpadding='6' style='border-collapse:collapse;font-size:14px;width:100%'>"
            f"<tr style='text-align:left'><th>Bureau</th><th>Winkels</th><th>Stand</th><th></th><th></th></tr>"
            f"{rijen or '<tr><td colspan=5>Nog geen bureau met genoeg winkels. De ronde bekijkt elk uur 15 winkels.</td></tr>'}"
            f"</table></body>")


@app.route("/admin/wachtlijst")
def admin_wachtlijst():
    """Stap 165: hoeveel winkels per land wachten. Zo kiezen we welk land eerst."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import wachtlijst
    rijen = "".join(f"<tr><td>{escape(markten.landnaam_en(t['land']))}</td><td>{t['wachtend']}</td><td>{t['gemeld']}</td></tr>"
                    for t in wachtlijst.telling())
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Wachtlijst | Krillo</title><body style='font-family:Arial,sans-serif;max-width:700px;"
            f"margin:40px auto;padding:0 16px;line-height:1.5'><h1>Wachtlijst per land</h1>"
            f"<p>Winkels die de gratis check deden of op /index hun adres achterlieten, uit een land dat we nog niet "
            f"meten. Staat een land in INDEX_LANDEN in Render, dan krijgen ze vanzelf een keer bericht.</p>"
            f"<table cellpadding='6'><tr style='text-align:left'><th>Land</th><th>Wachtend</th><th>Bericht gehad</th></tr>"
            f"{rijen or '<tr><td colspan=3>Nog niemand.</td></tr>'}</table></body>")


@app.route("/admin/leren", methods=["GET", "POST"])
def admin_leren():
    """Stap 96 en 153: wat de agents onderzochten, wat ze zelf doorvoerden, en
    wat ze voorstellen. Met een knop om nu een onderzoek te starten."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import leeragent
    import verkoopagent as va
    melding = ""
    if request.method == "POST" and request.form.get("onderwerp") in leeragent.ONDERWERPEN:
        onderwerp = request.form["onderwerp"]
        threading.Thread(target=leeragent.onderzoek, args=(onderwerp,), daemon=True).start()
        melding = f"Onderzoek '{onderwerp}' gestart. Over een minuut of twee staat het hieronder (pagina verversen)."
    blokken = ""
    for r in leeragent.laatste():
        naam = leeragent.ONDERWERPEN.get(r["onderwerp"], {}).get("naam", r["onderwerp"])
        if r.get("fout"):
            blokken += (f"<h2>{escape(naam)}</h2><p style='color:#9B1C1C'>{escape(r['op'].strftime('%d-%m-%Y'))}: "
                        f"mislukt: {escape(r['fout'])}</p>")
            continue
        blokken += (f"<h2>{escape(naam)}</h2><p style='color:#666'>{escape(r['op'].strftime('%d-%m-%Y'))}</p><ul>"
                    + "".join(f"<li>{escape(b.get('tekst', ''))} <a href='{escape(b.get('bron', ''))}' target='_blank' "
                              f"rel='noopener'>bron</a></li>" for b in (r.get("bevindingen") or []))
                    + "</ul>" + ("<p><strong>Voorstellen:</strong></p><ul>" + "".join(
                        f"<li>{escape(v)}</li>" for v in r.get("voorstellen") or []) + "</ul>" if r.get("voorstellen") else "")
                    + (f"<p><strong>Nieuwe mailtekst:</strong> {escape(r['uitdager'])}<br><em>{escape(r.get('uitdager_stand') or '')}</em></p>"
                       if r.get("uitdager") else ""))
    u = va.uitdager()
    winnaar = db.get_instelling(va.SLEUTEL_WINNAAR) or "nog geen (a en b lopen)"
    bord = "".join(f"<tr><td>{escape(r['versie'])}</td><td>{r['verstuurd']}</td><td>{r['doorgeklikt']}</td><td>{r['klant']}</td></tr>"
                   for r in va.scorebord())
    knoppen = "".join(f"<button name='onderwerp' value='{k}' style='padding:6px 12px;margin:0 6px 6px 0'>{escape(v['naam'])}</button>"
                      for k, v in leeragent.ONDERWERPEN.items())
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Leren | Krillo</title><body style='font-family:Arial,sans-serif;max-width:860px;"
            f"margin:40px auto;padding:0 16px;line-height:1.5'><h1>Wat de agents leren</h1>"
            f"<p style='color:#0B7C5E'>{escape(melding)}</p>"
            f"<p>Elke nacht onderzoekt een onderwerp dat 30 dagen niet aan de beurt was, met hun eigen cijfers erbij. "
            f"Een betere mailtekst gaat vanzelf als uitdager naast de huidige en wint alleen als hij aantoonbaar beter "
            f"scoort. Voorstellen die geld kosten of de strategie veranderen komen hier en in het ochtendbericht.</p>"
            f"<form method='post'>Nu onderzoeken: {knoppen}</form>"
            f"<h2>Mail van de verkoopagent</h2><p>Winnaar: <strong>{escape(winnaar)}</strong>. Uitdager: "
            f"{escape(u['versie'] + ': ' + u['tekst']) if u else 'geen'}</p>"
            f"<table cellpadding='5'><tr style='text-align:left'><th>Versie</th><th>Verstuurd</th><th>Doorgeklikt</th>"
            f"<th>Klant</th></tr>{bord or '<tr><td colspan=4>Nog niets verstuurd.</td></tr>'}</table>"
            f"{blokken or '<p>Nog geen onderzoek gedaan. Het eerste komt vannacht.</p>'}</body>")


@app.route("/admin/wereld")
def admin_wereld():
    """Stap 148: het dorp van de agents. Ververst elke minuut vanzelf."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import agentwereld
    return render_template("agentwereld.html", w=agentwereld.stand())


# ---------------------------------------------------------------------------
# VOORSTELLEN TER AKKOORD (1 oktober). Zie voorstellen.py en groeiagent.py.
# Nino tikt in het ochtendbericht op "ja of nee" en komt hier. De link zelf doet
# niets: mailprogramma's en virusscanners openen links vooraf, en die mogen
# niets goedkeuren. Pas de knop (POST) beslist. De lange willekeurige code in
# het adres is de toegang, zodat het vanaf de telefoon zonder inloggen kan.
# ---------------------------------------------------------------------------
def _voorstel_pagina(titel, inhoud):
    from html import escape as _e
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<meta name='robots' content='noindex'><title>{_e(titel)} | Krillo</title>"
            f"<body style='font-family:Arial,sans-serif;max-width:680px;margin:32px auto;padding:0 16px;"
            f"line-height:1.55;color:#111'>{inhoud}</body>")


def _voorstel_blok(v, met_knoppen=True):
    from html import escape as _e
    import groeiagent
    soortnaam = {"actie": "Handeling: gebeurt meteen na akkoord",
                 "taak": "Taak voor jou", "bouwen": "Nieuwe functie: gaat op de bouwlijst voor Claude"}
    stuk = [f"<div style='border:1px solid #ddd;border-radius:10px;padding:14px 16px;margin:0 0 14px'>"
            f"<div style='font-size:12px;color:#666;text-transform:uppercase;letter-spacing:.04em'>"
            f"{_e(soortnaam.get(v['soort'], v['soort']))} &middot; {_e(v.get('bron') or '')}"
            f"{(' &middot; ongeveer ' + str(v['minuten']) + ' min') if v.get('minuten') else ''}</div>"
            f"<h2 style='font-size:18px;margin:6px 0'>{_e(v['titel'])}</h2>"
            f"<p style='margin:0 0 10px'>{_e(v.get('waarom') or '')}</p>"]
    if v.get("bron") == "gidsen":
        stuk.append("<details><summary>Teksten om te plakken</summary><table cellpadding='4'>" + "".join(
            f"<tr><td style='vertical-align:top;color:#666'>{_e(k)}</td><td>{_e(w)}</td></tr>"
            for k, w in groeiagent.AANMELDTEKST.items()) + "</table></details>")
    if met_knoppen:
        knop = ("style='font-size:16px;padding:10px 18px;border-radius:8px;border:1px solid #111;"
                "margin:8px 8px 0 0;cursor:pointer'")
        stuk.append(f"<form method='post' action='/v/{_e(v['token'])}' style='margin:0'>")
        if v["stand"] == "open":
            ja = "Akkoord, ik doe het" if v["soort"] == "taak" else "Akkoord"
            stuk.append(f"<button name='keuze' value='akkoord' {knop[:-1]};background:#111;color:#fff'>{ja}</button>"
                        f"<button name='keuze' value='nee' {knop}>Nee</button>")
            if v["soort"] == "taak":
                stuk.append(f"<button name='keuze' value='gedaan' {knop}>Al gedaan</button>")
        elif v["stand"] == "akkoord" and v["soort"] == "taak":
            stuk.append(f"<button name='keuze' value='gedaan' {knop[:-1]};background:#111;color:#fff'>Gedaan</button>")
        stuk.append("</form>")
    stuk.append("</div>")
    return "".join(stuk)


@app.route("/v/<token>", methods=["GET", "POST"])
def voorstel_beslissen(token):
    import voorstellen
    from html import escape as _e
    v = voorstellen.bij_token(token)
    if not v:
        return _voorstel_pagina("Voorstel", "<h1>Dit voorstel bestaat niet (meer)</h1>"), 404
    melding = ""
    if request.method == "POST":
        gelukt, melding = voorstellen.beslis(token, (request.form.get("keuze") or "").strip())
        v = voorstellen.bij_token(token)
        melding = (f"<p style='padding:10px 14px;border-radius:8px;background:"
                   f"{'#e8f5e9' if gelukt else '#fdecea'}'>{_e(melding)}</p>")
    return _voorstel_pagina("Voorstel", melding + _voorstel_blok(v) +
                            "<p><a href='/admin/voorstellen'>Alle voorstellen</a></p>")


@app.route("/admin/klantblik")
def admin_klantblik():
    """Wat de klantblik vond (klantblik.py). Met ?nu=ja draait hij meteen."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import klantblik
    from html import escape as _e
    if request.args.get("nu") == "ja":
        threading.Thread(target=klantblik.draai, args=(app,), daemon=True).start()
        return redirect("/admin/klantblik?gestart=ja")
    uit = klantblik.laatste()
    stuk = ["<h1>Klantblik</h1><p>Elke ochtend rond zes uur loopt Krillo alle pagina's na zoals een klant ze "
            "ziet: de openbare site, de demo, ranglijsten en winkelpagina's, en het dashboard van je testwinkels. "
            "Hij volgt elke link en zoekt naar wat een klant als fout ziet. Fouten staan in het ochtendbericht.</p>"]
    if request.args.get("gestart") == "ja":
        stuk.append("<p><strong>Gestart.</strong> Ververs over een minuut of twee.</p>")
    if not uit.get("op"):
        stuk.append("<p>Hij heeft nog niet gedraaid.</p>")
    else:
        stuk.append(f"<p>Laatst: {_e(uit['op'])}. {uit.get('paginas', 0)} pagina's gelezen, {uit.get('links', 0)} "
                    f"adressen nagekeken, in {uit.get('duur', '?')} seconden.</p>")
        for ernst, kop in (("fout", "Fouten"), ("waarschuwing", "Twijfelgevallen")):
            rijen = uit.get(ernst) or []
            stuk.append(f"<h2>{kop} ({len(rijen)})</h2>")
            if not rijen:
                stuk.append("<p>Geen.</p>")
                continue
            stuk.append("<ul>" + "".join(
                f"<li style='margin-bottom:6px'>{_e(f['tekst'])} <span style='color:#666'>(op {f['aantal']} "
                f"pagina's: " + ", ".join(f"<a href='{_e(p)}'>{_e(p[:60])}</a>" for p in f["paginas"][:4])
                + ")</span></li>" for f in rijen) + "</ul>")
        import proefaankoop
        pa = proefaankoop.laatste()
        if pa.get("op"):
            stuk.append(f"<h2>Proefaankoop ({_e(pa['op'])})</h2><p>Een nepklant koopt elke ochtend Watch, door de "
                        f"echte code (zonder factuur, abonnement of mail naar buiten).</p><ul>"
                        + "".join(f"<li style='color:#B42318'>{_e(f)}</li>" for f in pa.get("fout") or [])
                        + "".join(f"<li>{_e(g)}</li>" for g in pa.get("goed") or []) + "</ul>")
        tekst = klantblik.tekst_voor_claude(uit)
        if tekst:
            stuk.append("<h2>Voor Claude</h2><textarea readonly rows='10' style='width:100%;font-family:monospace;"
                        "font-size:13px'>" + _e(tekst) + "</textarea>")
    stuk.append("<p><a href='/admin/klantblik?nu=ja'>Nu nalopen</a></p>")
    return _voorstel_pagina("Klantblik", "".join(stuk))


@app.route("/admin/snelmeting")
def admin_snelmeting():
    """Stap 198: de snelmeting van een klant bekijken, en met ?nu=ja meteen draaien."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import snelmeting
    from html import escape as _e
    url = scan_engine.normalize_url((request.args.get("url") or "").strip()) if request.args.get("url") else ""
    stuk = ["<h1>Snelmeting</h1><p>Elke week, op de vaste meetdag van de klant, de vijf belangrijkste vragen "
            "opnieuw aan ChatGPT en Gemini (eerst de gekozen vragen, dan de verloren, dan de gewonnen). "
            "Ongeveer 10 tot 15 cent per klant per week.</p>"
            "<form method='get'><input name='url' placeholder='bijvoorbeeld sounds.nl' size='30' required> "
            "<button>Bekijken</button></form>"]
    if url:
        if request.args.get("nu") == "ja":
            threading.Thread(target=snelmeting.meet, args=(url,), daemon=True).start()
            return redirect(f"/admin/snelmeting?url={quote(url)}&gestart=ja")
        if request.args.get("gestart") == "ja":
            stuk.append("<p><strong>Gestart.</strong> Ververs over een minuut.</p>")
        vragen = snelmeting.vragen_voor(url)
        stuk.append(f"<h2>{_e(url)}</h2><p>Meetdag: {['maandag', 'dinsdag', 'woensdag', 'donderdag', 'vrijdag', 'zaterdag', 'zondag'][meetdag(url)]}. "
                    f"De vijf vragen nu:</p><ol>" + "".join(f"<li>{_e(v)}</li>" for v in vragen) + "</ol>"
                    + ("" if vragen else "<p>Geen: deze winkel staat nog in geen ranglijst.</p>"))
        o = snelmeting.overzicht(url)
        if o:
            stuk.append(f"<p>Laatste: {_e(str(o['op'])[:16])}, genoemd in {o['genoemd']} van {o['van']} antwoorden"
                        + (f" (de keer ervoor {o['vorige_genoemd']} van {o['vorige_van']})" if o.get('vorige_van') else "")
                        + ".</p><ul>" + "".join(
                            f"<li>{_e(v['vraag'])}: " + ", ".join(
                                f"{_e(a['naam'])} {'ja' if a['genoemd'] else 'nee'}" for a in v["assistenten"]) + "</li>"
                            for v in o["vragen"]) + "</ul>")
        stuk.append(f"<p><a href='/admin/snelmeting?url={quote(url)}&nu=ja'>Nu meten</a> (kost ongeveer 10 tot 15 cent)</p>")
    return _voorstel_pagina("Snelmeting", "".join(stuk))


@app.route("/admin/voorstellen", methods=["GET"])
def admin_voorstellen():
    """Alle open voorstellen, de lopende taken, de bouwlijst en wat er besloten is."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import voorstellen
    import groeiagent
    from html import escape as _e
    open_v = voorstellen.open_voorstellen()
    lopend = voorstellen.lopende_taken()
    bouw = voorstellen.bouwlijst()
    verslag = groeiagent.laatste_verslag()
    stuk = ["<h1>Voorstellen</h1><p>Wat de agents willen doen. Een handeling gebeurt meteen na akkoord; een "
            "taak is voor jou; een nieuwe functie gaat op de bouwlijst en Claude bouwt hem.</p>"]
    stuk.append(f"<h2>Open ({len(open_v)})</h2>" + ("".join(_voorstel_blok(v) for v in open_v)
                                                     or "<p>Niets open.</p>"))
    if lopend:
        stuk.append(f"<h2>Taken waar je ja op zei ({len(lopend)})</h2>" + "".join(_voorstel_blok(v) for v in lopend))
    stuk.append(f"<h2>Bouwlijst voor Claude ({len(bouw)})</h2>")
    if bouw:
        stuk.append("<p>Kopieer dit en plak het in je gesprek met Claude:</p><textarea readonly rows='8' "
                    "style='width:100%;font-family:monospace;font-size:13px'>"
                    + _e(voorstellen.tekst_voor_claude(bouw)) + "</textarea>")
    else:
        stuk.append("<p>Leeg.</p>")
    if verslag.get("op"):
        stuk.append(f"<h2>De groeiagent</h2><p>Laatst gekeken: {_e(verslag['op'].replace('T', ' om '))}. Hij kijkt elke "
                    f"{groeiagent.ELKE_UREN} uur overdag. Nieuw de vorige keer: "
                    f"{_e(', '.join(verslag.get('nieuw') or []) or 'niets')}.</p>")
    oud = voorstellen.geschiedenis()
    if oud:
        stuk.append("<h2>Besloten</h2><table cellpadding='5' style='border-collapse:collapse;font-size:14px'>"
                    + "".join(f"<tr><td>{_e(str(r.get('besloten_op') or '')[:16])}</td><td>{_e(r['stand'])}</td>"
                              f"<td>{_e(r['titel'])}</td><td style='color:#666'>{_e(r.get('uitkomst') or '')}</td></tr>"
                              for r in oud) + "</table>")
    return _voorstel_pagina("Voorstellen", "".join(stuk))


# ---------------------------------------------------------------------------
# HET BEHEERPORTAAL (30 september). Nino: "nu is het teveel pagina's waar ik
# niet snel even bij kan vanuit 1 portaal". Er waren 40 beheerpagina's en geen
# beginpagina: je moest de adressen onthouden. Nu is /admin de ingang, met
# alles per onderwerp, een zoekveld, en bovenaan wat er nu te doen is. En elke
# beheerpagina krijgt bovenaan een balk terug naar het portaal.
#
# De lijst staat hier op EEN plek. test_beheerportaal kijkt of elke
# beheerpagina erin staat, zodat een nieuwe pagina niet stil ontbreekt.
# ---------------------------------------------------------------------------
BEHEER_GROEPEN = [
    # 7 oktober (Nino: "teveel pagina's, veel kan samen"): wat je elke dag nodig
    # hebt bovenaan; de rest ingeklapt onder "Minder vaak nodig".
    ("Elke dag", [
        ("/admin/ochtendbericht", "Ochtendbericht", "Het bericht van vanochtend, nu bekijken"),
        ("/admin/bezoek", "Trechter en bezoek", "Per dag: van bezoek tot betaald, en de koude mail"),
        ("/admin/bezoekers", "Gratis checks", "Handmatige checks die wachten, mislukte checks, herkomst"),
        ("/admin/benadering", "Benadering", "De lijst, de rem, en wat de mails opleveren"),
        ("/admin/antwoorden", "Antwoorden", "Wie terugmailde, met een concept-antwoord"),
        ("/admin/verkoop", "Verkoopagent", "Opvolgingen goedkeuren of overslaan"),
        ("/admin/voorstellen", "Voorstellen", "Ja of nee op wat de agents willen doen, en de bouwlijst voor Claude"),
        ("/admin/kosten", "Kosten", "Wat de metingen en modellen kosten"),
    ]),
    ("Klanten", [
        ("/admin/bestellingen", "Bestellingen", "Wie betaald heeft"),
        ("/admin/snelmeting", "Snelmeting", "De wekelijkse meting van de vijf belangrijkste vragen per klant"),
        ("/admin/uitvoeringen", "Werklijst Fix", "Wat wij in winkels van klanten doen"),
        ("/admin/werkbriefje", "Werkbriefje", "Wat jij precies doet in de winkel van een klant"),
        ("/admin/oplevering", "Oplevering", "Het overzicht dat de klant krijgt als het klaar is"),
        ("/admin/oplossingen", "Kant-en-klare teksten", "De teksten van het actieplan los schrijven"),
        ("/admin/voorbeeld", "Klantpagina bekijken", "De klantpagina voor een winkel naar keuze"),
        ("/admin/shopify", "Shopify-app", "Welke winkels de app hebben"),
        ("/admin/wordpress", "WordPress-winkels", "Fix in gekoppelde WooCommerce-winkels"),
        ("/admin/doorverwijzen", "Partners", "Partneraanvragen goedkeuren"),
    ]),
    ("Meer klanten vinden", [
        ("/admin/formulieren", "Contactformulieren", "Winkels zonder info@, bericht staat klaar"),
        ("/admin/onderzoeksmail", "Onderzoeksmail", "Gemeten winkels met hun eigen uitkomst"),
        ("/admin/bureaus", "Bureaus", "Webbureaus uit de voettekst van winkels"),
        ("/admin/merkaanvragen", "Merkaanvragen", "Aanvragen via /agencies"),
        ("/admin/wachtlijst", "Wachtlijst per land", "Welke landen wachten, en hoeveel"),
        ("/admin/linkedin", "LinkedIn", "Posts van de LinkedIn-agent met plaatje"),
        ("/admin/persbericht", "Persbericht", "Klaar om te kopieren"),
        ("/admin/lijstjes", "Lijstjes", "Wat de lijstjesagent vond en mailde"),
        ("/admin/artikelen", "Artikelen", "Concepten van de artikelagent nakijken en plaatsen"),
    ]),
    ("Index", [
        ("/admin/ranglijst", "Ranglijst", "Een categorie meten en bekijken"),
        ("/admin/categorieen", "Categorieen", "Winkels indelen en tellen"),
        ("/admin/opschonen", "Opschonen", "De winkellijst schoon voor publicatie"),
        ("/admin/metingen", "Metingen", "Wat de modellen antwoordden"),
        ("/admin/koopvragen", "Koopvragen", "De vragen per webshop"),
    ]),
    ("Minder vaak nodig", [
        ("/admin/klantblik", "Klantblik", "Alle pagina's nagelopen zoals een klant ze ziet: wat er niet klopt"),
        ("/admin/agents", "Commandocentrum", "Alle agents met hun schakelaars"),
        ("/admin/controle", "Nachtcontrole", "Wat de controleagent vond, en nu draaien"),
        ("/admin/traag", "Trage pagina's", "Welke pagina's traag waren, en waarom"),
        ("/admin/merken", "Merken en platforms", "Wat het opschonen als merk aanmerkte"),
        ("/admin/beoordelingen", "Beoordelingen", "Wat er uit de antwoorden gehaald is"),
        ("/admin/benchmark", "Benchmark", "Alle gemeten winkels bij elkaar"),
        ("/admin/bronnen", "Bronnen", "Welke externe pagina's gevonden zijn"),
        ("/admin/modellen", "Modellen", "Werken de ingestelde modelnamen nog"),
        ("/admin/demo", "Demo-uitkomsten", "De volledige meting voor een niet-klant"),
        ("/admin/leren", "Leeragent", "Wat de agents onderzochten en doorvoerden"),
        ("/admin/wereld", "Agentendorp", "Het dorp van de agents, ververst vanzelf"),
    ]),
]


@app.route("/admin")
@app.route("/admin/")
def admin_portaal():
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return redirect("/admin/inloggen?verder=/admin")
    if doorsturen:
        return redirect(doorsturen)
    tegels = ""
    for groep, paginas in BEHEER_GROEPEN:
        items = "".join(
            f"<a class='tegel' href='{pad}' data-zoek='{escape((naam + ' ' + uitleg + ' ' + pad).lower())}'>"
            f"<b>{escape(naam)}</b><span>{escape(uitleg)}</span></a>" for pad, naam, uitleg in paginas)
        if groep == "Minder vaak nodig":
            tegels += (f"<section><details><summary><h2 style='display:inline'>{escape(groep)}</h2></summary>"
                       f"<div class='raster'>{items}</div></details></section>")
        else:
            tegels += f"<section><h2>{escape(groep)}</h2><div class='raster'>{items}</div></section>"
    # Wat er te doen is komt los binnen (fetch): het zijn een stuk of tien
    # tellingen in de database, en het portaal zelf moet meteen open staan.
    return ("<!doctype html><html lang='nl'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'><title>Beheer | Krillo</title>"
            "<style>body{font-family:Arial,sans-serif;margin:0;background:#f6f7f9;color:#111}"
            ".binnen{max-width:1100px;margin:0 auto;padding:28px 16px 60px}"
            "h1{font-size:28px;margin:0 0 4px}h2{font-size:13px;letter-spacing:.08em;text-transform:uppercase;"
            "color:#6b7280;margin:28px 0 10px}"
            "#zoek{width:100%;box-sizing:border-box;font-size:17px;padding:12px 14px;border:1px solid #d6d9df;"
            "border-radius:10px;margin:14px 0 4px}"
            ".raster{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:10px}"
            ".tegel{display:block;background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;"
            "text-decoration:none;color:inherit}.tegel:hover{border-color:#1d4ed8}"
            ".tegel b{display:block;font-size:15px;margin-bottom:3px}.tegel span{font-size:13px;color:#6b7280}"
            "#tedoen{background:#fff;border:1px solid #e5e7eb;border-left:4px solid #1d4ed8;border-radius:10px;"
            "padding:12px 16px;margin-top:18px}#tedoen li{margin:6px 0}#tedoen a{color:#1d4ed8}"
            ".stil{color:#6b7280;font-size:14px}</style><body><div class='binnen'>"
            "<h1>Beheer</h1><div class='stil'>Alle beheerpagina's op een plek. Typ om te zoeken.</div>"
            "<input id='zoek' placeholder='Zoek een pagina, bijvoorbeeld mail, linkedin, kosten' autofocus>"
            "<div id='tedoen'><b>Nu te doen</b><div class='stil' id='tedoenLijst'>Even ophalen...</div></div>"
            f"{tegels}"
            "<p class='stil' style='margin-top:30px'><a href='/'>Naar de site</a> &middot; "
            "<a href='/admin/uitloggen'>Uitloggen</a></p></div>"
            "<script>"
            "var z=document.getElementById('zoek');z.addEventListener('input',function(){var q=z.value.toLowerCase().trim();"
            "document.querySelectorAll('details').forEach(function(d){d.open=!!q});"
            "document.querySelectorAll('.tegel').forEach(function(t){t.style.display=!q||t.dataset.zoek.indexOf(q)>-1?'':'none'});"
            "document.querySelectorAll('section').forEach(function(s){var z2=[].some.call(s.querySelectorAll('.tegel'),"
            "function(t){return t.style.display!=='none'});s.style.display=z2?'':'none'})});"
            "z.addEventListener('keydown',function(e){if(e.key==='Enter'){var t=[].find.call(document.querySelectorAll('.tegel'),"
            "function(t){return t.style.display!=='none'});if(t)location=t.href}});"
            "fetch('/admin/te-doen.json').then(function(r){return r.json()}).then(function(d){var l=document.getElementById('tedoenLijst');"
            "if(!d.lijst||!d.lijst.length){l.textContent='Niets dat op jou wacht.';return}"
            "l.className='';var ul=document.createElement('ul');d.lijst.forEach(function(i){var li=document.createElement('li');"
            "var a=document.createElement('a');a.href=i.link;a.textContent=i.tekst;li.appendChild(a);ul.appendChild(li)});"
            "l.textContent='';l.appendChild(ul)}).catch(function(){document.getElementById('tedoenLijst').textContent="
            "'Kon het lijstje niet ophalen. Het ochtendbericht heeft het ook.'})"
            "</script></body></html>")


@app.route("/admin/te-doen.json")
def admin_te_doen():
    mag, _ = _mag_bij_beheer()
    if not mag:
        return jsonify({"lijst": []}), 403
    import ochtendbericht
    basis = get_base_url().rstrip("/")
    try:
        lijst = [{"tekst": t, "link": (l[len(basis):] if l and l.startswith(basis) else l) or "/admin"}
                 for t, l in ochtendbericht.te_doen(basis)]
    except Exception as e:
        print(f"Te doen voor het portaal mislukt: {e}")
        lijst = []
    return jsonify({"lijst": lijst})


@app.after_request
def _beheerbalk(antwoord):
    """Een smalle balk boven elke beheerpagina, terug naar /admin.

    Na de start van de body gezet, zodat de pagina zelf niet verandert. Niet op
    het portaal zelf, het inlogscherm, plaatjes en JSON."""
    try:
        pad = request.path
        if (not pad.startswith("/admin/") or pad in ("/admin/", "/admin/inloggen", "/admin/uitloggen")
                or antwoord.status_code != 200 or antwoord.direct_passthrough
                or not (antwoord.mimetype or "").startswith("text/html")):
            return antwoord
        html = antwoord.get_data(as_text=True)
        m = re.search(r"<body[^>]*>", html, flags=re.I)
        if not m or "id='beheerbalk'" in html:
            return antwoord
        balk = ("<div id='beheerbalk' style='position:sticky;top:0;z-index:9999;background:#111;color:#fff;"
                "font:14px Arial,sans-serif;padding:8px 16px;display:flex;gap:14px;align-items:center'>"
                "<a href='/admin' style='color:#fff;font-weight:bold;text-decoration:none'>&larr; Beheer</a>"
                "<a href='/admin/ochtendbericht' style='color:#cbd5e1;text-decoration:none'>Ochtendbericht</a>"
                "<a href='/admin/benadering' style='color:#cbd5e1;text-decoration:none'>Benadering</a>"
                "<a href='/admin/antwoorden' style='color:#cbd5e1;text-decoration:none'>Antwoorden</a>"
                "<a href='/admin/linkedin' style='color:#cbd5e1;text-decoration:none'>LinkedIn</a>"
                "<a href='/admin/wordpress' style='color:#cbd5e1;text-decoration:none'>WordPress</a></div>")
        antwoord.set_data(html[:m.end()] + balk + html[m.end():])
    except Exception:
        pass
    return antwoord


# ---------------------------------------------------------------------------
# STAP 87 (30 september): WordPress en WooCommerce koppelen, zodat Fix daar
# net zo werkt als in Shopify. De klant geeft een applicatiewachtwoord (nooit
# zijn gewone wachtwoord), wij controleren het en bewaren het versleuteld.
# Nino doet het werk op /admin/wordpress: voorstellen maken, nakijken,
# toepassen, en alles kan terug. Zie wordpress_werk.py.
# ---------------------------------------------------------------------------
@app.route("/mijn/<klant_token>/wordpress", methods=["GET", "POST"])
def klant_wordpress(klant_token):
    import wordpress_werk
    klant = db.get_klant(klant_token)
    if not klant:
        return redirect("/login")
    url = klant["webshop_url"]
    melding, fout = None, None
    if request.method == "POST":
        if request.form.get("actie") == "los":
            db.wis_koppeling(url)
            melding = "Disconnected. Also revoke the application password in WordPress: Users, Profile."
        else:
            uit = wordpress_werk.koppel(url, request.form.get("site"), request.form.get("gebruiker"),
                                        request.form.get("wachtwoord"))
            if uit["gelukt"]:
                melding = "Connected. We check your store and make the first changes within two working days."
                _meld_aan_beheer("WordPress gekoppeld", f"{url} koppelde WordPress. Aan de slag op /admin/wordpress.")
            else:
                fout = uit["fout"]
    k = db.get_koppeling(url)
    gekoppeld = bool(k and k.get("platform") == wordpress_werk.PLATFORM and k.get("stand") == "werkt")
    e = escape
    berichten = ((f"<p style='color:#0B7C5E'>{e(melding)}</p>" if melding else "")
                 + (f"<p style='color:#B42318'>{e(fout)}</p>" if fout else ""))
    formulier = (
        f"<p><b>Connected</b> to {e(k['basis_url'])}. You can revoke access at any time.</p>"
        f"<form method='post'><button name='actie' value='los'>Disconnect</button></form>" if gekoppeld else
        "<ol><li>In WordPress, go to <b>Users</b>, <b>Profile</b>.</li>"
        "<li>Scroll to <b>Application Passwords</b>, type the name <b>Krillo</b> and click <b>Add New Application "
        "Password</b>.</li><li>Copy the password WordPress shows (it looks like xxxx xxxx xxxx xxxx) and paste it "
        "below. This is not your login password: it only works for this connection and you can revoke it with "
        "one click.</li></ol>"
        "<form method='post' style='display:grid;gap:10px;max-width:460px'>"
        f"<label>Store address<br><input name='site' value='{e(url)}' style='width:100%;padding:8px'></label>"
        "<label>WordPress username<br><input name='gebruiker' autocomplete='off' style='width:100%;padding:8px'></label>"
        "<label>Application password<br><input name='wachtwoord' type='password' autocomplete='off' "
        "style='width:100%;padding:8px'></label>"
        "<button style='padding:10px;background:#1B3FE0;color:#fff;border:0;border-radius:8px'>Connect</button></form>")
    return (f"<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<meta name='robots' content='noindex'><title>Connect WordPress | Krillo</title>"
            f"<body style='font-family:Arial,sans-serif;max-width:640px;margin:40px auto;padding:0 16px;line-height:1.55'>"
            f"<p><a href='/mijn/{e(klant_token)}'>&larr; Your dashboard</a></p>"
            f"<h1>Connect your WooCommerce store</h1>"
            f"<p>With this connection we make the Fix changes in your store for you: descriptions for product "
            f"photos, product texts where they are missing, and a questions page. We save what was there before, "
            f"so every change can be undone.</p>"
            f"{berichten}{formulier}</body></html>")


@app.route("/admin/wordpress", methods=["GET", "POST"])
def admin_wordpress():
    """Het werk in gekoppelde WooCommerce-winkels: voorstellen, toepassen, terugzetten."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import json as _json
    import wordpress_werk
    url = (request.values.get("url") or "").strip()
    melding = ""
    sleutel = f"wp_voorstellen:{url}"
    if request.method == "POST" and request.form.get("actie") == "koppel":
        # 30 september: Nino koppelt zelf, voor de proef of voor een Fix-klant
        # die het liever samen doet. Het wachtwoord typt hij hier, nooit in een
        # mail of chat; het gaat versleuteld de database in.
        doel = url or scan_engine.normalize_url(request.form.get("site") or "")
        uit = wordpress_werk.koppel(doel, request.form.get("site"), request.form.get("gebruiker"),
                                    request.form.get("wachtwoord"))
        melding = "Gekoppeld. Klik nu op Winkel nalopen en voorstellen maken." if uit["gelukt"] else uit["fout"]
        return redirect(f"/admin/wordpress?url={quote(doel)}&m={quote(melding)}")
    if request.method == "POST" and url:
        winkel = wordpress_werk.winkel_van(url)
        actie = request.form.get("actie")
        if not winkel:
            melding = "Geen werkende koppeling voor deze winkel."
        elif actie == "voorstellen":
            try:
                uit = winkel.maak_voorstellen()
                db.zet_instelling(sleutel, _json.dumps(uit["voorstellen"]))
                melding = (f"{len(uit['voorstellen'])} voorstel(len). {uit['aantallen']['zonder_alt']} foto's zonder "
                           f"beschrijving, {uit['aantallen']['dunne_tekst']} dunne productteksten."
                           + (f" Fouten: {'; '.join(uit['fouten'])}" if uit["fouten"] else ""))
            except wordpress_werk.Fout as e:
                melding = str(e)
        elif actie in ("toepassen", "alles"):
            voorstellen = _json.loads(db.get_instelling(sleutel) or "[]")
            kies = request.form.get("id")
            gedaan, mis = 0, []
            for v in voorstellen:
                if actie == "toepassen" and v["id"] != kies:
                    continue
                uit = winkel.pas_toe(v, url)
                if uit["gelukt"]:
                    gedaan += 1
                    v["klaar"] = True
                else:
                    mis.append(f"{v.get('waar')}: {uit.get('fout')}")
            db.zet_instelling(sleutel, _json.dumps(voorstellen))
            melding = f"{gedaan} toegepast." + (f" Niet gelukt: {' | '.join(mis[:5])}" if mis else "")
        elif actie == "terug":
            w = next((w for w in db.get_wijzigingen(url) if w.get("taak_id") == request.form.get("id")), None)
            uit = winkel.zet_terug(w, klant_url=url) if w else {"gelukt": False, "fout": "Niet gevonden."}
            melding = "Teruggezet." if uit["gelukt"] else f"Terugzetten mislukt: {uit['fout']}"
        return redirect(f"/admin/wordpress?url={quote(url)}&m={quote(melding)}")
    melding = request.args.get("m") or ""
    e = escape
    melding_html = (f"<p style='background:#E8F6EF;padding:10px 14px;border-radius:8px'>{e(melding)}</p>"
                    if melding else "")
    winkels = wordpress_werk.gekoppelde_winkels()
    lijst = "".join(f"<li><a href='/admin/wordpress?url={quote(w['webshop_url'])}'>{e(w['webshop_url'])}</a> "
                    f"({e(w['stand'] or '')})</li>" for w in winkels) or "<li>Nog geen gekoppelde winkels.</li>"
    werk = ""
    if url:
        voorstellen = _json.loads(db.get_instelling(sleutel) or "[]")
        rijen = "".join(
            f"<tr><td>{e(v.get('wat') or '')}</td><td><a href='{e(v.get('link') or '')}' target='_blank'>"
            f"{e(v.get('waar') or '')}</a></td><td style='max-width:420px'>{e((v.get('nieuw') or '')[:300])}</td><td>"
            + ("Klaar" if v.get("klaar") else
               f"<form method='post'><input type='hidden' name='url' value='{e(url)}'>"
               f"<input type='hidden' name='id' value='{e(v['id'])}'><button name='actie' value='toepassen'>"
               f"Toepassen</button></form>") + "</td></tr>" for v in voorstellen)
        gedaan = "".join(
            f"<tr><td>{e(w.get('wat') or '')}</td><td>{e(w.get('waar') or '')}</td><td>"
            f"<form method='post'><input type='hidden' name='url' value='{e(url)}'>"
            f"<input type='hidden' name='id' value='{e(w['taak_id'])}'><button name='actie' value='terug'>"
            f"Terugzetten</button></form></td></tr>"
            for w in db.get_wijzigingen(url) if (w.get("taak_id") or "").startswith("wp:"))
        werk = (f"<h2>{e(url)}</h2><form method='post'><input type='hidden' name='url' value='{e(url)}'>"
                f"<button name='actie' value='voorstellen'>Winkel nalopen en voorstellen maken</button> "
                f"<button name='actie' value='alles'>Alle voorstellen toepassen</button></form>"
                f"<h3>Voorstellen</h3><table cellpadding='6'>{rijen or '<tr><td>Nog geen.</td></tr>'}</table>"
                f"<h3>Gedaan (kan terug)</h3><table cellpadding='6'>{gedaan or '<tr><td>Nog niets.</td></tr>'}</table>")
    koppelvak = ("<h2>Een winkel koppelen</h2><p>Voor de proef of voor een klant. Vul het adres van de "
                 "WordPress-site in, de gebruikersnaam, en het applicatiewachtwoord (WordPress: Gebruikers, "
                 "Profiel, Applicatiewachtwoorden). Winkeladres alleen invullen als het anders is dan de site.</p>"
                 "<form method='post' style='display:grid;gap:8px;max-width:460px'><input type='hidden' name='actie' "
                 "value='koppel'><input name='site' placeholder='https://jouwtestsite.s1-tastewp.com' required>"
                 "<input name='gebruiker' placeholder='Gebruikersnaam' autocomplete='off' required>"
                 "<input name='wachtwoord' type='password' placeholder='Applicatiewachtwoord' autocomplete='off' required>"
                 "<input name='url' placeholder='Winkeladres van de klant (mag leeg)'>"
                 "<button>Koppelen</button></form>")
    return (f"<!doctype html><meta charset='utf-8'><title>WordPress | Krillo</title>"
            f"<body style='font-family:system-ui;max-width:1100px;margin:30px auto;padding:0 16px'>"
            f"<h1>WordPress en WooCommerce</h1>"
            f"{melding_html}"
            f"<p>Klanten koppelen zelf via hun dashboard (/mijn/&lt;link&gt;/wordpress) met een applicatiewachtwoord. "
            f"Hier loop je hun winkel na, kijk je de voorstellen na en zet je ze erin. Alles kan terug.</p>"
            f"<ul>{lijst}</ul>{werk}{koppelvak}</body>")


def _cpu_deel():
    """Hoeveel processor de server mag gebruiken, uit de instellingen van de
    container zelf (cgroup). 0.1 betekent een tiende van een processor. None
    als het niet te lezen is."""
    try:
        with open("/sys/fs/cgroup/cpu.max") as f:
            quota, periode = f.read().split()[:2]
        if quota != "max":
            return round(int(quota) / int(periode), 2)
    except Exception:
        pass
    try:
        with open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us") as f:
            quota = int(f.read().strip())
        with open("/sys/fs/cgroup/cpu/cpu.cfs_period_us") as f:
            periode = int(f.read().strip())
        if quota > 0:
            return round(quota / periode, 2)
    except Exception:
        pass
    return None


def _rekenkracht_zin():
    """30 september: het tweede deel van de traagheid. Het gratis pakket van
    Render geeft een fractie van een processor. Het opbouwen van een pagina dat
    bij ons 0,3 seconde kost, kost daar dan seconden, en de achtergrondtaken
    (metingen, benadering) delen diezelfde fractie. Dit laat zien wat de server
    echt heeft, zodat het geen gok is."""
    deel = _cpu_deel()
    if deel is None:
        return "Niet uit te lezen op deze server."
    if deel < 0.5:
        return (f"{deel:g} processor. Dat is heel weinig: elke pagina en elke achtergrondtaak "
                f"deelt dit. Zet de webservice in Render op Starter (0,5) of beter Standard (1).")
    if deel < 1:
        return f"{deel:g} processor. Werkbaar; Standard (1 processor) maakt de pagina's nog vlotter."
    return f"{deel:g} processor. Genoeg."


@app.route("/admin/traag")
def admin_traag():
    """Welke pagina's traag waren sinds de laatste start (29 september)."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    t = traag_overzicht()
    # De afstand tot de database (30 september). Dit is de grootste knop: een
    # pagina doet tientallen vragen, en elke vraag kost een paar reizen.
    reis = db.reistijd_ms()
    if reis is None:
        reis_zin = "De database gaf geen antwoord, dus de afstand is niet gemeten."
    elif reis <= 10:
        reis_zin = (f"Een reis naar de database duurt {reis:g} ms. Dat is goed: de site en "
                    f"de database staan dicht bij elkaar.")
    elif reis <= 40:
        reis_zin = (f"Een reis naar de database duurt {reis:g} ms. Dat kan beter: zet de "
                    f"webservice in Render in dezelfde regio als de database in Neon (Frankfurt).")
    else:
        reis_zin = (f"Een reis naar de database duurt {reis:g} ms. Dat is te ver weg en "
                    f"de hoofdoorzaak van trage pagina's: de site en de database staan in "
                    f"verschillende delen van de wereld. Zet de webservice in Render in de "
                    f"regio Frankfurt, net als de database in Neon.")
    cpu_zin = escape(_rekenkracht_zin())
    rijen = "".join(f"<tr><td>{escape(p['pad'])}</td><td>{p['keer']}</td><td>{p['max']} s</td>"
                    f"<td>{p.get('vragen', 0)}</td><td>{p.get('db_sec', 0)} s</td><td>{p.get('los', 0)}</td>"
                    f"<td>{p.get('na_start', 0)}</td><td>{escape(p['laatst'])}</td></tr>"
                    for p in t["paden"])
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Traag | Krillo</title><body style='font-family:Arial,sans-serif;max-width:800px;"
            f"margin:40px auto;padding:0 16px;line-height:1.5'><h1>Trage pagina's</h1>"
            f"<p>Sinds de laatste start: {t['totaal']} verzoeken, waarvan {t['traag']} van {TRAAG_SECONDEN:g} "
            f"seconden of langer. Na een deploy begint de telling opnieuw.</p>"
            f"<p id='reistijd'><b>Afstand tot de database:</b> {escape(reis_zin)}</p>"
            f"<p id='rekenkracht'><b>Rekenkracht van de server:</b> {cpu_zin}</p>"
            f"<p id='geheugen'><b>Geheugen en de nacht:</b> {escape(_nachtregel())}</p>"
            f"<p>Bij het langste verzoek: hoeveel databasevragen, hoeveel tijd daarvan in de database zat, "
            f"en hoeveel losse verbindingen nodig waren (0 is goed). 'Vlak na start' telt de keren "
            f"binnen twee minuten na het opstarten: dan was de server net wakker.</p>"
            f"<div style='overflow-x:auto'><table cellpadding='6'><tr style='text-align:left'><th>Pagina</th>"
            f"<th>Keer traag</th><th>Langste</th><th>Vragen</th><th>Database</th><th>Los</th>"
            f"<th>Vlak na start</th><th>Laatst</th></tr>"
            f"{rijen or '<tr><td colspan=8>Niets traags gezien.</td></tr>'}</table></div></body>")


@app.route("/sitemap.xml")
def sitemap_xml():
    # Uit het geheugen (29 september): het opbouwen vraagt elke ranglijst op,
    # en een zoekmachine die de sitemap ophaalde liet de hele site wachten.
    return Response(sitemap_inhoud(), mimetype="application/xml")


def sitemap_inhoud():
    return _bewaard(("sitemap",), _bouw_sitemap)


def _bouw_sitemap():
    # Een sitemap zonder lastmod dwingt een zoekmachine om elke pagina steeds
    # opnieuw op te halen om te zien of er iets veranderd is. Met een datum
    # erbij weet hij meteen wat nieuw is, en dat is precies wat je wil op het
    # moment dat je artikelen toevoegt.
    nieuwste = max([a["datum"] for a in artikelen.alle()] or ["2026-08-01"])
    # /uitkomst/<token> staat hier BEWUST niet in. Die pagina's gaan over één
    # winkel met naam en toenaam en horen niet in Google.
    vast = ["/", "/articles", "/how-we-measure", "/faq",
            "/index", "/demo", "/about", "/proof", "/terms", "/privacy",
            "/withdrawal", "/tools", "/compare", "/partners", "/changelog"]
    import trackerpaginas
    vast += [f"/{slug}" for slug in trackerpaginas.PAGINAS]
    regels = [(p, nieuwste) for p in vast]
    # Het nieuws per gemeten land, uit markten.py (niet meer vast nl en be).
    regels += [(f"/news/{land}", nieuwste) for land in markten.index_landen()]
    regels += [(f"/articles/{a['slug']}", a["datum"]) for a in artikelen.alle()]
    # Stap 162 en 163: de gratis tools en de vergelijkingen.
    import gratistools
    import vergelijkingen
    regels += [(f"/tools/{t}", nieuwste) for t in gratistools.TOOLS]
    regels += [(f"/compare/{t}", vergelijkingen.TOOLS[t].get("gekeken") or vergelijkingen.GEKEKEN)
               for t in vergelijkingen.TOOLS]
    # De categoriepagina's van de index, met hun EIGEN meetdatum. Dat is niet
    # cosmetisch: een zoekmachine ziet daaraan dat de pagina van vorige maand
    # veranderd is, en haalt hem opnieuw op. Zonder datum zou hij moeten gokken.
    #
    # Ze staan hier los van de vaste pagina's omdat ze komen en gaan: een
    # categorie verschijnt zodra hij gemeten is en genoeg winkels heeft. Deze
    # lijst leest dus elke keer wat er echt staat en niet wat er ooit stond.
    try:
        for rij in db.landen_in_index():
            land = rij["land"]
            if land not in sitetaal.LANDEN:
                continue
            regels.append((f"/index/{land}", nieuwste))
            for c in db.categorieen_per_land(land):
                datum = (c["afgerond_op"].strftime("%Y-%m-%d")
                         if c.get("afgerond_op") else nieuwste)
                regels.append((f"/index/{land}/{c['categorie']}", datum))
                # Stap 90: de winkels die AI noemt, elk een eigen pagina.
                try:
                    lijst = _ranglijst_bewaard(c["categorie"], land) or {}
                    if len(lijst.get("rijen") or []) >= MINIMUM_PER_LAND:
                        regels += [(f"/index/{land}/{c['categorie']}/{_winkel_slug(r['webshop_url'])}", datum)
                                   for r in lijst["rijen"] if (r.get("genoemd") or 0) > 0]
                except Exception as e:
                    print(f"Winkelpagina's in sitemap overslaan voor {c['categorie']}: {e}")
    except Exception as e:
        # Een sitemap zonder de index is vervelend; een sitemap die een foutmelding
        # teruggeeft is erger, want dan verdwijnt ook de rest uit Google.
        print(f"Index in sitemap overslaan: {e}")
    # Het adres komt uit BASE_URL. Stond hier vast op www.krillo.nl, en dan
    # dient een verhuisde site een sitemap in met adressen van het oude domein.
    # Search Console keurt zo'n sitemap af, want een sitemap mag alleen gaan
    # over het eigendom waar hij onder ingediend wordt.
    basis = get_base_url().rstrip("/")
    urls = "".join(
        f"<url><loc>{basis}{p}</loc>"
        f"<lastmod>{datum}</lastmod><changefreq>weekly</changefreq></url>"
        for p, datum in regels
    )
    inhoud = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return inhoud


@app.route("/llms.txt")
def llms_txt():
    # HERSCHREVEN 18 september 2026, want dit bestand stond vol met dingen die
    # niet meer waar waren. Er stond:
    #   - "Volledige audit: 79 euro eenmalig". Dat product is op 11 september
    #     vervallen en staat nergens meer op de site.
    #   - "De betaalde eenmalige opknapbeurt". Ook vervallen; het is nu een
    #     maandabonnement.
    #   - "Het monitoring-abonnement meet elke week opnieuw". Dubbel fout:
    #     monitoring bestaat niet meer EN de keten draait maandelijks, niet
    #     wekelijks. Diezelfde onwaarheid is op 18 september uit de
    #     veelgestelde vragen gehaald, maar hier bleef hij staan.
    #   - Geen woord over de index, terwijl dat inmiddels het kernproduct is.
    #
    # Waarom dat erger is dan een verouderde pagina: dit bestand is geschreven
    # OM door AI-assistenten gelezen te worden. Krillo verkoopt dat AI jouw
    # winkel goed beschrijft. Dan is je eigen machineleesbare beschrijving vol
    # producten die niet bestaan precies de fout waar wij anderen op
    # controleren.
    #
    # De prijzen worden nu UIT payments.PAKKETTEN opgebouwd in plaats van
    # overgetypt. Zo kan dit bestand nooit meer iets anders beweren dan het
    # bestelscherm, ook niet als de prijzen weer veranderen.
    def _euro(sleutel):
        return int(float(payments.PAKKETTEN[sleutel]["prijs"]["value"]))

    # In het Engels sinds 23 september. De site is Engels (taalregel van 18
    # september: een adres, een taal), en dit bestand is de beschrijving van
    # die site voor AI. Een Nederlandse beschrijving van een Engelse site is
    # precies het soort tegenstrijdigheid waar wij anderen op controleren.
    prijsregels = "\n".join([
        "- Free check: 0 euro, no account and no payment details needed",
        f"- Watch: {_euro('watch')} euro per month, your rank in the index every "
        "month, the buying questions you do not appear in with the real answer, "
        "and every fix written out to do yourself",
        f"- Fix: {_euro('fix')} euro per month, everything in Watch plus Krillo "
        "installs the fixes in the store and shows the difference at the next "
        "monthly measurement. Cancel any time.",
        f"- Brands and agencies: {_euro('merken')} euro per month, up to 25 "
        "stores in one dashboard",
        f"- An extra country for the same store: {_euro('watch')} euro per month",
    ])

    inhoud = """# Krillo

> Krillo measures whether AI assistants such as ChatGPT and Gemini name and recommend
> online stores when shoppers ask real buying questions, publishes public rankings of
> that, and fixes what keeps paying customers out of those answers.

## What Krillo does
For every category, Krillo puts thirty buying questions to several AI models, worded
the way a shopper would really ask them, and keeps every full answer. From those
answers it reads which stores are named, in which place, and whether they are only
named or actually recommended. That produces a public ranking per category per
country, free to read without an account.

Krillo also checks a store on thirteen points, across access, readability, structure
and content. That free check shows the score and every finding, followed by a taste of
buying questions put to AI.

Measuring happens once a month, not more often. Paying customers get their rank every
month, the buying questions they do not appear in with the real answer, and which
competitor was named instead. With the Fix plan Krillo installs the fixes in the store,
keeps the old text so anything can be put back, and shows the difference at the next
monthly measurement.

A platform is counted apart from a store. A marketplace, portal or comparison site is
not a competitor of a store but a place a store should be listed on, so it does not
take a position in the ranking.

## What Krillo does not promise
Krillo promises no result. Whether an AI names your store also depends on things
outside your own site: what others write about you, reviews, comparison sites and brand
awareness. Krillo does not measure that and does not pretend to.

## Who it is for
Owners of online stores, without a marketing agency and without technical knowledge.
""" + markten.meting_zin_en() + """ They can do it themselves with the written fixes, or have
Krillo do it.

## Pricing
""" + prijsregels + """

## Important pages
- Home page, free check and free visibility test: https://krilloai.com/
- The public index: every measured category and ranking, free to read without an
  account: https://krilloai.com/index
- Example of a customer dashboard, without an account: https://krilloai.com/demo
- Articles about AI visibility (in Dutch): https://krilloai.com/articles
- How we measure: https://krilloai.com/how-we-measure
- Frequently asked questions: https://krilloai.com/veelgestelde-vragen
- About Krillo and contact: https://krilloai.com/about
- The Krillo index, rankings per category and country: https://krilloai.com/index

## Articles
""" + "\n".join(
        f"- {a['titel']}: https://krilloai.com/articles/{a['slug']}"
        for a in artikelen.alle()
    ) + """

## Contact
hello@krilloai.com
"""
    # Alle adressen in een keer naar het huidige domein trekken.
    #
    # Waarom een vervanging en geen f-string: dit bestand is een lap tekst van
    # duizenden tekens met accolades erin. Die een voor een ontwijken om er een
    # f-string van te maken is precies het soort wijziging waarbij je een
    # accolade over het hoofd ziet en de pagina stil omvalt. Een vervanging
    # achteraf raakt alleen de adressen en laat de rest met rust.
    #
    # Het mailadres is sinds 21 september hello@krilloai.com en wordt hier niet
    # vervangen: alleen de webadressen gaan mee met BASE_URL.
    basis = get_base_url().rstrip("/")
    inhoud = inhoud.replace("https://krilloai.com", basis)
    return Response(inhoud, mimetype="text/plain")


def _herkomst():
    """Waar de bezoeker vandaan komt, zonder iets over de persoon vast te leggen.

    We kijken naar een campagnelabel in de link (utm_source) en anders naar het
    domein van de vorige pagina. Geen IP-adres en geen cookie: we willen weten
    of LinkedIn of een forum bezoekers oplevert, niet wie die bezoekers zijn."""
    bron = (request.args.get("utm_source") or "").strip()[:60]
    if bron:
        return bron.lower()

    verwijzer = request.referrer or ""
    if not verwijzer:
        return None
    try:
        from urllib.parse import urlparse
        domein = (urlparse(verwijzer).netloc or "").lower().replace("www.", "")
    except Exception:
        return None
    # Onszelf niet meetellen. Niet alleen krillo.nl hardcoderen: op een
    # testomgeving, een preview-adres of met www ervoor zou de site zichzelf
    # anders als bron opschrijven, en dan staat "krillo.nl" bovenaan de lijst
    # met plekken die bezoekers opleveren.
    eigen = (request.host or "").lower().replace("www.", "").split(":")[0]
    if not domein or "krillo.nl" in domein or (eigen and domein == eigen):
        return None
    return domein[:60]


def _mailtaal(webshop_url):
    """De taal van een mail: sinds 21 september altijd Engels.

    De taalregel van 18 september is een adres, een taal, en krilloai.com is
    Engels. Tot 21 september kreeg een .nl-winkel hier Nederlands terug, en dan
    kreeg iemand die op een Engelse site betaalde Nederlandse post. De mail is
    een deel van de site. Zie ook emailing.py bovenaan.

    De oude bepaling op markt staat er nog onder voor het geval de taalregel
    ooit per markt wordt; hij wordt nu niet bereikt."""
    return "en"
    if not webshop_url:
        return "nl"
    try:
        return "nl" if _markt_van(webshop_url)["is_nederlands"] else "en"
    except Exception as e:
        print(f"Taal bepalen mislukt voor {webshop_url}: {e}")
        return "nl"


# De sleutel waarmee Flask het inlogkoekje ondertekent. Zonder deze regel kan
# Flask geen sessie bewaren en werkt het inlogscherm niet.
#
# Terugval op ADMIN_KEY als SESSIE_SLEUTEL niet gezet is: dan werkt het inloggen
# meteen, zonder dat er eerst iets in Render bij moet. Een eigen SESSIE_SLEUTEL
# is netter, want dan hoeft de beheersleutel niet ook nog koekjes te tekenen.
app.secret_key = (os.environ.get("SESSIE_SLEUTEL")
                  or os.environ.get("ADMIN_KEY") or "krillo-zonder-sleutel")

# Hoe lang je ingelogd blijft op de beheerpagina's.
INLOG_DAGEN = int(os.environ.get("INLOG_DAGEN", "14"))
app.permanent_session_lifetime = timedelta(days=INLOG_DAGEN)


def _mag_bij_beheer():
    """Of deze bezoeker bij de beheerpagina's mag.

    Twee manieren, en dat is met opzet:

    1. Ingelogd via /admin/inloggen. Dan staat er niets in het webadres.
    2. Met ?key= in het adres, zoals het altijd werkte. Die manier blijft
       bestaan, want de cron-taken gebruiken hem en jouw bladwijzers ook.

    Wat er wel verandert: komt iemand binnen met ?key=, dan onthouden wij dat in
    een koekje en sturen wij hem door naar hetzelfde adres ZONDER de sleutel.
    Daarna staat de sleutel niet meer in de adresbalk, niet in je geschiedenis,
    niet in een schermafdruk en niet in de logboeken van Render. Dat is het hele
    punt: de sleutel bestaat nog, hij ligt alleen niet meer overal rond.

    Geeft (mag, doorsturen_naar) terug."""
    admin_key = os.environ.get("ADMIN_KEY")
    if not admin_key:
        return False, None
    if session.get("beheer") is True:
        return True, None
    if _sleutel_klopt(request.args.get("key"), admin_key):
        session.permanent = True
        session["beheer"] = True
        # Alleen doorsturen bij een gewoon bezoek. Een POST doorsturen zou het
        # formulier weggooien, en een cron-taak heeft geen adresbalk.
        if request.method == "GET":
            zonder = {k: v for k, v in request.args.items() if k != "key"}
            return True, url_for(request.endpoint, **{**(request.view_args or {}),
                                                      **zonder})
        return True, None
    return False, None


def _naar_inloggen():
    """Naar het inlogscherm, en na het inloggen terug naar waar je heen wilde.

    1 oktober: links in het ochtendbericht en in de beheerpagina's dragen de
    sleutel niet meer. Wie (nog) niet ingelogd is, logt een keer in en komt dan
    op de pagina waar hij op klikte, niet op het portaal."""
    from urllib.parse import quote as _q, urlencode as _ue
    zonder = {k: v for k, v in request.args.items() if k != "key"}
    verder = request.path + (("?" + _ue(zonder)) if zonder else "")
    if not verder.startswith("/admin") or request.method != "GET":
        return redirect("/admin/inloggen")
    return redirect("/admin/inloggen?verder=" + _q(verder, safe=""))


def _zonder_beheersleutel(tekst, sleutel):
    """Haalt de beheersleutel uit een stuk tekst (1 oktober).

    Nino stuurde een schermafdruk van /admin/oplossingen in de chat, en daarop
    stond de sleutel in platte tekst. Veel beheerpagina's zetten hem in hun
    links (?key=...). Dat hoeft niet meer: wie ingelogd is, heeft een koekje.
    Dit vangnet haalt hem uit ELKE pagina en elke doorverwijzing, ook uit
    pagina's die later bijkomen. Alleen bij een sleutel van 12 tekens of meer:
    een korte sleutel kan ook een gewoon woord zijn, en dan zou de pagina stuk
    gaan."""
    if not sleutel or len(sleutel) < 12 or not tekst or sleutel not in tekst:
        return tekst
    return tekst.replace(sleutel, "")


def _sleutel_klopt(gegeven, verwacht):
    """Vergelijkt een sleutel zonder dat de duur iets verraadt.

    Met == stopt de vergelijking bij het eerste verschillende teken, en dan
    kan iemand aan de reactietijd zien hoeveel tekens hij goed had. Dat is
    theoretisch over het internet, maar het kost een regel om het goed te doen
    en shopify_app.py doet het elders al zo."""
    if not gegeven or not verwacht:
        return False
    return hmac.compare_digest(str(gegeven), str(verwacht))


def _schoon_bron(waarde):
    """Maakt een bronlabel schoon voordat het de database of Mollie in gaat.

    Het label komt uit de browser van de bezoeker en is dus door iedereen te
    verzinnen. Het wordt nergens uitgevoerd of als HTML getoond, maar een label
    van tienduizend tekens of met regeleinden erin maakt de beheerpagina en de
    metadata van Mollie onleesbaar. Daarom kort, kleine letters, en alleen
    tekens die in een campagnenaam thuishoren."""
    tekst = (waarde or "")
    if not isinstance(tekst, str):
        return None
    tekst = re.sub(r"[^a-z0-9._\-]", "", tekst.strip().lower())[:60]
    return tekst or None


def _onthoud_doorverwijzing(url, data):
    """Stap 94: kwam de bezoeker via een doorverwijslink (?ref= op de site), dan
    onthouden wij de code bij het winkeladres dat hij invult. Zo telt een
    aanmelding dagen later nog, zonder cookie. Mag nooit de check breken."""
    ref = (data or {}).get("ref")
    if not ref or not url:
        return
    try:
        import doorverwijzen
        doorverwijzen.onthoud(scan_engine.normalize_url(url), ref)
    except Exception as e:
        print(f"Doorverwijzing onthouden mislukt: {e}")


@app.route("/api/scan", methods=["POST"])
def api_scan():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Enter a website address."}), 400

    herkomst = data.get("herkomst") or _herkomst()
    _onthoud_doorverwijzing(url, data)
    result = run_scan(url)
    if "error" in result:
        db.bewaar_gratis_scan(url, gelukt=False, foutsoort=result["error"][:200], herkomst=herkomst)
        # 5 oktober: iemand probeerde het vijf keer en niemand wist het. Nu een
        # melding aan Nino, hoogstens een keer per site per dag.
        try:
            if db.claim_moment(f"gratis_fout:{scan_engine.normalize_url(url)}", 24 * 3600):
                _meld_aan_beheer(f"Gratis check mislukt: {url}",
                                 f"De gratis check voor {url} lukte niet: {result['error']}"
                                 + (f" (code {result.get('weigering')})" if result.get("weigering") else "")
                                 + ". Een mogelijke klant. Open de site zelf, en geef het adres aan Claude als "
                                   "het bij ons fout gaat.")
        except Exception as e:
            print(f"Melding mislukte gratis check mislukt: {e}")
        # GEVONDEN 24 SEPTEMBER bij mediamarkt.nl: grote winkels houden onze
        # scanner tegen, en dan kreeg de bezoeker alleen "we could not reach
        # this website", terwijl zijn PLEK gewoon in de index staat. De plek
        # hangt niet af van het lezen van zijn site. Dus: staat hij in de
        # index, dan krijgt hij zijn plek, met eerlijk erbij dat het lezen
        # van zijn site niet lukte.
        rang = _rang_voor_gratis_check(scan_engine.normalize_url(url))
        if rang:
            return jsonify({"url": scan_engine.normalize_url(url), "rang": rang,
                            "score": None, "checks": [],
                            "niet_gelezen": checktaal.fout_in_het_engels(result["error"])})
        # Engels voor de bezoeker (24 september), het Nederlands blijft in de database.
        return jsonify(checktaal.naar_het_engels(result)), 400

    db.bewaar_gratis_scan(result["url"], score=result.get("score"), herkomst=herkomst)

    previous = db.get_previous_score(result["url"])
    if previous:
        result["vorige_score"] = previous["score"]
        result["verschil"] = result["score"] - previous["score"]

    # DE ECHTE PLEK (24 september). De knop heet "Get my rank", maar gaf
    # alleen het cijfer over dertien technische punten. Staat de winkel in de
    # index, dan komt zijn plek er nu bovenaan bij, uit dezelfde ranglijst als
    # de openbare pagina. Staat hij er (nog) niet in, dan zegt de pagina dat
    # eerlijk, in plaats van een plek te verzinnen.
    result = checktaal.naar_het_engels(result)
    result["rang"] = _rang_voor_gratis_check(result.get("url"))
    # Stap 165: een winkel uit een land dat de index nog niet meet, krijgt de
    # wachtlijst aangeboden in plaats van "not in the index yet".
    if not result["rang"]:
        result["buiten_markt"] = markten.buiten_de_index(result.get("url"))
    return jsonify(result)


@app.route("/api/handcheck", methods=["POST"])
def api_handcheck():
    """7 oktober: een mislukte gratis check is geen eindpunt meer.

    Ongeveer 4 op de 10 checks gaven geen uitslag (de site weigert servers, een
    beveiligingscontrole, geen antwoord). Die bezoeker WILDE zijn uitslag, en
    kreeg alleen het advies om zelf te mailen: dat doet bijna niemand. Nu laat
    hij in hetzelfde vak zijn mailadres achter, wij krijgen een melding en
    kijken de winkel met de hand na. Vastgelegd in de instellingen, zodat er
    niets verloren gaat als de melding niet aankomt."""
    import json as _json
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    url = (data.get("url") or "").strip()[:300]
    if not _EMAIL_VORM.match(email) or len(email) > 190 or not url:
        return jsonify({"fout": "Enter a valid email address."}), 400
    import gratistools
    if not gratistools.mag_nu("handcheck:" + (_bezoeker_kenmerk() or request.remote_addr or "?")):
        return jsonify({"ok": True})
    try:
        lijst = _json.loads(db.get_instelling("handchecks") or "[]")
    except ValueError:
        lijst = []
    lijst.append({"email": email, "url": url, "op": datetime.utcnow().isoformat(timespec="minutes")})
    db.zet_instelling("handchecks", _json.dumps(lijst[-200:]))
    _meld_aan_beheer("Mislukte check: iemand wil zijn uitslag",
                     f"{escape(email)} probeerde {escape(url)}. De check gaf geen uitslag. "
                     f"Bekijk de winkel en mail binnen een werkdag zijn plek en de drie grootste punten.")
    return jsonify({"ok": True})


@app.route("/api/wachtlijst", methods=["POST"])
def api_wachtlijst():
    """Stap 165: op de wachtlijst voor een land. Alleen adres, winkel en land."""
    import wachtlijst
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    land = (data.get("land") or "").strip().lower()
    url = (data.get("url") or "").strip()[:300] or None
    if not _EMAIL_VORM.match(email) or len(email) > 190:
        return jsonify({"fout": "Enter a valid email address."}), 400
    if land not in markten.WACHTLIJST_LANDEN or markten.in_index(land) and land != "other":
        return jsonify({"fout": "Choose your country."}), 400
    import gratistools
    if not gratistools.mag_nu("wachtlijst:" + (_bezoeker_kenmerk() or request.remote_addr or "?")):
        return jsonify({"fout": "You are on the list already."}), 429
    if not wachtlijst.zet_op_lijst(email, url, land):
        return jsonify({"fout": "Something went wrong. Email hello@krilloai.com."}), 500
    return jsonify({"ok": True, "land": markten.landnaam_en(land)})


def _rang_voor_gratis_check(webshop_url):
    """De plek in de index voor de gratis check, of None. Nooit een fout."""
    if not webshop_url:
        return None
    try:
        kandidaten = [webshop_url]
        kaal = webshop_url.replace("://www.", "://")
        kandidaten += [kaal, kaal.replace("://", "://www.")]
        for kandidaat in dict.fromkeys(kandidaten):
            beeld = klantbeeld.bouw(kandidaat, max_vragen=0)
            if beeld and beeld.get("land") and (beeld.get("van") or 0) >= MINIMUM_PER_LAND:
                # 7 oktober: het concept is "wie AI aanraadt in plaats van jou".
                # Dus ook de namen: de bovenste drie winkels van dezelfde lijst,
                # zonder de winkel zelf. Mislukt dat, dan gewoon zonder namen.
                voor, voor_rijen = [], []
                try:
                    lijst = db.ranglijst_per_land(beeld["categorie"], beeld["land"], limiet=8)
                    eigen = scan_engine.normalize_url(kandidaat)
                    for r in (lijst or {}).get("rijen") or []:
                        if scan_engine.normalize_url(r.get("webshop_url") or "") == eigen:
                            continue
                        naam = r.get("naam") or re.sub(r"^https?://(www\.)?", "", r.get("webshop_url") or "")
                        if len(voor) < 3:
                            voor.append(naam)
                        # 8 oktober (versie 10, de gratis uitslag als mini-rapport):
                        # de vijf winkels die AI het vaakst noemt, met hun telling.
                        if len(voor_rijen) < 5:
                            voor_rijen.append({"naam": naam, "positie": r.get("positie"),
                                               "genoemd": r.get("genoemd") or 0})
                except Exception as e:
                    print(f"Namen voor de gratis check mislukt: {e}")
                # De koopvragen die de winkel verliest, met wie AI in zijn plaats
                # noemt. Komt uit de opgeslagen antwoorden, dus geen extra kosten.
                # Alleen wat er echt in de antwoorden staat; maximaal vijf.
                verloren, aantal_verloren = [], None
                try:
                    import dashboardpaginas as _dp
                    vo = _dp.vragen_overzicht(beeld["ronde"], kandidaat, beeld.get("naam"))
                    aantal_verloren = vo.get("verloren")
                    for v in vo.get("vragen") or []:
                        if v.get("gewonnen"):
                            continue
                        winnaars = []
                        for m in v.get("per_model") or []:
                            for n in m.get("anderen") or []:
                                if n not in winnaars:
                                    winnaars.append(n)
                        if winnaars:
                            verloren.append({"vraag": v["vraag"], "winnaars": winnaars[:3]})
                        if len(verloren) == 5:
                            break
                except Exception as e:
                    print(f"Verloren vragen voor de gratis check mislukt: {e}")
                return {
                    "voor": voor, "voor_rijen": voor_rijen,
                    "verloren": verloren, "aantal_verloren": aantal_verloren,
                    "nul": bool(beeld.get("nul")),
                    "positie": beeld["positie"], "van": beeld["van"],
                    "categorie": categorieen.naam_en(beeld["categorie"]),
                    "land": sitetaal.landnaam(beeld["land"], "en"),
                    # De vragen staan in de taal van de markt; de uitslag zegt dat erbij.
                    "taal": markten.vraagtaal_en(beeld["land"]),
                    "genoemd": beeld.get("genoemd") or 0,
                    "telbaar": beeld.get("telbaar") or 0,
                    "link": f"/index/{beeld['land']}/{beeld['categorie']}#p{beeld['positie']}",
                }
    except Exception as e:
        print(f"Plek voor de gratis check ophalen mislukt voor {webshop_url}: {e}")
    return None


_EMAIL_VORM = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


def _draai_zichtbaarheidstest(test_id, webshop_url, email, base_url):
    """Draait de gratis test en mailt de uitslag. Op de achtergrond, want vijf
    vragen aan de modellen duurt een minuut of twee."""
    try:
        resultaat = zichtbaarheid.draai(test_id, webshop_url)
        if not resultaat:
            return
        try:
            emailing.send_zichtbaarheidstest(
                email, webshop_url, resultaat,
                zichtbaarheid.samenvattingszin(resultaat, webshop_url),
                base_url,
            )
        except Exception as e:
            # De uitslag staat al in de database en op de pagina. Een mail die
            # niet aankomt mag de test niet als mislukt laten gelden.
            print(f"Uitslag mailen mislukt voor {webshop_url}: {e}")
    except Exception as e:
        print(f"Zichtbaarheidstest mislukt voor {webshop_url}: {e}")


def _draai_voorproef(test_id, webshop_url):
    """De korte meting die meteen na de gratis scan draait, zonder e-mailadres."""
    try:
        # Zonder bronanalyse. De voorproef draait bij ELKE gratis scan, ook bij
        # iemand die alleen even kwam kijken. Daar een zoekmachine en een reeks
        # paginabezoeken achteraan sturen maakt de goedkoopste stap van de
        # trechter ineens de duurste. De bronanalyse zit in de volledige gratis
        # test, waar iemand een e-mailadres voor achterlaat.
        zichtbaarheid.draai(test_id, webshop_url,
                            aantal_vragen=zichtbaarheid.VOORPROEF_VRAGEN,
                            max_aanbieders=1, bronnen_erbij=False)
    except Exception as e:
        print(f"Voorproef mislukt voor {webshop_url}: {e}")


@app.route("/api/voorproef", methods=["POST"])
def api_voorproef():
    """Drie koopvragen, meteen na de gratis scan, zonder dat er iets gevraagd wordt.

    Dit bestaat omdat de gratis scan zonder dit een SEO-tool lijkt. Het cijfer
    over dertien technische punten is het minst bijzondere wat Krillo doet, en
    dat stond bovenaan terwijl het enige onderscheidende eronder achter een
    formulier zat. Wie niet doorklikte, en dat is bijna iedereen, oordeelde over
    het verkeerde product.

    Geen e-mailadres, dus ook geen mail. De rem is dezelfde als bij de volledige
    test, en dezelfde winkel krijgt binnen dertig dagen de bewaarde uitslag."""
    if not zichtbaarheid.VOORPROEF_AAN:
        return jsonify({"status": "uit"}), 200

    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No store address given."}), 400
    url = scan_engine.normalize_url(url)

    eerder = db.laatste_geslaagde_test(url, zichtbaarheid.HERGEBRUIK_DAGEN)
    if eerder and eerder.get("resultaat"):
        return jsonify({"status": "klaar",
                        "resultaat": zichtbaarheid.opgeschoond(eerder["resultaat"]),
                        "zin": zichtbaarheid.samenvattingszin(eerder["resultaat"], url)})

    # Loopt er al een meting voor deze winkel, dan geen tweede starten.
    # Dit is een publieke pagina zonder wachtwoord: twee keer klikken, of een
    # dubbelklik, startte anders twee volledige metingen bij de modellen. Dat
    # kost twee keer geld voor precies dezelfde uitslag.
    if db.loopt_er_al_een_test(url):
        return jsonify({"status": "uit"}), 200

    mag, _ = zichtbaarheid.mag_starten()
    if not mag:
        # Bewust geen foutmelding aan de bezoeker. Hij vroeg hier niet om, hij
        # deed gewoon een scan. Dan hoort hij geen melding te krijgen dat er
        # iets niet kon.
        return jsonify({"status": "uit"}), 200

    # Zonder e-mailadres, dus met een vaste plaatsaanduiding. Dat is geen
    # persoonsgegeven en er gaat nooit mail heen.
    aanvraag = db.start_zichtbaarheidstest(url, "voorproef@krilloai.com", False, _herkomst(),
                                           soort="voorproef")
    if not aanvraag:
        return jsonify({"status": "uit"}), 200

    threading.Thread(target=_draai_voorproef, args=(aanvraag["id"], url), daemon=True).start()
    return jsonify({"kenmerk": aanvraag["kenmerk"], "status": "bezig"})


@app.route("/api/zichtbaarheidstest", methods=["POST"])
def api_zichtbaarheidstest():
    """Fase 5 punt 12. Start de gratis zichtbaarheidstest voor een webshop.

    Vraagt om een e-mailadres, en dat is met opzet. Het kost echt geld per test,
    dus we doen hem alleen voor iemand die er om vraagt. En het levert een lijst
    op van mensen die zelf om contact gevraagd hebben, wat het enige nette
    fundament is onder alles wat we ze daarna sturen."""
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    email = (data.get("email") or "").strip().lower()
    nieuwsbrief = bool(data.get("nieuwsbrief"))

    if not url:
        return jsonify({"error": "Enter your store address first."}), 400
    if not email or not _EMAIL_VORM.match(email) or len(email) > 190:
        return jsonify({"error": "Enter a valid email address."}), 400
    if not data.get("voorwaarden_akkoord"):
        return jsonify({"error": "Please agree to the privacy policy."}), 400

    url = scan_engine.normalize_url(url)
    herkomst = data.get("herkomst") or _herkomst()
    _onthoud_doorverwijzing(url, data)

    # Is deze winkel kortgeleden al gemeten, dan hergebruiken we die uitslag.
    # Scheelt geld, maar belangrijker: wie zijn uitslag doorstuurt hoort niet
    # drie verschillende cijfers te zien door de ruis in AI-antwoorden.
    # Met soort="volledig": een voorproef van drie vragen mag nooit doorgaan
    # voor de volledige test van vijf. Wie zijn adres achterlaat hoort de test
    # te krijgen waarvoor hij tekende, niet de korte versie die hij al zag.
    eerder = db.laatste_geslaagde_test(url, zichtbaarheid.HERGEBRUIK_DAGEN, soort="volledig")
    if eerder and eerder.get("resultaat"):
        # Als hergebruik wegschrijven, want deze test kost niets. Telden we hem
        # mee in de dagteller, dan zou een uitslag die tien keer gedeeld wordt
        # de gratis test voor iedereen dichtzetten zonder dat er een cent
        # uitgegeven is.
        aanvraag = db.start_zichtbaarheidstest(url, email, nieuwsbrief, herkomst,
                                               hergebruikt=True)
        if aanvraag:
            db.zet_zichtbaarheidstest(aanvraag["id"], "klaar", resultaat=eerder["resultaat"])
        # base_url en de zin hier bepalen en niet in de thread. In de thread is
        # er geen verzoek meer, en get_base_url() leest het verzoek. Deed je
        # dat daar, dan liep de mail elke keer stuk zonder dat iemand het merkt:
        # de uitslag staat immers gewoon op de pagina.
        basis = get_base_url()
        zin = zichtbaarheid.samenvattingszin(eerder["resultaat"], url)
        resultaat = zichtbaarheid.opgeschoond(eerder["resultaat"])
        threading.Thread(
            target=lambda: emailing.send_zichtbaarheidstest(email, url, resultaat, zin, basis),
            daemon=True).start()
        return jsonify({"kenmerk": (aanvraag or {}).get("kenmerk"), "status": "klaar",
                        "resultaat": resultaat, "zin": zin})

    # Loopt er al een meting voor deze winkel, dan geen tweede starten. Anders
    # betaal je twee keer voor dezelfde uitslag. Deze bezoeker vroeg er zelf om
    # en wacht op een antwoord, dus die krijgt wel te horen wat er aan de hand
    # is, in plaats van een stille afwijzing zoals bij de voorproef.
    if db.loopt_er_al_een_test(url):
        return jsonify({"error": "A check for this store is already running. It will be done in a few minutes."}), 409

    mag, reden = zichtbaarheid.mag_starten()
    if not mag:
        return jsonify({"error": reden}), 429

    aanvraag = db.start_zichtbaarheidstest(url, email, nieuwsbrief, herkomst)
    if not aanvraag:
        return jsonify({"error": "That did not work just now. Please try again in a moment."}), 500

    threading.Thread(target=_draai_zichtbaarheidstest,
                     args=(aanvraag["id"], url, email, get_base_url()), daemon=True).start()
    return jsonify({"kenmerk": aanvraag["kenmerk"], "status": "wachtrij"})


@app.route("/api/zichtbaarheidstest/<kenmerk>")
def api_zichtbaarheidstest_status(kenmerk):
    """De pagina vraagt hier om de tien seconden of de uitslag er al is.

    Op kenmerk en niet op rijnummer. Met een rijnummer kon iemand die zelf een
    test deed simpelweg naar beneden tellen en van elke andere bezoeker de
    winkel en de volledige uitslag opvragen.

    Geeft ook geen e-mailadres terug, ook niet met het juiste kenmerk."""
    test = db.get_zichtbaarheidstest_op_kenmerk(kenmerk)
    if not test:
        return jsonify({"error": "Onbekende test."}), 404

    antwoord = {"status": test.get("status") or "wachtrij",
                "webshop_url": test.get("webshop_url")}
    if test.get("status") == "klaar" and test.get("resultaat"):
        antwoord["resultaat"] = zichtbaarheid.opgeschoond(test["resultaat"])
        antwoord["zin"] = zichtbaarheid.samenvattingszin(test["resultaat"],
                                                         test.get("webshop_url"))
    elif test.get("status") == "mislukt":
        antwoord["fout"] = ("De test kon niet afgemaakt worden. Dat ligt meestal aan de site "
                            "die ons niet binnenliet, of aan een AI-model dat even dichtzat.")
    return jsonify(antwoord)


def _oude_kassa_dicht():
    """De losse audit (79 euro) en de eenmalige uitvoering (149 euro).

    Allebei van de site verdwenen (11 en 17 september), maar hun kassa stond
    nog open. Met een oude link kon iemand ze dus nog kopen, terwijl de
    voorwaarden sinds 21 september alleen Watch, Fix en het pakket voor merken
    beschrijven. Een product verkopen waar geen voorwaarden bij staan is precies
    het soort ding dat in een geschil tegen je werkt.

    Dicht met een schakelaar in plaats van weggehaald: de betaalketen erachter
    (factuur, toegangsmail, werklijst) wordt ook door Fix gebruikt, en de tests
    die die keten bewaken zetten OUDE_KASSA_AAN=ja. In Render staat hij niet, en
    dan is de deur dicht."""
    if (os.environ.get("OUDE_KASSA_AAN") or "").strip().lower() == "ja":
        return None
    return jsonify({"error": "This product is no longer available. See our plans at "
                             "krilloai.com/#pricing."}), 410


@app.route("/api/checkout/audit", methods=["POST"])
def checkout_audit():
    dicht = _oude_kassa_dicht()
    if dicht:
        return dicht
    data = request.get_json(silent=True) or {}
    webshop_url = scan_engine.normalize_url((data.get("url") or "").strip())
    email = (data.get("email") or "").strip()
    bedrijfsnaam = (data.get("bedrijfsnaam") or "").strip()
    voorwaarden = bool(data.get("voorwaarden_akkoord"))
    direct = bool(data.get("directe_uitvoering_akkoord"))
    if not webshop_url or not email:
        return jsonify({"error": "Enter your store address and email address."}), 400
    # De vorm van het adres controleren. Stond hier niet, alleen bij de gratis
    # test. Wie zich vertypt betaalde dus 79 euro, Brevo weigerde stilletjes, en
    # niemand merkte iets: niet de klant, niet wij.
    if not _EMAIL_VORM.match(email):
        return jsonify({"error": "That email address does not look right. Please check it: this is where we send everything."}), 400
    if not voorwaarden:
        return jsonify({"error": "Please agree to the terms and the privacy policy."}), 400
    if not direct:
        return jsonify({"error": "Geef aan dat we direct mogen beginnen."}), 400

    bron = _schoon_bron(data.get("herkomst")) or _schoon_bron(_herkomst())
    result = payments.create_audit_payment(get_base_url(), webshop_url, email,
                                           bedrijfsnaam, bron=bron)
    if "payment_id" in result:
        db.leg_toestemming_vast(result["payment_id"], email, webshop_url, "audit", voorwaarden, direct)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/checkout/uitvoering", methods=["POST"])
def checkout_uitvoering():
    """Wij voeren het uit in de webshop van de klant.

    Zelfde toestemmingen als bij de audit, want het is net zo goed een dienst
    die meteen begint: zodra wij toegang hebben en aan het werk gaan, kan de
    klant zijn herroepingsrecht niet meer inroepen voor het deel dat af is.

    Het platform komt uit een eerdere scan als we die hebben. Weten we het niet,
    dan gaat er algemene uitleg mee in plaats van een gok.

    Sinds 21 september dicht, zie _oude_kassa_dicht."""
    dicht = _oude_kassa_dicht()
    if dicht:
        return dicht
    data = request.get_json(silent=True) or {}
    webshop_url = scan_engine.normalize_url((data.get("url") or "").strip())
    email = (data.get("email") or "").strip()
    bedrijfsnaam = (data.get("bedrijfsnaam") or "").strip()
    voorwaarden = bool(data.get("voorwaarden_akkoord"))
    direct = bool(data.get("directe_uitvoering_akkoord"))
    if not webshop_url or not email:
        return jsonify({"error": "Enter your store address and email address."}), 400
    # De vorm van het adres controleren. Stond hier niet, alleen bij de gratis
    # test. Wie zich vertypt betaalde dus 79 euro, Brevo weigerde stilletjes, en
    # niemand merkte iets: niet de klant, niet wij.
    if not _EMAIL_VORM.match(email):
        return jsonify({"error": "That email address does not look right. Please check it: this is where we send everything."}), 400
    if not voorwaarden:
        return jsonify({"error": "Please agree to the terms and the privacy policy."}), 400
    if not direct:
        return jsonify({"error": "Geef aan dat we direct mogen beginnen."}), 400

    platform = None
    try:
        platform = (db.get_winkelprofiel(webshop_url) or {}).get("platform")
    except Exception as e:
        print(f"Platform ophalen mislukt bij de kassa voor {webshop_url}: {e}")

    bron = _schoon_bron(data.get("herkomst")) or _schoon_bron(_herkomst())
    result = payments.create_uitvoering_payment(get_base_url(), webshop_url, email,
                                                bedrijfsnaam, bron=bron, platform=platform)
    if "payment_id" in result:
        db.leg_toestemming_vast(result["payment_id"], email, webshop_url, "uitvoering",
                                voorwaarden, direct)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/checkout/monitoring", methods=["POST"])
def checkout_monitoring():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    webshop_url = scan_engine.normalize_url((data.get("url") or "").strip())
    bedrijfsnaam = (data.get("bedrijfsnaam") or "").strip()
    voorwaarden = bool(data.get("voorwaarden_akkoord"))
    if not email or not webshop_url:
        return jsonify({"error": "Enter your email address and store address."}), 400
    if not _EMAIL_VORM.match(email):
        return jsonify({"error": "That email address does not look right. Please check it: this is where we send everything."}), 400
    if not voorwaarden:
        return jsonify({"error": "Please agree to the terms and the privacy policy."}), 400

    # Loopt er al een abonnement op deze winkel, dan houden wij het hier tegen.
    # Zonder deze controle maakt elke nieuwe aanmelding een tweede abonnement
    # bij Mollie met dezelfde winkel erin, en dan wordt er elke maand twee keer
    # geïncasseerd. Erger nog: het opzeggen zegt maar een van de twee op, dus
    # hij krijgt een bevestiging terwijl er gewoon geld af blijft gaan.
    try:
        if payments.zoek_abonnement(webshop_url):
            return jsonify({
                "error": "This store already has a Krillo plan. Want Fix instead of Watch? Open "
                         "your dashboard, page Plan, and click Switch to Fix: no second payment. "
                         "Lost your dashboard link? Use Log in at the top of this page. From Fix "
                         "to Watch: email hello@krilloai.com and we switch you the same day."
            }), 400
    except Exception as e:
        # Kunnen wij het niet nakijken, dan gaan wij door. Iemand tegenhouden
        # die wil betalen omdat onze controle hapert is erger dan het risico.
        print(f"Bestaand abonnement nakijken mislukt voor {webshop_url}: {e}")

    # Welk pakket. Onbekend of leeg wordt het standaardpakket; payments.pakket_van
    # doet die keuze op EEN plek, zodat de site en de webhook nooit iets anders
    # kunnen denken.
    pakket = (data.get("pakket") or "").strip().lower()
    # Merken en bureaus richten wij samen in (zo staat het op de site en in de
    # voorwaarden). Dus niet zelf af te rekenen via deze kassa (23 september).
    if pakket == "merken":
        return jsonify({"error": "The brands and agencies plan is set up together with "
                                 "you. Email hello@krilloai.com and we arrange it."}), 400

    bron = _schoon_bron(data.get("herkomst")) or _schoon_bron(_herkomst())
    # Nooit twee keer betalen voor dezelfde winkel (stap 26). Betaalt deze
    # winkel al via onze Shopify-app, dan hier niet nog een abonnement.
    try:
        via_app = db.shopify_winkel_bij_url(scan_engine.normalize_url(webshop_url))
        if via_app and via_app.get("toegangssleutel"):
            stand_app = shopify_billing.huidig_abonnement(via_app["winkel"],
                                                          _shopify_sleutel(via_app))
            if stand_app.get("actief"):
                return jsonify({"error": "This store already has a Krillo plan through "
                                         "the Shopify app. Manage it there."}), 409
    except Exception as e:
        print(f"Shopify-abonnement nakijken bij de kassa mislukt: {e}")

    # Stap 94: kwam hij via een doorverwijslink, dan gaat de code mee naar Mollie.
    # Een onbekende of afgewezen code valt hier stil weg: nooit een aanmelding
    # tegenhouden om een link.
    doorverwijzer = None
    try:
        import doorverwijzen
        doorverwijzer = doorverwijzen.code_bij_kassa(webshop_url, data.get("ref"))
    except Exception as e:
        print(f"Doorverwijzer nakijken bij de kassa mislukt: {e}")
    # Stap 167: Watch per maand begint met 14 gratis dagen, een keer per winkel.
    # Vraagt de site om de proef maar was deze winkel of dit adres al klant,
    # dan zeggen wij dat eerlijk in plaats van stil 49 euro te vragen.
    proef = False
    if data.get("proef"):
        import proefperiode
        reden = proefperiode.proef_geweigerd_om(webshop_url, email, pakket,
                                                payments.periode_van(data.get("periode")))
        proef = reden is None
        if reden in ("winkel", "email"):
            wie = ("This store" if reden == "winkel" else "This email address")
            return jsonify({"error": f"{wie} already had a Krillo subscription, so the free trial is not "
                                     "available again. You can start Watch at EUR 49 a month instead.",
                            "zonder_proef": True, "reden": reden}), 409
    result = payments.create_monitoring_signup(get_base_url(), email, webshop_url,
                                               bedrijfsnaam, bron=bron, pakket=pakket,
                                               periode=payments.periode_van(data.get("periode")),
                                               doorverwijzer=doorverwijzer, proef=proef)
    if "payment_id" in result:
        db.leg_toestemming_vast(result["payment_id"], email, webshop_url, "monitoring", voorwaarden, False)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


def _meld_aan_beheer(kop, bericht):
    """Stuurt een waarschuwing naar het eigen adres.

    Alleen voor dingen die stil misgaan en die je moet weten voordat een klant
    het merkt. Zet BEHEERDER_EMAIL in Render; staat hij er niet, dan blijft het
    bij de logs."""
    print(f"BEHEERMELDING: {kop} | {bericht}")
    # BEHEERDER_EMAIL eerst, want dat is de naam die de rest van de code en de
    # README gebruiken. Stond hier alleen BEHEER_EMAIL, en dan kwam geen enkele
    # noodmelding aan bij iemand die netjes BEHEERDER_EMAIL had ingevuld. Precies
    # de drie meldingen die ertoe doen ("betaald maar niet geleverd",
    # "abonnement niet aangemaakt") verdwenen daardoor in de logs.
    adres = (os.environ.get("BEHEERDER_EMAIL") or os.environ.get("BEHEER_EMAIL")
             or os.environ.get("SMTP_REPLY_TO") or "").strip()
    if not adres:
        return False
    # Stap 126: nooit naar de antwoordagent zelf.
    if adres.lower().endswith(".krilloai.com"):
        return False
    try:
        return emailing.send_email(
            adres, f"Krillo: {kop}",
            f"<p style='font-family:Arial,sans-serif;font-size:15px;'>{bericht}</p>")
    except Exception as e:
        print(f"Beheermelding versturen mislukt: {e}")
        return False


def _zet_in_index(webshop_url):
    """Een klant op de winkellijst, met het land uit zijn domein. Mag nooit een
    betaling of een ronde laten omvallen, dus fouten worden alleen gelogd."""
    try:
        if webshop_url and webshop_url.startswith("http"):
            land = categoriemeting._land_bij_domein(
                categoriemeting._schoon_domein(webshop_url) or "")
            db.zet_klant_op_lijst(scan_engine.normalize_url(webshop_url), land=land)
            # Wie betaalt, wacht geen maand op zijn plek: meteen uitrekenen uit
            # de antwoorden van deze maand (Nino, 1 oktober).
            _plaats_in_ranglijst(scan_engine.normalize_url(webshop_url))
    except Exception as e:
        print(f"Klant in de index zetten mislukt voor {webshop_url}: {e}")


def _meld_nieuwe_klant(soort, webshop_url, email, bedrag, extra=None):
    """Een bericht naar je eigen adres zodra er iemand betaald heeft.

    Dit ontbrak, en dat is raar als je erover nadenkt: er ging wel een mail uit
    als er iets MISGING, maar niet als het goed ging. De belangrijkste
    gebeurtenis van het hele bedrijf, de eerste betalende klant, kwam dus nergens
    binnen behalve in de mail van Mollie en op een beheerpagina die je zelf moet
    openen.

    Bij "wij doen het" is dat niet alleen jammer maar ook riskant: daar moet jij
    binnen een paar dagen echt aan de slag, en de klant zit te wachten. Daarom
    staat in dit bericht meteen waar je heen moet klikken."""
    # Elke nieuwe klant op de winkellijst, zodat zijn categorie gemeten wordt
    # en hij een positie krijgt. Zie db.zet_klant_op_lijst voor het waarom.
    # Hier, omdat dit de ene plek is waar elke nieuwe klant langskomt, via
    # Mollie en via Shopify.
    _zet_in_index(webshop_url)
    # Wie eerder opzegde en terugkomt, krijgt weer zijn maandbericht.
    db.zet_klant_opgezegd(webshop_url, opgezegd=False)
    basis = get_base_url()
    # 1 oktober: geen beheersleutel meer in mails. Ben je niet ingelogd, dan log
    # je een keer in en kom je daarna op deze pagina (zie _naar_inloggen).
    achter = f"?url={quote(webshop_url)}"
    regels = [
        f"<strong>{soort}</strong> voor {webshop_url}",
        f"Bedrag: {bedrag}",
        f"E-mailadres: {email}",
    ]
    if extra:
        regels.append(extra)
    if basis:
        regels.append(f'<a href="{basis}/admin/werkbriefje{achter}">Naar het werkbriefje</a>')
        regels.append(f'<a href="{basis}/admin/bestellingen">Naar de bestellingen</a>')
    return _meld_aan_beheer(f"Nieuwe klant: {soort}", "<br>".join(regels))


def _scan_met_herkansing(webshop_url, pogingen=3):
    """Scant, en probeert het nog twee keer als het misgaat.

    De meeste mislukkingen zijn tijdelijk: een trage server, een robotcheck die
    even aanslaat. Meteen opgeven betekent dat iemand die net betaald heeft
    niets krijgt vanwege een hapering van vijf seconden."""
    laatste = {"error": "onbekend"}
    for poging in range(max(1, pogingen)):
        if poging:
            time.sleep(4 * poging)
        try:
            laatste = run_scan(webshop_url)
        except Exception as e:
            laatste = {"error": f"{type(e).__name__}: {e}"[:200]}
        if "error" not in laatste:
            if poging:
                print(f"Scan van {webshop_url} lukte bij poging {poging + 1}.")
            return laatste
        print(f"Scan van {webshop_url} mislukt (poging {poging + 1}): {laatste['error']}")
    return laatste


def _uitvoering_voorbereiden(payment_id, webshop_url, email, klant_token, base_url):
    """Zet het werk klaar voor een klant die "wij doen het" gekocht heeft.

    Wat de prijskaart belooft is "alles uit de volledige audit zit erbij". Dat
    werd niet gedaan: de uitvoering-tak zette de opdracht op de werklijst en
    vroeg om toegang, en verder gebeurde er niets. Geen scan, geen rapport, geen
    meting. Daardoor was de klantpagina van iemand die 149 euro betaald had leeg,
    en stond er op het werkbriefje geen enkele taak.

    Draait op de achtergrond en mag rustig een paar minuten duren: de klant moet
    eerst toch zelf toegang regelen voordat er iets kan gebeuren."""
    try:
        scan_result = _scan_met_herkansing(webshop_url)
        if "error" in scan_result:
            _meld_aan_beheer(
                "Uitvoering: scan mislukt",
                f"{email} betaalde 149 euro voor {webshop_url}, maar de site is niet te "
                f"scannen: {scan_result.get('error')}. De opdracht staat wel op de "
                f"werklijst. Er is dus GEEN werkbriefje. Kijk er met de hand naar.")
            return

        db.zet_platform(webshop_url, scan_result.get("platform"))
        db.save_report("monitoring", webshop_url, email, scan_result.get("score", 0),
                       scan_result.get("checks", []), None, None, klant_token)

        # Dezelfde keten als bij een abonnee, want het werkbriefje leunt op de
        # meting: zonder vermeldingen is er geen actieplan, en zonder actieplan
        # weet jij niet wat je in die winkel moet doen.
        _meet_en_beoordeel(webshop_url, None, klant_token, base_url)
    except Exception as e:
        print(f"Uitvoering voorbereiden mislukt voor {webshop_url}: {e}")
        _meld_aan_beheer(
            "Uitvoering: voorbereiding mislukt",
            f"Het klaarzetten van het werk voor {webshop_url} ({email}, 149 euro) ging "
            f"mis: {type(e).__name__}: {e}. De opdracht staat op de werklijst maar er "
            f"is geen werkbriefje.")


def _levering_mislukt(payment_id, webshop_url, email, soort, reden):
    """Er is betaald maar wij konden niet leveren.

    Twee dingen gebeuren hier, en allebei zijn ze nodig. De claim gaat terug,
    zodat een volgende melding van Mollie het opnieuw probeert. En er gaat een
    bericht naar het eigen adres, want anders staat het alleen in de logs van
    Render en kijkt niemand daar."""
    db.ontclaim_payment(payment_id)
    _meld_aan_beheer(
        "Betaald maar niet geleverd",
        f"Betaling {payment_id} voor {webshop_url} ({soort}, {email}) is binnen, maar "
        f"de scan lukte niet: {reden}. Mollie stuurt deze melding niet opnieuw. Ga naar "
        f"{get_base_url()}/admin/bestellingen en klik bij deze bestelling op 'Opnieuw "
        f"verwerken'. Lukt dat ook niet, doe het dan met de hand of geef het geld terug.")


def _is_proefbetaling(payment_id):
    """Is dit een betaling uit de TESTomgeving van Mollie (de proefbetaling van
    de nachtcontrole)? Alleen te zien met de testsleutel."""
    sleutel = (os.environ.get("MOLLIE_TEST_KEY") or "").strip()
    if not sleutel.startswith("test_"):
        return False
    try:
        with payments.met_sleutel(sleutel):
            gegevens = payments.betaling_nakijken(payment_id)
        return bool(gegevens) and gegevens.get("mode") == "test"
    except Exception:
        return False


def _leg_doorverwijzing_vast(metadata, webshop_url, payment_id):
    """Stap 94: een nieuwe betalende klant via een doorverwijslink. Vastleggen en
    Nino een seintje geven. Mag nooit de levering aan de klant breken."""
    try:
        import doorverwijzen
        wie = doorverwijzen.leg_vast(metadata.get("doorverwijzer"), webshop_url, payment_id,
                                     (metadata.get("pakket") or "").lower() or None,
                                     payments.periode_van(metadata.get("periode")))
        if not wie:
            return None
        if wie["soort"] == "partner":
            uitleg = (f"Partner {wie.get('naam') or wie['code']} ({wie.get('email')}) krijgt "
                      f"{doorverwijzen.PROCENT_PARTNER} procent van wat deze klant betaalt, "
                      f"zolang de klant betaalt, hoogstens {doorverwijzen.MAANDEN_PARTNER} maanden.")
        else:
            uitleg = (f"Klant {wie.get('webshop_url')} verwees door en krijgt zijn volgende maand "
                      f"gratis (in Mollie de volgende afschrijving een maand opschuiven, niet terugbetalen), na {doorverwijzen.WACHTDAGEN} dagen als deze klant dan "
                      f"nog betaalt.")
        _meld_aan_beheer("Nieuwe klant via een doorverwijzing",
                         f"{webshop_url} werd klant via de link van {wie['code']}. {uitleg} "
                         f"Wat openstaat zie je op /admin/doorverwijzen; uitbetalen doe je met de hand.")
        return wie
    except Exception as e:
        print(f"Doorverwijzing vastleggen mislukt voor {webshop_url}: {e}")
        return None


def _verwerk_betaling(payment_id, base_url):
    """Doet het echte werk na een geslaagde betaling: scannen, AI-tekst maken,
    rapport opslaan en e-mail versturen. Draait op de achtergrond zodat Mollie
    niet hoeft te wachten en de melding niet opnieuw stuurt."""
    try:
        # Eerst kijken of er echt betaald is. Zolang dat niet zo is doen we
        # niets en claimen we niets, zodat de melding die later WEL "paid"
        # zegt gewoon verwerkt wordt.
        status = payments.get_payment_status(payment_id)
        # GEVONDEN 28 SEPTEMBER: de proefbetaling van de nachtcontrole bestaat
        # alleen in de testomgeving van Mollie. Mollie meldt hem toch aan deze
        # webhook; met de echte sleutel is hij er dan niet. Dat is geen klant
        # en geen storing: stil overslaan, zonder vier pogingen en zonder mail.
        if status is None and payments.is_testbetaling(payment_id):
            print(f"Betaling {payment_id} is een proefbetaling (testsleutel), overgeslagen.")
            return
        # GEVONDEN 24 SEPTEMBER: lukte het ophalen bij Mollie niet (time-out),
        # dan stopte het hier stil. Mollie had al 200 terug en probeert niet
        # opnieuw: een betaalde klant kreeg dan niets en jij wist van niets.
        # Nu nog drie pogingen, en daarna een mail aan jou.
        if status is None and _is_proefbetaling(payment_id):
            # 28 september: de nachtcontrole maakt met MOLLIE_TEST_KEY een
            # proefbetaling. Mollie meldt die hier, en met de echte sleutel is
            # hij onvindbaar (hij staat in de testomgeving). Dat gaf de melding
            # "vier keer ophalen mislukte" voor een betaling die niet bestaat.
            print(f"Proefbetaling {payment_id} van de nachtcontrole gemeld door Mollie: genegeerd.")
            return
        for wacht in (5, 20, 60):
            if status is not None:
                break
            time.sleep(wacht)
            status = payments.get_payment_status(payment_id)
        if status is None:
            _meld_aan_beheer(
                "Betaling niet op te halen bij Mollie",
                f"Mollie meldde betaling {payment_id}, maar vier keer ophalen mislukte. "
                f"Kijk in Mollie (Betalingen, zoek op {payment_id}) of er betaald is. "
                f"Zo ja: de klant heeft nog niets gekregen, neem contact op.")
            return
        # Een maandbetaling van een abonnement (23 september). Die draagt geen
        # metadata van ons. Mislukt hij, dan moet JIJ dat weten: anders loopt
        # een klant door zonder te betalen en merkt niemand het.
        if status and status.get("subscription_id") and not (status.get("metadata") or {}).get("type"):
            if status.get("status") in ("failed", "expired", "canceled"):
                klant = payments.klant_bij_id(status.get("customer_id")) or {}
                _meld_aan_beheer(
                    "Maandbetaling mislukt",
                    f"De maandbetaling {payment_id} voor {klant.get('webshop_url') or 'een klant'} "
                    f"staat op {status.get('status')}. Mollie probeert een mislukte incasso "
                    f"niet vanzelf opnieuw. Neem contact op met {klant.get('email') or 'de klant'}.")
                return
        if not (status and status["is_paid"]):
            return

        # Pas nu vastleggen dat wij deze betaling oppakken. Komt Mollie later
        # nog een keer met dezelfde betaling, dan stopt het hier.
        geclaimd = db.claim_payment(payment_id)
        if geclaimd is None:
            # Wij KONDEN niet claimen. Dat is iets anders dan "al verwerkt" en
            # het hoort een belletje te geven, want dit is het pad waarin iemand
            # wel betaalt en geen klantrecord krijgt.
            _meld_aan_beheer(
                "Betaling niet geclaimd",
                f"Betaling {payment_id} is binnen, maar wij konden niet vastleggen dat "
                f"wij hem oppakken (database niet bereikbaar). Er is NIETS geleverd. "
                f"Controleer deze betaling met de hand in Mollie.")
            return
        if not geclaimd:
            print(f"Betaling {payment_id} was al verwerkt, overgeslagen.")
            return

        # Tweede blokkade: is er voor deze betaling al een rapport gemaakt?
        if db.report_bestaat_al(payment_id):
            print(f"Er bestaat al een rapport voor betaling {payment_id}, niets verstuurd.")
            return

        # LET OP: hier stond een controle die betalingen ouder dan drie uur
        # negeerde, gemeten vanaf het AANMAKEN van de betaling. Dat brak elke
        # overboeking: die is per definitie een dag of langer onderweg, en bij
        # aankomst werd hij als "late herhaling" weggegooid. Geld ontvangen,
        # niets geleverd. Dubbele verwerking wordt al voorkomen door de claim
        # hierboven en door report_bestaat_al, dus een leeftijdsgrens voegde
        # niets toe.

        metadata = status.get("metadata") or {}
        payment_type = metadata.get("type")
        # 1 oktober: de proefaankoop van de nacht (proefaankoop.py) loopt deze
        # zelfde weg, maar zonder factuur, abonnement, scan, melding of meting.
        # Alleen bij een kenmerk dat met tr_proefaankoop_ begint EN dat vlagje.
        proefaankoop = bool(metadata.get("proefaankoop")) and str(payment_id).startswith("tr_proefaankoop_")
        if status.get("subscription_id") and not payment_type:
            # Maandbetaling gelukt: een factuur, zodat een klant vanaf maand
            # twee ook een factuur krijgt. Verder niets; het werk loopt al.
            klant = payments.klant_bij_id(status.get("customer_id")) or {}
            if not klant.get("email"):
                _meld_aan_beheer(
                    "Maandbetaling zonder klantgegevens",
                    f"Maandbetaling {payment_id} is binnen, maar de klant bij Mollie kon "
                    f"niet opgehaald worden. Er is GEEN factuur verstuurd. Maak hem met "
                    f"de hand.")
            metadata = {"type": "maandbetaling", "webshop_url": klant.get("webshop_url"),
                        "email": klant.get("email")}
            payment_type = "maandbetaling"
        webshop_url = metadata.get("webshop_url")
        email = metadata.get("email")
        bedrijfsnaam = metadata.get("bedrijfsnaam")
        # Waar deze klant vandaan kwam. Komt ongewijzigd terug uit de metadata
        # van Mollie, ook bij een overboeking die een dag onderweg was. Bij
        # betalingen van voor deze wijziging staat er niets, en dan blijft het
        # veld leeg in plaats van dat we iets gaan raden.
        bron = _schoon_bron(metadata.get("bron"))

        # Eerst de betaalbevestiging met factuur, die hoort er meteen te zijn.
        # De audit zelf duurt langer omdat er gescand en geschreven moet worden.
        if email:
            # In het Engels en met de naam van wat iemand echt kocht. Hier stond
            # "Krillo monitoring, eerste maand", ook voor wie Watch of Fix nam.
            if payment_type == "audit":
                omschrijving = f"Krillo full audit for {webshop_url}"
            elif payment_type == "uitvoering":
                omschrijving = f"Krillo carries out the improvements for {webshop_url}"
            elif payment_type == "maandbetaling":
                bedrag_tekst = f"{status.get('bedrag'):.2f}" if status.get("bedrag") is not None else None
                pakket_maand = payments.pakket_bij_bedrag(bedrag_tekst, status.get("interval"))
                soort_periode = ("yearly" if payments.periode_bij_bedrag(bedrag_tekst, status.get("interval")) == "jaar"
                                 else "monthly")
                omschrijving = (f"Krillo {payments.pakket_van(pakket_maand)['naam']}, {soort_periode}, "
                                f"for {webshop_url}")
            else:
                pakketnaam = payments.pakket_van(metadata.get("pakket"))["naam"]
                eerste = "first year" if payments.periode_van(metadata.get("periode")) == "jaar" else "first month"
                omschrijving = f"Krillo {pakketnaam}, {eerste}, for {webshop_url}"
            bedrag = status.get("bedrag")
            # Stap 167: voor de cent van de gratis proef geen factuur.
            if bedrag is not None and not metadata.get("proef") and not proefaankoop:
                factuurnummer = db.maak_factuur(payment_id, email, bedrijfsnaam,
                                                omschrijving, bedrag, bron=bron)
                if factuurnummer and factuurnummer.get("nieuw"):
                    # ALLEEN bij een nieuwe factuur mailen. Bij een herhaling van
                    # Mollie na een mislukte levering kwam dezelfde factuur er
                    # anders nog een keer uit, voor iets wat de klant nog steeds
                    # niet gekregen had.
                    if not emailing.send_factuur_email(
                            email, factuurnummer["factuurnummer"], omschrijving,
                            bedrag, bedrijfsnaam):
                        _meld_aan_beheer(
                            "Factuur niet verstuurd",
                            f"De factuur voor betaling {payment_id} ({email}) kon niet "
                            f"verstuurd worden. De factuur staat wel in de database.")

        if payment_type == "uitvoering" and webshop_url and email:
            # Deze opdracht wordt door een mens uitgevoerd, dus het enige wat
            # hier gebeurt is: op de werklijst zetten en om toegang vragen.
            # Eerst de werklijst en dan pas de mail: gaat de mail mis, dan staat
            # de opdracht er tenminste, en zie je op de beheerpagina dat er
            # iemand wacht. Andersom zou een klant gevraagd worden om toegang
            # voor een opdracht die nergens staat.
            platform = metadata.get("platform")
            if not db.start_uitvoering(payment_id, webshop_url, email, platform):
                print(f"LET OP: uitvoering voor {webshop_url} staat NIET op de werklijst.")
            # Meteen een bericht naar het eigen adres. Hier moet een mens aan de
            # slag, dus dit is het enige product waarbij stilte betekent dat er
            # niets gebeurt.
            _meld_nieuwe_klant("Wij doen het", webshop_url, email, "149 euro eenmalig (oude route)",
                               extra=(f"Platform: {platform}" if platform else
                                      "Platform onbekend, kijk zelf even waar hij op draait."))
            klant_token = db.get_or_create_klant(webshop_url, email)
            if not klant_token:
                # Deze webshop hoort al bij een ander e-mailadres. Wij geven die
                # pagina niet aan iemand anders, ook niet als hij net betaald
                # heeft. Dat kan een tikfout zijn of iemand die de URL van een
                # bekende winkel invulde; beide moeten met de hand bekeken.
                _meld_aan_beheer(
                    "Bestelling op een webshop van een andere klant",
                    f"{email} bestelde een uitvoering voor {webshop_url}, maar die "
                    f"webshop hoort al bij een ander adres. De klantpagina is NIET "
                    f"gedeeld. Kijk of dit klopt en handel het met de hand af.")
            monitoring_url = f"{base_url}/mijn/{klant_token}" if klant_token else None
            if not emailing.send_uitvoering_welkom(email, webshop_url, platform,
                                                   monitoring_url):
                _meld_aan_beheer(
                    "Toegangsmail niet verstuurd",
                    f"{email} betaalde 149 euro voor {webshop_url}, maar de mail met de "
                    f"vraag om toegang is NIET verstuurd. Zonder die mail kan hij niets "
                    f"doen en gebeurt er niets. Neem contact op.")

            # En dan het werk waar hij voor betaald heeft klaarzetten.
            #
            # Dit ontbrak volledig, en het is precies wat de prijskaart belooft:
            # "Alles uit de volledige audit zit erbij". Er werd niet gescand,
            # geen rapport bewaard en niet gemeten. Gevolg: de klantpagina van
            # iemand die 149 euro betaalde was leeg, en JIJ had geen werkbriefje,
            # dus je wist niet wat je in zijn winkel moest doen.
            #
            # Op de achtergrond, want dit duurt minuten en de klant hoeft er niet
            # op te wachten: hij moet eerst toch toegang regelen. Mislukt het,
            # dan krijg jij bericht en staat de opdracht nog steeds op je
            # werklijst.
            threading.Thread(
                target=_uitvoering_voorbereiden,
                args=(payment_id, webshop_url, email, klant_token, base_url),
                daemon=True,
            ).start()

        elif payment_type == "audit" and webshop_url and email:
            scan_result = _scan_met_herkansing(webshop_url)
            if "error" in scan_result:
                # Betaald, maar wij kunnen niet leveren. De claim gaat terug, zodat
                # een volgende melding van Mollie het opnieuw probeert. Zou de claim
                # blijven staan, dan is het geld binnen, komt er nooit een rapport,
                # en merkt niemand het.
                _levering_mislukt(payment_id, webshop_url, email, "audit",
                                  scan_result.get("error"))
            else:
                # Op welk winkelplatform deze shop draait. Werd tot nu toe
                # alleen bij demo's opgeslagen, waardoor we het van betalende
                # klanten juist niet wisten. Zonder dit schrijft de tekst bij
                # "waar zet je dit neer" een route in Shopify voor iemand met
                # WooCommerce.
                db.zet_platform(webshop_url, scan_result.get("platform"))
                ai_fixes = ai_content.generate_ai_fixes(
                    webshop_url, scan_result.get("checks", []), scan_result.get("gevonden_paginas")
                )
                # NIET stil terugvallen op de gratis sjabloonteksten. Dat deed
                # hij wel, en dan betaalde iemand 79 euro voor precies de drie
                # voorbeelden die hij een minuut eerder gratis op de homepage
                # zag. Lukt het schrijven niet, dan is dat een fout die jij moet
                # weten, en dan gaat de mail niet uit: de betaling blijft open
                # staan zodat een volgende melding van Mollie het opnieuw
                # probeert.
                if ai_fixes is None:
                    _levering_mislukt(
                        payment_id, webshop_url, email, "audit",
                        "De uitgeschreven oplossingen konden niet gemaakt worden "
                        "(AI-sleutel ontbreekt of de kostenrem staat dicht). Er is "
                        "GEEN mail verstuurd, want dan had de klant de gratis "
                        "voorbeeldteksten gekregen voor 79 euro.")
                    return
                fixes = ai_fixes
                token = db.save_report("audit", webshop_url, email, scan_result.get("score", 0),
                                        scan_result.get("checks", []), fixes, payment_id)
                report_url = f"{base_url}/rapport/{token}" if token else None
                emailing.send_audit_email(email, webshop_url, scan_result, fixes, report_url,
                                          taal=_mailtaal(webshop_url))

        elif payment_type == "monitoring_first_payment":
            customer_id = metadata.get("customer_id")
            if customer_id and not proefaankoop:
                # Het antwoord WEL nakijken. Ging dit mis, dan heeft de klant de
                # eerste maand betaald maar wordt er daarna nooit meer
                # geincasseerd, en valt hij stilletjes uit de dienst.
                # EERST kijken of er al een abonnement loopt bij deze klant.
                # Zonder deze controle gebeurde dit: de levering mislukt, de
                # claim gaat terug, Mollie komt opnieuw langs, en er wordt een
                # TWEEDE doorlopend abonnement aangemaakt. Dan gaat er elke maand
                # twee keer 39 euro af, en opzeggen haalt er maar een van de
                # twee weg. De klant krijgt een bevestiging terwijl er geld af
                # blijft gaan.
                bestaand = None
                try:
                    bestaand = payments.zoek_abonnement(webshop_url)
                except Exception as e:
                    print(f"Nakijken op een bestaand abonnement mislukt: {e}")
                if bestaand:
                    print(f"Er loopt al een abonnement voor {webshop_url}, "
                          f"geen tweede aangemaakt.")
                    uitkomst = {"id": bestaand.get("subscription_id")}
                else:
                    # Het pakket komt uit de metadata van de eerste betaling.
                    # Zonder dit werd elk abonnement het standaardbedrag, ook
                    # als iemand Watch van 49 euro gekozen had, en dan wordt er
                    # elke maand honderd euro te veel afgeschreven.
                    # Stap 167: bij de gratis proef begint het abonnement na de 14 dagen.
                    import proefperiode
                    uitkomst = payments.create_subscription(
                        customer_id, pakket=metadata.get("pakket"),
                        webhook_url=f"{base_url}/webhooks/mollie",
                        startdatum=proefperiode.eerste_incasso() if metadata.get("proef") else None,
                        periode=metadata.get("periode")) or {}
                if uitkomst.get("error"):
                    print(f"LET OP: doorlopend abonnement NIET aangemaakt voor "
                          f"{webshop_url} ({customer_id}): {uitkomst['error']}")
                    _meld_aan_beheer(
                        "Abonnement niet aangemaakt",
                        f"{webshop_url} heeft de eerste maand betaald, maar het "
                        f"doorlopende abonnement is niet aangemaakt bij Mollie. "
                        f"Reden: {uitkomst['error']}. Maak het met de hand aan, "
                        f"anders wordt er nooit meer geincasseerd.")
            if webshop_url and email:
                # EERST DE KLANT, DAN PAS DE SCAN (23 september). Hier stond het
                # andersom: mislukte de scan (een robotcheck, een trage server),
                # dan stopte alles hier. Het abonnement liep al, maar er kwam
                # geen klantpagina, geen welkomstmail, geen plek in de index.
                # En Mollie meldt een betaalde betaling niet nog een keer, dus
                # de herkansing waar de claim op rekende kwam nooit. De positie
                # komt uit de index en heeft de scan niet nodig; de scan is een
                # extra en mag nu mislukken.
                scan_result = ({"error": "proefaankoop"} if proefaankoop
                               else _scan_met_herkansing(webshop_url))
                scan_gelukt = "error" not in scan_result
                if not scan_gelukt and not proefaankoop:
                    _meld_aan_beheer(
                        "Scan mislukt bij een nieuwe klant",
                        f"{webshop_url} heeft betaald. De klant is wel aangemaakt en "
                        f"gemaild, maar zijn site kon niet gescand worden: "
                        f"{scan_result.get('error')}. De positie komt uit de index; "
                        f"de dertien controlepunten volgen bij de wekelijkse scan.")
                    scan_result = {"score": 0, "checks": []}
                if proefaankoop:
                    scan_result = {"score": 0, "checks": []}
                # (Het blok hieronder stond eerst in een else na de scan.)
                if webshop_url:
                    if scan_gelukt:
                        db.zet_platform(webshop_url, scan_result.get("platform"))
                    klant_token = db.get_or_create_klant(webshop_url, email)
                    if klant_token:
                        # Stap 352: wat hij in /start koos (categorie, vragen) meteen in zijn dashboard.
                        try:
                            import aanmelden
                            aanmelden.pas_toe(webshop_url)
                        except Exception as e:
                            print(f"Aanmelding toepassen mislukt: {e}")
                    if klant_token and customer_id:
                        db.zet_mollie_klant(webshop_url, customer_id,
                                            (metadata.get("pakket") or "").lower() or None,
                                            payments.periode_van(metadata.get("periode")))
                        if metadata.get("proef"):
                            import proefperiode
                            proefperiode.zet_gratis_tot(webshop_url, proefperiode.laatste_gratis_dag())
                    if not klant_token:
                        _meld_aan_beheer(
                            "Aanmelding op een webshop van een andere klant",
                            f"{email} meldde zich aan voor monitoring op {webshop_url}, "
                            f"maar die webshop hoort al bij een ander adres. De "
                            f"klantpagina is NIET gedeeld. Handel dit met de hand af.")
                    if scan_gelukt:
                        db.save_report("monitoring", webshop_url, email,
                                       scan_result.get("score", 0),
                                       scan_result.get("checks", []), None, payment_id,
                                       klant_token)
                    monitoring_url = f"{base_url}/mijn/{klant_token}" if klant_token else None
                    pakket = (metadata.get("pakket") or payments.STANDAARD_PAKKET).lower()
                    welkom_ok = False
                    plek = None
                    try:
                        import klantbeeld
                        plek = klantbeeld.bouw(webshop_url, max_vragen=1)
                    except Exception as e:
                        print(f"Plek voor de welkomstmail mislukt voor {webshop_url}: {e}")
                    try:
                        import proefperiode
                        welkom_ok = emailing.send_monitoring_welcome_email(
                            email, webshop_url, scan_result, monitoring_url,
                            taal=_mailtaal(webshop_url), pakket=pakket,
                            gratis_tot=proefperiode.laatste_gratis_dag() if metadata.get("proef") else None,
                            plek=plek)
                        if welkom_ok and plek and plek.get("positie"):
                            # Zijn plek stond al in de welkomstmail: geen tweede
                            # mail "je plek is er" (zie _meld_eerste_plek).
                            db.claim_moment(f"eerste_plek:{webshop_url}", 365 * 24 * 3600)
                    except Exception as e:
                        print(f"Welkomstmail mislukt voor {webshop_url}: {e}")
                    # Zonder deze mail heeft een betalende klant geen link naar
                    # zijn eigen pagina (27 september: dit ging stil mis).
                    if not welkom_ok:
                        _meld_aan_beheer(
                            "Welkomstmail NIET verstuurd",
                            f"{email} betaalde voor {webshop_url} ({pakket}), maar de welkomstmail "
                            f"ging niet weg. Stuur hem zijn link met de hand: {monitoring_url}")
                    # En meteen om toegang vragen. Sinds 11 september voeren wij
                    # de verbeteringen ook bij het abonnement uit, en zonder
                    # toegang kan dat niet. Dezelfde mail als bij "wij doen het",
                    # met de stappen voor zijn platform erin.
                    #
                    # Mislukt die mail, dan is dat geen ramp: op zijn eigen
                    # pagina staat dan gewoon wat er moet gebeuren, kant en
                    # klaar om zelf te doen. Daarom geen alarm hier.
                    #
                    # ALLEEN BIJ FIX (sinds 21 september). Watch is "de
                    # oplossingen uitgeschreven, om zelf te doen"; een Watch-klant
                    # die een mail krijgt dat wij toegang tot zijn winkel nodig
                    # hebben, denkt dat hij iets anders gekocht heeft.
                    if pakket != "watch":
                        # Op de werklijst, net als de oude eenmalige uitvoering.
                        # Dit ontbrak (gevonden 21 september): zonder regel op
                        # de werklijst kan het overzicht van wat we veranderd
                        # hebben niet verstuurd worden, en komt er nooit een
                        # nameting, want die hangt aan de opleverdatum.
                        if not db.start_uitvoering(payment_id, webshop_url, email,
                                                   scan_result.get("platform")):
                            _meld_aan_beheer(
                                "Fix niet op de werklijst",
                                f"{webshop_url} nam Fix, maar de opdracht staat NIET op "
                                f"de werklijst. Zet hem er met de hand op.")
                        try:
                            emailing.send_uitvoering_welkom(
                                email, webshop_url, scan_result.get("platform"),
                                monitoring_url)
                        except Exception as e:
                            print(f"Toegangsmail bij Fix mislukt voor {webshop_url}: {e}")
                    if status.get("mode") == "test":
                        db.zet_klant_test(webshop_url)
                    elif metadata.get("doorverwijzer"):
                        _leg_doorverwijzing_vast(metadata, webshop_url, payment_id)
                    if proefaankoop:
                        # Geen bericht aan Nino, geen plek in de index en geen
                        # meting: dit is de nachtelijke proef, geen klant.
                        return
                    _meld_nieuwe_klant(
                        ("TEST, geen echt geld: " if status.get("mode") == "test" else "")
                        + ("Gratis proef Watch (14 dagen, daarna 49 euro per maand)" if metadata.get("proef") else "Abonnement"),
                        webshop_url, email, "1 cent nu, 49 euro vanaf dag 15" if metadata.get("proef") else "maandpakket",
                        extra=(f'Zijn pagina: <a href="{monitoring_url}">{monitoring_url}</a>'
                               if monitoring_url else None))

                    # Meteen de eerste meting bij de AI-modellen, niet pas over
                    # een week. Een nieuwe klant die zeven dagen naar een lege
                    # pagina kijkt, zegt op voordat hij iets gezien heeft.
                    threading.Thread(
                        target=_meet_en_beoordeel,
                        args=(webshop_url, email, klant_token, base_url),
                        daemon=True,
                    ).start()
    except Exception as e:
        # Dit was het gevaarlijkste stukje van het hele bedrijf. De claim staat
        # op dat moment al vast, dus zonder wat hieronder gebeurt stopt elke
        # volgende melding van Mollie bij "was al verwerkt" en is de betaling
        # voorgoed onverwerkbaar. De klant heeft betaald, krijgt niets, en er
        # gaat nergens een belletje. Nu gaat de claim terug EN krijg jij bericht.
        print(f"Verwerken van betaling {payment_id} mislukt: {e}")
        try:
            db.ontclaim_payment(payment_id)
        except Exception as e2:
            print(f"Claim terugdraaien mislukt na fout: {e2}")
        _meld_aan_beheer(
            "Betaling niet verwerkt",
            f"Bij betaling {payment_id} ging er iets mis na de betaling: "
            f"{type(e).__name__}: {e}. Mollie stuurt deze melding niet opnieuw. Ga naar "
            f"{get_base_url()}/admin/bestellingen en klik bij deze bestelling op 'Opnieuw "
            f"verwerken'. Blijft het misgaan, doe het dan met de hand of geef het geld terug.")


@app.route("/admin/inloggen", methods=["GET", "POST"])
def admin_inloggen():
    """Het inlogscherm voor de beheerpagina's.

    Waarom dit bestaat: de sleutel stond in het webadres van elke beheerpagina.
    Dat staat dus ook in je browsergeschiedenis, in de logboeken van Render, en
    op elke schermafdruk die je maakt. Er is er in augustus al een keer een in
    een schermafdruk in een chat beland. Met nul klanten is dat te overzien, met
    klanten niet meer.

    De sleutel blijft bestaan en ?key= blijft werken, want de cron-taken
    gebruiken hem. Wat er verandert: na een keer inloggen hoeft hij nergens meer
    in het adres, en kom je binnen met ?key=, dan onthouden wij het en halen wij
    hem meteen uit de adresbalk."""
    admin_key = os.environ.get("ADMIN_KEY")
    fout = None
    if request.method == "POST":
        if admin_key and _sleutel_klopt((request.form.get("sleutel") or "").strip(),
                                        admin_key):
            session.permanent = True
            session["beheer"] = True
            # 30 september: na het inloggen naar het portaal, niet naar een losse
            # pagina. En alleen naar een eigen beheerpagina, nooit naar buiten.
            verder = request.args.get("verder") or ""
            return redirect(verder if verder.startswith("/admin") else "/admin")
        # Bewust geen verschil tussen "geen sleutel ingesteld" en "verkeerde
        # sleutel". Dat verschil vertelt een vreemde iets wat hij niet hoeft te
        # weten.
        fout = "Die sleutel klopt niet."
    return render_template("admin_inloggen.html", fout=fout)


@app.route("/admin/uitloggen")
def admin_uitloggen():
    session.pop("beheer", None)
    return redirect("/admin/inloggen")


# Wat Brevo meldt over een verstuurde mail (stap 78, 24 september).
# Harde bounce of ongeldig adres: nooit meer naar dit adres. Spamklacht of
# afmelden via Brevo: behandelen als een afmelding (geen post meer, uit de
# index), want dat is wat zo iemand bedoelt. Een zachte bounce (brievenbus
# even vol) laten wij liggen.
BREVO_HARD = {"hard_bounce", "hardbounce", "invalid_email", "blocked", "error"}
BREVO_KLACHT = {"spam", "complaint", "unsubscribed", "unsubscribe"}


@app.route("/webhooks/brevo/<sleutel>", methods=["POST"])
def brevo_webhook(sleutel):
    """De sleutel in het adres is wat je in Render als BREVO_WEBHOOK_SLEUTEL
    zet en in Brevo achter het webhookadres plakt. Zonder die sleutel kan
    iedereen hier winkels afmelden, dus zonder sleutel bestaat deze route niet."""
    goed = (os.environ.get("BREVO_WEBHOOK_SLEUTEL") or "").strip()
    if not goed or not hmac.compare_digest(sleutel, goed):
        return "", 404
    data = request.get_json(silent=True) or {}
    items = data if isinstance(data, list) else [data]
    for item in items:
        soort = str(item.get("event") or "").lower().replace("-", "_")
        email = (item.get("email") or "").strip()
        if not email:
            continue
        if soort in BREVO_HARD:
            db.noteer_mailgebeurtenis(email, "bounce")
        elif soort in BREVO_KLACHT:
            for url in db.noteer_mailgebeurtenis(email, "klacht"):
                db.meld_benadering_af(url)
            if soort in ("spam", "complaint"):
                _meld_aan_beheer("Spamklacht op een koude mail",
                                 f"{email} markeerde onze mail als spam. De winkel is "
                                 f"afgemeld. Kijk op /admin/benadering naar het percentage.")
    return "", 200


@app.route("/webhooks/inbound/<sleutel>", methods=["POST"])
def inbound_webhook(sleutel):
    """De antwoordagent (stap 126): Brevo stuurt hier elke mail die op het
    antwoordadres binnenkomt. Zelfde sleutel als de Brevo-webhook hierboven,
    zodat er geen nieuwe sleutel in Render hoeft."""
    goed = (os.environ.get("BREVO_WEBHOOK_SLEUTEL") or "").strip()
    if not goed or not hmac.compare_digest(sleutel, goed):
        return "", 404
    import antwoordagent
    try:
        antwoordagent.verwerk(request.get_json(silent=True) or {}, get_base_url().rstrip("/"),
                              _meld_aan_beheer)
    except Exception as e:
        # Toch 200: anders stuurt Brevo hem steeds opnieuw. Wel een belletje.
        print(f"Antwoord verwerken mislukt: {e}")
        _meld_aan_beheer("Antwoord verwerken mislukt",
                         f"Er kwam een mail binnen op het antwoordadres, maar verwerken ging mis: "
                         f"{escape(str(e))}. Kijk in de Render-logs.")
    return "", 200


@app.route("/webhooks/mollie", methods=["POST"])
def mollie_webhook():
    """Mollie roept dit aan zodra de status van een betaling verandert.
    We antwoorden meteen en doen het werk op de achtergrond, anders denkt
    Mollie dat het mislukt is en stuurt het bericht steeds opnieuw."""
    payment_id = request.form.get("id")
    if not payment_id:
        return "", 400

    # BEWUST GEEN CLAIM HIER. Die zit in _verwerk_betaling, en pas nadat
    # vaststaat dat er echt betaald is.
    #
    # Dit stond hier wel, en dat kostte klanten. Mollie meldt bij elke
    # statuswissel: open, pending, canceled, failed en paid. De melding bij
    # "pending" verbruikte de claim, en de melding bij "paid" werd daarna
    # weggegooid als "was al verwerkt". Wie met iDEAL of een overboeking
    # betaalde kreeg dus niets: geen factuur, geen rapport, geen mail, en geen
    # foutmelding waaruit je het had kunnen afleiden.
    base_url = get_base_url()
    threading.Thread(target=_verwerk_betaling, args=(payment_id, base_url), daemon=True).start()
    return "", 200


def meetdag(webshop_url):
    """Op welke dag van de week deze klant aan de beurt is. Maandag is 0.

    Elke klant krijgt een vaste dag, afgeleid van zijn eigen webadres. Dezelfde
    winkel komt dus altijd op dezelfde dag uit, ook na een herstart, en zonder
    dat we er iets voor hoeven op te slaan.

    Waarom dit nodig is: alle abonnees op een dag meten kost bij vijftig klanten
    meer dan de dagelijkse kostenrem toelaat. Die rem zou dan halverwege de dag
    ingrijpen en de rest van de klanten die week overslaan, zonder dat iemand
    dat merkt. Spreiden is beter dan de rem verhogen, want de rem moet blijven
    doen waar hij voor is."""
    schoon = (webshop_url or "").strip().lower()
    return sum(schoon.encode("utf-8")) % 7


def _is_aan_de_beurt(webshop_url, vandaag, alles=False):
    """Of deze klant vandaag gemeten wordt.

    Naast de vaste dag zit er een vangnet in: is een klant meer dan negen dagen
    niet gemeten, dan gebeurt het alsnog. Anders zou een gemiste cron of een
    storing betekenen dat iemand een week overslaat zonder dat het opvalt."""
    if alles:
        return True

    vorige = db.get_previous_score(webshop_url)
    laatste = (vorige or {}).get("aangemaakt_op")

    # Vandaag al gemeten? Dan niet nog een keer. Vuurt de cron door een storing
    # twee keer, of opent iemand de link met de sleutel nog eens om te kijken of
    # hij werkt, dan kreeg elke klant twee keer dezelfde weekmail, kwamen er
    # twee rapporten in zijn verloop, en draaiden de AI-metingen dubbel. Die
    # kosten dus ook dubbel.
    if laatste is not None:
        try:
            # Allebei in UTC vergelijken (28 september). De database geeft de
            # tijd terug in zijn eigen tijdzone en "vandaag" is UTC; rond
            # middernacht vielen die op twee verschillende dagen, en dan werd
            # dezelfde klant in een nacht twee keer gemeten en gemaild.
            def _utc_dag(t):
                return (t.astimezone(timezone.utc) if t.tzinfo else t).date()
            if _utc_dag(laatste) == _utc_dag(vandaag):
                return False
        except (AttributeError, TypeError):
            pass

    if meetdag(webshop_url) == vandaag.weekday():
        return True

    if laatste is None:
        return True
    try:
        dagen = (vandaag - laatste).days
    except TypeError:
        return True
    if dagen > 9:
        print(f"{webshop_url} is {dagen} dagen niet gemeten, wordt nu alsnog gedaan.")
        return True
    return False


def _shopify_abonnees():
    """De Shopify-winkels die betalen voor monitoring.

    Dit hoort hier omdat het anders stilletjes misgaat: op het scherm in de app
    staat "elke week opnieuw gemeten", en dat is precies wat je verkoopt. Wordt
    deze lijst niet meegenomen in de wekelijkse ronde, dan betaalt iemand 39
    dollar per maand voor iets wat nooit gebeurt, en dat merkt hij pas na
    weken.

    De stand komt elke keer vers van Shopify. Kunnen wij hem niet ophalen, dan
    slaan wij de winkel over in plaats van te gokken: liever een week te laat
    gemeten dan iemand meten die niet betaalt."""
    uit = []
    try:
        winkels = db.get_shopify_winkels()
    except Exception as e:
        print(f"Shopify-abonnees ophalen mislukt: {e}")
        return uit
    for rij in winkels:
        if not rij.get("actief") or not rij.get("toegangssleutel"):
            continue
        if not rij.get("webshop_url"):
            continue
        sleutel = _shopify_sleutel(rij)
        if not sleutel:
            # Verlopen sleutel en geen bruikbare verversleutel. Daar is zonder
            # de winkelier niets aan te doen: hij moet de app een keer openen.
            print(f"Shopify: geen werkende sleutel voor {rij['winkel']}, overgeslagen.")
            continue
        try:
            stand = shopify_billing.huidig_abonnement(rij["winkel"], sleutel)
        except Exception as e:
            print(f"Abonnement nakijken mislukt voor {rij['winkel']}: {e}")
            continue
        if not stand.get("actief"):
            if stand.get("fout") and "404" in str(stand["fout"]) and "Not Found" in str(stand["fout"]):
                # 1 oktober (krillo-demo.myshopify.com): Shopify kent de winkel
                # niet meer. Een gesloten proefwinkel of een app die weg is. Dan
                # is er niets na te kijken en elke week dezelfde melding is ruis:
                # op inactief, en een keer melden.
                db.shopify_verwijderd(rij["winkel"])
                _meld_aan_beheer(
                    "Shopify-winkel bestaat niet meer",
                    f"Shopify kent {rij['winkel']} niet meer (404). Waarschijnlijk een gesloten proefwinkel of "
                    f"is de app verwijderd. De winkel staat nu op inactief; je krijgt hier geen meldingen meer over.")
                continue
            if stand.get("fout"):
                # Wij WETEN het niet. Deze winkel wordt deze week overgeslagen
                # terwijl op zijn scherm staat dat hij elke week gemeten wordt.
                # Dat mag niet stil gebeuren.
                _meld_aan_beheer(
                    "Abonnement niet na te kijken",
                    f"Bij {rij['winkel']} lukte het niet om het abonnement bij Shopify "
                    f"op te vragen: {stand['fout']}. Die winkel is deze ronde "
                    f"overgeslagen. Kijk of hij nog klant is.")
            continue
        adres = (rij.get("email") or "").strip()
        if not adres or not _EMAIL_VORM.match(adres):
            # Hier stond een verzonnen adres. Dat ziet eruit als "we hebben hem
            # bericht" terwijl de mail nergens aankomt, en op het scherm staat
            # dat hij een waarschuwing krijgt als er iets verandert. Dan liever
            # geen mail en wel een melding in de logs.
            print(f"LET OP: geen mailadres voor {rij['winkel']}, deze klant krijgt "
                  f"geen weekbericht. Vul het aan in de database.")
            continue
        uit.append({"webshop_url": rij["webshop_url"], "email": adres,
                    "winkel": rij["winkel"], "plan": stand.get("plan")})
    if uit:
        print(f"{len(uit)} betalende Shopify-winkel(s) meegenomen in de ronde.")
    return uit


def _shopify_automatisch_aanvullen(winkel, base_url):
    """Vult uit onszelf aan bij een winkel met een abonnement.

    Dit is wat er op de prijskaart staat: nieuwe producten worden opgepakt en
    ingevuld. Zonder deze functie was dat een belofte zonder dekking.

    Let op wat hier anders is dan bij de knop. Bij de knop ziet de eigenaar
    elk voorstel voordat er iets gebeurt. Hier niet, want er is niemand die
    kijkt. Wat hij koopt is juist dat wij het doen zonder dat hij ernaar hoeft
    te kijken. Daarom drie dingen: hij kan het uitzetten, hij krijgt achteraf
    een mail met precies wat er veranderd is, en elke wijziging blijft met een
    knop terug te draaien. Dat laatste is de reden dat dit te verantwoorden is.

    Verder gelden alle gewone regels nog: alleen invullen waar het leeg is,
    nooit iets overschrijven, en de oude waarde eerst bewaren."""
    rij = db.get_shopify_winkel(winkel) or {}
    if not rij.get("toegangssleutel") or not rij.get("webshop_url"):
        return None
    if not rij.get("automatisch", True):
        print(f"Automatisch aanvullen staat uit voor {winkel}.")
        return None

    # Niet twee keer op een dag. Draait de cron dubbel, dan zou dat dubbele
    # kosten bij het model geven voor hetzelfde werk.
    laatst = rij.get("automatisch_op")
    if laatst:
        try:
            if (datetime.now(timezone.utc) - laatst).days < 5:
                return None
        except (TypeError, AttributeError):
            pass

    webshop_url = rij["webshop_url"]
    ruimte = kosten.mag_doorgaan(webshop_url=webshop_url)
    if not ruimte["mag"]:
        print(f"Automatisch aanvullen overgeslagen voor {winkel}: {ruimte['reden']}")
        return None

    sleutel = _shopify_sleutel(rij)
    if not sleutel:
        print(f"Automatisch aanvullen overgeslagen voor {winkel}: geen werkende sleutel.")
        return None

    try:
        markt_gegevens = _markt_van(webshop_url)
        uitkomst = shopify_werk.maak_voorstellen(winkel, sleutel, markt_gegevens)
    except Exception as e:
        print(f"Automatisch aanvullen mislukt voor {winkel}: {e}")
        return None

    gedaan = []
    for voorstel in (uitkomst.get("voorstellen") or [])[:shopify_werk.AUTOMATISCH_PER_WEEK]:
        # Elke keer opnieuw opvragen. Vijfentwintig wijzigingen kunnen langer
        # duren dan het uur dat een sleutel geldig is.
        sleutel = _shopify_sleutel(rij)
        if not sleutel:
            print(f"Automatisch aanvullen afgebroken voor {winkel}: sleutel verlopen.")
            break
        uit = shopify_werk.pas_toe(winkel, sleutel, voorstel, webshop_url)
        if uit.get("gelukt"):
            gedaan.append({"wat": voorstel.get("wat"), "waar": voorstel.get("waar"),
                           "nieuw": voorstel.get("nieuw")})
            db.tel_shopify_wijziging(winkel)

    db.markeer_shopify_automatisch(winkel)
    if not gedaan:
        return None

    print(f"Automatisch aangevuld bij {winkel}: {len(gedaan)} wijziging(en).")
    adres = (rij.get("email") or "").strip()
    if adres and _EMAIL_VORM.match(adres):
        try:
            emailing.send_shopify_bijgewerkt(
                adres, webshop_url, gedaan,
                _app_adres_in_beheerscherm(winkel),
                taal=_mailtaal(webshop_url))
        except Exception as e:
            print(f"Bericht over bijwerken mislukt voor {winkel}: {e}")
    return gedaan


def _draai_wekelijkse_scans(base_url, alles=False):
    """STAP 66, 21 SEPTEMBER: alleen nog de scan, geen eigen AI-meting en geen mail.

    Tot 21 september kreeg elke betalende klant hier elke week een eigen
    AI-meting van zijn winkel en een wekelijkse mail: het model van voor de
    index. Sindsdien kreeg dezelfde klant OOK het maandbericht met zijn positie
    uit de index. Twee metingen, twee soorten mail, en de eigen meting kostte per
    klant per week geld terwijl het omzetmodel rekent met ongeveer een euro per
    Watch-klant per maand. Op de site wordt alleen maandelijks meten beloofd.

    Wat blijft: de scan van de dertien punten (geen AI, kost niets), het rapport
    dat daarbij bewaard wordt (daaraan ziet het dashboard dat er een abonnement
    loopt), en het automatisch aanvullen bij Shopify-winkels.

    Doet de scans op de achtergrond. Draait los van het verzoek, zodat de
    aanroeper niet hoeft te wachten en er niets vastloopt, ook niet als er
    straks honderd abonnees zijn.

    Deze functie mag elke dag aangeroepen worden. Er wordt dan per dag alleen
    het deel van de klanten gedaan dat die dag aan de beurt is, waardoor elke
    klant een keer per week gemeten wordt en de kosten over de week verdeeld
    zijn. Met alles=True wordt iedereen gedaan, ongeacht de dag."""
    try:
        vandaag = datetime.now(timezone.utc)
        customers = payments.list_active_monitoring_customers() + _shopify_abonnees()
        aan_de_beurt = [c for c in customers
                        if _is_aan_de_beurt(c["webshop_url"], vandaag, alles)]
        print(f"{len(customers)} actieve klant(en), {len(aan_de_beurt)} vandaag aan de beurt.")
        for c in aan_de_beurt:
            try:
                was_dicht = scan_engine.staat_achter_wachtwoord(c["webshop_url"])
                scan_result = run_scan(c["webshop_url"])
                if "error" in scan_result:
                    print(f"Scan mislukt voor {c['webshop_url']}, overgeslagen.")
                    continue

                db.zet_platform(c["webshop_url"], scan_result.get("platform"))
                klant_token = db.get_or_create_klant(c["webshop_url"], c["email"])
                # Vangnet: staat een betalende klant nog niet op de winkellijst,
                # dan komt hij er nu op. Zonder dit krijgt hij nooit een positie.
                _zet_in_index(c["webshop_url"])
                db.save_report("monitoring", c["webshop_url"], c["email"], scan_result.get("score", 0),
                                scan_result.get("checks", []), None, None, klant_token)
                if was_dicht:
                    _meld_winkel_open(c["webshop_url"], c["email"], klant_token, scan_result.get("score", 0))
                # Hier stonden tot 21 september de eigen AI-meting van deze
                # winkel en de wekelijkse mail. De reden stond erbij: "waar een
                # klant voor betaalt is of AI hem noemt." Dat klopt nog steeds,
                # maar dat antwoord komt sinds de index uit de maandelijkse
                # meting van zijn categorie, met het maandbericht erbij. Twee
                # metingen en twee soorten mail over dezelfde vraag verwarren
                # een klant en kosten per week geld. Zie stap 66 bovenaan.

                # Stap 198 (1 oktober, akkoord Nino): de wekelijkse snelmeting
                # van zijn vijf belangrijkste vragen. Eigen try: mislukt hij, dan
                # loopt de rest van de ronde gewoon door.
                try:
                    import snelmeting
                    v = snelmeting.meet(c["webshop_url"])
                    print(f"Snelmeting {c['webshop_url']}: {v}")
                    # 2 oktober (stap 180): de eigen vragen van de klant mee.
                    try:
                        import eigenvragen
                        print(f"Eigen vragen {c['webshop_url']}: {eigenvragen.meet(c['webshop_url'])}")
                    except Exception as e:
                        print(f"Eigen vragen mislukt voor {c['webshop_url']}: {e}")
                    # 2 oktober (goedgekeurd, als test): de weekmail met de uitkomst.
                    if v.get("gemeten"):
                        import weekmail
                        weekmail.stuur_voor(c["webshop_url"], c.get("email"), klant_token, base_url)
                        # 8 oktober: apart seintje als een vraag is weggevallen.
                        try:
                            weekmail.stuur_verloren(c["webshop_url"], c.get("email"), klant_token, base_url)
                        except Exception as e:
                            print(f"Weggevallen-vragen mail mislukt voor {c['webshop_url']}: {e}")
                except Exception as e:
                    print(f"Snelmeting mislukt voor {c['webshop_url']}: {e}")
                # Stap 255: de product- en categoriepagina's, per pagina wat AI mist.
                try:
                    import paginacheck
                    paginacheck.ronde(c["webshop_url"])
                except Exception as e:
                    print(f"Paginacheck mislukt voor {c['webshop_url']}: {e}")

                # Is dit een Shopify-winkel met Fix, dan vullen wij ook uit
                # onszelf aan. Dat staat op de prijskaart van Fix en zonder dit
                # is het een belofte zonder dekking. Watch krijgt dit bewust
                # niet: Watch is "de oplossingen uitgeschreven, om zelf te doen".
                if c.get("winkel") and c.get("plan") == "fix":
                    try:
                        _shopify_automatisch_aanvullen(c["winkel"], base_url)
                    except Exception as e:
                        print(f"Automatisch aanvullen mislukt voor {c['winkel']}: {e}")
            except Exception as e:
                print(f"Wekelijkse scan mislukt voor {c.get('webshop_url')}: {e}")
        print("Ronde afgerond.")
    except Exception as e:
        print(f"Wekelijkse scan volledig mislukt: {e}")


@app.route("/api/cron/weekly-scans", methods=["GET", "POST"])
def weekly_scans():
    """Wordt DAGELIJKS aangeroepen. Per dag is een deel van de klanten aan de
    beurt, zo verdeelt het werk en de kosten zich over de week en wordt elke
    klant een keer per week gemeten.

    Draait de cron nog wekelijks, zet er dan &alles=ja achter, dan wordt
    iedereen in een keer gedaan zoals vroeger. Bij meer dan ongeveer veertig
    klanten loopt dat tegen de dagelijkse kostenrem aan, dus dat is alleen
    bedoeld voor de overgang.

    Antwoordt meteen, het werk gebeurt op de achtergrond."""
    cron_key = os.environ.get("CRON_KEY")
    if not cron_key or not _sleutel_klopt(request.args.get("key"), cron_key):
        return "", 404

    alles = request.args.get("alles") == "ja"
    base_url = get_base_url()
    if not _ruimte_voor_zwaar_werk("wekelijkse scans"):
        return "later", 200
    # 8 oktober: de wachtklok doet dit ook (vangnet). Een keer per dag, wie
    # er ook eerst is; anders betaal je de weekvragen dubbel.
    if not alles and not db.claim_moment(WEEKSCANS_KLOK, 20 * 3600):
        return "al gedaan vandaag", 200
    threading.Thread(target=_draai_wekelijkse_scans, args=(base_url, alles), daemon=True).start()
    return "ok", 200


WEEKSCANS_KLOK = "wekelijkse_scans_klok"


@app.after_request
def _geen_sleutel_in_antwoord(antwoord):
    """Zie _zonder_beheersleutel: de beheersleutel gaat nooit mee naar de browser."""
    sleutel = (os.environ.get("ADMIN_KEY") or "").strip()
    if not sleutel or len(sleutel) < 12:
        return antwoord
    try:
        plek = antwoord.headers.get("Location")
        if plek and sleutel in plek:
            antwoord.headers["Location"] = _zonder_beheersleutel(plek, sleutel)
        soort = antwoord.mimetype or ""
        if (not antwoord.direct_passthrough and not antwoord.is_streamed
                and (soort.startswith("text/") or soort == "application/json")):
            tekst = antwoord.get_data(as_text=True)
            if sleutel in tekst:
                antwoord.set_data(_zonder_beheersleutel(tekst, sleutel))
    except Exception as e:
        print(f"Sleutel uit het antwoord halen mislukt: {e}")
    return antwoord


@app.after_request
def _shopify_inbed_kop(antwoord):
    """Een ingebedde app moet per verzoek zeggen wie hem in een venster mag zetten.

    Shopify eist dit voor de App Store, en het is tegelijk de enige bescherming
    tegen een willekeurige andere site die ons app-scherm in een onzichtbaar
    venster zet en de winkelier daarin laat klikken."""
    if not request.path.startswith("/shopify"):
        return antwoord
    winkel = shopify_app._schoon(request.args.get("shop") or "")
    if shopify_app.geldige_winkel(winkel):
        toegestaan = f"https://{winkel} https://admin.shopify.com"
    else:
        # Geen winkel in het verzoek, dus wij weten niet wie hem mag inbedden.
        # Dan niemand. Shopify stuurt bij het openen van het app-scherm altijd
        # de winkel mee, dus dit raakt geen echte bezoeker.
        toegestaan = "'none'"
    antwoord.headers["Content-Security-Policy"] = f"frame-ancestors {toegestaan};"
    return antwoord


_benadering_slot = threading.Lock()


def _benadering_ronde():
    """Een ronde, maar nooit twee tegelijk (24 september).

    De uurlijkse taak en de knop op de beheerpagina konden allebei een ronde
    starten. Twee rondes tegelijk kunnen dezelfde winkel kiezen voordat een
    van beide hem als gemaild markeert: dan krijgt hij twee koude mails."""
    if not _benadering_slot.acquire(blocking=False):
        print("Benadering, er loopt al een ronde; deze slaat over.")
        return
    try:
        return _benadering_ronde_werk()
    finally:
        _benadering_slot.release()


def _benadering_ronde_werk():
    """Eén rondje van de automatische benadering. Draait op de achtergrond.

    De volgorde is met opzet zo: eerst adressen zoeken (kost niets), dan meten
    (kost geld bij de modellen), dan pas mailen. Zo staat er altijd een voorraad
    gemeten winkels klaar en hoeft de post nooit te wachten op een meting.

    Alles wat deze ronde doet wordt onderweg opgeschreven in `verslag` en aan
    het eind bewaard. Dat is er bij gekomen omdat de lijst dagenlang op precies
    dezelfde standen bleef staan terwijl er elk uur een ronde langskwam, en van
    buitenaf niet te zien was welke van de zeven remmen dat deed. Nu staat het
    per ronde op de beheerpagina."""
    verslag = {"adressen": None, "gemeten_klaar": None, "ingepland": 0,
               "doorgezet": 0, "gemaild": 0, "mislukt": [], "redenen": []}
    benadering.onthoud_ronde()

    # De verkoopagent (stap 125): wie zijn pagina bekeek krijgt een persoonlijke
    # opvolging. Draait ook als de koude mail uit staat: dit zijn mensen die al
    # reageerden. Een fout hier mag de rest van de ronde nooit tegenhouden.
    if commandocentrum.aan("verkoop"):
        try:
            import verkoopagent
            verslag["opvolging"] = verkoopagent.ronde(
                get_base_url().rstrip("/"),
                lambda url: klantbeeld.bouw(url),
                categorienaam=lambda b: categorieen.naam_en(b["categorie"]),
                binnen_kantooruren=benadering.binnen_kantooruren())
        except Exception as e:
            verslag["mislukt"].append(f"opvolging: {e}")
            print(f"Verkoopagent mislukt: {e}")

    # Ontvangstbevestigingen die nog als concept klaarstaan alsnog afhandelen (29 september).
    try:
        import antwoordagent
        verslag["automatisch_opgeruimd"] = antwoordagent.ruim_automatische_op()
    except Exception as e:
        print(f"Automatische antwoorden opruimen mislukt: {e}")

    # De bewegingsagent (stap 116): wie gemaild is en na de maandmeting echt
    # verschoof, hoort het. Hoogstens een extra mail per 30 dagen (extra_op).
    if commandocentrum.aan("beweging"):
        try:
            import bewegingsagent
            verslag["beweging"] = bewegingsagent.ronde(
                get_base_url().rstrip("/"), lambda url: klantbeeld.bouw(url),
                categorienaam=lambda b: categorieen.naam_en(b["categorie"]),
                binnen_kantooruren=benadering.binnen_kantooruren(),
                aan=benadering.instellingen().get("aan", False))
        except Exception as e:
            verslag["mislukt"].append(f"beweging: {e}")
            print(f"Bewegingsagent mislukt: {e}")

    # De badge-agent (stap 89): de top van elke ranglijst krijgt een felicitatie
    # met een badge voor hun site. Zelfde rust en regels als de andere extra mail.
    if commandocentrum.aan("badge"):
        try:
            import badgeagent
            verslag["badge"] = badgeagent.ronde(
                get_base_url().rstrip("/"), lambda url: klantbeeld.bouw(url),
                categorienaam=lambda b: categorieen.naam_en(b["categorie"]),
                landnaam=lambda b: sitetaal.landnaam(b["land"], "en") if b.get("land") else None,
                binnen_kantooruren=benadering.binnen_kantooruren(),
                aan=benadering.instellingen().get("aan", False))
        except Exception as e:
            verslag["mislukt"].append(f"badge: {e}")
            print(f"Badge-agent mislukt: {e}")

    # De bureauvinder (stap 115): elk uur 15 winkels uit de index op een bureau
    # in de voettekst bekijken. Mailen gaat met de hand tot er tien weg zijn;
    # daarna alleen met BUREAUMAIL_AUTO=1, hoogstens twee per dag, in kantooruren.
    if commandocentrum.aan("bureau"):
        try:
            import bureauvinder
            verslag["bureaus"] = bureauvinder.ronde()
            ruimte = bureauvinder.mag_automatisch() if benadering.binnen_kantooruren() else 0
            for b in [b for b in bureauvinder.groepen() if b["stand"] == "nieuw" and b.get("email")][:ruimte]:
                _stuur_bureaumail(b, get_base_url().rstrip("/"), False)
        except Exception as e:
            verslag["mislukt"].append(f"bureaus: {e}")
            print(f"Bureauvinder mislukt: {e}")

    # De klantagenten (stap 99, 130, 152): behouden, overstappen, terugwinnen.
    # Alleen in kantooruren; elke mail langs de controleagent.
    if commandocentrum.aan("klant"):
        try:
            import klantagenten
            import verkoopagent
            if benadering.binnen_kantooruren():
                verslag["klanten"] = klantagenten.ronde(
                    get_base_url().rstrip("/"), lambda url: klantbeeld.bouw(url),
                    categorienaam=lambda b: categorieen.naam_en(b["categorie"]),
                    vraag_voor=verkoopagent._vraag_voor)
        except Exception as e:
            verslag["mislukt"].append(f"klantagenten: {e}")
            print(f"Klantagenten mislukt: {e}")

    # Stap 167: drie dagen voor het einde van de gratis proef een herinnering.
    if commandocentrum.aan("proef"):
        try:
            import proefperiode
            if benadering.binnen_kantooruren():
                verslag["proef"] = proefperiode.ronde(get_base_url().rstrip("/"), lambda url: klantbeeld.bouw(url),
                                                      prijs=_prijs_euro("watch") or 49)
                # 30 september: wie in de proef 3 of meer vragen op zijn lijst zette,
                # krijgt een keer de vraag of wij het live zetten (Fix).
                verslag["fix_aanbod"] = proefperiode.fix_aanbod_ronde(get_base_url().rstrip("/"),
                                                                      fix_prijs=_prijs_euro("fix") or 149)
                # Stap 129 (1 oktober): wie op dag 2 zijn dashboard nog niet opende
                # en niets koos, krijgt zijn drie verloren vragen.
                verslag["activatie"] = proefperiode.activatie_ronde(
                    get_base_url().rstrip("/"), lambda url: klantbeeld.bouw(url, max_vragen=5))
        except Exception as e:
            verslag["mislukt"].append(f"proef: {e}")
            print(f"Proefherinnering mislukt: {e}")

    # Stap 166: plekmeldingen, wie zijn plek claimde hoort het als die verandert.
    if commandocentrum.aan("plekmelding"):
        try:
            import plekmelding
            if benadering.binnen_kantooruren():
                verslag["plekmelding"] = plekmelding.ronde(
                    get_base_url().rstrip("/"), lambda url: klantbeeld.bouw(url),
                    categorienaam=lambda b: categorieen.naam_en(b["categorie"]))
        except Exception as e:
            verslag["mislukt"].append(f"plekmelding: {e}")
            print(f"Plekmelding mislukt: {e}")

    # De persagent (29 september): het persbericht een keer per maand vanzelf
    # naar de vakmedia, alleen als er nieuws is. Binnen kantooruren.
    if commandocentrum.aan("pers"):
        try:
            import persagent
            import indexnieuws
            if benadering.binnen_kantooruren():
                verslag["pers"] = persagent.ronde(
                    lambda land: _bewaard(("nieuws", land),
                                          lambda l: indexnieuws.overzicht(l, ranglijst=_ranglijst_bewaard), land),
                    lambda ov: indexnieuws.persbericht_nl(ov, get_base_url().rstrip("/"), embed=embed_code),
                    melden=_meld_aan_beheer)
        except Exception as e:
            verslag["mislukt"].append(f"pers: {e}")
            print(f"Persagent mislukt: {e}")

    # De LinkedIn-agent (29 september): een week vooruit de posts klaarzetten.
    if commandocentrum.aan("linkedin"):
        try:
            import linkedinagent
            verslag["linkedin"] = linkedinagent.klaarzetten(
                get_base_url().rstrip("/"),
                _bewaard(("perland", linkedinagent.LAND), db.categorieen_per_land, linkedinagent.LAND,
                         MINIMUM_PER_LAND) or [],
                _ranglijst_bewaard, categorieen.naam_en, sitetaal.landnaam(linkedinagent.LAND, "en"))
        except Exception as e:
            verslag["mislukt"].append(f"linkedin: {e}")
            print(f"LinkedIn-agent mislukt: {e}")

    # De artikelagent (stap 203, 30 september): op dinsdag een concept, Nino keurt goed.
    if commandocentrum.aan("artikel"):
        try:
            import artikelagent
            verslag["artikel"] = artikelagent.ronde()
        except Exception as e:
            verslag["mislukt"].append(f"artikel: {e}")
            print(f"Artikelagent mislukt: {e}")

    # De lijstjesagent (29 september): schrijvers van artikelen "beste GEO-tools"
    # een keer mailen, hoogstens drie per week, binnen kantooruren.
    if commandocentrum.aan("lijstjes"):
        try:
            import lijstjesagent
            if benadering.binnen_kantooruren():
                verslag["lijstjes"] = lijstjesagent.ronde(get_base_url().rstrip("/"))
        except Exception as e:
            verslag["mislukt"].append(f"lijstjes: {e}")
            print(f"Lijstjesagent mislukt: {e}")

    # De wachtlijst (stap 165): staat een land nu aan, dan krijgt wie erop wacht
    # een keer bericht. Zij vroegen er zelf om, dus ook buiten kantooruren niet
    # erg, maar wel netjes binnen: zelfde regel als de andere mail.
    if commandocentrum.aan("wachtlijst"):
        try:
            import wachtlijst
            if benadering.binnen_kantooruren():
                verslag["wachtlijst"] = wachtlijst.ronde(get_base_url().rstrip("/"))
        except Exception as e:
            verslag["mislukt"].append(f"wachtlijst: {e}")
            print(f"Wachtlijst mislukt: {e}")

    # Eerst kijken of de lijst zichzelf moet aanvullen. Zonder dit raakt de
    # benaderlijst gewoon op: bij vijftien mails per dag is tweehonderd winkels
    # binnen twee weken leeg, en dan staat de machine stil zonder dat er iets
    # kapot is. Dat gebeurt alleen als de voorraad onder de grens zakt, anders
    # betaal je voor namen die weken blijven liggen.
    try:
        aanvulling = winkelvinder.vul_aan_indien_nodig(
            ronde=benadering.rondenummer())
        verslag["gevonden_winkels"] = aanvulling.get("nieuw", 0)
        if aanvulling.get("gezocht") and aanvulling.get("reden"):
            verslag["redenen"].append(aanvulling["reden"])
    except Exception as e:
        verslag["mislukt"].append(f"winkels zoeken: {e}")
        print(f"Benadering, winkels zoeken mislukt: {e}")

    try:
        gevonden = benadering.zoek_adressen()
        verslag["adressen"] = gevonden
        print(f"Benadering, adressen: {gevonden}")
    except Exception as e:
        verslag["mislukt"].append(f"adressen zoeken: {e}")
        print(f"Benadering, adressen zoeken mislukt: {e}")

    try:
        # En de winkels die eerder afvielen nog een keer, met de verbeterde
        # zoeker. Op 12 september stonden er 476 op "geen adres" tegen 157 met
        # een adres: driekwart van alles wat de vinder oplevert werd weggegooid.
        # Die winkels hebben bijna allemaal wel een adres, het stond alleen niet
        # op de eerste vijf pagina's die wij bekeken. Kost geen AI-geld.
        herkansing = benadering.herkans_adressen()
        if herkansing.get("bekeken"):
            verslag["herkansing"] = herkansing
            print(f"Benadering, tweede kans op een adres: {herkansing}")
    except Exception as e:
        verslag["mislukt"].append(f"adressen herkansen: {e}")
        print(f"Benadering, herkansing mislukt: {e}")

    try:
        # Stap 306: winkels zonder adres op hun site, via de zoekmachine.
        via_zoek = benadering.adressen_via_zoekmachine()
        if via_zoek.get("bekeken"):
            verslag["zoekmachine"] = via_zoek
            print(f"Benadering, adressen via de zoekmachine: {via_zoek}")
    except Exception as e:
        verslag["mislukt"].append(f"adressen via zoekmachine: {e}")
        print(f"Benadering, zoekmachine mislukt: {e}")

    try:
        # Winkels die geklikt hebben maar geen meting kregen omdat de dagpot op
        # was. Die staan vooraan in de rij: iemand die op zijn uitkomst klikt is
        # het beste wat er die dag gebeurt, en in de mail is hem een grotere
        # meting beloofd.
        wachtenden = benadering.wachtenden_op_volledige_meting()
        for url in wachtenden:
            if _volledige_meting_na_klik(url):
                verslag["ingehaald"] = verslag.get("ingehaald", 0) + 1
        if wachtenden:
            print(f"Benadering, uitgestelde metingen opgepakt: {wachtenden}")
    except Exception as e:
        verslag["mislukt"].append(f"uitgestelde metingen: {e}")
        print(f"Benadering, uitgestelde metingen mislukt: {e}")

    try:
        # Aan beide kanten door dezelfde schrijfwijze halen voordat wij
        # vergelijken.
        #
        # Waarom: dit is de vergelijking die bepaalt of een winkel van "meten"
        # naar "gemeten" gaat, en dus of hij ooit post krijgt. Klopt hij niet,
        # dan wordt dezelfde winkel elk uur opnieuw gemeten en gaat er nooit
        # iets uit, zonder dat er ergens een foutmelding verschijnt. De
        # rapporten van voor september staan nog in de oude schrijfwijze, met
        # www ervoor of http in plaats van https, en die zouden hier stil langs
        # elkaar heen lopen.
        # LET OP de ondergrens hieronder. Een winkel telt pas als gemeten als de
        # meting ook bruikbaar is voor post. Stond hier "meer dan nul vragen", dan
        # gebeurde dit: een winkel met vijf vragen ging naar "gemeten", de mail
        # weigerde hem omdat er minstens tien nodig zijn, de ronde zette hem terug
        # op "adres", en de volgende ronde zag "meer dan nul" en zette hem weer op
        # "gemeten". Eeuwig rond, en nooit post.
        # LET OP: dit hangt NIET meer aan het demorapport. Dat rapport werd
        # maandenlang niet bewaard door een NOT NULL op de kolom email, en
        # daardoor gold geen enkele meting als bruikbaar terwijl er 55 winkels
        # met beoordeelde antwoorden stonden. "Bruikbaar" hoort te hangen aan
        # het enige dat telt: genoeg meegetelde vragen om post te kunnen sturen.
        al_gemeten = {scan_engine.normalize_url(u)
                      for u in db.winkels_met_genoeg_vragen(MINIMUM_VRAGEN_VOOR_POST)}
        verslag["gemeten_klaar"] = len(al_gemeten)
        # Opruimen gaat voor de geldcontrole uit, en dat is geen detail. Zolang
        # dit binnen te_meten zat werd er bij een lege dagpot niets vrijgemaakt,
        # en bleven winkels voorgoed op "meten" staan. Opruimen kost niets.
        verslag["vrijgemaakt"] = benadering.maak_vastgelopen_metingen_vrij(al_gemeten)

        # De wachtrij staat in het geheugen en verdwijnt bij elke herstart van
        # Render, ook bij een nieuwe versie. Winkels bleven dan op "meten" staan
        # terwijl er niets meer liep, en kwamen pas zes uur later weer aan de
        # beurt. Ondertussen zette elke ronde er vijf nieuwe bij, dus de teller
        # "meten" liep op naar vijfenzestig zonder dat er iets gebeurde.
        #
        # Nu: staat de wachtrij leeg en loopt er niets, dan pakken wij eerst op
        # wat er al op "meten" staat, voordat wij er nieuwe bij zetten.
        verslag["opnieuw_opgepakt"] = _hervat_onderbroken_metingen()

        # Een keer per dag het volume verdubbelen tot het doel bereikt is.
        # Niet in een keer naar honderd: Gmail en Outlook kijken vooral naar
        # hoe SNEL je volume oploopt, en een jong domein dat van vijftien
        # naar honderd springt ziet er precies zo uit als een gekaapt domein.
        # Eerst de rem (stap 117): landt de post slecht, dan eerst omlaag.
        try:
            rem = benadering.rem_als_nodig(melden=_meld_aan_beheer)
            if rem.get("geremd"):
                verslag["volume"] = f"geremd van {rem['van']} naar {rem['naar']} per dag"
        except Exception as e:
            print(f"Rem nakijken mislukt: {e}")
        opbouw = benadering.verhoog_volume_stapsgewijs()
        if opbouw.get("verhoogd"):
            verslag["volume"] = f"{opbouw['van']} naar {opbouw['naar']} per dag"

        # En niet nog meer inplannen zolang er nog werk ligt. Zonder deze rem
        # groeit de lijst sneller dan de werker hem afwerkt, en dan zegt de
        # pagina "65 in meting" terwijl er een voor een gemeten wordt.
        in_de_rij = len(_demo_wachtrij) + _metingen_bezig()
        verslag["in_de_rij"] = in_de_rij
        ruimte = kosten.ruimte_voor_benadering()
        verslag["dagpot"] = {
            "besteed": (round(ruimte["besteed"], 2)
                        if ruimte.get("besteed") is not None else None),
            "grens": (round(ruimte["grens"], 2)
                      if ruimte.get("grens") is not None else None),
            "past_nog": ruimte.get("past_nog"),
        }
        # Niet meer inplannen dan er met de rest van de dagpot betaald kan
        # worden. Zonder deze grens plande een ronde er gewoon vijf in, ook als
        # er nog maar twee euro over was. Die metingen worden dan halverwege
        # afgekapt door de rem: wel betaald bij de modellen, geen uitkomst, en
        # de winkel blijft op "meten" staan tot hij na zes uur opnieuw mag.
        past = ruimte.get("past_nog")
        hoeveel = None if past is None else min(
            past, benadering.instellingen()["metingen_per_ronde"])
        mag_meten = (ruimte["mag"] and (hoeveel is None or hoeveel > 0)
                     and in_de_rij < WACHTRIJ_VOL)
        klaar_te_meten = (benadering.te_meten(hoeveel=hoeveel, al_gemeten=al_gemeten)
                          if mag_meten else [])
        if in_de_rij >= WACHTRIJ_VOL:
            verslag["redenen"].append(
                f"Er staan al {in_de_rij} metingen in de rij, dus er zijn er geen "
                f"nieuwe bij gezet. Een meting duurt minuten en ze gaan een voor "
                f"een.")
        if ruimte["mag"] and hoeveel == 0:
            verslag["redenen"].append("Er is nog wel dagpot over, maar niet genoeg "
                                      "voor een hele meting.")
            print("Benadering, geen metingen deze ronde: er is nog wel dagpot over, "
                  "maar niet genoeg voor een hele meting.")
        if not ruimte["mag"]:
            verslag["redenen"].append(ruimte["reden"])
            print(f"Benadering, geen metingen deze ronde: {ruimte['reden']}")
        if ruimte["mag"] and (hoeveel is None or hoeveel > 0) and not klaar_te_meten:
            verslag["redenen"].append("Er stond geen enkele winkel klaar om te "
                                      "meten: alles staat al op gemeten, in de "
                                      "meting, of zonder adres.")
        if klaar_te_meten:
            # EERST vastleggen dat deze winkels in de meting zitten, en pas
            # daarna de meting starten. Andersom gaat er een ronde overheen
            # waarin ze nog op "adres" staan, komen ze opnieuw aan de beurt, en
            # betaal je twee keer voor dezelfde meting. Dat is precies wat er
            # gebeurd is: vijf winkels, elk drie tot vijf keer gemeten.
            benadering.markeer_in_meting(klaar_te_meten)
            erbij = _demo_inplannen(klaar_te_meten, benchmark_stand=True,
                                    vragen=BENADERING_VRAGEN,
                                    aanbieders=BENADERING_AANBIEDERS)
            verslag["ingepland"] = len(klaar_te_meten)
            verslag["winkels"] = [str(u) for u in klaar_te_meten[:5]]
            if not erbij:
                # Dit is het geval waar wij eerder blind voor waren: de winkels
                # gaan wel op "meten" maar de wachtrij pakt ze niet op, en dan
                # blijft de lijst dagenlang op precies dezelfde standen staan.
                verslag["redenen"].append(
                    f"{len(klaar_te_meten)} winkel(s) klaargezet, maar de meetrij "
                    f"nam er geen enkele aan.")
            print(f"Benadering, in de meetrij gezet: {len(klaar_te_meten)}")
        # Winkels waarvan de meting inmiddels klaar is doorzetten naar 'gemeten'.
        # Ook de winkels die nu op "meten" staan, want daar zit de winst: die
        # zijn betaald en moeten niet nog een keer.
        doorgezet = 0
        for winkel in db.get_benaderingen(stand=("adres", "meten")):
            if scan_engine.normalize_url(winkel["webshop_url"]) in al_gemeten:
                db.zet_benadering(winkel["webshop_url"], stand="gemeten")
                doorgezet += 1
        verslag["doorgezet"] = doorgezet

        # En de andere kant op: staat een winkel op "gemeten" terwijl zijn meting
        # niet bruikbaar is, dan hoort hij daar niet te staan.
        #
        # Waarom dit nodig is. Op 11 september stonden er 43 winkels op "gemeten"
        # en zei de pagina "43 winkels staan klaar om post te krijgen". Dat was
        # niet waar: die waren allemaal gemeten toen de kostenrem nog na drie
        # vragen afkapte, en de mail weigert onder de tien. Elke ronde probeerde
        # er drie, kreeg drie keer nul, en zette er drie terug. Dat zijn vijftien
        # rondes om de lijst één keer door te komen, en ondertussen stond er een
        # getal op het scherm dat niets betekende.
        #
        # Nu gebeurt het in één keer en klopt de teller meteen.
        terug = 0
        opgegeven = 0
        for winkel in db.get_benaderingen(stand="gemeten"):
            if scan_engine.normalize_url(winkel["webshop_url"]) in al_gemeten:
                # Deze had wel genoeg vragen. Teller schoon, want de
                # geschiedenis doet er niet meer toe.
                benadering.vergeet_meetpogingen(winkel["webshop_url"])
                continue
            # Hoe vaak hebben wij het bij deze winkel al geprobeerd? Dit is de
            # rem die er niet was. Zonder deze telling kwam dezelfde winkel elke
            # dag terug, kostte elke dag geld, en werd elke dag opnieuw
            # geweigerd voor de mail. Dat is geen storing die overgaat: bij
            # sommige winkels noemt AI bij die koopvragen gewoon nooit een
            # winkel, en dan is er morgen ook niets te melden.
            poging = benadering.tel_meetpoging(winkel["webshop_url"])
            if poging >= benadering.MAX_MEETPOGINGEN:
                db.zet_benadering(
                    winkel["webshop_url"], stand="afgevallen",
                    notitie=(f"Na {poging} metingen nog steeds te weinig vragen waar "
                             f"AI een winkel noemt. Hier valt geen eerlijke uitkomst "
                             f"over te sturen, dus wij stoppen ermee."))
                opgegeven += 1
                continue
            db.zet_benadering(
                winkel["webshop_url"], stand="adres",
                notitie=(f"Meting haalde te weinig vragen, opnieuw ingepland "
                         f"(poging {poging} van {benadering.MAX_MEETPOGINGEN})."))
            terug += 1
        verslag["terug_naar_meten"] = terug
        verslag["opgegeven"] = opgegeven
        if terug:
            verslag["redenen"].append(
                f"{terug} winkel(s) stonden op 'gemeten' met een meting die te weinig "
                f"vragen haalde. Die worden opnieuw gemeten.")
    except Exception as e:
        verslag["mislukt"].append(f"meten: {e}")
        print(f"Benadering, meten mislukt: {e}")

    try:
        mag, reden = benadering.hoeveel_mag_er_nu()
        if not mag:
            verslag["redenen"].append(reden)
            print(f"Benadering, geen post deze ronde: {reden}")
            benadering.onthoud_rondeverslag(verslag)
            return
        # 30 september: meer kandidaten ophalen dan er mogen, en doorgaan tot
        # er `mag` verstuurd zijn. Hiervoor haalde de ronde er precies `mag`
        # op. Stonden bovenaan vijf winkels zonder bruikbare plek (GEEN_POSITIE),
        # dan ging er niets uit, en de volgende ronde stonden diezelfde vijf er
        # weer: de post stond stil terwijl er honderden klaar lagen.
        # 30 september (bel-air.be): eerst de site zelf lezen. Alleen wie daar
        # als webshop in de goede categorie uitkomt, kan hierna post krijgen.
        try:
            import categoriecheck
            verslag["categoriecheck"] = categoriecheck.ronde()
        except Exception as e:
            verslag["mislukt"].append(f"categoriecheck: {e}")
            print(f"Categoriecheck mislukt: {e}")
        beurt = benadering.te_mailen(mag * KANDIDATEN_FACTOR)
        if not beurt:
            verslag["redenen"].append("Er mocht wel post uit, maar geen enkele winkel "
                                      "was aan de beurt: gemeten, adres bekend en nog "
                                      "nooit gemaild.")
        for winkel in beurt:
            if verslag["gemaild"] >= mag:
                break
            gelukt, fout = _stuur_onderzoeksmail(winkel["webshop_url"], winkel["email"],
                                                 winkel.get("land"))
            if not gelukt and str(fout or "").startswith("GEEN_POSITIE"):
                # Een week uit de rij, dan staat hij niet meer vooraan te blokkeren.
                # Is zijn categorie dan gemeten, dan komt hij vanzelf terug.
                db.zet_overgeslagen(winkel["webshop_url"])
            benadering.markeer_gemaild(winkel["webshop_url"], gelukt, fout)
            if gelukt:
                # Ook in het winkelprofiel, want dat is wat de beheerpagina
                # toont. Stond het alleen op de benaderlijst, dan zag je daar
                # een lege kolom en drukte je met de hand nog eens op versturen.
                db.markeer_onderzoeksmail(winkel["webshop_url"])
                verslag["gemaild"] += 1
                # De namen erbij, niet alleen het aantal. "gemaild: 2" laat je
                # nog steeds raden of het echt gebeurd is en naar wie.
                verslag.setdefault("naar", []).append(
                    f"{winkel['webshop_url']} ({winkel['email']})")
            else:
                verslag["mislukt"].append(
                    f"mail {winkel['webshop_url']}: {str(fout)[:120]}")
            print(f"Benadering, mail naar {winkel['webshop_url']}: "
                  f"{'gelukt' if gelukt else fout}")
    except Exception as e:
        verslag["mislukt"].append(f"mailen: {e}")
        print(f"Benadering, mailen mislukt: {e}")

    # Het warmste publiek dat er is: mensen die zelf hun mailadres invulden voor
    # de gratis test. Die kregen tot nu toe hun uitkomst en daarna nooit meer
    # iets. Bewust NA de benadering, want dit gaat om een handvol mails per dag
    # en de benaderlijst is groter.
    try:
        verslag["opgevolgd"] = _volg_gratis_tests_op()
    except Exception as e:
        verslag["mislukt"].append(f"opvolging: {e}")
        print(f"Opvolging gratis tests mislukt: {e}")

    benadering.onthoud_rondeverslag(verslag)
    _dagbericht_sturen()


# Hoeveel dagen na de gratis test wij nog een keer schrijven. Kort genoeg dat
# iemand het zich herinnert, lang genoeg dat het niet als een verkoopmachine
# leest.
OPVOLGEN_NA_DAGEN = int(os.environ.get("OPVOLGEN_NA_DAGEN", "3"))
OPVOLGEN_PER_RONDE = int(os.environ.get("OPVOLGEN_PER_RONDE", "3"))


def _volg_gratis_tests_op():
    """Stuurt een tweede bericht aan aanvragers van de gratis test.

    Houdt zich aan dezelfde klok en dezelfde schakelaar als de rest van de post.
    Staat de benadering uit, dan gaat hier ook niets uit: dat is een schakelaar
    voor alle ongevraagde post, niet alleen voor de benaderlijst.

    Wat hier anders is dan bij de benadering: deze mensen hebben er zelf om
    gevraagd. Ze krijgen precies een herinnering en daarna nooit meer."""
    inst = benadering.instellingen()
    if not inst["aan"] or not benadering.binnen_kantooruren():
        return 0
    gedaan = 0
    for lead in db.leads_om_op_te_volgen(na_dagen=OPVOLGEN_NA_DAGEN,
                                         hoeveel=OPVOLGEN_PER_RONDE):
        try:
            if db.is_afgemeld(lead["webshop_url"]):
                db.markeer_lead_opgevolgd(lead["id"])
                continue
            # STAP 118 (28 september): persoonlijk als de winkel in de index
            # staat, met de ene vraag die hij verliest, zoals de verkoopagent.
            # Anders de algemene herinnering van altijd.
            gelukt, ronde, persoonlijk = _persoonlijke_opvolging(lead)
            if gelukt is None:
                gelukt = emailing.send_opvolging_gratis_test(
                    lead["email"], lead["webshop_url"], get_base_url(),
                    taal=_mailtaal(lead["webshop_url"]))
            # Ook bij een mislukte verzending afvinken. Blijft hij openstaan,
            # dan probeert elke ronde hetzelfde adres opnieuw, en een adres dat
            # blijft weigeren is precies wat je reputatie sloopt.
            db.markeer_lead_opgevolgd(lead["id"], ronde=ronde, persoonlijk=persoonlijk)
            if gelukt:
                gedaan += 1
            print(f"Opvolging naar {lead['email']} voor {lead['webshop_url']}: "
                  f"{'gelukt' if gelukt else 'mislukt'}")
        except Exception as e:
            print(f"Opvolging mislukt voor {lead.get('email')}: {e}")
    try:
        gedaan += _stuur_maandberichten()
    except Exception as e:
        print(f"Maandberichten na de gratis check mislukt: {e}")
    return gedaan


def _afmeldlink(webshop_url):
    token = db.get_benchmark_token(webshop_url)
    basis = get_base_url().rstrip("/")
    return (f"{basis}/afmelden/{token}" if token else None), (f"{basis}/uitkomst/{token}" if token else basis)


def _persoonlijke_opvolging(lead):
    """De tweede mail na de gratis check, persoonlijk. Geeft (gelukt, ronde,
    persoonlijk); gelukt is None als er niets persoonlijks te zeggen valt."""
    import verkoopagent as va
    url = lead["webshop_url"]
    try:
        beeld = klantbeeld.bouw(url)
    except Exception as e:
        print(f"Beeld voor opvolging mislukt voor {url}: {e}")
        beeld = None
    if not beeld or not beeld.get("positie"):
        return None, None, False
    afmeld, pagina = _afmeldlink(url)
    vraag = va._vraag_voor(url, beeld)
    ontbreekt = None
    if vraag and vraag.get("concurrenten"):
        try:
            import vraagaanpak
            ontbreekt = vraagaanpak.wat_ontbreekt(url, vraag["vraag"])
        except Exception as e:
            print(f"Wat ontbreekt nakijken mislukt voor {url}: {e}")
    concept = va.maak_concept({"webshop_url": url}, beeld, vraag, link_url=pagina,
                              nummer=1, categorienaam=categorieen.naam_en(beeld["categorie"]),
                              versie=va.kies_versie(url), aanleiding="check", ontbreekt=ontbreekt)
    if not concept:
        return None, None, False
    gelukt = emailing.send_opvolging(lead["email"], concept["onderwerp"], concept["alineas"],
                                     concept["link"], afmeld_url=afmeld)
    return gelukt, beeld.get("ronde"), True


MAANDBERICHTEN_PER_RONDE = int(os.environ.get("MAANDBERICHTEN_PER_RONDE", "5"))


def _stuur_maandberichten():
    """De derde mail na de gratis check: zijn nieuwe plek, maar alleen als er
    sinds de tweede mail een nieuwe meting is. Geen nieuws, geen mail."""
    import verkoopagent as va
    gedaan = 0
    for lead in db.leads_voor_maandbericht(limiet=MAANDBERICHTEN_PER_RONDE * 4):
        if gedaan >= MAANDBERICHTEN_PER_RONDE:
            break
        url = lead["webshop_url"]
        if db.is_afgemeld(url):
            db.markeer_maandbericht(lead["id"], True)  # nooit meer proberen
            continue
        try:
            beeld = klantbeeld.bouw(url)
        except Exception:
            beeld = None
        if not beeld or not beeld.get("ronde") or beeld.get("ronde") == lead.get("opvolg_ronde"):
            db.markeer_maandbericht(lead["id"], False)
            continue
        afmeld, pagina = _afmeldlink(url)
        bericht = va.maak_maandbericht(beeld, link_url=pagina,
                                       categorienaam=categorieen.naam_en(beeld["categorie"]))
        gelukt = bool(bericht) and emailing.send_opvolging(
            lead["email"], bericht["onderwerp"], bericht["alineas"], bericht["link"], afmeld_url=afmeld)
        # Ook mislukt afvinken: hetzelfde adres elke ronde opnieuw proberen
        # sloopt de reputatie van het domein.
        db.markeer_maandbericht(lead["id"], True)
        gedaan += 1 if gelukt else 0
    return gedaan


def _dagbericht_sturen():
    """Eén keer per dag een berichtje aan jezelf over hoe de benadering loopt.

    Dit bestaat omdat de lijst drie dagen stilstond en dat pas opviel toen er
    met de hand op de beheerpagina gekeken werd. Een machine die stilstaat en
    daar niets over zegt kost elke dag geld en levert niets op. Liever een mail
    te veel dan nog een keer drie dagen niets.

    Faalt hij, dan gebeurt er verder niets. Een bericht over de ronde mag de
    ronde zelf nooit omgooien."""
    ontvanger = os.environ.get("BEHEERDER_EMAIL")
    if not ontvanger:
        return
    try:
        if benadering.dagbericht_al_gestuurd():
            return
        # Alleen binnen de uren dat er post uitgaat, anders krijg je het bericht
        # om zes uur 's ochtends terwijl de dag nog niets gedaan heeft.
        if not benadering.binnen_kantooruren():
            return
        bezig = len([1 for stand in _demo_status.values()
                     if stand and stand != "klaar" and not stand.startswith("mislukt")])
        dagpot = kosten.ruimte_voor_benadering()
        diagnose = benadering.waarom_gaat_er_niets_uit(
            moment_laatste_ronde=benadering.laatste_ronde(),
            meetruimte=dagpot, metingen_bezig=bezig)
        _, regels = benadering.dagbericht_tekst(
            diagnose, dagpot=dagpot, trechter=db.trechter_benadering())
        # Sinds stap 132 (28 september) is het dagbericht het ochtendbericht:
        # eerst wat jij moet doen, dan wat elke agent deed, dan deze diagnose.
        import ochtendbericht
        # Trage pagina's sinds de laatste start (29 september).
        t = traag_overzicht()
        if t["traag"]:
            ergste = t["paden"][0]
            regels = list(regels) + [f"Trage pagina's sinds de laatste start: {t['traag']} van {t['totaal']} "
                                     f"verzoeken duurden {TRAAG_SECONDEN:g} seconden of langer. Traagste: "
                                     f"{ergste['pad']} ({ergste['max']} s, {ergste.get('vragen', 0)} "
                                     f"databasevragen). Alles op /admin/traag."]
        # De afstand tot de database, elke ochtend (30 september). Boven de
        # 40 ms staan Render en Neon te ver uit elkaar, en dat is dan de oorzaak.
        reis = db.reistijd_ms()
        if reis is not None and reis > 40:
            regels = list(regels) + [f"Een reis naar de database duurt {reis:g} ms. Dat is te ver: zet "
                                     f"de webservice in Render in de regio Frankfurt, net als Neon."]
        # 1 oktober: het geheugen en of de nacht afkwam. Na de herstart van die
        # nacht kwam er geen bericht en wist niemand waarom.
        # 2 oktober: de nachtregel staat nu bovenaan (ochtendbericht.nachtregel).
        onderwerp, body = ochtendbericht.tekst(
            ochtendbericht.verzamel(get_base_url().rstrip("/")), extra_regels=regels)
        if emailing.send_email(ontvanger, onderwerp, body):
            benadering.onthoud_dagbericht()
    except Exception as e:
        print(f"Dagbericht mislukt: {e}")


def _nu_meten_en_mailen(webshop_url):
    """Eén winkel meteen meten en daarna zijn uitkomst mailen.

    Dit staat naast de gewone ronde en niet erin, met opzet. De ronde houdt zich
    aan de dagpot, aan de klok en aan de rondelimiet, en dat hoort ook zo. Maar
    als er dagenlang niets uitgaat wil je één winkel kunnen pakken en met eigen
    ogen zien waar het stukloopt, in plaats van nog een uur te wachten op een
    ronde die het weer stil overslaat.

    Wat hij wel blijft respecteren: de kostenrem per meting en het feit dat een
    winkel maar één keer post krijgt. Hij mag dus geld kosten, maar hij kan geen
    dubbele mail sturen."""
    verslag = {"handmatig": webshop_url, "gemaild": 0, "mislukt": [], "redenen": []}
    try:
        winkel = None
        for rij in db.get_benaderingen(alleen_niet_afgemeld=False):
            if scan_engine.normalize_url(rij["webshop_url"]) == webshop_url:
                winkel = rij
                break
        if winkel is None:
            verslag["redenen"] = ["Deze winkel staat niet op de benaderlijst."]
        elif winkel.get("gemaild_op"):
            verslag["redenen"] = ["Deze winkel heeft al post gehad, dus er gaat niets uit."]
        elif not winkel.get("email"):
            verslag["redenen"] = ["Van deze winkel kennen wij geen algemeen "
                                  "e-mailadres, dus er kan niets heen."]
        else:
            benadering.markeer_in_meting([webshop_url])
            _demo_draaien(webshop_url, benchmark_stand=True,
                          vragen=BENADERING_VRAGEN,
                          aanbieders=BENADERING_AANBIEDERS)
            stand = _demo_status.get(webshop_url) or ""
            if stand.startswith("mislukt"):
                verslag["redenen"] = [f"De meting is mislukt: {stand[:160]}"]
                db.zet_benadering(webshop_url, stand="adres", notitie=stand[:400])
            else:
                db.zet_benadering(webshop_url, stand="gemeten")
                gelukt, fout = _stuur_onderzoeksmail(
                    webshop_url, winkel["email"], winkel.get("land"))
                benadering.markeer_gemaild(webshop_url, gelukt, fout)
                if gelukt:
                    db.markeer_onderzoeksmail(webshop_url)
                    verslag["gemaild"] = 1
                    verslag["redenen"] = [f"Gemeten en gemaild naar {winkel['email']}."]
                else:
                    verslag["redenen"] = [f"Wel gemeten, mail mislukt: {str(fout)[:160]}"]
                    verslag["mislukt"].append(str(fout)[:160])
    except Exception as e:
        verslag["mislukt"].append(str(e)[:200])
        verslag["redenen"] = [f"Er ging iets mis: {str(e)[:160]}"]
    print(f"Handmatig, {webshop_url}: {'; '.join(verslag['redenen'])}")
    benadering.onthoud_rondeverslag(verslag)


# Hoeveel vragen een meting voor de benadering stelt.
#
# Dit getal MOET boven MINIMUM_VRAGEN_VOOR_POST liggen, en daar zat een fout die
# alle post tegenhield zonder dat er ergens een foutmelding verscheen. De
# benadering mat met de benchmarkstand, en die stelt er vijf. De mail weigert
# onder de tien. Elke winkel werd dus keurig gemeten, kostte geld, en kreeg
# daarna te horen "er zijn maar 5 vragen meegeteld, dat is te weinig". Nul post,
# elke dag opnieuw, met de rekening er wel bij. Een test bewaakt nu dat deze
# twee getallen elkaar niet meer stilletjes kunnen tegenspreken.
#
# Vijftien en niet elf, omdat niet elke gestelde vraag ook meetelt: een model dat
# uitvalt of een antwoord dat niets oplevert telt niet mee. Met vijftien houd je
# marge boven de tien en blijft de meting binnen de schatting van 75 cent.
# Sinds 11 september bewust KLEIN, en dat is een strategische keuze.
#
# Een volledige benadering van vijftien vragen aan twee modellen kost ongeveer
# een euro. Bij vijftien mails per dag is dat vijftien euro; bij de honderd per
# dag die wij willen zou het honderd euro per dag zijn, drieduizend per maand.
# Dat gaat niet.
#
# De vraag is dan ook niet hoeveel vragen wij KUNNEN stellen, maar hoeveel er
# nodig zijn om iemand te laten schrikken. Daar zijn er geen vijftien voor
# nodig. "Wij stelden zes koopvragen aan ChatGPT en bij geen daarvan werd je
# genoemd" is even hard, zolang er eerlijk zes staat en niet iets vaags.
#
# Het geld gaat dus naar achteren in de trechter: de volledige meting met twee
# modellen en de bronanalyse draait pas als iemand zijn uitkomst OPENT. Zie
# _volledige_meting_na_klik. Betalen na het signaal in plaats van ervoor.
BENADERING_VRAGEN = int(os.environ.get("BENADERING_VRAGEN", "6"))

# Hoeveel AI-aanbieders de eerste meting gebruikt. Een is genoeg voor een eerste
# bericht en halveert de kosten. De volledige meting daarna gebruikt ze allebei.
BENADERING_AANBIEDERS = int(os.environ.get("BENADERING_AANBIEDERS", "1"))

# Hoeveel vragen de VOLLEDIGE meting stelt, die pas draait als iemand zijn
# uitkomst opent. Met alle aanbieders, want dan is er iemand die kijkt.
MEET_VRAGEN_NA_KLIK = int(os.environ.get("MEET_VRAGEN_NA_KLIK", "15"))

# Onder hoeveel meegetelde vragen wij geen post sturen.
#
# Drie is de ondergrens waaronder een uitkomst niets zegt.
#
# Dit stond op tien, passend bij een meting van vijftien vragen. Nu de eerste
# meting er zes stelt bij een model, hoort deze grens mee omlaag, anders gaat er
# weer geen post uit. Die twee getallen zitten met een test aan elkaar vast,
# precies omdat ze in september een maand lang stilletjes alle post tegenhielden.
#
# Onder de drie blijft het staan: bij nul of twee meetellende vragen zegt een
# uitkomst niets en is ongevraagde post met zo'n cijfer erin misleidend. De mail
# noemt altijd het echte aantal, dus "bij 0 van de 4 koopvragen genoemd", nooit
# een vaag "wij hebben gemeten".
MINIMUM_VRAGEN_VOOR_POST = int(os.environ.get("MINIMUM_VRAGEN_VOOR_POST", "3"))

# Vanaf hoeveel gemeten winkels wij onszelf een onderzoek mogen noemen in de
# vergelijkingsregel. Onder dit aantal laten wij die regel weg.
MINIMUM_WINKELS_VOOR_VERGELIJKING = 25


# Vanaf hoeveel mails per versie wij een winnaar durven aan te wijzen. Onder
# dit aantal is een verschil van een of twee kliks toeval, en zou je op toeval
# een mail weggooien.
MINIMUM_MAILS_PER_VERSIE = int(os.environ.get("MINIMUM_MAILS_PER_VERSIE", "60"))
MINIMUM_ACTIES_VOOR_WINNAAR = int(os.environ.get("MINIMUM_ACTIES_VOOR_WINNAAR", "15"))


def _varianten_met_oordeel():
    """De telling per mailversie, met een eerlijk oordeel erbij.

    Winnen gaat op doorklikken naar de prijzen en klant worden, niet op
    openen: een open meet een pixel die mailprogramma's zelf al laden."""
    rijen = db.trechter_per_variant()
    for r in rijen:
        g = r.get("gemaild") or 0
        r["klik_pct"] = round(100 * (r.get("bekeken") or 0) / g, 1) if g else 0
        r["door_pct"] = round(100 * (r.get("doorgeklikt") or 0) / g, 1) if g else 0
        r["mens_pct"] = round(100 * (r.get("mensen") or 0) / g, 1) if g else 0
    # 1 oktober: vergelijken op wat mensen doen. Eerst klant, dan naar de
    # prijzen, dan echte mensen. "Link geklikt" telt niet meer mee: dat is
    # vooral mailbeveiliging. En alleen de versies met genoeg mails tellen; een
    # kleine versie (d past maar bij een paar winkels) hield het oordeel eerst
    # voor altijd tegen.
    def _score(r):
        return ((r.get("klant") or 0), r["door_pct"], r["mens_pct"])
    groot = [r for r in rijen if (r.get("gemaild") or 0) >= MINIMUM_MAILS_PER_VERSIE]
    oordeel = None
    if len(rijen) >= 2 and len(groot) < 2:
        oordeel = (f"Nog geen winnaar: pas vanaf {MINIMUM_MAILS_PER_VERSIE} mails per versie "
                   "is een verschil meer dan toeval.")
    elif len(groot) >= 2 and not any(r.get("klant") for r in groot) \
            and sum((r.get("doorgeklikt") or 0) + (r.get("mensen") or 0) for r in groot) \
            < MINIMUM_ACTIES_VOOR_WINNAAR:
        # 2 oktober: "Versie b wint" op 1 doorklik tegen 0. Dat is toeval, geen
        # winnaar. Pas bij genoeg echte acties (mensen plus naar de prijzen)
        # zegt een verschil iets. Een betalende klant beslist wel meteen.
        acties = sum((r.get("doorgeklikt") or 0) + (r.get("mensen") or 0) for r in groot)
        oordeel = (f"Nog geen winnaar: {acties} echte acties (mensen plus naar de prijzen) is te weinig. "
                   f"Pas vanaf {MINIMUM_ACTIES_VOOR_WINNAAR} zegt een verschil iets. Laat alle versies lopen.")
    elif len(groot) >= 2:
        beste = max(groot, key=_score)
        slechtste = min(groot, key=_score)
        if _score(beste) == _score(slechtste):
            oordeel = "Gelijkspel. Laat ze allebei lopen."
        elif beste["variant"] == "d":
            # Versie d past alleen bij een deel van de winkels (stap 225). Alleen
            # "d" zou de rest op versie a zetten; houd de beste van de andere erbij.
            rest = [r for r in groot if r["variant"] != "d"]
            tweede = max(rest, key=_score)["variant"] if rest else "a"
            oordeel = (f"Versie d wint bij de winkels waar hij past. Zet in Render MAIL_VARIANTEN op "
                       f"\"d,{tweede}\": d voor wie vaak genoemd en zelden aangeraden wordt, {tweede} voor de rest.")
        else:
            oordeel = (f"Versie {beste['variant']} wint. Zet in Render MAIL_VARIANTEN op "
                       f"\"{beste['variant']}\" om versie {slechtste['variant']} te laten afvallen.")
    return {"rijen": rijen, "oordeel": oordeel}


KANDIDATEN_FACTOR = 6


def _stuur_onderzoeksmail(webshop_url, email, land=None, proef=False, variant=None):
    """Stuurt één winkel zijn eigen uitkomst. Geeft (gelukt, reden) terug.

    Eén plek voor zowel de knop met de hand als de automatische ronde, zodat er
    nooit twee versies van deze mail ontstaan."""
    if not email or not _EMAIL_VORM.match(email or ""):
        return False, "Geen geldig mailadres."
    # De enige plek waar de onderzoeksmail vandaan komt, dus ook de enige plek
    # waar de afmelding gecontroleerd hoeft te worden. Zowel de knop met de
    # hand als de automatische ronde komt hier langs.
    if db.is_afgemeld(webshop_url):
        return False, "Deze winkel heeft zich afgemeld. Er gaat geen post meer heen."
    token = db.get_benchmark_token(webshop_url)
    if not token:
        return False, "Er kon geen link naar de uitkomst gemaakt worden."
    try:
        # SINDS 23 SEPTEMBER (stap 36): de mail gaat over de POSITIE in de
        # index, uit dezelfde maandmeting als de openbare ranglijst. Hiervoor
        # ging hij over een eigen meting van de winkel. Geen positie, geen
        # mail: dan komt hij vanzelf terug zodra zijn categorie gemeten is.
        beeld = klantbeeld.bouw(webshop_url, land=(land or "").lower() or None, max_vragen=20)
        if not beeld or (beeld.get("telbaar") or 0) < MINIMUM_VRAGEN_VOOR_POST:
            return False, ("GEEN_POSITIE: deze winkel staat (nog) niet in een ranglijst. "
                           "Hij komt vanzelf terug zodra zijn categorie gemeten is.")
        # GEVONDEN 24 SEPTEMBER: de link in de mail moet naar een pagina die
        # bestaat. Zonder land geen landpagina, en een landlijst korter dan
        # MINIMUM_PER_LAND geeft "nog niet gemeten". Dan liever geen mail.
        if not beeld.get("land") or (beeld.get("van") or 0) < MINIMUM_PER_LAND:
            return False, ("GEEN_POSITIE: zijn land is onbekend of zijn landlijst is te kort "
                           "voor een openbare pagina.")
        # Alleen een voorbeeldvraag die past bij wat DEZE winkel verkoopt (24
        # september, keekabuu.com kreeg een vraag over kinderwagens). Past er
        # geen, dan gaat de mail zonder voorbeeldvraag: zijn plek klopt wel.
        beeld["gemiste_vragen"] = vraagkeuze.passende_vragen(
            webshop_url, beeld.get("gemiste_vragen"))
        basis = get_base_url().rstrip("/")
        # Welke versie van de mail (stap 56). Vast per winkel; een proefmail
        # mag er een kiezen, zodat je beide versies kunt bekijken.
        variant = variant or emailing.kies_variant(webshop_url, d_mag=emailing.d_geschikt(beeld))
        if variant == "d" and not emailing.d_geschikt(beeld):
            # Een proef van d over een winkel waarvoor d niet klopt: dan niet.
            return False, "Versie d past niet bij deze winkel (niet vaak genoemd, of wel aangeraden)."
        citaat = None
        if variant == "d":
            try:
                import imago
                citaten = imago.beeld(webshop_url, None,
                                      db.antwoorden_met_tekst_van_ronde(beeld.get("ronde")))["citaten"]
                citaat = citaten[0] if citaten else None
            except Exception as e:
                print(f"Citaat voor versie d mislukt ({webshop_url}): {e}")
        platform = (db.get_winkelprofiel(webshop_url) or {}).get("platform")
        # Stap 217 (30 september): bij kleine Shopify-winkels de leverancierstekst-
        # check in de mail. Drie zoekopdrachten, binnen het dagplafond van de tool;
        # lukt het niet, dan gaat de mail gewoon zonder die zin.
        leverancier = None
        if (platform or "").lower() == "shopify" and not proef:
            try:
                import gratistools
                uit = gratistools.leverancierstekst_check(webshop_url, max_producten=3)
                leverancier = uit if uit.get("teksten") else None
            except Exception as e:
                print(f"Leverancierstekst voor de mail mislukt ({webshop_url}): {e}")
        gelukt = emailing.send_onderzoeksmail(
            email, webshop_url, f"{basis}/uitkomst/{token}", beeld=beeld,
            categorienaam=categorieen.naam_en(beeld["categorie"]),
            landnaam=sitetaal.landnaam(beeld["land"], "en") if beeld.get("land") else None,
            # Een proefmail (naar jezelf) krijgt GEEN echte afmeldlink: klik
            # je die aan, of de afmeldknop die Gmail er zelf boven zet, dan
            # verdwijnt die winkel uit de index (23 september).
            afmeld_url=None if proef else f"{basis}/afmelden/{token}",
            onderwerp_voor=f"[TEST {variant}] " if proef else "",
            variant=variant, platform=platform,
            leverancier=leverancier, citaat=citaat,
            concurrent_is_klant=db.categorie_heeft_klant(beeld.get("categorie"), beeld.get("land"),
                                                         behalve_url=webshop_url))
        # Alleen een echte mail telt mee in de vergelijking van de versies.
        if gelukt and not proef:
            db.zet_mail_variant(webshop_url, variant)
            db.zet_mail_kenmerken(webshop_url, platform,
                                  (leverancier or {}).get("gekopieerd") if leverancier else None)
        return bool(gelukt), None if gelukt else "Verzenden mislukt, kijk in de logs."
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"[:200]


@app.route("/wakker")
def wakker():
    """Een piepklein antwoord om de app wakker te houden.

    Render zet een app die vijftien minuten niets te doen heeft in de slaap.
    De eerstvolgende bezoeker wacht dan een halve minuut op een leeg scherm,
    en dat is precies wat er gebeurde bij het openen van de Shopify-app.

    Roep dit elke tien minuten aan. Bewust zonder sleutel en zonder database:
    dit moet het altijd doen en niets kosten."""
    return "ok", 200


@app.route("/api/cron/onderhoud", methods=["GET", "POST"])
def cron_onderhoud():
    """Het onderhoud: indelen, opschonen en meten, zonder dat iemand kijkt.

    Een keer per nacht aanroepen vanuit Render. Antwoordt meteen, het werk
    gebeurt op de achtergrond, en een ronde die al loopt wordt met rust
    gelaten. Zie onderhoud.py voor wat er precies gebeurt en waarom er
    hoogstens een categorie per ronde gemeten wordt."""
    cron_key = os.environ.get("CRON_KEY")
    if not cron_key or not _sleutel_klopt(request.args.get("key"), cron_key):
        return "", 404
    # De nachtronde roept dit aan zodra een categorie gemeten is. Zo kan
    # onderhoud.py het werk van klanten verversen zonder app.py te importeren
    # (dat zou een kringetje zijn: app importeert onderhoud).
    gestart = _start_nachtwerk()
    return ("ok" if gestart else "loopt al"), 200


def geheugen_mb():
    """Hoeveel geheugen dit proces nu gebruikt (RSS), in MB. None als het niet lukt.

    1 oktober: Render herstartte de dienst 's nachts omdat hij boven de 512 MB
    kwam. Daarom staat het geheugen nu in de log van elke nachtstap, op
    /admin/traag en in het ochtendbericht."""
    try:
        with open("/proc/self/status") as f:
            for regel in f:
                if regel.startswith("VmRSS:"):
                    return round(int(regel.split()[1]) / 1024)
    except Exception:
        return None
    return None


GEHEUGEN_GRENS_MB = int(os.environ.get("GEHEUGEN_GRENS_MB", "400"))


def _nachtwerk_achter_elkaar():
    """Alle nachtstappen NA ELKAAR op een draad (1 oktober).

    WAAROM. Tot 30 september startte de nacht zes draden tegelijk: de
    onderhoudsronde (met de meting), de nachtcontrole (die de hele site
    nabootst), de index-controle, de leeragent, de lijstjesagent en de
    robotwacht. Elk haalt ranglijsten en antwoorden op. Samen gingen ze in de
    nacht van 30 september op 1 oktober over de 512 MB van Render: de dienst
    werd herstart, het werk was weg, en er kwam geen ochtendbericht.
    Nu een voor een, met opruimen ertussen. Het duurt langer, maar de nacht
    heeft tijd genoeg. Zit het geheugen na een stap toch boven de grens, dan
    slaan we de stappen over die kunnen wachten (de leeragent, de lijstjes),
    in plaats van de hele dienst te laten omvallen."""
    import nachtcontrole
    import nachtagenten
    import leeragent
    import lijstjesagent
    import robotwacht
    stappen = [
        ("onderhoud", lambda: onderhoud._werk(), True),
        ("betalingen", _controleer_betalingen, True),
        # 2 oktober: de indexcontrole en de robotwacht VOOR de nachtcontrole.
        # De nachtcontrole bootst de hele site na en duurt het langst; bleef
        # die hangen, dan liep de indexcontrole niet en stonden de bevindingen
        # van een eerdere nacht nog in het ochtendbericht.
        ("indexcontrole", lambda: nachtagenten.draai(_meld_aan_beheer), True),
        ("robotwacht", lambda: robotwacht.ronde(meld=_meld_aan_beheer, basis_url=get_base_url()), True),
        ("nachtcontrole", lambda: nachtcontrole.draai(app, _meld_aan_beheer), True),
        ("leeragent", leeragent.draai, False),
        ("lijstjes", lijstjesagent.zoek, False),
    ]
    verslag = {}
    # 2 oktober: tijdens het nachtwerk niets onthouden (zie db.onthouden_pauze).
    db.onthouden_pauze(True)
    try:
        return _nachtstappen(stappen, verslag)
    finally:
        db.onthouden_pauze(False)


def _nachtstappen(stappen, verslag):
    for naam, stap, moet in stappen:
        voor = geheugen_mb()
        if not moet and voor and voor > GEHEUGEN_GRENS_MB:
            verslag[naam] = f"overgeslagen, geheugen {voor} MB"
            print(f"NACHT {naam}: overgeslagen, geheugen {voor} MB boven {GEHEUGEN_GRENS_MB}")
            continue
        # 2 oktober: na elke stap bewaren waar we zijn. Valt de dienst om, dan
        # zegt het ochtendbericht bij welke stap.
        verslag["bezig"] = naam
        try:
            db.zet_instelling("nachtwerk_verslag", json.dumps(verslag)[:4000])
        except Exception:
            pass
        try:
            stap()
            verslag[naam] = "ok"
        except Exception as e:
            verslag[naam] = f"mislukt: {e}"[:160]
            print(f"NACHT {naam} mislukt: {e}")
        db.vergeet_onthouden()
        _bewaard_opslag.clear()
        db.geef_geheugen_terug()
        print(f"NACHT {naam}: geheugen {voor} -> {geheugen_mb()} MB")
    verslag["geheugen_na"] = geheugen_mb()
    verslag.pop("bezig", None)
    try:
        db.zet_instelling(NACHTWERK_KLAAR_SLEUTEL, str(int(time.time())))
        db.zet_instelling("nachtwerk_verslag", json.dumps(verslag)[:4000])
    except Exception:
        pass
    return verslag


# 4 OKTOBER: drie herstarts in twee dagen (3 okt 04:07 en 09:11, 4 okt 08:02),
# telkens overdag of vroeg in de ochtend, niet in het nachtwerk. Om 08:00
# startten de uurronde van de benadering en de wekelijkse scans tegelijk op een
# dienst die al op 440 MB stond. Zwaar werk start nu alleen als er ruimte is:
# eerst geheugen teruggeven, en staat hij dan nog boven ZWAAR_WERK_MB, dan slaat
# dit werk een ronde over (het komt de volgende ronde vanzelf terug).
ZWAAR_WERK_MB = int(os.environ.get("ZWAAR_WERK_MB", "400"))


def _ruimte_voor_zwaar_werk(naam):
    mb = geheugen_mb()
    if mb and mb > ZWAAR_WERK_MB:
        db.vergeet_onthouden()
        _bewaard_opslag.clear()
        db.geef_geheugen_terug()
        na = geheugen_mb()
        print(f"Geheugen voor {naam}: {mb} MB, na teruggeven {na} MB.")
        if na and na > ZWAAR_WERK_MB:
            print(f"{naam} overgeslagen: geheugen {na} MB boven {ZWAAR_WERK_MB}.")
            return False
    return True


def _nachtregel():
    """Een zin over de nacht. Sinds 2 oktober in ochtendbericht.nachtregel, zodat
    hij ook bovenaan /admin/ochtendbericht staat."""
    import ochtendbericht
    return ochtendbericht.nachtregel(geheugen=geheugen_mb())["tekst"]


def _start_nachtwerk():
    """Alles van de nacht. Apart, zodat de wachtklok het ook kan starten."""
    onderhoud.NA_METING = _ververs_klantwerk
    try:
        db.zet_instelling(NACHTWERK_SLEUTEL, str(int(time.time())))
    except Exception:
        pass
    # De onderhoudsronde markeren als bezig, zodat een tweede start niets doet.
    with onderhoud._slot:
        if onderhoud._stand["bezig"]:
            return False
        onderhoud._stand.update({"bezig": True, "stap": "starten", "gestart_op": time.time(),
                                 "klaar_op": None, "fout": None})
    threading.Thread(target=_nachtwerk_achter_elkaar, daemon=True).start()
    return True


# ---------------------------------------------------------------------------
# DE WACHTKLOK (30 september). Na de verhuizing naar de nieuwe dienst in
# Frankfurt kwam er twee uur lang geen enkele uurronde: de taak in Render die
# elk uur /api/cron/benadering aanroept, riep die niet meer (goed) aan. Van
# buitenaf zag je alleen dat er geen mail meer uitging. Nu kijkt de site zelf
# elke vijf minuten:
# - is er langer dan WACHTKLOK_MINUTEN geen uurronde geweest, dan start hij er
#   zelf een, en meldt hij het een keer per dag aan Nino;
# - is het nachtwerk langer dan 26 uur niet gestart, dan doet hij dat tussen
#   2 en 5 uur 's nachts.
# De taak in Render blijft de gewone weg; dit is het vangnet. Twee diensten
# tegelijk (oud en nieuw) kunnen niet allebei starten: wie de ronde "claimt"
# doet dat in een keer in de database (db.claim_moment).
# ---------------------------------------------------------------------------
WACHTKLOK_MINUTEN = int(os.environ.get("WACHTKLOK_MINUTEN", "75"))
NACHTWERK_SLEUTEL = "nachtwerk_gestart"
NACHTWERK_KLAAR_SLEUTEL = "nachtwerk_klaar"
_wachtklok = {"gestart": False}


def _wachtklok_tik(nu=None):
    """Een keer kijken. Geeft terug wat er gestart is (voor de test)."""
    gedaan = []
    klok = benadering.KLOK
    nu = nu or (datetime.now(klok) if klok else datetime.now())
    laatst = benadering.laatste_ronde()
    if laatst is not None and laatst.tzinfo is None and nu.tzinfo is not None:
        laatst = laatst.replace(tzinfo=nu.tzinfo)
    te_lang = laatst is None or (nu - laatst).total_seconds() > WACHTKLOK_MINUTEN * 60
    if te_lang and db.claim_moment("wachtklok_benadering", 50 * 60):
        print("WACHTKLOK: geen uurronde gezien, de site start er zelf een.")
        if _ruimte_voor_zwaar_werk("benaderingsronde (wachtklok)"):
            threading.Thread(target=_benadering_ronde, daemon=True).start()
            gedaan.append("benadering")
        if db.claim_moment("wachtklok_melding", 20 * 3600):
            _meld_aan_beheer("De uurtaak in Render riep de site niet aan",
                             "Er was langer dan een uur geen ronde van de benadering. De site heeft er zelf een "
                             "gestart, dus de post loopt door. Kijk in Render bij de Cron Job welk adres hij "
                             "aanroept: dat moet https://krilloai.com/api/cron/benadering?key=... zijn.")
    try:
        nacht = float(db.get_instelling(NACHTWERK_SLEUTEL) or 0)
    except (TypeError, ValueError):
        nacht = 0
    try:
        klaar = float(db.get_instelling(NACHTWERK_KLAAR_SLEUTEL) or 0)
    except (TypeError, ValueError):
        klaar = 0
    # 1 oktober: gestart maar nooit klaar (de dienst werd herstart, het werk was
    # weg) telt als niet gedaan, zolang het nog nacht is.
    afgebroken = nacht and klaar < nacht and time.time() - nacht > 2 * 3600 and not onderhoud._stand.get("bezig")
    if (2 <= nu.hour < 7 and afgebroken and db.claim_moment("wachtklok_nacht_opnieuw", 6 * 3600)) or \
            (2 <= nu.hour < 5 and time.time() - nacht > 26 * 3600 and db.claim_moment("wachtklok_nacht", 20 * 3600)):
        print("WACHTKLOK: geen nachtwerk gezien, de site start het zelf.")
        _start_nachtwerk()
        gedaan.append("nacht")
    # 1 oktober: een categorie van een betalende klant die nog nooit gemeten is,
    # meteen meten (niet 's nachts, dan loopt het nachtwerk).
    if not (2 <= nu.hour < 7):
        try:
            gestart = _meet_klantcategorie()
            if gestart:
                gedaan.append(f"klantmeting {gestart}")
        except Exception as e:
            print(f"Klantmeetrij mislukt: {e}")
    # 8 oktober (controle "maakt Krillo het waar?"): alle weekbeloftes (vijf
    # vragen, dertien controles, de weekmail) hingen aan een cron in Render.
    # Ontbreekt die, dan gebeurde er niets. Nu ook vanuit de wachtklok, tussen
    # tien en twaalf, als de cron het vandaag nog niet deed (zelfde claim).
    if 10 <= nu.hour < 12 and not onderhoud._stand.get("bezig") \
            and _ruimte_voor_zwaar_werk("wekelijkse scans") and db.claim_moment(WEEKSCANS_KLOK, 20 * 3600):
        threading.Thread(target=_draai_wekelijkse_scans, args=(get_base_url(), False), daemon=True).start()
        gedaan.append("wekelijkse scans")
    # 1 oktober: de klantblik loopt elke ochtend alle pagina's na zoals een klant
    # ze ziet, na de nacht en voor het ochtendbericht van acht uur.
    import commandocentrum
    if 6 <= nu.hour < 8 and not onderhoud._stand.get("bezig") and commandocentrum.aan("klantblik") \
            and db.claim_moment("klantblik_klok", 20 * 3600):
        def _klantblik():
            try:
                import klantblik
                klantblik.draai(app)
            except Exception as e:
                print(f"Klantblik mislukt: {e}")
            # 1 oktober: daarna de proefaankoop (een nepklant koopt Watch, door de
            # echte code). Na de klantblik, op dezelfde draad: nooit tegelijk.
            try:
                import proefaankoop
                proefaankoop.ronde(app, get_base_url().rstrip("/"))
            except Exception as e:
                print(f"Proefaankoop mislukt: {e}")
        threading.Thread(target=_klantblik, daemon=True).start()
        gedaan.append("klantblik")
    # LET OP: de claimsleutels hier ("..._klok") mogen nooit dezelfde naam hebben
    # als een instelling waar een agent zijn verslag in zet (gevonden 1 oktober:
    # "groeiagent" en "klantblik" waren allebei; de claim las dan JSON als getal
    # en lukte nooit meer).
    # 1 oktober: de groeiagent kijkt elke vier uur overdag waar de klantenstroom
    # vastloopt en zet voorstellen klaar (de eerste voor het ochtendbericht).
    if 6 <= nu.hour < 21 and commandocentrum.aan("groei") and db.claim_moment("groeiagent_klok", 4 * 3600 - 300):
        def _groei():
            try:
                import groeiagent
                v = groeiagent.ronde()
                if v.get("nieuw"):
                    print(f"Groeiagent: nieuw {v['nieuw']}")
            except Exception as e:
                print(f"Groeiagent mislukt: {e}")
        threading.Thread(target=_groei, daemon=True).start()
        gedaan.append("groeiagent")
    # 1 oktober: een keer per maand het klantnieuws (alleen de grootste
    # verbeteringen, klantnieuws.py). De claim per maand zit in de ronde zelf.
    if 9 <= nu.hour < 17 and db.claim_moment("klantnieuws_kijk", 6 * 3600):
        def _nieuws():
            try:
                import klantnieuws
                v = klantnieuws.ronde(get_base_url())
                if v.get("verstuurd"):
                    print(f"Klantnieuws verstuurd: {v}")
            except Exception as e:
                print(f"Klantnieuws mislukt: {e}")
        threading.Thread(target=_nieuws, daemon=True).start()
        gedaan.append("klantnieuws")
    # 8 oktober: de gratis maand voor doorverwijzers. Eens per dag overdag; de
    # code zelf is idempotent (een keer per doorverwezen klant), zie doorverwijzen.py.
    if 9 <= nu.hour < 18 and db.claim_moment("gratis_maand_klok", 20 * 3600):
        def _gratis_maand():
            try:
                import doorverwijzen
                v = doorverwijzen.geef_gratis_maanden(meld=_meld_aan_beheer)
                if v["gegeven"] or v["mislukt"]:
                    print(f"Gratis maanden: {v}")
            except Exception as e:
                print(f"Gratis maand mislukt: {e}")
        threading.Thread(target=_gratis_maand, daemon=True).start()
        gedaan.append("gratis maand")
    # Stap 88 (30 september): het opleveroverzicht vanzelf, overdag, hooguit
    # een keer per uur (zie opleveragent.py).
    if 9 <= nu.hour < 19 and db.claim_moment("oplevering_auto", 55 * 60):
        def _oplever():
            try:
                import opleveragent
                v = opleveragent.ronde(get_base_url())
                if v["verstuurd"] or v["mislukt"]:
                    print(f"Oplevering vanzelf: {v}")
            except Exception as e:
                print(f"Oplevering vanzelf mislukt: {e}")
        threading.Thread(target=_oplever, daemon=True).start()
        gedaan.append("oplevering")
    return gedaan


def _start_wachtklok():
    if _wachtklok["gestart"] or app.testing:
        return
    _wachtklok["gestart"] = True

    def lus():
        while True:
            time.sleep(300)
            try:
                _wachtklok_tik()
            except Exception as e:
                print(f"Wachtklok mislukt: {e}")
    threading.Thread(target=lus, daemon=True).start()


def _start_nachtagenten():
    """De nachtagenten naast de nachtronde, elk op de achtergrond.
    Stap 97, 100, 143: de index nakijken, de concurrenten (maandag), de kosten.
    Stap 96 en 153: de leeragent, hoogstens een onderzoek per nacht."""
    import nachtagenten
    import leeragent
    threading.Thread(target=nachtagenten.draai, args=(_meld_aan_beheer,), daemon=True).start()
    threading.Thread(target=leeragent.draai, daemon=True).start()
    # De lijstjesagent zoekt een keer per week nieuwe artikelen "beste GEO-tools".
    import lijstjesagent
    threading.Thread(target=lijstjesagent.zoek, daemon=True).start()
    # Stap 181: een keer per week kijken of AI-robots de winkels van klanten nog mogen lezen.
    import robotwacht
    threading.Thread(target=robotwacht.ronde, kwargs={"meld": _meld_aan_beheer,
                                                       "basis_url": get_base_url()}, daemon=True).start()


@app.route("/api/cron/benadering", methods=["GET", "POST"])
def cron_benadering():
    """Elk uur aanroepen vanuit Render. Doet per keer een klein stukje.

    Antwoordt meteen, het werk gebeurt op de achtergrond."""
    cron_key = os.environ.get("CRON_KEY")
    if not cron_key or not _sleutel_klopt(request.args.get("key"), cron_key):
        return "", 404
    if not _ruimte_voor_zwaar_werk("benaderingsronde"):
        return "later", 200
    threading.Thread(target=_benadering_ronde, daemon=True).start()
    return "ok", 200


@app.route("/afmelden/<token>", methods=["GET", "POST"])
def afmelden(token):
    """De afmeldlink uit de mail. Eén klik, geen vragen, geen formulier.

    Elke mail die je stuurt aan iemand die er niet om vroeg moet dit hebben, en
    hij moet echt werken. Een afmeldlink die om een bevestiging vraagt is de
    reden dat mensen op 'spam' drukken in plaats van op de link.

    Ook op POST, want de knop 'Afmelden' die Gmail zelf bovenaan de mail zet
    stuurt een POST en geen GET. Zonder dat doet die knop niets."""
    webshop_url = db.winkel_bij_benchmark_token(token)
    if not webshop_url:
        if request.method == "POST":
            return "", 404
        return render_template("afgemeld.html", gelukt=False), 404

    # 7 OKTOBER (gevonden in de trechter per dag: 11 tot 19 afmeldingen op 60
    # mails, elke dag). Beveiligingsscanners van bedrijven (Microsoft, Mimecast,
    # Proofpoint) openen ELKE link in een mail voordat de mens hem leest, ook
    # de afmeldlink. Met afmelden op GET meldde de scanner de winkel dus af, en
    # haalde hem ook nog uit de openbare index. Nu: een gewone klik (GET) toont
    # een knop, de knop (POST) meldt af. De afmeldknop van Gmail zelf stuurt een
    # POST en werkt dus nog steeds met een klik.
    if request.method == "GET":
        return render_template("afgemeld.html", vraag=True, token=token,
                               winkel=webshop_url)

    # Kijken of het echt bewaard is. Een bevestigingsscherm tonen terwijl er
    # niets is opgeslagen is erger dan een foutmelding: hij denkt dat het
    # geregeld is en krijgt toch weer post.
    bewaard = db.meld_benadering_af(webshop_url)
    if not bewaard:
        print(f"LET OP: afmelding NIET bewaard voor {webshop_url}")
        if request.method == "POST":
            return "", 500
        return render_template("afgemeld.html", gelukt=False), 500

    # Wie zich afmeldt hoort ook niet meer in de rij te staan voor een
    # uitgestelde meting. Anders betalen wij morgen nog 2,50 euro aan een winkel
    # die net gezegd heeft dat hij niets meer van ons wil.
    benadering.haal_van_wachtlijst(webshop_url)

    if request.form.get("bevestig"):
        return render_template("afgemeld.html", gelukt=True, winkel=webshop_url)
    return "", 200


def _benader_regels(alles=False, aantal=200):
    regels = db.get_benaderingen(alleen_niet_afgemeld=False)
    if alles:
        return regels
    nul = datetime.min.replace(tzinfo=timezone.utc)

    def recent(r):
        tijden = [t for t in (r.get("antwoord_op"), r.get("bekeken_op"), r.get("gemaild_op"), r.get("opvolg_op")) if t]
        tijden = [t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in tijden]
        return max(tijden) if tijden else nul
    return sorted(regels, key=recent, reverse=True)[:aantal]


def _benader_totaal():
    try:
        return sum((db.tel_benaderingen().get("per_stand") or {}).values())
    except Exception:
        return None


@app.route("/admin/benadering", methods=["GET", "POST"])
def admin_benadering():
    """De machinekamer van de benadering: de lijst erin, de rem instellen, en
    zien wat er gebeurd is."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    melding = None
    if request.method == "POST":
        actie = (request.form.get("actie") or "").strip()
        if actie == "lijst":
            uit = benadering.voeg_lijst_toe(request.form.get("lijst") or "")
            melding = (f"{uit['nieuw']} nieuwe winkels toegevoegd, "
                       f"{uit['al_bekend']} stonden er al op.")
            if uit["fout"]:
                melding += f" {len(uit['fout'])} regel(s) overgeslagen: {uit['fout'][:3]}"
        elif actie == "instellingen":
            db.zet_instelling("benadering_aan",
                              "ja" if request.form.get("aan") == "ja" else "nee")
            for veld in ("mail_per_dag", "mail_per_ronde", "adressen_per_ronde",
                         "metingen_per_ronde"):
                waarde = (request.form.get(veld) or "").strip()
                if waarde.isdigit():
                    db.zet_instelling(veld, int(waarde))
            melding = "Instellingen bewaard."
        elif actie == "ronde":
            threading.Thread(target=_benadering_ronde, daemon=True).start()
            melding = ("Een ronde is gestart. Ververs deze pagina over een minuut "
                       "of twee, dan zie je het resultaat.")
        elif actie == "nu":
            url = scan_engine.normalize_url((request.form.get("url") or "").strip())
            if not url or "." not in url:
                melding = "Vul een webadres in, bijvoorbeeld voorbeeldwinkel.nl."
            else:
                threading.Thread(target=_nu_meten_en_mailen, args=(url,),
                                 daemon=True).start()
                melding = (f"{url} wordt nu gemeten en daarna gemaild. Dit duurt een "
                           f"paar minuten. Ververs deze pagina, de uitkomst komt in "
                           f"het logboek hierboven te staan.")
        elif actie == "scanners_terug":
            # 9 oktober (Nino: "ja, graag terugzetten"): alleen in de index,
            # nooit terug op de maillijst.
            n = db.zet_terug_in_index(db.scanner_afmeldingen())
            melding = f"{n} winkel(s) staan weer in de index. Ze krijgen geen post meer van ons."
        elif actie in ("is_test", "is_echt"):
            url = (request.form.get("url") or "").strip()
            db.zet_klant_test(url, actie == "is_test")
            melding = f"{url} telt nu {'NIET ' if actie == 'is_test' else ''}als klant."
        elif actie == "stand":
            url = (request.form.get("url") or "").strip()
            nieuwe = (request.form.get("stand") or "").strip()
            if db.zet_benadering(url, stand=nieuwe):
                melding = f"{url} staat nu op {nieuwe}."
            else:
                melding = "Dat lukte niet."

    inst = benadering.instellingen()
    mag, reden = benadering.hoeveel_mag_er_nu()
    # Hoeveel metingen er op dit moment echt lopen. Zonder dit getal lijkt een
    # ronde die gewoon aan het werk is precies op een ronde die vastligt.
    bezig = _metingen_bezig()
    return render_template(
        "admin_benadering.html", scanner_afgemeld=len(db.scanner_afmeldingen()),
        geen_adres=db.redenen_geen_adres(),
        zoekmachine=benadering.zoekmachine_stand(),
        diagnose=benadering.waarom_gaat_er_niets_uit(
            moment_laatste_ronde=benadering.laatste_ronde(),
            meetruimte=kosten.ruimte_voor_benadering(),
            metingen_bezig=bezig),
        trechter=db.trechter_benadering(),
        per_dag=db.trechter_per_dag(7),
        varianten=_varianten_met_oordeel(),
        verslagen=benadering.rondeverslagen(),
        meetfouten=benadering.meetfouten(),
        wachtrij=len(_demo_wachtrij),
        nu_bezig=[u for u, st in _demo_status.items()
                  if st and st != "klaar" and not st.startswith("mislukt")][:5],
        nu_bezig_stand=dict(list(_demo_status.items())[-5:]),
        dagpot=kosten.ruimte_voor_benadering(),
        # 29 september: de pagina deed er 32 seconden over. Alle 2000+ regels
        # met een formulier per regel; nu de 200 met de meest recente
        # activiteit, en ?alles=1 voor de hele lijst.
        regels=_benader_regels(request.args.get("alles") == "1"),
        regels_totaal=_benader_totaal(),
        tellingen=db.tel_benaderingen(),
        klanten_lijst=db.klanten_op_lijst(),
        instellingen=inst,
        mag_nu=mag,
        reden=reden,
        standen=db.BENADER_STANDEN,
        melding=melding,
        sleutel=admin_key,
    )


@app.route("/monitoring/<klant_token>")
def monitoring_doorsturen(klant_token):
    """Het oude werkscherm. Staat sinds 21 september in het dashboard.

    Blijft bestaan als doorverwijzing, want deze link staat in elke mail die
    tot die dag verstuurd is. Een 301: de oude plek komt niet terug."""
    return redirect(f"/mijn/{klant_token}/fixes", code=301)


@app.route("/monitoring/<klant_token>/details")
def monitoring_pagina(klant_token):
    """De klantpagina. Twee weergaven op dezelfde gegevens.

    Standaard krijgt een klant alleen zijn takenlijst. De cijfers, citaten,
    concurrenten en de dertien controlepunten staan op /details.

    Dat is bewust zo gesplitst. Alles op een pagina zetten leverde tien blokken
    op waar een winkeleigenaar niet doorheen kwam, en dan is het niet meer
    duidelijk wat hij moet doen. De cijfers zijn de onderbouwing, niet het
    product."""
    klant = db.get_klant(klant_token)
    if klant is None:
        return render_template("fout.html", titel="This page does not exist or is no longer valid"), 404

    rapporten = db.get_klant_rapporten(klant_token)
    laatste = rapporten[0] if rapporten else None
    vorige = rapporten[1] if len(rapporten) > 1 else None

    # Loopt er echt een abonnement? Een klant die alleen de uitvoering van 149
    # euro kocht krijgt dezelfde pagina, en die las tot nu toe "je betaalt 39
    # euro per maand" met een opzegknop eronder. Dat is een onjuiste mededeling
    # over een betalingsverplichting, en het is precies het soort fout waar
    # iemand zijn geld voor terugvraagt.
    abonnement = _abonnement_stand(klant["webshop_url"], rapporten)[0]

    verschil = None
    nieuwe_problemen = []
    checks_by_categorie = {}

    if laatste:
        if vorige:
            verschil = laatste["score"] - vorige["score"]
            vorige_problemen = {
                c["titel"] for c in vorige["checks"] if c["status"] != "ok"
            }
            nieuwe_problemen = [
                c for c in laatste["checks"]
                if c["status"] != "ok" and c["titel"] not in vorige_problemen
            ]
        # 8 oktober (Nino zag "TOEGANG" en "Gebruikt de site een beveiligde
        # verbinding?" op een verder Engelse pagina): de dertien punten in de
        # taal van de klant. scan_engine blijft Nederlands; hier vertalen.
        engels = _mailtaal(klant["webshop_url"]) != "nl"
        checks_hier = laatste["checks"]
        if engels:
            import checktaal
            checks_hier = checktaal.naar_het_engels({"checks": laatste["checks"]})["checks"]
        groepnaam = ({"toegang": "Access", "leesbaarheid": "Readability", "structuur": "Structure",
                      "inhoud": "Content", "vertrouwen": "Trust", "overig": "Other"} if engels else {})
        if engels and nieuwe_problemen:
            nieuwe_problemen = checktaal.naar_het_engels({"checks": nieuwe_problemen})["checks"]
        for c in checks_hier:
            cat = c.get("categorie", "overig")
            checks_by_categorie.setdefault(groepnaam.get(cat, cat), []).append(c)

    verloop = list(reversed(rapporten))[-8:]

    # Fase 5 stap 7: de vermeldingen bij AI, als die er zijn. Staat er nog
    # niets, dan tonen we hier ook niets. Een lege sectie met nullen erin leest
    # als een slechte uitkomst, terwijl er alleen nog niet gemeten is.
    gegevens = _klantgegevens(klant["webshop_url"])

    pagina = _paginagegevens(klant["webshop_url"])
    return render_template(
        "monitoring_details.html",
        t=pagina["t"],
        paginataal=pagina["taal"],
        shopify_beheer=pagina["shopify_beheer"],
        vermeldingen=gegevens["vermeldingen"],
        controle=gegevens["controle"],
        beweging=gegevens["beweging"],
        bronnen=gegevens["bronnen"],
        actieplan=gegevens["actieplan"],
        verklaring=verklaring.maak_verklaring(
            laatste["checks"] if laatste else [], gegevens["vermeldingen"],
            taal=_mailtaal(klant["webshop_url"])),
        webshop_url=klant["webshop_url"],
        klant_token=klant_token,
        laatste=laatste,
        verschil=verschil,
        verloop=verloop,
        nieuwe_problemen=nieuwe_problemen,
        checks_by_categorie=checks_by_categorie,
        uitvoering=_laatste_uitvoering(klant["webshop_url"]),
        wijzigingen=db.get_wijzigingen(klant["webshop_url"]),
        abonnement=abonnement,
        opgezegd=_is_opgezegd(klant["webshop_url"]),
        status_labels=_standlabels(pagina["t"]),
    )


@app.route("/rapport/<token>")
def rapport(token):
    report = db.get_report(token)
    if report is None:
        return render_template("fout.html", titel="Report not found"), 404

    checks = report["checks"]
    by_categorie = {}
    for c in checks:
        by_categorie.setdefault(c.get("categorie", "overig"), []).append(c)

    history = db.get_history(report["webshop_url"]) if report["type"] == "monitoring" else []

    return render_template(
        "rapport.html",
        type=report["type"],
        webshop_url=report["webshop_url"],
        score=report["score"],
        fixes=report.get("fixes"),
        checks_by_categorie=by_categorie,
        history=history,
        aangemaakt_op=report["aangemaakt_op"].strftime("%d-%m-%Y"),
        status_labels=_standlabels(
            paginataal.teksten(_mailtaal(report["webshop_url"]))),
    )


def _standlabels(t):
    """De labels bij de dertien controlepunten, in de taal van de pagina.

    Stonden hard in drie render-aanroepen, alle drie in het Nederlands. Een
    Engelse winkel zag daardoor "verbeterpunt" tussen verder Engelse tekst."""
    return {"ok": t["stand_ok"], "deels": t["stand_deels"],
            "probleem": t["stand_probleem"]}


def _paginagegevens(webshop_url):
    """De taal van de klantpagina, en het adres van de app als dit een
    Shopify-winkel is.

    Twee dingen die bij elkaar horen omdat ze op dezelfde pagina thuishoren en
    door twee routes gebruikt worden: de echte klantpagina en de
    voorbeeldweergave. Zouden die het elk zelf uitrekenen, dan is de
    voorbeeldweergave niet meer waar hij voor bedoeld is: laten zien wat een
    klant precies ziet."""
    taal = _mailtaal(webshop_url)
    beheer = None
    try:
        rij = db.shopify_winkel_bij_webadres(webshop_url)
        # Alleen als de app er nog in zit EN deze klant niet via de site bij
        # Mollie betaalt (27 september). Anders zag een Mollie-klant die ooit de
        # app probeerde "je abonnement loopt via Shopify" in plaats van de
        # opzegknop, en kon hij nergens opzeggen.
        klant = db.klant_bij_url(webshop_url) or {}
        if (rij and rij.get("winkel") and rij.get("toegangssleutel")
                and rij.get("actief", True) and not klant.get("mollie_klant_id")):
            beheer = _app_adres_in_beheerscherm(rij["winkel"])
    except Exception as e:
        print(f"Shopify-winkel zoeken mislukt voor {webshop_url}: {e}")
    return {"taal": taal, "t": paginataal.teksten(taal), "shopify_beheer": beheer}


def _markt_van(webshop_url):
    """In welke taal en voor welk land we deze winkel meten.

    Weten we het niet, dan komt er Nederlands uit, want dat is wat Krillo altijd
    al deed en wat voor alle bestaande klanten klopt."""
    try:
        profiel = db.get_winkelprofiel(webshop_url) or {}
        return markt.bepaal(profiel.get("taal"), profiel.get("land"))
    except Exception as e:
        print(f"Markt ophalen mislukt voor {webshop_url}: {e}")
        return markt.bepaal(None, None)


def _genereer_koopvragen_achtergrond(webshop_url, vervang=False):
    """Draait op de achtergrond, want scannen plus vragen bedenken duurt een
    minuut of meer. De pagina hoeft daar niet op te wachten."""
    try:
        scan_result = run_scan(webshop_url)
        extra = scan_result.get("gevonden_paginas") if "error" not in scan_result else None
        m = _markt_van(webshop_url)
        print(f"Koopvragen voor {webshop_url} in {markt.omschrijving(m)}.")
        resultaat = koopvragen.genereer_koopvragen(
            webshop_url, extra, taal=m["taal"], landnaam=m["land"])
        if resultaat is None:
            print(f"Koopvragen genereren mislukt voor {webshop_url}")
            return
        nieuw = db.bewaar_koopvragen(webshop_url, resultaat["omschrijving"],
                                     resultaat["vragen"], vervang=vervang,
                                     winkelnaam=resultaat.get("naam"))
        print(f"Koopvragen klaar voor {webshop_url}: {len(resultaat['vragen'])} vragen, {nieuw} nieuw opgeslagen.")
        _vul_koopvragen_aan(webshop_url)
    except Exception as e:
        print(f"Koopvragen genereren mislukt voor {webshop_url}: {e}")


def _vul_koopvragen_aan(webshop_url):
    """Vult de vragenset weer aan tot het doel per intentie.

    Nodig na ontdubbelen en na een generatie die te weinig vragen opleverde.
    Zonder dit krimpt de set bij elke klik en hou je uiteindelijk twee
    winkelvragen over."""
    try:
        actief = [dict(v) for v in db.get_koopvragen(webshop_url, alleen_actief=True)]
        tekort = koopvragen.tel_tekort(actief)
        if not tekort:
            return
        profiel = db.get_winkelprofiel(webshop_url)
        omschrijving = profiel.get("omschrijving") if profiel else ""
        alles = db.get_koopvragen(webshop_url, alleen_actief=False)
        m = _markt_van(webshop_url)
        extra = koopvragen.vul_vragen_aan(
            webshop_url, omschrijving, tekort, [v["vraag"] for v in alles],
            taal=m["taal"], landnaam=m["land"]
        )
        if extra:
            db.bewaar_koopvragen(webshop_url, omschrijving, extra, vervang=False)
        print(f"Aangevuld voor {webshop_url}: tekort {tekort}, {len(extra)} vragen erbij.")
    except Exception as e:
        print(f"Aanvullen mislukt voor {webshop_url}: {e}")


@app.route("/admin/koopvragen")
def admin_koopvragen():
    """Nog niet zichtbaar voor klanten. Hiermee kan je per webshop de
    koopvragen laten genereren, beoordelen en ontdubbelen."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    if not webshop_url:
        return render_template("admin_koopvragen.html", webshop_url="geen webshop opgegeven",
                                status="leeg", vragen=[], groepen={}, dubbelen=0, sleutel=admin_key)

    bestaand = db.get_koopvragen(webshop_url)
    opnieuw = request.args.get("opnieuw") == "ja"

    if not bestaand or opnieuw:
        threading.Thread(target=_genereer_koopvragen_achtergrond,
                         args=(webshop_url, opnieuw), daemon=True).start()
        return render_template("admin_koopvragen.html", webshop_url=webshop_url,
                                status="bezig", vragen=[], groepen={}, dubbelen=0, sleutel=admin_key)

    vragen = [{"vraag": v["vraag"], "intentie": v["intentie"]} for v in bestaand]

    # Alleen aanvullen, zonder eerst dubbelingen te zoeken.
    if request.args.get("aanvul") == "ja":
        threading.Thread(target=_vul_koopvragen_aan, args=(webshop_url,), daemon=True).start()
        return redirect(f"/admin/koopvragen?url={webshop_url}&aangevuld=ja")

    # Zoeken naar dubbelingen kost een AI-aanroep, dus dat doen we alleen als
    # erom gevraagd wordt. Deed hij dat bij elke keer verversen, dan betaal je
    # voor elke pagina die je opent.
    zoeken = request.args.get("dubbel") == "ja" or request.args.get("ontdubbel") == "ja"
    dubbelingen = koopvragen.vind_dubbele_vragen(vragen, webshop_url=webshop_url) if zoeken else []
    if request.args.get("ontdubbel") == "ja" and dubbelingen:
        for d in dubbelingen:
            db.zet_vraag_uit(webshop_url, d["weglaten"])
        threading.Thread(target=_vul_koopvragen_aan, args=(webshop_url,), daemon=True).start()
        return redirect(f"/admin/koopvragen?url={webshop_url}&aangevuld=ja")

    weg_te_laten = {d["weglaten"]: d["houden"] for d in dubbelingen}
    groepen = {}
    for v in vragen:
        v = dict(v)
        lijkt_op = weg_te_laten.get(v["vraag"])
        v["dubbel"] = (lijkt_op[:40] + "...") if lijkt_op else None
        groepen.setdefault(v["intentie"] or "overig", []).append(v)

    profiel = db.get_winkelprofiel(webshop_url)
    return render_template(
        "admin_koopvragen.html",
        webshop_url=webshop_url,
        status="klaar",
        omschrijving=profiel.get("omschrijving") if profiel else "",
        # Wat de machine uit alle eerdere metingen geleerd heeft, met de cijfers
        # erbij. Die cijfers staan hier niet voor de sier: zodra iets zijn eigen
        # gedrag aanpast op basis van geschiedenis, hoor je te kunnen zien waarop
        # dat gebaseerd is. Anders is het een zwarte doos die duurder wordt zonder
        # dat iemand kan nagaan waarom.
        geleerd=koopvragen.wat_wij_geleerd_hebben(),
        zwak_onder=koopvragen.ZWAK_ONDER,
        vragen=vragen,
        groepen=groepen,
        dubbelen=len(dubbelingen),
        te_veel=len(vragen) > metingen.VRAGEN_PER_RONDE,
        per_ronde=metingen.VRAGEN_PER_RONDE,
        aanvullen_bezig=request.args.get("aangevuld") == "ja",
        gezocht=zoeken,
        tekort=koopvragen.tel_tekort([dict(v) for v in bestaand]),
        sleutel=admin_key,
    )


_metingen_bezig = set()
_metingen_slot = threading.Lock()


def _meet_achtergrond(webshop_url):
    """Een meetronde duurt al gauw een paar minuten, dus die laten we niet op
    het verzoek wachten.

    De set eromheen voorkomt dat er twee rondes tegelijk lopen voor dezelfde
    webshop. Zonder die controle start elke keer verversen een nieuwe ronde en
    betaal je twee of drie keer voor dezelfde meting."""
    try:
        metingen.meet_webshop(webshop_url)
    except Exception as e:
        print(f"Meting mislukt voor {webshop_url}: {e}")
    finally:
        with _metingen_slot:
            _metingen_bezig.discard(webshop_url)


def _start_meting(webshop_url):
    """Geeft terug of er een nieuwe ronde gestart is."""
    with _metingen_slot:
        if webshop_url in _metingen_bezig:
            return False
        _metingen_bezig.add(webshop_url)
    threading.Thread(target=_meet_achtergrond, args=(webshop_url,), daemon=True).start()
    return True


@app.route("/admin/metingen")
def admin_metingen():
    """Fase 5 stap 3. Laat zien wat de AI-modellen antwoordden op de
    koopvragen van een webshop. Nog niet zichtbaar voor klanten: het
    beoordelen van die antwoorden is stap 4."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    aanbieders = metingen.beschikbare_aanbieders()

    if not webshop_url:
        return render_template(
            "admin_metingen.html", webshop_url="", sleutel=admin_key,
            aanbieders=aanbieders, metingen_aan=metingen.METINGEN_AAN,
            webshops=db.get_webshops_met_koopvragen(),
            rondes=[], antwoorden=[], meting_id=None, gestart=False,
        )

    if request.args.get("start") == "ja":
        # Meteen doorsturen naar de pagina zonder start=ja. Anders start elke
        # keer verversen een nieuwe meetronde.
        _start_meting(webshop_url)
        return redirect(f"/admin/metingen?url={webshop_url}&gestart=ja")

    net_gestart = request.args.get("gestart") == "ja"
    meting_id = request.args.get("meting") or None
    antwoorden = [dict(a) for a in db.get_ai_antwoorden(webshop_url, meting_id)]
    for a in antwoorden:
        a["naam_gevonden"] = metingen.ruwe_naamtreffer(a.get("antwoord"), webshop_url)

    return render_template(
        "admin_metingen.html",
        webshop_url=webshop_url,
        sleutel=admin_key,
        aanbieders=aanbieders,
        metingen_aan=metingen.METINGEN_AAN,
        webshops=db.get_webshops_met_koopvragen(),
        rondes=db.get_metingen(webshop_url),
        antwoorden=antwoorden,
        meting_id=meting_id,
        gestart=net_gestart,
    )


_beoordelen_bezig = set()


def _beoordeel_achtergrond(webshop_url, meting_id, winkelnaam):
    try:
        beoordeling.beoordeel_ronde(webshop_url, meting_id, winkelnaam)
    except Exception as e:
        print(f"Beoordelen mislukt voor {webshop_url}: {e}")
    finally:
        with _metingen_slot:
            _beoordelen_bezig.discard(webshop_url)


def _meet_en_beoordeel(webshop_url, email=None, klant_token=None, base_url=None,
                       stap=None, max_vragen=None, controleer=True, bronnen_aan=True,
                       max_aanbieders=None):
    """De hele keten van fase 5 achter elkaar: meten, beoordelen, controleren en
    zo nodig waarschuwen.

    Draait wekelijks na de gewone scan. De volgorde ligt vast omdat elke stap op
    de vorige leunt: zonder antwoorden valt er niets te beoordelen, en zonder
    beoordeling zijn er geen uitspraken om te controleren.

    Elke stap in een eigen try, want een storing bij een AI-aanbieder mag nooit
    de rest tegenhouden.

    Met stap= kan een aanroeper meelezen waar de keten is. Die keten duurt
    minuten, dus zonder terugmelding lijkt een demopagina stil te staan."""
    def melden(tekst):
        if stap:
            try:
                stap(tekst)
            except Exception:
                pass

    # Zonder koopvragen valt er niets te meten. Bij een nieuwe abonnee bestaan
    # die nog niet, dus die maken we hier alsnog aan. Anders zou een klant die
    # net 39 euro betaald heeft een lege pagina zien terwijl op de site staat
    # dat we elke week dertig vragen stellen.
    if not db.get_koopvragen(webshop_url, alleen_actief=True):
        print(f"Nog geen koopvragen voor {webshop_url}, die maken we eerst.")
        melden("koopvragen maken")
        _genereer_koopvragen_achtergrond(webshop_url, vervang=False)

    winkelnaam = _winkelnaam(webshop_url)

    melden("vragen stellen aan AI")
    samenvatting = metingen.meet_webshop(webshop_url, max_vragen=max_vragen,
                                         max_aanbieders=max_aanbieders) or {}
    meting_id = samenvatting.get("meting_id")
    if not meting_id:
        # BEWUST GEEN TERUGVAL op db.laatste_meting_id(). Die stond hier, en
        # dan ging de hele keten bij een mislukte meting vrolijk verder op de
        # ronde van vorige week: opnieuw beoordelen (kost geld), bronnen
        # zoeken bij oude antwoorden, en een klantpagina met cijfers van zeven
        # dagen oud onder de datum van vandaag. Liever niets dan oud nieuws
        # dat zich voordoet als vers.
        reden = samenvatting.get("reden") or "onbekende reden"
        melden(f"mislukt: er is niets gemeten ({reden})")
        print(f"Meting overgeslagen voor {webshop_url}: {reden}")
        # Gaat dit mis bij een BETALENDE klant, dan moet jij dat weten. Hij las
        # net in zijn welkomstmail "reken op ongeveer een kwartier", kijkt een
        # kwartier later, en ziet "er is nog niet gemeten". Voor 39 euro per
        # maand. Zonder dit bericht kwam dat alleen in de logs van Render.
        #
        # Alleen bij een klant, niet bij een demo of de benadering: die hebben
        # hun eigen logboek en zouden dit tot tientallen berichten per dag maken.
        if klant_token:
            _meld_aan_beheer(
                "Meting mislukt bij een klant",
                f"De meting voor {webshop_url} ({email}) leverde niets op: {reden}. "
                f"Deze klant ziet op zijn pagina 'er is nog niet gemeten'. Kijk of de "
                f"sleutels van de AI-aanbieders werken en of de kostenrem niet dicht "
                f"staat.")
        return

    # Is de ronde halverwege gestopt, dan is dat geen normale ronde. De klant
    # mag geen "genoemd bij 1 van de 3 vragen" te zien krijgen alsof dat een
    # volledige week is.
    #
    # Hier stond alleen een print. Dat betekende dat precies het scherm waar
    # deze regels voor waarschuwen gewoon getoond werd: de dagpot is gedeeld
    # met alle klanten, dus op een drukke dag kon een winkel na drie van de
    # dertig vragen stoppen en las zijn pagina "genoemd bij 1 van de 3". Dat is
    # geen klein cijfer, dat is een verkeerd cijfer, en het staat op de pagina
    # waar hij voor betaalt.
    #
    # De grens van 75 procent is dezelfde die waarschuwing.py gebruikt om twee
    # rondes vergelijkbaar te noemen. Onder die grens beoordelen wij niets en
    # tonen wij niets: liever geen cijfer dan een verkeerd cijfer.
    if samenvatting.get("gestopt_door_rem"):
        gedaan = samenvatting.get("gelukt") or 0
        bedoeld = samenvatting.get("gesteld") or gedaan
        deel = (gedaan / bedoeld) if bedoeld else 0
        print(f"LET OP: de meetronde voor {webshop_url} is halverwege gestopt na "
              f"{gedaan} van {bedoeld} vragen: {samenvatting.get('reden')}")
        if deel < 0.75:
            melden("mislukt: er is niets gemeten "
                   f"(de ronde stopte na {gedaan} van {bedoeld} vragen)")
            return

    try:
        melden("antwoorden beoordelen")
        beoordeling.beoordeel_ronde(webshop_url, meting_id, winkelnaam)
    except Exception as e:
        print(f"Beoordelen mislukt voor {webshop_url}: {e}")

    # Bij een benchmark slaan we de uitspraakcontrole over. Die kost een extra
    # AI-aanroep per winkel en levert een oordeel op over die ene winkel, terwijl
    # een benchmark alleen naar het patroon over alle winkels kijkt. Over zestig
    # winkels scheelt dat zo een tientje voor iets wat je toch niet gebruikt.
    controle_samenvatting = None
    if controleer:
        melden("uitspraken controleren")
        controle_samenvatting = _controleer_uitspraken(webshop_url, meting_id, winkelnaam)

    # Fase 5 punt 14. Staat bewust ná het beoordelen, want die bepaalt bij
    # welke vragen we ontbreken en welke concurrenten er wel opdoken. Zonder
    # dat weet de bronanalyse niet waar hij moet kijken.
    #
    # Ook bewust in een eigen try en overslaanbaar: valt de zoekmachine uit of
    # is er geen sleutel, dan mist er die week een blok op de klantpagina en
    # draait de rest gewoon door. Dat is beter dan een meetronde die klapt op
    # een dienst die niets met de meting zelf te maken heeft.
    if bronnen_aan:
        melden("externe bronnen zoeken")
        _zoek_bronnen(webshop_url, meting_id, winkelnaam, melden)

    # Fase 5 punt 15. Het plan samenstellen en de kant-en-klare oplossingen
    # laten schrijven, zodat ze klaarstaan als de klant zijn pagina opent.
    # Hier en niet daar: een pagina die staat te wachten op een AI is
    # onbruikbaar, en verversen zou elke keer opnieuw geld kosten.
    try:
        melden("actieplan klaarzetten")
        _maak_taakoplossingen(webshop_url, _klantgegevens(webshop_url)["actieplan"], melden)
    except Exception as e:
        print(f"Taakoplossingen klaarzetten mislukt voor {webshop_url}: {e}")

    # Alleen mailen als er iets te melden valt. Een wekelijks bericht dat er
    # niets veranderd is, leert een klant om je mail weg te klikken.
    try:
        beweging = waarschuwing.vergelijk(
            [dict(b) for b in db.get_beoordelingen_rondes(webshop_url, rondes=2)], winkelnaam,
            taal="en")
        tekst = waarschuwing.bericht(webshop_url, beweging, controle_samenvatting, taal="en")
        if tekst and email:
            monitoring_url = f"{base_url}/mijn/{klant_token}" if (base_url and klant_token) else None
            emailing.send_vermeldingen_update(email, webshop_url, tekst, monitoring_url,
                                              taal=_mailtaal(webshop_url))
    except Exception as e:
        print(f"Waarschuwing versturen mislukt voor {webshop_url}: {e}")


# Wat de laatste bronanalyse per winkel deed. Alleen in het geheugen, dus na
# een herstart van Render is dit leeg. Dat is prima: het is bedoeld om te zien
# waarom een poging niets opleverde, niet om te bewaren. De echte uitkomsten
# staan in de database.
_bronnen_status = {}


def _zet_bronnen_status(webshop_url, tekst, klaar=False):
    _bronnen_status[webshop_url] = {"tekst": tekst, "klaar": klaar}
    print(f"Bronnen {webshop_url}: {tekst}")


# Voor elke taak laten we een tekst schrijven, ook voor de onjuistheden.
#
# Dat was eerst niet zo, en dat was fout. Juist bij "AI zegt dat je 30 dagen
# retour geeft terwijl het er 100 zijn" wil een winkelier niet horen dat hij
# het moet rechtzetten, maar de zin lezen die hij op zijn site kan plakken.
# Die taak heeft de kant-en-klare tekst het hardst nodig, niet het minst.
GEEN_OPLOSSING_NODIG = set()


def _ververs_klantwerk(ronde, categorie, base_url=None):
    """Na de maandmeting van een categorie: het werk van elke klant erin
    vernieuwen. STAP 72, 23 september.

    Wat hier gebeurt, in deze volgorde:
    1. De antwoorden van de ronde worden per klant omgezet in beoordelingen
       (klantwerk.py). Dat kost geen modelaanroep: de antwoorden zijn al
       gelezen. Hieruit volgen zijn cijfers, de vragen die hij mist en de
       winkels die boven hem staan.
    2. Uit die verse beoordelingen rolt zijn actieplan, en daarvoor worden de
       kant-en-klare oplossingen geschreven. DAT kost wel geld, dus het gaat
       langs de kostenrem en alleen voor taken die er nog niet zijn.
    3. Heeft hij Fix (of het pakket voor merken), dan komt er een regel op de
       werklijst, zodat jij ziet dat er deze maand werk klaarstaat en het
       overzicht met de oude tekst later verstuurd kan worden.

    Waarom dit bestaat: tot vandaag werden de oplossingen alleen bij de START
    van een abonnement gemaakt. Een klant van drie maanden zag dus nog precies
    de drie dingen van zijn eerste dag, terwijl Fix belooft dat wij elke maand
    de drie dingen doen die het meeste opleveren.

    Draait op de draad van de nachtronde en mag nooit de ronde laten klappen:
    alles zit in een try."""
    verslag = {"categorie": categorie, "klanten": 0, "regels": 0,
               "plannen": 0, "werklijst": 0}
    try:
        klanten = db.klanten_in_categorie(categorie)
        # Stap 76: alleen de klanten voor wie deze ronde telt (een Belgische
        # ronde: Belgische klanten; de gewone: niet de klanten van een land met
        # een eigen ronde). Anders schrijven wij oplossingen op de verkeerde
        # vragen, en dat kost geld.
        ronde_land = db.ronde_land(ronde)
        eigen_landen = db.landen_met_eigen_ronde(categorie)
        klanten = [k for k in klanten if vraaglanden.hoort_bij_ronde(
            k.get("land") or (db.winkel_kort(k["webshop_url"]) or {}).get("land"),
            ronde_land, eigen_landen)]
    except Exception as e:
        print(f"Klanten van {categorie} ophalen mislukt: {e}")
        return verslag
    if not klanten:
        return verslag

    try:
        uit = klantwerk.beoordelingen_uit_ronde(ronde, categorie, klanten)
        verslag["klanten"] = uit.get("klanten", 0)
        verslag["regels"] = uit.get("regels", 0)
    except Exception as e:
        print(f"Beoordelingen uit ronde {ronde} mislukt: {e}")
        return verslag

    for klant in klanten:
        url = klant["webshop_url"]
        # De kostenrem per klant nakijken en niet een keer vooraf: bij tien
        # klanten in een categorie kan de pot halverwege leeg zijn, en dan
        # stoppen we liever dan dat we hem overschrijden.
        try:
            ruimte = kosten.mag_doorgaan(webshop_url=url)
            if not ruimte["mag"]:
                verslag["gestopt_door"] = ruimte["reden"]
                break
        except Exception as e:
            print(f"Kostenrem nakijken mislukt voor {url}: {e}")

        try:
            plan = _klantgegevens(url)["actieplan"]
            _maak_taakoplossingen(url, plan)
            verslag["plannen"] += 1
        except Exception as e:
            print(f"Oplossingen vernieuwen mislukt voor {url}: {e}")

        # Fix doet het werk zelf, dus er hoort een opdracht op de werklijst.
        # Het kenmerk is de ronde plus de winkel: een keer per maandmeting,
        # en een tweede poging levert geen dubbele opdracht op.
        try:
            if _doet_werk_voor(url):
                kenmerk = f"maand-{ronde}-{url}"[:120]
                platform = (db.get_winkelprofiel(url) or {}).get("platform")
                if db.start_uitvoering(kenmerk, url, klant.get("email"), platform):
                    verslag["werklijst"] += 1
                    # Een Shopify-winkel vult Krillo zelf (wekelijkse ronde).
                    # Elke andere winkel doe jij nu nog met de hand, en dat
                    # moet je weten ZONDER zelf de werklijst open te hoeven
                    # doen (27 september, controle voor de eerste klant).
                    if not db.shopify_winkel_bij_webadres(url):
                        _meld_aan_beheer(
                            "Fix-werk klaar voor een klant",
                            f"Na de maandmeting van {categorie} staat er nieuw werk klaar voor "
                            f"{url} ({klant.get('email')}, platform {platform or 'onbekend'}). "
                            f"Ga naar {get_base_url()}/admin/uitvoeringen.")
        except Exception as e:
            print(f"Werklijst bijwerken mislukt voor {url}: {e}")

    print(f"Klantwerk vernieuwd voor {categorie}: {verslag}")
    return verslag


def _doet_werk_voor(webshop_url):
    """Of wij in deze winkel zelf werken: Fix, het pakket voor merken, of de
    oude eenmalige uitvoering. Bij Watch niet, die doet het zelf.

    Waarom het zo omslachtig moet: welk pakket iemand heeft staat bij Mollie
    en bij Shopify, niet bij ons. Wij vragen het daar op. Lukt dat niet, dan
    zeggen wij NEE: een opdracht op de werklijst zetten voor iemand die Watch
    nam, betekent dat jij werk doet waar niet voor betaald is."""
    try:
        abonnement = payments.zoek_abonnement(webshop_url)
        if abonnement:
            pakket = (abonnement.get("pakket") or "").lower()
            if pakket:
                return pakket != "watch"
            # Geen pakket bekend bij een lopend abonnement: dan kijken we naar
            # het bedrag. Watch is het goedkoopste pakket.
            bedrag = str(abonnement.get("bedrag") or "")
            watch = (payments.PAKKETTEN["watch"]["prijs"]["value"],
                     payments.PAKKETTEN["watch"].get("jaarprijs", {}).get("value"))
            return bedrag not in watch
    except Exception as e:
        print(f"Abonnement opvragen mislukt voor {webshop_url}: {e}")
    try:
        rij = db.shopify_winkel_bij_url(webshop_url)
        if rij and rij.get("toegangssleutel"):
            stand = shopify_billing.huidig_abonnement(rij["winkel"], _shopify_sleutel(rij))
            return bool(stand.get("actief")) and stand.get("plan") == "fix"
    except Exception as e:
        print(f"Shopify-abonnement opvragen mislukt voor {webshop_url}: {e}")
    return False


def _laatste_uitvoering(webshop_url):
    """De meest recente opdracht "wij doen het" van deze winkel, of None.

    Bewust de nieuwste en niet de eerste: bestelt iemand het een jaar later nog
    eens, dan hoort de klantpagina die tweede opdracht te tonen en niet de
    afgeronde van vorig jaar. Afgebroken opdrachten laten we weg, want daar
    hoeft een klant niets meer van te zien."""
    try:
        for u in db.get_uitvoeringen(webshop_url):
            if u.get("stand") != "afgebroken":
                return u
    except Exception as e:
        print(f"Uitvoering ophalen mislukt voor {webshop_url}: {e}")
    return None


def _maak_taakoplossingen(webshop_url, plan, melden=None):
    """Laat voor elke taak in het plan de kant-en-klare oplossing schrijven,
    en bewaart die.

    Gebeurt hier, in de wekelijkse keten, en niet bij het openen van de
    klantpagina. Twee redenen: een pagina die een halve minuut staat te denken
    is onbruikbaar, en een klant die vijf keer ververst zou vijf keer betalen.

    Al geschreven oplossingen worden overgeslagen. Een taak die blijft staan
    krijgt dus dezelfde tekst als vorige week, en dat hoort ook: hetzelfde
    probleem met een andere formulering laat het lijken alsof er iets veranderd
    is."""
    uitkomsten = []
    if not plan or not plan.get("acties"):
        return uitkomsten

    # Op welk winkelplatform deze shop draait, zodat de tekst bij "waar zet je
    # dit neer" de menunamen van dat platform gebruikt. Weten we het niet, dan
    # blijft het None en vraagt de prompt om twee routes. Nooit gokken: een
    # route in Shopify voorschrijven aan iemand met WooCommerce laat het hele
    # product onbetrouwbaar lijken.
    platform = None
    try:
        profiel = db.get_winkelprofiel(webshop_url) or {}
        platform = profiel.get("platform")
    except Exception as e:
        print(f"Platform ophalen mislukt voor {webshop_url}: {e}")

    bestaand = db.get_taakoplossingen(webshop_url)
    for actie in plan["acties"]:
        taak_id = actie.get("id")
        if not taak_id or taak_id in GEEN_OPLOSSING_NODIG:
            continue
        if taak_id in bestaand:
            uitkomsten.append({"titel": actie["titel"], "gelukt": True, "fout": None,
                               "was_er_al": True})
            continue
        if melden:
            try:
                melden(f"oplossing schrijven: {actie['titel'][:40]}")
            except Exception:
                pass
        # In de taal van de winkel. De tekst die hieruit komt plakt de eigenaar
        # letterlijk op zijn eigen website, dus een Nederlandse zin op een
        # Amerikaanse winkel is niet onhandig maar onbruikbaar.
        m = _markt_van(webshop_url)
        uitkomst = ai_content.genereer_taakoplossing(
            webshop_url, taak_id, actie["titel"], actie["hoe"],
            platform=platform,
            taal="nl" if m["is_nederlands"] else "en") or {}
        if uitkomst.get("gelukt"):
            db.bewaar_taakoplossing(webshop_url, taak_id, uitkomst["titel"],
                                    uitkomst["oplossing"], uitkomst["waar"],
                                    taal="nl" if m["is_nederlands"] else "en")
            uitkomsten.append({"titel": actie["titel"], "gelukt": True, "fout": None,
                               "was_er_al": False})
        else:
            uitkomsten.append({"titel": actie["titel"], "gelukt": False,
                               "fout": uitkomst.get("fout") or "onbekende reden",
                               "was_er_al": False})
    return uitkomsten


def _zoek_bronnen(webshop_url, meting_id=None, winkelnaam=None, melden=None):
    """Fase 5 punt 14. Zoekt de externe pagina's op waar de concurrenten wel
    staan en de klant niet.

    Leunt op het klantbeeld van deze ronde, dus op precies dezelfde cijfers als
    de klant op zijn pagina ziet. Zou dit zijn eigen selectie maken, dan kan de
    bronanalyse over andere vragen gaan dan de meting erboven, en dan staan er
    twee waarheden op een pagina."""
    try:
        if not bronnen.beschikbaar():
            _zet_bronnen_status(webshop_url, bronnen.waarom_niet(), klaar=True)
            return None

        # BEWUST de nieuwste BEOORDEELDE ronde en niet de nieuwste gemeten
        # ronde. Anders kan de bronanalyse over een andere ronde gaan dan de
        # cijfers die de klant erboven ziet, en dan staan er twee waarheden op
        # een pagina. De klantpagina kiest via get_beoordelingen() dezelfde.
        meting_id = meting_id or db.laatste_beoordeelde_meting_id(webshop_url)
        if not meting_id:
            gemeten = db.laatste_meting_id(webshop_url)
            if gemeten:
                _zet_bronnen_status(
                    webshop_url,
                    f"Er is wel gemeten (ronde {gemeten[:8]}) maar nog niets beoordeeld. "
                    f"Zonder beoordeling weten we niet bij welke vragen je ontbreekt en "
                    f"welke concurrenten er opdoken. Beoordeel die ronde eerst.",
                    klaar=True)
            else:
                _zet_bronnen_status(
                    webshop_url,
                    "Er is nog geen enkele meetronde voor deze winkel. Meet eerst.",
                    klaar=True)
            return None

        beoordelingen = [dict(b) for b in db.get_beoordelingen(webshop_url, meting_id)]
        if not beoordelingen:
            _zet_bronnen_status(
                webshop_url,
                f"Ronde {meting_id[:8]} heeft geen beoordelingen. Beoordeel die ronde eerst.",
                klaar=True)
            return None

        klantbeeld = beoordeling.klantbeeld(webshop_url, beoordelingen)
        vragen = bronnen.kies_vragen(klantbeeld)
        concurrenten = bronnen.kies_concurrenten(klantbeeld)
        if not vragen:
            _zet_bronnen_status(
                webshop_url,
                "Geen vragen om na te trekken: deze winkel wordt bij elke meetellende vraag "
                "genoemd en aanbevolen. Dan valt er hier niets te halen.", klaar=True)
            return None
        if not concurrenten:
            _zet_bronnen_status(
                webshop_url,
                "Geen concurrenten gevonden in de beoordelingen van deze ronde. "
                "De bronanalyse zoekt naar winkels die AI wel noemt, en die zijn er niet.",
                klaar=True)
            return None

        _zet_bronnen_status(webshop_url,
                            f"Bezig: {len(vragen)} vragen natrekken bij {len(concurrenten)} concurrenten.")

        # In het land van de winkel zoeken. Een winkel in Texas moet in
        # Amerikaanse zoekresultaten gezocht worden; zoeken we daar met de
        # Nederlandse instelling, dan vinden we pagina's waar hij nooit op zou
        # staan en klopt de hele bronanalyse niet.
        m = _markt_van(webshop_url)
        vindplaatsen = bronnen.analyseer(
            webshop_url, klantbeeld, winkelnaam=winkelnaam,
            meting_id=meting_id, melden=melden,
            land=m["zoek_land"], taal=m["zoek_taal"],
        )
        if vindplaatsen:
            # Eerst weg wat er van deze ronde stond, dan pas bewaren. Anders
            # stapelen de resultaten van elke poging op elkaar en blijf je
            # kijken naar vindplaatsen die met oudere, soepelere regels
            # binnengekomen zijn. Dan zie je nooit of een verbetering geholpen
            # heeft.
            weg = db.verwijder_bronvindplaatsen(webshop_url, meting_id)
            bewaard = db.bewaar_bronvindplaatsen(webshop_url, meting_id, vindplaatsen)
            _zet_bronnen_status(
                webshop_url,
                f"Klaar: {bewaard} vindplaatsen over {len(vragen)} vragen"
                + (f", {weg} oude regels vervangen." if weg else "."), klaar=True)
        else:
            _zet_bronnen_status(
                webshop_url,
                f"Klaar, maar niets gevonden. {len(vragen)} vragen gezocht en geen enkele "
                f"pagina bevatte onze winkel of een van de concurrenten. Test hieronder de "
                f"zoekmachine: geeft die ook niets terug, dan zit het probleem daar.",
                klaar=True)
        return bronnen.vat_samen(vindplaatsen, winkelnaam)
    except Exception as e:
        _zet_bronnen_status(webshop_url, f"Mislukt: {type(e).__name__}: {e}"[:400], klaar=True)
        return None


def _controleer_uitspraken(webshop_url, meting_id=None, winkelnaam=None):
    """Fase 5 stap 9. Legt de uitspraken van AI naast wat er op de site staat.

    Haalt de sitetekst vers op, want die staat bewust niet in de database: het
    zijn duizenden tekens die bij elke scan veranderen."""
    try:
        meting_id = meting_id or db.laatste_meting_id(webshop_url)
        if not meting_id:
            return None
        beoordelingen = [dict(b) for b in db.get_beoordelingen(webshop_url, meting_id)]
        uitspraken = controle.verzamel_uitspraken(beoordelingen)
        if not uitspraken:
            return None
        sitetekst = scan_engine.haal_sitetekst(webshop_url, controle.MAX_SITETEKST)
        if not sitetekst:
            print(f"Controle overgeslagen voor {webshop_url}: site niet te lezen.")
            return None
        uitkomsten = controle.controleer(webshop_url, winkelnaam, uitspraken, sitetekst)
        db.bewaar_uitspraakcontroles(webshop_url, meting_id, uitkomsten)
        return controle.vat_samen(uitkomsten)
    except Exception as e:
        print(f"Uitspraken controleren mislukt voor {webshop_url}: {e}")
        return None


def _winkelnaam(webshop_url):
    """De naam zoals de winkel zichzelf noemt.

    Eerst het veld waar het model de naam apart in zet. Staat dat er niet
    (oudere winkels), dan de oude manier: de omschrijving splitsen op " is ".
    Beide gaan langs dezelfde controle."""
    profiel = db.get_winkelprofiel(webshop_url) or {}
    uit_veld = scan_engine.bruikbare_winkelnaam(profiel.get("winkelnaam"))
    if uit_veld:
        return uit_veld
    omschrijving = profiel.get("omschrijving") or ""
    if " is " in omschrijving:
        return scan_engine.bruikbare_winkelnaam(omschrijving.split(" is ")[0])
    return None


def _klantgegevens(webshop_url):
    """Alles wat zowel de klantpagina als de voorbeeldweergave nodig heeft.

    Op een plek, zodat een abonnee en de voorbeeldweergave nooit iets anders
    kunnen laten zien."""
    # De klant ziet de nieuwste ronde. Voor stijgen of dalen zijn er twee
    # nodig, en die haalt get_beoordelingen niet op.
    beoordelingen = [dict(b) for b in db.get_beoordelingen(webshop_url)]
    twee_rondes = [dict(b) for b in db.get_beoordelingen_rondes(webshop_url, rondes=2)]
    vermeldingen = beoordeling.klantbeeld(webshop_url, beoordelingen) if beoordelingen else None
    winkelnaam = _winkelnaam(webshop_url)
    # Alles op deze pagina komt uit DEZELFDE ronde. Zonder dat zou je de
    # bronnen en de controles van vorige week naast de cijfers van deze week
    # kunnen zetten, en dan klopt het verhaal niet meer. Liever niets tonen dan
    # iets dat bij een andere meting hoort.
    #
    # Voor de uitspraakcontrole stond hier eerder geen ronde. Die pakte dan de
    # nieuwste ronde waarvoor toevallig controles bestonden. Mislukte de
    # controle deze week, dan zag de klant de cijfers van deze week met daaronder
    # de fouten van vorige week, en die kwamen als FEIT bovenaan zijn takenlijst,
    # citaat en al, terwijl AI dat deze week misschien niet meer zegt.
    ronde = db.laatste_beoordeelde_meting_id(webshop_url)
    controles = ([dict(c) for c in db.get_uitspraakcontroles(webshop_url, ronde)]
                 if ronde else [])
    vindplaatsen = ([dict(v) for v in db.get_bronvindplaatsen(webshop_url, ronde)]
                    if ronde else [])
    controle_samenvatting = controle.vat_samen(controles) if controles else None
    bronnen_samenvatting = bronnen.vat_samen(vindplaatsen, winkelnaam) if vindplaatsen else None

    # Fase 5 punt 15. Leunt op alles hierboven en op de verklaring uit de
    # scan, dus die halen we er hier bij. Bewust op deze ene plek berekend,
    # zodat de klantpagina en de voorbeeldweergave nooit een ander plan kunnen
    # tonen dan elkaar.
    checks = (db.get_rapporten_voor_webshop(webshop_url) or [{}])[0].get("checks") or []
    #
    # De taal van het advies volgt de markt van de winkel. Een Amerikaanse
    # winkel kreeg tot nu toe een Engels scherm met Nederlands advies eronder.
    # Weten we de markt niet, dan geeft _markt_van Nederlands terug, dus voor
    # bestaande klanten verandert er niets.
    m = _markt_van(webshop_url)
    # SINDS 23 SEPTEMBER: het plan zelf (titels, waarom) is Engels, want het
    # dashboard is Engels (een adres, een taal). Een Nederlandse winkel las
    # anders Nederlandse titels op een Engels scherm. De OPLOSSING die de
    # eigenaar op zijn site plakt blijft in de taal van zijn winkel: die
    # hieronder ophalen in winkeltaal, niet in plantaal.
    plantaal = "en"
    winkeltaal = "nl" if m["is_nederlands"] else "en"
    plan = actieplan.maak_actieplan(
        verklaring=verklaring.maak_verklaring(checks, vermeldingen, taal=plantaal),
        klantbeeld=vermeldingen,
        bronnen=bronnen_samenvatting,
        controle=controle_samenvatting,
        winkelnaam=winkelnaam,
        taal=plantaal,
    )

    # De bewaarde oplossingen aan de taken hangen. Alleen lezen, nooit
    # schrijven: dat gebeurt in de wekelijkse keten.
    if plan and plan.get("acties"):
        # Alleen oplossingen in de taal die deze winkel ook op het scherm ziet.
        # Staat er een Nederlandse tekst van vorige week onder een Engels kopje,
        # dan lijkt het alsof er iets kapot is. Liever niets, want de volgende
        # ronde maakt hem alsnog, dan wel in de goede taal.
        opgeslagen = db.get_taakoplossingen(webshop_url, taal=winkeltaal)
        for actie in plan["acties"]:
            bewaard = opgeslagen.get(actie.get("id"))
            if bewaard:
                actie["oplossing"] = bewaard.get("oplossing")
                actie["waar"] = bewaard.get("waar")

    return {
        "vermeldingen": vermeldingen,
        "controle": controle_samenvatting,
        "beweging": waarschuwing.vergelijk(twee_rondes, winkelnaam),
        "bronnen": bronnen_samenvatting,
        "actieplan": plan,
    }


_demo_status = {}
_demo_wachtrij = []
_demo_slot = threading.Lock()
_demo_werker_draait = [False]


# Na hoeveel mislukte metingen wij een winkel laten vallen. Een site die drie
# keer niet te bereiken is, is er gewoon niet, en elke volgende poging kost een
# plek in de rij en een stukje dagpot.
MISLUKT_GENOEG = int(os.environ.get("MISLUKT_GENOEG", "3"))

# Vanaf hoeveel wachtende metingen een ronde er geen nieuwe meer bij zet.
WACHTRIJ_VOL = int(os.environ.get("WACHTRIJ_VOL", "5"))

# Hoe lang een winkel op "meten" mag staan zonder dat er iets loopt, voordat wij
# hem opnieuw oppakken. Kort, want als de wachtrij leeg is en er loopt niets, is
# er niets om op te wachten.
HERVAT_NA_MINUTEN = int(os.environ.get("HERVAT_NA_MINUTEN", "20"))


def _metingen_bezig():
    """Hoeveel metingen er op dit moment echt lopen."""
    return len([1 for stand in _demo_status.values()
                if stand and stand != "klaar" and not stand.startswith("mislukt")])


def _hervat_onderbroken_metingen():
    """Pakt winkels op die op "meten" staan terwijl er niets meer loopt.

    Geeft terug hoeveel er opnieuw ingepland zijn."""
    if _demo_wachtrij or _metingen_bezig():
        return 0
    grens = datetime.now(benadering.KLOK) - timedelta(minutes=HERVAT_NA_MINUTEN)
    hervatten = []
    for winkel in db.get_benaderingen(stand="meten", limiet=WACHTRIJ_VOL):
        begonnen = winkel.get("meting_gestart_op")
        if begonnen is not None and begonnen.tzinfo is None and benadering.KLOK:
            begonnen = begonnen.replace(tzinfo=benadering.KLOK)
        if begonnen is not None and begonnen > grens:
            continue
        hervatten.append(winkel["webshop_url"])
    if not hervatten:
        return 0
    benadering.markeer_in_meting(hervatten)
    _demo_inplannen(hervatten, benchmark_stand=True, vragen=BENADERING_VRAGEN,
                    aanbieders=BENADERING_AANBIEDERS, opnieuw=False)
    print(f"Benadering, onderbroken metingen opnieuw opgepakt: {len(hervatten)}")
    return len(hervatten)


def _demo_werker():
    """Werkt de wachtrij een voor een af.

    Met opzet een enkele werker en geen thread per winkel. Twintig winkels
    tegelijk meten betekent twintig keer zoveel aanroepen per minuut, en dan
    krijg je van OpenAI en Google precies de 429's terug waar we eerder al last
    van hadden. Rustig achter elkaar duurt langer maar levert bruikbare
    metingen op, en dat is het enige wat telt."""
    while True:
        with _demo_slot:
            if not _demo_wachtrij:
                _demo_werker_draait[0] = False
                return
            regel = _demo_wachtrij.pop(0)
            url, benchmark_stand = regel[0], regel[1]
            vragen = regel[2] if len(regel) > 2 else None
            aanbieders = regel[3] if len(regel) > 3 else None
        _demo_draaien(url, benchmark_stand, vragen=vragen, aanbieders=aanbieders)
        _meting_afgerond_melden(url)


def _meting_afgerond_melden(webshop_url):
    """Schrijft de uitkomst van een meting terug naar de benaderlijst.

    Dit ontbrak, en daardoor was "er wordt wel gemeten maar er komt niets af"
    van buitenaf niet te verklaren. De reden van een mislukking stond alleen in
    het geheugen van de server en in de uitdraai van Render. Elke ronde meldde
    keurig "ingepland: 5, doorgezet naar gemeten: 0" en daar hield het op.

    Een mislukte meting gaat meteen terug naar "adres" met de reden erbij, in
    plaats van zes uur op "meten" te blijven staan. Er is niets om op te wachten:
    hij is al mislukt."""
    stand = _demo_status.get(webshop_url) or ""
    try:
        # Zoeken over de HELE lijst, niet alleen bij wat op "meten" staat.
        #
        # Dat was een gat waar geld doorheen liep. Werd een winkel tijdens zijn
        # meting door de opruimronde teruggezet op "adres", dan stond hij bij
        # het afronden niet meer op "meten", vond deze functie hem niet, en gaf
        # hij op. De mislukking werd dus nooit geteld en de winkel kwam de
        # volgende ronde gewoon weer aan de beurt. Zo kon dezelfde onbereikbare
        # site acht keer op een dag geprobeerd worden.
        kaal = scan_engine.normalize_url(webshop_url)
        rij = None
        for r in db.get_benaderingen(alleen_niet_afgemeld=False):
            if scan_engine.normalize_url(r["webshop_url"]) == kaal:
                rij = r
                break
        if rij is None:
            return  # geen winkel van de benadering, dus niets te melden
        if (rij.get("stand") or "") == "afgevallen":
            # Al opgegeven. Niets meer doen, en zeker niet terugzetten op
            # "adres", want dan begint het hele rondje opnieuw.
            return
        if stand.startswith("mislukt"):
            # Hoe vaak deze winkel al mislukt is. Zonder dit blijft een winkel
            # die gewoon niet bestaat elk uur opnieuw aan de beurt komen: in het
            # logboek van 11 september stond woefwinkel.be acht keer op een dag,
            # steeds met "we konden deze website niet bereiken". Elke poging
            # bezet een plek in de rij van winkels die het wel doen.
            #
            # Dit telde eerst uit het foutenlogboek, en dat bewaart maar tien
            # regels. Bij vijftien metingen per dag is de vorige poging daar
            # allang uit gerold, begint het tellen weer bij nul, en valt een
            # winkel dus nooit af. Daarom nu een eigen teller die blijft staan.
            pogingen = benadering.tel_meetpoging(rij["webshop_url"])
            if pogingen >= MISLUKT_GENOEG:
                db.zet_benadering(
                    rij["webshop_url"], stand="afgevallen",
                    notitie=f"Na {pogingen} pogingen niet te meten: {stand[:300]}")
                print(f"Benadering, {webshop_url} afgevallen na {pogingen} pogingen.")
            else:
                db.zet_benadering(rij["webshop_url"], stand="adres", notitie=stand[:400])
            benadering.onthoud_meetfout(rij["webshop_url"], stand)
            print(f"Benadering, meting mislukt voor {webshop_url}: {stand[:160]}")
        elif stand == "klaar":
            db.zet_benadering(rij["webshop_url"], stand="gemeten", notitie="")
    except Exception as e:
        print(f"Uitkomst van de meting bewaren mislukt voor {webshop_url}: {e}")


def _demo_inplannen(urls, benchmark_stand=False, opnieuw=False, vragen=None,
                    aanbieders=None):
    """Zet winkels in de wachtrij en start de werker als die stilstaat.

    Geeft terug hoeveel er echt bijgekomen zijn. Een winkel die al in de rij
    staat, al loopt, of al een afgeronde meting heeft, komt er niet nog een keer
    bij: dan zou je twee keer betalen voor dezelfde meting.

    Die laatste controle gaat tegen de database aan en niet tegen het geheugen,
    en dat is precies het punt. Bij een benchmark van zestig winkels loopt de
    wachtrij uren. Herstart Render tussendoor, dan is de wachtrij weg terwijl de
    afgeronde metingen gewoon bewaard zijn. Zonder deze controle zou je de lijst
    opnieuw plakken en alles nog een keer betalen."""
    al_gedaan = set()
    if not opnieuw:
        try:
            al_gedaan = {w["webshop_url"] for w in db.get_demo_webshops()
                         if (w.get("vragen") or 0) >= MINIMUM_VRAGEN_VOOR_POST}
        except Exception as e:
            print(f"Kon niet nakijken welke demo's al gedaan zijn: {e}")

    # De laatste sluis: wie opgegeven is, komt er niet meer in.
    #
    # Dit staat hier expres dubbel. Er zijn drie wegen naar de wachtrij (de
    # gewone ronde, het hervatten van onderbroken metingen, en de beheerpagina)
    # en het is een kwestie van tijd voor er een vierde bij komt. Een winkel die
    # afgevallen is hoort via geen enkele weg nog geld te kosten.
    opgegeven = set()
    try:
        opgegeven = {scan_engine.normalize_url(w["webshop_url"])
                     for w in db.get_benaderingen(stand="afgevallen",
                                                  alleen_niet_afgemeld=False)}
    except Exception as e:
        print(f"Kon de afgevallen winkels niet ophalen: {e}")

    toegevoegd = 0
    overgeslagen = 0
    with _demo_slot:
        for url in urls:
            if scan_engine.normalize_url(url) in opgegeven:
                overgeslagen += 1
                print(f"Meting overgeslagen: {url} is al afgevallen.")
                continue
            huidig = _demo_status.get(url, "")
            bezig = huidig and huidig != "klaar" and not huidig.startswith("mislukt")
            if url in al_gedaan:
                overgeslagen += 1
                _demo_status.setdefault(url, "klaar")
                continue
            if any(w[0] == url for w in _demo_wachtrij) or bezig:
                continue
            _demo_wachtrij.append((url, benchmark_stand, vragen, aanbieders))
            _demo_status[url] = "in de wachtrij"
            toegevoegd += 1
        starten = toegevoegd and not _demo_werker_draait[0]
        if starten:
            _demo_werker_draait[0] = True
    if starten:
        threading.Thread(target=_demo_werker, daemon=True).start()
    if overgeslagen:
        print(f"{overgeslagen} winkel(s) overgeslagen, die waren al gemeten.")
    return toegevoegd


BENCHMARK_VRAGEN = int(os.environ.get("BENCHMARK_VRAGEN", "5"))


def _demo_draaien(webshop_url, benchmark_stand=False, vragen=None, aanbieders=None):
    """De hele keten voor een winkel die geen klant is, in één keer.

    Bewust dezelfde route als bij een echte klant: eerst de gewone scan, dan
    koopvragen, meten, beoordelen en controleren. Zou de demo een eigen kortere
    weg nemen, dan laat je iets zien wat een klant nooit krijgt.

    Er gaat geen mail uit. _meet_en_beoordeel verstuurt alleen als er een
    e-mailadres meegegeven wordt, en dat doen we hier niet. Dat is de reden dat
    deze functie geen e-mailadres kent: dan kan het ook niet per ongeluk.
    """
    try:
        _demo_status[webshop_url] = "site scannen"
        resultaat = run_scan(webshop_url)
        if "error" in resultaat:
            _demo_status[webshop_url] = f"mislukt: {resultaat['error'][:120]}"
            return

        # Als demo bewaren, niet als scan of monitoring. Daaraan herkennen we
        # later welke winkels demo's zijn, en het houdt ze buiten de cijfers
        # over echte klanten.
        # De uitkomst NAKIJKEN. Dit ging mis en het bleef maandenlang onzichtbaar:
        # de kolom email stond op NOT NULL terwijl een demo geen klant heeft, dus
        # elke poging mislukte. Er werd wel gemeten en betaald, maar het rapport
        # werd nooit bewaard. De benchmarkpagina bleef leeg en niemand kon zien
        # waarom.
        if not db.save_report("demo", resultaat["url"], None,
                              resultaat.get("score", 0),
                              resultaat.get("checks", [])):
            _demo_status[webshop_url] = ("mislukt: de meting is gelukt maar het rapport "
                                         "kon niet bewaard worden")
            return
        db.zet_platform(resultaat["url"], resultaat.get("platform"))

        _meet_en_beoordeel(
            resultaat["url"],
            stap=lambda t: _demo_status.__setitem__(webshop_url, t),
            max_vragen=vragen or (BENCHMARK_VRAGEN if benchmark_stand else None),
            max_aanbieders=aanbieders,
            controleer=not benchmark_stand,
            # In de benchmarkstand ook de bronanalyse overslaan. Die kost per
            # winkel een paar zoekopdrachten en tientallen paginabezoeken, en
            # een benchmark kijkt alleen naar het patroon over alle winkels
            # samen. Over zestig winkels scheelt dat uren wachttijd voor iets
            # wat in de optelling niet gebruikt wordt.
            bronnen_aan=not benchmark_stand,
        )
        _demo_status[webshop_url] = "klaar"
    except Exception as e:
        print(f"Demo mislukt voor {webshop_url}: {e}")
        _demo_status[webshop_url] = f"mislukt: {str(e)[:120]}"


@app.route("/admin/demo", methods=["GET", "POST"])
def admin_demo():
    """Demo-uitkomsten: de volledige meting voor een winkel die geen klant is.

    Bedoeld om in een gesprek te laten zien wat iemand krijgt, in plaats van
    het uit te leggen. Kost ongeveer een euro per winkel, dus het starten
    gebeurt alleen op een knop en nooit vanzelf bij het openen van de pagina."""
    admin_key = os.environ.get("ADMIN_KEY")
    # Deze pagina kent ook een sleutel in het FORMULIER, want de knoppen sturen
    # hem mee. Die manier blijft werken; voor de rest gaat het net als bij de
    # andere beheerpagina's via het inlogscherm.
    if request.method == "POST" and _sleutel_klopt(request.form.get("key"), admin_key):
        session.permanent = True
        session["beheer"] = True
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    # Meerdere winkels tegelijk mag: gescheiden door een nieuwe regel, een komma
    # of een spatie. Dat is nodig voor een benchmark over tientallen winkels,
    # die je niet een voor een wil intypen.
    ruw = (request.form.get("url") if request.method == "POST" else None) or request.args.get("url") or ""
    urls = [scan_engine.normalize_url(u.strip())
            for u in re.split(r"[\s,;]+", ruw) if u.strip()]

    if urls and (request.args.get("start") == "ja" or request.form.get("start") == "ja"):
        benchmark_stand = (request.form.get("benchmark") == "ja"
                           or request.args.get("benchmark") == "ja")
        # De "opnieuw"-link naast een winkel moet wel opnieuw meten. Een lijst
        # plakken niet: dan wil je alleen de winkels die nog niet gedaan zijn.
        opnieuw = request.args.get("opnieuw") == "ja"
        _demo_inplannen(urls, benchmark_stand, opnieuw)
        # Terug zonder start=ja, anders begint elke keer verversen opnieuw.
        return redirect(f"/admin/demo")

    winkels = db.get_demo_webshops()
    bekend = {w["webshop_url"] for w in winkels}
    # Winkels die net gestart zijn staan nog niet in de database, maar moeten
    # wel zichtbaar zijn, anders lijkt de knop niets gedaan te hebben.
    for url, status in _demo_status.items():
        if url not in bekend:
            winkels.append({"webshop_url": url, "laatste": None, "score": None, "vragen": 0})
    for w in winkels:
        w["status"] = _demo_status.get(w["webshop_url"], "")

    return render_template("admin_demo.html", winkels=winkels, sleutel=admin_key,
                           wachtrij=len(_demo_wachtrij),
                           bezig=any(w["status"] and w["status"] not in ("klaar",)
                                     and not w["status"].startswith("mislukt") for w in winkels))


@app.route("/admin/onderzoeksmail", methods=["GET", "POST"])
def admin_onderzoeksmail():
    """De gemeten winkels, met per winkel de link naar zijn eigen uitkomst en
    een knop om hem die te mailen.

    Bewust één voor één en geen knop die alles ineens verstuurt. Zestig mails
    tegelijk naar mensen die er niet om gevraagd hebben is precies het verschil
    tussen een onderzoek en spam, en het is ook de snelste manier om je
    mailadres bij Brevo op een zwarte lijst te krijgen."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    melding = None
    if request.method == "POST":
        webshop_url = scan_engine.normalize_url((request.form.get("url") or "").strip())
        email = (request.form.get("email") or "").strip()
        actie = (request.form.get("actie") or "bewaren").strip()

        if not webshop_url:
            melding = "Er ontbrak een winkel."
        elif not email or not _EMAIL_VORM.match(email):
            melding = "Vul een geldig e-mailadres in."
        else:
            if actie == "proef":
                # Een proefmail naar jezelf (23 september). Precies dezelfde
                # mail als een winkel krijgt, maar naar het adres dat jij
                # invult, en er wordt NIETS vastgelegd: geen contactadres, niet
                # als gemaild. Zo kun je de mail bekijken zonder dat die winkel
                # daarna overgeslagen wordt.
                land = ((db.get_benadering(webshop_url) or {}).get("land"))
                # Beide versies (stap 56), zodat je ze naast elkaar ziet.
                verstuurd, fout, gestuurd = True, None, []
                for v in emailing.MAILVARIANTEN:
                    ok, reden = _stuur_onderzoeksmail(webshop_url, email, land, proef=True,
                                                      variant=v)
                    if ok:
                        gestuurd.append(v)
                    elif v == "d" and reden and reden.startswith("Versie d past niet"):
                        continue   # d hoort niet bij elke winkel; geen fout
                    else:
                        verstuurd, fout = False, fout or reden
                melding = (f"{len(gestuurd)} proefmails over {webshop_url} verstuurd naar {email} "
                           f"(versie {', '.join(gestuurd)}, zie [TEST ...] in het onderwerp)."
                           + ("" if "d" in gestuurd else " Versie d niet: die is alleen voor winkels die "
                              "vaak genoemd en zelden aangeraden worden.")
                           + " Er is niets vastgelegd." if verstuurd else
                           f"De proefmail is NIET verstuurd. {fout or ''}")
                return render_template("admin_onderzoeksmail.html", regels=[], d_kandidaten=db.d_kandidaten(),
                                       melding=melding, basis=get_base_url(),
                                       sleutel=admin_key, alleen_proef=True)
            db.zet_contact_email(webshop_url, email)
            if actie != "versturen":
                melding = f"Adres bewaard bij {webshop_url}."
            else:
                # Dezelfde functie als de automatische ronde gebruikt. Eén mail,
                # één plek, geen twee versies die uit elkaar gaan lopen.
                land = ((db.get_benadering(webshop_url) or {}).get("land"))
                verstuurd, fout = _stuur_onderzoeksmail(webshop_url, email, land)
                if verstuurd:
                    db.markeer_onderzoeksmail(webshop_url)
                    db.zet_benadering(webshop_url, stand="gemaild", gemaild=True)
                    melding = f"Verstuurd naar {email}."
                else:
                    # BEWUST niet als verstuurd markeren. Anders sla je hem
                    # over bij de volgende ronde terwijl hij niets gehad
                    # heeft.
                    melding = (f"De mail is NIET verstuurd. {fout or ''} "
                               "Kijk zo nodig in de logs van Render.")

    regels = []
    # In twee query's voor de hele lijst (23 september). Per winkel opvragen
    # liet deze pagina bij ruim duizend winkels eindeloos laden.
    benchmark = db.benchmark_regels()
    profielen, lijst = db.profielen_en_lijstregels([r.get("webshop_url") for r in benchmark])
    for r in benchmark:
        url = r.get("webshop_url")
        profiel = profielen.get(url) or {}
        lijstregel = lijst.get(url) or {}
        regels.append({
            "webshop_url": url,
            "genoemd": r.get("genoemd"),
            "vragen": r.get("vragen"),
            "score": r.get("score"),
            "email": profiel.get("contact_email") or lijstregel.get("email"),
            # Beide plekken, want de automatische ronde en de knop met de hand
            # schrijven allebei. Zie je hier een lege kolom terwijl er al post
            # uit is, dan druk je nog een keer en krijgt iemand twee mails.
            "gemaild_op": profiel.get("onderzoeksmail_op") or lijstregel.get("gemaild_op"),
            "afgemeld": bool(profiel.get("afgemeld_op") or lijstregel.get("afgemeld")),
            "token": profiel.get("benchmark_token"),
        })

    return render_template(
        "admin_onderzoeksmail.html",
        regels=regels,
        melding=melding,
        basis=get_base_url(),
        sleutel=admin_key,
        d_kandidaten=db.d_kandidaten(),
    )


# ---------------------------------------------------------------------------
# De openbare index: per categorie een ranglijst
# ---------------------------------------------------------------------------
#
# DIT IS HET GRATIS KANAAL WAAR KRILLO ZIJN KLANTEN VANDAAN MOET HALEN.
#
# Een winkelier die zoekt of hij door AI genoemd wordt, vindt hier zijn
# categorie, ziet wie er wel genoemd wordt en waar hij zelf staat. Dat is de
# reden om op de knop te drukken, en het kost ons niets per bezoeker.
#
# Tegelijk is dit precies het soort pagina dat AI-assistenten zelf citeren: een
# lijst met een datum, een methode en een bron. Dat is niet toevallig; het is
# hetzelfde dat wij onze klanten aanraden, en we horen het zelf te doen.
#
# WAT ER BEWUST NIET OP STAAT: de namen van winkels die bij geen enkele vraag
# genoemd werden. Meten wat er niet gebeurt is eerlijk, maar iemand publiekelijk
# bij naam op een lijst van niet-genoemden zetten is iets anders. Het aantal
# staat er wel, want dat is het cijfer dat het verhaal draagt.

# Hoeveel winkels een categorie in EEN land minstens moet hebben voordat er een
# openbare ranglijst van komt. Een lijst van twee winkels is geen ranglijst, en
# een pagina die dat toch beweert is precies de overpromise waar wij anderen op
# controleren. Deze ondergrens geldt voor het overzicht EN voor de losse pagina,
# anders staat er een categorie niet in het overzicht terwijl hij wel bestaat.
MINIMUM_PER_LAND = int(os.environ.get("INDEX_MINIMUM_PER_LAND", "3"))


@app.route("/index")
def openbare_index():
    """Het overzicht van alle gemeten categorieen.

    EEN ADRES, EEN TAAL. De hele site staat in het Engels, en alleen een
    uitdrukkelijke ?taal=nl in het adres zet hem om. Bewust NIET de taal van de
    browser: Google haalt de site op zonder taalkop en zou dan iets anders te
    zien krijgen dan een Nederlandse bezoeker op hetzelfde adres. Dan staan er
    twee versies onder een adres en weet een zoekmachine niet welke hij moet
    tonen. Het land dat voorgekozen staat in het keuzemenu mag de browser wel
    bepalen: dat verandert de pagina niet. Er wordt nooit doorgestuurd op
    IP-adres. Zie de uitleg bovenin sitetaal.py."""
    landen = [r["land"] for r in _bewaard(("landen",), db.landen_in_index)]
    taal = sitetaal.kies_taal(pad_taal=request.args.get("taal"))
    voorkeur = (request.args.get("markt") or "").lower()
    if voorkeur not in landen:
        voorkeur = sitetaal.land_uit_kop(
            request.headers.get("Accept-Language"), landen)
    return _indexoverzicht(voorkeur, taal, canonical="/index")


@app.route("/index/<stuk>")
def openbare_index_stuk(stuk):
    """Een land, of een categorie van voor de landenopdeling.

    Adressen die Google al kent moeten blijven werken. Voor de landen bestonden
    stond een categorie op /index/speelgoed; die stuurt nu permanent door naar
    /index/nl/speelgoed. Een 301 en geen 302, want de oude plek komt niet
    terug en een tijdelijke verwijzing laat Google beide adressen aanhouden."""
    kort = (stuk or "").lower()
    if kort in sitetaal.LANDEN:
        landen = [r["land"] for r in _bewaard(("landen",), db.landen_in_index)]
        if kort not in landen:
            return render_template(
                "fout.html", titel="This country is not in the index yet",
                bericht="We are measuring it soon. The countries that are in "
                        "already are listed on /index."), 404
        return _indexoverzicht(kort,
                               sitetaal.kies_taal(pad_taal=request.args.get("taal")),
                               canonical=f"/index/{kort}")
    return redirect(f"/index/nl/{stuk}", code=301)


def _indexoverzicht(land, taal, canonical="/index"):
    """Het overzicht, voor een land of zonder land."""
    t = sitetaal.teksten(taal)
    cijfers = _bewaard(("cijfers",), db.index_cijfers)
    landen = _bewaard(("landen",), db.landen_in_index)
    rijen = (_bewaard(("perland", land), db.categorieen_per_land, land, MINIMUM_PER_LAND) if land
             else _bewaard(("openbaar",), db.openbare_categorieen, MINIMUM_PER_LAND))
    for r in rijen:
        r["naam"] = categorieen.naam_van(r["categorie"])
    rijen.sort(key=lambda r: r["naam"])
    # 7 oktober (Nino): er stond "52 categories" bij Nederland EN bij Belgie,
    # terwijl de lijst eronder er minder had. Dat getal telde elke categorie
    # die ooit gemeten is, ook zonder openbare ranglijst. Nu tellen de
    # categorieen en winkels precies wat er op DEZE pagina staat, per land.
    cijfers = dict(cijfers or {})
    cijfers["categorieen"] = len({r["categorie"] for r in rijen})
    cijfers["winkels"] = sum(int(r.get("winkels") or 0) for r in rijen)
    return render_template(
        "index_overzicht.html",
        t=t, taal=taal, land=land, naam_en=categorieen.naam_en,
        landnaam=sitetaal.landnaam(land, taal) if land else None,
        landen=[{"code": r["land"],
                 "naam": sitetaal.landnaam(r["land"], taal),
                 "taalcode": sitetaal.taal_van_land(r["land"]),
                 "categorieen": r["categorieen"]} for r in landen],
        basis_url=get_base_url().rstrip("/"),
        binnenkort=[{"code": c, "naam": sitetaal.landnaam(c, taal)}
                    for c in sitetaal.LANDEN
                    if c not in {r["land"] for r in landen}],
        cijfers=cijfers,
        categorieen_lijst=rijen,
        canonical=canonical,
    )


@app.route("/index/<land>/<slug>")
def openbare_categorie(land, slug):
    """De ranglijst van een categorie in een land.

    De pagina zelf staat in het Engels, net als de rest van de site. Wat er in
    de taal van het LAND blijft staan is het enige dat daar ook echt hoort: de
    koopvragen die wij gesteld hebben en de naam van de categorie. Dat zijn
    geen vertaalbare teksten maar de meting zelf, en het zijn precies de
    woorden waarop een Nederlandse koper zoekt. Zo leest de site als een
    Engelse site en blijft de Nederlandse zoekterm toch op de pagina staan."""
    land = (land or "").lower()
    if land not in sitetaal.LANDEN:
        return render_template("fout.html", titel="We do not know this country",
                               bericht="The countries we measure are listed on /index."), 404

    taal = sitetaal.kies_taal(pad_taal=request.args.get("taal"))
    t = sitetaal.teksten(taal)
    # 1000 en niet 100 (24 september): de mail noemt een plek uit de hele
    # lijst. Stond een winkel op #140, dan vond de pagina hem niet, en viel de
    # balk met zijn eigen plek en de knop weg.
    lijst = _bewaard(("ranglijst", slug, land), db.ranglijst_per_land, slug, land, 1000)
    if (not lijst or not lijst.get("ronde")
            or len(lijst["rijen"]) < MINIMUM_PER_LAND):
        return render_template(
            "fout.html", titel="This category has not been measured here yet",
            bericht="We measure it as soon as enough stores are in it. The "
                    "categories that are measured are listed on /index."), 404

    genoemd = [r for r in lijst["rijen"] if (r["genoemd"] or 0) > 0]

    # De balk voor wie via zijn eigen mail komt (stap 56). Alleen als het
    # kenmerk bij een winkel hoort die in DEZE lijst staat; een oud of
    # doorgestuurd kenmerk van een andere categorie laat de pagina gewoon zoals
    # hij is. Het kenmerk komt niet op de pagina, alleen in de knop terug.
    jij = None
    kenmerk = (request.args.get("jij") or "").strip()
    if kenmerk:
        try:
            eigen_url = db.winkel_bij_benchmark_token(kenmerk)
        except Exception:
            eigen_url = None
        for r in lijst["rijen"] if eigen_url else []:
            if r["webshop_url"] == eigen_url:
                jij = {"positie": r["positie"], "van": len(lijst["rijen"]),
                       "genoemd": r["genoemd"] or 0, "telbaar": lijst["telbaar"],
                       "naam": (r.get("naam") if r.get("naam") and not str(r.get("naam")).startswith("http")
                                else eigen_url.replace("https://", "").replace("www.", "").rstrip("/")),
                       "verder": f"/uitkomst/{kenmerk}/verder",
                       # Stap 168: de gratis proef als grote knop, met winkel
                       # en mailadres al ingevuld (zie uitkomst_verder).
                       "proef": f"/uitkomst/{kenmerk}/verder?plan=watch",
                       "vragen": f"/uitkomst/{kenmerk}/questions"}
                break
    lijst_voor_ai = [{"@type": "ListItem", "position": r["positie"],
                      "name": r["naam"] or r["webshop_url"], "url": r["webshop_url"]}
                     for r in genoemd]

    # De andere landen waar deze categorie ook gemeten is. Dat wordt hreflang,
    # zodat een zoekmachine weet dat dit dezelfde pagina voor een ander land is
    # en ze niet als kopieen van elkaar behandelt.
    anders = []
    for rij in _bewaard(("landen",), db.landen_in_index):
        code = rij["land"]
        if code == land or code not in sitetaal.LANDEN:
            continue
        if any(c["categorie"] == slug
               for c in _bewaard(("perland", code), db.categorieen_per_land, code, MINIMUM_PER_LAND)):
            anders.append({"code": code,
                           "taal": sitetaal.taal_van_land(code),
                           "naam": sitetaal.landnaam(code, taal)})

    # Het kruimelpad als gestructureerde gegevens. Dit is wat een zoekmachine
    # laat zien als "Krillo > Nederland > Speelgoed" in plaats van een kale
    # link, en het vertelt tegelijk dat deze pagina onder een land hangt.
    basis_url = get_base_url().rstrip("/")
    kruimels = [
        {"@type": "ListItem", "position": 1, "name": "Krillo",
         "item": f"{basis_url}/index"},
        {"@type": "ListItem", "position": 2,
         "name": sitetaal.landnaam(land, taal), "item": f"{basis_url}/index/{land}"},
        {"@type": "ListItem", "position": 3, "name": categorieen.naam_van(slug),
         "item": f"{basis_url}/index/{land}/{slug}"},
    ]

    return render_template(
        "index_categorie.html",
        t=t, taal=taal, land=land, slug=slug, kruimels=kruimels,
        landnaam=sitetaal.landnaam(land, taal),
        andere_landen=anders,
        naam=categorieen.naam_van(slug),
        naam_en=categorieen.naam_en(slug),
        jij=jij,
        lijst_voor_ai=lijst_voor_ai,
        ranglijst=genoemd,
        niet_genoemd=len(lijst["rijen"]) - len(genoemd),
        totaal=len(lijst["rijen"]),
        telbaar=lijst["telbaar"],
        gemeten_op=(genoemd[0].get("gemeten_op") if genoemd else None),
        vragen=_bewaard(("vragen", lijst["ronde"]), db.gemeten_vragen_van_ronde, lijst["ronde"]),
        modellen=_assistenten(_bewaard(("modellen", lijst["ronde"]), db.modellen_van_ronde, lijst["ronde"])),
        canonical=f"/index/{land}/{slug}",
        basis_url=basis_url,
        basis=get_base_url(),
        winkel_slug=_winkel_slug,
        embed=embed_code(land, slug, basis_url),
        # Stap 187: de kaart genoemd tegen aanbevolen.
        kaart=_categoriekaart_svg(lijst["rijen"], lijst["telbaar"]),
        # Stap 178: waar AI kopers naartoe stuurt.
        bronnen=_bronnen_van_ronde(lijst["ronde"]),
    )


def _categoriekaart_svg(rijen, telbaar):
    try:
        import categoriekaart
        return categoriekaart.svg(rijen, telbaar)
    except Exception as e:
        print(f"Categoriekaart mislukt: {e}")
        return ""


@app.route("/index/<land>/<slug>/map.png")
def categoriekaart_png(land, slug):
    """Stap 187: de kaart als plaatje voor LinkedIn (1200 x 1200)."""
    import categoriekaart
    land = (land or "").lower()
    lijst = _bewaard(("ranglijst", slug, land), db.ranglijst_per_land, slug, land, 1000) \
        if land in sitetaal.LANDEN else None
    if not lijst or not lijst.get("ronde") or len(categoriekaart.punten(lijst["rijen"], lijst["telbaar"])) < 3:
        return "Not enough stores named for a map.", 404
    naam = categorieen.naam_en(slug) if hasattr(categorieen, "naam_en") else categorieen.naam_van(slug)
    gemeten = next((r.get("gemeten_op") for r in lijst["rijen"] if r.get("gemeten_op")), None)
    maand = gemeten.strftime("%B %Y") if hasattr(gemeten, "strftime") else ""
    # 1 oktober (geheugen): elk plaatje een keer tekenen per meting, en nooit
    # twee tegelijk. Een tekening kost even een paar tientallen MB; acht
    # tegelijk (Google die alle kaarten opvraagt) ging over de grens van Render.
    sleutel = (land, slug, lijst.get("ronde"))
    data = _kaart_png_opslag.get(sleutel)
    if data is None:
        with _kaart_png_slot:
            data = _kaart_png_opslag.get(sleutel)
            if data is None:
                data = categoriekaart.png(lijst["rijen"], lijst["telbaar"], naam, sitetaal.landnaam(land, "en"), maand)
                if len(_kaart_png_opslag) >= 80:
                    _kaart_png_opslag.clear()
                _kaart_png_opslag[sleutel] = data
    return Response(data, mimetype="image/png", headers={"Cache-Control": "public, max-age=86400"})


_kaart_png_opslag = {}
_kaart_png_slot = threading.Lock()


def _winkel_slug(webshop_url):
    """Het stukje adres voor de winkelpagina: het domein zonder www (stap 90)."""
    return (webshop_url or "").lower().replace("https://", "").replace("http://", "").replace(
        "www.", "").split("/")[0]


def _winkel_naam(rij):
    naam = rij.get("naam")
    return naam if naam and not str(naam).startswith("http") else _winkel_slug(rij.get("webshop_url"))


@app.route("/index/<land>/<slug>/<winkel>")
def openbare_winkel(land, slug, winkel):
    """Stap 90: een pagina per winkel in de index.

    WAAROM. Een eigenaar die zijn eigen winkelnaam googelt, of ChatGPT vraagt
    "raadt ChatGPT mijn winkel aan", komt hier uit, en elke pagina eindigt bij
    de gratis check. Profound haalt zo zijn verkeer binnen, per merk.

    ALLEEN WINKELS DIE AI NOEMT. De categoriepagina noemt de winkels met nul
    vermeldingen niet bij naam, alleen als aantal. Een eigen pagina met "wordt
    niet genoemd" zou meer openbaar maken dan de ranglijst zelf, en dat doen we
    niet. Afgemelde winkels staan al niet in de ranglijst."""
    land = (land or "").lower()
    winkel = (winkel or "").lower()
    if land not in sitetaal.LANDEN:
        return redirect("/index", code=302)
    lijst = _bewaard(("ranglijst", slug, land), db.ranglijst_per_land, slug, land, 1000)
    if not lijst or not lijst.get("ronde") or len(lijst.get("rijen") or []) < MINIMUM_PER_LAND:
        return redirect("/index", code=302)
    genoemd = [r for r in lijst["rijen"] if (r.get("genoemd") or 0) > 0]
    rij = next((r for r in genoemd if _winkel_slug(r["webshop_url"]) == winkel), None)
    if not rij:
        return redirect(f"/index/{land}/{slug}", code=302)
    taal = "en"
    basis_url = get_base_url().rstrip("/")
    naam = _winkel_naam(rij)
    categorie = categorieen.naam_van(slug)
    landnaam = sitetaal.landnaam(land, taal)
    buren = [dict(r, weergave=_winkel_naam(r), pad=f"/index/{land}/{slug}/{_winkel_slug(r['webshop_url'])}")
             for r in genoemd if r is not rij and abs(r["positie"] - rij["positie"]) <= 2][:4]
    kruimels = [
        {"@type": "ListItem", "position": 1, "name": "Krillo", "item": f"{basis_url}/index"},
        {"@type": "ListItem", "position": 2, "name": landnaam, "item": f"{basis_url}/index/{land}"},
        {"@type": "ListItem", "position": 3, "name": categorie, "item": f"{basis_url}/index/{land}/{slug}"},
        {"@type": "ListItem", "position": 4, "name": naam, "item": f"{basis_url}/index/{land}/{slug}/{winkel}"},
    ]
    return render_template(
        "index_winkel.html", land=land, slug=slug, winkel=winkel, rij=rij, naam=naam,
        categorie=categorie, landnaam=landnaam, totaal=len(lijst["rijen"]), telbaar=lijst["telbaar"],
        buren=buren, kruimels=kruimels, basis_url=basis_url,
        maand=(rij.get("gemeten_op").strftime("%B %Y") if rij.get("gemeten_op") else None),
        imago=_imago(lijst["ronde"], rij["webshop_url"], naam),
        modellen=_assistenten(_bewaard(("modellen", lijst["ronde"]), db.modellen_van_ronde, lijst["ronde"])))


def _bronnen_van_ronde(ronde):
    """Stap 178. Bewaard per ronde: de uitkomst is klein, de antwoorden niet."""
    if not ronde:
        return []
    try:
        import bronnenkaart
        return _bewaard(("bronnen", ronde),
                        lambda: bronnenkaart.bronnen(db.antwoorden_met_tekst_van_ronde(ronde)))
    except Exception as e:
        print(f"Bronnen mislukt voor ronde {ronde}: {e}")
        return []


def _imago(ronde, webshop_url, naam):
    """Stap 179. Nooit een fout naar de bezoeker: zonder imago blijft de pagina gewoon staan."""
    try:
        import imago
        # Het resultaat bewaren, niet de antwoorden zelf: zestig antwoordteksten
        # per ronde, voor honderd rondes, is te veel geheugen op Render.
        return _bewaard(("imago", ronde, webshop_url),
                        lambda: imago.beeld(webshop_url, naam, db.antwoorden_met_tekst_van_ronde(ronde)))
    except Exception as e:
        print(f"Imago mislukt voor {webshop_url}: {e}")
        return None


@app.route("/api/plekmelding", methods=["POST"])
def api_plekmelding():
    """Stap 166: een melding als de plek van deze winkel verandert. Eerst een
    bevestigingsmail; pas na de klik komen er meldingen."""
    import plekmelding
    import gratistools
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    land, slug, winkel = (data.get("land") or "").lower(), data.get("slug") or "", (data.get("winkel") or "").lower()
    if not _EMAIL_VORM.match(email) or len(email) > 190:
        return jsonify({"fout": "Enter a valid email address."}), 400
    if not gratistools.mag_nu("plek:" + (_bezoeker_kenmerk() or request.remote_addr or "?")):
        return jsonify({"fout": "Check your inbox: we already sent a confirmation."}), 429
    lijst = _ranglijst_bewaard(slug, land) if land in sitetaal.LANDEN else None
    rij = next((r for r in (lijst or {}).get("rijen") or [] if _winkel_slug(r["webshop_url"]) == winkel), None)
    if not rij:
        return jsonify({"fout": "We could not find this store in the ranking."}), 404
    uit = plekmelding.aanmelden(email, rij["webshop_url"], land, slug, rij["positie"], lijst.get("ronde"))
    if not uit:
        return jsonify({"fout": "Something went wrong. Try again in a moment."}), 500
    if uit.get("bevestigd_op"):
        return jsonify({"ok": True, "al": True})
    basis = get_base_url().rstrip("/")
    onderwerp, alineas = plekmelding.bevestigmail(winkel, None)
    emailing.send_klantbericht(email, onderwerp, alineas, f"{basis}/plekmelding/{uit['token']}/bevestig",
                               knop="Confirm rank updates")
    return jsonify({"ok": True})


@app.route("/plekmelding/<token>/bevestig")
def plekmelding_bevestig(token):
    import plekmelding
    rij = plekmelding.bevestig(token)
    if not rij:
        return render_template("fout.html", titel="This link no longer works",
                               bericht="Sign up again on your store's page in the index."), 404
    if rij.get("nieuw"):
        # De warmste lead die er is: hij zocht zijn eigen winkel op en wil het volgen.
        _meld_aan_beheer("Iemand claimde zijn plek",
                         f"{escape(rij['email'])} volgt nu de plek van {escape(rij['webshop_url'])} "
                         f"({escape(rij.get('categorie') or '')}, #{rij.get('positie')}). Warme lead: "
                         f"hij zocht zijn eigen winkel op.")
    return render_template("fout.html", titel="Confirmed",
                           bericht="We email you when the rank of your store changes. Every email has a link to stop.")


@app.route("/plekmelding/<token>/stop", methods=["GET", "POST"])
def plekmelding_stop(token):
    import plekmelding
    plekmelding.afmelden(token)
    if request.method == "POST":
        return "", 204
    return render_template("fout.html", titel="You will not hear from us again",
                           bericht="We stopped the rank updates for this store.")


@app.route("/embed/<land>/<slug>")
def ingesloten_ranglijst(land, slug):
    """Stap 164: de ranglijst om in te sluiten (iframe) voor vakmedia en blogs.
    De top 5 van de laatste meting, werkt zichzelf bij, met een link terug.
    Mag in elk venster staan: alleen /shopify is beperkt (zie hierboven)."""
    land = (land or "").lower()
    lijst = (_bewaard(("ranglijst", slug, land), db.ranglijst_per_land, slug, land, 1000)
             if land in sitetaal.LANDEN else None)
    rijen = [r for r in (lijst or {}).get("rijen") or [] if (r.get("genoemd") or 0) > 0]
    if not lijst or not lijst.get("ronde") or len(lijst.get("rijen") or []) < MINIMUM_PER_LAND or not rijen:
        return Response("", status=404)
    antwoord = app.make_response(render_template(
        "embed_ranglijst.html", land=land, slug=slug, rijen=rijen[:5], telbaar=lijst["telbaar"],
        categorie=categorieen.naam_van(slug), landnaam=sitetaal.landnaam(land, "en"),
        maand=(rijen[0].get("gemeten_op").strftime("%B %Y") if rijen[0].get("gemeten_op") else ""),
        winkel_slug=_winkel_slug, winkel_naam=_winkel_naam, basis_url=get_base_url().rstrip("/")))
    antwoord.headers["Cache-Control"] = "public, max-age=21600"
    antwoord.headers["X-Robots-Tag"] = "noindex"
    return antwoord


def embed_code(land, slug, basis_url=None):
    """De code die een redactie plakt (stap 164). Ook in het persbericht."""
    basis_url = basis_url or get_base_url().rstrip("/")
    naam = categorieen.naam_van(slug)
    return (f'<iframe src="{basis_url}/embed/{land}/{slug}" title="Krillo Index: {naam}" '
            f'width="100%" height="360" style="border:0;max-width:560px" loading="lazy"></iframe>')


def _dashboard(webshop_url, land=None, voorbeeld=False, klant_token=None, beheer=None,
               pagina="overzicht", proef=None, categorie=None):
    """Het dashboard van een winkel. Dezelfde pagina's voor het openbare
    voorbeeld, voor een klant en voor de beheerweergave.

    SINDS 28 SEPTEMBER vijf echte pagina's (zie dashboardpaginas.PAGINAS), elk
    met een eigen adres: /mijn/<token>, /mijn/<token>/ranking, /questions,
    /fixes en /plan (en hetzelfde onder /demo). Daarvoor was het een lange
    pagina met een zijbalk die alleen naar beneden scrolde.

    Een klant ziet zijn eigen versie: Watch krijgt de verbeteringen om zelf te
    doen, Fix ziet wat wij deden. Dat verschil zit in _werkblok en
    _plan_uitleg, niet in losse sjablonen, zodat het nooit uit elkaar loopt."""
    import dashboardpaginas as dp
    if pagina not in {n for n, _, _ in dp.PAGINAS}:
        pagina = "overzicht"
    beeld = klantbeeld.bouw(webshop_url, land=land, categorie=categorie)
    werk = klant_token is not None or beheer is not None
    if not beeld and not werk:
        return None
    taal = sitetaal.kies_taal(pad_taal=request.args.get("taal"))

    # Waar elke knop van de zijbalk heen gaat.
    if proef:
        # De gratis voorproef na de koude mail (stap 135, 28 september).
        basis, achter = f"/uitkomst/{proef}", ""
    elif klant_token:
        basis, achter = f"/mijn/{klant_token}", ""
    elif beheer:
        basis, achter = None, None
    else:
        basis, achter = "/demo", ""
    extra = f"?taal={taal}" if request.args.get("taal") else ""
    links, link_van = [], {}
    for naam, pad, labels in dp.PAGINAS:
        if basis is None:
            href = (f"/admin/voorbeeld?url={quote(webshop_url)}&pagina={naam}"
                    + (f"&taal={taal}" if request.args.get("taal") else ""))
        else:
            href = basis + (f"/{pad}" if pad else "") + extra
        links.append({"naam": naam, "label": labels.get(taal, labels["en"]), "href": href,
                      "aan": naam == pagina})
        link_van[naam] = href
    paginanaam = next(l["label"] for l in links if l["aan"])

    werkblok = _werkblok(webshop_url, taal, klant_token=klant_token, beheer=beheer) if werk else None
    gegevens = {}
    if not beeld:
        gegevens["geen_plek"] = _geen_plek_reden(webshop_url)
        # Een klant (of de beheerweergave) zonder plek: meteen uitrekenen uit de
        # antwoorden van deze maand, in plaats van een maand te wachten.
        eigen_controle = (request.headers.get("User-Agent") or "").startswith("KrilloKlantblik")
        if werk and gegevens["geen_plek"].get("soort") in ("niet_in_meting", "geen_categorie", "niet_gemeten") \
                and not gegevens["geen_plek"].get("wordt_gemeten") and not eigen_controle:
            _plaats_in_ranglijst(webshop_url)
            # Alleen "bezig" zeggen als het ook echt loopt (of net liep).
            if time.time() - _plaatsen_bezig.get(webshop_url, 0) < 600:
                gegevens["geen_plek"]["bezig"] = True
        # 8 oktober: de startpagina met stappen in plaats van een lege pagina.
        if klant_token and not proef:
            try:
                klant_rij = db.get_klant(klant_token) or {}
                wachtwoord = False if eigen_controle else _wachtwoord_nu(webshop_url, klant_rij)
                gegevens["start"] = _startstappen(webshop_url, klant_token, gegevens["geen_plek"], taal,
                                                  pakket=klant_rij.get("pakket"), wachtwoord=wachtwoord)
                gegevens["wachtwoord"] = wachtwoord
                gegevens["categorie_post"] = f"/mijn/{klant_token}/categorie"
                gegevens["categoriekeuzes"] = _categoriekeuzes()
                gegevens["gekozen_land"] = ((db.winkel_kort(webshop_url) or {}).get("land")
                                            or categoriemeting._land_bij_domein(
                                                categoriemeting._schoon_domein(webshop_url) or "") or "nl")
                gegevens["categorie_melding"] = request.args.get("categorie") or ""
                import pixel
                sleutel = pixel.sleutel_voor(webshop_url)
                gegevens["pixel"] = {"status": pixel.status(webshop_url),
                                     "shopify": pixel.shopify_code(sleutel, get_base_url()),
                                     "site": pixel.site_code(sleutel, get_base_url()),
                                     "winkel": webshop_url, "check": f"/mijn/{klant_token}/pixelcheck"}
            except Exception as e:
                print(f"Startpagina mislukt voor {webshop_url}: {e}")
    elif klant_token and not proef:
        # Wie wel een plek heeft maar intussen zijn winkel dichtzette: zeggen,
        # want dan gaan zijn fixes over de wachtwoordpagina.
        gegevens["wachtwoord"] = scan_engine.staat_achter_wachtwoord(webshop_url)
        # 8 oktober: ook met een plek kan de klant van categorie wisselen (Ranking).
        gegevens["categorie_post"] = f"/mijn/{klant_token}/categorie"
        gegevens["categoriekeuzes"] = _categoriekeuzes()
        gegevens["gekozen_land"] = (beeld.get("land") or "nl")
        # 8 oktober (Nino koos Winter sports en bleef Sports and fitness zien):
        # een kleine categorie die nog niet gemeten is, rolt op in zijn ouder.
        # Dat is goed (anders zie je niets), maar dan moet het er wel staan.
        try:
            eigen = (db.winkel_kort(webshop_url) or {}).get("categorie")
            if eigen and eigen != beeld.get("categorie") and eigen not in categorieen.NIET_MEETBAAR:
                reden = _geen_plek_reden_voor_categorie(eigen, beeld.get("land") or "nl")
                gegevens["eigen_categorie"] = dict(reden, naam=categorieen.naam_en(eigen),
                                                   ouder=categorieen.naam_en(beeld.get("categorie")))
        except Exception as e:
            print(f"Eigen categorie nakijken mislukt voor {webshop_url}: {e}")
    # Stap 316: de pagina Site check, met of zonder plek.
    if pagina == "sitecheck":
        gegevens["sitecheck"] = _sitecheck(webshop_url, klant_token, taal) if klant_token and not proef else None
    # 8 oktober (versie 10, Nino: "choose the assistants is een mooie
    # functie, voeg die toe"): welke nieuwe assistenten deze klant erbij wil.
    if pagina in ("overzicht", "abonnement") and klant_token and not proef:
        gegevens["assistenten_keuze"] = _assistenten_keuze(webshop_url)
        gegevens["assistenten_url"] = f"/mijn/{klant_token}/assistenten"
    elif pagina == "overzicht" and voorbeeld:
        # 9 oktober, Nino: "waar staat choose the assistants in het voorbeeld?"
        # In het voorbeeld laten we het blok zien, maar zonder adres: de
        # schakelaars bewegen, er wordt niets bewaard, en dat staat erbij.
        gegevens["assistenten_keuze"] = []
        gegevens["assistenten_url"] = ""
    if beeld:
        winkelnaam = beeld.get("naam")
        if pagina in ("overzicht", "vragen"):
            try:
                gegevens["vragen"] = dp.vragen_overzicht(beeld["ronde"], webshop_url, winkelnaam)
            except Exception as e:
                print(f"Vragen voor het dashboard mislukt voor {webshop_url}: {e}")
                gegevens["vragen"] = {"vragen": [], "gewonnen": 0, "verloren": 0, "totaal": 0,
                                      "per_assistent": []}
            if proef:
                # In de voorproef zijn de eerste twee vragen helemaal open, de
                # rest staat op slot: de vraag zelf wel, het antwoord en wie
                # er genoemd werd niet. Dat gaat ook NIET mee naar de browser.
                for i, v in enumerate(gegevens["vragen"]["vragen"]):
                    if i >= dp.PROEF_OPEN_VRAGEN:
                        v["per_model"] = [{"assistent": m["assistent"], "genoemd": m["genoemd"],
                                           "aanbevolen": False, "anderen": [], "fragment": ""}
                                          for m in v["per_model"]]
                        v["slot"] = True
            # 8 oktober: vragen die de klant als "niet voor mijn winkel" wegzette.
            if klant_token and not proef:
                gegevens["niet_voor_mij"] = _niet_voor_mij(webshop_url)
                gegevens["vragen"] = _zonder_niet_voor_mij(gegevens["vragen"], set(gegevens["niet_voor_mij"]))
                gegevens["weg_url"] = f"/mijn/{klant_token}/niet-voor-mij"
            gegevens["balken"] = dp.balken_per_assistent(gegevens["vragen"]["per_assistent"])
            # 1 oktober: de vragen met de minste concurrentie, om eerst over te schrijven.
            gegevens["open_plekken"] = [] if proef else dp.open_plekken(gegevens["vragen"])
            # 2 oktober (stap 180): de eigen vragen van de klant, alleen in zijn dashboard.
            if klant_token and not proef:
                try:
                    import eigenvragen
                    klant_rij = db.get_klant(klant_token) or {}
                    lijst = eigenvragen.overzicht(webshop_url)
                    gegevens["eigen"] = {
                        "lijst": lijst, "max": eigenvragen.maximum(klant_rij.get("pakket")),
                        "voorstellen": eigenvragen.voorstellen(
                            webshop_url, categorienaam=beeld.get("categorie") if beeld else None,
                            land=(beeld or {}).get("land") or "nl", al=[v["vraag"] for v in lijst]),
                        "melding": request.args.get("eigen") or "",
                        "actie": f"/mijn/{klant_token}/eigen-vragen"}
                except Exception as e:
                    print(f"Eigen vragen voor het dashboard mislukt: {e}")
        if pagina == "verbeteringen" and werk and not proef:
            # Stap 255: AI-gereedheid per pagina, uit de wekelijkse ronde.
            try:
                import paginacheck
                gegevens["paginacheck"] = paginacheck.laatste(webshop_url)
            except Exception as e:
                print(f"Paginacheck voor het dashboard mislukt: {e}")
        if pagina == "verbeteringen":
            # 1 oktober: per verloren vraag wat je concreet doet (vraagaanpak.py).
            try:
                import vraagaanpak
                vo = dp.vragen_overzicht(beeld["ronde"], webshop_url, winkelnaam)
                if klant_token:
                    vo = _zonder_niet_voor_mij(vo, set(_niet_voor_mij(webshop_url)))
                gekozen_lijst = db.gekozen_vragen(webshop_url) if klant_token else []
                gegevens["aanpak"] = vraagaanpak.voor_dashboard(
                    vo, gekozen_lijst, sitetaal.landnaam(beeld.get("land"), taal) if beeld.get("land") else None,
                    en=(taal != "nl"), maximaal=(2 if proef else 3))
                # Stap 290: per vraag de bronnen die AI noemt en de pagina die moet antwoorden.
                if not proef:
                    try:
                        import paginacheck
                        pc = paginacheck.laatste(webshop_url) or {}
                        vraagaanpak.verrijk(gegevens["aanpak"], db.antwoorden_met_tekst_van_ronde(beeld["ronde"]),
                                            pc.get("paginas"))
                    except Exception as e:
                        print(f"Bronnen en pagina per vraag mislukt voor {webshop_url}: {e}")
            except Exception as e:
                print(f"Aanpak per vraag mislukt voor {webshop_url}: {e}")
        if klant_token and not proef:
            # Versie 10: ook buiten het overzicht, voor "Your first month" onderaan de zijbalk.
            try:
                gegevens["gids"] = _eerste_maand(webshop_url, klant_token, beeld, taal,
                                                 pakket=(db.get_klant(klant_token) or {}).get("pakket"))
            except Exception as e:
                print(f"Gids voor het overzicht mislukt voor {webshop_url}: {e}")
        if pagina == "overzicht":
            # Stap 198: de wekelijkse snelmeting, alleen voor een betalende klant.
            if werk and not proef:
                try:
                    import snelmeting
                    gegevens["snel"] = snelmeting.overzicht(webshop_url)
                    # 2 oktober: de productkaart uit dezelfde wekelijkse vragen.
                    try:
                        import productkaart
                        gegevens["productkaart"] = productkaart.kaart(webshop_url)
                    except Exception as e:
                        print(f"Productkaart mislukt voor {webshop_url}: {e}")
                    gegevens["snel_dag"] = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                                            "Saturday", "Sunday"][meetdag(webshop_url)]
                except Exception as e:
                    print(f"Snelmeting voor het dashboard mislukt: {e}")
            # 7 oktober: brengt AI ook bezoek en verkoop? Een klant vult zijn eigen
            # cijfers in (aiverkeer.py); demo en voorproef zien een voorbeeld.
            try:
                import aiverkeer
                if klant_token:
                    pakket = ((db.get_klant(klant_token) or {}).get("pakket") or "watch")
                    prijs = float(payments.prijs_van(pakket)["value"])
                    gegevens["aiverkeer"] = aiverkeer.overzicht(webshop_url, beeld.get("verloop"),
                                                                maandprijs=prijs)
                    gegevens["aiverkeer_post"] = f"/mijn/{klant_token}/aiverkeer"
                    # Stap 304: de pixel, met de code al ingevuld voor deze winkel.
                    try:
                        import pixel
                        sleutel = pixel.sleutel_voor(webshop_url)
                        gegevens["pixel"] = {"status": pixel.status(webshop_url),
                                             "shopify": pixel.shopify_code(sleutel, get_base_url()),
                                             "site": pixel.site_code(sleutel, get_base_url()),
                                             "winkel": webshop_url, "check": f"/mijn/{klant_token}/pixelcheck"}
                    except Exception as e:
                        print(f"Pixel voor het dashboard mislukt: {e}")
                elif not beheer:
                    gegevens["aiverkeer"] = aiverkeer.voorbeeld()
                    gegevens["aiverkeer_voorbeeld"] = True
            except Exception as e:
                print(f"AI-verkeer voor het dashboard mislukt: {e}")
            eigen = [{"naam": winkelnaam, "jij": True,
                      "punten": [(r.get("afgerond_op"), r["positie"]) for r in beeld.get("verloop") or []]}]
            gegevens["grafiek_eigen"] = dp.lijngrafiek(eigen, taal=taal)
            # 29 september: de ranglijst als kaart op het overzicht (zoals Peec):
            # de top 5, en jijzelf eronder als je daar niet bij zit.
            try:
                rijen = (_ranglijst_bewaard(beeld["categorie"], beeld.get("land")) or {}).get("rijen") or []
            except Exception as e:
                print(f"Ranglijst voor het overzicht mislukt: {e}")
                rijen = []
            gegevens["top"] = dp.topkaart(rijen, webshop_url, beeld.get("telbaar") or 0, aantal=7)
            # Stap 241: het concurrent-alarm. Maand uit deze ranglijst, week uit
            # de snelmeting (alleen voor een betalende klant, die heeft hem).
            try:
                import concurrentalarm
                alarm = concurrentalarm.zinnen_maand(concurrentalarm.maand(rijen, webshop_url), taal)
                if werk and not proef:
                    alarm = concurrentalarm.zinnen_week(concurrentalarm.week_voor(webshop_url), taal) + alarm
                gegevens["alarm"] = alarm[:5]
            except Exception as e:
                print(f"Concurrent-alarm voor het dashboard mislukt: {e}")
            # Versie 8 (30 september): de beweging per winkel naast de ranglijst,
            # de grafiek als gegevens voor de browser en de lijntjes in de tegels.
            try:
                gegevens["reeksen"] = dp.grafiek_reeksen(beeld)
            except Exception as e:
                print(f"Grafiekgegevens voor het overzicht mislukt: {e}")
                gegevens["reeksen"] = []
            gegevens["vonkjes"] = {s: dp.vonkje(beeld.get("verloop"), s) for s in ("positie", "zicht", "aanbevolen")}
            # Versie 2: het verloop van jou EN de winkels boven je, zoals Peec
            # de concurrenten in een grafiek zet.
            try:
                buren = dp.buren_verloop(beeld)
                gegevens["grafiek_buren"] = dp.lijngrafiek(buren, breedte=760, hoogte=240, taal=taal)
                anderen = [b for b in buren if not b.get("jij")]
                gegevens["buren"] = ([{"naam": winkelnaam, "kleur": dp.KLEUR_JIJ}]
                                     + [{"naam": b["naam"], "kleur": dp.KLEUREN_ANDEREN[i % 3]}
                                        for i, b in enumerate(anderen)])
            except Exception as e:
                print(f"Verloop met buren voor het overzicht mislukt: {e}")
        if pagina == "ranglijst":
            # Twee keer proberen (28 september: de demo liet "All 0 stores" zien
            # terwijl dezelfde ranglijst een regel hoger wel lukte; een tijdelijk
            # verbindingsprobleem met de database). Lukt het echt niet, dan in
            # de log, en het scherm zegt eerlijk dat de lijst even niet laadt.
            gegevens["ranglijst"] = []
            for poging in range(2):
                try:
                    gegevens["ranglijst"] = db.ranglijst_per_land(
                        beeld["categorie"], beeld.get("land"), limiet=500).get("rijen") or []
                except Exception as e:
                    print(f"Ranglijst voor het dashboard mislukt (poging {poging + 1}): {e}")
                if gegevens["ranglijst"]:
                    break
                time.sleep(0.4)
            if not gegevens["ranglijst"]:
                print(f"Ranglijst voor het dashboard LEEG voor {webshop_url} ({beeld['categorie']})")
            # 1 oktober (stap 179 en 187 op het dashboard): de kaart met de klant
            # erin gemarkeerd, en wat AI letterlijk over hem zegt. In de voorproef
            # (na de koude mail) ook: dat is juist wat hem overhaalt.
            try:
                import categoriekaart
                gegevens["kaart"] = categoriekaart.svg(gegevens["ranglijst"], beeld.get("telbaar"),
                                                       markeer=webshop_url)
            except Exception as e:
                print(f"Kaart voor het dashboard mislukt: {e}")
            gegevens["imago"] = _imago(beeld["ronde"], webshop_url, winkelnaam)
            # Stap 244 (8 oktober): dezelfde telling voor de winkel die AI het vaakst
            # noemt, zodat de klant ziet om welke woorden die gekozen wordt en hij niet.
            try:
                import imago as _im
                leider = next((r for r in gegevens.get("ranglijst") or []
                               if not scan_engine.is_eigen_winkel(webshop_url, r.get("webshop_url") or "")), None)
                if leider and gegevens.get("imago") is not None:
                    gegevens["imago_leider"] = leider.get("naam") or leider.get("webshop_url")
                    gegevens["imago_vergelijk"] = _im.vergelijk(
                        gegevens["imago"], _imago(beeld["ronde"], leider["webshop_url"], leider.get("naam")))
            except Exception as e:
                print(f"Imago-vergelijking mislukt voor {webshop_url}: {e}")
            # Stap 178 (1 oktober): waar AI kopers in deze categorie naartoe stuurt.
            gegevens["bronnen"] = _bronnen_van_ronde(beeld["ronde"])
            buren = dp.buren_verloop(beeld)
            gegevens["grafiek_buren"] = dp.lijngrafiek(buren, breedte=1000, hoogte=280, taal=taal)
            anderen = [b for b in buren if not b.get("jij")]
            gegevens["buren"] = ([{"naam": b["naam"], "kleur": dp.KLEUREN_ANDEREN[i % 3]}
                                  for i, b in enumerate(anderen)]
                                 + [{"naam": winkelnaam, "kleur": dp.KLEUR_JIJ}])
    # "Add to my fixes" (30 september): de lijst van de klant, op het overzicht
    # voor de knoppen en op Verbeteringen bovenaan.
    gegevens["gekozen"] = db.gekozen_vragen(webshop_url) if klant_token else []
    # Versie 10 (8 oktober): zijbalk met groepen, en de blokken van het canvas.
    try:
        gegevens.update(_canvas_gegevens(webshop_url, beeld, pagina, links, taal, klant_token, proef,
                                         werkblok, gegevens))
    except Exception as e:
        print(f"Canvasgegevens mislukt voor {webshop_url}: {e}")
    return render_template(
        "dashboard.html",
        t=sitetaal.teksten(taal), taal=taal, beeld=beeld, pagina=pagina,
        paginanaam=paginanaam, links=links, link_van=link_van,
        winkelnaam=_winkelnaam(webshop_url) or webshop_url.replace("https://", ""),
        landnaam=sitetaal.landnaam(beeld.get("land"), taal) if beeld else None,
        modellen=sorted({dp.assistent_naam(m) for m in db.modellen_van_ronde(beeld["ronde"])}) if beeld else [],
        # Engelse naam op een Engelse pagina (27 september).
        categorienaam=((categorieen.naam_en(beeld["categorie"]) if taal == "en"
                        else categorieen.naam_van(beeld["categorie"])) if beeld else None),
        buiten_markt=_buiten_markt(webshop_url),
        volgende=dp.volgende_stap(beeld, werkblok, taal),
        plan_uitleg=_plan_uitleg(webshop_url, werkblok, taal) if werkblok else None,
        doorverwijzing=_doorverwijzing_voor(webshop_url, pagina, werkblok, proef),
        werk_deel=("fixes" if pagina == "verbeteringen" else "plan"),
        volgende_meting_na=timedelta(days=30),
        voorbeeld=voorbeeld,
        proef=proef,
        prijzen={"watch": _prijs_euro("watch"), "fix": _prijs_euro("fix")},
        werkblok=werkblok,
        basis_url=get_base_url().rstrip("/"),
        **dict({"top": []}, **gegevens),
    )


_plaatsen_bezig = {}
# Lukte het plaatsen niet (geen categorie te bepalen, of de kostenrem), dan
# niet elke tien minuten opnieuw en niet steeds "ververs over een paar minuten"
# beloven. Pas na zes uur weer proberen; de nacht pakt hem ook op.
_plaatsen_mislukt = {}


def _plaats_in_ranglijst(webshop_url):
    """Zet een winkel METEEN in de ranglijst van deze maand (1 oktober).

    Nino: "iemand betaalt en ziet een maand niks, dat is niet goed". Klopt. Een
    nieuwe meting is niet nodig: de antwoorden van deze maand zijn bewaard. Komt
    de winkel in zijn categorie, dan rekent herbereken_ranglijst de lijst opnieuw
    uit die antwoorden, met de nieuwe winkel erbij. Nul vragen opnieuw, nul euro
    voor het meten; hooguit een aanroep om de categorie te bepalen. Daarna heeft
    hij binnen een paar minuten zijn plek en zijn verloren vragen.
    Hooguit eens per tien minuten per winkel. Geeft True als hij gestart is."""
    nu = time.time()
    if nu - _plaatsen_bezig.get(webshop_url, 0) < 600:
        return False
    if nu - _plaatsen_mislukt.get(webshop_url, 0) < 6 * 3600:
        return False
    _plaatsen_bezig[webshop_url] = nu

    def werk():
        try:
            import categoriemeting
            w = db.get_benadering(webshop_url) or {"webshop_url": webshop_url}
            cat = w.get("categorie")
            if not cat:
                ingedeeld = categorieen.deel_in([dict(w, webshop_url=webshop_url)], voorrang=True)
                # Het model schrijft het adres soms net anders terug (zonder www).
                # Bij een winkel is er maar een antwoord, dus dat nemen we dan.
                cat = ingedeeld.get(webshop_url) or (
                    next(iter(ingedeeld.values())) if len(ingedeeld) == 1 else None)
                if cat:
                    db.zet_categorie(webshop_url, cat)
            if not cat or cat in categorieen.NIET_MEETBAAR:
                _plaatsen_mislukt[webshop_url] = time.time()
                return
            land = (w.get("land") or "").lower() or None
            gemeten = False
            for probeer in categorieen.familie(cat):
                if db.laatste_afgeronde_ronde(probeer):
                    gemeten = True
                    categoriemeting.herbereken_ranglijst(probeer)
                if land and db.laatste_afgeronde_ronde(probeer, land=land):
                    categoriemeting.herbereken_ranglijst(probeer, land=land)
            if not gemeten:
                # 1 oktober, de klantreis nagelopen: is zijn categorie nog nooit
                # gemeten (te weinig winkels voor de openbare index), dan wachtte
                # een betalende klant tot er tien winkels waren. Nu gaat zijn
                # categorie voor in de rij en wordt hij gemeten zodra er geen
                # andere meting loopt (de wachtklok kijkt elke vijf minuten).
                # Op de openbare index komt hij pas bij tien winkels, zoals altijd.
                zet_in_klantmeetrij(cat)
            db.vergeet_onthouden()
            _bewaard_opslag.clear()
            print(f"Plek berekend voor {webshop_url} in {cat}")
            if gemeten:
                _meld_eerste_plek(webshop_url)
        except Exception as e:
            _plaatsen_mislukt[webshop_url] = time.time()
            print(f"Plaatsen in de ranglijst mislukt voor {webshop_url}: {e}")
    threading.Thread(target=werk, daemon=True).start()
    return True


def _meld_eerste_plek(webshop_url):
    """Een keer per klant: "je staat erin, op plek X van Y" (1 oktober).

    De welkomstmail belooft: we mailen je zodra je plek er is. Komt die plek uit
    de antwoorden van deze maand (_plaats_in_ranglijst), dan gaat hier die mail.
    Komt hij uit een meting van zijn categorie, dan doen de gewone berichten na
    de meting dat (meldingen.na_meting). Alleen voor een klant met een adres, en
    hooguit een keer per jaar per winkel, ook als dit vaker wordt aangeroepen."""
    try:
        import klantbeeld
        klant = db.klant_bij_url(webshop_url) or {}
        if not klant.get("email") or not klant.get("klant_token") or klant.get("opgezegd_op"):
            return False
        beeld = klantbeeld.bouw(webshop_url, max_vragen=3)
        if not beeld or not beeld.get("positie"):
            return False
        if not db.claim_moment(f"eerste_plek:{webshop_url}", 365 * 24 * 3600):
            return False
        naam = categorieen.naam_en(beeld["categorie"])
        gemist = beeld.get("gemiste_vragen") or []
        # 8 oktober: bij nul keer genoemd geen "#35 of 69" (een plek op
        # alfabet) maar eerlijk zeggen dat AI je nog niet noemt.
        if beeld.get("nul"):
            tekst = (f"This month, AI did not name your store in any of the "
                     f"{beeld.get('telbaar') or 'measured'} buying questions in {naam}. "
                     f"{beeld.get('genoemde_winkels')} of {beeld['van']} stores in your category were named. "
                     f"That is your starting point, and from here your dashboard shows every step up.")
        else:
            tekst = (f"Your store is in the Krillo Index: #{beeld['positie']} of {beeld['van']} in {naam}, "
                     f"from this month's measurement.")
        if gemist:
            v = gemist[0]
            anderen = ", ".join((v.get("concurrenten") or [])[:2])
            tekst += (f"\n\nOne question you lose: \u201c{v['vraag']}\u201d"
                      + (f" AI names {anderen} there." if anderen else ""))
        tekst += "\n\nYour dashboard shows every question, who AI names instead, and what to do first."
        return emailing.send_vermeldingen_update(
            klant["email"], webshop_url, tekst,
            monitoring_url=f"{get_base_url().rstrip('/')}/mijn/{klant['klant_token']}",
            onderwerp=("Your rank is in: AI does not name you yet" if beeld.get("nul")
                       else f"Your rank in the Krillo Index: #{beeld['positie']}"), kop="Your rank is in",
            intro=f"From this month's measurement of {naam}, with ChatGPT and Gemini.",
            feiten=[("Category", naam),
                    ("Your place", "Not named yet" if beeld.get("nul") else f"#{beeld['positie']} of {beeld['van']}"),
                    ("Questions where AI names you", f"{beeld.get('genoemd') or 0} of {beeld.get('telbaar') or 0}"),
                    ("Stores AI names", f"{beeld.get('genoemde_winkels')} of {beeld['van']}")])
    except Exception as e:
        print(f"Mail eerste plek mislukt voor {webshop_url}: {e}")
        return False


KLANTMEETRIJ = "klantmeetrij"


def zet_in_klantmeetrij(categorie):
    """Een categorie van een betalende klant die nog nooit gemeten is: voor in de rij."""
    try:
        rij = json.loads(db.get_instelling(KLANTMEETRIJ) or "[]")
    except Exception:
        rij = []
    if categorie and categorie not in rij:
        rij.append(categorie)
        db.zet_instelling(KLANTMEETRIJ, json.dumps(rij))
    return rij


def _klantmeetrij():
    try:
        rij = json.loads(db.get_instelling(KLANTMEETRIJ) or "[]")
        return rij if isinstance(rij, list) else []
    except Exception:
        return []


def _meet_klantcategorie(nu=None):
    """Voor de wachtklok: de eerste categorie uit de klantmeetrij meten, als er
    geen andere meting of nachtwerk loopt. Geeft de gestarte categorie of None."""
    import categoriemeting
    rij = _klantmeetrij()
    if not rij or onderhoud._stand.get("bezig") or categoriemeting.stand().get("bezig"):
        return None
    cat = rij[0]
    if db.laatste_afgeronde_ronde(cat):
        # Intussen gemeten (bijvoorbeeld door de nacht): uit de rij, niets te doen.
        db.zet_instelling(KLANTMEETRIJ, json.dumps(rij[1:]))
        return None
    def _berichten(uitkomst):
        # Dezelfde berichten als na een nachtmeting: de klant hoort zijn plek.
        import meldingen
        meldingen.na_meting(uitkomst["ronde"], cat, verstuur=True, basis=get_base_url())
        db.vergeet_onthouden()
        _bewaard_opslag.clear()

    if not categoriemeting.start_meting(cat, na=_berichten):
        return None
    db.zet_instelling(KLANTMEETRIJ, json.dumps(rij[1:]))
    print(f"Klantmeetrij: {cat} wordt nu gemeten voor een betalende klant.")
    return cat


def _sitecheck(webshop_url, klant_token, taal):
    """De pagina Site check (stap 316): score, verloop en de dertien punten,
    in de taal van het dashboard, binnen het dashboard."""
    try:
        rapporten = db.get_klant_rapporten(klant_token, limit=8) or []
    except Exception as e:
        print(f"Sitecheck ophalen mislukt voor {webshop_url}: {e}")
        rapporten = []
    if not rapporten:
        return {"leeg": True}
    laatste = rapporten[0]
    checks = laatste.get("checks") or []
    if isinstance(checks, str):
        checks = json.loads(checks)
    if taal != "nl":
        import checktaal
        checks = checktaal.naar_het_engels({"checks": checks})["checks"]
    namen = ({"toegang": "Access", "leesbaarheid": "Readability", "structuur": "Structure",
              "inhoud": "Content"} if taal != "nl" else
             {"toegang": "Toegang", "leesbaarheid": "Leesbaarheid", "structuur": "Structuur", "inhoud": "Inhoud"})
    groepen = {}
    for c in checks:
        groepen.setdefault(namen.get(c.get("categorie"), c.get("categorie") or "Other"), []).append(c)
    # Wat eerst: problemen boven, goed onder, per groep.
    volgorde = {"probleem": 0, "deels": 1, "onbekend": 2, "ok": 3, "goed": 3}
    for g in groepen.values():
        g.sort(key=lambda c: volgorde.get(c.get("status"), 1))
    verloop = [{"score": r.get("score"), "op": r.get("aangemaakt_op")} for r in reversed(rapporten)]
    return {"score": laatste.get("score"), "op": laatste.get("aangemaakt_op"), "groepen": groepen,
            "verloop": verloop, "goed": sum(1 for c in checks if c.get("status") in ("ok", "goed")),
            "totaal": len(checks), "pdf": f"/mijn/{klant_token}/checks.pdf"}


def _canvas_gegevens(webshop_url, beeld, pagina, links, taal, klant_token, proef, werkblok, gegevens):
    """De gegevens voor het dashboard in de vorm van het canvas (8 oktober, versie 10).

    Alleen de bedrading: de zijbalk met groepen en badges, en per pagina wat het
    sjabloon extra nodig heeft (overzicht: samenvatting, Why you lose, What to do
    now, bronnen, doelkaart; Why you lose: de vraag met antwoorden, winnaar,
    bronnen en acties). De logica zelf staat in dashboardcanvas.py en
    waaromverlies.py. Een fout hier mag het dashboard nooit breken."""
    import dashboardcanvas as dc
    import dashboardpaginas as dp
    import waaromverlies as wv
    uit = {}
    gekozen = gegevens.get("gekozen") or []
    sitescore = None
    if klant_token and not proef:
        try:
            rap = db.get_klant_rapporten(klant_token, limit=1) or []
            sitescore = rap[0].get("score") if rap else None
        except Exception:
            sitescore = None
    uit["menu"] = dc.menu(links, dc.badges(beeld, gekozen, sitescore, taal), taal)
    uit["gids_zij"] = dc.gids_regel(gegevens.get("gids"), taal)
    if not beeld or pagina not in ("overzicht", "waarom"):
        return uit
    waarom_href = next((l["href"] for l in links if l["naam"] == "waarom"), None)
    uit["waarom_href"] = waarom_href
    mijn = bool(klant_token and not proef)
    try:
        rijen = (_ranglijst_bewaard(beeld["categorie"], beeld.get("land")) or {}).get("rijen") or []
    except Exception:
        rijen = []
    eigen_checks = wv.klant_checks(klant_token) if mijn else None
    paginas = None
    if mijn:
        try:
            import paginacheck
            paginas = (paginacheck.laatste(webshop_url) or {}).get("paginas")
        except Exception:
            paginas = None
    if pagina == "overzicht":
        vr = gegevens.get("vragen") or {}
        uit["samenvatting"] = dc.samenvatting(beeld, vr, taal)
        uit["bronnen_donut"] = dc.bronnen_donut(_bronnen_van_ronde(beeld["ronde"]), taal)
        verloren = wv.verloren_vragen(vr)
        uit["acties_nu"] = dc.acties_nu(verloren, gekozen, werkblok, taal, href_waarom=waarom_href)
        if verloren:
            q = verloren[0]
            kaart = {"vraag": q["vraag"], "winnaar": wv.winnaar_naam(q), "redenen": [], "geladen": False,
                     "href": f"{waarom_href}{'&' if '?' in waarom_href else '?'}vraag={quote(q['vraag'])}"}
            url = wv.winnaar_url(kaart["winnaar"], rijen)
            cache = wv.lees_cache(url) if (url and eigen_checks) else None
            if cache:
                onderwerp, ontbreekt = wv.pagina_ontbreekt(q["vraag"], paginas)
                rij = wv.vergelijk(cache["checks"], eigen_checks["checks"], taal)
                kaart["redenen"] = wv.redenen(rij, kaart["winnaar"], onderwerp, ontbreekt, taal)[:4]
                kaart["geladen"] = True
            uit["waarom_kaart"] = kaart
        eigen = gegevens.get("eigen") or {}
        uit["doelen"] = dc.doelen(vr, gekozen, eigen.get("lijst") or [], taal, waarom_href, rijen,
                                  eigen_checks["checks"] if eigen_checks else None, paginas) if mijn else []
        uit["doel_voorstellen"] = dc.voorstellen(vr, gekozen)
        return uit
    # pagina == "waarom"
    try:
        vo = dp.vragen_overzicht(beeld["ronde"], webshop_url, beeld.get("naam"))
    except Exception as e:
        print(f"Vragen voor Why you lose mislukt voor {webshop_url}: {e}")
        return uit
    if mijn:
        vo = _zonder_niet_voor_mij(vo, set(_niet_voor_mij(webshop_url)))
    if proef:
        # In de voorproef zijn alleen de eerste vragen open; de rest laten we niet eens zien.
        vo = dict(vo, vragen=vo["vragen"][:dp.PROEF_OPEN_VRAGEN])
    eigen_lijst = []
    if mijn:
        try:
            import eigenvragen
            eigen_lijst = eigenvragen.overzicht(webshop_url)
        except Exception:
            eigen_lijst = []
    v = wv.kies_vraag(vo, request.args.get("vraag"), eigen_lijst)
    uit["waarom_vragen"] = [{"vraag": q["vraag"], "gewonnen": q.get("gewonnen"), "eigen": False,
                             "href": f"{waarom_href}{'&' if '?' in waarom_href else '?'}vraag={quote(q['vraag'])}"}
                            for q in vo.get("vragen", [])[:8]]
    uit["waarom_vragen"] += [{"vraag": e["vraag"], "gewonnen": False, "eigen": True,
                              "href": f"{waarom_href}{'&' if '?' in waarom_href else '?'}vraag={quote(e['vraag'])}"}
                             for e in eigen_lijst]
    if not v:
        return uit
    try:
        antwoord_rijen = db.antwoorden_met_tekst_van_ronde(beeld["ronde"]) if not v.get("eigen") else []
        w = wv.pagina_gegevens(v, antwoord_rijen, rijen, beeld.get("naam") or webshop_url, webshop_url, gekozen, taal,
                               sitetaal.landnaam(beeld.get("land"), taal) if beeld.get("land") else None,
                               paginas, dp.assistent_naam, dp.zonder_opmaak)
        w["verloren_aantal"] = vo.get("verloren")
        w["totaal"] = vo.get("totaal")
        if mijn:
            w["vergelijk_url"] = f"/mijn/{klant_token}/waarom/vergelijk?vraag={quote(v['vraag'])}" + (
                f"&taal={taal}" if request.args.get("taal") else "")
            w["kies_url"] = f"/mijn/{klant_token}/kies" if (werkblok and not werkblok.get("opgezegd")) else None
        w["eigen_check_er"] = bool(eigen_checks)
        uit["waarom"] = w
    except Exception as e:
        print(f"Pagina Why you lose mislukt voor {webshop_url}: {e}")
    return uit


GIDS_WEG = "gids_weg:"
EERSTE_WIJZIGING = "eerste_wijziging:"


def _eerste_maand(webshop_url, klant_token, beeld, taal, pakket=None, gekozen=None):
    """De gids "Your first month with Krillo" op het overzicht (8 oktober).

    Nino: "iemand komt op het dashboard, maar wat dan? Er is geen stappenplan,
    geen uitleg hoe lang iets duurt." De startpagina doet dat tot er een plek
    is; daarna stond er niets. Stripe, Shopify en Peec zetten bovenaan een
    korte lijst met wat je eerst doet, hoe lang het duurt en een vinkje als
    het klaar is. Hier hetzelfde, en elk vinkje komt uit de database. De klant
    kan de gids wegklikken; als alles klaar is verdwijnt hij vanzelf."""
    nl = taal == "nl"
    if db.get_instelling(GIDS_WEG + webshop_url):
        return None
    fix = (pakket or "").lower() not in ("watch", "")
    try:
        import pixel
        verbonden = bool((pixel.status(webshop_url) or {}).get("verbonden"))
    except Exception:
        verbonden = False
    gekozen = gekozen if gekozen is not None else (db.gekozen_vragen(webshop_url) or [])
    gewijzigd = bool(db.get_instelling(EERSTE_WIJZIGING + webshop_url))
    if fix and not gewijzigd:
        try:
            gewijzigd = bool(db.get_wijzigingen(webshop_url))
        except Exception:
            pass
    dag = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][meetdag(webshop_url)]
    gemeten = beeld.get("gemeten_op")
    volgende = (gemeten + timedelta(days=30)).strftime("%-d %B") if hasattr(gemeten, "strftime") else None
    stappen = [
        {"titel": "Je stand is gemeten" if nl else "Your standing is measured", "tijd": "",
         "tekst": ("Je plek, en bij welke koopvragen AI een ander noemt." if nl else
                   "Your rank, and the buying questions where AI names someone else."), "klaar": True},
        {"titel": "Kies tot drie vragen om te winnen" if nl else "Pick up to three questions to win",
         "tijd": "2 min", "klaar": bool(gekozen), "link": "vragen",
         "tekst": ("Open een vraag hieronder en klik op Add to my fixes. Begin met vragen waar weinig winkels genoemd worden." if nl else
                   "Open a question below and click Add to my fixes. Start with questions where few stores are named.")},
        {"titel": "Koppel je verkoop" if nl else "Connect your sales", "tijd": "2 min", "klaar": verbonden,
         "link": "pixel",
         "tekst": ("Dan zie je wat AI je oplevert in bezoek, bestellingen en omzet." if nl else
                   "Then you see what AI brings you in visits, orders and revenue.")},
        {"titel": ("Wij zetten je eerste fix live" if fix else "Zet je eerste fix live") if nl else
                  ("We put your first fix live" if fix else "Put your first fix live"),
         "tijd": "" if fix else ("30 min" if nl else "30 min"), "klaar": gewijzigd, "link": "fixes",
         "tekst": (("Na je toegang doen wij het; je ziet elke wijziging op Fixes." if nl else
                    "Once you give access, we do it; every change shows on Fixes.") if fix else
                   ("Op Fixes staat de tekst klaar om te kopieren en waar hij komt. Klaar? Vink het hier af." if nl else
                    "Fixes has the text ready to copy and where it goes. Done? Tick it off here.")),
         "afvinken": not fix and not gewijzigd},
        {"titel": "Zie het effect" if nl else "See the effect", "tijd": "", "klaar": False, "info": True,
         "tekst": ((f"Elke {dag} stellen we je vijf belangrijkste vragen opnieuw. AI pikt een wijziging meestal "
                    f"binnen een paar dagen tot een paar weken op. Je nieuwe plek in de index: rond {volgende}.") if nl else
                   (f"Every {dag} we ask your five key questions again. AI usually picks up a change within days "
                    f"to a few weeks. Your new rank in the index: around {volgende}."))},
    ]
    taken = [s for s in stappen if not s.get("info")]
    klaar = sum(1 for s in taken if s["klaar"])
    if klaar == len(taken):
        return None
    return {"stappen": stappen, "klaar": klaar, "totaal": len(taken),
            "weg_url": f"/mijn/{klant_token}/gids", "afvink_url": f"/mijn/{klant_token}/gids"}


@app.route("/mijn/<klant_token>/gids", methods=["POST"])
def gids_bewaren(klant_token):
    """De gids wegklikken, of "eerste fix live" afvinken (8 oktober)."""
    klant = db.get_klant(klant_token)
    if not klant:
        return jsonify({"ok": False}), 404
    wat = (request.get_json(silent=True) or {}).get("wat")
    if wat == "weg":
        db.zet_instelling(GIDS_WEG + klant["webshop_url"], datetime.now(timezone.utc).isoformat())
    elif wat == "gedaan":
        db.zet_instelling(EERSTE_WIJZIGING + klant["webshop_url"], datetime.now(timezone.utc).isoformat())
    else:
        return jsonify({"ok": False}), 400
    return jsonify({"ok": True})


def _geen_plek_reden_voor_categorie(cat, land):
    """Hoe ver een categorie is: hoeveel winkels we kennen, hoeveel nodig, en of
    hij nu voor een klant gemeten wordt (8 oktober)."""
    import categoriemeting
    aantal = (db.winkels_per_categorie_in_land((land or "nl").lower()) or {}).get(cat, 0)
    st = categoriemeting.stand()
    return {"aantal": aantal, "nodig": categorieen.MINIMUM_VOOR_INDEX,
            "wordt_gemeten": bool(cat in _klantmeetrij() or (st.get("bezig") and st.get("categorie") == cat))}


def _geen_plek_reden(webshop_url):
    """Waarom een winkel (nog) geen plek heeft, in een zin die klopt (1 oktober).

    Nino zag bij Loods 5 "Your category has not been measured yet", terwijl
    meubels wel gemeten is. Er zijn drie verschillende redenen, elk met een
    ander verhaal: geen categorie, wel een categorie maar die is nog niet
    gemeten, of de categorie is gemeten maar deze winkel zat er toen nog niet in."""
    try:
        winkel = db.winkel_kort(webshop_url) or {}
        cat = winkel.get("categorie")
        if not cat or cat in categorieen.NIET_MEETBAAR:
            return {"soort": "geen_categorie"}
        naam = categorieen.naam_en(cat)
        for probeer in categorieen.familie(cat):
            lijst = db.ranglijst_per_land(probeer, (winkel.get("land") or "").lower() or None, limiet=5)
            if lijst and lijst.get("ronde"):
                rij = (lijst.get("rijen") or [{}])[0]
                gemeten = rij.get("gemeten_op")
                return {"soort": "niet_in_meting", "categorie": naam,
                        "gemeten": gemeten.strftime("%-d %B") if hasattr(gemeten, "strftime") else None,
                        "volgende": (gemeten + timedelta(days=30)).strftime("%-d %B")
                        if hasattr(gemeten, "strftime") else None}
        aantal = (db.winkels_per_categorie_in_land((winkel.get("land") or "nl").lower()) or {}).get(cat, 0)
        import categoriemeting
        st = categoriemeting.stand()
        wordt_gemeten = (cat in _klantmeetrij()) or (st.get("bezig") and st.get("categorie") == cat)
        return {"soort": "niet_gemeten", "categorie": naam, "aantal": aantal,
                "nodig": categorieen.MINIMUM_VOOR_INDEX, "wordt_gemeten": bool(wordt_gemeten)}
    except Exception as e:
        print(f"Reden zonder plek mislukt voor {webshop_url}: {e}")
        return {"soort": "onbekend"}


_wachtwoord_gekeken = {}


def _wachtwoord_nu(webshop_url, klant=None):
    """Staat de winkel achter een wachtwoord? Een snelle controle hooguit eens
    per zes uur per winkel (een verzoek, geen scan), anders wat de laatste scan
    onthield. Alleen voor de startpagina van een klant zonder plek."""
    nu = time.time()
    if nu - _wachtwoord_gekeken.get(webshop_url, 0) > 6 * 3600:
        _wachtwoord_gekeken[webshop_url] = nu
        was_dicht = scan_engine.staat_achter_wachtwoord(webshop_url)
        uitkomst = scan_engine.controleer_wachtwoord_nu(webshop_url)
        if uitkomst is False and was_dicht:
            # Net open gegaan: de laatste scan ging over de wachtwoordpagina.
            # Meteen opnieuw scannen, niet een week wachten.
            _herscan_op_achtergrond(webshop_url, klant or {})
        if uitkomst is not None:
            return uitkomst
    return scan_engine.staat_achter_wachtwoord(webshop_url)


def _meld_winkel_open(webshop_url, email, klant_token, score):
    """De winkel stond achter een wachtwoord en is nu open (8 oktober): de klant
    een mail met zijn eerste echte sitecheck. Een keer per winkel per maand."""
    try:
        if not email or not klant_token or not db.claim_moment(f"winkel_open:{webshop_url}", 30 * 24 * 3600):
            return False
        tekst = (f"Your store is open, so AI can read it now, and so can we. Your first real site check "
                 f"scores {score} of 100. We are writing your fixes for your own pages now; they are in "
                 f"your dashboard within the hour.")
        return emailing.send_vermeldingen_update(
            email, webshop_url, tekst,
            monitoring_url=f"{get_base_url().rstrip('/')}/mijn/{klant_token}",
            onderwerp="Your store is open: your first site check is in", kop="Your store is open")
    except Exception as e:
        print(f"Mail winkel open mislukt voor {webshop_url}: {e}")
        return False


def _herscan_op_achtergrond(webshop_url, klant):
    """Een nieuwe sitecheck voor een klant, los van het verzoek. Kost niets
    behalve een paar verzoeken aan zijn eigen winkel."""
    def werk():
        try:
            uitslag = run_scan(webshop_url)
            if "error" in uitslag:
                return
            db.save_report("monitoring", webshop_url, klant.get("email"), uitslag.get("score", 0),
                           uitslag.get("checks", []), None, None, klant.get("klant_token"))
            _meld_winkel_open(webshop_url, klant.get("email"), klant.get("klant_token"), uitslag.get("score", 0))
            # En meteen de fixes over de echte winkel laten schrijven.
            _oplossingen_bezig[webshop_url] = True
            try:
                _maak_taakoplossingen(webshop_url, _klantgegevens(webshop_url)["actieplan"])
            finally:
                _oplossingen_bezig.pop(webshop_url, None)
        except Exception as e:
            print(f"Herscan mislukt voor {webshop_url}: {e}")
    threading.Thread(target=werk, daemon=True).start()


def _categoriekeuzes():
    """Alle meetbare categorieen voor de kiezer, op Engelse naam gesorteerd."""
    return sorted(({"slug": s, "naam": categorieen.naam_en(s)} for s in categorieen.GELDIG
                   if s not in categorieen.NIET_MEETBAAR), key=lambda c: c["naam"])


def _startstappen(webshop_url, klant_token, geen_plek, taal, pakket=None, wachtwoord=False):
    """De startpagina van een klant die nog geen plek heeft (8 oktober).

    WAAROM. Nino betaalde als test en zag een overzicht met een kaartje en een
    zin, verder leeg. Zo voelt het alsof er niets gebeurt, terwijl er wel van
    alles loopt. Peec, Profound, Stripe en Shopify lossen dit op dezelfde manier
    op: een lijst van een paar stappen met een vinkje bij wat klaar is, wat nu
    loopt, en wat de klant zelf kan doen. Dus hier precies dat, met alleen wat
    echt waar is: elk vinkje komt uit de database, niet uit een belofte.
    Geeft een lijst stappen met status klaar, bezig, wacht, actie of let_op."""
    nl = taal == "nl"
    soort = (geen_plek or {}).get("soort")
    stappen = []
    pakketnaam = "Fix" if (pakket or "").lower() == "fix" else "Watch"
    stappen.append({"sleutel": "plan", "status": "klaar",
                    "titel": (f"{pakketnaam} staat aan" if nl else f"{pakketnaam} is active"),
                    "tekst": ("Je betaling is binnen en je dashboard is van jou." if nl else
                              "Your payment is in and this dashboard is yours.")})
    # De sitecheck: de dertien punten uit de laatste scan.
    score = None
    try:
        rapporten = db.get_klant_rapporten(klant_token, limit=1) if klant_token else []
        score = rapporten[0].get("score") if rapporten else None
    except Exception:
        pass
    if wachtwoord:
        stappen.append({"sleutel": "site", "status": "let_op",
                        "titel": "Je winkel staat achter een wachtwoord" if nl else "Your store is behind a password",
                        "tekst": ("AI kan hem daardoor niet lezen, en wij ook niet. Haal het wachtwoord weg "
                                  "(in Shopify: Online winkel, Voorkeuren) en we kijken binnen een dag opnieuw." if nl else
                                  "So AI cannot read it, and neither can we. Remove the password "
                                  "(in Shopify: Online Store, Preferences) and we check again within a day. "
                                  "A Shopify development store keeps its password until you pick a plan.")})
    elif score is not None:
        stappen.append({"sleutel": "site", "status": "klaar",
                        "titel": (f"Sitecheck: {score} van 100" if nl else f"Site check: {score} of 100"),
                        "tekst": ("Hoe goed AI je winkel kan lezen. Elke week opnieuw." if nl else
                                  "How well AI can read your store. Checked again every week.")})
    else:
        stappen.append({"sleutel": "site", "status": "bezig",
                        "titel": "Sitecheck" if nl else "Site check",
                        "tekst": ("Loopt. Meestal binnen een paar minuten klaar." if nl else
                                  "Running. Usually done within a few minutes.")})
    # De categorie: kiezen kan altijd, ook als we hem zelf al bepaalden.
    verzoek = None
    try:
        ruw = db.get_instelling(CATEGORIEVERZOEK + scan_engine.normalize_url(webshop_url))
        verzoek = json.loads(ruw) if ruw else None
    except Exception:
        verzoek = None
    if verzoek and soort in ("geen_categorie", "onbekend", None):
        stappen.append({"sleutel": "categorie", "status": "bezig",
                        "titel": "We zetten een categorie voor je klaar" if nl else "We are setting up a category for you",
                        "tekst": (f"Je schreef: \u201c{verzoek.get('wat')}\u201d. Binnen een werkdag hoor je van ons "
                                  "wat er gebeurt." if nl else
                                  f"You wrote: \u201c{verzoek.get('wat')}\u201d. Within one working day we email you "
                                  "what happens next."), "wijzig": True})
    elif soort in ("geen_categorie", "onbekend", None):
        stappen.append({"sleutel": "categorie", "status": "actie",
                        "titel": "Kies je categorie" if nl else "Choose your category",
                        "tekst": ("Wat verkoop je vooral? Daarmee vergelijken we je met de winkels die AI "
                                  "noemt voor dezelfde koopvragen." if nl else
                                  "What do you mainly sell? We compare you with the stores AI names "
                                  "for the same buying questions.")})
    else:
        stappen.append({"sleutel": "categorie", "status": "klaar",
                        "titel": (f"Categorie: {geen_plek.get('categorie')}" if nl else
                                  f"Category: {geen_plek.get('categorie')}"),
                        "tekst": "", "wijzig": True})
    # De plek in de index.
    if soort in ("geen_categorie", "onbekend", None):
        status, tekst = "wacht", ("Zodra je categorie gekozen is." if nl else "As soon as your category is set.")
    elif geen_plek.get("bezig") or soort == "niet_in_meting":
        status, tekst = "bezig", ("We rekenen je plek uit de antwoorden van deze maand. Een paar minuten." if nl else
                                  "We are working out your rank from this month's answers. A few minutes.")
    elif geen_plek.get("wordt_gemeten"):
        status, tekst = "bezig", ("We meten je categorie nu voor je. Meestal binnen het uur; je krijgt een mail." if nl else
                                  "We are measuring your category for you now. Usually within the hour; we email you.")
    else:
        status, tekst = "wacht", (f"We meten vanaf {geen_plek.get('nodig')} winkels en kennen er nu "
                                  f"{geen_plek.get('aantal')}. We zoeken elke nacht bij en mailen je zodra het zover is." if nl else
                                  f"We measure from {geen_plek.get('nodig')} stores and know {geen_plek.get('aantal')} now. "
                                  "We add stores every night and email you when it is ready.")
    stappen.append({"sleutel": "plek", "status": status,
                    "titel": "Je plek in de index" if nl else "Your rank in the index", "tekst": tekst})
    stappen.append({"sleutel": "fixes", "status": "wacht",
                    "titel": "Je eerste fixes" if nl else "Your first fixes",
                    "tekst": ("Per koopvraag waar AI een ander noemt: wat je verandert en waar. Komen met je plek." if nl else
                              "For each buying question where AI names someone else: what to change and where. "
                              "They arrive with your rank.")})
    verbonden = False
    try:
        import pixel
        verbonden = bool((pixel.status(webshop_url) or {}).get("verbonden"))
    except Exception:
        pass
    stappen.append({"sleutel": "pixel", "status": "klaar" if verbonden else "actie",
                    "titel": ("Verkoop gekoppeld" if verbonden else "Koppel je verkoop (2 minuten)") if nl else
                             ("Sales connected" if verbonden else "Connect your sales (2 minutes)"),
                    "tekst": ("" if verbonden else
                              ("Dan zie je wat AI je oplevert aan bezoek, bestellingen en omzet." if nl else
                               "Then you see what AI brings you in visits, orders and revenue."))})
    klaar = sum(1 for s in stappen if s["status"] == "klaar")
    return {"stappen": stappen, "klaar": klaar, "totaal": len(stappen)}


def _doorverwijzing_voor(webshop_url, pagina, werkblok, proef):
    """Stap 94: de eigen link voor de pagina Abonnement. Alleen voor een echte,
    betalende klant (niet op de demo of een proefpagina). Lukt het niet, dan
    gewoon geen blok: nooit het dashboard breken om een link."""
    if pagina != "abonnement" or not werkblok or proef:
        return None
    try:
        klant = db.klant_bij_url(webshop_url) or {}
        if not klant or klant.get("is_test") or klant.get("opgezegd_op"):
            return None
        import doorverwijzen
        return doorverwijzen.voor_klant(webshop_url)
    except Exception as e:
        print(f"Doorverwijslink voor het dashboard mislukt: {e}")
        return None


def _prijs_euro(pakket):
    try:
        return int(float(payments.PAKKETTEN[pakket]["prijs"]["value"]))
    except Exception:
        return None


def _plan_uitleg(webshop_url, werkblok, taal="en"):
    """Wat er in het pakket van deze klant zit, voor de pagina Abonnement.

    Watch en Fix zijn verschillende producten, en de klant moet op zijn eigen
    pagina kunnen lezen wat HIJ gekocht heeft, niet een algemene prijslijst."""
    en = taal != "nl"
    klant = db.klant_bij_url(webshop_url) or {}
    pakket = (klant.get("pakket") or "").lower()
    via_shopify = bool(werkblok and werkblok.get("shopify_beheer"))
    if pakket == "watch":
        naam = "Watch"
        punten = (["Your rank in the index every month, in your category and country",
                   "Every buying question you lose, with the store named instead",
                   "Every week your five key questions checked again",
                   "Every fix written out, ready to copy into your store yourself",
                   "Cancel any time, from this page"] if en else
                  ["Elke maand je plek in de index, in je categorie en land",
                   "Elke koopvraag die je verliest, met de winkel die wel genoemd werd",
                   "Elke week je vijf belangrijkste vragen opnieuw gemeten",
                   "Elke verbetering uitgeschreven, klaar om zelf over te nemen",
                   "Elke maand opzegbaar, vanaf deze pagina"])
    elif pakket:
        naam = "Fix"
        punten = (["Everything in Watch",
                   "We write every change and put it in your store for you",
                   "Every change listed with the old text, and every change can be undone",
                   "At the next monthly measurement you see the difference"] if en else
                  ["Alles van Watch",
                   "Wij schrijven elke wijziging en zetten hem in je winkel",
                   "Elke wijziging staat erbij met de oude tekst, en alles kan terug",
                   "Bij de volgende maandmeting zie je het verschil"])
    else:
        # 1 oktober: hier stond "Krillo" als pakketnaam. Dat zag Nino in de
        # beheerweergave van een winkel die (nog) geen klant is. Een echte klant
        # heeft altijd Watch of Fix; zonder pakket zeggen we dat gewoon.
        naam = "No plan yet" if en else "Nog geen pakket"
        punten = (["This is a preview of the dashboard. A customer sees Watch or Fix here."] if en else
                  ["Dit is een voorbeeld van het dashboard. Een klant ziet hier Watch of Fix."])
    if via_shopify:
        betaling = ("You pay through your Shopify invoice. You change or cancel your plan in "
                    "Shopify, under the Krillo app." if en else
                    "Je betaalt via je Shopify-factuur. Wijzigen of opzeggen doe je in Shopify, bij de app.")
    elif klant.get("aangemaakt_op"):
        begon = klant["aangemaakt_op"].strftime("%d-%m-%Y")
        if klant.get("periode") == "jaar":
            betaling = (f"Customer since {begon}. You pay yearly, in advance, through Mollie (two "
                        f"months free); every payment gets an invoice by email." if en else
                        f"Klant sinds {begon}. Je betaalt per jaar vooruit via Mollie (twee maanden "
                        f"gratis); bij elke betaling krijg je een factuur per mail.")
            punten = [p.replace("Cancel any time, from this page",
                                "Cancel any time from this page; it then does not renew")
                      .replace("Elke maand opzegbaar, vanaf deze pagina",
                               "Opzegbaar vanaf deze pagina; het jaar verlengt dan niet")
                      for p in punten]
        elif klant.get("gratis_tot") and klant["gratis_tot"] >= datetime.now().date():
            # Stap 167: tijdens de gratis proef.
            tot = klant["gratis_tot"].strftime("%d-%m-%Y")
            betaling = (f"Free trial until {tot}. After that Watch is EUR 49 a month by direct debit through "
                        f"Mollie. Cancel before {tot} on this page and you pay nothing." if en else
                        f"Gratis proef tot {tot}. Daarna is Watch 49 euro per maand via Mollie. Zeg je voor "
                        f"{tot} op via deze pagina, dan betaal je niets.")
        else:
            betaling = (f"Customer since {begon}. You pay monthly by direct debit through Mollie; "
                        f"every payment gets an invoice by email." if en else
                        f"Klant sinds {begon}. Je betaalt maandelijks via Mollie; bij elke betaling "
                        f"krijg je een factuur per mail.")
    else:
        betaling = ""
    return {"naam": naam, "punten": punten, "betaling": betaling}


def _buiten_markt(webshop_url):
    """Verkoopt deze winkel buiten de landen die de index meet? Dan krijgt hij geen
    plek in de index, en mag het dashboard niet beloven dat die komt."""
    try:
        import markten
        profiel = db.get_winkelprofiel(webshop_url) or {}
        return not markten.in_index(profiel.get("land"))
    except Exception:
        return False


def _abonnement_stand(webshop_url, rapporten=None):
    """(loopt er een abonnement, doen wij het werk) voor het klantscherm.

    SINDS 23 SEPTEMBER uit de klantregel, niet meer uit "is er ooit een
    maandrapport gemaakt". Dat laatste bleef waar na opzeggen, dus een klant
    die opzegde zag nog steeds "je betaalt per maand" met een opzegknop. En
    Watch-klanten lazen "wij voeren dit voor je uit", terwijl Watch betekent:
    zelf doen. Het pakket staat nu bij de klant (Mollie bij de eerste
    betaling, Shopify bij elk lopend abonnement)."""
    klant = db.klant_bij_url(webshop_url) or {}
    if not klant or _toegang_voorbij(klant):
        return False, False
    # (Of hij opzegde vraag je met _is_opgezegd hieronder.)
    pakket = (klant.get("pakket") or "").lower()
    heeft_rapport = any((r.get("type") or "") == "monitoring" for r in (rapporten or []))
    abonnement = bool(pakket) or heeft_rapport
    return abonnement, bool(pakket) and pakket != "watch"


def _toegang_voorbij(klant):
    """Of de betaalde periode van een opgezegde klant voorbij is.

    opgezegd_op is sinds 27 september het moment waarop de toegang stopt; dat
    kan in de toekomst liggen (einde van de betaalde maand)."""
    eind = klant.get("opgezegd_op")
    if not eind:
        return False
    try:
        if eind.tzinfo is None:
            eind = eind.replace(tzinfo=timezone.utc)
        return eind <= datetime.now(timezone.utc)
    except Exception:
        return True


def _einde_betaalde_maand(begon, nu=None, maanden=1):
    """Het einde van de lopende betaalde periode, gerekend vanaf de eerste betaling.

    Een klant die op de 10e begon, betaalt elke 10e; zegt hij op de 25e op, dan
    loopt zijn toegang tot de 10e van de volgende maand. Met maanden=12 (een
    jaarabonnement, stap 106) tot dezelfde dag na een heel betaald jaar."""
    nu = nu or datetime.now(timezone.utc)
    if not begon:
        return nu
    if begon.tzinfo is None:
        begon = begon.replace(tzinfo=timezone.utc)
    jaar, maand = begon.year, begon.month
    while True:
        maand += max(1, int(maanden))
        while maand > 12:
            jaar, maand = jaar + 1, maand - 12
        # Een maand zonder die dag (31 februari): de laatste dag van die maand.
        dag = begon.day
        while True:
            try:
                kandidaat = begon.replace(year=jaar, month=maand, day=dag)
                break
            except ValueError:
                dag -= 1
        if kandidaat > nu:
            return kandidaat


def _is_opgezegd(webshop_url):
    """Of deze klant opzegde (klanten.opgezegd_op), voor de tekst onderaan."""
    return bool((db.klant_bij_url(webshop_url) or {}).get("opgezegd_op"))


def _werkblok(webshop_url, taal, klant_token=None, beheer=None):
    """Alles wat het werkblok van templates/_werk.html nodig heeft.

    Op een plek, zodat een klant en de beheerweergave nooit iets anders zien.
    De taal is die van het dashboard (een adres, een taal), niet die van het
    domein van de winkel: op een Engelse site hoort een Engels werkblok."""
    rapporten = (db.get_klant_rapporten(klant_token) if klant_token
                 else db.get_rapporten_voor_webshop(webshop_url)) or []
    gegevens = _klantgegevens(webshop_url)
    pagina = _paginagegevens(webshop_url)
    return {
        "wt": paginataal.teksten(taal),
        "uitvoering": _laatste_uitvoering(webshop_url),
        "wijzigingen": db.get_wijzigingen(webshop_url),
        "actieplan": gegevens["actieplan"],
        "laatste": rapporten[0] if rapporten else None,
        "verloop": list(reversed(rapporten))[-8:],
        # Loopt er echt een abonnement? Wie alleen een eenmalige opdracht had,
        # las vroeger "je betaalt per maand" met een opzegknop eronder. Dat is
        # een onjuiste mededeling over een betalingsverplichting.
        "abonnement": _abonnement_stand(webshop_url, rapporten)[0],
        "doet_werk": _abonnement_stand(webshop_url, rapporten)[1],
        "opgezegd": _is_opgezegd(webshop_url),
        # 27 september: einddatum na opzeggen, en of die al voorbij is.
        "opgezegd_tot": (db.klant_bij_url(webshop_url) or {}).get("opgezegd_op"),
        "afgelopen": _toegang_voorbij(db.klant_bij_url(webshop_url) or {}),
        # Doet de Shopify-app het werk zelf? Dan geen "wachten op toegang".
        "shopify_winkel": bool((db.shopify_winkel_bij_webadres(webshop_url) or {}).get("toegangssleutel")),
        "shopify_beheer": pagina["shopify_beheer"],
        "klant_token": klant_token,
        "webshop_url": webshop_url,
        "beheer": beheer,
    }


@app.route("/demo")
@app.route("/demo/<pad>")
def openbaar_voorbeeld(pad=""):
    """Het dashboard van een ECHTE winkel, zonder inloggen.

    Waarom dit bestaat: op de homepage staat een knop naar het dashboard, en een
    bezoeker die nog geen klant is kan daar anders niets. Een schermafbeelding
    zou ook kunnen, maar die is over twee maanden verouderd en niemand gelooft
    hem. Dit is echte data die zichzelf bijwerkt.

    Er staat niets geheims op: precies dezelfde cijfers staan op de openbare
    indexpagina van die categorie."""
    import dashboardpaginas as dp
    if pad and pad not in dp.PAD_NAAR_PAGINA:
        return redirect("/demo")
    # 29 SEPTEMBER: Nino klikte op "Product" en kreeg "There is no example yet",
    # terwijl 29 categorieen gemeten zijn. De ene zoekvraag hierachter vond
    # niets (hij eiste een naam en een oude plekkolom). Nu eerst die vraag, en
    # anders de eerste goede winkel uit de bewaarde ranglijsten. En valt een
    # dashboard om, dan de volgende kandidaat in plaats van een foutpagina.
    # 29 september, Nino: "de productpagina is sloom". Elke keer werd het hele
    # dashboard van de voorbeeldwinkel opnieuw opgebouwd uit de database. Het is
    # voor iedereen dezelfde pagina, dus bewaren wij hem tien minuten.
    sleutel = (pad, request.args.get("taal") or "")
    bewaard = _demo_bewaard.get(sleutel)
    if bewaard and _thuis_onthouden_aan():
        # 30 september: na tien minuten wachtte de volgende bezoeker weer op het
        # hele opbouwen (Nino zag 50 seconden op /demo). Nu krijgt hij meteen de
        # bewaarde pagina, en bouwen we de nieuwe op de achtergrond. Het is
        # voorbeelddata: een versie van tien minuten oud is prima.
        if time.time() - bewaard[0] >= DEMO_SECONDEN:
            _ververs_demo_op_achtergrond(sleutel, pad)
        return bewaard[1]
    pagina = _maak_demo(pad)
    if pagina is None:
        # Nooit meer een doodlopende pagina achter "Product": dan de index,
        # daar staan dezelfde echte cijfers.
        return redirect("/index")
    _demo_bewaard[sleutel] = (time.time(), pagina)
    return pagina


DEMO_SECONDEN = 600
_demo_bewaard = {}
_demo_bezig = set()


def _ververs_demo_op_achtergrond(sleutel, pad):
    """Bouw een voorbeeldpagina opnieuw, maar nooit twee keer tegelijk."""
    with _bewaard_slot:
        if sleutel in _demo_bezig:
            return
        _demo_bezig.add(sleutel)
    taal = sleutel[1]

    def _bouw():
        try:
            doel = "/demo" + (f"/{pad}" if pad else "") + (f"?taal={taal}" if taal else "")
            with app.test_request_context(doel):
                pagina = _maak_demo(pad)
            if pagina:
                _demo_bewaard[sleutel] = (time.time(), pagina)
        except Exception as e:
            print(f"Voorbeeld verversen mislukt ({pad}): {e}")
        finally:
            _demo_bezig.discard(sleutel)
    threading.Thread(target=_bouw, daemon=True).start()


def _maak_demo(pad=""):
    import dashboardpaginas as dp
    pagina = None
    for keuze in _voorbeeld_kandidaten():
        pagina = _dashboard(keuze["webshop_url"], land=keuze.get("land"), voorbeeld=True,
                            pagina=dp.PAD_NAAR_PAGINA.get(pad, "overzicht"),
                            categorie=keuze.get("categorie"))
        if pagina is not None:
            break
    if isinstance(pagina, tuple):
        pagina = pagina[0]
    if pagina is not None and not isinstance(pagina, str):
        pagina = pagina.get_data(as_text=True) if hasattr(pagina, "get_data") else str(pagina)
    return pagina


def _voorbeeld_kandidaten(maximaal=3):
    """Winkels die zich lenen voor het voorbeeld: genoemd, niet nummer 1, liefst
    met een naam, uit de grootste gemeten categorie. Uit het geheugen."""
    uit = []
    try:
        eerste = db.voorbeeldwinkel()
        if eerste:
            uit.append(eerste)
    except Exception as e:
        print(f"Voorbeeldwinkel mislukt: {e}")
    try:
        landen = [r["land"] for r in _bewaard(("landen",), db.landen_in_index) or []]
        land = "nl" if "nl" in landen else (landen[0] if landen else None)
        if land:
            cats = sorted(_bewaard(("perland", land), db.categorieen_per_land, land, MINIMUM_PER_LAND) or [],
                          key=lambda c: -(c.get("winkels") or 0))
            for c in cats[:5]:
                rijen = (_ranglijst_bewaard(c["categorie"], land) or {}).get("rijen") or []
                goed = [r for r in rijen if (r.get("genoemd") or 0) > 0 and 2 <= r["positie"] <= 10]
                goed.sort(key=lambda r: (not (r.get("naam") and not str(r.get("naam")).startswith("http")), r["positie"]))
                for r in goed[:1]:
                    uit.append({"webshop_url": r["webshop_url"], "categorie": c["categorie"], "land": land})
                if len(uit) >= maximaal:
                    break
    except Exception as e:
        print(f"Voorbeeldkandidaten uit de ranglijsten mislukt: {e}")
    gezien, schoon = set(), []
    for k in uit:
        if k["webshop_url"] not in gezien:
            gezien.add(k["webshop_url"])
            schoon.append(k)
    return schoon[:maximaal]


@app.route("/admin/rapport.pdf")
def admin_rapport_pdf():
    """Het maandrapport van een winkel naar keuze bekijken (1 oktober), zonder
    dat die winkel klant hoeft te zijn. Precies dezelfde PDF als een klant krijgt."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    beeld = klantbeeld.bouw(url, max_vragen=5) if url else None
    if not beeld:
        return ("Deze winkel staat (nog) niet in een ranglijst, dus er is geen rapport. "
                "Probeer een winkel uit /index."), 404
    return _rapport_pdf_antwoord(url, beeld)


def _rapport_pdf_antwoord(url, beeld):
    import klantrapport
    maand = beeld.get("gemeten_op").strftime("%B %Y") if hasattr(beeld.get("gemeten_op"), "strftime") else ""
    data = klantrapport.pdf(beeld, categorieen.naam_en(beeld["categorie"]),
                            sitetaal.landnaam(beeld.get("land"), "en") if beeld.get("land") else "",
                            imago=_imago(beeld["ronde"], url, beeld.get("naam")), maand=maand)
    naam = _winkel_slug(url).replace(".", "-")
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="krillo-{naam}.pdf"',
                             "Cache-Control": "private, max-age=3600"})


@app.route("/mijn/<klant_token>/report.pdf")
def klant_rapport_pdf(klant_token):
    """Stap 184: het maandrapport als PDF van een pagina, om door te sturen."""
    klant = db.get_klant(klant_token)
    if not klant:
        return render_template("fout.html", titel="This link no longer works",
                               bericht="Ask for a new one on /get-my-link and we will email it again."), 404
    url = klant["webshop_url"]
    beeld = klantbeeld.bouw(url, max_vragen=5)
    if not beeld:
        return render_template("fout.html", titel="No report yet",
                               bericht="Your category has not been measured yet. The report is here after the "
                                       "first measurement."), 404
    return _rapport_pdf_antwoord(url, beeld)


@app.route("/mijn/<klant_token>/checks.pdf")
def klant_checks_pdf(klant_token):
    """1 oktober: de dertien controles op volgorde van wat eerst moet, als PDF om
    door te geven aan een webdesigner of SEO-partij."""
    klant = db.get_klant(klant_token)
    if not klant:
        return render_template("fout.html", titel="This link no longer works",
                               bericht="Ask for a new one on /get-my-link and we will email it again."), 404
    url = klant["webshop_url"]
    rapporten = db.get_rapporten_voor_webshop(url) or []
    laatste = rapporten[0] if rapporten else None
    if not laatste or not laatste.get("checks"):
        return render_template("fout.html", titel="No checks yet",
                               bericht="The first technical check runs within a week of your start."), 404
    import klantrapport
    datum = laatste.get("aangemaakt_op").strftime("%d %b %Y") if hasattr(laatste.get("aangemaakt_op"), "strftime") else ""
    data = klantrapport.scan_pdf(url, laatste["checks"], datum)
    naam = _winkel_slug(url).replace(".", "-")
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="krillo-checks-{naam}.pdf"',
                             "Cache-Control": "private, max-age=3600"})


@app.route("/mijn/<klant_token>")
@app.route("/mijn/<klant_token>/<pad>")
def klant_dashboard(klant_token, pad=""):
    """Het dashboard van een klant, achter zijn geheime link.

    Geen wachtwoord: de link IS de sleutel. Dat is bewust, want een wachtwoord
    dat je een keer per maand nodig hebt ben je kwijt, en dan is de drempel om
    te kijken hoger dan de moeite om op te zeggen."""
    klant = db.get_klant(klant_token)
    if not klant:
        return render_template(
            "fout.html", titel="This link no longer works",
            bericht="Ask for a new one on /get-my-link and we will email it "
                    "again."), 404
    import dashboardpaginas as dp
    if pad and pad not in dp.PAD_NAAR_PAGINA:
        return redirect(f"/mijn/{klant_token}")
    # Stap 99: de behoudagent wil weten wie zijn pagina nog opent.
    try:
        import klantagenten
        klantagenten.bekeken(klant_token)
    except Exception as e:
        print(f"Bekeken bijhouden mislukt: {e}")
    return _dashboard(klant["webshop_url"], klant_token=klant_token,
                      pagina=dp.PAD_NAAR_PAGINA.get(pad, "overzicht"))


ASSISTENTKEUZE = "assistenten:"


def _assistenten_keuze(webshop_url):
    """De assistenten die nog niet gemeten worden en die deze klant erbij wil.

    Waarom zo: ChatGPT en Gemini meten we bij iedereen, die staan altijd aan.
    Perplexity, Google AI Mode en Grok meten we nog niet. Een klant zet ze aan
    in zijn dashboard; dat is een aanmelding: zodra we die assistent meten,
    komt hij in zijn metingen. Tot dan beloven we niets anders, en Nino ziet
    welke assistent het meest gevraagd wordt (een eerlijk signaal voor stap 188)."""
    try:
        lijst = json.loads(db.get_instelling(ASSISTENTKEUZE + webshop_url) or "[]")
        later = {a["sleutel"] for a in ASSISTENTEN if not a["gemeten"]}
        return [k for k in lijst if k in later] if isinstance(lijst, list) else []
    except Exception:
        return []


@app.route("/mijn/<klant_token>/assistenten", methods=["POST"])
def klant_assistenten(klant_token):
    """Een nieuwe assistent aan- of uitzetten (8 oktober, versie 10)."""
    klant = db.get_klant(klant_token)
    if not klant:
        return jsonify({"ok": False}), 404
    gegevens = request.get_json(silent=True) or {}
    sleutel = (gegevens.get("sleutel") or "").strip()
    aan = bool(gegevens.get("aan", True))
    later = {a["sleutel"]: a["naam"] for a in ASSISTENTEN if not a["gemeten"]}
    if sleutel not in later:
        # ChatGPT en Gemini kun je niet uitzetten: die zitten in elk pakket en
        # tellen mee voor de plek in de index.
        return jsonify({"ok": False, "error": "This assistant is always included."}), 400
    lijst = _assistenten_keuze(klant["webshop_url"])
    if aan and sleutel not in lijst:
        lijst.append(sleutel)
    if not aan:
        lijst = [k for k in lijst if k != sleutel]
    db.zet_instelling(ASSISTENTKEUZE + klant["webshop_url"], json.dumps(lijst))
    if aan:
        try:
            if db.claim_moment(f"assistent_melding:{klant['webshop_url']}:{sleutel}", 30 * 24 * 3600):
                _meld_aan_beheer(f"Klant wil {later[sleutel]} erbij",
                                 f"{klant['webshop_url']} zette {later[sleutel]} aan in het dashboard. "
                                 "Dat is een aanmelding: meet die assistent zodra hij in Krillo zit (stap 188).")
        except Exception as e:
            print(f"Melding assistentkeuze mislukt: {e}")
    return jsonify({"ok": True, "gekozen": lijst})


NIETVOORMIJ = "nietvoormij:"


def _niet_voor_mij(webshop_url):
    """De koopvragen die een klant wegzette als "niet voor mijn winkel"."""
    try:
        lijst = json.loads(db.get_instelling(NIETVOORMIJ + webshop_url) or "[]")
        return lijst if isinstance(lijst, list) else []
    except Exception:
        return []


@app.route("/mijn/<klant_token>/niet-voor-mij", methods=["POST"])
def klant_niet_voor_mij(klant_token):
    """"Not for my store" bij een koopvraag (8 oktober, Nino: een snowboardwinkel
    kreeg vragen over yogamatten in de brede categorie Sport en fitness).

    De vraag verdwijnt uit ZIJN vragenlijst en fixes. Zijn plek in de index
    blijft over de hele categorie gerekend: anders vergelijken we winkels in
    dezelfde ranglijst met verschillende maten. Dat staat er ook bij."""
    klant = db.get_klant(klant_token)
    if not klant:
        return jsonify({"ok": False}), 404
    gegevens = request.get_json(silent=True) or {}
    vraag = (gegevens.get("vraag") or "").strip()
    aan = bool(gegevens.get("aan", True))
    lijst = _niet_voor_mij(klant["webshop_url"])
    if aan:
        beeld = klantbeeld.bouw(klant["webshop_url"])
        if not beeld or not vraag:
            return jsonify({"ok": False}), 400
        import dashboardpaginas as dp
        try:
            bekend = {v["vraag"] for v in dp.vragen_overzicht(beeld["ronde"], klant["webshop_url"],
                                                             beeld.get("naam"))["vragen"]}
        except Exception:
            bekend = set()
        if vraag not in bekend:
            return jsonify({"ok": False}), 400
        if vraag not in lijst:
            lijst.append(vraag)
    else:
        lijst = [v for v in lijst if v != vraag]
    db.zet_instelling(NIETVOORMIJ + klant["webshop_url"], json.dumps(lijst[:200]))
    if aan:
        db.zet_gekozen_vraag(klant["webshop_url"], vraag, False)
    return jsonify({"ok": True, "aantal": len(lijst)})


def _zonder_niet_voor_mij(vo, weg):
    """Een vragenoverzicht zonder de weggezette vragen; telt opnieuw."""
    if not vo or not weg:
        return vo
    uit = dict(vo)
    uit["vragen"] = [v for v in vo.get("vragen", []) if v["vraag"] not in weg]
    uit["gewonnen"] = sum(1 for v in uit["vragen"] if v.get("gewonnen"))
    uit["verloren"] = len(uit["vragen"]) - uit["gewonnen"]
    uit["totaal"] = len(uit["vragen"])
    return uit


@app.route("/mijn/<klant_token>/kies", methods=["POST"])
def klant_kies_vraag(klant_token):
    """"Add to my fixes" in het dashboard (30 september, het idee bij dashboard 8).

    De klant zet een koopvraag op zijn lijst of haalt hem eraf. Alleen met een
    geldige klantlink; op het voorbeeld (/demo) en de voorproef is er geen
    knop maar een link naar de proef. Alleen vragen die echt in zijn laatste
    meting stonden worden bewaard, zodat dit geen vrij tekstveld in onze
    database is."""
    klant = db.get_klant(klant_token)
    if not klant:
        return jsonify({"ok": False}), 404
    gegevens = request.get_json(silent=True) or {}
    vraag = (gegevens.get("vraag") or "").strip()
    aan = bool(gegevens.get("aan", True))
    beeld = klantbeeld.bouw(klant["webshop_url"])
    if not beeld or not vraag:
        return jsonify({"ok": False}), 400
    import dashboardpaginas as dp
    try:
        bekend = {v["vraag"] for v in dp.vragen_overzicht(beeld["ronde"], klant["webshop_url"],
                                                         beeld.get("naam"))["vragen"]}
    except Exception as e:
        print(f"Vragen voor het kiezen ophalen mislukt: {e}")
        bekend = set()
    if vraag not in bekend:
        return jsonify({"ok": False}), 400
    aantal = db.zet_gekozen_vraag(klant["webshop_url"], vraag, aan)
    return jsonify({"ok": aantal is not None, "aantal": aantal or 0, "aan": aan})


@app.route("/mijn/<klant_token>/waarom/vergelijk")
def klant_waarom_vergelijk(klant_token):
    """"Their page next to yours" (8 oktober, stap 335), als JSON.

    De scan van de winnaar (dertien checks, andermans website) duurt seconden en
    mag dus niet in het opbouwen van de pagina zitten. De pagina Why you lose
    laadt dit met fetch en toont zolang een laadstaat. De scan zelf, met zeven
    dagen geheugen en een tijdslimiet, staat in waaromverlies.py. Alleen met een
    geldige klantlink."""
    import dashboardpaginas as dp
    import waaromverlies as wv
    klant = db.get_klant(klant_token)
    if not klant:
        return jsonify({"ok": False, "fout": "This link no longer works."}), 404
    taal = sitetaal.kies_taal(pad_taal=request.args.get("taal"))
    url = klant["webshop_url"]
    beeld = klantbeeld.bouw(url)
    if not beeld:
        return jsonify({"ok": False, "soort": "geen_meting",
                        "fout": "There is no measurement for your store yet."}), 200
    try:
        vo = _zonder_niet_voor_mij(dp.vragen_overzicht(beeld["ronde"], url, beeld.get("naam")),
                                   set(_niet_voor_mij(url)))
        import eigenvragen
        eigen = eigenvragen.overzicht(url)
    except Exception as e:
        print(f"Vergelijken: vragen ophalen mislukt voor {url}: {e}")
        return jsonify({"ok": False, "fout": "Something went wrong. Try again in a minute."}), 200
    v = wv.kies_vraag(vo, request.args.get("vraag"), eigen)
    if not v:
        return jsonify({"ok": False, "soort": "geen_vraag", "fout": "That question is not in your measurement."}), 200
    try:
        import paginacheck
        paginas = (paginacheck.laatste(url) or {}).get("paginas")
    except Exception:
        paginas = None
    onderwerp, ontbreekt = wv.pagina_ontbreekt(v["vraag"], paginas)
    try:
        rijen = (_ranglijst_bewaard(beeld["categorie"], beeld.get("land")) or {}).get("rijen") or []
    except Exception:
        rijen = []
    uit = wv.vergelijking_json(v, rijen, wv.klant_checks(klant_token), taal=taal,
                               onderwerp=onderwerp, pagina_ontbreekt=ontbreekt)
    return jsonify(uit)


@app.route("/mijn/<klant_token>/eigen-vragen", methods=["POST"])
def klant_eigen_vragen(klant_token):
    """Een eigen vraag toevoegen of weghalen (2 oktober, stap 180). Na toevoegen
    meteen een keer meten, op de achtergrond; daarna elke week mee."""
    import eigenvragen
    klant = db.get_klant(klant_token)
    if not klant:
        return render_template("fout.html", titel="This link no longer works",
                               bericht="Open your dashboard and try again."), 404
    url = klant["webshop_url"]
    if request.form.get("actie") == "weg":
        try:
            eigenvragen.verwijder(url, int(request.form.get("id") or 0))
            melding = "Removed."
        except ValueError:
            melding = "Not found."
    else:
        uit = eigenvragen.voeg_toe(url, request.form.get("vraag"), klant.get("pakket"))
        if uit["ok"]:
            threading.Thread(target=eigenvragen.meet, args=(url,), kwargs={"alleen_id": uit["id"]},
                             daemon=True).start()
            melding = "Added. We ask ChatGPT and Gemini now; refresh in a minute."
        else:
            melding = uit["fout"]
    # 8 oktober (stap 336): de doelkaart op het overzicht gebruikt deze route ook en
    # wil na het toevoegen terug naar het overzicht, niet naar Questions.
    if request.form.get("terug") == "overzicht":
        return redirect(f"/mijn/{klant_token}?eigen={quote(melding)}#doel")
    return redirect(f"/mijn/{klant_token}/questions?eigen={quote(melding)}#eigen")


@app.route("/login", methods=["GET", "POST"])
# /mijn-link was het oude adres (stap 114). Het formulier kan nog in een open
# tabblad staan, dus een POST daarheen blijft gewoon werken; GET gaat met een 301.
@app.route("/mijn-link", methods=["GET", "POST"], endpoint="mijn_link_oud")
@app.route("/get-my-link", methods=["GET", "POST"])
def link_opnieuw():
    """De link opnieuw laten mailen.

    Zonder dit is een klant die zijn mail kwijt is voorgoed buitengesloten, en
    die belt niet maar zegt op.

    Het antwoord is ALTIJD hetzelfde, of het adres nu bestaat of niet. Anders is
    dit formulier een manier om uit te vinden welke webshops klant bij ons zijn,
    en dat gaat niemand aan."""
    if request.path == "/mijn-link" and request.method == "GET":
        return redirect("/get-my-link" + (("?" + request.query_string.decode()) if request.query_string else ""),
                        code=301)
    verstuurd = request.args.get("m") == "verstuurd"
    if request.method == "POST":
        adres = (request.form.get("email") or "").strip().lower()
        try:
            klant = db.klant_bij_email(adres) if adres else None
            if klant:
                emailing.send_vermeldingen_update(
                    klant["email"], klant["webshop_url"],
                    "Keep this email: the link is your key, so there is no password to remember. "
                    "Did you not ask for this? Then you can ignore it; nothing changes.",
                    monitoring_url=f"{get_base_url().rstrip('/')}/mijn/{klant['klant_token']}",
                    taal="en", onderwerp="Your Krillo dashboard link",
                    kop="Your dashboard link", intro="One click and you are in.",
                    feiten=[("Store", klant["webshop_url"].replace("https://", "").replace("www.", "").rstrip("/")),
                            ("Plan", (klant.get("pakket") or "watch").capitalize())])
        except Exception as e:
            print(f"Link opnieuw sturen mislukt: {e}")
        return redirect(("/login" if request.path == "/login" else "/get-my-link") + "?m=verstuurd")
    # 29 september: Peec heeft een nette inlogpagina met een link per mail en
    # geen wachtwoord. Dat hadden wij al (de geheime link), alleen heette het
    # "Lost your link?" en stond het nergens in het menu. Nu is het /login,
    # met "Log in" rechtsboven op de site. Zelfde werking, zelfde regels.
    if request.path == "/login":
        return render_template("login.html", verstuurd=verstuurd)
    return render_template("mijn_link.html", verstuurd=verstuurd)


@app.route("/onderzoek")
def onderzoek():
    """Stuurt door naar de index (23 september).

    Dit was de publieke uitkomst van de oude benchmark: Nederlands, en op basis
    van de losse metingen per winkel van voor de index. De index IS nu het
    onderzoek. Permanent doorsturen, zodat Google het oude adres overdraagt.
    De oude pagina staat hieronder nog in onderzoek_oud, niet meer bereikbaar."""
    return redirect("/index", code=301)


def onderzoek_oud():
    """De publieke uitkomst van de benchmark (oud, niet meer bereikbaar).

    Dit is geen verkooppagina maar een onderzoek. Er staan aantallen in en geen
    namen van winkels: het patroon gaat naar buiten, de losse winkel blijft
    binnen. Dat is ook precies waarom een gemeten winkelier hem durft te openen
    en waarom een vakblad hem durft over te nemen.

    De cijfers komen uit dezelfde optelling als de beheerpagina, zodat er nooit
    twee verschillende uitkomsten in omloop zijn."""
    regels = db.benchmark_regels()
    cijfers = benchmark.tel_op(regels)
    platforms = benchmark.per_platform(regels)
    return render_template(
        "onderzoek.html",
        c=cijfers,
        platforms=platforms,
        zinnen=benchmark.kernzinnen(cijfers, platforms),
        # Geen winkelnamen mee naar de sjabloon. Wat er niet is kan er ook niet
        # per ongeluk op komen te staan.
    )


def _volledige_meting_na_klik(webshop_url):
    """Draait de volledige meting voor een winkel die zijn uitkomst opende.

    Op de achtergrond, want de bezoeker hoeft daar niet op te wachten: hij ziet
    de uitkomst van de eerste meting, en de volgende keer dat hij kijkt staat er
    meer. Precies een keer per winkel, anders kost drie keer verversen drie
    volledige metingen.

    Valt onder dezelfde dagpot als al het andere. Is die op, dan gebeurt er
    niets en staat dat in de logs. Dat is geen ramp: de bezoeker heeft zijn
    uitkomst al."""
    try:
        if benadering.volledige_meting_gedaan(webshop_url):
            return False
        rem = kosten.mag_doorgaan(webshop_url=webshop_url)
        if not rem["mag"]:
            # NIET zomaar overslaan. Dit was een stil gat: in de mail staat dat
            # er meteen een grotere meting overheen gaat zodra je je pagina
            # opent, en was het geld voor die dag op, dan gebeurde er niets en
            # kwam deze winkel er ook nooit meer langs. De belofte was dan
            # gewoon niet waar en niemand die het zag.
            #
            # Iemand die klikt is bovendien het beste wat er die dag gebeurt.
            # Juist aan hem hoort de dure meting besteed te worden, desnoods een
            # dag later.
            print(f"Volledige meting na klik uitgesteld voor {webshop_url}: {rem['reden']}")
            benadering.zet_op_wachtlijst_volledige_meting(webshop_url)
            return False
        # Meteen vastleggen, voor de meting begint. Twee bezoekers tegelijk
        # zouden anders allebei een meting starten.
        benadering.onthoud_volledige_meting(webshop_url)
        _demo_inplannen([webshop_url], benchmark_stand=True,
                        vragen=MEET_VRAGEN_NA_KLIK, opnieuw=True)
        print(f"Volledige meting gestart na een klik op de uitkomst van {webshop_url}.")
        return True
    except Exception as e:
        print(f"Volledige meting na klik mislukt voor {webshop_url}: {e}")
        return False


@app.route("/uitkomst/<token>")
def uitkomst(token):
    """De eigen uitkomst van een winkel die wij in de benchmark gemeten hebben.

    Deze link gaat naar iemand die er niet om gevraagd heeft. Daarom drie
    dingen: het kenmerk is niet te raden, de pagina wordt niet geïndexeerd, en
    er staat bovenaan waarom hij deze mail kreeg en hoe hij eraf komt.

    Bewust geen actielijst met kant-en-klare teksten. Dat is het betaalde deel.
    Hier staat wat we gemeten hebben en hoe hij het doet ten opzichte van de
    rest, en dat is genoeg om te willen weten wat je eraan doet."""
    webshop_url = db.winkel_bij_benchmark_token(token)
    if not webshop_url:
        return render_template(
            "fout.html", titel="This link no longer works",
            bericht="Ask us for a new one, or run the free check on the homepage."), 404

    # Alleen tellen dat de pagina geopend is. Zonder dit weet je na honderd
    # verstuurde mails alleen dat er honderd verstuurd zijn.
    db.noteer_uitkomst_bekeken(webshop_url)

    # SINDS 23 SEPTEMBER (stap 36) wijst de mail naar de openbare ranglijst.
    # Deze route blijft ertussen zodat wij tellen dat hij geopend is, en stuurt
    # dan door naar de categorie, met zijn eigen regel in beeld (#p<positie>).
    # Staat de winkel (nog) niet in een ranglijst, bijvoorbeeld bij een link
    # uit een oude mail, dan de oude pagina zoals die was.
    try:
        beeld = klantbeeld.bouw(webshop_url)
    except Exception as e:
        print(f"Positie ophalen voor de uitkomstlink mislukt voor {webshop_url}: {e}")
        beeld = None
    if beeld and beeld.get("land"):
        # SINDS 28 SEPTEMBER (stap 135): zijn EIGEN dashboard, als gratis
        # voorproef. Hiervoor ging hij naar de openbare ranglijst met een balk
        # bovenaan, en van de 24 die hun uitkomst openden ging er 1 naar de
        # prijzen. Op een lijst vol andere winkels zie je niet wat JIJ krijgt.
        # Nu ziet hij zijn plek, zijn buren, zijn verloren vragen met het echte
        # antwoord, en wat Watch en Fix voor hem doen, met een knop die meteen
        # het afrekenen opent met zijn winkel al ingevuld.
        return _dashboard(webshop_url, land=beeld["land"], proef=token, pagina="overzicht")
    # Nog geen positie: naar de openbare index. De oude uitkomstpagina hieronder
    # is Nederlands en uit het oude model (23 september); die tonen wij niet
    # meer aan iemand die een Engelse mail kreeg.
    return redirect("/index")

    # En nu pas de volledige meting. Dit is het hele idee achter de lichte
    # eerste meting: iemand die deze pagina opent is de eerste die laat merken
    # dat hij kijkt, en dat is het moment waarop het de moeite waard wordt om
    # vijftien vragen bij twee modellen te stellen en de bronnen na te trekken.
    # Ervoor betalen wij ongeveer twintig cent per winkel, erna ongeveer een
    # euro, en dan alleen voor de winkels waar iemand achter zit.
    _volledige_meting_na_klik(webshop_url)

    gegevens = _klantgegevens(webshop_url)
    laatste = (db.get_rapporten_voor_webshop(webshop_url) or [None])[0]
    cijfers = benchmark.tel_op(db.benchmark_regels())

    return render_template(
        "uitkomst.html",
        webshop_url=webshop_url,
        # Het kenmerk meegeven zodat de afmeldknop op deze pagina kan staan.
        # Er stond alleen "mail ons", en iemand die zich overvallen voelt door
        # ongevraagde post klikt eerder op de spamknop van zijn mailprogramma
        # dan dat hij een mail gaat typen. Een spamklacht kost je je domein,
        # een afmelding kost je een adres.
        afmeld_token=token,
        winkelnaam=_winkelnaam(webshop_url),
        vermeldingen=gegevens["vermeldingen"],
        actieplan=gegevens["actieplan"],
        laatste=laatste,
        c=cijfers,
        token=token,
    )


@app.route("/uitkomst/<token>/<pad>")
def uitkomst_pagina(token, pad):
    """De andere pagina's van de voorproef (ranking, questions, fixes, plan)."""
    import dashboardpaginas as dp
    webshop_url = db.winkel_bij_benchmark_token(token)
    if not webshop_url or pad not in dp.PAD_NAAR_PAGINA:
        return redirect(f"/uitkomst/{token}" if webshop_url else "/index")
    try:
        beeld = klantbeeld.bouw(webshop_url)
    except Exception:
        beeld = None
    if not (beeld and beeld.get("land")):
        return redirect("/index")
    return _dashboard(webshop_url, land=beeld["land"], proef=token,
                      pagina=dp.PAD_NAAR_PAGINA[pad])


# ---------------------------------------------------------------------------
# STAP 352 (9 oktober): de aanmeldroute /start, naar het voorbeeld van Peec.
# Eerst een account (mailadres), dan de winkel, het profiel, de vragen die hij
# wil winnen, een stukje van zijn eigen uitslag, en pas dan pakket en betaling.
# Zie aanmelden.py voor het waarom.
# ---------------------------------------------------------------------------
@app.route("/start")
def start_pagina():
    import aanmelden
    plan = request.args.get("plan")
    plan = plan if plan in ("watch", "fix") else "watch"
    winkel = scan_engine.normalize_url(request.args.get("winkel") or "") if request.args.get("winkel") else ""
    return render_template("start.html", plan=plan, winkel=winkel,
                           kenmerk=(request.args.get("t") or "")[:80],
                           categorieen_lijst=aanmelden.categorie_keuzes(),
                           prijs_watch=payments.PAKKETTEN["watch"]["prijs"]["value"].split(".")[0],
                           prijs_fix=payments.PAKKETTEN["fix"]["prijs"]["value"].split(".")[0])


@app.route("/api/start/account", methods=["POST"])
def start_account():
    import aanmelden
    d = request.get_json(silent=True) or {}
    email = (d.get("email") or "").strip()
    if not _EMAIL_VORM.match(email):
        return jsonify({"error": "That email address does not look right. Please check it."}), 400
    if not d.get("akkoord"):
        return jsonify({"error": "Please agree to the terms and the privacy policy."}), 400
    token = aanmelden.begin(email)
    # Nino wil weten dat er iemand begint, ook als hij niet afrondt: dit adres
    # is de eerste echte lead uit de site.
    _meld_aan_beheer("Iemand begint aan /start", f"{email} maakte een account aan op /start.")
    return jsonify({"ok": True, "token": token})


@app.route("/api/start/winkel", methods=["POST"])
def start_winkel():
    import aanmelden
    d = request.get_json(silent=True) or {}
    token, url = d.get("token") or "", (d.get("url") or "").strip()
    if not aanmelden.lees(token):
        return jsonify({"error": "Your session expired. Start again, it takes a minute."}), 404
    if not url or "." not in url:
        return jsonify({"error": "Type your store address, for example yourstore.com."}), 400
    p = aanmelden.profiel(url)
    aanmelden.zet(token, url=p["url"], naam=p["naam"], categorie=p["categorie"], land=p["land"], stap="profiel")
    return jsonify({"ok": True, "profiel": p})


@app.route("/api/start/profiel", methods=["POST"])
def start_profiel():
    import aanmelden
    d = request.get_json(silent=True) or {}
    token = d.get("token") or ""
    if not aanmelden.lees(token):
        return jsonify({"error": "Your session expired. Start again, it takes a minute."}), 404
    slug, land = d.get("categorie") or "", (d.get("land") or "nl").lower()
    if slug not in categorieen.GELDIG or slug in categorieen.NIET_MEETBAAR:
        return jsonify({"error": "Choose the category that fits your store best."}), 400
    if land not in ("nl", "be"):
        return jsonify({"error": "Krillo measures the Netherlands and Belgium for now."}), 400
    naam = (d.get("naam") or "").strip()[:80]
    aanmelden.zet(token, categorie=slug, land=land, naam=naam or None, stap="vragen")
    return jsonify({"ok": True, "vragen": aanmelden.vragen(slug), "taal": markten.vraagtaal_en(land)})


@app.route("/api/start/doelen", methods=["POST"])
def start_doelen():
    """Bewaart de vragen die hij wil winnen, en geeft een stukje van zijn uitslag."""
    import aanmelden
    d = request.get_json(silent=True) or {}
    token = d.get("token") or ""
    g = aanmelden.lees(token)
    if not g:
        return jsonify({"error": "Your session expired. Start again, it takes a minute."}), 404
    doelen = [str(v)[:300] for v in (d.get("doelen") or []) if v][:aanmelden.MAX_DOELEN]
    aanmelden.zet(token, doelen=doelen, stap="voorproef")
    rang = None
    try:
        r = _rang_voor_gratis_check(g.get("url")) if g.get("url") else None
        if r:
            rang = {k: r.get(k) for k in ("positie", "van", "categorie", "land", "genoemd", "telbaar", "nul", "aantal_verloren")}
            rang["voor"] = [w.get("naam") for w in (r.get("voor_rijen") or [])][:3]
    except Exception as e:
        print(f"Voorproef voor /start mislukt: {e}")
    return jsonify({"ok": True, "rang": rang, "doelen": doelen})


@app.route("/api/start/plan", methods=["POST"])
def start_plan():
    """Welk pakket hij koos (ook als hij daarna bij Mollie afhaakt)."""
    import aanmelden
    d = request.get_json(silent=True) or {}
    plan = d.get("plan") if d.get("plan") in ("watch", "fix") else None
    if not aanmelden.lees(d.get("token") or "") or not plan:
        return jsonify({"ok": False}), 400
    aanmelden.zet(d["token"], plan=plan, stap="betalen")
    return jsonify({"ok": True})


@app.route("/uitkomst/<token>/verder")
def uitkomst_verder(token):
    """De knop op de uitkomstpagina. Telt de doorklik en stuurt dan door.

    Een eigen route en geen gewone link, want dit is de enige stap in de hele
    trechter die over geld gaat. Zonder dit weet je wel hoeveel mensen hun
    uitkomst openen, maar niet of ze daarna ook iets willen."""
    webshop_url = db.winkel_bij_benchmark_token(token)
    if not webshop_url:
        return redirect("/#pricing")
    db.noteer_doorgeklikt(webshop_url)
    # Met ?plan= opent de homepage meteen het afrekenvenster voor dat pakket,
    # met zijn winkel ingevuld. Een klik minder op het moment dat telt.
    plan = request.args.get("plan")
    plan = plan if plan in ("watch", "fix") else None
    # Stap 168: het kenmerk gaat mee (t=), zodat de homepage het mailadres
    # waar wij naartoe mailden kan invullen via /api/voorvullen. Niet het
    # adres zelf in de link: dat komt dan in logboeken en doorverwijzingen.
    # 9 oktober (stap 352): niet meer meteen de kassa, maar de aanmeldroute.
    # Van ongeveer 59 mensen die hier klikten vulde niemand de kassa in.
    return redirect(f"/start?winkel={quote(webshop_url)}&utm_source=koude_mail"
                    + (f"&plan={plan}&t={quote(token)}" if plan else ""))


@app.route("/api/voorvullen/<token>")
def api_voorvullen(token):
    """Stap 168: het mailadres bij een uitkomstlink, om de kassa in te vullen.
    Alleen met het geheime kenmerk uit onze eigen mail, en niet voor wie zich
    afmeldde."""
    webshop_url = db.winkel_bij_benchmark_token(token)
    if not webshop_url or db.is_afgemeld(webshop_url):
        return jsonify({}), 404
    w = db.winkel_kort(webshop_url) or {}
    email = ""
    try:
        import proefperiode
        rij = proefperiode._sql("SELECT email FROM benadering WHERE webshop_url = %s", (webshop_url,))
        email = (rij or {}).get("email") or ""
    except Exception as e:
        print(f"Voorvullen mislukt: {e}")
    return jsonify({"winkel": webshop_url.replace("https://", "").replace("www.", "").rstrip("/"),
                    "email": email, "naam": w.get("naam") or ""})


@app.route("/admin/benchmark")
def admin_benchmark():
    """Telt op wat er over alle gemeten winkels uitkwam.

    Dit is de pagina waar je je publiceerbare zinnen vandaan haalt. De losse
    winkels staan eronder zodat je kan controleren of een uitschieter klopt,
    maar wat je naar buiten brengt zijn alleen de aantallen."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    regels = db.benchmark_regels()
    cijfers = benchmark.tel_op(regels)
    platforms = benchmark.per_platform(regels)
    return render_template(
        "admin_benchmark.html",
        # Ruwe tellingen erbij. Zonder deze stond er alleen "er is nog geen
        # enkele demo gedraaid", terwijl de benaderpagina 45 gemeten winkels
        # meldde. Twee schermen die elkaar tegenspreken zonder dat je kunt zien
        # welke van de twee liegt.
        diagnose=db.benchmark_diagnose(),
        regels=regels,
        c=cijfers,
        platforms=platforms,
        zinnen=benchmark.kernzinnen(cijfers, platforms),
        sleutel=admin_key,
    )


@app.route("/admin/voorbeeld")
def admin_voorbeeld():
    """Laat de klantpagina zien voor een webshop naar keuze, zonder dat daar een
    abonnement voor hoeft te bestaan.

    Nodig omdat de monitoringpagina alleen bereikbaar is via een klant_token dat
    pas ontstaat bij een betaald abonnement. Zonder deze route kan je niet
    controleren hoe een klant zijn eigen pagina ziet."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    if not webshop_url:
        # 1 oktober: hier stond alleen "Geef een webshop op met &url=...". Nu een
        # invulveld, plus de knop voor het maandrapport (stap 184).
        return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
                f"<title>Klantpagina bekijken | Krillo</title><body style='font-family:Arial,sans-serif;"
                f"max-width:640px;margin:40px auto;padding:0 16px;line-height:1.5'>"
                f"<h1>Klantpagina bekijken</h1><p>Typ een winkel die in een ranglijst staat. Je ziet zijn "
                f"dashboard zoals een klant het ziet, en je kunt zijn maandrapport (PDF) openen.</p>"
                f"<form method='get'><input name='url' placeholder='bijvoorbeeld sounds.nl' size='30' required> "
                f"<button>Dashboard</button> <button formaction='/admin/rapport.pdf'>Maandrapport (PDF)</button>"
                f"</form></body>")

    rapporten = db.get_rapporten_voor_webshop(webshop_url)
    laatste = rapporten[0] if rapporten else None
    vorige = rapporten[1] if len(rapporten) > 1 else None

    verschil = laatste["score"] - vorige["score"] if (laatste and vorige) else None
    checks_by_categorie = {}
    if laatste:
        for c in laatste["checks"]:
            checks_by_categorie.setdefault(c.get("categorie", "overig"), []).append(c)

    gegevens = _klantgegevens(webshop_url)

    plan = gegevens["actieplan"]
    maand = db.kosten_per_klant_deze_maand(webshop_url) or {}
    uitgegeven = float(maand.get("kosten") or 0)
    taakstand = {
        "met_tekst": [a["titel"] for a in (plan or {}).get("acties", []) if a.get("oplossing")],
        "zonder_tekst": [a["titel"] for a in (plan or {}).get("acties", []) if not a.get("oplossing")],
        "uitgegeven": uitgegeven,
        "grens": kosten.GRENS_PER_KLANT_MAAND_EURO,
        "rem_dicht": uitgegeven >= kosten.GRENS_PER_KLANT_MAAND_EURO,
    }

    # Het werkscherm van de klant staat sinds 21 september in het dashboard,
    # dus de beheerweergave laat dat dashboard zien. Alleen de detailpagina met
    # de dertien controlepunten is nog een eigen scherm.
    if request.args.get("details") != "ja":
        return _dashboard(webshop_url,
                          beheer={"sleutel": admin_key, "taakstand": taakstand},
                          pagina=request.args.get("pagina") or "overzicht")

    pagina = _paginagegevens(webshop_url)
    return render_template(
        "monitoring_details.html",
        t=pagina["t"],
        paginataal=pagina["taal"],
        shopify_beheer=pagina["shopify_beheer"],
        webshop_url=webshop_url,
        klant_token=None,
        voorbeeld=True,
        sleutel=admin_key,
        taakstand=taakstand,
        vermeldingen=gegevens["vermeldingen"],
        controle=gegevens["controle"],
        beweging=gegevens["beweging"],
        bronnen=gegevens["bronnen"],
        actieplan=gegevens["actieplan"],
        verklaring=verklaring.maak_verklaring(
            laatste["checks"] if laatste else [], gegevens["vermeldingen"],
            taal=_mailtaal(webshop_url)),
        laatste=laatste,
        verschil=verschil,
        verloop=list(reversed(rapporten))[-8:],
        nieuwe_problemen=[],
        checks_by_categorie=checks_by_categorie,
        uitvoering=_laatste_uitvoering(webshop_url),
        wijzigingen=db.get_wijzigingen(webshop_url),
        abonnement=True,
        status_labels=_standlabels(pagina["t"]),
    )


@app.route("/admin/beoordelingen")
def admin_beoordelingen():
    """Fase 5 stap 4. Laat zien wat er uit de antwoorden gehaald is: welke
    winkels genoemd worden, of onze winkel erbij staat, en of dat een
    vermelding of een echte aanbeveling was."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    meting_id = request.args.get("meting") or None

    # Opnieuw beoordelen gooit de oordelen van deze ronde weg en doet ze over.
    # Kost opnieuw geld, dus alleen op verzoek. Nodig zodra de beoordelaar iets
    # nieuws kan bepalen wat er bij de oude oordelen nog niet in zat.
    if webshop_url and request.args.get("opnieuw") == "ja":
        weg = db.verwijder_beoordelingen(webshop_url, meting_id)
        print(f"{weg} beoordelingen weggegooid voor {webshop_url}, worden opnieuw gedaan.")

    if webshop_url and (request.args.get("start") == "ja" or request.args.get("opnieuw") == "ja"):
        # De winkelnaam uit het profiel meegeven, want in de antwoorden staat
        # Dille & Kamille en niet dille-kamille.nl.
        profiel = db.get_winkelprofiel(webshop_url)
        omschrijving = (profiel or {}).get("omschrijving") or ""
        winkelnaam = _winkelnaam(webshop_url)
        start = False
        with _metingen_slot:
            if webshop_url not in _beoordelen_bezig:
                _beoordelen_bezig.add(webshop_url)
                start = True
        if start:
            threading.Thread(target=_beoordeel_achtergrond,
                             args=(webshop_url, meting_id, winkelnaam), daemon=True).start()
        return redirect(f"/admin/beoordelingen?url={webshop_url}&bezig=ja")

    if webshop_url and request.args.get("controleer") == "ja":
        start = False
        with _metingen_slot:
            if webshop_url not in _beoordelen_bezig:
                _beoordelen_bezig.add(webshop_url)
                start = True
        if start:
            def klus():
                try:
                    _controleer_uitspraken(webshop_url, meting_id, _winkelnaam(webshop_url))
                finally:
                    with _metingen_slot:
                        _beoordelen_bezig.discard(webshop_url)
            threading.Thread(target=klus, daemon=True).start()
        return redirect(f"/admin/beoordelingen?url={webshop_url}&bezig=ja")

    beoordelingen = [dict(b) for b in db.get_beoordelingen(webshop_url, meting_id)] if webshop_url else []
    samenvatting = beoordeling.vat_samen(beoordelingen)

    # Onze eigen winkel oplichten in de concurrentietabel.
    for c in samenvatting["concurrenten"]:
        c["wij"] = scan_engine.is_eigen_winkel(webshop_url, c["naam"])

    return render_template(
        "admin_beoordelingen.html",
        webshop_url=webshop_url,
        sleutel=admin_key,
        beoordelingen=beoordelingen,
        s=samenvatting,
        bezig=request.args.get("bezig") == "ja",
        controle=controle.vat_samen(
            [dict(c) for c in db.get_uitspraakcontroles(webshop_url)]) if webshop_url else None,
        verklaring=verklaring.maak_verklaring(
            (db.get_rapporten_voor_webshop(webshop_url) or [{}])[0].get("checks") or [],
            beoordeling.klantbeeld(webshop_url, beoordelingen) if beoordelingen else None,
            taal=_mailtaal(webshop_url),
        ) if webshop_url else None,
    )


# Het schrijven op /admin/oplossingen loopt op de achtergrond (1 oktober): per
# winkel of hij bezig is, en wat de laatste keer de uitkomst was.
_oplossingen_bezig = {}
_oplossingen_klaar = {}


@app.route("/admin/oplossingen")
def admin_oplossingen():
    """Laat de kant-en-klare teksten van het actieplan los schrijven.

    Bestaat omdat het anders niet te doen is: de teksten worden normaal in de
    wekelijkse keten geschreven, en die hele keten opnieuw draaien kost tien
    minuten en ongeveer een euro. Als je alleen wil zien of het schrijven
    werkt, is dat zonde. Hier gebeurt alleen dat laatste stukje, en je ziet per
    taak wat eruit kwam of wat er misging.

    Met &opnieuw=ja gooit hij de bewaarde teksten eerst weg, zodat je een
    nieuwe versie kan laten schrijven na een aanpassing aan de opdracht."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    if not webshop_url:
        return "Geef een webshop op met &url=...", 400

    gegevens = _klantgegevens(webshop_url)
    plan = gegevens["actieplan"]

    if request.args.get("opnieuw") == "ja" and plan:
        for actie in plan.get("acties", []):
            if actie.get("id"):
                db.verwijder_taakoplossing(webshop_url, actie["id"])
        plan = _klantgegevens(webshop_url)["actieplan"]

    # 1 oktober: dit liep IN het verzoek. Drie teksten met het model duren langer
    # dan de 120 seconden die Render een verzoek geeft, en dan kreeg Nino
    # "Internal Server Error" (WORKER TIMEOUT). Nu op de achtergrond: deze pagina
    # zegt wat er loopt, en verversen laat de uitkomst zien.
    loopt = _oplossingen_bezig.get(webshop_url)
    if plan and not loopt and (request.args.get("opnieuw") == "ja" or request.args.get("start") == "ja"
                               or webshop_url not in _oplossingen_klaar):
        def _schrijf():
            try:
                _oplossingen_klaar[webshop_url] = _maak_taakoplossingen(webshop_url, plan)
            except Exception as e:
                _oplossingen_klaar[webshop_url] = [{"titel": "alles", "gelukt": False, "fout": str(e)[:200],
                                                     "was_er_al": False}]
            finally:
                _oplossingen_bezig.pop(webshop_url, None)
        _oplossingen_bezig[webshop_url] = True
        threading.Thread(target=_schrijf, daemon=True).start()
        loopt = True
    if request.args.get("opnieuw") == "ja":
        # Niet op dit adres blijven staan: verversen zou alles opnieuw weggooien.
        return redirect(f"/admin/oplossingen?url={quote(webshop_url)}")
    uitkomsten = [] if loopt else _oplossingen_klaar.get(webshop_url, [])

    regels = []
    for u in uitkomsten:
        if u["was_er_al"]:
            stand = "stond er al"
        elif u["gelukt"]:
            stand = "nieuw geschreven"
        else:
            stand = f"MISLUKT: {u['fout']}"
        regels.append(f"{u['titel']}\n    {stand}")

    if not plan:
        tekst = ("Er is nog geen actieplan voor deze winkel. Draai eerst de keten via "
                 "/admin/demo, of wacht op de wekelijkse ronde.")
    elif loopt:
        tekst = ("Bezig met schrijven op de achtergrond (een tot drie minuten). Ververs deze pagina "
                 "ZONDER &opnieuw=ja om de uitkomst te zien.")
    elif not regels:
        tekst = "Het actieplan heeft geen taken die een geschreven tekst nodig hebben."
    else:
        tekst = "\n\n".join(regels)

    maand = db.kosten_per_klant_deze_maand(webshop_url) or {}
    uitgegeven = float(maand.get("kosten") or 0)

    return Response(
        f"Taakoplossingen voor {webshop_url}\n"
        f"{'=' * (22 + len(webshop_url))}\n\n"
        f"{tekst}\n\n"
        f"Deze maand uitgegeven aan deze winkel: {uitgegeven:.2f} van "
        f"{kosten.GRENS_PER_KLANT_MAAND_EURO:.2f} euro\n\n"
        f"Bekijk het resultaat op /admin/voorbeeld?url={webshop_url}\n"
        f"Opnieuw laten schrijven: voeg &opnieuw=ja toe aan dit adres.\n",
        mimetype="text/plain; charset=utf-8")


@app.route("/admin/bronnen")
def admin_bronnen():
    """Fase 5 punt 14. Laat zien welke externe pagina's er gevonden zijn en wie
    daarop staat.

    Hier controleer je het belangrijkste risico van deze stap: dat een naam
    verkeerd herkend wordt. Zie je een pagina waarvan je weet dat de winkel er
    wel op staat terwijl er nee staat, dan klopt de naamherkenning niet en moet
    dat eerst opgelost worden. Een verkeerde vindplaats is erger dan geen
    vindplaats, want de klant gaat erop af."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    meting_id = request.args.get("meting") or None

    # Opnieuw zoeken kost echt geld, dus alleen op een knop en nooit vanzelf
    # bij het openen van de pagina. Dezelfde afspraak als bij de demo.
    if webshop_url and request.args.get("start") == "ja":
        start = False
        with _metingen_slot:
            if webshop_url not in _beoordelen_bezig:
                _beoordelen_bezig.add(webshop_url)
                start = True
        if start:
            _zet_bronnen_status(webshop_url, "Gestart, bezig met voorbereiden.")

            def klus():
                try:
                    _zoek_bronnen(webshop_url, meting_id, _winkelnaam(webshop_url))
                finally:
                    with _metingen_slot:
                        _beoordelen_bezig.discard(webshop_url)
            threading.Thread(target=klus, daemon=True).start()
        else:
            # Niet stilzwijgend niets doen. Eerder gebeurde er dan schijnbaar
            # niets terwijl de knop wel ingedrukt was, en dan zit je te wachten
            # op iets dat nooit komt.
            _zet_bronnen_status(
                webshop_url,
                "Er liep al een taak voor deze winkel (beoordelen, controleren of zoeken). "
                "Wacht tot die klaar is en probeer het dan opnieuw.", klaar=True)
        return redirect(f"/admin/bronnen?url={webshop_url}")

    # De zoekmachine los testen. Kost een halve cent en bewijst in een keer of
    # de sleutel werkt. Zonder dit sta je te gissen of het aan de zoekmachine
    # ligt of aan de winkel.
    proef = None
    if webshop_url and request.args.get("proef") == "ja":
        proef = bronnen.test_zoekmachine(
            (request.args.get("vraag") or "").strip() or None, webshop_url=webshop_url)

    vindplaatsen = [dict(v) for v in db.get_bronvindplaatsen(webshop_url, meting_id)] if webshop_url else []
    winkelnaam = _winkelnaam(webshop_url) if webshop_url else None

    # Waarom levert dit niets op? Alles wat de bronanalyse nodig heeft, op een
    # rij, zonder dat er iets gezocht of betaald wordt.
    diagnose = None
    if webshop_url:
        beoordeeld = meting_id or db.laatste_beoordeelde_meting_id(webshop_url)
        gemeten = db.laatste_meting_id(webshop_url)
        beoordelingen = ([dict(b) for b in db.get_beoordelingen(webshop_url, beoordeeld)]
                         if beoordeeld else [])
        klantbeeld = beoordeling.klantbeeld(webshop_url, beoordelingen) if beoordelingen else None
        diagnose = {
            "gemeten_ronde": gemeten,
            "meting_id": beoordeeld,
            # Is er wel gemeten maar niet beoordeeld, dan is dat precies wat je
            # moet weten, en dan hoort er een knop bij die het oplost.
            "onbeoordeelde_ronde": bool(gemeten and gemeten != beoordeeld),
            "beoordelingen": len(beoordelingen),
            "vragen": bronnen.kies_vragen(klantbeeld) if klantbeeld else [],
            "concurrenten": bronnen.kies_concurrenten(klantbeeld) if klantbeeld else [],
            "genoemd": (klantbeeld or {}).get("genoemd"),
            "telbaar": (klantbeeld or {}).get("telbaar"),
        }

    status = _bronnen_status.get(webshop_url) if webshop_url else None

    return render_template(
        "admin_bronnen.html",
        webshop_url=webshop_url,
        sleutel=admin_key,
        winkelnaam=winkelnaam,
        vindplaatsen=vindplaatsen,
        s=bronnen.vat_samen(vindplaatsen, winkelnaam) if vindplaatsen else None,
        status=status,
        diagnose=diagnose,
        proef=proef,
        werkt=bronnen.beschikbaar(),
        waarom_niet=bronnen.waarom_niet(),
        aanbieder=bronnen.ZOEK_AANBIEDER,
    )


@app.route("/admin/modellen")
def admin_modellen():
    """Laat per aanbieder zien of de ingestelde modelnaam werkt, en welke namen
    deze sleutel wel mag gebruiken. Mislukken alle metingen bij een aanbieder,
    dan is een verkeerde modelnaam veruit de meest voorkomende oorzaak."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    resultaten = []
    for a in metingen.AANBIEDERS:
        if not os.environ.get(a["sleutel_naam"]):
            continue
        resultaten.append({
            "toonnaam": a["toonnaam"],
            "provider": a["provider"],
            "model": a["model"],
            "test": metingen.test_aanbieder(a) if a["model"] else
                    {"gelukt": False, "antwoord": "", "fout": "Geen modelnaam ingesteld."},
            "lijst": metingen.haal_modellijst(a["provider"]),
        })

    return render_template("admin_modellen.html", resultaten=resultaten, sleutel=admin_key)


@app.route("/admin/bezoekers")
def admin_bezoekers():
    """Wat er op de site gebeurt: hoeveel gratis scans, waar ze vandaan komen,
    welke winkels het vaakst gescand worden en hoeveel er betaalden.

    Zonder dit lanceer je blind: komt er niemand, of komen ze wel en haken ze
    af? Dat zijn twee verschillende problemen."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    dagen = int(request.args.get("dagen", 30))
    overzicht = db.scanoverzicht(dagen)
    totaal = overzicht["totaal"] or {}
    scans = totaal.get("scans") or 0
    betaald = totaal.get("betaald") or 0
    # 7 oktober: wie na een mislukte check "Check it by hand" invulde, en welke
    # checks mislukten. Dit zijn warme mensen: ze wilden hun uitslag.
    try:
        handchecks = list(reversed(json.loads(db.get_instelling("handchecks") or "[]")))[:30]
    except Exception:
        handchecks = []
    try:
        conn = db._get_connection()
        with conn, conn.cursor() as cur:
            cur.execute("""SELECT gedaan_op, webshop_url, coalesce(foutsoort, '') FROM gratis_scans
                            WHERE NOT coalesce(gelukt, false) ORDER BY gedaan_op DESC LIMIT 20""")
            mislukt = [{"op": r[0], "url": r[1], "fout": r[2]} for r in cur.fetchall()]
        conn.close()
    except Exception as e:
        print(f"Mislukte checks ophalen mislukt: {e}")
        mislukt = []
    return render_template(
        "admin_bezoekers.html",
        handchecks=handchecks, mislukt=mislukt,
        dagen=dagen,
        totaal=totaal,
        # Bewust als "x van de y" en niet als percentage: bij kleine aantallen
        # suggereert een percentage een precisie die er niet is.
        betaald=betaald,
        scans=scans,
        per_dag=overzicht["per_dag"],
        per_herkomst=overzicht["per_herkomst"],
        per_bron=overzicht.get("per_bron") or [],
        top_winkels=overzicht["top_winkels"],
        leads=db.zichtbaarheidstest_leads(),
        sleutel=admin_key,
    )


@app.route("/admin/categorieen", methods=["GET", "POST"])
def admin_categorieen():
    """Winkels indelen in categorieen, en tellen of dat genoeg oplevert.

    Dit is de pagina waarop de hele ombouw naar de index staat of valt. Meten
    per categorie is alleen goedkoper als er genoeg winkels per categorie zijn:
    bij vijftig winkels per categorie is de besparing vijftigvoudig, bij drie is
    er geen besparing en deugt het plan niet.

    Het indelen zit met opzet op een POST, dus achter een knop. Het kost geld en
    het schrijft in de database, en dat mag nooit gebeuren doordat iemand een
    pagina opent of ververst. Dat is de les van 11 september."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    # Het indelen gebeurt op een EIGEN DRAAD en niet in dit verzoek. Bij 975
    # winkels zijn dat vierentwintig aanroepen van samen tien minuten, en
    # gunicorn kapt na twee minuten af. Op 13 september leverde dat twee
    # storingen op en moest de server herstart worden. Dezelfde fout als met de
    # kostenpagina op 11 september: lang werk aan een verzoek hangen.
    # Doorsturen na een POST. Op 13 september moest dit vier keer aangeklikt
    # worden en werd er vier keer betaald; verversen na een POST was daar een
    # van de oorzaken van.
    MELDINGEN = {
        "gestart": ("Het indelen is gestart en draait op de achtergrond. Ververs deze "
                    "pagina over een minuut of twee om te zien hoe ver hij is. Je kunt "
                    "het tabblad gerust sluiten, hij gaat gewoon door."),
        "loopt-al": "Het indelen loopt al. Ververs de pagina om te zien hoe ver hij is.",
    }
    bericht = MELDINGEN.get(request.args.get("m"))
    if request.method == "POST":
        hoeveel = int(request.form.get("hoeveel") or 0) or None
        opnieuw = request.form.get("opnieuw") == "ja"
        gestart = categorieen.start_indelen(hoeveel=hoeveel, opnieuw=opnieuw)
        return redirect("/admin/categorieen?m=" + ("gestart" if gestart else "loopt-al"))

    tel = categorieen.telling()
    return render_template(
        "admin_categorieen.html",
        bericht=bericht,
        stand=categorieen.stand(),
        tel=tel,
        besparing=categorieen.besparing(tel),
        naam_van=categorieen.naam_van,
        aantal_categorieen=len(categorieen.CATEGORIEEN) - 1,
    )


@app.route("/admin/opschonen", methods=["GET", "POST"])
def admin_opschonen():
    """De winkellijst opschonen voordat er een ranglijst openbaar gaat.

    Drie dingen worden hier vastgezet: welke regels geen webadres hebben, welke
    adressen van dezelfde keten zijn, en wat een merk is in plaats van een
    winkel. Zie opschonen.py voor waarom die drie, en de eerste echte ranglijst
    van 14 september voor wat er misgaat als je het niet doet.

    Achter een POST, want het kost geld en het schrijft in de database. Op een
    eigen draad, want het zijn tientallen modelaanroepen en gunicorn kapt na
    twee minuten af."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    # Doorsturen na een POST, zodat verversen niets opnieuw start. Zie de
    # uitleg bij admin_ranglijst: een pagina die bij elke verversing opnieuw
    # begint, laat je nooit de uitkomst zien en kan geld kosten.
    MELDINGEN = {
        "gestart": ("Het opschonen is gestart en draait op de achtergrond. Ververs "
                    "deze pagina over een minuut of twee. Je kunt het tabblad gerust "
                    "sluiten, hij gaat gewoon door."),
        "loopt-al": "Het opschonen loopt al. Ververs de pagina om te zien hoe ver hij is.",
    }
    bericht = MELDINGEN.get(request.args.get("m"))
    if request.method == "POST":
        hoeveel = int(request.form.get("hoeveel") or 0) or None
        gestart = opschonen.start_opschonen(hoeveel=hoeveel)
        return redirect("/admin/opschonen?m=" + ("gestart" if gestart else "loopt-al"))

    return render_template(
        "admin_opschonen.html",
        bericht=bericht,
        stand=opschonen.stand(),
        tel=db.opschoonstand(),
        onderhoudstand=onderhoud.stand(),
        wachtrij=db.categorieen_om_te_meten(onderhoud.MINIMUM,
                                            onderhoud.OPNIEUW_METEN_NA_DAGEN),
        nog_op_te_schonen=len(db.winkels_zonder_opschoning()),
        vervalt_na=onderhoud.OPNIEUW_METEN_NA_DAGEN,
    )


@app.route("/admin/ranglijst", methods=["GET", "POST"])
def admin_ranglijst():
    """Een categorie meten en de ranglijst bekijken.

    Dit is de eerste plek waar de nieuwe opzet zichtbaar wordt: een koopvraag
    wordt EEN keer gesteld en alle winkels in die categorie worden er tegelijk
    op gescoord. Wat eruit komt is geen cijfer maar een positie, en dat is wat
    er straks in de mail en op de openbare pagina staat.

    Meten gebeurt op een eigen draad. Dertig vragen aan twee modellen duurt een
    minuut of tien; aan een verzoek hangen levert een storing op, en die fout is
    op 11 en 13 september allebei al gemaakt."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    tel = categorieen.telling()
    bruikbaar = [r for r in tel["rijen"] if r["aantal"] >= tel["minimum"]]
    gekozen = request.values.get("categorie") or (bruikbaar[0]["categorie"] if bruikbaar else None)

    # NA EEN POST ALTIJD DOORSTUREN NAAR EEN GET. Zonder dit stuurt de browser
    # bij elke verversing hetzelfde formulier opnieuw op. Op 16 september zag
    # Nino daardoor een kwartier lang "bezig sinds 0 seconden": elke verversing
    # startte een nieuwe meting en gooide de vorige weg, en de foutmelding van
    # de mislukte poging kreeg hij nooit te zien. Erger nog: elke verversing kan
    # geld kosten.
    #
    # Dit is de klassieke oplossing: verwerk de POST, stuur door naar een GET,
    # en zet de melding in het webadres. Verversen is dan alleen nog kijken.
    MELDINGEN = {
        "gestart": ("De meting is gestart en draait op de achtergrond. Ververs deze "
                    "pagina over een paar minuten. Het tabblad mag dicht."),
        "loopt-al": "Er loopt al een meting. Ververs de pagina om te zien hoe ver hij is.",
        "vergelijk-gestart": ("De vergelijking is gestart. Ververs deze pagina over een "
                              "minuut, dan staat eronder wat eruit kwam."),
        "vergelijk-loopt-al": "Er loopt al een vergelijking. Ververs de pagina.",
        "herberekend": ("De ranglijst is opnieuw uitgerekend uit de antwoorden die "
                        "er al stonden. Dit heeft niets gekost."),
        "niets-te-herberekenen": ("Er is nog geen afgeronde meting van deze categorie, "
                                  "dus er valt niets te herberekenen."),
        "gesnoeid": ("De vragen die nooit een winkel opleverden staan uit. Bij de "
                     "volgende meting worden ze niet meer gesteld en komen er nieuwe "
                     "voor terug."),
        "niets-te-snoeien": ("Elke vraag leverde weleens een winkel op. Er hoefde "
                             "niets uit."),
    }
    bericht = MELDINGEN.get(request.args.get("m"))
    if request.args.get("m") == "herberekend" and request.args.get("winkels"):
        bericht += f" Er staan nu {request.args.get('winkels')} winkels in de lijst."

    def _terug(code, **extra):
        adres = f"/admin/ranglijst?categorie={gekozen or ''}&m={code}"
        for sleutel, waarde in extra.items():
            adres += f"&{sleutel}={waarde}"
        return redirect(adres)

    # Herberekenen: de ranglijst opnieuw uitrekenen uit de bewaarde antwoorden.
    # Nul modelaanroepen, nul euro, klaar in een seconde. Daarom mag dit wel in
    # het verzoek zelf en hoeft er geen draad aan te pas te komen.
    if request.method == "POST" and gekozen and request.form.get("actie") == "herbereken":
        uitkomst = categoriemeting.herbereken_ranglijst(gekozen)
        if uitkomst.get("fout"):
            return _terug("niets-te-herberekenen")
        return _terug("herberekend", winkels=uitkomst["winkels"])

    if request.method == "POST" and gekozen and request.form.get("actie") == "snoeien":
        uitkomst = categoriemeting.snoei_vragen(gekozen)
        return _terug("gesnoeid" if uitkomst["uitgezet"] else "niets-te-snoeien")

    if request.method == "POST" and gekozen and request.form.get("actie") == "vergelijk":
        # Het goedkope leesmodel naast het dure, op antwoorden die er al staan.
        # Geen enkele vraag wordt opnieuw gesteld, maar het zijn wel twintig
        # leesopdrachten en dat is te lang voor een verzoek. Dus op een eigen
        # draad, net als het meten zelf.
        # Een zelf ingetypte naam wint van de keuzelijst. Modelnamen verschillen
        # per aanbieder en per account, en op /admin/modellen staat wat deze
        # sleutels echt mogen gebruiken.
        kandidaat = categoriemeting.kandidaat_uit_naam(request.form.get("eigen_model"))
        if kandidaat is None:
            gekozen_model = (request.form.get("kandidaat") or "").strip()
            kandidaat = next((k for k in categoriemeting.KANDIDATEN
                              if k["model"] == gekozen_model), None)
        gestart = categoriemeting.start_vergelijking(gekozen, aantal=6, kandidaat=kandidaat)
        return _terug("vergelijk-gestart" if gestart else "vergelijk-loopt-al")

    # Meten gebeurt ALLEEN met een expliciete knop. Tot 16 september startte ook
    # het wisselen van categorie een meting, want dat keuzemenu stuurde hetzelfde
    # formulier op. Een ander product kiezen hoort niets te kosten.
    if request.method == "POST" and gekozen and request.form.get("actie") == "meten":
        vragen = int(request.form.get("vragen") or 0) or None
        gestart = categoriemeting.start_meting(
            gekozen, max_vragen=vragen, land=(request.form.get("land") or "").strip() or None)
        return _terug("gestart" if gestart else "loopt-al")

    lijst = db.laatste_ranglijst(gekozen) if gekozen else None
    return render_template(
        "admin_ranglijst.html",
        bericht=bericht,
        stand=categoriemeting.stand(),
        categorieen_lijst=bruikbaar,
        gekozen=gekozen,
        naam_van=categorieen.naam_van,
        ranglijst=lijst,
        ronde_kosten=db.kosten_van_ronde(lijst["ronde"]) if lijst and lijst.get("ronde") else None,
        vragen=db.categorie_vragen(gekozen) if gekozen else [],
        vraaglanden=list(vraaglanden.VRAAGLANDEN),
        # DROOGLOOP. Laat zien wie er bij de volgende nachtronde bericht zou
        # krijgen en waarom, zonder dat er ook maar iets verstuurd wordt. Zo kun
        # je de regels nakijken voordat er een echte klant iets in zijn inbox
        # krijgt, en een verkeerde mail kun je niet terughalen.
        berichten=(meldingen.na_meting(lijst["ronde"], gekozen, verstuur=False)
                   if lijst and lijst.get("ronde") else None),
        intenties=db.telbaarheid_per_intentie(gekozen) if gekozen else [],
        zwakke_vragen=db.vragen_die_nooit_meetelden(gekozen) if gekozen else [],
        vergelijking=categoriemeting.vergelijkstand(),
        kandidaten=categoriemeting.KANDIDATEN,
    )


@app.route("/admin/bezoek")
def admin_bezoek():
    """Hoeveel mensen er op de site komen, op welke pagina's, en waar vandaan.

    Dit is de pagina die naast /admin/bezoekers hoort en niet hetzelfde is.
    Daar staat wie een gratis scan DEED, hier staat wie er langskwam. Zonder dit
    tweede getal weet je bij nul verkopen niet welk probleem je hebt: komt er
    niemand, of komt er wel iemand en haakt die af. Dat zijn twee verschillende
    problemen met twee verschillende oplossingen, en tot vandaag was er geen
    enkel cijfer om ze uit elkaar te houden."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    dagen = int(request.args.get("dagen", 30))
    overzicht = db.bezoekoverzicht(dagen)
    totaal = overzicht["totaal"] or {}

    # De trechter over DEZELFDE periode als het bezoek, en niet over dertig
    # dagen. De scans en de betalingen bestaan al maanden, de bezoekersteller
    # staat pas sinds 12 september aan. Werden die twee over een verschillende
    # periode geteld, dan stond er negen bezoekers naast zesentwintig scans en
    # rekende de pagina daar vrolijk "1 op 0" uit. Een trechter waar de tweede
    # stap groter is dan de eerste is geen trechter.
    eerste = totaal.get("eerste")
    trechterdagen = dagen
    if eerste:
        gemeten = (datetime.now(timezone.utc) - eerste).days + 1
        trechterdagen = max(1, min(dagen, gemeten))
    scantotaal = (db.scanoverzicht(trechterdagen)["totaal"] or {})
    # 7 oktober (Nino): elke dag zien waar mensen heen gaan en afhaken.
    try:
        per_dag_trechter = db.trechter_volledig(14)
    except Exception as e:
        print(f"Trechter per dag mislukt: {e}")
        per_dag_trechter = []
    return render_template(
        "admin_bezoek.html",
        trechter_dag=per_dag_trechter,
        dagen=dagen,
        trechterdagen=trechterdagen,
        sinds=eerste,
        totaal=totaal,
        bezoeken=totaal.get("bezoeken") or 0,
        scans=scantotaal.get("scans") or 0,
        betaald=scantotaal.get("betaald") or 0,
        per_dag=overzicht["per_dag"],
        per_pagina=overzicht["per_pagina"],
        per_herkomst=overzicht["per_herkomst"],
        per_apparaat=overzicht["per_apparaat"],
    )


@app.route("/admin/kosten")
def admin_kosten():
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    dagen = int(request.args.get("dagen", 30))

    # Alleen op een knop, nooit vanzelf bij het openen van de pagina.
    #
    # Dit stond hier eerst bij elke keer laden, en dat heeft de hele site
    # platgelegd. Ook nu het snel is blijft het een opdracht die de database
    # aanpast, en zoiets hoort niet te gebeuren omdat iemand toevallig een
    # pagina opent. Een verversing in de browser is geen opdracht.
    hersteld = 0
    if request.args.get("herstel") == "ja":
        hersteld = db.herstel_onbekende_kosten(kosten.zoek_prijs)
        print(f"Kostenpagina: {hersteld} aanroepen alsnog van een prijs voorzien.")

    overzicht = db.kostenoverzicht(dagen)
    # 1 oktober: per agent, vandaag en de laatste week naast elkaar.
    vandaag_r = kosten.per_agent(1)
    week_r = kosten.per_agent(7)
    rijen = {}
    for r in week_r:
        rijen[r["soort"]] = {"naam": r["naam"], "eigen_agent": r["eigen_agent"], "vandaag": 0.0, "week": r["kosten"]}
    for r in vandaag_r:
        rijen.setdefault(r["soort"], {"naam": r["naam"], "eigen_agent": r["eigen_agent"], "week": r["kosten"]})
        rijen[r["soort"]]["vandaag"] = r["kosten"]
    return render_template(
        "admin_kosten.html",
        per_agent_vandaag=vandaag_r,
        per_agent_week=week_r,
        per_agent_rijen=sorted(rijen.values(), key=lambda r: (-r["vandaag"], -r["week"])),
        vandaag_totaal=sum(r["kosten"] for r in vandaag_r),
        eigen_rem=kosten.mag_eigen_agent(),
        weekgrenzen=[{"naam": kosten.naam_van(a) if a != "leeragent" else "Leeragent",
                      "week": kosten.week_van(a), "grens": g} for a, g in kosten.WEEKGRENS_EURO.items()],
        dagen=dagen,
        hersteld=hersteld,
        # Welk model er precies onbekend is. Zonder die naam weet je niet wat je
        # in kosten.py moet zetten.
        onbekende_modellen=db.onbekende_modellen(dagen),
        totaal=overzicht["totaal"],
        per_klant=overzicht["per_klant"],
        marges=kosten.marge_per_klant([
            dict(r, kosten=kosten.naar_maand(float(r.get("kosten") or 0), dagen))
            for r in overzicht["per_klant"]
        ]),
        abonnement=kosten.ABONNEMENT_PER_MAAND,
        per_model=overzicht["per_model"],
        grenzen={
            "scan_euro": kosten.GRENS_PER_SCAN_EURO,
            "scan_aanroepen": kosten.GRENS_PER_SCAN_AANROEPEN,
            "klant_maand": kosten.GRENS_PER_KLANT_MAAND_EURO,
            "dag_totaal": kosten.GRENS_TOTAAL_DAG_EURO,
            "pogingen": kosten.MAX_POGINGEN,
        },
    )


def _is_geleverd(order):
    """Heeft deze betaalde bestelling iets opgeleverd: een klantregel of een rapport?

    Maandbetalingen van een lopend abonnement dragen geen metadata van ons
    (type "onbekend"); die tellen we als geleverd, want daar hoort geen nieuwe
    klant bij."""
    if order.get("type") in (None, "", "onbekend") or order.get("webshop_url") in (None, "", "-"):
        return True
    try:
        if db.report_bestaat_al(order["id"]):
            return True
        return bool(db.klant_bij_url(scan_engine.normalize_url(order["webshop_url"])))
    except Exception as e:
        print(f"Levering nakijken mislukt voor {order.get('id')}: {e}")
        return True


def _betaling_opnieuw(payment_id):
    """Een betaalde bestelling opnieuw laten verwerken (27 september).

    Mollie stuurt een betaalde melding maar een keer als wij meteen 200
    antwoorden, en dat doen wij. Stopte de verwerking halverwege (een herstart
    van de server tijdens een upload, een storing), dan kwam er niets meer. Nu
    kan dat met een knop, en de nachtronde wijst je erop."""
    db.ontclaim_payment(payment_id)
    threading.Thread(target=_verwerk_betaling, args=(payment_id, get_base_url()),
                     daemon=True).start()


def _controleer_betalingen():
    """Nachtelijk: betaalde bestellingen van de laatste dagen zonder levering."""
    try:
        nu = datetime.now(timezone.utc)
        for o in payments.list_recent_orders(limit=50):
            if _is_geleverd(o):
                continue
            betaald = o.get("paid_at")
            try:
                betaald_op = datetime.fromisoformat(str(betaald).replace("Z", "+00:00"))
            except Exception:
                betaald_op = None
            # Pas na een uur melden: de verwerking kan nog bezig zijn. En niet
            # ouder dan vier dagen, anders elke nacht dezelfde melding.
            if betaald_op and not (timedelta(hours=1) < nu - betaald_op < timedelta(days=4)):
                continue
            _meld_aan_beheer(
                "Betaald maar nog niets geleverd",
                f"Bestelling {o['id']} ({o.get('type')}, {o.get('webshop_url')}, {o.get('email')}) "
                f"is betaald op {betaald}, maar er is geen klant of rapport. Ga naar "
                f"{get_base_url()}/admin/bestellingen en klik bij deze bestelling op "
                f"'Opnieuw verwerken'.")
    except Exception as e:
        print(f"Betalingen nakijken mislukt: {e}")


@app.route("/admin/verkoop", methods=["GET", "POST"])
def admin_verkoop():
    """De verkoopagent (stap 125): concepten goedkeuren of overslaan."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import verkoopagent as va
    melding = ""
    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        actie = request.form.get("actie")
        if actie == "versturen" and url:
            melding = "Verstuurd." if va.keur_goed(url, get_base_url().rstrip("/")) else "Versturen mislukt."
        elif actie == "overslaan" and url:
            va.sla_over(url)
            melding = "Overgeslagen."
        elif actie == "opnieuw" and url:
            va.schrijf_opnieuw(url)
            melding = "Weggegooid; klik op Nu een ronde draaien voor een nieuw concept."
        elif actie == "zelf_aan" and va.aantal_goedgekeurd() >= va.VRIJ_NA_GOEDGEKEURD:
            db.zet_instelling(va.SLEUTEL_ZELF, "ja")
            melding = "De verkoopagent verstuurt voortaan zelf, binnen kantooruren."
        elif actie == "zelf_uit":
            db.zet_instelling(va.SLEUTEL_ZELF, "nee")
            melding = "Zelf versturen staat uit. Alles wacht weer op jou."
        elif actie == "nu":
            verslag = va.ronde(get_base_url().rstrip("/"), lambda u: klantbeeld.bouw(u),
                               categorienaam=lambda b: categorieen.naam_en(b["categorie"]),
                               binnen_kantooruren=benadering.binnen_kantooruren())
            melding = f"Ronde gedraaid: {verslag['concepten']} nieuwe concepten, {verslag['verstuurd']} verstuurd."
    lijst = va.concepten()
    goed = va.aantal_goedgekeurd()
    winnaar = db.get_instelling(va.SLEUTEL_WINNAAR)
    regels = "".join(f"<tr><td>{escape(r['versie'])}</td><td>{r['verstuurd']}</td><td>{r['doorgeklikt']}</td>"
                     f"<td>{r['klant']}</td></tr>" for r in va.scorebord())
    bord = (f"<p>Twee versies van de uitleg lopen naast elkaar. Na {va.MIN_PER_VERSIE} briefjes per versie "
            f"en een duidelijk verschil kiest de agent zelf de winnaar. "
            f"{'Winnaar: versie ' + escape(winnaar) + '.' if winnaar else 'Nog geen winnaar.'}</p>"
            f"<table cellpadding='6' style='border-collapse:collapse'><tr><th>Versie</th><th>Verstuurd</th>"
            f"<th>Doorgeklikt</th><th>Klant</th></tr>{regels or '<tr><td colspan=4>Nog niets verstuurd.</td></tr>'}</table>")
    zelf = va.zelf_versturen()
    blokken = ""
    for c in lijst:
        k = c["concept"]
        tekst = "".join(f"<p>{a}</p>" for a in emailing.alina_s_veilig(k.get("alineas")))
        blokken += (
            f"<div style='border:1px solid #ddd;border-radius:10px;padding:16px 20px;margin:14px 0'>"
            f"<div style='font-size:13px;color:#666'>Aan {escape(c.get('email') or '')} &middot; "
            f"opvolging {int(c.get('opvolg_aantal') or 0) + 1} van 2 &middot; bekeken "
            f"{escape(str(c.get('bekeken_op'))[:16])}</div>"
            f"<div style='font-weight:700;margin:6px 0'>{escape(k.get('onderwerp') or '')}</div>"
            f"<div style='font-size:14.5px;line-height:1.55'>{tekst}"
            f"<p><a href='{escape(k.get('link') or '')}'>Open my Krillo page</a></p></div>"
            f"<form method='post' style='display:inline'><input type='hidden' name='url' value='{escape(c['webshop_url'])}'>"
            f"<button name='actie' value='versturen' style='padding:8px 14px;background:#1B3FE0;color:#fff;border:0;border-radius:6px'>Versturen</button> "
            f"<button name='actie' value='overslaan' style='padding:8px 14px'>Overslaan</button> "
            f"<button name='actie' value='opnieuw' style='padding:8px 14px'>Opnieuw schrijven</button></form></div>")
    if not blokken:
        blokken = "<p>Er wachten geen concepten. Zodra iemand zijn pagina bekijkt, komt hier binnen het uur een concept.</p>"
    schakelaar = (
        "<button name='actie' value='zelf_uit'>Zelf versturen UIT zetten</button>" if zelf else
        (f"<button name='actie' value='zelf_aan'>Laat de agent zelf versturen</button>"
         if goed >= va.VRIJ_NA_GOEDGEKEURD else
         f"<span>Zelf versturen kan na {va.VRIJ_NA_GOEDGEKEURD} goedgekeurde concepten ({goed} nu).</span>"))
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Verkoop | Krillo</title><body style='font-family:Arial,sans-serif;max-width:760px;"
            f"margin:40px auto;padding:0 16px;line-height:1.5'><h1>Verkoopagent</h1>"
            f"<p>Wie zijn Krillo-pagina bekeek, krijgt een persoonlijke opvolging (hoogstens twee). "
            f"Stand: <strong>{'verstuurt zelf' if zelf else 'wacht op jouw goedkeuring'}</strong>.</p>"
            f"<p style='color:#0B7C5E'>{escape(melding)}</p>"
            f"<form method='post'>{schakelaar} <button name='actie' value='nu'>Nu een ronde draaien</button></form>"
            f"<p><a href='/admin/antwoorden'>Antwoorden van winkels</a></p>"
            f"<h2 style='margin-top:28px'>Scorebord</h2>{bord}"
            f"<h2 style='margin-top:28px'>Concepten ({len(lijst)})</h2>{blokken}</body>")


@app.route("/admin/antwoorden", methods=["GET", "POST"])
def admin_antwoorden():
    """De antwoordagent (stap 126): wie terugmailde, met een concept-antwoord."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import antwoordagent as aa
    basis = get_base_url().rstrip("/")
    melding = ""
    if request.method == "POST":
        actie = request.form.get("actie")
        try:
            nr = int(request.form.get("id") or 0)
        except ValueError:
            nr = 0
        if actie == "versturen" and nr:
            melding = ("Verstuurd." if aa.verstuur(nr, request.form.get("tekst") or "")
                       else "Versturen mislukt (leeg, al verstuurd, of Brevo weigerde).")
        elif actie == "klaar" and nr:
            aa.klaar(nr)
            melding = "Op klaar gezet, er gaat niets uit."
        elif actie == "uit_index":
            # 30 september (bel-air.be): "wij zijn geen webshop". Meteen uit elke
            # ranglijst en uit de post, en nooit meer gemaild.
            import categoriecheck
            url = (request.form.get("url") or "").strip()
            if url:
                gevonden = categoriecheck.zet_uit_index(url)
                db.vergeet_onthouden()
                melding = (f"Uit de index en uit de post: {', '.join(gevonden)}. Krijgt nooit meer mail van ons."
                           if gevonden else
                           f"{url} stond niet in onze lijst. Wel afgemeld, zodat hij er ook later niet in komt.")
        elif actie == "koppelen":
            _, melding = aa.koppel_brevo(basis, (os.environ.get("BREVO_WEBHOOK_SLEUTEL") or "").strip(),
                                         request.form.get("domein") or None)
        elif actie == "test":
            doel = f"test@{aa.domein()}"
            melding = (f"Testmail verstuurd naar {doel}. Ververs deze pagina over een minuut: "
                       f"hij moet hieronder staan als 'test'." if emailing.send_email(
                           doel, aa.TEST_ONDERWERP, "<p>Test van de antwoordagent.</p>")
                       else "Testmail versturen mislukt.")
    rijen = aa.lijst()
    kleur = {"concept": "#1B3FE0", "afgemeld": "#B42318", "verstuurd": "#0B7C5E"}
    blokken = ""
    for r in rijen:
        try:
            from zoneinfo import ZoneInfo
            tijd = r["ontvangen_op"].astimezone(ZoneInfo("Europe/Amsterdam")).strftime("%d-%m %H:%M")
        except Exception:
            tijd = str(r["ontvangen_op"])[:16]
        kop = (f"<div style='font-size:13px;color:#666'>{escape(tijd)} &middot; "
               f"{escape(r.get('naam') or '')} &lt;{escape(r['van'])}&gt; &middot; "
               f"{escape(r.get('webshop_url') or 'winkel onbekend')} &middot; soort <strong>{escape(r.get('soort') or '')}"
               f"</strong> &middot; <span style='color:{kleur.get(r['stand'], '#666')}'>{escape(r['stand'])}</span></div>"
               f"<div style='font-weight:700;margin:6px 0'>{escape(r.get('onderwerp') or '')}</div>"
               f"<div style='white-space:pre-wrap;background:#F4F5F8;padding:10px 12px;border-radius:8px;"
               f"font-size:14px'>{escape(r.get('tekst') or '')}</div>")
        if r["stand"] == "concept":
            kop += (f"<form method='post' style='margin-top:10px'><input type='hidden' name='id' value='{r['id']}'>"
                    f"<div style='font-size:13px;color:#666;margin-bottom:4px'>Concept-antwoord (pas gerust aan; "
                    f"de handtekening met je naam en Krillo komt er vanzelf onder):</div>"
                    f"<textarea name='tekst' rows='9' style='width:100%;font:inherit;font-size:14px;padding:8px'>"
                    f"{escape(r.get('concept') or '')}</textarea><br>"
                    f"<button name='actie' value='versturen' style='padding:8px 14px;background:#1B3FE0;color:#fff;"
                    f"border:0;border-radius:6px'>Versturen</button> "
                    f"<button name='actie' value='klaar' style='padding:8px 14px'>Zelf afgehandeld</button></form>"
                    + (f"<form method='post' style='margin-top:6px'><input type='hidden' name='url' "
                       f"value='{escape(r['webshop_url'])}'><button name='actie' value='uit_index' "
                       f"style='padding:6px 12px;font-size:13px'>Geen webshop of verkeerde categorie: "
                       f"uit de index halen</button></form>" if r.get("webshop_url") else ""))
        elif r["stand"] == "verstuurd" and r.get("concept"):
            kop += (f"<div style='font-size:13px;color:#666;margin-top:8px'>Ons antwoord:</div>"
                    f"<div style='white-space:pre-wrap;font-size:14px'>{escape(r['concept'])}</div>")
        blokken += f"<div style='border:1px solid #ddd;border-radius:10px;padding:14px 18px;margin:14px 0'>{kop}</div>"
    wacht = sum(1 for r in rijen if r["stand"] == "concept")
    gekoppeld = db.get_instelling("antwoord_gekoppeld")
    reply = (os.environ.get("SMTP_REPLY_TO") or "").strip()
    stand = ("gekoppeld aan " + escape(aa.domein())) if gekoppeld else "nog niet gekoppeld"
    reply_ok = reply.lower().endswith("@" + aa.domein())
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Antwoorden | Krillo</title><body style='font-family:Arial,sans-serif;max-width:760px;"
            f"margin:40px auto;padding:0 16px;line-height:1.5'><h1>Antwoordagent</h1>"
            f"<p>Wie op een mail van ons antwoordt, komt hier. Afmelden gaat vanzelf; al het andere krijgt "
            f"een concept dat pas weggaat als jij op Versturen drukt.</p>"
            f"<p>Brevo: <strong>{stand}</strong>. Antwoordadres in Render (SMTP_REPLY_TO): "
            f"<strong>{escape(reply) or 'niet ingevuld'}</strong>"
            f"{'' if reply_ok else ' (antwoorden komen nog NIET hier)'}.</p>"
            f"<p style='color:#0B7C5E'>{escape(melding)}</p>"
            f"<form method='post'>Domein <input name='domein' value='{escape(aa.domein())}' size='18'> "
            f"<button name='actie' value='koppelen'>Koppel bij Brevo</button> "
            f"<button name='actie' value='test'>Stuur een testmail</button></form>"
            f"<p style='margin-top:10px'><a href='/admin/verkoop'>Naar de verkoopagent</a></p>"
            # 30 september: bel-air.be mailde naar Nino's eigen inbox en stond dus niet
            # hieronder, waardoor de knop per antwoord er niet was. Dit veld werkt altijd.
            f"<h2 style='margin-top:28px'>Een site uit de index halen</h2>"
            f"<form method='post'><p style='margin:0 0 6px'>Geen webshop, of een fout in de categorie? Typ het "
            f"adres zoals je het ziet (bijvoorbeeld bel-air.be). Hij gaat uit elke ranglijst en krijgt nooit "
            f"meer post.</p><input name='url' placeholder='bel-air.be' size='28' required> "
            f"<button name='actie' value='uit_index'>Uit de index halen</button></form>"
            f"<h2 style='margin-top:28px'>Binnengekomen ({wacht} wachten op jou)</h2>"
            f"{blokken or '<p>Nog niets binnengekomen.</p>'}</body>")


@app.route("/admin/formulieren", methods=["GET", "POST"])
def admin_formulieren():
    """Stap 156: winkels zonder info@ maar met een contactformulier. Het bericht
    staat klaar; Nino plakt het er met de hand in. Bewust niet automatisch
    (captcha's, en een machine die formulieren invult is spam)."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import verkoopagent as va
    melding = ""
    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        if url and db.markeer_formulier_gedaan(url):
            melding = f"{url} afgevinkt." if request.form.get("actie") == "gedaan" else f"{url} overgeslagen."
    basis = get_base_url().rstrip("/")
    blokken = ""
    import ochtendbericht
    vandaag = ochtendbericht._tel("SELECT count(*) FROM benadering WHERE formulier_op >= date_trunc('day', now())") or 0
    for w in db.formulier_winkels(limiet=max(0, FORMULIEREN_PER_DAG - vandaag)):
        url = w["webshop_url"]
        try:
            beeld = klantbeeld.bouw(url)
        except Exception:
            beeld = None
        token = db.get_benchmark_token(url)
        bericht = va.formulier_bericht(
            beeld, va._vraag_voor(url, beeld) if beeld else None,
            link_url=f"{basis}/uitkomst/{token}" if token else basis,
            categorienaam=categorieen.naam_en(beeld["categorie"]) if beeld else None)
        if not bericht:
            continue
        blokken += (
            f"<div style='border:1px solid #ddd;border-radius:10px;padding:14px 18px;margin:14px 0'>"
            f"<div style='font-weight:700'>{escape(url)} &middot; #{escape(str(w.get('positie')))}</div>"
            f"<p style='margin:6px 0'><a href='{escape(w['formulier_url'])}' target='_blank' rel='noopener'>"
            f"1. Open het contactformulier</a> &middot; 2. Kopieer dit bericht &middot; 3. Vul als naam "
            f"Nino en als mail hello@krilloai.com in</p>"
            f"<textarea readonly rows='11' style='width:100%;font:inherit;font-size:14px;padding:8px' "
            f"onclick='this.select()'>{escape(bericht)}</textarea>"
            f"<form method='post' style='margin-top:8px'><input type='hidden' name='url' value='{escape(url)}'>"
            f"<button name='actie' value='gedaan' style='padding:8px 14px;background:#1B3FE0;color:#fff;border:0;"
            f"border-radius:6px'>Geplakt en verstuurd</button> "
            f"<button name='actie' value='overslaan' style='padding:8px 14px'>Overslaan</button></form></div>")
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Formulieren | Krillo</title><body style='font-family:Arial,sans-serif;max-width:760px;"
            f"margin:40px auto;padding:0 16px;line-height:1.5'><h1>Contactformulieren</h1>"
            f"<p>Winkels zonder info@ maar met een contactformulier en een plek in de index. Het bericht "
            f"staat klaar. Hoogstens {FORMULIEREN_PER_DAG} per dag: dit is handwerk, en zo blijft het "
            f"persoonlijk.</p><p style='color:#0B7C5E'>{escape(melding)}</p>"
            f"{blokken or ('<p>Voor vandaag gedaan. Morgen staan er nieuwe klaar.</p>' if vandaag >= FORMULIEREN_PER_DAG else '<p>Er staan nu geen winkels klaar. De adresvinder vult dit vanzelf aan.</p>')}</body>")


FORMULIEREN_PER_DAG = int(os.environ.get("FORMULIEREN_PER_DAG", "5"))


@app.route("/admin/merken", methods=["GET", "POST"])
def admin_merken():
    """Winkels met een adres die het opschonen als merk of platform aanmerkte,
    en daarom geen post krijgen (28 september: 59 merken, 5 platforms). Een
    merk met een eigen webshop hoort er wel bij; met een klik zet je hem terug."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import bewegingsagent as sa  # alleen voor de kleine _sql-hulp
    melding = ""
    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        if url and request.form.get("actie") == "winkel":
            db.zet_soort(url, "winkel")
            melding = f"{url} is weer een winkel en kan post krijgen."
    rijen = sa._sql("""SELECT webshop_url, soort, email, categorie FROM benadering
                        WHERE stand IN ('adres', 'meten', 'gemeten') AND coalesce(soort, 'winkel') <> 'winkel'
                          AND NOT afgemeld ORDER BY soort, webshop_url""", alles=True) or []
    regels = "".join(
        f"<tr><td><a href='{escape(r['webshop_url'])}' target='_blank' rel='noopener'>{escape(r['webshop_url'])}</a></td>"
        f"<td>{escape(r['soort'] or '')}</td><td>{escape(r.get('categorie') or '')}</td>"
        f"<td><form method='post' style='margin:0'><input type='hidden' name='url' value='{escape(r['webshop_url'])}'>"
        f"<button name='actie' value='winkel'>Is toch een winkel</button></form></td></tr>" for r in rijen)
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Merken | Krillo</title><body style='font-family:Arial,sans-serif;max-width:900px;"
            f"margin:40px auto;padding:0 16px;line-height:1.5'><h1>Merken en platforms ({len(rijen)})</h1>"
            f"<p>Deze hebben een adres maar krijgen geen post, omdat ze als merk of platform zijn aangemerkt. "
            f"Open de site: verkoopt hij zelf online aan kopers, dan is het een winkel.</p>"
            f"<p style='color:#0B7C5E'>{escape(melding)}</p><table cellpadding='6' style='border-collapse:collapse'>"
            f"<tr style='text-align:left'><th>Site</th><th>Soort</th><th>Categorie</th><th></th></tr>{regels}</table></body>")


@app.route("/badge/<token>.svg")
def badge_plaatje(token):
    """De badge (stap 89). Bij elke weergave uit de laatste meting, dus nooit
    een oude plek. Onbekend kenmerk: de neutrale badge, zodat een geplakte code
    nooit een kapot plaatje op de site van een winkel laat zien."""
    import badgeagent
    gegevens = None
    try:
        url = db.winkel_bij_benchmark_token(token)
        if url:
            beeld = klantbeeld.bouw(url)
            gegevens = badgeagent.badge_gegevens(
                beeld, categorieen.naam_en(beeld["categorie"]) if beeld else None)
            # Bijhouden dat hij op een site staat (en waar), als bewijs dat het werkt.
            bron = (request.headers.get("Referer") or "")[:200]
            if bron and "krilloai.com" not in bron:
                badgeagent._sql("UPDATE benadering SET badge_gezien_op = now(), badge_gezien_bij = %s "
                                "WHERE webshop_url = %s", (bron, url))
    except Exception as e:
        print(f"Badge opbouwen mislukt: {e}")
    antwoord = app.response_class(badgeagent.badge_svg(gegevens), mimetype="image/svg+xml")
    antwoord.headers["Cache-Control"] = "public, max-age=21600"
    return antwoord


@app.route("/admin/ochtendbericht")
def admin_ochtendbericht():
    """Het ochtendbericht (stap 132) nu bekijken, zonder op de ochtend te wachten."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import ochtendbericht
    onderwerp, body = ochtendbericht.tekst(ochtendbericht.verzamel(get_base_url().rstrip("/")))
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Ochtendbericht | Krillo</title><body style='margin:40px auto;max-width:640px;padding:0 16px'>"
            f"<p style='font-family:Arial,sans-serif;color:#666'>Onderwerp: {escape(onderwerp)}</p>{body}</body>")


@app.route("/admin/controle", methods=["GET", "POST"])
def admin_controle():
    """De uitkomst van de controleagent, en een knop om hem nu te draaien."""
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    import nachtcontrole
    index_bezig = False
    if request.method == "POST" and request.form.get("actie") == "index":
        # 2 oktober: de indexcontrole nu draaien, op de achtergrond (hij loopt
        # alle categorieen langs). Zonder onthouden, zoals in de nacht.
        import nachtagenten

        def _index_nu():
            db.onthouden_pauze(True)
            try:
                nachtagenten.draai(None)
            finally:
                db.onthouden_pauze(False)
        threading.Thread(target=_index_nu, daemon=True).start()
        index_bezig = True
    if request.method == "POST" and request.form.get("actie") != "index":
        uit = nachtcontrole.draai(app, lambda kop, tekst: None)
    else:
        try:
            uit = json.loads(db.get_instelling("nachtcontrole") or "null")
        except Exception:
            uit = None
    rijen = "".join(f"<li style='color:#9B1C1C'>{escape(f)}</li>" for f in (uit or {}).get("fout", []))
    rijen += "".join(f"<li style='color:#0B7C5E'>{escape(g)}</li>" for g in (uit or {}).get("goed", []))
    kop = ("Nog nooit gedraaid." if not uit else
           f"Laatste controle {escape(uit.get('op', '')[:16])}: {len(uit.get('fout', []))} fout, "
           f"{len(uit.get('goed', []))} goed.")
    # Stap 97, 100 en 38: de nachtagenten en de tegengehouden mails.
    try:
        na = json.loads(db.get_instelling("nachtagenten") or "{}")
        afgekeurd = json.loads(db.get_instelling("tekstkeuring_afgekeurd") or "[]")
    except Exception:
        na, afgekeurd = {}, []
    # str(): een Markup erbij optellen escapet de rest van de pagina (2 okt, zo gezien).
    datum = str(escape(na.get("datum") or "nog nooit"))
    rijen += ("<h2>Kwaliteit van de index</h2><p>Laatst gedraaid: " + datum + ". "
              + ("<b>Gestart; ververs over een paar minuten.</b>" if index_bezig else "")
              + "</p><form method='post'><input type='hidden' name='actie' value='index'>"
              "<button style='padding:8px 14px'>Indexcontrole nu draaien</button></form><ul>" + ("".join(f"<li>{escape(f)}</li>" for f in na.get("kwaliteit") or [])
              or "<li>Niets gevonden.</li>") + "</ul><h2>Concurrenten (elke maandag)</h2><ul>"
              + ("".join(f"<li>{escape(f)}</li>" for f in na.get("concurrenten") or []) or "<li>Alle bedragen op /compare kloppen nog.</li>")
              + "</ul><h2>Tegengehouden door de controleagent</h2><ul>"
              + ("".join(f"<li>{escape(a.get('op', ''))} {escape(a.get('wat', ''))}: {escape(a.get('onderwerp') or '')} "
                         f"({escape('; '.join(a.get('fouten') or []))})</li>" for a in reversed(afgekeurd))
                 or "<li>Niets tegengehouden.</li>") + "</ul>")
    return (f"<!doctype html><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>Controle | Krillo</title><body style='font-family:Arial,sans-serif;max-width:760px;"
            f"margin:40px auto;padding:0 16px;line-height:1.6'><h1>Nachtcontrole</h1><p>{kop}</p>"
            f"<form method='post'><button style='padding:8px 14px'>Nu controleren</button></form>"
            f"<ul>{rijen}</ul></body>")


@app.route("/admin/bestellingen", methods=["GET", "POST"])
def admin_bestellingen():
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    melding = None
    if request.method == "POST":
        pid = (request.form.get("payment_id") or "").strip()
        if re.fullmatch(r"tr_[A-Za-z0-9]+", pid):
            _betaling_opnieuw(pid)
            melding = f"Betaling {pid} wordt opnieuw verwerkt. Ververs over een minuut."
        else:
            melding = "Dat is geen geldig betalingsnummer."
    orders = payments.list_recent_orders()
    for o in orders:
        o["geleverd"] = _is_geleverd(o)
    return render_template("admin_bestellingen.html", orders=orders, melding=melding)


@app.route("/admin/uitvoeringen", methods=["GET", "POST"])
def admin_uitvoeringen():
    """De werklijst voor "wij voeren het uit".

    Zolang dit handwerk is, is dit de belangrijkste pagina van het hele systeem:
    hier staat wie betaald heeft en nog zit te wachten. Een klant die betaalt en
    daarna niets hoort is erger dan een klant die nooit betaalt."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    melding = None
    if request.method == "POST":
        uitvoering_id = request.form.get("id")
        stand = (request.form.get("stand") or "").strip()
        notitie = (request.form.get("notitie") or "").strip() or None
        if uitvoering_id and db.zet_uitvoering_stand(uitvoering_id, stand, notitie):
            melding = "Opgeslagen."
        else:
            melding = "Dat is niet gelukt. Controleer de stand."

    return render_template(
        "admin_uitvoeringen.html",
        uitvoeringen=db.get_uitvoeringen(),
        standen=db.UITVOERING_STANDEN,
        standtekst=db.UITVOERING_STAND_TEKST,
        melding=melding,
        sleutel=admin_key,
    )


# ---------------------------------------------------------------------------
# De Shopify-app
# ---------------------------------------------------------------------------
#
# Stap 1: installeren en de verplichte webhooks. Nog geen scherm met cijfers en
# nog geen betaling; die komen in de volgende stappen. Dit stuk moet eerst
# kloppen, want zonder een geldige installatie en zonder die webhooks komt de
# app de beoordeling van Shopify niet door.


# Waar de meting van een Shopify-winkel is. Alleen in het geheugen: na een
# herstart van Render is dit leeg, en dan ziet de winkelier gewoon de laatste
# uitkomst uit de database. De echte gegevens staan nooit alleen hier.
_shopify_status = {}


def _shopify_meten(winkel, webshop_url, email=None):
    """Scant de winkel en meet daarna bij ChatGPT en Gemini.

    Draait op de achtergrond, want dit duurt minuten. De winkelier ziet
    ondertussen waar we zijn.

    Bewust dezelfde keten als bij een betalende monitoringklant, zodat een
    winkel via Shopify en een winkel via krillo.nl nooit iets anders te zien
    krijgen bij dezelfde uitkomst."""
    def melden(tekst, klaar=False):
        _shopify_status[winkel] = {"tekst": tekst, "klaar": klaar,
                                   "mislukt": False}
        print(f"Shopify {winkel}: {tekst}")

    try:
        melden("je winkel doorlezen")
        resultaat = run_scan(webshop_url)
        if "error" in resultaat:
            _shopify_status[winkel] = {
                "tekst": "We konden je winkel niet inlezen. Staat er een wachtwoord op?",
                "klaar": True, "mislukt": True}
            return

        db.zet_platform(resultaat["url"], "Shopify")
        # Het e-mailadres MOET mee. De rapportentabel eist het, en zonder
        # rapport is er geen verklaring, en zonder verklaring blijft het
        # actieplan leeg terwijl er wel gemeten is. Dat ging hier eerst mis en
        # het viel alleen op in de logs, niet op het scherm.
        db.save_report("shopify", resultaat["url"], email or f"shopify@{winkel}",
                       resultaat.get("score", 0), resultaat.get("checks", []))
        _meet_en_beoordeel(resultaat["url"], stap=lambda t: melden(t))
        melden("klaar", klaar=True)
    except Exception as e:
        print(f"Shopify-meting mislukt voor {winkel}: {e}")
        _shopify_status[winkel] = {
            "tekst": "Er ging iets mis bij het meten. Probeer het zo nog eens.",
            "klaar": True, "mislukt": True}


# De voortgangsteksten in het Engels.
#
# Waarom een tabel en niet overal een taalparameter: die teksten worden gemaakt
# in de meetketen, en die keten is gedeeld met krillo.nl en met de wekelijkse
# ronde. Zou die keten talen moeten kennen, dan moet elke stap in elk bestand
# aangepast worden, en dan gaat er ergens eentje mis. Nu vertalen wij op één
# plek: vlak voordat het scherm het te zien krijgt.
#
# Staat een tekst hier niet in, dan gaat hij onvertaald door. Dat is met opzet:
# liever een Nederlandse regel dan een lege balk of een foutmelding.
STAND_ENGELS = {
    "werk onderbroken": "The check was interrupted. Please click Check my store again.",
    "we beginnen": "starting",
    "je winkel doorlezen": "reading your store",
    "koopvragen maken": "writing shopping questions",
    "vragen stellen aan AI": "asking the AI assistants",
    "antwoorden beoordelen": "reading the answers",
    "uitspraken controleren": "checking what they say about you",
    "externe bronnen zoeken": "looking for pages you are missing from",
    "actieplan klaarzetten": "putting your plan together",
    "we kijken je winkel na": "checking your store",
    "klaar": "done",
    "We konden je winkel niet inlezen. Staat er een wachtwoord op?":
        "We could not read your store. Is it password protected?",
    "Er ging iets mis bij het meten. Probeer het zo nog eens.":
        "Something went wrong while measuring. Please try again in a moment.",
    "Er ging iets mis bij het nakijken van je winkel.":
        "Something went wrong while checking your store.",
}


# Wat een Engelse winkelier ziet als er iets misgaat en wij de reden niet
# kunnen vertalen. De reden zelf komt uit de kostenrem of uit de meetketen en
# staat in het Nederlands, met bedragen en interne begrippen erin. Die laten wij
# bewust weg in plaats van hem onvertaald te tonen: een halve Nederlandse zin op
# een Engels scherm is erger dan een net gebrek aan detail. In de logboeken
# staat de echte reden wel, dus wij kunnen het altijd nazoeken.
MISLUKT_ENGELS = "Something went wrong. Please try again in a moment."


def _stand_in_taal(stand, markt):
    """De voortgangstekst in de taal van de winkel.

    Een Engelse winkelier las "Working: vragen stellen aan AI" op zijn eigen
    beheerscherm. Dat is precies het soort detail waaraan je ziet dat een app
    niet af is."""
    # Sinds 23 september ALTIJD Engels, ook voor een Nederlandse winkel: het
    # app-scherm is Engels (een adres, een taal).
    if not stand:
        return stand
    uit = dict(stand)
    tekst = stand.get("tekst")
    vertaald = STAND_ENGELS.get(tekst)
    if vertaald is None and tekst:
        # Niet in de tabel. Zit er een reden achter, dan is dat vrije
        # Nederlandse tekst uit de rem of uit de meetketen. Die tonen wij niet.
        vertaald = MISLUKT_ENGELS if str(tekst).startswith("mislukt") else tekst
    uit["tekst"] = vertaald
    return uit


def _voorstel_voor_scherm(voorstel, markt=None):
    """Een voorstel klaarmaken om te tonen.

    De HTML-versie gaat er bewust uit: die hoeft het scherm niet te weten en
    het scheelt een hoop overbodig verkeer."""
    if not voorstel:
        return None
    uit = {k: v for k, v in voorstel.items() if k != "nieuw_html"}
    woord = _wijziging_soort_woord(voorstel.get("id"), markt)
    if woord:
        uit["wat"] = woord
    uit["nieuw"] = _zonder_opmaak(uit.get("nieuw"))
    uit["oud"] = _zonder_opmaak(uit.get("oud"))
    return uit


def _voorstellen_per_plan(voorstellen, plan, gratis_over):
    """Wat elk plan van de voorstellen te zien krijgt.

    26 september: Watch belooft "every fix written out, ready to copy", maar een
    gratis winkel zag precies dezelfde teksten. Dan koop je met Watch niets
    extra's aan fixes, en die belofte is dan lucht. De trap is nu:
      Fix:    alles, en alles met een klik in de winkel.
      Watch:  alles uitgeschreven om over te nemen (Copy-knop), plus de
              gratis wijzigingen met een klik, net als iedereen.
      Gratis: de teksten van de wijzigingen die hij nog gratis krijgt. Van de
              rest ziet hij WAAR het ontbreekt, niet de tekst.
    De tekst van wat op slot staat gaat niet mee naar de browser: vaag maken
    met CSS laat hem gewoon in de broncode staan. Zijn eigen oude tekst ("oud")
    mag wel mee, die staat al in zijn winkel."""
    if plan in ("fix", "watch"):
        return voorstellen
    open_ = max(0, int(gratis_over or 0))
    uit = []
    for i, v in enumerate(voorstellen):
        if not v:
            continue
        if i < open_:
            uit.append(v)
        else:
            uit.append({k: w for k, w in v.items() if k != "nieuw"} | {"slot": True})
    return uit


def _voorstel_uit_wijziging(wijziging):
    """Bouwt een voorstel terug uit een teruggezette wijziging.

    Nodig als de app tussendoor opnieuw opgestart is en de voorstellen uit het
    geheugen weg zijn. Alles wat pas_toe nodig heeft staat in het kenmerk:
    "shopify:alt:<product>:<foto>", "shopify:tekst:<product>" of
    "shopify:faq"."""
    delen = (wijziging.get("taak_id") or "").split(":")
    if len(delen) < 2 or delen[0] != "shopify":
        return None
    soort = delen[1]
    nieuw = wijziging.get("nieuwe_waarde") or ""
    voorstel = {"id": wijziging["taak_id"], "soort": soort,
                "wat": wijziging.get("wat"), "waar": wijziging.get("waar"),
                "oud": wijziging.get("oude_waarde") or "",
                "nieuw": _zonder_opmaak(nieuw), "nieuw_html": nieuw}
    try:
        if soort == "alt" and len(delen) >= 4:
            voorstel["product_id"] = int(delen[2])
            voorstel["afbeelding_id"] = int(delen[3])
            voorstel["nieuw"] = nieuw
            voorstel.pop("nieuw_html", None)
        elif soort == "tekst" and len(delen) >= 3:
            voorstel["product_id"] = int(delen[2])
        elif soort not in ("faq", "llms"):
            return None
    except ValueError:
        return None
    return voorstel


def _zonder_opmaak(tekst):
    """Haalt de HTML eruit, zodat er tekst op het scherm komt en geen code.

    Wij bewaren de HTML wel, want die moet ongewijzigd terug de winkel in
    kunnen bij het terugzetten. Alleen bij het TONEN hoort hij weg."""
    if not tekst:
        return ""
    kaal = re.sub(r"<br\s*/?>|</p>|</h[1-6]>", " ", str(tekst), flags=re.I)
    kaal = re.sub(r"<[^>]+>", "", kaal)
    # Alle HTML-tekens terug naar gewone tekens. Hier stond een eigen lijstje
    # (&amp; &lt; ...), en daar ontbrak &#x27;: op 26 september stond er
    # "extra&#x27;s" op het scherm in plaats van "extra's".
    import html as _html
    kaal = _html.unescape(kaal).replace("\xa0", " ")
    return re.sub(r"\s+", " ", kaal).strip()


def _wijziging_soort_woord(taak_id, markt):
    """Het soort wijziging, in de taal van de winkel van nu.

    Het kenmerk ziet eruit als "shopify:tekst:123". Dat middelste woord is het
    enige wat in een vaste taal vastligt, dus daar rekenen wij mee, en niet met
    het woord dat ooit is opgeslagen."""
    delen = (taak_id or "").split(":")
    if len(delen) < 2:
        return None
    sleutel = {"alt": "alt", "tekst": "tekst", "faq": "faq", "llms": "llms"}.get(delen[1])
    if not sleutel:
        return None
    return shopify_werk._label(markt, sleutel)


def _app_adres_in_beheerscherm(winkel):
    """Het adres waarop deze app in het beheerscherm van de winkelier staat.

    Dit is waar wij hem naartoe sturen nadat hij bij Shopify betaald heeft, en
    nadat het installeren klaar is.

    Waarom via de winkel zelf en niet via admin.shopify.com/store/x/apps/naam:
    dat laatste adres hangt aan de naam die de app in de winkel heeft, en die
    naam kennen wij niet met zekerheid. Klopt hij niet, dan krijgt de winkelier
    een 404 direct nadat hij akkoord is gegaan met 55 dollar per maand. Dat is
    het slechtst denkbare moment voor een lege pagina.

    Het adres hieronder werkt met ons eigen klantnummer bij Shopify. Dat weten
    wij altijd, want zonder dat nummer draait de app helemaal niet. Shopify
    zoekt er zelf de juiste app bij en stuurt door naar het nieuwe
    beheerscherm."""
    api_key = (os.environ.get("SHOPIFY_API_KEY") or "").strip()
    if api_key:
        return f"https://{winkel}/admin/apps/{api_key}"
    # Zonder klantnummer draait er niets, maar dan liever de appslijst dan een
    # kapot adres.
    winkelnaam_kort = winkel.replace(".myshopify.com", "")
    print("LET OP: SHOPIFY_API_KEY ontbreekt, terugkeer gaat naar de appslijst.")
    return f"https://admin.shopify.com/store/{winkelnaam_kort}/apps"


_voorbeeld_cache = {"op": 0.0, "waarde": None}
VOORBEELD_BEWAAR_SECONDEN = 600


def _voorbeeld_voor_app():
    """Het voorbeeld, maar hooguit eens per tien minuten opnieuw berekend.

    26 september: de app deed er rond 30 seconden over om te openen. Het
    voorbeeld is voor iedere winkel zonder positie hetzelfde en verandert
    alleen na een maandmeting. Elke keer opnieuw bouwen (ranglijst van 500,
    alle antwoorden van een ronde doorlopen) is dus zonde van de wachttijd."""
    nu = time.monotonic()
    if _voorbeeld_cache["waarde"]:
        # Is hij oud, dan geven we hem toch meteen en bouwen we op de
        # achtergrond een nieuwe (27 september: de log liet 4,6 seconden zien
        # voor het voorbeeld, bij de eerste opening na een herstart).
        if nu - _voorbeeld_cache["op"] >= VOORBEELD_BEWAAR_SECONDEN and not _voorbeeld_cache.get("bezig"):
            _voorbeeld_cache["bezig"] = True
            _SNEL_POOL.submit(_voorbeeld_verversen)
        return _voorbeeld_cache["waarde"]
    return _voorbeeld_verversen()


def _voorbeeld_verversen():
    try:
        waarde = _voorbeeld_bouwen()
        if waarde:
            _voorbeeld_cache.update(op=time.monotonic(), waarde=waarde)
        return waarde
    finally:
        _voorbeeld_cache["bezig"] = False


def _voorbeeld_opwarmen():
    """Bij het opstarten van de server alvast het voorbeeld bouwen.

    Alleen op Render (daar staat RENDER=true), niet in de tests: die tellen hoe
    vaak het voorbeeld gebouwd wordt."""
    time.sleep(3)
    try:
        _voorbeeld_verversen()
    except Exception as e:
        print(f"Voorbeeld opwarmen mislukt: {e}")


def _voorbeeld_bouwen():
    """Een ECHTE winkel uit de index, als voorbeeld voor wie nog geen positie heeft.

    WAAROM (24 september). Een nieuwe installatie ziet eerst een leeg blok:
    "je positie komt eraan" of "we meten jouw markt nog niet". Dan heeft de
    winkelier niets om naar te kijken en snapt hij niet wat hij krijgt. Nu
    zien ze eronder hoe het scherm eruitziet met echte cijfers, van een echte
    winkel, duidelijk als voorbeeld gemarkeerd. Dezelfde winkel als /demo op
    de site; de cijfers staan ook op de openbare ranglijst, dus niets geheims."""
    try:
        keuze = db.voorbeeldwinkel()
        if not keuze:
            return None
        vb = klantbeeld.bouw(keuze["webshop_url"], land=keuze.get("land"))
        if not vb:
            return None
        vb = dict(vb)
        vb["categorienaam"] = categorieen.naam_en(vb["categorie"])
        vb["landnaam"] = sitetaal.landnaam(vb["land"], "en") if vb.get("land") else ""
        vb["winkelnaam"] = (vb.get("naam") or keuze["webshop_url"]).replace("https://", "")
        return vb
    except Exception as e:
        print(f"Voorbeeld voor de app ophalen mislukt: {e}")
        return None


from concurrent.futures import ThreadPoolExecutor  # noqa: E402

# Een kleine vaste groep draden voor Shopify-vragen die tegelijk kunnen. Klein
# gehouden: er draait maar een werker met acht draden (Procfile).
_SNEL_POOL = ThreadPoolExecutor(max_workers=4)
_land_ververst_op = {}
LAND_VERVERS_SECONDEN = 600


if os.environ.get("RENDER"):
    threading.Thread(target=lambda: _voorbeeld_opwarmen(), daemon=True).start()


class _Stopwatch:
    """Houdt bij hoe lang elke stap van het openen duurt, en zet het in de log.

    Alleen als het openen langer dan anderhalve seconde duurde, anders vult het
    de log voor niets. Voorbeeld in Render: "Shopify-scherm x.myshopify.com
    traag: 4.2s (sleutel 0.1, land 0.0, positie 3.8, ...)"."""

    def __init__(self, winkel):
        self.winkel = winkel
        self.begin = self.vorige = time.monotonic()
        self.stappen = []

    def tik(self, naam):
        nu = time.monotonic()
        self.stappen.append((naam, nu - self.vorige))
        self.vorige = nu

    def klaar(self):
        totaal = time.monotonic() - self.begin
        if totaal > 1.5:
            delen = ", ".join(f"{n} {t:.1f}" for n, t in self.stappen)
            print(f"Shopify-scherm {self.winkel} traag: {totaal:.1f}s ({delen})")
        return totaal


def _land_verversen_nodig(winkel):
    return time.monotonic() - _land_ververst_op.get(winkel, -1e9) > LAND_VERVERS_SECONDEN


def _land_verversen(winkel, sleutel, webshop_url):
    """Taal en land opnieuw bij Shopify vragen (zie _shopify_scherm)."""
    _land_ververst_op[winkel] = time.monotonic()
    try:
        vers = shopify_app.winkelgegevens(winkel, sleutel) or {}
        if vers.get("land"):
            db.zet_markt(scan_engine.normalize_url(webshop_url), vers.get("taal"),
                         vers.get("land"))
    except Exception as e:
        print(f"Land van {winkel} verversen mislukt: {e}")


def _shopify_scherm(winkel, rij):
    """Het scherm dat de winkelier binnen Shopify ziet.

    SINDS 23 SEPTEMBER (stap 26) is de ingang zijn POSITIE IN DE INDEX, net als
    op krilloai.com. Hiervoor was de ingang een knop "Measure my store" die een
    eigen meting van dertig vragen startte, gratis, voor iedereen die de app
    installeerde. Dat kostte bij elke installatie geld, en het leverde een los
    cijfer op dat kon botsen met de openbare ranglijst.

    Nu: bij het openen komt de winkel op de winkellijst (stand "shopify", dus
    nooit in de koude mailrij). Het nachtelijk indelen geeft hem een categorie,
    de herberekening geeft hem een positie uit de bewaarde antwoorden, en de
    volgende keer dat hij de app opent staat die er. Nul modelaanroepen."""
    webshop_url = rij.get("webshop_url") or ""
    gegevens = _klantgegevens(webshop_url) if webshop_url else {}
    laatste = (db.get_rapporten_voor_webshop(webshop_url) or [None])[0] if webshop_url else None

    # HET LAND ELKE KEER VERS (24 september). Het werd alleen bij het
    # installeren opgehaald. Zette de winkelier daarna zijn adres op Nederland,
    # dan bleef de app "we meten jouw markt nog niet" zeggen. Een aanroep bij
    # Shopify per keer openen; mislukt die, dan geldt wat we al wisten.
    #
    # SNELHEID (26 september). Het openen duurde rond 30 seconden. Alles wat
    # bij Shopify nagevraagd moet worden, liep hier na elkaar. Nu:
    #  - het land op de achtergrond (hooguit eens per 10 minuten) als de
    #    winkel al in NL of BE staat; alleen anders wacht het scherm erop;
    #  - het abonnement wordt meteen gevraagd, zodat het klaar is tegen de tijd
    #    dat de positie uit de database komt;
    #  - elke stap wordt getimed en in de log gezet, zodat we in Render zien
    #    waar de tijd heen gaat in plaats van te raden.
    klok = _Stopwatch(winkel)
    sleutel_nu = _shopify_sleutel(rij) if rij.get("toegangssleutel") else None
    klok.tik("sleutel")
    abo_vraag = (_SNEL_POOL.submit(shopify_billing.huidig_abonnement, winkel, sleutel_nu)
                 if sleutel_nu else None)
    if webshop_url and sleutel_nu:
        profiel = db.get_winkelprofiel(scan_engine.normalize_url(webshop_url)) or {}
        bekend_land = (profiel.get("land") or "").upper()
        # Staat hij al in een land dat wij meten, dan verandert het land bijna
        # nooit en ververst het op de achtergrond (hooguit eens per 10 minuten).
        # Kennen wij het land niet, of ligt het buiten NL en BE, dan wacht het
        # scherm er wel op: dat is precies de winkelier die net zijn land op
        # Nederland zette en anders "we meten jouw markt nog niet" blijft lezen.
        # Alleen wachten als wij het land nog niet weten, of als het buiten NL
        # en BE ligt EN we het de laatste 10 minuten niet nagevraagd hebben.
        # In de video van 26 september wachtte een Amerikaanse winkel bij ELKE
        # opening op Shopify; dat hoort maar eens per tien minuten.
        # 27 september: alleen nog wachten als wij het land helemaal niet
        # kennen. Een winkel die zijn land verandert ziet dat bij de volgende
        # opening; daarvoor wachtte elke Amerikaanse winkel 2,5 seconden.
        moet_wachten = not bekend_land
        if moet_wachten or _land_verversen_nodig(winkel):
            land_vraag = _SNEL_POOL.submit(_land_verversen, winkel, sleutel_nu, webshop_url)
            if moet_wachten:
                try:
                    land_vraag.result(timeout=8)
                except Exception as e:
                    print(f"Land van {winkel} verversen duurde te lang of mislukte: {e}")
    klok.tik("land")

    markt = _markt_van(webshop_url) if webshop_url else None
    landcode = ((markt or {}).get("landcode") or "").upper()
    # De index meet de landen uit markten.py. Een winkel die op een ander land
    # verkoopt krijgt geen positie, en dat moet er eerlijk staan in plaats van
    # dat hij eeuwig "komt eraan" leest.
    import markten
    in_markt = markten.in_index(landcode)
    beeld = None
    categorienaam = None
    if webshop_url and in_markt:
        try:
            db.zet_klant_op_lijst(scan_engine.normalize_url(webshop_url),
                                  land=landcode or None, stand="shopify")
            # Ook na installeren via Shopify: meteen een plek, geen maand wachten.
            _plaats_in_ranglijst(scan_engine.normalize_url(webshop_url))
        except Exception as e:
            print(f"Shopify-winkel op de lijst zetten mislukt voor {webshop_url}: {e}")
        try:
            beeld = klantbeeld.bouw(scan_engine.normalize_url(webshop_url),
                                    land=(landcode or "").lower() or None)
            kort = db.winkel_kort(scan_engine.normalize_url(webshop_url)) or {}
            if kort.get("categorie"):
                categorienaam = categorieen.naam_en(kort["categorie"])
        except Exception as e:
            print(f"Positie ophalen mislukt voor {webshop_url}: {e}")

    klok.tik("positie")
    voorbeeld_app = None if beeld else _voorbeeld_voor_app()
    klok.tik("voorbeeld")

    # WAT GRATIS IS EN WAT NIET (24 september). Gratis: je positie, hoe vaak je
    # genoemd en aanbevolen werd, wie er vlak boven je staat, en EEN verloren
    # vraag compleet. Bij de andere verloren vragen zie je de vraag, maar niet
    # wie er in jouw plaats genoemd werd; dat is Watch. Het verloop per maand is
    # ook Watch. Zo ziet iemand de waarde voordat hij betaalt, en is er een
    # reden om te betalen (zie krillo-app-paywall in het project).
    #
    # Wat op slot staat gaat NIET mee naar de browser. Vaag maken met CSS zou
    # de namen gewoon in de broncode laten staan.
    #
    # Lukt het niet om bij Shopify na te vragen of hij betaalt, dan tonen we
    # alles. Liever een keer te veel laten zien dan een betalende klant voor
    # een dichte deur zetten.
    betaalt, proef_over = True, False
    if beeld and abo_vraag is not None:
        try:
            stand_abo = abo_vraag.result(timeout=15)
            if not stand_abo.get("fout"):
                betaalt = bool(stand_abo.get("actief"))
        except Exception as e:
            print(f"Abonnement nakijken voor het scherm mislukt voor {winkel}: {e}")
        proef_over = not rij.get("proef_gehad_op")
    slot = 0
    if beeld and not betaalt:
        beeld = dict(beeld)
        vragen = list(beeld.get("gemiste_vragen") or [])
        beeld["gemiste_vragen"] = vragen[:1] + [{"vraag": v.get("vraag"), "slot": True}
                                                 for v in vragen[1:]]
        slot = max(0, len(vragen) - 1)
        beeld["verloop"] = []

    klok.tik("abonnement")
    klok.klaar()
    return render_template(
        "shopify_app.html",
        betaalt=betaalt,
        slot=slot,
        proef_over=proef_over,
        proefdagen=shopify_billing.PROEFDAGEN,
        api_key=os.environ.get("SHOPIFY_API_KEY", ""),
        winkel=winkel,
        winkelnaam=rij.get("naam") or webshop_url,
        webshop_url=webshop_url,
        vermeldingen=gegevens.get("vermeldingen"),
        actieplan=gegevens.get("actieplan"),
        bronnen=gegevens.get("bronnen"),
        laatste=laatste,
        markt=markt,
        stand=_stand_in_taal(_shopify_status.get(winkel), markt),
        gratis_totaal=shopify_werk.GRATIS_WIJZIGINGEN,
        plannen=shopify_billing.PLANNEN,
        # Per jaar betalen in de app pas na de goedkeuring (zie na_goedkeuring).
        jaar_aan=shopify_billing.na_goedkeuring(),
        beeld=beeld,
        in_markt=in_markt,
        voorbeeld=voorbeeld_app,
        # Dezelfde staafjes als het dashboard op de site (klantbeeld.balkhoogtes).
        staven=klantbeeld.balkhoogtes(beeld.get("verloop") or []) if beeld else [],
        voorbeeld_staven=(klantbeeld.balkhoogtes(voorbeeld_app.get("verloop") or [])
                          if voorbeeld_app else []),
        categorienaam=categorienaam or (categorieen.naam_en(beeld["categorie"])
                                        if beeld else None),
        landnaam=sitetaal.landnaam(beeld["land"], "en") if beeld else None,
        basis_url=get_base_url().rstrip("/"),
    )


# Hoeveel seconden voor het verlopen wij al gaan verversen. Een meting duurt
# minuten, dus een sleutel die over dertig seconden verloopt is voor ons al
# verlopen. Zonder deze marge valt een lange meting halverwege om.
SLEUTEL_MARGE_SECONDEN = 300


def _shopify_sleutel(rij):
    """Geeft een sleutel die nu echt werkt, of None.

    Overal waar wij met Shopify praten moet dit ertussen zitten. Sleutels zijn
    een uur geldig, dus de sleutel die een uur geleden in de database gezet is
    doet het niet meer, en dat is precies de 403 waar dit voor gebouwd is.

    Er wordt niets teruggegeven zonder dat het nieuwe paar eerst opgeslagen is.
    Gebruiken wij een verse sleutel zonder hem op te slaan, dan vervalt de oude
    verversleutel en zijn wij de winkel voorgoed kwijt."""
    if not rij:
        return None
    winkel = rij.get("winkel")
    sleutel = rij.get("toegangssleutel")
    tot = rij.get("sleutel_tot")

    if sleutel and tot:
        over = (tot - datetime.now(timezone.utc)).total_seconds()
        if over > SLEUTEL_MARGE_SECONDEN:
            return sleutel

    verversleutel = rij.get("verversleutel")
    if not winkel or not verversleutel:
        # Geen verversleutel: dit is nog een sleutel van de oude soort, of de
        # winkel is nooit goed opgeslagen. Verversen kan niet, de winkelier
        # moet de app een keer openen zodat wij een nieuw kaartje krijgen.
        return None

    uitkomst = shopify_app.ververs_sleutel(winkel, verversleutel)
    if not uitkomst.get("gelukt"):
        print(f"Shopify: verversen mislukt voor {winkel}: {uitkomst.get('fout')}")
        if uitkomst.get("voorgoed_mislukt"):
            db.wis_shopify_verversleutel(winkel)
        return None

    bewaard = db.vervang_shopify_sleutelpaar(
        winkel, uitkomst["sleutel"], uitkomst.get("geldig_seconden"),
        uitkomst.get("verversleutel"), uitkomst.get("verversleutel_seconden"),
        rechten=uitkomst.get("rechten"))
    if not bewaard:
        # Niet opgeslagen betekent: niet gebruiken. Wij mogen de oude
        # verversleutel niet laten vervallen voor een sleutel die wij straks
        # nergens meer kunnen terugvinden.
        print(f"LET OP: nieuw sleutelpaar voor {winkel} is NIET opgeslagen. Niet gebruikt.")
        return None

    # De rij die de aanroeper vasthoudt bijwerken, anders pakt de volgende
    # regel in dezelfde functie nog de oude sleutel.
    rij["toegangssleutel"] = uitkomst["sleutel"]
    rij["verversleutel"] = uitkomst.get("verversleutel")
    rij["sleutel_tot"] = datetime.now(timezone.utc) + timedelta(
        seconds=int(uitkomst.get("geldig_seconden") or 0))
    return uitkomst["sleutel"]


def _shopify_uit_kaartje(id_token, winkel_uit_link=None):
    """Controleert het kaartje van Shopify en zorgt dat we een sleutel hebben.

    Geeft (winkel, rij) terug, of (None, None) als het kaartje niet deugt. Bij
    een winkel die we nog niet kennen, of waarvan de sleutel weg is, ruilen we
    het kaartje meteen in. Zo is een winkel die de app opnieuw installeert
    zonder gedoe weer werkend."""
    inhoud = shopify_app.controleer_id_token(id_token)
    if not inhoud:
        return None, None
    winkel = inhoud["winkel"]
    # Als er ook een winkel in de link staat, moet die dezelfde zijn. Anders
    # zou iemand met een geldig kaartje van zijn eigen winkel de gegevens van
    # een andere winkel kunnen opvragen.
    if winkel_uit_link and winkel_uit_link != winkel:
        print(f"Shopify: kaartje van {winkel} maar link zegt {winkel_uit_link}. Geweigerd.")
        return None, None

    rij = db.get_shopify_winkel(winkel)
    # Hebben wij al een sleutel die het doet, of een verversleutel waarmee wij
    # er een kunnen halen, dan is er niets aan de hand.
    #
    # Wat hier NIET mag staan is "hebben wij een sleutel, klaar". Een winkel
    # met een sleutel van de oude eeuwige soort komt dan nooit meer aan een
    # nieuwe, en elke aanroep bij Shopify geeft 403. Juist nu wij een geldig
    # kaartje in handen hebben is het moment om die om te ruilen.
    if rij and rij.get("toegangssleutel") and _shopify_sleutel(rij):
        return winkel, rij

    uitkomst = shopify_app.wissel_id_token(winkel, id_token)
    if not uitkomst.get("gelukt"):
        print(f"Shopify: inwisselen mislukt voor {winkel}: {uitkomst.get('fout')}")
        return winkel, None

    sleutel = uitkomst["sleutel"]
    gegevens = shopify_app.winkelgegevens(winkel, sleutel) or {}
    webshop_url = scan_engine.normalize_url(shopify_app.winkeladres(winkel, sleutel))
    db.bewaar_shopify_winkel(winkel, sleutel, rechten=uitkomst.get("rechten"),
                             webshop_url=webshop_url, email=gegevens.get("email"),
                             naam=gegevens.get("naam"),
                             geldig_seconden=uitkomst.get("geldig_seconden"),
                             verversleutel=uitkomst.get("verversleutel"),
                             verversleutel_seconden=uitkomst.get("verversleutel_seconden"))
    # Shopify vertelt ons de taal en het land van de winkel. Dat leggen we
    # meteen vast, want zonder dat krijgt een winkel in Texas Nederlandse
    # koopvragen. Dit moet gebeuren VOORDAT er gemeten wordt.
    if webshop_url:
        db.zet_markt(webshop_url, gegevens.get("taal"), gegevens.get("land"))
    threading.Thread(target=shopify_app.meld_webhooks_aan,
                     args=(winkel, sleutel, get_base_url()), daemon=True).start()
    return winkel, db.get_shopify_winkel(winkel)


@app.route("/shopify")
def shopify_start():
    """Waar Shopify de winkelier heen stuurt.

    Twee gevallen, en die moeten allebei werken:

    1. Er staat een id_token in de link. Dan heeft Shopify het installeren zelf
       geregeld en zit de winkelier in het beheerscherm naar ons scherm te
       kijken. Wij controleren het kaartje en tonen zijn cijfers.
    2. Er staat alleen ?shop=... in de link. Dan komt hij via de oude manier
       binnen en beginnen we het installeren zelf.

    Allebei nodig zolang de app nog op de oude installatiemanier staat
    ingesteld. Zodra dat omgezet is loopt alles via geval 1, en dan blijft
    geval 2 gewoon werken zonder kwaad te kunnen."""
    winkel = (request.args.get("shop") or "").strip().lower()
    id_token = request.args.get("id_token")

    if not shopify_app.beschikbaar():
        print(f"Shopify-installatie geweigerd: {shopify_app.waarom_niet()}")
        return render_template(
            "fout.html",
            titel="The Shopify app is not active yet",
            bericht=("We are getting the app ready. Please try again later, "
                     "or email hello@krilloai.com.")), 503

    # Geval 1: Shopify heeft het installeren zelf gedaan en stuurt ons een
    # kaartje mee. Dan is dit geen installatiepagina maar het scherm van de app.
    if id_token:
        _begin_kaartje = time.monotonic()
        echte_winkel, rij = _shopify_uit_kaartje(
            id_token, winkel if shopify_app.geldige_winkel(winkel) else None)
        _duur_kaartje = time.monotonic() - _begin_kaartje
        if _duur_kaartje > 1.5:
            # Het deel VOOR het scherm: kaartje controleren, sleutel ophalen of
            # verversen, bij een nieuwe installatie de winkelgegevens.
            print(f"Shopify-kaartje {echte_winkel} traag: {_duur_kaartje:.1f}s")
        if not echte_winkel:
            return "Invalid request.", 401
        if not rij or not rij.get("toegangssleutel"):
            return render_template(
                "fout.html", titel="We could not open your store",
                bericht=("Remove the app and install it again. If it keeps "
                         "going wrong, email hello@krilloai.com.")), 502
        return _shopify_scherm(echte_winkel, rij)

    if not winkel:
        return render_template(
            "fout.html",
            titel="Install from your Shopify store",
            bericht=("This page opens from the Shopify App Store or from your own "
                     "Shopify admin. Go to krilloai.com if you want to see what "
                     "Krillo does.")), 400

    if not shopify_app.geldige_winkel(winkel):
        # BEWUST het opgegeven adres niet terugtonen op de pagina. Dat komt van
        # buiten en hoort niet in onze HTML terecht te komen.
        print(f"Shopify-installatie geweigerd, geen geldig winkeladres: {winkel!r}")
        return render_template(
            "fout.html",
            titel="This is not a valid store address",
            bericht="Open the app from your own Shopify admin."), 400

    # Heeft deze winkel de app AL, dan tonen wij gewoon het scherm.
    #
    # Hier stond eerder meteen een doorverwijzing naar het toestemmingsscherm
    # van Shopify. Dat is een van de dingen waarop een app afgekeurd wordt:
    # iemand die al toestemming gaf en de app opent via een bewaarde link,
    # kreeg opnieuw de vraag of Krillo bij zijn producten mag.
    rij = db.get_shopify_winkel(winkel)
    if rij and rij.get("toegangssleutel") and rij.get("actief"):
        # ALLEEN met een geldige handtekening van Shopify (25 september).
        # Hier stond het scherm voor iedereen die ?shop=<winkel> intypte: wie
        # een geinstalleerde winkel kende, zag zijn cijfers en concurrenten
        # zonder in te loggen. Zonder handtekening sturen wij hem naar de app
        # in zijn eigen Shopify-beheer; daar krijgt hij het gewoon te zien,
        # met een kaartje van Shopify erbij.
        if shopify_app.klopt_query_handtekening(request.args.to_dict()):
            return _shopify_scherm(winkel, rij)
        sleutel_app = (os.environ.get("SHOPIFY_API_KEY") or "").strip()
        return redirect(f"https://{winkel}/admin/apps/{sleutel_app}", code=302)

    link = shopify_app.installatielink(winkel, get_base_url())
    if not link:
        return render_template(
            "fout.html", titel="Installing does not work right now",
            bericht="Please try again in a moment, or email hello@krilloai.com."), 503

    # NIET met een gewone doorverwijzing. Shopify weigert zijn eigen
    # toestemmingspagina in een venster binnen het beheerscherm, en dan ziet de
    # winkelier een lege bladzijde in plaats van een scherm. Daarom een klein
    # paginaatje dat het BOVENSTE venster verplaatst. Werkt ook gewoon als de
    # app buiten Shopify geopend wordt, want dan is het bovenste venster het
    # enige venster.
    return render_template("shopify_doorsturen.html", link=link)


def _shopify_uit_kop():
    """Haalt de winkel uit het kaartje in de Authorization-kop.

    Het scherm binnen Shopify vraagt bij elke actie een vers kaartje op en
    stuurt dat mee. Zo hoeft er geen sessie of cookie te bestaan, en kan een
    verzoek niet van een andere winkel komen dan het kaartje zegt."""
    kop = request.headers.get("Authorization") or ""
    if not kop.lower().startswith("bearer "):
        return None, None
    return _shopify_uit_kaartje(kop[7:].strip())


@app.route("/shopify/api/meten", methods=["POST"])
def shopify_api_meten():
    """Vroeger: een eigen meting starten. Sinds 23 september niet meer (stap 26).

    De positie in de app komt uit de index, net als op de site. Een eigen
    meting per installatie kostte bij elke installatie geld en gaf een tweede
    cijfer naast de openbare ranglijst. Deze route blijft bestaan zodat een
    oud geopend scherm een nette uitleg krijgt in plaats van een 404."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Not allowed."}), 401
    return jsonify({"error": "Your rank now comes from the Krillo index. Reload this "
                             "page to see it."}), 410

    webshop_url = rij.get("webshop_url")
    if not webshop_url:
        return jsonify({"error": "We do not know your store's address yet."}), 400

    markt = _markt_van(webshop_url)
    bezig = _shopify_status.get(winkel)
    if bezig and not bezig.get("klaar"):
        # Al bezig. Twee metingen tegelijk kosten dubbel en leveren niets
        # extra's op, dus we melden gewoon waar de lopende meting is.
        return jsonify({"stand": _stand_in_taal(bezig, markt)})

    _shopify_status[winkel] = {"tekst": "we beginnen", "klaar": False, "mislukt": False}
    threading.Thread(target=_shopify_meten,
                     args=(winkel, webshop_url, rij.get("email")), daemon=True).start()
    return jsonify({"stand": _stand_in_taal(_shopify_status[winkel], markt)})


_shopify_voorstellen = {}
_shopify_werk_status = {}


def _shopify_voorstellen_maken(winkel, sleutel, webshop_url):
    """Kijkt wat er ontbreekt en schrijft de teksten. Zet nog niets in de winkel."""
    _shopify_werk_status[winkel] = {"tekst": "we kijken je winkel na", "klaar": False,
                                    "mislukt": False}
    try:
        markt_gegevens = _markt_van(webshop_url)
        uitkomst = shopify_werk.maak_voorstellen(winkel, sleutel, markt_gegevens)
        _shopify_voorstellen[winkel] = {v["id"]: v for v in uitkomst["voorstellen"]}
        betaalt, plan = False, None
        try:
            rij = db.get_shopify_winkel(winkel) or {}
            if rij.get("toegangssleutel"):
                # Onbeperkt toepassen hoort bij Fix. Watch is de oplossingen
                # uitgeschreven om zelf te doen, en krijgt net als iedereen de
                # gratis wijzigingen met een klik.
                stand_nu = shopify_billing.huidig_abonnement(winkel, _shopify_sleutel(rij))
                if stand_nu.get("fout"):
                    # Shopify gaf geen antwoord. Dan tonen we de teksten (zoals
                    # Watch), maar zetten we niets extra in de winkel. Liever
                    # een keer te veel laten lezen dan een betalende klant voor
                    # een dichte deur.
                    plan = "watch"
                elif stand_nu["actief"]:
                    plan = stand_nu.get("plan")
                betaalt = plan == "fix" and not stand_nu.get("fout")
        except Exception as e:
            print(f"Abonnement nakijken mislukt voor {winkel}: {e}")
            plan = "watch"
        rij_nu = db.get_shopify_winkel(winkel) or {}
        al_gedaan = max(
            len([w for w in db.get_wijzigingen(webshop_url or "")
                 if (w.get("taak_id") or "").startswith("shopify:")]),
            int(rij_nu.get("wijzigingen_ooit") or 0))
        gratis_over = None if betaalt else max(0, shopify_werk.GRATIS_WIJZIGINGEN - al_gedaan)
        _shopify_werk_status[winkel] = {
            "tekst": "klaar", "klaar": True, "mislukt": False,
            "betaalt": betaalt,
            "plan": plan,
            "gratis_over": gratis_over,
            "gratis_totaal": shopify_werk.GRATIS_WIJZIGINGEN,
            "aantallen": uitkomst["aantallen"],
            "fouten": uitkomst["fouten"],
            "voorstellen": _voorstellen_per_plan(
                [_voorstel_voor_scherm(stuk, markt_gegevens) for stuk in uitkomst["voorstellen"]],
                plan, gratis_over),
        }
    except Exception as e:
        print(f"Voorstellen maken mislukt voor {winkel}: {e}")
        _shopify_werk_status[winkel] = {
            "tekst": "Er ging iets mis bij het nakijken van je winkel.",
            "klaar": True, "mislukt": True}


@app.route("/shopify/api/voorstellen", methods=["POST"])
def shopify_api_voorstellen():
    """Maak voorstellen: wat wij zouden invullen, en wat er dan komt te staan.

    Dit is met opzet een aparte stap van het toepassen. De eigenaar moet eerst
    zien wat er in zijn winkel komt te staan. Het is zijn winkel."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Not allowed."}), 401
    markt = _markt_van(rij.get("webshop_url") or "")
    bezig = _shopify_werk_status.get(winkel)
    if bezig and not bezig.get("klaar"):
        return jsonify({"stand": _stand_in_taal(bezig, markt)})
    threading.Thread(
        target=_shopify_voorstellen_maken,
        args=(winkel, _shopify_sleutel(rij), rij.get("webshop_url")),
        daemon=True).start()
    return jsonify({"stand": _stand_in_taal(
        {"tekst": "we kijken je winkel na", "klaar": False, "mislukt": False}, markt)})


@app.route("/shopify/api/werkstand")
def shopify_api_werkstand():
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij:
        return jsonify({"error": "Not allowed."}), 401
    stand = _shopify_werk_status.get(winkel)
    # Geen stand terwijl het scherm erom vraagt (25 september): dan is de
    # server tussendoor herstart en is het werk kwijt. Zonder dit bleef het
    # scherm eindeloos op "Working" staan met een lopende klok.
    if not stand:
        stand = {"mislukt": True, "tekst": "werk onderbroken"}
    stand = _stand_in_taal(stand, _markt_van(rij.get("webshop_url") or ""))
    # Losse foutmeldingen van het voorbereiden zijn interne Nederlandse tekst
    # ("Kostenrem: ..."). Op het Engelse scherm een gewone zin.
    if stand.get("fouten"):
        stand = dict(stand, fouten=["Some parts could not be prepared right now. "
                                    "Try again in a few minutes."])
    return jsonify({"stand": stand})  # al door _stand_in_taal gegaan, zie hierboven


@app.route("/shopify/api/toepassen", methods=["POST"])
def shopify_api_toepassen():
    """Zet de gekozen voorstellen echt in de winkel.

    Alleen wat de eigenaar aangevinkt heeft, en alleen voorstellen die wij zelf
    net gemaakt hebben. Wij nemen geen tekst aan die het scherm meestuurt: dan
    zou iemand met een eigen verzoek elke tekst in zijn winkel kunnen laten
    zetten via ons, en dat is precies het soort gat waar je later spijt van
    krijgt."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Not allowed."}), 401
    webshop_url = rij.get("webshop_url")
    if not webshop_url:
        return jsonify({"error": "We do not know your store's address yet."}), 400

    gevraagd = (request.get_json(silent=True) or {}).get("ids") or []
    bekend = _shopify_voorstellen.get(winkel) or {}
    if not bekend:
        return jsonify({"error": "These proposals have expired. Check your store again and we will make fresh ones."}), 409

    # Hoeveel er gratis nog in mogen. Wij tellen wat er al echt in de winkel
    # staat, niet wat er in deze ronde gevraagd wordt: anders kan iemand door
    # de knop vaker in te drukken alsnog alles gratis krijgen.
    # Onbeperkt toepassen is Fix. Watch houdt de gratis wijzigingen die iedereen
    # krijgt, en de rest staat uitgeschreven om zelf over te nemen.
    stand_nu = shopify_billing.huidig_abonnement(winkel, _shopify_sleutel(rij))
    betaalt = stand_nu["actief"] and stand_nu.get("plan") == "fix"
    al_gedaan = len([w for w in db.get_wijzigingen(webshop_url)
                     if (w.get("taak_id") or "").startswith("shopify:")])
    # De teller loopt alleen op. Hier stond eerder het aantal wijzigingen dat NU
    # in de winkel staat, en dat betekende: drie keer toepassen, drie keer
    # terugzetten, en je had weer drie gratis. Dan doet Krillo al het werk voor
    # niets.
    ooit = max(al_gedaan, int(rij.get("wijzigingen_ooit") or 0))
    over = 10_000 if betaalt else max(0, shopify_werk.GRATIS_WIJZIGINGEN - ooit)

    gedaan, mislukt, overgeslagen, geblokkeerd = [], [], [], []
    for kenmerk in gevraagd[:50]:
        voorstel = bekend.get(kenmerk)
        if not voorstel:
            continue
        if over <= 0:
            geblokkeerd.append({"id": kenmerk, "waar": voorstel.get("waar")})
            continue
        uit = shopify_werk.pas_toe(winkel, _shopify_sleutel(rij), voorstel, webshop_url)
        if uit.get("gelukt"):
            gedaan.append({"id": kenmerk, "waar": voorstel.get("waar")})
            over -= 1
            db.tel_shopify_wijziging(winkel)
        elif uit.get("overgeslagen"):
            # Overgeslagen kost geen tegoed: er is niets veranderd.
            overgeslagen.append({"id": kenmerk, "waar": voorstel.get("waar"),
                                 "reden": uit.get("fout")})
        else:
            mislukt.append({"id": kenmerk, "waar": voorstel.get("waar"),
                            "reden": uit.get("fout")})
    # Stap 157 (na de goedkeuring): om een review vragen op een moment van
    # waarde, zijn eerste gelukte wijziging. Een keer per winkel; Shopify
    # bepaalt zelf of het venster echt verschijnt. Nooit iets beloven of belonen.
    vraag_review = bool(gedaan) and shopify_billing.na_goedkeuring() and db.review_mag_gevraagd(winkel)
    return jsonify({"gedaan": gedaan, "overgeslagen": overgeslagen, "mislukt": mislukt,
                    "vraag_review": vraag_review,
                    "geblokkeerd": geblokkeerd, "betaalt": betaalt,
                    "plan": stand_nu.get("plan") if stand_nu.get("actief") else None,
                    "gratis_over": None if betaalt else over,
                    "gratis_totaal": shopify_werk.GRATIS_WIJZIGINGEN})


@app.route("/shopify/api/wijzigingen")
def shopify_api_wijzigingen():
    """Alles wat wij in deze winkel veranderd hebben, met de oude tekst erbij."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij:
        return jsonify({"error": "Not allowed."}), 401
    webshop_url = rij.get("webshop_url") or ""
    markt = _markt_van(webshop_url) if webshop_url else None
    regels = []
    for w in db.get_wijzigingen(webshop_url):
        taak_id = w.get("taak_id") or ""
        if not taak_id.startswith("shopify:"):
            continue
        regels.append({
            "id": taak_id,
            # Het soort staat in het kenmerk, en dat is de enige plek waar het
            # in een vaste taal staat. Het opgeslagen woord komt uit de taal van
            # de winkel op het moment van toepassen, en dan las een Engelse
            # winkelier ineens "Producttekst" op zijn eigen scherm.
            "wat": _wijziging_soort_woord(taak_id, markt) or w.get("wat"),
            "waar": w.get("waar"),
            # Zonder dit staat er letterlijk <p> en </p> op het scherm van de
            # winkelier. Wij bewaren de HTML wel, want die moet terug de winkel
            # in kunnen, maar tonen doen wij de tekst.
            "oud": _zonder_opmaak(w.get("oude_waarde"))[:600],
            "nieuw": _zonder_opmaak(w.get("nieuwe_waarde"))[:600],
            "op": w["gedaan_op"].isoformat() if w.get("gedaan_op") else None})
    return jsonify({"wijzigingen": regels})


@app.route("/shopify/api/terugzetten", methods=["POST"])
def shopify_api_terugzetten():
    """Eén wijziging ongedaan maken.

    Dit is geen extraatje. Wij beloven dat alles terug kan, en een belofte die
    alleen in de tekst staat en niet in een knop is geen belofte."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Not allowed."}), 401
    webshop_url = rij.get("webshop_url") or ""
    kenmerk = (request.get_json(silent=True) or {}).get("id") or ""

    wijziging = None
    for w in db.get_wijzigingen(webshop_url):
        if w.get("taak_id") == kenmerk:
            wijziging = w
    if not wijziging:
        return jsonify({"error": "We do not know that change."}), 404

    uit = shopify_werk.zet_terug(winkel, _shopify_sleutel(rij), wijziging, webshop_url)
    if not uit.get("gelukt"):
        return jsonify({"error": uit.get("fout") or "Terugzetten mislukt."}), 502
    db.verwijder_wijziging(webshop_url, kenmerk)

    # Het voorstel weer terugzetten in de lijst.
    #
    # Zonder dit moest je na een klik op "Undo this" opnieuw je hele winkel
    # laten nakijken om die ene wijziging terug te krijgen, en kreeg je er
    # tientallen andere voorstellen bij die je niet gevraagd had. Iemand die
    # per ongeluk klikt hoort hem gewoon weer aan te kunnen zetten.
    voorstel = (_shopify_voorstellen.get(winkel) or {}).get(kenmerk)
    if not voorstel:
        voorstel = _voorstel_uit_wijziging(wijziging)
    if voorstel:
        _shopify_voorstellen.setdefault(winkel, {})[kenmerk] = voorstel

    markt = _markt_van(webshop_url) if webshop_url else None
    # Mag hij hem ook weer aanzetten? Het scherm zei altijd "apply it again
    # whenever you want", ook tegen een gratis winkel die zijn 3 al gebruikt
    # had (26 september). De teller loopt alleen op, dus terugzetten geeft geen
    # gratis wijziging terug; dat moet het scherm dan ook eerlijk zeggen.
    betaalt, plan, over = _shopify_tegoed(winkel, rij, webshop_url)
    return jsonify({"ok": True, "id": kenmerk,
                    "betaalt": betaalt, "plan": plan,
                    "gratis_over": None if betaalt else over,
                    "gratis_totaal": shopify_werk.GRATIS_WIJZIGINGEN,
                    "voorstel": _voorstel_voor_scherm(voorstel, markt) if voorstel else None})


def _shopify_tegoed(winkel, rij, webshop_url):
    """(betaalt, plan, gratis_over) zoals het toepassen het rekent."""
    try:
        stand_nu = shopify_billing.huidig_abonnement(winkel, _shopify_sleutel(rij))
    except Exception as e:
        print(f"Abonnement nakijken mislukt voor {winkel}: {e}")
        stand_nu = {"actief": False}
    plan = stand_nu.get("plan") if stand_nu.get("actief") else None
    betaalt = plan == "fix"
    al_gedaan = len([w for w in db.get_wijzigingen(webshop_url)
                     if (w.get("taak_id") or "").startswith("shopify:")])
    ooit = max(al_gedaan, int(rij.get("wijzigingen_ooit") or 0))
    return betaalt, plan, max(0, shopify_werk.GRATIS_WIJZIGINGEN - ooit)


@app.route("/shopify/api/abonnement")
def shopify_api_abonnement():
    """Of deze winkel een lopend abonnement heeft. Elke keer vers bij Shopify."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Not allowed."}), 401
    stand = shopify_billing.huidig_abonnement(winkel, _shopify_sleutel(rij))
    # Loopt er echt een abonnement, dan is de gratis proefperiode ook echt
    # gebruikt. Pas hier, en niet al bij het maken van de link.
    if stand["actief"]:
        # Elke keer dat wij een lopend abonnement zien: klantregel aanwezig en
        # niet opgezegd. Ook bij iemand die eerder opzegde en terugkwam.
        try:
            _shopify_klant_actief(winkel, rij, stand.get("plan"),
                                  is_test=bool((stand.get("abonnement") or {}).get("test")))
        except Exception as e:
            print(f"Shopify-klant bijwerken mislukt voor {winkel}: {e}")
    if stand["actief"] and not rij.get("proef_gehad_op"):
        db.markeer_proef_gehad(winkel)
        # Dit is precies één keer per winkel de eerste keer dat wij een lopend
        # abonnement zien, dus de goede plek voor een bericht aan onszelf. Bij
        # Shopify komt er geen melding van Mollie binnen, dus zonder dit zou een
        # abonnee via de app pas bij de wekelijkse ronde opvallen.
        plan_nu = shopify_billing.PLANNEN.get(stand.get("plan") or "fix")
        # Een testabonnement (ontwikkelwinkel, of de beoordelaar van Shopify)
        # levert geen geld op. Dat moet in de kop staan (27 september: de
        # beoordelaar startte Watch en jij kreeg "Nieuwe klant, 55 USD").
        is_test = bool((stand.get("abonnement") or {}).get("test"))
        _meld_nieuwe_klant(
            ("TEST, geen echt geld: " if is_test else "")
            + f"{plan_nu['naam']} via de Shopify-app", rij.get("webshop_url") or winkel,
            rij.get("email") or "onbekend, via Shopify",
            (f"0 (testabonnement, zou {plan_nu['prijs']} {shopify_billing.PLAN_VALUTA} zijn)"
             if is_test else f"{plan_nu['prijs']} {shopify_billing.PLAN_VALUTA} per maand"),
            extra=f"Winkel in Shopify: {winkel}")
        rij = db.get_shopify_winkel(winkel) or rij
    return jsonify({
        "actief": stand["actief"],
        "abonnement": stand["abonnement"],
        "plan": stand.get("plan"),
        "prijzen": {k: v["prijs"] for k, v in shopify_billing.PLANNEN.items()},
        "valuta": shopify_billing.PLAN_VALUTA,
        "proefdagen": 0 if rij.get("proef_gehad_op") else shopify_billing.PROEFDAGEN,
        # Of het LOPENDE abonnement een test is (25 september), niet alleen de
        # instelling: in een ontwikkelwinkel is elk abonnement een test, ook
        # als SHOPIFY_BILLING_TEST uit staat.
        "test": bool((stand.get("abonnement") or {}).get("test")) or shopify_billing.testmodus(),
    })


@app.route("/shopify/api/abonneren", methods=["POST"])
def shopify_api_abonneren():
    """Start een abonnement en geef de bevestigingslink terug.

    Hier is nog niets afgesloten en niets betaald. Het scherm moet de winkelier
    naar die link sturen in het BOVENSTE venster, niet in het lijstje waar onze
    app in staat: Shopify weigert de betaalpagina in een venster-in-een-venster
    en dan ziet hij een lege bladzijde."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Not allowed."}), 401

    plan = ((request.get_json(silent=True) or {}).get("plan") or "").strip().lower()
    if plan not in shopify_billing.PLANNEN:
        return jsonify({"error": "Choose Watch or Fix."}), 400
    periode = "jaar" if ((request.get_json(silent=True) or {}).get("periode") == "jaar") else "maand"

    # Nooit twee keer betalen voor dezelfde winkel, ook niet via twee wegen.
    # Loopt er al een abonnement via krilloai.com (Mollie), dan hier niet nog
    # een via Shopify (stap 26, 23 september).
    if rij.get("webshop_url"):
        try:
            via_site = payments.zoek_abonnement(scan_engine.normalize_url(rij["webshop_url"]))
        except Exception as e:
            print(f"Abonnement op de site nakijken mislukt voor {winkel}: {e}")
            via_site = None
        if via_site:
            return jsonify({"error": "Your store already has a Krillo plan through "
                                     "krilloai.com. To switch, cancel that one first "
                                     "from your dashboard link.", "actief": True}), 409

    bestaand = shopify_billing.huidig_abonnement(winkel, _shopify_sleutel(rij))
    if bestaand["actief"] and bestaand.get("plan") == plan:
        # Twee keer hetzelfde plan betekent twee keer betalen. Dat mag nooit
        # gebeuren door een dubbele klik. Een ANDER plan mag wel: dan vervangt
        # Shopify het lopende abonnement zelf, er lopen er nooit twee tegelijk.
        return jsonify({"error": "You are already on this plan.",
                        "actief": True}), 409

    # Terug naar het INGEBEDDE app-scherm in het beheerscherm van Shopify, niet
    # naar onze eigen /shopify. Die laatste ziet geen kaartje en stuurt de
    # winkelier door naar een nieuw toestemmingsscherm. Iemand die net akkoord
    # is gegaan met 55 dollar en dan opnieuw om toestemming gevraagd wordt, is
    # precies degene die afhaakt.
    terug = _app_adres_in_beheerscherm(winkel)
    # De gratis proefperiode krijg je een keer. Opzeggen en meteen weer starten
    # gaf anders telkens zeven nieuwe gratis dagen, en dat kan eindeloos.
    al_gehad = bool(rij.get("proef_gehad_op"))
    proefdagen = 0 if al_gehad else None
    # Wie al betaalt en van plan wisselt, krijgt geen nieuwe proefperiode.
    if bestaand["actief"]:
        proefdagen = 0
    uit = shopify_billing.start_abonnement(winkel, _shopify_sleutel(rij), terug,
                                           proefdagen=proefdagen, plan=plan, periode=periode)
    if not uit["gelukt"]:
        return jsonify({"error": uit["fout"]}), 502
    # Hier stond dat de proefperiode nu verbruikt was. Dat is te vroeg: op dit
    # punt is er alleen een link gemaakt en heeft de winkelier nog nergens ja
    # op gezegd. Klikt hij die pagina weg, dan was zijn gratis week op zonder
    # dat hij ooit iets had. De volgende keer stond er dan 55 dollar per maand
    # terwijl het scherm zeven dagen gratis belooft.
    #
    # Het verbruiken gebeurt nu pas als er echt een lopend abonnement is, zie
    # de route hieronder die de stand opvraagt.
    return jsonify({"link": uit["link"], "test": uit["test"], "plan": plan,
                    "proefdagen": 0 if (al_gehad or bestaand["actief"])
                    else shopify_billing.PROEFDAGEN})


@app.route("/shopify/api/opzeggen", methods=["POST"])
def shopify_api_opzeggen():
    """Opzeggen vanuit onze eigen app."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij or not rij.get("toegangssleutel"):
        return jsonify({"error": "Not allowed."}), 401
    stand = shopify_billing.huidig_abonnement(winkel, _shopify_sleutel(rij))
    if not stand["actief"]:
        if stand.get("fout"):
            # Wij WETEN het niet, en dat is iets anders dan "er loopt niets".
            # Zou je hier gewoon "er loopt geen abonnement" zeggen, dan denkt
            # iemand dat hij opgezegd heeft terwijl er over vier dagen 55 dollar
            # afgeschreven wordt. Op de prijskaart staat "cancel any time".
            return jsonify({"error": "We could not reach Shopify for your plan just now. Please try again in a moment."}), 503
        return jsonify({"error": "There is no active plan."}), 400
    uit = shopify_billing.zeg_op(winkel, _shopify_sleutel(rij),
                                 (stand["abonnement"] or {}).get("id"))
    if not uit["gelukt"]:
        return jsonify({"error": uit["fout"]}), 502
    if rij.get("webshop_url"):
        db.zet_klant_opgezegd(rij["webshop_url"])
    return jsonify({"ok": True})


@app.route("/shopify/api/automatisch", methods=["GET", "POST"])
def shopify_api_automatisch():
    """Of wij uit onszelf mogen aanvullen bij deze winkel.

    Moet uit kunnen, en hij moet kunnen zien dat het aanstaat. Een app die
    ongevraagd in andermans winkel schrijft zonder schakelaar is een app waar
    terecht over geklaagd wordt."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij:
        return jsonify({"error": "Not allowed."}), 401
    if request.method == "POST":
        aan = bool((request.get_json(silent=True) or {}).get("aan"))
        db.zet_shopify_automatisch(winkel, aan)
        rij = db.get_shopify_winkel(winkel) or rij
    return jsonify({"aan": bool(rij.get("automatisch", True)),
                    "laatst": (rij.get("automatisch_op").isoformat()
                               if rij.get("automatisch_op") else None)})


@app.route("/shopify/api/stand")
def shopify_api_stand():
    """Waar de meting is. Het scherm vraagt dit elke paar seconden.

    Dit is de meest zichtbare tekst van de hele app: hij staat er minutenlang
    en ververst elke vijf seconden. Juist hier moet de taal dus kloppen."""
    winkel, rij = _shopify_uit_kop()
    if not winkel or not rij:
        return jsonify({"error": "Not allowed."}), 401
    return jsonify({"stand": _stand_in_taal(
        _shopify_status.get(winkel), _markt_van(rij.get("webshop_url") or ""))})


@app.route("/shopify/callback")
def shopify_callback():
    """Waar Shopify de winkelier terugstuurt nadat hij toestemming gaf.

    Hier gebeuren drie controles die geen van drieën mogen worden overgeslagen:
    klopt de handtekening, is het winkeladres echt, en hebben wij deze
    installatie zelf in gang gezet."""
    argumenten = request.args.to_dict()
    winkel = (argumenten.get("shop") or "").strip().lower()
    code = argumenten.get("code")
    kenmerk = argumenten.get("state")

    if not shopify_app.klopt_query_handtekening(argumenten):
        print(f"Shopify-callback geweigerd: handtekening klopt niet, winkel {winkel!r}")
        return "Invalid request.", 401
    if not shopify_app.geldige_winkel(winkel) or not code:
        print(f"Shopify-callback geweigerd: winkel of code ontbreekt, {winkel!r}")
        return "Invalid request.", 400
    if not shopify_app.kenmerk_klopt(kenmerk):
        # Dit gebeurt ook gewoon als Render tussendoor opnieuw is opgestart,
        # want de openstaande installaties staan alleen in het geheugen. Daarom
        # geen enge foutmelding maar de vraag om het nog eens te proberen.
        print(f"Shopify-callback geweigerd: onbekend of verlopen kenmerk, {winkel!r}")
        return render_template(
            "fout.html", titel="The installation has expired",
            bericht="Start again from your Shopify admin."), 400

    uitkomst = shopify_app.haal_toegangssleutel(winkel, code)
    if not uitkomst.get("gelukt"):
        print(f"Shopify-sleutel ophalen mislukt voor {winkel}: {uitkomst.get('fout')}")
        return render_template(
            "fout.html", titel="Installing did not work",
            bericht="Please try again. If it keeps going wrong, email hello@krilloai.com."), 502

    sleutel = uitkomst["sleutel"]
    gegevens = shopify_app.winkelgegevens(winkel, sleutel) or {}
    webshop_url = scan_engine.normalize_url(shopify_app.winkeladres(winkel, sleutel))

    bewaard = db.bewaar_shopify_winkel(
        winkel, sleutel, rechten=uitkomst.get("rechten"), webshop_url=webshop_url,
        email=gegevens.get("email"), naam=gegevens.get("naam"),
        geldig_seconden=uitkomst.get("geldig_seconden"),
        verversleutel=uitkomst.get("verversleutel"),
        verversleutel_seconden=uitkomst.get("verversleutel_seconden"))
    if not bewaard:
        # Zonder opslaan hebben we straks geen sleutel meer en kunnen we niets.
        # Dan liever nu een eerlijke fout dan een app die stil niets doet.
        print(f"LET OP: Shopify-winkel {winkel} is NIET opgeslagen.")
        return render_template(
            "fout.html", titel="Installing only half worked",
            bericht="Remove the app and install it again, or email hello@krilloai.com."), 500

    # De taal en het land van de winkel vastleggen. Vergeet je dit, dan valt
    # alles terug op Nederlands en krijgt een winkel in Texas dertig Nederlandse
    # koopvragen over Nederlandse webshops. Dat is geen schoonheidsfoutje: dat
    # is een meting over de verkeerde markt, zonder enige foutmelding.
    if gegevens.get("taal") or gegevens.get("land"):
        db.zet_markt(webshop_url, gegevens.get("taal"), gegevens.get("land"))

    # De verplichte webhooks. Op de achtergrond, want de winkelier hoeft daar
    # niet op te wachten, maar wel meteen: zonder deze webhooks komt de app de
    # beoordeling niet door.
    threading.Thread(
        target=shopify_app.meld_webhooks_aan,
        args=(winkel, sleutel, get_base_url()), daemon=True).start()

    # Terug naar het SCHERM VAN DE APP, niet naar de lijst met alle apps.
    # "Redirect to the app UI after installation" staat letterlijk in de eisen
    # van Shopify, en de appslijst is niet het scherm van de app.
    return redirect(_app_adres_in_beheerscherm(winkel))


def _webhook_binnen(onderwerp):
    """Gemeenschappelijke controle voor elke webhook van Shopify.

    Geeft (winkel, gegevens) terug, of (None, None) als het verzoek niet klopt.
    De handtekening wordt over de RUWE body berekend, want anders klopt hij
    nooit."""
    handtekening = request.headers.get("X-Shopify-Hmac-Sha256")
    ruw = request.get_data()
    if not shopify_app.klopt_webhook_handtekening(ruw, handtekening):
        print(f"Shopify-webhook {onderwerp} geweigerd: handtekening klopt niet.")
        return None, None
    winkel = (request.headers.get("X-Shopify-Shop-Domain") or "").strip().lower()
    try:
        gegevens = json.loads(ruw.decode("utf-8")) if ruw else {}
    except Exception:
        gegevens = {}
    return winkel, gegevens


@app.route("/shopify/webhooks/naleving", methods=["POST"])
def shopify_naleving():
    """Eén adres voor de drie verplichte privacy-webhooks van Shopify.

    Waarom dit erbij komt terwijl de drie losse adressen hieronder al bestaan:
    die drie kan je namelijk NIET aanmelden. Niet via de API (die weigert deze
    onderwerpen), en niet meer in het partnerscherm (die velden zijn weg).
    Ze horen in shopify.app.toml, en daar hoort per blok één adres bij dat alle
    drie de onderwerpen ontvangt. Dit is dat adres.

    Welk onderwerp het is staat in de kop X-Shopify-Topic. Daar kiezen wij op.

    De drie losse adressen blijven bestaan. Dat is geen dubbelop maar met opzet:
    de controle van Shopify klopt soms nog aan op de oude paden, en een 404 daar
    telt als afgekeurd."""
    handtekening = request.headers.get("X-Shopify-Hmac-Sha256")
    ruw = request.get_data()
    if not shopify_app.klopt_webhook_handtekening(ruw, handtekening):
        print("Shopify-nalevingswebhook geweigerd: handtekening klopt niet.")
        return "", 401

    onderwerp = (request.headers.get("X-Shopify-Topic") or "").strip().lower()
    winkel = (request.headers.get("X-Shopify-Shop-Domain") or "").strip().lower()

    if onderwerp == "customers/data_request":
        print(f"AVG-verzoek gegevens van {winkel}: Krillo bewaart geen gegevens van "
              f"kopers van deze winkel. Niets te leveren.")
    elif onderwerp == "customers/redact":
        print(f"AVG-wisverzoek klant van {winkel}: niets opgeslagen, niets gewist.")
    elif onderwerp == "shop/redact":
        if db.wis_shopify_winkel(winkel):
            print(f"Alles gewist voor {winkel} na shop/redact.")
        else:
            print(f"LET OP: wissen na shop/redact MISLUKT voor {winkel}. "
                  f"Handmatig nakijken.")
    else:
        # Een onderwerp dat wij hier niet verwachten. Wel 200 terug, want de
        # handtekening klopte en het kwam echt van Shopify. Blijven herhalen
        # heeft geen zin, maar het moet wel in de logs staan.
        print(f"Onbekend onderwerp op de nalevingswebhook: {onderwerp!r} van {winkel}")
    return "", 200


@app.route("/shopify/webhooks/klantgegevens", methods=["POST"])
def shopify_klantgegevens():
    """customers/data_request. Verplicht.

    Een consument vraagt via de winkelier welke gegevens wij van hem hebben.
    Krillo bewaart geen gegevens van de klanten van een webshop: we meten de
    winkel, niet de kopers. Er is dus niets te leveren, en dat leggen we vast
    zodat we het kunnen laten zien als het gevraagd wordt."""
    winkel, gegevens = _webhook_binnen("customers/data_request")
    if winkel is None:
        return "", 401
    print(f"AVG-verzoek gegevens van {winkel}: Krillo bewaart geen gegevens van "
          f"kopers van deze winkel. Niets te leveren.")
    return "", 200


@app.route("/shopify/webhooks/klant-wissen", methods=["POST"])
def shopify_klant_wissen():
    """customers/redact. Verplicht.

    Zelfde verhaal: wij hebben niets van individuele kopers, dus er valt niets
    te wissen. We antwoorden wel netjes, want anders blijft Shopify het
    opnieuw sturen."""
    winkel, gegevens = _webhook_binnen("customers/redact")
    if winkel is None:
        return "", 401
    print(f"AVG-wisverzoek klant van {winkel}: niets opgeslagen, niets gewist.")
    return "", 200


@app.route("/shopify/webhooks/winkel-wissen", methods=["POST"])
def shopify_winkel_wissen():
    """shop/redact. Verplicht.

    Komt 48 uur nadat de app verwijderd is. Hier moet ALLES van deze winkel
    weg, niet alleen de installatie: ook wat we gemeten en geschreven hebben,
    want dat gaat over hem."""
    winkel, gegevens = _webhook_binnen("shop/redact")
    if winkel is None:
        return "", 401
    if db.wis_shopify_winkel(winkel):
        print(f"Alles gewist voor {winkel} na shop/redact.")
    else:
        # Bewust toch 200 terug: anders blijft Shopify het herhalen terwijl het
        # probleem aan onze kant zit. Wel luid in de logs, want dit is een
        # wettelijke verplichting die we dan niet zijn nagekomen.
        print(f"LET OP: wissen na shop/redact MISLUKT voor {winkel}. Handmatig nakijken.")
    return "", 200


def _shopify_klant_actief(winkel, rij, plan=None, is_test=False):
    """Een winkel met een lopend Shopify-abonnement is klant, met alles erbij.

    WAAROM (23 september). De maandmeting en het maandbericht kijken naar de
    tabel klanten. Een abonnee via Shopify kwam daar pas in bij de wekelijkse
    scan, en alleen als zijn mailadres bekend was. Tot die tijd kreeg hij geen
    oplossingen en geen maandbericht, terwijl hij betaalde. Dit zet hem er
    meteen in, haalt een eerdere opzegging weg en zet hem op de winkellijst."""
    webshop_url = scan_engine.normalize_url(rij.get("webshop_url") or "")
    if not webshop_url:
        return False
    email = (rij.get("email") or "").strip()
    if not email:
        # Zonder adres kan er geen klantregel komen (en geen maandbericht).
        # Dat moet JIJ weten, want hij betaalt wel.
        _meld_aan_beheer(
            "Shopify-abonnee zonder mailadres",
            f"{winkel} ({webshop_url}) heeft een lopend abonnement, maar Shopify gaf "
            f"geen mailadres. Er is daarom geen klantregel: geen maandbericht en geen "
            f"oplossingen. Vraag het adres op en zet het in de database.")
        return False
    if not db.get_or_create_klant(webshop_url, email):
        # Deze winkel hoort al bij een klant met een ander adres. Dan niets
        # aan die klant veranderen (niet zijn pakket, niet zijn opzegging).
        _meld_aan_beheer(
            "Shopify-abonnee op een winkel van een andere klant",
            f"{winkel} sloot een abonnement af voor {webshop_url}, maar die winkel hoort "
            f"al bij een ander mailadres. Er is niets aangepast. Bekijk het met de hand.")
        return False
    db.zet_klant_opgezegd(webshop_url, opgezegd=False)
    if plan:
        db.zet_klant_pakket(webshop_url, plan)
    # Een testabonnement (ontwikkelwinkel, de beoordelaar) telt nooit als klant.
    db.zet_klant_test(webshop_url, bool(is_test))
    _zet_in_index(webshop_url)
    return True


@app.route("/shopify/webhooks/abonnement", methods=["POST"])
def shopify_abonnement_gewijzigd():
    """app_subscriptions/update. Een abonnement veranderde van stand.

    Niet blind op de stand in het bericht varen: bij een planwissel (Watch naar
    Fix) stopt Shopify het oude abonnement en start een nieuw, en die twee
    berichten kunnen in willekeurige volgorde aankomen. Dus bij elk bericht
    vragen wij Shopify zelf of er NU een abonnement loopt."""
    winkel, gegevens = _webhook_binnen("app_subscriptions/update")
    if winkel is None:
        return "", 401
    rij = db.get_shopify_winkel(winkel) or {}
    if not rij.get("toegangssleutel") or not rij.get("webshop_url"):
        return "", 200
    try:
        stand = shopify_billing.huidig_abonnement(winkel, _shopify_sleutel(rij))
    except Exception as e:
        print(f"Abonnement nakijken na webhook mislukt voor {winkel}: {e}")
        return "", 200
    if stand.get("fout"):
        # Weten wij het niet zeker, dan niets veranderen. Liever een dag te
        # laat opgezegd dan een betalende klant ten onrechte stilgezet.
        return "", 200
    if stand.get("actief"):
        _shopify_klant_actief(winkel, rij, stand.get("plan"))
    else:
        # Alleen opzeggen als deze klantregel echt van deze Shopify-winkel is
        # (zelfde mailadres). Anders zou een betalende klant via de site
        # stilgezet worden door iets in Shopify.
        url = scan_engine.normalize_url(rij["webshop_url"])
        klant = db.klant_bij_url(url) or {}
        if (klant and not klant.get("mollie_klant_id")
                and (klant.get("email") or "").strip().lower() == (rij.get("email") or "").strip().lower()):
            db.zet_klant_opgezegd(url)
            _meld_aan_beheer("Shopify-abonnement gestopt",
                             f"{winkel} ({url}) heeft zijn abonnement in Shopify gestopt.")
    return "", 200


@app.route("/shopify/webhooks/verwijderd", methods=["POST"])
def shopify_verwijderd():
    """app/uninstalled. De winkelier heeft de app eruit gehaald.

    De sleutel werkt vanaf nu toch niet meer, dus die gooien we meteen weg. De
    rest van de gegevens blijft nog 48 uur staan tot shop/redact komt: haalt
    iemand de app er per ongeluk uit en zet hem terug, dan is zijn geschiedenis
    er nog."""
    winkel, gegevens = _webhook_binnen("app/uninstalled")
    if winkel is None:
        return "", 401
    rij_weg = db.get_shopify_winkel(winkel) or {}
    db.shopify_verwijderd(winkel)
    # App eruit is ook opzeggen: Shopify stopt het abonnement dan zelf.
    # MAAR NIET voor een klant die via de site bij Mollie betaalt (27 september,
    # controle voor de eerste klant). Een Fix-klant van de site die de gratis
    # app probeert en weer verwijdert, werd hier stilgezet terwijl Mollie
    # gewoon bleef afschrijven.
    if rij_weg.get("webshop_url"):
        url_weg = scan_engine.normalize_url(rij_weg["webshop_url"])
        klant_weg = db.klant_bij_url(url_weg) or {}
        if klant_weg and not klant_weg.get("mollie_klant_id"):
            db.zet_klant_opgezegd(url_weg)
    print(f"Shopify-app verwijderd uit {winkel}, sleutel gewist.")
    return "", 200


@app.route("/admin/shopify")
def admin_shopify():
    """Welke winkels de app geïnstalleerd hebben. Voor jou, niet voor klanten."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)
    return render_template(
        "admin_shopify.html",
        winkels=db.get_shopify_winkels(alleen_actief=False),
        actief=shopify_app.beschikbaar(),
        waarom_niet=shopify_app.waarom_niet(),
        rechten=shopify_app.SCOPES,
        sleutel=admin_key,
    )


@app.route("/admin/werkbriefje", methods=["GET", "POST"])
def admin_werkbriefje():
    """Wat jij precies moet doen in de webshop van een klant die betaald heeft.

    Dit is de handmatige uitvoering van het actieplan. De klantpagina toont
    hetzelfde plan aan de klant; deze pagina voegt er toe wat jij nodig hebt om
    het werk te doen: een vak om de OUDE tekst in te plakken voordat je hem
    vervangt, en een vak voor wat je er neergezet hebt.

    Die oude tekst is het hele punt. We beloven de klant dat hij alles kan
    terugzetten, en die belofte is alleen waar als het ergens staat. Plak hem
    dus in voordat je iets vervangt, niet erna, want dan is hij weg."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    melding = None

    if request.method == "POST":
        taak_id = (request.form.get("taak_id") or "").strip()
        actie = (request.form.get("actie") or "opslaan").strip()
        if not webshop_url or not taak_id:
            melding = "Er ontbrak een winkel of een taak."
        elif actie == "verwijderen":
            melding = ("Weggehaald." if db.verwijder_wijziging(webshop_url, taak_id)
                       else "Er stond niets om weg te halen.")
        else:
            gelukt = db.bewaar_wijziging(
                webshop_url, taak_id,
                wat=(request.form.get("wat") or "").strip() or taak_id,
                waar=(request.form.get("waar") or "").strip() or None,
                oude_waarde=(request.form.get("oude_waarde") or "").strip() or None,
                nieuwe_waarde=(request.form.get("nieuwe_waarde") or "").strip() or None,
            )
            melding = "Opgeslagen." if gelukt else "Opslaan is niet gelukt."

    plan = None
    uitvoering = None
    wijzigingen = []
    stek = toepasmodule.ONBEKEND
    if webshop_url:
        plan = _klantgegevens(webshop_url)["actieplan"]
        uitvoering = _laatste_uitvoering(webshop_url)
        wijzigingen = db.get_wijzigingen(webshop_url)

        # De weg door het beheerscherm van dit ene platform bij elke taak. Zonder
        # dit staat er bij elke taak "dit pas je aan in de instellingen van je
        # webshop", en dan zit je alsnog te zoeken in een scherm dat je niet
        # kent. Bij twee klanten is dat vervelend, bij twintig schaalt het niet.
        profiel = db.get_winkelprofiel(webshop_url) or {}
        platform = profiel.get("platform") or (uitvoering or {}).get("platform")
        stek = toepasmodule.stekker(platform)
        plan = toepasmodule.verrijk_plan(plan, platform)

    return render_template(
        "admin_werkbriefje.html",
        webshop_url=webshop_url,
        plan=plan,
        uitvoering=uitvoering,
        stekker=stek,
        # Op taak-id, zodat het formulier bij elke taak meteen laat zien wat er
        # al vastgelegd is en je niet twee keer hetzelfde intypt.
        vastgelegd={w["taak_id"]: w for w in wijzigingen},
        wijzigingen=wijzigingen,
        melding=melding,
        sleutel=admin_key,
    )


@app.route("/admin/oplevering", methods=["GET", "POST"])
def admin_oplevering():
    """Het overzicht dat de klant krijgt als het werk klaar is.

    Bewust een aparte stap en niet automatisch bij "opgeleverd": jij hoort dit
    eerst zelf te lezen voordat het naar een betalende klant gaat."""
    admin_key = os.environ.get("ADMIN_KEY")
    mag, doorsturen = _mag_bij_beheer()
    if not mag:
        return _naar_inloggen()
    if doorsturen:
        return redirect(doorsturen)

    webshop_url = scan_engine.normalize_url((request.args.get("url") or "").strip())
    wijzigingen = db.get_wijzigingen(webshop_url) if webshop_url else []
    uitvoering = _laatste_uitvoering(webshop_url) if webshop_url else None
    melding = None

    if request.method == "POST":
        if not wijzigingen:
            melding = "Er is nog niets vastgelegd om te versturen."
        elif not (uitvoering and uitvoering.get("email")):
            melding = "Bij deze winkel staat geen opdracht met een e-mailadres."
        else:
            klant_token = db.get_or_create_klant(webshop_url, uitvoering["email"])
            monitoring_url = (f"{get_base_url()}/mijn/{klant_token}"
                              if klant_token else None)
            verstuurd = emailing.send_oplevering(
                uitvoering["email"], webshop_url, [dict(w) for w in wijzigingen],
                monitoring_url)
            if verstuurd:
                db.zet_uitvoering_stand(uitvoering["id"], "opgeleverd")
                melding = "Verstuurd, en de opdracht staat nu op opgeleverd."
            else:
                # BEWUST de stand niet aanpassen als de mail mislukte. Anders
                # staat er "opgeleverd" terwijl de klant niets gekregen heeft,
                # en dan valt hij tussen wal en schip.
                melding = ("De mail is NIET verstuurd, dus de opdracht blijft op de "
                           "oude stand staan. Kijk in de logs van Render waarom.")

    return render_template(
        "admin_oplevering.html",
        webshop_url=webshop_url,
        wijzigingen=wijzigingen,
        uitvoering=uitvoering,
        melding=melding,
        sleutel=admin_key,
    )


@app.route("/bedankt")
def bedankt():
    """De pagina waar Mollie de bezoeker naartoe stuurt na het betalen.

    LET OP: Mollie stuurt hierheen bij ELKE afloop, ook bij afbreken,
    mislukken en verlopen, en geeft daarbij geen betaal-id mee dat wij kunnen
    natrekken. Deze pagina kan dus niet weten of er betaald is.

    Daarom staat er nu een tekst die in beide gevallen waar is. Hij stond hier
    als "Bedankt voor je audit, we gaan direct aan de slag", en dat las iemand
    die bij zijn bank op annuleren had gedrukt ook. Die zat vervolgens te
    wachten op een mail die nooit kwam.

    Beter zou zijn om de betaling hier echt na te trekken. Dat vraagt een eigen
    kenmerk dat we bij het aanmaken van de betaling meegeven en opslaan, zodat
    we hier weten welke betaling het was. Staat op de lijst; tot die tijd
    beweren we niets wat we niet weten."""
    checkout_type = request.args.get("type", "audit")

    # Sinds wij het betaalkenmerk in de terugkeerlink zetten kunnen wij hier WEL
    # nakijken wat er gebeurd is. Lukt dat niet, dan valt hij terug op de oude,
    # voorzichtige tekst die in beide gevallen waar is.
    kenmerk = (request.args.get("ref") or "").strip()
    betaald = None
    if kenmerk:
        try:
            stand = payments.get_payment_status(kenmerk)
            if stand is not None:
                # Alleen "niet betaald" zeggen als het ZEKER mislukt is. Een
                # betaling die nog op open of pending staat (een overboeking,
                # een bank die even nadenkt) kreeg anders "Nothing was charged",
                # en een uur later toch een afschrijving (27 september).
                if stand.get("is_paid"):
                    betaald = True
                elif stand.get("status") in ("canceled", "failed", "expired"):
                    betaald = False
        except Exception as e:
            print(f"Betaling natrekken op de bedanktpagina mislukt: {e}")

    if betaald is False:
        # Afgebroken, mislukt of verlopen. Hier hoort geen vinkje en geen
        # bedankje. Iemand die bij zijn bank op annuleren drukte zat anders te
        # wachten op een mail die nooit zou komen.
        return render_template(
            "bedankt.html", gelukt=False,
            title="The payment was not completed",
            message=("Nothing was charged. That happens: cancelled, refused by the bank, "
                     "or expired. You can simply try again."),
            note="Stuck every time? Email hello@krilloai.com and we sort it out by hand.")

    if checkout_type == "monitoring":
        return render_template(
            "bedankt.html", gelukt=betaald,
            title=("Payment received. Welcome to Krillo" if betaald else "Your payment went through Mollie"),
            # 1 oktober: wist hij al zeker dat er betaald is, dan zei de pagina toch
            # "if the payment succeeded". Nu zeker als het zeker is, en de tijd
            # zoals hij echt is (de welkomstmail gaat binnen een paar minuten).
            message=(("Your welcome email with the link to your dashboard is on its way and "
                      "usually arrives within a few minutes. Your dashboard fills itself: your "
                      "rank, the questions where AI names someone else, and your first fixes, "
                      "usually within the hour.") if betaald else
                     ("If the payment succeeded, you get an email with the link to your own "
                      "dashboard within a few minutes. That page says what to do first.")),
            note=(("No email after ten minutes? Look in your spam folder, or get your link "
                   "again via Log in at the top of the page. Questions: hello@krilloai.com.")
                  if betaald else
                  ("If nothing was charged and no email arrives, the payment was not "
                   "completed. You can simply try again, or email hello@krilloai.com.")))
    if checkout_type == "uitvoering":
        return render_template(
            "bedankt.html", gelukt=betaald,
            title="Your payment went through Mollie",
            message=("If the payment succeeded, an email is waiting for you within a few "
                     "minutes. It contains exactly one thing: how to give us access to your "
                     "store. Without that step we cannot start, so do it now. It takes two "
                     "minutes."),
            note=("Nothing received? Check your spam folder first. If nothing was charged "
                  "either, the payment was not completed and you can try again. Otherwise "
                  "email hello@krilloai.com."))
    return render_template(
        "bedankt.html", gelukt=betaald,
        title="Your payment went through Mollie",
        message=("If the payment succeeded, we start right away and you receive the full "
                 "audit by email within a few minutes."),
        note=("Nothing received? Check your spam folder first. If nothing was charged "
              "either, the payment was not completed and you can try again. Otherwise "
              "email hello@krilloai.com."))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, host="0.0.0.0", port=port)
