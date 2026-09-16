"""De winkellijst opschonen voordat er een openbare ranglijst van gemaakt wordt.

WAAROM DIT BESTAAT

Op 14 september kwam de eerste echte ranglijst uit de nieuwe categoriemeting:
servies en tafelgerei, veertig winkels. Er stonden drie soorten fouten in, en
alle drie zijn ze blokkerend zodra zo'n lijst openbaar wordt.

1. DEZELFDE KETEN TWEE KEER. cookinglife.be stond eerste en cookinglife.nl
   tweede. Villeroy & Boch stond op zeven en op acht. Dat is niet een top tien
   met tien winkels erin maar met acht, en een echte concurrent zakt er
   onterecht door weg. Voor de winkel zelf is het ook raar: hij ziet zichzelf
   twee keer, met twee verschillende posities.

2. MERKEN DIE GEEN WEBSHOP ZIJN. Villeroy & Boch en Brabantia zijn fabrikanten.
   Die horen niet in een lijst van webshops. Ze horen er wel bij te zijn, want
   voor een merk is het juist interessant om te weten waar het genoemd wordt,
   maar dan in een aparte lijst en met een ander verhaal.

3. REGELS ZONDER WEBADRES. Zestien van de veertig stonden er met alleen een
   naam: "Atelier Object", "Blubber en Glas", "Hamono", "Mento". Die kunnen wij
   nooit koppelen aan een naam in een AI-antwoord, want de koppeling loopt via
   het webadres. Ze scoren dus altijd nul, ook als ChatGPT ze wel degelijk
   noemt. Dat is oneerlijk tegenover die winkel en het is een klacht die je
   niet kunt weerleggen.

WAT DIT BESTAND DOET

Het zet bij elke winkel twee dingen vast:

- soort: winkel, merk, of geen-adres.
- hoort_bij: het webadres van de winkel waar deze onder valt. Voor
  cookinglife.be is dat cookinglife.nl. Voor de meeste winkels is dat zichzelf.

De meting blijft daarna gewoon ALLE adressen herkennen, ook cookinglife.be, en
telt de treffer bij het hoofdadres op. Zo gaat er geen enkele vermelding
verloren en staat er toch een schone lijst op het scherm.

EEN KEUZE MET REDEN: het ketens-samenvoegen gebeurt zonder modelaanroep, puur
op het webadres. Dat is te controleren, kost niets, en werkt in elk land
hetzelfde. Alleen voor merk-of-winkel is een model nodig, want dat kun je aan
een adres niet zien.
"""
import json
import os
import threading
import time

import anthropic

import beoordeling
import db
import kosten

MODEL = os.environ.get("OPSCHOON_MODEL", "claude-sonnet-4-6")
PER_AANROEP = int(os.environ.get("OPSCHOON_PER_AANROEP", "40"))

SOORT_WINKEL = "winkel"
SOORT_MERK = "merk"
SOORT_GEEN_ADRES = "geen-adres"

# Landcodes en veelgebruikte uitgangen. Hiermee halen wij de stam van een adres
# eraf: cookinglife.be en cookinglife.nl hebben allebei de stam "cookinglife".
UITGANGEN = (
    ".co.uk", ".com.au", ".co.nz", ".com.br",
    ".nl", ".be", ".de", ".at", ".fr", ".com", ".eu", ".co", ".net", ".org",
    ".shop", ".store", ".online", ".es", ".it", ".se", ".dk", ".pl", ".uk",
)

# Onder deze lengte voegen wij nooit samen. "abc.nl" en "abc.be" kunnen prima
# twee losse bedrijven zijn; bij een stam van vier letters of meer is toeval
# een stuk onwaarschijnlijker.
STAM_MINIMUM = int(os.environ.get("OPSCHOON_STAM_MINIMUM", "5"))

# Welk land wint als dezelfde keten meerdere adressen heeft. De volgorde is niet
# willekeurig: de meeste van onze winkels zijn Nederlands, en een bezoeker die
# zijn eigen winkel zoekt verwacht het adres van zijn eigen land bovenaan.
VOORKEUR = (".nl", ".be", ".com", ".de", ".fr")


# ---------------------------------------------------------------------------
# Zonder modelaanroep: wat je aan het adres alleen al kunt zien
# ---------------------------------------------------------------------------

def _kaal(url):
    """Het adres zonder protocol, zonder www en zonder pad."""
    adres = (url or "").strip().lower()
    for weg in ("https://", "http://"):
        if adres.startswith(weg):
            adres = adres[len(weg):]
    if adres.startswith("www."):
        adres = adres[4:]
    return adres.split("/")[0].split("?")[0].strip()


def heeft_webadres(url):
    """Is dit een echt webadres, of staat hier gewoon een naam?

    "Atelier Object" is geen adres. "https://atelierobject.nl" wel. Alles
    zonder punt, met een spatie erin, of zonder herkenbare uitgang valt af."""
    adres = _kaal(url)
    if not adres or " " in adres or "." not in adres:
        return False
    if adres.startswith(".") or adres.endswith("."):
        return False
    laatste = "." + adres.rsplit(".", 1)[-1]
    # Een uitgang van een of twee letters bestaat niet, en een uitgang met een
    # cijfer erin is geen domein maar een IP-adres of een typefout.
    return len(laatste) >= 3 and laatste[1:].isalpha()


def stam(url):
    """De naam zonder landuitgang: cookinglife.be wordt "cookinglife"."""
    adres = _kaal(url)
    if not adres:
        return ""
    for uitgang in sorted(UITGANGEN, key=len, reverse=True):
        if adres.endswith(uitgang):
            return adres[:-len(uitgang)]
    return adres.rsplit(".", 1)[0]


def kies_hoofd(urls):
    """Welk adres van een keten het hoofdadres wordt."""
    if not urls:
        return None

    def rang(url):
        adres = _kaal(url)
        for plek, uitgang in enumerate(VOORKEUR):
            if adres.endswith(uitgang):
                return (plek, len(adres), adres)
        return (len(VOORKEUR), len(adres), adres)

    return sorted(urls, key=rang)[0]


def groepeer_ketens(urls):
    """Geeft {webadres: hoofdadres} voor alles wat bij elkaar hoort.

    Kost geen enkele modelaanroep. Adressen zonder keten komen er ook in, met
    zichzelf als hoofdadres, zodat de aanroeper nooit hoeft te controleren of
    een adres in de uitkomst zit."""
    groepen = {}
    los = []
    for url in urls:
        if not heeft_webadres(url):
            los.append(url)
            continue
        s = stam(url)
        if len(s) < STAM_MINIMUM:
            los.append(url)
            continue
        groepen.setdefault(s, []).append(url)

    uit = {url: url for url in los}
    for leden in groepen.values():
        hoofd = kies_hoofd(leden)
        for url in leden:
            uit[url] = hoofd
    return uit


# ---------------------------------------------------------------------------
# Met modelaanroep: merk of winkel
# ---------------------------------------------------------------------------

def _client():
    sleutel = os.environ.get("ANTHROPIC_API_KEY")
    if not sleutel:
        return None
    return anthropic.Anthropic(api_key=sleutel)


def _prompt(winkels):
    regels = []
    for w in winkels:
        stukken = [w["webshop_url"]]
        if w.get("naam"):
            stukken.append(w["naam"])
        regels.append("- " + " | ".join(stukken))
    return f"""Hieronder staan webadressen van bedrijven. Bepaal per bedrijf of het
een WINKEL is of een MERK.

winkel: verkoopt online rechtstreeks aan consumenten en voert daarbij meerdere
merken of eigen producten. Een webshop dus.

merk: een fabrikant of ontwerpmerk dat vooral via andere winkels verkocht wordt.
Villeroy & Boch en Brabantia zijn merken, ook al kun je op hun eigen site
bestellen. Kenmerk: als je aan iemand vraagt waar hij dit koopt, noemt hij een
winkel en niet deze site.

onbekend: je weet het niet zeker. Kies dit liever dan gokken.

{chr(10).join(regels)}

Antwoord met alleen JSON, zonder uitleg eromheen:
{{"soorten": [{{"webshop_url": "...", "soort": "winkel"}}]}}"""


def merken_in(winkels):
    """Geeft {webshop_url: "winkel" of "merk"} terug voor een groep winkels.

    Alles waar het model "onbekend" op zegt komt er niet in voor. Die winkel
    houdt dan zijn huidige soort en wordt later opnieuw bekeken. Een verzonnen
    indeling is erger dan geen indeling: een winkel die onterecht als merk uit
    de ranglijst verdwijnt merkt dat zelf, en dan ben je in een keer al het
    vertrouwen kwijt."""
    client = _client()
    if client is None or not winkels:
        return {}

    rem = kosten.mag_doorgaan()
    if not rem["mag"]:
        print(f"Opschonen geblokkeerd door de kostenrem: {rem['reden']}")
        return {}

    try:
        gestart = time.monotonic()
        antwoord = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            messages=[{"role": "user", "content": _prompt(winkels)}],
        )
        kosten.registreer_aanroep(
            provider="anthropic", model=MODEL,
            invoer_tokens=antwoord.usage.input_tokens,
            uitvoer_tokens=antwoord.usage.output_tokens,
            soort="winkels-opschonen",
            duur_ms=int((time.monotonic() - gestart) * 1000),
        )
        data = beoordeling._schoon_json(antwoord.content[0].text)
    except Exception as e:
        print(f"Merk-of-winkel bepalen mislukt: {e}")
        return {}

    uit = {}
    for regel in (data or {}).get("soorten", []):
        url = (regel.get("webshop_url") or "").strip()
        soort = (regel.get("soort") or "").strip().lower()
        if url and soort in (SOORT_WINKEL, SOORT_MERK):
            uit[url] = soort
    return uit


# ---------------------------------------------------------------------------
# Het hele opschoonwerk, op een eigen draad
# ---------------------------------------------------------------------------

# De voortgang moet ONDERWEG kloppen, niet pas aan het eind. Op 16 september
# stond het opschonen drieentwintig minuten te draaien zonder dat er ergens te
# zien was hoe ver hij was of hoe lang het nog duurde. Een knop waarvan je niet
# weet of hij nog leeft is net zo erg als een knop die stuk is: je drukt hem
# nog een keer in, en dan betaal je alles dubbel.
_stand = {"bezig": False, "stap": None, "bekeken": 0, "totaal": 0,
          "zonder_adres": 0, "merken": 0, "samengevoegd": 0,
          "aanroepen": 0, "aanroepen_totaal": 0,
          "gestart_op": None, "klaar_op": None, "fout": None}
_slot = threading.Lock()


def stand():
    """De voortgang, met verstreken tijd en een schatting van wat er nog komt."""
    uit = dict(_stand)
    if uit["gestart_op"]:
        uit["verstreken_sec"] = int(time.time() - uit["gestart_op"])
        uit["verstreken"] = _duur(uit["verstreken_sec"])
        gedaan, totaal = uit["aanroepen"], uit["aanroepen_totaal"]
        if gedaan and totaal and gedaan < totaal:
            per_stuk = uit["verstreken_sec"] / gedaan
            uit["resterend"] = _duur(int(per_stuk * (totaal - gedaan)))
    return uit


def _duur(seconden):
    """Een tijdsduur in gewone taal: "3 minuten", niet "PT3M"."""
    if seconden < 60:
        return f"{seconden} seconden"
    minuten = seconden // 60
    if minuten < 60:
        return f"{minuten} minuut" if minuten == 1 else f"{minuten} minuten"
    uren, rest = divmod(minuten, 60)
    return f"{uren} uur en {rest} minuten"


def schoon_alles_op(hoeveel=None):
    """Loopt de hele lijst na en zet soort en hoort_bij vast.

    Geeft een verslag terug. Draait op de aanroepende draad; de beheerpagina
    start hem via start_opschonen() op een eigen draad, want dit doet tientallen
    modelaanroepen en dat hoort nooit aan een verzoek te hangen."""
    winkels = db.alle_benaderingen_kaal(hoeveel)
    verslag = {"bekeken": len(winkels), "zonder_adres": 0, "merken": 0,
               "samengevoegd": 0, "aanroepen": 0}
    _stand["totaal"] = len(winkels)
    if not winkels:
        return verslag

    # Stap 1, gratis: wat geen adres is kan nooit gekoppeld worden.
    _stand["stap"] = "adressen nakijken"
    zonder = [w["webshop_url"] for w in winkels
              if not heeft_webadres(w["webshop_url"])]
    # In EEN opdracht, niet een per winkel. Zie db.zet_soorten voor waarom.
    db.zet_soorten({url: SOORT_GEEN_ADRES for url in zonder})
    verslag["zonder_adres"] = len(zonder)
    _stand["zonder_adres"] = len(zonder)

    # Stap 2, ook gratis: ketens samenvoegen.
    _stand["stap"] = "ketens samenvoegen"
    met_adres = [w["webshop_url"] for w in winkels
                 if heeft_webadres(w["webshop_url"])]
    koppeling = groepeer_ketens(met_adres)
    db.zet_hoort_bij_veel(koppeling)
    samen = sum(1 for url, hoofd in koppeling.items() if hoofd != url)
    verslag["samengevoegd"] = samen
    _stand["samengevoegd"] = samen

    # Stap 3, met modelaanroepen: merk of winkel. Alleen de hoofdadressen, want
    # alleen die komen in een ranglijst terecht.
    _stand["stap"] = "merk of winkel"
    hoofden = [w for w in winkels
               if heeft_webadres(w["webshop_url"])
               and koppeling.get(w["webshop_url"]) == w["webshop_url"]]
    # Nu pas weten wij hoeveel aanroepen er komen, en dus hoe lang het duurt.
    _stand["aanroepen_totaal"] = (len(hoofden) + PER_AANROEP - 1) // PER_AANROEP
    for begin in range(0, len(hoofden), PER_AANROEP):
        groep = hoofden[begin:begin + PER_AANROEP]
        uitkomst = merken_in(groep)
        verslag["aanroepen"] += 1
        _stand["aanroepen"] = verslag["aanroepen"]
        db.zet_soorten(uitkomst)
        verslag["merken"] += sum(1 for s in uitkomst.values() if s == SOORT_MERK)
        _stand["merken"] = verslag["merken"]
        if not uitkomst:
            # Geen sleutel of de kostenrem staat dicht. Doorgaan heeft dan geen
            # zin en kost alleen maar tijd.
            break

    _stand["bekeken"] = len(winkels)
    _stand["stap"] = "klaar"
    return verslag


def _werk(hoeveel):
    try:
        verslag = schoon_alles_op(hoeveel)
        print(f"Opschonen klaar: {verslag}")
    except Exception as e:
        _stand["fout"] = f"{type(e).__name__}: {e}"[:200]
        print(f"Opschonen mislukt: {e}")
    finally:
        _stand["bezig"] = False
        _stand["klaar_op"] = time.time()


def start_opschonen(hoeveel=None):
    """Start het opschonen op een eigen draad.

    Nooit in het verzoek zelf. Die fout is op 11 en op 13 september gemaakt en
    kostte allebei de keren een omgevallen server."""
    with _slot:
        if _stand["bezig"]:
            return False
        _stand.update({"bezig": True, "stap": "starten", "bekeken": 0,
                       "totaal": 0, "zonder_adres": 0, "merken": 0,
                       "samengevoegd": 0, "aanroepen": 0, "aanroepen_totaal": 0,
                       "gestart_op": time.time(), "klaar_op": None, "fout": None})
    threading.Thread(target=_werk, args=(hoeveel,), daemon=True).start()
    return True
