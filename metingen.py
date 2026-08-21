"""
Krillo - metingen: de koopvragen echt aan AI stellen en de antwoorden bewaren.

Dit is fase 5 stap 3. Tot nu toe meet Krillo of een webshop goed leesbaar is
voor AI. Dat is de bodem, niet het gebouw. Hier begint het echte product: per
webshop de koopvragen stellen aan de AI-assistenten die kopers ook echt
gebruiken, en het volledige antwoord bewaren.

Twee dingen zijn hier belangrijk en die staan bewust vast:

1. Het hele antwoord wordt bewaard, ook de tekst zelf. Het beoordelen van die
   antwoorden (welke winkels worden genoemd, in welke volgorde) is stap 4. Als
   we straks slimmer leren beoordelen, willen we dat op de oude antwoorden
   opnieuw kunnen doen. Data die je niet bewaart kan je niet alsnog verzamelen.

2. We meten via de API. Iemand die in de ChatGPT-app iets vraagt krijgt een
   antwoord dat meeweegt met live zoekresultaten, locatie en geschiedenis. Wij
   meten een benadering daarvan. Dat moet ook zo op de site staan, anders
   verkopen we meer zekerheid dan we hebben.

De vraag gaat er kaal in, precies zoals een koper hem zou typen. Geen extra
instructies, want elke zin die wij eromheen zetten stuurt het antwoord en dan
meten we onszelf in plaats van de werkelijkheid.
"""

import os
import time
import uuid

import requests

import db
import kosten

# Aan of uit. Bedoeld als noodrem: zet METINGEN_AAN op "nee" in Render en er
# wordt niets meer gemeten, zonder dat je code hoeft aan te passen.
METINGEN_AAN = os.environ.get("METINGEN_AAN", "ja").strip().lower() not in ("nee", "no", "false", "0")

# Hoeveel vragen per webshop per ronde. Bewust klein: dertig vragen maal twee
# modellen maal vier weken is al 240 aanroepen per klant per maand.
VRAGEN_PER_RONDE = int(os.environ.get("MEET_VRAGEN_PER_RONDE", "30"))

# Een antwoord op een koopvraag is een paar alinea's. Ruim genoeg, en het
# begrenst meteen wat een uitschieter kan kosten.
MAX_ANTWOORD_TOKENS = int(os.environ.get("MEET_MAX_TOKENS", "900"))

# Google apart, en veel ruimer. De nieuwe Gemini-modellen denken eerst na en
# die denkstappen tellen mee in hetzelfde budget. Met 900 was het budget op
# voordat het antwoord begon: we kregen antwoorden van 30 tokens terug, en een
# keer zelfs 0. Dat werd opgeslagen als een gelukte meting zonder vermelding,
# terwijl er in werkelijkheid niets gemeten was.
MAX_ANTWOORD_TOKENS_GOOGLE = int(os.environ.get("MEET_MAX_TOKENS_GOOGLE", "4000"))

# Optionele noodrem: zet MEET_GOOGLE_DENKBUDGET op 0 om het nadenken helemaal
# uit te zetten. Alleen gebruiken als een ruimer budget niet blijkt te helpen,
# want niet elk model accepteert deze instelling.
GOOGLE_DENKBUDGET = os.environ.get("MEET_GOOGLE_DENKBUDGET", "").strip()

# Een antwoord van een paar woorden is geen antwoord op een koopvraag. Zo'n
# uitkomst mag nooit tellen als "deze winkel werd niet genoemd", want dan maak
# je van een technisch probleem een meetresultaat.
MIN_ANTWOORD_TEKENS = int(os.environ.get("MEET_MIN_TEKENS", "120"))
TIJDSLIMIET = int(os.environ.get("MEET_TIJDSLIMIET", "90"))

# Minimaal aantal seconden tussen twee aanroepen naar dezelfde aanbieder.
#
# Dertig vragen achter elkaar afvuren gaat mis bij aanbieders met een limiet
# per minuut. Google's gratis laag laat er maar een stuk of tien per minuut
# toe, dus zonder pauze mislukt bijna alles met een 429. Eén losse testvraag
# lukt dan wel, en dat maakt het verwarrend: het lijkt alsof de modelnaam fout
# is terwijl het tempo het probleem is.
MIN_INTERVAL = {
    "openai": float(os.environ.get("MEET_INTERVAL_OPENAI", "0.5")),
    "google": float(os.environ.get("MEET_INTERVAL_GOOGLE", "15")),
    "anthropic": float(os.environ.get("MEET_INTERVAL_ANTHROPIC", "0.5")),
}

_laatste_aanroep = {}


def _wacht_je_beurt(provider):
    """Houdt per aanbieder bij wanneer we voor het laatst iets vroegen en wacht
    zo nodig, zodat we netjes onder de limiet per minuut blijven."""
    interval = MIN_INTERVAL.get(provider, 0)
    if interval <= 0:
        return
    vorige = _laatste_aanroep.get(provider)
    if vorige is not None:
        te_wachten = interval - (time.monotonic() - vorige)
        if te_wachten > 0:
            time.sleep(te_wachten)
    _laatste_aanroep[provider] = time.monotonic()

# De modellen waaraan we de vragen stellen. Per aanbieder een eigen sleutel.
# Staat er geen sleutel in Render, dan slaan we die aanbieder gewoon over, dus
# je kan met een deel beginnen en later uitbreiden zonder code te wijzigen.
#
# Waarom OpenAI en Google en niet Anthropic: op de site staat dat we meten of
# ChatGPT en Gemini je webshop noemen. Dan moet je die ook bevragen. Anthropic
# kan erbij door MEET_MODEL_ANTHROPIC in te vullen, maar staat standaard uit.
AANBIEDERS = [
    {
        "provider": "openai",
        "model": os.environ.get("MEET_MODEL_OPENAI", "gpt-5.6-terra"),
        "sleutel_naam": "OPENAI_API_KEY",
        "toonnaam": "ChatGPT (OpenAI)",
    },
    {
        "provider": "google",
        "model": os.environ.get("MEET_MODEL_GOOGLE", "gemini-3.7-flash"),
        "sleutel_naam": "GOOGLE_API_KEY",
        "toonnaam": "Gemini (Google)",
    },
    {
        "provider": "anthropic",
        "model": os.environ.get("MEET_MODEL_ANTHROPIC", ""),
        "sleutel_naam": "ANTHROPIC_API_KEY",
        "toonnaam": "Claude (Anthropic)",
    },
]


def beschikbare_aanbieders():
    """Alleen de aanbieders waarvoor een sleutel en een modelnaam bekend zijn.
    Zo draait dit meteen zodra jij de sleutels in Render zet, en doet het tot
    die tijd niets in plaats van te crashen."""
    klaar = []
    for a in AANBIEDERS:
        if not a["model"]:
            continue
        if not os.environ.get(a["sleutel_naam"]):
            continue
        klaar.append(a)
    return klaar


def _vraag_openai(model, vraag):
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": vraag}],
            "max_completion_tokens": MAX_ANTWOORD_TOKENS,
        },
        timeout=TIJDSLIMIET,
    )
    resp.raise_for_status()
    data = resp.json()
    antwoord = (data["choices"][0]["message"].get("content") or "").strip()
    gebruik = data.get("usage") or {}
    return antwoord, gebruik.get("prompt_tokens", 0), gebruik.get("completion_tokens", 0)


def _vraag_google(model, vraag):
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={
            "x-goog-api-key": os.environ["GOOGLE_API_KEY"],
            "Content-Type": "application/json",
        },
        json=_google_verzoek(vraag),
        timeout=TIJDSLIMIET,
    )
    resp.raise_for_status()
    data = resp.json()
    kandidaten = data.get("candidates") or []
    delen = []
    reden = ""
    if kandidaten:
        reden = kandidaten[0].get("finishReason") or ""
        for deel in (kandidaten[0].get("content") or {}).get("parts") or []:
            if deel.get("text"):
                delen.append(deel["text"])
    gebruik = data.get("usageMetadata") or {}
    tekst = " ".join(delen).strip()

    # Kwam het antwoord niet af, dan is dat een mislukking en geen uitkomst.
    if not tekst or reden == "MAX_TOKENS":
        gedacht = gebruik.get("thoughtsTokenCount", 0)
        raise RuntimeError(
            f"Google gaf geen bruikbaar antwoord (finishReason={reden or 'onbekend'}, "
            f"denktokens={gedacht}). Verhoog MEET_MAX_TOKENS_GOOGLE of zet "
            f"MEET_GOOGLE_DENKBUDGET op 0."
        )

    return (
        tekst,
        gebruik.get("promptTokenCount", 0),
        gebruik.get("candidatesTokenCount", 0),
    )


def _google_verzoek(vraag):
    config = {"maxOutputTokens": MAX_ANTWOORD_TOKENS_GOOGLE}
    if GOOGLE_DENKBUDGET != "":
        try:
            config["thinkingConfig"] = {"thinkingBudget": int(GOOGLE_DENKBUDGET)}
        except ValueError:
            pass
    return {"contents": [{"parts": [{"text": vraag}]}], "generationConfig": config}


def _vraag_anthropic(model, vraag):
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": MAX_ANTWOORD_TOKENS,
            "messages": [{"role": "user", "content": vraag}],
        },
        timeout=TIJDSLIMIET,
    )
    resp.raise_for_status()
    data = resp.json()
    delen = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    gebruik = data.get("usage") or {}
    return (
        " ".join(delen).strip(),
        gebruik.get("input_tokens", 0),
        gebruik.get("output_tokens", 0),
    )


_VRAGERS = {
    "openai": _vraag_openai,
    "google": _vraag_google,
    "anthropic": _vraag_anthropic,
}


def stel_een_vraag(aanbieder, vraag):
    """Stelt een vraag aan een model, met een paar pogingen bij een storing.

    Mislukt het alsnog, dan geven we dat eerlijk terug in plaats van een leeg
    antwoord op te slaan alsof de winkel niet genoemd werd. Een mislukte meting
    is iets anders dan een meting zonder vermelding, en dat verschil moet in de
    cijfers terug te vinden zijn."""
    vrager = _VRAGERS.get(aanbieder["provider"])
    if vrager is None:
        return {"gelukt": False, "foutsoort": "onbekende aanbieder", "pogingen": 0,
                "antwoord": "", "invoer_tokens": 0, "uitvoer_tokens": 0, "duur_ms": 0}

    laatste_fout = ""
    gestart = time.monotonic()
    for poging in range(1, kosten.MAX_POGINGEN + 1):
        try:
            _wacht_je_beurt(aanbieder["provider"])
            antwoord, invoer, uitvoer = vrager(aanbieder["model"], vraag)
            if len(antwoord) < MIN_ANTWOORD_TEKENS:
                raise RuntimeError(
                    f"Antwoord van {len(antwoord)} tekens is te kort om iets uit te lezen. "
                    f"Dit telt als mislukt, niet als een winkel die niet genoemd werd."
                )
            return {
                "gelukt": True,
                "antwoord": antwoord,
                "invoer_tokens": invoer,
                "uitvoer_tokens": uitvoer,
                "duur_ms": int((time.monotonic() - gestart) * 1000),
                "pogingen": poging,
                "foutsoort": None,
            }
        except Exception as e:
            # De losse foutregel van een HTTP-fout bevat alleen de code en de
            # URL. Wat er precies aan de hand is staat in het antwoord zelf,
            # bijvoorbeeld of een limiet per minuut of per dag geraakt is.
            # Zonder die tekst sta je te gissen.
            uitleg = ""
            body = getattr(getattr(e, "response", None), "text", "") or ""
            if body:
                uitleg = " | " + " ".join(body.split())[:220]
            laatste_fout = (f"{type(e).__name__}: {e}"[:200] + uitleg)[:420]
            # Bij een 429 zegt de aanbieder: je gaat te snel. Dan heeft snel
            # opnieuw proberen geen zin, dan moet je juist langer wachten.
            antwoord_obj = getattr(e, "response", None)
            code = getattr(antwoord_obj, "status_code", None)
            # 429 is te snel, 503 is de aanbieder zelf die het even niet
            # aankan. In beide gevallen helpt meteen opnieuw proberen niet,
            # alleen wachten helpt.
            te_snel = code in (429, 503)
            if poging < kosten.MAX_POGINGEN:
                if te_snel:
                    wacht = (10 if code == 503 else 20) * poging
                    herhaal = getattr(antwoord_obj, "headers", {}) or {}
                    try:
                        wacht = max(wacht, int(float(herhaal.get("Retry-After", 0))))
                    except (TypeError, ValueError):
                        pass
                    reden = "overbelast" if code == 503 else "te snel"
                    print(f"{aanbieder['provider']} {reden}, {wacht}s wachten.")
                    time.sleep(wacht)
                else:
                    time.sleep(2 * poging)

    return {
        "gelukt": False,
        "antwoord": "",
        "invoer_tokens": 0,
        "uitvoer_tokens": 0,
        "duur_ms": int((time.monotonic() - gestart) * 1000),
        "pogingen": kosten.MAX_POGINGEN,
        "foutsoort": laatste_fout,
    }


def _kies_vragen(vragen, grens):
    """Kiest welke vragen deze ronde meegaan.

    Simpelweg de eerste dertig pakken gaat mis: de vragen komen gesorteerd op
    intentie binnen, dus dan meet je dertig keer 'algemeen' en geen enkele
    winkelvraag. Daarom pakken we om de beurt een vraag uit elke intentie, tot
    de grens bereikt is. Blijven er intenties met minder vragen over, dan vullen
    de andere de rest aan."""
    if len(vragen) <= grens:
        return vragen

    per_intentie = {}
    for v in vragen:
        per_intentie.setdefault(v.get("intentie") or "overig", []).append(v)

    gekozen = []
    ronde = 0
    while len(gekozen) < grens:
        toegevoegd = False
        for naam in sorted(per_intentie):
            lijst = per_intentie[naam]
            if ronde < len(lijst):
                gekozen.append(lijst[ronde])
                toegevoegd = True
                if len(gekozen) == grens:
                    break
        if not toegevoegd:
            break
        ronde += 1
    return gekozen


def meet_webshop(webshop_url, max_vragen=None):
    """Stelt de actieve koopvragen van een webshop aan alle beschikbare
    modellen en bewaart elk antwoord volledig.

    Over de kostenrem: die wordt gecheckt voor elke vraag, dus voordat de
    modellen bevraagd worden. Bewust niet voor elke losse aanroep, want dat
    zijn twee databasevragen per keer en dat maakt een ronde onnodig traag.
    Tussen twee controles zit hooguit een handvol aanroepen van een paar cent,
    dus als rem is dit ruim genoeg."""
    samenvatting = {
        "webshop_url": webshop_url,
        "meting_id": None,
        "gesteld": 0,
        "gelukt": 0,
        "mislukt": 0,
        "gestopt_door_rem": False,
        "reden": None,
    }

    if not METINGEN_AAN:
        samenvatting["reden"] = "Metingen staan uit (METINGEN_AAN)."
        return samenvatting

    aanbieders = beschikbare_aanbieders()
    if not aanbieders:
        samenvatting["reden"] = (
            "Geen enkele AI-sleutel gevonden voor de metingen. "
            "Zet OPENAI_API_KEY en GOOGLE_API_KEY in Render."
        )
        print(samenvatting["reden"])
        return samenvatting

    vragen = db.get_koopvragen(webshop_url, alleen_actief=True)
    if not vragen:
        samenvatting["reden"] = "Deze webshop heeft nog geen actieve koopvragen."
        return samenvatting

    grens = max_vragen or VRAGEN_PER_RONDE
    vragen = _kies_vragen(vragen, grens)

    meting_id = uuid.uuid4().hex
    samenvatting["meting_id"] = meting_id
    te_snel = {}
    opgegeven = set()
    print(f"Meting {meting_id[:8]} gestart voor {webshop_url}: "
          f"{len(vragen)} vragen aan {len(aanbieders)} model(len).")

    for v in vragen:
        rem = kosten.mag_doorgaan(webshop_url=webshop_url)
        if not rem["mag"]:
            samenvatting["gestopt_door_rem"] = True
            samenvatting["reden"] = rem["reden"]
            print(f"Meting gestopt door de kostenrem: {rem['reden']}")
            break

        for aanbieder in aanbieders:
            if aanbieder["provider"] in opgegeven:
                continue
            uitkomst = stel_een_vraag(aanbieder, v["vraag"])
            samenvatting["gesteld"] += 1
            if uitkomst["gelukt"]:
                samenvatting["gelukt"] += 1
                te_snel[aanbieder["provider"]] = 0
            else:
                samenvatting["mislukt"] += 1
                print(f"Vraag mislukt bij {aanbieder['provider']}: {uitkomst['foutsoort']}")
                # Blijft een aanbieder zeggen dat we te snel gaan, dan heeft
                # doorgaan geen zin. Dan zit je aan een limiet per minuut of
                # per dag, en dertig vragen lang blijven proberen kost alleen
                # maar tijd. We slaan hem over en melden dat eerlijk.
                fout = uitkomst["foutsoort"] or ""
                if "429" in fout or "503" in fout:
                    te_snel[aanbieder["provider"]] = te_snel.get(aanbieder["provider"], 0) + 1
                    if te_snel[aanbieder["provider"]] >= 3:
                        opgegeven.add(aanbieder["provider"])
                        print(f"{aanbieder['provider']} overgeslagen: te vaak geweigerd of overbelast.")
                else:
                    te_snel[aanbieder["provider"]] = 0

            kosten.registreer_aanroep(
                provider=aanbieder["provider"],
                model=aanbieder["model"],
                invoer_tokens=uitkomst["invoer_tokens"],
                uitvoer_tokens=uitkomst["uitvoer_tokens"],
                soort="koopvraag-stellen",
                webshop_url=webshop_url,
                duur_ms=uitkomst["duur_ms"],
                gelukt=uitkomst["gelukt"],
                foutsoort=uitkomst["foutsoort"],
                pogingen=uitkomst["pogingen"],
            )

            db.bewaar_ai_antwoord({
                "meting_id": meting_id,
                "webshop_url": webshop_url,
                "vraag_id": v.get("id"),
                "vraag": v["vraag"],
                "intentie": v.get("intentie"),
                "provider": aanbieder["provider"],
                "model": aanbieder["model"],
                "antwoord": uitkomst["antwoord"],
                "gelukt": uitkomst["gelukt"],
                "foutsoort": uitkomst["foutsoort"],
                "invoer_tokens": uitkomst["invoer_tokens"],
                "uitvoer_tokens": uitkomst["uitvoer_tokens"],
                "duur_ms": uitkomst["duur_ms"],
            })

    print(f"Meting {meting_id[:8]} klaar voor {webshop_url}: "
          f"{samenvatting['gelukt']} gelukt, {samenvatting['mislukt']} mislukt.")
    return samenvatting


def ruwe_naamtreffer(antwoord, webshop_url):
    """Kijkt alleen of de naam van de winkel letterlijk in het antwoord staat.

    LET OP: dit is met opzet dom en het is NIET de meting. Een winkel kan
    genoemd worden zonder dat de naam precies zo gespeld staat, en een naam kan
    voorkomen zonder dat het een aanbeveling is. Het echte beoordelen van
    antwoorden is stap 4 en doet een agent. Dit is puur bedoeld om zelf snel
    over de antwoorden te kunnen kijken, en het staat daarom alleen op de
    beheerpagina en nooit bij een klant."""
    if not antwoord or not webshop_url:
        return False
    naam = webshop_url.lower()
    for weg in ("https://", "http://", "www."):
        naam = naam.replace(weg, "")
    kern = naam.split("/")[0].split(".")[0]
    if len(kern) < 4:
        return False
    # Alles wat geen letter of cijfer is weghalen, aan beide kanten. Zo vinden
    # we "Bergzicht Outdoor" ook terug als het domein bergzicht-outdoor.nl is.
    plat = lambda t: "".join(teken for teken in t.lower() if teken.isalnum())
    return plat(kern) in plat(antwoord)


# ---------------------------------------------------------------------------
# Hulpmiddel om te controleren welke modellen jouw sleutels echt mogen
# gebruiken. Een verkeerde modelnaam is de meest voorkomende reden dat alle
# aanroepen bij een aanbieder mislukken, en dat zie je alleen als je de lijst
# bij de aanbieder zelf opvraagt.
# ---------------------------------------------------------------------------

def haal_modellijst(provider):
    """Vraagt bij een aanbieder op welke modellen deze sleutel mag gebruiken.

    Geeft terug: {"gelukt": bool, "modellen": [namen], "fout": tekst}."""
    try:
        if provider == "openai":
            sleutel = os.environ.get("OPENAI_API_KEY")
            if not sleutel:
                return {"gelukt": False, "modellen": [], "fout": "Geen OPENAI_API_KEY ingesteld."}
            resp = requests.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {sleutel}"},
                timeout=30,
            )
            resp.raise_for_status()
            namen = sorted(m["id"] for m in resp.json().get("data", []))
            return {"gelukt": True, "modellen": namen, "fout": None}

        if provider == "google":
            sleutel = os.environ.get("GOOGLE_API_KEY")
            if not sleutel:
                return {"gelukt": False, "modellen": [], "fout": "Geen GOOGLE_API_KEY ingesteld."}
            resp = requests.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": sleutel},
                timeout=30,
            )
            resp.raise_for_status()
            namen = sorted(
                m["name"].replace("models/", "")
                for m in resp.json().get("models", [])
                if "generateContent" in (m.get("supportedGenerationMethods") or [])
            )
            return {"gelukt": True, "modellen": namen, "fout": None}

        if provider == "anthropic":
            sleutel = os.environ.get("ANTHROPIC_API_KEY")
            if not sleutel:
                return {"gelukt": False, "modellen": [], "fout": "Geen ANTHROPIC_API_KEY ingesteld."}
            resp = requests.get(
                "https://api.anthropic.com/v1/models",
                headers={"x-api-key": sleutel, "anthropic-version": "2023-06-01"},
                timeout=30,
            )
            resp.raise_for_status()
            namen = sorted(m["id"] for m in resp.json().get("data", []))
            return {"gelukt": True, "modellen": namen, "fout": None}

        return {"gelukt": False, "modellen": [], "fout": "Onbekende aanbieder."}
    except Exception as e:
        return {"gelukt": False, "modellen": [], "fout": f"{type(e).__name__}: {e}"[:400]}


def test_aanbieder(aanbieder):
    """Stelt een piepklein vraagje om te zien of deze combinatie van sleutel en
    modelnaam werkt. Kost bijna niets en geeft de echte foutmelding terug."""
    uitkomst = stel_een_vraag(aanbieder, "Zeg alleen het woord: werkt")
    return {
        "gelukt": uitkomst["gelukt"],
        "antwoord": (uitkomst["antwoord"] or "")[:200],
        "fout": uitkomst["foutsoort"],
    }
