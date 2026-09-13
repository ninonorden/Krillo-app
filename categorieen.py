"""Winkels indelen in categorieen, en tellen of dat genoeg oplevert.

WAAROM DIT BESTAND BESTAAT, EN WAAROM HET HET BELANGRIJKSTE VAN DE HELE OMBOUW IS.

Krillo meet nu per winkel: dertig koopvragen per klant per week, ongeveer tien
euro per klant per maand. Daarmee groeien de kosten even hard mee als de omzet
en loopt het bedrijf vast rond de tienduizend euro omzet.

Het alternatief is per CATEGORIE meten. Vraag "waar koop ik online emaille
servies" een keer, en kijk daarna welke van de tweeenzestig servieswinkels in
dat antwoord voorkomen. Een meting, tweeenzestig uitkomsten. De meetkosten per
winkel gaan dan van tien euro per maand naar ongeveer twee cent.

Dat hangt volledig op een aanname: dat er genoeg winkels per categorie zijn. Bij
vijftig winkels per categorie is de besparing vijftigvoudig. Bij drie winkels
per categorie is er geen besparing en deugt het hele plan niet.

Dit bestand toetst die aanname VOORDAT er iets omgebouwd wordt, en doet daarna
het echte indeelwerk.

DRIE KEUZES DIE HIER GEMAAKT ZIJN, MET REDEN:

1. Een VASTE lijst categorieen, geen vrije tekst. Laat je het model zelf een
   categorie verzinnen, dan krijgt bijna elke winkel zijn eigen categorie
   ("duurzame babykleding van biologisch katoen") en is het hele voordeel weg.
   Liever te breed dan te fijn.

2. In BATCHES van veertig winkels per aanroep. Een aanroep per winkel zou 765
   aanroepen betekenen; zo zijn het er twintig. De hele indeling van je huidige
   lijst kost daarmee ongeveer veertig cent in plaats van tien euro.

3. Twijfelgevallen krijgen "overig" en doen NIET mee aan de index. Een winkel in
   de verkeerde categorie krijgt een positie die niet klopt, en dan ben je in
   een keer al het vertrouwen kwijt dat je met een goede meting opbouwt. Liever
   geen uitspraak dan een verzonnen uitspraak.
"""
import json
import os
import time

import anthropic

import beoordeling
import db
import kosten

# Bewust hetzelfde model als de rest van de tekstverwerking. Door de batches is
# de prijs geen probleem: veertig winkels in een aanroep kost ongeveer twee
# cent, dus de hele lijst van 765 winkels kost minder dan een euro.
MODEL = os.environ.get("CATEGORIE_MODEL", "claude-sonnet-4-6")

# Hoeveel winkels er in een aanroep gaan. Veertig past ruim binnen een
# antwoord van 4096 tekens en houdt de prompt kort genoeg om nauwkeurig te
# blijven. Hoger kan, maar dan gaat het model slordiger indelen.
PER_AANROEP = int(os.environ.get("CATEGORIE_PER_AANROEP", "40"))

# De ondergrens waaronder een categorie niet meedoet aan de openbare index. Een
# ranglijst van vier winkels is geen ranglijst, en zo'n pagina is bij Google
# eerder een blok aan het been dan een klantenstroom.
MINIMUM_VOOR_INDEX = int(os.environ.get("CATEGORIE_MINIMUM", "10"))

# De vaste categorielijst. Afgeleid van de vijftien branches waarin de winkels
# tot nu toe gevonden zijn, uitgesplitst tot het niveau waarop een koopvraag
# zinnig is. "Sport en outdoor" is te breed om er een koopvraag over te stellen,
# "hardlopen" niet.
#
# Een categorie erbij is een regel in deze lijst. Een categorie eraf is NIET
# zomaar een regel weg: winkels die erin zaten moeten dan opnieuw ingedeeld.
CATEGORIEEN = [
    ("kleding-dames", "Dameskleding"),
    ("kleding-heren", "Herenkleding"),
    ("kleding-kinderen", "Kinderkleding"),
    ("kleding-duurzaam", "Duurzame en biologische kleding"),
    ("schoenen", "Schoenen"),
    ("sieraden", "Sieraden"),
    ("horloges", "Horloges"),
    ("tassen-lederwaren", "Tassen en lederwaren"),
    ("wonen-interieur", "Wonen en interieur"),
    ("meubels", "Meubels"),
    ("verlichting", "Verlichting"),
    ("beddengoed-textiel", "Beddengoed en woontextiel"),
    ("woondecoratie", "Woondecoratie en accessoires"),
    ("kunst-posters", "Kunst en posters"),
    ("keuken-servies", "Servies en tafelgerei"),
    ("kookgerei", "Pannen en kookgerei"),
    ("koffie-thee", "Koffie en thee"),
    ("delicatessen", "Delicatessen en speciaalzaken"),
    ("wijn-drank", "Wijn en sterke drank"),
    ("chocolade-snoep", "Chocolade en snoep"),
    ("babyspullen", "Babyspullen en verzorging"),
    ("speelgoed", "Speelgoed"),
    ("speelgoed-educatief", "Educatief en houten speelgoed"),
    ("kraamcadeaus", "Kraamcadeaus en gepersonaliseerde cadeaus"),
    ("sport-fitness", "Sport en fitness"),
    ("hardlopen", "Hardlopen"),
    ("wielrennen", "Wielrennen en fietskleding"),
    ("outdoor-kamperen", "Outdoor en kamperen"),
    ("watersport", "Watersport"),
    ("yoga", "Yoga en pilates"),
    ("elektronica", "Elektronica algemeen"),
    ("audio", "Audio en koptelefoons"),
    ("computers-accessoires", "Computers en accessoires"),
    ("telefoon-accessoires", "Telefoonhoesjes en accessoires"),
    ("gaming", "Gaming"),
    ("slim-huis", "Slimme huis en domotica"),
    ("cosmetica-natuurlijk", "Natuurlijke cosmetica"),
    ("huidverzorging", "Huidverzorging"),
    ("haarverzorging", "Haarverzorging"),
    ("parfum", "Parfum"),
    ("makeup", "Make-up"),
    ("scheren-baard", "Scheren en baardverzorging"),
    ("supplementen", "Supplementen en gezondheid"),
    ("medische-hulpmiddelen", "Medische hulpmiddelen en hulpmiddelen thuis"),
    ("hond", "Hondenbenodigdheden"),
    ("kat", "Kattenbenodigdheden"),
    ("dieren-overig", "Overige dierbenodigdheden"),
    ("kamerplanten", "Kamerplanten"),
    ("tuin", "Tuin en buitenleven"),
    ("zaden-bloembollen", "Zaden en bloembollen"),
    ("hobby-knutselen", "Hobby en knutselen"),
    ("breien-haken", "Breien, haken en stoffen"),
    ("schrijfwaren-kantoor", "Schrijfwaren en kantoor"),
    ("boeken", "Boeken"),
    ("muziekinstrumenten", "Muziekinstrumenten"),
    ("gereedschap", "Gereedschap en klussen"),
    ("auto-accessoires", "Auto-accessoires"),
    ("fietsonderdelen", "Fietsen en onderdelen"),
    ("zerowaste", "Duurzaam en zero waste"),
    ("feestartikelen", "Feestartikelen"),
    ("reizen-bagage", "Reizen en bagage"),
    ("erotiek", "Erotiek"),
    ("overig", "Overig, doet niet mee aan de index"),
]

GELDIG = {slug for slug, _ in CATEGORIEEN}
NAMEN = dict(CATEGORIEEN)


def naam_van(slug):
    """De leesbare naam bij een categorie."""
    return NAMEN.get(slug, slug or "onbekend")


def _client():
    sleutel = os.environ.get("ANTHROPIC_API_KEY")
    if not sleutel:
        return None
    return anthropic.Anthropic(api_key=sleutel)


def _prompt(winkels):
    lijst = "\n".join(f"- {slug}: {naam}" for slug, naam in CATEGORIEEN)
    regels = []
    for w in winkels:
        stukken = [w["webshop_url"]]
        if w.get("naam"):
            stukken.append(w["naam"])
        if w.get("branche"):
            stukken.append(f"branche: {w['branche']}")
        if w.get("omschrijving"):
            stukken.append(w["omschrijving"][:280])
        regels.append(" | ".join(stukken))
    winkeltekst = "\n".join(regels)
    return f"""Hieronder staat een lijst webshops en daarboven een vaste lijst categorieen.
Deel elke webshop in bij precies een categorie uit die lijst.

DE CATEGORIEEN:
{lijst}

REGELS:
- Gebruik UITSLUITEND de slugs uit de lijst hierboven. Verzin er geen bij.
- Weet je het niet zeker, of verkoopt de winkel van alles wat, kies dan "overig".
  Een verkeerde categorie is veel erger dan "overig": de winkel krijgt dan een
  positie in een ranglijst waar hij niet thuishoort.
- Kies de categorie waarin de winkel het GROOTSTE deel van zijn omzet haalt, niet
  een hoekje van het assortiment.
- Een winkel die alleen doorverkoopt van AliExpress en overal een beetje van heeft,
  is "overig".

DE WEBSHOPS:
{winkeltekst}

Antwoord met alleen JSON, zonder uitleg eromheen:
{{"indeling": [{{"webshop_url": "...", "categorie": "slug"}}]}}"""


def deel_in(winkels):
    """Deelt een lijst winkels in. Geeft {webshop_url: slug} terug.

    Winkels waar het model niets zinnigs over zegt komen niet in de uitkomst
    voor. Die blijven dus zonder categorie en worden bij een volgende ronde
    opnieuw geprobeerd, in plaats van dat ze stil op "overig" belanden."""
    client = _client()
    if client is None or not winkels:
        return {}

    rem = kosten.mag_doorgaan()
    if not rem["mag"]:
        print(f"Indelen geblokkeerd door de kostenrem: {rem['reden']}")
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
            soort="winkels-indelen",
            duur_ms=int((time.monotonic() - gestart) * 1000),
        )
        data = beoordeling._schoon_json(antwoord.content[0].text)
    except Exception as e:
        print(f"Indelen mislukt: {e}")
        return {}

    uit = {}
    for regel in (data or {}).get("indeling", []):
        url = (regel.get("webshop_url") or "").strip()
        slug = (regel.get("categorie") or "").strip()
        # Een verzonnen categorie is erger dan geen categorie: hij zou een
        # ranglijst maken die nergens op slaat. Die gooien wij dus weg.
        if url and slug in GELDIG:
            uit[url] = slug
    return uit


def deel_alles_in(hoeveel=None, opnieuw=False):
    """Deelt de winkels in die nog geen categorie hebben.

    Met opnieuw=True worden ook winkels die al ingedeeld zijn opnieuw bekeken.
    Dat is nodig als de categorielijst verandert.

    Geeft een verslag terug met wat er gebeurd is."""
    winkels = db.winkels_zonder_categorie(hoeveel, opnieuw=opnieuw)
    verslag = {"bekeken": len(winkels), "ingedeeld": 0, "overgeslagen": 0, "aanroepen": 0}
    if not winkels:
        return verslag

    for begin in range(0, len(winkels), PER_AANROEP):
        groep = winkels[begin:begin + PER_AANROEP]
        uitkomst = deel_in(groep)
        verslag["aanroepen"] += 1
        for w in groep:
            slug = uitkomst.get(w["webshop_url"])
            if slug:
                db.zet_categorie(w["webshop_url"], slug)
                verslag["ingedeeld"] += 1
            else:
                verslag["overgeslagen"] += 1
        # Bij een lege uitkomst is er iets mis (rem, sleutel, storing). Dan
        # heeft doorgaan geen zin en kost het alleen geld.
        if not uitkomst:
            verslag["gestopt"] = "geen uitkomst van het model, gestopt na deze groep"
            break
    return verslag


def telling():
    """De cijfers waarop de go of no-go rust.

    De vraag is niet hoeveel categorieen er zijn, maar hoeveel WINKELS er in een
    categorie zitten die groot genoeg is om een ranglijst van te maken. Een
    indeling met tachtig categorieen van drie winkels is een mislukking, ook al
    ziet de lijst er netjes uit."""
    rijen = db.categorie_telling()
    totaal = sum(r["aantal"] for r in rijen)
    zonder = next((r["aantal"] for r in rijen if not r["categorie"]), 0)
    overig = next((r["aantal"] for r in rijen if r["categorie"] == "overig"), 0)
    echte = [r for r in rijen if r["categorie"] and r["categorie"] != "overig"]
    bruikbaar = [r for r in echte if r["aantal"] >= MINIMUM_VOOR_INDEX]
    in_bruikbaar = sum(r["aantal"] for r in bruikbaar)
    ingedeeld = sum(r["aantal"] for r in echte)

    return {
        "totaal": totaal,
        "zonder_categorie": zonder,
        "overig": overig,
        "ingedeeld": ingedeeld,
        "categorieen": len(echte),
        "bruikbare_categorieen": len(bruikbaar),
        "winkels_in_bruikbare": in_bruikbaar,
        "aandeel_bruikbaar": round(in_bruikbaar / ingedeeld * 100) if ingedeeld else 0,
        "gemiddeld_per_categorie": round(ingedeeld / len(echte), 1) if echte else 0,
        "minimum": MINIMUM_VOOR_INDEX,
        "rijen": sorted(echte, key=lambda r: -r["aantal"]),
        # Het slagingscriterium, hier en niet op het scherm, zodat er maar een
        # plek is waar het staat.
        "geslaagd": bool(ingedeeld) and (in_bruikbaar / ingedeeld) >= 0.5,
    }


def besparing(telling_uitkomst, per_meting_euro=2.50):
    """Wat de categoriemeting scheelt ten opzichte van meten per winkel.

    Dit is de hele reden van de ombouw, dus het hoort op het scherm te staan in
    plaats van in een document."""
    bruikbaar = telling_uitkomst.get("bruikbare_categorieen") or 0
    winkels = telling_uitkomst.get("winkels_in_bruikbare") or 0
    oud = winkels * per_meting_euro
    nieuw = bruikbaar * per_meting_euro
    return {
        "per_winkel_oud": per_meting_euro,
        "per_winkel_nieuw": round(nieuw / winkels, 4) if winkels else 0,
        "ronde_oud": round(oud, 2),
        "ronde_nieuw": round(nieuw, 2),
        "factor": round(oud / nieuw) if nieuw else 0,
    }
