"""Het onderhoud: alles wat vanzelf moet gebeuren als er winkels bijkomen.

WAAROM DIT BESTAAT

Vandaag draait Krillo op knoppen. Een knop om in te delen, een knop om op te
schonen, een knop om te meten. Dat werkt zolang het om negenhonderd winkels in
twee landen gaat en er iemand op die knoppen drukt.

Het gaat niet werken bij tienduizend winkels in acht landen. Dan komen er elke
dag winkels bij, verlopen er elke dag metingen, en is er niemand die bijhoudt
welke categorie aan de beurt is. Dit bestand haalt dat weg bij de mens.

WAT EEN RONDE DOET, IN DEZE VOLGORDE

1. INDELEN. Winkels zonder categorie krijgen er een. Veertig per aanroep.
2. OPSCHONEN. Nieuwe winkels krijgen hun soort en hun hoofdadres. Het adreswerk
   is gratis en gebeurt voor alles wat binnen is; alleen merk-of-winkel kost
   geld en gaat per veertig.
3. HERBEREKENEN. Elke bestaande ranglijst opnieuw uitrekenen uit de antwoorden
   die er al staan, zodat wat er net bij het opschonen geleerd is er meteen in
   zit. Kost niets, want er wordt niets opnieuw gevraagd of gelezen.
4. METEN. Hoogstens EEN categorie per ronde, en alleen als hij nog nooit gemeten
   is of als de laatste meting verlopen is.
5. BERICHTEN. Meteen na die meting krijgen de klanten in die categorie hun
   nameting, hun waarschuwing of hun maandbericht. Hooguit een per klant per
   ronde, en nooit twee binnen veertien dagen. Zie meldingen.py.

DRIE REGELS DIE HIER NIET ONDERHANDELBAAR ZIJN

- De volgorde is niet willekeurig. Een winkel die nog geen categorie heeft kan
  niet gemeten worden, en een winkel die nog niet opgeschoond is hoort niet in
  een ranglijst. Indelen voor opschonen voor meten.

- HOOGSTENS EEN ZWARE KLUS PER RONDE. Een ronde die alles doet wat er ligt,
  doet op een dag met driehonderd nieuwe winkels ineens driehonderd euro. Door
  per ronde een categorie te meten en de rest te laten liggen, groeit de
  uitgave met de tijd mee en niet met de stapel.

- ALTIJD EERST DE KOSTENREM. Voor elke stap wordt gevraagd of er nog dagpot is.
  Zit die dicht, dan stopt de ronde en gaat hij morgen verder waar hij gebleven
  was. Er gaat niets verloren, want elke stap kijkt zelf wat er nog te doen is.

WAAROM DIT VEILIG KAN DRAAIEN ZONDER DAT IEMAND KIJKT

Elke stap is te herhalen zonder schade. Indelen slaat over wat al ingedeeld is,
opschonen slaat over wat al opgeschoond is, meten slaat over wat nog vers is.
Valt een ronde halverwege om, dan pakt de volgende het gewoon op.
"""
import os
import threading
import time

import categorieen
import categoriemeting
import db
import kosten
import meldingen
import opschonen

# Hoeveel winkels er per ronde ingedeeld worden. Veertig per aanroep, dus dit
# zijn vijf aanroepen van samen een paar cent.
INDELEN_PER_RONDE = int(os.environ.get("ONDERHOUD_INDELEN", "200"))

# Hoeveel winkels er per ronde op merk-of-winkel bekeken worden. Ook veertig
# per aanroep.
OPSCHONEN_PER_RONDE = int(os.environ.get("ONDERHOUD_OPSCHONEN", "200"))

# Hoeveel categorieen er per ronde gemeten worden. EEN. Zie de regel hierboven.
METEN_PER_RONDE = int(os.environ.get("ONDERHOUD_METEN", "1"))

# Hoe vaak een categorie opnieuw gemeten wordt. Dertig dagen, want dat is ook
# wat een klant per maand betaalt en wat er in zijn rapport hoort te staan.
OPNIEUW_METEN_NA_DAGEN = int(os.environ.get("ONDERHOUD_VERVALT_NA", "30"))

# Wat een categorie minimaal aan winkels moet hebben voordat hij gemeten wordt.
# Hetzelfde getal als voor de openbare index: een ranglijst van vier winkels is
# geen ranglijst.
MINIMUM = categorieen.MINIMUM_VOOR_INDEX

_stand = {"bezig": False, "stap": None, "gestart_op": None, "klaar_op": None,
          "laatste_verslag": None, "fout": None}
_slot = threading.Lock()


def stand():
    uit = dict(_stand)
    if uit["gestart_op"] and uit["bezig"]:
        uit["verstreken_sec"] = int(time.time() - uit["gestart_op"])
    return uit


# ---------------------------------------------------------------------------
# De drie stappen
# ---------------------------------------------------------------------------

def stap_indelen(hoeveel=None):
    """Winkels zonder categorie er een geven."""
    rem = kosten.mag_doorgaan()
    if not rem["mag"]:
        return {"overgeslagen": "kostenrem", "reden": rem["reden"]}
    return categorieen.deel_alles_in(hoeveel=hoeveel or INDELEN_PER_RONDE)


def stap_opschonen(hoeveel=None):
    """Nieuwe winkels hun soort en hun hoofdadres geven.

    Het adreswerk gebeurt voor ALLE nieuwe winkels, ook als het er duizend zijn,
    want dat kost niets. Alleen merk-of-winkel is aan een aantal gebonden."""
    nieuw = db.winkels_zonder_opschoning()
    verslag = {"nieuw": len(nieuw), "zonder_adres": 0, "samengevoegd": 0,
               "merken": 0, "aanroepen": 0}
    if not nieuw:
        return verslag

    # Gratis stap 1: wat geen adres is kan nooit gekoppeld worden. In EEN
    # databaseopdracht, niet een per winkel: zie db.zet_soorten.
    zonder = {w["webshop_url"]: opschonen.SOORT_GEEN_ADRES for w in nieuw
              if not opschonen.heeft_webadres(w["webshop_url"])}
    db.zet_soorten(zonder)
    verslag["zonder_adres"] = len(zonder)

    # Gratis stap 2: ketens samenvoegen. Dit moet tegen de HELE lijst, niet
    # alleen tegen de nieuwe winkels. Komt cookinglife.be vandaag binnen en
    # stond cookinglife.nl er al maanden, dan hoort die nieuwe er meteen onder.
    bestaand = [w["webshop_url"] for w in db.alle_benaderingen_kaal()]
    koppeling = opschonen.groepeer_ketens(bestaand)
    voor_nieuw = {w["webshop_url"]: koppeling.get(w["webshop_url"], w["webshop_url"])
                  for w in nieuw}
    db.zet_hoort_bij_veel(voor_nieuw)
    verslag["samengevoegd"] = sum(1 for u, h in voor_nieuw.items() if h != u)

    # Betaalde stap 3: merk of winkel, alleen voor de hoofdadressen.
    hoofden = [w for w in nieuw
               if opschonen.heeft_webadres(w["webshop_url"])
               and koppeling.get(w["webshop_url"]) == w["webshop_url"]]
    hoofden = hoofden[:hoeveel or OPSCHONEN_PER_RONDE]
    for begin in range(0, len(hoofden), opschonen.PER_AANROEP):
        rem = kosten.mag_doorgaan()
        if not rem["mag"]:
            verslag["gestopt_door"] = rem["reden"]
            break
        groep = hoofden[begin:begin + opschonen.PER_AANROEP]
        uitkomst = opschonen.merken_in(groep)
        verslag["aanroepen"] += 1
        db.zet_soorten(uitkomst)
        verslag["merken"] += sum(1 for s in uitkomst.values()
                                 if s == opschonen.SOORT_MERK)
        if not uitkomst:
            break
    return verslag


def stap_herberekenen():
    """Elke bestaande ranglijst opnieuw uitrekenen uit de bewaarde antwoorden.

    Kost niets: geen vraag wordt opnieuw gesteld, geen antwoord opnieuw gelezen.
    Daarom staat er ook geen kostenrem voor.

    Waarom dit na het opschonen moet. Het opschonen zet net vast dat
    cookinglife.be bij cookinglife.nl hoort en dat Brabantia een merk is. De
    ranglijsten die er al liggen weten dat nog niet en laten dus dubbele regels
    en merken zien. Zonder deze stap zou je voor die verbetering opnieuw moeten
    meten, en dat kost per categorie veertig cent voor precies dezelfde
    antwoorden."""
    verslag = {"categorieen": 0, "bijgewerkt": 0}
    for slug in db.gemeten_categorieen():
        verslag["categorieen"] += 1
        uit = categoriemeting.herbereken_ranglijst(slug)
        if not uit.get("fout"):
            verslag["bijgewerkt"] += 1
    return verslag


# Wat er na een geslaagde meting van een categorie gebeurt met de klanten in
# die categorie. app.py zet hier zijn eigen functie in (_ververs_klantwerk).
# Zo blijft onderhoud.py vrij van app.py: die importeert onderhoud al, en
# andersom zou een kringetje zijn.
NA_METING = None


def stap_meten(hoeveel=None):
    """De categorie meten die er het langst op wacht.

    Hoogstens een per ronde. Dat is de rem die voorkomt dat een dag met
    driehonderd nieuwe winkels ineens driehonderd euro kost."""
    hoeveel = METEN_PER_RONDE if hoeveel is None else hoeveel
    verslag = {"gemeten": [], "overgeslagen": 0}
    if hoeveel <= 0:
        return verslag

    aan_de_beurt = db.categorieen_om_te_meten(MINIMUM, OPNIEUW_METEN_NA_DAGEN)
    verslag["wachtrij"] = len(aan_de_beurt)
    for rij in aan_de_beurt[:hoeveel]:
        rem = kosten.mag_doorgaan()
        if not rem["mag"]:
            verslag["gestopt_door"] = rem["reden"]
            break
        # Niet alleen vragen of het MAG, maar of een HELE meting er nog bij
        # past. Een meting die halverwege door de rem wordt afgekapt is wel
        # betaald en levert geen ranglijst op. Dan is er geld weg en is er
        # niets voor teruggekomen, en dat is precies wat wij niet willen.
        ruimte = kosten.ruimte_vandaag()
        if not ruimte["past_een_categorie"]:
            verslag["gestopt_door"] = (
                f"Er is vandaag nog "
                f"{('onbekend' if ruimte['onbekend'] else format(ruimte['over'], '.2f') + ' euro')} "
                f"over van de dagpot, en een hele meting kost ongeveer "
                f"{kosten.SCHATTING_CATEGORIE_EURO:.2f} euro. Morgen weer.")
            verslag["ruimte"] = ruimte
            break
        uit = categoriemeting.meet_categorie(rij["categorie"])
        regel = {
            "categorie": rij["categorie"],
            "winkels": uit.get("winkels"),
            "telbaar": uit.get("telbaar"),
            "fout": uit.get("fout"),
            # Stap 62: hoeveel winkels AI noemde die wij nog niet kenden.
            "nieuwe_winkels": len(uit.get("nieuwe_winkels") or []),
        }

        # Meteen na de meting de berichten. Alleen HIER wordt er echt verstuurd;
        # de knop op de beheerpagina doet dat bewust niet, want dan mail je je
        # hele klantenbestand terwijl je aan het testen bent.
        if uit.get("ronde") and not uit.get("fout"):
            try:
                regel["berichten"] = meldingen.na_meting(
                    uit["ronde"], rij["categorie"], verstuur=True,
                    basis=os.environ.get("BASE_URL"))
            except Exception as e:
                print(f"Berichten na meting mislukt voor {rij['categorie']}: {e}")
                regel["berichten"] = {"fout": str(e)[:160]}

            # Stap 72: het werk van de klanten in deze categorie verversen.
            # NA de berichten, want die gaan over de positie en hoeven niet te
            # wachten op het schrijven van oplossingen.
            if NA_METING:
                try:
                    regel["klantwerk"] = NA_METING(uit["ronde"], rij["categorie"],
                                                   os.environ.get("BASE_URL"))
                except Exception as e:
                    print(f"Klantwerk vernieuwen mislukt voor {rij['categorie']}: {e}")
                    regel["klantwerk"] = {"fout": str(e)[:160]}
        verslag["gemeten"].append(regel)
    return verslag


# ---------------------------------------------------------------------------
# De hele ronde
# ---------------------------------------------------------------------------

def ronde():
    """Een hele onderhoudsronde. Draait op de aanroepende draad.

    Nooit rechtstreeks vanuit een verzoek aanroepen: een meting duurt minuten.
    De cron-ingang zet hem op een eigen draad."""
    verslag = {"begonnen": time.strftime("%Y-%m-%d %H:%M")}

    _stand["stap"] = "indelen"
    verslag["indelen"] = stap_indelen()

    _stand["stap"] = "opschonen"
    verslag["opschonen"] = stap_opschonen()

    # Gratis, en het moet na het opschonen: wat daar geleerd is over ketens en
    # merken hoort meteen in de bestaande ranglijsten te staan.
    _stand["stap"] = "ranglijsten herberekenen"
    verslag["herberekenen"] = stap_herberekenen()

    _stand["stap"] = "meten"
    verslag["meten"] = stap_meten()

    # Stap 71: wat langer bewaard is dan het privacybeleid belooft, weg. Elke
    # nacht, want dan is niets ooit meer dan een dag over zijn termijn.
    _stand["stap"] = "bewaartermijnen"
    verslag["bewaartermijnen"] = db.ruim_verlopen_gegevens(12)

    _stand["stap"] = "klaar"
    verslag["kosten_vandaag"] = kosten.mag_doorgaan()
    return verslag


def _werk():
    try:
        _stand["laatste_verslag"] = ronde()
        print(f"Onderhoudsronde klaar: {_stand['laatste_verslag']}")
    except Exception as e:
        _stand["fout"] = f"{type(e).__name__}: {e}"[:200]
        print(f"Onderhoudsronde mislukt: {e}")
    finally:
        _stand["bezig"] = False
        _stand["klaar_op"] = time.time()


def start_ronde():
    """Start een onderhoudsronde op een eigen draad.

    Loopt er al een, dan gebeurt er niets. Dat is belangrijk: de cron kan
    dubbel afgaan, en twee rondes tegelijk zouden dezelfde categorie twee keer
    meten en dus twee keer betalen."""
    with _slot:
        if _stand["bezig"]:
            return False
        _stand.update({"bezig": True, "stap": "starten",
                       "gestart_op": time.time(), "klaar_op": None, "fout": None})
    threading.Thread(target=_werk, daemon=True).start()
    return True
