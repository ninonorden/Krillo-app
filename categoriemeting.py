"""Meten per categorie: een vraag, alle winkels tegelijk gescoord.

DIT IS HET HART VAN DE NIEUWE KRILLO.

Tot nu toe kreeg elke winkel zijn eigen dertig koopvragen, elke week opnieuw
gesteld aan twee modellen. Dat kost ongeveer tien euro per klant per maand,
waardoor de kosten even hard groeien als de omzet en het bedrijf vastloopt rond
de tienduizend euro.

Hier gebeurt het anders. De vraag "waar koop ik online emaille servies" wordt
EEN keer gesteld. Daarna kijken we welke van de veertig servieswinkels in dat
antwoord voorkomen. Een meting, veertig uitkomsten.

Op de lijst van 13 september: 924 winkels in 34 categorieen. Los meten is
2280 euro per ronde, per categorie meten 77,50 euro. Zesentwintig keer
goedkoper, en dat verschil groeit: de kosten hangen aan het aantal categorieen
en niet aan het aantal winkels. Bij tienduizend winkels in dezelfde categorieen
kost het nog steeds 77,50 euro.

WAT ER UIT DE METING KOMT DAT ER EERST NIET WAS: een POSITIE. Niet "genoemd bij
2 van de 30 vragen" maar "41e van de 62, en deze drie stonden boven je". Een
positie is scherper, hij verandert elke week, en hij geeft een reden om terug te
komen.

DRIE KEUZES MET REDEN:

1. De winkellijst uit een antwoord wordt EEN keer gelezen, niet een keer per
   winkel. Dat is waar de besparing echt vandaan komt: het dure werk (een model
   het antwoord laten lezen) is winkelonafhankelijk. Het koppelen aan onze
   winkels is daarna gewoon vergelijken in de database en kost niets.

2. Elk antwoord wordt volledig bewaard. Dat is de dataset die de historie
   opbouwt, en die kan niemand met terugwerkende kracht namaken. Over twee jaar
   is dat de belangrijkste bezitting van dit bedrijf.

3. Een vraag waarin geen enkele winkel genoemd kon worden telt niet mee. Vraagt
   iemand naar een merk of naar algemene informatie, dan komt daar geen webshop
   in voor, ook de beste niet. Zulke vragen meetellen maakt elk cijfer mooier of
   lelijker dan het is.
"""
import json
import os
import threading
import time

import anthropic

import beoordeling
import categorieen
import db
import kosten
import metingen
import scan_engine

MODEL = os.environ.get("CATEGORIE_LEESMODEL", "claude-sonnet-4-6")

# Hoeveel koopvragen er per categorie bedacht worden. Dertig, net als bij de
# oude meting per winkel, zodat de cijfers vergelijkbaar blijven met wat er al
# gemeten is en de belofte op de site niet hoeft te veranderen.
VRAGEN_PER_CATEGORIE = int(os.environ.get("VRAGEN_PER_CATEGORIE", "30"))


# ---------------------------------------------------------------------------
# De koopvragen van een categorie
# ---------------------------------------------------------------------------

def _client():
    sleutel = os.environ.get("ANTHROPIC_API_KEY")
    return anthropic.Anthropic(api_key=sleutel) if sleutel else None


def bedenk_vragen(slug, landnaam="Nederlandse", taal="Nederlands",
                  aantal=VRAGEN_PER_CATEGORIE):
    """Bedenkt de koopvragen voor een hele categorie.

    Belangrijk verschil met koopvragen.py: die kijkt naar de pagina's van EEN
    winkel en bedenkt vragen die bij dat assortiment passen. Hier gaat het om de
    categorie zelf, want dezelfde vraag moet voor alle winkels erin gelden.

    De naam van geen enkele winkel komt in de vragen voor. Anders meet je of AI
    een naam kan herhalen in plaats van of een winkel uit zichzelf genoemd
    wordt."""
    client = _client()
    if client is None:
        return []
    naam = categorieen.naam_van(slug)
    intentie_uitleg = "\n".join(f"- {n}: {u}" for n, u in koopintenties(landnaam))
    per_intentie = max(2, aantal // 6)

    prompt = f"""Je helpt bij het meten welke webshops door AI-assistenten aanbevolen worden.

De categorie is: {naam}
Het land is: {landnaam}

Bedenk {aantal} vragen die een koper in {taal} echt aan ChatGPT of Gemini zou
stellen als hij iets uit deze categorie wil kopen. Verdeel ze over deze soorten,
ongeveer {per_intentie} per soort:
{intentie_uitleg}

REGELS:
- Geen enkele winkelnaam of merknaam in de vragen. Anders meten we of AI een
  naam kan herhalen in plaats van of een winkel uit zichzelf genoemd wordt.
- Elke vraag moet ECHT om een winkel of een plek om te kopen kunnen vragen.
  Vragen die alleen om informatie vragen ("hoe onderhoud ik een koekenpan")
  leveren geen enkele webshop op en zijn dus weggegooid geld.
- Schrijf ze zoals iemand ze intypt: gewone taal, geen zoekmachinetermen.
- Varieer in wat er gezocht wordt binnen de categorie, zodat de meting niet op
  een smal stukje van de markt hangt.

Antwoord ALLEEN met JSON:
{{"vragen": [{{"vraag": "...", "intentie": "algemeen"}}]}}"""

    try:
        gestart = time.monotonic()
        antwoord = client.messages.create(
            model=MODEL, max_tokens=4096,
            messages=[{"role": "user", "content": prompt}])
        kosten.registreer_aanroep(
            provider="anthropic", model=MODEL,
            invoer_tokens=antwoord.usage.input_tokens,
            uitvoer_tokens=antwoord.usage.output_tokens,
            soort="categorievragen-bedenken",
            duur_ms=int((time.monotonic() - gestart) * 1000))
        data = beoordeling._schoon_json(antwoord.content[0].text) or {}
    except Exception as e:
        print(f"Vragen bedenken mislukt voor {slug}: {e}")
        return []

    geldig = {n for n, _ in koopintenties()}
    uit = []
    gezien = set()
    for v in data.get("vragen", []):
        tekst = (v.get("vraag") or "").strip()
        if not tekst or tekst.lower() in gezien:
            continue
        gezien.add(tekst.lower())
        intentie = v.get("intentie") if v.get("intentie") in geldig else "algemeen"
        uit.append({"vraag": tekst, "intentie": intentie})
    return uit[:aantal]


def koopintenties(landnaam="Nederlandse"):
    """Dezelfde zes soorten koopvragen als bij de meting per winkel, zodat de
    cijfers vergelijkbaar blijven met alles wat er al gemeten is."""
    import koopvragen
    return koopvragen.intenties(landnaam)


# ---------------------------------------------------------------------------
# Een antwoord lezen: welke winkels staan erin
# ---------------------------------------------------------------------------
#
# HIER ZIT DE HELE MEETPRIJS IN. Een categorie meten is dertig vragen aan twee
# modellen, dus zestig antwoorden, en elk antwoord moet gelezen worden. Het
# stellen van de vraag kunnen we niet goedkoper maken, want we meten juist wat
# ChatGPT en Gemini antwoorden. Het lezen wel: dat is een leesopdracht met een
# vast format eruit, en daar is geen duur model voor nodig.
#
# Op 14 september kostte een winkel ongeveer 35 cent per maand. Het leeswerk is
# daarvan het grootste deel. Met een goedkoper leesmodel gaat dat naar een paar
# cent.
#
# MAAR: dat mag de uitkomst niet veranderen. Een goedkoper model dat een winkel
# over het hoofd ziet, kost een klant zijn positie. Daarom staat het leesmodel
# in een omgevingsvariabele en zit er een vergelijking in (vergelijk_lezers)
# die het goedkope en het dure model over dezelfde bewaarde antwoorden laat
# lopen en vertelt hoe vaak ze het eens zijn. Pas overstappen als dat klopt.

_PROMPT_SJABLOON = """Je leest het antwoord dat een AI-assistent gaf op een koopvraag.
Haal eruit welke WEBSHOPS erin genoemd worden.

De vraag was:
{vraag}

Het antwoord was:
{antwoord}

WINKELS TEGENOVER MERKEN. Zet een naam alleen bij winkels als je er als
consument rechtstreeks iets kan kopen, dus een webshop of een winkelketen. Zet
hem niet in de lijst als het een merk of label is dat via andere winkels
verkocht wordt. Voorbeelden: fonQ, Loods 5, de Bijenkorf en Flinders zijn
winkels. Serax, HKliving en Ferm Living zijn merken. Een merk met een eigen
webshop telt als winkel.

KON ER UBERHAUPT EEN WINKEL GENOEMD WORDEN. Vraagt de vraag om een winkel of om
een plek om te kopen, dan is dat ja. Vraagt hij alleen naar merken, producten of
algemene informatie, dan is dat nee, ook als er toevallig toch een winkel
langskomt. Zo'n vraag telt niet mee in de meting.

AANBEVOLEN OF ALLEEN GENOEMD. Veel antwoorden geven eerst een lijst en sluiten
af met een advies ("ik zou vooral kijken naar X en Y"). Alleen wie in dat
slotadvies staat, of wie duidelijk als eerste keuze wordt aangeraden, is
aanbevolen. In een rij staan is genoemd, niet aanbevolen.

POSITIE is de volgorde waarin de winkels in het antwoord voorkomen, te beginnen
bij 1.

Antwoord ALLEEN met geldige JSON, niets ervoor of erna:

{{
  "winkel_kon_genoemd": true,
  "winkels": [{{"naam": "fonQ", "positie": 1}}],
  "aanbevolen": ["fonQ"]
}}"""


# BEWUST STAAT HIER HET DURE MODEL ALS STANDAARD. Het goedkope model gaat pas
# aan als de vergelijking op echte antwoorden groen licht geeft, en dat zetten
# wij dan in Render om. Andersom zou betekenen dat een nieuwe versie stilletjes
# de meetkwaliteit verandert van iedereen die al in de ranglijst staat, zonder
# dat iemand het gezien heeft.
#
# Overzetten doe je zo: LEES_PROVIDER op openai en LEES_MODEL op gpt-5.6-luna.
# Dat model is ongeveer vijftien keer goedkoper dan het huidige.
LEES_PROVIDER = os.environ.get("LEES_PROVIDER", "anthropic")
LEES_MODEL = os.environ.get("LEES_MODEL", MODEL)

# Het model waar wij naartoe WILLEN. Dit is wat de vergelijking test, en wat je
# in Render invult zodra die vergelijking groen licht geeft. Het staat hier
# apart van LEES_MODEL, want anders zou de vergelijking het huidige model met
# zichzelf vergelijken en altijd honderd procent zeggen.
KANDIDAAT_PROVIDER = os.environ.get("LEES_KANDIDAAT_PROVIDER", "openai")
KANDIDAAT_MODEL = os.environ.get("LEES_KANDIDAAT_MODEL", "gpt-5.6-luna")

# De modellen die het leeswerk zouden kunnen overnemen, van goedkoop naar duur.
# De prijzen staan in kosten.py; deze lijst is er zodat je ze kunt uitproberen
# zonder nieuwe versie. Wat er uitkomt bepaalt of de hele index vijftien euro
# kost of achtenzeventig.
KANDIDATEN = [
    {"provider": "google", "model": "gemini-2.5-flash-lite", "toonnaam": "Gemini flash-lite (goedkoopst)"},
    {"provider": "openai", "model": "gpt-5.6-luna", "toonnaam": "GPT luna"},
    {"provider": "google", "model": "gemini-3.5-flash-lite", "toonnaam": "Gemini 3.5 flash-lite"},
    {"provider": "openai", "model": "gpt-5.4-mini", "toonnaam": "GPT mini"},
    {"provider": "google", "model": "gemini-3.7-flash", "toonnaam": "Gemini flash"},
]

SLEUTELS = {"openai": "OPENAI_API_KEY", "google": "GOOGLE_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY"}


def _lezer():
    """Welk model de antwoorden leest.

    Ontbreekt de sleutel van het goedkope model, dan valt hij terug op het dure.
    Stilletjes niets meten zou veel erger zijn dan iets duurder meten."""
    if os.environ.get(SLEUTELS.get(LEES_PROVIDER, "")):
        return {"provider": LEES_PROVIDER, "model": LEES_MODEL}
    return {"provider": "anthropic", "model": MODEL}


def _lees_met(aanbieder, prompt):
    """Laat een model de leesopdracht uitvoeren en geeft de JSON terug.

    Loopt via metingen.stel_een_vraag, want daar zitten de herkansingen, de
    wachtrij per aanbieder en de foutafhandeling al in. Twee keer hetzelfde
    bouwen is twee keer dezelfde fout kunnen maken."""
    uitkomst = metingen.stel_een_vraag(aanbieder, prompt, min_tekens=2)
    if not uitkomst["gelukt"]:
        print(f"Antwoord lezen mislukt met {aanbieder['model']}: {uitkomst['foutsoort']}")
        return None
    kosten.registreer_aanroep(
        provider=aanbieder["provider"], model=aanbieder["model"],
        invoer_tokens=uitkomst["invoer_tokens"],
        uitvoer_tokens=uitkomst["uitvoer_tokens"],
        soort="categorie-antwoord-lezen",
        duur_ms=uitkomst["duur_ms"])
    return beoordeling._schoon_json(uitkomst["antwoord"]) or {}


def winkels_uit_antwoord(vraag, antwoord):
    """Haalt uit een AI-antwoord welke WINKELS er genoemd worden, en wie er
    aanbevolen wordt. Zonder te weten om welke winkel het ons te doen is.

    Dat laatste is precies waarom dit goedkoop is. Het dure werk, een model het
    antwoord laten lezen, is winkelonafhankelijk. Voor veertig winkels in de
    categorie hoeft dat dus maar EEN keer, en het koppelen daarna is gewoon
    vergelijken."""
    if not antwoord:
        return None

    prompt = _leesprompt(vraag, antwoord)

    data = _lees_met(_lezer(), prompt)
    if data is None:
        return None

    winkels = []
    for w in data.get("winkels", []):
        naam = (w.get("naam") or "").strip()
        if naam:
            winkels.append({"naam": naam, "positie": w.get("positie")})
    return {
        "winkel_kon_genoemd": bool(data.get("winkel_kon_genoemd")),
        "winkels": winkels,
        "aanbevolen": [n.strip() for n in data.get("aanbevolen", []) if (n or "").strip()],
    }


def koppel_aan_winkels(genoemde, onze_winkels):
    """Legt de namen uit een antwoord naast onze eigen winkels.

    Kost geen enkele modelaanroep. Dit is het stuk dat een meting van een
    categorie in veertig uitkomsten omzet.

    scan_engine.is_eigen_winkel doet het echte werk: die weet dat
    dille-kamille.nl hetzelfde is als "Dille & Kamille", "Dille en Kamille" en
    "Dille-Kamille"."""
    uit = {}
    namen = [w["naam"] for w in genoemde.get("winkels", [])]
    posities = {w["naam"]: w.get("positie") for w in genoemde.get("winkels", [])}
    aanbevolen = {n.lower() for n in genoemde.get("aanbevolen", [])}

    for winkel in onze_winkels:
        url = winkel["webshop_url"]
        treffer = None
        for naam in namen:
            if scan_engine.is_eigen_winkel(url, naam):
                treffer = naam
                break
        uit[url] = {
            "genoemd": treffer is not None,
            "aanbevolen": bool(treffer) and treffer.lower() in aanbevolen,
            "positie": posities.get(treffer) if treffer else None,
            "als_naam": treffer,
        }
    return uit


def _leesprompt(vraag, antwoord):
    """De leesopdracht, los, zodat de vergelijking dezelfde opdracht gebruikt."""
    return _PROMPT_SJABLOON.format(vraag=vraag, antwoord=antwoord)


def vergelijk_lezers(categorie, aantal=20, goedkoop=None, duur=None):
    """Legt het goedkope leesmodel naast het dure, op al bewaarde antwoorden.

    Dit is het bewijs dat de overstap mag. Er wordt geen enkele vraag opnieuw
    gesteld: de antwoorden van de laatste ronde staan er nog, en alleen het
    lezen wordt overgedaan. Twintig antwoorden kost een paar cent.

    WAT ER GEMETEN WORDT, EN WAAROM DAT NIET DE HELE NAMENLIJST IS.

    Op 16 september gaf de eerste vergelijking 100 procent over meetellen en
    60 procent over de namenlijst. Dat leek afkeuren, maar het meet te streng.
    Ziet het ene model vijf winkels en het andere dezelfde vijf plus een
    zesde die niet van ons is, dan zijn de namenlijsten ongelijk terwijl er in
    onze ranglijst geen letter verandert.

    Wat er wel toe doet: de winkels die in ONZE lijst staan. Alleen die krijgen
    een positie, en alleen daar kan een klant iets door verliezen. Daarom wordt
    het groene licht op dat cijfer gebaseerd, en staat het cijfer over de hele
    namenlijst er alleen als achtergrond bij."""
    goedkoop = goedkoop or {"provider": KANDIDAAT_PROVIDER, "model": KANDIDAAT_MODEL}
    duur = duur or {"provider": "anthropic", "model": MODEL}
    if (goedkoop["provider"], goedkoop["model"]) == (duur["provider"], duur["model"]):
        return {"categorie": categorie, "bekeken": 0, "mislukt": 0,
                "fout": "Het kandidaatmodel is hetzelfde als het huidige. Dan "
                        "vergelijk je een model met zichzelf en zegt de uitkomst niets."}

    rijen = db.bewaarde_antwoorden(categorie, aantal)
    uit = {"categorie": categorie, "bekeken": 0, "mislukt": 0,
           "eens_over_meetellen": 0, "eens_over_winkels": 0,
           "eens_over_onze_winkels": 0,
           "goedkoop": goedkoop["model"], "duur": duur["model"], "verschillen": []}
    if not rijen:
        uit["fout"] = f"Geen bewaarde antwoorden voor {categorie}."
        return uit

    # De winkels van deze categorie, want alleen die kunnen een positie krijgen.
    onze_winkels = db.winkels_in_categorie_met_kinderen(categorie)

    for rij in rijen:
        prompt = _leesprompt(rij["vraag"], rij["antwoord"])
        a = _lees_met(goedkoop, prompt)
        b = _lees_met(duur, prompt)
        if a is None or b is None:
            uit["mislukt"] += 1
            continue
        uit["bekeken"] += 1

        mee_a = bool(a.get("winkel_kon_genoemd"))
        mee_b = bool(b.get("winkel_kon_genoemd"))
        if mee_a == mee_b:
            uit["eens_over_meetellen"] += 1

        namen_a = {(w.get("naam") or "").strip().lower()
                   for w in a.get("winkels", []) if (w.get("naam") or "").strip()}
        namen_b = {(w.get("naam") or "").strip().lower()
                   for w in b.get("winkels", []) if (w.get("naam") or "").strip()}
        if namen_a == namen_b:
            uit["eens_over_winkels"] += 1

        # Het cijfer dat telt: zijn ze het eens over ONZE winkels. Alleen die
        # komen in de ranglijst en alleen daar kan iemand een positie door
        # verliezen.
        onze_a = {u for u, hoe in koppel_aan_winkels(a, onze_winkels).items()
                  if hoe["genoemd"]}
        onze_b = {u for u, hoe in koppel_aan_winkels(b, onze_winkels).items()
                  if hoe["genoemd"]}
        if onze_a == onze_b:
            uit["eens_over_onze_winkels"] += 1
        elif len(uit["verschillen"]) < 5:
            uit["verschillen"].append({
                "vraag": rij["vraag"],
                "alleen_goedkoop": sorted(onze_a - onze_b),
                "alleen_duur": sorted(onze_b - onze_a),
                "namen_alleen_goedkoop": sorted(namen_a - namen_b),
                "namen_alleen_duur": sorted(namen_b - namen_a),
            })

    if uit["bekeken"]:
        uit["aandeel_meetellen"] = round(uit["eens_over_meetellen"] / uit["bekeken"], 3)
        uit["aandeel_winkels"] = round(uit["eens_over_winkels"] / uit["bekeken"], 3)
        uit["aandeel_onze_winkels"] = round(
            uit["eens_over_onze_winkels"] / uit["bekeken"], 3)
        # De grens. Onder de negentig procent overeenstemming over ONZE winkels
        # gaat er een klant een positie verliezen die hij niet verloren heeft.
        # Dan is het goedkope model niet goed genoeg, hoeveel het ook scheelt.
        # Het cijfer over de hele namenlijst staat er wel bij, maar telt niet
        # mee: een extra winkel die niet van ons is verandert geen positie.
        uit["mag_over"] = (uit["aandeel_meetellen"] >= 0.95
                           and uit["aandeel_onze_winkels"] >= 0.90)
    return uit


_vgl_stand = {"bezig": False, "categorie": None, "uitkomst": None, "fout": None}
_vgl_slot = threading.Lock()


def vergelijkstand():
    return dict(_vgl_stand)


def _vgl_werk(categorie, aantal, kandidaat=None):
    try:
        _vgl_stand["uitkomst"] = vergelijk_lezers(categorie, aantal=aantal,
                                                  goedkoop=kandidaat)
    except Exception as e:
        _vgl_stand["fout"] = f"{type(e).__name__}: {e}"[:200]
        print(f"Vergelijking mislukt voor {categorie}: {e}")
    finally:
        _vgl_stand["bezig"] = False


def start_vergelijking(categorie, aantal=10, kandidaat=None):
    """Start de vergelijking van de twee leesmodellen op een eigen draad.

    Tien antwoorden door twee modellen is twintig leesopdrachten. Dat past niet
    binnen de twee minuten van gunicorn, en dat is precies de fout die op 11 en
    op 13 september allebei een omgevallen server opleverde."""
    with _vgl_slot:
        if _vgl_stand["bezig"]:
            return False
        _vgl_stand.update({"bezig": True, "categorie": categorie,
                           "uitkomst": None, "fout": None})
    threading.Thread(target=_vgl_werk, args=(categorie, aantal, kandidaat),
                     daemon=True).start()
    return True


def rol_ketens_op(telling, winkels):
    """Telt de adressen van dezelfde keten bij elkaar op en laat eruit wat niet
    in een winkelranglijst hoort.

    Waarom dit moet. In de eerste echte ranglijst stond cookinglife.be eerste en
    cookinglife.nl tweede, met exact dezelfde cijfers. Dat is dezelfde winkel op
    twee plekken, waardoor een top tien er maar acht bevat en een echte
    concurrent onterecht wegzakt.

    Wat hier NIET gebeurt: een vermelding weggooien. cookinglife.be wordt nog
    steeds herkend in een antwoord, de treffer verhuist alleen naar het
    hoofdadres. Wordt een keten in dezelfde vraag onder twee adressen genoemd,
    dan telt dat een keer, want de telling gaat over vragen en niet over
    vermeldingen. Daarom zijn het verzamelingen en geen getallen.

    Eruit gaan: merken, want Brabantia is geen webshop, en regels zonder
    webadres, want die kunnen nooit aan een AI-antwoord gekoppeld worden en
    zouden dus eeuwig onterecht nul scoren."""
    aanwezig = {w["webshop_url"] for w in winkels}
    hoofd_van, soort_van = {}, {}
    for w in winkels:
        url = w["webshop_url"]
        hoofd = w.get("hoort_bij") or url
        # Wijst het hoofdadres naar een winkel buiten deze categorie, dan houdt
        # dit adres zichzelf. Anders verdwijnt de hele telling in het niets.
        hoofd_van[url] = hoofd if hoofd in aanwezig else url
        soort_van[url] = w.get("soort") or "winkel"

    samen = {}
    for url, t in telling.items():
        doel = hoofd_van.get(url, url)
        if soort_van.get(doel, "winkel") != "winkel":
            continue
        bij = samen.setdefault(doel, {"genoemd": set(), "aanbevolen": set(),
                                      "beste_positie": None})
        bij["genoemd"] |= t["genoemd"]
        bij["aanbevolen"] |= t["aanbevolen"]
        p = t["beste_positie"]
        if p and (bij["beste_positie"] is None or p < bij["beste_positie"]):
            bij["beste_positie"] = p
    return samen


# ---------------------------------------------------------------------------
# Een hele categorie meten
# ---------------------------------------------------------------------------

_stand = {"bezig": False, "categorie": None, "vraag_nu": 0, "vragen_totaal": 0,
          "antwoorden": 0, "mislukt": 0, "klaar_op": None, "fout": None}
_slot = threading.Lock()


def stand():
    return dict(_stand)


def meet_categorie(slug, max_vragen=None):
    """Meet een categorie: elke vraag een keer per model, alle winkels gescoord.

    Draait op de aanroepende draad. De beheerpagina start hem via
    start_meting() op een eigen draad, want dit duurt minuten en dat hoort nooit
    aan een verzoek te hangen."""
    winkels = db.winkels_in_categorie_met_kinderen(slug)
    if not winkels:
        return {"fout": f"Geen winkels in {slug}."}

    vragen = db.categorie_vragen(slug)
    if not vragen:
        nieuw = bedenk_vragen(slug)
        if not nieuw:
            return {"fout": "Er konden geen vragen bedacht worden."}
        db.bewaar_categorie_vragen(slug, nieuw)
        vragen = db.categorie_vragen(slug)
    if max_vragen:
        vragen = vragen[:max_vragen]

    aanbieders = metingen.beschikbare_aanbieders()
    if not aanbieders:
        return {"fout": "Geen enkele AI-sleutel gevonden."}

    ronde = db.start_categorie_ronde(slug, len(vragen), len(winkels))
    _stand.update({"vragen_totaal": len(vragen) * len(aanbieders), "vraag_nu": 0})

    # Per winkel bijhouden bij hoeveel vragen hij genoemd en aanbevolen werd.
    telling = {w["webshop_url"]: {"genoemd": set(), "aanbevolen": set(),
                                  "beste_positie": None} for w in winkels}
    telbaar = set()

    for vraag in vragen:
        for aanbieder in aanbieders:
            _stand["vraag_nu"] += 1
            rem = kosten.mag_doorgaan()
            if not rem["mag"]:
                _stand["fout"] = f"Gestopt door de kostenrem: {rem['reden']}"
                break

            uitkomst = metingen.stel_een_vraag(aanbieder, vraag["vraag"])
            if not uitkomst["gelukt"]:
                _stand["mislukt"] += 1
                continue
            kosten.registreer_aanroep(
                provider=aanbieder["provider"], model=aanbieder["model"],
                invoer_tokens=uitkomst["invoer_tokens"],
                uitvoer_tokens=uitkomst["uitvoer_tokens"],
                soort="categoriemeting", duur_ms=uitkomst["duur_ms"])

            genoemde = winkels_uit_antwoord(vraag["vraag"], uitkomst["antwoord"])
            if genoemde is None:
                _stand["mislukt"] += 1
                continue

            db.bewaar_categorie_antwoord(
                ronde, slug, vraag["vraag"], aanbieder["model"],
                uitkomst["antwoord"], genoemde)
            _stand["antwoorden"] += 1

            if not genoemde["winkel_kon_genoemd"]:
                # Een vraag waar geen enkele webshop in kon voorkomen telt niet
                # mee. Anders maak je elk cijfer mooier of lelijker dan het is.
                continue
            telbaar.add(vraag["vraag"])

            for url, hoe in koppel_aan_winkels(genoemde, winkels).items():
                if hoe["genoemd"]:
                    telling[url]["genoemd"].add(vraag["vraag"])
                    p = hoe["positie"]
                    huidig = telling[url]["beste_positie"]
                    if p and (huidig is None or p < huidig):
                        telling[url]["beste_positie"] = p
                if hoe["aanbevolen"]:
                    telling[url]["aanbevolen"].add(vraag["vraag"])

    # Eerst opschonen: ketens bij elkaar, merken en adresloze regels eruit. Dit
    # gebeurt na het tellen en niet ervoor, zodat een vermelding van
    # cookinglife.be wel meetelt maar niet als eigen regel op de lijst komt.
    opgeschoond = rol_ketens_op(telling, winkels)

    # De ranglijst. Aanbevolen weegt zwaarder dan genoemd, want in een rij staan
    # is iets anders dan aangeraden worden.
    rangen = sorted(
        ({"webshop_url": u,
          "genoemd": len(t["genoemd"]),
          "aanbevolen": len(t["aanbevolen"]),
          "beste_positie": t["beste_positie"]} for u, t in opgeschoond.items()),
        key=lambda r: (-r["aanbevolen"], -r["genoemd"], r["webshop_url"]))
    for plek, rij in enumerate(rangen, start=1):
        rij["positie"] = plek
    db.bewaar_categorie_uitkomsten(ronde, slug, rangen, len(telbaar))

    return {"ronde": ronde, "categorie": slug, "winkels": len(rangen),
            "gemeten_adressen": len(winkels),
            "vragen": len(vragen), "telbaar": len(telbaar),
            "antwoorden": _stand["antwoorden"], "mislukt": _stand["mislukt"],
            "ranglijst": rangen}


def _werk(slug, max_vragen):
    try:
        uitkomst = meet_categorie(slug, max_vragen=max_vragen)
        if uitkomst.get("fout"):
            _stand["fout"] = uitkomst["fout"]
        print(f"Categoriemeting klaar: {slug}, {uitkomst}")
    except Exception as e:
        _stand["fout"] = f"{type(e).__name__}: {e}"[:200]
        print(f"Categoriemeting mislukt voor {slug}: {e}")
    finally:
        _stand["bezig"] = False
        _stand["klaar_op"] = time.time()


def start_meting(slug, max_vragen=None):
    """Start een categoriemeting op een eigen draad.

    Nooit in het verzoek zelf: dertig vragen aan twee modellen is een minuut of
    tien, en gunicorn kapt na twee minuten af. Die fout is op 11 en op 13
    september allebei gemaakt en hoeft geen derde keer."""
    with _slot:
        if _stand["bezig"]:
            return False
        _stand.update({"bezig": True, "categorie": slug, "vraag_nu": 0,
                       "vragen_totaal": 0, "antwoorden": 0, "mislukt": 0,
                       "klaar_op": None, "fout": None})
    threading.Thread(target=_werk, args=(slug, max_vragen), daemon=True).start()
    return True
