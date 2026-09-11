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

import json
import os
from datetime import datetime, timedelta

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

# Hoe lang een meting mag duren voordat wij hem als vastgelopen beschouwen.
# Een meting duurt minuten, niet uren. Zes uur is ruim genoeg om een lange
# wachtrij af te werken, en kort genoeg om een winkel niet dagen te laten hangen.
METING_VASTGELOPEN_NA_UUR = 6


def maak_vastgelopen_metingen_vrij(al_gemeten=None):
    """Zet winkels die uren op "meten" hangen terug op "adres".

    Dit stond eerst binnen te_meten, en daar zat een gat in dat de hele lijst
    dagen heeft stilgelegd. Is de dagpot op, dan wordt te_meten helemaal niet
    aangeroepen, en dus werd er ook niets vrijgemaakt. Winkels die bleven hangen
    kwamen daardoor nooit meer aan de beurt, ook niet toen er de volgende dag
    weer ruimte was. Nu draait dit elke ronde, los van het geld, want opruimen
    kost niets.

    Geeft terug hoeveel er vrijgemaakt zijn."""
    klaar = {scan_engine.normalize_url(u) for u in (al_gemeten or [])}
    grens = datetime.now(KLOK) - timedelta(hours=METING_VASTGELOPEN_NA_UUR)
    vrij = 0
    for winkel in db.get_benaderingen(stand="meten"):
        url = winkel["webshop_url"]
        if scan_engine.normalize_url(url) in klaar:
            db.zet_benadering(url, stand="gemeten")
            continue
        begonnen = winkel.get("meting_gestart_op")
        if begonnen is not None and begonnen.tzinfo is None and KLOK:
            begonnen = begonnen.replace(tzinfo=KLOK)
        if begonnen is not None and begonnen > grens:
            continue
        db.zet_benadering(url, stand="adres",
                          notitie="Meting liep vast, opnieuw ingepland.")
        vrij += 1
    return vrij


def te_meten(hoeveel=None, al_gemeten=None):
    """Welke winkels aan de beurt zijn om gemeten te worden.

    Wat hier NIET meer gebeurt: een winkel teruggeven die al in de meting zit.
    Dat gebeurde wel, en het kostte echt geld. De wachtrij staat in het geheugen
    van de server, dus een herstart van Render maakte hem leeg. De winkel stond
    dan nog op "adres" en kwam de volgende ronde gewoon weer aan de beurt. Vijf
    winkels, elk drie tot vijf keer gemeten, zestien euro op een dag, en de
    teller "gemeten" bleef op nul. Nu zetten wij hem eerst op "meten" en pakken
    wij hem pas weer op als hij daar uren later nog steeds staat.
    """
    hoeveel = hoeveel if hoeveel is not None else instellingen()["metingen_per_ronde"]
    # Door dezelfde schrijfwijze halen, anders lopen "https://www.winkel.nl" en
    # "https://winkel.nl" hier stil langs elkaar heen en wordt dezelfde winkel
    # eeuwig opnieuw gemeten.
    klaar = {scan_engine.normalize_url(u) for u in (al_gemeten or [])}
    uit = []

    maak_vastgelopen_metingen_vrij(al_gemeten)

    for winkel in db.get_benaderingen(stand="adres", limiet=hoeveel * 4):
        url = winkel["webshop_url"]
        if scan_engine.normalize_url(url) in klaar:
            # Al gemeten in een eerdere ronde, alleen de stand liep achter.
            db.zet_benadering(url, stand="gemeten")
            continue
        uit.append(url)
        if len(uit) >= hoeveel:
            break
    return uit


def markeer_in_meting(urls):
    """Zet winkels op "meten" zodat de volgende ronde ze met rust laat.

    Dit moet gebeuren VOORDAT de meting start. Doe je het erna, dan is er al een
    ronde overheen gegaan en heb je twee keer betaald."""
    for url in urls or []:
        db.zet_benadering(url, stand="meten", meting_gestart=True)


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


RONDENUMMER_SLEUTEL = "benadering_rondenummer"


def rondenummer():
    """Het volgnummer van deze ronde, oplopend en blijvend.

    De winkelvinder gebruikt dit om door de branches te rouleren. Zonder een
    blijvend nummer zou elke ronde dezelfde zoekopdrachten doen en dus dezelfde
    winkels terugkrijgen, en daar betaal je dan wel voor."""
    try:
        n = int(db.get_instelling(RONDENUMMER_SLEUTEL, 0) or 0) + 1
    except (TypeError, ValueError):
        n = 1
    try:
        db.zet_instelling(RONDENUMMER_SLEUTEL, n)
    except Exception as e:
        print(f"Rondenummer bewaren mislukt: {e}")
    return n


VERSLAG_SLEUTEL = "benadering_rondeverslagen"
VERSLAGEN_BEWAREN = 12


def onthoud_rondeverslag(verslag):
    """Bewaart wat een ronde echt gedaan heeft, zodat je het terug kunt lezen.

    Dit bestaat omdat "er gebeurt niets" en "hij heeft zijn werk gedaan en er
    was niets te doen" er van buitenaf precies hetzelfde uitzien. De uitdraai
    van Render is er wel, maar die rolt door en je moet ervoor inloggen. De
    laatste twaalf rondes op de beheerpagina zijn genoeg om te zien waar het
    stokt.

    Bewust in de instellingentabel en niet in een eigen tabel: geen migratie
    nodig, en twaalf regels tekst wegen niets."""
    try:
        eerdere = rondeverslagen()
    except Exception:
        eerdere = []
    verslag = dict(verslag or {})
    verslag.setdefault("moment", datetime.now(KLOK).isoformat())
    nieuw = ([verslag] + eerdere)[:VERSLAGEN_BEWAREN]
    try:
        db.zet_instelling(VERSLAG_SLEUTEL, json.dumps(nieuw))
    except Exception as e:
        # Een mislukt logboek mag nooit de ronde zelf omgooien. Het logboek is
        # er om problemen te laten zien, niet om er zelf een te worden.
        print(f"Rondeverslag bewaren mislukt: {e}")


def rondeverslagen():
    """De laatste rondes, nieuwste eerst. Altijd een lijst, nooit None."""
    try:
        waarde = db.get_instelling(VERSLAG_SLEUTEL)
    except Exception:
        return []
    if not waarde:
        return []
    try:
        uit = json.loads(str(waarde))
    except (ValueError, TypeError):
        return []
    return [r for r in uit if isinstance(r, dict)] if isinstance(uit, list) else []


DAGBERICHT_SLEUTEL = "benadering_dagbericht_op"


def dagbericht_al_gestuurd(vandaag=None):
    """Of het dagbericht vandaag al de deur uit is.

    De ronde draait elk uur, dus zonder deze controle krijg je twaalf keer per
    dag hetzelfde bericht en zet je het na twee dagen uit. Dan mis je het juist
    op de dag dat het ertoe doet."""
    vandaag = vandaag or datetime.now(KLOK).date().isoformat()
    return str(db.get_instelling(DAGBERICHT_SLEUTEL) or "") == vandaag


def onthoud_dagbericht(vandaag=None):
    vandaag = vandaag or datetime.now(KLOK).date().isoformat()
    db.zet_instelling(DAGBERICHT_SLEUTEL, vandaag)


def dagbericht_tekst(diagnose, tellingen=None, dagpot=None):
    """Het dagbericht in gewone taal. Geeft (onderwerp, regels) terug.

    Bewust dezelfde diagnose als op de beheerpagina, en niet een eigen tekstje
    ernaast. Twee plekken die hetzelfde zeggen lopen na twee wijzigingen uit
    elkaar, en dan weet je niet meer welke van de twee je moet geloven."""
    tellingen = tellingen or db.tel_benaderingen()
    per_stand = tellingen.get("per_stand") or {}
    blokkades = [r for ernst, r in diagnose if ernst == "blok"]

    onderwerp = ("Krillo: de benadering staat stil"
                 if blokkades else "Krillo: de benadering loopt")
    regels = [
        f"Vandaag gemaild: {tellingen.get('vandaag_gemaild') or 0}.",
        f"Op de lijst: {tellingen.get('totaal') or 0}. "
        f"Klaar om post te krijgen: {per_stand.get('gemeten', 0)}. "
        f"Wacht op een meting: {per_stand.get('adres', 0) + per_stand.get('meten', 0)}.",
    ]
    if dagpot and dagpot.get("besteed") is not None:
        regels.append(f"Dagpot voor eigen metingen: {dagpot['besteed']:.2f} van "
                      f"{dagpot['grens']:.2f} euro gebruikt.")
    if blokkades:
        regels.append("Wat het tegenhoudt:")
        regels.extend(blokkades)
    else:
        regels.append("Er staat niets in de weg.")
    return onderwerp, regels


MEETFOUTEN_SLEUTEL = "benadering_meetfouten"
MEETFOUTEN_BEWAREN = 10


def onthoud_meetfout(webshop_url, reden):
    """Bewaart waarom een meting mislukt is, zodat het terug te lezen is.

    Dit ontbrak volledig. De reden stond alleen in het geheugen van de server en
    in de uitdraai van Render, en de beheerpagina meldde alleen "ingepland: 5,
    doorgezet naar gemeten: 0". Dat is precies genoeg om te weten dat er iets
    mis is en niets om te weten wat."""
    try:
        eerdere = meetfouten()
        nieuw = [{"moment": datetime.now(KLOK).isoformat(),
                  "winkel": str(webshop_url)[:200],
                  "reden": str(reden)[:300]}] + eerdere
        db.zet_instelling(MEETFOUTEN_SLEUTEL, json.dumps(nieuw[:MEETFOUTEN_BEWAREN]))
    except Exception as e:
        print(f"Meetfout bewaren mislukt: {e}")


def tel_meetfouten(webshop_url):
    """Hoe vaak deze winkel al mislukt is, voor zover wij het bewaard hebben.

    Het logboek bewaart de laatste tien fouten, dus dit telt niet verder terug
    dan dat. Voor de vraag "geven wij deze winkel op" is dat genoeg: drie
    mislukkingen binnen de laatste tien is ruim voldoende bewijs."""
    kaal = scan_engine.normalize_url(webshop_url)
    return len([1 for f in meetfouten()
                if scan_engine.normalize_url(f.get("winkel")) == kaal])


def meetfouten():
    """De laatste mislukte metingen, nieuwste eerst."""
    try:
        waarde = db.get_instelling(MEETFOUTEN_SLEUTEL)
        uit = json.loads(str(waarde)) if waarde else []
        return [r for r in uit if isinstance(r, dict)] if isinstance(uit, list) else []
    except Exception:
        return []


# Hoe vaak wij een winkel opnieuw meten voordat wij hem opgeven.
#
# Waarom dit er is, en dit is de duurste les van 11 september. Een winkel kan om
# twee heel verschillende redenen geen bruikbare uitkomst opleveren:
#
# 1. De meting ging stuk. De site was niet bereikbaar, of een model gaf niets
#    terug. Opnieuw proberen heeft dan zin, want morgen kan het wel lukken.
# 2. De meting ging prima, maar AI noemde bij die koopvragen geen enkele winkel.
#    Dan tellen er te weinig vragen mee, en dat is geen storing maar een
#    eigenschap van die markt. Opnieuw meten levert morgen precies hetzelfde op,
#    en kost wel weer een paar euro.
#
# Krillo behandelde die twee hetzelfde: terug op de lijst, morgen opnieuw. Zo
# kwamen winkels als terra-cotta.be elke dag terug, kostten elke keer geld, en
# werden elke keer opnieuw geweigerd voor de mail. Deze teller zet daar een rem
# op: na dit aantal pogingen valt een winkel af, met de reden erbij.
MEETPOGINGEN_SLEUTEL = "benadering_meetpogingen"
MAX_MEETPOGINGEN = int(os.environ.get("MAX_MEETPOGINGEN", "3"))


def _meetpogingen_alles():
    try:
        waarde = db.get_instelling(MEETPOGINGEN_SLEUTEL)
        uit = json.loads(str(waarde)) if waarde else {}
        return uit if isinstance(uit, dict) else {}
    except Exception:
        return {}


def meetpogingen(webshop_url):
    """Hoe vaak wij deze winkel al zonder bruikbare uitkomst gemeten hebben.

    Anders dan tel_meetfouten telt dit niet uit een logboek van tien regels maar
    uit een eigen teller per winkel, die blijft staan. Een logboek van tien is
    te kort: bij vijftien metingen per dag is de vorige poging er allang uit
    gerold en begint het tellen weer bij nul. Dat is precies waarom woefwinkel.be
    op een dag acht keer geprobeerd is terwijl hij na drie keer had moeten
    afvallen."""
    return int(_meetpogingen_alles().get(scan_engine.normalize_url(webshop_url), 0))


def tel_meetpoging(webshop_url):
    """Telt er een poging bij op en geeft de nieuwe stand terug."""
    kaal = scan_engine.normalize_url(webshop_url)
    alles = _meetpogingen_alles()
    alles[kaal] = int(alles.get(kaal, 0)) + 1
    try:
        db.zet_instelling(MEETPOGINGEN_SLEUTEL, json.dumps(alles))
    except Exception as e:
        print(f"Meetpoging bewaren mislukt voor {webshop_url}: {e}")
    return alles[kaal]


def vergeet_meetpogingen(webshop_url):
    """Zet de teller terug. Doen zodra een winkel wel een bruikbare meting had:
    vanaf dat moment is de geschiedenis niet meer interessant."""
    kaal = scan_engine.normalize_url(webshop_url)
    alles = _meetpogingen_alles()
    if kaal in alles:
        alles.pop(kaal, None)
        try:
            db.zet_instelling(MEETPOGINGEN_SLEUTEL, json.dumps(alles))
        except Exception as e:
            print(f"Meetpogingen opschonen mislukt voor {webshop_url}: {e}")


def mag_nog_een_poging(webshop_url):
    """Of deze winkel nog een meting waard is."""
    return meetpogingen(webshop_url) < MAX_MEETPOGINGEN


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
        # Let op wat hier NIET beweerd wordt. Wij weten alleen dat wij geen
        # ronde hebben opgeschreven, en dat is iets anders dan dat er nooit een
        # gedraaid heeft: deze klok bestaat pas sinds september 2026, dus vlak
        # na een nieuwe versie staat hij altijd leeg. Stonden er winkels voorbij
        # "nieuw", dan hebben er wel degelijk rondes gedraaid.
        gelopen = (per_stand.get("adres", 0) + per_stand.get("geen_adres", 0)
                   + per_stand.get("meten", 0) + per_stand.get("gemeten", 0))
        if gelopen:
            uit.append(("wacht", "Sinds de laatste nieuwe versie is er nog geen "
                                 "ronde langsgekomen. Er zijn wel eerder rondes "
                                 "geweest, want er staan winkels voorbij 'nieuw'. "
                                 "Na de eerstvolgende ronde staat hier de tijd."))
        else:
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
        elif meetruimte is not None and meetruimte.get("past_nog") == 0:
            # Niets zeggen. Een paar regels lager staat de echte reden: er past
            # geen hele meting meer in de dagpot. De regel hieronder zou hier
            # naar een onderbroken wachtrij wijzen, en dat is dan niet waar,
            # want er is helemaal niets gestart. Twee verklaringen tegelijk is
            # erger dan een, want dan ga je de verkeerde repareren.
            pass
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

    # 6. De restpot. Bewust een eigen regel en niet weggestopt in de tak
    # hierboven, want juist deze oorzaak werd drie dagen lang verkeerd gemeld.
    # De pot is dan formeel niet op, dus "mag" staat op waar, maar er is te
    # weinig over voor nog een hele meting en er wordt dus niets ingepland. De
    # pagina wees ondertussen naar een onderbroken wachtrij, en daar was niets
    # mis mee. Zolang er winkels op meting staan te wachten hoort dit er te
    # staan, ongeacht welke tak hierboven aan de beurt was.
    wachtenden = per_stand.get("adres", 0) + per_stand.get("meten", 0)
    if (wachtenden and meetruimte is not None and meetruimte.get("mag")
            and meetruimte.get("past_nog") == 0):
        besteed = meetruimte.get("besteed")
        grens = meetruimte.get("grens")
        bedragen = (f" Er is vandaag {besteed:.2f} euro van de {grens:.2f} euro "
                    f"gebruikt." if besteed is not None and grens is not None
                    else "")
        uit.append(("blok", "Er is te weinig dagpot over voor nog een hele meting, "
                            "dus er wordt deze ronde niets gemeten en komt er ook "
                            "niets op 'gemeten'." + bedragen
                            + " Om middernacht loopt het vanzelf weer door, of "
                              "verhoog de dagpot in Render."))

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
    je hem voorgoed over terwijl hij nooit iets gehad heeft.

    Op een uitzondering na: een meting met te weinig vragen wordt nooit beter
    door hem nog een keer aan te bieden. Zo'n winkel blijft anders eeuwig op
    'gemeten' staan, wordt elke ronde opnieuw geweigerd, en bezet ondertussen
    een plek in de rij van winkels die wel klaar zijn. Die gaat terug naar
    'adres' en wordt gewoon opnieuw gemeten."""
    if gelukt:
        return db.zet_benadering(webshop_url, stand="gemaild", gemaild=True, notitie="")
    reden = (fout or "Verzenden mislukt.")[:400]
    if reden.startswith("TE_WEINIG_VRAGEN"):
        return db.zet_benadering(webshop_url, stand="adres", notitie=reden)
    return db.zet_benadering(webshop_url, notitie=reden)


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
