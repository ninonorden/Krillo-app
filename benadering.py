"""Winkels benaderen, automatisch, met een rem erop.

Wat hier gebeurt is steeds hetzelfde rondje, elk uur een klein stukje:

  1. Van een paar nieuwe winkels het mailadres opzoeken op hun eigen site.
  2. Een paar winkels met een adres laten meten bij ChatGPT en Gemini.
  3. Een paar gemeten winkels hun eigen uitkomst mailen.

Waarom een klein stukje per uur en niet alles in één keer:

Krillo.nl is een jong domein dat nog bijna geen post heeft verstuurd. Gmail en
Outlook kijken naar hoeveel je stuurt, hoe snel dat oploopt, en hoeveel mensen
klagen. Ga je van nul naar honderd per dag, dan kom je binnen een week in de
spammap terecht en kom je daar niet meer uit. Ook je gewone post aan klanten
niet. De rem hieronder is dus geen voorzichtigheid, het is de enige manier
waarop dit over een maand nog werkt.

Twee dingen die dit bestand nooit doet:
- Twee keer naar dezelfde winkel mailen. De stand staat in de database en niet
  in het geheugen, want de server herstart vaker dan je denkt.
- Mailen naar een persoonlijk adres. Naar het algemene adres van een bedrijf
  mag je zakelijk mailen in Nederland en in Belgie. Naar het persoonlijke adres
  van een medewerker mag dat in Belgie niet, en dat is precies de plek waar dit
  fout kan gaan zonder dat je het merkt.
"""

import os
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    KLOK = ZoneInfo("Europe/Amsterdam")
except Exception:
    KLOK = None

import contactvinder
import db
import scan_engine

# De standaarden. Alle drie te veranderen op de beheerpagina zonder dat er een
# nieuwe versie van de site voor nodig is.
STANDAARD_PER_DAG = 15
STANDAARD_PER_RONDE = 3
STANDAARD_ADRESSEN_PER_RONDE = 10
STANDAARD_METINGEN_PER_RONDE = 5

# Buiten deze uren gaat er geen post uit. Een mail die om drie uur 's nachts
# binnenkomt leest als een machine, en dat is hij ook, maar dat hoeft er niet
# bovenop te staan.
VROEGSTE_UUR = 8
LAATSTE_UUR = 20


def _getal(sleutel, standaard):
    try:
        return max(0, int(db.get_instelling(sleutel, standaard)))
    except (TypeError, ValueError):
        return standaard


def instellingen():
    return {
        "aan": (db.get_instelling("benadering_aan", "nee") or "nee").lower() == "ja",
        "per_dag": _getal("mail_per_dag", STANDAARD_PER_DAG),
        "per_ronde": _getal("mail_per_ronde", STANDAARD_PER_RONDE),
        "adressen_per_ronde": _getal("adressen_per_ronde", STANDAARD_ADRESSEN_PER_RONDE),
        "metingen_per_ronde": _getal("metingen_per_ronde", STANDAARD_METINGEN_PER_RONDE),
    }


def binnen_kantooruren(moment=None):
    nu = moment or (datetime.now(KLOK) if KLOK else datetime.now())
    return VROEGSTE_UUR <= nu.hour < LAATSTE_UUR


# ------------------------------------------------------------- 1. adres zoeken

def zoek_adressen(hoeveel=None):
    """Zoekt bij een paar nieuwe winkels het mailadres op hun eigen site."""
    hoeveel = hoeveel if hoeveel is not None else instellingen()["adressen_per_ronde"]
    gedaan = {"bekeken": 0, "gevonden": 0, "niets": 0}
    for winkel in db.get_benaderingen(stand="nieuw", limiet=hoeveel):
        url = winkel["webshop_url"]
        gedaan["bekeken"] += 1
        try:
            uitkomst = contactvinder.zoek_adres(url)
        except Exception as e:
            print(f"Adres zoeken mislukt voor {url}: {e}")
            db.zet_benadering(url, stand="geen_adres",
                              notitie=f"Zoeken mislukt: {type(e).__name__}")
            gedaan["niets"] += 1
            continue
        if uitkomst.get("adres"):
            db.zet_benadering(url, stand="adres", email=uitkomst["adres"],
                              email_bron=uitkomst.get("vandaan"), notitie="")
            gedaan["gevonden"] += 1
        else:
            db.zet_benadering(url, stand="geen_adres",
                              notitie=uitkomst.get("reden") or "Niets gevonden.")
            gedaan["niets"] += 1
    return gedaan


# ------------------------------------------------------------------ 2. meten

def te_meten(hoeveel=None, al_gemeten=None):
    """Welke winkels aan de beurt zijn om gemeten te worden.

    De lijst met al gemeten winkels geef je mee, zodat wij hier niet hoeven te
    weten hoe de meting werkt."""
    hoeveel = hoeveel if hoeveel is not None else instellingen()["metingen_per_ronde"]
    klaar = set(al_gemeten or [])
    uit = []
    for winkel in db.get_benaderingen(stand="adres", limiet=hoeveel * 4):
        if winkel["webshop_url"] in klaar:
            # Al gemeten in een eerdere ronde, alleen de stand liep achter.
            db.zet_benadering(winkel["webshop_url"], stand="gemeten")
            continue
        uit.append(winkel["webshop_url"])
        if len(uit) >= hoeveel:
            break
    return uit


def markeer_gemeten(urls):
    for url in urls or []:
        db.zet_benadering(url, stand="gemeten")


# ------------------------------------------------------------------ 3. mailen

def hoeveel_mag_er_nu(nu=None):
    """Hoeveel mails er in deze ronde nog mogen. Dit is de rem.

    Vier dingen kunnen hem op nul zetten: de schakelaar staat uit, het is
    nacht, de dagrem is op, of de rondelimiet is bereikt. Alle vier gelden ze
    even hard."""
    inst = instellingen()
    if not inst["aan"]:
        return 0, "De automatische benadering staat uit."
    if not binnen_kantooruren(nu):
        return 0, f"Buiten de uren dat wij post versturen ({VROEGSTE_UUR}:00 tot {LAATSTE_UUR}:00)."
    tellingen = db.tel_benaderingen()
    over_vandaag = inst["per_dag"] - (tellingen.get("vandaag_gemaild") or 0)
    if over_vandaag <= 0:
        return 0, f"De dagrem van {inst['per_dag']} is bereikt."
    return min(inst["per_ronde"], over_vandaag), None


LAATSTE_RONDE_SLEUTEL = "benadering_laatste_ronde"


def onthoud_ronde(moment=None):
    """Legt vast wanneer de laatste ronde gedraaid heeft.

    In de database en niet in het geheugen, want Render herstart de server
    vaker dan je denkt en dan zou hij elke keer zeggen dat er nooit een ronde
    geweest is."""
    moment = moment or datetime.now(KLOK)
    db.zet_instelling(LAATSTE_RONDE_SLEUTEL, moment.isoformat())


def laatste_ronde():
    """Wanneer er voor het laatst een ronde draaide, of None."""
    waarde = db.get_instelling(LAATSTE_RONDE_SLEUTEL)
    if not waarde:
        return None
    try:
        return datetime.fromisoformat(str(waarde))
    except ValueError:
        return None


def waarom_gaat_er_niets_uit(moment_laatste_ronde=None, meetruimte=None,
                             metingen_bezig=0):
    """Vertelt in gewone taal waarom er op dit moment geen post uitgaat.

    Dit bestaat omdat "er staan 93 winkels op de lijst en er is nul gemaild"
    zeven verschillende oorzaken kan hebben, en die zijn van buitenaf niet uit
    elkaar te houden. Zonder dit blok moet je in de logboeken van Render gaan
    graven om te zien of de schakelaar uit staat of dat er simpelweg nog geen
    enkele winkel een adres heeft.

    Geeft een lijst met (ernst, regel). Ernst is "blok" als het echt tegenhoudt,
    "wacht" als het vanzelf goed komt, en "goed" als het in orde is."""
    uit = []
    inst = instellingen()
    tellingen = db.tel_benaderingen()
    per_stand = tellingen.get("per_stand") or {}

    # 1. Draait er wel iets. Zonder aanroep gebeurt er helemaal niets, en dat
    # is verreweg de meest voorkomende oorzaak.
    if moment_laatste_ronde is None:
        uit.append(("blok", "Er is nog geen ronde gedraaid. Zonder een cron-taak "
                            "op /api/cron/benadering gebeurt er niets, hoeveel "
                            "winkels er ook op de lijst staan."))
    else:
        uren = (datetime.now(KLOK) - moment_laatste_ronde).total_seconds() / 3600
        if uren > 3:
            uit.append(("blok", f"De laatste ronde was {uren:.0f} uur geleden. "
                                f"Controleer de cron-taak, die hoort elk uur te "
                                f"draaien."))
        else:
            uit.append(("goed", f"De laatste ronde was {uren:.1f} uur geleden."))

    # 2. De schakelaar.
    if not inst["aan"]:
        uit.append(("blok", "De schakelaar hieronder staat uit. Er wordt wel "
                            "gezocht en gemeten, maar er gaat geen post uit."))
    else:
        uit.append(("goed", "De schakelaar staat aan."))

    # 3. De klok.
    if not binnen_kantooruren():
        uit.append(("wacht", f"Het is nu buiten {VROEGSTE_UUR}:00 tot "
                             f"{LAATSTE_UUR}:00. Er gaat vanzelf weer post uit "
                             f"zodra het weer kan."))

    # 4. De dagrem.
    vandaag = tellingen.get("vandaag_gemaild") or 0
    if vandaag >= inst["per_dag"]:
        uit.append(("wacht", f"De dagrem van {inst['per_dag']} is bereikt, "
                             f"{vandaag} vandaag verstuurd. Morgen gaat het door."))

    # 5. Waar de voorraad stokt. De volgorde is nieuw, adres, gemeten, gemaild.
    nieuw = per_stand.get("nieuw", 0)
    adres = per_stand.get("adres", 0)
    gemeten = per_stand.get("gemeten", 0)
    geen_adres = per_stand.get("geen_adres", 0)
    if not tellingen.get("totaal"):
        uit.append(("blok", "Er staan geen winkels op de lijst. Plak er eerst "
                            "een lijst in."))
    elif gemeten:
        uit.append(("goed", f"{gemeten} winkels staan klaar om post te krijgen."))
    elif adres:
        # Hier zat het echte probleem. De wachtrij voor metingen staat in het
        # geheugen van de server. Zet Render de app in slaap, dan is die rij weg
        # en is er niets gemeten, terwijl het adressen zoeken wel gelukt is
        # omdat dat binnen de ronde zelf afgehandeld wordt. Van buitenaf zie je
        # dan alleen "102 met adres, 0 gemeten" en dat verklaart niets.
        if meetruimte is not None and not meetruimte.get("mag"):
            uit.append(("blok", "Er wordt niet gemeten omdat de dagpot voor de "
                                "eigen benadering op is. "
                                + (meetruimte.get("reden") or "")))
        elif metingen_bezig:
            uit.append(("goed", f"Er zijn nu {metingen_bezig} metingen bezig. "
                                f"Een meting duurt minuten, dus geef het even."))
        else:
            uit.append(("blok", f"{adres} winkels hebben een adres, maar er is er "
                                f"nog geen enkele gemeten. Dat wijst op een "
                                f"onderbroken meting: de wachtrij staat in het "
                                f"geheugen en verdwijnt als Render de app in slaap "
                                f"zet. Houd de app wakker met een cron-taak op "
                                f"/wakker, elke tien minuten."))
    elif nieuw:
        uit.append(("wacht", f"Alle {nieuw} winkels staan nog op 'nieuw'. Er is "
                             f"nog geen e-mailadres gevonden. Dat gebeurt "
                             f"{inst['adressen_per_ronde']} per ronde, dus dit "
                             f"kost een paar rondes."))

    if geen_adres:
        uit.append(("wacht", f"Bij {geen_adres} winkels vonden wij geen algemeen "
                             f"e-mailadres. Die slaan wij over, dat is geen fout."))
    return uit


def te_mailen(hoeveel):
    """De winkels die aan de beurt zijn voor post: gemeten, adres bekend, nog
    nooit gemaild, niet afgemeld."""
    if hoeveel <= 0:
        return []
    uit = []
    for winkel in db.get_benaderingen(stand="gemeten", limiet=hoeveel * 3):
        if not winkel.get("email") or winkel.get("gemaild_op"):
            continue
        uit.append(winkel)
        if len(uit) >= hoeveel:
            break
    return uit


def markeer_gemaild(webshop_url, gelukt, fout=None):
    """Alleen bij een gelukte verzending gaat de stand om.

    Mislukt hij, dan blijft de winkel op 'gemeten' staan en komt hij een
    volgende ronde weer langs. Zou je hem hier al op 'gemaild' zetten, dan sla
    je hem voorgoed over terwijl hij nooit iets gehad heeft."""
    if gelukt:
        return db.zet_benadering(webshop_url, stand="gemaild", gemaild=True, notitie="")
    return db.zet_benadering(webshop_url, notitie=(fout or "Verzenden mislukt.")[:400])


# ---------------------------------------------------------------- de lijst erin

def voeg_lijst_toe(tekst):
    """Zet een geplakte lijst met winkels op de benaderlijst.

    Per regel een webadres, en er mag van alles achter staan: naam, land,
    branche, gescheiden door een puntkomma of een tab. Wat er niet staat laten
    wij leeg, wij verzinnen het niet."""
    klaar, fout, gezien = [], [], set()
    for regel in (tekst or "").splitlines():
        regel = regel.strip()
        if not regel or regel.startswith("#"):
            continue
        delen = [d.strip() for d in regel.replace("\t", ";").split(";")]
        url = scan_engine.normalize_url(delen[0])
        if not url or "." not in url:
            fout.append(regel[:80])
            continue
        if url in gezien:
            # Twee keer dezelfde winkel in één geplakte lijst. Dat mag niet in
            # dezelfde opdracht terechtkomen, want dan valt de hele invoer om.
            continue
        gezien.add(url)
        klaar.append((
            url,
            delen[1] if len(delen) > 1 and delen[1] else None,
            delen[2] if len(delen) > 2 and delen[2] else None,
            delen[3] if len(delen) > 3 and delen[3] else None,
        ))

    # In stukken van honderd. Eén opdracht met tweehonderd regels lukt prima,
    # maar met een lijst van duizenden wordt de opdracht zo groot dat hij weer
    # tegen een tijdslimiet aanloopt. Honderd per keer is overal snel.
    nieuw = 0
    for begin in range(0, len(klaar), 100):
        nieuw += db.voeg_benaderingen_toe(klaar[begin:begin + 100])
    return {"nieuw": nieuw, "al_bekend": len(klaar) - nieuw, "fout": fout}
