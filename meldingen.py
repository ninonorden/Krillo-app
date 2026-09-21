"""Wie er na een meting bericht krijgt, en waarover. Met een rem erop.

WAAROM DIT BESTAAT

Op de site staan drie beloftes die tot vandaag niet waar waren:

1. "Proof it worked: four weeks later we measure again." Er was geen enkele
   regel code die vier weken na een oplevering opnieuw mat en liet zien wat het
   opleverde. Dat is de belofte die in het pakket van 149 euro staat, dus die
   moet als eerste kloppen.
2. "A warning when you drop." De waarschuwing bestond wel (waarschuwing.py) maar
   hing aan de oude meting per winkel, niet aan de positie in de index. Hij
   keek dus naar het verkeerde getal.
3. "Measured again every month." Er werd wel gemeten, maar er ging niets uit.

DE REM, EN WAAROM DIE ER MOET ZIJN

Nino's zorg, letterlijk: "het kan niet zijn dat elke minuut een melding komt
stel iemand daalt de hele tijd."

Dat is precies goed gezien, en het is hoe diensten zichzelf om zeep helpen. Een
klant die drie mails in een week krijgt zet ze uit, en daarna ziet hij ook de
mail niet meer die er wel toe doet. Drie remmen tegelijk:

- EEN BERICHT PER MEETRONDE. Vastgelegd in de database, niet in de code: de
  tabel berichten heeft een unieke sleutel op (winkel, ronde). Meet je dezelfde
  categorie drie keer op een dag, dan gaat er nog steeds hooguit een mail uit.
- EEN RUSTPERIODE van veertien dagen tussen twee berichten, wat er ook gebeurt.
- EEN DREMPEL: onder de drie plaatsen daling melden we niets. Een plaats heen of
  weer is ruis. AI-antwoorden verschillen van dag tot dag zonder dat er iets
  veranderd is, en daar moet je iemand niet mee lastigvallen.

WELK BERICHT WINT

Nameting gaat voor alles, ook binnen de rustperiode. Dat is het enige bericht
waar de klant echt op zit te wachten, en het komt een keer per oplevering.
Daarna een daling, want daar moet iets mee. Daarna pas het gewone maandbericht.

WAT ER BEWUST NIET GEBEURT

Verzenden zit niet in de knop "Meet deze categorie" op de beheerpagina. Dat is
opzettelijk: anders mail je je hele klantenbestand terwijl je aan het testen
bent. Alleen de nachtronde verstuurt echt. Op de beheerpagina kun je wel zien
wat er verstuurd ZOU worden, zonder dat er iets uitgaat.
"""
import os
from datetime import datetime, timedelta, timezone

import db

# Onder dit aantal plaatsen daling melden we niets. Een plaats heen of weer is
# ruis, geen nieuws.
DREMPEL_DALING = int(os.environ.get("MELDING_DREMPEL_DALING", "3"))

# Hoeveel dagen er minstens tussen twee berichten zit, wat er ook gebeurt.
RUSTPERIODE_DAGEN = int(os.environ.get("MELDING_RUSTPERIODE", "14"))

# Het venster waarin een nameting hoort te komen: vanaf vier weken na de
# oplevering, tot tien weken erna. Eerder is te vroeg, want de assistenten
# hebben de site dan nog niet opnieuw gelezen. Later is geen nameting meer maar
# een gewoon maandbericht.
NAMETING_VANAF_DAGEN = int(os.environ.get("NAMETING_VANAF", "26"))
NAMETING_TOT_DAGEN = int(os.environ.get("NAMETING_TOT", "70"))


def _nu():
    return datetime.now(timezone.utc)


def _dagen_geleden(moment):
    if not moment:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (_nu() - moment).days


# ---------------------------------------------------------------------------
# De beslissing: welk bericht hoort deze klant te krijgen
# ---------------------------------------------------------------------------

def kies_bericht(klant, laatste=None, nameting_gedaan=False):
    """Bepaalt welk bericht deze klant krijgt. Puur rekenwerk, geen database.

    Los gehouden van het versturen, zodat een test alle gevallen kan naspelen
    zonder database en zonder ook maar een mail te versturen. Dat is niet netjes
    willen doen: bij een verkeerde beslissing gaat er een mail uit naar een
    echte klant en die kun je niet terughalen."""
    positie = klant.get("positie")
    if not positie:
        return {"soort": "geen", "reden": "geen positie in deze ronde"}

    vorige = klant.get("vorige_positie")
    verschil = (vorige - positie) if vorige else None  # plus is gestegen

    # 1. Nameting. Gaat voor alles, ook binnen de rustperiode.
    dagen = _dagen_geleden(klant.get("opgeleverd_op"))
    if (dagen is not None and not nameting_gedaan
            and NAMETING_VANAF_DAGEN <= dagen <= NAMETING_TOT_DAGEN):
        return {"soort": "nameting", "verschil": verschil, "dagen_na": dagen,
                "reden": f"opgeleverd {dagen} dagen geleden"}

    # 2. De rustperiode. Hierna mag er alleen nog iets uit als het lang genoeg
    #    geleden is dat we iets stuurden.
    if laatste and laatste.get("verstuurd_op"):
        sinds = _dagen_geleden(laatste["verstuurd_op"])
        if sinds is not None and sinds < RUSTPERIODE_DAGEN:
            return {"soort": "geen",
                    "reden": f"{sinds} dagen geleden al bericht gehad"}

    # 3. Een daling die er echt toe doet.
    if verschil is not None and verschil <= -DREMPEL_DALING:
        return {"soort": "daling", "verschil": verschil,
                "reden": f"{abs(verschil)} plaatsen gezakt"}

    # 4. Het gewone maandbericht.
    return {"soort": "maand", "verschil": verschil, "reden": "maandelijkse stand"}


# ---------------------------------------------------------------------------
# De teksten, in twee talen
# ---------------------------------------------------------------------------

def _beweging(verschil, taal):
    if verschil is None:
        return ("Dit is je eerste gemeten positie."
                if taal == "nl" else "This is your first measured position.")
    if verschil > 0:
        return (f"Je bent {verschil} {'plaats' if verschil == 1 else 'plaatsen'} gestegen."
                if taal == "nl" else
                f"You moved up {verschil} {'place' if verschil == 1 else 'places'}.")
    if verschil < 0:
        n = abs(verschil)
        return (f"Je bent {n} {'plaats' if n == 1 else 'plaatsen'} gezakt."
                if taal == "nl" else
                f"You dropped {n} {'place' if n == 1 else 'places'}.")
    return ("Je positie is gelijk gebleven."
            if taal == "nl" else "Your position stayed the same.")


def tekst(klant, keuze, categorienaam, taal="nl"):
    """De mailtekst. Geen opsmuk, geen uitroeptekens, en slecht nieuws krijgt
    geen mooie verpakking.

    Bij een daling staat er altijd bij wat wij eraan gaan doen. Een kale melding
    dat je gezakt bent maakt een klant ongerust zonder hem iets te bieden, en
    dat is precies het moment waarop iemand opzegt."""
    p = klant.get("positie")
    van = klant.get("van")
    genoemd = klant.get("genoemd") or 0
    telbaar = klant.get("telbaar") or 0
    aanbevolen = klant.get("aanbevolen") or 0
    beweging = _beweging(keuze.get("verschil"), taal)
    soort = keuze["soort"]

    if taal == "en":
        stand = (f"You are number {p} of {van} in {categorienaam}. {beweging} "
                 f"You were named in {genoemd} of {telbaar} buying questions, "
                 f"and recommended in {aanbevolen}.")
        if soort == "nameting":
            return (f"Four weeks ago we made changes to your store. We have now "
                    f"measured again, with the same questions.\n\n{stand}\n\n"
                    f"This is the whole point of the re-measure: not our opinion "
                    f"that it worked, but the same measurement before and after.")
        if soort == "daling":
            return (f"Your position dropped, so we are telling you before you "
                    f"notice it in your sales.\n\n{stand}\n\n"
                    f"We are already looking at which questions you lost and what "
                    f"changed in the answers. You will get the fixes for approval.")
        return (f"We measured {categorienaam} again this month.\n\n{stand}")

    stand = (f"Je staat op plaats {p} van de {van} in {categorienaam}. {beweging} "
             f"Je werd genoemd bij {genoemd} van de {telbaar} koopvragen, "
             f"en aanbevolen bij {aanbevolen}.")
    if soort == "nameting":
        return (f"Vier weken geleden hebben wij je webshop aangepast. We hebben nu "
                f"opnieuw gemeten, met precies dezelfde vragen.\n\n{stand}\n\n"
                f"Dat is waar de nameting voor is: niet onze mening dat het gewerkt "
                f"heeft, maar dezelfde meting ervoor en erna.")
    if soort == "daling":
        return (f"Je positie is gezakt, en dat horen wij je te vertellen voordat je "
                f"het aan je verkopen merkt.\n\n{stand}\n\n"
                f"Wij kijken al na bij welke vragen je weggevallen bent en wat er in "
                f"de antwoorden veranderd is. De oplossingen krijg je ter goedkeuring.")
    return (f"We hebben {categorienaam} deze maand opnieuw gemeten.\n\n{stand}")


def onderwerp(keuze, categorienaam, taal="nl"):
    soort = keuze["soort"]
    if taal == "en":
        if soort == "nameting":
            return f"The re-measure of your store is in ({categorienaam})"
        if soort == "daling":
            return f"Your position in {categorienaam} dropped"
        return f"Your position in {categorienaam} this month"
    if soort == "nameting":
        return f"De nameting van je webshop is binnen ({categorienaam})"
    if soort == "daling":
        return f"Je positie in {categorienaam} is gezakt"
    return f"Je positie in {categorienaam} deze maand"


# ---------------------------------------------------------------------------
# De ronde zelf
# ---------------------------------------------------------------------------

def na_meting(ronde, categorie, verstuur=False, basis=None):
    """Loopt de klanten van een afgeronde meting langs.

    verstuur=False is de DROOGLOOP: hij rekent precies hetzelfde uit en zet
    niets in de database en verstuurt niets. Dat is wat de beheerpagina laat
    zien. Alleen de nachtronde roept hem aan met verstuur=True.

    Waarom die stand standaard uit staat: een mail naar een echte klant kun je
    niet terughalen, en de knop "Meet deze categorie" op de beheerpagina hoort
    niet ongemerkt je hele klantenbestand te mailen."""
    import categorieen
    naam = categorieen.naam_van(categorie)
    verslag = {"ronde": ronde, "categorie": categorie, "klanten": 0,
               "verstuurd": 0, "overgeslagen": 0, "droogloop": not verstuur,
               "per_soort": {}, "regels": []}

    for klant in db.klanten_in_ronde(ronde):
        verslag["klanten"] += 1
        laatste = db.laatste_bericht(klant["webshop_url"])
        gedaan = db.nameting_al_gestuurd(klant["webshop_url"],
                                         klant.get("opgeleverd_op"))
        keuze = kies_bericht(klant, laatste=laatste, nameting_gedaan=gedaan)
        verslag["per_soort"][keuze["soort"]] = \
            verslag["per_soort"].get(keuze["soort"], 0) + 1
        verslag["regels"].append({
            "webshop_url": klant["webshop_url"],
            "soort": keuze["soort"],
            "reden": keuze.get("reden"),
            "positie": klant.get("positie"),
            "vorige_positie": klant.get("vorige_positie"),
        })

        if keuze["soort"] == "geen":
            verslag["overgeslagen"] += 1
            continue
        if not verstuur:
            continue

        # Eerst vastleggen, dan pas versturen. Andersom zou een mail kunnen
        # uitgaan waarvan wij daarna niet weten dat hij uit is, en dan krijgt
        # dezelfde klant hem bij de volgende ronde nog eens.
        details = {"positie": klant.get("positie"),
                   "vorige_positie": klant.get("vorige_positie"),
                   "opgeleverd_op": str(klant.get("opgeleverd_op") or "")}
        if not db.noteer_bericht(klant["webshop_url"], keuze["soort"], ronde,
                                 categorie=categorie, details=details):
            verslag["overgeslagen"] += 1
            continue

        try:
            import emailing
            taal = _taal_van(klant["webshop_url"])
            link = f"{(basis or '').rstrip('/')}/mijn/{klant['klant_token']}" \
                if basis and klant.get("klant_token") else None
            emailing.send_vermeldingen_update(
                klant["email"], klant["webshop_url"],
                tekst(klant, keuze, naam, taal=taal),
                monitoring_url=link, taal=taal)
            verslag["verstuurd"] += 1
        except Exception as e:
            print(f"Bericht versturen mislukt voor {klant['webshop_url']}: {e}")
            verslag.setdefault("fouten", []).append(str(e)[:120])

    return verslag


def _taal_van(webshop_url):
    """Nederlands voor een .nl of .be winkel, anders Engels.

    Bewust simpel: het adres is het enige dat we van iedere winkel zeker weten.
    Zodra er landen bijkomen hangt dit aan het land van de meting."""
    kaal = (webshop_url or "").lower()
    return "nl" if (".nl" in kaal or ".be" in kaal) else "en"
