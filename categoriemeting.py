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

def winkels_uit_antwoord(vraag, antwoord):
    """Haalt uit een AI-antwoord welke WINKELS er genoemd worden, en wie er
    aanbevolen wordt. Zonder te weten om welke winkel het ons te doen is.

    Dat laatste is precies waarom dit goedkoop is. Het dure werk, een model het
    antwoord laten lezen, is winkelonafhankelijk. Voor veertig winkels in de
    categorie hoeft dat dus maar EEN keer, en het koppelen daarna is gewoon
    vergelijken."""
    client = _client()
    if client is None or not antwoord:
        return None

    prompt = f"""Je leest het antwoord dat een AI-assistent gaf op een koopvraag.
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

    try:
        gestart = time.monotonic()
        resp = client.messages.create(
            model=MODEL, max_tokens=2048,
            messages=[{"role": "user", "content": prompt}])
        kosten.registreer_aanroep(
            provider="anthropic", model=MODEL,
            invoer_tokens=resp.usage.input_tokens,
            uitvoer_tokens=resp.usage.output_tokens,
            soort="categorie-antwoord-lezen",
            duur_ms=int((time.monotonic() - gestart) * 1000))
        data = beoordeling._schoon_json(resp.content[0].text) or {}
    except Exception as e:
        print(f"Antwoord lezen mislukt: {e}")
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

    # De ranglijst. Aanbevolen weegt zwaarder dan genoemd, want in een rij staan
    # is iets anders dan aangeraden worden.
    rangen = sorted(
        ({"webshop_url": u,
          "genoemd": len(t["genoemd"]),
          "aanbevolen": len(t["aanbevolen"]),
          "beste_positie": t["beste_positie"]} for u, t in telling.items()),
        key=lambda r: (-r["aanbevolen"], -r["genoemd"], r["webshop_url"]))
    for plek, rij in enumerate(rangen, start=1):
        rij["positie"] = plek
    db.bewaar_categorie_uitkomsten(ronde, slug, rangen, len(telbaar))

    return {"ronde": ronde, "categorie": slug, "winkels": len(winkels),
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
